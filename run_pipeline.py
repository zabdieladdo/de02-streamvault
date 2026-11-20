"""Run every pipeline stage, print counts and timings, and write the run log."""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pipeline import checks, config, extract, fetch, load, validate
from pipeline.errors import PipelineStopError
from pipeline.redact import redact
from pipeline.validate import REASON_ORDER


def _display_path(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(config.REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="StreamVault analysis pipeline.")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore the cache and request everything again")
    parser.add_argument("--limit", type=_positive_int, metavar="N",
                        help="fetch only the first N ids (a limited run)")
    return parser.parse_args(argv)


def _stage1(record: dict) -> dict:
    t0 = time.perf_counter()
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    raw, meta = extract.read_id_file(config.INPUT_IDS)
    ids_to_fetch, quarantine = validate.classify_ids(raw, run_at=run_at)
    report = checks.check_load_stage(meta, raw, ids_to_fetch, quarantine)
    reconciliation = load.build_reconciliation(len(raw), ids_to_fetch, quarantine)
    load.write_stage1_outputs(ids_to_fetch, quarantine, reconciliation, report)

    seconds = time.perf_counter() - t0
    by_reason = {c: int(n) for c, n in quarantine["reason_code"].value_counts().items()}
    ordered = [c for c in REASON_ORDER if c in by_reason]
    n_passed = int(report["passed"].sum())
    n_failed = int((~report["passed"]).sum())
    n_large = int(ids_to_fetch["flag_large_id"].sum())

    record.update(
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
        }
    )
    record["seconds"]["stage1_load_ids"] = round(seconds, 4)

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
    return {
        "raw": raw, "ids_to_fetch": ids_to_fetch, "quarantine": quarantine, "report": report,
    }


def _count(outcomes: pd.Series, names) -> int:
    return int(outcomes.isin(names).sum())


def _outcome_line(label: str, outcomes: pd.Series) -> str:
    ok = _count(outcomes, fetch.SUCCESS)
    nf = _count(outcomes, fetch.NOT_FOUND)
    skipped = _count(outcomes, ["skipped"])
    failed = len(outcomes) - ok - nf - skipped
    parts = [f"ok {ok}"]
    if nf:
        parts.append(f"not found {nf}")
    if skipped:
        parts.append(f"skipped {skipped}")
    parts.append(f"failed {failed}")
    return f"{label} " + " | ".join(parts)


def _stage2(stage1: dict, args, session, key, record: dict) -> None:
    t0 = time.perf_counter()
    ids = stage1["ids_to_fetch"]
    try:
        run = fetch.fetch_all(ids, session=session, key=key, refresh=args.refresh, limit=args.limit)
    finally:
        record["seconds"]["fetch"] = round(time.perf_counter() - t0, 3)
    seconds = time.perf_counter() - t0

    results, fq = run.results, run.quarantine
    fetched_ids = load.build_fetched_ids(run.ids_processed, results, fq)
    report2 = checks.check_fetch_stage(run)
    quarantine = (
        pd.concat([stage1["quarantine"], fq]).sort_values("line_number").reset_index(drop=True)
    )
    reconciliation = load.build_reconciliation(
        len(stage1["raw"]), ids, quarantine, fetched_ids,
        ids_processed=len(run.ids_processed), limit=args.limit,
    )
    report = pd.concat([stage1["report"], report2], ignore_index=True)
    load.write_fetch_outputs(fetched_ids, quarantine, reconciliation, report)

    n_cached = int(results["source"].eq("cache").sum())
    by_outcome = {k: int(v) for k, v in results["outcome"].value_counts().items()}
    attempts = results["attempts"].dropna()
    max_attempts = int(attempts.max()) if len(attempts) else None
    rate = run.network_calls / run.network_seconds if run.network_calls and run.network_seconds else None
    n_passed, n_failed = int(report2["passed"].sum()), int((~report2["passed"]).sum())
    incomplete = not bool(report2.loc[report2["check_id"] == "C-10i", "passed"].iloc[0])
    by_reason = {c: int(n) for c, n in fq["reason_code"].value_counts().items()}
    ordered = [c for c in fetch.REASON_ORDER if c in by_reason]

    record.update(
        {
            "fetch_network_calls": run.network_calls,
            "fetch_cached": n_cached,
            "fetch_by_outcome": by_outcome,
            "fetch_quarantined_by_reason": {c: by_reason[c] for c in ordered},
            "requests_per_second_achieved": round(rate, 2) if rate else None,
            "max_attempts": max_attempts,
            "ids_fetched": len(fetched_ids),
            "analysis_incomplete": incomplete,
            "limit": args.limit,
            "refresh": args.refresh,
            "checks_passed": record["checks_passed"] + n_passed,
            "checks_failed": record["checks_failed"] + n_failed,
        }
    )

    details = results[results["endpoint"] == "details"]["outcome"]
    credits_ = results[results["endpoint"] == "credits"]["outcome"]
    print()
    print("Stage 2: fetch details and credits")
    if args.limit:
        print(f"  LIMITED RUN: first {len(run.ids_processed)} of {len(ids)} ids only")
    print(f"  ids          {len(run.ids_processed)}")
    print(f"  requests     {run.network_calls} made, {n_cached} from cache")
    if rate:
        print(f"  rate         {rate:.1f} requests per second achieved "
              f"(throttle {config.REQUESTS_PER_SECOND:.1f})")
    else:
        print("  rate         no network requests made")
    print(f"  outcomes     {_outcome_line('details', details)}   {_outcome_line('credits', credits_)}")
    print(f"  retries      max attempts {max_attempts if max_attempts is not None else 'n/a'}")
    detail = ", ".join(f"{c} {by_reason[c]}" for c in ordered)
    print(f"  quarantined  {len(fq)} at this stage" + (f"   ({detail})" if detail else ""))
    print(f"  fetched      {len(fetched_ids)} films with details and credits")
    print(f"  checks       {n_passed} passed, {n_failed} failed")
    if incomplete:
        row = report2.loc[report2["check_id"] == "C-10i", "detail"].iloc[0]
        print(f"  ANALYSIS INCOMPLETE: {row}")
    print(f"  time         {seconds:.1f} s")
    print(f"Outputs written to {_display_path(config.OUT_DIR)}/")


def main(argv=None, session=None) -> int:
    """Run the pipeline. `session` lets tests pass a fake in place of the network."""
    args = _parse_args(argv)
    try:
        key = config.get_api_key()
    except PipelineStopError:
        key = None  # a fully cached run needs no key; the fetch stage raises if it does
    record: dict = {"seconds": {}, "stopped": None}
    code = 0
    try:
        stage1 = _stage1(record)
        _stage2(stage1, args, session, key, record)
    except PipelineStopError as exc:
        message = redact(str(exc), key)
        print(f"STOPPED: {message}")
        record["stopped"] = message
        code = 1
    if "input_sha256" in record:  # stage 1 got far enough to log
        load.append_run_log(record)
    return code


if __name__ == "__main__":
    sys.exit(main())
