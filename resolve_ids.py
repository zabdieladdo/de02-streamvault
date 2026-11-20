"""Turn the IMDb ids that stage 1 quarantined into TMDb films, and suggest an id list that includes them.

Run it after run_pipeline.py: python resolve_ids.py. It is optional and never run by run_pipeline.py. It needs
TMDB_API_KEY unless every answer is already saved, writes out/resolved_ids.csv (and out/id_list_suggested.csv
when it finds films that are not on the list), and never writes to data/input/: the client's file stays as received.
"""
import sys

import requests

from pipeline import config, resolve
from pipeline.errors import PipelineStopError
from pipeline.redact import redact


def main(argv: list[str] | None = None, session: requests.Session | None = None) -> int:
    """Resolve the quarantined IMDb ids. `session` lets tests pass a fake in place of the network."""
    key = None
    try:
        rows, ids_to_fetch = resolve.load_inputs(config.OUT_DIR)
        if rows.empty:
            print("No IMDb ids to resolve")
            return 0
        try:
            key = config.get_api_key()
        except PipelineStopError:
            key = None  # fine when every answer is already saved; the lookup says so if not
        lookups = resolve.lookup_all(rows["raw_value"].tolist(), session=session, key=key)
        table = resolve.build_table(rows, lookups, ids_to_fetch)
        suggested = resolve.suggested_ids(ids_to_fetch, table)
        resolve.write_results(config.OUT_DIR, table, suggested)
        print(resolve.format_summary(table, suggested, config.OUT_DIR, len(ids_to_fetch)))
    except PipelineStopError as exc:
        print(f"STOPPED: {redact(str(exc), key)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
