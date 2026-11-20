"""Stage 7: write the result tables to out/."""
import json

import pandas as pd

from pipeline import config
from pipeline.fetch import REASON_DETAIL as FETCH_REASON_DETAIL
from pipeline.fetch import REASON_ORDER as FETCH_REASON_ORDER
from pipeline.validate import REASON_DETAIL, REASON_ORDER


def build_reconciliation(
    rows_raw: int,
    ids_to_fetch: pd.DataFrame,
    quarantine: pd.DataFrame,
    fetched_ids: pd.DataFrame | None = None,
    ids_processed: int | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Raw count, one row per quarantine reason, then the count sent to each next stage.

    Without `fetched_ids` it stops at "Sent to the API stage" (stage 1 only).
    """
    records = [{"stage": "Raw rows in file", "rows": rows_raw, "delta": pd.NA, "reason": ""}]

    def add_reasons(frame: pd.DataFrame, remaining: int, order: list, detail: dict) -> int:
        counts = frame["reason_code"].value_counts()
        codes = [c for c in order if c in counts.index]
        codes += [c for c in counts.index if c not in order]
        for code in codes:
            n = int(counts[code])
            remaining -= n
            records.append(
                {
                    "stage": f"Quarantined: {code}",
                    "rows": remaining,
                    "delta": -n,
                    "reason": detail.get(code, code),
                }
            )
        return remaining

    add_reasons(quarantine[quarantine["stage"] == "load"], rows_raw, REASON_ORDER, REASON_DETAIL)
    records.append(
        {"stage": "Sent to the API stage", "rows": len(ids_to_fetch), "delta": pd.NA, "reason": ""}
    )

    if fetched_ids is not None:
        remaining = len(ids_to_fetch)
        if ids_processed is not None and ids_processed < len(ids_to_fetch):
            skipped = len(ids_to_fetch) - ids_processed
            remaining -= skipped
            records.append(
                {
                    "stage": "Not processed (limited run)",
                    "rows": remaining,
                    "delta": -skipped,
                    "reason": f"--limit {limit}",
                }
            )
        add_reasons(
            quarantine[quarantine["stage"] == "fetch"],
            remaining,
            FETCH_REASON_ORDER,
            FETCH_REASON_DETAIL,
        )
        records.append(
            {
                "stage": "Fetched with details and credits",
                "rows": len(fetched_ids),
                "delta": pd.NA,
                "reason": "",
            }
        )

    out = pd.DataFrame(records)
    out["rows"] = out["rows"].astype("int64")
    out["delta"] = out["delta"].astype("Int64")
    return out


def build_fetched_ids(ids_processed: pd.DataFrame, results: pd.DataFrame, quarantine: pd.DataFrame) -> pd.DataFrame:
    """One row per id that went forward, with where each response came from."""
    cols = [
        "tmdb_id", "first_line_number", "details_source", "credits_source",
        "details_attempts", "credits_attempts", "details_fetched_at", "credits_fetched_at",
    ]
    quarantined = set(quarantine.loc[quarantine["stage"] == "fetch", "raw_value"].astype(int))
    forward = ids_processed[~ids_processed["tmdb_id"].isin(quarantined)][["tmdb_id", "first_line_number"]]

    def side(endpoint):
        part = results[results["endpoint"] == endpoint].set_index("tmdb_id")
        return pd.DataFrame(
            {
                f"{endpoint}_source": part["source"],
                f"{endpoint}_attempts": part["attempts"],
                f"{endpoint}_fetched_at": part["fetched_at"],
            }
        )

    out = forward.set_index("tmdb_id").join(side("details")).join(side("credits")).reset_index()
    return out[cols].sort_values("first_line_number").reset_index(drop=True)


def write_stage1_outputs(
    ids_to_fetch: pd.DataFrame,
    quarantine: pd.DataFrame,
    reconciliation: pd.DataFrame,
    checks: pd.DataFrame,
    out_dir=None,
) -> None:
    """Write the four stage 1 CSVs to out_dir, default OUT_DIR (UTF-8, no index)."""
    out_dir = out_dir or config.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "ids_to_fetch.csv": ids_to_fetch,
        "quarantine.csv": quarantine,
        "reconciliation.csv": reconciliation,
        "checks_report.csv": checks,
    }
    for name, table in tables.items():
        table.to_csv(out_dir / name, index=False, encoding="utf-8")


def append_run_log(record: dict) -> None:
    """Append one JSON line to out/run_log.jsonl."""
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.OUT_DIR / "run_log.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_fetch_outputs(
    fetched_ids: pd.DataFrame,
    quarantine: pd.DataFrame,
    reconciliation: pd.DataFrame,
    checks: pd.DataFrame,
    out_dir=None,
) -> None:
    """Rewrite the shared tables with the fetch stage added, and write fetched_ids.csv."""
    out_dir = out_dir or config.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "fetched_ids.csv": fetched_ids,
        "quarantine.csv": quarantine,
        "reconciliation.csv": reconciliation,
        "checks_report.csv": checks,
    }
    for name, table in tables.items():
        table.to_csv(out_dir / name, index=False, encoding="utf-8")
