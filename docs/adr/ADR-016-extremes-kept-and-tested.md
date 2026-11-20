# ADR-016: Extreme multiples are kept and listed; the outlier test removes each group's top film and reports the shift

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

A few films earn many times their budget. Removing them makes averages look tidier but throws away real results; keeping them lets one film carry a group average. The rubric asks whether one outlier produces the gap.

## Decision

Multiples above 50× or below 0.05× are listed for review and kept in every measure. Separately, each group's median is recomputed without its single highest-multiple film, and the shift is reported.

Measured: two films listed, Star Wars (70.5×) and Jaws (67.2×), both real results and kept. Without each group's top film, the franchise median moves from 5.62 to 5.53 and the standalone median from 3.84 to 3.24 (all years). The leader does not change.

## Alternatives considered

### Alternative A: Exclude extremes from the measures

- **How it would work:** drop films above or below the thresholds.
- **Why it is attractive:** averages stop being pulled by a handful of films.
- **Why rejected:** these are real box-office results; the median already resists them, and removing them hides exactly what Kwame's board will ask about.

### Alternative B: Trim the top and bottom 5% of each group

- **How it would work:** a trimmed mean or median.
- **Why it is attractive:** a standard statistical method.
- **Why rejected:** with 8 films in the smallest group, 5% is less than one film; the rule would do nothing there and different things in different groups. Removing one named film is clearer and can be explained to a board.

## Consequences

- **What this buys:** the answer to "does one film produce the gap?" is a number, with the film named.
- **What this costs:** the 50× and 0.05× thresholds are conventions; they only decide what is listed, not what is measured.
- **What it costs the client if I am wrong:** if an extreme film's figures are wrong, it still sits in the measures; the review list is where that would be caught.
- **What would make me revisit this:** a listed extreme found to be a data error in the spot-check.

## What this survives

Unchanged at 500 titles. The leave-one-out is computed per group, so it scales with the number of groups, not films.
