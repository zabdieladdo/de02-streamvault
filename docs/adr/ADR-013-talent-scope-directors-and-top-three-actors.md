# ADR-013: The talent table holds directors and the top three billed actors only, separate from films

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

Kwame asked which directors and lead actors signal a title worth licensing. The credits response lists the full cast and crew, often dozens of people per film.

## Decision

`talent.csv` has one row per film, person and role, for directors and the three top-billed actors. People are identified by TMDb person id, because names are not unique. No money column is carried into this table; money is joined from films when needed, as many-to-one.

Measured: 458 rows: 336 lead actors (3 for each of the 112 films) and 122 directors (some films list more than one).

## Alternatives considered

### Alternative A: Keep the full cast and crew

- **How it would work:** every credit becomes a row.
- **Why it is attractive:** nothing is thrown away; other roles could be studied later.
- **Why rejected:** Kwame asked about directors and leads only; thousands of extra rows add checks and explanations with no question to answer.

### Alternative B: Add writers and producers

- **How it would work:** include crew with those jobs.
- **Why it is attractive:** writers and producers also carry franchises.
- **Why rejected:** not asked for; each extra role needs its own definition and test.

## Consequences

- **What this buys:** a small table that answers the question asked; no way to multiply revenue by cast size by accident.
- **What this costs:** a fourth-billed actor who later became the draw is not counted.
- **What it costs the client if I am wrong:** a negotiator may lose a talent lever the table never looked at.
- **What would make me revisit this:** Kwame's negotiators naming another role they use as leverage.

## What this survives

At 500 titles the table grows to about 1,600-2,000 rows; the shape and the checks are unchanged.
