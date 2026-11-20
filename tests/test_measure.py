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
    assert measure.main(["--warm-runs", "2", "--cold-copies", "0", "--out", str(tmp_path / "result")]) == 0
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
    assert measure.main(["--warm-runs", "1", "--cold-copies", "0", "--out", str(tmp_path / "result")]) == 1
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
    assert measure.main(["--warm-runs", "1", "--cold-copies", "1", "--cold-followups", "1",
                         "--out", str(tmp_path / "result")]) == 0
    runs = pd.read_csv(tmp_path / "result" / "timing_runs.csv")
    assert list(runs["state"]) == ["warm", "cold", "warm"] and list(runs["copy"]) == [1, 1, 1]
