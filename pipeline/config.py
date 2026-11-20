"""Paths from the repo root, the TMDb key from the environment, and all thresholds."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

INPUT_IDS = REPO_ROOT / "data" / "input" / "id_list.csv"
OUT_DIR = REPO_ROOT / "out"
RAW_DIR = REPO_ROOT / "data" / "raw"  # unused until the fetch stage

EXPECTED_HEADER = "tmdb_id"

# Compared after strip and lower-case. Anything else that is not a whole number
# falls to invalid_text, so a new placeholder never passes silently.
PLACEHOLDER_VALUES = {"n/a", "na", "null", "none", "nan", "-", "?"}

# Flag for review only; never a filter. The API decides whether an id exists.
LARGE_ID_REVIEW_THRESHOLD = 2_000_000
