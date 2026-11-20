"""Looking up IMDb ids through the find endpoint. A fake session answers; nothing touches the network."""
import json
import os
import time

import pytest
import requests

from pipeline import config, resolve
from pipeline.errors import PipelineStopError
from tests.conftest import TEST_KEY, FakeResponse, FakeSession

pytestmark = pytest.mark.usefixtures("fetch_env")

DARK_KNIGHT = {"id": 155, "title": "The Dark Knight", "release_date": "2008-07-16"}
OTHER = {"id": 9999, "title": "Another Film", "release_date": "1999-01-01"}


def find_body(*films):
    return json.dumps({"movie_results": list(films), "person_results": [], "tv_results": []}).encode("utf-8")


def answer(*films, status=200):
    return FakeResponse(status, find_body(*films))


def session_for(**by_imdb):
    return FakeSession({f"/find/{imdb}": response for imdb, response in by_imdb.items()})


def lookup(ids, session=None, key=TEST_KEY):
    return resolve.lookup_all(ids, session=session, key=key)


def test_one_film_in_movie_results_is_resolved_with_its_id_title_and_year():
    [one] = lookup(["tt0468569"], session_for(tt0468569=answer(DARK_KNIGHT)))
    assert (one.outcome, one.tmdb_id, one.title, one.release_year) == ("resolved", 155, "The Dark Knight", 2008)
    assert one.source == "network" and one.note == ""


def test_no_film_is_not_found():
    [one] = lookup(["tt0000001"], session_for(tt0000001=answer()))
    assert one.outcome == "not_found" and one.tmdb_id is None and "no film" in one.note


def test_more_than_one_film_is_ambiguous_and_both_candidates_are_in_the_note():
    [one] = lookup(["tt0000002"], session_for(tt0000002=answer(DARK_KNIGHT, OTHER)))
    assert one.outcome == "ambiguous" and one.tmdb_id is None
    assert "155 The Dark Knight (2008)" in one.note and "9999 Another Film (1999)" in one.note


def test_a_film_with_no_release_date_has_no_year():
    [one] = lookup(["tt0000003"], session_for(tt0000003=answer({"id": 5, "title": "Undated", "release_date": ""})))
    assert one.outcome == "resolved" and one.release_year is None


def test_a_request_that_fails_is_recorded_and_the_other_ids_carry_on():
    session = session_for(tt0000004=FakeResponse(500, b"{}"), tt0468569=answer(DARK_KNIGHT))
    failed, resolved = lookup(["tt0000004", "tt0468569"], session)
    assert (failed.outcome, failed.note) == ("failed", "HTTP 500")
    assert resolved.outcome == "resolved"
    assert not resolve.find_file("tt0000004").exists()  # a failure is not saved


def test_a_network_error_is_a_failed_lookup_not_a_crash():
    session = session_for(tt0000005=requests.ConnectionError("no route"))
    [one] = lookup(["tt0000005"], session)
    assert one.outcome == "failed" and "ConnectionError" in one.note


def test_an_answer_that_is_not_the_expected_json_is_failed():
    session = session_for(tt0000006=FakeResponse(200, b"<html>"))
    [one] = lookup(["tt0000006"], session)
    assert one.outcome == "failed" and "not valid JSON" in one.note
    assert not resolve.find_file("tt0000006").exists()


def test_a_rejected_key_stops_everything():
    with pytest.raises(PipelineStopError, match="401"):
        lookup(["tt0468569"], session_for(tt0468569=FakeResponse(401, b"{}")))


def test_a_good_answer_is_saved_as_received_under_data_raw_find():
    lookup(["tt0468569"], session_for(tt0468569=answer(DARK_KNIGHT)))
    path = resolve.find_file("tt0468569")
    assert path == config.RAW_DIR / "find" / "tt0468569.json"
    assert path.read_bytes() == find_body(DARK_KNIGHT)


def test_a_saved_answer_is_reused_and_a_second_run_makes_no_request():
    lookup(["tt0468569", "tt0000001"], session_for(tt0468569=answer(DARK_KNIGHT), tt0000001=answer()))
    again = FakeSession()
    first, second = lookup(["tt0468569", "tt0000001"], again)
    assert again.calls == []
    assert (first.outcome, first.source, second.outcome, second.source) == ("resolved", "cache", "not_found", "cache")


def test_a_saved_answer_older_than_180_days_is_asked_for_again():
    lookup(["tt0468569"], session_for(tt0468569=answer(DARK_KNIGHT)))
    old = time.time() - (config.CACHE_MAX_AGE_DAYS + 1) * 86400
    os.utime(resolve.find_file("tt0468569"), (old, old))
    session = session_for(tt0468569=answer(OTHER))
    [one] = lookup(["tt0468569"], session)
    assert session.calls == ["/find/tt0468569"] and one.tmdb_id == 9999 and one.source == "network"


def test_a_saved_answer_that_is_damaged_is_asked_for_again():
    lookup(["tt0468569"], session_for(tt0468569=answer(DARK_KNIGHT)))
    resolve.find_file("tt0468569").write_bytes(b"{broken")
    session = session_for(tt0468569=answer(DARK_KNIGHT))
    [one] = lookup(["tt0468569"], session)
    assert session.calls == ["/find/tt0468569"] and one.outcome == "resolved"


def test_the_same_id_twice_is_asked_for_once_and_answered_twice():
    session = session_for(tt0468569=answer(DARK_KNIGHT))
    results = lookup(["tt0468569", "tt0468569"], session)
    assert session.calls == ["/find/tt0468569"] and [r.tmdb_id for r in results] == [155, 155]


def test_a_value_that_is_not_an_imdb_id_is_never_sent():
    session = FakeSession()
    results = lookup(["../../movie/155", "tt12"], session)
    assert [r.outcome for r in results] == ["failed", "failed"] and session.calls == []
    assert all("Not an IMDb id" in r.note for r in results)


def test_the_request_asks_for_the_imdb_id_source_with_the_key_and_the_usual_timeout():
    seen = {}

    class Recording(FakeSession):
        def get(self, url, params=None, timeout=None):
            seen.update(url=url, params=params, timeout=timeout)
            return super().get(url, params, timeout)

    lookup(["tt0468569"], Recording({"/find/tt0468569": answer(DARK_KNIGHT)}))
    assert seen["url"] == f"{config.API_BASE}/find/tt0468569"
    assert seen["params"] == {"api_key": TEST_KEY, "external_source": "imdb_id"}
    assert seen["timeout"] == config.TIMEOUT


def test_without_a_key_a_missing_answer_stops_with_a_plain_message_and_makes_no_request():
    session = FakeSession()
    with pytest.raises(PipelineStopError, match="TMDB_API_KEY not set"):
        lookup(["tt0468569"], session, key=None)
    assert session.calls == []


def test_without_a_key_saved_answers_still_work():
    lookup(["tt0468569"], session_for(tt0468569=answer(DARK_KNIGHT)))
    [one] = lookup(["tt0468569"], FakeSession(), key=None)
    assert one.outcome == "resolved"


def test_the_key_never_appears_in_a_note_or_a_saved_file(fetch_env, capsys):
    url = f"{config.API_BASE}/find/tt0000007?api_key={TEST_KEY}"
    session = session_for(tt0000007=requests.ConnectionError(f"Max retries exceeded with url: {url}"))
    [one] = lookup(["tt0000007"], session)
    print(one)
    shown = capsys.readouterr()
    assert TEST_KEY not in one.note + shown.out + shown.err and "api_key=***" in one.note
    for path in fetch_env.tmp_path.rglob("*"):
        if path.is_file():
            assert TEST_KEY.encode() not in path.read_bytes(), path
