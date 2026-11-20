"""Stage 7: write the result tables to out/."""
import json

import pandas as pd

from pipeline import config
from pipeline.validate import REASON_DETAIL, REASON_ORDER


def build_reconciliation(rows_raw: int, ids_to_fetch: pd.DataFrame, quarantine: pd.DataFrame) -> pd.DataFrame:
    """Raw count, one row per quarantine reason, then the count sent to the API stage."""
    counts = quarantine["reason_code"].value_counts()
    records = [{"stage": "Raw rows in file", "rows": rows_raw, "delta": pd.NA, "reason": ""}]
    remaining = rows_raw
    ordered = [c for c in REASON_ORDER if c in counts.index]
    ordered += [c for c in counts.index if c not in REASON_ORDER]
    for code in ordered:
        n = int(counts[code])
        remaining -= n
        records.append(
            {
                "stage": f"Quarantined: {code}",
                "rows": remaining,
                "delta": -n,
                "reason": REASON_DETAIL.get(code, code),
            }
        )
    records.append(
        {"stage": "Sent to the API stage", "rows": len(ids_to_fetch), "delta": pd.NA, "reason": ""}
    )
    out = pd.DataFrame(records)
    out["rows"] = out["rows"].astype("int64")
    out["delta"] = out["delta"].astype("Int64")
    return out


def write_stage1_outputs(
    ids_to_fetch: pd.DataFrame,
    quarantine: pd.DataFrame,
    reconciliation: pd.DataFrame,
    checks: pd.DataFrame,
) -> None:
    """Write the four stage 1 CSVs to OUT_DIR (UTF-8, no index)."""
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    tables = {
        "ids_to_fetch.csv": ids_to_fetch,
        "quarantine.csv": quarantine,
        "reconciliation.csv": reconciliation,
        "checks_report.csv": checks,
    }
    for name, table in tables.items():
        table.to_csv(config.OUT_DIR / name, index=False, encoding="utf-8")


def append_run_log(record: dict) -> None:
    """Append one JSON line to out/run_log.jsonl."""
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.OUT_DIR / "run_log.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
