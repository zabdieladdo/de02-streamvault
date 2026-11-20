"""Paths from the repo root, the TMDb key from the environment, and all thresholds."""
import os
from pathlib import Path

from pipeline.errors import PipelineStopError

REPO_ROOT = Path(__file__).resolve().parents[1]


def _from_environment(name: str, default: Path) -> Path:
    """A folder or file taken from an environment variable when it is set and not empty, else the default.

    Measurement runs use this to work on copies and on synthetic data without touching the real
    snapshot or outputs. Normal runs set none of the variables.
    """
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else default


INPUT_IDS = _from_environment("STREAMVAULT_INPUT_IDS", REPO_ROOT / "data" / "input" / "id_list.csv")
OUT_DIR = _from_environment("STREAMVAULT_OUT_DIR", REPO_ROOT / "out")
LIMITED_OUT_DIR = OUT_DIR / "limited"  # --limit runs write here, never over full results
RAW_DIR = _from_environment("STREAMVAULT_RAW_DIR", REPO_ROOT / "data" / "raw")

EXPECTED_HEADER = "tmdb_id"

# Compared after strip and lower-case. Anything else that is not a whole number
# falls to invalid_text, so a new placeholder never passes silently.
PLACEHOLDER_VALUES = {"n/a", "na", "null", "none", "nan", "-", "?"}

# Flag for review only; never a filter. The API decides whether an id exists.
LARGE_ID_REVIEW_THRESHOLD = 2_000_000

# --- Stage 2: fetch -------------------------------------------------------
API_BASE = "https://api.themoviedb.org/3"
ENDPOINTS = {"details": "/movie/{id}", "credits": "/movie/{id}/credits"}
REQUESTS_PER_SECOND = 4  # own throttle, well under any TMDb limit
TIMEOUT = (5, 15)  # (connect, read) seconds
MAX_RETRIES = 5
BACKOFF_FACTOR = 1  # waits roughly 1, 2, 4, 8, 16 s
RETRY_STATUSES = (429, 500, 502, 503, 504)
CACHE_MAX_AGE_DAYS = 180  # TMDb terms: no caching beyond 6 months
STOP_AFTER_CONSECUTIVE_NETWORK_ERRORS = 3
INCOMPLETE_THRESHOLD_PCT = 5  # S06: above this, the analysis is marked incomplete
USER_AGENT = "StreamVault-licensing-analysis/0.1 (educational project)"
RAW_DETAILS_DIR = RAW_DIR / "details"
RAW_CREDITS_DIR = RAW_DIR / "credits"
FETCH_LOG = RAW_DIR / "fetch_log.csv"
DOTENV_PATH = REPO_ROOT / ".env"


def get_api_key() -> str:
    """Return TMDB_API_KEY from the environment or .env. Never print or log it."""
    from dotenv import load_dotenv  # local import: only needed when a key is wanted

    load_dotenv(DOTENV_PATH)  # does not override a variable already set
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        raise PipelineStopError(
            "TMDB_API_KEY not set. Copy .env.example to .env and add your own key."
        )
    return key


# --- Stage 3: flatten and join ---------------------------------------------
LEAD_ACTOR_COUNT = 3  # the three lowest `order` values in a film's cast

# --- Stages 4 and 5: clean, flag, measure -----------------------------------
SMALL_MONEY_THRESHOLD = 10_000  # S24: a budget or revenue from 1 to this is suspect
UNITS_ERROR_VOTE_THRESHOLD = 500  # S24: at or above this many votes, suspect money is a likely units error
ROI_HIGH_REVIEW = 50  # multiples above this are listed in the review list, never removed (findings: Looked wrong)
ROI_LOW_REVIEW = 0.05  # same rule for multiples below this
WINDOW_START_YEAR = 2000
MIN_GROUP_FOR_CONCLUSION = 5  # S14
MIN_BUNDLE_FOR_RANKING = 3  # S14
TOP_MONEY_REVIEW_N = 5  # largest budgets and revenues listed for a person to confirm
SEQUEL_TITLE_PATTERN = r"\b(?:\d+|II|III|IV|V|VI|VII|VIII|IX|X)\b|\bPart\b|\bChapter\b|:"

# --- Stage 6: rank and recommend ---------------------------------------------
RELIABLE_MIN_TITLES = 3  # D20: independent titles needed before a person is called reliable
RELIABLE_HIT_RATE = 2 / 3  # D20, S25: share of titles above the list-wide median multiple
SHORTLIST_FRANCHISE_N = 3
SHORTLIST_STANDALONE_N = 5
