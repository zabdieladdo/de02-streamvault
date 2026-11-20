# ADR-005: One `requirements.txt` with exact version pins

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

Adjoa re-runs this every quarter, possibly on a different Python from ours (3.11 to 3.15). A loose `pandas>=3.0` installs a different pandas next year, which can change results without any change to the code. NumPy 2.5 dropped Python 3.11 and NumPy 2.4 has no build for 3.15.

## Decision

One `requirements.txt` with exact pins. The NumPy pin depends on the Python version. `ipykernel` is not listed; VS Code offers to install it when a notebook is opened.

## Alternatives considered

### Alternative A: Two files, runtime and development

- **How it would work:** `requirements.txt` for the pipeline and a second file for notebook and test tools.
- **Why it is attractive:** a smaller install for someone who only runs the pipeline.
- **Why rejected:** two files to keep in step for a repository this small; the only extra tool is `pytest`.

### Alternative B: Version ranges

- **How it would work:** `pandas>=3.0,<4`.
- **Why it is attractive:** picks up bug fixes.
- **Why rejected:** results can change between installs. An exact pin makes a difference between two runs a data difference, not a library difference.

## Consequences

- **What this buys:** the same install on any machine; the tested versions are stated.
- **What this costs:** pins must be updated by hand, and tested on 3.11 and 3.15 each time.
- **What it costs the client if I am wrong:** a pinned version with a security fix missed; low risk for a local tool.
- **What would make me revisit this:** a pinned version failing to install on Adjoa's Python.

## What this survives

New Python releases: the environment markers pick the right NumPy, and the clean-clone run on 3.11 and 3.15 is the check.
