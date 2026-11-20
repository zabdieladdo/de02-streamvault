"""End-to-end test of stage 1 against a fixture file."""
import json

import pandas as pd

import run_pipeline
from pipeline import config


def test_main_end_to_end(write_ids, tmp_path, monkeypatch, capsys):
    path = write_ids(["155", "", "N/A", "155", "9412887", "-1", "tt0468569"])
    out = tmp_path / "out"
    monkeypatch.setattr(config, "INPUT_IDS", path)
    monkeypatch.setattr(config, "OUT_DIR", out)

    assert run_pipeline.main() == 0

    for name in ("ids_to_fetch.csv", "quarantine.csv", "reconciliation.csv", "checks_report.csv"):
        assert (out / name).is_file()
    log_lines = (out / "run_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1
    record = json.loads(log_lines[0])
    assert record["rows_raw"] == 7
    assert record["ids_to_fetch"] == 2
    assert record["checks_failed"] == 0

    recon = pd.read_csv(out / "reconciliation.csv")
    assert recon["rows"].iloc[0] == 7
    assert recon["rows"].iloc[-1] == 2
    assert "Stage 1: load ids" in capsys.readouterr().out


def test_main_returns_1_on_bad_header(write_ids, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "INPUT_IDS", write_ids(["155"], header="id"))
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    assert run_pipeline.main() == 1
    assert "STOPPED" in capsys.readouterr().out
