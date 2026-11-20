# ADR-010: Request one film at a time, at most 4 requests a second, with 5 retries

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

Fetching 117 films takes two requests each. The fetch runs once per snapshot and is timed separately from the analysis, so it is not inside the 10-second budget. On 20 Nov a request took a median of 0.30 seconds (95th percentile 0.38, slowest 0.69), measured from the fetch log over 229 requests.

## Decision

Requests run one after another. A small limiter keeps two requests at least a quarter of a second apart, which caps the rate at 4 a second. Transient errors (429 and 5xx) are retried up to 5 times with a growing wait (about 1, 2, 4, 8 and 16 seconds), and a `Retry-After` header is respected. Requests time out after 5 seconds to connect and 15 to read. A 401 or 404 is never retried.

## Alternatives considered

### Alternative A: Several requests at once

- **How it would work:** a pool of threads, say 4 to 8 at a time.
- **Why it is attractive:** the first fetch would take about a quarter of the time.
- **Why rejected:** the fetch runs once per snapshot, so the saving is about a minute. Concurrency complicates the rate limiter, the fetch log, the "three errors in a row" stop and the tests.

### Alternative B: No throttle of our own

- **How it would work:** send requests as fast as each response returns.
- **Why it is attractive:** nothing to configure.
- **Why rejected:** nothing stops a fast connection from sending a burst. The ceiling is cheap insurance and, as measured, costs nothing.

## Consequences

- **What this buys:** simple code and a log that is easy to read in order. The measured pace was 3.3 requests a second, 227 requests in 69.6 seconds, with every request answered on the first attempt (no retries, no 429 seen).
- **What this costs:** the 4-a-second ceiling did not limit the run. Requests take about 0.3 seconds each, so one at a time gives about 3.3 a second; the throttle would only matter on a faster connection. A single struggling request can take up to about two minutes before it is marked failed (31 seconds of waiting plus up to six 15-second timeouts).
- **What it costs the client if I am wrong:** a slower first fetch, once per snapshot. No effect on the numbers.
- **What would make me revisit this:** a first fetch that Adjoa finds too slow, or a list large enough that the wait is a problem.

## What this survives

At 500 titles the fetch is about 1,000 requests, which at the observed pace would take roughly 5 minutes (an estimate from this run, not a measurement). At 5,000 titles it would be close to an hour, and concurrency would be worth revisiting.
