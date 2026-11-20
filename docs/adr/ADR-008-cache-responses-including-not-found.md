# ADR-008: Save every response and reuse it for 180 days, including "not found"

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

One full fetch is 229 requests and took about 70 seconds on 20 Nov. Adjoa re-runs the analysis each quarter, sometimes live in a meeting, and the analysis must run from saved data in seconds. TMDb's terms allow its data to be kept for six months at most. Five of the 117 ids sent to TMDb came back "not found". If those answers are not remembered, every run asks again and a fully saved run is impossible.

## Decision

Each successful response is saved as received, one file per film per endpoint, and reused until it is 180 days old. A "not found" answer is remembered for the same 180 days, in the fetch log, with TMDb's own message. Failed requests (timeouts, server errors, bad responses) are never remembered and are asked again on the next run. `--refresh` ignores all of this and asks for everything again.

## Alternatives considered

### Alternative A: Ask again for "not found" ids on every run

- **How it would work:** only successful responses are saved; a missing film is requested again each time.
- **Why it is attractive:** a film TMDb adds later is picked up at once.
- **Why rejected:** a run with every response saved would still need the network and a key for those five ids, which breaks the offline run Adjoa needs in a meeting.

### Alternative B: Remember "not found" for a shorter time than other responses

- **How it would work:** a separate expiry, say 30 days, for missing films.
- **Why it is attractive:** newly added films appear sooner.
- **Why rejected:** two expiry rules to explain, test and defend, for five ids. `--refresh` already covers the case.

## Consequences

- **What this buys:** a second run makes no requests (0 requests, 229 answered from the saved files, under a tenth of a second for the fetch stage) and needs no key or network. The 180-day limit stays inside TMDb's terms.
- **What this costs:** a film added to TMDb after our snapshot stays "not found" until the entry is 180 days old or someone uses `--refresh`. A `--limit` run writes to `out/limited/` so a quick check never overwrites full results (added 20 Nov).
- **What it costs the client if I am wrong:** a real film hidden behind a remembered "not found" would be missing from the shortlist. The five ids concerned here look like another system's catalogue numbers, so the expected cost is small.
- **What would make me revisit this:** any of the five ids starting to resolve, or a list where "not found" is common enough that a stale answer matters.

## What this survives

At 500 titles a re-run still reads saved files and makes no requests. Every quarter the cache is at most 180 days old, so the quarterly refetch is forced by the age check, not by anyone remembering to do it.
