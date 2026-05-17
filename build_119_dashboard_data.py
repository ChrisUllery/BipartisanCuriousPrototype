import re
from pathlib import Path

import pandas as pd

from config import MEMBER_VOTES_DIR, VOTE_SUMMARIES_DIR, DASHBOARD_DATA_DIR, DOCS_DIR


CURRENT_CONGRESS = "119"

VOTE_MAP = {
    "yea": "yea",
    "aye": "yea",
    "nay": "nay",
    "no": "nay",
    "present": "present",
    "not voting": "not_voting",
}

PARTY_MAP = {
    "Democratic": "democratic",
    "Republican": "republican",
    "Independent": "independent",
}


def clean_vote(value):
    return VOTE_MAP.get(str(value).strip().lower(), "unknown")


def clean_party(value):
    return PARTY_MAP.get(str(value).strip(), "other")


def get_party_position(row, party_prefix):
    yea = int(row.get(f"{party_prefix}_yea", 0))
    nay = int(row.get(f"{party_prefix}_nay", 0))

    if yea > nay:
        return "yea"
    if nay > yea:
        return "nay"
    return "mixed"


def classify_alignment(member_vote, rep_position, dem_position):
    if member_vote == "not_voting":
        return "Not Voting"

    if member_vote == "present":
        return "Present"

    if rep_position == "mixed" or dem_position == "mixed":
        return "Neither"

    if rep_position == dem_position and member_vote == rep_position:
        return "Bipartisan Majority"

    if member_vote == rep_position:
        return "Republican Majority"

    if member_vote == dem_position:
        return "Democratic Majority"

    return "Neither"


def parse_file_key(path):
    match = re.search(
        r"MemberVotes_(?P<congress>\d+)_(?P<session>[^_]+)_roll_(?P<roll>\d+)\.csv$",
        path.name,
    )

    if not match:
        return None

    return {
        "congress": match.group("congress"),
        "session": match.group("session"),
        "roll_number": match.group("roll"),
    }


def load_current_congress_votes():
    files = sorted(MEMBER_VOTES_DIR.glob(f"MemberVotes_{CURRENT_CONGRESS}_*_roll_*.csv"))

    if not files:
        raise FileNotFoundError(
            f"No MemberVotes files found for Congress {CURRENT_CONGRESS} in {MEMBER_VOTES_DIR}"
        )

    print(f"Found {len(files):,} member-vote files for Congress {CURRENT_CONGRESS}")

    frames = []

    for path in files:
        key = parse_file_key(path)

        if key is None:
            print(f"Skipping unexpected filename: {path.name}")
            continue

        df = pd.read_csv(path)

        df["congress"] = str(key["congress"])
        df["session"] = str(key["session"])
        df["roll_number"] = str(key["roll_number"])

        df["party_clean"] = df["party"].map(clean_party)
        df["vote_clean"] = df["vote"].map(clean_vote)

        df = df[df["vote_clean"] != "unknown"].copy()

        frames.append(df)

    if not frames:
        raise ValueError("No usable member vote rows loaded.")

    return pd.concat(frames, ignore_index=True)


def build_vote_summaries(votes):
    summary_rows = []

    vote_options = ["yea", "nay", "present", "not_voting"]
    party_options = ["democratic", "republican", "independent", "other"]

    grouped = votes.groupby(["congress", "session", "roll_number"])

    for (congress, session, roll_number), group in grouped:
        row = {
            "congress": str(congress),
            "session": str(session),
            "roll_number": str(roll_number),
        }

        for party in party_options:
            for vote in vote_options:
                row[f"{party}_{vote}"] = 0

        counts = (
            group.groupby(["party_clean", "vote_clean"])
            .size()
            .reset_index(name="count")
        )

        for _, count_row in counts.iterrows():
            party = str(count_row["party_clean"])
            vote = str(count_row["vote_clean"])
            key = f"{party}_{vote}"

            if key in row:
                row[key] = int(count_row["count"])

        row["rep_position"] = get_party_position(row, "republican")
        row["dem_position"] = get_party_position(row, "democratic")

        summary_rows.append(row)

    if not summary_rows:
        raise ValueError("No vote summaries could be built.")

    summary_df = pd.DataFrame(summary_rows)

    summary_df["roll_number_int"] = pd.to_numeric(
        summary_df["roll_number"],
        errors="coerce",
    )

    summary_df = (
        summary_df.sort_values(["session", "roll_number_int"])
        .drop(columns=["roll_number_int"])
        .reset_index(drop=True)
    )

    return summary_df


def build_member_alignment(votes, summaries):
    merged = votes.merge(
        summaries[["congress", "session", "roll_number", "rep_position", "dem_position"]],
        on=["congress", "session", "roll_number"],
        how="left",
    )

    # Keep only party-split roll calls.
    # If both parties' majorities voted the same way, the vote is neutral for this dashboard.
    merged = merged[
        merged["rep_position"].isin(["yea", "nay"])
        & merged["dem_position"].isin(["yea", "nay"])
        & (merged["rep_position"] != merged["dem_position"])
    ].copy()

    if merged.empty:
        raise ValueError("No party-split roll calls found after filtering out bipartisan votes.")

    merged["alignment"] = merged.apply(
        lambda r: classify_alignment(r["vote_clean"], r["rep_position"], r["dem_position"]),
        axis=1,
    )

    grouped = (
        merged.groupby(["representative", "party", "state", "state_abbr"])["alignment"]
        .value_counts()
        .unstack(fill_value=0)
        .reset_index()
    )

    required_alignment_cols = [
        "Republican Majority",
        "Democratic Majority",
        "Not Voting",
        "Present",
        "Neither",
    ]

    for col in required_alignment_cols:
        if col not in grouped.columns:
            grouped[col] = 0

    grouped["party_split_roll_calls"] = grouped[required_alignment_cols].sum(axis=1)

    grouped["votes_cast_on_party_split_roll_calls"] = (
        grouped["Republican Majority"]
        + grouped["Democratic Majority"]
        + grouped["Neither"]
    )

    grouped["with_republican_pct"] = (
        grouped["Republican Majority"]
        / grouped["votes_cast_on_party_split_roll_calls"]
        * 100
    ).round(1)

    grouped["with_democratic_pct"] = (
        grouped["Democratic Majority"]
        / grouped["votes_cast_on_party_split_roll_calls"]
        * 100
    ).round(1)

    grouped["missed_party_split_votes_pct"] = (
        grouped["Not Voting"]
        / grouped["party_split_roll_calls"]
        * 100
    ).round(1)

    grouped = grouped.fillna(
        {
            "with_republican_pct": 0,
            "with_democratic_pct": 0,
            "missed_party_split_votes_pct": 0,
        }
    )

    grouped = grouped.sort_values(
        ["party", "state_abbr", "representative"],
        ascending=[True, True, True],
    )

    return grouped


def write_basic_dashboard(member_alignment, summaries):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    total_roll_calls = summaries[["session", "roll_number"]].drop_duplicates().shape[0]
    total_members = member_alignment.shape[0]

    display = member_alignment.copy()

    keep_cols = [
        "representative",
        "party",
        "state_abbr",
        "party_split_roll_calls",
        "votes_cast_on_party_split_roll_calls",
        "with_republican_pct",
        "with_democratic_pct",
        "missed_party_split_votes_pct",
        "Republican Majority",
        "Democratic Majority",
        "Not Voting",
        "Present",
        "Neither",
    ]

    display = display[keep_cols]

    table_html = display.to_html(index=False, classes="member-table", border=0)

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>BipartisanCurious - 119th Congress Prototype</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 24px;
      background: #f7f7f7;
      color: #111;
    }}
    h1 {{
      margin-bottom: 4px;
    }}
    .subtitle {{
      color: #555;
      margin-bottom: 24px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .card {{
      background: white;
      padding: 18px;
      border-radius: 12px;
      box-shadow: 0 1px 5px rgba(0,0,0,0.08);
    }}
    .card .number {{
      font-size: 32px;
      font-weight: bold;
      margin-bottom: 4px;
    }}
    .card .label {{
      color: #555;
    }}
    .table-wrap {{
      overflow-x: auto;
      background: white;
      border-radius: 12px;
      padding: 12px;
      box-shadow: 0 1px 5px rgba(0,0,0,0.08);
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 14px;
    }}
    th, td {{
      padding: 8px 10px;
      border-bottom: 1px solid #ddd;
      text-align: left;
      white-space: nowrap;
    }}
    th {{
      background: #f0f0f0;
      position: sticky;
      top: 0;
    }}
  </style>
</head>
<body>
  <h1>BipartisanCurious</h1>
  <div class="subtitle">119th Congress prototype dashboard</div>

  <div class="cards">
    <div class="card">
      <div class="number">{total_roll_calls:,}</div>
      <div class="label">Total 119th roll calls scraped</div>
    </div>
    <div class="card">
      <div class="number">{total_members:,}</div>
      <div class="label">Members / delegates found</div>
    </div>
  </div>

  <div class="table-wrap">
    {table_html}
  </div>
</body>
</html>
"""

    output_path = DOCS_DIR / "index.html"
    output_path.write_text(html, encoding="utf-8")

    print(f"Wrote dashboard: {output_path}")


def main():
    VOTE_SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    DASHBOARD_DATA_DIR.mkdir(parents=True, exist_ok=True)

    votes = load_current_congress_votes()

    summaries = build_vote_summaries(votes)
    member_alignment = build_member_alignment(votes, summaries)

    summary_path = VOTE_SUMMARIES_DIR / "VoteSummaries_119.csv"
    alignment_path = DASHBOARD_DATA_DIR / "member_alignment_119.csv"

    summaries.to_csv(summary_path, index=False)
    member_alignment.to_csv(alignment_path, index=False)

    print(f"Wrote vote summaries: {summary_path}")
    print(f"Wrote member alignment: {alignment_path}")

    write_basic_dashboard(member_alignment, summaries)

    print("Done.")


if __name__ == "__main__":
    main()
