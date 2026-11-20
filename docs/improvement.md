# Improvement beyond the brief: IMDb id resolver

## The problem it solves

One of the three sources sent an IMDb id (`tt0468569`) where a TMDb id was expected (F-03). The pipeline quarantines such an id (ADR-002), so the title never reaches the analysis unless someone fixes it by hand. This year it was a third copy of The Dark Knight, so nothing was lost. Next year's list is about 500 titles from the same sources and may hold more, and a title that is missed is a title Kwame never sees priced.

## What I built

`python resolve_ids.py` takes each IMDb id the pipeline quarantined, asks TMDb which film it is, and says whether that film is already on the list. It writes `out/resolved_ids.csv` with one row per id (resolved, not found, ambiguous or failed). It writes a suggested id list, `out/id_list_suggested.csv`, only when it finds a film that is not already on the list, and it never changes the client's file in `data/input/`. It uses the same safeguards as the main fetch: saved answers reused for 180 days, retries, the same rate limit, and the key never written to any output. It is optional: the main analysis does not depend on it. This year's result, from the real run:

```
IMDb id resolver
  ids found in quarantine   1
  tt0468569   ->  155  The Dark Knight (2008)   already on the list (line 2): nothing to add
  suggested list            not written (no new films)
```

## What it is worth to Adjoa

Next year's studio batch can be used as sent: any IMDb ids in it are turned into the right films, or flagged, in one command instead of by hand.

## What it cost

- My time on it: the spec, the build and the tests (34 tests, with a fake session and no network). The hours were not recorded, so no figure is given here.
- One extra endpoint, TMDb's lookup by IMDb id, outside the two the brief names. Only this optional command uses it.
- One more folder of saved responses (`data/raw/find/`) under the same 180-day rule and the same limits on sharing.
- A person still decides whether to use the suggested list. A full run clears the `.csv` files in `out/`, so the suggestion has to be copied out of `out/` before it is used as the input (`STREAMVAULT_INPUT_IDS`), and an ambiguous or failed id is reported but never added.
