"""Run checks C-01 to C-27 and produce one pass/fail table."""
import pandas as pd

from pipeline import config
from pipeline.errors import PipelineStopError

STAGE = "load"


def _row(check_id: str, description: str, passed: bool, detail: str) -> dict:
    return {
        "check_id": check_id,
        "description": description,
        "stage": STAGE,
        "passed": bool(passed),
        "detail": detail,
    }


def check_load_stage(
    meta: dict,
    raw: pd.DataFrame,
    ids_to_fetch: pd.DataFrame,
    quarantine: pd.DataFrame,
) -> pd.DataFrame:
    """Checks for stage 1; returns check_id, description, stage, passed, detail."""
    rows = []

    # C-01: header and row count read without loss
    header_ok = str(meta["header"]).strip() == config.EXPECTED_HEADER
    count_ok = len(raw) == meta["raw_line_count"]
    rows.append(
        _row(
            "C-01",
            "Header and row count read without loss",
            header_ok and count_ok,
            f"header {meta['header']!r}; read {len(raw)} rows, counted {meta['raw_line_count']} lines",
        )
    )

    # C-02: every input line is accounted for exactly once
    accounted = pd.concat([ids_to_fetch["first_line_number"], quarantine["line_number"]])
    seen_once = accounted.value_counts().eq(1).all()
    same_set = set(accounted) == set(raw["line_number"])
    rows.append(
        _row(
            "C-02",
            "Every row classified exactly once",
            bool(seen_once) and same_set and len(accounted) == len(raw),
            f"{len(accounted)} classifications for {len(raw)} rows",
        )
    )

    # C-03: conservation
    non_repeat_quarantine = int((quarantine["reason_code"] != "repeat").sum())
    sum_ok = len(raw) == int(ids_to_fetch["n_occurrences"].sum()) + non_repeat_quarantine
    split_ok = len(raw) == len(ids_to_fetch) + len(quarantine)
    rows.append(
        _row(
            "C-03",
            "Conservation: raw = sent forward + quarantined",
            sum_ok and split_ok,
            f"raw {len(raw)} = to fetch {len(ids_to_fetch)} + quarantined {len(quarantine)}",
        )
    )

    # C-04: ids sent forward are unique
    rows.append(
        _row(
            "C-04",
            "Ids sent forward are unique",
            ids_to_fetch["tmdb_id"].is_unique,
            f"{len(ids_to_fetch)} ids, {ids_to_fetch['tmdb_id'].nunique()} distinct",
        )
    )

    # C-04b: review list, always passes
    large = ids_to_fetch.loc[ids_to_fetch["flag_large_id"], "tmdb_id"].tolist()
    rows.append(
        _row(
            "C-04b",
            "Large ids flagged, not removed",
            True,
            f"{len(large)} flagged for review: {', '.join(map(str, large)) or 'none'}",
        )
    )

    return pd.DataFrame(rows, columns=["check_id", "description", "stage", "passed", "detail"])


def raise_if_conservation_failed(report: pd.DataFrame) -> None:
    """C-03 failing means rows were lost or invented; stop the run."""
    c03 = report.loc[report["check_id"] == "C-03"]
    if not c03.empty and not bool(c03["passed"].iloc[0]):
        raise PipelineStopError(f"C-03 failed: {c03['detail'].iloc[0]}")
