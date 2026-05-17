import re
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from config import METADATA_DIR, MEMBER_VOTES_DIR, OVERWRITE_MEMBER_VOTES


HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://clerk.house.gov/Votes",
}

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

ERROR_LOG_PATH = LOG_DIR / "member_vote_scrape_errors.csv"
RUN_LOG_PATH = LOG_DIR / "member_vote_scrape_run_log.csv"

CURRENT_CONGRESS_ONLY = "119"


def get_latest_metadata_file():
    metadata_files = sorted(METADATA_DIR.glob("HouseVoteMetadata_*.csv"))

    if not metadata_files:
        raise FileNotFoundError(
            f"No metadata files found in {METADATA_DIR}. "
            "Run scrape_metadata.py first."
        )

    return metadata_files[-1]


def clean_filename_part(value):
    value = str(value).strip()
    value = re.sub(r"[^\w\-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def build_member_votes_path(row):
    congress = clean_filename_part(row["congress"])
    session = clean_filename_part(row["session"])
    roll_number = clean_filename_part(row["roll_number"])

    filename = f"MemberVotes_{congress}_{session}_roll_{roll_number}.csv"
    return MEMBER_VOTES_DIR / filename


def fetch_detail_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def parse_member_votes(html, metadata_row):
    soup = BeautifulSoup(html, "html.parser")

    table_body = soup.select_one("tbody#member-votes")

    if table_body is None:
        raise ValueError("Could not find tbody#member-votes on detail page.")

    rows = []

    for tr in table_body.select("tr"):
        if tr.find("td", id="nomatch"):
            continue

        member_cell = tr.find("td", {"data-label": "member"})
        party_cell = tr.find("td", {"data-label": "party"})
        vote_cell = tr.find("td", {"data-label": "vote"})

        # Prefer the visible mobile/xs state cell because it contains the full state name.
        state_cell = tr.find(
            "td",
            {
                "data-label": "state",
                "class": lambda c: c and "visible-sm" in c and "visible-xs" in c,
            },
        )

        # Fallback to any state-labeled cell.
        if state_cell is None:
            state_cell = tr.find("td", {"data-label": "state"})

        if not member_cell or not party_cell or not vote_cell:
            continue

        member_link = member_cell.find("a")
        representative = (
            member_link.get_text(" ", strip=True)
            if member_link
            else member_cell.get_text(" ", strip=True)
        )

        party = party_cell.get_text(" ", strip=True)
        state = state_cell.get_text(" ", strip=True) if state_cell else ""
        vote = vote_cell.get_text(" ", strip=True)

        # Try to grab state abbreviation from the hidden desktop state cell.
        state_abbr = ""

        state_cells = tr.find_all("td", {"data-label": "state"})
        for cell in state_cells:
            text = cell.get_text(" ", strip=True)
            if len(text) == 2 and text.isalpha():
                state_abbr = text.upper()
                break

        rows.append(
            {
                "congress": metadata_row["congress"],
                "session": metadata_row["session"],
                "roll_number": metadata_row["roll_number"],
                "date": metadata_row.get("date", ""),
                "bill_number": metadata_row.get("bill_number", ""),
                "vote_question": metadata_row.get("vote_question", ""),
                "vote_type": metadata_row.get("vote_type", ""),
                "status": metadata_row.get("status", ""),
                "details_url": metadata_row.get("details_url", ""),
                "representative": representative,
                "party": party,
                "state": state,
                "state_abbr": state_abbr,
                "vote": vote,
            }
        )

    return pd.DataFrame(rows)


def append_log_row(path, row):
    log_df = pd.DataFrame([row])
    write_header = not path.exists()
    log_df.to_csv(path, mode="a", header=write_header, index=False)


def scrape_one_vote(row):
    output_path = build_member_votes_path(row)

    if output_path.exists() and not OVERWRITE_MEMBER_VOTES:
        print(f"?? Skipping existing: {output_path.name}")
        return output_path, "skipped"

    details_url = str(row.get("details_url", "")).strip()

    if not details_url:
        print(
            f"?? Missing details_url for "
            f"{row['congress']} {row['session']} roll {row['roll_number']}"
        )
        return output_path, "missing_url"

    html = fetch_detail_page(details_url)
    member_votes = parse_member_votes(html, row)

    if member_votes.empty:
        print(
            f"?? No member votes parsed for "
            f"{row['congress']} {row['session']} roll {row['roll_number']}"
        )
        return output_path, "empty"

    member_votes.to_csv(output_path, index=False)

    print(
        f"? Saved {len(member_votes):,} rows: "
        f"{output_path.name}"
    )

    return output_path, "saved"


def main():
    metadata_path = get_latest_metadata_file()
    print(f"Using metadata file: {metadata_path}")

    metadata = pd.read_csv(metadata_path)

    required_columns = ["congress", "session", "roll_number", "details_url"]

    missing_columns = [
        column for column in required_columns
        if column not in metadata.columns
    ]

    if missing_columns:
        raise ValueError(f"Metadata file is missing columns: {missing_columns}")

    metadata = metadata[
        metadata["details_url"].notna()
        & (metadata["details_url"].astype(str).str.strip() != "")
    ].copy()

    if CURRENT_CONGRESS_ONLY:
        metadata = metadata[
            metadata["congress"].astype(str).str.strip() == str(CURRENT_CONGRESS_ONLY)
        ].copy()
        print(f"Filtered to Congress {CURRENT_CONGRESS_ONLY}: {len(metadata):,} rows")

    metadata["output_path"] = metadata.apply(build_member_votes_path, axis=1)

    if not OVERWRITE_MEMBER_VOTES:
        before_existing_filter = len(metadata)
        metadata = metadata[
            ~metadata["output_path"].apply(lambda p: Path(p).exists())
        ].copy()
        skipped_existing = before_existing_filter - len(metadata)
        print(f"Already-existing files removed before loop: {skipped_existing:,}")

    metadata = metadata.sort_values(
        ["congress", "session", "roll_number"],
        ascending=[True, True, True],
    )

    print(f"Votes to check: {len(metadata):,}")

    status_counts = {
        "saved": 0,
        "skipped": 0,
        "missing_url": 0,
        "empty": 0,
        "error": 0,
    }

    for index, row in tqdm(
        metadata.iterrows(),
        total=len(metadata),
        desc="Scraping member votes",
        unit="vote",
    ):
        label = (
            f"{row['congress']} {row['session']} "
            f"roll {row['roll_number']}"
        )

        print(f"\n?? {label}")

        try:
            output_path, status = scrape_one_vote(row)
            status_counts[status] = status_counts.get(status, 0) + 1

            append_log_row(
                RUN_LOG_PATH,
                {
                    "congress": row["congress"],
                    "session": row["session"],
                    "roll_number": row["roll_number"],
                    "details_url": row["details_url"],
                    "output_path": output_path,
                    "status": status,
                    "error": "",
                },
            )

        except Exception as e:
            status_counts["error"] += 1
            print(f"? Error scraping {label}: {e}")

            append_log_row(
                ERROR_LOG_PATH,
                {
                    "congress": row["congress"],
                    "session": row["session"],
                    "roll_number": row["roll_number"],
                    "details_url": row.get("details_url", ""),
                    "output_path": "",
                    "status": "error",
                    "error": str(e),
                },
            )

        time.sleep(0.25)

    print("\nDone.")
    print(status_counts)


if __name__ == "__main__":
    main()
