# Assumptions register (S01-S23)

Cite these numbers in every deliverable. Sources: `de02-lab-plan.md` (S01-S20), `de02-round2-answers.md` (S21-S23). Where `de02-final-outline.md` changed one (S14, S11), the current wording is used and the change is noted in the last column.

**S01 is the marked assumption**: the one whose failure would most change the recommendation.

| # | Assumption | Basis | If wrong | Note |
|---|---|---|---|---|
| **S01 (marked)** | **Box-office revenue relative to budget is a usable proxy for how much a licensed film is worth to a streaming service** | Judgement; the brief gives no streaming viewing data | A film that underperformed in cinemas can do well on streaming and the reverse, so ranking by box office could mis-rank both groups. The memo names it as the one unverifiable link ("one thing that would change it") | Audience measures (`vote_count`) as a second view reduce the risk. The real fix is StreamVault's own viewing figures |
| S02 | Franchise entry = `belongs_to_collection` is not null | Brief asks for an API-derived rule; D3 / ADR | Collections missing on some titles push franchises into the standalone group | Edge cases ranked in round 2, section 9 |
| S03 | Revenue = 0 means not reported; excluded from money KPIs, kept in counts | Chapter 10 flag-and-exclude; D5 | If some zeros are real (unreleased, festival-only), excluding them flatters that group | Release-type detail is later extra work. Compare `vote_count` of zero-revenue films against the rest |
| S04 | Budget = 0 means not reported; ROI only where both budget and revenue > 0 | Same as S03 | ROI group sizes shrink; report n | |
| S05 | Time budget: analysis stage (saved responses to written outputs) under 10 s at 500 titles on an ordinary laptop; fetch timed and reported separately | Evalu8 gives no number (confirmed 19 Nov); D1; "live in a meeting" implies seconds | A tighter budget needs profiling per stage; a looser one weakens the live-meeting case | |
| S06 | Failed fetches: retry transient errors, never 404s; exclude and list the rest; if more than 5% fail, the memo states the analysis is incomplete. A 401 or connection error stops the run | Judgement | The threshold is a convention; state it | C-05 stop rule added in round 2 |
| S07 | ROI (revenue / budget) partly answers Yaw because both figures are in the same year's dollars | Reasoning | Does not fix reporting-method changes before 2000; keep the caveat | |
| S08 | Grain: one row per film | Rubric; D4 | Genre analysis needs a separate exploded table, never used for money sums | |
| S09 | Multiple genres collapse to `primary_genre` (first listed) plus `n_genres` | Judgement; D4 | First-listed order on TMDb may not mean "main"; genre is not central to the question | |
| S10 | Window boundary: release year >= 2000 from `release_date` | Brief | Films with no date are excluded from the 2000+ window and listed | |
| S11 | Headline KPI: median ROI per group, with median `vote_count` as the second measure; mean reported beside the median | Chapters 12-14; D7 | A mean would let one hit carry the conclusion (the trilogy mistake) | Second measure added by D7 |
| S12 | Lead actor = cast order 0-2 | Judgement | A wider cut adds names; a narrower cut leaves few people with 2+ films | Franchise caveat: count each collection once per person, and report how many independent titles back each name |
| S13 | "Reliable signal" = a person with at least k films in the list and a median ROI above the list median, with n shown | Judgement | With 127 titles most people will have 1 film; the likely finding is "too little evidence for most names" | |
| S14 | Minimum evidence: 3 films to rank a bundle, 5 for a group-level conclusion; always show n | Convention; D9 | Smaller groups can produce a high median by chance | Replaces the plan's single minimum of 5 |
| S15 | Duplicates: same id twice = remove and record; same title + year under two ids = semantic duplicate, keep one and record; same title, different year = remake, keep both | Chapter 11 | Re-release ids could double-count one film's revenue | |
| S16 | Bundle value = median ROI of the collection's films in our list; collection members missing from the list are reported, not fetched | The brief limits us to two endpoints per listed title | Bundle value is estimated from a partial bundle; flagged in the deal note | |
| S17 | The snapshot date of the fetch is the "as of" date for every figure | Chapter 7 | Re-runs on another date can differ; the spot-check shows by how much | |
| S18 | Raw responses cached on disk, not committed; cache expires at 180 days; key never committed | D2, D10; TMDb terms 1.C (6-month cache limit, no redistribution) | A clean clone refetches once with the runner's own key; numbers can drift from ours, which the snapshot date and spot-check explain | The cache is also the single copy of cast and crew names (Act 843 copy rule) |
| S19 | The 31 October review date is fictional; today's date does not affect the analysis | Brief | None | |
| S20 | Films with `status` other than "Released" are excluded from money KPIs | Judgement | Unreleased films have no revenue by definition and would look like zeros | |
| S21 | Budget and revenue are in US dollars | TMDb contribution guidance; the data has no currency field | One film's ROI is off by the exchange rate; check C-17 catches scale errors only | Listed under "could not verify" |
| S22 | Ids above 7 million are not valid TMDb ids, to be confirmed by the API | Profile of the id list: 7733901, 8471293, 8471294, 9412887, 9412888 | If some resolve, they join the analysis | Not excluded at load; the API decides and the status is logged |
| S23 | StreamVault would need a commercial TMDb agreement to use this in production | TMDb terms 1.C and 2.A (commercial use) | Stated as a risk, not a legal finding | Goes in the memo's "could not stand behind" |
