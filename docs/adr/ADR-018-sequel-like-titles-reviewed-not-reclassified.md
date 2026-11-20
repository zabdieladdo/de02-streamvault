# ADR-018: Standalone films whose titles look like sequels are listed for review, never reclassified automatically

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

ADR-012 counts a film as a franchise entry only when TMDb places it in a collection. A real sequel missing its collection would be counted as standalone. Titles with a number, a Roman numeral, "Part", "Chapter" or a colon are a cheap signal.

## Decision

Standalone films whose titles match that pattern are listed for review. None is moved to the franchise group by the code.

Measured: 0 standalone films matched.

## Alternatives considered

### Alternative A: Reclassify matching standalones as franchise entries

- **How it would work:** the title pattern overrides TMDb's collection field.
- **Why it is attractive:** catches sequels TMDb has not grouped.
- **Why rejected:** titles with numbers or colons are often not sequels; the brief requires the franchise rule to come from the API, not from guessing at titles.

## Consequences

- **What this buys:** the franchise rule stays one checkable fact; doubtful cases reach a person.
- **What this costs:** a person must read the list on a larger run.
- **What it costs the client if I am wrong:** a sequel counted as standalone shifts the standalone median; with 8 standalone films from 2000 onward, one film matters.
- **What would make me revisit this:** a listed film confirmed as a sequel.

## What this survives

At 500 titles the list may have entries; it is a review list, so it never changes the measures without a person deciding.
