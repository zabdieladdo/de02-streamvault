# ADR-007: Run the pipeline from plain Python files with one command

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

Adjoa must be able to run the whole analysis without us. The graders also clone the repository and run it. Exploration happens in a notebook, but the analysis itself must be repeatable and testable.

## Decision

The pipeline is a set of modules under `pipeline/`, run in order by `python run_pipeline.py`. The notebook in `explore/` is for exploration only; nothing the pipeline depends on lives in it.

## Alternatives considered

### Alternative A: Run the analysis from a notebook

- **How it would work:** the stages are cells run top to bottom.
- **Why it is attractive:** results and commentary sit together.
- **Why rejected:** cell order and hidden state can change results, and the code is hard to test and to run from the command line.

## Consequences

- **What this buys:** one command; each stage can be tested on its own; stops with a message and a non-zero exit code when a check fails.
- **What this costs:** exploration and the pipeline are kept apart, so a finding in the notebook must be turned into code.
- **What it costs the client if I am wrong:** little; the same code could be called from a notebook later.
- **What would make me revisit this:** Adjoa preferring to work in a notebook.

## What this survives

Larger lists and added stages: each stage is a module with its own tests, and the runner prints counts and timings for every stage.
