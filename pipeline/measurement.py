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
from itertools import pairwise
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


# --- synthetic responses and growth ---------------------------------------------------------------------
# TMDb content may not be copied or reused beyond its terms, so growth is measured on responses that
# have TMDb's field names and shapes but invented values, from a fixed seed.

SYNTHETIC_SEED = 20261120
GROWTH_SIZES = (127, 500, 5000)
GENRES = [
    "Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama", "Family", "Fantasy",
    "History", "Horror", "Music", "Mystery", "Romance", "Science Fiction", "Thriller", "War", "Western",
]
CREW_JOBS = [
    "Producer", "Executive Producer", "Screenplay", "Editor", "Original Music Composer", "Director of Photography",
    "Casting", "Production Design", "Art Direction", "Costume Design", "Sound Designer", "Visual Effects Supervisor",
]
CAST_PER_FILM, CREW_PER_FILM = 50, 150
CAST_POOL, CREW_POOL, DIRECTOR_POOL = 30_000, 40_000, 1_500  # people repeat across films, as they do for real
COLLECTION_SHARE = 0.85  # about this share of films belong to a collection of 2 to 8 films


def _word(number: int) -> str:
    """Four letters from a number, so titles are unique and contain no digits or punctuation."""
    letters = []
    for _ in range(4):
        number, remainder = divmod(number, 26)
        letters.append(chr(97 + remainder))
    return "".join(reversed(letters)).capitalize()


def _collections(rng: np.random.Generator, n: int) -> np.ndarray:
    """A collection id for each film, or 0 for a standalone: whole collections of 2 to 8 films."""
    target = round(COLLECTION_SHARE * n)
    sizes = rng.integers(2, 9, size=n)
    whole = int(np.searchsorted(np.cumsum(sizes), target, side="right"))
    groups = sizes[:whole].tolist()
    rest = target - sum(groups)
    if rest >= 2:
        groups.append(rest)  # at most 8, because the next whole collection did not fit
    covered = sum(groups)
    ids = np.zeros(n, dtype="int64")
    ids[rng.permutation(n)[:covered]] = np.repeat(100_000 + np.arange(len(groups)), groups)
    return ids


def make_synthetic(
    n: int, folder: Path, seed: int = SYNTHETIC_SEED, fetched_at: str | None = None
) -> tuple[Path, Path]:
    """Write an id list, `n` details and credits files and a fetch log into `folder`; return (ids file, raw dir).

    Values are invented but have TMDb's field names and types. The fetch log marks every file as fetched
    `fetched_at` (today by default), so the fetch stage reads everything from the cache.
    """
    rng = np.random.default_rng(seed)
    fetched_at = fetched_at or pd.Timestamp.now("UTC").isoformat(timespec="seconds")
    raw = folder / "raw"
    (raw / "details").mkdir(parents=True, exist_ok=True)
    (raw / "credits").mkdir(parents=True, exist_ok=True)

    ids = np.arange(1000, 1000 + n)
    collection = _collections(rng, n)
    budget = np.clip(np.exp(rng.normal(np.log(3e7), 1.0, n)), 3e5, 4e8).round().astype("int64")
    multiple = np.clip(np.exp(rng.normal(np.log(4.0), 0.7, n)), 0.3, 40)
    revenue = (budget * multiple).round().astype("int64")
    dates = pd.to_datetime(
        {"year": rng.integers(1960, 2025, n), "month": rng.integers(1, 13, n), "day": rng.integers(1, 29, n)}
    ).dt.strftime("%Y-%m-%d")
    votes = np.clip(np.exp(rng.normal(np.log(8000), 1.0, n)), 600, 60_000).round().astype("int64")
    rating = rng.uniform(5.0, 8.8, n).round(3)
    popularity = np.exp(rng.normal(np.log(20), 0.6, n)).round(3)
    runtime = rng.integers(80, 181, n)
    genre_count = rng.integers(1, 5, n)
    companies = rng.integers(1, 6, n)

    for i in range(n):  # one pair of files per film, like the fetch stage writes
        film = int(ids[i])
        genres = rng.choice(len(GENRES), int(genre_count[i]), replace=False)
        details = {
            "adult": False, "backdrop_path": f"/b{film}.jpg",
            "belongs_to_collection": (
                {"id": int(collection[i]), "name": f"Saga {_word(int(collection[i]))}", "poster_path": "/c.jpg"}
                if collection[i] else None
            ),
            "budget": int(budget[i]), "genres": [{"id": int(g), "name": GENRES[g]} for g in genres],
            "homepage": "", "id": film, "imdb_id": f"tt{film:07d}", "original_language": "en",
            "original_title": f"Film {_word(film)}", "overview": "An invented film for timing.",
            "popularity": float(popularity[i]), "poster_path": f"/p{film}.jpg",
            "production_companies": [
                {"id": 50_000 + int(c), "name": f"Studio {_word(int(c))}", "origin_country": "US"}
                for c in rng.integers(0, 3000, int(companies[i]))
            ],
            "release_date": dates.iloc[i], "revenue": int(revenue[i]), "runtime": int(runtime[i]),
            "status": "Released", "tagline": "", "title": f"Film {_word(film)}", "video": False,
            "vote_average": float(rating[i]), "vote_count": int(votes[i]),
        }
        cast_ids = 10_000 + rng.choice(CAST_POOL, CAST_PER_FILM, replace=False)
        crew_ids = 60_000 + rng.choice(CREW_POOL, CREW_PER_FILM, replace=False)
        directors = 200_000 + rng.choice(DIRECTOR_POOL, 1 + int(rng.random() < 0.1), replace=False)
        other_jobs = [CREW_JOBS[j] for j in rng.integers(0, len(CREW_JOBS), CREW_PER_FILM)]
        crew_jobs = ["Director"] * len(directors) + other_jobs
        credits = {
            "id": film,
            "cast": [
                {"adult": False, "gender": 2, "id": int(p), "known_for_department": "Acting", "name": f"Actor {p}",
                 "original_name": f"Actor {p}", "popularity": 5.0, "profile_path": "/a.jpg", "cast_id": order,
                 "character": "Role", "credit_id": f"c{film}-{order}", "order": order}
                for order, p in enumerate(cast_ids)
            ],
            "crew": [
                {"adult": False, "gender": 1, "id": int(p), "known_for_department": "Crew", "name": f"Crew {p}",
                 "original_name": f"Crew {p}", "popularity": 3.0, "profile_path": "/c.jpg", "credit_id": f"w{film}-{k}",
                 "department": "Directing" if job == "Director" else "Production", "job": job}
                for k, (p, job) in enumerate(zip([*directors, *crew_ids], crew_jobs))
            ],
        }
        (raw / "details" / f"{film}.json").write_text(json.dumps(details), encoding="utf-8")
        (raw / "credits" / f"{film}.json").write_text(json.dumps(credits), encoding="utf-8")

    log = pd.DataFrame(
        {
            "tmdb_id": np.repeat(ids, 2), "endpoint": ["details", "credits"] * n,
            "path": [f"/movie/{i}{end}" for i in ids for end in ("", "/credits")],
            "status_code": 200, "outcome": "ok", "attempts": 1, "fetched_at": fetched_at, "elapsed_s": 0.3,
            "detail": "",
        }
    )
    log.to_csv(raw / "fetch_log.csv", index=False, encoding="utf-8")
    ids_file = folder / "id_list.csv"
    ids_file.write_bytes(("tmdb_id\r\n" + "".join(f"{i}\r\n" for i in ids)).encode("utf-8"))
    return ids_file, raw


def growth_runs(work: Path, sizes=GROWTH_SIZES, warm_after: int = 4) -> tuple[list[dict], dict[int, Path]]:
    """Synthetic data at each size: one cold run on the freshly written files, then warm runs.

    Returns the timing rows and, for each size, the folder its outputs were written to.
    """
    rows, outputs = [], {}
    for size in sizes:  # a few sizes, each generated and run in turn
        ids_file, raw = make_synthetic(size, work / f"synthetic_{size}")
        out = work / f"synthetic_{size}_out"
        rows += measure_runs("synthetic", size, raw, ids_file, out, ["cold"] + ["warm"] * warm_after)
        outputs[size] = out
    return rows, outputs


def growth_table(summary: pd.DataFrame) -> pd.DataFrame:
    """Median warm seconds per stage at each synthetic size, and the ratio from each size to the next."""
    warm = summary[(summary["scenario"] == "synthetic") & (summary["state"] == "warm")]
    wide = warm.pivot(index="metric", columns="size", values="median_s")
    sizes = sorted(wide.columns)
    order = [m for m in [*STAGE_KEYS, "stage_sum_s", "wall_s"] if m in wide.index]
    table = pd.DataFrame({"metric": order})
    for size in sizes:
        table[f"median_s_{size}"] = wide.loc[order, size].to_numpy()
    for small, large in pairwise(sizes):  # consecutive sizes
        table[f"ratio_{large}_{small}"] = (wide.loc[order, large] / wide.loc[order, small]).to_numpy()
    return table


def verdict(summary: pd.DataFrame) -> str:
    """One line: is a cached run at 500 titles inside the budget, cold and warm."""
    label = f"budget ({BUDGET_SECONDS} s wall, {BUDGET_TITLES} titles, cached)"
    at_budget_size = (summary["scenario"] == "synthetic") & (summary["size"] == BUDGET_TITLES)
    rows = summary[at_budget_size & (summary["metric"] == "wall_s")]
    cold, warm = rows[rows["state"] == "cold"], rows[rows["state"] == "warm"]
    if cold.empty or warm.empty:
        return f"{label}: not measured (no {BUDGET_TITLES}-title run)"
    cold_s, warm_s = float(cold["median_s"].iloc[0]), float(warm["median_s"].iloc[0])
    met = max(cold_s, warm_s) <= BUDGET_SECONDS
    return f"{label}: {'met' if met else 'not met'}, cold {cold_s:.1f} s, warm {warm_s:.1f} s"


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
    if options["sizes"]:
        growth, _ = growth_runs(work, options["sizes"], options["growth_followups"])
        rows += growth
    runs = pd.DataFrame(rows, columns=TIMING_COLUMNS)
    summary = summarize(runs)
    tables = {"timing_runs.csv": runs, "timing_summary.csv": summary}
    if options["sizes"]:
        tables["growth.csv"] = growth_table(summary)
    return tables
