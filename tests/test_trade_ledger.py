"""core/trade_ledger.py 손계산 검증 (합성 데이터, 네트워크 없음)."""

import pandas as pd
import pytest

from core.trade_ledger import run_cost_scenarios, run_ledger_backtest
import core.backtest_engine as be


def _df():
    idx = pd.bdate_range("2024-01-01", periods=4)
    return pd.DataFrame({"Open": [100, 110, 120, 90.0], "Close": [100, 120, 100, 90.0]}, index=idx)


def _pos(vals):
    return pd.Series(vals, index=_df().index, dtype=float)


def test_next_open_fill_and_gap_hand_calc():
    # 신호: day0 매수, day2 청산. 체결: day1 시가 110, day3 시가 90.
    r = run_ledger_backtest(_df(), _pos([1, 1, 0, 0]), initial_cash=1100.0)
    led = r.ledger
    assert list(led["side"]) == ["BUY", "SELL"]
    assert led.loc[0, "quantity"] == pytest.approx(10.0)  # 1100/110
    assert led.loc[0, "fill_time"] == _df().index[1]
    assert led.loc[0, "signal_time"] == _df().index[0]
    assert led.loc[1, "fill_time"] == _df().index[3]  # day2 신호 -> day3 시가 90
    assert led.loc[1, "fill_price"] == pytest.approx(90.0)
    # NAV(종가): day0 1100(미체결), day1 10*120=1200, day2 10*100=1000, day3 매도후 현금 900
    assert list(r.nav) == pytest.approx([1100, 1200, 1000, 900])
    # 기존 경로는 day0 종가 진입(갭 무시)이라 다른 값 -> 기준선과 달라야 함
    base = be.compute_equity_curve(_df(), _pos([1, 1, 0, 0]), initial_value=1100.0)
    assert base.iloc[1] == pytest.approx(1100 * 1.2)  # 종가->종가 20%, 시가체결과 다름


def test_costs_separated_hand_calc():
    r = run_ledger_backtest(_df(), _pos([1, 1, 0, 0]), initial_cash=1100.0,
                            fee_bps=10, slippage_bps=100, tax_bps=50)
    b, s = r.ledger.iloc[0], r.ledger.iloc[1]
    # 매수: 체결가 110*1.01=111.1, 수수료 0.1% 포함 가능수량 1100/(111.1*1.001)
    qty = 1100 / (111.1 * 1.001)
    assert b["quantity"] == pytest.approx(qty)
    assert b["fee"] == pytest.approx(qty * 111.1 * 0.001)
    assert b["slippage_cost"] == pytest.approx(qty * 1.1)
    assert b["tax"] == 0
    assert b["cash_after"] == pytest.approx(0.0, abs=1e-9)
    # 매도: 체결가 90*0.99=89.1, 세금 0.5%는 매도에만
    notional = qty * 89.1
    assert s["tax"] == pytest.approx(notional * 0.005)
    assert s["fee"] == pytest.approx(notional * 0.001)
    assert r.nav.iloc[-1] == pytest.approx(notional * (1 - 0.001 - 0.005))
    assert r.total_tax == pytest.approx(s["tax"])
    assert r.total_slippage_cost == pytest.approx(qty * 1.1 + qty * 0.9)


def test_last_day_signal_unfilled_and_integer_shares():
    r = run_ledger_backtest(_df(), _pos([0, 0, 0, 1]), initial_cash=1000.0)
    assert r.ledger.empty
    r2 = run_ledger_backtest(_df(), _pos([1, 1, 1, 1]), initial_cash=1000.0, integer_shares=True)
    assert r2.ledger.loc[0, "quantity"] == 9  # floor(1000/110)
    assert r2.daily["cash"].iloc[-1] == pytest.approx(1000 - 9 * 110)


def test_cost_scenarios_monotone_and_zero_position_flat():
    res = run_cost_scenarios(_df(), _pos([1, 1, 0, 0]), initial_cash=1100.0)
    navs = [res[k].nav.iloc[-1] for k in ("0bp", "5bp", "10bp", "25bp")]
    assert navs == sorted(navs, reverse=True) and navs[0] > navs[-1]
    flat = run_ledger_backtest(_df(), _pos([0, 0, 0, 0]), initial_cash=100.0, fee_bps=25)
    assert list(flat.nav) == [100.0] * 4


def test_baseline_default_unchanged():
    # 기존 경로가 그대로 종가->종가 shift(1) 모델임을 고정
    eq = be.compute_equity_curve(_df(), _pos([1, 1, 0, 0]), initial_value=100.0)
    assert list(eq) == pytest.approx([100, 120, 100, 100])
