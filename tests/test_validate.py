"""Tests for classify_ids."""
import pandas as pd
import pytest

from pipeline.validate import classify_ids


def raw_of(values):
    return pd.DataFrame(
        {"line_number": range(2, len(values) + 2), "raw_value": list(values)}
    )


def run(values):
    raw = raw_of(values)
    ids, quarantine = classify_ids(raw, run_at="2026-01-01T00:00:00+00:00")
    assert len(raw) == len(ids) + len(quarantine)  # conservation
    return ids, quarantine


def codes(quarantine):
    return dict(zip(quarantine["raw_value"], quarantine["reason_code"]))


def test_blank_quarantined():
    ids, q = run(["155", "", "278"])
    assert q["reason_code"].tolist() == ["blank"]
    assert q["line_number"].tolist() == [3]
    assert ids["tmdb_id"].tolist() == [155, 278]


@pytest.mark.parametrize("value", ["N/A", "n/a", "NULL", "none"])
def test_placeholders(value):
    _, q = run(["155", value])
    assert q["reason_code"].tolist() == ["placeholder_text"]


@pytest.mark.parametrize("value", ["tt0468569", "TT123"])
def test_imdb_id(value):
    _, q = run([value])
    assert q["reason_code"].tolist() == ["imdb_id_not_tmdb"]


@pytest.mark.parametrize("value", ["-1", "0", "000"])
def test_not_positive(value):
    _, q = run([value])
    assert q["reason_code"].tolist() == ["not_positive"]


def test_decimal():
    _, q = run(["603.0"])
    assert q["reason_code"].tolist() == ["decimal_form"]


@pytest.mark.parametrize("value", ["abc", "12a"])
def test_invalid_text(value):
    _, q = run([value])
    assert q["reason_code"].tolist() == ["invalid_text"]


def test_overlong_digits_do_not_crash():
    ids, q = run(["9" * 25])
    assert ids.empty
    assert q["reason_code"].tolist() == ["invalid_text"]


def test_padding_valid_and_flagged():
    ids, q = run([" 603 "])
    assert q.empty
    assert ids["tmdb_id"].tolist() == [603]
    assert ids["was_padded"].tolist() == [True]


def test_leading_zero_normalised_then_repeat():
    ids, q = run(["0603"])
    assert ids["tmdb_id"].tolist() == [603]
    assert ids["leading_zero_normalised"].tolist() == [True]

    ids, q = run(["603", "0603"])
    assert ids["tmdb_id"].tolist() == [603]
    assert q["reason_code"].tolist() == ["repeat"]
    assert q["reason_detail"].tolist() == ["Repeat of line 2"]


def test_repeats():
    ids, q = run(["550", "1", "2", "550", "3", "4", "5", "6", "550"])
    first = ids[ids["tmdb_id"] == 550].iloc[0]
    assert first["first_line_number"] == 2
    assert first["n_occurrences"] == 3
    assert q["line_number"].tolist() == [5, 10]
    assert q["reason_code"].tolist() == ["repeat", "repeat"]
    assert q["reason_detail"].tolist() == ["Repeat of line 2"] * 2


def test_large_id_flagged_and_kept():
    ids, q = run(["155", "9412887"])
    assert q.empty
    large = ids.set_index("tmdb_id")["flag_large_id"]
    assert large[9412887] and not large[155]


def test_quarantine_columns_and_stage():
    _, q = run(["", "155"])
    assert list(q.columns) == [
        "line_number", "raw_value", "reason_code", "reason_detail", "stage", "run_at",
    ]
    assert (q["stage"] == "load").all()
    assert q["run_at"].nunique() == 1


def test_ids_to_fetch_columns_dtype_order():
    ids, _ = run(["278", "155", "278"])
    assert list(ids.columns) == [
        "tmdb_id", "first_line_number", "n_occurrences",
        "was_padded", "leading_zero_normalised", "flag_large_id",
    ]
    assert str(ids["tmdb_id"].dtype) == "int64"
    assert ids["tmdb_id"].tolist() == [278, 155]  # file order


def test_all_quarantined_gives_empty_ids():
    ids, q = run(["", "N/A"])
    assert ids.empty and len(q) == 2


def test_mixed_conservation():
    run(["155", "", "N/A", "-1", "tt1", "155", "603.0", "x", " 7 ", "0007"])
