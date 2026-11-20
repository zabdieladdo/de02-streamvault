"""Measure how long a full cached run takes, per stage, and how that grows with the number of films.

Run it with: python measure.py. It never makes a network request and never writes the real data/raw/ or
out/ files: it works on copies and on synthetic data in a temporary folder and writes its results to
out/measurement/. See docs/measurement_report.md for the method and the results.
"""
import argparse
import sys
import tempfile
from pathlib import Path

from pipeline import config, measurement
from pipeline.errors import PipelineStopError

DEFAULTS = {
    "warm_runs": 10, "cold_copies": 3, "cold_followups": 4, "sizes": list(measurement.GROWTH_SIZES),
    "growth_followups": 4, "vector_runs": 5,
    "budget_cold_copies": measurement.BUDGET_COLD_COPIES,
}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure the pipeline's run time.")
    parser.add_argument("--warm-runs", type=int, default=DEFAULTS["warm_runs"], help="warm runs on the real snapshot")
    parser.add_argument("--cold-copies", type=int, default=DEFAULTS["cold_copies"],
                        help="fresh copies of the responses for the cold-start test")
    parser.add_argument("--cold-followups", type=int, default=DEFAULTS["cold_followups"],
                        help="warm runs after each cold run")
    parser.add_argument("--sizes", type=int, nargs="*", default=DEFAULTS["sizes"],
                        help="synthetic film counts for the growth test (none to skip it)")
    parser.add_argument("--growth-followups", type=int, default=DEFAULTS["growth_followups"],
                        help="warm runs after the cold run at each size")
    parser.add_argument("--budget-cold-copies", type=int, default=DEFAULTS["budget_cold_copies"],
                        help="fresh copies run cold at 500 titles, and again with a stale snapshot")
    parser.add_argument("--vector-runs", type=int, default=DEFAULTS["vector_runs"],
                        help="timed runs of the row-wise and vectorised versions (0 to skip)")
    parser.add_argument("--out", type=Path, default=config.REPO_ROOT / "out" / "measurement",
                        help="where the results are written")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the measurements, write out/measurement/ and print the summary."""
    args = parse_args(argv)
    options = {
        "warm_runs": args.warm_runs, "cold_copies": args.cold_copies, "cold_followups": args.cold_followups,
        "sizes": args.sizes, "growth_followups": args.growth_followups, "vector_runs": args.vector_runs,
        "budget_cold_copies": args.budget_cold_copies,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="streamvault_measure_") as tmp:
            tables = measurement.run_all(options, Path(tmp))
    except PipelineStopError as exc:
        print(f"STOPPED: {exc}")
        return 1
    measurement.write_results(args.out, tables)
    print(measurement.format_report(tables["timing_summary.csv"]))
    print(measurement.verdict(tables["timing_summary.csv"]))
    if "vectorisation.csv" in tables:
        print(measurement.format_vectorisation(tables["vectorisation.csv"]))
    print(f"Results written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
