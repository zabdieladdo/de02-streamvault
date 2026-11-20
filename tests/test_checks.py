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


# --- stage 6 checks -----------------------------------------------------------------

def _rank_tables():
    from pipeline import metrics, rank
    from tests.conftest import make_talent
    from tests.test_rank import shortlist_fixture

    f = shortlist_fixture()
    ref = rank.reference_values(f)
    bundles = rank.build_bundles(f)
    ep, _ = rank.middle_entry_test(f, bundles)
    talent = make_talent([(1, 7, "Ann", "director"), (2, 7, "Ann", "director"), (3, 7, "Ann", "director")])
    signal = rank.talent_signal(talent, f, ref["list_median_roi"], ref["list_median_votes"])
    shortlist = rank.build_shortlist(bundles, f)
    kpis = pd.concat(metrics.window_kpis(f), ignore_index=True)
    deal = rank.deal_note_figures(bundles, kpis, ref["list_median_roi"])
    return dict(bundles=bundles, films_clean=f, entry_positions=ep, signal=signal, shortlist=shortlist,
                deal_note=deal, talent=talent, ref=ref)


def _rank_report(**changes):
    from pipeline import checks as c

    tables = {**_rank_tables(), **changes}
    return c.check_rank_stage(**tables).set_index("check_id")


def test_rank_checks_pass_on_good_input():
    report = _rank_report()
    assert list(report.index) == ["C-26", "C-28", "C-29", "C-30", "C-31", "C-32"]
    assert report["passed"].all()
    assert "3 franchise, 5 standalone, 1 audience pick" in report.loc["C-26", "detail"]


def test_c26_fails_when_a_shortlisted_bundle_is_too_small():
    t = _rank_tables()
    small = t["bundles"].assign(n_roi_usable=2)
    assert not _rank_report(bundles=small).loc["C-26", "passed"]


def test_c28_fails_when_a_bundle_is_missing():
    t = _rank_tables()
    assert not _rank_report(bundles=t["bundles"].iloc[1:]).loc["C-28", "passed"]


def test_c29_fails_on_a_repeated_film_id():
    t = _rank_tables()
    doubled = pd.concat([t["films_clean"], t["films_clean"].iloc[[0]]], ignore_index=True)
    assert not _rank_report(films_clean=doubled).loc["C-29", "passed"]


def test_c30_fails_when_an_opener_or_a_film_is_missing():
    t = _rank_tables()
    ep = t["entry_positions"]
    assert not _rank_report(entry_positions=ep[ep["position"] != "opener"]).loc["C-30", "passed"]
    assert not _rank_report(entry_positions=ep.iloc[1:]).loc["C-30", "passed"]


def test_c31_fails_when_a_ratio_is_wrong():
    t = _rank_tables()
    assert not _rank_report(bundles=t["bundles"].assign(relative_value=99.0)).loc["C-31", "passed"]
    assert not _rank_report(deal_note=t["deal_note"].assign(walkaway_ratio=0.0)).loc["C-31", "passed"]


def test_c32_fails_when_a_reliable_person_has_too_few_titles():
    t = _rank_tables()
    forged = t["signal"].assign(signal="reliable", n_titles=2, titles_above=2)
    assert not _rank_report(signal=forged).loc["C-32", "passed"]


def test_only_the_integrity_checks_stop_the_run():
    from pipeline import checks as c

    report = _rank_report().reset_index()
    report.loc[:, "passed"] = False
    for check_id in ("C-26", "C-32"):  # recorded, run continues
        c.raise_if_integrity_failed(report[report["check_id"] == check_id], "rank")
    for check_id in ("C-28", "C-29", "C-30", "C-31"):
        with pytest.raises(PipelineStopError, match=check_id):
            c.raise_if_integrity_failed(report[report["check_id"] == check_id], "rank")
