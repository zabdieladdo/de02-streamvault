"""End-to-end tests of stages 1 and 2 against fixture files and a fake session."""
import json

import pandas as pd
import pytest
import requests

import run_pipeline
from pipeline import config
from tests.conftest import NOT_FOUND_BODY, TEST_KEY, FakeResponse, FakeSession

IDS = ["155", "", "N/A", "155", "9412887", "-1", "tt0468569", "603"]


@pytest.fixture
def env(write_ids, fetch_env, monkeypatch):
    monkeypatch.setattr(config, "INPUT_IDS", write_ids(IDS))
    monkeypatch.setattr(config, "OUT_DIR", fetch_env.tmp_path / "out")
    monkeypatch.setattr(config, "LIMITED_OUT_DIR", fetch_env.tmp_path / "out" / "limited")
    return fetch_env


def fake():
    return FakeSession({"/movie/9412887": FakeResponse(404, NOT_FOUND_BODY)})


def test_main_end_to_end(env, capsys):
    session = fake()
    assert run_pipeline.main([], session=session) == 0
    out = env.tmp_path / "out"

    for name in (
        "ids_to_fetch.csv", "fetched_ids.csv", "quarantine.csv",
        "reconciliation.csv", "checks_report.csv", "run_log.jsonl",
    ):
        assert (out / name).is_file(), name
    lines = (out / "run_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["rows_raw"] == 8
    assert record["ids_to_fetch"] == 3
    assert record["fetch_network_calls"] == 5  # 155 x2, 603 x2, 9412887 details only
    assert record["ids_fetched"] == 2
    assert record["checks_failed"] == 0
    assert record["analysis_incomplete"] is False
    assert record["stopped"] is None

    recon = pd.read_csv(out / "reconciliation.csv")
    assert recon["rows"].iloc[0] == 8
    assert recon["stage"].iloc[-1] == "Fetched with details and credits"
    assert recon["rows"].iloc[-1] == 2
    sent = recon[recon["stage"] == "Sent to the API stage"]["rows"].iloc[0]
    assert sent == 3
    assert "Quarantined: not_found_on_api" in set(recon["stage"])

    q = pd.read_csv(out / "quarantine.csv", dtype=str)
    assert set(q["stage"]) == {"load", "fetch"}
    assert q["line_number"].astype(int).is_monotonic_increasing
    assert len(q) + len(pd.read_csv(out / "fetched_ids.csv")) == 8

    text = capsys.readouterr().out
    assert "Stage 2: fetch details and credits" in text
    assert TEST_KEY not in text


def test_second_run_makes_no_requests(env):
    run_pipeline.main([], session=fake())
    second = FakeSession()
    assert run_pipeline.main([], session=second) == 0
    assert second.calls == []
    log = [json.loads(x) for x in (env.tmp_path / "out" / "run_log.jsonl").read_text().splitlines()]
    assert log[-1]["fetch_network_calls"] == 0 and log[-1]["fetch_cached"] > 0


def test_fully_cached_run_works_without_key(env, monkeypatch):
    run_pipeline.main([], session=fake())
    monkeypatch.delenv("TMDB_API_KEY")
    second = FakeSession()
    assert run_pipeline.main([], session=second) == 0
    assert second.calls == []


def test_limit_run_is_marked(env, capsys):
    session = FakeSession()
    assert run_pipeline.main(["--limit", "1"], session=session) == 0
    assert set(session.calls) == {"/movie/155", "/movie/155/credits"}
    text = capsys.readouterr().out
    assert "LIMITED RUN" in text
    last = text.rstrip().splitlines()[-1]
    assert last.startswith("Outputs written to ") and "limited" in last
    assert last.endswith("(LIMITED RUN; full results in " + last.split("full results in ")[1])
    assert last.endswith("/ unchanged)")
    recon = pd.read_csv(env.tmp_path / "out" / "limited" / "reconciliation.csv")
    assert "Not processed (limited run)" in set(recon["stage"])
    assert recon["rows"].iloc[-1] == 1


def test_refresh_requests_again(env):
    run_pipeline.main([], session=fake())
    second = fake()
    assert run_pipeline.main(["--refresh"], session=second) == 0
    assert len(second.calls) == 5


def test_stop_on_401_returns_1_and_logs(env, capsys):
    session = FakeSession({"/movie/155": FakeResponse(401, b"{}")})
    assert run_pipeline.main([], session=session) == 1
    text = capsys.readouterr().out
    assert "STOPPED" in text and "401" in text
    record = json.loads((env.tmp_path / "out" / "run_log.jsonl").read_text().splitlines()[-1])
    assert "401" in record["stopped"]


def test_key_not_in_any_output(env, capsys):
    err = requests.ConnectionError(f"failed: {config.API_BASE}/movie/603?api_key={TEST_KEY}")
    session = FakeSession({"/movie/603": err})
    run_pipeline.main([], session=session)
    shown = capsys.readouterr()
    assert TEST_KEY not in shown.out + shown.err
    for path in env.tmp_path.rglob("*"):
        if path.is_file():
            assert TEST_KEY.encode() not in path.read_bytes(), path


def test_main_returns_1_on_bad_header(write_ids, fetch_env, monkeypatch, capsys):
    monkeypatch.setattr(config, "INPUT_IDS", write_ids(["155"], header="id"))
    monkeypatch.setattr(config, "OUT_DIR", fetch_env.tmp_path / "out")
    assert run_pipeline.main([]) == 1
    assert "STOPPED" in capsys.readouterr().out


CSV_OUTPUTS = (
    "ids_to_fetch.csv", "fetched_ids.csv", "quarantine.csv", "reconciliation.csv", "checks_report.csv",
)


def test_limited_run_leaves_full_outputs_alone(env):
    out = env.tmp_path / "out"
    run_pipeline.main([], session=fake())
    before = {p.name: p.read_bytes() for p in out.glob("*.csv")}
    assert set(before) == set(CSV_OUTPUTS)
    run_pipeline.main(["--limit", "1"], session=FakeSession())
    after = {p.name: p.read_bytes() for p in out.glob("*.csv")}
    assert after == before


def test_limited_run_writes_its_own_outputs(env):
    run_pipeline.main([], session=fake())
    run_pipeline.main(["--limit", "1"], session=FakeSession())
    limited = env.tmp_path / "out" / "limited"
    assert {p.name for p in limited.glob("*.csv")} == set(CSV_OUTPUTS)
    recon = pd.read_csv(limited / "reconciliation.csv")
    assert recon["rows"].iloc[-1] == 1  # one id fetched


def test_run_log_records_both_runs_and_output_dir(env):
    run_pipeline.main([], session=fake())
    run_pipeline.main(["--limit", "1"], session=FakeSession())
    lines = (env.tmp_path / "out" / "run_log.jsonl").read_text(encoding="utf-8").splitlines()
    full, limited = (json.loads(x) for x in lines)
    assert full["limit"] is None and full["output_dir"] == str(env.tmp_path / "out")
    assert limited["limit"] == 1 and limited["output_dir"].endswith("limited")
