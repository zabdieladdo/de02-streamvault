# Architecture decision records

One file per decision, named `ADR-001-short-slug.md`, written from [template.md](template.md). Each ADR records the alternative we rejected and what choosing it would have changed.

Status values: Accepted, Planned (agreed in `de02-final-outline.md`, ADR not yet written), or Superseded by ADR-00M. A decision is written down when it is made, so Planned rows are written as their step is built.

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](ADR-001-quarantine-file-with-reason-and-stage.md) | Excluded ids go to a quarantine file with a reason and the stage where they left | Accepted | 2026-11-20 |
| [ADR-008](ADR-008-cache-responses-including-not-found.md) | Save every response and reuse it for 180 days, including "not found" | Accepted | 2026-11-20 |
| [ADR-011](ADR-011-one-row-per-film.md) | The analysis table has one row per film | Accepted | 2026-11-20 |
| [ADR-012](ADR-012-franchise-means-tmdb-collection.md) | A film is a franchise entry when TMDb places it in a collection | Accepted | 2026-11-20 |
| [ADR-017](ADR-017-headline-measure-median-multiple.md) | The headline measure is the median revenue÷budget multiple per group, with the mean, total÷total and median vote count beside it | Accepted | 2026-11-20 |
| [ADR-024](ADR-024-zero-money-means-not-reported.md) | A budget or revenue of zero means "not reported", not zero | Accepted | 2026-11-20 |
| [ADR-030](ADR-030-read-saved-responses-from-one-snapshot-per-endpoint.md) | Read saved responses from one snapshot per endpoint | Proposed | 2026-11-20 |
| — | No numeric time budget from Evalu8; ours is analysis stage under 10 s at 500 titles, fetch timed separately (D1) | Planned | — |
| — | `tt0468569` excluded; id resolver is the improvement beyond the brief (D6) | Planned | — |
