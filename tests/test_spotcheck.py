"""Spot-check: which films, the live fetch that never writes, the comparison and its impact."""
import hashlib
from pathlib import Path

import pandas as pd
import pytest
import requests

from pipeline import clean, config, fetch, spotcheck
from pipeline.errors import PipelineStopError
from tests.conftest import NOT_FOUND_BODY, TEST_KEY, FakeResponse, FakeSession, make_films, ok_body
from tests.test_fetch import make_ids


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


# --- the live fetch never writes ----------------------------------------------------------

def tree_hash(root: Path) -> dict:
    """Every file under root, by relative path, with the hash of its bytes."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_live_fetch_returns_details_and_credits_for_each_film(fetch_env):
    session = FakeSession()
    results = spotcheck.fetch_live([603, 155], session=session, key=TEST_KEY)
    assert session.calls == ["/movie/603", "/movie/603/credits", "/movie/155", "/movie/155/credits"]
    assert [(r.tmdb_id, r.endpoint, r.outcome) for r in results] == [
        (603, "details", "ok"), (603, "credits", "ok"), (155, "details", "ok"), (155, "credits", "ok"),
    ]
    assert results[0].body["id"] == 603 and results[1].body["cast"] == []


def test_live_fetch_leaves_the_snapshot_and_the_fetch_log_byte_identical(fetch_env, monkeypatch):
    fetch.fetch_all(make_ids(603, 155), session=FakeSession(), key=TEST_KEY)  # the snapshot being checked
    before = tree_hash(config.RAW_DIR)
    assert any(name.endswith("fetch_log.csv") for name in before) and len(before) == 5

    def forbidden(*args, **kwargs):
        raise AssertionError("the spot-check must never write the snapshot")

    monkeypatch.setattr(fetch, "_write_cache", forbidden)
    monkeypatch.setattr(fetch, "write_fetch_log", forbidden)
    session = FakeSession(
        {"/movie/603": FakeResponse(200, ok_body(603)), "/movie/155": FakeResponse(404, NOT_FOUND_BODY)}
    )
    results = spotcheck.fetch_live([603, 155, 999], session=session, key=TEST_KEY)  # 999 was never in the snapshot
    assert len(results) == 6 and {r.outcome for r in results} == {"ok", "not_found"}
    assert tree_hash(config.RAW_DIR) == before
    assert not (config.RAW_DETAILS_DIR / "999.json").exists()


def test_a_missing_film_or_failed_request_is_recorded_and_the_run_carries_on(fetch_env):
    session = FakeSession(
        {"/movie/603": FakeResponse(404, NOT_FOUND_BODY), "/movie/155/credits": FakeResponse(503, b"{}")}
    )
    results = spotcheck.fetch_live([603, 155], session=session, key=TEST_KEY)
    by = {(r.tmdb_id, r.endpoint): r for r in results}
    assert by[(603, "details")].outcome == "not_found" and by[(603, "details")].body is None
    assert by[(155, "credits")].outcome == "failed" and by[(155, "credits")].status_code == 503
    assert by[(155, "details")].outcome == "ok"


def test_a_401_stops_the_check(fetch_env):
    session = FakeSession({"/movie/603": FakeResponse(401, b"{}")})
    with pytest.raises(PipelineStopError, match="401"):
        spotcheck.fetch_live([603, 155], session=session, key=TEST_KEY)
    assert session.calls == ["/movie/603"]


def test_three_network_errors_in_a_row_stop_the_check(fetch_env):
    err = requests.ConnectionError("down")
    session = FakeSession({"/movie/603": err, "/movie/603/credits": err, "/movie/155": err})
    with pytest.raises(PipelineStopError, match="network"):
        spotcheck.fetch_live([603, 155, 11], session=session, key=TEST_KEY)
    assert len(session.calls) == 3


def test_a_wrong_id_in_the_answer_keeps_no_body(fetch_env):
    session = FakeSession({"/movie/603": FakeResponse(200, ok_body(999))})
    res = spotcheck.fetch_live([603], session=session, key=TEST_KEY)[0]
    assert res.outcome == "id_mismatch" and res.body is None


def test_the_key_never_appears_in_a_result(fetch_env):
    err = requests.ConnectionError(f"failed: {config.API_BASE}/movie/603?api_key={TEST_KEY}")
    session = FakeSession({"/movie/603": err})
    results = spotcheck.fetch_live([603], session=session, key=TEST_KEY)
    assert results[0].outcome == "network_error"
    assert TEST_KEY not in repr(results) and "api_key=***" in results[0].detail


def test_no_key_stops_before_any_request(fetch_env):
    session = FakeSession()
    with pytest.raises(PipelineStopError, match="TMDB_API_KEY"):
        spotcheck.fetch_live([603], session=session, key=None)
    assert session.calls == []


def test_a_session_opened_here_is_closed_and_one_passed_in_is_not(fetch_env, monkeypatch):
    mine = FakeSession()
    spotcheck.fetch_live([603], session=mine, key=TEST_KEY)
    assert mine.closed is False
    built = []
    monkeypatch.setattr(fetch, "build_session", lambda: built.append(FakeSession()) or built[-1])
    spotcheck.fetch_live([603], key=TEST_KEY)
    assert len(built) == 1 and built[0].closed is True and built[0].calls
