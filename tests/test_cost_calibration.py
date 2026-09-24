"""core/cost_calibration.py 테스트. 네트워크 없음(전부 mock). 기대값은 종이 계산 하드코딩."""

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import core.cost_calibration as cc
from core.trade_ledger import run_cost_scenarios, run_ledger_backtest


def _df():
    idx = pd.bdate_range("2024-01-01", periods=4)
    return pd.DataFrame({"Open": [100, 110, 120, 90.0], "Close": [100, 120, 100, 90.0]}, index=idx)


def _pos():
    return pd.Series([1, 1, 0, 0], index=_df().index, dtype=float)


def _orders(n_buy, n_sell, buy_px=100.20, sell_px=99.90):
    """기준가(시가) 100.00. 매수 100.20 -> +20bp, 매도 99.90 -> +10bp (불리할수록 양수)."""
    orders, exp = [], {}
    for i in range(n_buy + n_sell):
        side = "buy" if i < n_buy else "sell"
        cid = f"c{i}"
        orders.append({"id": f"o{i}", "client_order_id": cid, "symbol": "AAPL", "side": side,
                       "status": "filled", "qty": "1", "filled_qty": "1",
                       "filled_avg_price": str(buy_px if side == "buy" else sell_px),
                       "submitted_at": "2026-09-01T13:30:00Z", "filled_at": "2026-09-01T13:30:05Z"})
        exp[cid] = {"expected_price": 100.0}
    return orders, exp


def test_insufficient_sample_returns_none_with_reason_and_n():
    orders, exp = _orders(10, 10)  # 20건 < 30
    r = cc.build_calibration_from_orders(orders, exp)
    assert r["status"] == "insufficient_sample"
    assert r["reason"] == "insufficient_sample"
    assert r["scenario"] is None
    assert r["n"] == 20
    assert r["stats"]["overall"]["median_bp"] is None


def test_side_split_medians_from_hand_calc():
    orders, exp = _orders(30, 30)
    r = cc.build_calibration_from_orders(orders, exp)
    assert r["status"] == "ok" and r["n"] == 60
    sc = r["scenario"]
    assert sc["side_split"] is True
    assert sc["buy_slippage_bps"] == pytest.approx(20.0, abs=1e-6)
    assert sc["sell_slippage_bps"] == pytest.approx(10.0, abs=1e-6)
    assert sc["fee_bps"] == 0.0
    assert r["stats"]["BUY"]["p75_bp"] == pytest.approx(20.0, abs=1e-6)
    assert r["stats"]["SELL"]["p90_bp"] == pytest.approx(10.0, abs=1e-6)
    assert r["label"] == "measured vs assumed"


def test_one_side_short_uses_overall_median_flagged():
    orders, exp = _orders(15, 15)  # 전체 30, 방향별 15 -> 전체 중앙값(=15bp: 절반 20, 절반 10)
    r = cc.build_calibration_from_orders(orders, exp)
    assert r["status"] == "ok"
    assert r["scenario"]["side_split"] is False
    assert r["scenario"]["slippage_bps"] == pytest.approx(15.0, abs=1e-6)
    assert r["scenario"]["buy_slippage_bps"] == pytest.approx(15.0, abs=1e-6)


def test_measured_scenario_nav_hand_calc():
    orders, exp = _orders(30, 30)
    cal = cc.build_calibration_from_orders(orders, exp)
    res = run_cost_scenarios(_df(), _pos(), initial_cash=1100.0, measured_calibration=cal)
    # 종이 계산: 매수 체결가 110*1.002=110.22, 수량 1100/110.22, 매도 90*(1-0.001)=89.91
    # 최종 NAV = 1100*89.91/110.22 = 897.30539; 0bp 최종 = 1100/110*90 = 900
    assert res["measured"].nav.iloc[-1] == pytest.approx(897.30539, abs=1e-4)
    assert res["0bp"].nav.iloc[-1] == pytest.approx(900.0)
    assert res["0bp"].nav.iloc[-1] - res["measured"].nav.iloc[-1] == pytest.approx(2.69461, abs=1e-4)
    p = res["measured"].params
    assert p["scenario_label"] == "measured vs assumed"
    assert p["measured_sample_n"] == 60
    assert p["measured_generated_at"] == cal["generated_at"]
    assert p["measured_side_split"] is True
    # 슬리피지 비용 원장 합: 수량*시가*방향별 비율. 매수 q*110*0.002, 매도 q*90*0.001, q=1100/110.22
    q = 1100 / 110.22
    assert res["measured"].total_slippage_cost == pytest.approx(q * 110 * 0.002 + q * 90 * 0.001, rel=1e-9)


def test_measured_absent_when_insufficient_or_none():
    orders, exp = _orders(5, 5)
    cal = cc.build_calibration_from_orders(orders, exp)
    for arg in (None, cal, {"status": "unavailable"}):
        assert "measured" not in run_cost_scenarios(_df(), _pos(), 1100.0, measured_calibration=arg)


def test_default_run_cost_scenarios_unchanged_bit_identical():
    a = run_cost_scenarios(_df(), _pos(), 1100.0, tax_bps=5)
    b = run_cost_scenarios(_df(), _pos(), 1100.0, tax_bps=5, measured_calibration=None)
    assert list(a) == ["0bp", "5bp", "10bp", "25bp"] == list(b)
    for k in a:
        assert a[k].nav.equals(b[k].nav)
        assert a[k].params == b[k].params
        assert "scenario_label" not in a[k].params
    # 방향별 인자 기본값은 slippage_bps 와 동일 동작
    x = run_ledger_backtest(_df(), _pos(), 1100.0, fee_bps=4, slippage_bps=6)
    y = run_ledger_backtest(_df(), _pos(), 1100.0, fee_bps=4, slippage_bps=6,
                            buy_slippage_bps=6, sell_slippage_bps=6)
    assert x.nav.equals(y.nav)


def test_negative_measured_slippage_is_allowed_for_side_override():
    r = run_ledger_backtest(_df(), _pos(), 1100.0, buy_slippage_bps=-10.0, sell_slippage_bps=0.0)
    # 종이 계산: day1 목표 10주 @109.89(=110*0.999) -> 현금 1.1. day2 시가 120: 평가 1201.1,
    # 목표 10.0091667주 -> 0.0091667주 추가 @119.88 -> 현금 0.0011. day3 매도 10.0091667주 @90 = 900.825
    # -> 최종 900.825 + 0.0011 = 900.8261 (음수 슬리피지 = 기준가보다 유리한 체결)
    assert r.nav.iloc[-1] == pytest.approx(900.8261, abs=1e-4)
    assert r.ledger.loc[0, "fill_price"] == pytest.approx(109.89)


def test_refresh_without_keys_is_unavailable_no_exception_no_file(monkeypatch, tmp_path):
    monkeypatch.delenv(cc.KEY_ENV, raising=False)
    monkeypatch.delenv(cc.SECRET_ENV, raising=False)
    target = tmp_path / "cal.json"
    r = cc.refresh_cost_calibration(save_path=target)
    assert r["status"] == "unavailable" and r["reason"] == "missing_credentials"
    assert not target.exists()


def test_refresh_fetch_failure_is_unavailable_and_never_leaks_secret(monkeypatch, tmp_path):
    monkeypatch.setenv(cc.KEY_ENV, "KEY-SENTINEL-123")
    monkeypatch.setenv(cc.SECRET_ENV, "SECRET-SENTINEL-456")

    class Boom:
        def __init__(self, *a, **k):
            pass
        list_closed_orders = None

        @classmethod
        def from_env(cls, **k):
            raise ConnectionError("network down")

    monkeypatch.setattr(cc, "AlpacaFillReader", Boom)
    r = cc.refresh_cost_calibration(save_path=tmp_path / "c.json")
    assert r["status"] == "unavailable"
    assert "SENTINEL" not in json.dumps(r)


def test_refresh_ok_saves_json_and_load_marks_stale(monkeypatch, tmp_path):
    monkeypatch.setenv(cc.KEY_ENV, "KEY-SENTINEL-123")
    monkeypatch.setenv(cc.SECRET_ENV, "SECRET-SENTINEL-456")
    orders, exp = _orders(30, 30)

    class FakeReader:
        @classmethod
        def from_env(cls, **k):
            return cls()

        def list_closed_orders(self, **k):
            return {"orders": orders, "partial": False, "errors": [], "pages": 1}

    monkeypatch.setattr(cc, "AlpacaFillReader", FakeReader)
    monkeypatch.setattr(cc, "_fill_reference_opens", lambda o: (exp, []))
    target = tmp_path / "sub" / "cal.json"
    r = cc.refresh_cost_calibration(save_path=target)
    assert r["status"] == "ok" and r["saved"] is True and target.exists()
    raw = target.read_text(encoding="utf-8")
    assert "SENTINEL" not in raw
    fresh = cc.load_cost_calibration(target)
    assert fresh["stale"] is False and fresh["scenario"]["buy_slippage_bps"] == pytest.approx(20.0, abs=1e-6)
    later = datetime.now(timezone.utc) + timedelta(days=15)
    assert cc.load_cost_calibration(target, now=later)["stale"] is True
    within = datetime.now(timezone.utc) + timedelta(days=13)
    assert cc.load_cost_calibration(target, now=within)["stale"] is False


def test_load_missing_or_corrupt_returns_none(tmp_path):
    assert cc.load_cost_calibration(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert cc.load_cost_calibration(bad) is None
