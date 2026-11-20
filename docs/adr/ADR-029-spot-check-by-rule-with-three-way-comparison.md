# ADR-029: The spot-check picks films by rule and classifies each difference by comparing the live value, the saved response and our table

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

The pipeline's figures come from a saved snapshot. A spot-check must show whether we read that snapshot correctly, and whether TMDb has changed since. The rubric asks for the rows most likely to be wrong: heaviest parsing, extreme of the distribution, affected by a cleaning decision, nearly failed to fetch.

## Decision

`spotcheck.py` chooses films by rule from the outputs: most cast, crew and genres; highest and lowest multiple; most list entries for one film; most fetch attempts (slowest response when none retried); and every film of the deal-note candidate. It re-fetches each live without touching the snapshot, compares field by field, and classifies each difference from three values: live, saved, ours. Same live and saved but different ours is a parsing error; different live but same saved and ours is a source change. Vote count, vote average and popularity are reported as volatile. Any change to budget, revenue, release date, collection or vote count is tested for whether it changes a ranking.

## Alternatives considered

### Alternative A: Hand-pick a few well-known films

- **How it would work:** choose films by name and compare.
- **Why it is attractive:** quick; easy to read.
- **Why rejected:** cannot be re-run on Adjoa's next list, and well-known films are the least likely to be wrong.

### Alternative B: Skip the "nearly failed" slice because no request retried

- **How it would work:** check three slices only.
- **Why it is attractive:** honest that the slice is empty.
- **Why rejected:** a missing slice reads as forgotten. The slowest response is the nearest stand-in, labelled as such.

### Alternative C: Treat every changed value as a discrepancy

- **How it would work:** any difference is a finding.
- **Why it is attractive:** strict.
- **Why rejected:** vote counts and popularity change daily on TMDb; counting them would bury a real error among expected drift.

## Consequences

- **What this buys:** measured on 8 films and 112 fields: 99 match, 13 volatile changes (vote counts up 3 to 8, under 0.1%; popularity within about ±2.5%), 0 parsing errors, 0 wrong fields, 0 source changes; no ranking changes.
- **What this costs:** 8 of 112 films are checked; the snapshot was about 6.5 hours old, so a source change was unlikely.
- **What it costs the client if I am wrong:** an error in an unchecked film would not be caught here.
- **What would make me revisit this:** a source change or parsing error on a future run.

## What this survives

At 500 titles the rules pick the same number of films; Adjoa runs it before each quarterly meeting, when the snapshot is weeks or months old and source changes become likely.
