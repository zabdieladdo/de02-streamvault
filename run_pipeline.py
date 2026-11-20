"""Run every pipeline stage, print counts and timings, and write the run log."""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pipeline import checks, clean, config, extract, fetch, load, metrics, transform, validate
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


def _stage1(record: dict, out_dir: Path) -> dict:
    t0 = time.perf_counter()
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    raw, meta = extract.read_id_file(config.INPUT_IDS)
    ids_to_fetch, quarantine = validate.classify_ids(raw, run_at=run_at)
    report = checks.check_load_stage(meta, raw, ids_to_fetch, quarantine)
    reconciliation = load.build_reconciliation(len(raw), ids_to_fetch, quarantine)
    load.write_stage1_outputs(ids_to_fetch, quarantine, reconciliation, report, out_dir=out_dir)

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
    print(f"Outputs written to {_display_path(out_dir)}/")

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


def _stage2(stage1: dict, args, session, key, record: dict, out_dir: Path) -> dict:
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
    load.write_fetch_outputs(fetched_ids, quarantine, reconciliation, report, out_dir=out_dir)

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
    print(f"Outputs written to {_display_path(out_dir)}/")
    return {"run": run, "fetched_ids": fetched_ids, "quarantine": quarantine, "report": report}


def _stage3(stage1: dict, stage2: dict, args, record: dict, out_dir: Path) -> None:
    t0 = time.perf_counter()
    fetched_ids = stage2["fetched_ids"]
    run = transform.flatten_stage(fetched_ids)
    films, talent = run.films, run.talent

    report3 = checks.check_flatten_stage(run, stage1["quarantine"])
    quarantine = (
        pd.concat([stage2["quarantine"], run.quarantine])
        .sort_values("line_number").reset_index(drop=True)
    )
    reconciliation = load.build_reconciliation(
        len(stage1["raw"]), stage1["ids_to_fetch"], quarantine, fetched_ids,
        ids_processed=len(stage2["run"].ids_processed), limit=args.limit, films_out=films,
    )
    report = pd.concat([stage2["report"], report3], ignore_index=True)
    load.write_flatten_outputs(
        films, talent, run.join_report, quarantine, reconciliation, report, out_dir=out_dir
    )
    seconds = time.perf_counter() - t0

    roles = talent["role"].value_counts()
    n_collections = int(films["collection_id"].nunique())
    n_franchise = int(films["is_franchise"].sum())
    no_director = int((films["n_directors"] == 0).sum())
    few_leads = int((films["n_lead_actors"] < config.LEAD_ACTOR_COUNT).sum())
    date_empty = int((films["release_date_raw"] == "").sum())
    date_bad = int(films["release_date_unparseable"].sum())
    zero_budget = int((films["budget"] == 0).sum())
    zero_revenue = int((films["revenue"] == 0).sum())
    n_passed, n_failed = int(report3["passed"].sum()), int((~report3["passed"]).sum())
    joins = run.join_report

    record.update(
        {
            "films_rows": len(films),
            "talent_rows": len(talent),
            "talent_by_role": {k: int(v) for k, v in roles.items()},
            "films_with_no_director": no_director,
            "films_with_fewer_than_3_leads": few_leads,
            "release_date_empty": date_empty,
            "release_date_unparseable": date_bad,
            "zero_budget": zero_budget,
            "zero_revenue": zero_revenue,
            "franchise_films": n_franchise,
            "distinct_collections": n_collections,
            "checks_passed": record["checks_passed"] + n_passed,
            "checks_failed": record["checks_failed"] + n_failed,
        }
    )
    record["seconds"]["flatten"] = round(seconds, 4)

    print()
    print("Stage 3: flatten and join")
    print(f"  films        {len(films)} rows (one per film), {len(run.quarantine)} quarantined at this stage")
    print(f"  franchise    {n_franchise} films in {n_collections} collections; "
          f"{len(films) - n_franchise} standalone")
    print(f"  talent       {len(talent)} rows: {int(roles.get('lead_actor', 0))} lead actors, "
          f"{int(roles.get('director', 0))} directors")
    print(f"  gaps         {no_director} films with no director | {few_leads} with fewer than "
          f"{config.LEAD_ACTOR_COUNT} lead actors | {date_empty} empty release dates")
    print(f"  money        {zero_budget} films with budget 0 | {zero_revenue} with revenue 0   "
          "(kept; decided in stage 4)")
    added = int((joins["result_rows"] - joins["left_rows"]).clip(lower=0).sum())
    lost = int((joins["left_rows"] - joins["result_rows"]).clip(lower=0).sum())
    print(f"  joins        {len(joins)} proven: {added} rows added, {lost} rows lost, "
          f"{int(joins['left_only'].sum())} unmatched")
    print(f"  imdb check   {report3.loc[report3['check_id'] == 'I-01', 'detail'].iloc[0]}")
    print(f"  checks       {n_passed} passed, {n_failed} failed")
    print(f"  time         {seconds:.2f} s")
    return {"films": films, "quarantine": quarantine, "reconciliation": reconciliation, "report": report}


def _num(value, fmt="{:.2f}") -> str:
    return "n/a" if pd.isna(value) else fmt.format(value)


def _stage4(stage3: dict, record: dict, out_dir: Path) -> dict:
    t0 = time.perf_counter()
    films_clean = clean.add_flags(stage3["films"])
    review = clean.build_review_list(films_clean)
    report4 = checks.check_clean_stage(films_clean)
    report = pd.concat([stage3["report"], report4], ignore_index=True)
    n_usable = int(films_clean["roi_usable"].sum())
    reconciliation = load.add_usable_multiple_row(stage3["reconciliation"], n_usable)
    load.write_clean_outputs(films_clean, review, reconciliation, report, out_dir=out_dir)
    seconds = time.perf_counter() - t0

    f = films_clean
    reasons = f["roi_exclusion_reason"].value_counts()
    flags = {
        "units_error_likely": int(f["units_error_likely"].sum()),
        "possible_micro_budget": int(f["possible_micro_budget"].sum()),
        "roi_extreme": int(f["roi_extreme"].sum()),
        "sequel_like_title": int(f["sequel_like_title"].sum()),
        "possible_same_film": int(f["possible_same_film"].sum()),
    }
    in_window = f[f["in_window_2000"]]
    n_franchise_w = int(in_window["is_franchise"].sum())
    no_year = int(f["release_year"].isna().sum())
    n_passed, n_failed = int(report4["passed"].sum()), int((~report4["passed"]).sum())

    record.update(
        {
            "roi_usable": n_usable,
            "roi_excluded_by_reason": {k: int(v) for k, v in reasons.items() if k},
            "flag_counts": flags,
            "films_in_2000_window": len(in_window),
            "films_without_year": no_year,
            "checks_passed": record["checks_passed"] + n_passed,
            "checks_failed": record["checks_failed"] + n_failed,
        }
    )
    record["seconds"]["clean"] = round(seconds, 4)

    excluded = ", ".join(
        f"{int(reasons.get(key, 0))} {label}" for key, label in (
            ("not released", "not released"), ("budget not reported", "budget 0"),
            ("revenue not reported", "revenue 0"), ("likely units error", "units error"))
    )
    print()
    print("Stage 4: clean and flag")
    print(f"  usable multiple   {n_usable} of {len(f)} films  (excluded: {excluded})")
    print(f"  review list       {flags['units_error_likely']} units | {flags['possible_micro_budget']} "
          f"micro-budget | {flags['roi_extreme']} extreme multiples | {flags['sequel_like_title']} "
          f"sequel-like standalones | {flags['possible_same_film']} possible same film")
    print(f"  2000 onward       {len(in_window)} films ({n_franchise_w} franchise, "
          f"{len(in_window) - n_franchise_w} standalone); {no_year} without a year")
    print(f"  checks            {n_passed} passed, {n_failed} failed")
    return {"films_clean": films_clean, "report": report, "quarantine": stage3["quarantine"],
            "films": stage3["films"]}


def _stage5(stage4: dict, args, record: dict, out_dir: Path) -> None:
    t0 = time.perf_counter()
    f = stage4["films_clean"]
    kpis_all, kpis_2000 = metrics.window_kpis(f)
    kpis = pd.concat([kpis_all, kpis_2000], ignore_index=True)
    again = pd.concat(metrics.window_kpis(f), ignore_index=True)  # C-25: a second computation
    comparison = metrics.compare_windows(kpis_all, kpis_2000)
    i01 = transform.imdb_crossref(stage4["films"], stage4["quarantine"][stage4["quarantine"]["stage"] == "load"])
    impact = metrics.decision_impact(f, stage4["quarantine"], i01)
    report5 = checks.check_measure_stage(kpis_all, kpis_2000, f, kpis_rerun=again)
    report = pd.concat([stage4["report"], report5], ignore_index=True)
    load.write_measure_outputs(kpis, comparison, impact, report, out_dir=out_dir)
    seconds = time.perf_counter() - t0

    disagree = metrics.disagreeing_measures(comparison)
    cannot = metrics.incomparable_measures(comparison)
    changed = impact[impact["leader_changes"]]
    changes = [f"{d} ({w})" for d, w in zip(changed["decision"], changed["window"])]
    n_passed, n_failed = int(report5["passed"].sum()), int((~report5["passed"]).sum())
    record.update(
        {
            "windows_disagree": bool(disagree),
            "windows_disagree_measures": disagree,
            "decision_changes_leader": changes,
            "checks_passed": record["checks_passed"] + n_passed,
            "checks_failed": record["checks_failed"] + n_failed,
        }
    )
    record["seconds"]["measure"] = round(seconds, 4)

    print()
    print("Stage 5: measures")
    print(f"  {'window':<12}  {'group':<11}{'films':>6}{'usable':>8}{'median':>8}{'mean':>8}"
          f"{'w/o top':>9}{'total/total':>13}{'votes(med)':>12}")
    for row in kpis.itertuples(index=False):  # a loop over the four printed rows, not over films
        print(f"  {row.window:<12}  {row.group:<11}{row.n_films:>6}{row.n_roi_usable:>8}"
              f"{_num(row.median_roi):>8}{_num(row.mean_roi):>8}{_num(row.median_roi_without_top):>9}"
              f"{_num(row.aggregate_roi):>13}{_num(row.median_vote_count, '{:.0f}'):>12}")
    if disagree:
        print(f"  WINDOWS DISAGREE: {', '.join(disagree)}")
    elif cannot:
        print(f"  windows       cannot compare on {', '.join(cannot)} (a group has no usable films)")
    else:
        print("  windows       agree on all measures")
    if changes:
        for d, w in zip(changed["decision"], changed["window"]):
            print(f"  decisions     {d} changes the leader in {w}")
    else:
        print("  decisions     none changes the leader")
    print(f"  checks        {n_passed} passed, {n_failed} failed")
    print(f"  time          clean {record['seconds']['clean']:.2f} s | measure {seconds:.2f} s")
    if args.limit:
        print(f"Outputs written to {_display_path(out_dir)}/ "
              f"(LIMITED RUN; full results in {_display_path(config.OUT_DIR)}/ unchanged)")
    else:
        print(f"Outputs written to {_display_path(out_dir)}/")


def main(argv=None, session=None) -> int:
    """Run the pipeline. `session` lets tests pass a fake in place of the network."""
    args = _parse_args(argv)
    try:
        key = config.get_api_key()
    except PipelineStopError:
        key = None  # a fully cached run needs no key; the fetch stage raises if it does
    out_dir = config.LIMITED_OUT_DIR if args.limit else config.OUT_DIR
    record: dict = {"seconds": {}, "stopped": None, "output_dir": _display_path(out_dir)}
    code = 0
    try:
        stage1 = _stage1(record, out_dir)
        stage2 = _stage2(stage1, args, session, key, record, out_dir)
        stage3 = _stage3(stage1, stage2, args, record, out_dir)
        stage4 = _stage4(stage3, record, out_dir)
        _stage5(stage4, args, record, out_dir)
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
