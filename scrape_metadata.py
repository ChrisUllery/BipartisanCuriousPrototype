import math
import re
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import (
    METADATA_DIR,
    START_CONGRESS,
    END_CONGRESS,
    SESSIONS,
    OVERWRITE_METADATA,
)


BASE_URL = "https://clerk.house.gov"
MEMBER_VOTES_URL = f"{BASE_URL}/Votes/MemberVotes"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://clerk.house.gov/Votes",
    "X-Requested-With": "XMLHttpRequest",
}


def clean_roll_number(value):
    if value is None:
        return ""

    value = str(value).strip()
    value = re.sub(r"[^\d]", "", value)
    return value


def extract_count(vote_block, label):
    label_aliases = {
        "yea": ["yea", "aye"],
        "nay": ["nay", "no"],
        "present": ["present"],
        "not voting": ["not voting"],
    }

    aliases = label_aliases.get(label.lower(), [label.lower()])

    for count_tag in vote_block.select("p[aria-label]"):
        aria_label = count_tag.get("aria-label", "").lower()

        for alias in aliases:
            if alias in aria_label:
                digits = "".join(filter(str.isdigit, aria_label))
                return int(digits) if digits else None

    return None


def get_labeled_description(vote_block, label_text):
    for desc_tag in vote_block.select("p.roll-call-description"):
        label = desc_tag.find("label")

        if label and label_text.lower() in label.get_text(strip=True).lower():
            label.extract()
            return desc_tag.get_text(" ", strip=True)

    return ""


def parse_total_results(soup):
    """
    Parse text like:
    1 - 10 of 175 Results
    """
    info = soup.select_one(".pagination_info")

    if not info:
        return None

    text = info.get_text(" ", strip=True)
    match = re.search(r"of\s+([\d,]+)\s+Results", text, re.IGNORECASE)

    if not match:
        return None

    return int(match.group(1).replace(",", ""))


def parse_vote_block(vote_block, congress_num, session):
    row_comment = vote_block.select_one(".row-comment")
    date = ""
    congress_session_label = ""

    if row_comment:
        parts = row_comment.get_text(" ", strip=True).split("|")

        if len(parts) == 2:
            date = parts[0].strip()
            congress_session_label = parts[1].strip()

    heading_links = vote_block.select(".heading a")

    roll_anchor = next(
        (a for a in heading_links if "Roll number" in a.get("aria-label", "")),
        None,
    )

    bill_anchor = next(
        (a for a in heading_links if "bill number" in a.get("aria-label", "")),
        None,
    )

    roll_number = clean_roll_number(roll_anchor.get_text(strip=True)) if roll_anchor else ""
    roll_url = f"{BASE_URL}{roll_anchor['href']}" if roll_anchor and roll_anchor.get("href") else ""

    bill_number = bill_anchor.get_text(strip=True) if bill_anchor else ""
    bill_url = bill_anchor.get("href", "") if bill_anchor else ""

    bill_title = ""
    bill_description = ""

    bill_desc_tag = vote_block.select_one("span.billdesc")

    if bill_desc_tag:
        bill_description = bill_desc_tag.get_text(" ", strip=True)
        title_container = bill_desc_tag.find_parent("p")

        if title_container:
            title_label = title_container.find("span", class_="billtitle")

            if title_label:
                bill_title = title_label.get_text(" ", strip=True)
    else:
        for inner_tag in vote_block.select("p.roll-call-description"):
            if not inner_tag.find("label") and inner_tag.get_text(strip=True):
                bill_description = inner_tag.get_text(" ", strip=True)
                break

    detail_link = vote_block.select_one("a.btn-library")
    details_url = f"{BASE_URL}{detail_link['href']}" if detail_link and detail_link.get("href") else ""

    return {
        "congress": congress_num,
        "session": session,
        "date": date,
        "congress_session": congress_session_label,
        "roll_number": roll_number,
        "roll_url": roll_url,
        "bill_number": bill_number,
        "bill_url": bill_url,
        "bill_title": bill_title,
        "bill_description": bill_description,
        "vote_question": get_labeled_description(vote_block, "Vote Question"),
        "vote_type": get_labeled_description(vote_block, "Vote Type"),
        "status": get_labeled_description(vote_block, "Status"),
        "yea": extract_count(vote_block, "yea"),
        "nay": extract_count(vote_block, "nay"),
        "present": extract_count(vote_block, "present"),
        "not_voting": extract_count(vote_block, "not voting"),
        "details_url": details_url,
    }


def fetch_vote_page(congress_num, session, page_num):
    params = {
        "Page": page_num,
        "CongressNum": congress_num,
        "Session": session,
    }

    response = requests.get(
        MEMBER_VOTES_URL,
        params=params,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()
    return response.text


def scrape_congress_session(congress_num, session):
    print(f"\n➡️ {congress_num}th Congress, {session} Session")

    first_html = fetch_vote_page(congress_num, session, 1)
    soup = BeautifulSoup(first_html, "html.parser")

    total_results = parse_total_results(soup)

    if not total_results:
        print("⚠️ No results found.")
        return []

    total_pages = math.ceil(total_results / 10)

    print(f"📊 Found {total_results:,} votes across {total_pages:,} pages")

    rows = []

    for page_num in range(1, total_pages + 1):
        if page_num == 1:
            page_soup = soup
        else:
            html = fetch_vote_page(congress_num, session, page_num)
            page_soup = BeautifulSoup(html, "html.parser")

        vote_blocks = page_soup.select("div.role-call-vote")

        print(f"📄 Page {page_num}: found {len(vote_blocks)} vote blocks")

        for vote_block in vote_blocks:
            try:
                row = parse_vote_block(vote_block, congress_num, session)
                rows.append(row)
            except Exception as e:
                print(f"❌ Error parsing vote block on page {page_num}: {e}")

    print(f"✅ Finished {congress_num} {session}: {len(rows):,} votes scraped")

    return rows


def main():
    existing_files = sorted(METADATA_DIR.glob("HouseVoteMetadata_*.csv"))

    if existing_files and not OVERWRITE_METADATA:
        print("⚠️ Existing metadata files found.")
        print("This run will create a new timestamped file.")
        print("No old files will be deleted.")

    all_rows = []

    for congress_num in range(START_CONGRESS, END_CONGRESS + 1):
        for session in SESSIONS:
            try:
                rows = scrape_congress_session(congress_num, session)
                all_rows.extend(rows)
            except Exception as e:
                print(f"❌ Error scraping {congress_num} {session}: {e}")

    if not all_rows:
        print("\n❌ No metadata scraped.")
        return

    df = pd.DataFrame(all_rows)

    df = df.drop_duplicates(
        subset=["congress", "session", "roll_number"]
    )

    df = df.sort_values(
        ["congress", "session", "roll_number"],
        ascending=[True, True, True],
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    metadata_path = METADATA_DIR / f"HouseVoteMetadata_{timestamp}.csv"

    df.to_csv(metadata_path, index=False)

    print("\n✅ Metadata saved")
    print(f"📁 {metadata_path}")
    print(f"📊 Rows: {len(df):,}")


if __name__ == "__main__":
    main()