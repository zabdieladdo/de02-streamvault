# ADR-006: A budget or revenue of zero means "not reported", not zero

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Zabdiel

## Context

TMDb stores 0 where a contributor entered nothing. Averaged in as real, a zero revenue drags a group down; a zero budget cannot be divided by.

## Decision

Budget 0 or revenue 0 is treated as not reported (S03, S04): the film stays in counts and is left out of the multiple, with the reason recorded.

## Alternatives considered

### Alternative A: Treat zero as a real value

- **How it would work:** revenue 0 gives a multiple of 0.
- **Why it is attractive:** no judgement; uses every value as given.
- **Why rejected:** a film with no reported revenue did not earn nothing; its zero would pull its group down.

## Consequences

- **What this buys:** measured on this snapshot: 0 films affected; the with-and-without comparison shows no change.
- **What this costs:** a genuinely unreleased or zero-earning film would be left out of the multiple.
- **What it costs the client if I am wrong:** on a larger list, zeros are more likely on lesser-known films; leaving them out flatters their group.
- **What would make me revisit this:** zeros concentrated in one group on a larger list.

## What this survives

At 500 titles this rule will start to apply; the decision-impact table shows its effect each run.
