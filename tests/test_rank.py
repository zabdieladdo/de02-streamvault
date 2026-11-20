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


# --- talent signal ------------------------------------------------------------------

LIST_MEDIAN = 4.0  # the fixtures below put films clearly above (8) or below (2) this


def standalone_films(rois):
    """Standalone films 1..n with the given multiples."""
    return [{"tmdb_id": i + 1, "title": f"S{i + 1}", **money(r)} for i, r in enumerate(rois)]


def signal_for(film_rows, talent_rows, list_median=LIST_MEDIAN, list_votes=1000.0):
    f = flagged(film_rows)
    return rank.talent_signal(make_talent(talent_rows), f, list_median, list_votes).set_index("person_id")


def test_each_collection_counts_once_per_person():
    rows = bundle_rows(5, [8, 8, 8]) + [{"tmdb_id": 10, "title": "solo", **money(2)}]
    talent = [(1, 7, "Ann", "lead_actor"), (2, 7, "Ann", "lead_actor"), (3, 7, "Ann", "lead_actor"),
              (10, 7, "Ann", "lead_actor")]
    s = signal_for(rows, talent).loc[7]
    assert s["n_films"] == 4 and s["n_titles"] == 2 and s["largest_unit_films"] == 3
    assert s["titles_above"] == 1 and s["hit_rate"] == 0.5
    assert s["signal"] == "too little evidence"  # three films, but only two independent titles


def test_two_thirds_counts_as_reliable():
    f = standalone_films([8, 8, 2])  # 2 of 3 titles above 4
    t = [(1, 1, "Ann", "director"), (2, 1, "Ann", "director"), (3, 1, "Ann", "director")]
    s = signal_for(f, t).loc[1]
    assert s["n_titles"] == 3 and s["titles_above"] == 2 and s["signal"] == "reliable"


def test_float_edge_holds_for_larger_groups():
    f = standalone_films([8] * 6 + [2] * 3)  # 6 of 9 = two thirds exactly
    t = [(i, 1, "Ann", "director") for i in range(1, 10)]
    assert signal_for(f, t).loc[1, "signal"] == "reliable"


def test_negative_and_mixed():
    f = standalone_films([2, 2, 2, 8, 8, 2, 2])
    t = [(1, 1, "Neg", "director"), (2, 1, "Neg", "director"), (3, 1, "Neg", "director"),
         (4, 2, "Mix", "director"), (5, 2, "Mix", "director"), (6, 2, "Mix", "director"), (7, 2, "Mix", "director")]
    s = signal_for(f, t)
    assert s.loc[1, "signal"] == "reliable negative" and s.loc[1, "titles_above"] == 0
    assert s.loc[2, "signal"] == "mixed" and s.loc[2, "n_titles"] == 4 and s.loc[2, "titles_above"] == 2


def test_promising_needs_two_titles_both_above():
    f = standalone_films([8, 8, 8, 2])
    t = [(1, 1, "Both", "director"), (2, 1, "Both", "director"),
         (3, 2, "Split", "director"), (4, 2, "Split", "director"),
         (1, 3, "One", "director")]
    s = signal_for(f, t)
    assert s.loc[1, "signal"] == "promising, too little evidence"
    assert s.loc[2, "signal"] == "too little evidence"
    assert s.loc[3, "signal"] == "too little evidence"


def test_director_and_lead_actor_are_separate_rows():
    f = standalone_films([8, 8, 8])
    t = [(i, 1, "Ann", "director") for i in (1, 2, 3)] + [(i, 1, "Ann", "lead_actor") for i in (1, 2)]
    sig = rank.talent_signal(make_talent(t), flagged(f), LIST_MEDIAN, 1000.0)
    assert len(sig) == 2 and set(sig["role"]) == {"director", "lead_actor"}
    by = sig.set_index("role")
    assert by.loc["director", "n_titles"] == 3 and by.loc["lead_actor", "n_titles"] == 2


def test_unusable_films_are_not_titles_but_still_count_as_films():
    rows = standalone_films([8, 8, 8])
    rows[2] = {**rows[2], "budget": 0}
    t = [(1, 1, "Ann", "director"), (2, 1, "Ann", "director"), (3, 1, "Ann", "director")]
    s = signal_for(rows, t).loc[1]
    assert s["n_films"] == 3 and s["n_titles"] == 2


def test_vote_hit_rate_sits_beside_the_multiple_hit_rate():
    rows = [{"tmdb_id": 1, "title": "a", "votes": 5000, **money(2)}, {"tmdb_id": 2, "title": "b", "votes": 5000, **money(2)},
            {"tmdb_id": 3, "title": "c", "votes": 10, **money(8)}]
    t = [(1, 1, "Ann", "director"), (2, 1, "Ann", "director"), (3, 1, "Ann", "director")]
    s = signal_for(rows, t).loc[1]
    assert s["titles_above"] == 1 and s["vote_titles_above"] == 2 and s["vote_hit_rate"] == pytest.approx(2 / 3)
    assert s["signal"] == "reliable negative"  # 1 of 3 sits exactly on the negative edge (1 - 2/3)


def test_signal_rows_are_ordered_by_role_signal_then_hit_rate():
    f = standalone_films([8, 8, 8, 2, 2, 2])
    t = [(1, 1, "Weak", "director"), (2, 1, "Weak", "director"), (3, 1, "Weak", "director")]  # 3 of 3 above
    t += [(4, 2, "Neg", "director"), (5, 2, "Neg", "director"), (6, 2, "Neg", "director")]
    t += [(1, 3, "Once", "director")]
    sig = rank.talent_signal(make_talent(t), flagged(f), LIST_MEDIAN, 1000.0)
    assert list(sig["name"]) == ["Weak", "Neg", "Once"]
    assert list(sig["signal"]) == ["reliable", "reliable negative", "too little evidence"]


def test_talent_join_keeps_every_row_and_flags_a_repeated_film_id():
    f = flagged(standalone_films([8, 8]))
    talent = make_talent([(1, 1, "A", "director"), (2, 1, "A", "director")])
    assert rank.talent_join_rows(talent, f) == (2, True)
    doubled = pd.concat([f, f.iloc[[0]]], ignore_index=True)
    rows, unique = rank.talent_join_rows(talent, doubled)
    assert rows == 3 and not unique  # the join would add a row: C-29 stops the run


# --- shortlist ----------------------------------------------------------------------

def shortlist_fixture(n_bundles=4):
    rows = []
    for c in range(1, n_bundles + 1):  # bundle c has median multiple 10 - c, so bundle 1 is best
        rows += bundle_rows(c, [9 - c, 10 - c, 11 - c], years=[1999, 2004, 2008], base_id=100 * c, votes=2000 - 100 * c)
    # eight standalones: multiples 20, 18, ... descending; votes rise as multiples fall
    rows += [{"tmdb_id": 1000 + i, "title": f"S{i}", "year": 2010 + i, "votes": 1000 + 1000 * i, **money(20 - 2 * i)}
             for i in range(8)]
    return flagged(rows)


def test_shortlist_has_three_five_and_one_audience_pick():
    f = shortlist_fixture()
    sl = rank.build_shortlist(rank.build_bundles(f), f)
    assert sl["list"].value_counts().to_dict() == {"standalone": 5, "franchise": 3, "audience pick": 1}
    fr = sl[sl["list"] == "franchise"]
    assert list(fr["collection_id"]) == [1, 2, 3] and list(fr["rank"]) == [1, 2, 3]
    st = sl[sl["list"] == "standalone"]
    assert list(st["name"]) == ["S0", "S1", "S2", "S3", "S4"]
    pick = sl[sl["list"] == "audience pick"].iloc[0]
    assert pick["name"] == "S7"  # most votes among those outside the top five
    assert pick["vote_count_or_median"] == 8000 and pick["rank_by_multiple"] == 8 and pick["vote_rank"] == 1


def test_audience_pick_is_never_in_the_top_five():
    f = shortlist_fixture()
    sl = rank.build_shortlist(rank.build_bundles(f), f)
    top = set(sl.loc[sl["list"] == "standalone", "tmdb_id"])
    assert sl.loc[sl["list"] == "audience pick", "tmdb_id"].iloc[0] not in top


def test_shortlist_short_when_too_few_bundles():
    rows = bundle_rows(1, [4, 5, 6]) + bundle_rows(2, [2, 3, 4], base_id=10) + bundle_rows(3, [1, 1], base_id=20)
    f = flagged(rows + [{"tmdb_id": 99, "title": "solo", **money(3)}])
    sl = rank.build_shortlist(rank.build_bundles(f), f)
    assert (sl["list"] == "franchise").sum() == 2
    assert (sl["list"] == "standalone").sum() == 1 and (sl["list"] == "audience pick").sum() == 0


def test_franchise_columns():
    f = shortlist_fixture()
    sl = rank.build_shortlist(rank.build_bundles(f), f)
    top = sl[sl["list"] == "franchise"].iloc[0]
    assert top["release_years"] == "1999-2008" and top["n_on_list"] == 3
    assert top["multiple"] == 9 and top["figure_2000_on"] == 9.5  # films 9 (2004) and 10 (2008) are 2000 onward
    assert top["weakest"] == "1-1 8.0×"


def test_standalone_before_2000_shows_pre_2000():
    rows = [{"tmdb_id": i, "title": f"S{i}", "year": 1980 + i * 10, **money(10 - i)} for i in range(1, 4)]
    f = flagged(rows)
    sl = rank.build_shortlist(rank.build_bundles(f), f)
    figs = dict(zip(sl["name"], sl["figure_2000_on"]))
    assert figs["S1"] == "pre-2000" and figs["S2"] == 8 and figs["S3"] == 7


def test_reason_text_carries_the_row_figures():
    f = shortlist_fixture()
    sl = rank.build_shortlist(rank.build_bundles(f), f)
    fr = sl[sl["list"] == "franchise"].iloc[0]
    assert fr["reason"] == (
        "All years: Median 9.0× across 3 films on the list (1st of 4 rankable bundles); weakest film 1-1 at 8.0×; "
        "9.5× from 2000 onward; 1st by audience votes."
    )
    st = sl[sl["list"] == "standalone"].iloc[2]
    assert st["reason"] == "All years: 16.0× its budget (3rd of 8 standalones); released 2012; 6th of 8 by audience votes."
    pick = sl[sl["list"] == "audience pick"].iloc[0]
    assert pick["reason"] == (
        "All years: Most-voted standalone not in the top five: 8,000 votes (1st of 8) but 6.0× its budget (8th of 8)."
    )


def test_ordinals_handle_the_teens():
    got = rank._ordinal(pd.Series([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111])).tolist()
    assert got == ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th"]


def test_tied_multiples_rank_by_votes():
    rows = [{"tmdb_id": 1, "title": "few", "votes": 10, **money(5)}, {"tmdb_id": 2, "title": "many", "votes": 90, **money(5)}]
    f = flagged(rows)
    sl = rank.build_shortlist(rank.build_bundles(f), f)
    assert list(sl["name"]) == ["many", "few"]


def test_empty_list_gives_an_empty_shortlist():
    f = flagged([{"budget": 0}])
    sl = rank.build_shortlist(rank.build_bundles(f), f)
    assert len(sl) == 0 and list(sl.columns) == rank.SHORTLIST_COLUMNS


# --- deal note ----------------------------------------------------------------------

def deal_for(rows):
    from pipeline import metrics

    f = flagged(rows)
    ref = rank.reference_values(f)
    kpis = pd.concat(metrics.window_kpis(f), ignore_index=True)
    dn = rank.deal_note_figures(rank.build_bundles(f), kpis, ref["list_median_roi"])
    return dn.set_index("candidate", drop=False), ref


def test_deal_note_ratios_equal_hand_computed_values():
    # list: bundle 1 (4, 8, 12) and standalones 2, 4, 6 -> list median of 6 films is (4 + 6) / 2 = 5
    rows = bundle_rows(1, [4, 8, 12], years=[2001, 2004, 2010]) + [
        {"tmdb_id": 50, "title": "a", **money(2)}, {"tmdb_id": 51, "title": "b", **money(4)}, {"tmdb_id": 52, "title": "c", **money(6)}]
    dn, ref = deal_for(rows)
    r = dn.loc["robust candidate"]
    assert ref["list_median_roi"] == 5
    assert r["median_roi"] == 8 and r["relative_value"] == 8 / 5
    assert r["weakest_roi"] == 4 and r["walkaway_ratio"] == 4 / 5 and r["weakest_title"] == "1-1"
    assert r["standalone_median_roi"] == 4 and r["relative_to_standalone"] == 2.0
    assert r["n_on_list"] == 3 and r["release_years"] == "2001-2010"
    assert r["bundle_rank"] == 1 and r["bundle_rank_2000_on"] == 1 and r["rankable_2000_on"]


def test_one_bundle_leading_both_windows_appears_in_all_three_rows():
    dn, _ = deal_for(bundle_rows(1, [4, 8, 12], years=[2001, 2004, 2010]))
    assert list(dn["candidate"]) == list(rank.CANDIDATES)
    assert set(dn["collection_id"]) == {1}


def test_the_candidates_can_be_three_different_rules_over_different_bundles():
    f = window_fixture()
    b = rank.build_bundles(f)
    dn = rank.deal_note_figures(b, pd.DataFrame(columns=["window", "group", "median_roi"]), 5.0).set_index("candidate")
    assert dn.loc["all-years leader", "collection_id"] == 1 and dn.loc["2000-onward leader", "collection_id"] == 2
    # both bundles have a worse-of-two rank of 2; bundle 2 wins on the higher walk-away (6 against 2)
    assert dn.loc["robust candidate", "collection_id"] == 2
    assert dn.loc["robust candidate", "walkaway_ratio"] == 6 / 5


def test_robust_candidate_minimises_the_worse_of_the_two_ranks():
    rows = (bundle_rows(1, [20, 20, 20], years=[1980, 1990, 2001], base_id=0)        # best overall, only one film from 2000
            + bundle_rows(2, [9, 9, 9], years=[2001, 2004, 2008], base_id=10)        # rankable in both windows
            + bundle_rows(3, [8, 8, 8], years=[2001, 2004, 2008], base_id=20)        # rankable in both windows, lower
            + bundle_rows(4, [10, 10, 10], years=[1985, 2002, 2004], base_id=30))    # strong overall, only two films from 2000
    b = rank.build_bundles(flagged(rows)).set_index("collection_id")
    assert not b.loc[1, "rankable_2000_on"] and not b.loc[4, "rankable_2000_on"]
    dn = rank.deal_note_figures(b.reset_index(), pd.DataFrame(columns=["window", "group", "median_roi"]), 5.0).set_index("candidate")
    assert dn.loc["robust candidate", "collection_id"] == 2
    assert dn.loc["all-years leader", "collection_id"] == 1 and dn.loc["2000-onward leader", "collection_id"] == 2


def test_no_bundle_rankable_in_both_windows_gives_no_robust_row():
    rows = bundle_rows(1, [4, 8, 12], years=[1980, 1990, 2001])
    dn, _ = deal_for(rows)
    assert list(dn["candidate"]) == ["all-years leader"]


def test_deal_note_flags_a_thin_recent_figure():
    dn, _ = deal_for(bundle_rows(1, [2, 3, 4], years=[1995, 1999, 2003]))
    r = dn.loc["all-years leader"]
    assert r["thin_2000_on"] and r["straddles_2000"] and not r["rankable_2000_on"]


def test_no_rankable_bundle_gives_no_deal_note():
    dn, _ = deal_for(bundle_rows(1, [2, 3]))
    assert len(dn) == 0 and list(dn.columns) == rank.DEAL_NOTE_COLUMNS


# --- both windows -------------------------------------------------------------------

def window_fixture():
    """Bundle A is best over all years (an old hit) but weak since 2000; bundle B is the reverse."""
    rows = bundle_rows(1, [30, 30, 30, 2, 2], years=[1980, 1983, 2001, 2004, 2008], base_id=100, votes=900)
    rows += bundle_rows(2, [6, 7, 8], years=[2002, 2005, 2009], base_id=200, votes=500)
    rows += bundle_rows(3, [4, 5], years=[2003, 2006], base_id=300)  # only two films: never rankable
    rows += [{"tmdb_id": 400 + i, "title": f"old{i}", "year": 1990 + i, **money(20 - i)} for i in range(3)]
    rows += [{"tmdb_id": 500 + i, "title": f"new{i}", "year": 2010 + i, "votes": 100 * (i + 1), **money(10 - i)}
             for i in range(6)]
    return flagged(rows)


def test_bundles_get_a_rank_for_films_from_2000():
    b = rank.build_bundles(window_fixture()).set_index("collection_id")
    assert b.loc[1, "bundle_rank"] == 1 and b.loc[2, "bundle_rank"] == 2
    assert b.loc[2, "bundle_rank_2000_on"] == 1 and b.loc[1, "bundle_rank_2000_on"] == 2
    assert b.loc[1, "rankable_2000_on"] and b.loc[1, "n_roi_2000_on"] == 3 and b.loc[1, "median_roi_2000_on"] == 2


def test_rank_for_2000_is_missing_when_too_few_films_are_from_2000():
    b = rank.build_bundles(window_fixture()).set_index("collection_id")
    assert not b.loc[3, "rankable"] and not b.loc[3, "rankable_2000_on"]
    assert pd.isna(b.loc[3, "bundle_rank_2000_on"])


def test_rankable_overall_but_not_from_2000():
    rows = bundle_rows(1, [5, 6, 7], years=[1980, 1990, 2005]) + bundle_rows(2, [2, 3, 4], base_id=10)
    b = rank.build_bundles(flagged(rows)).set_index("collection_id")
    assert b.loc[1, "rankable"] and b.loc[1, "n_roi_2000_on"] == 1
    assert not b.loc[1, "rankable_2000_on"] and pd.isna(b.loc[1, "bundle_rank_2000_on"])
    assert b.loc[2, "rankable_2000_on"] and b.loc[2, "bundle_rank_2000_on"] == 1


def test_a_collection_with_no_film_from_2000_has_no_window_rank():
    b = rank.build_bundles(flagged(bundle_rows(1, [2, 3, 4], years=[1980, 1983, 1986]))).set_index("collection_id")
    assert b.loc[1, "n_roi_2000_on"] == 0 and not b.loc[1, "rankable_2000_on"]
    assert pd.isna(b.loc[1, "bundle_rank_2000_on"])


def test_tie_in_the_2000_window_goes_to_more_votes():
    rows = bundle_rows(1, [2, 3, 4], votes=100) + bundle_rows(2, [2, 3, 4], votes=900, base_id=10)
    b = rank.build_bundles(flagged(rows)).set_index("collection_id")
    assert b.loc[2, "bundle_rank_2000_on"] == 1 and b.loc[1, "bundle_rank_2000_on"] == 2


def test_shortlist_for_2000_uses_only_films_from_2000():
    f = window_fixture()
    b = rank.build_bundles(f)
    sl = rank.build_shortlist(b, f, "2000 onward")
    assert set(sl["window"]) == {"2000 onward"}
    fr = sl[sl["list"] == "franchise"]
    assert list(fr["collection_id"]) == [2, 1] and list(fr["multiple"]) == [7, 2]  # medians of films from 2000
    assert "old0" not in set(sl["name"])  # a pre-2000 standalone is outside this window
    stand = sl[sl["list"] == "standalone"]
    assert len(stand) == 5 and stand["release_years"].astype(int).min() >= 2010


def test_every_reason_states_its_window():
    f = window_fixture()
    sl = rank.build_shortlists(rank.build_bundles(f), f)
    assert set(sl["window"]) == {"all years", "2000 onward"}
    starts = sl["reason"].str[:12]
    assert starts[sl["window"] == "all years"].str.startswith("All years: ").all()
    assert starts[sl["window"] == "2000 onward"].str.startswith("2000 onward:").all()
    row = sl[(sl["window"] == "2000 onward") & (sl["list"] == "franchise")].iloc[0]
    assert "films from 2000 onward on the list (1st of 2 bundles rankable from 2000 on)" in row["reason"]


def test_audience_pick_in_the_2000_window_is_outside_that_windows_top_five():
    f = window_fixture()
    sl = rank.build_shortlist(rank.build_bundles(f), f, "2000 onward")
    pick = sl[sl["list"] == "audience pick"].iloc[0]
    top = set(sl.loc[sl["list"] == "standalone", "tmdb_id"])
    assert pick["tmdb_id"] not in top and pick["name"] == "new5" and "from 2000 onward" in pick["reason"]


def test_the_windows_can_give_different_shortlists():
    f = window_fixture()
    sl = rank.build_shortlists(rank.build_bundles(f), f)
    d = rank.window_differences(sl).set_index("list")
    assert list(d.index) == ["franchise", "standalone", "audience pick"]
    assert not d.loc["franchise", "same"] and not d.loc["standalone", "same"]
    assert d.loc["franchise", "names_all_years"] == "Collection 1 | Collection 2"
    assert d.loc["franchise", "names_2000_onward"] == "Collection 2 | Collection 1"
    assert d.loc["franchise", "names_in_both"] == "Collection 1 | Collection 2"  # same names, different order
    assert "old0" in d.loc["standalone", "names_all_years"] and "old0" not in d.loc["standalone", "names_2000_onward"]


def test_identical_windows_are_reported_as_the_same():
    rows = bundle_rows(1, [2, 3, 4], years=[2001, 2004, 2008]) + [
        {"tmdb_id": 50 + i, "title": f"s{i}", "year": 2010 + i, "votes": 100 + i, **money(9 - i)} for i in range(7)]
    f = flagged(rows)
    d = rank.window_differences(rank.build_shortlists(rank.build_bundles(f), f))
    assert d["same"].all()
    assert list(d.columns) == rank.DIFFERENCE_COLUMNS


def test_empty_shortlist_in_a_window_is_handled():
    f = flagged(bundle_rows(1, [2, 3, 4], years=[1980, 1983, 1986]))
    sl = rank.build_shortlists(rank.build_bundles(f), f)
    d = rank.window_differences(sl).set_index("list")
    assert set(sl["window"]) == {"all years"} and d.loc["franchise", "names_2000_onward"] == ""
    assert not d.loc["franchise", "same"]
