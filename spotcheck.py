"""Re-fetch the chosen films live from TMDb and compare them with the snapshot, field by field.

Run it after run_pipeline.py: python spotcheck.py. It needs the network and TMDB_API_KEY, is never run
by run_pipeline.py, and never writes to data/raw/ or the fetch log: the snapshot is what is checked.
"""
import sys

import requests

from pipeline import config, spotcheck
from pipeline.errors import PipelineStopError
from pipeline.redact import redact


def main(argv: list[str] | None = None, session: requests.Session | None = None) -> int:
    """Run the spot-check. `session` lets tests pass a fake in place of the network."""
    key = None
    try:
        key = config.get_api_key()
        tables = spotcheck.load_outputs()
        spotcheck.run_spotcheck(tables, session=session, key=key)
    except PipelineStopError as exc:
        print(f"STOPPED: {redact(str(exc), key)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
