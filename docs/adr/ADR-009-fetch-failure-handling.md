# ADR-009: Record a failed film and carry on; stop the run when the fault is ours

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

A run makes about 230 requests. Some will fail for reasons that belong to one film (TMDb has no such id, a timeout, a server error). Others fail for a reason that belongs to us (a wrong or expired key, no network). The second kind would otherwise be recorded as 117 separate failures, all with the same cause.

## Decision

A request that fails for one film is retried by the session, then written to the fetch log and the quarantine file, and the run continues. The run stops, after writing the fetch log so far, when the fault is ours: a 401 from TMDb, a network error on the very first request, or three network errors in a row. If more than 5% of the ids fail to fetch, the run still finishes but prints "ANALYSIS INCOMPLETE" and records it in the run log. A film TMDb does not know is a fact about the list, not a failed request, and does not count towards the 5%.

## Alternatives considered

### Alternative A: Stop on the first failure

- **How it would work:** any error ends the run.
- **Why it is attractive:** nothing is ever half done; no incomplete output.
- **Why rejected:** one missing film, which is expected in this list, would stop the whole analysis. Five of 117 ids were not found.

### Alternative B: Retry every failure until it succeeds

- **How it would work:** no limit on retries, no stopping.
- **Why it is attractive:** no film is ever missing because of a passing error.
- **Why rejected:** a 404 never succeeds, and a dead network would hang a meeting.

### Alternative C: Record every failure and always continue

- **How it would work:** treat all errors alike.
- **Why it is attractive:** one rule, simplest code.
- **Why rejected:** a wrong key would produce 117 recorded "failures" and a shorter, wrong analysis that looks like a data problem.

## Consequences

- **What this buys:** a bad key or a dead network is reported as one clear message within a few requests. Per-film problems are listed with their reason and stage, and the reconciliation still adds up.
- **What this costs:** the 5% threshold is a convention, not a rule from the data. Three network errors in a row can stop a run during a short outage.
- **What it costs the client if I am wrong:** if failures stay under 5% but include important films, the analysis is not marked incomplete and a title is missing from the shortlist. Every failure is still listed by id in the quarantine file.
- **What would make me revisit this:** failures appearing in normal runs, or a share of failures that matters at 500 titles.

## What this survives

At 500 titles 5% is 25 films, which is a lot to lose, but each failure is listed and the log is written even when the run stops. A stopped run can be restarted: films already saved are not asked for again.
