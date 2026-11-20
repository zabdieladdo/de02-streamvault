"""Tests for the load-stage checks."""
import pandas as pd
import pytest

from pipeline.checks import check_load_stage, raise_if_conservation_failed
from pipeline.errors import PipelineStopError
from pipeline.validate import classify_ids

VALUES = ["155", "", "N/A", "155", "9412887", "-1"]


@pytest.fixture
def stage():
    raw = pd.DataFrame({"line_number": range(2, len(VALUES) + 2), "raw_value": VALUES})
    meta = {"header": "tmdb_id", "raw_line_count": len(VALUES)}
    ids, q = classify_ids(raw)
    return meta, raw, ids, q


def test_all_pass(stage):
    report = check_load_stage(*stage)
    assert list(report["check_id"]) == ["C-01", "C-02", "C-03", "C-04", "C-04b"]
    assert report["passed"].all()
    assert "9412887" in report.loc[report["check_id"] == "C-04b", "detail"].iloc[0]


def test_dropped_row_fails_c02_and_c03_and_stops(stage):
    meta, raw, ids, q = stage
    report = check_load_stage(meta, raw, ids, q.iloc[1:])  # lose a quarantine row
    failed = set(report.loc[~report["passed"], "check_id"])
    assert {"C-02", "C-03"} <= failed
    with pytest.raises(PipelineStopError):
        raise_if_conservation_failed(report)


def test_duplicate_id_fails_c04(stage):
    meta, raw, ids, q = stage
    report = check_load_stage(meta, raw, pd.concat([ids, ids.iloc[[0]]]), q)
    assert not report.loc[report["check_id"] == "C-04", "passed"].iloc[0]


def test_row_count_mismatch_fails_c01(stage):
    meta, raw, ids, q = stage
    report = check_load_stage({**meta, "raw_line_count": 99}, raw, ids, q)
    assert not report.loc[report["check_id"] == "C-01", "passed"].iloc[0]


# --- fetch-stage checks ---------------------------------------------------------
from pipeline import config, fetch  # noqa: E402
from tests.conftest import NOT_FOUND_BODY, FakeResponse, FakeSession  # noqa: E402


def _fetch_run(fetch_env, script=None, n=3):
    ids = pd.DataFrame(
        {
            "tmdb_id": pd.Series([603, 155, 278, 550, 680, 11][:n], dtype="int64"),
            "first_line_number": range(2, n + 2),
        }
    )
    return fetch.fetch_all(ids, session=FakeSession(script), key=fetch_env.key)


def _passed(report):
    return dict(zip(report["check_id"], report["passed"]))


def test_fetch_checks_all_pass(fetch_env):
    from pipeline.checks import check_fetch_stage

    run = _fetch_run(fetch_env, {"/movie/155": FakeResponse(404, NOT_FOUND_BODY)})
    report = check_fetch_stage(run)
    assert list(report["check_id"]) == ["C-05", "C-06", "C-07", "C-08", "C-09", "C-03f", "C-10i"]
    assert report["passed"].all()  # a not-found film is not a failed request


def test_fetch_check_id_mismatch_fails_c07(fetch_env):
    from pipeline.checks import check_fetch_stage
    from tests.conftest import ok_body

    run = _fetch_run(fetch_env, {"/movie/155": FakeResponse(200, ok_body(999))})
    assert not _passed(check_fetch_stage(run))["C-07"]


def test_fetch_check_credits_missing_is_explained(fetch_env):
    from pipeline.checks import check_fetch_stage

    run = _fetch_run(fetch_env, {"/movie/155/credits": FakeResponse(404, NOT_FOUND_BODY)})
    assert _passed(check_fetch_stage(run))["C-08"]


def test_fetch_check_c08_fails_when_details_failed_but_credits_ok(fetch_env):
    from pipeline.checks import check_fetch_stage

    run = _fetch_run(fetch_env, {"/movie/155": FakeResponse(503, b"{}")})
    assert not _passed(check_fetch_stage(run))["C-08"]


def test_fetch_check_incomplete_above_threshold(fetch_env):
    from pipeline.checks import check_fetch_stage

    run = _fetch_run(fetch_env, {"/movie/155": FakeResponse(503, b"{}")})  # 1 of 3 = 33%
    assert not _passed(check_fetch_stage(run))["C-10i"]


def test_fetch_check_conservation_and_stale_cache(fetch_env):
    from pipeline.checks import check_fetch_stage

    run = _fetch_run(fetch_env)
    run.results.loc[0, "cache_age_days"] = config.CACHE_MAX_AGE_DAYS + 1
    assert not _passed(check_fetch_stage(run))["C-09"]
    run.results = run.results.iloc[1:]  # a lost result
    assert not _passed(check_fetch_stage(run))["C-06"]
