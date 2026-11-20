# Data findings — StreamVault

## Summary

127 rows were received. 10 left at load (blank, placeholder, negative, IMDb id, six repeats), 5 at the fetch (not on TMDb), leaving 112 films in the analysis table, one row per film, as of the 20 Nov 2026 snapshot. TMDb's data for these 112 is complete: no zero budgets or revenues, no missing release dates, no unreleased films, every film with a director and three billed actors. The faults in this lab are in the candidate list, not in the data returned for it. The largest risk to the recommendation is the list's shape: 96 franchise films against 16 standalones (F-06).

## Reconciliation

| Stage | Rows | Delta | Reason |
|---|---|---|---|
| Raw rows in file | 127 | | Input file 730 bytes, SHA-256 5B5138AC…4DC57A |
| Load: blank | 126 | -1 | Empty value (line 69) |
| Load: placeholder text | 125 | -1 | `N/A` |
| Load: IMDb id | 124 | -1 | `tt0468569` |
| Load: zero or negative | 123 | -1 | `-1` |
| Load: repeats | 117 | -6 | Six ids listed twice |
| Sent to the API | 117 | | |
| Fetch: not found on TMDb | 112 | -5 | Five ids returned "not found" (F-05) |
| Fetched with details and credits | 112 | | Snapshot 20 Nov 2026 |
| In the analysis table (one row per film) | 112 | 0 | Flatten stage: 0 unreadable responses; 3 joins proven with no rows added or lost |

## Findings, ranked by risk

Order after the flatten stage: F-06, F-01, F-05, F-02, F-03, F-04.

### F-06: The candidate list is mostly franchise films — Severity: High

- **What it is:** of 112 films, 96 belong to 32 TMDb collections and 16 are standalone.
- **How I detected it:** count of `is_franchise` after flattening (stage 3 summary).
- **Scale:** standalones are 14% of the list. In the 2000-onward window there are 8 standalone films.
- **Effect on the client's number:** every standalone figure rests on 16 films or fewer; one unusual standalone moves the standalone median far more than one franchise film moves the franchise median. The comparison Kwame asked for is lopsided before any calculation.
- **What I did about it:** group sizes are reported beside every figure; minimum group sizes apply (S14); the memo's confidence level reflects the standalone count.
- **Residual risk:** cannot be fixed by cleaning; it is how the list was built. A fair standalone comparison needs more standalone candidates.

### F-01: Six ids listed twice — Severity: High

- **What it is:** 155, 278, 550, 603, 680 and 1891 each appear on two lines.
- **How I detected it:** `duplicated()` on the parsed id; each repeat points to its first line in `quarantine.csv`.
- **Scale:** 6 of 127 rows (4.7%).
- **Effect on the client's number:** if kept, each film counts twice in its group. In groups of 3 to 10 films that can move a median by a whole position, and a repeated franchise entry inflates that bundle's evidence.
- **What I did about it:** kept the first occurrence, quarantined the rest.
- **Residual risk:** repeats under different ids (the same film under two TMDb ids) are not caught here; checked after the fetch by title and year (C-20).

### F-05: Five ids that TMDb does not know — Severity: Medium

- **What it is:** 7733901, 8471293, 8471294, 9412887 and 9412888 (file lines 99, 18, 73, 35 and 93) came back "not found" from TMDb. They are far above the range of film ids seen elsewhere in the list, and two of them are consecutive pairs (8471293 and 8471294; 9412887 and 9412888). They look like another system's catalogue numbers.
- **How I detected it:** the film request for each id returned HTTP 404 with the message "The resource you requested could not be found.", recorded in the fetch log.
- **Scale:** 5 of 117 ids sent to TMDb (4.3%); 5 of 127 rows in the file (3.9%).
- **Effect on the client's number:** five candidate titles cannot be evaluated, and nobody knows which films they are. If any is part of a bundle, that bundle looks smaller in the analysis than it is.
- **What I did about it:** quarantined as `not_found_on_api` with TMDb's message. Credits were not requested for them. The answer is remembered for 180 days, so a re-run does not ask again, and it is not counted as a failed request (ADR-008, ADR-009).
- **Residual risk:** if the ids are real titles in another catalogue, those titles are missing from the shortlist. Q4 asks what they refer to.

### F-02: The standard file reader drops a row without warning — Severity: Medium

- **What it is:** a default read returns 126 rows, because the blank line is skipped and `N/A` becomes a null.
- **How I detected it:** comparing the default read with a separate line count.
- **Scale:** 1 row lost; any blank line in a future list would be lost the same way.
- **Effect on the client's number:** none on the averages, but the counts would not reconcile, which undermines every other figure in front of the board.
- **What I did about it:** read as text with blank lines kept; the run stops if the two counts differ (C-01).
- **Residual risk:** low; covered by a test.

### F-03: IMDb id confirmed as a third copy of film 155 — Severity: Low (was Medium)

- **What it is:** `tt0468569` is the IMDb id that TMDb's own record for film 155 (The Dark Knight) carries.
- **How I detected it:** check I-01 compared the quarantined IMDb id with every fetched film's `imdb_id`.
- **Scale:** 1 row. The Dark Knight is listed three times in total: lines 2 and 91 as 155, line 95 as `tt0468569`.
- **Effect on the client's number:** none; the film is in the analysis once.
- **What I did about it:** stays quarantined; the evidence moves from "appears to be" to confirmed by the API.
- **Residual risk:** one source supplied IMDb ids; next year's list may contain more.

### F-04: Three rows carry no id — Severity: Low

- **What it is:** a blank (line 69), `N/A` and `-1`.
- **How I detected it:** text rules in the load stage.
- **Scale:** 3 rows.
- **Effect on the client's number:** none; there is nothing to analyse.
- **What I did about it:** quarantined with reasons.
- **Residual risk:** if these were placeholders for titles someone meant to add, those titles are missing and nobody can say which.

### Observation: problems cluster near the end of the file

Of the 15 rows that are quarantined or flagged (10 quarantined at load, 5 large ids), 7 sit in lines 2-89 (7 of 88 rows, 8%) and 8 in lines 90-128 (8 of 39 rows, 21%). Lines 90-102 alone hold 7 of 13. Two of the five not-found ids (lines 93 and 99) are in the last block. One reading: the last block was appended from a single source, possibly the studio batch, which would also explain the IMDb id. This is a hypothesis, not a finding: the file has no source column. It matters for Adjoa because, if true, checking that one source's next batch catches most of next year's problems (Q1).

## Looked wrong, is not wrong

| Apparent problem | Why it looks wrong | Why it is actually fine |
|---|---|---|
| Ids such as 299534, 299536, 301528 | Much larger than 11 or 13 | TMDb numbers films in the order they were added; recent films have large ids |
| Windows line endings in the file | Can be changed silently by tools on other systems | The reader handles both (tested); the file is stored unchanged in the repository |
| 122 directors for 112 films | More directors than films | Some films have two credited directors; each is a separate talent row, and the films table still has one row per film |
| Talent key not unique on film id alone (join report) | A join key that repeats looks like a fan-out | The talent table is many rows per film by design; its key is film, person and role, and the join was checked as many-to-one with no rows added |

## Could not verify

- Which of the three sources each row came from: the file has no source column, so repeats and bad values cannot be traced to the source that produced them. The clustering above suggests, but does not show, one source.
- What the five not-found ids refer to: TMDb has no record of them, so we cannot tell whether they are films, and if so which.
