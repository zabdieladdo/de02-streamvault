# ADR-003: Store every table as CSV

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

Each stage writes a file for the next stage and for people to read. Raw API responses stay JSON as received. Adjoa opens the outputs on her own laptop, often in a spreadsheet.

## Decision

Every stored table is a CSV, UTF-8, no index. Parquet is used only if a table needs its types preserved between stages.

## Alternatives considered

### Alternative A: Parquet for intermediate tables

- **How it would work:** stages hand each other Parquet files; only final outputs are CSV.
- **Why it is attractive:** keeps types, compact, fast.
- **Why rejected:** adds a library (`pyarrow`) to install on Adjoa's laptop, and a person cannot open the files to check a stage. Tables here are a few hundred rows, so speed is not the issue.

## Consequences

- **What this buys:** every intermediate file can be opened and read by a person; one fewer dependency.
- **What this costs:** types are lost on write, so dates and ids must be given explicit types on every read.
- **What it costs the client if I am wrong:** a column read back with the wrong type could change a figure silently. The type check at the flatten stage (C-12) is the guard.
- **What would make me revisit this:** a table that cannot be read back correctly from CSV, or tables large enough to slow the analysis stage.

## What this survives

At 500 titles the files stay small. At 5,000 rows the timing run in the measurement report shows whether CSV still fits the time budget.
