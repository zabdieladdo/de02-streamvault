# ADR-014: Lead actors are the three lowest billing positions; directors are crew with the job "Director"

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

TMDb has no "lead" field. Each cast member has a billing number, `order`, where lower is billed higher; the numbers can have gaps. Crew members have a department and a job; the Directing department also contains assistant directors and other roles.

## Decision

Lead actors are the three cast members with the lowest `order` in each film, ranked 1 to 3 (ties broken by list position). Directors are crew members whose job is exactly "Director". A person who directs and acts in the same film appears once per role.

## Alternatives considered

### Alternative A: Lead actors are those with `order` 0, 1 or 2

- **How it would work:** filter on the billing number directly.
- **Why it is attractive:** one line; matches how TMDb usually numbers billing.
- **Why rejected:** where the numbering has gaps, a film can end up with fewer than three leads for no real reason (tested with orders 0, 2, 5, 7).

### Alternative B: Directors are everyone in the Directing department

- **How it would work:** filter on department instead of job.
- **Why it is attractive:** catches co-directors listed under a different job title.
- **Why rejected:** also catches assistant and second-unit directors, who are not the talent a negotiator means.

## Consequences

- **What this buys:** every film has exactly three leads and at least one director on this snapshot (checked: 0 films short of either).
- **What this costs:** billing reflects contracts, not screen time or audience draw.
- **What it costs the client if I am wrong:** a film's real draw may be the fourth-billed actor; that person is missed.
- **What would make me revisit this:** a film where the top three billed are obviously not the leads, found in the spot-check.

## What this survives

Unchanged at 500 titles; films with fewer than three cast members or no director are listed by check C-11, not dropped.
