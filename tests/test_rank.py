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


# --- middle entries -----------------------------------------------------------------

def entries_for(rows):
    f = flagged(rows)
    return rank.middle_entry_test(f, rank.build_bundles(f))


def test_positions_follow_release_date_not_input_order():
    rows = [
        {"tmdb_id": 4, "title": "late", "franchise": 1, "date": "2012-01-01", **money(4)},
        {"tmdb_id": 1, "title": "open", "franchise": 1, "date": "1999-01-01", **money(8)},
        {"tmdb_id": 3, "title": "mid2", "franchise": 1, "date": "2005-01-01", **money(2)},
        {"tmdb_id": 2, "title": "mid1", "franchise": 1, "date": "2001-01-01", **money(6)},
    ]
    ep, _ = entries_for(rows)
    assert list(ep["title"]) == ["open", "mid1", "mid2", "late"]
    assert list(ep["order_in_bundle"]) == [1, 2, 3, 4]
    assert list(ep["position"]) == ["opener", "middle", "middle", "latest"]
    assert list(ep["ratio_to_opener"].iloc[1:]) == [0.75, 0.25, 0.5]
    assert pd.isna(ep["ratio_to_opener"].iloc[0])


def test_same_day_release_is_ordered_by_film_id():
    rows = [{"tmdb_id": 9, "title": "b", "franchise": 1, "date": "2000-05-05", **money(2)},
            {"tmdb_id": 3, "title": "a", "franchise": 1, "date": "2000-05-05", **money(3)},
            {"tmdb_id": 5, "title": "c", "franchise": 1, "date": "2001-05-05", **money(4)}]
    ep, _ = entries_for(rows)
    assert list(ep["title"]) == ["a", "b", "c"]
    assert list(ep["position"]) == ["opener", "middle", "latest"]


def test_two_film_bundle_is_not_tested_and_three_film_bundle_has_one_middle():
    rows = bundle_rows(1, [2, 3]) + bundle_rows(2, [1, 2, 3], base_id=10)
    ep, summary = entries_for(rows)
    assert set(ep["collection_id"]) == {2}
    assert (ep["position"] == "middle").sum() == 1
    assert summary.set_index("measure").loc["bundles tested", "value"] == 1


def test_each_tested_bundle_has_one_opener_one_latest_and_all_its_films():
    rows = bundle_rows(1, [2, 3, 4, 5]) + bundle_rows(2, [1, 2, 3], base_id=10) + bundle_rows(3, [9, 9], base_id=20)
    ep, _ = entries_for(rows)
    by = ep.groupby("collection_id")["position"].value_counts().unstack(fill_value=0)
    assert (by["opener"] == 1).all() and (by["latest"] == 1).all()
    assert ep.groupby("collection_id").size().to_dict() == {1: 4, 2: 3}


def test_unusable_film_is_left_out_of_the_positions():
    rows = bundle_rows(1, [2, 3, 4, 5])
    rows[1] = {**rows[1], "budget": 0}
    ep, _ = entries_for(rows)
    assert len(ep) == 3 and "1-2" not in set(ep["title"])


def test_a_long_series_cannot_outweigh_a_short_one():
    x = [{"tmdb_id": 1, "title": "x-open", "franchise": 1, "date": "2000-01-01", **money(4)}]
    x += [{"tmdb_id": 2 + i, "title": f"x-mid{i}", "franchise": 1, "date": f"200{1 + i}-01-01", **money(2)} for i in range(5)]
    x += [{"tmdb_id": 8, "title": "x-last", "franchise": 1, "date": "2010-01-01", **money(4)}]
    y = [{"tmdb_id": 11, "title": "y-open", "franchise": 2, "date": "2000-01-01", **money(2)},
         {"tmdb_id": 12, "title": "y-mid", "franchise": 2, "date": "2003-01-01", **money(4)},
         {"tmdb_id": 13, "title": "y-last", "franchise": 2, "date": "2010-01-01", **money(2)}]
    _, summary = entries_for(x + y)
    s = summary.set_index("measure")
    assert s.loc["middle films tested", "value"] == 6
    assert s.loc["within-bundle median ratio, middle to opener", "value"] == 1.25  # not 0.5
    assert s.loc["bundles where middle entries trail the opener", "value"] == 1
    assert s.loc["share of bundles where middle entries trail the opener", "value"] == 0.5
    assert s.loc["pooled median multiple: middle", "value"] == 2  # display only
    assert s.loc["within-bundle median ratio, latest to opener", "value"] == 1.0  # both latest films equal their openers


def test_summary_carries_the_opener_bias_note():
    _, summary = entries_for(bundle_rows(1, [2, 3, 4]))
    note = summary.set_index("measure").loc["note", "note"]
    assert "Openers are selected winners" in note and "partly built in" in note


def test_no_rankable_bundle_gives_empty_entries_and_a_summary():
    ep, summary = entries_for(bundle_rows(1, [2, 3]))
    assert len(ep) == 0 and list(ep.columns) == rank.ENTRY_COLUMNS
    s = summary.set_index("measure")
    assert s.loc["bundles tested", "value"] == 0
    assert pd.isna(s.loc["within-bundle median ratio, middle to opener", "value"])
