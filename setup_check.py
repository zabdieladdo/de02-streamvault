"""DE02 setup check. Run from the activated virtual environment: python setup_check.py

Checks Python version, imports, the TMDB_API_KEY environment variable, and makes
one TMDb request for a single film. The key is never printed.
"""
import os
import sys

try:  # optional: read TMDB_API_KEY from a local .env file (never committed)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MIN_PY = (3, 11)  # pandas 3 does not install on 3.10
SAMPLE_ID = 550   # any valid TMDb movie id works


def main() -> int:
    ok = True
    print(f"python  {sys.version.split()[0]}  ({sys.executable})")
    if sys.version_info < MIN_PY:
        print("FAIL  Python 3.11 or newer is required")
        ok = False
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        print("WARN  not inside a virtual environment (activate it first)")

    try:
        import numpy as np
        import pandas as pd
        import requests
        print(f"pandas  {pd.__version__}   numpy  {np.__version__}   requests  {requests.__version__}")
        if int(pd.__version__.split(".")[0]) < 3:
            print("WARN  pandas is older than 3.x; chained-assignment behaviour differs from the module text")
    except ImportError as exc:
        print(f"FAIL  import error: {exc}")
        return 1

    key = os.environ.get("TMDB_API_KEY")
    if not key:
        print("FAIL  TMDB_API_KEY not found in the environment or in a .env file")
        return 1
    print("key     found in environment (not shown)")

    try:
        r = requests.get(
            f"https://api.themoviedb.org/3/movie/{SAMPLE_ID}",
            params={"api_key": key},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"FAIL  request error: {type(exc).__name__}")
        return 1
    print(f"http    {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        print(f"film    {d.get('title')!r}  release_date={d.get('release_date')!r}  revenue={d.get('revenue')!r}")
    else:
        print(f"FAIL  {r.text[:200]}")
        ok = False
    print("OK" if ok else "NOT OK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
