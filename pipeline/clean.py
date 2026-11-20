"""Stage 4: add usability flags to the films table. Rows are flagged, never removed."""
import numpy as np
import pandas as pd

from pipeline import config


def _true(mask: pd.Series) -> pd.Series:
    """A plain bool Series, with missing treated as False."""
    return mask.fillna(False).astype(bool)


def add_flags(films: pd.DataFrame) -> pd.DataFrame:
    """Return the films table with flag columns added. No row is removed and no value corrected."""
    out = films.copy()
    budget = out["budget"].astype("float64").fillna(0)
    revenue = out["revenue"].astype("float64").fillna(0)
    votes = out["vote_count"].astype("float64").fillna(0)

    out["is_released"] = _true(out["status"].astype("string").eq("Released"))

    out["budget_suspect_units"] = budget.between(1, config.SMALL_MONEY_THRESHOLD)
    out["revenue_suspect_units"] = revenue.between(1, config.SMALL_MONEY_THRESHOLD)
    suspect = out["budget_suspect_units"] | out["revenue_suspect_units"]
    well_known = votes >= config.UNITS_ERROR_VOTE_THRESHOLD
    out["units_error_likely"] = suspect & well_known
    out["possible_micro_budget"] = suspect & ~well_known

    out["budget_usable"] = budget > 0  # zero means not reported (S04)
    out["revenue_usable"] = (revenue > 0) & out["is_released"]  # S03, S20
    out["roi_usable"] = out["budget_usable"] & out["revenue_usable"] & ~out["units_error_likely"]
    out["roi_exclusion_reason"] = np.select(
        [
            ~out["is_released"],
            ~out["budget_usable"],
            revenue <= 0,
            out["units_error_likely"],
        ],
        ["not released", "budget not reported", "revenue not reported", "likely units error"],
        default="",
    )

    safe_budget = budget.where(budget > 0)  # never divide by zero
    out["roi"] = (revenue / safe_budget).where(out["roi_usable"])
    out["roi_extreme"] = (out["roi"] > config.ROI_HIGH_REVIEW) | (out["roi"] < config.ROI_LOW_REVIEW)

    out["in_window_2000"] = _true(out["release_year"].ge(config.WINDOW_START_YEAR))

    title = out["title"].astype("string")
    out["sequel_like_title"] = ~out["is_franchise"].astype(bool) & _true(
        title.str.contains(config.SEQUEL_TITLE_PATTERN, regex=True)  # case-sensitive on purpose
    )
    letters = title.str.casefold().str.replace(r"[\W_]+", "", regex=True).fillna("")
    year = out["release_year"].astype("string").fillna("")
    out["title_year_key"] = letters + "|" + year
    out["possible_same_film"] = out["title_year_key"].duplicated(keep=False) & (letters != "")
    return out
