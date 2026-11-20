"""Run every pipeline stage, print counts and timings, and write the run log."""
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pipeline import checks, config, extract, load, validate
from pipeline.errors import PipelineStopError
from pipeline.validate import REASON_ORDER


def _display_path(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(config.REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _stage1() -> int:
    t0 = time.perf_counter()
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    raw, meta = extract.read_id_file(config.INPUT_IDS)
    ids_to_fetch, quarantine = validate.classify_ids(raw, run_at=run_at)
    report = checks.check_load_stage(meta, raw, ids_to_fetch, quarantine)
    reconciliation = load.build_reconciliation(len(raw), ids_to_fetch, quarantine)
    load.write_stage1_outputs(ids_to_fetch, quarantine, reconciliation, report)

    seconds = time.perf_counter() - t0
    by_reason = {
        code: int(n)
        for code, n in quarantine["reason_code"].value_counts().items()
    }
    ordered = [c for c in REASON_ORDER if c in by_reason]
    n_passed = int(report["passed"].sum())
    n_failed = int((~report["passed"]).sum())
    n_large = int(ids_to_fetch["flag_large_id"].sum())

    load.append_run_log(
        {
            "run_at": run_at,
            "input_path": _display_path(config.INPUT_IDS),
            "input_bytes": meta["input_bytes"],
            "input_sha256": meta["input_sha256"],
            "bom_found": meta["bom_found"],
            "rows_raw": len(raw),
            "quarantined_by_reason": {c: by_reason[c] for c in ordered},
            "ids_to_fetch": len(ids_to_fetch),
            "checks_passed": n_passed,
            "checks_failed": n_failed,
            "seconds": {"stage1_load_ids": round(seconds, 4)},
        }
    )

    print("Stage 1: load ids")
    print(
        f"  input   {_display_path(config.INPUT_IDS)}  {meta['input_bytes']} bytes  "
        f"sha256 {meta['input_sha256'][:8].upper()}..."
    )
    print(f"  rows    {len(raw)} read ({meta['raw_line_count']} lines counted)")
    print(f"  quarantined  {len(quarantine)}")
    if ordered:
        print("     " + " | ".join(f"{c} {by_reason[c]}" for c in ordered))
    print(f"  to fetch     {len(ids_to_fetch)}   ({n_large} flagged as large ids, kept)")
    print(f"  checks  {n_passed} passed, {n_failed} failed")
    print(f"  time    {seconds:.3f} s")
    print(f"Outputs written to {_display_path(config.OUT_DIR)}/")

    checks.raise_if_conservation_failed(report)  # after the report is on disk
    return 0


def main() -> int:
    try:
        return _stage1()
    except PipelineStopError as exc:
        print(f"STOPPED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
