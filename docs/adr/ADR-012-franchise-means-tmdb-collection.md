# ADR-012: A film is a franchise entry when TMDb places it in a collection

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

The brief asks for the franchise-versus-standalone comparison and says the rule must come from the API response, not from knowledge of films. TMDb's film record has a field, `belongs_to_collection`, that is either empty or names the series the film belongs to. Studios sell franchises as bundles.

## Decision

`is_franchise` is true when `belongs_to_collection` is not empty. The collection id groups the films of one bundle. A film counts as a franchise entry even when it is the only film from its collection in the list.

Measured on this snapshot: 96 films in 32 collections, 16 standalone. 9 collections have only one film in the list.

## Alternatives considered

### Alternative A: Infer franchises from shared studio, cast and release timing

- **How it would work:** films sharing a production company, lead actors and a gap of a few years between releases are grouped.
- **Why it is attractive:** works even where TMDb's collection data is missing.
- **Why rejected:** one studio makes many unrelated films; directors and actors repeat across unrelated films; long-running franchises change studio, recast and leave decades between entries. It rebuilds, badly, a fact the data already states.

### Alternative B: Count a film as a franchise entry only if at least two films of its collection are in the list

- **How it would work:** single-member collections are treated as standalone.
- **Why it is attractive:** every franchise group in the analysis has something to compare against.
- **Why rejected:** the studio still sells that film only as part of its bundle; calling it standalone misstates how it would be bought. Single-member collections are instead excluded from bundle rankings by the minimum group size (S14).

## Consequences

- **What this buys:** a rule anyone can check against TMDb, and one that needs no outside list.
- **What this costs:** TMDb's collections are maintained by volunteers; a sequel without a collection is counted as standalone, and a studio's "universe" may be split across several TMDb collections.
- **What it costs the client if I am wrong:** a franchise film counted as standalone would make the standalone group look stronger or weaker than it is. The next stage lists standalones whose titles look like sequels for a person to inspect.
- **What would make me revisit this:** finding a sequel among the standalones, or Kwame's team saying a studio bundles collections TMDb keeps separate.

## What this survives

The rule needs no change at 500 titles. The share of single-member collections will matter more as the list grows.
