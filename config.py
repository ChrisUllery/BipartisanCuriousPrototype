# config.py
from pathlib import Path

# -------------------------
# Project directories
# -------------------------

PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = PROJECT_ROOT / "data"

RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DASHBOARD_DATA_DIR = DATA_DIR / "dashboard"

METADATA_DIR = RAW_DIR / "metadata"
MEMBER_VOTES_DIR = RAW_DIR / "member_votes"

VOTE_SUMMARIES_DIR = PROCESSED_DIR / "vote_summaries"
STANCE_TABLES_DIR = PROCESSED_DIR / "stance_tables"
ALIGNMENT_TABLES_DIR = PROCESSED_DIR / "alignment_tables"

DOCS_DIR = PROJECT_ROOT / "docs"
DOCS_ASSETS_DIR = DOCS_DIR / "assets"

# -------------------------
# Scraping settings
# -------------------------

START_CONGRESS = 119
END_CONGRESS = 119

# Set this manually for now.
# Later we can make it infer automatically.
ACTIVE_CONGRESS = 119

SESSIONS = ["1st", "2nd"]

# -------------------------
# Behavior switches
# -------------------------

OVERWRITE_METADATA = False
OVERWRITE_MEMBER_VOTES = False
OVERWRITE_HISTORIC_OUTPUTS = False
ALWAYS_REBUILD_ACTIVE_CONGRESS = True

# -------------------------
# Ensure folders exist
# -------------------------

REQUIRED_DIRS = [
    DATA_DIR,
    RAW_DIR,
    PROCESSED_DIR,
    DASHBOARD_DATA_DIR,
    METADATA_DIR,
    MEMBER_VOTES_DIR,
    VOTE_SUMMARIES_DIR,
    STANCE_TABLES_DIR,
    ALIGNMENT_TABLES_DIR,
    DOCS_DIR,
    DOCS_ASSETS_DIR,
]

for folder in REQUIRED_DIRS:
    folder.mkdir(parents=True, exist_ok=True)