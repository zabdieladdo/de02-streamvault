"""Spot-check: which films, the live fetch that never writes, the comparison and its impact."""
import pandas as pd

from pipeline import clean, spotcheck
from tests.conftest import make_films


def money(roi):
    return {"budget": 1_000_000, "revenue": round(roi * 1_000_000)}


# --- which films ----------------------------------------------------------------------

def selection_inputs(attempts=None, elapsed=None):
    """Six films: ids 1-3 are a collection, 4-6 are standalones; the answers are easy to read."""
    rows = [
        {"tmdb_id": 1, "title": "One", "franchise": 7, **money(4)},
        {"tmdb_id": 2, "title": "Two", "franchise": 7, **money(6)},
        {"tmdb_id": 3, "title": "Three", "franchise": 7, **money(5)},
        {"tmdb_id": 4, "title": "High", **money(90)},
        {"tmdb_id": 5, "title": "Low", **money(1.1)},
        {"tmdb_id": 6, "title": "Listed", **money(3)},
    ]
    films = clean.add_flags(make_films(rows)).assign(
        n_cast=[10, 300, 20, 20, 20, 20], n_crew=[10, 400, 20, 20, 20, 20], n_genres=[2, 3, 2, 2, 2, 2],
        imdb_id=pd.array([pd.NA] * 5 + ["tt6"], dtype="string"),
    )
    ids = pd.DataFrame({"tmdb_id": [1, 2, 3, 4, 5, 6], "n_occurrences": [1, 1, 1, 1, 1, 2]})
    quarantine = pd.DataFrame(
        {"stage": ["load", "load"], "reason_code": ["imdb_id_not_tmdb", "repeat"], "raw_value": ["tt6", "6"]}
    )
    deal = pd.DataFrame(
        {"candidate": ["all-years leader", "robust candidate"], "collection_id": [7, 7],
         "collection_name": ["Collection 7", "Collection 7"]}
    )
    log = pd.DataFrame(
        {
            "tmdb_id": [1, 2, 3, 4, 5, 6] * 2, "endpoint": ["details"] * 6 + ["credits"] * 6,
            "attempts": attempts or [1] * 12,
            "elapsed_s": elapsed or [0.3, 0.3, 0.3, 0.3, 0.9, 0.3] + [0.2] * 6,
        }
    )
    return films, ids, quarantine, deal, log


def select(**kw):
    films, ids, quarantine, deal, log = selection_inputs(**kw)
    return spotcheck.select_spotcheck_films(films, ids, quarantine, deal, log)


def test_each_slice_picks_the_film_the_rule_names():
    sel = select().groupby("slice")["tmdb_id"].apply(list).to_dict()
    assert sel["heaviest_parsing"] == [2]  # 300 + 400 + 3
    assert sel["extreme_high"] == [4] and sel["extreme_low"] == [5]
    assert sel["cleaning_decision"] == [6]  # 2 list rows plus the IMDb id that matched it
    assert sel["drives_recommendation"] == [1, 2, 3]  # every film of the robust candidate
    assert list(sel) and set(sel) <= set(spotcheck.SLICES)


def test_selection_is_ordered_by_slice_and_has_one_row_per_film_and_slice():
    sel = select()
    assert list(sel.columns) == spotcheck.SELECTION_COLUMNS
    assert not sel.duplicated(["slice", "tmdb_id"]).any()
    assert list(sel["slice"].drop_duplicates()) == [s for s in spotcheck.SLICES if s in set(sel["slice"])]


def test_nearly_failed_with_no_retries_takes_the_slowest_response_and_says_so():
    row = select()[lambda d: d["slice"] == "nearly_failed"].iloc[0]
    assert row["tmdb_id"] == 5 and row["stand_in"]  # all attempts 1: the 0.9 s response
    assert "details" in row["detail"] and "0.9" in row["detail"]


def test_nearly_failed_with_a_retry_takes_the_most_attempts_and_is_no_stand_in():
    attempts = [1, 1, 1, 1, 1, 1] + [1, 1, 3, 1, 1, 1]  # the credits request for film 3 needed 3 attempts
    row = select(attempts=attempts)[lambda d: d["slice"] == "nearly_failed"].iloc[0]
    assert row["tmdb_id"] == 3 and not row["stand_in"] and "credits: 3 attempt" in row["detail"]


def test_a_film_in_two_slices_is_checked_once_with_both_slices_listed():
    films = spotcheck.films_to_check(select())
    assert films["tmdb_id"].is_unique
    two = films.set_index("tmdb_id")["slices"]
    assert two[2] == "heaviest_parsing|drives_recommendation"
    assert two[5] == "extreme_low|nearly_failed"
    assert len(films) == 6 and films["stand_in"].sum() == 1  # only film 5 carries the stand-in slice


def test_cleaning_decision_counts_the_matched_imdb_id_and_the_repeats():
    films, ids, quarantine, deal, log = selection_inputs()
    ids = ids.assign(n_occurrences=[2, 1, 1, 1, 1, 2])  # film 1 is also listed twice
    no_imdb = quarantine.iloc[1:]  # without the IMDb id, films 1 and 6 tie at 2 and the lower id wins
    sel = spotcheck.select_spotcheck_films(films, ids, no_imdb, deal, log)
    assert sel.loc[sel["slice"] == "cleaning_decision", "tmdb_id"].tolist() == [1]
    with_imdb = spotcheck.select_spotcheck_films(films, ids, quarantine, deal, log)
    assert with_imdb.loc[with_imdb["slice"] == "cleaning_decision", "tmdb_id"].tolist() == [6]  # 2 + 1 = 3


def test_no_robust_candidate_means_no_recommendation_slice():
    films, ids, quarantine, deal, log = selection_inputs()
    sel = spotcheck.select_spotcheck_films(films, ids, quarantine, deal.iloc[:1], log)
    assert "drives_recommendation" not in set(sel["slice"])


def test_unusable_films_are_never_the_extremes():
    films, ids, quarantine, deal, log = selection_inputs()
    films = films.assign(roi=films["roi"].where(films["tmdb_id"] != 4), roi_usable=films["tmdb_id"] != 4)
    sel = spotcheck.select_spotcheck_films(films, ids, quarantine, deal, log)
    assert sel.loc[sel["slice"] == "extreme_high", "tmdb_id"].tolist() == [2]  # the next-highest usable film


def test_selection_does_not_change_its_inputs():
    films, ids, quarantine, deal, log = selection_inputs()
    before = [x.copy() for x in (films, ids, quarantine, deal, log)]
    spotcheck.select_spotcheck_films(films, ids, quarantine, deal, log)
    for a, b in zip((films, ids, quarantine, deal, log), before):
        pd.testing.assert_frame_equal(a, b)
