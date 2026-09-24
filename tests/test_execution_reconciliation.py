"""core/execution_reconciliation.py 테스트.

실제 네트워크 호출은 없다(가짜 session 주입). 기대값은 요구사항에서 손계산으로 독립 산출했다.
"""
from __future__ import annotations

import math

import pytest
import requests

from core.execution_reconciliation import (
    MIN_SAMPLE_FOR_REPRESENTATIVE,
    STATUS_FILLED,
    STATUS_NOT_PLACED,
    STATUS_PARTIAL,
    STATUS_REJECTED,
    STATUS_UNFILLED,
    AlpacaFillReader,
    FillQueryError,
    build_report,
    classify_fill,
    compare_with_cost_assumptions,
    normalize_fills,
    reconcile_orders,
    slippage_bps,
    summarize_slippage,
)
from core.trade_ledger import COST_SCENARIOS_BPS, LEDGER_COLUMNS


# ----------------------------------------------------------------------------- 가짜 HTTP
class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(str(self.status_code))
            err.response = type("R", (), {"status_code": self.status_code})()
            raise err


class FakeSession:
    """요청을 기록하고 미리 준비한 응답을 순서대로 돌려준다."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, params=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": dict(params or {}), "headers": headers})
        if not self.responses:
            raise AssertionError("예상보다 많은 요청")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def order(cid, symbol="AAPL", side="buy", qty="10", filled_qty="10", price="100.05",
          status="filled", submitted="2026-09-01T13:30:00Z", filled="2026-09-01T13:30:02Z", oid=None):
    return {"id": oid or f"broker-{cid}", "client_order_id": cid, "symbol": symbol, "side": side,
            "qty": qty, "filled_qty": filled_qty, "filled_avg_price": price, "status": status,
            "submitted_at": submitted, "filled_at": filled}


def reader(responses, **kwargs):
    return AlpacaFillReader("k", "s", session=FakeSession(responses), sleep=lambda _s: None, **kwargs)


# ----------------------------------------------------------------------------- (b) 슬리피지 손계산
def test_slippage_bps_hand_calculated():
    # 매수: 예상 100.00 -> 실제 100.05 = 0.05/100.00 = 0.0005 = 5bp (불리 = 양수)
    assert slippage_bps(100.00, 100.05, "BUY") == pytest.approx(5.0)
    # 매수가 유리하게 체결되면 음수: 99.98 -> -0.02/100 = -2bp
    assert slippage_bps(100.00, 99.98, "BUY") == pytest.approx(-2.0)
    # 매도: 예상 200.00 -> 실제 199.80 = 0.20/200.00 = 0.001 = 10bp (불리 = 양수)
    assert slippage_bps(200.00, 199.80, "SELL") == pytest.approx(10.0)
    # 매도가 유리하게 높게 체결: 200.10 -> -0.10/200 = -5bp
    assert slippage_bps(200.00, 200.10, "SELL") == pytest.approx(-5.0)
    # 기준가 없음/0/미지의 side -> 계산하지 않는다
    assert slippage_bps(None, 100.0, "BUY") is None
    assert slippage_bps(0.0, 100.0, "BUY") is None
    assert slippage_bps(100.0, 100.0, "") is None


def test_normalized_ledger_keeps_trade_ledger_schema_and_costs():
    cid = "q-aaaa-bbbb-r00001-00-AAPL"
    expectations = {cid: {"expected_price": 100.00, "expected_quantity": 10.0, "side": "BUY"}}
    frame = normalize_fills([order(cid)], expectations)
    assert list(frame.columns)[:len(LEDGER_COLUMNS)] == LEDGER_COLUMNS
    row = frame.iloc[0]
    assert row["side"] == "BUY"
    assert row["quantity"] == pytest.approx(10.0)
    assert row["ref_open"] == pytest.approx(100.00)
    assert row["fill_price"] == pytest.approx(100.05)
    # 손계산: 명목 10 * 100.05 = 1000.5, 슬리피지 금액 10 * (100.05 - 100.00) = 0.5
    assert row["notional"] == pytest.approx(1000.5)
    assert row["slippage_cost"] == pytest.approx(0.5)
    assert row["fee"] == pytest.approx(0.0) and row["tax"] == pytest.approx(0.0)
    # 실계정에서는 체결 1건 단위 현금/NAV 를 재구성하지 않는다 -> NaN (컬럼은 유지)
    assert math.isnan(row["cash_after"]) and math.isnan(row["nav_after"])


def test_normalized_ledger_sell_slippage_sign():
    cid = "q-aaaa-bbbb-r00001-01-MSFT"
    frame = normalize_fills(
        [order(cid, symbol="MSFT", side="sell", qty="5", filled_qty="5", price="199.80")],
        {cid: {"expected_price": 200.00}})
    # 매도 손계산: 5 * (200.00 - 199.80) = 1.0 (불리 = 양수 비용)
    assert frame.iloc[0]["slippage_cost"] == pytest.approx(1.0)


# ----------------------------------------------------------------------------- (a) 매칭
def test_reconcile_matches_by_client_order_id():
    cid_a, cid_b = "q-x-y-r00007-00-AAPL", "q-x-y-r00007-01-MSFT"
    expectations = {
        cid_a: {"expected_price": 100.00, "expected_quantity": 10.0, "symbol": "AAPL", "side": "BUY"},
        cid_b: {"expected_price": 200.00, "expected_quantity": 5.0, "symbol": "MSFT", "side": "SELL"},
    }
    orders = [
        order(cid_a),
        order(cid_b, symbol="MSFT", side="sell", qty="5", filled_qty="5", price="199.80",
              submitted="2026-09-01T13:30:00Z", filled="2026-09-01T13:30:30Z"),
        order("q-other-run-99-ZZZ", symbol="ZZZ"),  # 이 대조 대상이 아닌 주문
    ]
    result = reconcile_orders(orders, expectations)
    by_cid = {r["client_order_id"]: r for r in result["rows"]}
    assert by_cid[cid_a]["slippage_bp"] == pytest.approx(5.0)
    assert by_cid[cid_b]["slippage_bp"] == pytest.approx(10.0)
    assert by_cid[cid_a]["fill_delay_seconds"] == pytest.approx(2.0)
    assert by_cid[cid_b]["fill_delay_seconds"] == pytest.approx(30.0)
    assert by_cid[cid_a]["quantity_fill_ratio"] == pytest.approx(1.0)
    assert [u["client_order_id"] for u in result["unmatched_actual"]] == ["q-other-run-99-ZZZ"]


def test_expected_order_missing_at_broker_is_not_placed():
    cid = "q-x-y-r00008-00-AAPL"
    result = reconcile_orders([], {cid: {"expected_price": 100.0, "symbol": "AAPL", "side": "BUY"}})
    assert result["rows"] == []
    assert result["unmatched_expected"][0]["fill_status"] == STATUS_NOT_PLACED
    assert result["counts"][STATUS_NOT_PLACED] == 1


# ----------------------------------------------------------------------------- (c) 분류
def test_classification_partial_unfilled_rejected():
    assert classify_fill(order("c1")) == STATUS_FILLED
    partial = order("c2", qty="10", filled_qty="4", status="partially_filled")
    assert classify_fill(partial) == STATUS_PARTIAL
    # 장중 취소됐지만 일부 체결된 주문도 부분체결
    assert classify_fill(order("c3", qty="10", filled_qty="4", status="canceled")) == STATUS_PARTIAL
    # 접수만 되고 체결 없음
    assert classify_fill(order("c4", filled_qty="0", price=None, status="new", filled=None)) == STATUS_UNFILLED
    # 거절 (체결 0)
    assert classify_fill(order("c5", filled_qty="0", price=None, status="rejected", filled=None)) == STATUS_REJECTED
    # 취소 + 체결 0 -> 거절 계열
    assert classify_fill(order("c6", filled_qty="0", price=None, status="expired", filled=None)) == STATUS_REJECTED


def test_reconcile_counts_each_classification_and_partial_ratio():
    exp = {f"c{i}": {"expected_price": 100.0, "expected_quantity": 10.0, "symbol": "AAPL", "side": "BUY"}
           for i in range(1, 5)}
    orders = [
        order("c1"),
        order("c2", qty="10", filled_qty="4", price="100.05", status="partially_filled"),
        order("c3", filled_qty="0", price=None, status="new", filled=None),
        order("c4", filled_qty="0", price=None, status="rejected", filled=None),
    ]
    result = reconcile_orders(orders, exp)
    counts = result["counts"]
    assert counts[STATUS_FILLED] == 1 and counts[STATUS_PARTIAL] == 1
    assert counts[STATUS_UNFILLED] == 1 and counts[STATUS_REJECTED] == 1
    partial_row = next(r for r in result["rows"] if r["client_order_id"] == "c2")
    assert partial_row["quantity_fill_ratio"] == pytest.approx(0.4)  # 4 / 10
    unfilled_row = next(r for r in result["rows"] if r["client_order_id"] == "c3")
    assert unfilled_row["slippage_bp"] is None and unfilled_row["fill_delay_seconds"] is None


# ----------------------------------------------------------------------------- (d) 표본 부족
def _rows(n, bp=5.0, side="BUY", symbol="AAPL"):
    return [{"client_order_id": f"c{i}", "symbol": symbol, "side": side, "fill_status": STATUS_FILLED,
             "slippage_bp": bp, "fill_delay_seconds": 2.0, "quantity_fill_ratio": 1.0} for i in range(n)]


def test_small_sample_claims_no_representative_value():
    summary = summarize_slippage(_rows(5))
    assert summary["overall"]["status"] == "insufficient_sample"
    assert summary["overall"]["n"] == 5
    for key in ("median_bp", "p25_bp", "p75_bp", "p10_bp", "p90_bp"):
        assert summary["overall"][key] is None
    assert summary["overall"]["observed_max_bp"] == pytest.approx(5.0)
    # 매도 표본은 0건이어도 같은 규칙
    assert summary["by_side"]["SELL"]["status"] == "insufficient_sample"
    assert summary["by_side"]["SELL"]["n"] == 0
    # 표본이 부족하면 가정 비용과의 비교에도 대표값을 넣지 않는다
    comparison = compare_with_cost_assumptions(summary)
    assert comparison["comparable"] is False
    assert all(row["difference_bps"] is None for row in comparison["table"])


def test_sufficient_sample_reports_median_and_difference_table():
    # 30건 이상이면 대표값을 낸다. 전부 5bp 이므로 중앙값 = 5.0 (손계산)
    rows = _rows(MIN_SAMPLE_FOR_REPRESENTATIVE)
    summary = summarize_slippage(rows)
    assert summary["overall"]["status"] == "ok"
    assert summary["overall"]["median_bp"] == pytest.approx(5.0)
    comparison = compare_with_cost_assumptions(summary)
    table = {row["scenario"]: row for row in comparison["table"]}
    # 손계산: 가정 5bp 시나리오의 슬리피지 가정은 3.0bp -> 5.0 - 3.0 = +2.0
    assert table["5bp"]["assumed_slippage_bps"] == pytest.approx(COST_SCENARIOS_BPS["5bp"]["slippage_bps"])
    assert table["5bp"]["difference_bps"] == pytest.approx(2.0)
    # 25bp 시나리오는 15.0bp 가정 -> 5.0 - 15.0 = -10.0
    assert table["25bp"]["difference_bps"] == pytest.approx(-10.0)
    # 비교는 차이만 보여준다: 우열 판단 필드는 없다
    assert set(table["5bp"]) == {"scenario", "assumed_slippage_bps", "assumed_fee_bps",
                                 "measured_median_slippage_bps", "difference_bps"}


def test_median_of_mixed_sample_is_hand_checked():
    # 15건 4bp + 15건 6bp = 30건, 정렬 시 중앙 두 값이 4와 6 -> 중앙값 5.0
    rows = _rows(15, bp=4.0) + _rows(15, bp=6.0)
    summary = summarize_slippage(rows)
    assert summary["overall"]["median_bp"] == pytest.approx(5.0)
    assert summary["overall"]["p25_bp"] == pytest.approx(4.0)
    assert summary["overall"]["p75_bp"] == pytest.approx(6.0)


def test_by_side_and_by_symbol_are_separated():
    rows = _rows(3, bp=5.0, side="BUY", symbol="AAPL") + _rows(2, bp=9.0, side="SELL", symbol="MSFT")
    summary = summarize_slippage(rows)
    assert summary["by_side"]["BUY"]["n"] == 3 and summary["by_side"]["SELL"]["n"] == 2
    assert set(summary["by_symbol"]) == {"AAPL", "MSFT"}
    assert summary["by_symbol"]["MSFT"]["n"] == 2


# ----------------------------------------------------------------------------- (e) 페이지네이션
def test_closed_order_pagination_walks_pages_and_dedupes():
    page1 = [order(f"c{i}", submitted=f"2026-09-01T13:0{i}:00Z", oid=f"o{i}") for i in range(3)]
    page2 = [page1[-1]] + [order("c9", submitted="2026-09-01T13:09:00Z", oid="o9")]  # 중복 1건 포함
    session_responses = [FakeResponse(page1), FakeResponse(page2)]
    r = reader(session_responses)
    result = r.list_closed_orders(page_limit=3)
    assert [o["id"] for o in result["orders"]] == ["o0", "o1", "o2", "o9"]  # 중복 제거
    assert result["pages"] == 2 and result["partial"] is False
    # 두 번째 요청은 첫 페이지의 마지막 submitted_at 이후부터 조회한다
    assert r._session.calls[1]["params"]["after"] == "2026-09-01T13:02:00Z"
    assert r._session.calls[0]["params"]["status"] == "closed"


def test_pagination_stops_when_page_is_short():
    r = reader([FakeResponse([order("c1")])])
    result = r.list_closed_orders(page_limit=500)
    assert result["pages"] == 1 and len(result["orders"]) == 1 and result["errors"] == []


def test_activities_pagination_uses_page_token():
    page1 = [{"id": f"a{i}", "activity_type": "FILL"} for i in range(2)]
    r = reader([FakeResponse(page1), FakeResponse([{"id": "a9", "activity_type": "FILL"}])])
    result = r.list_fill_activities(page_size=2)
    assert len(result["activities"]) == 3 and result["pages"] == 2
    assert r._session.calls[1]["params"]["page_token"] == "a1"


def test_rate_limit_is_retried_then_succeeds():
    r = reader([FakeResponse(None, status_code=429), FakeResponse([order("c1")])])
    result = r.list_closed_orders(page_limit=500)
    assert len(result["orders"]) == 1 and result["errors"] == []


def test_partial_failure_keeps_earlier_pages():
    page1 = [order(f"c{i}", submitted=f"2026-09-01T13:0{i}:00Z", oid=f"o{i}") for i in range(2)]
    fails = [FakeResponse(None, status_code=503)] * 3
    r = reader([FakeResponse(page1)] + fails, max_retries=3)
    result = r.list_closed_orders(page_limit=2)
    assert len(result["orders"]) == 2
    assert result["partial"] is True and result["errors"]


def test_auth_error_raises_without_leaking_credentials():
    r = reader([FakeResponse(None, status_code=401)])
    with pytest.raises(FillQueryError) as exc:
        r.list_closed_orders()
    assert "401" in str(exc.value)
    assert "APCA" not in str(exc.value) and "secret" not in str(exc.value).lower()


def test_reader_requires_credentials():
    with pytest.raises(ValueError):
        AlpacaFillReader("", "")


def test_no_network_call_without_explicit_query():
    r = reader([])  # 응답을 하나도 주지 않아도 생성만으로는 요청이 없다
    assert r._session.calls == []


# ----------------------------------------------------------------------------- 리포트 전체
def test_build_report_is_self_describing_and_honest_about_sample():
    cid = "q-x-y-r00010-00-AAPL"
    report = build_report([order(cid)], {cid: {"expected_price": 100.00, "expected_quantity": 10.0,
                                               "symbol": "AAPL", "side": "BUY"}})
    assert report["counts"][STATUS_FILLED] == 1
    assert report["rows"][0]["slippage_bp"] == pytest.approx(5.0)
    assert report["slippage_summary"]["overall"]["status"] == "insufficient_sample"
    assert report["cost_assumption_comparison"]["comparable"] is False
    assert report["ledger_columns"][:len(LEDGER_COLUMNS)] == LEDGER_COLUMNS


def test_build_report_without_expectations_still_classifies():
    report = build_report([order("c1"), order("c2", filled_qty="0", price=None, status="rejected", filled=None)])
    assert report["counts"][STATUS_FILLED] == 1 and report["counts"][STATUS_REJECTED] == 1
    assert all(row["slippage_bp"] is None for row in report["rows"])  # 기준가가 없으면 슬리피지 미계산
