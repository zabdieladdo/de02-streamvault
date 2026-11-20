"""The raw, input and output folders can be set by environment variable, for measurement runs."""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from pipeline import config

REPO = Path(config.REPO_ROOT)
VARIABLES = ("STREAMVAULT_RAW_DIR", "STREAMVAULT_INPUT_IDS", "STREAMVAULT_OUT_DIR")
SHOW_PATHS = (
    "import pipeline.config as c;"
    "print(c.RAW_DIR);print(c.INPUT_IDS);print(c.OUT_DIR);print(c.LIMITED_OUT_DIR);"
    "print(c.RAW_DETAILS_DIR);print(c.RAW_CREDITS_DIR);print(c.FETCH_LOG)"
)


def child_env(**overrides) -> dict:
    """This process's environment without any StreamVault variable, plus the given ones."""
    env = {k: v for k, v in os.environ.items() if k not in VARIABLES}
    env.update(overrides)
    return env


def paths(**overrides) -> list[Path]:
    out = subprocess.run(
        [sys.executable, "-c", SHOW_PATHS], cwd=REPO, env=child_env(**overrides), capture_output=True, text=True,
        check=True,
    )
    return [Path(line) for line in out.stdout.splitlines()]


def tree_hash(root: Path) -> dict:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_defaults_are_unchanged_when_no_variable_is_set():
    raw, ids, out, limited, details, credits, log = paths()
    assert raw == REPO / "data" / "raw" and ids == REPO / "data" / "input" / "id_list.csv"
    assert out == REPO / "out" and limited == REPO / "out" / "limited"
    assert details == raw / "details" and credits == raw / "credits" and log == raw / "fetch_log.csv"


def test_each_variable_moves_its_folder_and_everything_derived_from_it(tmp_path):
    raw, ids, out, limited, details, credits, log = paths(
        STREAMVAULT_RAW_DIR=str(tmp_path / "raw"), STREAMVAULT_INPUT_IDS=str(tmp_path / "ids.csv"),
        STREAMVAULT_OUT_DIR=str(tmp_path / "out"),
    )
    assert raw == tmp_path / "raw" and ids == tmp_path / "ids.csv" and out == tmp_path / "out"
    assert limited == tmp_path / "out" / "limited"
    assert details == raw / "details" and credits == raw / "credits" and log == raw / "fetch_log.csv"


def test_one_variable_leaves_the_other_defaults_alone(tmp_path):
    raw, ids, out, *_ = paths(STREAMVAULT_OUT_DIR=str(tmp_path / "out"))
    assert out == tmp_path / "out" and raw == REPO / "data" / "raw" and ids == REPO / "data" / "input" / "id_list.csv"


def test_an_empty_variable_means_the_default(tmp_path):
    raw, _, out, *_ = paths(STREAMVAULT_RAW_DIR="", STREAMVAULT_OUT_DIR="  ")
    assert raw == REPO / "data" / "raw" and out == REPO / "out"


def test_a_run_with_the_variables_set_changes_nothing_under_the_real_data_or_out(tmp_path):
    ids = tmp_path / "ids.csv"
    ids.write_text("tmdb_id\r\n155\r\n603\r\n", encoding="utf-8")
    real = {"data": tree_hash(REPO / "data"), "out": tree_hash(REPO / "out")}
    assert real["data"] and real["out"]  # there is a real snapshot and real outputs to protect

    env = child_env(
        STREAMVAULT_RAW_DIR=str(tmp_path / "raw"), STREAMVAULT_INPUT_IDS=str(ids),
        STREAMVAULT_OUT_DIR=str(tmp_path / "out"), TMDB_API_KEY="",  # an empty key: no request can be made
    )
    run = subprocess.run(
        [sys.executable, "run_pipeline.py"], cwd=REPO, env=env, capture_output=True, text=True, check=False
    )
    assert run.returncode == 1 and "TMDB_API_KEY not set" in run.stdout  # nothing cached, no key: it stops cleanly

    assert tree_hash(REPO / "data") == real["data"]
    assert tree_hash(REPO / "out") == real["out"]
    assert (tmp_path / "out" / "ids_to_fetch.csv").is_file()  # stage 1 wrote into the folder it was given
    assert (tmp_path / "out" / "run_log.jsonl").is_file()
    assert (tmp_path / "out" / "run_status.txt").read_text(encoding="utf-8").startswith("stopped at")
