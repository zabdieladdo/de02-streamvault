"""The fetch stage builds one snapshot per endpoint from the per-film files. No network: a FakeSession answers."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pipeline import config, fetch
from pipeline.errors import PipelineStopError
from tests.conftest import NOT_FOUND_BODY, TEST_KEY, FakeResponse, FakeSession
from tests.test_fetch import make_ids, read_log

pytestmark = pytest.mark.usefixtures("fetch_env")

REPO = Path(config.REPO_ROOT)


def tree_hash(root: Path) -> dict:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def per_film_files() -> dict:
    both = {**tree_hash(config.RAW_DETAILS_DIR)}
    both.update({"c" + k: v for k, v in tree_hash(config.RAW_CREDITS_DIR).items()})
    return both


def lines(endpoint):
    text = fetch.snapshot_file(endpoint).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.split(chr(10)) if line]


def state_of_snapshots():
    files = {n: fetch.snapshot_file(n) for n in fetch.SNAPSHOT_NAMES}
    return {n: (f.stat().st_mtime_ns, f.read_bytes()) for n, f in files.items()}


def fetch_two():
    return fetch.fetch_all(make_ids(603, 155), session=FakeSession(), key=TEST_KEY)


def test_the_snapshots_are_named_for_their_endpoint_and_sit_beside_the_per_film_folders():
    assert fetch.snapshot_file("details") == config.RAW_DIR / "snapshot_movie.jsonl"
    assert fetch.snapshot_file("credits") == config.RAW_DIR / "snapshot_credits.jsonl"


def test_after_a_fetch_each_snapshot_has_one_line_per_ok_film_matching_its_file_and_the_log():
    fetch_two()
    log = read_log()
    for endpoint in ("details", "credits"):
        got = lines(endpoint)
        assert [r["tmdb_id"] for r in got] == [155, 603]
        assert all(set(r) == {"tmdb_id", "fetched_at", "response"} for r in got)
        for record in got:
            saved = json.loads(fetch.cache_file(endpoint, record["tmdb_id"]).read_bytes())
            assert record["response"] == saved
            row = log[(log["tmdb_id"] == str(record["tmdb_id"])) & (log["endpoint"] == endpoint)].iloc[0]
            assert record["fetched_at"] == row["fetched_at"]


def test_a_film_that_was_not_found_or_failed_is_not_in_the_snapshot():
    session = FakeSession({
        "/movie/404": FakeResponse(404, NOT_FOUND_BODY),
        "/movie/500": FakeResponse(500, b"{}"),
    })
    fetch.fetch_all(make_ids(603, 404, 500), session=session, key=TEST_KEY)
    assert [r["tmdb_id"] for r in lines("details")] == [603]
    assert [r["tmdb_id"] for r in lines("credits")] == [500, 603]  # its credits did come back ok; 404 had none


def test_the_snapshot_is_written_to_a_temp_file_and_renamed_so_none_is_left_behind():
    fetch_two()
    names = sorted(p.name for p in config.RAW_DIR.glob("snapshot_*"))
    assert names == ["snapshot_credits.jsonl", "snapshot_movie.jsonl"]


def test_the_snapshot_text_is_unchanged_when_the_responses_hold_non_ascii_and_odd_characters():
    config.RAW_DETAILS_DIR.mkdir(parents=True)
    body = {"id": 7, "title": "Amélie   é \"quoted\" 中文", "budget": 1_000_000, "vote_average": 7.3}
    (config.RAW_DETAILS_DIR / "7.json").write_text(json.dumps(body), encoding="utf-8")
    at = datetime.now(UTC).isoformat(timespec="seconds")
    log = {(7, "details"): {"outcome": "ok", "fetched_at": at}}
    fetch.build_snapshot("details", log)
    assert fetch.read_snapshot("details") == {7: (at, body)}


def test_a_run_that_changes_nothing_leaves_the_snapshots_as_they_are():
    fetch_two()
    before = state_of_snapshots()
    again = FakeSession()
    run = fetch.fetch_all(make_ids(603, 155), session=again, key=TEST_KEY)
    assert again.calls == [] and run.extra["snapshot_build_s"] < 0.5
    assert state_of_snapshots() == before


def test_the_fetch_stage_records_how_long_the_build_took():
    run = fetch_two()
    assert run.extra["snapshot_build_s"] > 0


def test_a_new_film_fetched_later_is_added_to_the_snapshot():
    fetch.fetch_all(make_ids(603), session=FakeSession(), key=TEST_KEY)
    fetch.fetch_all(make_ids(603, 155), session=FakeSession(), key=TEST_KEY)
    assert [r["tmdb_id"] for r in lines("details")] == [155, 603]


def test_a_missing_snapshot_is_built_even_when_every_response_is_cached():
    fetch_two()
    for name in fetch.SNAPSHOT_NAMES:
        fetch.snapshot_file(name).unlink()
    quiet = FakeSession()
    fetch.fetch_all(make_ids(603, 155), session=quiet, key=TEST_KEY)
    assert quiet.calls == [] and len(lines("details")) == 2 and len(lines("credits")) == 2


# --- the 180 days ---------------------------------------------------------------------------------------

def age_one(tmdb_id, days):
    log = read_log()
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
    log.loc[log["tmdb_id"] == str(tmdb_id), "fetched_at"] = old
    log.to_csv(config.FETCH_LOG, index=False)


def test_a_film_past_the_180_day_limit_is_left_out_of_the_snapshot_when_it_is_rebuilt():
    fetch_two()
    age_one(603, config.CACHE_MAX_AGE_DAYS + 20)
    fetch.build_snapshots(fetch.read_fetch_log())
    assert [r["tmdb_id"] for r in lines("details")] == [155]
    assert [r["tmdb_id"] for r in lines("credits")] == [155]


def test_a_film_just_inside_the_limit_stays_in():
    fetch_two()
    age_one(603, config.CACHE_MAX_AGE_DAYS - 1)
    fetch.build_snapshots(fetch.read_fetch_log())
    assert [r["tmdb_id"] for r in lines("details")] == [155, 603]


def test_a_refetched_expired_film_is_back_in_with_its_new_time():
    fetch_two()
    age_one(603, config.CACHE_MAX_AGE_DAYS + 20)
    fetch.fetch_all(make_ids(603, 155), session=FakeSession(), key=TEST_KEY)  # 603 expired, so it is requested again
    held = fetch.read_snapshot("details")
    assert sorted(held) == [155, 603]
    assert datetime.fromisoformat(held[603][0]) > datetime.now(UTC) - timedelta(minutes=5)


def test_a_film_whose_file_was_removed_is_left_out_until_it_is_fetched_again():
    fetch_two()
    fetch.cache_file("details", 603).unlink()
    fetch.build_snapshots(fetch.read_fetch_log())
    assert [r["tmdb_id"] for r in lines("details")] == [155] and [r["tmdb_id"] for r in lines("credits")] == [155, 603]


def test_a_file_that_is_not_valid_json_is_left_out_so_flatten_can_quarantine_it_from_its_own_file():
    fetch_two()
    fetch.cache_file("credits", 603).write_bytes(b"{not json")
    fetch.build_snapshots(fetch.read_fetch_log())
    assert [r["tmdb_id"] for r in lines("credits")] == [155]


# --- what a build must not touch -------------------------------------------------------------------------

def test_building_changes_no_per_film_file_and_the_log_and_the_input_list_stay_as_they_were():
    fetch_two()
    files, log = per_film_files(), config.FETCH_LOG.read_bytes()
    ids_before = (REPO / "data" / "input" / "id_list.csv").read_bytes()
    for name in fetch.SNAPSHOT_NAMES:
        fetch.snapshot_file(name).unlink()
    fetch.build_snapshots(fetch.read_fetch_log())
    assert per_film_files() == files and config.FETCH_LOG.read_bytes() == log
    assert (REPO / "data" / "input" / "id_list.csv").read_bytes() == ids_before
    assert REPO not in config.RAW_DIR.parents  # a temp folder, not data/raw


def test_the_snapshot_files_contain_no_key():
    fetch_two()
    for name in fetch.SNAPSHOT_NAMES:
        assert TEST_KEY not in fetch.snapshot_file(name).read_text(encoding="utf-8")


def test_a_snapshot_that_cannot_be_written_stops_the_run_at_check_c_34(monkeypatch):
    real_replace = fetch.os.replace

    def refuse(source, target):
        if Path(target).name.startswith("snapshot_"):
            raise OSError("disk full")
        real_replace(source, target)

    monkeypatch.setattr(fetch.os, "replace", refuse)
    with pytest.raises(PipelineStopError, match="response snapshots") as stopped:
        fetch.fetch_all(make_ids(603), session=FakeSession(), key=TEST_KEY)
    assert stopped.value.check_id == "C-34"


def test_the_same_responses_always_give_the_same_snapshot_bytes():
    fetch_two()
    first = {n: fetch.snapshot_file(n).read_bytes() for n in fetch.SNAPSHOT_NAMES}
    fetch.build_snapshots(fetch.read_fetch_log())
    assert {n: fetch.snapshot_file(n).read_bytes() for n in fetch.SNAPSHOT_NAMES} == first
