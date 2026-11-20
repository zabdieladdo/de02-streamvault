# StreamVault licensing analysis

Compares franchise bundles with standalone films for StreamVault's licensing review,
using film data from TMDb. Built so it can be re-run each quarter on a new id list.

Built by Zabdiel; run each quarter by Adjoa.

Tested on: Python 3.15

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

Input: `data/input/id_list.csv` (one column of TMDb film ids). The code never changes this file.
Outputs are written to `out/` (not committed; regenerated on each run).
API responses are saved in `data/raw/` and reused for up to 180 days. The first run on an empty `data/raw/` needs your key and the network; later runs need neither.

### Where things are saved

| Folder or file | What it holds |
|---|---|
| `data/raw/details/`, `data/raw/credits/` | One saved response per film and endpoint (the source of truth) |
| `data/raw/fetch_log.csv` | Every request or saved answer: outcome, time, attempts |
| `data/raw/snapshot_movie.jsonl`, `data/raw/snapshot_credits.jsonl` | The same responses in one file per endpoint, which the analysis reads. Rebuilt automatically if they stop matching the fetch log |
| `data/raw/find/` | Saved answers from `resolve_ids.py` (optional) |

None of these is committed. They are TMDb's data: do not share them, and they expire after 180 days.

### Output files

| File in `out/` | What it is |
|---|---|
| `quarantine.csv` | Every id left out, with the reason and the stage (load or fetch) |
| `reconciliation.csv` | Row count after each stage, from the rows in the file to the analysis table |
| `ids_to_fetch.csv` | The valid ids sent to the fetch stage |
| `fetched_ids.csv` | The films that came back with details and credits, and where each response came from |
| `films.csv` | The analysis table: one row per film |
| `talent.csv` | Directors and the three top-billed actors: one row per film and person |
| `join_report.csv` | Proof for each join: rows before and after, key checks, unmatched keys |
| `films_profile.csv` | A profile of every column of `films.csv` (empty values, zeros, range) |
| `films_clean.csv` | `films.csv` with the usability flags and the revenue-to-budget multiple |
| `review_list.csv` | Items for a person to look at: suspect money, extreme multiples, sequel-like titles, possible repeats |
| `kpis.csv` | The measures for franchise and standalone films, in both windows (all years, 2000 onward) |
| `window_comparison.csv` | Which group leads on each measure in each window, and whether the windows agree |
| `decision_impact.csv` | Each cleaning decision run with and without it |
| `bundles.csv` | One row per franchise bundle: value, rank and weakest film in both windows |
| `entry_positions.csv`, `middle_entry_test.csv` | Each bundle film against its first film, and the test of whether middle films earn less |
| `talent_signal.csv` | Directors and lead actors with enough independent titles to show a signal |
| `shortlist.csv`, `window_differences.csv` | The shortlist in each window, and where the two windows differ |
| `deal_note.csv` | The candidate for the deal note, priced relative to the list |
| `checks_report.csv` | Every check, with pass or fail |
| `run_log.jsonl` | One line per run: counts, times, outcomes |
| `run_status.txt` | `complete`, or where the run stopped |
| `spotcheck.csv`, `spotcheck_summary.csv` | From `spotcheck.py` (cleared by a normal run) |
| `resolved_ids.csv`, `id_list_suggested.csv` | From `resolve_ids.py` (cleared by a normal run) |
| `measurement/` | From `measure.py`: `timing_runs.csv`, `timing_summary.csv`, `growth.csv`, `vectorisation.csv` |
| `limited/` | The outputs of a `--limit` run |

### Settings you can change

Three environment variables point a run at other folders; leave them unset for a normal run. They exist so `measure.py` and the tests can work on copies.

| Variable | Default |
|---|---|
| `STREAMVAULT_INPUT_IDS` | `data/input/id_list.csv` |
| `STREAMVAULT_RAW_DIR` | `data/raw/` |
| `STREAMVAULT_OUT_DIR` | `out/` |

## When the run stops

Check `out/run_status.txt` first. If it says stopped, the folder holds only what this run wrote before it stopped.

The run prints `STOPPED:` followed by a message and ends with exit code 1. The message names the check that failed. Whatever was written to `out/` before the stop stays there, and `out/run_log.jsonl` records the reason. Details of every check are in `out/checks_report.csv`.

**The run stops when:**

- TMDb rejects the API key.
- The network is down (three failed connections in a row).
- The two snapshot files cannot be written or rebuilt (check C-34).
- Rows were lost between stages (checks C-03, C-03f, C-03g): a film that went in did not come out and is not in the quarantine file.
- The measure figures are inconsistent (checks C-ROI, C-21, C-22, C-23, C-25): a multiple where there should be none, a measure row without its group sizes, group sizes that do not add up to the films in the window, a 2000-onward group larger than its all-years group, or two runs on the same input giving different results.

**The run does not stop for:**

- Films TMDb does not know ("not found"). They go to the quarantine file with the reason.
- A single failed request. That film is recorded as failed and the run carries on.
- Review-list items (checks C-15 to C-20): suspect money values, extreme multiples, sequel-like titles, possible repeats. They are listed in `out/review_list.csv` and the run continues. A person decides what to do with them.
- Whether both windows come from the same function (check C-24): this is checked by the test suite. The run records the result in `out/checks_report.csv` but does not stop for it.

If more than 5% of films fail to fetch, the run completes but prints `ANALYSIS INCOMPLETE`. Treat the results as unfinished and run it again.

### A run took about 16 seconds instead of about 4

The two snapshot files in `data/raw/` no longer matched the fetch log (for example they were copied in from another run), so the run rebuilt them from the saved responses. The stage 3 summary says `SNAPSHOT REBUILT`, and `out/run_status.txt` says so too. The results are correct. Run once more; the next run is fast.

## Spot-check

Run `python spotcheck.py` before using the results in a meeting, especially when the saved responses are weeks old. It re-fetches about 8 films live and compares them with the saved responses and the analysis tables. It needs the network and your key, and never changes the saved responses. Results are in `out/spotcheck.csv` and `out/spotcheck_summary.csv`; a normal pipeline run clears them, because they describe the snapshot at the time of the check. The last line says whether any difference changes the recommendation.

## Other commands

| Command | What it does | Needs the network and a key? |
|---|---|---|
| `python setup_check.py` | Checks the Python version, the packages and the key, and asks TMDb for one film | Yes |
| `python spotcheck.py` | The spot-check described above | Yes |
| `python resolve_ids.py` | Looks up the IMDb ids that the load stage quarantined and says which film each is. Writes `out/resolved_ids.csv`, and `out/id_list_suggested.csv` only if it finds films not on the list. It never changes the client's file: read the suggestion, then copy it out of `out/` (a normal run clears the `.csv` files there) and set `STREAMVAULT_INPUT_IDS` to the copy | Yes, unless every answer is already saved |
| `python measure.py` | Times full cached runs (warm, cold, growth to 5,000 films) and compares row-by-row with vectorised code. Takes about 7 minutes. Works on copies and invented data, writes `out/measurement/` | No |
| `python check_memo.py` | Checks `docs/client_memo.md`: every figure is in the outputs, no banned wording, 550 words or fewer, the template headings | No |

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

## The five deliverables and the documents behind them

1. Data diagnosis: [docs/findings.md](docs/findings.md)
2. Working analysis and timing: this repository, and [docs/measurement_report.md](docs/measurement_report.md)
3. Decision notes: [docs/adr/](docs/adr/README.md), and [docs/decisions-summary.md](docs/decisions-summary.md) for the decisions without a record of their own
4. Client memo: [docs/client_memo.md](docs/client_memo.md)
5. Improvement beyond the brief: [docs/improvement.md](docs/improvement.md) and `resolve_ids.py`

Also: [docs/assumptions.md](docs/assumptions.md) (S01-S26), [docs/data_contract.md](docs/data_contract.md) (the fields used) and [docs/questions.md](docs/questions.md) (open questions and who holds each answer).

## Attribution

This product uses TMDB and the TMDB APIs but is not endorsed, certified,
or otherwise approved by TMDB.
