"""Spot-check: pick the films most likely to be wrong, re-fetch them live, compare field by field.

Nothing here writes to data/raw/ or the fetch log: the saved snapshot is what is being checked,
so the check must not change it.
"""
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import requests

from pipeline import config, fetch
from pipeline.errors import PipelineStopError
from pipeline.redact import redact
from pipeline.transform import imdb_crossref

SLICES = (
    "heaviest_parsing", "extreme_high", "extreme_low", "cleaning_decision", "nearly_failed",
    "drives_recommendation",
)
SELECTION_COLUMNS = ["slice", "tmdb_id", "title", "detail", "stand_in"]


def _pick(frame: pd.DataFrame, column: str, ascending: bool = False) -> pd.DataFrame:
    """The one row with the largest (or smallest) value; ties go to the lowest film id."""
    ordered = frame.sort_values([column, "tmdb_id"], ascending=[ascending, True], kind="stable")
    return ordered.head(1)


def _rows(slice_name: str, films: pd.DataFrame, detail: pd.Series, stand_in: bool = False) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "slice": slice_name, "tmdb_id": films["tmdb_id"].astype("int64"),
            "title": films["title"].astype(str), "detail": detail.astype(str), "stand_in": stand_in,
        }
    )


def select_spotcheck_films(
    films_clean: pd.DataFrame,
    ids_to_fetch: pd.DataFrame,
    quarantine: pd.DataFrame,
    deal_note: pd.DataFrame,
    fetch_log: pd.DataFrame,
) -> pd.DataFrame:
    """One row per (slice, film): the films most likely to be wrong, chosen by rule from the outputs.

    The rules are computed from the data, never hard-coded, so a re-run on a new list picks its own.
    `nearly_failed` is a stand-in (stand_in True) when no request needed a retry.
    """
    f = films_clean
    parts = []

    weight = f["n_cast"] + f["n_crew"] + f["n_genres"].astype("int64")
    heavy = _pick(f.assign(weight=weight), "weight")
    parts.append(_rows("heaviest_parsing", heavy, "cast + crew + genres = " + heavy["weight"].astype(str)))

    usable = f[f["roi_usable"].astype(bool)].assign(roi=lambda d: d["roi"].astype("float64"))
    if len(usable):
        high, low = _pick(usable, "roi"), _pick(usable, "roi", ascending=True)
        parts.append(_rows("extreme_high", high, "multiple " + high["roi"].round(2).astype(str)))
        parts.append(_rows("extreme_low", low, "multiple " + low["roi"].round(2).astype(str)))

    # list entries: how many rows of the id list point at the film (repeats, plus a matched IMDb id)
    load_quarantine = quarantine[quarantine["stage"] == "load"]
    matched = imdb_crossref(f, load_quarantine).dropna(subset=["tmdb_id"])
    imdb_hits = matched["tmdb_id"].astype("int64").value_counts()
    entries = ids_to_fetch.set_index("tmdb_id")["n_occurrences"].astype("int64")
    listed = f.assign(
        list_entries=f["tmdb_id"].map(entries).fillna(0).astype("int64")
        + f["tmdb_id"].map(imdb_hits).fillna(0).astype("int64")
    )
    cleaned = _pick(listed, "list_entries")
    parts.append(_rows("cleaning_decision", cleaned, "listed " + cleaned["list_entries"].astype(str) + " times"))

    # nearly failed: the most attempts in the fetch log; with no retries, the slowest response
    log = fetch_log.assign(
        tmdb_id=pd.to_numeric(fetch_log["tmdb_id"]).astype("int64"),
        attempts=pd.to_numeric(fetch_log["attempts"]), elapsed_s=pd.to_numeric(fetch_log["elapsed_s"]),
    )
    log = log[log["tmdb_id"].isin(f["tmdb_id"])]
    if len(log):
        worst = log.sort_values(["attempts", "elapsed_s", "tmdb_id"], ascending=[False, False, True]).head(1)
        stand_in = bool(worst["attempts"].iloc[0] <= 1)
        films = f[f["tmdb_id"].isin(worst["tmdb_id"])]
        detail = (worst["endpoint"].astype(str) + ": " + worst["attempts"].astype(int).astype(str)
                  + " attempt(s), " + worst["elapsed_s"].astype(str) + " s")
        parts.append(_rows("nearly_failed", films, pd.Series(detail.to_numpy(), index=films.index), stand_in))

    # the films of the robust deal-note candidate: they drive the recommendation
    robust = deal_note[deal_note["candidate"] == "robust candidate"]
    if len(robust):
        mine = f[f["collection_id"].isin(robust["collection_id"].astype("int64"))].sort_values("tmdb_id")
        label = "robust candidate: " + str(robust["collection_name"].iloc[0])
        parts.append(_rows("drives_recommendation", mine, pd.Series(label, index=mine.index, dtype=str)))

    out = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else None
    if out is None:
        return pd.DataFrame(columns=SELECTION_COLUMNS)
    order = out["slice"].map({name: i for i, name in enumerate(SLICES)})
    out = out.assign(_order=order).sort_values(["_order", "tmdb_id"]).drop(columns="_order")
    return out.reset_index(drop=True)[SELECTION_COLUMNS]


def films_to_check(selection: pd.DataFrame) -> pd.DataFrame:
    """One row per film, with every slice it carries listed once; a film in two slices appears once."""
    if selection.empty:
        return pd.DataFrame(columns=["tmdb_id", "title", "slices", "stand_in"])
    first = selection.reset_index().groupby("tmdb_id")["index"].min()
    grouped = selection.groupby("tmdb_id").agg(
        title=("title", "first"), slices=("slice", "|".join), stand_in=("stand_in", "any"),
    )
    return grouped.assign(first=first).sort_values("first").drop(columns="first").reset_index()


# --- live fetch: read-only ------------------------------------------------------------

ENDPOINTS = ("details", "credits")


@dataclass
class LiveResult:
    """One live answer for a film and an endpoint. Kept in memory and in out/; never in data/raw/."""

    tmdb_id: int
    endpoint: str
    outcome: str
    status_code: int | None
    attempts: int | None
    elapsed_s: float
    fetched_at: str
    detail: str = ""
    body: dict | None = None


def fetch_one_live(
    session: requests.Session, limiter: fetch.RateLimiter, endpoint: str, tmdb_id: int, key: str
) -> LiveResult:
    """One live request, with the fetch stage's timeout and retries. Writes nothing; raises on a 401.

    This is deliberately not fetch.get_one, which saves the response into data/raw/: the snapshot is
    what is being checked, so the check must not be able to change it.
    """
    path = fetch.endpoint_path(endpoint, tmdb_id)
    limiter.wait()
    started = time.perf_counter()
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")

    def result(outcome, status=None, attempts=None, detail="", body=None):
        return LiveResult(
            tmdb_id, endpoint, outcome, status, attempts, round(time.perf_counter() - started, 3),
            fetched_at, redact(detail, key), body,
        )

    try:
        response = session.get(config.API_BASE + path, params={"api_key": key}, timeout=config.TIMEOUT)
    except requests.RequestException as exc:
        return result("network_error", detail=f"{type(exc).__name__}: {exc}")

    history = getattr(getattr(getattr(response, "raw", None), "retries", None), "history", None)
    attempts = 1 + (len(history) if history else 0)
    status = response.status_code
    if status == 401:
        raise PipelineStopError("API key rejected (401). Check TMDB_API_KEY; nothing further requested.")
    if status == 404:
        return result("not_found", status, attempts, fetch._message(response))
    if status != 200:
        return result("failed", status, attempts, f"HTTP {status} {fetch._message(response)}".strip())
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return result("bad_response", status, attempts, "Response was not valid JSON")
    if body.get("id") != tmdb_id:
        return result("id_mismatch", status, attempts, f"Response id {body.get('id')!r} does not match")
    return result("ok", status, attempts, "", body)


def fetch_live(
    tmdb_ids: list[int], session: requests.Session | None = None, key: str | None = None
) -> list[LiveResult]:
    """Details and credits for each film, live. A loop over the films: each needs its own requests.

    A session passed in is left open; one opened here is closed. Nothing is written to disk.
    """
    if not key:
        raise PipelineStopError("TMDB_API_KEY not set. Copy .env.example to .env and add your own key.")
    opened = session is None
    session = fetch.build_session() if opened else session
    limiter = fetch.RateLimiter(config.REQUESTS_PER_SECOND)
    results: list[LiveResult] = []
    consecutive = 0
    try:
        for tmdb_id in tmdb_ids:
            for endpoint in ENDPOINTS:
                res = fetch_one_live(session, limiter, endpoint, int(tmdb_id), key)
                results.append(res)
                consecutive = consecutive + 1 if res.outcome == "network_error" else 0
                if consecutive >= config.STOP_AFTER_CONSECUTIVE_NETWORK_ERRORS:
                    raise PipelineStopError(
                        f"{consecutive} network errors in a row; the network appears to be down. "
                        "Nothing was written."
                    )
    finally:
        if opened:
            session.close()
    return results


# --- compare field by field -----------------------------------------------------------

# (endpoint, field, kind). Kinds: exact, volatile (changes daily on TMDb), roi (a computed ratio).
FIELDS = [
    ("details", "title", "exact"),
    ("details", "release_date", "exact"),
    ("details", "status", "exact"),
    ("details", "budget", "exact"),
    ("details", "revenue", "exact"),
    ("details", "belongs_to_collection.id", "exact"),
    ("details", "genres[].name", "exact"),
    ("details", "imdb_id", "exact"),
    ("details", "vote_count", "volatile"),
    ("details", "vote_average", "volatile"),
    ("details", "popularity", "volatile"),
    ("credits", "director person ids", "exact"),
    ("credits", "top 3 cast person ids", "exact"),
    ("computed", "revenue / budget", "roi"),
]
FIELD_KIND = {field: kind for _, field, kind in FIELDS}
FIELD_ENDPOINT = {field: endpoint for endpoint, field, _ in FIELDS}
OUR_COLUMN = {
    "title": "title", "release_date": "release_date_raw", "status": "status", "budget": "budget",
    "revenue": "revenue", "belongs_to_collection.id": "collection_id", "genres[].name": "genres_all",
    "imdb_id": "imdb_id", "vote_count": "vote_count", "vote_average": "vote_average",
    "popularity": "popularity",
}
# fields whose value can be read from the wrong place in the response: money and dates only
WRONG_FIELD_CHECKED = {"budget": "budget", "revenue": "revenue", "release_date": "release_date"}
ROI_REL_TOL = 1e-9
COMPARISON_COLUMNS = [
    "tmdb_id", "title", "slices", "endpoint", "field", "fresh", "raw", "ours", "class", "note",
]
DISCREPANCY_EXCLUDED = ("match", "volatile_changed", "unverified")


def _canon(value) -> str:
    """A value as comparable text: missing is "", whole numbers have no decimal point."""
    if value is None or value is pd.NA:
        return ""
    if isinstance(value, float | np.floating):
        return "" if np.isnan(value) else (str(int(value)) if float(value).is_integer() else repr(float(value)))
    if isinstance(value, bool | np.bool_):
        return str(bool(value))
    if isinstance(value, int | np.integer):
        return str(int(value))
    return str(value)


def _ratio(budget, revenue):
    """revenue / budget when both are positive, else None (the pipeline's own rule for a multiple)."""
    b, r = pd.to_numeric(pd.Series([budget, revenue]), errors="coerce")
    return float(r / b) if pd.notna(b) and pd.notna(r) and b > 0 and r > 0 else None


def _ids(frame: pd.DataFrame, limit: int | None = None, sort: bool = False) -> str:
    ids = frame["id"].dropna().astype("int64")
    ids = ids.sort_values() if sort else ids
    return "|".join(ids.head(limit).astype(str)) if limit else "|".join(ids.astype(str))


def extract_details(payload: dict | None) -> dict:
    """The compared fields from a details response (a fresh one or a saved one)."""
    if not payload:
        return {}
    collection = payload.get("belongs_to_collection") or {}
    genres = pd.json_normalize(payload.get("genres") or []).reindex(columns=["name"])["name"].dropna()
    values = {
        "title": payload.get("title"), "release_date": payload.get("release_date"),
        "status": payload.get("status"), "budget": payload.get("budget"), "revenue": payload.get("revenue"),
        "belongs_to_collection.id": collection.get("id"), "genres[].name": "|".join(genres.astype(str)),
        "imdb_id": payload.get("imdb_id"), "vote_count": payload.get("vote_count"),
        "vote_average": payload.get("vote_average"), "popularity": payload.get("popularity"),
    }
    values["revenue / budget"] = _ratio(values["budget"], values["revenue"])
    return values


def extract_credits(payload: dict | None) -> dict:
    """Director ids (sorted) and the top three cast ids in billing order, from a credits response."""
    if not payload:
        return {}
    crew = pd.json_normalize(payload.get("crew") or []).reindex(columns=["id", "job"])
    cast = pd.json_normalize(payload.get("cast") or []).reindex(columns=["id", "order"])
    cast = cast.assign(order=pd.to_numeric(cast["order"], errors="coerce"))
    leads = cast.sort_values("order", na_position="last", kind="stable").drop_duplicates("id")
    directors = crew[crew["job"] == "Director"].drop_duplicates("id")
    return {
        "director person ids": _ids(directors, sort=True),
        "top 3 cast person ids": _ids(leads, limit=3),
    }


def our_values(film: pd.Series, talent: pd.DataFrame) -> dict:
    """The same fields as our tables hold them: films_clean for the film, talent.csv for its people."""
    mine = talent[talent["tmdb_id"] == film["tmdb_id"]]
    directors = mine[mine["role"] == "director"].sort_values("person_id")
    leads = mine[mine["role"] == "lead_actor"].sort_values("billing_rank")
    values = {field: film[column] for field, column in OUR_COLUMN.items()}
    values["director person ids"] = "|".join(directors["person_id"].astype(str))
    values["top 3 cast person ids"] = "|".join(leads["person_id"].astype(str))
    usable = bool(film["roi_usable"])
    values["revenue / budget"] = film["roi"] if usable else _ratio(film["budget"], film["revenue"])
    return values


def _other_fields(raw_details: dict | None, own_key: str) -> list:
    """Every other plain number or text in a saved details response, for the wrong-field test."""
    if not raw_details:
        return []
    return [
        v for k, v in raw_details.items()
        if k != own_key and v not in (None, "", 0) and isinstance(v, str | int | float) and not isinstance(v, bool)
    ]


def comparison_rows(
    film: dict, fresh: dict, raw: dict, ours: dict, raw_details: dict | None, fresh_ok: dict
) -> pd.DataFrame:
    """One row per field for one film: fresh, saved and our value, ready to classify."""
    rows = []
    for endpoint, field, kind in FIELDS:  # the fixed list of compared fields
        own = WRONG_FIELD_CHECKED.get(field)
        ours_value = ours.get(field)
        other = [_canon(v) for v in _other_fields(raw_details, own)] if own else []
        rows.append(
            {
                "tmdb_id": film["tmdb_id"], "title": film["title"], "slices": film["slices"],
                "endpoint": endpoint, "field": field, "kind": kind,
                "fresh": fresh.get(field), "raw": raw.get(field), "ours": ours_value,
                "fresh_ok": fresh_ok.get(endpoint, True),
                "in_other_field": bool(own and _canon(ours_value) not in ("", "0") and _canon(ours_value) in other),
            }
        )
    return pd.DataFrame(rows)


def classify_table(table: pd.DataFrame) -> pd.DataFrame:
    """Add `class` and `note` by comparing fresh, saved (raw) and our value in every row at once.

    match; parsing_error (fresh = raw, ours differs); source_changed (fresh differs, raw = ours);
    both at once; volatile_changed for fields TMDb updates daily; wrong_field when ours equals another
    field of the saved response; unverified when the live answer was not available.
    """
    t = table.copy()
    text = {c: t[c].map(_canon) for c in ("fresh", "raw", "ours")}
    num = {c: pd.to_numeric(text[c], errors="coerce") for c in text}
    tol = np.where(t["kind"] == "roi", ROI_REL_TOL, 0.0)

    def same(a: str, b: str) -> pd.Series:
        close = num[a].notna() & num[b].notna() & np.isclose(num[a].fillna(0), num[b].fillna(0), rtol=tol, atol=0)
        return (text[a] == text[b]) | pd.Series(close, index=t.index)

    fresh_raw, raw_ours = same("fresh", "raw"), same("raw", "ours")
    volatile = t["kind"] == "volatile"
    wrong = t["in_other_field"].astype(bool) & ~raw_ours
    t["class"] = np.select(
        [~t["fresh_ok"].astype(bool), wrong, fresh_raw & raw_ours, raw_ours & volatile, raw_ours, fresh_raw],
        ["unverified", "wrong_field", "match", "volatile_changed", "source_changed", "parsing_error"],
        default="parsing_error_and_source_changed",
    )
    change = (num["fresh"] - num["raw"]) / num["raw"].where(num["raw"] != 0) * 100
    t["note"] = np.where(
        t["class"] == "volatile_changed",
        np.where(change.notna(), change.round(1).map("{:+.1f}%".format), "changed"),
        np.where(t["class"] == "unverified", "live response not available", ""),
    )
    for c in ("fresh", "raw", "ours"):
        t[c] = text[c]
    return t


def is_discrepancy(classes: pd.Series) -> pd.Series:
    """A discrepancy is any difference that is not a match, a volatile change or an unchecked field."""
    return ~classes.isin(DISCREPANCY_EXCLUDED)


def read_raw(endpoint: str, tmdb_id: int) -> dict | None:
    """The saved response for a film, read only; None if the snapshot has no usable file."""
    path = fetch.cache_file(endpoint, tmdb_id)
    if not path.is_file():
        return None
    try:
        body = json.loads(path.read_bytes())
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def build_comparison(
    checked: pd.DataFrame, live: list[LiveResult], films_clean: pd.DataFrame, talent: pd.DataFrame
) -> pd.DataFrame:
    """Compare every chosen film field by field: live answer, saved snapshot and our tables.

    A loop over the few spot-check films, each of which needs its own saved files read.
    """
    answers = {(r.tmdb_id, r.endpoint): r for r in live}
    by_id = films_clean.set_index("tmdb_id", drop=False)
    parts = []
    for film in checked.to_dict("records"):
        tmdb_id = int(film["tmdb_id"])
        live_details, live_credits = answers.get((tmdb_id, "details")), answers.get((tmdb_id, "credits"))
        ok = {
            "details": bool(live_details and live_details.outcome == "ok"),
            "credits": bool(live_credits and live_credits.outcome == "ok"),
        }
        ok["computed"] = ok["details"]
        raw_details, raw_credits = read_raw("details", tmdb_id), read_raw("credits", tmdb_id)
        fresh = {**extract_details(live_details.body if live_details else None),
                 **extract_credits(live_credits.body if live_credits else None)}
        raw = {**extract_details(raw_details), **extract_credits(raw_credits)}
        ours = our_values(by_id.loc[tmdb_id], talent)
        parts.append(comparison_rows(film, fresh, raw, ours, raw_details, ok))
    if not parts:
        return pd.DataFrame(columns=[*COMPARISON_COLUMNS, "kind"])
    table = classify_table(pd.concat(parts, ignore_index=True))
    return table[[*COMPARISON_COLUMNS, "kind"]]
