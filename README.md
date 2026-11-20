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

## Tests

```powershell
python -m pytest -q
```

## Documentation

- `docs/findings.md`: data problems found and where every id ended up
- `docs/adr/`: decisions and the alternatives rejected
- `docs/assumptions.md`: assumptions S01-S23

## Attribution

This product uses TMDB and the TMDB APIs but is not endorsed, certified,
or otherwise approved by TMDB.