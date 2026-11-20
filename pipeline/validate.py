"""Quarantine rules: reject bad rows with a reason and the stage that caught them."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from pipeline import config

# Rule order; also the order used in the reconciliation table.
REASON_DETAIL = {
    "blank": "Empty value",
    "placeholder_text": "Placeholder text, no id",
    "imdb_id_not_tmdb": "IMDb id format, not a TMDb id; not resolved in this analysis (see ADR-002)",
    "not_positive": "Zero or negative; not a valid TMDb id",
    "decimal_form": "Number written with a decimal point (spreadsheet export?); not auto-corrected",
    "invalid_text": "Not a whole number",
    "repeat": "Same id listed more than once; first occurrence kept",
}
REASON_ORDER = list(REASON_DETAIL)

MAX_ID_DIGITS = 18  # keeps the value inside int64
_TOO_LONG_DETAIL = f"Too many digits to be an id (more than {MAX_ID_DIGITS})"


def classify_ids(
    raw: pd.DataFrame, run_at: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Give every raw row exactly one class; return (ids_to_fetch, quarantine)."""
    run_at = run_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    df = raw.sort_values("line_number").reset_index(drop=True)
    raw_value = df["raw_value"].astype(str)
    value = raw_value.str.strip()

    digits = value.str.fullmatch(r"[0-9]+")
    is_zero = digits & (value.str.lstrip("0") == "")
    too_long = digits & (value.str.lstrip("0").str.len() > MAX_ID_DIGITS)

    # First matching rule wins (np.select takes the first True).
    rules = [
        ("blank", value == ""),
        ("placeholder_text", value.str.lower().isin(config.PLACEHOLDER_VALUES)),
        ("imdb_id_not_tmdb", value.str.fullmatch(r"tt[0-9]+", case=False)),
        ("not_positive", value.str.fullmatch(r"-[0-9]+") | is_zero),
        ("decimal_form", value.str.fullmatch(r"[0-9]+\.[0-9]+")),
        ("invalid_text", ~digits | too_long),
    ]
    conditions = [mask.to_numpy(dtype=bool) for _, mask in rules]
    reason_code = np.select(conditions, [code for code, _ in rules], default="")
    reason_detail = np.select(
        conditions, [REASON_DETAIL[code] for code, _ in rules], default=""
    )
    reason_detail = np.where(
        (reason_code == "invalid_text") & too_long.to_numpy(dtype=bool),
        _TOO_LONG_DETAIL,
        reason_detail,
    )

    df = df.assign(
        value=value,
        reason_code=reason_code,
        reason_detail=reason_detail,
        was_padded=value != raw_value,
    )

    valid = df[df["reason_code"] == ""].copy()
    valid["tmdb_id"] = valid["value"].astype("int64")
    valid["leading_zero_normalised"] = valid["value"].str.match(r"^0[0-9]")
    valid["first_line_number"] = valid.groupby("tmdb_id")["line_number"].transform("min")
    valid["n_occurrences"] = valid.groupby("tmdb_id")["line_number"].transform("size")
    is_repeat = valid["line_number"] != valid["first_line_number"]

    repeats = valid[is_repeat].copy()
    repeats["reason_code"] = "repeat"
    repeats["reason_detail"] = "Repeat of line " + repeats["first_line_number"].astype(str)

    firsts = valid[~is_repeat]
    ids_to_fetch = (
        pd.DataFrame(
            {
                "tmdb_id": firsts["tmdb_id"].astype("int64"),
                "first_line_number": firsts["first_line_number"],
                "n_occurrences": firsts["n_occurrences"],
                "was_padded": firsts["was_padded"],
                "leading_zero_normalised": firsts["leading_zero_normalised"],
                "flag_large_id": firsts["tmdb_id"] > config.LARGE_ID_REVIEW_THRESHOLD,
            }
        )
        .sort_values("first_line_number")
        .reset_index(drop=True)
    )

    rejected = pd.concat([df[df["reason_code"] != ""], repeats])
    quarantine = (
        rejected[["line_number", "raw_value", "reason_code", "reason_detail"]]
        .assign(stage="load", run_at=run_at)
        .sort_values("line_number")
        .reset_index(drop=True)
    )
    return ids_to_fetch, quarantine
