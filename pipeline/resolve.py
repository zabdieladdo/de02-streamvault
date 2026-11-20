"""Resolve IMDb ids that stage 1 quarantined, through TMDb's find endpoint. Optional: run_pipeline.py never calls it.

The find endpoint is a third endpoint, outside the two the brief names. Answers are saved to data/raw/find/ under
the same 180-day rule as the other saved responses (ADR-008), and the session, timeout, retries, rate limit and
key redaction are those of the fetch stage.
"""
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from pipeline import config, fetch
from pipeline.errors import PipelineStopError
from pipeline.redact import redact

FIND_PATH = "/find/{imdb_id}"
IMDB_ID = re.compile(r"tt\d{7,9}")
RESOLVED, NOT_FOUND, AMBIGUOUS, FAILED = "resolved", "not_found", "ambiguous", "failed"


@dataclass
class Lookup:
    """What TMDb said about one IMDb id."""

    imdb_id: str
    outcome: str
    tmdb_id: int | None = None
    title: str = ""
    release_year: int | None = None
    note: str = ""
    source: str = "network"  # "cache" when a saved answer was used


def find_file(imdb_id: str) -> Path:
    """Where the saved answer for this IMDb id lives."""
    return config.RAW_DIR / "find" / f"{imdb_id}.json"


def read_saved(imdb_id: str, now: datetime | None = None) -> dict | None:
    """The saved answer, if there is one that is under 180 days old and well formed; otherwise None."""
    path = find_file(imdb_id)
    if not path.is_file():
        return None
    now = now or datetime.now(UTC)
    age_days = (now - datetime.fromtimestamp(path.stat().st_mtime, UTC)).total_seconds() / 86400
    if age_days >= config.CACHE_MAX_AGE_DAYS:
        return None
    try:
        body = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) and isinstance(body.get("movie_results"), list) else None


def _year(release_date: object) -> int | None:
    text = str(release_date or "")[:4]
    return int(text) if text.isdigit() else None


def _describe(film: dict) -> str:
    year = _year(film.get("release_date"))
    return f"{film.get('id')} {film.get('title', '')}" + (f" ({year})" if year else "")


def classify(imdb_id: str, body: dict, source: str = "network") -> Lookup:
    """One film in movie_results is resolved, none is not_found, more than one is ambiguous."""
    films = [f for f in body["movie_results"] if isinstance(f, dict) and isinstance(f.get("id"), int)]
    if len(films) == 1:
        film = films[0]
        return Lookup(imdb_id, RESOLVED, film["id"], str(film.get("title", "")), _year(film.get("release_date")),
                      source=source)
    if not films:
        return Lookup(imdb_id, NOT_FOUND, note="TMDb has no film with this IMDb id", source=source)
    candidates = "; ".join(_describe(f) for f in films)
    return Lookup(imdb_id, AMBIGUOUS, note=f"{len(films)} films: {candidates}", source=source)


def request_find(
    session: requests.Session, limiter: fetch.RateLimiter, imdb_id: str, key: str
) -> tuple[dict | None, str]:
    """One request to the find endpoint. Returns (answer, "") or (None, why it failed); saves a good answer."""
    limiter.wait()
    url = config.API_BASE + FIND_PATH.format(imdb_id=imdb_id)
    try:
        response = session.get(url, params={"api_key": key, "external_source": "imdb_id"}, timeout=config.TIMEOUT)
    except requests.RequestException as exc:
        return None, redact(f"{type(exc).__name__}: {exc}", key)
    if response.status_code == 401:
        raise PipelineStopError("API key rejected (401). Check TMDB_API_KEY; nothing further requested.")
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}"
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("movie_results"), list):
        return None, "Response was not valid JSON with movie_results"
    fetch._write_cache(find_file(imdb_id), response.content)
    return body, ""


def lookup_all(
    imdb_ids: list[str], session: requests.Session | None = None, key: str | None = None
) -> list[Lookup]:
    """Look up each IMDb id once, from the saved answer where there is one. A failed lookup is recorded and the
    others carry on. This is a loop over ids because each needs its own request."""
    results: dict[str, Lookup] = {}
    limiter = fetch.RateLimiter(config.REQUESTS_PER_SECOND)
    opened_here = False
    try:
        for imdb_id in dict.fromkeys(imdb_ids):  # each distinct id once, in the order given
            if not IMDB_ID.fullmatch(imdb_id):
                results[imdb_id] = Lookup(imdb_id, FAILED, note="Not an IMDb id; no request made")
                continue
            saved = read_saved(imdb_id)
            if saved is not None:
                results[imdb_id] = classify(imdb_id, saved, source="cache")
                continue
            if key is None:
                raise PipelineStopError(
                    "TMDB_API_KEY not set, and some answers are not saved. "
                    "Copy .env.example to .env and add your own key."
                )
            if session is None:
                session, opened_here = fetch.build_session(), True
            body, why = request_find(session, limiter, imdb_id, key)
            results[imdb_id] = classify(imdb_id, body) if body is not None else Lookup(imdb_id, FAILED, note=why)
    finally:
        if opened_here and session is not None:
            session.close()
    return [results[i] for i in imdb_ids]


# --- the report and the suggested list ---------------------------------------------------------------------

IMDB_REASON = "imdb_id_not_tmdb"
RESOLVED_NAME, SUGGESTED_NAME = "resolved_ids.csv", "id_list_suggested.csv"
TABLE_COLUMNS = [
    "line_number", "imdb_id", "outcome", "tmdb_id", "title", "release_year", "already_in_list",
    "first_line_number", "note",
]


def load_inputs(out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The quarantined IMDb ids (line number, value) and the valid ids of the client's list, from a pipeline run."""
    missing = [n for n in ("quarantine.csv", "ids_to_fetch.csv") if not (out_dir / n).is_file()]
    if missing:
        raise PipelineStopError(f"Missing {', '.join(missing)} in {out_dir}. Run python run_pipeline.py first.")
    quarantine = pd.read_csv(out_dir / "quarantine.csv", dtype=str, keep_default_na=False)
    rows = quarantine[quarantine["reason_code"] == IMDB_REASON][["line_number", "raw_value"]].copy()
    rows["line_number"] = rows["line_number"].astype("int64")
    return rows.reset_index(drop=True), pd.read_csv(out_dir / "ids_to_fetch.csv")


def build_table(rows: pd.DataFrame, lookups: list[Lookup], ids_to_fetch: pd.DataFrame) -> pd.DataFrame:
    """One row per quarantined IMDb id, with whether a resolved film is already on the client's list."""
    first_line = dict(zip(ids_to_fetch["tmdb_id"], ids_to_fetch["first_line_number"], strict=True))
    records = []
    for line, look in zip(rows["line_number"], lookups, strict=True):  # a few rows, one per quarantined id
        on_list = look.tmdb_id in first_line
        records.append(
            {
                "line_number": line, "imdb_id": look.imdb_id, "outcome": look.outcome, "tmdb_id": look.tmdb_id,
                "title": look.title, "release_year": look.release_year, "already_in_list": on_list,
                "first_line_number": first_line.get(look.tmdb_id), "note": look.note,
            }
        )
    table = pd.DataFrame(records, columns=TABLE_COLUMNS)
    for column in ("tmdb_id", "release_year", "first_line_number"):
        table[column] = table[column].astype("Int64")
    return table


def suggested_ids(ids_to_fetch: pd.DataFrame, table: pd.DataFrame) -> list[int] | None:
    """The client's valid ids plus the resolved films that are not on it; None when there is nothing to add."""
    resolved = table[(table["outcome"] == RESOLVED) & ~table["already_in_list"]]
    new = list(dict.fromkeys(int(i) for i in resolved.sort_values("line_number")["tmdb_id"]))
    if not new:
        return None
    return [*(int(i) for i in ids_to_fetch["tmdb_id"]), *new]


def write_results(out_dir: Path, table: pd.DataFrame, suggested: list[int] | None) -> None:
    """Write resolved_ids.csv, and the suggested list only when there is one (an old suggestion is removed)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / RESOLVED_NAME, index=False, encoding="utf-8")
    target = out_dir / SUGGESTED_NAME
    if suggested is None:
        target.unlink(missing_ok=True)
    else:
        pd.DataFrame({"tmdb_id": suggested}).to_csv(target, index=False, encoding="utf-8")


def _line(row: dict) -> str:
    label = f"  {row['imdb_id']:<12}->  "
    if row["outcome"] == RESOLVED:
        year = f" ({row['release_year']})" if pd.notna(row["release_year"]) else ""
        film = f"{row['tmdb_id']}  {row['title']}{year}"
        if row["already_in_list"]:
            return f"{label}{film}   already on the list (line {row['first_line_number']}): nothing to add"
        return f"{label}{film}   not on the list: added to the suggested list"
    if row["outcome"] == NOT_FOUND:
        return f"{label}not found on TMDb"
    if row["outcome"] == AMBIGUOUS:
        return f"{label}ambiguous, not added: {row['note']}"
    return f"{label}failed, not added: {row['note']}"


def format_summary(table: pd.DataFrame, suggested: list[int] | None, out_dir: Path, n_valid: int) -> str:
    """The text the command prints."""
    lines = ["IMDb id resolver", f"  ids found in quarantine   {len(table)}"]
    lines += [_line(row) for row in table.to_dict("records")]  # one line per id
    if suggested is None:
        lines.append("  suggested list            not written (no new films)")
    else:
        new = len(suggested) - n_valid
        lines.append(
            f"  suggested list            written to {out_dir / SUGGESTED_NAME} ({n_valid} ids from the client's "
            f"list + {new} new)"
        )
        lines.append("  To use it: read it first, then copy it out of the out folder (a full run clears the .csv")
        lines.append("  files there) and set STREAMVAULT_INPUT_IDS to the copy. The client's file is not changed.")
    return chr(10).join(lines)
