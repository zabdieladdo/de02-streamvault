"""Tests for reading the id file."""
import pytest

from pipeline.errors import PipelineStopError
from pipeline.extract import read_id_file


def test_blank_line_kept(write_ids):
    raw, meta = read_id_file(write_ids(["155", "", "278"]))
    assert len(raw) == 3
    assert raw["raw_value"].tolist() == ["155", "", "278"]
    assert raw["line_number"].tolist() == [2, 3, 4]
    assert meta["raw_line_count"] == 3


def test_values_not_stripped_or_converted(write_ids):
    raw, _ = read_id_file(write_ids([" 603 ", "N/A", "0603"]))
    assert raw["raw_value"].tolist() == [" 603 ", "N/A", "0603"]


def test_crlf_and_lf_agree(write_ids):
    values = ["155", "", "N/A", "603"]
    a, _ = read_id_file(write_ids(values, newline="\r\n", name="a.csv"))
    b, _ = read_id_file(write_ids(values, newline="\n", name="b.csv"))
    assert a.equals(b)


def test_metadata(write_ids):
    path = write_ids(["155"])
    _, meta = read_id_file(path)
    assert meta["input_bytes"] == path.stat().st_size
    assert len(meta["input_sha256"]) == 64
    assert meta["bom_found"] is False


def test_bom_stripped_and_recorded(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_bytes(b"\xef\xbb\xbftmdb_id\r\n155\r\n")
    raw, meta = read_id_file(path)
    assert meta["bom_found"] is True
    assert raw["raw_value"].tolist() == ["155"]


def test_wrong_header_stops(write_ids):
    with pytest.raises(PipelineStopError):
        read_id_file(write_ids(["155"], header="id"))


def test_header_only_stops(write_ids):
    with pytest.raises(PipelineStopError):
        read_id_file(write_ids([]))


def test_missing_file_stops(tmp_path):
    with pytest.raises(PipelineStopError):
        read_id_file(tmp_path / "nope.csv")


def test_two_columns_stops(tmp_path):
    path = tmp_path / "two.csv"
    path.write_bytes(b"tmdb_id,extra\r\n155,x\r\n")
    with pytest.raises(PipelineStopError):
        read_id_file(path)
