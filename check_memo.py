"""Check docs/client_memo.md: every figure comes from out/, no banned wording, short enough, right headings.

Run it with: python check_memo.py. It reads out/ and the memo and writes nothing. Exit code 0 when every check
passes, 1 otherwise, with one line for each problem.
"""
import argparse
import math
import re
import sys
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

from pipeline import config, measurement

MEMO_PATH = config.REPO_ROOT / "docs" / "client_memo.md"
MAX_WORDS = 550  # one page with the table
TEMPLATE_HEADINGS = ["What I found", "What I built", "What I recommend", "What I could not stand behind"]
TEMPLATE_FIELDS = ["From", "Date", "Subject"]
BANNED_TERMS = [
    "TMDb", "API", "pandas", "Python", "CSV", "JSON", "pipeline", "ADR", "ROI", "median", "dataframe",
    "spot-check", "snapshot", "cache", "script", "repository", "GitHub", "regex", "endpoint",
]
# the outputs the memo may draw its figures from
SOURCE_FILES = [
    "kpis.csv", "bundles.csv", "shortlist.csv", "deal_note.csv", "talent_signal.csv", "middle_entry_test.csv",
    "spotcheck_summary.csv", "reconciliation.csv", "measurement/timing_summary.csv",
]
YEAR_SOURCE = "films.csv"  # release years of the films, for years named in the memo
FIXED_NUMBERS = {Decimal(2000), Decimal(127), Decimal(14)}  # the 2000 cut-off, the id list, the brief's $14M
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
DATE = re.compile(r"\b(\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})\b")
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _places(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def _round(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def numbers_in(text: str) -> list[tuple[str, bool]]:
    """Every number written in a text, as (token, is_percentage), dates taken out first."""
    text = DATE.sub(" ", text)
    found = []
    for match in NUMBER.finditer(text):
        found.append((match.group(0), text[match.end():match.end() + 1] == "%"))
    return found


def read_sources(out_dir: Path) -> tuple[set[Decimal], set[Decimal], list[str]]:
    """The values the memo may quote: every number in the source outputs, as exact decimals.

    Returns (values, years, missing) where `missing` names source files that are not there.
    """
    values: set[Decimal] = set()
    missing = []
    for name in SOURCE_FILES:
        path = out_dir / name
        if not path.is_file():
            missing.append(name)
            continue
        table = pd.read_csv(path, dtype=str, keep_default_na=False)
        cells = [*table.columns, *table.to_numpy().ravel().tolist()]
        for cell in cells:
            for token, _ in numbers_in(str(cell)):
                values.add(_decimal(token))
    summary = out_dir / "measurement" / "timing_summary.csv"
    if summary.is_file():  # "under N seconds": N is the next whole second above the 500-title run times
        table = pd.read_csv(summary)
        wall = table[(table["size"] == measurement.BUDGET_TITLES) & (table["metric"] == "wall_s")]
        wall = wall[wall["state"].isin(["cold", "warm"])]
        if not wall.empty:
            values.add(Decimal(math.ceil(float(wall["median_s"].max()))))
    years: set[Decimal] = set()
    films = out_dir / YEAR_SOURCE
    if films.is_file():
        released = pd.read_csv(films, usecols=["release_year"])["release_year"].dropna()
        years = {Decimal(int(year)) for year in released}
    return values, years, missing


def as_of_dates(out_dir: Path) -> set[str]:
    """The date of the run that made the outputs, written the way the memo writes dates."""
    status = out_dir / "run_status.txt"
    if not status.is_file():
        return set()
    match = re.search(r"\d{4}-\d{2}-\d{2}", status.read_text(encoding="utf-8"))
    if not match:
        return set()
    day = datetime.strptime(match.group(0), "%Y-%m-%d")
    return {f"{day.day} {MONTHS[day.month - 1]} {day.year}"}


def supported(token: str, is_percent: bool, values: set[Decimal], years: set[Decimal]) -> bool:
    """True when some source value, rounded to the places written, equals the number in the memo."""
    written = _decimal(token)
    places = _places(token)
    if written in FIXED_NUMBERS or (places == 0 and written in years):
        return True
    candidates = values | {v * 100 for v in values} if is_percent else values
    return any(_round(v, places) == written for v in candidates)


def check_figures(text: str, out_dir: Path) -> list[str]:
    """Every number or date in the memo that the outputs do not support."""
    values, years, missing = read_sources(out_dir)
    problems = [f"figures: source output not found: {name}" for name in missing]
    allowed_dates = as_of_dates(out_dir)
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in DATE.finditer(line):
            if match.group(0) not in allowed_dates:
                problems.append(f"figures: line {line_number}: date {match.group(0)!r} is not the date of the outputs")
        for token, is_percent in numbers_in(line):
            if not supported(token, is_percent, values, years):
                shown = token + ("%" if is_percent else "")
                problems.append(f"figures: line {line_number}: {shown} is not in the outputs")
    return problems


def check_wording(text: str) -> list[str]:
    """Banned terms, each with its line."""
    problems = []
    for term in BANNED_TERMS:
        spelled = re.escape(term).replace(r"\-", "[- ]")
        pattern = re.compile(rf"(?<![\w-]){spelled}s?(?![\w-])", re.IGNORECASE)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                problems.append(f"wording: line {line_number}: banned term {term!r}")
    return problems


def word_count(text: str) -> int:
    """Words in the memo, not counting table rules and markup characters."""
    words = [w for w in re.sub(r"[|*#]", " ", text).split() if re.search(r"\w", w)]
    return len(words)


def check_length(text: str) -> list[str]:
    count = word_count(text)
    return [f"length: {count} words, over the limit of {MAX_WORDS}"] if count > MAX_WORDS else []


def check_headings(text: str) -> list[str]:
    """The template headings and fields, present and in order."""
    problems = []
    lines = text.splitlines()
    if not any(re.match(r"# Memo to \S", line) for line in lines):
        problems.append("headings: the title '# Memo to <name>' is missing")
    position = -1
    for heading in TEMPLATE_HEADINGS:
        found = next((i for i, line in enumerate(lines) if line.strip() == f"## {heading}"), None)
        if found is None:
            problems.append(f"headings: '## {heading}' is missing")
        elif found < position:
            problems.append(f"headings: '## {heading}' is out of order")
        else:
            position = found
    for field in TEMPLATE_FIELDS:
        row = next((line for line in lines if line.startswith(f"**{field}:**")), None)
        if row is None:
            problems.append(f"headings: the '{field}:' line is missing")
        elif not row.split(":**", 1)[1].strip():
            problems.append(f"headings: the '{field}:' line is empty")
    return problems


def check_placeholders(text: str) -> list[str]:
    return [
        f"placeholder: line {n}: unfilled {m.group(0)}"
        for n, line in enumerate(text.splitlines(), start=1) for m in re.finditer(r"\[\[[^\]]*\]\]", line)
    ]


def check(memo: Path, out_dir: Path) -> list[str]:
    """All problems found in the memo, in the order: placeholders, headings, length, wording, figures."""
    text = memo.read_text(encoding="utf-8")
    return [
        *check_placeholders(text), *check_headings(text), *check_length(text), *check_wording(text),
        *check_figures(text, out_dir),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the client memo against the outputs.")
    parser.add_argument("--memo", type=Path, default=MEMO_PATH)
    parser.add_argument("--out", type=Path, default=config.OUT_DIR, help="the folder with the run's outputs")
    args = parser.parse_args(argv)
    if not args.memo.is_file():
        print(f"STOPPED: memo not found: {args.memo}")
        return 1
    text = args.memo.read_text(encoding="utf-8")
    problems = check(args.memo, args.out)
    print(f"Memo check: {word_count(text)} words (limit {MAX_WORDS})")
    for problem in problems:
        print(f"  FAIL {problem}")
    print("Memo check: PASSED" if not problems else f"Memo check: FAILED, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
