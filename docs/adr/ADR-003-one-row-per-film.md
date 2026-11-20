# ADR-003: The analysis table has one row per film

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Zabdiel

## Context

Each film response contains lists: genres, production companies, and in the credits, cast and crew. Kwame's questions are about films (which to license, at what price), and every money figure belongs to a film. The shape of the table decides whether a total or a median can be trusted.

## Decision

`films.csv` has one row per film, keyed by TMDb id. Lists are reduced to counts and one summary value: `n_genres`, `primary_genre` (first listed), `genres_all` for reference, `n_production_companies`, `n_cast`, `n_directors`. People go in a separate table.

## Alternatives considered

### Alternative A: One row per film per genre

- **How it would work:** explode the genre list; a film with four genres becomes four rows.
- **Why it is attractive:** genre averages become a simple group-by; no information is collapsed.
- **Why rejected:** every money total and median counts a four-genre film four times unless each calculation remembers to undo it. Kwame asked nothing that needs genre averages.

### Alternative B: One row per film per person

- **How it would work:** join cast and crew onto films.
- **Why it is attractive:** one table answers both film and talent questions.
- **Why rejected:** a film's revenue repeats once per person; summed, the totals are inflated by the cast size (the fan-out the module warns about).

## Consequences

- **What this buys:** every count, total and median in the analysis is per film with no multiplier; the join to the talent table is checked as many-to-one (measured: 458 talent rows matched to 112 films, 0 rows added).
- **What this costs:** "primary genre" is the first genre TMDb lists, which TMDb does not document as the main one; per-genre analysis would need a separate table.
- **What it costs the client if I am wrong:** if Kwame's negotiators price by genre, this table cannot answer that without another step.
- **What would make me revisit this:** a question from Kwame or Adjoa that is about genres rather than films.

## What this survives

At 500 titles the table is 500 rows; nothing about the shape depends on how many genres or people a film has.
