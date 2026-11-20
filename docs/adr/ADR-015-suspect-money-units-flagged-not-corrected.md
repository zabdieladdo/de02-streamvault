# ADR-015: Budgets or revenues of $1 to $10,000 are flagged; with 500 or more votes they are treated as likely units errors; no value is corrected

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

TMDb's figures are entered by volunteers. A budget typed as "63" meaning 63 million produces a revenue÷budget multiple in the millions and wrecks any average. But real micro-budget films exist, with budgets and box office in the thousands of dollars, and their multiples are genuine extremes. TMDb returns whole dollars only (check C-12), so fractional "in millions" entries cannot arrive.

## Decision

A budget or revenue between $1 and $10,000 is flagged. If the film has 500 or more votes it is treated as a likely units error and left out of the multiple only. If it has fewer than 500 votes it is kept as a possible micro-budget film. Both are listed for review. No value is ever changed. The five largest budgets and revenues are also listed for review, to catch an extra digit.

Measured on this snapshot: 0 films flagged either way. The rule exists for larger lists.

## Alternatives considered

### Alternative A: Exclude every value in the range

- **How it would work:** any budget or revenue of $1-$10,000 leaves the multiple.
- **Why it is attractive:** one simple rule; no vote threshold to defend.
- **Why rejected:** removes real micro-budget films, whose high multiples are exactly the extremes the analysis should keep.

### Alternative B: Multiply suspect values by 1,000,000

- **How it would work:** a small budget on a well-known film is assumed to be in millions and scaled up.
- **Why it is attractive:** recovers a data point instead of losing it.
- **Why rejected:** invents a figure. If the guess is wrong, a median is corrupted with no trace. Same reasoning as ADR-002 not correcting `603.0`.

## Consequences

- **What this buys:** a units error cannot distort a median; a real micro-budget film is not discarded.
- **What this costs:** the 500-vote line is a convention (S24); a film near it can fall on the wrong side.
- **What it costs the client if I am wrong:** a mis-entered budget that slips through could make one film look like the best buy on the list. Mitigated by the review list and the largest-values check.
- **What would make me revisit this:** a flagged film whose real figures are confirmed from another source and contradict the rule.

## What this survives

At 500 titles, with more obscure films, this rule will start to fire. The review list grows with it and stays readable.
