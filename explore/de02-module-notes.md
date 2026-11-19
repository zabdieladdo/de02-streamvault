# DE02 notes page: StreamVault lab (started Mon 16 Nov 2026)

Scratch notebook (`de02_scratch.ipynb`) holds the four running lists chapter 5 asks for. This page holds the checklist, the lab map, and the decision log.

## 1. Pre-Learning-Path checklist

| Item | State | Who |
|---|---|---|
| Read the TO DO chapter | Done (read together) | both |
| Python 3.11+, venv, pandas/NumPy/requests import | Commands below; run `setup_check.py` | Done |
| git: init, commit, push, clone into a different folder | Commands below | Done |
| TMDb account, key, one successful request | Register at themoviedb.org, then `setup_check.py` | Done |
| Key in an environment variable | Commands below (never in a committed file) | Done |
| Evalu8 sign-in, StreamVault brief read once | Brief text read in the PDF; confirm the Evalu8 login works | Done |
| Read the five shared templates on Evalu8 | Not reachable from here. Findings, ADR, client memo, improvement beyond the brief, measurement report | Done |
| Scratch notebook with four running lists | Done: `de02_scratch.ipynb` | done |
| Three-sentence franchise definition, before research | Blank cell in the notebook. Write it yourself, then I argue against it | you |
| Thirteen sessions blocked in the calendar | Done: `DE02_study_plan.ics` (the module table lists 14 sessions, not 13) | done |
| One forum post | Suggested post below | you |
| Cohort dates and submission deadline | Check the module pages. The brief gives no deadline; my plan assumed Wed/Thu | you |

## 2. Setup commands

macOS/Linux:
```
mkdir de02-streamvault && cd de02-streamvault
python3.11 -m venv .venv        # or python3.12 / 3.13
source .venv/bin/activate
pip install -r requirements.txt
export TMDB_API_KEY="paste-key-here"   # current shell only; add to ~/.zshrc or ~/.bashrc to persist
python setup_check.py
git init && git add . && git commit -m "Initial setup"
```
Windows (PowerShell):
```
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
setx TMDB_API_KEY "paste-key-here"     # persists; open a new terminal afterwards
python setup_check.py
```
Clone practice (this is what the assessment does):
```
git remote add origin <your-repo-url> && git push -u origin main
cd .. && git clone <your-repo-url> de02-clone-test
cd de02-clone-test && python -m venv .venv && (activate) && pip install -r requirements.txt
```
`.gitignore` already excludes `.venv/`, `.env`, and `data/raw/`. Decide later whether raw API responses go in the repo (Adjoa needs them to re-run without refetching) or stay local; log it in section 4.

## 3. Lab map

| Deliverable | Template | Rubric "strong" cue | Session |
|---|---|---|---|
| Data diagnosis | data findings | consequence per fault, ranked by risk; table of all 127 ids with reason and stage; real-vs-looks-broken | 12 |
| Working analysis | none (repo) | clean clone, no edits, key from env, both windows, no row loops, inside budget, fails loudly | 11, 13 |
| Decision notes | ADR (closing section: what this survives) | rejected alternative + effect of choosing differently; Adjoa can reverse it knowingly | write as you go |
| Client memo | client memo | one page, no tool names; recommendation, shortlist (3 franchise, 5 standalone), two windows, deal note, what you could not verify | 14 |
| Improvement | improvement beyond the brief | something Kwame or Adjoa would use, plus what it is worth to them | 14 |
| Timing report | measurement report | numeric budget from the brief; time the code at least once | 10, 13 |

Brief also asks for: a read on directors and lead actors that signal a licensing-worthy title. Check it appears in the memo plan.

Spot-check rule (rubric): pick the rows most likely to be wrong: one through the messiest parsing, one at an extreme, one affected by a cleaning decision, one that nearly failed to fetch. Compare field by field.

Evaluate rule: report group sizes, median beside mean, outlier influence; say which comparison you stand behind. If the two windows disagree, say so first.

## 4. Decision log (write when made)

Format per entry: date / what the brief left open / assumption / decision / rejected alternative / what it did to the result / what to revisit.

- 16 Nov: venv or Docker for reproducibility. Open. Lean: venv with a pinned `requirements.txt`. Docker removes Python-version mismatch (pandas 3 needs 3.11+) but Adjoa then needs Docker Desktop on her laptop and the module assesses a clean clone with a dependency list. Revisit if a clean clone fails on a different Python version.

## 5. Forum post (low stakes, no lab content)

Suggested: "Starting DE02 today. Setting up with a venv and a pinned requirements.txt. Has anyone tested a clean-clone run on Windows vs macOS yet, and did the Python version matter?" It asks about mechanics and shares no data or decisions.
