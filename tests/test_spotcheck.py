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
    assert "film multiple 9.20 -> 1.00" in row["impact"] and "bundle median 9.20 -> 9.00" in row["impact"]
    assert overall["moves"] and "Collection 1 -> Collection 2" in overall["what"]


def test_a_change_that_leaves_the_ranking_alone_does_not_move_it():
    table, overall = assess(difference(100, "1-1", "revenue", 11_000_000, 12_000_000))  # 12.0 down to 11.0
    row = table.iloc[0]
    assert not row["moves_recommendation"] and "robust candidate unchanged" in row["impact"]
    assert "shortlists unchanged" in row["impact"] and "bundle median 9.20 -> 9.20" in row["impact"]
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
