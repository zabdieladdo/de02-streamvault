"""Tests for the load-stage checks."""
import pandas as pd
import pytest

from pipeline.checks import check_load_stage, raise_if_conservation_failed
from pipeline.errors import PipelineStopError
from pipeline.validate import classify_ids

VALUES = ["155", "", "N/A", "155", "9412887", "-1"]


@pytest.fixture
def stage():
    raw = pd.DataFrame({"line_number": range(2, len(VALUES) + 2), "raw_value": VALUES})
    meta = {"header": "tmdb_id", "raw_line_count": len(VALUES)}
    ids, q = classify_ids(raw)
    return meta, raw, ids, q


def test_all_pass(stage):
    report = check_load_stage(*stage)
    assert list(report["check_id"]) == ["C-01", "C-02", "C-03", "C-04", "C-04b"]
    assert report["passed"].all()
    assert "9412887" in report.loc[report["check_id"] == "C-04b", "detail"].iloc[0]


def test_dropped_row_fails_c02_and_c03_and_stops(stage):
    meta, raw, ids, q = stage
    report = check_load_stage(meta, raw, ids, q.iloc[1:])  # lose a quarantine row
    failed = set(report.loc[~report["passed"], "check_id"])
    assert {"C-02", "C-03"} <= failed
    with pytest.raises(PipelineStopError):
        raise_if_conservation_failed(report)


def test_duplicate_id_fails_c04(stage):
    meta, raw, ids, q = stage
    report = check_load_stage(meta, raw, pd.concat([ids, ids.iloc[[0]]]), q)
    assert not report.loc[report["check_id"] == "C-04", "passed"].iloc[0]


def test_row_count_mismatch_fails_c01(stage):
    meta, raw, ids, q = stage
    report = check_load_stage({**meta, "raw_line_count": 99}, raw, ids, q)
    assert not report.loc[report["check_id"] == "C-01", "passed"].iloc[0]
