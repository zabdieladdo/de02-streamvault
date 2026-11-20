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
