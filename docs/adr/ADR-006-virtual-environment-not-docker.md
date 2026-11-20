# ADR-006: Plain virtual environment, not Docker

- **Status:** Accepted
- **Date:** 2026-11-16
- **Decision owner:** Noell

## Context

Adjoa runs the pipeline on her own laptop, each quarter, sometimes live in a meeting. The pipeline is a few Python files with five dependencies.

## Decision

Use a plain Python virtual environment created from `requirements.txt`. The README gives the setup steps.

## Alternatives considered

### Alternative A: Docker

- **How it would work:** a container image with Python and the packages; Adjoa runs one container command.
- **Why it is attractive:** the same environment everywhere, including the operating system.
- **Why rejected:** Adjoa would need Docker installed and running, which is heavier than the tool it wraps. Exact pins in `requirements.txt` already fix the packages.

## Consequences

- **What this buys:** nothing extra to install beyond Python; quick start on a laptop.
- **What this costs:** the operating system and Python version are not fixed, only the packages.
- **What it costs the client if I am wrong:** a setup failure on Adjoa's machine costs her time before a meeting.
- **What would make me revisit this:** a setup failure that pins and the environment markers cannot explain, or the pipeline moving to a shared server.

## What this survives

A new laptop or a new Python version, as long as the install on 3.11 to 3.15 is re-tested.
