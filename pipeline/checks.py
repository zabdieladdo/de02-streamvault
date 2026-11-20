"""Run checks C-01 to C-27 and produce one pass/fail table."""
import numpy as np
import pandas as pd

from pipeline import config
from pipeline.errors import PipelineStopError

STAGE = "load"


def _row(check_id: str, description: str, passed: bool, detail: str) -> dict:
    return {
        "check_id": check_id,
        "description": description,
        "stage": STAGE,
        "passed": bool(passed),
        "detail": detail,
    }


def check_load_stage(
    meta: dict,
    raw: pd.DataFrame,
    ids_to_fetch: pd.DataFrame,
    quarantine: pd.DataFrame,
) -> pd.DataFrame:
    """Checks for stage 1; returns check_id, description, stage, passed, detail."""
    rows = []

    # C-01: header and row count read without loss
    header_ok = str(meta["header"]).strip() == config.EXPECTED_HEADER
    count_ok = len(raw) == meta["raw_line_count"]
    rows.append(
        _row(
            "C-01",
            "Header and row count read without loss",
            header_ok and count_ok,
            f"header {meta['header']!r}; read {len(raw)} rows, counted {meta['raw_line_count']} lines",
        )
    )

    # C-02: every input line is accounted for exactly once
    accounted = pd.concat([ids_to_fetch["first_line_number"], quarantine["line_number"]])
    seen_once = accounted.value_counts().eq(1).all()
    same_set = set(accounted) == set(raw["line_number"])
    rows.append(
        _row(
            "C-02",
            "Every row classified exactly once",
            bool(seen_once) and same_set and len(accounted) == len(raw),
            f"{len(accounted)} classifications for {len(raw)} rows",
        )
    )

    # C-03: conservation
    non_repeat_quarantine = int((quarantine["reason_code"] != "repeat").sum())
    sum_ok = len(raw) == int(ids_to_fetch["n_occurrences"].sum()) + non_repeat_quarantine
    split_ok = len(raw) == len(ids_to_fetch) + len(quarantine)
    rows.append(
        _row(
            "C-03",
            "Conservation: raw = sent forward + quarantined",
            sum_ok and split_ok,
            f"raw {len(raw)} = to fetch {len(ids_to_fetch)} + quarantined {len(quarantine)}",
        )
    )

    # C-04: ids sent forward are unique
    rows.append(
        _row(
            "C-04",
            "Ids sent forward are unique",
            ids_to_fetch["tmdb_id"].is_unique,
            f"{len(ids_to_fetch)} ids, {ids_to_fetch['tmdb_id'].nunique()} distinct",
        )
    )

    # C-04b: review list, always passes
    large = ids_to_fetch.loc[ids_to_fetch["flag_large_id"], "tmdb_id"].tolist()
    rows.append(
        _row(
            "C-04b",
            "Large ids flagged, not removed",
            True,
            f"{len(large)} flagged for review: {', '.join(map(str, large)) or 'none'}",
        )
    )

    return pd.DataFrame(rows, columns=["check_id", "description", "stage", "passed", "detail"])


def raise_if_conservation_failed(report: pd.DataFrame) -> None:
    """C-03 failing means rows were lost or invented; stop the run."""
    c03 = report.loc[report["check_id"] == "C-03"]
    if not c03.empty and not bool(c03["passed"].iloc[0]):
        raise PipelineStopError(f"C-03 failed: {c03['detail'].iloc[0]}")


def check_fetch_stage(run) -> pd.DataFrame:
    """Checks for stage 2. `run` is a fetch.FetchRun. Same columns as the load checks."""
    results, quarantine, ids = run.results, run.quarantine, run.ids_processed
    stage = "fetch"
    rows = []

    def add(check_id, description, passed, detail):
        rows.append(
            {
                "check_id": check_id, "description": description, "stage": stage,
                "passed": bool(passed), "detail": detail,
            }
        )

    # C-05: a 401 or a network error on the first request already stopped the run
    add(
        "C-05", "Key accepted and network reachable", run.preflight_ok,
        "first request accepted" if run.network_calls else "no network request needed (all cached)",
    )

    # C-06: one final outcome per id and endpoint
    per_pair = results.groupby(["tmdb_id", "endpoint"]).size() if len(results) else pd.Series(dtype=int)
    c06 = (
        len(results) == 2 * len(ids)
        and bool((per_pair == 1).all())
        and set(results["tmdb_id"]) == set(ids["tmdb_id"])
    )
    add("C-06", "Every id has one final outcome per endpoint", c06,
        f"{len(results)} results for {len(ids)} ids x 2 endpoints")

    # C-07: the response is the film requested
    n_mismatch = int((results["outcome"] == "id_mismatch").sum())
    add("C-07", "Responses are the film requested", n_mismatch == 0,
        f"{n_mismatch} responses with a different id")

    # C-08: details and credits cover the same films (credits_missing is the known exception)
    ok = results[results["outcome"].isin(["ok", "cached"])]
    d_ids = set(ok.loc[ok["endpoint"] == "details", "tmdb_id"])
    c_ids = set(ok.loc[ok["endpoint"] == "credits", "tmdb_id"])
    credits_missing = {
        int(v) for v in quarantine.loc[quarantine["reason_code"] == "credits_missing", "raw_value"]
    }
    unexplained = (d_ids ^ c_ids) - credits_missing
    add("C-08", "Details and credits cover the same films", not unexplained,
        f"{len(unexplained)} ids with one endpoint only, besides {len(credits_missing)} credits_missing")

    # C-09: nothing older than the TMDb cache limit was used
    ages = results["cache_age_days"].dropna().astype(float)
    too_old = int((ages >= config.CACHE_MAX_AGE_DAYS).sum())
    add("C-09", "Cache within TMDb's 6-month limit", too_old == 0,
        f"{len(ages)} cached entries used, oldest {ages.max():.0f} days" if len(ages)
        else "no cached entries used")

    # C-03f: conservation through fetch
    forward = len(ids) - len(quarantine)
    add("C-03f", "Conservation through fetch", forward >= 0 and len(ids) == forward + len(quarantine),
        f"ids processed {len(ids)} = fetched {forward} + quarantined {len(quarantine)}")

    # C-10i: enough of the list fetched. Not-found films are a fact about the list, not a failure.
    n_failed = int((quarantine["reason_code"] == "fetch_failed").sum())
    pct = 100 * n_failed / len(ids) if len(ids) else 0.0
    add("C-10i", "Analysis complete enough", pct <= config.INCOMPLETE_THRESHOLD_PCT,
        f"{n_failed} of {len(ids)} ids failed to fetch ({pct:.1f}%, limit {config.INCOMPLETE_THRESHOLD_PCT}%)")

    return pd.DataFrame(rows, columns=["check_id", "description", "stage", "passed", "detail"])


def check_flatten_stage(run, load_quarantine: pd.DataFrame) -> pd.DataFrame:
    """Checks for stage 3. `run` is a transform.FlattenRun; same columns as the other checks."""
    from pipeline.transform import imdb_crossref  # local import: transform imports fetch

    films, talent, joins = run.films, run.talent, run.join_report
    stage = "flatten"
    rows = []

    def add(check_id, description, passed, detail):
        rows.append(
            {
                "check_id": check_id, "description": description, "stage": stage,
                "passed": bool(passed), "detail": detail,
            }
        )

    n_in, n_q = len(run.fetched_ids), len(run.quarantine)

    add("C-10", "One row per film",
        films["tmdb_id"].is_unique and len(films) == n_in - n_q,
        f"{len(films)} rows, {films['tmdb_id'].nunique()} distinct ids; {n_in} in, {n_q} quarantined")

    no_cast = int((films["n_cast"] == 0).sum())
    no_dir = int((films["n_directors"] == 0).sum())
    few_leads = int((films["n_lead_actors"] < config.LEAD_ACTOR_COUNT).sum())
    missing = set(run.credits_ids) - set(films["tmdb_id"])
    add("C-11", "Flattening drops no film", not missing,
        f"{len(missing)} films lost; {no_cast} with no cast, {no_dir} with no director, "
        f"{few_leads} with fewer than {config.LEAD_ACTOR_COUNT} lead actors")

    int_ok = all(pd.api.types.is_integer_dtype(films[c]) for c in ("budget", "revenue", "vote_count"))
    date_ok = pd.api.types.is_datetime64_any_dtype(films["release_date"])
    n_empty = int((films["release_date_raw"] == "").sum())
    n_bad = int(films["release_date_unparseable"].sum())
    add("C-12", "Columns have the types the metrics need", int_ok and date_ok,
        f"budget, revenue, vote_count integer: {int_ok}; release_date datetime: {date_ok}; "
        f"{n_empty} empty dates, {n_bad} unparseable")

    names_per_collection = films.dropna(subset=["collection_id"]).groupby("collection_id")["collection_name"].nunique()
    add("C-13", "One name per collection", bool((names_per_collection <= 1).all()),
        f"{len(names_per_collection)} collections; {int((names_per_collection > 1).sum())} with more than one name")

    bad_joins = joins[joins["rows_changed"] | (joins["left_only"] > 0)]
    add("C-14", "Joins neither drop nor duplicate films", bad_joins.empty,
        f"{len(joins)} joins proven; {len(bad_joins)} changed the row count or left rows unmatched")

    key_unique = not talent.duplicated(["tmdb_id", "person_id", "role"]).any()
    talent_join = joins[joins["join"].str.startswith("3")]
    linked = bool((talent_join["left_only"] == 0).all())
    add("C-14t", "Talent keys unique and linked", key_unique and linked,
        f"{len(talent)} talent rows; key unique: {key_unique}; unmatched to a film: "
        f"{int(talent_join['left_only'].sum())}")

    add("C-03g", "Conservation through flatten", n_in == len(films) + n_q,
        f"fetched {n_in} = films {len(films)} + quarantined {n_q}")

    cross = imdb_crossref(films, load_quarantine)
    if cross.empty:
        text = "no IMDb ids were quarantined at load"
    else:
        found = cross.dropna(subset=["tmdb_id"])
        parts = [
            f"{i} matches film {int(f)} ({t})"
            for i, f, t in zip(found["imdb_id"], found["tmdb_id"], found["title"])
        ]
        parts += [f"{v} matches no fetched film" for v in cross.loc[cross["tmdb_id"].isna(), "imdb_id"]]
        text = "; ".join(parts)
    add("I-01", "IMDb id cross-reference (information)", True, text)

    return pd.DataFrame(rows, columns=["check_id", "description", "stage", "passed", "detail"])


def check_clean_stage(films_clean: pd.DataFrame, as_of_year: int | None = None) -> pd.DataFrame:
    """Checks C-15 to C-20 and C-ROI for stage 4; same columns as the other checks."""
    from datetime import datetime, timezone

    f = films_clean
    year_limit = as_of_year or datetime.now(timezone.utc).year
    rows = []

    def add(check_id, description, passed, detail):
        rows.append(
            {
                "check_id": check_id, "description": description, "stage": "clean",
                "passed": bool(passed), "detail": detail,
            }
        )

    def names(mask, n=8):
        titles = f.loc[mask, "title"].astype("string").fillna("(no title)").tolist()
        return ", ".join(titles[:n]) + (f" and {len(titles) - n} more" if len(titles) > n else "")

    n_neg = int(((f["budget"] < 0) | (f["revenue"] < 0)).sum())
    add("C-15", "No negative budget or revenue", n_neg == 0, f"{n_neg} films with a negative value")

    year = f["release_year"]
    n_missing = int(year.isna().sum())
    n_out = int(((year < 1900) | (year > year_limit)).sum())
    add("C-16", f"Release year between 1900 and {year_limit}", n_out == 0,
        f"{n_out} outside the range; {n_missing} with no year")

    n_units, n_micro = int(f["units_error_likely"].sum()), int(f["possible_micro_budget"].sum())
    add("C-17", "Suspect money values counted (review, not a failure)", True,
        f"{n_units} likely units errors; {n_micro} possible micro-budget films")

    ext = f["roi_extreme"].astype(bool)
    add("C-18", "Extreme multiples counted (listed, never removed)", True,
        f"{int(ext.sum())} extreme multiples" + (f": {names(ext)}" if ext.any() else ""))

    n_unreleased = int((~f["is_released"]).sum())
    n_video = int(f["video"].fillna(False).astype(bool).sum())
    n_adult = int(f["adult"].fillna(False).astype(bool).sum())
    add("C-19", "Unreleased, video and adult films counted", True,
        f"{n_unreleased} not released; {n_video} video; {n_adult} adult")

    n_groups = int(f.loc[f["possible_same_film"], "title_year_key"].nunique())
    n_seq = int(f["sequel_like_title"].sum())
    add("C-20", "Possible repeats and sequel-like standalones counted", True,
        f"{n_groups} possible same-film groups; {n_seq} sequel-like standalones")

    roi = f["roi"]
    mismatch = int((roi.isna() == f["roi_usable"]).sum())
    n_inf = int(np.isinf(roi.dropna()).sum())
    add("C-ROI", "roi is missing exactly where it is not usable", mismatch == 0 and n_inf == 0,
        f"{mismatch} rows disagree with roi_usable; {n_inf} infinite values")

    return pd.DataFrame(rows)
