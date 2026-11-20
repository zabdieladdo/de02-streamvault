"""Stage 2: fetch details and credits from TMDb with retries, a rate limit, a cache and a fetch log."""
import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
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

SNAPSHOT_NAMES = {"details": "snapshot_movie.jsonl", "credits": "snapshot_credits.jsonl"}


@dataclass
class FetchResult:
    """The outcome of one request, or one answer read from the cache, for a film and an endpoint."""

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
    """Everything the fetch stage produced: results, quarantine, ids processed and call counts."""

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
        """Allow at most `requests_per_second` network requests a second."""
        self.interval = 1.0 / requests_per_second
        self._last: float | None = None

    def wait(self) -> None:
        """Sleep, if needed, so the next request starts one interval after the last."""
        if self._last is not None:
            gap = self.interval - (time.monotonic() - self._last)
            if gap > 0:
                time.sleep(gap)
        self._last = time.monotonic()


# --- helpers ---------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _age_days(iso: str, now: datetime) -> float | None:
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return (now - then).total_seconds() / 86400


def endpoint_path(endpoint: str, tmdb_id: int) -> str:
    """The API path for an endpoint and film id, from the templates in config."""
    return config.ENDPOINTS[endpoint].format(id=tmdb_id)


def cache_file(endpoint: str, tmdb_id: int) -> Path:
    """The file where the raw JSON for this film and endpoint is saved."""
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

def get_one(
    session: requests.Session, limiter: RateLimiter, endpoint: str, tmdb_id: int, key: str
) -> FetchResult:
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
    """Write the fetch log, one row per film and endpoint, to the file named in config."""
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


# --- snapshots: one file per endpoint, so the analysis opens two files instead of about a thousand -----------
# The per-film files stay the source of truth (ADR-008). A snapshot holds one line per film whose fetch-log
# status is "ok": {"tmdb_id", "fetched_at", "response"}. It is a derived file in data/raw/, ignored by git and
# expired with the per-film files, and it can always be rebuilt from them.

def snapshot_file(endpoint: str) -> Path:
    """Where the snapshot for this endpoint lives (beside the per-film folders)."""
    return config.RAW_DIR / SNAPSHOT_NAMES[endpoint]


def expected_snapshot(endpoint: str, log: dict, now: datetime | None = None) -> dict[int, str]:
    """film id -> fetched_at for every ok fetch-log row of this endpoint that is still inside the 180 days."""
    now = now or datetime.now(UTC)
    wanted = {}
    for (tmdb_id, name), row in log.items():
        if name != endpoint or row["outcome"] != "ok":
            continue
        age = _age_days(row["fetched_at"], now)
        if age is not None and age < config.CACHE_MAX_AGE_DAYS:  # an expired film is left out
            wanted[tmdb_id] = row["fetched_at"]
    return wanted


def snapshot_text(held: dict[int, tuple[str, dict]]) -> str:
    """The text of a snapshot: one compact JSON line per film, in film id order."""
    lines = [
        json.dumps({"tmdb_id": i, "fetched_at": at, "response": body}, ensure_ascii=False, separators=(",", ":"))
        for i, (at, body) in sorted(held.items())
    ]
    return chr(10).join(lines) + (chr(10) if lines else "")


def build_snapshot(endpoint: str, log: dict, now: datetime | None = None) -> dict[int, tuple[str, dict]]:
    """Write the snapshot from the per-film files, to a temp file first, and return what it holds.

    A film whose file is missing, not valid JSON or for another id is left out; the flatten stage then
    reads that film from its own file and quarantines it as before.
    """
    held: dict[int, tuple[str, dict]] = {}
    for tmdb_id, fetched_at in sorted(expected_snapshot(endpoint, log, now).items()):
        path = cache_file(endpoint, tmdb_id)
        try:
            body = json.loads(path.read_bytes())
        except (OSError, ValueError):
            continue
        if isinstance(body, dict) and body.get("id") == tmdb_id:
            held[tmdb_id] = (fetched_at, body)
    target = snapshot_file(endpoint)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(snapshot_text(held).encode("utf-8"))
    os.replace(tmp, target)
    return held


def read_snapshot(endpoint: str) -> dict[int, tuple[str, dict]] | None:
    """What the snapshot holds (film id -> fetched_at, response), or None if it is missing or unreadable."""
    path = snapshot_file(endpoint)
    if not path.is_file():
        return None
    held: dict[int, tuple[str, dict]] = {}
    try:
        for line in path.read_text(encoding="utf-8").split(chr(10)):
            if not line:
                continue
            record = json.loads(line)
            held[int(record["tmdb_id"])] = (record["fetched_at"], record["response"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return held


def snapshot_problem(endpoint: str, held: dict | None, log: dict, now: datetime | None = None) -> str:
    """Why a snapshot cannot be trusted ("" when its ids and fetched_at values match the fetch log)."""
    wanted = expected_snapshot(endpoint, log, now)
    if held is None:
        if not wanted and not snapshot_file(endpoint).exists():
            return ""  # nothing to hold, so no file is needed
        return f"{endpoint} snapshot missing or unreadable"
    have = {i: at for i, (at, _) in held.items()}
    if have == wanted:
        return ""
    extra, absent = len(have.keys() - wanted.keys()), len(wanted.keys() - have.keys())
    changed = sum(1 for i in have.keys() & wanted.keys() if have[i] != wanted[i])
    return f"{endpoint} snapshot differs from the fetch log ({absent} missing, {extra} extra, {changed} changed)"


def build_snapshots(log: dict, now: datetime | None = None) -> None:
    """Rebuild both snapshots; a failure stops the run (check C-34)."""
    try:
        for endpoint in SNAPSHOT_NAMES:
            build_snapshot(endpoint, log, now)
    except OSError as exc:
        raise PipelineStopError(f"Could not write the response snapshots: {exc}", check_id="C-34") from exc


# --- the fetch loop -----------------------------------------------------------

def fetch_all(
    ids: pd.DataFrame,
    session: requests.Session | None = None,
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

    now = datetime.now(UTC)
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
            mtime = datetime.fromtimestamp(file.stat().st_mtime, UTC)
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
                # the credits row depends on the details answer, so it keeps that answer's time: a run
                # that makes no request must not rewrite the log
                skipped = FetchResult(
                    tmdb_id, "credits", endpoint_path("credits", tmdb_id), None,
                    "skipped", None, details.fetched_at, 0.0, "details not found",
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

    started = time.perf_counter()
    missing = any(expected_snapshot(e, log, now) and not snapshot_file(e).is_file() for e in SNAPSHOT_NAMES)
    if state["network_calls"] or missing:  # something changed, or there is no snapshot yet
        build_snapshots(log, now)
    snapshot_build_s = time.perf_counter() - started

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
        extra={"snapshot_build_s": snapshot_build_s},
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
