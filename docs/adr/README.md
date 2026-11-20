# Architecture decision records

One file per decision, named `ADR-001-short-slug.md`, written from [template.md](template.md). Each ADR records the alternative we rejected and what choosing it would have changed.

Status values: Accepted, Planned (agreed in `de02-final-outline.md`, ADR not yet written), or Superseded by ADR-00M. A decision is written down when it is made, so Planned rows are written as their step is built.

| ADR | Decision | Status | Outline ref |
|---|---|---|---|
| [ADR-001](ADR-001-quarantine-file-with-reason-and-stage.md) | Excluded ids go to a quarantine file with a reason and the stage where they left | Accepted | Step 2 |
| [ADR-002](ADR-002-id-classification-rules.md) | Read the id list as text and classify each value by fixed rules | Accepted | Step 2 |
| [ADR-003](ADR-003-csv-for-stored-tables.md) | Store every table as CSV; Parquet only if types must be preserved | Accepted | D8 |
| [ADR-004](ADR-004-raw-cache-and-outputs-not-committed.md) | Cache raw responses for 180 days; do not commit the cache or `out/` | Accepted | D2, D10 |
| [ADR-005](ADR-005-exact-version-pins.md) | One `requirements.txt` with exact pins, NumPy by Python version | Accepted | D11 |
| [ADR-006](ADR-006-virtual-environment-not-docker.md) | Plain virtual environment, not Docker | Accepted | 16 Nov |
| [ADR-007](ADR-007-plain-python-runner.md) | Run the pipeline from plain Python files with one command | Accepted | Step 1 |
| — | No numeric time budget from Evalu8; ours is analysis stage under 10 s at 500 titles, fetch timed separately | Planned | D1 |
| — | Franchise = TMDb collection, with ranked edge cases | Planned | D3 |
| — | Genre: first-listed genre plus genre count, one row per film | Planned | D4 |
| — | Revenue or budget of 0 = missing; flag and exclude per metric | Planned | D5 |
| — | `tt0468569` excluded; id resolver is the improvement beyond the brief | Planned | D6 |
| — | Headline: median ROI per group; median vote count as second measure | Planned | D7 |
| — | Minimum 3 films to rank a bundle, 5 for a group conclusion | Planned | D9 |
