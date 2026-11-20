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
