"""core/guru_tracker.py 단위 테스트 (모듈 D: 거장 포트폴리오 추종).

네트워크(SEC EDGAR/ARK/yfinance)를 타지 않도록, DB 저장/조회 로직(sync 이후 단계)만
합성 데이터로 검증한다. 실제 13F/ARK CSV 파싱 및 SEC EDGAR 연동은 이 환경에서
실제 네트워크 호출로 별도 확인했다(과제 설명 참고).
"""

from contextlib import contextmanager

import pytest

import core.guru_tracker as guru_tracker
from core.models import GuruHolding


@pytest.fixture()
def patched_session(db_session, monkeypatch):
    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(guru_tracker, "get_session", _fake_get_session)
    return db_session


def _make_holding_row(name, ticker, weight):
    return guru_tracker.HoldingRow(ticker=ticker, name=name, shares=1000.0, value=1_000_000.0, weight_pct=weight)


def test_sync_guru_holdings_replaces_previous_snapshot(patched_session, monkeypatch):
    calls = {"n": 0}

    def _fake_fetch(cik, resolve_tickers=True):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_make_holding_row("APPLE INC", "AAPL", 50.0)], "2024-05-15"
        return [_make_holding_row("MSFT CORP", "MSFT", 60.0)], "2024-08-14"

    monkeypatch.setattr(guru_tracker, "fetch_latest_13f_holdings", _fake_fetch)

    info1 = guru_tracker.sync_guru_holdings("워런 버핏")
    assert info1["holding_count"] == 1
    assert info1["resolved_ticker_count"] == 1

    holdings = guru_tracker.get_guru_holdings("워런 버핏")
    assert [h["ticker"] for h in holdings] == ["AAPL"]

    # 재동기화하면 이전 스냅샷은 지워지고 최신 결과만 남아야 한다.
    info2 = guru_tracker.sync_guru_holdings("워런 버핏")
    assert info2["filing_date"] == "2024-08-14"
    holdings2 = guru_tracker.get_guru_holdings("워런 버핏")
    assert [h["ticker"] for h in holdings2] == ["MSFT"]


def test_sync_guru_holdings_rejects_unknown_guru(patched_session):
    with pytest.raises(ValueError):
        guru_tracker.sync_guru_holdings("존재하지않는거장")


def test_sync_ark_daily_uses_ark_fetcher(patched_session, monkeypatch):
    def _fake_ark_fetch(fund_ticker):
        return [_make_holding_row("TESLA INC", "TSLA", 10.0)], "2024-06-01"

    monkeypatch.setattr(guru_tracker, "fetch_ark_fund_holdings", _fake_ark_fetch)

    info = guru_tracker.sync_guru_holdings("캐시 우드")
    assert info["holding_count"] == 1
    assert "ARKK" in info["fund_name"]

    holdings = guru_tracker.get_guru_holdings("캐시 우드")
    assert holdings[0]["ticker"] == "TSLA"


def test_unresolved_ticker_stored_as_none_with_issuer_name(patched_session, monkeypatch):
    def _fake_fetch(cik, resolve_tickers=True):
        return [_make_holding_row("SOME PREFERRED SHARE CLASS", None, 5.0)], "2024-05-15"

    monkeypatch.setattr(guru_tracker, "fetch_latest_13f_holdings", _fake_fetch)

    guru_tracker.sync_guru_holdings("워런 버핏")
    holdings = guru_tracker.get_guru_holdings("워런 버핏")
    assert holdings[0]["ticker"] is None
    assert holdings[0]["issuer_name"] == "SOME PREFERRED SHARE CLASS"


def test_get_common_holdings_intersection(patched_session):
    patched_session.add_all(
        [
            GuruHolding(guru_name="A", ticker="AAPL", weight_pct=10.0, fund_name="FundA"),
            GuruHolding(guru_name="A", ticker="MSFT", weight_pct=5.0, fund_name="FundA"),
            GuruHolding(guru_name="B", ticker="AAPL", weight_pct=20.0, fund_name="FundB"),
            GuruHolding(guru_name="B", ticker="GOOG", weight_pct=15.0, fund_name="FundB"),
            # 티커 미확인 종목은 교집합 계산에서 제외되어야 한다.
            GuruHolding(guru_name="A", ticker=None, issuer_name="UNRESOLVED CO", weight_pct=1.0, fund_name="FundA"),
        ]
    )
    patched_session.commit()

    common = guru_tracker.get_common_holdings(["A", "B"])
    assert len(common) == 1
    assert common[0]["ticker"] == "AAPL"
    assert common[0]["guru_count"] == 2
    assert common[0]["total_weight"] == pytest.approx(30.0)


def test_get_common_holdings_requires_at_least_two_gurus(patched_session):
    assert guru_tracker.get_common_holdings(["A"]) == []
    assert guru_tracker.get_common_holdings([]) == []


def test_custom_guru_management(tmp_path, monkeypatch):
    custom_file = tmp_path / "custom_gurus.json"
    monkeypatch.setattr(guru_tracker, "CUSTOM_GURU_FILE", custom_file)

    assert "새거장" not in guru_tracker.get_all_gurus()

    guru_tracker.add_custom_guru("새거장", "1234567890", "새펀드")
    all_gurus = guru_tracker.get_all_gurus()
    assert "새거장" in all_gurus
    assert all_gurus["새거장"]["cik"] == "1234567890"
    assert guru_tracker.is_custom_guru("새거장")

    guru_tracker.remove_custom_guru("새거장")
    assert "새거장" not in guru_tracker.get_all_gurus()


def test_add_custom_guru_rejects_duplicate_of_default(tmp_path, monkeypatch):
    custom_file = tmp_path / "custom_gurus.json"
    monkeypatch.setattr(guru_tracker, "CUSTOM_GURU_FILE", custom_file)

    with pytest.raises(ValueError):
        guru_tracker.add_custom_guru("워런 버핏", "0001067983", "Berkshire")


def test_add_custom_guru_rejects_blank_input(tmp_path, monkeypatch):
    custom_file = tmp_path / "custom_gurus.json"
    monkeypatch.setattr(guru_tracker, "CUSTOM_GURU_FILE", custom_file)

    with pytest.raises(ValueError):
        guru_tracker.add_custom_guru("", "0001067983", "펀드")
    with pytest.raises(ValueError):
        guru_tracker.add_custom_guru("이름", "", "펀드")


def test_resolve_ticker_uses_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "issuer_ticker_cache.json"
    monkeypatch.setattr(guru_tracker, "TICKER_CACHE_FILE", cache_file)

    call_count = {"n": 0}

    class _FakeSearch:
        def __init__(self, query, max_results=5):
            call_count["n"] += 1
            self.quotes = [{"symbol": "AAPL", "quoteType": "EQUITY", "exchange": "NMS"}]

    import sys
    import types

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Search = _FakeSearch
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    t1 = guru_tracker.resolve_ticker("APPLE INC")
    t2 = guru_tracker.resolve_ticker("apple inc")  # 대소문자만 다름 -> 캐시 히트

    assert t1 == "AAPL"
    assert t2 == "AAPL"
    assert call_count["n"] == 1  # 두 번째 호출은 캐시에서 바로 반환


def test_parse_infotable_xml_aggregates_by_issuer():
    xml_bytes = b"""<?xml version="1.0"?>
    <informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
      <infoTable>
        <nameOfIssuer>APPLE INC</nameOfIssuer>
        <value>1000</value>
        <shrsOrPrnAmt><sshPrnamt>100</sshPrnamt></shrsOrPrnAmt>
      </infoTable>
      <infoTable>
        <nameOfIssuer>APPLE INC</nameOfIssuer>
        <value>500</value>
        <shrsOrPrnAmt><sshPrnamt>50</sshPrnamt></shrsOrPrnAmt>
      </infoTable>
      <infoTable>
        <nameOfIssuer>MSFT CORP</nameOfIssuer>
        <value>2000</value>
        <shrsOrPrnAmt><sshPrnamt>200</sshPrnamt></shrsOrPrnAmt>
      </infoTable>
    </informationTable>"""

    rows = guru_tracker._parse_infotable_xml(xml_bytes)
    by_name = {r.name: r for r in rows}

    assert by_name["APPLE INC"].shares == 150.0
    assert by_name["APPLE INC"].value == 1_500_000.0  # value 단위는 천달러 -> *1000
    assert by_name["MSFT CORP"].value == 2_000_000.0

    total = sum(r.value for r in rows)
    assert by_name["MSFT CORP"].weight_pct == pytest.approx(2_000_000 / total * 100)
