# ADR-019: A bundle is valued by the median multiple of its films on the list, with at least three usable films

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

Studios sell a franchise as a bundle: all its films or none. Two years ago a trilogy bought on the strength of one film underperformed. Of 32 collections on the list, 22 have three or more usable films.

## Decision

Each bundle is ranked by the median revenue÷budget multiple of its films on the list. Total revenue ÷ total budget, the weakest film's multiple and the median vote count are shown beside it. A bundle needs at least 3 usable films to be ranked (S14). Bundles are ranked separately over all years and from 2000 onward.

## Alternatives considered

### Alternative A: Total revenue ÷ total budget

- **How it would work:** sum the bundle's revenue and budget, divide.
- **Why it is attractive:** matches buying the bundle as one block.
- **Why rejected:** the bundle's biggest film decides the result; the weak films Kwame must also buy disappear into the total, which is how the trilogy mistake happens.

### Alternative B: The weakest film's multiple

- **How it would work:** rank by the lowest multiple in the bundle.
- **Why it is attractive:** shows the worst film Kwame is forced to take.
- **Why rejected:** one film decides, and long series are punished for length. Kept beside the ranking and used as the walk-away line (ADR-023).

## Consequences

- **What this buys:** the ranking exposes weak entries. Measured: all-years leader Star Wars (median 13.4× over 6 films; weakest Attack of the Clones 5.4×); 2000-onward leader The Lord of the Rings (11.7× over 3 films; weakest The Fellowship of the Ring 9.4×).
- **What this costs:** every bundle figure is based on the films on the list; the studio's full bundle may hold more (TMDb's collection endpoint is outside the two endpoints the brief names).
- **What it costs the client if I am wrong:** a bundle whose missing films are weak would be overvalued.
- **What would make me revisit this:** a studio's bundle contents differing from the films on the list for a shortlisted franchise.

## What this survives

At 500 titles more bundles reach three films and become rankable; the rule is unchanged.
