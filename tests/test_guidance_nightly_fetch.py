"""(2026-09-25) 가이던스 shadow 야간 잡의 실제 SEC 조회 배선 테스트.

요구사항(독립적으로 정한 기대값):
    - 야간 잡은 record_guidance_shadow 를 fetch_events=True 로 부르고, 티커 수 상한은 20 이하,
      소요 시간·SEC 요청 수 상한을 fetch 인자로 넘긴다.
    - SEC 403 이면 즉시 중단(남은 티커는 조회하지 않음)하고 기록·잡은 실패로 죽지 않는다.
    - 결과에 조회 티커 수·실패 수·관측 수·방향 판정 수 vs unknown 수·요청 상한이 남는다.
실제 네트워크는 쓰지 않는다(가짜 requests 세션, 가짜 티커 클라이언트).
"""

import json
from datetime import date, datetime, timezone
from decimal import Decimal

from core import guidance_event_provider as gep
from core import guidance_shadow as gs
from core.earnings_events import GuidanceChange, GuidanceItem, SecEdgarClient
from scheduler import run_scheduler

AS_OF = date(2026, 6, 10)


def _satellite_result(tickers=("AAA", "BBB", "CCC")):
    return {"as_of": AS_OF.isoformat(), "selected": list(tickers),
            "per_ticker_weights": {t: 0.03 for t in tickers}, "sizing_method": "equal", "new_orders_allowed": True}


class _Resp:
    def __init__(self, status, body=""):
        self.status_code = status
        self.content = body.encode("utf-8")
        self.headers = {}


class _ForbiddenSession:
    """모든 요청에 403 을 돌려주는 가짜 세션(SEC 차단 상황)."""

    def __init__(self):
        self.urls = []

    def get(self, url, headers=None, timeout=None):  # noqa: ARG002
        self.urls.append(url)
        return _Resp(403, "Forbidden")


class _TickerClient:
    def __init__(self):
        self.calls = []

    def resolve_cik(self, ticker):
        self.calls.append(ticker)
        return "0000000320"


def _sec_client(tmp_path, session):
    return SecEdgarClient(cache_dir=tmp_path / "sec", session=session, sleep=lambda _s: None,
                          user_agent="test-agent")


def _obs(ticker, label, reason="midpoint_comparison"):
    item = GuidanceItem(
        cik="0000000001", accession="0000000001-26-000009", acceptance_utc=datetime(2026, 6, 1, tzinfo=timezone.utc),
        source_url="https://example.test/ex99.htm", metric="revenue", basis="gaap", period_key="Q3FY2026",
        period_raw="third quarter", shape="range", low=Decimal("10"), high=Decimal("11"), unit="currency",
        currency="USD", anchor="outlook")
    return gs.GuidanceObservation(ticker, GuidanceChange(change=label, reason=reason, current=item),
                                  datetime(2026, 6, 1, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# 1. 야간 잡이 fetch_events=True 와 상한을 넘긴다
# ---------------------------------------------------------------------------
def test_nightly_job_calls_recorder_with_fetch_events_and_caps(monkeypatch, capsys):
    calls = []

    def fake_record(*args, **kwargs):
        calls.append(kwargs)
        return {"ok": True, "as_of": "2026-06-10", "n_pool": 3, "inserted": 3,
                "event_fetch_summary": gs.summarize_event_fetch(
                    {"n_tickers_requested": 3, "n_tickers_queried": 3, "n_tickers_failed": 0,
                     "n_network_requests": 12, "max_network_requests": 300},
                    {}, {"AAA": [_obs("AAA", "unknown", "no_previous_in_retrieved_history")]})}

    monkeypatch.setattr(gs, "record_guidance_shadow", fake_record)
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: True)
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda *a, **k: calls.append(("failure", a)))

    run_scheduler.guidance_shadow_record_job()

    assert len(calls) == 1
    kw = calls[0]
    assert kw["fetch_events"] is True
    assert 1 <= kw["max_tickers"] <= 20
    assert kw["fetch_kwargs"]["time_budget_seconds"] > 0
    assert kw["fetch_kwargs"]["max_network_requests"] > 0
    out = capsys.readouterr().out
    assert "SEC 가이던스 조회" in out
    assert "unknown 1" in out and "알려진 한계" in out


# ---------------------------------------------------------------------------
# 2. 403 이면 즉시 중단, 기록은 계속되고 잡은 죽지 않는다
# ---------------------------------------------------------------------------
def test_sec_403_aborts_immediately_and_recording_continues(db_session, tmp_path):
    session = _ForbiddenSession()
    ticker_client = _TickerClient()

    def fetcher(tickers, **kw):
        return gep.fetch_guidance_events(tickers, cache_dir=tmp_path / "gcache",
                                         sec_client=_sec_client(tmp_path, session), ticker_client=ticker_client, **kw)

    out = gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=_satellite_result(),
                                    fetch_events=True, max_tickers=20, event_fetcher=fetcher,
                                    fetch_kwargs=dict(gs.NIGHTLY_FETCH_KWARGS))

    assert out["ok"] is True
    summary = out["event_fetch_summary"]
    assert summary["aborted_on_access_block"] is True
    assert len(session.urls) == 1  # 첫 403 이후 SEC 를 다시 두드리지 않는다
    assert ticker_client.calls == ["AAA"]  # 뒤 티커는 조회 시도조차 하지 않는다
    assert out["event_fetch_failures"] == {"AAA": "sec_access_blocked", "BBB": "sec_access_blocked",
                                           "CCC": "sec_access_blocked"}
    assert summary["candidate_basis_counts"]["no_release"] == 3
    assert summary["sec_request_cap"] == gs.NIGHTLY_MAX_SEC_REQUESTS


def test_nightly_job_survives_sec_403(monkeypatch, db_session, tmp_path):
    session = _ForbiddenSession()
    real = gs.record_guidance_shadow

    def fetcher(tickers, **kw):
        return gep.fetch_guidance_events(tickers, cache_dir=tmp_path / "gcache",
                                         sec_client=_sec_client(tmp_path, session), ticker_client=_TickerClient(), **kw)

    def wired(*args, **kwargs):
        return real(AS_OF, session=db_session, satellite_result=_satellite_result(), event_fetcher=fetcher, **kwargs)

    failures = []
    monkeypatch.setattr(gs, "record_guidance_shadow", wired)
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: True)
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda *a, **k: failures.append(a))

    run_scheduler.guidance_shadow_record_job()  # 예외가 새면 테스트가 실패한다

    assert failures == []
    assert len(session.urls) == 1


def test_fetcher_exception_does_not_stop_recording(db_session):
    def boom(tickers, **kw):
        raise RuntimeError("unexpected")

    out = gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=_satellite_result(),
                                    fetch_events=True, event_fetcher=boom)

    assert out["ok"] is True
    assert out["n_pool"] == 3
    assert "RuntimeError" in out["event_fetch_summary"]["fetch_error"]


# ---------------------------------------------------------------------------
# 3. 요청 수·소요 시간 상한 (티커 사이 소프트 상한)
# ---------------------------------------------------------------------------
class _CountingClient:
    """request_count 만 올리는 가짜 SEC 클라이언트 자리(실제 조회는 _observations_for_ticker 를 가짜로 바꾼다)."""

    def __init__(self):
        self.request_count = 0


def test_request_budget_skips_remaining_tickers(monkeypatch, tmp_path):
    client = _CountingClient()

    def fake_obs(ticker, *, sec_client, **kw):
        sec_client.request_count += 13  # 콜드 캐시 티커 1개 분량
        return [], 6

    monkeypatch.setattr(gep, "_observations_for_ticker", fake_obs)
    res = gep.fetch_guidance_events(["A", "B", "C", "D"], as_of=AS_OF, cache_dir=tmp_path / "c",
                                    sec_client=client, ticker_client=object(), max_network_requests=20)

    statuses = [o.status for o in res.outcomes]
    assert statuses == [gep.STATUS_OK, gep.STATUS_OK, gep.STATUS_SKIPPED_BUDGET, gep.STATUS_SKIPPED_BUDGET]
    assert res.meta["stopped_on_budget"] == "request_budget_exceeded"
    assert res.meta["n_network_requests"] == 26  # 상한 20 + 티커 1개 분량 이내에서 멈춘다
    assert res.meta["max_network_requests"] == 20


def test_time_budget_skips_remaining_tickers(monkeypatch, tmp_path):
    now = {"t": 0.0}

    def fake_obs(ticker, **kw):
        now["t"] += 100.0
        return [], 1

    monkeypatch.setattr(gep, "_observations_for_ticker", fake_obs)
    res = gep.fetch_guidance_events(["A", "B", "C"], as_of=AS_OF, cache_dir=tmp_path / "c",
                                    sec_client=_CountingClient(), ticker_client=object(),
                                    time_budget_seconds=150.0, clock=lambda: now["t"])

    assert [o.status for o in res.outcomes] == [gep.STATUS_OK, gep.STATUS_OK, gep.STATUS_SKIPPED_BUDGET]
    assert res.meta["stopped_on_budget"] == "time_budget_exceeded"


def test_same_day_cache_is_reused_without_network(monkeypatch, tmp_path):
    calls = []

    def fake_obs(ticker, **kw):
        calls.append(ticker)
        return [], 2

    monkeypatch.setattr(gep, "_observations_for_ticker", fake_obs)
    kw = dict(as_of=AS_OF, cache_dir=tmp_path / "c", ticker_client=object())
    gep.fetch_guidance_events(["A", "B"], sec_client=_CountingClient(), **kw)
    second = gep.fetch_guidance_events(["A", "B"], sec_client=_CountingClient(), **kw)

    assert calls == ["A", "B"]  # 두 번째 실행은 캐시만 쓴다
    assert second.meta["n_cache_hits"] == 2
    assert second.meta["n_network_requests"] == 0


def test_nightly_caps_are_bounded():
    assert gs.NIGHTLY_MAX_TICKERS <= 20
    assert 0 < gs.NIGHTLY_MAX_SEC_REQUESTS <= 300
    assert 0 < gs.NIGHTLY_TIME_BUDGET_SECONDS <= 600


# ---------------------------------------------------------------------------
# 4. 요약: 방향 판정 수 vs unknown 수를 따로 드러낸다
# ---------------------------------------------------------------------------
def test_summary_separates_directional_and_unknown():
    events = {
        "AAA": [_obs("AAA", "raised"), _obs("AAA", "unknown", "no_previous_in_retrieved_history")],
        "BBB": [_obs("BBB", "unknown", "no_previous_in_retrieved_history"),
                _obs("BBB", "unknown", "basis_mismatch"), _obs("BBB", "maintained")],
    }
    meta = {"n_tickers_requested": 3, "n_tickers_queried": 3, "n_tickers_failed": 1, "n_network_requests": 30,
            "max_network_requests": 300, "time_budget_seconds": 300.0}

    s = gs.summarize_event_fetch(meta, {"CCC": "no_earnings_filings"}, events)

    assert s["n_tickers_queried"] == 3
    assert s["n_tickers_failed"] == 1
    assert s["n_observations"] == 5
    assert s["n_observations_directional"] == 2
    assert s["n_observations_unknown"] == 3
    assert s["unknown_reason_counts"] == {"no_previous_in_retrieved_history": 2, "basis_mismatch": 1}
    assert s["sec_request_cap"] == 300
    assert "unknown" in s["known_limitation"]
    line = gs.format_event_fetch_summary(s)
    assert "방향 판정 2" in line and "unknown 3" in line and "30/300" in line
    assert "test-agent" not in json.dumps(s, ensure_ascii=False)
