# ADR-007: Read saved responses from one snapshot per endpoint

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Zabdiel

## Context

The target is a full cached run under 10 s wall time at 500 titles (S05). The first measurement gave 15.6 s cold (one run), so the target was not met (`docs/measurement_report.md`, Results 1). The flatten stage took 13.2 s cold against 1.5 s warm, and no other stage changed between cold and warm. It opens about 1,000 newly written files, one details and one credits file per film, and reading them for the first time is slow. 
The per-film files are the saved responses ADR-002 describes, one file per film and endpoint with a 180-day life. The spec for this step said not to optimise in the measurement branch and left the fix to a separate decision.

## Decision

Keep the per-film files in `data/raw/` as the source of truth. At the end of the fetch stage, build two snapshot files in the same folder, `snapshot_movie.jsonl` and `snapshot_credits.jsonl`, one line per film whose fetch-log status is `ok`, and have the flatten stage read those two files. Before flatten, the snapshot's film ids and fetch times are compared with the fetch log; a snapshot that does not match is rebuilt from the per-film files, and the rebuild is reported (run log, run status, stage 3 summary). A rebuild that cannot be written stops the run (C-34). The spot-check still reads the per-film files.

## Alternatives considered

### Alternative A: leave it and narrow the budget boundary

- **How it would work:** Count a cached run as warm only, and report the first read of newly written files as a separate known cost.
- **Why it is attractive:** No code change; the warm 500-title run took 3.8 s.
- **Why rejected:** Adjoa's quarterly re-run follows a fetch, so the first run after a fetch is the one that matters, and it took 15.6 s.

### Alternative B: replace the per-film files with the combined files

- **How it would work:** Store only one combined file per endpoint and drop the per-film files.
- **Why it is attractive:** One copy of the data, no rebuild path.
- **Why rejected:** It changes ADR-002 and the fetch cache (each new film would rewrite a large file), and the spot-check and the fetch log are built around per-film files. The extra copy is the price of leaving those alone.

### Alternative C: read the per-film files in parallel

- **How it would work:** Open the files with several threads.
- **Why it is attractive:** Keeps the data layout as it is.
- **Why rejected:** The cause of the slow read is not isolated, so there is no evidence parallel reads would help; it also adds a source of run-to-run difference.

## Consequences

- **What this buys:** The 500-title cold run took 3.61 s (median of 3) and the warm run 3.34 s, inside the 10 s budget. The flatten stage at 500 titles went from 13.2 s to 1.14 s cold. The 21 CSV outputs are identical to those from reading the per-film files (21 of 21, `run_at` left out of `quarantine.csv`).
- **What this costs:**
  - An extra copy of the TMDb data. The snapshots sit in the same folder as the per-film files (`data/raw/`, not committed), follow the same 180-day rule (a film past 180 days, or whose file is missing or unreadable, is left out when the snapshot is rebuilt) and may not be shared. On the real data the two files take about 9 MB for 127 films.
  - The rebuild cost. A stale snapshot is rebuilt by reading the per-film files again, which brings back the slow first read: 16.09 s median at 500 titles (worst 17.70 s), over the budget. Results stay correct, the rebuild is reported, and the next run is fast. Deleting the snapshots does not cause this: the fetch stage builds a missing snapshot.
  - More code on the read path: a build step, a staleness check and a new stop (C-34).
- **What it costs the client if I am wrong:** If the snapshot and the per-film files ever disagreed without the check noticing, the analysis would use the snapshot's version. The check compares film ids and fetch times with the fetch log, not file contents, so a per-film file edited by hand would not be noticed until the snapshot is rebuilt.
- **What would make me revisit this:** a cause found for the slow first read that removes it without a second copy; a data volume where a rebuild is common; or a licence reading that treats the second copy differently from the first.

## What this survives

- A rebuilt snapshot gives the same outputs, byte for byte, as the one it replaced.
- A film that is not in the snapshot is read from its own file, so a damaged file is quarantined with the same reason as before.
- The spot-check, the fetch log and the 180-day rule are unchanged.
