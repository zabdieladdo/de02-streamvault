# StreamVault licensing analysis

Compares franchise bundles with standalone films for StreamVault's licensing review,
using film data from TMDb. Built so it can be re-run each quarter on a new id list.

## Setup (once)

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Get your own free TMDb API key (the licence is personal; do not reuse someone else's).
Copy `.env.example` to `.env` and put your key after `TMDB_API_KEY=`.
Never commit `.env`.

Check the setup:

```powershell
python setup_check.py
```

## Run

```powershell
python run_pipeline.py              # normal run: uses saved responses where they are under 180 days old
python run_pipeline.py --refresh    # ask TMDb for everything again, ignoring saved responses
python run_pipeline.py --limit 1    # quick check on the first N ids only
```

A `--limit` run writes to `out/limited/` and leaves full results in `out/` unchanged.

A run where every response is already saved needs no network and no API key.

Input: `data/input/id_list.csv` (one column of TMDb film ids).
Outputs are written to `out/` (not committed; regenerated on each run).
API responses are saved in `data/raw/` and reused for up to 180 days.

## When the run stops

Check `out/run_status.txt` first. If it says stopped, the folder holds only what this run wrote before it stopped.

The run prints `STOPPED:` followed by a message and ends with exit code 1. The message names the check that failed. Whatever was written to `out/` before the stop stays there, and `out/run_log.jsonl` records the reason. Details of every check are in `out/checks_report.csv`.

**The run stops when:**

- TMDb rejects the API key.
- The network is down (three failed connections in a row).
- Rows were lost between stages (checks C-03, C-03f, C-03g): a film that went in did not come out and is not in the quarantine file.
- The measure figures are inconsistent (checks C-ROI, C-21, C-22, C-23, C-25): a multiple where there should be none, a measure row without its group sizes, group sizes that do not add up to the films in the window, a 2000-onward group larger than its all-years group, or two runs on the same input giving different results.

**The run does not stop for:**

- Films TMDb does not know ("not found"). They go to the quarantine file with the reason.
- A single failed request. That film is recorded as failed and the run carries on.
- Review-list items (checks C-15 to C-20): suspect money values, extreme multiples, sequel-like titles, possible repeats. They are listed in `out/review_list.csv` and the run continues. A person decides what to do with them.
- Whether both windows come from the same function (check C-24): this is checked by the test suite. The run records the result in `out/checks_report.csv` but does not stop for it.

If more than 5% of films fail to fetch, the run completes but prints `ANALYSIS INCOMPLETE`. Treat the results as unfinished and run it again.

## Spot-check

Run `python spotcheck.py` before using the results in a meeting, especially when the saved responses are weeks old. It re-fetches about 8 films live and compares them with the saved responses and the analysis tables. It needs the network and your key, and never changes the saved responses. Results are in `out/spotcheck.csv` and `out/spotcheck_summary.csv`; a normal pipeline run clears them, because they describe the snapshot at the time of the check. The last line says whether any difference changes the recommendation.

## Tests

```powershell
python -m pytest -q
```

## Development

Code style is checked with [ruff](https://docs.astral.sh/ruff/). It is optional: it is not in `requirements.txt` and the pipeline does not need it. To run it:

```powershell
pip install ruff
ruff check .
```

The settings are in `ruff.toml`. Lines may be up to 120 characters. The usual limit of 88 would flag about 700 lines and reflow them into more, shorter lines (long messages, table rows and test fixtures), with no gain for a reader. The `explore/` folder is not checked.

The test suite passes with warnings turned into errors, so a deprecated or unsafe pandas call fails the build:

```powershell
python -m pytest -q -W error
```

`pytest.ini` puts the project root on the path, so the tests run from the repository root with no further setup.

## Documentation

- `docs/findings.md`: data problems found and where every id ended up
- `docs/adr/`: decisions and the alternatives rejected
- `docs/assumptions.md`: assumptions S01-S26

## Attribution

This product uses TMDB and the TMDB APIs but is not endorsed, certified,
or otherwise approved by TMDB.