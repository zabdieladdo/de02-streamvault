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
