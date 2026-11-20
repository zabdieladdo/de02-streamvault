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

DEFAULTS = {"warm_runs": 10}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure the pipeline's run time.")
    parser.add_argument("--warm-runs", type=int, default=DEFAULTS["warm_runs"], help="warm runs on the real snapshot")
    parser.add_argument("--out", type=Path, default=config.REPO_ROOT / "out" / "measurement",
                        help="where the results are written")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the measurements, write out/measurement/ and print the summary."""
    args = parse_args(argv)
    options = {"warm_runs": args.warm_runs}
    try:
        with tempfile.TemporaryDirectory(prefix="streamvault_measure_") as tmp:
            tables = measurement.run_all(options, Path(tmp))
    except PipelineStopError as exc:
        print(f"STOPPED: {exc}")
        return 1
    measurement.write_results(args.out, tables)
    print(measurement.format_report(tables["timing_summary.csv"]))
    print(f"Results written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
