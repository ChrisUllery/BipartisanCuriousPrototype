import re
from pathlib import Path

import pandas as pd


ALIGNMENT_PATH = Path("data/dashboard/member_alignment_119.csv")
PROFILE_PATH = Path("data/raw/member_profiles/member_profiles_119.csv")

OUTPUT_PATH = Path("data/dashboard/member_alignment_119_enriched.csv")
UNMATCHED_PATH = Path("data/dashboard/member_alignment_119_unmatched_profiles.csv")
MATCH_REVIEW_PATH = Path("data/dashboard/member_alignment_119_match_review.csv")


def normalize_name(value):
    value = str(value).strip()

    # Remove parenthetical state/district hints, e.g. "Amodei (NV)"
    value = re.sub(r"\s*\([^)]*\)", "", value)

    # Lowercase and remove punctuation
    value = value.lower()
    value = value.replace(".", "")
    value = value.replace(",", "")
    value = value.replace("'", "")
    value = value.replace("?", "")
    value = value.replace("-", " ")

    # Collapse whitespace
    value = re.sub(r"\s+", " ", value).strip()

    return value


def last_name_key(full_name):
    value = normalize_name(full_name)

    if not value:
        return ""

    parts = value.split()

    # Drop common suffixes
    suffixes = {"jr", "sr", "ii", "iii", "iv", "v"}
    parts = [p for p in parts if p not in suffixes]

    if not parts:
        return ""

    return parts[-1]


def build_alignment_key(row):
    return f"{row['state_abbr']}|{normalize_name(row['representative'])}"


def build_profile_last_name_key(row):
    return f"{row['state_abbr']}|{last_name_key(row['full_name'])}"


def main():
    alignment = pd.read_csv(ALIGNMENT_PATH)
    profiles = pd.read_csv(PROFILE_PATH)

    alignment["state_abbr"] = alignment["state_abbr"].astype(str).str.strip()
    profiles["state_abbr"] = profiles["state_abbr"].astype(str).str.strip()

    alignment["match_key"] = alignment.apply(build_alignment_key, axis=1)
    profiles["match_key"] = profiles.apply(build_profile_last_name_key, axis=1)

    profile_cols = [
        "match_key",
        "bioguide_id",
        "govtrack_id",
        "icpsr_id",
        "wikidata_id",
        "full_name",
        "first_name",
        "last_name",
        "party",
        "state_abbr",
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

    profiles_small = profiles[profile_cols].copy()

    # Find duplicate keys in profile table. These need manual review because last-name matching is not unique.
    duplicate_profile_keys = (
        profiles_small["match_key"]
        .value_counts()
        .loc[lambda s: s > 1]
        .index
        .tolist()
    )

    profiles_deduped = profiles_small[
        ~profiles_small["match_key"].isin(duplicate_profile_keys)
    ].copy()

    enriched = alignment.merge(
        profiles_deduped,
        on="match_key",
        how="left",
        suffixes=("", "_profile"),
    )

    # If party/state columns from profile came through, keep alignment party/state as primary.
    if "party_profile" in enriched.columns:
        enriched = enriched.drop(columns=["party_profile"])

    if "state_abbr_profile" in enriched.columns:
        enriched = enriched.drop(columns=["state_abbr_profile"])

    unmatched = enriched[enriched["bioguide_id"].isna()].copy()

    # Build a review table for unmatched rows, with possible same-state candidates.
    review_rows = []

    for _, row in unmatched.iterrows():
        state = row["state_abbr"]
        rep = row["representative"]

        same_state = profiles[profiles["state_abbr"] == state].copy()

        candidates = same_state[
            [
                "bioguide_id",
                "full_name",
                "party",
                "state_abbr",
                "district",
                "district_key",
                "official_url",
            ]
        ].to_dict("records")

        review_rows.append(
            {
                "representative": rep,
                "party": row.get("party", ""),
                "state_abbr": state,
                "match_key": row["match_key"],
                "reason": (
                    "duplicate_profile_key"
                    if row["match_key"] in duplicate_profile_keys
                    else "no_profile_match"
                ),
                "same_state_candidate_count": len(candidates),
                "same_state_candidates": candidates,
            }
        )

    review = pd.DataFrame(review_rows)

    # Put useful profile columns near the front.
    front_cols = [
        "representative",
        "full_name",
        "bioguide_id",
        "party",
        "state",
        "state_abbr",
        "district",
        "district_code",
        "district_key",
        "official_url",
    ]

    existing_front_cols = [c for c in front_cols if c in enriched.columns]
    remaining_cols = [c for c in enriched.columns if c not in existing_front_cols and c != "match_key"]

    enriched = enriched[existing_front_cols + remaining_cols]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(OUTPUT_PATH, index=False)
    unmatched.to_csv(UNMATCHED_PATH, index=False)
    review.to_csv(MATCH_REVIEW_PATH, index=False)

    print(f"Wrote enriched alignment: {OUTPUT_PATH}")
    print(f"Rows: {len(enriched):,}")
    print(f"Matched rows: {enriched['bioguide_id'].notna().sum():,}")
    print(f"Unmatched rows: {enriched['bioguide_id'].isna().sum():,}")
    print()
    print(f"Wrote unmatched rows: {UNMATCHED_PATH}")
    print(f"Wrote match review: {MATCH_REVIEW_PATH}")
    print()
    print("Sample enriched rows:")
    print(
        enriched[
            [
                "representative",
                "full_name",
                "party",
                "state_abbr",
                "district",
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
