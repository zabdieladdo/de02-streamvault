"""Stage 5: group measures. Fixtures are small enough to check by hand."""
import pandas as pd
import pytest

from pipeline import clean, config, metrics
from tests.conftest import make_films


def kpis_for(rows, window="all years"):
    return metrics.group_kpis(clean.add_flags(make_films(rows)), window).set_index("group")


def money(roi):
    return {"budget": 1_000_000, "revenue": int(roi * 1_000_000)}


def test_leave_one_out_median_and_top_film():
    k = kpis_for([{"title": f"F{r}", "franchise": True, **money(r)} for r in (1, 2, 3, 100)])
    row = k.loc["franchise"]
    assert row["median_roi"] == 2.5
    assert row["median_roi_without_top"] == 2.0
    assert row["shift_without_top"] == -0.5
    assert row["top_film_title"] == "F100" and row["top_film_roi"] == 100
    assert row["mean_roi"] == pytest.approx(26.5)


def test_single_usable_film_has_no_leave_one_out_median():
    k = kpis_for([{"franchise": True, **money(3)}])
    assert pd.isna(k.loc["franchise", "median_roi_without_top"])


def test_aggregate_is_total_over_total():
    rows = [
        {"franchise": True, "budget": 1_000_000, "revenue": 4_000_000},
        {"franchise": True, "budget": 3_000_000, "revenue": 4_000_000},
    ]
    k = kpis_for(rows)
    assert k.loc["franchise", "aggregate_roi"] == 2.0  # 8M / 4M, not the mean of 4 and 1.33


def test_both_groups_present_when_standalones_have_null_collection():
    rows = [{"franchise": True, **money(2)}, {"franchise": False, **money(4)}, {"franchise": False, **money(6)}]
    k = kpis_for(rows)
    assert list(k.index) == ["franchise", "standalone"]
    assert k["n_films"].sum() == 3 and k.loc["standalone", "n_films"] == 2


def test_empty_group_still_has_a_row():
    k = kpis_for([{"franchise": True, **money(2)}])
    assert k.loc["standalone", "n_films"] == 0 and k.loc["standalone", "n_roi_usable"] == 0
    assert not k.loc["standalone", "meets_min_group"]


def test_unusable_films_count_in_n_films_not_in_usable():
    k = kpis_for([{"franchise": False, **money(2)}, {"franchise": False, "budget": 0}])
    row = k.loc["standalone"]
    assert row["n_films"] == 2 and row["n_roi_usable"] == 1 and row["median_roi"] == 2


def test_votes_use_every_film_in_the_group():
    k = kpis_for([{"votes": 10, "budget": 0}, {"votes": 30, **money(2)}, {"votes": 80, **money(2)}])
    assert k.loc["standalone", "median_vote_count"] == 30


def test_min_group_size_flag():
    four = [{"franchise": False, **money(2)} for _ in range(4)]
    assert not kpis_for(four).loc["standalone", "meets_min_group"]
    assert kpis_for(four + [{"franchise": False, **money(2)}]).loc["standalone", "meets_min_group"]


def test_same_function_serves_both_windows(monkeypatch):
    films = clean.add_flags(make_films([
        {"year": 1995, "franchise": True, **money(2)}, {"year": 2005, "franchise": True, **money(4)},
    ]))
    a = metrics.group_kpis(films, "all years")
    b = metrics.group_kpis(films[films["in_window_2000"]], "2000 onward")
    assert a.loc[0, "n_films"] == 2 and b.loc[0, "n_films"] == 1
    assert a.loc[0, "window"] == "all years" and b.loc[0, "window"] == "2000 onward"
    monkeypatch.setattr(config, "MIN_GROUP_FOR_CONCLUSION", 1)  # one change reaches both outputs
    assert metrics.group_kpis(films, "x").loc[0, "meets_min_group"]
    assert metrics.group_kpis(films[films["in_window_2000"]], "y").loc[0, "meets_min_group"]


def windows_for(rows):
    films = clean.add_flags(make_films(rows))
    a = metrics.group_kpis(films, "all years")
    b = metrics.group_kpis(films[films["in_window_2000"]], "2000 onward")
    return films, a, b


DISAGREE = [  # franchise leads on all years, standalone leads from 2000
    {"year": 1990, "franchise": True, **money(10)}, {"year": 1991, "franchise": True, **money(10)},
    {"year": 2005, "franchise": True, **money(2)},
    {"year": 2006, "franchise": False, **money(5)},
]


def test_disagreement_is_detected():
    _, a, b = windows_for(DISAGREE)
    cmp = metrics.compare_windows(a, b)
    row = cmp.set_index("measure").loc["median_roi"]
    assert row["leader_all_years"] == "franchise" and row["leader_2000_onward"] == "standalone"
    assert not row["agree"]
    assert "median_roi" in metrics.disagreeing_measures(cmp)
    assert row["gap_all_years"] == 5 and row["gap_2000_onward"] == -3


def test_agreement():
    _, a, b = windows_for([{"year": 2005, "franchise": True, **money(9)}, {"year": 2006, **money(2)}])
    cmp = metrics.compare_windows(a, b)
    assert cmp["agree"].all() and metrics.disagreeing_measures(cmp) == []
    assert list(cmp["measure"]) == list(metrics.MEASURES)


def test_incomparable_window_is_not_agreement():
    _, a, b = windows_for([{"year": 1990, "franchise": True, **money(9)}, {"year": 1991, **money(2)}])
    row = metrics.compare_windows(a, b).set_index("measure").loc["median_roi"]
    assert row["leader_2000_onward"] == "" and not row["agree"]


def test_measure_checks_pass_on_good_input():
    from pipeline import checks
    films, a, b = windows_for(DISAGREE)
    report = checks.check_measure_stage(a, b, films, kpis_rerun=pd.concat([a, b], ignore_index=True))
    assert report["passed"].all()
    assert list(report["check_id"]) == ["C-21", "C-22", "C-23", "C-24", "C-25"]


def test_measure_checks_catch_a_dropped_group_and_a_difference():
    from pipeline import checks
    films, a, b = windows_for(DISAGREE)
    r = checks.check_measure_stage(a.iloc[:1], b, films).set_index("check_id")
    assert not r.loc["C-22", "passed"]
    changed = pd.concat([a, b], ignore_index=True).assign(n_films=99)
    r2 = checks.check_measure_stage(a, b, films, kpis_rerun=changed).set_index("check_id")
    assert not r2.loc["C-25", "passed"]


# --- decision impact ----------------------------------------------------------------

def quarantine_frame(repeats=(), not_found=0):
    rows = [{"stage": "load", "reason_code": "repeat", "raw_value": str(i)} for i in repeats]
    rows += [{"stage": "fetch", "reason_code": "not_found_on_api", "raw_value": "9"}] * not_found
    return pd.DataFrame(rows, columns=["stage", "reason_code", "raw_value"])


NO_I01 = pd.DataFrame({"imdb_id": [], "tmdb_id": [], "title": []})


def impact(rows, quarantine=None, i01=None):
    films = clean.add_flags(make_films(rows))
    return metrics.decision_impact(
        films, quarantine_frame() if quarantine is None else quarantine, NO_I01 if i01 is None else i01
    )


def pick(table, decision, variant=None, window="all years"):
    m = table["decision"].str.startswith(decision) & (table["window"] == window)
    if variant is not None:
        m &= table["variant"] == variant
    out = table[m]
    assert len(out) == 1, (decision, variant, window, len(out))
    return out.iloc[0]


GROUP = (
    [{"franchise": True, **money(r)} for r in (2, 3, 4, 5, 6)]
    + [{"franchise": False, **money(r)} for r in (1, 2, 3, 4, 5)]
)


def test_every_decision_has_a_row_for_both_windows():
    t = impact(GROUP)
    assert list(t.columns) == metrics.IMPACT_COLUMNS
    assert set(t["window"]) == {"all years", "2000 onward"}
    for _, part in t.groupby(["decision", "variant"]):
        assert sorted(part["window"]) == ["2000 onward", "all years"]


def test_decisions_that_affect_nothing_keep_their_row():
    t = impact(GROUP)
    for d in ("zero money", "unreleased excluded", "likely units errors"):
        assert pick(t, d)["films_affected"] == 0
        assert pick(t, d, window="2000 onward")["films_affected"] == 0
    assert pick(t, "baseline")["leader_changes"] == False


def test_repeats_kept_adds_one_row_per_repeat():
    rows = [{"tmdb_id": 1, "franchise": True, **money(2)}, {"tmdb_id": 2, "franchise": True, **money(30)},
            {"tmdb_id": 3, "franchise": False, **money(5)}]
    t = impact(rows, quarantine_frame(repeats=[2, 2]))
    base, kept = pick(t, "baseline"), pick(t, "repeats removed")
    assert kept["films_affected"] == 2
    assert kept["franchise_n"] == base["franchise_n"] + 2
    assert base["franchise_median_roi"] == 16 and kept["franchise_median_roi"] == 30  # medians recomputed


def test_repeats_include_the_imdb_match():
    rows = [{"tmdb_id": 1, **money(2)}, {"tmdb_id": 2, **money(4)}]
    i01 = pd.DataFrame({"imdb_id": ["tt1"], "tmdb_id": [2], "title": ["Film 2"]})
    t = impact(rows, quarantine_frame(repeats=[1]), i01)
    assert pick(t, "repeats removed")["films_affected"] == 2


def test_not_found_ids_have_no_data_and_do_not_move_medians():
    t = impact(GROUP, quarantine_frame(not_found=5))
    base, nf = pick(t, "baseline"), pick(t, "not-found")
    assert nf["films_affected"] == 5 and nf["variant"] == "no data to include"
    assert nf["franchise_median_roi"] == base["franchise_median_roi"]
    assert nf["standalone_median_roi"] == base["standalone_median_roi"]


def test_zero_revenue_allowed_gives_multiple_zero_but_zero_budget_stays_out():
    rows = GROUP + [{"franchise": False, "revenue": 0}, {"franchise": False, "budget": 0}]
    z = pick(impact(rows), "zero money")
    assert z["films_affected"] == 2
    assert z["standalone_n"] == 6  # the zero-revenue film joins; the zero-budget film cannot
    assert z["standalone_median_roi"] == 2.5  # [0, 1, 2, 3, 4, 5]


def test_unreleased_and_units_variants_recompute():
    rows = GROUP + [{"franchise": False, "status": "Rumored", **money(100)},
                    {"franchise": False, "budget": 63, "revenue": 6_300, "votes": 9999}]
    t = impact(rows)
    assert pick(t, "unreleased")["films_affected"] == 1 and pick(t, "unreleased")["standalone_n"] == 6
    assert pick(t, "likely units")["films_affected"] == 1 and pick(t, "likely units")["standalone_n"] == 6


def test_leader_change_is_reported_against_the_baseline():
    rows = [{"franchise": True, **money(r)} for r in (5, 6, 7, 8, 9)] + \
           [{"franchise": False, **money(r)} for r in (1, 2, 3, 4, 5)] + \
           [{"franchise": False, "status": "Rumored", **money(500)} for _ in range(6)]
    row = pick(impact(rows), "unreleased")
    assert pick(impact(rows), "baseline")["leader"] == "franchise"
    assert row["leader"] == "standalone" and row["leader_changes"]


def test_outlier_variant_removes_the_top_film_of_each_group():
    rows = [{"franchise": True, **money(r)} for r in (1, 2, 3, 100, 101)] + \
           [{"franchise": False, **money(r)} for r in (1, 2, 3, 4, 5, 6)]
    o = pick(impact(rows), "outlier")
    assert o["films_affected"] == 2 and o["franchise_n"] == 4 and o["standalone_n"] == 5
    assert o["franchise_median_roi"] == 2.5 and o["standalone_median_roi"] == 3


def test_minimum_group_size_blanks_the_leader():
    rows = [{"franchise": True, **money(r)} for r in (5, 6, 7, 8, 9)] + \
           [{"franchise": False, **money(r)} for r in (1, 2, 3, 4)]  # only 4 standalone
    t = impact(rows)
    assert pick(t, "minimum group", "5")["leader"] == ""
    assert pick(t, "minimum group", "5")["films_affected"] == 1  # one group below 5
    assert pick(t, "minimum group", "3")["leader"] == "franchise"
    assert pick(t, "minimum group", "none")["films_affected"] == 0
    assert pick(t, "baseline")["leader"] == ""


def test_decision_impact_does_not_change_its_inputs():
    films = clean.add_flags(make_films(GROUP))
    before = films.copy()
    metrics.decision_impact(films, quarantine_frame(repeats=[1]), NO_I01)
    pd.testing.assert_frame_equal(films, before)


def test_duplicated_film_id_stops_the_decision_impact_cleanly():
    from pipeline.errors import PipelineStopError

    films = clean.add_flags(make_films(GROUP))
    doubled = pd.concat([films, films.iloc[[0, 1]]], ignore_index=True)
    with pytest.raises(PipelineStopError, match="C-10 failed") as caught:
        metrics.decision_impact(doubled, quarantine_frame(repeats=[1]), NO_I01)
    assert caught.value.check_id == "C-10"
    assert "1, 2" in str(caught.value) and "one row per film" in str(caught.value)


def test_unique_film_ids_still_build_the_decision_impact():
    films = clean.add_flags(make_films(GROUP))
    assert len(metrics.decision_impact(films, quarantine_frame(), NO_I01)) == 20
