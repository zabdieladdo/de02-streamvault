"""Stage 6: rank bundles, test middle entries, measure talent signal, build the shortlist."""
import numpy as np
import pandas as pd

from pipeline import config


def reference_values(films_clean: pd.DataFrame) -> dict:
    """The two list-wide medians every relative figure is measured against (all years)."""
    usable = films_clean["roi_usable"].astype(bool)
    roi = films_clean.loc[usable, "roi"].astype("float64")
    votes = films_clean["vote_count"].astype("float64")
    return {
        "list_median_roi": float(roi.median()) if len(roi) else float("nan"),
        "list_median_votes": float(votes.median()) if len(votes) else float("nan"),
        "n_usable": int(usable.sum()),
    }


BUNDLE_COLUMNS = [
    "collection_id", "collection_name", "n_on_list", "n_roi_usable", "median_roi", "mean_roi",
    "aggregate_roi", "weakest_roi", "weakest_title", "median_vote_count", "first_year", "last_year",
    "straddles_2000", "n_2000_on", "median_roi_2000_on", "thin_2000_on", "rankable", "bundle_rank",
    "vote_rank", "relative_value", "walkaway_ratio",
]


def build_bundles(films_clean: pd.DataFrame) -> pd.DataFrame:
    """One row per collection, from the franchise films on the list.

    Every figure is based on the films of the collection that are on the list; the full bundle a
    studio sells may hold more films.
    """
    ref = reference_values(films_clean)
    f = films_clean[films_clean["is_franchise"].astype(bool) & films_clean["collection_id"].notna()]
    usable = f["roi_usable"].astype(bool)
    f = f.sort_values("tmdb_id").assign(
        collection_id=lambda d: d["collection_id"].astype("int64"),
        roi_u=lambda d: d["roi"].astype("float64").where(d["roi_usable"].astype(bool)),
        rev_u=lambda d: d["revenue"].astype("float64").where(d["roi_usable"].astype(bool)),
        bud_u=lambda d: d["budget"].astype("float64").where(d["roi_usable"].astype(bool)),
        votes=lambda d: d["vote_count"].astype("float64"),
        year=lambda d: d["release_year"].astype("float64"),
    )
    g = f.groupby("collection_id")
    weakest = f[f["roi_u"].notna()]
    weakest = weakest.loc[weakest.groupby("collection_id")["roi_u"].idxmin()].set_index("collection_id")
    recent = f[f["in_window_2000"].astype(bool)].groupby("collection_id")

    b = pd.DataFrame(
        {
            "collection_name": g["collection_name"].first().astype("object"),
            "n_on_list": g.size(),
            "n_roi_usable": g["roi_usable"].sum().astype("int64"),
            "median_roi": g["roi_u"].median(),
            "mean_roi": g["roi_u"].mean(),
            "aggregate_roi": g["rev_u"].sum(min_count=1) / g["bud_u"].sum(min_count=1),
            "weakest_roi": weakest["roi_u"],
            "weakest_title": weakest["title"].astype("object"),
            "median_vote_count": g["votes"].median(),
            "first_year": g["year"].min(),
            "last_year": g["year"].max(),
            "n_2000_on": recent.size(),
            "median_roi_2000_on": recent["roi_u"].median(),
        }
    )
    b["n_2000_on"] = b["n_2000_on"].fillna(0).astype("int64")
    b["straddles_2000"] = (b["first_year"] < config.WINDOW_START_YEAR) & (b["last_year"] >= config.WINDOW_START_YEAR)
    b["thin_2000_on"] = (b["n_2000_on"] > 0) & (b["n_2000_on"] < config.MIN_BUNDLE_FOR_RANKING)
    b["rankable"] = b["n_roi_usable"] >= config.MIN_BUNDLE_FOR_RANKING

    b = b.reset_index()
    order = b[b["rankable"]].sort_values(
        ["median_roi", "median_vote_count", "collection_id"], ascending=[False, False, True]
    )
    b["bundle_rank"] = pd.Series(np.arange(1, len(order) + 1), index=order.index).reindex(b.index).astype("Int64")
    b["vote_rank"] = (
        b.loc[b["rankable"], "median_vote_count"].rank(method="min", ascending=False).reindex(b.index).astype("Int64")
    )
    b["relative_value"] = b["median_roi"] / ref["list_median_roi"]
    b["walkaway_ratio"] = b["weakest_roi"] / ref["list_median_roi"]
    b[["first_year", "last_year"]] = b[["first_year", "last_year"]].astype("Int64")
    b = b[BUNDLE_COLUMNS].sort_values(["bundle_rank", "collection_id"], na_position="last")
    return b.reset_index(drop=True)


ENTRY_COLUMNS = [
    "collection_id", "collection_name", "tmdb_id", "title", "release_date", "order_in_bundle",
    "position", "roi", "ratio_to_opener",
]
OPENER_BIAS_NOTE = (
    "Openers are selected winners: a sequel is usually made because the first film did well, "
    "so openers beating middle entries is partly built in."
)


def middle_entry_test(films_clean: pd.DataFrame, bundles: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Within each rankable bundle, compare middle entries and the latest film with the opener.

    Films are ordered by release date, then film id. The main test is the within-bundle ratio to the
    opener, with each bundle counted once; pooled medians by position are shown for display.
    """
    ids = bundles.loc[bundles["rankable"], "collection_id"].astype("int64")
    f = films_clean[films_clean["roi_usable"].astype(bool) & films_clean["collection_id"].isin(ids)]
    f = f.assign(collection_id=f["collection_id"].astype("int64"), roi=f["roi"].astype("float64"))
    f = f.sort_values(["collection_id", "release_date", "tmdb_id"]).reset_index(drop=True)
    g = f.groupby("collection_id")
    order = g.cumcount() + 1
    size = g["tmdb_id"].transform("size")
    position = np.select([order == 1, order == size], ["opener", "latest"], default="middle")
    opener_roi = g["roi"].transform("first")

    ep = pd.DataFrame(
        {
            "collection_id": f["collection_id"], "collection_name": f["collection_name"].astype("object"),
            "tmdb_id": f["tmdb_id"], "title": f["title"].astype("object"),
            "release_date": f["release_date"], "order_in_bundle": order.astype("int64"),
            "position": position, "roi": f["roi"],
            "ratio_to_opener": (f["roi"] / opener_roi).where(order > 1),
        }
    )[ENTRY_COLUMNS]

    pooled = ep.groupby("position")["roi"].median()
    middle_ratio = ep[ep["position"] == "middle"].groupby("collection_id")["ratio_to_opener"].median()
    latest_ratio = ep[ep["position"] == "latest"].groupby("collection_id")["ratio_to_opener"].median()
    n_trail = int((middle_ratio < 1).sum())
    n_tested = int(ep["collection_id"].nunique())
    rows = [
        ("bundles tested", float(n_tested), "rankable bundles (3 or more usable films)"),
        ("middle films tested", float((ep["position"] == "middle").sum()), ""),
        ("pooled median multiple: opener", pooled.get("opener", np.nan), "display only: long series weigh more here"),
        ("pooled median multiple: middle", pooled.get("middle", np.nan), "display only"),
        ("pooled median multiple: latest", pooled.get("latest", np.nan), "display only"),
        ("within-bundle median ratio, middle to opener", middle_ratio.median(),
         "main test: the median over bundles of each bundle median middle-to-opener ratio; each bundle counts once"),
        ("within-bundle median ratio, latest to opener", latest_ratio.median(),
         "median over bundles of the latest-to-opener ratio"),
        ("bundles where middle entries trail the opener", float(n_trail),
         f"{n_trail} of {n_tested} bundles have a median middle ratio below 1"),
        ("share of bundles where middle entries trail the opener",
         n_trail / n_tested if n_tested else np.nan, ""),
        ("note", np.nan, OPENER_BIAS_NOTE),
    ]
    summary = pd.DataFrame(rows, columns=["measure", "value", "note"])
    return ep, summary


SIGNAL_ORDER = [
    "reliable", "reliable negative", "mixed", "promising, too little evidence", "too little evidence",
]
SIGNAL_COLUMNS = [
    "role", "person_id", "name", "n_films", "n_titles", "titles_above", "hit_rate", "median_title_roi",
    "n_units", "vote_titles_above", "vote_hit_rate", "largest_unit_films", "signal",
]


def _hit_rate_fraction() -> tuple[int, int]:
    """RELIABLE_HIT_RATE as whole numbers (2/3 gives 2 and 3) so comparisons need no float rounding."""
    from fractions import Fraction

    frac = Fraction(config.RELIABLE_HIT_RATE).limit_denominator(1000)
    return frac.numerator, frac.denominator


def talent_join_rows(talent: pd.DataFrame, films_clean: pd.DataFrame) -> tuple[int, bool]:
    """Rows after joining talent to films on film id, and whether the film key is unique (C-29)."""
    joined = talent[["tmdb_id"]].merge(films_clean[["tmdb_id"]], on="tmdb_id", how="left")
    return len(joined), bool(films_clean["tmdb_id"].is_unique)


def talent_signal(
    talent: pd.DataFrame, films_clean: pd.DataFrame, list_median_roi: float, list_median_votes: float
) -> pd.DataFrame:
    """One row per person and role: how often their independent titles beat the list median multiple.

    Titles are counted once per person: all of a person's films in one collection are one title.
    Directors and lead actors are separate rows.
    """
    # A repeated film id would multiply talent rows; it is dropped here and reported by C-29.
    films = films_clean[
        ["tmdb_id", "roi", "roi_usable", "vote_count", "is_franchise", "collection_id"]
    ].drop_duplicates("tmdb_id")
    j = talent.merge(films, on="tmdb_id", how="left", validate="many_to_one")

    in_collection = j["is_franchise"].fillna(False).astype(bool) & j["collection_id"].notna()
    j["title_unit"] = ("film:" + j["tmdb_id"].astype("string")).where(
        ~in_collection, "collection:" + j["collection_id"].astype("string")
    )
    j["roi_u"] = j["roi"].astype("float64").where(j["roi_usable"].fillna(False).astype(bool))
    j["votes"] = j["vote_count"].astype("float64")

    units = j.groupby(["person_id", "role", "title_unit"], as_index=False).agg(
        name=("name", "first"), unit_roi=("roi_u", "median"), unit_votes=("votes", "median"),
        unit_films=("tmdb_id", "size"),
    )
    units["above"] = units["unit_roi"] > list_median_roi
    units["vote_above"] = units["unit_votes"] > list_median_votes

    p = units.groupby(["person_id", "role"], as_index=False).agg(
        name=("name", "first"), n_films=("unit_films", "sum"), n_titles=("unit_roi", "count"),
        titles_above=("above", "sum"), median_title_roi=("unit_roi", "median"),
        n_units=("title_unit", "size"), vote_titles_above=("vote_above", "sum"),
        largest_unit_films=("unit_films", "max"),
    )
    p[["n_films", "n_titles", "titles_above", "n_units", "vote_titles_above", "largest_unit_films"]] = p[
        ["n_films", "n_titles", "titles_above", "n_units", "vote_titles_above", "largest_unit_films"]
    ].astype("int64")
    p["hit_rate"] = (p["titles_above"] / p["n_titles"]).where(p["n_titles"] > 0)
    p["vote_hit_rate"] = p["vote_titles_above"] / p["n_units"]

    num, den = _hit_rate_fraction()
    enough = p["n_titles"] >= config.RELIABLE_MIN_TITLES
    reliable = enough & (p["titles_above"] * den >= p["n_titles"] * num)
    negative = enough & (p["titles_above"] * den <= p["n_titles"] * (den - num))
    promising = (p["n_titles"] == 2) & (p["titles_above"] == 2)
    p["signal"] = np.select(
        [reliable, negative, enough, promising],
        ["reliable", "reliable negative", "mixed", "promising, too little evidence"],
        default="too little evidence",
    )
    p["_order"] = p["signal"].map({name: i for i, name in enumerate(SIGNAL_ORDER)})
    p = p.sort_values(
        ["role", "_order", "hit_rate", "n_titles", "median_title_roi", "person_id"],
        ascending=[True, True, False, False, False, True],
    )
    return p[SIGNAL_COLUMNS].reset_index(drop=True)


SHORTLIST_COLUMNS = [
    "list", "rank", "name", "collection_id", "tmdb_id", "multiple", "rank_by_multiple",
    "vote_count_or_median", "vote_rank", "release_years", "figure_2000_on", "n_on_list", "weakest", "reason",
]


def _ordinal(n: pd.Series) -> pd.Series:
    """1 -> 1st, 2 -> 2nd, 11 -> 11th, 22 -> 22nd, built without a loop."""
    n = n.astype("int64")
    last_two = n % 100
    suffix = np.select(
        [(last_two >= 11) & (last_two <= 13), n % 10 == 1, n % 10 == 2, n % 10 == 3],
        ["th", "st", "nd", "rd"], default="th",
    )
    return n.astype(str) + suffix


def _times(x: pd.Series) -> pd.Series:
    """A multiple to one decimal place with the times sign: 7.1×."""
    return x.astype("float64").round(1).astype(str) + "×"


def _thousands(n: pd.Series) -> pd.Series:
    return n.astype("int64").astype(str).str.replace(r"\B(?=(\d{3})+(?!\d))", ",", regex=True)


def _years(first: pd.Series, last: pd.Series) -> pd.Series:
    a, b = first.astype("string"), last.astype("string")
    return a.where(first == last, a + "-" + b)


def build_shortlist(bundles: pd.DataFrame, films_clean: pd.DataFrame) -> pd.DataFrame:
    """Top bundles, top standalones and one audience pick, each with a plain-sentence reason."""
    parts = []

    # franchise: rankable bundles, best median multiple first
    n_rankable = int(bundles["rankable"].sum())
    fr = bundles[bundles["rankable"] & (bundles["bundle_rank"] <= config.SHORTLIST_FRANCHISE_N)]
    fr = fr.sort_values("bundle_rank")
    recent = fr["median_roi_2000_on"]
    recent_text = np.where(
        recent.notna(), _times(recent.fillna(0)) + " from 2000 onward", "no films from 2000 onward"
    )
    parts.append(
        pd.DataFrame(
            {
                "list": "franchise", "rank": np.arange(1, len(fr) + 1), "name": fr["collection_name"],
                "collection_id": fr["collection_id"], "tmdb_id": pd.array([pd.NA] * len(fr), dtype="Int64"),
                "multiple": fr["median_roi"], "rank_by_multiple": fr["bundle_rank"],
                "vote_count_or_median": fr["median_vote_count"], "vote_rank": fr["vote_rank"],
                "release_years": _years(fr["first_year"], fr["last_year"]),
                "figure_2000_on": recent.astype("object").where(recent.notna(), "pre-2000"),
                "n_on_list": fr["n_on_list"],
                "weakest": fr["weakest_title"] + " " + _times(fr["weakest_roi"]),
                "reason": (
                    "Median " + _times(fr["median_roi"]) + " across " + fr["n_on_list"].astype(str)
                    + " films on the list (" + _ordinal(fr["bundle_rank"]) + " of " + str(n_rankable)
                    + " rankable bundles); weakest film " + fr["weakest_title"] + " at "
                    + _times(fr["weakest_roi"]) + "; " + pd.Series(recent_text, index=fr.index) + "; "
                    + _ordinal(fr["vote_rank"]) + " by audience votes."
                ),
            }
        )
    )

    # standalones: usable films, best multiple first (ties: more votes, then film id)
    s = films_clean[~films_clean["is_franchise"].astype(bool) & films_clean["roi_usable"].astype(bool)].copy()
    s["roi"] = s["roi"].astype("float64")
    s["votes"] = s["vote_count"].astype("float64")
    s = s.sort_values(["roi", "votes", "tmdb_id"], ascending=[False, False, True]).reset_index(drop=True)
    n_stand = len(s)
    s["rank_by_multiple"] = np.arange(1, n_stand + 1)
    s["vote_rank"] = s["votes"].rank(method="min", ascending=False)
    s["release_years"] = s["release_year"].astype("string")
    s["pre2000"] = ~s["in_window_2000"].astype(bool)
    s["figure_2000_on"] = s["roi"].astype("object").where(~s["pre2000"], "pre-2000")

    def standalone_rows(rows: pd.DataFrame, list_name: str, reason: pd.Series) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "list": list_name, "rank": np.arange(1, len(rows) + 1), "name": rows["title"],
                "collection_id": pd.array([pd.NA] * len(rows), dtype="Int64"), "tmdb_id": rows["tmdb_id"],
                "multiple": rows["roi"], "rank_by_multiple": rows["rank_by_multiple"],
                "vote_count_or_median": rows["votes"], "vote_rank": rows["vote_rank"],
                "release_years": rows["release_years"], "figure_2000_on": rows["figure_2000_on"],
                "n_on_list": pd.array([pd.NA] * len(rows), dtype="Int64"),
                "weakest": pd.Series([pd.NA] * len(rows), index=rows.index, dtype="string"),
                "reason": reason,
            }
        )

    top = s.head(config.SHORTLIST_STANDALONE_N)
    parts.append(
        standalone_rows(
            top, "standalone",
            _times(top["roi"]) + " its budget (" + _ordinal(top["rank_by_multiple"]) + " of " + str(n_stand)
            + " standalones); released " + top["release_years"] + "; " + _ordinal(top["vote_rank"]) + " of "
            + str(n_stand) + " by audience votes.",
        )
    )

    # audience pick: the most-voted standalone that is not in the top group
    rest = s.iloc[config.SHORTLIST_STANDALONE_N:].sort_values(["votes", "tmdb_id"], ascending=[False, True]).head(1)
    top_label = "five" if config.SHORTLIST_STANDALONE_N == 5 else str(config.SHORTLIST_STANDALONE_N)
    parts.append(
        standalone_rows(
            rest, "audience pick",
            "Most-voted standalone not in the top " + top_label + ": " + _thousands(rest["votes"]) + " votes ("
            + _ordinal(rest["vote_rank"]) + " of " + str(n_stand) + ") but " + _times(rest["roi"])
            + " its budget (" + _ordinal(rest["rank_by_multiple"]) + " of " + str(n_stand) + ").",
        )
    )

    out = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else None
    if out is None:
        return pd.DataFrame(columns=SHORTLIST_COLUMNS)
    out[["rank", "rank_by_multiple", "vote_rank"]] = out[["rank", "rank_by_multiple", "vote_rank"]].astype("int64")
    return out[SHORTLIST_COLUMNS]


DEAL_NOTE_COLUMNS = [
    "collection_name", "n_on_list", "release_years", "median_roi", "list_median_roi", "relative_value",
    "weakest_title", "weakest_roi", "walkaway_ratio", "median_roi_2000_on", "straddles_2000",
    "thin_2000_on", "standalone_median_roi", "relative_to_standalone", "median_vote_count", "vote_rank",
]


def deal_note_figures(bundles: pd.DataFrame, kpis: pd.DataFrame, list_median_roi: float) -> pd.DataFrame:
    """The figures for the strongest bundle, all as ratios: no price exists in the brief.

    relative_value is the bundle median multiple divided by the list median multiple (what drove the
    view); walkaway_ratio is the weakest film multiple divided by the same list median.
    """
    top = bundles[bundles["rankable"] & (bundles["bundle_rank"] == 1)].copy()
    if top.empty:
        return pd.DataFrame(columns=DEAL_NOTE_COLUMNS)
    stand = kpis[(kpis["window"] == "all years") & (kpis["group"] == "standalone")]["median_roi"]
    stand_median = float(stand.iloc[0]) if len(stand) else float("nan")
    return pd.DataFrame(
        {
            "collection_name": top["collection_name"], "n_on_list": top["n_on_list"],
            "release_years": _years(top["first_year"], top["last_year"]),
            "median_roi": top["median_roi"], "list_median_roi": list_median_roi,
            "relative_value": top["median_roi"] / list_median_roi,
            "weakest_title": top["weakest_title"], "weakest_roi": top["weakest_roi"],
            "walkaway_ratio": top["weakest_roi"] / list_median_roi,
            "median_roi_2000_on": top["median_roi_2000_on"], "straddles_2000": top["straddles_2000"],
            "thin_2000_on": top["thin_2000_on"], "standalone_median_roi": stand_median,
            "relative_to_standalone": top["median_roi"] / stand_median,
            "median_vote_count": top["median_vote_count"], "vote_rank": top["vote_rank"],
        }
    )[DEAL_NOTE_COLUMNS].reset_index(drop=True)
