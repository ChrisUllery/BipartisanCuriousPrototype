from pathlib import Path
from datetime import date

import pandas as pd
import requests
import yaml


RAW_PROFILE_DIR = Path("data") / "raw" / "member_profiles"
RAW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

CURRENT_LEGISLATORS_URL = (
    "https://raw.githubusercontent.com/unitedstates/"
    "congress-legislators/main/legislators-current.yaml"
)

OUTPUT_CSV = RAW_PROFILE_DIR / "member_profiles_119.csv"

TODAY = date.today()


def normalize_party(value):
    value = str(value).strip()

    if value == "Democrat":
        return "Democratic"

    return value


def district_to_code(district):
    if district is None:
        return ""

    try:
        district_int = int(district)
    except Exception:
        return str(district).strip()

    if district_int == 0:
        return "00"

    return f"{district_int:02d}"


def build_full_name(name_data):
    official_full = name_data.get("official_full")
    if official_full:
        return official_full

    parts = [
        name_data.get("first", ""),
        name_data.get("middle", ""),
        name_data.get("last", ""),
        name_data.get("suffix", ""),
    ]

    return " ".join(str(part).strip() for part in parts if str(part).strip())


def get_current_house_term(terms):
    current_terms = []

    for term in terms:
        if term.get("type") != "rep":
            continue

        start = pd.to_datetime(term.get("start"), errors="coerce").date()
        end = pd.to_datetime(term.get("end"), errors="coerce").date()

        if start <= TODAY <= end:
            current_terms.append(term)

    if not current_terms:
        return None

    return sorted(current_terms, key=lambda t: t.get("start", ""))[-1]


def main():
    print("Downloading current legislators YAML...")
    response = requests.get(CURRENT_LEGISLATORS_URL, timeout=60)
    response.raise_for_status()

    legislators = yaml.safe_load(response.text)

    rows = []

    for person in legislators:
        term = get_current_house_term(person.get("terms", []))

        if term is None:
            continue

        name_data = person.get("name", {})
        id_data = person.get("id", {})

        state_abbr = str(term.get("state", "")).strip()
        district_code = district_to_code(term.get("district"))
        district_key = f"{state_abbr}-{district_code}" if state_abbr and district_code else ""

        rows.append(
            {
                "bioguide_id": id_data.get("bioguide", ""),
                "govtrack_id": id_data.get("govtrack", ""),
                "icpsr_id": id_data.get("icpsr", ""),
                "wikidata_id": id_data.get("wikidata", ""),
                "full_name": build_full_name(name_data),
                "first_name": name_data.get("first", ""),
                "middle_name": name_data.get("middle", ""),
                "last_name": name_data.get("last", ""),
                "suffix": name_data.get("suffix", ""),
                "nickname": name_data.get("nickname", ""),
                "party": normalize_party(term.get("party", "")),
                "state_abbr": state_abbr,
                "district": term.get("district", ""),
                "district_code": district_code,
                "district_key": district_key,
                "official_url": term.get("url", ""),
                "office": term.get("office", ""),
                "address": term.get("address", ""),
                "phone": term.get("phone", ""),
                "term_start": term.get("start", ""),
                "term_end": term.get("end", ""),
            }
        )

    df = pd.DataFrame(rows)

    df = df.sort_values(["state_abbr", "district_code", "last_name", "first_name"])

    df.to_csv(OUTPUT_CSV, index=False)

    print(f"Wrote member profiles: {OUTPUT_CSV}")
    print(f"Rows: {len(df):,}")
    print()
    print(df[[
        "bioguide_id",
        "full_name",
        "party",
        "state_abbr",
        "district",
        "district_key",
        "official_url",
    ]].head(25).to_string(index=False))


if __name__ == "__main__":
    main()
