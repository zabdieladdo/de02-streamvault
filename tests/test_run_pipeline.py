"""End-to-end tests of stages 1 and 2 against fixture files and a fake session."""
import json
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

import run_pipeline
from pipeline import config
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
        "films_clean": clean.add_flags(films), "films": films, "report": pd.DataFrame(),
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
