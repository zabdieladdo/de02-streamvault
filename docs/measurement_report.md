# Fetch timing report

## Target

The brief sets no numeric target (confirmed 19 Nov). The fetch is timed separately from the analysis and sits outside the analysis time budget (S05). Our own ceiling for requests is 4 a second (ADR-010). The analysis-stage target, under 10 seconds at 500 titles, is measured later, when that stage is built.

## Method

- Hardware: 11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz, 4 cores, 32 GB RAM, Microsoft Windows 11 Business
- What was timed: the whole fetch stage, from the first cache check to after the fetch log is written (`seconds.fetch` in `out/run_log.jsonl`). It includes the pauses of the rate limiter. A single request is timed from sending to the end of the response, including any retries but not the limiter's pause (`elapsed_s` in `data/raw/fetch_log.csv`).
- Runs, warm or cold, and which figure is reported: the cold fetch was run once, because it makes about 230 requests to TMDb. The cached scenario was run three times. With three runs or fewer the 95th percentile is not meaningful and is shown as "n/a".
- How to reproduce: delete `data/raw/`, run `python run_pipeline.py` (cold), then run it again (cached). `python run_pipeline.py --limit 1` times the first film only. The figures below are from 20 Nov 2026, on one network, at one time of day.

## Results

| Scenario | Runs | Median | p95 | Worst | Target met? |
|---|---|---|---|---|---|
| Full fetch, cold cache: 117 ids, 227 requests, 3.27 requests a second | 1 | 69.6 s | n/a | 69.6 s | No target set |
| First film only (`--limit 1`): 2 requests | 1 | 0.94 s | n/a | 0.94 s | No target set |
| Full fetch, every response saved: 0 requests, 229 answered from the cache | 3 | 0.076 s | n/a | 0.089 s | No target set |
| One request (all 229 in the fetch log) | 229 | 0.299 s | 0.382 s | 0.690 s | Not applicable |

- The cold fetch made 227 requests, not 229, because id 155 was already saved from the `--limit 1` run just before it.
- Every request was answered on the first attempt: no retries and no 429 in 229 requests.
- The 4-a-second ceiling never limited the run. Requests take about 0.3 seconds each, so one at a time gives about 3.3 a second.
- The cached figure is the fetch stage only. Loading the id list added 0.03 to 0.04 seconds in the same runs.

## Before / after

Not yet measured; added when the analysis stage is built.

## Caveats

- One cold run. Network speed and TMDb's response time vary, so another day could give a different figure.
- One machine, with the network and time of day not controlled.
- At 500 titles the fetch would be about 1,000 requests, which at this pace is roughly 5 minutes. This is an estimate worked out from this run, not a measurement.
- The cached runs measure reading saved files and writing the log; they say nothing about how long the analysis stage will take.
