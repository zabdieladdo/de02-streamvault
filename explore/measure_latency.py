"""Measure round-trip time to TMDb from this machine (explore script, not part of the pipeline).

Makes 10 sequential GET /movie/{id} requests on one reused connection, using ids
from out/ids_to_fetch.csv, and prints each time plus the median. The median tells
us the fastest rate a one-at-a-time fetch can reach, whatever the throttle setting.

Run from the repo root:  python explore/measure_latency.py
"""
import os
import statistics
import sys
import time
from pathlib import Path

import pandas as pd
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

N = 10
REPO_ROOT = Path(__file__).resolve().parents[1]
key = os.environ.get("TMDB_API_KEY")
if not key:
    sys.exit("TMDB_API_KEY not set")

ids = pd.read_csv(REPO_ROOT / "out" / "ids_to_fetch.csv")["tmdb_id"]
ids = ids[ids <= 2_000_000].head(N).tolist()  # skip the five large ids: we want normal responses

session = requests.Session()
session.headers["User-Agent"] = "StreamVault-licensing-analysis/0.1 (latency check)"

times = []
for i, tmdb_id in enumerate(ids, start=1):
    start = time.perf_counter()
    r = session.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}",
                    params={"api_key": key}, timeout=(5, 15))
    elapsed = time.perf_counter() - start
    times.append(elapsed)
    print(f"{i:2d}  id {tmdb_id:>7}  status {r.status_code}  {elapsed:.3f} s")
    time.sleep(0.25)  # stay polite; the sleep is outside the timed region

warm = times[1:]  # the first request also sets up the secure connection
med = statistics.median(warm)
print()
print(f"first request (includes connection setup): {times[0]:.3f} s")
print(f"later requests: median {med:.3f} s, min {min(warm):.3f} s, max {max(warm):.3f} s")
print(f"fastest one-at-a-time rate: about {1 / med:.1f} requests per second")
print("If that is below 4, the 4-per-second throttle never takes effect on this network.")
