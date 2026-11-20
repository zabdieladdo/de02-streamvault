"""End-to-end tests of stages 1 and 2 against fixture files and a fake session."""
import json
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

import run_pipeline
from pipeline import config
from pipeline.errors import PipelineStopError
from tests.conftest import NOT_FOUND_BODY, TEST_KEY, FakeResponse, FakeSession

IDS = ["155", "", "N/A", "155", "9412887", "-1", "tt0468569", "603"]


@pytest.fixture
def env(write_ids, fetch_env, monkeypatch):
    monkeypatch.setattr(config, "INPUT_IDS", write_ids(IDS))
    monkeypatch.setattr(config, "OUT_DIR", fetch_env.tmp_path / "out")
    monkeypatch.setattr(config, "LIMITED_OUT_DIR", fetch_env.tmp_path / "out" / "limited")
    return fetch_env


def fake():
    return FakeSession({"/movie/9412887": FakeResponse(404, NOT_FOUND_BODY)})


def test_main_end_to_end(env, capsys):
    session = fake()
    assert run_pipeline.main([], session=session) == 0
    out = env.tmp_path / "out"

    for name in (
        "ids_to_fetch.csv", "fetched_ids.csv", "quarantine.csv",
        "reconciliation.csv", "checks_report.csv", "run_log.jsonl",
        "films.csv", "talent.csv", "join_report.csv", "films_profile.csv",
    ):
        assert (out / name).is_file(), name
    lines = (out / "run_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["rows_raw"] == 8
    assert record["ids_to_fetch"] == 3
    assert record["fetch_network_calls"] == 5  # 155 x2, 603 x2, 9412887 details only
    assert record["ids_fetched"] == 2
    assert record["checks_failed"] == 0
    assert record["films_rows"] == 2 and record["talent_rows"] == 0
    assert record["analysis_incomplete"] is False
    assert record["stopped"] is None

    recon = pd.read_csv(out / "reconciliation.csv")
    assert recon["rows"].iloc[0] == 8
    assert recon["stage"].iloc[-1].startswith("Films with a usable revenue")
    assert recon["stage"].iloc[-2] == "In the analysis table (one row per film)"
    assert "Fetched with details and credits" in set(recon["stage"])
    assert recon["rows"].iloc[-2] == 2
    assert record["roi_usable"] == 0 and "windows_disagree" in record
    assert {"clean", "measure"} <= set(record["seconds"])
    sent = recon[recon["stage"] == "Sent to the API stage"]["rows"].iloc[0]
    assert sent == 3
    assert "Quarantined: not_found_on_api" in set(recon["stage"])

    q = pd.read_csv(out / "quarantine.csv", dtype=str)
    assert set(q["stage"]) == {"load", "fetch"}
    assert q["line_number"].astype(int).is_monotonic_increasing
    assert len(q) + len(pd.read_csv(out / "fetched_ids.csv")) == 8

    text = capsys.readouterr().out
    assert "Stage 2: fetch details and credits" in text
    assert "Stage 3: flatten and join" in text
    assert "Stage 4: clean and flag" in text and "Stage 5: measures" in text
    assert TEST_KEY not in text


def test_second_run_makes_no_requests(env):
    run_pipeline.main([], session=fake())
    second = FakeSession()
    assert run_pipeline.main([], session=second) == 0
    assert second.calls == []
    log = [json.loads(x) for x in (env.tmp_path / "out" / "run_log.jsonl").read_text().splitlines()]
    assert log[-1]["fetch_network_calls"] == 0 and log[-1]["fetch_cached"] > 0


def test_fully_cached_run_works_without_key(env, monkeypatch):
    run_pipeline.main([], session=fake())
    monkeypatch.delenv("TMDB_API_KEY")
    second = FakeSession()
    assert run_pipeline.main([], session=second) == 0
    assert second.calls == []


def test_limit_run_is_marked(env, capsys):
    session = FakeSession()
    assert run_pipeline.main(["--limit", "1"], session=session) == 0
    assert set(session.calls) == {"/movie/155", "/movie/155/credits"}
    text = capsys.readouterr().out
    assert "LIMITED RUN" in text
    last = text.rstrip().splitlines()[-1]
    assert last.startswith("Outputs written to ") and "limited" in last
    assert last.endswith("(LIMITED RUN; full results in " + last.split("full results in ")[1])
    assert last.endswith("/ unchanged)")
    recon = pd.read_csv(env.tmp_path / "out" / "limited" / "reconciliation.csv")
    assert "Not processed (limited run)" in set(recon["stage"])
    assert recon["rows"].iloc[-2] == 1


def test_refresh_requests_again(env):
    run_pipeline.main([], session=fake())
    second = fake()
    assert run_pipeline.main(["--refresh"], session=second) == 0
    assert len(second.calls) == 5


def test_stop_on_401_returns_1_and_logs(env, capsys):
    session = FakeSession({"/movie/155": FakeResponse(401, b"{}")})
    assert run_pipeline.main([], session=session) == 1
    text = capsys.readouterr().out
    assert "STOPPED" in text and "401" in text
    record = json.loads((env.tmp_path / "out" / "run_log.jsonl").read_text().splitlines()[-1])
    assert "401" in record["stopped"]


def test_key_not_in_any_output(env, capsys):
    err = requests.ConnectionError(f"failed: {config.API_BASE}/movie/603?api_key={TEST_KEY}")
    session = FakeSession({"/movie/603": err})
    run_pipeline.main([], session=session)
    shown = capsys.readouterr()
    assert TEST_KEY not in shown.out + shown.err
    for path in env.tmp_path.rglob("*"):
        if path.is_file():
            assert TEST_KEY.encode() not in path.read_bytes(), path


def test_main_returns_1_on_bad_header(write_ids, fetch_env, monkeypatch, capsys):
    monkeypatch.setattr(config, "INPUT_IDS", write_ids(["155"], header="id"))
    monkeypatch.setattr(config, "OUT_DIR", fetch_env.tmp_path / "out")
    assert run_pipeline.main([]) == 1
    assert "STOPPED" in capsys.readouterr().out


CSV_OUTPUTS = (
    "ids_to_fetch.csv", "fetched_ids.csv", "quarantine.csv", "reconciliation.csv", "checks_report.csv",
    "films.csv", "talent.csv", "join_report.csv", "films_profile.csv",
    "films_clean.csv", "review_list.csv", "kpis.csv", "window_comparison.csv", "decision_impact.csv",
    "bundles.csv", "entry_positions.csv", "middle_entry_test.csv", "talent_signal.csv", "shortlist.csv",
    "deal_note.csv", "window_differences.csv",
)


def test_limited_run_leaves_full_outputs_alone(env):
    out = env.tmp_path / "out"
    run_pipeline.main([], session=fake())
    before = {p.name: p.read_bytes() for p in out.glob("*.csv")}
    assert set(before) == set(CSV_OUTPUTS)
    run_pipeline.main(["--limit", "1"], session=FakeSession())
    after = {p.name: p.read_bytes() for p in out.glob("*.csv")}
    assert after == before


def test_limited_run_writes_its_own_outputs(env):
    run_pipeline.main([], session=fake())
    run_pipeline.main(["--limit", "1"], session=FakeSession())
    limited = env.tmp_path / "out" / "limited"
    assert {p.name for p in limited.glob("*.csv")} == set(CSV_OUTPUTS)
    recon = pd.read_csv(limited / "reconciliation.csv")
    assert recon["rows"].iloc[-2] == 1  # one id fetched


def test_run_log_records_both_runs_and_output_dir(env):
    run_pipeline.main([], session=fake())
    run_pipeline.main(["--limit", "1"], session=FakeSession())
    lines = (env.tmp_path / "out" / "run_log.jsonl").read_text(encoding="utf-8").splitlines()
    full, limited = (json.loads(x) for x in lines)
    assert full["limit"] is None and full["output_dir"] == str(env.tmp_path / "out")
    assert limited["limit"] == 1 and limited["output_dir"].endswith("limited")


KPI_FILES = ("kpis.csv", "window_comparison.csv", "decision_impact.csv", "films_clean.csv", "review_list.csv")


def test_stages_4_and_5_write_identical_files_on_a_second_run(env):
    out = env.tmp_path / "out"
    run_pipeline.main([], session=fake())
    first = {n: (out / n).read_bytes() for n in KPI_FILES}
    assert run_pipeline.main([], session=FakeSession()) == 0
    assert {n: (out / n).read_bytes() for n in KPI_FILES} == first
    checks = pd.read_csv(out / "checks_report.csv").set_index("check_id")
    assert checks.loc["C-25", "passed"]


def test_new_outputs_have_the_expected_shape(env):
    from pipeline import load
    run_pipeline.main([], session=fake())
    out = env.tmp_path / "out"
    films = load.read_films_clean(out / "films_clean.csv")
    assert len(films) == len(load.read_films(out / "films.csv"))  # no row leaves at stage 4
    kpis = pd.read_csv(out / "kpis.csv")
    assert len(kpis) == 4 and set(kpis["window"]) == {"all years", "2000 onward"}
    impact = pd.read_csv(out / "decision_impact.csv")
    assert len(impact) == 2 * 10


def test_windows_disagree_prints_a_banner_and_the_run_continues(capsys, tmp_path):
    from pipeline import clean
    from tests.conftest import make_films
    rows = [{"year": 1990, "franchise": True, "budget": 1_000_000, "revenue": 10_000_000}] * 2 + [
        {"year": 2005, "franchise": True, "budget": 1_000_000, "revenue": 2_000_000},
        {"year": 2006, "franchise": False, "budget": 1_000_000, "revenue": 5_000_000},
    ]
    films = make_films(rows).assign(imdb_id=pd.Series(pd.NA, dtype="string"))
    stage4 = {
        "films_clean": clean.add_flags(films), "films": films, "report": pd.DataFrame(), "talent": pd.DataFrame(),
        "quarantine": pd.DataFrame({"stage": [], "reason_code": [], "raw_value": []}),
    }
    record = {"seconds": {"clean": 0.0}, "checks_passed": 0, "checks_failed": 0}
    run_pipeline._stage5(stage4, SimpleNamespace(limit=None), record, tmp_path)  # does not raise
    text = capsys.readouterr().out
    assert "WINDOWS DISAGREE: median_roi" in text
    assert record["windows_disagree"] is True and "median_roi" in record["windows_disagree_measures"]


# --- integrity checks stop the run, after the outputs are written ------------------

def _stops_on(env, capsys, check_id, written):
    """Run main(); it must stop with code 1, name the check, and have written the outputs."""
    assert run_pipeline.main([], session=fake()) == 1
    text = capsys.readouterr().out
    assert "STOPPED" in text and f"{check_id} failed" in text
    out = env.tmp_path / "out"
    for name in written:
        assert (out / name).is_file(), name
    report = pd.read_csv(out / "checks_report.csv").set_index("check_id")
    assert not report.loc[check_id, "passed"]
    record = json.loads((out / "run_log.jsonl").read_text().splitlines()[-1])
    assert check_id in record["stopped"]


STAGE4_FILES = ("films_clean.csv", "review_list.csv", "checks_report.csv")
STAGE5_FILES = STAGE4_FILES + ("kpis.csv", "window_comparison.csv", "decision_impact.csv")


def test_c_roi_failure_stops_the_run(env, capsys, monkeypatch):
    real = run_pipeline.clean.add_flags

    def broken(films):
        out = real(films)
        out["roi"] = 3.0  # a multiple on rows where roi_usable is False
        return out

    monkeypatch.setattr(run_pipeline.clean, "add_flags", broken)
    _stops_on(env, capsys, "C-ROI", STAGE4_FILES)
    assert not (env.tmp_path / "out" / "kpis.csv").exists()  # stage 5 never ran


def test_infinite_multiple_also_fails_c_roi(env, capsys, monkeypatch):
    real = run_pipeline.clean.add_flags

    def broken(films):
        out = real(films)
        out["roi_usable"] = True
        out["roi"] = float("inf")
        return out

    monkeypatch.setattr(run_pipeline.clean, "add_flags", broken)
    _stops_on(env, capsys, "C-ROI", STAGE4_FILES)


def _patch_kpis(monkeypatch, change):
    real = run_pipeline.metrics.window_kpis
    calls = {"n": 0}

    def patched(films):
        a, b = real(films)
        calls["n"] += 1
        return change(a, b, calls["n"])

    monkeypatch.setattr(run_pipeline.metrics, "window_kpis", patched)


def test_c22_failure_stops_the_run(env, capsys, monkeypatch):
    _patch_kpis(monkeypatch, lambda a, b, n: (a.assign(n_films=a["n_films"] + 1), b))
    _stops_on(env, capsys, "C-22", STAGE5_FILES)


def test_c23_failure_stops_the_run(env, capsys, monkeypatch):
    _patch_kpis(monkeypatch, lambda a, b, n: (a, b.assign(n_films=b["n_films"] + 5)))
    _stops_on(env, capsys, "C-23", STAGE5_FILES)


def test_c25_failure_stops_the_run(env, capsys, monkeypatch):
    def second_call_differs(a, b, n):
        return (a, b) if n == 1 else (a.assign(n_roi_usable=a["n_roi_usable"] + 1), b)

    _patch_kpis(monkeypatch, second_call_differs)
    _stops_on(env, capsys, "C-25", STAGE5_FILES)


def test_failing_c18_does_not_stop_the_run(env, capsys, monkeypatch):
    real = run_pipeline.checks.check_clean_stage

    def failing_c18(*args, **kwargs):
        report = real(*args, **kwargs)
        report.loc[report["check_id"] == "C-18", "passed"] = False
        return report

    monkeypatch.setattr(run_pipeline.checks, "check_clean_stage", failing_c18)
    assert run_pipeline.main([], session=fake()) == 0
    out = env.tmp_path / "out"
    report = pd.read_csv(out / "checks_report.csv").set_index("check_id")
    assert not report.loc["C-18", "passed"]  # recorded
    assert (out / "kpis.csv").is_file()  # stage 5 still ran
    assert "STOPPED" not in capsys.readouterr().out


# --- conservation through fetch and flatten stops the run ----------------------------

def test_c03f_failure_stops_the_run(env, capsys, monkeypatch):
    real = run_pipeline.fetch.fetch_all

    def losing_rows(*args, **kwargs):
        run = real(*args, **kwargs)
        extra = run.quarantine.iloc[[0, 0, 0]]  # more quarantined rows than ids processed
        run.quarantine = pd.concat([run.quarantine, extra], ignore_index=True)
        return run

    monkeypatch.setattr(run_pipeline.fetch, "fetch_all", losing_rows)
    _stops_on(env, capsys, "C-03f", ("fetched_ids.csv", "quarantine.csv", "reconciliation.csv"))
    assert not (env.tmp_path / "out" / "films.csv").exists()  # flatten never ran


def test_c03g_failure_stops_the_run(env, capsys, monkeypatch):
    real = run_pipeline.transform.flatten_stage

    def losing_a_film(*args, **kwargs):
        run = real(*args, **kwargs)
        run.films = run.films.iloc[1:]  # a film vanishes after the join
        return run

    monkeypatch.setattr(run_pipeline.transform, "flatten_stage", losing_a_film)
    _stops_on(env, capsys, "C-03g", ("films.csv", "talent.csv", "quarantine.csv", "reconciliation.csv"))
    assert not (env.tmp_path / "out" / "films_clean.csv").exists()  # stage 4 never ran


# --- no stale outputs, and a status line for every run ------------------------------

def _break_c_roi(monkeypatch):
    real = run_pipeline.clean.add_flags

    def broken(films):
        out = real(films)
        out["roi"] = 3.0
        return out

    monkeypatch.setattr(run_pipeline.clean, "add_flags", broken)


def test_successful_run_writes_complete_status(env):
    assert run_pipeline.main([], session=fake()) == 0
    text = (env.tmp_path / "out" / "run_status.txt").read_text(encoding="utf-8")
    assert text.startswith("complete 20") and text.count("\n") == 1


def test_stopped_run_leaves_no_stale_outputs(env, monkeypatch, capsys):
    out = env.tmp_path / "out"
    assert run_pipeline.main([], session=fake()) == 0
    assert (out / "kpis.csv").is_file()  # from the earlier, successful run

    _break_c_roi(monkeypatch)
    assert run_pipeline.main([], session=FakeSession()) == 1
    assert not (out / "kpis.csv").exists()
    assert not (out / "decision_impact.csv").exists()
    assert (out / "films_clean.csv").is_file()  # written by this run before it stopped
    status = (out / "run_status.txt").read_text(encoding="utf-8")
    assert status.startswith("stopped at C-ROI, stage 4, 20")
    assert len((out / "run_log.jsonl").read_text().splitlines()) == 2  # the log is kept


def test_stop_without_a_check_still_writes_a_status(write_ids, fetch_env, monkeypatch):
    monkeypatch.setattr(config, "INPUT_IDS", write_ids(["155"], header="id"))
    monkeypatch.setattr(config, "OUT_DIR", fetch_env.tmp_path / "out")
    assert run_pipeline.main([]) == 1
    status = (fetch_env.tmp_path / "out" / "run_status.txt").read_text(encoding="utf-8")
    assert status.startswith("stopped at an error") and ", stage 1, " in status


def test_limited_run_clears_only_its_own_folder(env):
    out = env.tmp_path / "out"
    run_pipeline.main([], session=fake())
    run_pipeline.main(["--limit", "1"], session=FakeSession())
    (out / "limited" / "old.csv").write_text("stale", encoding="utf-8")
    full = {p.name: p.read_bytes() for p in out.glob("*.csv")}
    run_pipeline.main(["--limit", "1"], session=FakeSession())
    assert not (out / "limited" / "old.csv").exists()
    assert {p.name: p.read_bytes() for p in out.glob("*.csv")} == full
    assert (out / "run_status.txt").read_text().startswith("complete")
    assert (out / "limited" / "run_status.txt").read_text().startswith("complete")


def test_full_run_keeps_the_limited_folder(env):
    out = env.tmp_path / "out"
    run_pipeline.main(["--limit", "1"], session=FakeSession())
    marker = {p.name: p.read_bytes() for p in (out / "limited").glob("*")}
    run_pipeline.main([], session=fake())
    assert {p.name for p in (out / "limited").glob("*")} == set(marker)


def test_c21_failure_stops_the_run(env, capsys, monkeypatch):
    real = run_pipeline.metrics.window_kpis

    def missing_group_size(films):
        a, b = real(films)
        a = a.astype({"n_films": "float64"})
        a.loc[0, "n_films"] = float("nan")  # a measure row without its group size
        return a, b

    monkeypatch.setattr(run_pipeline.metrics, "window_kpis", missing_group_size)
    _stops_on(env, capsys, "C-21", STAGE5_FILES)
    status = (env.tmp_path / "out" / "run_status.txt").read_text(encoding="utf-8")
    assert status.startswith("stopped at C-21, stage 5, ")


# --- stage 6: rank and recommend ----------------------------------------------------

def _stage5_tables(tmp_path):
    """Everything stage 6 reads, built from the hand-written shortlist fixture."""
    from pipeline import metrics
    from tests.conftest import make_talent
    from tests.test_rank import shortlist_fixture

    f = shortlist_fixture()
    talent = make_talent([(1, 7, "Ann", "director"), (2, 7, "Ann", "director"), (3, 7, "Ann", "director"),
                          (101, 8, "Bob", "lead_actor")])
    kpis = pd.concat(metrics.window_kpis(f), ignore_index=True)
    return {"films_clean": f, "kpis": kpis, "report": pd.DataFrame(), "talent": talent}


def test_stage6_summary_and_outputs(tmp_path, capsys):
    record = {"seconds": {}, "checks_passed": 0, "checks_failed": 0}
    run_pipeline._stage6(_stage5_tables(tmp_path), record, tmp_path)
    text = capsys.readouterr().out
    assert "Stage 6: rank and recommend" in text
    assert "franchise: Collection 1, Collection 2, Collection 3" in text
    assert "standalone: S0, S1, S2, S3, S4" in text and "audience pick: S7" in text
    assert "NO ROBUST CANDIDATE" in text  # these bundles have only two films from 2000
    assert "SHORTLIST SHORT (all years)" not in text and "note: openers are selected winners" in text
    for name in ("bundles.csv", "entry_positions.csv", "middle_entry_test.csv", "talent_signal.csv",
                 "shortlist.csv", "deal_note.csv", "window_differences.csv", "checks_report.csv"):
        assert (tmp_path / name).is_file(), name
    assert record["shortlist_sizes"]["all years"] == {"franchise": 3, "standalone": 5, "audience pick": 1}
    assert set(record["shortlist_sizes"]) == {"all years", "2000 onward"}
    assert isinstance(record["shortlist_differs_between_windows"], list)
    assert record["strongest_bundle"] is None and record["no_robust_candidate"] is True
    assert record["deal_note_candidates"] == {"all-years leader": "Collection 1"}
    assert record["bundles_rankable"] == 4
    assert {"list_median_roi", "list_median_votes", "bundles_tested_middle", "talent_reliable",
            "relative_value"} <= set(record)
    assert "rank" in record["seconds"]


def test_short_shortlist_is_announced_and_the_run_continues(env, capsys):
    assert run_pipeline.main([], session=fake()) == 0  # these fixture films have no money: nothing to rank
    text = capsys.readouterr().out
    assert "SHORTLIST SHORT (all years): 0 of 3 franchise" in text
    assert "SHORTLIST SHORT (2000 onward): 0 of 5 standalone" in text
    assert text.rstrip().splitlines()[-1].startswith("Outputs written to ")
    out = env.tmp_path / "out"
    assert (out / "shortlist.csv").is_file() and (out / "deal_note.csv").is_file()
    assert (out / "run_status.txt").read_text().startswith("complete")


def test_c29_stops_stage6_after_writing_outputs_when_a_film_id_repeats(tmp_path):
    tables = _stage5_tables(tmp_path)
    f = tables["films_clean"]
    tables["films_clean"] = pd.concat([f, f.iloc[[0]]], ignore_index=True)  # a film id twice
    record = {"seconds": {}, "checks_passed": 0, "checks_failed": 0}
    with pytest.raises(PipelineStopError, match="C-29 failed"):
        run_pipeline._stage6(tables, record, tmp_path)
    for name in ("bundles.csv", "talent_signal.csv", "shortlist.csv", "checks_report.csv"):
        assert (tmp_path / name).is_file(), name  # outputs were written first
    report = pd.read_csv(tmp_path / "checks_report.csv").set_index("check_id")
    assert not report.loc["C-29", "passed"]


def test_c29_stop_reaches_the_exit_code_and_status(env, capsys, monkeypatch):
    monkeypatch.setattr(run_pipeline.rank, "talent_join_rows", lambda talent, films: (len(talent) + 1, False))
    _stops_on(env, capsys, "C-29", ("bundles.csv", "talent_signal.csv", "shortlist.csv", "checks_report.csv"))
    status = (env.tmp_path / "out" / "run_status.txt").read_text(encoding="utf-8")
    assert status.startswith("stopped at C-29, stage 6, ")


def test_stage6_prints_the_two_windows_and_where_they_differ(tmp_path, capsys):
    from pipeline import metrics
    from tests.conftest import make_talent
    from tests.test_rank import window_fixture

    f = window_fixture()
    tables = {"films_clean": f, "kpis": pd.concat(metrics.window_kpis(f), ignore_index=True),
              "report": pd.DataFrame(), "talent": make_talent([(100, 1, "A", "director")])}
    record = {"seconds": {}, "checks_passed": 0, "checks_failed": 0}
    run_pipeline._stage6(tables, record, tmp_path)  # a difference is reported, not raised
    text = capsys.readouterr().out
    assert "all years: franchise: Collection 1, Collection 2" in text
    assert "2000 onward: franchise: Collection 2, Collection 1" in text
    lines = text.splitlines()
    assert "  SHORTLIST DIFFERS BETWEEN WINDOWS: franchise, standalone" in lines  # on its own line
    assert record["shortlist_differs_between_windows"] == ["franchise", "standalone"]
    diff = pd.read_csv(tmp_path / "window_differences.csv")
    assert dict(zip(diff["list"], diff["same"])) == {"franchise": False, "standalone": False, "audience pick": True}
    sl = pd.read_csv(tmp_path / "shortlist.csv")
    assert set(sl["window"]) == {"all years", "2000 onward"}


def test_stage6_says_nothing_when_the_windows_agree(tmp_path, capsys):
    from pipeline import metrics
    from tests.conftest import make_talent
    from tests.test_rank import bundle_rows, flagged, money

    rows = bundle_rows(1, [2, 3, 4], years=[2001, 2004, 2008]) + [
        {"tmdb_id": 50 + i, "title": f"s{i}", "year": 2010 + i, "votes": 100 + i, **money(9 - i)} for i in range(7)]
    f = flagged(rows)
    tables = {"films_clean": f, "kpis": pd.concat(metrics.window_kpis(f), ignore_index=True),
              "report": pd.DataFrame(), "talent": make_talent([(1, 1, "A", "director")])}
    record = {"seconds": {}, "checks_passed": 0, "checks_failed": 0}
    run_pipeline._stage6(tables, record, tmp_path)
    assert "SHORTLIST DIFFERS" not in capsys.readouterr().out
    assert record["shortlist_differs_between_windows"] == []


def _window_tables():
    from pipeline import metrics
    from tests.conftest import make_talent
    from tests.test_rank import window_fixture

    f = window_fixture()
    return {"films_clean": f, "kpis": pd.concat(metrics.window_kpis(f), ignore_index=True),
            "report": pd.DataFrame(), "talent": make_talent([(100, 1, "A", "director")])}


def test_stage6_names_the_robust_candidate_and_the_window_leaders(tmp_path, capsys):
    record = {"seconds": {}, "checks_passed": 0, "checks_failed": 0}
    run_pipeline._stage6(_window_tables(), record, tmp_path)
    text = capsys.readouterr().out
    assert "deal note     robust candidate Collection 2:" in text
    assert "ranks 2 all years, 1 from 2000" in text
    assert "window leaders: all-years leader: Collection 1 | 2000-onward leader: Collection 2" in text
    assert "NO ROBUST CANDIDATE" not in text
    assert record["strongest_bundle"] == "Collection 2" and record["no_robust_candidate"] is False
    assert record["deal_note_candidates"] == {
        "all-years leader": "Collection 1", "2000-onward leader": "Collection 2", "robust candidate": "Collection 2"}
    deal = pd.read_csv(tmp_path / "deal_note.csv")
    assert list(deal["candidate"]) == ["all-years leader", "2000-onward leader", "robust candidate"]
    assert {"bundle_rank", "bundle_rank_2000_on", "rankable_2000_on"} <= set(deal.columns)


def test_stage6_continues_when_there_is_no_robust_candidate(tmp_path, capsys):
    tables = _window_tables()
    f = tables["films_clean"]
    cid = f["collection_id"]
    later = cid.eq(1).fillna(False) & (f["release_year"] > 2003).fillna(False)
    tables["films_clean"] = f[~cid.eq(2).fillna(False) & ~later]  # bundle 1 keeps one film from 2000
    record = {"seconds": {}, "checks_passed": 0, "checks_failed": 0}
    run_pipeline._stage6(tables, record, tmp_path)  # does not raise: no robust candidate is not an error
    lines = capsys.readouterr().out.splitlines()
    assert "  NO ROBUST CANDIDATE" in lines
    assert record["no_robust_candidate"] is True and record["strongest_bundle"] is None


def test_c33_stops_the_run_after_writing_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(run_pipeline.rank, "robust_candidate", lambda bundles: bundles.iloc[0:0])
    with pytest.raises(PipelineStopError, match="C-33 failed"):
        run_pipeline._stage6(_window_tables(), {"seconds": {}, "checks_passed": 0, "checks_failed": 0}, tmp_path)
    assert (tmp_path / "deal_note.csv").is_file() and (tmp_path / "bundles.csv").is_file()


def test_a_repeated_film_id_stops_stage_5_naming_c10(env, capsys, monkeypatch):
    real = run_pipeline.clean.add_flags

    def repeated_film(films):
        out = real(films)
        return pd.concat([out, out.iloc[[0]]], ignore_index=True)

    monkeypatch.setattr(run_pipeline.clean, "add_flags", repeated_film)
    assert run_pipeline.main([], session=fake()) == 1  # a clean stop, not a raw MergeError
    text = capsys.readouterr().out
    assert "STOPPED: C-10 failed" in text and "MergeError" not in text
    out = env.tmp_path / "out"
    assert (out / "films_clean.csv").is_file()  # stage 4 finished and wrote its outputs
    assert not (out / "kpis.csv").exists()  # the stage 5 tables were never built
    assert (out / "run_status.txt").read_text(encoding="utf-8").startswith("stopped at C-10, stage 5, ")
    record = json.loads((out / "run_log.jsonl").read_text().splitlines()[-1])
    assert "C-10" in record["stopped"]


def test_stage6_prints_both_reference_medians_and_the_standalone_picks_above_them(tmp_path, capsys):
    record = {"seconds": {}, "checks_passed": 0, "checks_failed": 0}
    run_pipeline._stage6(_window_tables(), record, tmp_path)
    text = capsys.readouterr().out
    ref = run_pipeline.rank.reference_values(_window_tables()["films_clean"])
    assert f"list median multiple {ref['list_median_roi']:.2f}×" in text
    assert f"from 2000 onward: {ref['list_median_roi_2000_on']:.2f}× ({ref['n_usable_2000_on']} films)" in text
    line = next(x for x in text.splitlines() if "standalone picks above list median" in x)
    assert line.startswith("  standalone picks above list median: all years ") and "| 2000 onward " in line
    assert record["list_median_roi_2000_on"] == round(ref["list_median_roi_2000_on"], 4)
    assert record["list_median_votes_2000_on"] == ref["list_median_votes_2000_on"]
    assert set(record["standalone_picks_above_list_median"]) == {"all years", "2000 onward"}
    k, n = record["standalone_picks_above_list_median"]["2000 onward"]
    assert n == 5 and 0 <= k <= n
