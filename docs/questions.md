# Questions for the client

Kwame is not available to answer, so each question carries the answer we assumed and what we did. Questions are numbered as they arise; each links to a finding.

| ID | When | To | Finding | Question | Answer we assumed | What we did |
|---|---|---|---|---|---|---|
| Q1 | Load | Adjoa | F-01, F-03 | Can each row in the list carry its source (tracker, predecessor's spreadsheet, studio batch)? Problem rows bunch at the end of the file (8 of 15 in the last 39 rows): was that block added from one source, perhaps the studio batch? | No source available | Treated all rows the same; noted under "Could not verify" |
| Q2 | Load | Adjoa | F-04 | Were the blank, `N/A` and `-1` rows placeholders for titles still to be chosen? | Not titles | Quarantined (ADR-001) |
| Q3 | Load | Studio licensing desk | F-03 | Do you send IMDb ids rather than TMDb ids? | Yes, for at least one row | Quarantined; resolver planned (improvement) |
| Q4 | Fetch | Studio licensing desk or Adjoa | F-05 | What do ids 7733901, 8471293, 8471294, 9412887 and 9412888 refer to? Are they another catalogue's numbers, and which films are they? | Another system's catalogue numbers, not TMDb films | Quarantined as not found; not asked again until the saved answer is 180 days old (ADR-002) |
