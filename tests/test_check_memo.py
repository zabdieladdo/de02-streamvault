"""The memo checker: figures from out/, banned wording, length, headings. Small made-up outputs, no real data."""
from pathlib import Path

import pandas as pd
import pytest

import check_memo
from pipeline import config

GOOD = """# Memo to Kwame

**From:** Noell
**Date:** 20 November 2026
**Subject:** What the evidence supports

## What I found

Of the 127 titles on your list, 112 could be analysed, as of 20 November 2026. The typical franchise film
returned 5.6 times its budget; later films earn about 70% of the first. From 2000 onward the gap is 5.1 times.

## What I built

| What you asked for | Status | Evidence |
|---|---|---|
| A re-run each quarter | Done | A full re-run takes under 4 seconds at 500 titles |

## What I recommend

Spend part of the $14M on films from 1994 to 2005.

## What I could not stand behind

- Five ids matched no film.
"""


@pytest.fixture
def out(tmp_path) -> Path:
    """Outputs with just the numbers GOOD quotes."""
    folder = tmp_path / "out"
    (folder / "measurement").mkdir(parents=True)
    pd.DataFrame({"group": ["franchise"], "median_roi": [5.623799], "n_films": [96], "ratio": [0.7012]}).to_csv(
        folder / "kpis.csv", index=False)
    pd.DataFrame({"stage": ["Raw rows in file"], "rows": [112]}).to_csv(folder / "reconciliation.csv", index=False)
    pd.DataFrame({"reason": ["Median 5.1× across 6 films"]}).to_csv(folder / "shortlist.csv", index=False)
    pd.DataFrame({"size": [500, 500], "state": ["cold", "warm"], "metric": ["wall_s", "wall_s"],
                  "median_s": [3.61, 3.34]}).to_csv(folder / "measurement" / "timing_summary.csv", index=False)
    pd.DataFrame({"release_year": [1994, 2005, 1966]}).to_csv(folder / "films.csv", index=False)
    (folder / "run_status.txt").write_text("complete 2026-11-20T10:02:01+00:00\n", encoding="utf-8")
    for name in check_memo.SOURCE_FILES:  # the rest exist, empty
        path = folder / name
        if not path.exists():
            pd.DataFrame({"x": []}).to_csv(path, index=False)
    return folder


def memo_file(tmp_path, text) -> Path:
    path = tmp_path / "memo.md"
    path.write_text(text, encoding="utf-8")
    return path


def line_of(text, needle):
    return next(n for n, line in enumerate(text.splitlines(), start=1) if needle in line)


def problems(tmp_path, out, text):
    return check_memo.check(memo_file(tmp_path, text), out)


def test_a_memo_whose_figures_are_all_in_the_outputs_passes(tmp_path, out):
    assert problems(tmp_path, out, GOOD) == []


# --- figures ----------------------------------------------------------------------------------------------

def test_a_number_the_outputs_do_not_support_fails_and_is_named_with_its_line(tmp_path, out):
    bad = GOOD.replace("5.6 times", "6.4 times")
    found = problems(tmp_path, out, bad)
    assert found == [f"figures: line {line_of(bad, '6.4')}: 6.4 is not in the outputs"]


def test_a_figure_is_compared_at_the_precision_it_is_written(tmp_path, out):
    assert problems(tmp_path, out, GOOD.replace("5.6 times", "5.62 times")) == []  # 5.623799 to 2 places
    assert problems(tmp_path, out, GOOD.replace("5.6 times", "5.7 times")) != []  # one place: 5.6, not 5.7
    assert problems(tmp_path, out, GOOD.replace("5.6 times", "6 times")) == []  # whole number: 6


def test_a_percentage_matches_a_share_given_as_a_fraction(tmp_path, out):
    assert problems(tmp_path, out, GOOD) == []  # 70% from 0.7012
    assert [p for p in problems(tmp_path, out, GOOD.replace("70%", "75%")) if "75%" in p]


def test_a_count_from_the_outputs_is_accepted_and_a_made_up_count_is_not(tmp_path, out):
    bad = GOOD.replace("112 could", "113 could")
    assert problems(tmp_path, out, bad) == [f"figures: line {line_of(bad, '113')}: 113 is not in the outputs"]


def test_a_number_inside_the_text_of_an_output_counts_as_in_the_outputs(tmp_path, out):
    assert problems(tmp_path, out, GOOD.replace("5.6 times", "5.1 times")) == []  # in the shortlist's reason text


def test_the_fixed_numbers_and_the_years_of_the_films_are_accepted(tmp_path, out):
    assert problems(tmp_path, out, GOOD) == []  # 127, 2000, $14M, 1994 and 2005
    bad = GOOD.replace("1994 to 2005", "1995 to 2005")
    assert problems(tmp_path, out, bad) == [f"figures: line {line_of(bad, '1995')}: 1995 is not in the outputs"]


def test_a_time_bound_is_the_next_whole_second_above_the_500_title_run_times(tmp_path, out):
    assert problems(tmp_path, out, GOOD) == []  # 3.61 and 3.34: the next whole second above the slower is 4
    assert problems(tmp_path, out, GOOD.replace("under 4 seconds", "under 2 seconds")) != []
    assert problems(tmp_path, out, GOOD.replace("under 4 seconds", "under 10 seconds")) != []


def test_a_date_must_be_the_date_of_the_outputs(tmp_path, out):
    bad = GOOD.replace("as of 20 November 2026", "as of 21 November 2026")
    assert problems(tmp_path, out, bad) == [
        f"figures: line {line_of(bad, '21 November')}: date '21 November 2026' is not the date of the outputs"
    ]


def test_a_missing_output_is_reported_rather_than_ignored(tmp_path, out):
    (out / "kpis.csv").unlink()
    found = problems(tmp_path, out, GOOD)
    assert "figures: source output not found: kpis.csv" in found and any("5.6" in p for p in found)


# --- banned wording ---------------------------------------------------------------------------------------

def test_each_banned_term_fails_with_its_line(tmp_path, out):
    bad = GOOD.replace("Five ids matched no film.", "The Python script read the TMDb cache.")
    found = [p for p in problems(tmp_path, out, bad) if p.startswith("wording")]
    line = line_of(bad, "Python")
    assert found == [f"wording: line {line}: banned term {t!r}" for t in ("TMDb", "Python", "cache", "script")]


@pytest.mark.parametrize(
    "word", ["median", "Median", "MEDIAN", "medians", "spot-check", "spot check", "ROI", "snapshot"]
)
def test_banned_terms_are_found_in_any_case_and_as_plurals(tmp_path, out, word):
    assert any(p.startswith("wording") for p in problems(tmp_path, out, GOOD + f"\nThe {word} was fine.\n"))


@pytest.mark.parametrize("word", ["description", "scripted", "decache", "radius", "scriptwriter", "apiary"])
def test_a_banned_term_inside_another_word_is_not_a_hit(tmp_path, out, word):
    assert not [p for p in problems(tmp_path, out, GOOD + f"\nThe {word} was fine.\n") if p.startswith("wording")]


def test_the_banned_terms_include_the_ones_the_brief_names():
    for term in ("TMDb", "API", "pandas", "Python", "CSV", "JSON", "pipeline", "ADR", "ROI", "median", "dataframe",
                 "spot-check", "snapshot", "cache", "script", "repository", "GitHub", "regex", "endpoint"):
        assert term in check_memo.BANNED_TERMS


# --- length -----------------------------------------------------------------------------------------------

def test_a_memo_over_550_words_fails_and_one_at_the_limit_passes(tmp_path, out):
    base = check_memo.word_count(GOOD)
    at_limit = GOOD + "\n" + " ".join(["word"] * (550 - base)) + "\n"
    assert check_memo.word_count(at_limit) == 550 and problems(tmp_path, out, at_limit) == []
    over = at_limit + "word\n"
    assert problems(tmp_path, out, over) == ["length: 551 words, over the limit of 550"]


def test_markup_and_table_rules_are_not_counted_as_words():
    assert check_memo.word_count("## Heading\n\n| a | b |\n|---|---|\n| **c** | d |\n") == 5


# --- headings ---------------------------------------------------------------------------------------------

def test_a_missing_heading_is_named(tmp_path, out):
    found = problems(tmp_path, out, GOOD.replace("## What I recommend\n", ""))
    assert found == ["headings: '## What I recommend' is missing"]


def test_headings_out_of_order_fail(tmp_path, out):
    swapped = GOOD.replace("## What I built", "## TMP").replace("## What I recommend", "## What I built").replace(
        "## TMP", "## What I recommend")
    assert any("is out of order" in p for p in problems(tmp_path, out, swapped))


def test_the_title_and_the_from_date_subject_lines_must_be_there_and_filled(tmp_path, out):
    assert problems(tmp_path, out, GOOD.replace("# Memo to Kwame", "# A note")) == [
        "headings: the title '# Memo to <name>' is missing"
    ]
    empty = GOOD.replace("**From:** Noell", "**From:**")
    assert problems(tmp_path, out, empty) == ["headings: the 'From:' line is empty"]
    assert problems(tmp_path, out, GOOD.replace("**Subject:** What the evidence supports\n", "")) == [
        "headings: the 'Subject:' line is missing"
    ]


def test_an_unfilled_placeholder_fails_with_its_line(tmp_path, out):
    bad = GOOD.replace("under 4 seconds", "[[warm wall time]] seconds")
    assert f"placeholder: line {line_of(bad, '[[')}: unfilled [[warm wall time]]" in problems(tmp_path, out, bad)


# --- the command ------------------------------------------------------------------------------------------

def test_the_command_exits_0_for_a_good_memo_and_1_for_a_bad_one_and_writes_nothing(tmp_path, out, capsys):
    memo = memo_file(tmp_path, GOOD)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert check_memo.main(["--memo", str(memo), "--out", str(out)]) == 0
    assert "Memo check: PASSED" in capsys.readouterr().out
    bad = GOOD.replace("5.6 times", "9.9 times")
    memo.write_text(bad, encoding="utf-8")
    assert check_memo.main(["--memo", str(memo), "--out", str(out)]) == 1
    printed = capsys.readouterr().out
    assert f"FAIL figures: line {line_of(bad, '9.9')}: 9.9 is not in the outputs" in printed
    assert "FAILED, 1 problem(s)" in printed
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before


def test_the_command_stops_when_the_memo_is_missing(tmp_path, out, capsys):
    assert check_memo.main(["--memo", str(tmp_path / "none.md"), "--out", str(out)]) == 1
    assert "STOPPED: memo not found" in capsys.readouterr().out


# --- the real memo ----------------------------------------------------------------------------------------

REAL_OUT = Path(config.OUT_DIR)
REAL_MEMO = Path(config.REPO_ROOT) / "docs" / "client_memo.md"


@pytest.mark.skipif(not (REAL_OUT / "kpis.csv").is_file(), reason="needs a full run's outputs in out/")
@pytest.mark.xfail(strict=True, reason="the draft is over 550 words and quotes 104, which the outputs do not hold")
def test_the_real_memo_passes():
    assert check_memo.check(REAL_MEMO, REAL_OUT) == []
