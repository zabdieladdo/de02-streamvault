# ADR-005: The headline measure is the median revenue÷budget multiple per group, with the mean, total÷total and median vote count beside it

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Zabdiel

## Context

Kwame needs one comparison he can defend. Yaw distrusts pre-2000 money figures. Group sizes are uneven (96 franchise against 16 standalone films; 63 against 8 from 2000 onward), and a few films earn over 30× their budget.

## Decision

For each group and window: the median of each film's revenue÷budget is the headline. The mean sits beside it so the effect of extremes is visible. Total revenue ÷ total budget is a cross-check that lets large films weigh more. Median vote count is a second measure of audience interest, independent of box office. Group sizes are on every row.

## Alternatives considered

### Alternative A: Total revenue ÷ total budget as the headline

- **How it would work:** sum revenue and budget per group, then divide.
- **Why it is attractive:** reads like a portfolio return; large films count in proportion to their money.
- **Why rejected:** a handful of the largest films decide the result; Kwame is buying individual films and bundles, not a weighted portfolio. Kept as a cross-check (franchise leads on it too).

### Alternative B: Median revenue

- **How it would work:** compare box office directly.
- **Why it is attractive:** simplest to explain.
- **Why rejected:** mixes 1966 dollars with 2019 dollars, the exact objection Yaw will raise. A ratio of revenue to budget for the same film largely cancels inflation.

## Consequences

- **What this buys:** measured, franchise leads on median, mean and total÷total in both windows (median 5.62 against 3.84 all years; 5.05 against 3.84 from 2000 onward). The mean shows the standalone average (8.28) is lifted by one film, The Good, the Bad and the Ugly at 32.4×; the medians are 1.78 apart.
- **What this costs:** the multiple measures box-office return, not streaming value (S01). Median vote count points the other way (standalone 18,870 against franchise 15,494.5).
- **What it costs the client if I am wrong:** if box office is a poor stand-in for streaming demand, the ranking favours films that earned well in cinemas over films audiences return to. The vote-count disagreement says this risk is real on this list.
- **What would make me revisit this:** StreamVault's own viewing figures for licensed films.

## What this survives

The same function computes both windows (check C-24). At 500 titles the groups grow and the medians become more stable.
