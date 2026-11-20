# ADR-020: The "weak middle entries" claim is tested within each bundle against its first film, as a supporting check

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

Half of Kwame's team says StreamVault overpays for weak middle entries. The data can test whether middle films earn less than the film that started the franchise.

## Decision

Within each rankable bundle, films are ordered by release date: the first film, the middle films, the latest film. Each film's multiple is divided by the first film's multiple; for each bundle the median of its middle films' ratios is taken, then the median across bundles, so each bundle counts once. Pooled medians by position are shown for reading. This is a supporting check, not the headline.

## Alternatives considered

### Alternative A: Pooled medians only

- **How it would work:** median multiple of all first films against all middle films against all latest films.
- **Why it is attractive:** one simple table.
- **Why rejected:** strong and weak franchises are mixed; a long series with many middle films swamps the result.

## Consequences

- **What this buys:** measured on 22 bundles and 41 middle films: middle films earn a median 0.69 of their first film, and so do latest films (0.69); 18 of 22 bundles have middle films below their first film. Pooled medians: first 7.76×, middle 5.41×, latest 4.44×. The decline is general after the first film, not specific to middle entries.
- **What this costs:** first films are selected winners: a sequel is usually made because the first film succeeded, so "first beats later" is partly built in before any data is read.
- **What it costs the client if I am wrong:** if the decline were only selection, Kwame would discount sequels he should value.
- **What would make me revisit this:** StreamVault's own viewing figures by position in a series.

## What this survives

More bundles at 500 titles make the median across bundles steadier; the method is unchanged.
