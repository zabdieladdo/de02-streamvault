# Data findings — StreamVault

## Summary

Load stage only; the ranking is final after the fetch stage. Of the 127 rows in the id list, 117 go to the API and 10 are quarantined: six repeats, and four rows with no usable id (a blank, `N/A`, `-1` and an IMDb id). Repeats rank highest because a film counted twice can move a median in a small group. Five ids above 7 million were sent forward and are waiting for the API's answer.

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

## Findings, ranked by risk

### F-01: Six ids listed twice — Severity: High

- **What it is:** 155, 278, 550, 603, 680 and 1891 each appear on two lines.
- **How I detected it:** `duplicated()` on the parsed id; each repeat points to its first line in `quarantine.csv`.
- **Scale:** 6 of 127 rows (4.7%).
- **Effect on the client's number:** if kept, each film counts twice in its group. In groups of 3 to 10 films that can move a median by a whole position, and a repeated franchise entry inflates that bundle's evidence.
- **What I did about it:** kept the first occurrence, quarantined the rest.
- **Residual risk:** repeats under different ids (the same film under two TMDb ids) are not caught here; checked after the fetch by title and year (C-20).

### F-02: The standard file reader drops a row without warning — Severity: Medium

- **What it is:** a default read returns 126 rows, because the blank line is skipped and `N/A` becomes a null.
- **How I detected it:** comparing the default read with a separate line count.
- **Scale:** 1 row lost; any blank line in a future list would be lost the same way.
- **Effect on the client's number:** none on the averages, but the counts would not reconcile, which undermines every other figure in front of the board.
- **What I did about it:** read as text with blank lines kept; the run stops if the two counts differ (C-01).
- **Residual risk:** low; covered by a test.

### F-03: One IMDb id in a list of TMDb ids — Severity: Medium

- **What it is:** `tt0468569` is in IMDb's id format, not TMDb's.
- **How I detected it:** text pattern `tt` followed by digits.
- **Scale:** 1 row.
- **Effect on the client's number:** probably none: it appears to be a third copy of 155, which is already in the list. If it were a film not listed elsewhere, that film would be missing from the analysis.
- **What I did about it:** quarantined with a note; resolving IMDb ids is the planned improvement beyond the brief.
- **Residual risk:** it suggests one of the three sources used IMDb ids; next year's list may contain more.

### F-04: Three rows carry no id — Severity: Low

- **What it is:** a blank (line 69), `N/A` and `-1`.
- **How I detected it:** text rules in the load stage.
- **Scale:** 3 rows.
- **Effect on the client's number:** none; there is nothing to analyse.
- **What I did about it:** quarantined with reasons.
- **Residual risk:** if these were placeholders for titles someone meant to add, those titles are missing and nobody can say which.

### Pending after the fetch stage

- Five ids above 7 million (7733901, 8471293, 8471294, 9412887, 9412888) were flagged and sent forward. Severity set once the API answers.

### Observation: problems cluster near the end of the file

Of the 15 rows that are quarantined or flagged (10 quarantined, 5 large ids), 7 sit in lines 2-89 (7 of 88 rows, 8%) and 8 in lines 90-128 (8 of 39 rows, 21%). Lines 90-102 alone hold 7 of 13. One reading: the last block was appended from a single source, possibly the studio batch, which would also explain the IMDb id. This is a hypothesis, not a finding: the file has no source column. It matters for Adjoa because, if true, checking that one source's next batch catches most of next year's problems (Q1).

## Looked wrong, is not wrong

| Apparent problem | Why it looks wrong | Why it is actually fine |
|---|---|---|
| Ids such as 299534, 299536, 301528 | Much larger than 11 or 13 | TMDb numbers films in the order they were added; recent films have large ids |
| Windows line endings in the file | Can be changed silently by tools on other systems | The reader handles both (tested); the file is stored unchanged in the repository |

## Could not verify

- Which of the three sources each row came from: the file has no source column, so repeats and bad values cannot be traced to the source that produced them. The clustering above suggests, but does not show, one source.
