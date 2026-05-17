import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

from config import METADATA_DIR


CURRENT_CONGRESS_ONLY = "119"

OUTPUT_DIR = Path("data/raw/member_votes_xml")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

RUN_LOG_PATH = LOG_DIR / "member_vote_xml_scrape_run_log.csv"
ERROR_LOG_PATH = LOG_DIR / "member_vote_xml_scrape_errors.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://clerk.house.gov/Votes",
}

PARTY_MAP = {
    "D": "Democratic",
    "R": "Republican",
    "I": "Independent",
    "ID": "Independent",
}


def get_latest_metadata_file():
    metadata_files = sorted(METADATA_DIR.glob("HouseVoteMetadata_*.csv"))

    if not metadata_files:
        raise FileNotFoundError(
            f"No metadata files found in {METADATA_DIR}. "
            "Run scrape_metadata.py first."
        )

    return metadata_files[-1]


def clean_roll_number(value):
    value = str(value).strip()
    value = re.sub(r"[^\d]", "", value)

    if not value:
        return ""

    return str(int(value))


def roll_to_xml_url(row):
    session = str(row["session"]).strip()
    roll_number = clean_roll_number(row["roll_number"])

    if session == "1st":
        year = "2025"
    elif session == "2nd":
        year = "2026"
    else:
        raise ValueError(f"Unknown session: {session}")

    return f"https://clerk.house.gov/evs/{year}/roll{roll_number.zfill(3)}.xml"


def build_output_path(row):
    congress = str(row["congress"]).strip()
    session = str(row["session"]).strip()
    roll_number = clean_roll_number(row["roll_number"])

    return OUTPUT_DIR / f"MemberVotesXML_{congress}_{session}_roll_{roll_number}.csv"


def append_log_row(path, row):
    log_df = pd.DataFrame([row])
    write_header = not path.exists()
    log_df.to_csv(path, mode="a", header=write_header, index=False)


def fetch_xml(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.content


def text_or_blank(parent, tag):
    found = parent.find(tag)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def parse_xml_vote(xml_content, metadata_row, xml_url):
    root = ET.fromstring(xml_content)

    vote_data = root.find("vote-data")

    if vote_data is None:
        raise ValueError("XML has no vote-data element.")

    roll_number = clean_roll_number(metadata_row["roll_number"])

    rows = []

    for recorded_vote in vote_data.findall("recorded-vote"):
        legislator = recorded_vote.find("legislator")
        vote = text_or_blank(recorded_vote, "vote")

        if legislator is None:
            continue

        attrs = legislator.attrib

        party_code = attrs.get("party", "").strip()
        party = PARTY_MAP.get(party_code, party_code)

        rows.append(
            {
                "congress": metadata_row["congress"],
                "session": metadata_row["session"],
                "roll_number": roll_number,
                "date": metadata_row.get("date", ""),
                "bill_number": metadata_row.get("bill_number", ""),
                "vote_question": metadata_row.get("vote_question", ""),
                "vote_type": metadata_row.get("vote_type", ""),
                "status": metadata_row.get("status", ""),
                "details_url": metadata_row.get("details_url", ""),
                "xml_url": xml_url,
                "bioguide_id": attrs.get("name-id", "").strip(),
                "representative": legislator.text.strip() if legislator.text else "",
                "sort_field": attrs.get("sort-field", "").strip(),
                "unaccented_name": attrs.get("unaccented-name", "").strip(),
                "party_code": party_code,
                "party": party,
                "state_abbr": attrs.get("state", "").strip(),
                "role": attrs.get("role", "").strip(),
                "vote": vote,
            }
        )

    return pd.DataFrame(rows)


def scrape_one_xml_vote(row):
    output_path = build_output_path(row)

    if output_path.exists():
        return output_path, "skipped_existing", ""

    xml_url = roll_to_xml_url(row)

    xml_content = fetch_xml(xml_url)
    df = parse_xml_vote(xml_content, row, xml_url)

    if df.empty:
        return output_path, "empty", xml_url

    df.to_csv(output_path, index=False)

    return output_path, "saved", xml_url


def main():
    metadata_path = get_latest_metadata_file()
    print(f"Using metadata file: {metadata_path}")

    metadata = pd.read_csv(metadata_path)

    metadata = metadata[
        metadata["details_url"].notna()
        & (metadata["details_url"].astype(str).str.strip() != "")
    ].copy()

    metadata = metadata[
        metadata["congress"].astype(str).str.strip() == CURRENT_CONGRESS_ONLY
    ].copy()

    metadata = metadata.sort_values(
        ["congress", "session", "roll_number"],
        ascending=[True, True, True],
    )

    metadata["output_path"] = metadata.apply(build_output_path, axis=1)

    before = len(metadata)
    metadata = metadata[
        ~metadata["output_path"].apply(lambda p: Path(p).exists())
    ].copy()

    skipped_existing = before - len(metadata)

    print(f"Congress {CURRENT_CONGRESS_ONLY} metadata rows: {before:,}")
    print(f"Already-existing XML CSVs skipped before loop: {skipped_existing:,}")
    print(f"XML votes to scrape: {len(metadata):,}")

    status_counts = {
        "saved": 0,
        "skipped_existing": skipped_existing,
        "empty": 0,
        "error": 0,
    }

    for _, row in tqdm(
        metadata.iterrows(),
        total=len(metadata),
        desc="Scraping XML member votes",
        unit="vote",
    ):
        label = f"{row['congress']} {row['session']} roll {row['roll_number']}"

        try:
            output_path, status, xml_url = scrape_one_xml_vote(row)
            status_counts[status] = status_counts.get(status, 0) + 1

            append_log_row(
                RUN_LOG_PATH,
                {
                    "congress": row["congress"],
                    "session": row["session"],
                    "roll_number": row["roll_number"],
                    "xml_url": xml_url,
                    "output_path": output_path,
                    "status": status,
                    "error": "",
                },
            )

        except Exception as e:
            status_counts["error"] += 1

            xml_url = ""
            try:
                xml_url = roll_to_xml_url(row)
            except Exception:
                pass

            print(f"\nError scraping {label}: {e}")

            append_log_row(
                ERROR_LOG_PATH,
                {
                    "congress": row["congress"],
                    "session": row["session"],
                    "roll_number": row["roll_number"],
                    "xml_url": xml_url,
                    "output_path": "",
                    "status": "error",
                    "error": str(e),
                },
            )

        time.sleep(0.1)

    print("\nDone.")
    print(status_counts)


if __name__ == "__main__":
    main()
