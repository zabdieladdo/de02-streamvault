# ADR-004: Cache raw API responses on disk; do not commit the cache or `out/`

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

The analysis must re-run in seconds, so it cannot call the API each time. TMDb's terms limit caching to six months and forbid redistributing its content. The cache also holds the only copy of cast and crew names. The outputs in `out/` can be rebuilt by a run.

## Decision

Save each raw response to `data/raw/` and fetch again only if the file is missing or older than 180 days. `data/raw/` and `out/` are listed in `.gitignore` and never committed; each run regenerates `out/`.

## Alternatives considered

### Alternative A: Fetch on every run

- **How it would work:** call the API for every id each time.
- **Why it is attractive:** always current; no cache to manage.
- **Why rejected:** the analysis would no longer run in seconds, depends on the network, and breaks the "live in a meeting" use.

### Alternative B: Commit the outputs (or the cache) so graders see them

- **How it would work:** keep `out/` and the raw files in the repository.
- **Why it is attractive:** a reader sees results without running anything.
- **Why rejected:** committing raw responses redistributes TMDb content against its terms. Committed outputs go stale and can disagree with the code beside them.

## Consequences

- **What this buys:** fast re-runs from a saved snapshot; one copy of personal names; no TMDb content in the repository.
- **What this costs:** a clean clone must fetch once with the runner's own key, so its numbers can differ from ours. The snapshot date and the spot-check explain the difference.
- **What it costs the client if I am wrong:** a stale cache could present old figures as current; the 180-day check warns before that.
- **What would make me revisit this:** TMDb changing its caching terms, or Adjoa needing results without any key.

## What this survives

At 500 titles the first fetch takes minutes, once per snapshot; later runs read the cache.
