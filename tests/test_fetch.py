"""Tests for the fetch stage. No network: a FakeSession returns scripted responses."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import requests

from pipeline import config, fetch
from pipeline.errors import PipelineStopError
from tests.conftest import NOT_FOUND_BODY, TEST_KEY, FakeResponse, FakeSession, ok_body

pytestmark = pytest.mark.usefixtures("fetch_env")


def make_ids(*ids):
    return pd.DataFrame(
        {
            "tmdb_id": pd.Series(ids, dtype="int64"),
            "first_line_number": range(2, len(ids) + 2),
            "n_occurrences": 1,
            "was_padded": False,
            "leading_zero_normalised": False,
            "flag_large_id": False,
        }
    )


def run(ids, session=None, key=TEST_KEY, **kw):
    return fetch.fetch_all(ids, session=session or FakeSession(), key=key, **kw)


def outcomes(r, endpoint):
    part = r.results[r.results["endpoint"] == endpoint]
    return dict(zip(part["tmdb_id"], part["outcome"]))


def assert_conserved(r):
    forward = len(r.ids_processed) - len(r.quarantine)
    assert len(r.ids_processed) == forward + len(r.quarantine)
    assert r.quarantine["raw_value"].is_unique


def read_log():
    return pd.read_csv(config.FETCH_LOG, dtype=str, keep_default_na=False)


def age_log(days, **match):
    """Make log rows matching `match` look `days` old."""
    log = read_log()
    mask = pd.Series(True, index=log.index)
    for col, val in match.items():
        mask &= log[col] == str(val)
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    log.loc[mask, "fetched_at"] = old
    log.to_csv(config.FETCH_LOG, index=False)


def test_ok_details_and_credits(fetch_env):
    r = run(make_ids(603))
    assert (config.RAW_DETAILS_DIR / "603.json").read_bytes() == ok_body(603)
    assert (config.RAW_CREDITS_DIR / "603.json").read_bytes() == ok_body(603, "credits")
    assert outcomes(r, "details") == {603: "ok"} and outcomes(r, "credits") == {603: "ok"}
    assert read_log()["outcome"].tolist() == ["ok", "ok"]
    assert "path" in read_log().columns and not read_log()["path"].str.startswith("http").any()
    assert r.quarantine.empty
    assert_conserved(r)


def test_fresh_cache_makes_no_requests():
    run(make_ids(603, 155))
    second = FakeSession()
    r = run(make_ids(603, 155), session=second)
    assert second.calls == [] and r.network_calls == 0
    assert set(r.results["outcome"]) == {"cached"}
    assert set(r.results["source"]) == {"cache"}


def test_stale_cache_is_requested_again():
    run(make_ids(603))
    age_log(181, tmdb_id=603, endpoint="details")
    second = FakeSession()
    r = run(make_ids(603), session=second)
    assert second.calls == ["/movie/603"]
    assert outcomes(r, "details") == {603: "ok"} and outcomes(r, "credits") == {603: "cached"}


def test_refresh_requests_everything_again():
    run(make_ids(603))
    second = FakeSession()
    run(make_ids(603), session=second, refresh=True)
    assert second.calls == ["/movie/603", "/movie/603/credits"]


def test_fully_cached_run_needs_no_key():
    session = FakeSession({"/movie/404": FakeResponse(404, NOT_FOUND_BODY)})
    run(make_ids(603, 404), session=session)
    third = FakeSession()
    r = run(make_ids(603, 404), session=third, key=None)
    assert third.calls == [] and r.network_calls == 0
    assert outcomes(r, "details") == {603: "cached", 404: "cached_not_found"}


def test_request_needed_without_key_stops():
    with pytest.raises(PipelineStopError, match="TMDB_API_KEY"):
        run(make_ids(603), key=None)


def test_not_found_is_remembered():
    session = FakeSession({"/movie/404": FakeResponse(404, NOT_FOUND_BODY)})
    first = run(make_ids(404), session=session)
    assert first.quarantine["reason_code"].tolist() == ["not_found_on_api"]
    second = FakeSession()
    r = run(make_ids(404), session=second)
    assert second.calls == []
    assert outcomes(r, "details") == {404: "cached_not_found"}
    assert r.quarantine["reason_code"].tolist() == ["not_found_on_api"]
    assert "could not be found" in r.quarantine["reason_detail"].iloc[0]
    assert not (config.RAW_DETAILS_DIR / "404.json").exists()
    assert read_log().query("endpoint == 'details'")["detail"].iloc[0].startswith("The resource")


def test_not_found_expires():
    session = FakeSession({"/movie/404": FakeResponse(404, NOT_FOUND_BODY)})
    run(make_ids(404), session=session)
    age_log(181, tmdb_id=404, endpoint="details")
    second = FakeSession({"/movie/404": FakeResponse(404, NOT_FOUND_BODY)})
    run(make_ids(404), session=second)
    assert second.calls == ["/movie/404"]


@pytest.mark.parametrize(
    "bad",
    [requests.ConnectionError("down"), FakeResponse(503, b"{}")],
    ids=["network_error", "failed"],
)
def test_failures_are_not_remembered(bad):
    # second id succeeds first so the first-request preflight is satisfied
    session = FakeSession({"/movie/155/credits": bad})
    first = run(make_ids(603, 155), session=session)
    assert first.quarantine["reason_code"].tolist() == ["fetch_failed"]
    second = FakeSession()
    r = run(make_ids(603, 155), session=second)
    assert second.calls == ["/movie/155/credits"]
    assert r.quarantine.empty


def test_404_details_skips_credits_and_continues():
    session = FakeSession({"/movie/404": FakeResponse(404, NOT_FOUND_BODY)})
    r = run(make_ids(603, 404, 155), session=session)
    assert "/movie/404/credits" not in session.calls
    assert outcomes(r, "credits")[404] == "skipped"
    assert r.quarantine[["raw_value", "reason_code", "stage"]].values.tolist() == [
        ["404", "not_found_on_api", "fetch"]
    ]
    assert r.quarantine["line_number"].tolist() == [3]
    assert outcomes(r, "details")[155] == "ok"
    assert_conserved(r)


def test_404_credits_only():
    session = FakeSession({"/movie/603/credits": FakeResponse(404, NOT_FOUND_BODY)})
    r = run(make_ids(603), session=session)
    assert r.quarantine["reason_code"].tolist() == ["credits_missing"]
    assert (config.RAW_DETAILS_DIR / "603.json").exists()
    assert_conserved(r)


def test_401_on_first_request_stops():
    session = FakeSession({"/movie/603": FakeResponse(401, b"{}")})
    with pytest.raises(PipelineStopError, match="401"):
        run(make_ids(603, 155), session=session)
    assert session.calls == ["/movie/603"]


def test_401_mid_run_stops_and_keeps_log():
    session = FakeSession({"/movie/155": FakeResponse(401, b"{}")})
    with pytest.raises(PipelineStopError, match="401"):
        run(make_ids(603, 155), session=session)
    log = read_log()
    assert set(log["tmdb_id"]) == {"603"} and log["outcome"].tolist() == ["ok", "ok"]


def test_three_consecutive_network_errors_stop_and_keep_log():
    err = requests.ConnectionError("boom")
    session = FakeSession(
        {
            "/movie/155": err, "/movie/155/credits": err,
            "/movie/278": err,
        }
    )
    with pytest.raises(PipelineStopError, match="Network appears down after 3"):
        run(make_ids(603, 155, 278, 550), session=session)
    log = read_log()
    assert "550" not in set(log["tmdb_id"])
    assert (log["outcome"] == "network_error").sum() == 3


def test_network_error_on_first_request_stops():
    session = FakeSession({"/movie/603": requests.ConnectionError("down")})
    with pytest.raises(PipelineStopError, match="first request"):
        run(make_ids(603, 155), session=session)
    assert session.calls == ["/movie/603"]


def test_one_network_error_then_success_continues():
    session = FakeSession({"/movie/155": requests.ConnectionError("blip")})
    r = run(make_ids(603, 155, 278), session=session)
    assert outcomes(r, "details")[155] == "network_error"
    assert outcomes(r, "details")[278] == "ok"
    assert r.quarantine["reason_code"].tolist() == ["fetch_failed"]
    assert "details: ConnectionError" in r.quarantine["reason_detail"].iloc[0]
    assert_conserved(r)


def test_failed_status_detail_has_status_and_attempts():
    session = FakeSession({"/movie/155": FakeResponse(503, b"{}", retries=5)})
    r = run(make_ids(603, 155), session=session)
    assert r.quarantine["reason_detail"].iloc[0] == "details: HTTP 503, after 6 attempts"


def test_id_mismatch():
    session = FakeSession({"/movie/603": FakeResponse(200, ok_body(999))})
    r = run(make_ids(603), session=session)
    assert r.quarantine["reason_code"].tolist() == ["id_mismatch"]
    assert "999" in r.quarantine["reason_detail"].iloc[0]
    assert not (config.RAW_DETAILS_DIR / "603.json").exists()


def test_non_json_200_is_bad_response():
    session = FakeSession({"/movie/603": FakeResponse(200, b"<html>oops</html>")})
    r = run(make_ids(603), session=session)
    assert r.quarantine["reason_code"].tolist() == ["bad_response"]
    assert not (config.RAW_DETAILS_DIR / "603.json").exists()


def test_attempts_recorded_from_retry_history():
    session = FakeSession({"/movie/603": FakeResponse(200, ok_body(603), retries=2)})
    r = run(make_ids(603), session=session)
    assert r.results.query("endpoint == 'details'")["attempts"].iloc[0] == 3


def test_key_never_leaks(fetch_env, capsys):
    url = f"{config.API_BASE}/movie/155?api_key={TEST_KEY}"
    err = requests.ConnectionError(f"HTTPSConnectionPool: Max retries exceeded with url: {url}")
    session = FakeSession({"/movie/155": err})
    r = run(make_ids(603, 155, 278), session=session)
    print(r.quarantine.to_string(), r.results.to_string())
    out = capsys.readouterr()
    assert TEST_KEY not in out.out + out.err
    for path in fetch_env.tmp_path.rglob("*"):
        if path.is_file():
            assert TEST_KEY.encode() not in path.read_bytes(), path
    assert "api_key=***" in read_log()["detail"].str.cat()


def test_redact():
    from pipeline.redact import redact

    assert redact("GET /x?api_key=abc123&y=1 failed", "abc123") == "GET /x?api_key=***&y=1 failed"
    assert "secret" not in redact("token secret here", "secret")


def test_retry_policy():
    adapter = fetch.build_session().get_adapter("https://api.themoviedb.org")
    retry = adapter.max_retries
    assert retry.total == 5
    assert 429 in retry.status_forcelist
    assert 404 not in retry.status_forcelist and 401 not in retry.status_forcelist
    assert retry.respect_retry_after_header is True
    assert fetch.build_session().headers["User-Agent"] == config.USER_AGENT


def test_rate_limiter_sleeps_between_network_requests_only(monkeypatch):
    import time

    clock = {"t": 100.0}
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        clock["t"] += s

    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(time, "sleep", fake_sleep)

    limiter = fetch.RateLimiter(4)
    limiter.wait()
    limiter.wait()
    assert sleeps == [pytest.approx(0.25)]

    sleeps.clear()
    run(make_ids(603))  # 2 network requests: one sleep
    assert len(sleeps) == 1
    sleeps.clear()
    run(make_ids(603))  # cached: no sleep
    assert sleeps == []


def test_limit_processes_first_n_ids():
    session = FakeSession()
    r = run(make_ids(603, 155, 278), session=session, limit=1)
    assert r.ids_processed["tmdb_id"].tolist() == [603]
    assert set(session.calls) == {"/movie/603", "/movie/603/credits"}
    assert r.limit == 1
    assert_conserved(r)


def test_log_keeps_rows_for_ids_not_in_this_run():
    run(make_ids(603))
    run(make_ids(155))
    assert set(read_log()["tmdb_id"]) == {"603", "155"}


def test_cache_file_without_log_entry_uses_mtime():
    run(make_ids(603))
    config.FETCH_LOG.unlink()
    second = FakeSession()
    r = run(make_ids(603), session=second)
    assert second.calls == [] and set(r.results["outcome"]) == {"cached"}
