# ADR-002: Read the id list as text and classify each value by fixed rules

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

Reading the file with default settings returns 126 rows, not 127: the blank line is dropped and `N/A` becomes a null, with no warning. Values include text, a negative number, an IMDb id and repeats. Next year's list (about 500 titles) will come from the same kinds of source, so the rules must handle forms not seen yet.

## Decision

Read every value as text, count lines separately and stop if the counts differ, then classify each value by the first matching rule: blank, placeholder text, IMDb id, zero or negative, decimal form, other text, valid. Repeats keep the first occurrence. A leading zero (`0603`) is corrected to 603 and flagged; a decimal (`603.0`) is quarantined, not corrected. Values with too many digits to be an id are quarantined as `invalid_text`. Ids above 2,000,000 are flagged and still sent to the API.

## Alternatives considered

### Alternative A: Read the column as numbers and coerce failures to null

- **How it would work:** `pd.to_numeric(errors="coerce")`, drop nulls.
- **Why it is attractive:** one line; standard practice.
- **Why rejected:** blank, `N/A`, `tt0468569` and any future typo all become the same null, so the diagnosis cannot say what was wrong with each; the blank row is already lost before coercion.

### Alternative B: Correct every fixable form (decimals, IMDb ids, padding)

- **How it would work:** strip `.0`, look up IMDb ids, normalise everything that can be read as a number.
- **Why it is attractive:** fewer exclusions, more films analysed.
- **Why rejected:** a decimal suggests a spreadsheet touched the value, and the original may not be what is shown; correcting it hides that. IMDb lookup needs a third endpoint (planned as the improvement beyond the brief).

### Alternative C: Exclude ids above a plausible range at load

- **How it would work:** treat ids above about 2 million as invalid.
- **Why it is attractive:** saves five API calls that will probably fail.
- **Why rejected:** the threshold is a guess about TMDb's id range; the API's answer is evidence, the guess is not. Rule from the module: use a rule to make a list to look at, never as a filter.

## Consequences

- **What this buys:** every quarantined row has a specific reason; a new placeholder word cannot pass as an id; line-ending differences have no effect (tested).
- **What this costs:** a fixed placeholder list to maintain; five API calls likely to fail; repeats are resolved by file order, which says nothing about which source was right.
- **What it costs the client if I am wrong:** if a quarantined decimal or IMDb id was a film not listed elsewhere, that title is missing from the shortlist. On this year's file the IMDb id is probably a third copy of a listed film, so the expected cost is nil.
- **What would make me revisit this:** a list where decimals or IMDb ids make up more than a handful of rows, or the API resolving any of the five large ids.

## What this survives

Larger lists, both line-ending styles, a leading BOM, padded values and new placeholder words. Tested on fixtures, not on the real file, so the rules do not depend on this year's values.
