"""Stage 1-2: read ids as text, fetch from TMDb with timeout, retry and backoff, and cache raw responses."""
import hashlib
import io
import re
from pathlib import Path

import pandas as pd

from pipeline import config
from pipeline.errors import PipelineStopError


def read_id_file(path: Path) -> tuple[pd.DataFrame, dict]:
    """Read the id list as text, keeping every line, and return (raw, meta).

    raw has `line_number` (header = line 1) and `raw_value` (exactly as read).
    meta has input_bytes, input_sha256, bom_found, raw_line_count, header.
    """
    path = Path(path)
    if not path.is_file():
        raise PipelineStopError(f"Input file not found: {path}")

    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PipelineStopError(f"Input file is not valid UTF-8: {exc}") from exc
    bom_found = text.startswith("﻿")
    if bom_found:
        text = text[1:]
    if text == "":
        raise PipelineStopError("Input file is empty")

    # Count lines without pandas, so a silently dropped line shows up as a mismatch.
    lines = re.split(r"\r\n|\n|\r", text)
    if lines[-1] == "":
        lines.pop()  # exactly one, caused by the final line terminator
    raw_line_count = len(lines) - 1  # minus the header

    try:
        df = pd.read_csv(
            io.StringIO(text),
            dtype=str,
            keep_default_na=False,
            na_filter=False,
            skip_blank_lines=False,
            index_col=False,
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise PipelineStopError(f"Input file could not be read as one column: {exc}") from exc

    if df.shape[1] != 1:
        raise PipelineStopError(f"Expected exactly one column, found {df.shape[1]}")
    header = str(df.columns[0])
    if header.strip() != config.EXPECTED_HEADER:
        raise PipelineStopError(
            f"Expected header {config.EXPECTED_HEADER!r}, found {header.strip()!r}"
        )
    if len(df) != raw_line_count:
        raise PipelineStopError(
            f"Row count mismatch: pandas read {len(df)}, file has {raw_line_count} data lines"
        )
    if len(df) == 0:
        raise PipelineStopError("Input file has a header but no data rows")

    raw = pd.DataFrame(
        {
            "line_number": range(2, len(df) + 2),
            "raw_value": df.iloc[:, 0].astype(str).to_numpy(),
        }
    )
    meta = {
        "input_bytes": len(data),
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "bom_found": bom_found,
        "raw_line_count": raw_line_count,
        "header": header,
    }
    return raw, meta
