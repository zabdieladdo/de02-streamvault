"""Stage 6: bundles, middle entries, talent signal, shortlist, deal note. Hand-checkable fixtures."""
import numpy as np
import pandas as pd
import pytest

from pipeline import clean, config, rank
from tests.conftest import make_films, make_talent


def money(roi):
    return {"budget": 1_000_000, "revenue": int(round(roi * 1_000_000))}


def flagged(rows):
    return clean.add_flags(make_films(rows))


def bundle_rows(collection, rois, years=None, votes=1000, base_id=0):
    years = years or [2005 + i for i in range(len(rois))]
    return [
        {"tmdb_id": base_id + i + 1, "title": f"{collection}-{i + 1}", "franchise": collection, "year": y,
         "votes": votes, **money(r)}
        for i, (r, y) in enumerate(zip(rois, years))
    ]


def bundles_for(rows):
    return rank.build_bundles(flagged(rows)).set_index("collection_id")


# --- bundles ------------------------------------------------------------------------

def test_reference_values():
    f = flagged([money(2), money(4), {**money(6), "votes": 10}, {"budget": 0, "votes": 5000}])
    ref = rank.reference_values(f)
    assert ref["list_median_roi"] == 4 and ref["n_usable"] == 3
    assert ref["list_median_votes"] == 1000  # votes 1000, 1000, 10, 5000


def test_bundle_measures_are_exact():
    rows = bundle_rows(7, [1, 2, 3, 10], years=[1990, 1995, 2005, 2010])
    rows += [{"title": "x", **money(4)}]  # a standalone: not in any bundle
    b = bundles_for(rows).loc[7]
    assert b["n_on_list"] == 4 and b["n_roi_usable"] == 4
    assert b["median_roi"] == 2.5 and b["mean_roi"] == 4.0
    assert b["aggregate_roi"] == 16 / 4  # total revenue 16M over total budget 4M
    assert b["weakest_roi"] == 1 and b["weakest_title"] == "7-1"
    assert b["first_year"] == 1990 and b["last_year"] == 2010
    assert b["n_2000_on"] == 2 and b["median_roi_2000_on"] == 6.5
    assert b["rankable"] and b["bundle_rank"] == 1 and b["vote_rank"] == 1


def test_bundle_with_two_films_is_not_rankable():
    rows = bundle_rows(1, [2, 3]) + bundle_rows(2, [1, 2, 3], base_id=10)
    b = bundles_for(rows)
    assert not b.loc[1, "rankable"] and pd.isna(b.loc[1, "bundle_rank"]) and pd.isna(b.loc[1, "vote_rank"])
    assert b.loc[2, "rankable"] and b.loc[2, "bundle_rank"] == 1


def test_unusable_films_do_not_count_toward_ranking():
    rows = bundle_rows(1, [2, 3, 4])
    rows[2] = {**rows[2], "budget": 0}
    b = bundles_for(rows).loc[1]
    assert b["n_on_list"] == 3 and b["n_roi_usable"] == 2 and not b["rankable"]


def test_tie_on_median_goes_to_higher_votes():
    rows = bundle_rows(1, [2, 3, 4], votes=500) + bundle_rows(2, [2, 3, 4], votes=9000, base_id=10)
    b = bundles_for(rows)
    assert b.loc[2, "bundle_rank"] == 1 and b.loc[1, "bundle_rank"] == 2
    assert b.loc[2, "vote_rank"] == 1


def test_ranks_run_best_median_first():
    rows = bundle_rows(1, [2, 3, 4]) + bundle_rows(2, [8, 9, 10], base_id=10) + bundle_rows(3, [5, 6, 7], base_id=20)
    b = bundles_for(rows)
    assert [b.loc[c, "bundle_rank"] for c in (2, 3, 1)] == [1, 2, 3]
    assert list(rank.build_bundles(flagged(rows))["collection_id"]) == [2, 3, 1]


def test_straddle_and_thin_from_2000():
    b = bundles_for(bundle_rows(1, [2, 3, 4], years=[1995, 1999, 2003])).loc[1]
    assert b["straddles_2000"] and b["n_2000_on"] == 1 and b["thin_2000_on"]
    assert b["median_roi_2000_on"] == 4


def test_bundle_with_no_films_from_2000_has_no_figure():
    b = bundles_for(bundle_rows(1, [2, 3, 4], years=[1980, 1983, 1986])).loc[1]
    assert b["n_2000_on"] == 0 and pd.isna(b["median_roi_2000_on"])
    assert not b["straddles_2000"] and not b["thin_2000_on"]


def test_all_films_from_2000_is_not_thin():
    b = bundles_for(bundle_rows(1, [2, 3, 4], years=[2001, 2004, 2008])).loc[1]
    assert b["n_2000_on"] == 3 and not b["thin_2000_on"] and not b["straddles_2000"]


def test_bundle_conservation():
    rows = (bundle_rows(1, [2, 3]) + bundle_rows(2, [1, 2, 3, 4], base_id=10)
            + [{"title": "solo", **money(3)}, {"title": "solo2", "franchise": True, **money(3)}])
    f = flagged(rows)
    b = rank.build_bundles(f)
    assert b["n_on_list"].sum() == int(f["is_franchise"].sum()) == 7


def test_relative_value_and_walkaway_are_ratios_to_the_list_median():
    rows = bundle_rows(1, [2, 4, 8]) + [{"title": "s", **money(2)}, {"title": "t", **money(4)}, {"title": "u", **money(6)}]
    f = flagged(rows)
    ref = rank.reference_values(f)
    b = rank.build_bundles(f).set_index("collection_id").loc[1]
    assert ref["list_median_roi"] == 4
    assert b["relative_value"] == 1.0 and b["walkaway_ratio"] == 0.5


def test_single_film_collection_is_listed_but_not_ranked():
    b = rank.build_bundles(flagged([{"title": "a", "franchise": 9, **money(3)}]))
    assert len(b) == 1 and not b.loc[0, "rankable"] and b.loc[0, "n_on_list"] == 1


def test_no_franchise_films_gives_an_empty_table():
    b = rank.build_bundles(flagged([{"title": "a", **money(3)}]))
    assert len(b) == 0 and list(b.columns) == rank.BUNDLE_COLUMNS
