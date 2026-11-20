"""Stages 3-5: flatten JSON, join films to credits with validate=, and set per-metric flags."""
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from pipeline import config, fetch
from pipeline.errors import PipelineStopError

FLATTEN_REASON_DETAIL = {
    "cache_unreadable": "Saved response missing, not valid JSON, or for a different id",
}
FLATTEN_REASON_ORDER = list(FLATTEN_REASON_DETAIL)

FILM_COLUMNS = [
    "tmdb_id", "first_line_number", "imdb_id", "title", "original_title",
    "release_date_raw", "release_date", "release_date_unparseable", "release_year",
    "status", "runtime", "budget", "revenue", "vote_count", "vote_average", "popularity",
    "original_language", "adult", "video", "collection_id", "collection_name", "is_franchise",
    "n_genres", "primary_genre", "genres_all", "n_production_companies",
    "n_cast", "n_crew", "n_directors", "n_lead_actors",
]
TALENT_COLUMNS = ["tmdb_id", "person_id", "name", "role", "billing_rank", "cast_order"]
QUARANTINE_COLUMNS = ["line_number", "raw_value", "reason_code", "reason_detail", "stage", "run_at"]


# --- reading saved responses (a loop over files, like the fetch) --------------------

def read_saved_responses(fetched_ids: pd.DataFrame, run_at: str | None = None):
    """Read details and credits for each fetched id.

    Returns (details_list, credits_list, flatten_quarantine). A film whose file is missing,
    not valid JSON, or for another id goes to quarantine and is in neither list.
    """
    run_at = run_at or datetime.now(UTC).isoformat(timespec="seconds")
    ids = fetched_ids.sort_values("first_line_number")
    details_list, credits_list, bad = [], [], []

    def load(endpoint: str, tmdb_id: int):
        path = fetch.cache_file(endpoint, tmdb_id)
        if not path.is_file():
            return None, f"{endpoint} file missing"
        try:
            body = json.loads(path.read_bytes())
        except ValueError:
            return None, f"{endpoint} file is not valid JSON"
        if not isinstance(body, dict) or body.get("id") != tmdb_id:
            return None, f"{endpoint} file is for a different id"
        return body, None

    for tmdb_id, line in zip(ids["tmdb_id"].tolist(), ids["first_line_number"].tolist()):
        details, why_d = load("details", tmdb_id)
        credits_, why_c = load("credits", tmdb_id)
        problem = why_d or why_c
        if problem:
            bad.append(
                {
                    "line_number": line, "raw_value": str(tmdb_id),
                    "reason_code": "cache_unreadable",
                    "reason_detail": f"{FLATTEN_REASON_DETAIL['cache_unreadable']}: {problem}",
                    "stage": "flatten", "run_at": run_at,
                }
            )
        else:
            details_list.append(details)
            credits_list.append(credits_)
    return details_list, credits_list, pd.DataFrame(bad, columns=QUARANTINE_COLUMNS)


# --- details -> films ------------------------------------------------------------

def _list_stats(col: pd.Series) -> pd.DataFrame:
    """For a column of lists of dicts: count, first name and pipe-joined names per row."""
    exploded = col.astype(object).explode()
    dicts = exploded.dropna()
    count = exploded.notna().groupby(level=0).sum().reindex(col.index, fill_value=0)
    if dicts.empty:
        names = pd.Series(dtype=object)
    else:
        names = pd.json_normalize(dicts.tolist()).reindex(columns=["name"])["name"]
        names.index = dicts.index
    names = names.dropna()
    return pd.DataFrame(
        {
            "count": count.astype("Int64"),
            "first": names.groupby(level=0).first().reindex(col.index).astype("string"),
            "joined": (
                names.astype(str).groupby(level=0).agg(joined="|".join)["joined"]
                .reindex(col.index).astype("string")
            ),
        }
    )


def _int(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def flatten_details(details_list: list) -> pd.DataFrame:
    """One row per film. No cleaning: zeros stay zeros, empty dates stay empty."""
    wanted = [
        "id", "imdb_id", "title", "original_title", "release_date", "status", "runtime",
        "budget", "revenue", "vote_count", "vote_average", "popularity", "original_language",
        "adult", "video", "belongs_to_collection_id", "belongs_to_collection_name",
        "genres", "production_companies",
    ]
    raw = (
        pd.json_normalize(details_list, sep="_", max_level=1) if details_list else pd.DataFrame()
    ).reindex(columns=wanted)  # a missing key becomes null, never an error
    genres = _list_stats(raw["genres"])
    companies = _list_stats(raw["production_companies"])

    raw_date = raw["release_date"].astype("string").fillna("")
    parsed = pd.to_datetime(raw_date, format="%Y-%m-%d", errors="coerce")
    collection_id = _int(raw["belongs_to_collection_id"])

    return pd.DataFrame(
        {
            "tmdb_id": raw["id"].astype("int64"),
            "imdb_id": raw["imdb_id"].astype("string"),
            "title": raw["title"].astype("string"),
            "original_title": raw["original_title"].astype("string"),
            "release_date_raw": raw_date,
            "release_date": parsed,
            "release_date_unparseable": ((raw_date != "") & parsed.isna()).astype(bool),
            "release_year": parsed.dt.year.astype("Int64"),
            "status": raw["status"].astype("string"),
            "runtime": _int(raw["runtime"]),
            "budget": _int(raw["budget"]),
            "revenue": _int(raw["revenue"]),
            "vote_count": _int(raw["vote_count"]),
            "vote_average": pd.to_numeric(raw["vote_average"], errors="coerce").astype("float64"),
            "popularity": pd.to_numeric(raw["popularity"], errors="coerce").astype("float64"),
            "original_language": raw["original_language"].astype("string"),
            "adult": raw["adult"].astype("boolean"),
            "video": raw["video"].astype("boolean"),
            "collection_id": collection_id,
            "collection_name": raw["belongs_to_collection_name"].astype("string"),
            "is_franchise": collection_id.notna(),
            "n_genres": genres["count"],
            "primary_genre": genres["first"],
            "genres_all": genres["joined"],
            "n_production_companies": companies["count"],
        }
    )


# --- credits -> counts and talent ------------------------------------------------

def _people(df: pd.DataFrame, column: str, keep: list) -> pd.DataFrame:
    """One row per person per film from one list column ("cast" or "crew") of the credits records.

    Uses json_normalize with the list as record_path and the film id as meta. A film whose list is
    missing, null or empty has no rows here; its count is still 0 because flatten_credits rebuilds
    the counts from the full list of film ids.
    """
    has_list = df[column].map(type).eq(list)  # a missing key (NaN) or a null (None) is not a list
    records = df.loc[has_list, ["id", column]].to_dict("records")
    if records:
        people = pd.json_normalize(records, record_path=column, meta=["id"], meta_prefix="film_")
    else:
        people = pd.DataFrame()
    people = people.reindex(columns=[*keep, "film_id"])
    people["tmdb_id"] = people.pop("film_id").astype("int64")
    return people.reset_index(drop=True)


def flatten_credits(credits_list: list) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (credit_counts, talent): counts for every film, and directors plus lead actors."""
    df = (pd.DataFrame(credits_list) if credits_list else pd.DataFrame()).reindex(
        columns=["id", "cast", "crew"]
    )
    ids = df["id"].astype("int64")

    cast = _people(df, "cast", ["id", "name", "order"])
    crew = _people(df, "crew", ["id", "name", "job"])

    # lead actors: the lowest `order` values in each film, ties broken by list position
    cast = cast.assign(
        cast_order=pd.to_numeric(cast["order"], errors="coerce"),
        list_pos=cast.groupby("tmdb_id").cumcount(),
    )
    ranked = (
        cast.sort_values(["tmdb_id", "cast_order", "list_pos"], na_position="last", kind="stable")
        .drop_duplicates(["tmdb_id", "id"])  # one row per person per film
        .reset_index(drop=True)
    )
    ranked["billing_rank"] = ranked.groupby("tmdb_id").cumcount() + 1
    leads = ranked[ranked["billing_rank"] <= config.LEAD_ACTOR_COUNT]
    directors = crew[crew["job"] == "Director"].drop_duplicates(["tmdb_id", "id"])

    talent = pd.concat(
        [
            pd.DataFrame(
                {
                    "tmdb_id": leads["tmdb_id"], "person_id": leads["id"], "name": leads["name"],
                    "role": "lead_actor", "billing_rank": leads["billing_rank"],
                    "cast_order": leads["cast_order"],
                }
            ),
            pd.DataFrame(
                {
                    "tmdb_id": directors["tmdb_id"], "person_id": directors["id"],
                    "name": directors["name"], "role": "director",
                    "billing_rank": np.nan, "cast_order": np.nan,
                }
            ),
        ],
        ignore_index=True,
    )
    talent = talent.astype(
        {
            "tmdb_id": "int64", "person_id": "int64", "name": "string", "role": "string",
            "billing_rank": "Int64", "cast_order": "Int64",
        }
    )
    talent = (
        talent.sort_values(["tmdb_id", "role", "billing_rank"], kind="stable")
        .reset_index(drop=True)[TALENT_COLUMNS]
    )

    def count(frame: pd.DataFrame) -> pd.Series:
        sizes = frame.groupby("tmdb_id").size()
        return ids.map(sizes).fillna(0).astype("int64")

    counts = pd.DataFrame(
        {
            "tmdb_id": ids,
            "n_cast": count(cast), "n_crew": count(crew),
            "n_directors": count(directors), "n_lead_actors": count(leads),
        }
    )
    return counts, talent


# --- joins, proven ------------------------------------------------------------------

def prove_join(left, right, on, how, validate, name):
    """Merge with validate= and indicator=True; return (merged, one report row)."""
    try:
        merged = pd.merge(left, right, on=on, how=how, validate=validate, indicator=True)
    except pd.errors.MergeError as exc:
        raise PipelineStopError(f"Join {name} failed its {validate} check: {exc}") from exc
    status = merged["_merge"]
    left_only = merged.loc[status == "left_only", on]
    right_only = merged.loc[status == "right_only", on]
    unmatched = pd.concat([left_only, right_only]).astype(str).head(20)
    report = {
        "join": name,
        "left_rows": len(left),
        "right_rows": len(right),
        "left_key_unique": bool(left[on].is_unique),
        "right_key_unique": bool(right[on].is_unique),
        "result_rows": len(merged),
        "both": int((status == "both").sum()),
        "left_only": len(left_only),
        "right_only": len(right_only),
        "validate": validate,
        "rows_changed": len(merged) != len(left),
        "unmatched_keys": ",".join(unmatched),
    }
    return merged.drop(columns="_merge"), report


def build_analysis_tables(fetched_ids, films, credit_counts, talent):
    """Join fetched ids, films and credit counts; prove talent attaches without fan-out."""
    base = fetched_ids[["tmdb_id", "first_line_number"]]
    step1, r1 = prove_join(base, films, "tmdb_id", "left", "one_to_one", "1 fetched_ids-films")
    films_out, r2 = prove_join(
        step1, credit_counts, "tmdb_id", "left", "one_to_one", "2 films-credit_counts"
    )
    films_out = films_out[FILM_COLUMNS]
    _, r3 = prove_join(
        talent, films_out[["tmdb_id"]], "tmdb_id", "left", "many_to_one", "3 talent-films"
    )
    return films_out, talent, pd.DataFrame([r1, r2, r3])


@dataclass
class FlattenRun:
    films: pd.DataFrame
    talent: pd.DataFrame
    join_report: pd.DataFrame
    quarantine: pd.DataFrame
    fetched_ids: pd.DataFrame  # the ids given to this stage
    credits_ids: list


def flatten_stage(fetched_ids: pd.DataFrame, run_at: str | None = None) -> FlattenRun:
    """Stage 3 end to end, from saved responses to the analysis tables."""
    details_list, credits_list, quarantine = read_saved_responses(fetched_ids, run_at)
    readable = fetched_ids[~fetched_ids["tmdb_id"].astype(str).isin(quarantine["raw_value"])]
    films = flatten_details(details_list)
    credit_counts, talent = flatten_credits(credits_list)
    films_out, talent_out, join_report = build_analysis_tables(
        readable.sort_values("first_line_number"), films, credit_counts, talent
    )
    return FlattenRun(
        films_out, talent_out, join_report, quarantine, fetched_ids,
        credits_ids=credit_counts["tmdb_id"].tolist(),
    )


def imdb_crossref(films: pd.DataFrame, load_quarantine: pd.DataFrame) -> pd.DataFrame:
    """Quarantined IMDb ids, and the fetched film (if any) that carries each one."""
    q = load_quarantine[load_quarantine["reason_code"] == "imdb_id_not_tmdb"]
    wanted = pd.DataFrame({"imdb_id": q["raw_value"].astype(str).str.strip().str.lower()})
    have = films[["tmdb_id", "title", "imdb_id"]].assign(
        imdb_id=films["imdb_id"].astype("string").str.strip().str.lower()
    )
    return wanted.merge(have, on="imdb_id", how="left")
