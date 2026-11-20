"""The resolve_ids command: the report, the suggested list, and that the client's file is never touched."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import requests

import resolve_ids
from pipeline import config, resolve
from tests.conftest import TEST_KEY, FakeResponse, FakeSession

REAL_INPUT = Path(config.REPO_ROOT) / "data" / "input" / "id_list.csv"
DARK_KNIGHT = {"id": 155, "title": "The Dark Knight", "release_date": "2008-07-16"}
NEW_FILM = {"id": 603, "title": "The Matrix", "release_date": "1999-03-30"}
OTHER = {"id": 9999, "title": "Another Film", "release_date": "1999-01-01"}


def answer(*films):
    body = {"movie_results": list(films), "person_results": []}
    return FakeResponse(200, json.dumps(body).encode("utf-8"))


@pytest.fixture
def world(fetch_env, monkeypatch):
    """A finished run's outputs in a temporary out folder: ids 155 (line 2), 165 (line 3), 278 (line 4)."""
    out = fetch_env.tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(config, "OUT_DIR", out)
    ids = pd.DataFrame({"tmdb_id": [155, 165, 278], "first_line_number": [2, 3, 4]})
    ids.to_csv(out / "ids_to_fetch.csv", index=False)
    write_quarantine(out, [(95, "tt0468569")])
    return out


def write_quarantine(out, imdb_rows):
    rows = [(18, "8471293", "not_found_on_api"), (30, "-1", "not_positive"), (43, "603", "repeat")]
    rows += [(line, value, "imdb_id_not_tmdb") for line, value in imdb_rows]
    pd.DataFrame(rows, columns=["line_number", "raw_value", "reason_code"]).assign(
        reason_detail="x", stage="load", run_at="t").to_csv(out / "quarantine.csv", index=False)


def run(out, **by_imdb):
    session = FakeSession({f"/find/{imdb}": response for imdb, response in by_imdb.items()})
    code = resolve_ids.main([], session=session)
    return code, session


def resolved(out) -> pd.DataFrame:
    return pd.read_csv(out / "resolved_ids.csv", keep_default_na=False)


def input_hash():
    return hashlib.sha256(REAL_INPUT.read_bytes()).hexdigest()


def test_a_film_already_on_the_list_says_so_with_its_first_line_and_writes_no_suggestion(world, capsys):
    code, _ = run(world, tt0468569=answer(DARK_KNIGHT))
    row = resolved(world).iloc[0]
    assert code == 0 and row["outcome"] == "resolved" and row["already_in_list"] and row["first_line_number"] == 2
    assert (row["line_number"], row["imdb_id"], row["tmdb_id"], row["title"], row["release_year"]) == (
        95, "tt0468569", 155, "The Dark Knight", 2008)
    assert not (world / "id_list_suggested.csv").exists()
    assert capsys.readouterr().out == (
        "IMDb id resolver\n"
        "  ids found in quarantine   1\n"
        "  tt0468569   ->  155  The Dark Knight (2008)   already on the list (line 2): nothing to add\n"
        "  suggested list            not written (no new films)\n"
    )


def test_the_table_has_exactly_the_agreed_columns(world):
    run(world, tt0468569=answer(DARK_KNIGHT))
    assert list(resolved(world).columns) == [
        "line_number", "imdb_id", "outcome", "tmdb_id", "title", "release_year", "already_in_list",
        "first_line_number", "note",
    ]


def test_a_new_film_goes_into_the_suggested_list_after_the_clients_valid_ids(world, capsys):
    code, _ = run(world, tt0468569=answer(NEW_FILM))
    row = resolved(world).iloc[0]
    assert code == 0 and row["outcome"] == "resolved" and not row["already_in_list"] and row["first_line_number"] == ""
    suggested = pd.read_csv(world / "id_list_suggested.csv")
    assert list(suggested.columns) == ["tmdb_id"] and suggested["tmdb_id"].tolist() == [155, 165, 278, 603]
    printed = capsys.readouterr().out
    assert "603  The Matrix (1999)   not on the list: added to the suggested list" in printed
    assert "written to" in printed and "(3 ids from the client's list + 1 new)" in printed
    assert "copy it out of the out folder" in printed


def test_not_found_is_reported_and_nothing_is_suggested(world):
    code, _ = run(world, tt0468569=answer())
    row = resolved(world).iloc[0]
    assert code == 0 and row["outcome"] == "not_found" and row["tmdb_id"] == "" and not row["already_in_list"]
    assert not (world / "id_list_suggested.csv").exists()


def test_an_ambiguous_id_names_both_candidates_and_nothing_is_suggested(world):
    code, _ = run(world, tt0468569=answer(DARK_KNIGHT, NEW_FILM))
    row = resolved(world).iloc[0]
    assert code == 0 and row["outcome"] == "ambiguous" and row["tmdb_id"] == ""
    assert "155 The Dark Knight (2008)" in row["note"] and "603 The Matrix (1999)" in row["note"]
    assert not (world / "id_list_suggested.csv").exists()


def test_a_failed_lookup_is_reported_and_the_run_still_exits_0(world, capsys):
    code, _ = run(world, tt0468569=FakeResponse(500, b"{}"))
    row = resolved(world).iloc[0]
    assert code == 0 and row["outcome"] == "failed" and row["note"] == "HTTP 500"
    assert "failed, not added: HTTP 500" in capsys.readouterr().out
    assert not (world / "id_list_suggested.csv").exists()


def test_one_failure_does_not_stop_the_others_and_the_new_film_is_still_suggested(world):
    write_quarantine(world, [(95, "tt0468569"), (96, "tt0000002"), (97, "tt0000003")])
    code, _ = run(world, tt0468569=FakeResponse(500, b"{}"), tt0000002=answer(NEW_FILM), tt0000003=answer(DARK_KNIGHT))
    table = resolved(world)
    assert code == 0 and list(table["outcome"]) == ["failed", "resolved", "resolved"]
    assert list(table["already_in_list"]) == [False, False, True]
    assert pd.read_csv(world / "id_list_suggested.csv")["tmdb_id"].tolist() == [155, 165, 278, 603]


def test_two_imdb_ids_for_the_same_new_film_add_it_once(world):
    write_quarantine(world, [(95, "tt0000002"), (96, "tt0000003")])
    run(world, tt0000002=answer(NEW_FILM), tt0000003=answer(NEW_FILM))
    assert pd.read_csv(world / "id_list_suggested.csv")["tmdb_id"].tolist() == [155, 165, 278, 603]


def test_a_second_run_uses_the_saved_answer_and_makes_no_request(world):
    run(world, tt0468569=answer(DARK_KNIGHT))
    code, again = run(world)
    assert code == 0 and again.calls == [] and resolved(world).iloc[0]["outcome"] == "resolved"


def test_a_suggestion_from_an_earlier_run_is_removed_when_there_is_nothing_new(world):
    run(world, tt0468569=answer(NEW_FILM))
    assert (world / "id_list_suggested.csv").exists()
    (world / "ids_to_fetch.csv").write_text("tmdb_id,first_line_number\n155,2\n603,5\n", encoding="utf-8")
    run(world)  # the saved answer is the new film, which is now on the list
    assert not (world / "id_list_suggested.csv").exists() and resolved(world).iloc[0]["already_in_list"]


def test_with_no_imdb_ids_it_says_so_writes_nothing_and_exits_0(world, capsys):
    write_quarantine(world, [])
    session = FakeSession()
    assert resolve_ids.main([], session=session) == 0
    assert capsys.readouterr().out == "No IMDb ids to resolve\n"
    assert session.calls == [] and not (world / "resolved_ids.csv").exists()


def test_without_the_pipeline_outputs_it_stops_with_a_plain_message(world, capsys):
    (world / "quarantine.csv").unlink()
    assert resolve_ids.main([], session=FakeSession()) == 1
    printed = capsys.readouterr().out
    assert "STOPPED: Missing quarantine.csv" in printed and "Run python run_pipeline.py first." in printed


def test_the_clients_file_is_byte_identical_after_a_run_and_nothing_is_written_under_data_input(world):
    before, listing = input_hash(), sorted(p.name for p in REAL_INPUT.parent.iterdir())
    run(world, tt0468569=answer(NEW_FILM))
    assert input_hash() == before and sorted(p.name for p in REAL_INPUT.parent.iterdir()) == listing
    assert (world / "id_list_suggested.csv").is_file()  # the suggestion went to out/, not data/input/


def test_the_suggested_list_is_a_valid_input_file_for_stage_1(world):
    from pipeline import extract, validate

    run(world, tt0468569=answer(NEW_FILM))
    raw, _ = extract.read_id_file(world / "id_list_suggested.csv")
    ids_to_fetch, quarantine = validate.classify_ids(raw, run_at="t")
    assert ids_to_fetch["tmdb_id"].tolist() == [155, 165, 278, 603] and quarantine.empty


def test_the_key_never_appears_in_the_output_or_any_file(world, fetch_env, capsys):
    url = f"{config.API_BASE}/find/tt0468569?api_key={TEST_KEY}"
    run(world, tt0468569=requests.ConnectionError(f"Max retries exceeded with url: {url}"))
    shown = capsys.readouterr()
    assert TEST_KEY not in shown.out + shown.err
    for path in fetch_env.tmp_path.rglob("*"):
        if path.is_file():
            assert TEST_KEY.encode() not in path.read_bytes(), path
    assert "api_key=***" in resolved(world).iloc[0]["note"]


def test_the_real_outputs_and_the_real_saved_responses_are_not_touched(world):
    real_raw, real_out = Path(config.REPO_ROOT) / "data" / "raw", Path(config.REPO_ROOT) / "out"

    def state():
        return sorted((str(p), p.stat().st_mtime_ns) for p in [*real_raw.rglob("*"), *real_out.glob("*.csv")])

    before = state()
    run(world, tt0468569=answer(DARK_KNIGHT))
    assert state() == before  # nothing under data/raw/ (a find folder included) or out/ changed
    assert resolve.find_file("tt0468569").is_file()  # the saved answer went to the temporary folder
