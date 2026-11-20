"""Stage 7: write the result tables to out/."""
import json

import pandas as pd

from pipeline import config
from pipeline.fetch import REASON_DETAIL as FETCH_REASON_DETAIL
from pipeline.fetch import REASON_ORDER as FETCH_REASON_ORDER
from pipeline.transform import FLATTEN_REASON_DETAIL, FLATTEN_REASON_ORDER
from pipeline.validate import REASON_DETAIL, REASON_ORDER


def build_reconciliation(
    rows_raw: int,
    ids_to_fetch: pd.DataFrame,
    quarantine: pd.DataFrame,
    fetched_ids: pd.DataFrame | None = None,
    ids_processed: int | None = None,
    limit: int | None = None,
    films_out: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Raw count, one row per quarantine reason, then the count sent to each next stage.

    Without `fetched_ids` it stops at "Sent to the API stage" (stage 1 only).
    """
    records = [{"stage": "Raw rows in file", "rows": rows_raw, "delta": pd.NA, "reason": ""}]

    def add_reasons(frame: pd.DataFrame, remaining: int, order: list, detail: dict) -> int:
        counts = frame["reason_code"].value_counts()
        codes = [c for c in order if c in counts.index]
        codes += [c for c in counts.index if c not in order]
        for code in codes:
            n = int(counts[code])
            remaining -= n
            records.append(
                {
                    "stage": f"Quarantined: {code}",
                    "rows": remaining,
                    "delta": -n,
                    "reason": detail.get(code, code),
                }
            )
        return remaining

    add_reasons(quarantine[quarantine["stage"] == "load"], rows_raw, REASON_ORDER, REASON_DETAIL)
    records.append(
        {"stage": "Sent to the API stage", "rows": len(ids_to_fetch), "delta": pd.NA, "reason": ""}
    )

    if fetched_ids is not None:
        remaining = len(ids_to_fetch)
        if ids_processed is not None and ids_processed < len(ids_to_fetch):
            skipped = len(ids_to_fetch) - ids_processed
            remaining -= skipped
            records.append(
                {
                    "stage": "Not processed (limited run)",
                    "rows": remaining,
                    "delta": -skipped,
                    "reason": f"--limit {limit}",
                }
            )
        add_reasons(
            quarantine[quarantine["stage"] == "fetch"],
            remaining,
            FETCH_REASON_ORDER,
            FETCH_REASON_DETAIL,
        )
        records.append(
            {
                "stage": "Fetched with details and credits",
                "rows": len(fetched_ids),
                "delta": pd.NA,
                "reason": "",
            }
        )
        if films_out is not None:
            add_reasons(
                quarantine[quarantine["stage"] == "flatten"],
                len(fetched_ids),
                FLATTEN_REASON_ORDER,
                FLATTEN_REASON_DETAIL,
            )
            records.append(
                {
                    "stage": "In the analysis table (one row per film)",
                    "rows": len(films_out),
                    "delta": pd.NA,
                    "reason": "",
                }
            )

    out = pd.DataFrame(records)
    out["rows"] = out["rows"].astype("int64")
    out["delta"] = out["delta"].astype("Int64")
    return out


def build_fetched_ids(ids_processed: pd.DataFrame, results: pd.DataFrame, quarantine: pd.DataFrame) -> pd.DataFrame:
    """One row per id that went forward, with where each response came from."""
    cols = [
        "tmdb_id", "first_line_number", "details_source", "credits_source",
        "details_attempts", "credits_attempts", "details_fetched_at", "credits_fetched_at",
    ]
    quarantined = set(quarantine.loc[quarantine["stage"] == "fetch", "raw_value"].astype(int))
    forward = ids_processed[~ids_processed["tmdb_id"].isin(quarantined)][["tmdb_id", "first_line_number"]]

    def side(endpoint):
        part = results[results["endpoint"] == endpoint].set_index("tmdb_id")
        return pd.DataFrame(
            {
                f"{endpoint}_source": part["source"],
                f"{endpoint}_attempts": part["attempts"],
                f"{endpoint}_fetched_at": part["fetched_at"],
            }
        )

    out = forward.set_index("tmdb_id").join(side("details")).join(side("credits")).reset_index()
    return out[cols].sort_values("first_line_number").reset_index(drop=True)


def write_stage1_outputs(
    ids_to_fetch: pd.DataFrame,
    quarantine: pd.DataFrame,
    reconciliation: pd.DataFrame,
    checks: pd.DataFrame,
    out_dir=None,
) -> None:
    """Write the four stage 1 CSVs to out_dir, default OUT_DIR (UTF-8, no index)."""
    out_dir = out_dir or config.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "ids_to_fetch.csv": ids_to_fetch,
        "quarantine.csv": quarantine,
        "reconciliation.csv": reconciliation,
        "checks_report.csv": checks,
    }
    for name, table in tables.items():
        table.to_csv(out_dir / name, index=False, encoding="utf-8")


def append_run_log(record: dict) -> None:
    """Append one JSON line to out/run_log.jsonl."""
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.OUT_DIR / "run_log.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_fetch_outputs(
    fetched_ids: pd.DataFrame,
    quarantine: pd.DataFrame,
    reconciliation: pd.DataFrame,
    checks: pd.DataFrame,
    out_dir=None,
) -> None:
    """Rewrite the shared tables with the fetch stage added, and write fetched_ids.csv."""
    out_dir = out_dir or config.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "fetched_ids.csv": fetched_ids,
        "quarantine.csv": quarantine,
        "reconciliation.csv": reconciliation,
        "checks_report.csv": checks,
    }
    for name, table in tables.items():
        table.to_csv(out_dir / name, index=False, encoding="utf-8")


# --- stage 3 outputs -------------------------------------------------------------

STRING_COLUMNS = [
    "imdb_id", "title", "original_title", "status", "original_language",
    "collection_name", "primary_genre", "genres_all",
]
FILMS_DTYPES = {
    "tmdb_id": "int64", "first_line_number": "int64",
    **{c: "string" for c in STRING_COLUMNS},
    "release_date_raw": "string",
    "release_date_unparseable": "bool", "release_year": "Int64",
    "runtime": "Int64", "budget": "Int64", "revenue": "Int64", "vote_count": "Int64",
    "vote_average": "float64", "popularity": "float64",
    "adult": "boolean", "video": "boolean",
    "collection_id": "Int64", "is_franchise": "bool",
    "n_genres": "Int64", "n_production_companies": "Int64",
    "n_cast": "int64", "n_crew": "int64", "n_directors": "int64", "n_lead_actors": "int64",
}
TALENT_DTYPES = {
    "tmdb_id": "int64", "person_id": "int64", "name": "string", "role": "string",
    "billing_rank": "Int64", "cast_order": "Int64",
}


def _read(path, dtypes: dict, keep_empty=()) -> pd.DataFrame:
    """Read a CSV with explicit types. Blank means missing, except in `keep_empty` columns.

    A CSV cannot tell an empty string from a missing value, so text columns come back as
    missing; `release_date_raw` is always text, so it keeps "".
    """
    columns = list(pd.read_csv(path, nrows=0).columns)
    na_values = {c: [""] for c in columns if c not in keep_empty}
    return pd.read_csv(
        path, dtype={c: t for c, t in dtypes.items() if c in columns},
        keep_default_na=False, na_values=na_values, encoding="utf-8",
    )


def read_films(path) -> pd.DataFrame:
    df = _read(path, FILMS_DTYPES, keep_empty=("release_date_raw",))
    df["release_date"] = pd.to_datetime(df["release_date"], format="%Y-%m-%d", errors="coerce")
    return df


def read_talent(path) -> pd.DataFrame:
    return _read(path, TALENT_DTYPES)


def profile_films(films: pd.DataFrame) -> pd.DataFrame:
    """One row per column of the analysis table: the profile the findings are written from."""
    rows = []
    for col in films.columns:
        s = films[col]
        is_num = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)             and str(s.dtype) != "boolean"
        is_date = pd.api.types.is_datetime64_any_dtype(s)
        top = s.value_counts(dropna=True).head(3)
        rows.append(
            {
                "column": col,
                "dtype": str(s.dtype),
                "n_rows": len(s),
                "n_null": int(s.isna().sum()),
                "n_empty_string": int((s == "").sum()) if s.dtype == object or str(s.dtype) in ("string", "str") else "",
                "n_zero": int((s == 0).sum()) if is_num else "",
                "n_distinct": int(s.nunique(dropna=True)),
                "top_3": "; ".join(f"{v} ({n})" for v, n in top.items()),
                "min": s.min() if (is_num or is_date) and s.notna().any() else "",
                "max": s.max() if (is_num or is_date) and s.notna().any() else "",
            }
        )
    return pd.DataFrame(rows)


def write_flatten_outputs(
    films: pd.DataFrame,
    talent: pd.DataFrame,
    join_report: pd.DataFrame,
    quarantine: pd.DataFrame,
    reconciliation: pd.DataFrame,
    checks: pd.DataFrame,
    out_dir=None,
) -> None:
    """Write the stage 3 tables and rewrite the shared ones with the flatten stage added."""
    out_dir = out_dir or config.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    films.to_csv(out_dir / "films.csv", index=False, encoding="utf-8", date_format="%Y-%m-%d")
    talent.to_csv(out_dir / "talent.csv", index=False, encoding="utf-8")
    join_report.to_csv(out_dir / "join_report.csv", index=False, encoding="utf-8")
    profile_films(films).to_csv(out_dir / "films_profile.csv", index=False, encoding="utf-8",
                                date_format="%Y-%m-%d")
    quarantine.to_csv(out_dir / "quarantine.csv", index=False, encoding="utf-8")
    reconciliation.to_csv(out_dir / "reconciliation.csv", index=False, encoding="utf-8")
    checks.to_csv(out_dir / "checks_report.csv", index=False, encoding="utf-8")


# --- stages 4 and 5 outputs ------------------------------------------------------

FLAG_COLUMNS = [
    "is_released", "budget_suspect_units", "revenue_suspect_units", "units_error_likely",
    "possible_micro_budget", "budget_usable", "revenue_usable", "roi_usable", "roi_extreme",
    "in_window_2000", "sequel_like_title", "possible_same_film",
]
FILMS_CLEAN_DTYPES = {
    **FILMS_DTYPES,
    **{c: "bool" for c in FLAG_COLUMNS},
    "roi_exclusion_reason": "string", "roi": "float64", "title_year_key": "string",
}


def read_films_clean(path) -> pd.DataFrame:
    """Read films_clean.csv with explicit types. The exclusion reason keeps "" (usable films)."""
    df = _read(path, FILMS_CLEAN_DTYPES, keep_empty=("release_date_raw", "roi_exclusion_reason"))
    df["release_date"] = pd.to_datetime(df["release_date"], format="%Y-%m-%d", errors="coerce")
    return df


def add_usable_multiple_row(reconciliation: pd.DataFrame, n_usable: int) -> pd.DataFrame:
    """Append the count the measures rest on. No row leaves at stages 4 and 5; this is not a deduction."""
    row = pd.DataFrame(
        [{"stage": "Films with a usable revenue÷budget multiple", "rows": n_usable,
          "delta": pd.NA, "reason": ""}]
    )
    row = row.astype({"rows": "int64", "delta": "Int64"})
    return pd.concat([reconciliation, row], ignore_index=True)


def write_clean_outputs(films_clean, review, reconciliation, checks, out_dir=None) -> None:
    out_dir = out_dir or config.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    films_clean.to_csv(out_dir / "films_clean.csv", index=False, encoding="utf-8", date_format="%Y-%m-%d")
    review.to_csv(out_dir / "review_list.csv", index=False, encoding="utf-8")
    reconciliation.to_csv(out_dir / "reconciliation.csv", index=False, encoding="utf-8")
    checks.to_csv(out_dir / "checks_report.csv", index=False, encoding="utf-8")


def write_measure_outputs(kpis, comparison, impact, checks, out_dir=None) -> None:
    out_dir = out_dir or config.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    kpis.to_csv(out_dir / "kpis.csv", index=False, encoding="utf-8")
    comparison.to_csv(out_dir / "window_comparison.csv", index=False, encoding="utf-8")
    impact.to_csv(out_dir / "decision_impact.csv", index=False, encoding="utf-8")
    checks.to_csv(out_dir / "checks_report.csv", index=False, encoding="utf-8")


def write_rank_outputs(bundles, entry_positions, middle_summary, signal, shortlist, deal_note, differences,
                       checks, out_dir=None) -> None:
    out_dir = out_dir or config.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "bundles.csv": bundles, "entry_positions.csv": entry_positions,
        "middle_entry_test.csv": middle_summary, "talent_signal.csv": signal,
        "shortlist.csv": shortlist, "deal_note.csv": deal_note, "window_differences.csv": differences,
        "checks_report.csv": checks,
    }
    for name, table in tables.items():
        table.to_csv(out_dir / name, index=False, encoding="utf-8", date_format="%Y-%m-%d")
