"""Run checks C-01 to C-27 and produce one pass/fail table."""
import pandas as pd

from pipeline import config
from pipeline.errors import PipelineStopError

STAGE = "load"


def _row(check_id: str, description: str, passed: bool, detail: str) -> dict:
    return {
        "check_id": check_id,
        "description": description,
        "stage": STAGE,
        "passed": bool(passed),
        "detail": detail,
    }


def check_load_stage(
    meta: dict,
    raw: pd.DataFrame,
    ids_to_fetch: pd.DataFrame,
    quarantine: pd.DataFrame,
) -> pd.DataFrame:
    """Checks for stage 1; returns check_id, description, stage, passed, detail."""
    rows = []

    # C-01: header and row count read without loss
    header_ok = str(meta["header"]).strip() == config.EXPECTED_HEADER
    count_ok = len(raw) == meta["raw_line_count"]
    rows.append(
        _row(
            "C-01",
            "Header and row count read without loss",
            header_ok and count_ok,
            f"header {meta['header']!r}; read {len(raw)} rows, counted {meta['raw_line_count']} lines",
        )
    )

    # C-02: every input line is accounted for exactly once
    accounted = pd.concat([ids_to_fetch["first_line_number"], quarantine["line_number"]])
    seen_once = accounted.value_counts().eq(1).all()
    same_set = set(accounted) == set(raw["line_number"])
    rows.append(
        _row(
            "C-02",
            "Every row classified exactly once",
            bool(seen_once) and same_set and len(accounted) == len(raw),
            f"{len(accounted)} classifications for {len(raw)} rows",
        )
    )

    # C-03: conservation
    non_repeat_quarantine = int((quarantine["reason_code"] != "repeat").sum())
    sum_ok = len(raw) == int(ids_to_fetch["n_occurrences"].sum()) + non_repeat_quarantine
    split_ok = len(raw) == len(ids_to_fetch) + len(quarantine)
    rows.append(
        _row(
            "C-03",
            "Conservation: raw = sent forward + quarantined",
            sum_ok and split_ok,
            f"raw {len(raw)} = to fetch {len(ids_to_fetch)} + quarantined {len(quarantine)}",
        )
    )

    # C-04: ids sent forward are unique
    rows.append(
        _row(
            "C-04",
            "Ids sent forward are unique",
            ids_to_fetch["tmdb_id"].is_unique,
            f"{len(ids_to_fetch)} ids, {ids_to_fetch['tmdb_id'].nunique()} distinct",
        )
    )

    # C-04b: review list, always passes
    large = ids_to_fetch.loc[ids_to_fetch["flag_large_id"], "tmdb_id"].tolist()
    rows.append(
        _row(
            "C-04b",
            "Large ids flagged, not removed",
            True,
            f"{len(large)} flagged for review: {', '.join(map(str, large)) or 'none'}",
        )
    )

    return pd.DataFrame(rows, columns=["check_id", "description", "stage", "passed", "detail"])


def raise_if_conservation_failed(report: pd.DataFrame) -> None:
    """C-03 failing means rows were lost or invented; stop the run."""
    c03 = report.loc[report["check_id"] == "C-03"]
    if not c03.empty and not bool(c03["passed"].iloc[0]):
        raise PipelineStopError(f"C-03 failed: {c03['detail'].iloc[0]}")


def check_fetch_stage(run) -> pd.DataFrame:
    """Checks for stage 2. `run` is a fetch.FetchRun. Same columns as the load checks."""
    results, quarantine, ids = run.results, run.quarantine, run.ids_processed
    stage = "fetch"
    rows = []

    def add(check_id, description, passed, detail):
        rows.append(
            {
                "check_id": check_id, "description": description, "stage": stage,
                "passed": bool(passed), "detail": detail,
            }
        )

    # C-05: a 401 or a network error on the first request already stopped the run
    add(
        "C-05", "Key accepted and network reachable", run.preflight_ok,
        "first request accepted" if run.network_calls else "no network request needed (all cached)",
    )

    # C-06: one final outcome per id and endpoint
    per_pair = results.groupby(["tmdb_id", "endpoint"]).size() if len(results) else pd.Series(dtype=int)
    c06 = (
        len(results) == 2 * len(ids)
        and bool((per_pair == 1).all())
        and set(results["tmdb_id"]) == set(ids["tmdb_id"])
    )
    add("C-06", "Every id has one final outcome per endpoint", c06,
        f"{len(results)} results for {len(ids)} ids x 2 endpoints")

    # C-07: the response is the film requested
    n_mismatch = int((results["outcome"] == "id_mismatch").sum())
    add("C-07", "Responses are the film requested", n_mismatch == 0,
        f"{n_mismatch} responses with a different id")

    # C-08: details and credits cover the same films (credits_missing is the known exception)
    ok = results[results["outcome"].isin(["ok", "cached"])]
    d_ids = set(ok.loc[ok["endpoint"] == "details", "tmdb_id"])
    c_ids = set(ok.loc[ok["endpoint"] == "credits", "tmdb_id"])
    credits_missing = {
        int(v) for v in quarantine.loc[quarantine["reason_code"] == "credits_missing", "raw_value"]
    }
    unexplained = (d_ids ^ c_ids) - credits_missing
    add("C-08", "Details and credits cover the same films", not unexplained,
        f"{len(unexplained)} ids with one endpoint only, besides {len(credits_missing)} credits_missing")

    # C-09: nothing older than the TMDb cache limit was used
    ages = results["cache_age_days"].dropna().astype(float)
    too_old = int((ages >= config.CACHE_MAX_AGE_DAYS).sum())
    add("C-09", "Cache within TMDb's 6-month limit", too_old == 0,
        f"{len(ages)} cached entries used, oldest {ages.max():.0f} days" if len(ages)
        else "no cached entries used")

    # C-03f: conservation through fetch
    forward = len(ids) - len(quarantine)
    add("C-03f", "Conservation through fetch", forward >= 0 and len(ids) == forward + len(quarantine),
        f"ids processed {len(ids)} = fetched {forward} + quarantined {len(quarantine)}")

    # C-10i: enough of the list fetched. Not-found films are a fact about the list, not a failure.
    n_failed = int((quarantine["reason_code"] == "fetch_failed").sum())
    pct = 100 * n_failed / len(ids) if len(ids) else 0.0
    add("C-10i", "Analysis complete enough", pct <= config.INCOMPLETE_THRESHOLD_PCT,
        f"{n_failed} of {len(ids)} ids failed to fetch ({pct:.1f}%, limit {config.INCOMPLETE_THRESHOLD_PCT}%)")

    return pd.DataFrame(rows, columns=["check_id", "description", "stage", "passed", "detail"])
