"""Stage 6: rank bundles, test middle entries, measure talent signal, build the shortlist."""
import numpy as np
import pandas as pd

from pipeline import config


def reference_values(films_clean: pd.DataFrame) -> dict:
    """The two list-wide medians every relative figure is measured against (all years)."""
    usable = films_clean["roi_usable"].astype(bool)
    roi = films_clean.loc[usable, "roi"].astype("float64")
    votes = films_clean["vote_count"].astype("float64")
    return {
        "list_median_roi": float(roi.median()) if len(roi) else float("nan"),
        "list_median_votes": float(votes.median()) if len(votes) else float("nan"),
        "n_usable": int(usable.sum()),
    }


BUNDLE_COLUMNS = [
    "collection_id", "collection_name", "n_on_list", "n_roi_usable", "median_roi", "mean_roi",
    "aggregate_roi", "weakest_roi", "weakest_title", "median_vote_count", "first_year", "last_year",
    "straddles_2000", "n_2000_on", "median_roi_2000_on", "thin_2000_on", "rankable", "bundle_rank",
    "vote_rank", "relative_value", "walkaway_ratio",
]


def build_bundles(films_clean: pd.DataFrame) -> pd.DataFrame:
    """One row per collection, from the franchise films on the list.

    Every figure is based on the films of the collection that are on the list; the full bundle a
    studio sells may hold more films.
    """
    ref = reference_values(films_clean)
    f = films_clean[films_clean["is_franchise"].astype(bool) & films_clean["collection_id"].notna()]
    usable = f["roi_usable"].astype(bool)
    f = f.sort_values("tmdb_id").assign(
        collection_id=lambda d: d["collection_id"].astype("int64"),
        roi_u=lambda d: d["roi"].astype("float64").where(d["roi_usable"].astype(bool)),
        rev_u=lambda d: d["revenue"].astype("float64").where(d["roi_usable"].astype(bool)),
        bud_u=lambda d: d["budget"].astype("float64").where(d["roi_usable"].astype(bool)),
        votes=lambda d: d["vote_count"].astype("float64"),
        year=lambda d: d["release_year"].astype("float64"),
    )
    g = f.groupby("collection_id")
    weakest = f[f["roi_u"].notna()]
    weakest = weakest.loc[weakest.groupby("collection_id")["roi_u"].idxmin()].set_index("collection_id")
    recent = f[f["in_window_2000"].astype(bool)].groupby("collection_id")

    b = pd.DataFrame(
        {
            "collection_name": g["collection_name"].first().astype("object"),
            "n_on_list": g.size(),
            "n_roi_usable": g["roi_usable"].sum().astype("int64"),
            "median_roi": g["roi_u"].median(),
            "mean_roi": g["roi_u"].mean(),
            "aggregate_roi": g["rev_u"].sum(min_count=1) / g["bud_u"].sum(min_count=1),
            "weakest_roi": weakest["roi_u"],
            "weakest_title": weakest["title"].astype("object"),
            "median_vote_count": g["votes"].median(),
            "first_year": g["year"].min(),
            "last_year": g["year"].max(),
            "n_2000_on": recent.size(),
            "median_roi_2000_on": recent["roi_u"].median(),
        }
    )
    b["n_2000_on"] = b["n_2000_on"].fillna(0).astype("int64")
    b["straddles_2000"] = (b["first_year"] < config.WINDOW_START_YEAR) & (b["last_year"] >= config.WINDOW_START_YEAR)
    b["thin_2000_on"] = (b["n_2000_on"] > 0) & (b["n_2000_on"] < config.MIN_BUNDLE_FOR_RANKING)
    b["rankable"] = b["n_roi_usable"] >= config.MIN_BUNDLE_FOR_RANKING

    b = b.reset_index()
    order = b[b["rankable"]].sort_values(
        ["median_roi", "median_vote_count", "collection_id"], ascending=[False, False, True]
    )
    b["bundle_rank"] = pd.Series(np.arange(1, len(order) + 1), index=order.index).reindex(b.index).astype("Int64")
    b["vote_rank"] = (
        b.loc[b["rankable"], "median_vote_count"].rank(method="min", ascending=False).reindex(b.index).astype("Int64")
    )
    b["relative_value"] = b["median_roi"] / ref["list_median_roi"]
    b["walkaway_ratio"] = b["weakest_roi"] / ref["list_median_roi"]
    b[["first_year", "last_year"]] = b[["first_year", "last_year"]].astype("Int64")
    b = b[BUNDLE_COLUMNS].sort_values(["bundle_rank", "collection_id"], na_position="last")
    return b.reset_index(drop=True)
