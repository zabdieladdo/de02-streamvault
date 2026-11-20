"""Stage 5: group measures for one window at a time, window comparison, decision impact."""
import numpy as np
import pandas as pd

from pipeline import config

GROUPS = ("franchise", "standalone")
KPI_COLUMNS = [
    "window", "group", "n_films", "n_roi_usable", "median_roi", "mean_roi",
    "median_roi_without_top", "shift_without_top", "top_film_title", "top_film_roi",
    "aggregate_roi", "median_vote_count", "mean_vote_count", "meets_min_group",
]


def _label(films: pd.DataFrame) -> pd.Series:
    return pd.Series(np.where(films["is_franchise"].astype(bool), "franchise", "standalone"),
                     index=films.index, name="group")


def group_kpis(films_clean: pd.DataFrame, window_name: str) -> pd.DataFrame:
    """One row per group (franchise, standalone) for the films given.

    The window is chosen by the caller, who passes the films in it. The same function serves
    every window. Groups are always both present, with zero films if need be.
    """
    films = films_clean.assign(group=_label(films_clean))
    usable = films[films["roi_usable"]].assign(
        roi=lambda d: d["roi"].astype("float64"),
        revenue=lambda d: d["revenue"].astype("float64"),
        budget=lambda d: d["budget"].astype("float64"),
    )
    by_all = films.groupby("group", dropna=False)
    by_use = usable.groupby("group", dropna=False)

    # Leave one out: rank the multiples inside each group, mask rank 1, take the median of the rest.
    rank = by_use["roi"].rank(method="first", ascending=False)
    rest = usable[rank > 1].groupby("group", dropna=False)["roi"].median()
    top = usable[rank == 1].set_index("group")

    votes = films["vote_count"].astype("float64")
    kpis = pd.DataFrame(
        {
            "n_films": by_all.size(),
            "n_roi_usable": by_use.size(),
            "median_roi": by_use["roi"].median(),
            "mean_roi": by_use["roi"].mean(),
            "median_roi_without_top": rest,
            "top_film_title": top["title"].astype("object"),
            "top_film_roi": top["roi"],
            "aggregate_roi": by_use["revenue"].sum() / by_use["budget"].sum(),
            "median_vote_count": votes.groupby(films["group"]).median(),
            "mean_vote_count": votes.groupby(films["group"]).mean(),
        }
    ).reindex(list(GROUPS))
    kpis[["n_films", "n_roi_usable"]] = kpis[["n_films", "n_roi_usable"]].fillna(0).astype("int64")
    kpis["shift_without_top"] = kpis["median_roi_without_top"] - kpis["median_roi"]
    kpis["meets_min_group"] = kpis["n_roi_usable"] >= config.MIN_GROUP_FOR_CONCLUSION
    kpis.index.name = "group"
    kpis = kpis.reset_index()
    kpis.insert(0, "window", window_name)
    return kpis[KPI_COLUMNS]


MEASURES = ("median_roi", "mean_roi", "aggregate_roi", "median_vote_count")
COMPARISON_COLUMNS = [
    "measure", "leader_all_years", "leader_2000_onward", "agree", "gap_all_years", "gap_2000_onward",
]


def _leader_and_gap(kpis: pd.DataFrame, measure: str) -> tuple[str, float]:
    """Which group is higher on a measure, and franchise minus standalone. Blank if not comparable."""
    values = kpis.set_index("group")[measure].reindex(list(GROUPS))
    if values.isna().any():
        return "", float("nan")
    gap = float(values["franchise"] - values["standalone"])
    return ("tie" if gap == 0 else "franchise" if gap > 0 else "standalone"), gap


def compare_windows(kpis_all: pd.DataFrame, kpis_2000: pd.DataFrame) -> pd.DataFrame:
    """One row per measure: who leads in each window, whether they agree, and the gaps.

    `agree` is true only when both windows name the same leader; a window where the groups
    cannot be compared (a group has no usable films) does not count as agreement.
    """
    rows = []
    for measure in MEASURES:  # a short fixed list of measures
        lead_a, gap_a = _leader_and_gap(kpis_all, measure)
        lead_b, gap_b = _leader_and_gap(kpis_2000, measure)
        rows.append(
            {
                "measure": measure, "leader_all_years": lead_a, "leader_2000_onward": lead_b,
                "agree": bool(lead_a != "" and lead_a == lead_b),
                "gap_all_years": gap_a, "gap_2000_onward": gap_b,
            }
        )
    return pd.DataFrame(rows, columns=COMPARISON_COLUMNS)


def disagreeing_measures(comparison: pd.DataFrame) -> list[str]:
    return comparison.loc[~comparison["agree"], "measure"].tolist()
