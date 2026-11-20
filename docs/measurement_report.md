# Measurement report

## Target

A full cached run, from `python run_pipeline.py` to the last output file, takes under 10 seconds of wall time at 500 titles (S05). The fetch from TMDb is outside the budget: it is timed separately, and the brief sets no numeric target for it (confirmed 19 Nov). Our own ceiling for requests is 4 a second (ADR-010).

"Cached" means every response is already saved and no network request is made. "Wall time" is the time from starting the process to its end, so it includes Python start-up and imports, which Adjoa waits through. The sum of the stage times (our code only) is reported beside it.

## Method

- Hardware: 11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz, 4 cores, 32 GB RAM, Microsoft Windows 11 Business. One laptop, one network, 20 Nov 2026.
- Boundary: each measured run is a separate process of the real `run_pipeline.py`, with the API key blanked so a run that needed the network stops instead of making a request. Wall time is measured around the process; stage seconds come from that run's own line in `run_log.jsonl`.
- Real data and synthetic data: `measure.py` never writes the real `data/raw/` or `out/*.csv`. It works on copies and on synthetic responses in a temporary folder, chosen through `STREAMVAULT_RAW_DIR`, `STREAMVAULT_INPUT_IDS` and `STREAMVAULT_OUT_DIR`. Synthetic responses have TMDb's field names and types and invented values (about 50 cast and 150 crew per film, 1 to 4 genres, about 85% of films in collections of 2 to 8, fixed seed), because TMDb content may not be reused beyond its terms.
- Series: a warm series is a run of back-to-back runs on one folder; its first run on a freshly copied folder is reported on its own as "warm-up". A cold run is the first run on a freshly written or copied folder. The real snapshot: 1 warm-up and 10 warm runs, then 3 fresh copies, each run once cold and 4 times warm. Synthetic films at 127, 500 and 5,000: one cold run and 4 warm runs; at 500 titles on 3 fresh copies, plus 3 fresh copies with a stale snapshot, each run once.
- Percentiles: median and 95th percentile by linear interpolation between the closest ranks (numpy's default). With three runs or fewer the p95 is close to the worst and says little.
- Reproduce: `python measure.py` (about 10 minutes). The tables are written to `out/measurement/`: `timing_runs.csv`, `timing_summary.csv`, `growth.csv`, `vectorisation.csv`. Add `--help` for the options.

## Results

### 1. First measurement: 500 titles cold, not met

Before any change to how saved responses are read, the 500-title cold run took **15.6 s** against the 10 s budget (one run), so the target was **not met**. The same measurement gave warm 3.8 s (median of 4), real snapshot cold 4.74 s (median of 3) and warm 2.81 s (median of 10), and 5,000 titles cold 151.0 s (one run).

| Scenario (first measurement) | Runs | Median | p95 | Worst | Target met? |
|---|---|---|---|---|---|
| Real snapshot, 127 films, warm | 10 | 2.81 s | 4.34 s | 5.37 s | Yes |
| Real snapshot, fresh copy, cold | 3 | 4.74 s | 5.25 s | 5.30 s | Yes |
| Synthetic 500 films, cold | 1 | 15.60 s | n/a | 15.60 s | **No** |
| Synthetic 500 films, warm | 4 | 3.79 s | 4.31 s | 4.38 s | Yes |
| Synthetic 5,000 films, cold | 1 | 150.99 s | n/a | 150.99 s | Beyond the brief |

The cause was traced to the flatten stage: it opens about 1,000 newly written files (one details and one credits file per film) and reading them for the first time is slow. At 500 films the flatten stage took 13.2 s cold against 1.5 s warm, and every other stage took the same time cold and warm. The likely cause is scanning of newly written files by the operating system or security software; this is not proven.

### 2. After the snapshot change: 500 titles cold, met

The fetch stage now also writes one snapshot file per endpoint (`snapshot_movie.jsonl`, `snapshot_credits.jsonl`), and the flatten stage reads those two files instead of about 1,000 (ADR-030). Re-measured:

| Scenario | Runs | Median | p95 | Worst | Target met? |
|---|---|---|---|---|---|
| Real snapshot, 127 films, warm-up | 1 | 3.63 s | n/a | 3.63 s | Yes |
| Real snapshot, 127 films, warm | 10 | 2.74 s | 4.17 s | 4.49 s | Yes |
| Real snapshot, fresh copy, cold | 3 | 2.74 s | 3.09 s | 3.13 s | Yes |
| Real snapshot, fresh copy, warm | 12 | 2.87 s | 4.25 s | 4.31 s | Yes |
| Synthetic 127 films, cold | 1 | 3.08 s | n/a | 3.08 s | Yes |
| Synthetic 127 films, warm | 4 | 2.47 s | 2.74 s | 2.78 s | Yes |
| **Synthetic 500 films, cold (3 fresh copies)** | 3 | **3.61 s** | 4.07 s | 4.12 s | **Yes** |
| **Synthetic 500 films, warm** | 12 | **3.34 s** | 3.90 s | 4.07 s | **Yes** |
| Synthetic 500 films, cold, snapshot stale | 3 | 16.09 s | 17.54 s | 17.70 s | No (see Caveats) |
| Synthetic 5,000 films, cold | 1 | 38.12 s | n/a | 38.12 s | Beyond the brief |
| Synthetic 5,000 films, warm | 4 | 13.84 s | 21.55 s | 22.85 s | Beyond the brief |

Verdict line from `measure.py`: `budget (10 s wall, 500 titles, cached): met, cold 3.6 s, warm 3.3 s`.

Seconds per stage at 500 titles (median):

| Stage | Cold | Warm | Cold, snapshot stale |
|---|---|---|---|
| Load ids | 0.024 | 0.024 | 0.024 |
| Fetch (cache check and snapshot check) | 0.089 | 0.082 | 0.088 |
| Flatten and join | 1.144 | 1.191 | 12.965 |
| Clean | 0.034 | 0.036 | 0.061 |
| Measure | 0.288 | 0.308 | 0.437 |
| Rank | 0.193 | 0.199 | 0.240 |
| Sum of stages | 1.770 | 1.833 | 14.217 |
| Wall time | 3.613 | 3.343 | 16.087 |

Python start-up and imports account for the difference between wall time and the sum of stages (about 1.5 s warm).

### 3. The outputs did not change

The 21 CSV files a full run writes were compared with the same run before the snapshot change: **21 of 21 identical** (SHA-256 of the bytes). In `quarantine.csv` the `run_at` column was left out of the comparison, because it holds the time of the run and differs between any two runs, even of unchanged code; running the old code twice gave 20 identical files and only that column different. This was checked on the real data (127 ids), old code against new code, and again on the final code. A test also asserts that a run reading the snapshot and a run reading the per-film files give the same output on synthetic data.

### 4. Row by row against vectorised

On 5,000 synthetic films, computing the usability flags and the multiple row by row (`apply` with `axis=1`, written only for this measurement) took 0.6423 s (median of 5); the pipeline's vectorised code took 0.0169 s. The vectorised code is **38.1 times faster**, and the two give identical flags and multiples.

### 5. Growth from 127 to 5,000 films

Median warm seconds, synthetic data:

| Stage | 127 films | 500 films | 5,000 films | Ratio 500 / 127 | Ratio 5,000 / 500 |
|---|---|---|---|---|---|
| Load ids | 0.023 | 0.024 | 0.039 | 1.06 | 1.59 |
| Fetch | 0.032 | 0.082 | 0.546 | 2.51 | 6.69 |
| Flatten and join | 0.362 | 1.191 | 10.884 | 3.29 | 9.14 |
| Clean | 0.031 | 0.036 | 0.092 | 1.18 | 2.52 |
| Measure | 0.313 | 0.308 | 0.363 | 0.98 | 1.18 |
| Rank | 0.194 | 0.199 | 0.293 | 1.03 | 1.47 |
| Sum of stages | 0.953 | 1.833 | 12.190 | 1.92 | 6.65 |
| Wall time | 2.475 | 3.343 | 13.838 | 1.35 | 4.14 |

Flatten and join dominates at 500 and 5,000 films and grows about in proportion to the number of films (a tenfold rise in films gives a 9.1 times rise in time). The other stages grow more slowly than the film count. At 500 films about 1.5 s of the wall time is Python start-up, which does not grow.

## Before / after

| Change | Before | After |
|---|---|---|
| Read saved responses: one snapshot per endpoint instead of about 1,000 files (500 titles, cold, wall) | 15.6 s, one run, not met | 3.61 s, median of 3, met |
| Flatten stage, 500 titles, cold | 13.2 s | 1.14 s |
| Usability flags and multiple on 5,000 films: row by row to vectorised | 0.6423 s | 0.0169 s (38.1 times faster) |

The fetch figures below were measured earlier (20 Nov 2026) and are unchanged by this work:

| Scenario | Runs | Median | p95 | Worst | Target met? |
|---|---|---|---|---|---|
| Full fetch, cold cache: 117 ids, 227 requests, 3.27 requests a second | 1 | 69.6 s | n/a | 69.6 s | No target set |
| First film only (`--limit 1`): 2 requests | 1 | 0.94 s | n/a | 0.94 s | No target set |
| One request (all 229 in the fetch log) | 229 | 0.299 s | 0.382 s | 0.690 s | Not applicable |

- The cold fetch made 227 requests, not 229, because id 155 was already saved from the `--limit 1` run just before it.
- Every request was answered on the first attempt: no retries and no 429 in 229 requests.
- The 4-a-second ceiling never limited the run. Requests take about 0.3 seconds each, so one at a time gives about 3.3 a second.
- At 500 titles the fetch would be about 1,000 requests, which at this pace is roughly 5 minutes. This is an estimate worked out from the cold fetch, not a measurement.

## Caveats

- **A stale snapshot costs about 16 s at 500 titles.** If a snapshot no longer matches the fetch log (for example one copied in from another fetch), the flatten stage rebuilds it from the per-film files, which brings back the slow first read of about 1,000 files: 16.09 s median (worst 17.70 s) against the 10 s budget. The results stay correct, the rebuild is reported in the stage 3 summary, in `run_log.jsonl` and in `run_status.txt`, and the next run is fast because the snapshot is then current. Deleting the snapshot files does not cause this: the fetch stage builds a missing snapshot and the run stays fast.
- **5,000 titles is beyond the brief.** Warm median 13.8 s with a wide spread (p95 21.6 s, worst 22.9 s, four runs); cold 38.1 s (one run). The budget is for 500 titles.
- **The cause of the slow first read is not isolated.** Scanning of newly written files by the operating system or security software is the likely cause. It was not proven, for example by repeating the test with scanning switched off. Other machines may behave differently.
- The earlier slow first runs (8.85 s flatten at 04:17 UTC and 5.54 s at 07:11 UTC on 20 Nov, against 0.34 to 0.64 s for later runs) fit this pattern. The first measurement above showed the same effect on purpose: the flatten stage on a fresh copy of the real snapshot took 2.3 to 3.0 s against 0.5 s warm.
- One laptop, one network, one day. Disk cache and antivirus behaviour vary by machine.
- The synthetic data has the shape of TMDb's responses (field names, types, list sizes), not its content. Real responses may differ in size.
- Warm series vary from run to run: the real-snapshot warm runs had a median of 2.74 s and a worst of 4.49 s, and the first run of a series is usually the slowest (reported separately as warm-up).
- Cold runs of the 500-title size use fresh copies of one synthetic folder, so the three cold runs are not independent files.
