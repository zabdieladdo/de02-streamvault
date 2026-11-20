"""Stage 2: fetch details and credits from TMDb with retries, a rate limit, a cache and a fetch log."""
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pipeline import config
from pipeline.errors import PipelineStopError
from pipeline.redact import redact

LOG_COLUMNS = [
    "tmdb_id", "endpoint", "path", "status_code", "outcome",
    "attempts", "fetched_at", "elapsed_s", "detail",
]
RESULT_COLUMNS = LOG_COLUMNS + ["source", "cache_age_days", "fail_text"]

SUCCESS = ("ok", "cached")
NOT_FOUND = ("not_found", "cached_not_found")
FAILURES = ("failed", "network_error")

REASON_DETAIL = {
    "not_found_on_api": "TMDb has no film with this id",
    "credits_missing": "Film found but credits not found",
    "id_mismatch": "Response id does not match requested id",
    "bad_response": "Response was not valid JSON",
    "fetch_failed": "Request failed after retries",
}
REASON_ORDER = list(REASON_DETAIL)


@dataclass
class FetchResult:
    tmdb_id: int
    endpoint: str
    path: str
    status_code: int | None
    outcome: str
    attempts: int | None
    fetched_at: str
    elapsed_s: float
    detail: str = ""
    body: dict | None = None  # never written to the log
    age_days: float | None = None  # only for results read from the cache


@dataclass
class FetchRun:
    results: pd.DataFrame
    quarantine: pd.DataFrame
    ids_processed: pd.DataFrame
    network_calls: int = 0
    network_seconds: float = 0.0
    preflight_ok: bool = True
    refresh: bool = False
    limit: int | None = None
    extra: dict = field(default_factory=dict)


# --- session and rate limit ----------------------------------------------

def build_session() -> requests.Session:
    """Session with retries and backoff on transient errors, and an honest User-Agent."""
    retry = Retry(
        total=config.MAX_RETRIES,
        connect=config.MAX_RETRIES,
        read=config.MAX_RETRIES,
        status=config.MAX_RETRIES,
        backoff_factor=config.BACKOFF_FACTOR,
        status_forcelist=config.RETRY_STATUSES,
        allowed_methods=["GET"],
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = config.USER_AGENT
    return session


class RateLimiter:
    """Keep network requests at least 1 / requests_per_second seconds apart."""

    def __init__(self, requests_per_second: float):
        self.interval = 1.0 / requests_per_second
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            gap = self.interval - (time.monotonic() - self._last)
            if gap > 0:
                time.sleep(gap)
        self._last = time.monotonic()


# --- helpers ---------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_days(iso: str, now: datetime) -> float | None:
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (now - then).total_seconds() / 86400


def endpoint_path(endpoint: str, tmdb_id: int) -> str:
    return config.ENDPOINTS[endpoint].format(id=tmdb_id)


def cache_file(endpoint: str, tmdb_id: int) -> Path:
    directory = config.RAW_DETAILS_DIR if endpoint == "details" else config.RAW_CREDITS_DIR
    return directory / f"{tmdb_id}.json"


def _write_cache(path: Path, content: bytes) -> None:
    """Write the bytes as received, to a temp file first so a crash leaves no half file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def _message(response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            return str(body.get("status_message", ""))
    except ValueError:
        pass
    return ""


# --- one request -----------------------------------------------------------

def get_one(session, limiter: RateLimiter, endpoint: str, tmdb_id: int, key: str) -> FetchResult:
    """One network request. Writes the cache file on success; raises on a 401."""
    path = endpoint_path(endpoint, tmdb_id)
    limiter.wait()
    started = time.perf_counter()
    fetched_at = _now_iso()

    def result(outcome, status=None, attempts=None, detail="", body=None):
        return FetchResult(
            tmdb_id, endpoint, path, status, outcome, attempts, fetched_at,
            round(time.perf_counter() - started, 3), redact(detail, key), body,
        )

    try:
        response = session.get(
            config.API_BASE + path, params={"api_key": key}, timeout=config.TIMEOUT
        )
    except requests.RequestException as exc:
        return result("network_error", detail=f"{type(exc).__name__}: {exc}")

    history = getattr(getattr(getattr(response, "raw", None), "retries", None), "history", None)
    attempts = 1 + (len(history) if history else 0)
    status = response.status_code

    if status == 401:
        raise PipelineStopError(
            "API key rejected (401). Check TMDB_API_KEY; nothing further requested."
        )
    if status == 404:
        return result("not_found", status, attempts, _message(response))
    if status != 200:
        return result("failed", status, attempts, f"HTTP {status} {_message(response)}".strip())

    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return result("bad_response", status, attempts, "Response was not valid JSON")
    if body.get("id") != tmdb_id:
        return result(
            "id_mismatch", status, attempts,
            f"Response id {body.get('id')!r} does not match requested id",
        )
    _write_cache(cache_file(endpoint, tmdb_id), response.content)
    return result("ok", status, attempts, "", body)


# --- fetch log --------------------------------------------------------------

def read_fetch_log() -> dict:
    """Latest known state per (tmdb_id, endpoint), from data/raw/fetch_log.csv."""
    if not config.FETCH_LOG.is_file():
        return {}
    df = pd.read_csv(config.FETCH_LOG, dtype=str, keep_default_na=False)
    return {(int(r["tmdb_id"]), r["endpoint"]): r for r in df.to_dict("records")}


def write_fetch_log(log: dict) -> None:
    config.FETCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    rows = [log[k] for k in sorted(log)]
    pd.DataFrame(rows, columns=LOG_COLUMNS).to_csv(
        config.FETCH_LOG, index=False, encoding="utf-8"
    )


def _log_row(r: FetchResult) -> dict:
    return {
        "tmdb_id": r.tmdb_id, "endpoint": r.endpoint, "path": r.path,
        "status_code": "" if r.status_code is None else r.status_code,
        "outcome": r.outcome,
        "attempts": "" if r.attempts is None else r.attempts,
        "fetched_at": r.fetched_at, "elapsed_s": r.elapsed_s, "detail": r.detail,
    }


# --- the fetch loop -----------------------------------------------------------

def fetch_all(
    ids: pd.DataFrame,
    session=None,
    key: str | None = None,
    refresh: bool = False,
    limit: int | None = None,
    run_at: str | None = None,
) -> FetchRun:
    """Fetch details and credits for each id; record every outcome; quarantine failures.

    This is the one place a loop over ids is right: each id needs its own request.
    """
    run_at = run_at or _now_iso()
    ids = ids.sort_values("first_line_number").reset_index(drop=True)
    if limit is not None:
        ids = ids.head(limit)

    now = datetime.now(timezone.utc)
    log = read_fetch_log()
    limiter = RateLimiter(config.REQUESTS_PER_SECOND)
    state = {
        "session": session, "network_calls": 0, "network_seconds": 0.0,
        "consecutive": 0, "first_network": True, "preflight_ok": True, "opened_here": False,
    }
    rows: list[dict] = []

    def from_cache(tmdb_id: int, endpoint: str) -> FetchResult | None:
        entry = log.get((tmdb_id, endpoint))
        max_age = config.CACHE_MAX_AGE_DAYS
        path = endpoint_path(endpoint, tmdb_id)

        def cached(outcome, age, fetched_at):
            status = entry.get("status_code") if entry else ""
            attempts = entry.get("attempts") if entry else ""
            res = FetchResult(
                tmdb_id, endpoint, path,
                int(status) if status not in ("", None) else None,
                outcome,
                int(attempts) if attempts not in ("", None) else None,
                fetched_at, 0.0, entry.get("detail", "") if entry else "",
                age_days=age,
            )
            return res

        if entry and entry["outcome"] == "not_found":
            age = _age_days(entry["fetched_at"], now)
            if age is not None and age < max_age:
                return cached("cached_not_found", age, entry["fetched_at"])
            return None

        file = cache_file(endpoint, tmdb_id)
        if not file.is_file():
            return None
        if entry:
            if entry["outcome"] != "ok":
                return None
            fetched_at = entry["fetched_at"]
            age = _age_days(fetched_at, now)
        else:  # file with no log entry: trust its modification time
            mtime = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc)
            fetched_at = mtime.isoformat(timespec="seconds")
            age = (now - mtime).total_seconds() / 86400
        if age is None or age >= max_age:
            return None
        return cached("cached", age, fetched_at)

    def resolve(tmdb_id: int, endpoint: str) -> tuple[FetchResult, str]:
        if not refresh:
            hit = from_cache(tmdb_id, endpoint)
            if hit is not None:
                return hit, "cache"
        if key is None:
            raise PipelineStopError(
                "TMDB_API_KEY not set, and some responses are not cached. "
                "Copy .env.example to .env and add your own key."
            )
        if state["session"] is None:
            state["session"] = build_session()
            state["opened_here"] = True  # a session passed in by the caller is theirs to close

        started = time.perf_counter()
        try:
            res = get_one(state["session"], limiter, endpoint, tmdb_id, key)
        finally:
            state["network_seconds"] += time.perf_counter() - started
            state["network_calls"] += 1
        log[(tmdb_id, endpoint)] = _log_row(res)

        state["consecutive"] = state["consecutive"] + 1 if res.outcome == "network_error" else 0
        if state["first_network"]:  # preflight: the first request proves key and network
            state["first_network"] = False
            if res.outcome == "network_error":
                state["preflight_ok"] = False
                raise PipelineStopError(
                    "Network check failed on the first request; nothing further requested. "
                    + res.detail
                )
        if state["consecutive"] >= config.STOP_AFTER_CONSECUTIVE_NETWORK_ERRORS:
            raise PipelineStopError(
                f"Network appears down after {state['consecutive']} consecutive errors; "
                "nothing further requested"
            )
        return res, "network"

    def add(res: FetchResult, source: str) -> None:
        row = _log_row(res)
        row.update(
            status_code=res.status_code, attempts=res.attempts,
            source=source, cache_age_days=res.age_days, fail_text="",
        )
        if res.outcome in FAILURES:
            code = f"HTTP {res.status_code}" if res.status_code else res.detail
            n = res.attempts if res.attempts is not None else "all"
            row["fail_text"] = f"{res.endpoint}: {code}, after {n} attempts"
        rows.append(row)

    try:
        for tmdb_id in ids["tmdb_id"].tolist():
            details, src = resolve(tmdb_id, "details")
            add(details, src)
            if details.outcome in NOT_FOUND:
                skipped = FetchResult(
                    tmdb_id, "credits", endpoint_path("credits", tmdb_id), None,
                    "skipped", None, _now_iso(), 0.0, "details not found",
                )
                log[(tmdb_id, "credits")] = _log_row(skipped)
                add(skipped, "none")
                continue
            credits_, src = resolve(tmdb_id, "credits")
            add(credits_, src)
    finally:
        write_fetch_log(log)  # also on the stop path, so completed requests are kept
        if state["opened_here"]:
            state["session"].close()  # release the connections this stage opened

    results = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    for col in ("status_code", "attempts"):
        results[col] = pd.to_numeric(results[col]).astype("Int64")
    quarantine = _quarantine(ids, results, run_at)
    return FetchRun(
        results=results,
        quarantine=quarantine,
        ids_processed=ids,
        network_calls=state["network_calls"],
        network_seconds=state["network_seconds"],
        preflight_ok=state["preflight_ok"],
        refresh=refresh,
        limit=limit,
    )


# --- fetch-stage quarantine (vectorised) --------------------------------------

def _quarantine(ids: pd.DataFrame, results: pd.DataFrame, run_at: str) -> pd.DataFrame:
    cols = ["line_number", "raw_value", "reason_code", "reason_detail", "stage", "run_at"]
    if results.empty:
        return pd.DataFrame(columns=cols)

    def side(endpoint, prefix):
        part = results[results["endpoint"] == endpoint].set_index("tmdb_id")
        return part[["outcome", "detail", "fail_text"]].add_prefix(prefix)

    wide = (
        ids.set_index("tmdb_id")[["first_line_number"]]
        .join(side("details", "d_"))
        .join(side("credits", "c_"))
    )
    d, c = wide["d_outcome"], wide["c_outcome"]
    d_ok, c_ok = d.isin(SUCCESS), c.isin(SUCCESS)

    conditions = [
        d.isin(NOT_FOUND),
        d_ok & c.isin(NOT_FOUND),
        (d == "id_mismatch") | (c == "id_mismatch"),
        (d == "bad_response") | (c == "bad_response"),
        d.isin(FAILURES) | c.isin(FAILURES),
    ]
    codes = ["not_found_on_api", "credits_missing", "id_mismatch", "bad_response", "fetch_failed"]
    wide["reason_code"] = np.select(conditions, codes, default="")

    mismatch_text = np.where(d == "id_mismatch", wide["d_detail"], wide["c_detail"])
    failed_text = np.where(d.isin(FAILURES), wide["d_fail_text"], wide["c_fail_text"])
    wide["reason_detail"] = np.select(
        conditions,
        [
            "TMDb has no film with this id: " + wide["d_detail"].astype(str),
            "Film found but credits not found",
            mismatch_text,
            "Response was not valid JSON",
            failed_text,
        ],
        default="",
    )
    went_forward = wide["reason_code"] == ""
    assert (d_ok & c_ok)[went_forward].all(), "an id with no reason must have both endpoints ok"

    q = wide[~went_forward].reset_index()
    return (
        pd.DataFrame(
            {
                "line_number": q["first_line_number"],
                "raw_value": q["tmdb_id"].astype(str),
                "reason_code": q["reason_code"],
                "reason_detail": q["reason_detail"],
                "stage": "fetch",
                "run_at": run_at,
            }
        )
        .sort_values("line_number")
        .reset_index(drop=True)
    )
