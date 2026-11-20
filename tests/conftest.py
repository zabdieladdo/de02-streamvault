"""Shared fixtures: a helper that writes small id-list CSV files to tmp_path."""
import json
import re
from types import SimpleNamespace

import pandas as pd
import pytest

from pipeline import config


@pytest.fixture
def write_ids(tmp_path):
    """Return write(values, header="tmdb_id", newline="\\r\\n", name="ids.csv") -> Path."""

    def write(values, header="tmdb_id", newline="\r\n", name="ids.csv"):
        path = tmp_path / name
        lines = [header, *values]
        path.write_bytes((newline.join(lines) + newline).encode("utf-8"))
        return path

    return write


# --- fetch-stage helpers -------------------------------------------------------
TEST_KEY = "dummy-value-for-tests"  # not a real credential


def ok_body(tmdb_id, endpoint="details"):
    body = {"id": tmdb_id, "title": f"Film {tmdb_id}"}
    if endpoint == "credits":
        body = {"id": tmdb_id, "cast": [], "crew": []}
    return json.dumps(body).encode("utf-8")


NOT_FOUND_BODY = json.dumps(
    {"success": False, "status_code": 34, "status_message": "The resource you requested could not be found."}
).encode("utf-8")


class FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None, retries=0):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.raw = SimpleNamespace(retries=SimpleNamespace(history=[object()] * retries))

    def json(self):
        return json.loads(self.content)


class FakeSession:
    """Scripted stand-in for requests.Session.

    script maps a path ("/movie/603") to a FakeResponse, an Exception to raise, or a list of
    those used in order (the last one repeats). Unscripted paths answer 200 with a matching body.
    """

    def __init__(self, script=None):
        self.script = dict(script or {})
        self.calls = []
        self.closed = False

    def close(self):
        self.closed = True

    def get(self, url, params=None, timeout=None):
        path = url.removeprefix(config.API_BASE)
        self.calls.append(path)
        item = self.script.get(path)
        if isinstance(item, list):
            item = item.pop(0) if len(item) > 1 else item[0]
        if item is None:
            m = re.fullmatch(r"/movie/(\d+)(/credits)?", path)
            tmdb_id = int(m.group(1))
            item = FakeResponse(200, ok_body(tmdb_id, "credits" if m.group(2) else "details"))
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def no_sleep(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)


@pytest.fixture
def fetch_env(tmp_path, monkeypatch, no_sleep):
    """Point every fetch path at tmp_path and set a test key; never read the real .env."""
    raw = tmp_path / "raw"
    monkeypatch.setattr(config, "RAW_DIR", raw)
    monkeypatch.setattr(config, "RAW_DETAILS_DIR", raw / "details")
    monkeypatch.setattr(config, "RAW_CREDITS_DIR", raw / "credits")
    monkeypatch.setattr(config, "FETCH_LOG", raw / "fetch_log.csv")
    monkeypatch.setattr(config, "DOTENV_PATH", tmp_path / "no.env")
    monkeypatch.setenv("TMDB_API_KEY", TEST_KEY)
    return SimpleNamespace(raw=raw, key=TEST_KEY, tmp_path=tmp_path)


def _release_date(r: dict):
    """A date for a fixture row: the given date, else mid-year of its year, else missing."""
    if "date" in r:
        return pd.Timestamp(r["date"])
    year = r.get("year", 2010)
    return pd.NaT if pd.isna(year) else pd.Timestamp(f"{year}-06-01")


def make_films(rows: list[dict]) -> pd.DataFrame:
    """A films table (stage 3 shape, the columns stages 4 and 5 read) from short hand-written rows.

    Each row may give: title, year, status, budget, revenue, votes, franchise (bool or a
    collection id). Anything not given gets a plain default.
    """
    records = []
    for i, r in enumerate(rows, start=1):
        franchise = r.get("franchise", False)
        records.append(
            {
                "tmdb_id": r.get("tmdb_id", i),
                "first_line_number": i + 1,
                "title": r.get("title", f"Film {i}"),
                "release_year": r.get("year", 2010),
                "release_date": _release_date(r),
                "status": r.get("status", "Released"),
                "budget": r.get("budget", 1_000_000),
                "revenue": r.get("revenue", 2_000_000),
                "vote_count": r.get("votes", 1000),
                "is_franchise": bool(franchise),
                "collection_id": (franchise if franchise is not True else 100 + i) if franchise else pd.NA,
                "collection_name": (
                    f"Collection {franchise if franchise is not True else 100 + i}" if franchise else pd.NA
                ),
                "adult": False,
                "video": False,
            }
        )
    df = pd.DataFrame(records)
    for col in ("release_year", "budget", "revenue", "vote_count", "collection_id"):
        df[col] = df[col].astype("Int64")
    df["title"] = df["title"].astype("string")
    df["collection_name"] = df["collection_name"].astype("string")
    df["status"] = df["status"].astype("string")
    return df


def make_talent(rows: list[tuple]) -> pd.DataFrame:
    """A talent table from (tmdb_id, person_id, name, role) tuples."""
    df = pd.DataFrame(rows, columns=["tmdb_id", "person_id", "name", "role"])
    df["tmdb_id"] = df["tmdb_id"].astype("int64")
    df["person_id"] = df["person_id"].astype("int64")
    df["name"] = df["name"].astype("string")
    df["role"] = df["role"].astype("string")
    df["billing_rank"] = pd.array([pd.NA] * len(df), dtype="Int64")
    df["cast_order"] = pd.array([pd.NA] * len(df), dtype="Int64")
    return df
