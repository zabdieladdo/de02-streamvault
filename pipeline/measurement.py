"""Measure the pipeline's run time: warm runs, cold starts, growth on synthetic data, row-wise against vectorised.

The boundary is a full cached run: everything run_pipeline.py does when every response is already saved,
with no network. Every measured run is a subprocess of the real run_pipeline.py, so the wall time includes
Python start-up and imports (what Adjoa waits for) and the per-stage seconds come from that run's own log
line (our code). Nothing here makes a network request or writes the real data/raw/ or out/: runs work on
copies and synthetic folders, selected through the STREAMVAULT_* environment variables.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import config
from pipeline.errors import PipelineStopError

STAGE_KEYS = ["stage1_load_ids", "fetch", "flatten", "clean", "measure", "rank"]
TIMING_COLUMNS = ["scenario", "size", "run", "state", "wall_s", *STAGE_KEYS, "stage_sum_s", "copy"]
SUMMARY_COLUMNS = ["scenario", "size", "state", "metric", "runs", "median_s", "p95_s", "worst_s"]
BUDGET_SECONDS = 10  # S05: a full cached run, 500 titles
BUDGET_TITLES = 500
REAL_SIZE = 127  # rows in the real id list


class MeasurementError(PipelineStopError):
    """A measured run failed, so its time would mean nothing."""


def percentile(values, q: float) -> float:
    """The q-th percentile by linear interpolation between the closest ranks (numpy's default)."""
    return float(np.percentile(np.asarray(list(values), dtype="float64"), q, method="linear"))


def run_once(raw_dir: Path, ids_file: Path, out_dir: Path) -> dict:
    """One full run of run_pipeline.py on the given folders; its wall time and per-stage seconds.

    The API key is blanked, so a run that needed the network would stop with a message instead of
    making a request: a measured run is fully cached or it fails.
    """
    env = {
        **os.environ,
        "STREAMVAULT_RAW_DIR": str(raw_dir), "STREAMVAULT_INPUT_IDS": str(ids_file),
        "STREAMVAULT_OUT_DIR": str(out_dir), "TMDB_API_KEY": "",
    }
    started = time.perf_counter()
    run = subprocess.run(
        [sys.executable, str(config.REPO_ROOT / "run_pipeline.py")], cwd=config.REPO_ROOT, env=env,
        capture_output=True, text=True, check=False,
    )
    wall = time.perf_counter() - started
    if run.returncode != 0:
        tail = "\n".join(run.stdout.strip().splitlines()[-3:])
        raise MeasurementError(f"A measured run failed (exit {run.returncode}); not timed.\n{tail}")
    last = json.loads((out_dir / "run_log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    seconds = {key: float(last["seconds"].get(key, np.nan)) for key in STAGE_KEYS}
    return {"wall_s": wall, **seconds, "stage_sum_s": float(np.nansum(list(seconds.values())))}


def measure_runs(
    scenario: str, size: int, raw_dir: Path, ids_file: Path, out_dir: Path, states: list[str], copy: int = 1,
    first_run: int = 1,
) -> list[dict]:
    """One timed run per entry of `states` ("cold" or "warm"), in order, on the same folders.

    `copy` says which fresh copy of the responses the runs belong to (1 when there is only one).
    """
    rows = []
    for number, state in enumerate(states, start=first_run):  # a loop over runs: each is a separate process
        rows.append({"scenario": scenario, "size": size, "run": number, "state": state, "copy": copy,
                     **run_once(raw_dir, ids_file, out_dir)})
    return rows


def copy_snapshot(destination: Path) -> Path:
    """A copy of the real saved responses, so a measured run cannot change the real snapshot."""
    shutil.copytree(config.RAW_DIR, destination)
    return destination


def warm_runs(work: Path, runs: int = 10) -> list[dict]:
    """Warm runs of the full cached pipeline on the real snapshot (a copy of it), back to back."""
    raw = copy_snapshot(work / "warm_raw")
    return measure_runs("real snapshot", REAL_SIZE, raw, config.INPUT_IDS, work / "warm_out", ["warm"] * runs)


def cold_starts(work: Path, copies: int = 3, warm_after: int = 4) -> list[dict]:
    """Cold-start runs on purpose: a fresh copy of the saved responses, one run (cold), then more (warm).

    Repeated on `copies` separate fresh copies. "Cold" means the first run on files this process tree has
    not read before; the operating system may still hold freshly copied files in memory, so what the run
    shows is reported as measured, not assumed.
    """
    rows = []
    for number in range(1, copies + 1):  # each copy is made and run in turn
        raw = copy_snapshot(work / f"cold_raw_{number}")
        states = ["cold"] + ["warm"] * warm_after
        rows += measure_runs(
            "real snapshot, fresh copy", REAL_SIZE, raw, config.INPUT_IDS, work / f"cold_out_{number}", states,
            copy=number, first_run=(number - 1) * len(states) + 1,
        )
    return rows


def summarize(runs: pd.DataFrame) -> pd.DataFrame:
    """Median, 95th percentile (linear interpolation) and worst, per scenario, for wall time and each stage."""
    metrics = ["wall_s", *STAGE_KEYS, "stage_sum_s"]
    rows = []
    for (scenario, size, state), part in runs.groupby(["scenario", "size", "state"], sort=False):  # few groups
        for metric in metrics:
            values = part[metric].dropna()
            rows.append(
                {
                    "scenario": scenario, "size": size, "state": state, "metric": metric, "runs": len(values),
                    "median_s": percentile(values, 50), "p95_s": percentile(values, 95), "worst_s": float(values.max()),
                }
            )
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def write_results(out_dir: Path, tables: dict[str, pd.DataFrame]) -> None:
    """Write each table to out_dir as CSV, rounded to milliseconds for the time columns."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(out_dir / name, index=False, encoding="utf-8", float_format="%.4f")


# --- the report and the command -----------------------------------------------------------------

def format_report(summary: pd.DataFrame) -> str:
    """A table of wall time per scenario: runs, median, 95th percentile and worst."""
    wall = summary[summary["metric"] == "wall_s"]
    lines = [
        "Timing of a full cached run (wall time includes Python start-up and imports)",
        f"  {'scenario':<28}{'size':>6}{'runs':>6}{'median':>9}{'p95':>9}{'worst':>9}",
    ]
    for row in wall.to_dict("records"):  # one line per scenario
        label = f"{row['scenario']}, {row['state']}"
        lines.append(
            f"  {label:<28}{row['size']:>6}{row['runs']:>6}{row['median_s']:>8.2f}s{row['p95_s']:>8.2f}s"
            f"{row['worst_s']:>8.2f}s"
        )
    return "\n".join(lines)


def run_all(options: dict, work: Path) -> dict[str, pd.DataFrame]:
    """Every measurement the options ask for, in the temporary folder `work`; the tables to write."""
    rows = warm_runs(work, options["warm_runs"])
    if options["cold_copies"]:
        rows += cold_starts(work, options["cold_copies"], options["cold_followups"])
    runs = pd.DataFrame(rows, columns=TIMING_COLUMNS)
    return {"timing_runs.csv": runs, "timing_summary.csv": summarize(runs)}
