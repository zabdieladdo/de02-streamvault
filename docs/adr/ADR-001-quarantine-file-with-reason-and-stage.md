# ADR-001: Excluded ids go to a quarantine file with a reason and the stage where they left

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

The id list has 127 rows assembled from three sources and never cleaned. Some rows cannot be analysed (blank, placeholder text, a negative number, an IMDb id, repeats), and later stages will reject more (ids the API does not recognise). The brief requires a full account of where every one of the 127 ids ended up, and the rubric marks down a pipeline that "silently produces a shorter table".

## Decision

Every row that cannot go forward is written to `out/quarantine.csv` with its file line number, the raw value, a reason code, a plain-language detail, the stage, and the run time. A conservation check stops the run if rows in ≠ rows forward + rows quarantined.

## Alternatives considered

### Alternative A: Drop invalid rows

- **How it would work:** filter them out and continue with the valid ids.
- **Why it is attractive:** least code; the analysis table is clean.
- **Why rejected:** the 127 can no longer be reconciled, which the brief requires; the reader cannot tell a deliberate exclusion from a bug.

### Alternative B: Keep every row in one table with a flag column

- **How it would work:** add `is_valid` and `reason` columns; every metric filters on the flag.
- **Why it is attractive:** one table holds everything; nothing to keep in step.
- **Why rejected:** every later calculation must remember the filter. One forgotten filter puts an invalid or repeated row back into a median. Used later for rows that are usable for some metrics only (missing revenue), not for rows usable for none.

### Alternative C: Log messages only

- **How it would work:** print or log each exclusion and continue.
- **Why it is attractive:** no extra file.
- **Why rejected:** logs scroll away; Adjoa cannot sort, count or compare them between quarters, and nothing feeds the reconciliation table.

## Consequences

- **What this buys:** the reconciliation table is built from data, not written from memory; each exclusion is traceable to a line in the client's file; the same file collects later-stage exclusions.
- **What this costs:** one more output to keep consistent with the analysis table, guarded by the conservation check. The file is overwritten each run, so the history of exclusions across quarters lives only in `run_log.jsonl` counts, not row by row.
- **What it costs the client if I am wrong:** if a quarantine rule is too strict, a real candidate film never reaches the analysis and Kwame never sees it priced. Mitigated because every quarantined row is listed with its raw value for a person to read.
- **What would make me revisit this:** Adjoa needing to compare excluded ids between quarters row by row, or the quarantine growing past about 10% of a list, which would mean the source needs fixing rather than the pipeline.

## What this survives

At 500 titles the file grows in proportion and stays readable. New kinds of bad value fall to `invalid_text` rather than passing through. A run on a new list reconciles by itself; nobody has to rewrite the table by hand.
