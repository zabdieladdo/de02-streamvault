# ADR-027: Disagreement between the two windows is detected by the run and reported first

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

The brief says that if the recommendation changes between all years and 2000 onward, the memo must say so in the body. Suppressing it is the most serious error in the lab.

## Decision

Every measure and every list is computed for both windows from the same function. The run prints WINDOWS DISAGREE when a group leader differs, and SHORTLIST DIFFERS BETWEEN WINDOWS when any shortlist differs, and records both. The memo reports a disagreement before the recommendation.

## Alternatives considered

### Alternative A: Compare windows only at group level

- **How it would work:** check whether franchise or standalone leads in each window.
- **Why it is attractive:** that is the headline question.
- **Why rejected:** measured: the group leader is the same in both windows, but all three shortlists differ. A group-level check alone would have hidden that.

## Consequences

- **What this buys:** the franchise-versus-standalone verdict is shown to hold in both windows; the shortlist difference is surfaced, not discovered by Yaw.
- **What this costs:** the memo has to explain two lists.
- **What it costs the client if I am wrong:** n/a: the check only reports.
- **What would make me revisit this:** nothing; it runs every time.

## What this survives

Runs on every list size.
