"""Spot-check: pick the films most likely to be wrong, re-fetch them live, compare field by field.

Nothing here writes to data/raw/ or the fetch log: the saved snapshot is what is being checked,
so the check must not change it.
"""
import pandas as pd

from pipeline.transform import imdb_crossref

SLICES = (
    "heaviest_parsing", "extreme_high", "extreme_low", "cleaning_decision", "nearly_failed",
    "drives_recommendation",
)
SELECTION_COLUMNS = ["slice", "tmdb_id", "title", "detail", "stand_in"]


def _pick(frame: pd.DataFrame, column: str, ascending: bool = False) -> pd.DataFrame:
    """The one row with the largest (or smallest) value; ties go to the lowest film id."""
    ordered = frame.sort_values([column, "tmdb_id"], ascending=[ascending, True], kind="stable")
    return ordered.head(1)


def _rows(slice_name: str, films: pd.DataFrame, detail: pd.Series, stand_in: bool = False) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "slice": slice_name, "tmdb_id": films["tmdb_id"].astype("int64"),
            "title": films["title"].astype(str), "detail": detail.astype(str), "stand_in": stand_in,
        }
    )


def select_spotcheck_films(
    films_clean: pd.DataFrame,
    ids_to_fetch: pd.DataFrame,
    quarantine: pd.DataFrame,
    deal_note: pd.DataFrame,
    fetch_log: pd.DataFrame,
) -> pd.DataFrame:
    """One row per (slice, film): the films most likely to be wrong, chosen by rule from the outputs.

    The rules are computed from the data, never hard-coded, so a re-run on a new list picks its own.
    `nearly_failed` is a stand-in (stand_in True) when no request needed a retry.
    """
    f = films_clean
    parts = []

    weight = f["n_cast"] + f["n_crew"] + f["n_genres"].astype("int64")
    heavy = _pick(f.assign(weight=weight), "weight")
    parts.append(_rows("heaviest_parsing", heavy, "cast + crew + genres = " + heavy["weight"].astype(str)))

    usable = f[f["roi_usable"].astype(bool)].assign(roi=lambda d: d["roi"].astype("float64"))
    if len(usable):
        high, low = _pick(usable, "roi"), _pick(usable, "roi", ascending=True)
        parts.append(_rows("extreme_high", high, "multiple " + high["roi"].round(2).astype(str)))
        parts.append(_rows("extreme_low", low, "multiple " + low["roi"].round(2).astype(str)))

    # list entries: how many rows of the id list point at the film (repeats, plus a matched IMDb id)
    load_quarantine = quarantine[quarantine["stage"] == "load"]
    matched = imdb_crossref(f, load_quarantine).dropna(subset=["tmdb_id"])
    imdb_hits = matched["tmdb_id"].astype("int64").value_counts()
    entries = ids_to_fetch.set_index("tmdb_id")["n_occurrences"].astype("int64")
    listed = f.assign(
        list_entries=f["tmdb_id"].map(entries).fillna(0).astype("int64")
        + f["tmdb_id"].map(imdb_hits).fillna(0).astype("int64")
    )
    cleaned = _pick(listed, "list_entries")
    parts.append(_rows("cleaning_decision", cleaned, "listed " + cleaned["list_entries"].astype(str) + " times"))

    # nearly failed: the most attempts in the fetch log; with no retries, the slowest response
    log = fetch_log.assign(
        tmdb_id=pd.to_numeric(fetch_log["tmdb_id"]).astype("int64"),
        attempts=pd.to_numeric(fetch_log["attempts"]), elapsed_s=pd.to_numeric(fetch_log["elapsed_s"]),
    )
    log = log[log["tmdb_id"].isin(f["tmdb_id"])]
    if len(log):
        worst = log.sort_values(["attempts", "elapsed_s", "tmdb_id"], ascending=[False, False, True]).head(1)
        stand_in = bool(worst["attempts"].iloc[0] <= 1)
        films = f[f["tmdb_id"].isin(worst["tmdb_id"])]
        detail = (worst["endpoint"].astype(str) + ": " + worst["attempts"].astype(int).astype(str)
                  + " attempt(s), " + worst["elapsed_s"].astype(str) + " s")
        parts.append(_rows("nearly_failed", films, pd.Series(detail.to_numpy(), index=films.index), stand_in))

    # the films of the robust deal-note candidate: they drive the recommendation
    robust = deal_note[deal_note["candidate"] == "robust candidate"]
    if len(robust):
        mine = f[f["collection_id"].isin(robust["collection_id"].astype("int64"))].sort_values("tmdb_id")
        label = "robust candidate: " + str(robust["collection_name"].iloc[0])
        parts.append(_rows("drives_recommendation", mine, pd.Series(label, index=mine.index, dtype=str)))

    out = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else None
    if out is None:
        return pd.DataFrame(columns=SELECTION_COLUMNS)
    order = out["slice"].map({name: i for i, name in enumerate(SLICES)})
    out = out.assign(_order=order).sort_values(["_order", "tmdb_id"]).drop(columns="_order")
    return out.reset_index(drop=True)[SELECTION_COLUMNS]


def films_to_check(selection: pd.DataFrame) -> pd.DataFrame:
    """One row per film, with every slice it carries listed once; a film in two slices appears once."""
    if selection.empty:
        return pd.DataFrame(columns=["tmdb_id", "title", "slices", "stand_in"])
    first = selection.reset_index().groupby("tmdb_id")["index"].min()
    grouped = selection.groupby("tmdb_id").agg(
        title=("title", "first"), slices=("slice", "|".join), stand_in=("stand_in", "any"),
    )
    return grouped.assign(first=first).sort_values("first").drop(columns="first").reset_index()
