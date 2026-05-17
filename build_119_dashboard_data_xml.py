import re
from pathlib import Path

import pandas as pd


XML_VOTES_DIR = Path("data/raw/member_votes_xml")
PROFILE_PATH = Path("data/raw/member_profiles/member_profiles_119.csv")

VOTE_SUMMARIES_DIR = Path("data/processed/vote_summaries")
DASHBOARD_DATA_DIR = Path("data/dashboard")

VOTE_SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
DASHBOARD_DATA_DIR.mkdir(parents=True, exist_ok=True)

SUMMARY_OUTPUT = VOTE_SUMMARIES_DIR / "VoteSummaries_119_xml.csv"
ALIGNMENT_OUTPUT = DASHBOARD_DATA_DIR / "member_alignment_119_xml.csv"
ENRICHED_OUTPUT = DASHBOARD_DATA_DIR / "member_alignment_119_xml_enriched.csv"


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


def parse_file_key(path):
    match = re.search(
        r"MemberVotesXML_(?P<congress>\d+)_(?P<session>[^_]+)_roll_(?P<roll>\d+)\.csv$",
        path.name,
    )

    if not match:
        return None

    return {
        "congress": match.group("congress"),
        "session": match.group("session"),
        "roll_number": match.group("roll"),
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

    if rep_position == dem_position:
        return "Neutral"

    if member_vote == rep_position:
        return "Republican Majority"

    if member_vote == dem_position:
        return "Democratic Majority"

    return "Neither"


def load_xml_votes():
    files = sorted(XML_VOTES_DIR.glob("MemberVotesXML_119_*_roll_*.csv"))

    if not files:
        raise FileNotFoundError(f"No XML member vote files found in {XML_VOTES_DIR}")

    print(f"Found XML member vote files: {len(files):,}")

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
        raise ValueError("No usable XML vote rows loaded.")

    votes = pd.concat(frames, ignore_index=True)

    print(f"Total XML vote rows loaded: {len(votes):,}")

    return votes


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

    # Ignore neutral/bipartisan roll calls where both parties' majorities voted the same way.
    merged = merged[
        merged["rep_position"].isin(["yea", "nay"])
        & merged["dem_position"].isin(["yea", "nay"])
        & (merged["rep_position"] != merged["dem_position"])
    ].copy()

    print(f"Vote rows on party-split roll calls: {len(merged):,}")

    if merged.empty:
        raise ValueError("No party-split roll calls found.")

    merged["alignment"] = merged.apply(
        lambda r: classify_alignment(r["vote_clean"], r["rep_position"], r["dem_position"]),
        axis=1,
    )

    grouped = (
        merged.groupby(
            ["bioguide_id", "representative", "party", "party_code", "state_abbr"],
            dropna=False,
        )["alignment"]
        .value_counts()
        .unstack(fill_value=0)
        .reset_index()
    )

    required_cols = [
        "Republican Majority",
        "Democratic Majority",
        "Not Voting",
        "Present",
        "Neither",
    ]

    for col in required_cols:
        if col not in grouped.columns:
            grouped[col] = 0

    grouped["party_split_roll_calls"] = grouped[required_cols].sum(axis=1)

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


def enrich_with_profiles(alignment):
    profiles = pd.read_csv(PROFILE_PATH)

    profiles = profiles.rename(columns={"party": "profile_party"})

    profile_cols = [
        "bioguide_id",
        "full_name",
        "first_name",
        "last_name",
        "profile_party",
        "district",
        "district_code",
        "district_key",
        "official_url",
        "office",
        "address",
        "phone",
        "term_start",
        "term_end",
    ]

    profiles = profiles[[c for c in profile_cols if c in profiles.columns]].copy()

    enriched = alignment.merge(
        profiles,
        on="bioguide_id",
        how="left",
    )

    front_cols = [
        "bioguide_id",
        "representative",
        "full_name",
        "party",
        "party_code",
        "state_abbr",
        "district",
        "district_code",
        "district_key",
        "official_url",
    ]

    existing_front_cols = [c for c in front_cols if c in enriched.columns]
    remaining_cols = [c for c in enriched.columns if c not in existing_front_cols]

    enriched = enriched[existing_front_cols + remaining_cols]

    return enriched


def main():
    votes = load_xml_votes()

    summaries = build_vote_summaries(votes)
    alignment = build_member_alignment(votes, summaries)
    enriched = enrich_with_profiles(alignment)

    summaries.to_csv(SUMMARY_OUTPUT, index=False)
    alignment.to_csv(ALIGNMENT_OUTPUT, index=False)
    enriched.to_csv(ENRICHED_OUTPUT, index=False)

    print(f"Wrote XML vote summaries: {SUMMARY_OUTPUT}")
    print(f"Wrote XML member alignment: {ALIGNMENT_OUTPUT}")
    print(f"Wrote XML enriched alignment: {ENRICHED_OUTPUT}")
    print()
    print(f"Alignment rows: {len(alignment):,}")
    print(f"Enriched rows: {len(enriched):,}")
    print(f"Rows with district_key: {enriched['district_key'].notna().sum():,}")
    print(f"Rows missing district_key: {enriched['district_key'].isna().sum():,}")
    print()
    print("Sample:")
    print(
        enriched[
            [
                "bioguide_id",
                "representative",
                "full_name",
                "party",
                "state_abbr",
                "district_key",
                "with_democratic_pct",
                "with_republican_pct",
            ]
        ]
        .head(25)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
