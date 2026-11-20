"""The flatten stage reads the snapshots, checks them against the fetch log first, and rebuilds and reports if stale."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

import run_pipeline
from pipeline import config, fetch, measurement, transform
from pipeline.errors import PipelineStopError

REPO = Path(config.REPO_ROOT)
FILMS = 30


def tree_hash(root: Path) -> dict:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file() and not p.name.startswith("snapshot_")
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A synthetic folder of saved responses (no network, no real data) with every path pointed at it."""
    ids_file, raw = measurement.make_synthetic(FILMS, tmp_path / "synthetic")
    out = tmp_path / "out"
    for name, value in {
        "INPUT_IDS": ids_file, "RAW_DIR": raw, "RAW_DETAILS_DIR": raw / "details", "RAW_CREDITS_DIR": raw / "credits",
        "FETCH_LOG": raw / "fetch_log.csv", "OUT_DIR": out, "LIMITED_OUT_DIR": out / "limited",
        "DOTENV_PATH": tmp_path / "no.env",
    }.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setenv("TMDB_API_KEY", "")

    def no_session():
        raise AssertionError("a request was about to be made")

    monkeypatch.setattr(fetch, "build_session", no_session)
    return {"raw": raw, "out": out, "ids": ids_file, "tmp": tmp_path}


def go(world, expect=0):
    assert run_pipeline.main([]) == expect
    return world["out"]


def last_record(world):
    text = (world["out"] / "run_log.jsonl").read_text(encoding="utf-8")
    return json.loads(text.strip().split(chr(10))[-1])


def status(world):
    return (world["out"] / "run_status.txt").read_text(encoding="utf-8")


def outputs(out):
    """Every output CSV as text; the time a run happened is left out of the quarantine file."""
    files = {}
    for path in sorted(out.glob("*.csv")):
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        files[path.name] = frame.drop(columns=["run_at"], errors="ignore").to_csv(index=False)
    return files


def snapshot_lines(raw, endpoint):
    text = (raw / fetch.SNAPSHOT_NAMES[endpoint]).read_text(encoding="utf-8")
    return [line for line in text.split(chr(10)) if line]


def test_the_snapshots_match_the_per_film_files_after_a_run(world):
    go(world)
    for endpoint in fetch.SNAPSHOT_NAMES:
        records = [json.loads(line) for line in snapshot_lines(world["raw"], endpoint)]
        assert len(records) == FILMS and [r["tmdb_id"] for r in records] == sorted(r["tmdb_id"] for r in records)
        for record in records:
            on_disk = json.loads(fetch.cache_file(endpoint, record["tmdb_id"]).read_bytes())
            assert record["response"] == on_disk


def test_a_run_with_fresh_snapshots_does_not_rebuild_them_and_says_so(world):
    go(world)
    first = last_record(world)
    go(world)
    record = last_record(world)
    assert first["snapshot_rebuilt"] is False and record["snapshot_rebuilt"] is False
    assert "snapshot_rebuild_reason" not in record and record["snapshot_build_s"] < 0.5
    assert status(world).startswith("complete 20") and "snapshot" not in status(world)


def test_flatten_does_not_open_a_per_film_file_when_the_snapshot_holds_the_film(world):
    go(world)
    use = transform.prepare_snapshots()
    assert use.rebuilt is False
    for folder in (world["raw"] / "details", world["raw"] / "credits"):
        for path in folder.glob("*.json"):
            path.unlink()  # if flatten still needed them, every film would be quarantined
    ids = pd.read_csv(world["ids"]).assign(first_line_number=lambda d: range(2, len(d) + 2))
    details, credits_, quarantine = transform.read_saved_responses(ids, snapshots=use)
    assert len(details) == len(credits_) == FILMS and quarantine.empty


def test_outputs_are_identical_whether_the_run_reads_the_snapshot_or_the_per_film_files(world, monkeypatch):
    with_snapshot = outputs(go(world))
    assert len(with_snapshot) >= 20

    monkeypatch.setattr(transform, "prepare_snapshots", lambda now=None: transform.SnapshotUse(held={}))
    from_files = outputs(go(world))
    assert from_files == with_snapshot


def test_a_snapshot_with_a_film_missing_is_rebuilt_flagged_and_gives_the_same_outputs(world):
    first = outputs(go(world))
    path = world["raw"] / "snapshot_movie.jsonl"
    whole = path.read_bytes()
    kept = snapshot_lines(world["raw"], "details")[:-1]
    path.write_bytes((chr(10).join(kept) + chr(10)).encode("utf-8"))

    again = outputs(go(world))
    record = last_record(world)
    assert record["snapshot_rebuilt"] is True and "1 missing" in record["snapshot_rebuild_reason"]
    assert record["snapshot_build_s"] > 0
    assert "(snapshot rebuilt: details snapshot differs from the fetch log (1 missing" in status(world)
    assert path.read_bytes() == whole and again == first


def test_a_snapshot_with_a_changed_fetch_time_is_rebuilt(world):
    go(world)
    path = world["raw"] / "snapshot_credits.jsonl"
    lines = snapshot_lines(world["raw"], "credits")
    changed = json.loads(lines[0])
    changed["fetched_at"] = "2020-01-01T00:00:00+00:00"
    path.write_bytes((chr(10).join([json.dumps(changed), *lines[1:]]) + chr(10)).encode("utf-8"))
    go(world)
    assert "1 changed" in last_record(world)["snapshot_rebuild_reason"]


def test_a_snapshot_with_a_film_the_fetch_log_does_not_know_is_rebuilt(world):
    go(world)
    path = world["raw"] / "snapshot_movie.jsonl"
    stranger = json.dumps({"tmdb_id": 99999, "fetched_at": "2026-01-01T00:00:00+00:00", "response": {"id": 99999}})
    path.write_bytes(path.read_bytes() + stranger.encode("utf-8") + chr(10).encode("utf-8"))
    go(world)
    assert "1 extra" in last_record(world)["snapshot_rebuild_reason"]
    assert 99999 not in fetch.read_snapshot("details")


def test_an_unreadable_snapshot_is_rebuilt(world):
    go(world)
    (world["raw"] / "snapshot_movie.jsonl").write_bytes(b"this is not json" + chr(10).encode("utf-8"))
    go(world)
    assert "missing or unreadable" in last_record(world)["snapshot_rebuild_reason"]
    assert len(fetch.read_snapshot("details")) == FILMS


def test_a_deleted_snapshot_is_built_again_by_the_fetch_stage_without_a_rebuild_flag(world):
    go(world)
    (world["raw"] / "snapshot_movie.jsonl").unlink()
    (world["raw"] / "snapshot_credits.jsonl").unlink()
    go(world)
    record = last_record(world)
    assert record["snapshot_rebuilt"] is False and record["snapshot_build_s"] > 0
    assert len(fetch.read_snapshot("credits")) == FILMS


def test_a_film_past_the_180_days_is_dropped_from_the_snapshot_by_the_next_rebuild(world):
    go(world)
    log = pd.read_csv(config.FETCH_LOG, dtype=str, keep_default_na=False)
    old = (datetime.now(UTC) - timedelta(days=config.CACHE_MAX_AGE_DAYS + 5)).isoformat(timespec="seconds")
    log.loc[log["tmdb_id"] == "1003", "fetched_at"] = old
    log.to_csv(config.FETCH_LOG, index=False)

    use = transform.prepare_snapshots()
    assert use.rebuilt and "1 extra" in use.reason  # the snapshot still held a film the log no longer allows
    assert 1003 not in use.held["details"] and 1003 not in fetch.read_snapshot("credits")
    assert len(use.held["details"]) == FILMS - 1


def test_a_film_that_cannot_be_read_from_the_snapshot_is_read_from_its_own_file_and_quarantined_as_before(world):
    go(world)
    fetch.cache_file("credits", 1005).write_bytes(b"{not json")
    for name in fetch.SNAPSHOT_NAMES.values():
        (world["raw"] / name).unlink()
    out = go(world)
    quarantine = pd.read_csv(out / "quarantine.csv", dtype=str, keep_default_na=False)
    row = quarantine[quarantine["raw_value"] == "1005"].iloc[0]
    assert row["reason_code"] == "cache_unreadable" and "credits file is not valid JSON" in row["reason_detail"]
    assert len(pd.read_csv(out / "films.csv")) == FILMS - 1


def test_a_rebuild_that_cannot_be_written_stops_the_run_at_check_c_34(world, monkeypatch):
    go(world)
    path = world["raw"] / "snapshot_movie.jsonl"
    path.write_bytes(path.read_bytes() + b"x")  # unreadable, so flatten must rebuild it

    real_replace = fetch.os.replace

    def refuse(source, target):
        if Path(target).name.startswith("snapshot_"):
            raise OSError("disk full")
        real_replace(source, target)

    monkeypatch.setattr(fetch.os, "replace", refuse)
    go(world, expect=1)
    assert status(world).startswith("stopped at C-34, stage 3")
    assert "Could not rebuild the response snapshots" in last_record(world)["stopped"]


def test_prepare_snapshots_raises_c_34_itself_when_the_rebuild_fails(world, monkeypatch):
    go(world)
    (world["raw"] / "snapshot_movie.jsonl").write_bytes(b"junk")
    monkeypatch.setattr(fetch, "build_snapshot", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    with pytest.raises(PipelineStopError) as stopped:
        transform.prepare_snapshots()
    assert stopped.value.check_id == "C-34"


def test_a_run_changes_no_per_film_file_and_never_touches_the_input_list(world):
    real_input = (REPO / "data" / "input" / "id_list.csv").read_bytes()
    before_files = tree_hash(world["raw"] / "details"), tree_hash(world["raw"] / "credits")
    ids = world["ids"].read_bytes()
    go(world)
    log = config.FETCH_LOG.read_bytes()  # the fetch stage writes the log sorted, so compare from the second run on
    (world["raw"] / "snapshot_movie.jsonl").unlink()
    go(world)
    assert (tree_hash(world["raw"] / "details"), tree_hash(world["raw"] / "credits")) == before_files
    assert config.FETCH_LOG.read_bytes() == log and world["ids"].read_bytes() == ids
    assert (REPO / "data" / "input" / "id_list.csv").read_bytes() == real_input


def test_the_rebuild_flag_is_in_the_run_status_only_when_a_rebuild_happened(world):
    go(world)
    assert "rebuilt" not in status(world)
    path = world["raw"] / "snapshot_credits.jsonl"
    path.write_bytes(b"")
    go(world)
    assert "(snapshot rebuilt: credits snapshot differs from the fetch log (30 missing" in status(world)
    go(world)
    assert "rebuilt" not in status(world)


def test_the_printed_stage_summary_names_a_rebuild(world, capsys):
    go(world)
    (world["raw"] / "snapshot_movie.jsonl").write_bytes(b"")
    capsys.readouterr()
    go(world)
    assert "SNAPSHOT REBUILT: details snapshot differs from the fetch log (30 missing" in capsys.readouterr().out
