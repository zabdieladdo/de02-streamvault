"""Shared fixtures: a helper that writes small id-list CSV files to tmp_path."""
import pytest


@pytest.fixture
def write_ids(tmp_path):
    """Return write(values, header="tmdb_id", newline="\\r\\n", name="ids.csv") -> Path."""

    def write(values, header="tmdb_id", newline="\r\n", name="ids.csv"):
        path = tmp_path / name
        lines = [header, *values]
        path.write_bytes((newline.join(lines) + newline).encode("utf-8"))
        return path

    return write
