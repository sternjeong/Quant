"""core/earnings_events 오프라인 테스트 (SEC 네트워크 미사용).

fixture 문장은 직접 작성한 짧은 보도자료식 문장이다. 예상값은 구현이 아니라 요구사항(스펙 문서와 산수)에서
손으로 정했다: 스케일 곱셈, 뉴욕 시각 변환(EDT=UTC-4, EST=UTC-5), 중간값 비교 결과.
"""

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import requests

from core import earnings_events as ee

UTC = timezone.utc
T_NEW = datetime(2026, 7, 30, 20, 30, 28, tzinfo=UTC)
T_OLD = datetime(2026, 4, 30, 20, 30, 0, tzinfo=UTC)


def D(x):
    return Decimal(str(x))


def extract(text, acceptance=T_NEW, accession="0000000001-26-000002"):
    return ee.extract_guidance(text, cik="123456", accession=accession, acceptance_utc=acceptance)


def one(text, **kw):
    res = extract(text, **kw)
    assert len(res.items) == 1, (res.items, res.skipped)
    return res.items[0]


# ---------------------------------------------------------------------------
# User-Agent / 클라이언트
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status=200, body=b"{}", headers=None):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Clock:
    """sleep 이 시간을 앞으로 보내는 가짜 시계."""

    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def make_client(tmp_path, responses, clock=None, user_agent="test-agent", **kw):
    """user_agent=None 이면 환경변수 해석(get_user_agent)을 그대로 쓴다. 기본은 고정 문자열(.env 미접촉)."""
    clock = clock or Clock()
    session = FakeSession(responses)
    client = ee.SecEdgarClient(cache_dir=tmp_path / "cache", session=session, sleep=clock.sleep, clock=clock.now,
                               user_agent=user_agent, **kw)
    return client, session, clock


@pytest.fixture()
def no_dotenv(monkeypatch):
    """테스트가 실제 .env(사용자 값)를 읽지 않게 하고 관련 환경변수를 비운다."""
    monkeypatch.setattr(ee, "_DOTENV_LOADED", True)
    for name in ("SEC_EDGAR_USER_AGENT", "SEC_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)


def test_user_agent_precedence_edgar_env_then_sec_env_then_generic(monkeypatch, no_dotenv):
    assert ee.get_user_agent() == "QuantResearch personal-project"
    monkeypatch.setenv("SEC_USER_AGENT", "  ProjectX second-choice  ")
    assert ee.get_user_agent() == "ProjectX second-choice"
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "ProjectX first-choice")
    assert ee.get_user_agent() == "ProjectX first-choice"
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "   ")  # 공백뿐이면 다음 순위
    assert ee.get_user_agent() == "ProjectX second-choice"
    monkeypatch.setenv("SEC_USER_AGENT", "")
    assert ee.get_user_agent() == "QuantResearch personal-project"


def test_default_user_agent_has_no_personal_info():
    assert "@" not in ee.DEFAULT_USER_AGENT
    assert ee.USER_AGENT_ENVS == ("SEC_EDGAR_USER_AGENT", "SEC_USER_AGENT")


def test_access_error_message_does_not_leak_user_agent(tmp_path, monkeypatch, no_dotenv):
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "SECRET-CONTACT-VALUE")
    client, _, _ = make_client(tmp_path, [FakeResponse(403, b"blocked")], user_agent=None)
    with pytest.raises(ee.SecAccessError) as exc:
        client.get("https://www.sec.gov/x")
    assert "SECRET-CONTACT-VALUE" not in str(exc.value)
    assert "SECRET-CONTACT-VALUE" not in repr(client.__dict__.get("cache_dir", ""))


def test_request_sends_user_agent_header(tmp_path, monkeypatch, no_dotenv):
    monkeypatch.setenv("SEC_USER_AGENT", "TestAgent contact-not-real")
    client, session, _ = make_client(tmp_path, [FakeResponse(200, b"{}")], user_agent=None)
    client.get("https://data.sec.gov/submissions/CIK0000000001.json")
    assert session.calls[0]["headers"]["User-Agent"] == "TestAgent contact-not-real"


def test_client_rejects_interval_above_five_requests_per_second(tmp_path):
    with pytest.raises(ValueError):
        ee.SecEdgarClient(cache_dir=tmp_path, min_interval_seconds=0.1, user_agent="test-agent")


def test_requests_never_exceed_five_per_second(tmp_path):
    clock = Clock()
    n = 12
    client, session, _ = make_client(tmp_path, [FakeResponse(200, b"x")] * n, clock=clock)
    stamps = []
    orig_get = session.get

    def stamped(url, headers=None, timeout=None):
        stamps.append(clock.now())
        return orig_get(url, headers=headers, timeout=timeout)

    session.get = stamped
    for i in range(n):
        client.get(f"https://data.sec.gov/x/{i}", use_cache=False)
    for i in range(len(stamps)):
        window = [s for s in stamps if stamps[i] <= s < stamps[i] + 1.0]
        assert len(window) <= 5
    assert min(b - a for a, b in zip(stamps, stamps[1:])) >= 0.2 - 1e-9


def test_cache_hit_makes_no_request_and_ttl_expiry_refetches(tmp_path):
    clock = Clock()
    now = [datetime(2026, 9, 1, tzinfo=UTC)]
    session = FakeSession([FakeResponse(200, b"first"), FakeResponse(200, b"second")])
    client = ee.SecEdgarClient(cache_dir=tmp_path / "c", session=session, sleep=clock.sleep, clock=clock.now,
                               now=lambda: now[0], user_agent="test-agent")
    url = "https://data.sec.gov/submissions/CIK0000000001.json"
    a = client.get(url, ttl_seconds=3600)
    b = client.get(url, ttl_seconds=3600)
    assert (a.text, a.from_cache) == ("first", False)
    assert (b.text, b.from_cache) == ("first", True)
    assert len(session.calls) == 1
    now[0] = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)  # 2시간 경과 > ttl 1시간
    c = client.get(url, ttl_seconds=3600)
    assert (c.text, c.from_cache) == ("second", False)
    assert len(session.calls) == 2
    # ttl=None(불변 문서)이면 오래돼도 캐시를 쓴다
    now[0] = datetime(2027, 9, 1, tzinfo=UTC)
    assert client.get(url, ttl_seconds=None).from_cache is True


def test_403_is_not_retried_and_raises_access_error(tmp_path):
    client, session, clock = make_client(tmp_path, [FakeResponse(403, b"<html>Undeclared Automated Tool</html>")])
    with pytest.raises(ee.SecAccessError):
        client.get("https://www.sec.gov/Archives/edgar/data/1/2/x.htm")
    assert len(session.calls) == 1
    assert clock.sleeps == []


def test_block_page_with_http_200_is_access_error_and_not_cached(tmp_path):
    body = b"<title>SEC.gov | Your Request Originates from an Undeclared Automated Tool</title>"
    client, session, _ = make_client(tmp_path, [FakeResponse(200, body)])
    with pytest.raises(ee.SecAccessError):
        client.get("https://www.sec.gov/x")
    cache_dir = tmp_path / "cache"
    assert not cache_dir.exists() or list(cache_dir.glob("*")) == []  # 차단 페이지는 캐시하지 않는다


def test_404_is_not_retried(tmp_path):
    client, session, _ = make_client(tmp_path, [FakeResponse(404)])
    with pytest.raises(ee.SecFetchError):
        client.get("https://data.sec.gov/none")
    assert len(session.calls) == 1


def test_retries_5xx_with_exponential_backoff_then_succeeds(tmp_path):
    client, session, clock = make_client(tmp_path, [FakeResponse(503), FakeResponse(500), FakeResponse(200, b"ok")])
    doc = client.get("https://data.sec.gov/a", use_cache=False)
    assert doc.text == "ok"
    assert len(session.calls) == 3
    # 재시도 대기 1.0s, 2.0s(요청 간격 sleep 은 0.25s 미만 조각이라 제외하고 backoff 만 비교)
    backoffs = [s for s in clock.sleeps if s >= 1.0]
    assert backoffs == [1.0, 2.0]


def test_429_respects_retry_after_and_network_error_retries(tmp_path):
    client, session, clock = make_client(
        tmp_path, [FakeResponse(429, headers={"Retry-After": "7"}), requests.ConnectionError("boom"),
                   FakeResponse(200, b"ok")])
    assert client.get("https://data.sec.gov/a", use_cache=False).text == "ok"
    assert [s for s in clock.sleeps if s >= 1.0] == [7.0, 2.0]


def test_retry_exhausted_raises_fetch_error(tmp_path):
    client, session, _ = make_client(tmp_path, [FakeResponse(500)] * 3, max_attempts=3)
    with pytest.raises(ee.SecFetchError):
        client.get("https://data.sec.gov/a", use_cache=False)
    assert len(session.calls) == 3


# ---------------------------------------------------------------------------
# submissions / 인덱스 / HTML
# ---------------------------------------------------------------------------

SUBMISSIONS = {
    "cik": "1234",
    "name": "Example Corp",
    "tickers": ["EXPL"],
    "filings": {
        "recent": {
            "accessionNumber": ["0000001234-26-000010", "0000001234-26-000009", "0000001234-26-000008",
                                "0000001234-26-000007", "0000001234-26-000006"],
            "filingDate": ["2026-07-30", "2026-07-15", "2026-07-30", "2026-04-30", "2026-04-30"],
            "reportDate": ["2026-07-30", "", "2026-07-30", "2026-04-30", ""],
            "acceptanceDateTime": ["2026-07-30T20:30:28.000Z", "2026-07-15T13:00:00.000Z",
                                   "2026-07-30T21:00:00.000Z", "2026-04-30T11:00:00.000Z", ""],
            "form": ["8-K", "8-K", "8-K/A", "8-K", "8-K"],
            "items": ["2.02,9.01", "5.02", "2.02,9.01", "2.02", "2.02"],
            "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm", "e.htm"],
        },
        "files": [{"name": "CIK0000001234-submissions-001.json", "filingFrom": "2010-01-01", "filingTo": "2026-01-31"}],
    },
}
OLD_PAGE = {
    "accessionNumber": ["0000001234-25-000001"], "filingDate": ["2025-10-30"], "reportDate": ["2025-10-30"],
    "acceptanceDateTime": ["2025-10-30T20:15:00.000Z"], "form": ["8-K"], "items": ["2.02,9.01"],
    "primaryDocument": ["old.htm"],
}


def test_parse_submissions_picks_item_202_only_and_sorts_by_acceptance():
    out = ee.parse_submissions_earnings_filings(SUBMISSIONS)
    # 5.02(다른 item), 8-K/A(기본 제외), acceptance 없는 행 제외
    assert [f.accession for f in out] == ["0000001234-26-000007", "0000001234-26-000010"]
    last = out[-1]
    assert last.cik == "0000001234"
    assert last.ticker == "EXPL"
    assert last.acceptance_utc == datetime(2026, 7, 30, 20, 30, 28, tzinfo=UTC)
    assert last.filing_date == date(2026, 7, 30)
    assert last.items == ("2.02", "9.01")
    assert last.index_url == "https://www.sec.gov/Archives/edgar/data/1234/000000123426000010/0000001234-26-000010-index.htm"
    assert last.primary_document_url.endswith("/000000123426000010/a.htm")


def test_parse_submissions_amendments_and_date_filter_and_extra_pages():
    out = ee.parse_submissions_earnings_filings(SUBMISSIONS, include_amendments=True, since=date(2026, 7, 1))
    assert [f.accession for f in out] == ["0000001234-26-000010", "0000001234-26-000008"]
    assert [f.form for f in out] == ["8-K", "8-K/A"]
    both = ee.parse_submissions_earnings_filings(SUBMISSIONS, extra_pages=[OLD_PAGE])
    assert both[0].accession == "0000001234-25-000001"


class FakeSubmissionsClient:
    def __init__(self):
        self.pages = []

    def fetch_submissions(self, cik):
        return SUBMISSIONS

    def fetch_submissions_page(self, name):
        self.pages.append(name)
        return OLD_PAGE


def test_list_earnings_filings_fetches_old_pages_only_when_since_is_earlier():
    client = FakeSubmissionsClient()
    recent_only = ee.list_earnings_filings(client, 1234)
    assert client.pages == []
    assert len(recent_only) == 2
    with_old = ee.list_earnings_filings(client, 1234, since=date(2025, 1, 1))
    assert client.pages == ["CIK0000001234-submissions-001.json"]
    assert with_old[0].accession == "0000001234-25-000001"


INDEX_HTML = """<html><body><table class="tableFile" summary="Document Format Files">
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/1234/000000123426000010/a.htm">a.htm</a></td><td>8-K</td><td>1000</td></tr>
<tr><td>2</td><td>PRESS RELEASE</td><td><a href="/Archives/edgar/data/1234/000000123426000010/ex991.htm">ex991.htm</a></td><td>EX-99.1</td><td>2000</td></tr>
<tr><td>3</td><td>SLIDES</td><td><a href="/Archives/edgar/data/1234/000000123426000010/ex992.htm">ex992.htm</a></td><td>EX-99.2</td><td>3000</td></tr>
</table></body></html>"""


def test_parse_index_and_select_ex_99_1_only():
    docs = ee.parse_filing_index_html(INDEX_HTML)
    assert [d.doc_type for d in docs] == ["8-K", "EX-99.1", "EX-99.2"]
    assert docs[0].url == "https://www.sec.gov/Archives/edgar/data/1234/000000123426000010/a.htm"  # /ix?doc= 풀기
    chosen = ee.select_press_release_exhibit(docs)
    assert chosen.filename == "ex991.htm"


def test_select_does_not_guess_ex_99_2_and_uses_filename_only_when_type_missing():
    docs = ee.parse_filing_index_html(INDEX_HTML)
    assert ee.select_press_release_exhibit([d for d in docs if d.doc_type != "EX-99.1"]) is None
    typeless = [ee.FilingDocument("2", "", "q3-ex99-1.htm", "", "https://www.sec.gov/x/q3-ex99-1.htm")]
    assert ee.select_press_release_exhibit(typeless).filename == "q3-ex99-1.htm"
    typed_other = [ee.FilingDocument("2", "", "q3-ex99-1.htm", "EX-99.2", "https://www.sec.gov/x/q3-ex99-1.htm")]
    assert ee.select_press_release_exhibit(typed_other) is None


def test_fetch_press_release_uses_index_then_exhibit_and_caches(tmp_path):
    filing = ee.parse_submissions_earnings_filings(SUBMISSIONS)[-1]
    client, session, _ = make_client(tmp_path, [
        FakeResponse(200, INDEX_HTML), FakeResponse(200, "<html><body><p>Revenue guidance text.</p></body></html>")])
    pr = ee.fetch_press_release(client, filing)
    assert pr.exhibit_type == "EX-99.1"
    assert pr.text == "Revenue guidance text."
    assert [c["url"] for c in session.calls] == [
        filing.index_url, "https://www.sec.gov/Archives/edgar/data/1234/000000123426000010/ex991.htm"]
    again = ee.fetch_press_release(client, filing)  # 캐시: 추가 요청 없음
    assert again.text == pr.text and len(session.calls) == 2


def test_html_to_text_merges_symbol_cells_and_drops_hidden_and_scripts():
    html = ("<html><head><title>t</title></head><body><div style='display:none'>HIDDEN</div>"
            "<script>var x=1;</script><p>Line&nbsp;one</p>"
            "<table><tr><td>Revenue</td><td>$</td><td>1,200</td><td>-</td><td>$</td><td>1,250</td></tr>"
            "<tr><td>Gross margin</td><td>45.0</td><td>%</td></tr></table></body></html>")
    text = ee.html_to_text(html)
    assert "HIDDEN" not in text and "var x" not in text
    assert text.split("\n") == ["Line one", "Revenue | $1,200 | - | $1,250", "Gross margin | 45.0%"]


# ---------------------------------------------------------------------------
# 시각 처리
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("utc, session, entry, hhmm", [
    # 2026-07-30(목) EDT = UTC-4
    (datetime(2026, 7, 30, 11, 30, tzinfo=UTC), "pre_market", date(2026, 7, 30), "09:30"),  # 07:30 ET -> 같은 날 시가
    (datetime(2026, 7, 30, 13, 20, tzinfo=UTC), "pre_market", date(2026, 7, 31), "09:30"),  # 09:20+15분=09:35 > 09:30
    (datetime(2026, 7, 30, 13, 30, tzinfo=UTC), "regular", date(2026, 7, 31), "09:30"),  # 정각 09:30 은 strict 로 제외
    (datetime(2026, 7, 30, 15, 0, tzinfo=UTC), "regular", date(2026, 7, 31), "09:30"),  # 11:00 ET 장중 -> 다음 날
    (datetime(2026, 7, 30, 20, 30, 28, tzinfo=UTC), "after_hours", date(2026, 7, 31), "09:30"),  # 16:30 ET
    (datetime(2026, 7, 31, 21, 0, tzinfo=UTC), "after_hours", date(2026, 8, 3), "09:30"),  # 금 17:00 ET -> 월
    (datetime(2026, 8, 1, 15, 0, tzinfo=UTC), "non_trading_day", date(2026, 8, 3), "09:30"),  # 토요일
])
def test_session_classification_and_next_open(utc, session, entry, hhmm):
    assert ee.classify_release_session(utc).session == session
    got = ee.next_executable_open(utc)
    assert got.entry_date == entry
    assert got.entry_open_et.strftime("%H:%M") == hhmm
    assert got.calendar.startswith("weekday_only")


def test_pre_market_and_after_hours_are_not_merged_on_same_date():
    pre = ee.classify_release_session(datetime(2026, 7, 30, 11, 0, tzinfo=UTC))
    post = ee.classify_release_session(datetime(2026, 7, 30, 21, 0, tzinfo=UTC))
    assert pre.acceptance_et.date() == post.acceptance_et.date() == date(2026, 7, 30)
    assert (pre.session, post.session) == ("pre_market", "after_hours")
    assert ee.next_executable_open(pre.acceptance_utc).entry_date == date(2026, 7, 30)
    assert ee.next_executable_open(post.acceptance_utc).entry_date == date(2026, 7, 31)


def test_dst_changes_utc_to_et_offset():
    # 같은 UTC 13:20 이라도 EST(3/6, UTC-5)면 08:20, EDT(3/9, UTC-4)면 09:20
    est = ee.classify_release_session(datetime(2026, 3, 6, 13, 20, tzinfo=UTC))
    edt = ee.classify_release_session(datetime(2026, 3, 9, 13, 20, tzinfo=UTC))
    assert est.acceptance_et.strftime("%H:%M") == "08:20"
    assert edt.acceptance_et.strftime("%H:%M") == "09:20"
    assert ee.next_executable_open(datetime(2026, 3, 6, 13, 20, tzinfo=UTC)).entry_date == date(2026, 3, 6)
    assert ee.next_executable_open(datetime(2026, 3, 9, 13, 20, tzinfo=UTC)).entry_date == date(2026, 3, 10)
    assert ee.classify_release_session(datetime(2026, 1, 15, 21, 5, tzinfo=UTC)).session == "after_hours"  # 16:05 EST


def test_holiday_calendar_skips_closed_days_and_flags_weekday_fallback():
    days = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6), date(2026, 7, 7)]  # 7/3(금) 휴장
    utc = datetime(2026, 7, 2, 20, 30, tzinfo=UTC)  # 목 16:30 ET
    with_cal = ee.next_executable_open(utc, days)
    assert with_cal.entry_date == date(2026, 7, 6)
    assert with_cal.calendar == "trading_days_provided"
    assert ee.next_executable_open(utc).entry_date == date(2026, 7, 3)  # 달력 없으면 휴장 미반영
    assert ee.classify_release_session(datetime(2026, 7, 3, 15, 0, tzinfo=UTC), days).session == "non_trading_day"


def test_decision_cutoff_is_latest_of_all_times_and_requires_tz():
    a = datetime(2026, 7, 30, 20, 30, tzinfo=UTC)
    b = datetime(2026, 7, 31, 2, 0, tzinfo=UTC)
    c = datetime(2026, 7, 30, 22, 0, tzinfo=UTC)
    assert ee.decision_cutoff(a, b, c) == b
    assert ee.decision_cutoff(a, None) == a
    with pytest.raises(ValueError):
        ee.decision_cutoff(datetime(2026, 7, 30, 20, 30))
    # 늦게 수신한 문서는 acceptance 가 아니라 수신 시각 이후 시가에서만 진입 가능
    late_seen = ee.decision_cutoff(datetime(2026, 7, 30, 11, 0, tzinfo=UTC), datetime(2026, 7, 30, 14, 0, tzinfo=UTC))
    assert ee.next_executable_open(late_seen).entry_date == date(2026, 7, 31)


# ---------------------------------------------------------------------------
# 추출: 범위·점·경계
# ---------------------------------------------------------------------------


def test_revenue_range_in_billions_with_fiscal_quarter():
    it = one("For the fourth quarter of fiscal 2026, the Company expects revenue in the range of "
             "$1.20 billion to $1.25 billion.")
    assert (it.metric, it.period_key, it.shape) == ("revenue", "FY2026Q4", "range")
    assert (it.low, it.high) == (D("1200000000"), D("1250000000"))
    assert (it.unit, it.currency) == ("currency", "USD")
    assert it.cik == "0000123456" and it.accession == "0000000001-26-000002" and it.acceptance_utc == T_NEW
    assert "1.20 billion" in it.anchor


def test_shared_scale_and_mixed_scales_do_not_confuse_million_and_billion():
    shared = one("For fiscal 2026, we expect revenue of $4.90 to $5.00 billion.")
    assert (shared.low, shared.high) == (D("4900000000"), D("5000000000"))
    mixed = one("For fiscal 2026, we expect revenue between $950 million and $1.0 billion.")
    assert (mixed.low, mixed.high) == (D("950000000"), D("1000000000"))
    million = one("For fiscal 2026, we expect revenue of $950 million to $975 million.")
    assert (million.low, million.high) == (D("950000000"), D("975000000"))
    # 같은 금액을 다른 스케일로 쓰면 정규화 값이 같다
    a = one("For fiscal 2026, we expect revenue of $1,200 million to $1,300 million.")
    b = one("For fiscal 2026, we expect revenue of $1.2 billion to $1.3 billion.")
    assert (a.low, a.high) == (b.low, b.high)


def test_revenue_without_any_scale_is_flagged_and_not_comparable():
    it = one("For fiscal 2026, we expect revenue of $1,200 to $1,250.")
    assert "scale_ambiguous" in it.flags
    assert "scale_ambiguous" in it.problems
    change = ee.compare_guidance(it, None, history_complete=True)
    assert change.change == "unknown" and "scale_ambiguous" in change.reason


def test_eps_range_and_non_gaap_basis_and_not_scaled():
    it = one("The Company expects fiscal 2026 non-GAAP diluted EPS of $4.90 to $5.00.")
    assert (it.metric, it.basis, it.period_key, it.unit) == ("eps", "non_gaap", "FY2026", "per_share")
    assert (it.low, it.high) == (D("4.90"), D("5.00"))
    gaap = one("The Company expects fiscal 2026 GAAP diluted EPS of $3.10 to $3.20.")
    assert gaap.basis == "gaap"


def test_negative_eps_in_parentheses_and_with_minus_sign():
    paren = one("We now expect fiscal 2026 diluted EPS of $(0.10) to $(0.05).")
    assert (paren.low, paren.high) == (D("-0.10"), D("-0.05"))
    minus = one("We now expect fiscal 2026 diluted EPS of -$0.10 to -$0.05.")
    assert (minus.low, minus.high) == (D("-0.10"), D("-0.05"))


def test_loss_wording_without_sign_is_ambiguous_not_guessed():
    res = extract("We expect a net loss per share of $0.15 to $0.10 for fiscal 2026.")
    assert len(res.items) == 1
    assert "sign_ambiguous" in res.items[0].problems


def test_percent_margin_growth_and_point_estimates():
    m = one("For full year 2026, the Company expects GAAP operating margin of 27.5% to 28.5%.")
    assert (m.metric, m.basis, m.unit, m.low, m.high, m.currency) == (
        "operating_margin", "gaap", "percent", D("27.5"), D("28.5"), None)
    g = one("The Company expects fiscal 2026 gross margin of approximately 45 percent.")
    assert (g.metric, g.shape, g.low, g.high) == ("gross_margin", "point", D("45"), D("45"))
    growth = one("We expect revenue growth of 8% to 10% for fiscal 2026.")
    assert (growth.metric, growth.low, growth.high) == ("revenue_growth", D("8"), D("10"))
    shared_pct = one("We expect fiscal 2026 gross margin of 44 to 46 percent.")
    assert (shared_pct.low, shared_pct.high) == (D("44"), D("46"))


def test_plus_or_minus_percent_becomes_range_from_tolerance():
    it = one("Q4 FY26 revenue is expected to be $45.0 billion, plus or minus 2%.")
    assert it.period_key == "FY2026Q4"
    assert (it.low, it.high) == (D("44100000000"), D("45900000000"))  # 45.0 * 0.98 / 1.02
    assert "range_from_tolerance" in it.flags


def test_lower_and_upper_bound_shapes():
    lo = one("The Company expects revenue of at least $500 million in fiscal 2027.")
    assert (lo.shape, lo.low, lo.high) == ("lower_bound", D("500000000"), None)
    up = one("The Company expects operating income of up to $80 million in fiscal 2027.")
    assert (up.shape, up.low, up.high) == ("upper_bound", None, D("80000000"))


def test_two_metrics_in_one_sentence_get_their_own_values():
    res = extract("For fiscal 2026 the Company expects non-GAAP EPS of $1.30 to $1.35 and revenue of "
                  "$2.0 billion to $2.1 billion.")
    by_metric = {i.metric: i for i in res.items}
    assert (by_metric["eps"].low, by_metric["eps"].high) == (D("1.30"), D("1.35"))
    assert (by_metric["revenue"].low, by_metric["revenue"].high) == (D("2000000000"), D("2100000000"))


# ---------------------------------------------------------------------------
# 추출: 기간 혼동 방지, 직전 값/실적 참조 배제
# ---------------------------------------------------------------------------


def test_quarter_and_full_year_in_one_sentence_are_separated():
    res = extract("For the fourth quarter, we expect revenue of $1.2 to $1.25 billion; for fiscal 2026, "
                  "we expect revenue of $4.8 to $4.9 billion.")
    # 분기 값에는 연도가 없어 기간을 확정하지 않는다. 연간 값은 FY2026.
    by_period = {i.period_key: i for i in res.items}
    assert by_period["FY2026"].low == D("4800000000")
    quarter_items = [i for i in res.items if i.period_key is None]
    assert len(quarter_items) == 1 and quarter_items[0].low == D("1200000000")
    assert "period_unresolved" in quarter_items[0].problems


def test_period_variants_normalize_to_same_key():
    for text in ["For Q3 FY2026, we expect revenue of $1.1 to $1.2 billion.",
                 "For the third quarter of fiscal 2026, we expect revenue of $1.1 to $1.2 billion.",
                 "For fiscal 2026 third quarter, we expect revenue of $1.1 to $1.2 billion.",
                 "For the third quarter of fiscal year 2026 we expect revenue of $1.1 to $1.2 billion."]:
        assert one(text).period_key == "FY2026Q3", text
    assert one("For fiscal 2026, we expect revenue of $4.4 to $4.5 billion.").period_key == "FY2026"
    assert one("For the full year 2026, we expect revenue of $4.4 to $4.5 billion.").period_key == "FY2026"
    assert one("For the quarter ending September 30, 2026, we expect revenue of $1.1 to $1.2 billion."
               ).period_key == "QEND:2026-09-30"
    assert one("For the second half of fiscal 2026, we expect revenue of $2.1 to $2.2 billion."
               ).period_key == "FY2026H2"
    assert one("For calendar 2026, we expect revenue of $4.4 to $4.5 billion.").period_key == "CY2026"


def test_quarter_without_year_is_not_resolved():
    it = one("For the third quarter, we expect revenue of $1.1 to $1.2 billion.")
    assert it.period_key is None
    assert any(f.startswith("period_year_missing") for f in it.flags)
    assert ee.compare_guidance(it, None, history_complete=True).change == "unknown"


def test_actual_results_and_result_vs_guidance_are_not_extracted_as_new_guidance():
    res = extract("Revenue was $1.3 billion for the third quarter of fiscal 2026. "
                  "Revenue of $1.3 billion exceeded the high end of our guidance range of $1.2 to $1.25 billion.")
    assert res.items == []
    assert res.status != "guidance_found"


def test_prior_range_in_same_sentence_is_kept_only_as_prior_stated():
    it = one("The Company raised its fiscal 2026 revenue outlook to $4.9 billion to $5.0 billion, "
             "from $4.7 billion to $4.8 billion.")
    assert (it.low, it.high) == (D("4900000000"), D("5000000000"))
    assert it.prior_stated == (D("4700000000"), D("4800000000"))
    assert it.stated_action == "raise"


def test_from_x_to_y_after_raise_is_transition_not_a_range():
    it = one("The Company raises its fiscal 2026 revenue outlook from $4.7 billion to $4.9 billion.")
    assert (it.shape, it.low, it.high) == ("point", D("4900000000"), D("4900000000"))
    assert it.prior_stated == (D("4700000000"), D("4700000000"))
    # 변화 동사가 없는 "from X to Y"는 범위다
    rng = one("The Company expects fiscal 2026 revenue in a range from $4.7 billion to $4.9 billion.")
    assert (rng.shape, rng.low, rng.high) == ("range", D("4700000000"), D("4900000000"))


def test_compared_to_prior_guidance_is_excluded():
    it = one("The Company expects fiscal 2026 revenue of $5.1 billion to $5.2 billion, compared to "
             "prior guidance of $4.9 billion to $5.0 billion.")
    assert (it.low, it.high) == (D("5100000000"), D("5200000000"))


def test_disclaimer_and_qualitative_text_yield_no_items():
    assert extract("These forward-looking statements include our expectations for revenue of $3 million.").status \
        == "no_guidance_language"
    res = extract("We expect revenue to grow at a mid-teens rate over the next few years.")
    assert res.items == []


def test_withdrawal_statement():
    it = one("The Company is withdrawing its full-year 2026 guidance.")
    assert (it.shape, it.metric, it.period_key, it.stated_action) == ("withdrawn", "all", "FY2026", "withdraw")
    assert ee.compare_guidance(it, None).change == "withdrawn"
    assert extract("The Company will not withdraw its guidance and does not undertake any obligation.").items == []


def test_table_with_scale_header_and_columns():
    html = ("<html><body><p>Fourth Quarter Fiscal 2026 Outlook</p><p>(in millions, except per share data)</p>"
            "<table><tr><td>Q4 FY2026</td><td>FY2026</td></tr>"
            "<tr><td>Revenue</td><td>$</td><td>1,200</td><td>-</td><td>$</td><td>1,250</td>"
            "<td>$</td><td>4,800</td><td>-</td><td>$</td><td>4,900</td></tr>"
            "<tr><td>Non-GAAP diluted EPS</td><td>$1.20</td><td>-</td><td>$1.30</td>"
            "<td>$4.90</td><td>-</td><td>$5.00</td></tr></table></body></html>")
    res = extract(ee.html_to_text(html))
    got = {(i.metric, i.period_key): (i.low, i.high) for i in res.items}
    assert got[("revenue", "FY2026Q4")] == (D("1200000000"), D("1250000000"))  # 표 헤더의 "in millions"
    assert got[("revenue", "FY2026")] == (D("4800000000"), D("4900000000"))
    assert got[("eps", "FY2026Q4")] == (D("1.20"), D("1.30"))  # EPS 는 스케일을 곱하지 않는다
    assert got[("eps", "FY2026")] == (D("4.90"), D("5.00"))
    rev = [i for i in res.items if i.metric == "revenue" and i.period_key == "FY2026Q4"][0]
    assert rev.anchor.startswith("[Fourth Quarter Fiscal 2026 Outlook]")


def test_table_row_with_unknown_column_mapping_is_not_guessed():
    text = ("Fiscal 2026 Outlook\nQ4 FY2026 | FY2026\nGross margin | 45.0% - 46.0%\n")
    res = extract(text)
    assert len(res.items) == 1 and res.items[0].period_key is None
    assert "period_unresolved" in res.items[0].problems


def test_no_guidance_release_status():
    res = extract("Revenue was $1.1 billion, up 12% year over year. Net income was $200 million.")
    assert res.items == [] and res.status == "no_guidance_language"


# ---------------------------------------------------------------------------
# 변화 분류
# ---------------------------------------------------------------------------


def item(low, high, *, metric="revenue", period="FY2026", basis="unspecified", accession="A", at=T_NEW,
         unit="currency", currency="USD", shape="range", stated=None, flags=(), cik="0000000001"):
    return ee.GuidanceItem(
        cik=cik, accession=accession, acceptance_utc=at, source_url=None, metric=metric, basis=basis,
        period_key=period, period_raw=period, shape=shape, low=None if low is None else D(low),
        high=None if high is None else D(high), unit=unit, currency=currency, anchor="x", flags=tuple(flags),
        stated_action=stated)


def test_raised_lowered_maintained_by_midpoint():
    prev = item("1200", "1250", accession="P", at=T_OLD)  # 중간값 1225
    up = ee.compare_guidance(item("1250", "1300"), prev)  # 1275
    assert up.change == "raised" and up.mid_change == D("50")
    assert float(up.mid_change_pct) == pytest.approx(50 / 1225 * 100)
    down = ee.compare_guidance(item("1150", "1200"), prev)  # 1175
    assert down.change == "lowered" and down.mid_change == D("-50")
    same = ee.compare_guidance(item("1200", "1250"), prev)
    assert same.change == "maintained" and same.mid_change == D("0")


def test_same_midpoint_wider_range_is_maintained_with_width_flag():
    prev = item("1200", "1250", accession="P", at=T_OLD)
    res = ee.compare_guidance(item("1150", "1300"), prev)  # 중간값 1225 동일, 폭 50 -> 150
    assert res.change == "maintained"
    assert "width_changed" in res.flags
    assert (res.width_old, res.width_new) == (D("50"), D("150"))


def test_low_up_high_down_is_flagged_mixed_direction():
    prev = item("1000", "1400", accession="P", at=T_OLD)  # 1200
    res = ee.compare_guidance(item("1100", "1350"), prev)  # 1225: 하한 상승, 상한 하락
    assert res.change == "raised"
    assert "mixed_direction" in res.flags


def test_different_scale_spelling_compares_equal():
    prev = one("For fiscal 2026, we expect revenue of $1,200 million to $1,300 million.", acceptance=T_OLD,
               accession="P")
    cur = one("For fiscal 2026, we expect revenue of $1.2 billion to $1.3 billion.")
    assert ee.compare_guidance(cur, prev).change == "maintained"


def test_different_period_is_refused():
    prev = item("1200", "1250", period="FY2026Q3", accession="P", at=T_OLD)
    res = ee.compare_guidance(item("4800", "4900", period="FY2026"), prev)
    assert res.change == "unknown" and res.reason == "different_period"


def test_other_mismatches_are_refused():
    prev = item("1200", "1250", accession="P", at=T_OLD)
    assert ee.compare_guidance(item("1", "2", metric="eps", unit="per_share"), prev).reason == "different_metric"
    e_prev = item("1.2", "1.3", metric="eps", unit="per_share", basis="gaap", accession="P", at=T_OLD)
    assert ee.compare_guidance(item("1.3", "1.4", metric="eps", unit="per_share", basis="non_gaap"),
                               e_prev).reason == "basis_mismatch"
    assert ee.compare_guidance(item("1250", "1300", currency="EUR"), prev).reason == "unit_or_currency_mismatch"
    assert ee.compare_guidance(item("1250", "1300", cik="0000000002"), prev).reason == "different_company"
    later = item("1200", "1250", accession="P", at=datetime(2026, 8, 30, tzinfo=UTC))
    assert ee.compare_guidance(item("1250", "1300"), later).reason == "previous_not_before_current"


def test_revenue_basis_gaap_and_unspecified_are_same_but_non_gaap_differs():
    prev = item("1200", "1250", basis="gaap", accession="P", at=T_OLD)
    assert ee.compare_guidance(item("1250", "1300", basis="unspecified"), prev).change == "raised"
    assert ee.compare_guidance(item("1250", "1300", basis="non_gaap"), prev).reason == "basis_mismatch"


def test_initiated_requires_complete_history_or_issuer_wording():
    cur = item("1200", "1250")
    assert ee.compare_guidance(cur, None).change == "unknown"
    assert ee.compare_guidance(cur, None).reason == "no_previous_in_retrieved_history"
    assert ee.compare_guidance(cur, None, history_complete=True).change == "initiated"
    assert ee.compare_guidance(item("1200", "1250", stated="initiate"), None).change == "initiated"


def test_issuer_wording_conflict_becomes_unknown():
    prev = item("1200", "1250", accession="P", at=T_OLD)
    res = ee.compare_guidance(item("1150", "1200", stated="raise"), prev)
    assert res.change == "unknown" and res.reason.startswith("issuer_wording_conflicts")
    ok = ee.compare_guidance(item("1250", "1300", stated="raise"), prev)
    assert ok.change == "raised"


def test_withdrawn_and_reinstated():
    prev = item("1200", "1250", accession="P", at=T_OLD)
    withdrawn = item(None, None, shape="withdrawn", metric="all", unit=None, currency=None)
    assert ee.compare_guidance(withdrawn, prev).change == "withdrawn"
    withdrawn_prev = item(None, None, shape="withdrawn", accession="W", at=T_OLD, unit=None, currency=None)
    assert ee.compare_guidance(item("1200", "1250"), withdrawn_prev).change == "initiated"


def test_bound_and_range_are_not_compared():
    prev = item("500", None, shape="lower_bound", accession="P", at=T_OLD)
    assert ee.compare_guidance(item("500", "600"), prev).reason == "bound_type_mismatch"
    assert ee.compare_guidance(item("600", None, shape="lower_bound"), prev).change == "raised"


def test_find_previous_picks_latest_earlier_same_period_only():
    h1 = item("1000", "1100", accession="H1", at=datetime(2026, 1, 30, tzinfo=UTC))
    h2 = item("1100", "1200", accession="H2", at=datetime(2026, 4, 30, tzinfo=UTC))
    other_period = item("50", "60", period="FY2026Q3", accession="H3", at=datetime(2026, 5, 30, tzinfo=UTC))
    other_metric = item("1", "2", metric="eps", unit="per_share", accession="H4", at=datetime(2026, 6, 1, tzinfo=UTC))
    later = item("9999", "9999", accession="H5", at=datetime(2026, 9, 1, tzinfo=UTC))
    cur = item("1200", "1300", accession="CUR", at=T_NEW)
    assert ee.find_previous_guidance(cur, [h1, h2, other_period, other_metric, later, cur]) is h2
    assert ee.find_previous_guidance(cur, [other_period, other_metric]) is None


def test_compute_guidance_changes_end_to_end_from_text():
    old = extract("For fiscal 2026, the Company expects revenue of $4.7 to $4.8 billion and non-GAAP EPS of "
                  "$4.80 to $4.90.", acceptance=T_OLD, accession="OLD").items
    new = extract("The Company now expects fiscal 2026 revenue of $4.9 to $5.0 billion and non-GAAP EPS of "
                  "$4.80 to $4.90.").items
    changes = {c.current.metric: c.change for c in ee.compute_guidance_changes(new, old)}
    assert changes == {"revenue": "raised", "eps": "maintained"}


# ---------------------------------------------------------------------------
# 비교 정책 annual_same_fy_v1 (스펙 3절 '비교 정책', 2026-09-25)
# 기대값은 정책 정의에서 직접 계산한다: 방향은 연간 같은 FY 재발표끼리만, 분기·반기는 방향 없음.
# ---------------------------------------------------------------------------
T_Q1 = datetime(2026, 2, 26, 21, 5, tzinfo=UTC)  # 같은 FY 첫 발표
T_Q2 = datetime(2026, 5, 27, 20, 10, tzinfo=UTC)  # 같은 FY 재발표(직전)
T_Q3 = datetime(2026, 8, 26, 20, 15, tzinfo=UTC)  # 현재 발표


def test_period_type_classification():
    assert ee.period_type("FY2027") == "annual"
    assert ee.period_type("CY2026") == "annual"
    assert ee.period_type("YEND:2026-12-31") == "annual"
    assert ee.period_type("FY2027Q3") == "quarterly"
    assert ee.period_type("QEND:2026-09-30") == "quarterly"
    assert ee.period_type("FY2026H2") == "half_year"
    assert ee.period_type("PEND:2026-09-30") == "other"
    assert ee.period_type(None) is None


def _fy_history():
    first = item("40000", "41000", period="FY2027", accession="0000000001-26-000010", at=T_Q1)  # 중간값 40500
    prior = item("41000", "42000", period="FY2027", accession="0000000001-26-000020", at=T_Q2)  # 중간값 41500
    return first, prior


def test_same_fy_restatement_raised_lowered_maintained_with_evidence():
    first, prior = _fy_history()
    cur_acc = "0000000001-26-000030"
    cases = {("42000", "43000"): ("raised", D("1000")),  # 42500 - 41500
             ("40000", "41000"): ("lowered", D("-1000")),  # 40500 - 41500
             ("41000", "42000"): ("maintained", D("0"))}
    for (low, high), (want, delta) in cases.items():
        cur = item(low, high, period="FY2027", accession=cur_acc, at=T_Q3)
        (res,) = ee.compute_guidance_changes([cur], [first, prior])
        assert res.change == want and res.mid_change == delta
        assert res.reason == "midpoint_comparison"
        assert res.comparison_method == "annual_same_fy"
        assert res.period_type == "annual"
        assert res.policy == ee.COMPARISON_POLICY
        # 근거: 가장 최근의 더 이른 같은 FY 항목(prior)이지 첫 발표(first)가 아니다
        assert res.previous_accession == "0000000001-26-000020"
        assert res.previous_acceptance_utc == T_Q2
        assert res.previous_period_key == "FY2027"
        ev = res.evidence()
        assert ev["previous_accession"] == "0000000001-26-000020"
        assert ev["previous_acceptance_utc"] == T_Q2.isoformat()
        assert ev["current_accession"] == cur_acc and ev["comparison_method"] == "annual_same_fy"


def test_calendar_year_end_key_is_annual_and_comparable():
    prev = item("8.30", "8.45", metric="eps", unit="per_share", basis="non_gaap", period="YEND:2026-12-31",
                accession="P", at=T_Q2)
    cur = item("8.40", "8.55", metric="eps", unit="per_share", basis="non_gaap", period="YEND:2026-12-31",
               accession="C", at=T_Q3)
    (res,) = ee.compute_guidance_changes([cur], [prev])
    assert res.change == "raised" and res.mid_change == D("0.10")  # 8.475 - 8.375


def test_quarterly_guidance_never_gets_a_direction():
    # 같은 분기의 직전 값이 있어도(예: 실적표의 실제치가 가이던스처럼 추출된 경우) 방향을 내지 않는다.
    same_q_prev = item("15000", "15200", period="FY2026Q3", accession="P", at=T_Q2)
    cur = item("15800", "15800", shape="point", period="FY2026Q3", accession="C", at=T_Q3)
    (res,) = ee.compute_guidance_changes([cur], [same_q_prev])
    assert res.change == "unknown"
    assert res.reason == "quarterly_not_comparable" and res.reason_detail == "quarterly_not_comparable"
    assert res.previous is None and res.previous_accession is None  # 쓰지 않은 값은 근거로 남기지 않는다
    assert "same_period_previous_available" in res.flags
    assert res.comparison_method == "not_compared" and res.period_type == "quarterly"
    assert res.mid_change is None


def test_quarter_is_not_compared_with_the_previous_quarter():
    q2 = item("11000", "11100", period="FY2027Q2", accession="P", at=T_Q2)
    q3 = item("11420", "11500", period="FY2027Q3", accession="C", at=T_Q3)
    (res,) = ee.compute_guidance_changes([q3], [q2])
    assert res.change == "unknown" and res.reason == "quarterly_not_comparable"
    assert "same_period_previous_available" not in res.flags
    # QEND 키와 반기도 같은 원칙
    qend = item("1", "2", period="QEND:2026-09-30", accession="C", at=T_Q3)
    assert ee.compare_guidance(qend, None).reason == "quarterly_not_comparable"
    half = item("1", "2", period="FY2026H2", accession="C", at=T_Q3)
    assert ee.compare_guidance(half, None).reason == "half_year_not_comparable"
    # 분기는 '완전한 이력'이나 발행사 'initiate' 문구가 있어도 initiated 로 만들지 않는다
    assert ee.compare_guidance(q3, None, history_complete=True).change == "unknown"
    assert ee.compare_guidance(item("1", "2", period="FY2027Q3", stated="initiate"), None).change == "unknown"


def test_quarterly_withdrawal_is_still_withdrawn():
    w = item(None, None, shape="withdrawn", metric="all", unit=None, currency=None, period="FY2026Q3")
    res = ee.compare_guidance(w, None)
    assert res.change == "withdrawn" and res.comparison_method == "issuer_statement"


def test_no_prior_same_fy_keeps_legacy_reason_and_adds_detail():
    other_fy = item("40000", "41000", period="FY2026", accession="P", at=T_Q2)
    cur = item("42000", "43000", period="FY2027", accession="C", at=T_Q3)
    (res,) = ee.compute_guidance_changes([cur], [other_fy])
    assert res.change == "unknown"
    assert res.reason == "no_previous_in_retrieved_history"  # 기존 코드 유지(하위 호환)
    assert res.reason_detail == "no_prior_same_fy"
    # FY 와 CY 는 같은 연도 숫자여도 다른 기간이다
    cy = item("40000", "41000", period="CY2027", accession="P2", at=T_Q2)
    (res2,) = ee.compute_guidance_changes([cur], [cy])
    assert res2.reason_detail == "no_prior_same_fy"


def test_unit_currency_basis_mismatch_are_refused_with_detail():
    prev = item("1200", "1250", accession="P", at=T_OLD)
    unit = ee.compare_guidance(item("1250", "1300", unit="percent"), prev)
    assert (unit.change, unit.reason, unit.reason_detail) == ("unknown", "unit_or_currency_mismatch", "unit_mismatch")
    cur = ee.compare_guidance(item("1250", "1300", currency="EUR"), prev)
    assert (cur.change, cur.reason, cur.reason_detail) == ("unknown", "unit_or_currency_mismatch",
                                                           "currency_mismatch")
    e_prev = item("1.2", "1.3", metric="eps", unit="per_share", basis="gaap", accession="P", at=T_OLD)
    basis = ee.compare_guidance(item("1.3", "1.4", metric="eps", unit="per_share", basis="non_gaap"), e_prev)
    assert (basis.change, basis.reason_detail) == ("unknown", "basis_mismatch")
    # find_previous 는 basis 가 다른 항목을 직전 값으로 고르지 않는다 -> 비교 없이 no_prior_same_fy
    (via_history,) = ee.compute_guidance_changes(
        [item("1.3", "1.4", metric="eps", unit="per_share", basis="non_gaap")], [e_prev])
    assert via_history.change == "unknown" and via_history.reason_detail == "no_prior_same_fy"


def test_finished_year_next_to_next_year_guidance_is_not_compared():
    # 같은 발표에 FY2027 가이던스와 FY2026 수치(끝난 연도 실적 열)가 함께 있으면 FY2026 은 비교하지 않는다.
    prev_fy26 = item("60000", "61000", period="FY2026", accession="P", at=T_Q2)
    acc = "0000000001-26-000040"
    fy26_actual = item("63300", "63300", shape="point", period="FY2026", accession=acc, at=T_Q3)
    fy27_guide = item("72200", "73400", period="FY2027", accession=acc, at=T_Q3)
    fy30_target = item("90000", "90000", shape="point", period="FY2030", accession=acc, at=T_Q3)
    res = {c.current.period_key: c for c in
           ee.compute_guidance_changes([fy26_actual, fy27_guide, fy30_target], [prev_fy26])}
    assert res["FY2026"].change == "unknown"
    assert res["FY2026"].reason == "annual_period_superseded_in_release"
    assert "later_fy_in_release:FY2027" in res["FY2026"].flags
    # FY2030(+3년)은 장기 목표일 수 있어 FY2027 을 밀어내지 않는다 -> FY2027 은 직전 이력이 없어 no_prior_same_fy
    assert res["FY2027"].reason_detail == "no_prior_same_fy"


def test_legacy_fields_unchanged_for_directional_result():
    prev = item("1200", "1250", accession="P", at=T_OLD)
    res = ee.compare_guidance(item("1250", "1300"), prev)
    assert (res.change, res.reason, res.previous) == ("raised", "midpoint_comparison", prev)
    assert (res.width_old, res.width_new) == (D("50"), D("50"))
    # 새 필드 없이 만든 GuidanceChange(기존 호출부)도 그대로 동작한다
    bare = ee.GuidanceChange(change="raised", reason="midpoint_comparison", current=res.current)
    assert bare.reason_detail is None and bare.previous_accession is None
    assert bare.evidence()["reason_detail"] == "midpoint_comparison"
