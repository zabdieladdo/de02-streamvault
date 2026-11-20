"""Tests for stage 3: flatten, talent, proven joins, checks, outputs. Invented JSON, no network."""
import json

import pandas as pd
import pytest

from pipeline import checks, config, load, transform
from pipeline.errors import PipelineStopError

pytestmark = pytest.mark.usefixtures("fetch_env")


def film(tmdb_id, **extra):
    base = {"id": tmdb_id, "title": f"Film {tmdb_id}", "imdb_id": f"tt{tmdb_id:07d}",
            "release_date": "2008-07-16", "status": "Released", "budget": 100, "revenue": 300,
            "vote_count": 10, "vote_average": 7.5, "popularity": 1.5, "original_language": "en",
            "adult": False, "video": False, "genres": [{"id": 1, "name": "Action"}],
            "belongs_to_collection": None, "production_companies": [{"id": 1, "name": "Co"}]}
    base.update(extra)
    return base


def credits(tmdb_id, cast=(), crew=()):
    return {"id": tmdb_id, "cast": list(cast), "crew": list(crew)}


def actor(pid, order, name=None):
    return {"id": pid, "name": name or f"Actor {pid}", "order": order, "character": "x"}


def crew_member(pid, job, name=None):
    return {"id": pid, "name": name or f"Crew {pid}", "job": job, "department": "Directing"}


def save(tmdb_id, details=None, credits_=None):
    for endpoint, body in (("details", details), ("credits", credits_)):
        if body is None:
            continue
        path = transform.fetch.cache_file(endpoint, tmdb_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")


def ids_df(*ids):
    return pd.DataFrame({"tmdb_id": pd.Series(ids, dtype="int64"),
                         "first_line_number": range(2, len(ids) + 2)})


def flatten(details):
    return transform.flatten_details(details).set_index("tmdb_id")


# --- details -> films ---------------------------------------------------------------

def test_four_genres_one_row():
    g = [{"id": i, "name": n} for i, n in enumerate(["Action", "Drama", "Crime", "Thriller"])]
    f = flatten([film(1, genres=g)])
    assert len(f) == 1
    row = f.loc[1]
    assert row["n_genres"] == 4 and row["primary_genre"] == "Action"
    assert row["genres_all"] == "Action|Drama|Crime|Thriller"


@pytest.mark.parametrize("extra", [{"genres": []}, {"genres": None}])
def test_no_genres(extra):
    row = flatten([film(1, **extra)]).loc[1]
    assert row["n_genres"] == 0 and pd.isna(row["primary_genre"]) and pd.isna(row["genres_all"])


def test_genres_key_missing():
    d = film(1)
    del d["genres"]
    row = flatten([d]).loc[1]
    assert row["n_genres"] == 0 and pd.isna(row["primary_genre"])


def test_collection_and_standalone():
    f = flatten([film(1, belongs_to_collection={"id": 9, "name": "Saga", "poster_path": None}), film(2)])
    assert f.loc[1, "collection_id"] == 9 and f.loc[1, "collection_name"] == "Saga"
    assert bool(f.loc[1, "is_franchise"]) is True
    assert pd.isna(f.loc[2, "collection_id"]) and bool(f.loc[2, "is_franchise"]) is False


def test_no_collection_anywhere_keeps_columns():
    f = transform.flatten_details([film(1), film(2)])
    assert {"collection_id", "collection_name"} <= set(f.columns)
    assert f["collection_id"].isna().all() and f["collection_name"].isna().all()
    assert not f["is_franchise"].any()


def test_missing_key_is_null_not_error():
    d = film(1)
    del d["revenue"]
    f = flatten([d])
    assert pd.isna(f.loc[1, "revenue"])


def test_zeros_kept():
    f = flatten([film(1, budget=0, revenue=0)])
    assert f.loc[1, "budget"] == 0 and f.loc[1, "revenue"] == 0


def test_dates():
    f = flatten([film(1, release_date=""), film(2, release_date="2008-13-45"), film(3)])
    assert f.loc[1, "release_date_raw"] == "" and pd.isna(f.loc[1, "release_date"])
    assert not f.loc[1, "release_date_unparseable"]
    assert f.loc[2, "release_date_raw"] == "2008-13-45" and f.loc[2, "release_date_unparseable"]
    assert pd.isna(f.loc[2, "release_date"])
    assert f.loc[3, "release_year"] == 2008 and not f.loc[3, "release_date_unparseable"]


def test_dtypes():
    f = transform.flatten_details([film(1)])
    assert str(f["budget"].dtype) == "Int64" and str(f["tmdb_id"].dtype) == "int64"
    assert pd.api.types.is_datetime64_any_dtype(f["release_date"])


# --- credits -> talent ---------------------------------------------------------------

def test_cast_order_gaps_use_ranking():
    c = credits(1, cast=[actor(10, 7), actor(11, 0), actor(12, 5), actor(13, 2)])
    counts, talent = transform.flatten_credits([c])
    leads = talent[talent["role"] == "lead_actor"].sort_values("billing_rank")
    assert leads["cast_order"].tolist() == [0, 2, 5]
    assert leads["billing_rank"].tolist() == [1, 2, 3]
    assert counts.loc[0, "n_cast"] == 4 and counts.loc[0, "n_lead_actors"] == 3


def test_order_ties_broken_by_list_position():
    c = credits(1, cast=[actor(10, 1), actor(11, 1), actor(12, 1), actor(13, 1)])
    _, talent = transform.flatten_credits([c])
    assert talent.sort_values("billing_rank")["person_id"].tolist() == [10, 11, 12]


def test_fewer_than_three_cast():
    counts, talent = transform.flatten_credits([credits(1, cast=[actor(10, 0), actor(11, 1)])])
    assert counts.loc[0, "n_lead_actors"] == 2 and len(talent) == 2


def test_empty_cast_film_kept_in_counts():
    counts, talent = transform.flatten_credits([credits(1), credits(2, cast=[actor(10, 0)])])
    assert counts.set_index("tmdb_id").loc[1, "n_cast"] == 0
    assert set(counts["tmdb_id"]) == {1, 2}
    assert 1 not in set(talent["tmdb_id"])


def test_empty_everything():
    counts, talent = transform.flatten_credits([credits(1)])
    assert talent.empty and list(talent.columns) == transform.TALENT_COLUMNS
    assert counts.loc[0, "n_directors"] == 0


def test_two_directors_and_assistant_ignored():
    crew = [crew_member(20, "Director"), crew_member(21, "Director"),
            crew_member(22, "Assistant Director"), crew_member(23, "Producer")]
    counts, talent = transform.flatten_credits([credits(1, crew=crew)])
    assert sorted(talent.loc[talent["role"] == "director", "person_id"]) == [20, 21]
    assert counts.loc[0, "n_directors"] == 2 and counts.loc[0, "n_crew"] == 4
    assert 22 not in set(talent["person_id"])


def test_director_who_also_acts_has_two_rows():
    c = credits(1, cast=[actor(20, 0)], crew=[crew_member(20, "Director")])
    _, talent = transform.flatten_credits([c])
    assert sorted(talent["role"]) == ["director", "lead_actor"]
    assert not talent.duplicated(["tmdb_id", "person_id", "role"]).any()


def test_same_person_twice_in_cast_counted_once():
    c = credits(1, cast=[actor(10, 0), actor(10, 3), actor(11, 1)])
    _, talent = transform.flatten_credits([c])
    assert sorted(talent["person_id"]) == [10, 11]


# --- reading saved responses ----------------------------------------------------------

def test_unreadable_response_quarantined_and_conserved():
    save(1, film(1), credits(1))
    save(2, film(2))  # credits file missing
    save(3, film(999), credits(3))  # details for another id
    fetched = ids_df(1, 2, 3)
    run = transform.flatten_stage(fetched)
    assert run.films["tmdb_id"].tolist() == [1]
    assert sorted(run.quarantine["raw_value"]) == ["2", "3"]
    assert (run.quarantine["reason_code"] == "cache_unreadable").all()
    assert (run.quarantine["stage"] == "flatten").all()
    assert len(fetched) == len(run.films) + len(run.quarantine)


def test_invalid_json_quarantined():
    save(1, film(1), credits(1))
    transform.fetch.cache_file("details", 1).write_text("{not json", encoding="utf-8")
    run = transform.flatten_stage(ids_df(1))
    assert run.films.empty and len(run.quarantine) == 1


# --- joins -------------------------------------------------------------------------------

def good_run():
    save(1, film(1, belongs_to_collection={"id": 9, "name": "Saga"}),
         credits(1, cast=[actor(10, 0)], crew=[crew_member(20, "Director")]))
    save(2, film(2), credits(2))
    return transform.flatten_stage(ids_df(1, 2))


def test_join_report_for_good_fixture():
    run = good_run()
    j = run.join_report
    assert len(j) == 3
    assert not j["rows_changed"].any() and (j["left_only"] == 0).all()
    assert j["left_key_unique"].iloc[:2].all() and j["right_key_unique"].all()
    assert not j["left_key_unique"].iloc[2]  # talent has many rows per film, by design
    assert run.films["first_line_number"].tolist() == [2, 3]


def test_fan_out_is_caught():
    films = transform.flatten_details([film(1)])
    counts = pd.DataFrame({"tmdb_id": [1, 1], "n_cast": 0, "n_crew": 0, "n_directors": 0, "n_lead_actors": 0})
    _, talent = transform.flatten_credits([credits(1)])
    with pytest.raises(PipelineStopError, match="Join 2"):
        transform.build_analysis_tables(ids_df(1), films, counts, talent)


def test_unmatched_key_reported_when_validation_allows():
    left = pd.DataFrame({"tmdb_id": [1, 2]})
    right = pd.DataFrame({"tmdb_id": [1]})
    merged, row = transform.prove_join(left, right, "tmdb_id", "left", "one_to_one", "t")
    assert row["left_only"] == 1 and row["unmatched_keys"] == "2" and len(merged) == 2


# --- checks ------------------------------------------------------------------------------

def load_q(*imdb_ids):
    return pd.DataFrame({"raw_value": list(imdb_ids), "reason_code": "imdb_id_not_tmdb",
                         "line_number": 5, "reason_detail": "x", "stage": "load", "run_at": "t"})


def test_checks_all_pass_and_imdb_cross_reference():
    run = good_run()
    report = checks.check_flatten_stage(run, load_q("tt0000001"))
    assert list(report["check_id"]) == ["C-10", "C-11", "C-12", "C-13", "C-14", "C-14t", "C-03g", "I-01"]
    assert report["passed"].all()
    detail = report.loc[report["check_id"] == "I-01", "detail"].iloc[0]
    assert "tt0000001 matches film 1 (Film 1)" in detail


def test_imdb_cross_reference_no_match():
    report = checks.check_flatten_stage(good_run(), load_q("tt9999999"))
    assert "matches no fetched film" in report.loc[report["check_id"] == "I-01", "detail"].iloc[0]


def test_c13_catches_two_names_for_one_collection():
    save(1, film(1, belongs_to_collection={"id": 9, "name": "A"}), credits(1))
    save(2, film(2, belongs_to_collection={"id": 9, "name": "B"}), credits(2))
    run = transform.flatten_stage(ids_df(1, 2))
    report = checks.check_flatten_stage(run, load_q())
    assert not report.loc[report["check_id"] == "C-13", "passed"].iloc[0]


def test_c14_fails_if_a_join_changed_rows():
    run = good_run()
    run.join_report.loc[0, "rows_changed"] = True
    report = checks.check_flatten_stage(run, load_q())
    assert not report.loc[report["check_id"] == "C-14", "passed"].iloc[0]


def test_c14t_fails_on_duplicate_talent_key():
    run = good_run()
    run.talent = pd.concat([run.talent, run.talent.iloc[[0]]], ignore_index=True)
    report = checks.check_flatten_stage(run, load_q())
    assert not report.loc[report["check_id"] == "C-14t", "passed"].iloc[0]


# --- outputs ---------------------------------------------------------------------------

def test_csv_round_trip_keeps_values_and_dtypes(tmp_path):
    run = good_run()
    load.write_flatten_outputs(run.films, run.talent, run.join_report,
                               pd.DataFrame(columns=transform.QUARANTINE_COLUMNS),
                               pd.DataFrame({"stage": [], "rows": [], "delta": [], "reason": []}),
                               pd.DataFrame(columns=["check_id"]), out_dir=tmp_path)
    pd.testing.assert_frame_equal(load.read_films(tmp_path / "films.csv"), run.films)
    pd.testing.assert_frame_equal(load.read_talent(tmp_path / "talent.csv"), run.talent)
    iso = (tmp_path / "films.csv").read_text(encoding="utf-8")
    assert "2008-07-16" in iso


def test_profile_counts():
    save(1, film(1, budget=0, release_date=""), credits(1))
    save(2, film(2, revenue=None), credits(2))
    save(3, film(3), credits(3))
    run = transform.flatten_stage(ids_df(1, 2, 3))
    profile = load.profile_films(run.films).set_index("column")
    assert len(profile) == len(run.films.columns)
    assert profile.loc["budget", "n_zero"] == 1
    assert profile.loc["revenue", "n_null"] == 1
    assert profile.loc["release_date_raw", "n_empty_string"] == 1
    assert profile.loc["release_date", "n_null"] == 1
    assert profile.loc["status", "top_3"] == "Released (3)"
    assert profile.loc["tmdb_id", "min"] == 1 and profile.loc["tmdb_id", "max"] == 3


def test_reconciliation_continues_through_flatten():
    save(1, film(1), credits(1))
    run = transform.flatten_stage(ids_df(1, 2))  # id 2 has no saved files
    ids = ids_df(1, 2)
    q = run.quarantine
    recon = load.build_reconciliation(2, ids, q, ids, ids_processed=2, films_out=run.films)
    assert recon["stage"].iloc[-1] == "In the analysis table (one row per film)"
    assert recon["rows"].iloc[-1] == 1
    assert "Quarantined: cache_unreadable" in set(recon["stage"])
