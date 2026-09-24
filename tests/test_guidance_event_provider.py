"""core/guidance_event_provider.py (RES-04 가이던스 shadow 실제 SEC 배선) 테스트.

원칙: 실제 네트워크 호출을 하지 않는다. SEC 응답은 합성 fixture(submissions JSON / filing 인덱스 HTML /
EX-99.1 보도자료 HTML)를 돌려주는 가짜 HTTP 세션으로 주입하고, 티커->CIK 매핑도 가짜 클라이언트로 준다.
그 외 경로(요청·캐시·추출·비교)는 실제 core.earnings_events 코드를 그대로 지나간다.
"""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from core import guidance_event_provider as gep
from core import guidance_shadow as gs
from core.earnings_events import SecEdgarClient

AS_OF = date(2026, 6, 10)
CIK = "0000000320"
CIK_INT = 320

RECENT_ACC = "0000000320-26-000002"  # as_of 기준 9일 전 발표 -> 관측 창 안
OLD_ACC = "0000000320-26-000001"  # 약 100일 전 발표 -> history(비교 대상)로만 사용
RECENT_ACCEPT = "2026-06-01T16:05:00.000Z"
OLD_ACCEPT = "2026-03-02T16:05:00.000Z"


# ---------------------------------------------------------------------------
# 합성 SEC fixture
# ---------------------------------------------------------------------------
def _submissions() -> dict:
    return {
        "cik": CIK,
        "name": "Fixture Corp",
        "tickers": ["AAA"],
        "filings": {
            "recent": {
                "accessionNumber": [RECENT_ACC, OLD_ACC],
                "form": ["8-K", "8-K"],
                "items": ["2.02,9.01", "2.02,9.01"],
                "filingDate": ["2026-06-01", "2026-03-02"],
                "reportDate": ["2026-06-01", "2026-03-02"],
                "acceptanceDateTime": [RECENT_ACCEPT, OLD_ACCEPT],
                "primaryDocument": ["form8k.htm", "form8k.htm"],
            },
            "files": [],
        },
    }


def _folder(accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{CIK_INT}/{accession.replace('-', '')}"


def _index_html(accession: str) -> str:
    return f"""
    <html><body>
    <table class="tableFile" summary="Document Format Files">
      <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th></tr>
      <tr><td>1</td><td>8-K</td><td><a href="/Archives/edgar/data/{CIK_INT}/{accession.replace('-', '')}/form8k.htm">form8k.htm</a></td><td>8-K</td></tr>
      <tr><td>2</td><td>Press Release</td><td><a href="/Archives/edgar/data/{CIK_INT}/{accession.replace('-', '')}/ex99-1.htm">ex99-1.htm</a></td><td>EX-99.1</td></tr>
    </table>
    </body></html>
    """


_OLD_RELEASE = """<html><body>
<p>Fixture Corp Reports First Quarter Results</p>
<p>Outlook</p>
<p>For fiscal year 2026, the company expects revenue of $1.00 billion to $1.10 billion.</p>
</body></html>"""

_RECENT_RELEASE = """<html><body>
<p>Fixture Corp Raises Full-Year Outlook</p>
<p>Outlook</p>
<p>The company raised its fiscal year 2026 revenue guidance and now expects revenue of $1.20 billion to $1.30 billion.</p>
</body></html>"""


class _Response:
    def __init__(self, body: str, status: int = 200):
        self.status_code = status
        self.content = body.encode("utf-8")
        self.headers = {}


class _FakeSession:
    """SEC 응답을 URL 로 흉내 내는 가짜 requests.Session. 실제 소켓을 열지 않는다."""

    def __init__(self, fail_tickers=()):
        self.urls = []
        self.fail_tickers = set(fail_tickers)

    def get(self, url, headers=None, timeout=None):  # noqa: ARG002 - 시그니처만 맞춘다
        self.urls.append(url)
        if url.endswith(f"CIK{CIK}.json"):
            return _Response(json.dumps(_submissions()))
        for acc in (RECENT_ACC, OLD_ACC):
            if url == f"{_folder(acc)}/{acc}-index.htm":
                return _Response(_index_html(acc))
            if url == f"{_folder(acc)}/ex99-1.htm":
                return _Response(_RECENT_RELEASE if acc == RECENT_ACC else _OLD_RELEASE)
        return _Response("not found", status=404)


class _FakeTickerClient:
    """core.filing_changes.EdgarClient.resolve_cik 만 흉내 낸다."""

    def __init__(self, mapping, *, unknown=()):
        self.mapping = mapping
        self.unknown = set(unknown)
        self.calls = []

    def resolve_cik(self, ticker: str) -> str:
        self.calls.append(ticker)
        if ticker in self.unknown or ticker not in self.mapping:
            exc = RuntimeError(f"ticker not found in SEC ticker list: {ticker}")
            exc.kind = "ticker_not_found"
            raise exc
        return self.mapping[ticker]


def _sec_client(tmp_path, session):
    # sleep 을 no-op 으로 주되 요청 간격 기본값(0.25초 = 초당 4회)은 그대로 둔다(제한을 푸는 것이 아니다).
    return SecEdgarClient(cache_dir=tmp_path / "sec_cache", session=session, sleep=lambda _s: None,
                          user_agent="test-agent")


# ---------------------------------------------------------------------------
# (a) 티커 -> CIK -> 8-K Item 2.02 -> 가이던스 변환
# ---------------------------------------------------------------------------
def test_ticker_to_guidance_observation_pipeline(tmp_path):
    session = _FakeSession()
    result = gep.fetch_guidance_events(
        ["aaa"], as_of=AS_OF, cache_dir=tmp_path / "guidance_cache",
        sec_client=_sec_client(tmp_path, session), ticker_client=_FakeTickerClient({"AAA": CIK}))

    assert result.failures == {}
    assert list(result.events_by_ticker) == ["AAA"]
    observations = result.events_by_ticker["AAA"]
    assert len(observations) == 1  # 창 안(6/1) 발표 1건만 관측, 3/2 발표는 비교 대상으로만 쓰인다

    obs = observations[0]
    assert obs.ticker == "AAA"
    assert obs.available_at == datetime(2026, 6, 1, 16, 5, tzinfo=timezone.utc)
    assert obs.approximate is True
    assert obs.change.change == "raised"  # 1.05B -> 1.25B
    assert obs.change.current.metric == "revenue"
    assert obs.change.current.period_key == "FY2026"
    assert obs.change.previous is not None
    assert obs.change.previous.accession == OLD_ACC

    # guidance_shadow 의 feature 계산까지 그대로 이어진다(별도 파싱 없이)
    feature = gs.compute_guidance_feature("AAA", AS_OF, observations)
    assert feature.basis_status == gs.BASIS_CLEAR
    assert feature.veto_flag is False
    assert feature.latest_change == "raised"

    assert result.meta["n_tickers_ok"] == 1
    assert result.meta["n_network_requests"] > 0


def test_max_tickers_limits_queries(tmp_path):
    session = _FakeSession()
    ticker_client = _FakeTickerClient({"AAA": CIK, "BBB": CIK})
    result = gep.fetch_guidance_events(
        ["AAA", "BBB", "CCC"], as_of=AS_OF, max_tickers=1, cache_dir=tmp_path / "guidance_cache",
        sec_client=_sec_client(tmp_path, session), ticker_client=ticker_client)

    assert ticker_client.calls == ["AAA"]  # 상한을 넘은 티커는 조회 자체를 하지 않는다
    statuses = {o.ticker: o.status for o in result.outcomes}
    assert statuses["AAA"] == gep.STATUS_OK
    assert statuses["BBB"] == gep.STATUS_SKIPPED
    assert statuses["CCC"] == gep.STATUS_SKIPPED
    assert result.meta["n_tickers_skipped"] == 2


# ---------------------------------------------------------------------------
# (b) 한 티커 실패가 나머지를 막지 않는다
# ---------------------------------------------------------------------------
def test_one_ticker_failure_does_not_block_others(tmp_path):
    session = _FakeSession()
    result = gep.fetch_guidance_events(
        ["ZZZ", "AAA"], as_of=AS_OF, cache_dir=tmp_path / "guidance_cache",
        sec_client=_sec_client(tmp_path, session),
        ticker_client=_FakeTickerClient({"AAA": CIK}, unknown=["ZZZ"]))

    assert "AAA" in result.events_by_ticker  # 뒤 티커는 정상 처리
    assert "ZZZ" not in result.events_by_ticker
    assert result.failures == {"ZZZ": "RuntimeError:ticker_not_found"}
    assert result.meta["n_tickers_failed"] == 1
    assert result.meta["n_tickers_ok"] == 1


def test_missing_earnings_filings_is_reported_not_raised(tmp_path):
    class _EmptySession(_FakeSession):
        def get(self, url, headers=None, timeout=None):
            self.urls.append(url)
            if url.endswith(f"CIK{CIK}.json"):
                empty = _submissions()
                empty["filings"]["recent"] = {k: [] for k in empty["filings"]["recent"]}
                return _Response(json.dumps(empty))
            return _Response("not found", status=404)

    result = gep.fetch_guidance_events(
        ["AAA"], as_of=AS_OF, cache_dir=tmp_path / "guidance_cache",
        sec_client=_sec_client(tmp_path, _EmptySession()), ticker_client=_FakeTickerClient({"AAA": CIK}))

    assert result.events_by_ticker == {}
    assert result.failures == {"AAA": "no_earnings_filings"}


# ---------------------------------------------------------------------------
# (c) 캐시 적중 시 네트워크 재호출 없음
# ---------------------------------------------------------------------------
def test_same_day_second_call_hits_cache_without_network(tmp_path):
    cache_dir = tmp_path / "guidance_cache"
    first_session = _FakeSession()
    first = gep.fetch_guidance_events(
        ["AAA"], as_of=AS_OF, cache_dir=cache_dir, sec_client=_sec_client(tmp_path, first_session),
        ticker_client=_FakeTickerClient({"AAA": CIK}))
    assert first.meta["n_cache_hits"] == 0
    assert len(first_session.urls) > 0

    # 두 번째 호출: 캐시를 읽고 끝나야 하므로 HTTP 세션도 티커 클라이언트도 건드리지 않는다.
    second_session = _FakeSession()
    second_ticker_client = _FakeTickerClient({"AAA": CIK})
    second = gep.fetch_guidance_events(
        ["AAA"], as_of=AS_OF, cache_dir=cache_dir,
        sec_client=_sec_client(tmp_path / "second", second_session), ticker_client=second_ticker_client)

    assert second_session.urls == []  # 네트워크 재호출 없음
    assert second_ticker_client.calls == []
    assert second.meta["n_cache_hits"] == 1
    assert second.meta["n_network_requests"] == 0
    assert [o.status for o in second.outcomes] == [gep.STATUS_CACHED]

    # 캐시에서 되살린 관측이 첫 호출과 같은 값이어야 한다(직렬화 왕복 확인)
    a, b = first.events_by_ticker["AAA"][0], second.events_by_ticker["AAA"][0]
    assert (a.ticker, a.available_at, a.change.change, a.change.current.period_key) == \
           (b.ticker, b.available_at, b.change.change, b.change.current.period_key)
    assert a.change.current.low == b.change.current.low
    assert a.change.mid_change_pct == b.change.mid_change_pct


def test_cache_is_not_reused_for_different_as_of_or_params(tmp_path):
    cache_dir = tmp_path / "guidance_cache"
    gep.fetch_guidance_events(["AAA"], as_of=AS_OF, cache_dir=cache_dir,
                              sec_client=_sec_client(tmp_path, _FakeSession()),
                              ticker_client=_FakeTickerClient({"AAA": CIK}))

    other_day = gep.fetch_guidance_events(
        ["AAA"], as_of=AS_OF + timedelta(days=1), cache_dir=cache_dir,
        sec_client=_sec_client(tmp_path / "d2", _FakeSession()), ticker_client=_FakeTickerClient({"AAA": CIK}))
    assert other_day.meta["n_cache_hits"] == 0

    other_params = gep.fetch_guidance_events(
        ["AAA"], as_of=AS_OF, cache_dir=cache_dir, window_days=90,
        sec_client=_sec_client(tmp_path / "d3", _FakeSession()), ticker_client=_FakeTickerClient({"AAA": CIK}))
    assert other_params.meta["n_cache_hits"] == 0


def test_rate_limit_guard_rejects_too_fast_client(tmp_path):
    fast = SecEdgarClient(cache_dir=tmp_path / "sec_cache", session=_FakeSession(), sleep=lambda _s: None,
                          min_interval_seconds=0.2)
    fast._limiter._min_interval = 0.01  # 외부에서 제한을 푼 클라이언트를 흉내 낸다
    with pytest.raises(ValueError):
        gep.fetch_guidance_events(["AAA"], as_of=AS_OF, cache_dir=tmp_path / "guidance_cache",
                                  sec_client=fast, ticker_client=_FakeTickerClient({"AAA": CIK}))


# ---------------------------------------------------------------------------
# (d) record_guidance_shadow 기본값에서는 provider 가 호출되지 않는다
# ---------------------------------------------------------------------------
def _satellite_result():
    return {"as_of": AS_OF.isoformat(), "selected": ["AAA"], "per_ticker_weights": {"AAA": 0.05},
            "sizing_method": "equal", "new_orders_allowed": True}


class _SpyFetcher:
    def __init__(self, events=None):
        self.calls = []
        self.events = events or {}

    def __call__(self, tickers, *, as_of=None, max_tickers=None):
        self.calls.append((list(tickers), as_of, max_tickers))
        return gep.GuidanceEventFetchResult(
            self.events, (gep.TickerFetchOutcome("AAA", gep.STATUS_OK, len(self.events.get("AAA", []))),),
            {"as_of": as_of.isoformat() if as_of else None, "n_tickers_queried": len(list(tickers))})


def test_default_does_not_call_provider(db_session, monkeypatch):
    spy = _SpyFetcher()
    monkeypatch.setattr(gep, "fetch_guidance_events", spy)

    out = gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=_satellite_result())

    assert out["ok"] is True
    assert spy.calls == []  # 기본값(fetch_events=False)에서는 조회하지 않는다
    assert out["n_with_events_provided"] == 0
    assert out["fetch_events"] is False


def test_fetch_events_opt_in_uses_provider(db_session):
    change = gs.GuidanceObservation(
        "AAA",
        __import__("core.earnings_events", fromlist=["GuidanceChange"]).GuidanceChange(
            change="raised", reason="midpoint_comparison",
            current=gep._item_from_record({
                "metric": "revenue", "basis": "gaap", "period_key": "FY2026", "shape": "range",
                "low": "1000", "high": "1100", "anchor": "outlook"})),
        datetime(2026, 6, 1, 16, 5, tzinfo=timezone.utc))
    spy = _SpyFetcher({"AAA": [change]})

    out = gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=_satellite_result(),
                                    fetch_events=True, max_tickers=5, event_fetcher=spy)

    assert out["ok"] is True
    assert out["fetch_events"] is True
    assert len(spy.calls) == 1
    tickers, as_of_arg, max_t = spy.calls[0]
    assert tickers == ["AAA"]
    assert as_of_arg == AS_OF
    assert max_t == 5
    assert out["n_with_events_provided"] == 1
    assert out["n_event_fetch_failures"] == 0


def test_explicit_events_take_priority_over_fetch_events(db_session):
    spy = _SpyFetcher()
    out = gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=_satellite_result(),
                                    events_by_ticker={}, fetch_events=True, event_fetcher=spy)

    assert out["ok"] is True
    assert spy.calls == []  # 주입값이 우선 -> provider 를 부르지 않는다
    assert out["fetch_events"] is False
