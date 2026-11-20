"""Stage 4: flags are added, rows are never removed, values are never corrected."""
import numpy as np
import pandas as pd

from pipeline import checks, clean
from tests.conftest import make_films


def flagged(rows):
    return clean.add_flags(make_films(rows))


def test_units_rule_splits_on_votes():
    f = flagged([
        {"title": "Famous", "budget": 63, "revenue": 5_000_000, "votes": 20_000},
        {"title": "Tiny", "budget": 7_000, "revenue": 90_000, "votes": 30},
    ])
    famous, tiny = f.iloc[0], f.iloc[1]
    assert famous["units_error_likely"] and not famous["possible_micro_budget"]
    assert not famous["roi_usable"] and pd.isna(famous["roi"])
    assert famous["roi_exclusion_reason"] == "likely units error"
    assert tiny["possible_micro_budget"] and not tiny["units_error_likely"]
    assert tiny["roi_usable"] and tiny["roi"] == 90_000 / 7_000


def test_vote_threshold_edge_is_inclusive():
    f = flagged([{"budget": 500, "votes": 500}, {"budget": 500, "votes": 499}])
    assert f["units_error_likely"].tolist() == [True, False]


def test_suspect_values_are_not_corrected():
    films = make_films([{"budget": 63, "votes": 20_000}])
    f = clean.add_flags(films)
    assert f.loc[0, "budget"] == 63
    pd.testing.assert_series_equal(f["budget"], films["budget"])


def test_no_rows_are_removed():
    rows = [{"status": "Rumored"}, {"budget": 0}, {"revenue": 0}, {"budget": 63, "votes": 9999}, {}]
    assert len(flagged(rows)) == len(rows)


def test_zero_budget_is_not_usable_and_does_not_divide():
    f = flagged([{"budget": 0, "revenue": 5_000_000}])
    assert not f.loc[0, "budget_usable"] and not f.loc[0, "roi_usable"]
    assert f.loc[0, "roi_exclusion_reason"] == "budget not reported"
    assert pd.isna(f.loc[0, "roi"])
    assert not np.isinf(f["roi"].dropna()).any()


def test_zero_revenue_is_not_reported():
    f = flagged([{"revenue": 0}])
    assert f.loc[0, "roi_exclusion_reason"] == "revenue not reported"


def test_unreleased_is_excluded_with_reason():
    f = flagged([{"status": "Rumored"}])
    assert not f.loc[0, "is_released"] and not f.loc[0, "roi_usable"]
    assert f.loc[0, "roi_exclusion_reason"] == "not released"


def test_usable_row_has_empty_reason_and_a_multiple():
    f = flagged([{"budget": 100_000, "revenue": 250_000}])
    assert f.loc[0, "roi_exclusion_reason"] == "" and f.loc[0, "roi"] == 2.5


def test_extreme_multiple_is_flagged_not_removed():
    f = flagged([{"budget": 1_000_000, "revenue": 80_000_000}, {"budget": 1_000_000, "revenue": 20_000}])
    assert f["roi_extreme"].tolist() == [True, True]  # 80 and 0.01
    assert f["roi_usable"].all() and f["roi"].notna().all()


def test_window_edge_and_missing_year():
    f = flagged([{"year": 1999}, {"year": 2000}, {"year": pd.NA}])
    assert f["in_window_2000"].tolist() == [False, True, False]
    assert f["release_year"].isna().sum() == 1


def test_sequel_like_only_for_standalones():
    f = flagged([
        {"title": "Film II", "franchise": False},
        {"title": "Film II", "franchise": True},
        {"title": "Ivy", "franchise": False},
        {"title": "Big: The Return", "franchise": False},
    ])
    assert f["sequel_like_title"].tolist() == [True, False, False, True]


def test_same_film_by_title_and_year():
    f = flagged([
        {"title": "The Film", "year": 2001},
        {"title": "the film!", "year": 2001},
        {"title": "The Film", "year": 2002},
    ])
    assert f["possible_same_film"].tolist() == [True, True, False]


def test_clean_checks_pass_and_count():
    f = flagged([
        {"budget": 63, "votes": 9999}, {"budget": 7_000, "votes": 5}, {"budget": 1, "revenue": 99, "votes": 5},
    ])
    report = checks.check_clean_stage(f, as_of_year=2026)
    assert report["passed"].all()
    assert set(report["check_id"]) == {"C-15", "C-16", "C-17", "C-18", "C-19", "C-20", "C-ROI"}
    c17 = report.set_index("check_id").loc["C-17", "detail"]
    assert c17.startswith("1 likely units errors; 2 possible micro-budget")


def test_check_catches_negative_money_and_bad_year():
    f = flagged([{"budget": -5}, {"year": 1850}])
    report = checks.check_clean_stage(f, as_of_year=2026).set_index("check_id")
    assert not report.loc["C-15", "passed"] and not report.loc["C-16", "passed"]


def test_review_list_has_one_row_per_film_per_reason():
    f = flagged([
        {"title": "Wrong", "budget": 63, "votes": 20_000},
        {"title": "Micro", "budget": 7_000, "revenue": 90_000, "votes": 30},
        {"title": "Big II", "budget": 1_000_000, "revenue": 90_000_000},
        {"title": "Dup", "year": 2005}, {"title": "dup.", "year": 2005},
    ])
    review = clean.build_review_list(f)
    assert list(review.columns) == ["tmdb_id", "title", "release_year", "check", "value", "note"]
    by = review.groupby("check")["title"].apply(list)
    assert by["units_error_likely"] == ["Wrong"]
    assert by["possible_micro_budget"] == ["Micro"]
    assert by["roi_extreme"] == ["Big II"]
    assert by["sequel_like_title"] == ["Big II"]
    assert sorted(by["possible_same_film"]) == ["Dup", "dup."]
    assert not review.duplicated(["tmdb_id", "check"]).any()


def test_largest_values_are_listed_even_when_nothing_else_is():
    f = flagged([{"title": f"F{i}", "budget": 1_000_000 + i, "revenue": 3_000_000 + i} for i in range(8)])
    review = clean.build_review_list(f)
    assert set(review["check"]) == {"largest_budget", "largest_revenue"}  # an empty review is valid
    top = review[review["check"] == "largest_budget"]
    assert len(top) == 5 and top["value"].astype(int).max() == 1_000_007


def test_review_list_does_not_change_the_films():
    f = flagged([{"budget": 63, "votes": 20_000}])
    before = f.copy()
    clean.build_review_list(f)
    pd.testing.assert_frame_equal(f, before)
