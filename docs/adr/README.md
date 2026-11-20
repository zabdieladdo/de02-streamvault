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
| [ADR-011](ADR-011-one-row-per-film.md) | The analysis table has one row per film | Accepted | 2026-11-20 |
| [ADR-012](ADR-012-franchise-means-tmdb-collection.md) | A film is a franchise entry when TMDb places it in a collection | Accepted | 2026-11-20 |
| [ADR-013](ADR-013-talent-scope-directors-and-top-three-actors.md) | The talent table holds directors and the top three billed actors only, separate from films | Accepted | 2026-11-20 |
| [ADR-014](ADR-014-how-leads-and-directors-are-identified.md) | Lead actors are the three lowest billing positions; directors are crew with the job "Director" | Accepted | 2026-11-20 |
| [ADR-015](ADR-015-suspect-money-units-flagged-not-corrected.md) | Budgets or revenues of $1 to $10,000 are flagged; with 500 or more votes they are treated as likely units errors; no value is corrected | Accepted | 2026-11-20 |
| [ADR-016](ADR-016-extremes-kept-and-tested.md) | Extreme multiples are kept and listed; the outlier test removes each group's top film and reports the shift | Accepted | 2026-11-20 |
| [ADR-017](ADR-017-headline-measure-median-multiple.md) | The headline measure is the median revenue÷budget multiple per group, with the mean, total÷total and median vote count beside it | Accepted | 2026-11-20 |
| [ADR-018](ADR-018-sequel-like-titles-reviewed-not-reclassified.md) | Standalone films whose titles look like sequels are listed for review, never reclassified automatically | Accepted | 2026-11-20 |
| [ADR-019](ADR-019-bundle-value-median-multiple.md) | A bundle is valued by the median multiple of its films on the list, with at least three usable films | Accepted | 2026-11-20 |
| [ADR-020](ADR-020-middle-entry-test-within-bundle.md) | The "weak middle entries" claim is tested within each bundle against its first film, as a supporting check | Accepted | 2026-11-20 |
| [ADR-021](ADR-021-talent-signal-over-independent-titles.md) | A director or lead actor signals a title worth licensing only on three or more independent titles, two-thirds of them above the list median | Accepted | 2026-11-20 |
| [ADR-022](ADR-022-shortlist-by-multiple-with-vote-rank.md) | The shortlist ranks by multiple, shows each pick's vote rank, and names one audience pick | Accepted | 2026-11-20 |
| [ADR-023](ADR-023-deal-note-relative-value-and-walk-away.md) | The deal note prices relative to the list: median multiple ÷ list median per film, with the weakest film as the walk-away line | Accepted | 2026-11-20 |
| [ADR-024](ADR-024-zero-money-means-not-reported.md) | A budget or revenue of zero means "not reported", not zero | Accepted | 2026-11-20 |
| [ADR-025](ADR-025-missing-release-date.md) | A film with no release date is kept, left out of the 2000-onward window, and counted | Accepted | 2026-11-20 |
| [ADR-026](ADR-026-small-groups.md) | Three films to rank a bundle, five for a group conclusion, and every figure carries its count | Accepted | 2026-11-20 |
| [ADR-027](ADR-027-window-disagreement-is-reported-first.md) | Disagreement between the two windows is detected by the run and reported first | Accepted | 2026-11-20 |
| [ADR-028](ADR-028-stand-behind-2000-onward.md) | The shortlist and deal note stand behind the 2000-onward window; all-years figures are the caveat | Accepted | 2026-11-20 |
| — | No numeric time budget from Evalu8; ours is analysis stage under 10 s at 500 titles, fetch timed separately (D1) | Planned | — |
| — | `tt0468569` excluded; id resolver is the improvement beyond the brief (D6) | Planned | — |
