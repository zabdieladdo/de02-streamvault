# ADR-025: A film with no release date is kept, left out of the 2000-onward window, and counted

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

The 2000-onward window needs a release year. TMDb can return an empty release date.

## Decision

A film with no parseable date stays in the all-years figures, is left out of the 2000-onward window, and the count of such films is printed.

## Alternatives considered

### Alternative A: Drop the film

- **How it would work:** remove it from all figures.
- **Why it is attractive:** both windows use the same films.
- **Why rejected:** its money figures are valid for the all-years comparison.

### Alternative B: Fill the year from another field

- **How it would work:** infer from collection order or another source.
- **Why it is attractive:** keeps the film in both windows.
- **Why rejected:** invents a fact the source does not hold.

## Consequences

- **What this buys:** measured: 0 films without a date on this snapshot.
- **What this costs:** on a larger list, the 2000-onward window could lose films without a date.
- **What it costs the client if I am wrong:** a recent film with a missing date would be judged only in the all-years window.
- **What would make me revisit this:** more than a handful of undated films.

## What this survives

The count is printed on every run.
