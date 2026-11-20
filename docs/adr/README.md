# Architecture decision records

One file per decision, named `ADR-001-short-slug.md`, written from [template.md](template.md). Each ADR records the alternative we rejected and what choosing it would have changed.

Status values: Accepted, or Superseded by ADR-00M.

The decisions without a record of their own (missing dates, duplicates, failed requests, small groups, window disagreement, the talent signal) are listed in [../decisions-summary.md](../decisions-summary.md), with the assumption or finding that holds each one.

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](ADR-001-quarantine-file-with-reason-and-stage.md) | Excluded ids go to a quarantine file with a reason and the stage where they left | Accepted | 2026-11-20 |
| [ADR-002](ADR-002-cache-responses-including-not-found.md) | Save every response and reuse it for 180 days, including "not found" | Accepted | 2026-11-20 |
| [ADR-003](ADR-003-one-row-per-film.md) | The analysis table has one row per film | Accepted | 2026-11-20 |
| [ADR-004](ADR-004-franchise-means-tmdb-collection.md) | A film is a franchise entry when TMDb places it in a collection | Accepted | 2026-11-20 |
| [ADR-005](ADR-005-headline-measure-median-multiple.md) | The headline measure is the median revenue÷budget multiple per group, with the mean, total÷total and median vote count beside it | Accepted | 2026-11-20 |
| [ADR-006](ADR-006-zero-money-means-not-reported.md) | A budget or revenue of zero means "not reported", not zero | Accepted | 2026-11-20 |
| [ADR-007](ADR-007-read-saved-responses-from-one-snapshot-per-endpoint.md) | Read saved responses from one snapshot per endpoint | Accepted | 2026-11-20 |
