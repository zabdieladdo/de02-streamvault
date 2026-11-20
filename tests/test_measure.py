"""Measurement: the percentile method, the warm runs, and that nothing real is touched."""
import hashlib
import shutil
from pathlib import Path

import pandas as pd
import pytest

import measure
from pipeline import config, measurement

REPO = Path(config.REPO_ROOT)


def tree_hash(root: Path, pattern: str = "**/*") -> dict:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.glob(pattern)) if p.is_file()
    }


# --- the percentile method ---------------------------------------------------------------------------

def test_median_and_p95_of_ten_known_times_use_linear_interpolation():
    times = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert measurement.percentile(times, 50) == 5.5
    assert measurement.percentile(times, 95) == pytest.approx(9.55)  # 9 + 0.55 * (10 - 9)
    assert measurement.percentile(times, 100) == 10 and measurement.percentile(times, 0) == 1


def test_percentile_does_not_depend_on_the_order_of_the_times():
    assert measurement.percentile([9, 1, 5, 3, 7], 50) == 5


def test_a_single_time_is_its_own_median_and_p95():
    assert measurement.percentile([2.5], 50) == measurement.percentile([2.5], 95) == 2.5


def runs_frame():
    rows = []
    for number, wall in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], start=1):
        rows.append({"scenario": "s", "size": 127, "run": number, "state": "warm", "wall_s": float(wall),
                     **{k: wall / 10 for k in measurement.STAGE_KEYS}, "stage_sum_s": wall * 0.6})
    rows.append({"scenario": "s", "size": 127, "run": 1, "state": "cold", "wall_s": 20.0,
                 **{k: 1.0 for k in measurement.STAGE_KEYS}, "stage_sum_s": 6.0})
    return pd.DataFrame(rows, columns=measurement.TIMING_COLUMNS)


def test_the_summary_has_median_p95_and_worst_per_scenario_and_metric():
    summary = measurement.summarize(runs_frame())
    assert list(summary.columns) == measurement.SUMMARY_COLUMNS
    warm = summary[(summary["state"] == "warm") & (summary["metric"] == "wall_s")].iloc[0]
    assert warm["runs"] == 10 and warm["median_s"] == 5.5
    assert warm["p95_s"] == pytest.approx(9.55) and warm["worst_s"] == 10
    cold = summary[(summary["state"] == "cold") & (summary["metric"] == "wall_s")].iloc[0]
    assert cold["runs"] == 1 and cold["median_s"] == cold["p95_s"] == cold["worst_s"] == 20
    assert set(summary["metric"]) == {"wall_s", *measurement.STAGE_KEYS, "stage_sum_s"}


def test_the_report_has_one_line_per_scenario():
    text = measurement.format_report(measurement.summarize(runs_frame()))
    assert "wall time includes Python start-up" in text
    assert text.count("\n") == 3 and "s, warm" in text and "s, cold" in text and "5.50s" in text


# --- a measured run ---------------------------------------------------------------------------------

@pytest.fixture
def real_copy(tmp_path):
    """The real saved responses, copied; the measured runs work on this and never on the real folder."""
    return measurement.copy_snapshot(tmp_path / "raw")


def test_a_measured_run_gives_the_wall_time_and_every_stage_time(real_copy, tmp_path):
    row = measurement.run_once(real_copy, config.INPUT_IDS, tmp_path / "out")
    assert set(row) == {"wall_s", *measurement.STAGE_KEYS, "stage_sum_s"}
    assert all(row[k] > 0 for k in measurement.STAGE_KEYS)
    assert row["stage_sum_s"] == pytest.approx(sum(row[k] for k in measurement.STAGE_KEYS))
    assert row["wall_s"] > row["stage_sum_s"]  # start-up and imports sit outside the stages


def test_a_run_that_would_need_the_network_fails_instead_of_making_a_request(tmp_path):
    empty = tmp_path / "empty_raw"
    empty.mkdir()
    with pytest.raises(measurement.MeasurementError, match="TMDB_API_KEY not set"):
        measurement.run_once(empty, config.INPUT_IDS, tmp_path / "out")
    assert not (empty / "details").exists()  # nothing was fetched or saved


def test_warm_runs_are_all_warm_numbered_and_leave_the_real_snapshot_alone(tmp_path):
    before = {"raw": tree_hash(REPO / "data" / "raw"), "out": tree_hash(REPO / "out", "*.csv")}
    rows = measurement.warm_runs(tmp_path, runs=2)
    assert [(r["scenario"], r["size"], r["run"], r["state"]) for r in rows] == [
        ("real snapshot", 127, 1, "warm"), ("real snapshot", 127, 2, "warm"),
    ]
    assert tree_hash(REPO / "data" / "raw") == before["raw"]  # bytes, including fetch_log.csv
    assert tree_hash(REPO / "out", "*.csv") == before["out"]


# --- the command ---------------------------------------------------------------------------------------

def test_the_command_writes_the_two_tables_and_never_touches_the_real_outputs(tmp_path, capsys):
    real_out = tree_hash(REPO / "out", "*.csv")
    real_raw = tree_hash(REPO / "data" / "raw")
    only_warm = ["--warm-runs", "2", "--cold-copies", "0", "--sizes"]
    assert measure.main([*only_warm, "--out", str(tmp_path / "result")]) == 0
    runs = pd.read_csv(tmp_path / "result" / "timing_runs.csv")
    summary = pd.read_csv(tmp_path / "result" / "timing_summary.csv")
    assert list(runs.columns) == measurement.TIMING_COLUMNS and len(runs) == 2
    assert list(summary.columns) == measurement.SUMMARY_COLUMNS
    assert "Timing of a full cached run" in capsys.readouterr().out
    assert tree_hash(REPO / "out", "*.csv") == real_out and tree_hash(REPO / "data" / "raw") == real_raw


def test_the_command_stops_with_a_message_when_a_run_fails(tmp_path, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise measurement.MeasurementError("A measured run failed (exit 1); not timed.")

    monkeypatch.setattr(measurement, "run_once", broken)
    assert measure.main(["--warm-runs", "1", "--cold-copies", "0", "--sizes", "--out", str(tmp_path / "result")]) == 1
    assert "STOPPED: A measured run failed" in capsys.readouterr().out
    assert not (tmp_path / "result").exists()


def test_copying_the_snapshot_copies_every_file(tmp_path):
    copy = measurement.copy_snapshot(tmp_path / "copy")
    assert tree_hash(copy) == tree_hash(REPO / "data" / "raw")
    shutil.rmtree(copy)


# --- cold starts -----------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cold(tmp_path_factory):
    """One cold-start measurement (2 fresh copies, 1 warm run after each), shared by the tests below."""
    work = tmp_path_factory.mktemp("cold")
    made, real_copy = [], measurement.copy_snapshot

    def recording(destination):
        made.append(destination)
        return real_copy(destination)

    measurement.copy_snapshot = recording
    try:
        before = tree_hash(REPO / "data" / "raw")
        rows = measurement.cold_starts(work, copies=2, warm_after=1)
        untouched = tree_hash(REPO / "data" / "raw") == before
    finally:
        measurement.copy_snapshot = real_copy
    return {"rows": rows, "made": made, "work": work, "untouched": untouched}


def test_each_cold_start_uses_a_fresh_copy_and_runs_cold_then_warm(cold):
    rows, made = cold["rows"], cold["made"]
    assert len(made) == 2 and made[0] != made[1] and not made[0].samefile(made[1])
    assert [r["state"] for r in rows] == ["cold", "warm", "cold", "warm"]
    assert [r["copy"] for r in rows] == [1, 1, 2, 2]
    assert [r["run"] for r in rows] == [1, 2, 3, 4]
    assert {r["scenario"] for r in rows} == {"real snapshot, fresh copy"}
    assert cold["untouched"]  # the real snapshot is only ever read


def test_cold_and_warm_runs_are_summarised_separately(cold):
    summary = measurement.summarize(pd.DataFrame(cold["rows"], columns=measurement.TIMING_COLUMNS))
    wall = summary[summary["metric"] == "wall_s"].set_index("state")
    assert wall.loc["cold", "runs"] == 2 and wall.loc["warm", "runs"] == 2
    assert (wall["worst_s"] >= wall["median_s"]).all()


def test_a_cold_run_is_still_fully_cached_and_makes_no_request(cold):
    log = (cold["work"] / "cold_out_1" / "run_log.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert '"fetch_network_calls": 0' in log and '"fetch_cached": 229' in log  # the first, cold run of copy 1


def test_the_command_runs_the_cold_start_test_when_asked(tmp_path):
    cold_only = ["--warm-runs", "1", "--cold-copies", "1", "--cold-followups", "1", "--sizes"]
    assert measure.main([*cold_only, "--out", str(tmp_path / "result")]) == 0
    runs = pd.read_csv(tmp_path / "result" / "timing_runs.csv")
    assert list(runs["state"]) == ["warm", "cold", "warm"] and list(runs["copy"]) == [1, 1, 1]


# --- synthetic responses and growth ----------------------------------------------------------------------

FIXED_TIME = "2026-11-20T00:00:00+00:00"


def synthetic(tmp_path, n=40, **kw):
    kw.setdefault("fetched_at", FIXED_TIME)
    return measurement.make_synthetic(n, tmp_path / f"synthetic_{n}", **kw)


def use_synthetic_folders(monkeypatch, ids_file, raw):
    """Point the in-process pipeline at a synthetic folder, with outputs beside it."""
    out = raw.parent / "out"
    monkeypatch.setattr(config, "INPUT_IDS", ids_file)
    monkeypatch.setattr(config, "RAW_DIR", raw)
    monkeypatch.setattr(config, "RAW_DETAILS_DIR", raw / "details")
    monkeypatch.setattr(config, "RAW_CREDITS_DIR", raw / "credits")
    monkeypatch.setattr(config, "FETCH_LOG", raw / "fetch_log.csv")
    monkeypatch.setattr(config, "OUT_DIR", out)
    monkeypatch.setattr(config, "LIMITED_OUT_DIR", out / "limited")
    return out


def test_a_synthetic_response_passes_the_same_flatten_as_a_real_one(tmp_path, monkeypatch):
    from pipeline import transform

    ids_file, raw = synthetic(tmp_path, 40)
    use_synthetic_folders(monkeypatch, ids_file, raw)
    ids = pd.read_csv(ids_file)["tmdb_id"]
    fetched = pd.DataFrame({"tmdb_id": ids, "first_line_number": range(2, len(ids) + 2)})
    run = transform.flatten_stage(fetched)

    films = run.films
    assert len(run.quarantine) == 0 and len(films) == 40
    assert sorted(films["tmdb_id"]) == list(range(1000, 1040)) and films["tmdb_id"].is_unique
    assert (films["n_cast"] == 50).all() and films["n_crew"].between(151, 152).all()  # 150 crew plus 1 or 2 directors
    assert (films["n_lead_actors"] == 3).all() and films["n_directors"].between(1, 2).all()
    assert (films["status"] == "Released").all() and (films["budget"] >= 300_000).all()
    assert films["release_year"].between(1960, 2024).all() and films["title"].is_unique
    assert (films["revenue"] > 0).all() and films["release_date_unparseable"].eq(False).all()
    assert len(run.talent) == 40 * 3 + int(films["n_directors"].sum())


def test_about_85_percent_of_synthetic_films_sit_in_collections_of_2_to_8(tmp_path, monkeypatch):
    from pipeline import transform

    ids_file, raw = synthetic(tmp_path, 200)
    use_synthetic_folders(monkeypatch, ids_file, raw)
    ids = pd.read_csv(ids_file)["tmdb_id"]
    films = transform.flatten_stage(pd.DataFrame({"tmdb_id": ids, "first_line_number": range(2, 202)})).films
    sizes = films.groupby("collection_id").size()
    assert sizes.between(2, 8).all()
    assert 0.83 <= films["is_franchise"].mean() <= 0.85 and films["is_franchise"].sum() == sizes.sum()


def test_a_synthetic_folder_runs_through_the_whole_pipeline_with_no_failed_check(tmp_path):
    import json

    ids_file, raw = synthetic(tmp_path, 40)
    row = measurement.run_once(raw, ids_file, tmp_path / "out")
    assert row["wall_s"] > 0 and all(row[k] > 0 for k in measurement.STAGE_KEYS)
    record = json.loads((tmp_path / "out" / "run_log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert record["films_rows"] == 40 and record["checks_failed"] == 0 and record["stopped"] is None
    assert record["fetch_network_calls"] == 0 and record["fetch_cached"] == 80  # everything came from the cache


def test_a_synthetic_run_needs_no_network_at_all(tmp_path, monkeypatch, fetch_env):
    import run_pipeline
    from pipeline import fetch

    ids_file, raw = synthetic(tmp_path, 25)
    use_synthetic_folders(monkeypatch, ids_file, raw)

    def no_session():
        raise AssertionError("the fetch stage tried to open a connection")

    monkeypatch.setattr(fetch, "build_session", no_session)
    assert run_pipeline.main([]) == 0


def test_the_same_seed_gives_byte_identical_files_and_another_seed_does_not(tmp_path):
    first = synthetic(tmp_path / "a", 30)
    second = synthetic(tmp_path / "b", 30)
    assert tree_hash(first[1].parent) == tree_hash(second[1].parent)
    assert first[0].read_bytes() == second[0].read_bytes()  # the id list too
    other = synthetic(tmp_path / "c", 30, seed=1)
    assert tree_hash(other[1].parent) != tree_hash(first[1].parent)


def test_the_synthetic_files_contain_no_tmdb_text(tmp_path):
    _, raw = synthetic(tmp_path, 5)
    text = (raw / "details" / "1000.json").read_text(encoding="utf-8")
    assert "An invented film for timing." in text and "Film " in text


def test_the_fetch_log_marks_every_synthetic_file_as_fetched(tmp_path):
    ids_file, raw = synthetic(tmp_path, 8)
    log = pd.read_csv(raw / "fetch_log.csv")
    assert len(log) == 16 and set(log["outcome"]) == {"ok"} and set(log["fetched_at"]) == {FIXED_TIME}
    assert set(log["endpoint"]) == {"details", "credits"}
    assert len(list((raw / "details").glob("*.json"))) == len(list((raw / "credits").glob("*.json"))) == 8
    assert ids_file.read_bytes().startswith(b"tmdb_id\r\n1000\r\n")


# --- growth ------------------------------------------------------------------------------------------------

def test_growth_runs_one_cold_run_then_warm_runs_at_each_size_and_say_where_the_outputs_are(tmp_path):
    rows, outputs = measurement.growth_runs(tmp_path, sizes=(12, 24), warm_after=1)
    assert [(r["size"], r["state"]) for r in rows] == [(12, "cold"), (12, "warm"), (24, "cold"), (24, "warm")]
    assert {r["scenario"] for r in rows} == {"synthetic"} and set(outputs) == {12, 24}
    assert len(pd.read_csv(outputs[24] / "films.csv")) == 24


def growth_summary():
    rows = []
    for size, factor in ((127, 1.0), (500, 4.0), (5000, 40.0)):
        for state in ("cold", "warm"):
            for metric, base in {"flatten": 0.10, "rank": 0.05, "stage_sum_s": 0.30, "wall_s": 2.0}.items():
                rows.append({"scenario": "synthetic", "size": size, "state": state, "metric": metric, "runs": 4,
                             "median_s": base * factor * (2 if state == "cold" else 1), "p95_s": 0, "worst_s": 0})
    return pd.DataFrame(rows, columns=measurement.SUMMARY_COLUMNS)


def test_the_growth_table_gives_warm_medians_and_the_ratio_between_sizes():
    table = measurement.growth_table(growth_summary()).set_index("metric")
    assert list(table.columns) == [
        "median_s_127", "median_s_500", "median_s_5000", "ratio_500_127", "ratio_5000_500",
    ]
    assert table.loc["flatten", "median_s_127"] == pytest.approx(0.10)
    assert table.loc["flatten", "median_s_500"] == pytest.approx(0.40)
    assert table.loc["flatten", "ratio_500_127"] == pytest.approx(4.0)
    assert table.loc["rank", "ratio_5000_500"] == pytest.approx(10)
    assert list(table.index) == ["flatten", "rank", "stage_sum_s", "wall_s"]  # stages in pipeline order, totals last


def test_the_verdict_says_met_or_not_met_with_the_cold_and_warm_times():
    slow = "budget (10 s wall, 500 titles, cached): not met, cold 16.0 s, warm 8.0 s"
    assert measurement.verdict(growth_summary()) == slow
    fast = growth_summary().assign(median_s=lambda d: d["median_s"] / 4)
    assert measurement.verdict(fast) == "budget (10 s wall, 500 titles, cached): met, cold 4.0 s, warm 2.0 s"


def test_the_verdict_says_so_when_there_is_no_500_title_run():
    summary = growth_summary()
    text = measurement.verdict(summary[summary["size"] != 500])
    assert text == "budget (10 s wall, 500 titles, cached): not measured (no 500-title run)"


def test_the_command_writes_the_growth_table_and_prints_the_verdict(tmp_path, capsys):
    real_raw, real_out = tree_hash(REPO / "data" / "raw"), tree_hash(REPO / "out", "*.csv")
    assert measure.main(["--warm-runs", "1", "--cold-copies", "0", "--sizes", "10", "20", "--growth-followups", "1",
                         "--out", str(tmp_path / "result")]) == 0
    growth = pd.read_csv(tmp_path / "result" / "growth.csv")
    assert list(growth.columns) == ["metric", "median_s_10", "median_s_20", "ratio_20_10"]
    printed = capsys.readouterr().out
    assert "budget (10 s wall, 500 titles, cached): not measured" in printed
    assert tree_hash(REPO / "data" / "raw") == real_raw and tree_hash(REPO / "out", "*.csv") == real_out
