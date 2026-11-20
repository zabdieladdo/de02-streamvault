"""Stage 5: group measures for one window at a time, window comparison, decision impact."""
import numpy as np
import pandas as pd

from pipeline import config
from pipeline.errors import PipelineStopError

GROUPS = ("franchise", "standalone")
ALL_YEARS, FROM_2000 = "all years", "2000 onward"
KPI_COLUMNS = [
    "window", "group", "n_films", "n_roi_usable", "median_roi", "mean_roi",
    "median_roi_without_top", "shift_without_top", "top_film_title", "top_film_roi",
    "aggregate_roi", "median_vote_count", "mean_vote_count", "meets_min_group",
]


def _label(films: pd.DataFrame) -> pd.Series:
    return pd.Series(np.where(films["is_franchise"].astype(bool), "franchise", "standalone"),
                     index=films.index, name="group")


def group_kpis(films_clean: pd.DataFrame, window_name: str) -> pd.DataFrame:
    """One row per group (franchise, standalone) for the films given.

    The window is chosen by the caller, who passes the films in it. The same function serves
    every window. Groups are always both present, with zero films if need be.
    """
    films = films_clean.assign(group=_label(films_clean))
    usable = films[films["roi_usable"]].assign(
        roi=lambda d: d["roi"].astype("float64"),
        revenue=lambda d: d["revenue"].astype("float64"),
        budget=lambda d: d["budget"].astype("float64"),
    )
    by_all = films.groupby("group", dropna=False)
    by_use = usable.groupby("group", dropna=False)

    # Leave one out: rank the multiples inside each group, mask rank 1, take the median of the rest.
    rank = by_use["roi"].rank(method="first", ascending=False)
    rest = usable[rank > 1].groupby("group", dropna=False)["roi"].median()
    top = usable[rank == 1].set_index("group")

    votes = films["vote_count"].astype("float64")
    kpis = pd.DataFrame(
        {
            "n_films": by_all.size(),
            "n_roi_usable": by_use.size(),
            "median_roi": by_use["roi"].median(),
            "mean_roi": by_use["roi"].mean(),
            "median_roi_without_top": rest,
            "top_film_title": top["title"].astype("object"),
            "top_film_roi": top["roi"],
            "aggregate_roi": by_use["revenue"].sum() / by_use["budget"].sum(),
            "median_vote_count": votes.groupby(films["group"]).median(),
            "mean_vote_count": votes.groupby(films["group"]).mean(),
        }
    ).reindex(list(GROUPS))
    kpis[["n_films", "n_roi_usable"]] = kpis[["n_films", "n_roi_usable"]].fillna(0).astype("int64")
    kpis["shift_without_top"] = kpis["median_roi_without_top"] - kpis["median_roi"]
    kpis["meets_min_group"] = kpis["n_roi_usable"] >= config.MIN_GROUP_FOR_CONCLUSION
    kpis.index.name = "group"
    kpis = kpis.reset_index()
    kpis.insert(0, "window", window_name)
    return kpis[KPI_COLUMNS]


def window_kpis(films_clean: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The two KPI tables, both from group_kpis: all years, and films released in 2000 or later."""
    return (
        group_kpis(films_clean, ALL_YEARS),
        group_kpis(films_clean[films_clean["in_window_2000"]], FROM_2000),
    )


MEASURES = ("median_roi", "mean_roi", "aggregate_roi", "median_vote_count")
COMPARISON_COLUMNS = [
    "measure", "leader_all_years", "leader_2000_onward", "agree", "gap_all_years", "gap_2000_onward",
]


def _leader_and_gap(kpis: pd.DataFrame, measure: str) -> tuple[str, float]:
    """Which group is higher on a measure, and franchise minus standalone. Blank if not comparable."""
    values = kpis.set_index("group")[measure].reindex(list(GROUPS))
    if values.isna().any():
        return "", float("nan")
    gap = float(values["franchise"] - values["standalone"])
    return ("tie" if gap == 0 else "franchise" if gap > 0 else "standalone"), gap


def compare_windows(kpis_all: pd.DataFrame, kpis_2000: pd.DataFrame) -> pd.DataFrame:
    """One row per measure: who leads in each window, whether they agree, and the gaps.

    `agree` is true only when both windows name the same leader; a window where the groups
    cannot be compared (a group has no usable films) does not count as agreement.
    """
    rows = []
    for measure in MEASURES:  # a short fixed list of measures
        lead_a, gap_a = _leader_and_gap(kpis_all, measure)
        lead_b, gap_b = _leader_and_gap(kpis_2000, measure)
        rows.append(
            {
                "measure": measure, "leader_all_years": lead_a, "leader_2000_onward": lead_b,
                "agree": bool(lead_a != "" and lead_a == lead_b),
                "gap_all_years": gap_a, "gap_2000_onward": gap_b,
            }
        )
    return pd.DataFrame(rows, columns=COMPARISON_COLUMNS)


def disagreeing_measures(comparison: pd.DataFrame) -> list[str]:
    """Measures where both windows have a leader and the leaders differ."""
    both = (comparison["leader_all_years"] != "") & (comparison["leader_2000_onward"] != "")
    return comparison.loc[both & ~comparison["agree"], "measure"].tolist()


def incomparable_measures(comparison: pd.DataFrame) -> list[str]:
    """Measures where a window has no leader because a group has no usable films."""
    blank = (comparison["leader_all_years"] == "") | (comparison["leader_2000_onward"] == "")
    return comparison.loc[blank, "measure"].tolist()


IMPACT_COLUMNS = [
    "decision", "variant", "window", "films_affected", "franchise_n", "franchise_median_roi",
    "standalone_n", "standalone_median_roi", "gap", "leader", "leader_changes",
]


def _windows(films: pd.DataFrame):
    """The two windows and the films in each: a fixed pair, not a loop over films."""
    return ((ALL_YEARS, films), (FROM_2000, films[films["in_window_2000"]]))


def _with_roi(films: pd.DataFrame, usable: pd.Series) -> pd.DataFrame:
    """Recompute usable and the multiple under a different rule. Budget 0 is never divided."""
    budget = films["budget"].astype("float64").fillna(0)
    revenue = films["revenue"].astype("float64").fillna(0)
    roi = (revenue / budget.where(budget > 0)).where(usable)
    return films.assign(roi_usable=usable, roi=roi)


def _impact_row(decision, variant, window, affected, kpis, min_group, baseline_leader):
    k = kpis.set_index("group")
    fr, st = k.loc["franchise"], k.loc["standalone"]
    gap = fr["median_roi"] - st["median_roi"]
    comparable = pd.notna(gap) and fr["n_roi_usable"] >= min_group and st["n_roi_usable"] >= min_group
    leader = ("tie" if gap == 0 else "franchise" if gap > 0 else "standalone") if comparable else ""
    return {
        "decision": decision, "variant": variant, "window": window,
        "films_affected": int(affected),
        "franchise_n": int(fr["n_roi_usable"]), "franchise_median_roi": fr["median_roi"],
        "standalone_n": int(st["n_roi_usable"]), "standalone_median_roi": st["median_roi"],
        "gap": gap, "leader": leader,
        "leader_changes": False if baseline_leader is None else leader != baseline_leader,
    }


def decision_impact(films_clean: pd.DataFrame, quarantine: pd.DataFrame, i01_mapping: pd.DataFrame) -> pd.DataFrame:
    """One row per decision and window: what the headline would be if the decision went the other way.

    Rows with 0 films affected stay. `leader_changes` compares with the baseline row of the same window.
    The baseline applies the minimum group size (S14), so "leader" is blank where a group is too small.
    """
    f = films_clean
    repeated = f.loc[f["tmdb_id"].duplicated(keep=False), "tmdb_id"].drop_duplicates()
    if len(repeated):  # the repeats variant joins on film id, which must name one film
        ids = ", ".join(str(i) for i in repeated.head(5))
        raise PipelineStopError(
            f"C-10 failed: film id {ids} appears more than once in the films table "
            "(C-10 requires one row per film), so the decision-impact table cannot be built",
            check_id="C-10",
        )
    budget = f["budget"].astype("float64").fillna(0)
    revenue = f["revenue"].astype("float64").fillna(0)
    released, units = f["is_released"], f["units_error_likely"]
    min_default = config.MIN_GROUP_FOR_CONCLUSION
    rows, baseline_leader = [], {}

    def add(decision, variant, frame, affected, min_group=min_default, kpis_override=None):
        """Add the rows for both windows. `frame` is the full table under this variant."""
        for window, part in _windows(frame):
            kpis = group_kpis(part, window) if kpis_override is None else kpis_override(window, part)
            n = affected(window, part) if callable(affected) else affected
            rows.append(_impact_row(decision, variant, window, n, kpis, min_group,
                                    baseline_leader.get(window)))
            if decision == "baseline":
                baseline_leader[window] = rows[-1]["leader"]

    add("baseline", "as decided", f, 0)

    # repeats removed (ADR-002): add back one extra copy for each load-stage repeat and the IMDb id match
    q = quarantine[(quarantine["stage"] == "load") & (quarantine["reason_code"] == "repeat")]
    repeat_ids = pd.to_numeric(q["raw_value"], errors="coerce")
    matched = pd.to_numeric(i01_mapping["tmdb_id"], errors="coerce") if len(i01_mapping) else pd.Series(dtype="float64")
    extra_ids = pd.concat([repeat_ids, matched]).dropna().astype("int64").rename("tmdb_id").to_frame()
    extras = extra_ids.merge(f, on="tmdb_id", how="inner", validate="many_to_one")
    kept = pd.concat([f.assign(_extra=False), extras.assign(_extra=True)], ignore_index=True)
    add("repeats removed (ADR-002)", "repeats kept", kept,
        lambda w, part: part["_extra"].sum())

    n_not_found = int((quarantine["reason_code"] == "not_found_on_api").sum())
    add("not-found ids excluded (ADR-008)", "no data to include", f, n_not_found)

    ok = released & (budget > 0) & (revenue > 0) & ~units
    zero_mask = (budget == 0) | (revenue == 0)
    add("zero money = not reported (S03, S04)", "zeros treated as real",
        _with_roi(f, released & (budget > 0) & ~units).assign(_hit=zero_mask),
        lambda w, part: part["_hit"].sum())
    add("unreleased excluded (S20)", "unreleased included",
        _with_roi(f, (budget > 0) & (revenue > 0) & ~units).assign(_hit=~released),
        lambda w, part: part["_hit"].sum())
    add("likely units errors excluded (D12)", "included",
        _with_roi(f, released & (budget > 0) & (revenue > 0)).assign(_hit=units),
        lambda w, part: part["_hit"].sum())

    def without_top(window, part):
        k = group_kpis(part, window)
        return k.assign(
            median_roi=k["median_roi_without_top"],
            n_roi_usable=(k["n_roi_usable"] - 1).clip(lower=0),
        )
    add("outlier kept (D14)", "top film removed per group", f,
        lambda w, part: group_kpis(part, w)["top_film_title"].notna().sum(),
        kpis_override=without_top)

    for label, threshold in (("none", 0), ("3", config.MIN_BUNDLE_FOR_RANKING), ("5", min_default)):
        add("minimum group size (S14)", label, f,
            lambda w, part, t=threshold: (group_kpis(part, w)["n_roi_usable"] < t).sum(),
            min_group=threshold)

    return pd.DataFrame(rows, columns=IMPACT_COLUMNS)
