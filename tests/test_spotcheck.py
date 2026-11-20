"""Spot-check: which films, the live fetch that never writes, the comparison and its impact."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import requests

import run_pipeline
import spotcheck as command
from pipeline import clean, config, fetch, spotcheck
from pipeline.errors import PipelineStopError
from tests.conftest import NOT_FOUND_BODY, TEST_KEY, FakeResponse, FakeSession, make_films, ok_body
from tests.test_fetch import make_ids
from tests.test_run_pipeline import IDS, fake


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


# --- classify each difference ---------------------------------------------------------------

def classify_one(fresh, raw, ours, kind="exact", field="budget", in_other=False, fresh_ok=True):
    row = {
        "tmdb_id": 1, "title": "x", "slices": "s", "endpoint": "details", "field": field, "kind": kind,
        "fresh": fresh, "raw": raw, "ours": ours, "fresh_ok": fresh_ok, "in_other_field": in_other,
    }
    return spotcheck.classify_table(pd.DataFrame([row])).iloc[0]


def one_field(table, field):
    return table[table["field"] == field]


def test_all_three_the_same_is_a_match():
    assert classify_one(185_000_000, 185_000_000, 185_000_000)["class"] == "match"


def test_fresh_equals_saved_but_ours_differs_is_a_parsing_error():
    assert classify_one(185_000_000, 185_000_000, 18_500_000)["class"] == "parsing_error"


def test_fresh_differs_but_saved_equals_ours_is_a_source_change():
    assert classify_one(190_000_000, 185_000_000, 185_000_000)["class"] == "source_changed"


def test_all_three_different_is_both():
    assert classify_one(190_000_000, 185_000_000, 18_500_000)["class"] == "parsing_error_and_source_changed"


def test_a_value_read_from_the_wrong_place_is_a_wrong_field():
    raw_details = {"id": 1, "budget": 63, "vote_count": 5000, "title": "x"}
    ours = {"budget": 5000}  # we stored the vote count in the budget column
    rows = spotcheck.comparison_rows(
        {"tmdb_id": 1, "title": "x", "slices": "s"}, {"budget": 63}, {"budget": 63}, ours, raw_details, {}
    )
    row = one_field(rows, "budget")
    assert row["in_other_field"].iloc[0]
    assert spotcheck.classify_table(row).iloc[0]["class"] == "wrong_field"


def test_a_value_that_only_differs_is_not_a_wrong_field():
    raw_details = {"id": 1, "budget": 63, "vote_count": 5000}
    rows = spotcheck.comparison_rows(
        {"tmdb_id": 1, "title": "x", "slices": "s"}, {"budget": 63}, {"budget": 63}, {"budget": 64}, raw_details, {}
    )
    row = one_field(rows, "budget")
    assert not row["in_other_field"].iloc[0]
    assert spotcheck.classify_table(row).iloc[0]["class"] == "parsing_error"


def test_wrong_field_is_only_checked_for_money_and_dates():
    raw_details = {"id": 1, "title": "Five", "vote_count": "Five", "budget": 5}
    rows = spotcheck.comparison_rows(
        {"tmdb_id": 1, "title": "x", "slices": "s"}, {"title": "Five"}, {"title": "Five"}, {"title": "Fiv"},
        raw_details, {},
    )
    assert not one_field(rows, "title")["in_other_field"].iloc[0]


def test_a_changed_vote_count_is_volatile_not_a_discrepancy_and_reports_the_change():
    row = classify_one(11_000, 10_000, 10_000, kind="volatile", field="vote_count")
    assert row["class"] == "volatile_changed" and row["note"] == "+10.0%"
    assert not spotcheck.is_discrepancy(pd.Series([row["class"]])).iloc[0]


def test_a_volatile_field_is_still_a_parsing_error_when_our_table_is_wrong():
    assert classify_one(10_000, 10_000, 1_000, kind="volatile", field="vote_count")["class"] == "parsing_error"


def test_the_multiple_matches_within_a_tiny_tolerance_and_not_beyond_it():
    close = classify_one(5.0, 5.0, 5.0 + 1e-12, kind="roi", field="revenue / budget")
    far = classify_one(5.0, 5.0, 5.01, kind="roi", field="revenue / budget")
    assert close["class"] == "match" and far["class"] == "parsing_error"


def test_other_numbers_must_match_exactly():
    assert classify_one(185_000_000, 185_000_000, 185_000_001)["class"] == "parsing_error"  # no tolerance for money


def test_whole_numbers_compare_equal_as_int_or_float_and_missing_equals_missing():
    assert classify_one(185_000_000, 185_000_000.0, 185_000_000)["class"] == "match"
    for empty in (None, "", float("nan"), pd.NA):
        assert classify_one(None, empty, empty, field="imdb_id")["class"] == "match"
    assert classify_one("tt1", None, None, field="imdb_id")["class"] == "source_changed"


def test_a_field_whose_live_answer_is_missing_is_unverified_not_a_difference():
    row = classify_one(None, 185_000_000, 185_000_000, fresh_ok=False)
    assert row["class"] == "unverified" and not spotcheck.is_discrepancy(pd.Series([row["class"]])).iloc[0]


# --- read the same fields from a response ---------------------------------------------------

def test_details_fields_are_read_from_the_response():
    payload = {
        "id": 9, "title": "T", "release_date": "2008-07-16", "status": "Released", "budget": 100, "revenue": 300,
        "belongs_to_collection": {"id": 263, "name": "C"}, "genres": [{"name": "Action"}, {"name": "Crime"}],
        "imdb_id": "tt1", "vote_count": 5, "vote_average": 8.5, "popularity": 1.5,
    }
    got = spotcheck.extract_details(payload)
    assert got["belongs_to_collection.id"] == 263 and got["genres[].name"] == "Action|Crime"
    assert got["revenue / budget"] == 3.0 and got["release_date"] == "2008-07-16"
    assert spotcheck.extract_details(None) == {}


def test_details_without_a_collection_or_money_have_no_collection_and_no_multiple():
    got = spotcheck.extract_details(
        {"id": 9, "title": "T", "belongs_to_collection": None, "genres": [], "budget": 0, "revenue": 50}
    )
    assert got["belongs_to_collection.id"] is None and got["genres[].name"] == "" and got["revenue / budget"] is None


def test_credits_give_sorted_directors_and_the_top_three_by_billing_order():
    payload = {
        "cast": [{"id": 5, "order": 3}, {"id": 6, "order": 0}, {"id": 7, "order": 1}, {"id": 8, "order": 2},
                 {"id": 6, "order": 9}, {"id": 4}],  # a repeated person and one with no order
        "crew": [{"id": 30, "job": "Director"}, {"id": 20, "job": "Director"}, {"id": 21, "job": "Editor"},
                 {"id": 20, "job": "Director"}],
    }
    got = spotcheck.extract_credits(payload)
    assert got["director person ids"] == "20|30" and got["top 3 cast person ids"] == "6|7|8"


def test_credits_ties_keep_the_list_position_and_empty_lists_give_empty_text():
    tied = {"cast": [{"id": i, "order": 0} for i in (1, 2, 3, 4)], "crew": []}
    assert spotcheck.extract_credits(tied)["top 3 cast person ids"] == "1|2|3"
    empty = {"director person ids": "", "top 3 cast person ids": ""}
    assert spotcheck.extract_credits({"cast": [], "crew": []}) == empty
    assert spotcheck.extract_credits({"id": 1}) == empty


# --- compare a film from the snapshot, the live answer and our tables ------------------------

DETAILS = {
    "id": 603, "title": "The Matrix", "release_date": "1999-03-30", "status": "Released", "budget": 63_000_000,
    "revenue": 463_517_383, "belongs_to_collection": {"id": 2344, "name": "Matrix"},
    "genres": [{"name": "Action"}, {"name": "Science Fiction"}], "imdb_id": "tt0133093",
    "vote_count": 25_000, "vote_average": 8.2, "popularity": 40.5,
}
CREDITS = {
    "id": 603,
    "cast": [{"id": 6384, "order": 0}, {"id": 2975, "order": 1}, {"id": 530, "order": 2}, {"id": 9, "order": 3}],
    "crew": [{"id": 9340, "job": "Director"}, {"id": 9339, "job": "Director"}],
}


@pytest.fixture
def snapshot(fetch_env):
    import json

    config.RAW_DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    config.RAW_CREDITS_DIR.mkdir(parents=True, exist_ok=True)
    (config.RAW_DETAILS_DIR / "603.json").write_text(json.dumps(DETAILS), encoding="utf-8")
    (config.RAW_CREDITS_DIR / "603.json").write_text(json.dumps(CREDITS), encoding="utf-8")
    films = pd.DataFrame([{
        "tmdb_id": 603, "title": "The Matrix", "release_date_raw": "1999-03-30", "status": "Released",
        "budget": 63_000_000, "revenue": 463_517_383, "collection_id": 2344, "genres_all": "Action|Science Fiction",
        "imdb_id": "tt0133093", "vote_count": 25_000, "vote_average": 8.2, "popularity": 40.5,
        "roi_usable": True, "roi": 463_517_383 / 63_000_000,
    }])
    talent = pd.DataFrame({
        "tmdb_id": [603] * 5, "person_id": [9339, 9340, 6384, 2975, 530],
        "role": ["director", "director", "lead_actor", "lead_actor", "lead_actor"],
        "billing_rank": [pd.NA, pd.NA, 1, 2, 3],
    })
    checked = pd.DataFrame(
        {"tmdb_id": [603], "title": ["The Matrix"], "slices": ["extreme_low"], "stand_in": [False]}
    )
    return films, talent, checked


def live_from(details, credits, details_outcome="ok"):
    return [
        spotcheck.LiveResult(603, "details", details_outcome, 200, 1, 0.1, "t", "", details),
        spotcheck.LiveResult(603, "credits", "ok", 200, 1, 0.1, "t", "", credits),
    ]


def test_a_film_that_is_the_same_everywhere_matches_on_every_field(snapshot):
    films, talent, checked = snapshot
    table = spotcheck.build_comparison(checked, live_from(DETAILS, CREDITS), films, talent)
    assert len(table) == len(spotcheck.FIELDS) == 14
    assert set(table["class"]) == {"match"}
    assert set(table["field"]) == {f for _, f, _ in spotcheck.FIELDS}


def test_a_changed_live_budget_is_a_source_change_and_ours_is_still_right(snapshot):
    films, talent, checked = snapshot
    live = live_from({**DETAILS, "budget": 70_000_000}, CREDITS)
    by = spotcheck.build_comparison(checked, live, films, talent).set_index("field")["class"]
    assert by["budget"] == "source_changed" and by["revenue / budget"] == "source_changed"
    assert (by.drop(["budget", "revenue / budget"]) == "match").all()


def test_a_wrongly_parsed_value_in_our_table_is_a_parsing_error(snapshot):
    films, talent, checked = snapshot
    table = spotcheck.build_comparison(checked, live_from(DETAILS, CREDITS), films.assign(revenue=46_351_738), talent)
    assert table.set_index("field").loc["revenue", "class"] == "parsing_error"


def test_a_wrong_director_in_our_talent_table_is_found_by_the_credits_comparison(snapshot):
    films, talent, checked = snapshot
    talent = talent.assign(person_id=[1, 9340, 6384, 2975, 530])
    table = spotcheck.build_comparison(checked, live_from(DETAILS, CREDITS), films, talent)
    assert table.set_index("field").loc["director person ids", "class"] == "parsing_error"


def test_a_failed_live_answer_leaves_its_fields_unverified(snapshot):
    films, talent, checked = snapshot
    live = live_from(None, CREDITS, details_outcome="not_found")
    by = spotcheck.build_comparison(checked, live, films, talent).set_index("field")["class"]
    assert by["budget"] == "unverified" and by["revenue / budget"] == "unverified"
    assert by["director person ids"] == "match"


def test_comparison_reads_the_snapshot_without_writing_it(snapshot):
    films, talent, checked = snapshot
    before = tree_hash(config.RAW_DIR)
    spotcheck.build_comparison(checked, live_from(DETAILS, CREDITS), films, talent)
    assert tree_hash(config.RAW_DIR) == before


def test_a_missing_snapshot_file_is_not_a_crash(snapshot):
    films, talent, checked = snapshot
    (config.RAW_DETAILS_DIR / "603.json").unlink()
    table = spotcheck.build_comparison(checked, live_from(DETAILS, CREDITS), films, talent)
    assert table.set_index("field").loc["budget", "class"] in ("source_changed", "parsing_error_and_source_changed")


# --- does a difference move the recommendation? -----------------------------------------------

def impact_films():
    """Collection 1 leads collection 2 (median 9.2 against 9.1) in both windows; standalones s0-s6."""
    def bundle(collection, rois, base_id):
        return [
            {"tmdb_id": base_id + i, "title": f"{collection}-{i + 1}", "franchise": collection,
             "year": 2001 + 3 * i, **money(r)}
            for i, r in enumerate(rois)
        ]

    rows = bundle(1, [12, 9.2, 9.0], 100) + bundle(2, [9.1, 9.1, 9.1], 200)
    rows += [{"tmdb_id": 300 + i, "title": f"s{i}", "year": 2010 + i, "votes": 5000 - 100 * i, **money(20 - i)}
             for i in range(7)]
    return clean.add_flags(make_films(rows))


def difference(tmdb_id, title, field, fresh, raw, ours=None, cls="source_changed"):
    return {
        "tmdb_id": tmdb_id, "title": title, "slices": "s", "endpoint": "details", "field": field,
        "fresh": str(fresh), "raw": str(raw), "ours": str(raw if ours is None else ours), "class": cls,
        "note": "", "kind": "exact",
    }


def assess(*rows, films=None):
    return spotcheck.assess_impact(pd.DataFrame(list(rows)), impact_films() if films is None else films)


def test_a_fresh_revenue_that_drops_the_robust_candidate_below_another_bundle_moves_the_recommendation():
    table, overall = assess(difference(101, "1-2", "revenue", 1_000_000, 9_200_000))
    row = table.iloc[0]
    assert row["moves_recommendation"] and "robust candidate Collection 1 -> Collection 2" in row["impact"]
    assert "film multiple 9.20 -> 1.00" in row["impact"] and "bundle Collection 1: median 9.20 -> 9.00" in row["impact"]
    assert overall["moves"] and "Collection 1 -> Collection 2" in overall["what"]


def test_a_change_that_leaves_the_ranking_alone_does_not_move_it():
    table, overall = assess(difference(100, "1-1", "revenue", 11_000_000, 12_000_000))  # 12.0 down to 11.0
    row = table.iloc[0]
    assert not row["moves_recommendation"] and "robust candidate unchanged" in row["impact"]
    assert "shortlists unchanged" in row["impact"] and "bundle Collection 1: median 9.20 -> 9.20" in row["impact"]
    assert overall == {"moves": False, "what": "", "volatile_moves": False}


def test_a_parsing_error_on_money_is_assessed_with_the_correct_value():
    wrong_in_ours = difference(101, "1-2", "revenue", 1_000_000, 1_000_000, ours=9_200_000, cls="parsing_error")
    table, overall = assess(wrong_in_ours)
    assert table.iloc[0]["moves_recommendation"] and overall["moves"]


def test_a_budget_difference_is_assessed_like_a_revenue_difference():
    table, _ = assess(difference(101, "1-2", "budget", 9_200_000, 1_000_000))  # the multiple falls from 9.2 to 1.0
    assert table.iloc[0]["moves_recommendation"]


def test_a_film_that_is_a_standalone_has_no_bundle_in_its_note():
    table, _ = assess(difference(300, "s0", "revenue", 5_000_000, 20_000_000))
    assert "bundle median" not in table.iloc[0]["impact"] and "film multiple 20.00 -> 5.00" in table.iloc[0]["impact"]


def test_fields_that_enter_no_ranking_cannot_move_it():
    rows = [difference(101, "1-2", "title", "New title", "1-2"), difference(101, "1-2", "imdb_id", "tt9", "tt1"),
            difference(101, "1-2", "vote_average", 9.9, 8.0, cls="volatile_changed")]
    table, overall = assess(*rows)
    assert not table["moves_recommendation"].any() and (table["impact"] == "").all()
    assert overall["moves"] is False


def test_matches_and_unverified_rows_are_left_alone():
    rows = [difference(101, "1-2", "revenue", 9_200_000, 9_200_000, cls="match"),
            difference(101, "1-2", "revenue", "", 9_200_000, cls="unverified")]
    table, overall = assess(*rows)
    assert not table["moves_recommendation"].any() and overall["moves"] is False


def test_a_fresh_vote_count_that_reorders_the_vote_rank_is_reported():
    # s0 has 5000 votes and s1 4900: a fresh count of 5200 for s1 puts it first
    table, overall = assess(difference(301, "s1", "vote_count", 5200, 4900, cls="volatile_changed"))
    assert table.iloc[0]["moves_recommendation"] and overall["volatile_moves"] and overall["moves"]


def test_a_fresh_vote_count_that_keeps_the_order_does_not_move_anything():
    table, overall = assess(difference(301, "s1", "vote_count", 4950, 4900, cls="volatile_changed"))
    assert not table.iloc[0]["moves_recommendation"]
    assert overall == {"moves": False, "what": "", "volatile_moves": False}


def test_several_vote_counts_are_checked_together_as_well_as_one_at_a_time():
    rows = [difference(301, "s1", "vote_count", 4950, 4900, cls="volatile_changed"),
            difference(302, "s2", "vote_count", 4850, 4800, cls="volatile_changed")]
    table, overall = assess(*rows)
    assert not table["moves_recommendation"].any() and overall["volatile_moves"] is False


def test_no_differences_means_no_assessment_and_no_inputs_are_changed():
    films = impact_films()
    before = films.copy()
    comparison = pd.DataFrame([difference(101, "1-2", "revenue", 9_200_000, 9_200_000, cls="match")])
    table, overall = spotcheck.assess_impact(comparison, films)
    assert table["moves_recommendation"].eq(False).all() and overall["moves"] is False
    spotcheck.assess_impact(pd.DataFrame([difference(101, "1-2", "revenue", 1_000_000, 9_200_000)]), films)
    pd.testing.assert_frame_equal(films, before)


def test_the_assessment_never_touches_the_snapshot(fetch_env):
    config.RAW_DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    (config.RAW_DETAILS_DIR / "101.json").write_text("{}", encoding="utf-8")
    before = tree_hash(config.RAW_DIR)
    assess(difference(101, "1-2", "revenue", 1_000_000, 9_200_000))
    assert tree_hash(config.RAW_DIR) == before


# --- the command ---------------------------------------------------------------------------------

class Replay(FakeSession):
    """A live answer that is the saved snapshot, optionally with a few values changed."""

    def __init__(self, changes=None):
        super().__init__()
        self.changes = changes or {}  # {(endpoint, tmdb_id): {field: new value}}

    def get(self, url, params=None, timeout=None):
        path = url.removeprefix(config.API_BASE)
        self.calls.append(path)
        endpoint = "credits" if path.endswith("/credits") else "details"
        tmdb_id = int(path.split("/")[2])
        body = json.loads(fetch.cache_file(endpoint, tmdb_id).read_bytes())
        body.update(self.changes.get((endpoint, tmdb_id), {}))
        return FakeResponse(200, json.dumps(body).encode("utf-8"))


@pytest.fixture
def pipeline_env(write_ids, fetch_env, monkeypatch):
    """A small snapshot and outputs made by the real pipeline, all under tmp_path."""
    monkeypatch.setattr(config, "INPUT_IDS", write_ids(IDS))
    monkeypatch.setattr(config, "OUT_DIR", fetch_env.tmp_path / "out")
    monkeypatch.setattr(config, "LIMITED_OUT_DIR", fetch_env.tmp_path / "out" / "limited")
    assert run_pipeline.main([], session=fake()) == 0
    return fetch_env


def test_the_command_runs_end_to_end_and_writes_both_files_and_a_log_line(pipeline_env, capsys):
    capsys.readouterr()
    assert command.main(session=Replay()) == 0
    text = capsys.readouterr().out
    assert text.startswith("Spot-check against the live API (snapshot ") and "  recommendation   unchanged" in text
    out = pipeline_env.tmp_path / "out"
    table = pd.read_csv(out / "spotcheck.csv")
    assert list(table.columns) == spotcheck.OUTPUT_COLUMNS
    assert set(table["class"]) == {"match"}  # the live answer is the snapshot, so nothing differs
    summary = pd.read_csv(out / "spotcheck_summary.csv").set_index("metric")["value"]
    assert int(summary["fields_compared"]) == len(table) == 14 * int(summary["films_checked"])
    assert int(summary["class_match"]) == len(table) and summary["recommendation_changed"] == "False"
    last = json.loads((out / "run_log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert last["kind"] == "spotcheck" and last["by_class"]["match"] == len(table) and last["stopped"] is None


def test_the_command_leaves_data_raw_and_the_fetch_log_byte_identical(pipeline_env):
    before = tree_hash(config.RAW_DIR)
    assert any(name.endswith("fetch_log.csv") for name in before)
    assert command.main(session=Replay()) == 0
    assert tree_hash(config.RAW_DIR) == before


def test_pipeline_outputs_are_not_changed_by_the_check_except_its_own_files(pipeline_env):
    out = pipeline_env.tmp_path / "out"
    before = {p.name: p.read_bytes() for p in out.glob("*.csv")}
    command.main(session=Replay())
    after = {p.name: p.read_bytes() for p in out.glob("*.csv")}
    assert {k: v for k, v in after.items() if k not in ("spotcheck.csv", "spotcheck_summary.csv")} == before


def test_a_changed_live_value_is_reported_as_a_source_change_with_the_two_values(pipeline_env, capsys):
    capsys.readouterr()
    assert command.main(session=Replay({("details", 155): {"title": "A New Title"}})) == 0
    table = pd.read_csv(pipeline_env.tmp_path / "out" / "spotcheck.csv", keep_default_na=False)
    row = table[(table["tmdb_id"] == 155) & (table["field"] == "title")].iloc[0]
    assert row["class"] == "source_changed" and row["fresh"] == "A New Title"
    assert row["raw"] == row["ours"] == "Film 155"
    assert "1 source changed" in capsys.readouterr().out


def test_the_run_pipeline_command_never_runs_the_spot_check():
    assert "spotcheck" not in (Path(config.REPO_ROOT) / "run_pipeline.py").read_text(encoding="utf-8")


def test_a_rejected_key_stops_the_command_and_writes_nothing(pipeline_env, capsys):
    capsys.readouterr()
    session = FakeSession({"/movie/155": FakeResponse(401, b"{}")})
    assert command.main(session=session) == 1
    assert "STOPPED: API key rejected (401)" in capsys.readouterr().out
    assert not (pipeline_env.tmp_path / "out" / "spotcheck.csv").exists()


def test_missing_outputs_stop_with_a_plain_message(write_ids, fetch_env, monkeypatch, capsys):
    monkeypatch.setattr(config, "OUT_DIR", fetch_env.tmp_path / "nothing_here")
    assert command.main(session=FakeSession()) == 1
    assert "Run python run_pipeline.py first" in capsys.readouterr().out


def test_no_key_stops_the_command_before_any_request(pipeline_env, monkeypatch, capsys):
    monkeypatch.delenv("TMDB_API_KEY")
    session = FakeSession()
    assert command.main(session=session) == 1
    assert "TMDB_API_KEY not set" in capsys.readouterr().out and session.calls == []


def pin_selection_to_film_155():
    """Make film 155 the slowest response in the fetch log, so it is the only film the spot-check picks.

    Otherwise the choice of film for the nearly-failed slice follows the real response times of the
    test's own run and film 603 is sometimes picked as well.
    """
    log = pd.read_csv(config.FETCH_LOG)
    log.loc[log["tmdb_id"] == 155, "elapsed_s"] = 99.0
    log.to_csv(config.FETCH_LOG, index=False)


def test_the_key_appears_in_no_output_not_even_when_a_request_fails(pipeline_env, capsys):
    capsys.readouterr()
    err = requests.ConnectionError(f"failed: {config.API_BASE}/movie/155?api_key={TEST_KEY}")
    pin_selection_to_film_155()
    down = FakeSession({"/movie/155": err, "/movie/155/credits": err})
    assert command.main(session=down) == 0  # two failed requests are not enough to stop; the fields are unverified
    table = pd.read_csv(pipeline_env.tmp_path / "out" / "spotcheck.csv", keep_default_na=False)
    assert set(table["class"]) == {"unverified"}
    assert command.main(session=Replay()) == 0  # and a normal run
    shown = capsys.readouterr()
    assert TEST_KEY not in shown.out + shown.err
    for path in pipeline_env.tmp_path.rglob("*"):
        if path.is_file():
            assert TEST_KEY.encode() not in path.read_bytes(), path


# --- the printed summary --------------------------------------------------------------------------

def summary_inputs(classes, stand_in=False):
    selection = pd.DataFrame({
        "slice": [
            "heaviest_parsing", "extreme_high", "nearly_failed", "drives_recommendation", "drives_recommendation",
        ],
        "tmdb_id": [1, 2, 3, 4, 5], "detail": "",
        "title": ["Batman Begins", "Star Wars", "Back to the Future Part II", "The Fellowship", "The Two Towers"],
        "stand_in": [False, False, stand_in, False, False],
    })
    return selection, pd.DataFrame({"class": classes})


def test_the_summary_lists_every_slice_and_the_standin_footnote():
    selection, comparison = summary_inputs(["match"] * 4, stand_in=True)
    text = spotcheck.format_summary(selection, comparison, {"moves": False, "what": "", "volatile_moves": False},
                                    "2026-11-20", "2026-11-20 10:00 UTC")
    assert text.startswith("Spot-check against the live API (snapshot 2026-11-20, checked 2026-11-20 10:00 UTC)")
    assert "films        5   (heaviest parsing: Batman Begins | extreme high: Star Wars" in text
    assert "nearly failed*: Back" in text.replace("\n                    ", " ")
    assert "drives recommendation: The Fellowship, The Two Towers)" in text.replace("\n                    ", " ")
    assert "* no request needed a retry; slowest response used instead" in text
    assert "  fields       4 compared: 4 match | 0 source changed | 0 volatile changed | 0 parsing error" in text
    assert "0 parsing error | 0 wrong field" in text
    assert text.rstrip().endswith("  recommendation   unchanged")


def test_the_summary_has_no_footnote_when_a_request_really_was_retried():
    selection, comparison = summary_inputs(["match"], stand_in=False)
    none = {"moves": False, "what": "", "volatile_moves": False}
    text = spotcheck.format_summary(selection, comparison, none, "d", "t")
    assert "nearly failed:" in text.replace("\n                    ", " ") and "*" not in text


def test_the_summary_names_a_change_to_the_recommendation():
    selection, comparison = summary_inputs(["match", "source_changed"])
    overall = {"moves": True, "what": "robust candidate Collection 1 -> Collection 2", "volatile_moves": False}
    text = spotcheck.format_summary(selection, comparison, overall, "d", "t")
    assert text.rstrip().endswith("  recommendation   CHANGED: robust candidate Collection 1 -> Collection 2")
    assert "1 source changed" in text


def test_the_summary_counts_the_unusual_classes_only_when_they_occur():
    selection, comparison = summary_inputs(
        ["match", "parsing_error_and_source_changed", "unverified", "volatile_changed"]
    )
    volatile = {"moves": False, "what": "", "volatile_moves": True}
    text = spotcheck.format_summary(selection, comparison, volatile, "d", "t")
    assert "1 both parsing error and source change" in text and "1 unverified (no live answer)" in text
    assert "1 fields changed since the snapshot; a vote rank in the shortlist changes" in text
    plain = spotcheck.format_summary(selection, pd.DataFrame({"class": ["match"]}),
                                     {"moves": False, "what": "", "volatile_moves": False}, "d", "t")
    assert "unverified" not in plain and "both parsing" not in plain and "volatile  " not in plain


def test_the_summary_table_has_a_row_for_every_class_even_when_zero():
    selection, comparison = summary_inputs(["match", "match", "source_changed"])
    checked = spotcheck.films_to_check(selection.assign(slice=selection["slice"]))
    table = spotcheck.summarize(comparison, checked, {"moves": False, "what": "", "volatile_moves": False})
    values = table.set_index("metric")["value"]
    assert values["films_checked"] == 5 and values["fields_compared"] == 3 and values["discrepancies"] == 1
    for name in spotcheck.CLASSES:
        assert f"class_{name}" in values.index
    assert values["class_match"] == 2 and values["class_wrong_field"] == 0 and values["recommendation_changed"] is False


def test_a_revenue_that_moves_the_robust_candidate_makes_the_command_print_changed(fetch_env, tmp_path, capsys):
    films = impact_films().assign(
        n_cast=20, n_crew=20, n_genres=1, imdb_id=pd.array([pd.NA] * 13, dtype="string"),
        release_date_raw="2005-06-01", genres_all="Action", vote_average=7.0, popularity=1.0,
    )
    ids = pd.DataFrame({"tmdb_id": films["tmdb_id"], "n_occurrences": 1})
    quarantine = pd.DataFrame({"stage": [], "reason_code": [], "raw_value": []})
    deal = pd.DataFrame({"candidate": ["robust candidate"], "collection_id": [1], "collection_name": ["Collection 1"]})
    log = pd.DataFrame({"tmdb_id": films["tmdb_id"], "endpoint": "details", "attempts": 1, "elapsed_s": 0.3,
                        "fetched_at": "2026-11-20T04:00:00+00:00"})
    talent = pd.DataFrame({"tmdb_id": [], "person_id": [], "role": [], "billing_rank": []})
    config.RAW_DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    config.RAW_CREDITS_DIR.mkdir(parents=True, exist_ok=True)
    for film in films.to_dict("records"):  # a saved snapshot that agrees with our table
        details = {
            "id": film["tmdb_id"], "title": film["title"], "release_date": "2005-06-01", "status": "Released",
            "budget": int(film["budget"]), "revenue": int(film["revenue"]), "genres": [{"name": "Action"}],
            "belongs_to_collection": None if pd.isna(film["collection_id"]) else {"id": int(film["collection_id"])},
            "imdb_id": None, "vote_count": int(film["vote_count"]), "vote_average": 7.0, "popularity": 1.0,
        }
        (config.RAW_DETAILS_DIR / f"{film['tmdb_id']}.json").write_text(json.dumps(details), encoding="utf-8")
        credits_file = config.RAW_CREDITS_DIR / f"{film['tmdb_id']}.json"
        credits_file.write_text(json.dumps({"id": film["tmdb_id"]}), encoding="utf-8")
    tables = {"films_clean": films, "talent": talent, "ids_to_fetch": ids, "quarantine": quarantine,
              "deal_note": deal, "fetch_log": log}
    before = tree_hash(config.RAW_DIR)
    live = Replay({("details", 101): {"revenue": 1_000_000}})  # film 1-2: 9.2x falls to 1.0x
    result = spotcheck.run_spotcheck(tables, session=live, key=TEST_KEY, out_dir=tmp_path / "out")
    text = capsys.readouterr().out
    assert result["overall"]["moves"] and "  recommendation   CHANGED: " in text
    assert "robust candidate Collection 1 -> Collection 2" in text
    table = pd.read_csv(tmp_path / "out" / "spotcheck.csv", keep_default_na=False)
    moved = table[table["moves_recommendation"].astype(str) == "True"]
    assert "revenue" in set(moved["field"]) and set(moved["tmdb_id"]) == {101}  # only the film that changed
    assert tree_hash(config.RAW_DIR) == before


def test_the_run_log_line_goes_to_the_folder_given_not_to_the_default(pipeline_env, tmp_path, monkeypatch):
    other = tmp_path / "elsewhere"
    default_log = pipeline_env.tmp_path / "out" / "run_log.jsonl"
    before = default_log.read_bytes()
    tables = spotcheck.load_outputs()
    spotcheck.run_spotcheck(tables, session=Replay(), key=TEST_KEY, out_dir=other)
    assert default_log.read_bytes() == before  # the default folder's log is untouched
    assert json.loads((other / "run_log.jsonl").read_text(encoding="utf-8").splitlines()[-1])["kind"] == "spotcheck"
    assert (other / "spotcheck.csv").is_file() and (other / "spotcheck_summary.csv").is_file()


# --- release dates and collections ---------------------------------------------------------------

def window_films():
    """A pre-2000 standalone with the best multiple, six later standalones, and one bundle from 2000."""
    rows = [{"tmdb_id": 400, "title": "pre", "year": 1999, "votes": 100, **money(40)}]
    rows += [
        {"tmdb_id": 401 + i, "title": f"s{i}", "year": 2005 + i, "votes": 3000 - 100 * i, **money(20 - i)}
        for i in range(6)
    ]
    rows += [{"tmdb_id": 410, "title": "tail", "year": 1995, "votes": 50, **money(1.2)}]  # least-voted, worst multiple
    rows += [
        {"tmdb_id": 420 + i, "title": f"1-{i + 1}", "franchise": 1, "year": 2001 + 3 * i, **money(r)}
        for i, r in enumerate([4, 6, 8])
    ]
    return clean.add_flags(make_films(rows))


def test_a_fresh_release_date_that_moves_a_shortlisted_film_across_2000_moves_the_recommendation():
    table, overall = assess(difference(400, "pre", "release_date", "2001-06-01", "1999-06-01"), films=window_films())
    row = table.iloc[0]
    assert row["moves_recommendation"] and overall["moves"]
    assert "2000-onward window: film moves in" in row["impact"] and "a shortlist changes" in row["impact"]
    assert "pre release_date 1999-06-01 -> 2001-06-01" in row["impact"]


def test_a_new_release_date_on_the_same_side_of_2000_changes_nothing():
    table, overall = assess(difference(400, "pre", "release_date", "1998-01-01", "1999-06-01"), films=window_films())
    assert not table.iloc[0]["moves_recommendation"] and "2000-onward window: unchanged" in table.iloc[0]["impact"]
    assert overall["moves"] is False


def test_crossing_2000_does_not_move_it_when_the_film_stays_off_every_list():
    table, _ = assess(difference(410, "tail", "release_date", "2003-01-01", "1995-01-01"), films=window_films())
    row = table.iloc[0]
    assert "film moves in" in row["impact"] and not row["moves_recommendation"]


def test_a_bundle_film_that_leaves_the_window_can_drop_its_bundle_from_the_2000_onward_ranking():
    table, overall = assess(difference(421, "1-2", "release_date", "1999-03-01", "2004-06-01"), films=window_films())
    row = table.iloc[0]
    assert row["moves_recommendation"] and "2000-onward window: film moves out" in row["impact"]
    assert "bundle Collection 1" in row["impact"] and "(2000 onward 1 -> <NA>)" in row["impact"]  # only 2 films left
    assert overall["moves"]


def test_a_release_date_that_becomes_missing_takes_the_film_out_of_the_window():
    table, _ = assess(difference(401, "s0", "release_date", "", "2005-06-01"), films=window_films())
    assert "2000-onward window: film moves out" in table.iloc[0]["impact"] and table.iloc[0]["moves_recommendation"]


def test_a_fresh_collection_that_moves_a_standalone_into_a_bundle_moves_the_recommendation():
    # the best standalone joins collection 1, so it leaves the standalone lists and changes the bundle
    table, overall = assess(difference(400, "pre", "belongs_to_collection.id", 1, "", cls="source_changed"),
                            films=window_films())
    row = table.iloc[0]
    assert row["moves_recommendation"] and overall["moves"]
    assert "franchise film: no -> yes" in row["impact"]
    assert "bundle Collection 1: median 6.00 -> 7.00" in row["impact"]  # 4, 6, 8 becomes 4, 6, 8, 40


def test_a_film_that_leaves_its_collection_can_make_its_bundle_unrankable():
    table, _ = assess(difference(421, "1-2", "belongs_to_collection.id", "", 1), films=window_films())
    row = table.iloc[0]
    assert row["moves_recommendation"] and "franchise film: yes -> no" in row["impact"]
    assert "bundle Collection 1" in row["impact"] and "rank 1 -> <NA>" in row["impact"]


def test_a_low_ranked_standalone_joining_a_bundle_does_not_move_the_recommendation():
    # "tail" is on no list and has the fewest votes, so no rank or name on any shortlist changes
    table, _ = assess(difference(410, "tail", "belongs_to_collection.id", 1, ""), films=window_films())
    row = table.iloc[0]
    assert not row["moves_recommendation"] and "franchise film: no -> yes" in row["impact"]


def test_a_collection_the_list_does_not_know_yet_is_handled():
    table, _ = assess(difference(400, "pre", "belongs_to_collection.id", 99, ""), films=window_films())
    row = table.iloc[0]
    assert "franchise film: no -> yes" in row["impact"] and "Collection 99 (new)" in row["impact"]


def test_release_date_and_collection_matches_are_ignored():
    rows = [difference(400, "pre", "release_date", "1999-06-01", "1999-06-01", cls="match"),
            difference(400, "pre", "belongs_to_collection.id", "", "", cls="match")]
    table, overall = assess(*rows, films=window_films())
    assert not table["moves_recommendation"].any() and overall["moves"] is False


def test_a_changed_date_or_collection_does_not_alter_the_films_passed_in():
    films = window_films()
    before = films.copy()
    assess(difference(400, "pre", "release_date", "2001-06-01", "1999-06-01"),
           difference(400, "pre", "belongs_to_collection.id", 1, ""), films=films)
    pd.testing.assert_frame_equal(films, before)
