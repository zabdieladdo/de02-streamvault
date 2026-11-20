# Architecture decision records

One file per decision, named `ADR-001-short-slug.md`, written from [template.md](template.md). Each ADR records the alternative we rejected and what choosing it would have changed.

Status values: Accepted, Planned (agreed in `de02-final-outline.md`, ADR not yet written), or Superseded by ADR-00M. A decision is written down when it is made, so Planned rows are written as their step is built.

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](ADR-001-quarantine-file-with-reason-and-stage.md) | Excluded ids go to a quarantine file with a reason and the stage where they left | Accepted | 2026-11-20 |
| [ADR-002](ADR-002-id-classification-rules.md) | Read the id list as text and classify each value by fixed rules | Accepted | 2026-11-20 |
| [ADR-003](ADR-003-csv-for-stored-tables.md) | Store every table as CSV; Parquet only if types must be preserved | Accepted | 2026-11-20 |
| [ADR-004](ADR-004-raw-cache-and-outputs-not-committed.md) | Cache raw responses for 180 days; do not commit the cache or `out/` | Accepted | 2026-11-20 |
| [ADR-005](ADR-005-exact-version-pins.md) | One `requirements.txt` with exact pins, NumPy by Python version | Accepted | 2026-11-20 |
| [ADR-006](ADR-006-virtual-environment-not-docker.md) | Plain virtual environment, not Docker | Accepted | 2026-11-16 |
| [ADR-007](ADR-007-plain-python-runner.md) | Run the pipeline from plain Python files with one command | Accepted | 2026-11-20 |
| [ADR-008](ADR-008-cache-responses-including-not-found.md) | Save every response and reuse it for 180 days, including "not found" | Accepted | 2026-11-20 |
| [ADR-009](ADR-009-fetch-failure-handling.md) | Record a failed film and carry on; stop the run when the fault is ours | Accepted | 2026-11-20 |
| [ADR-010](ADR-010-sequential-requests-at-four-per-second.md) | Request one film at a time, at most 4 requests a second, with 5 retries | Accepted | 2026-11-20 |
| — | No numeric time budget from Evalu8; ours is analysis stage under 10 s at 500 titles, fetch timed separately (D1) | Planned | — |
| — | Franchise = TMDb collection, with ranked edge cases (D3) | Planned | — |
| — | Genre: first-listed genre plus genre count, one row per film (D4) | Planned | — |
| — | Revenue or budget of 0 = missing; flag and exclude per metric (D5) | Planned | — |
| — | `tt0468569` excluded; id resolver is the improvement beyond the brief (D6) | Planned | — |
| — | Headline: median ROI per group; median vote count as second measure (D7) | Planned | — |
| — | Minimum 3 films to rank a bundle, 5 for a group conclusion (D9) | Planned | — |
| — | Grain and talent scope: one row per film; directors and top three billed actors | Planned | — |
