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


# ---------------------------------------------------------------------------
# 기업행동(배당·분할) 옵트인 — 기대값은 요구사항에서 종이로 계산했다.
# ---------------------------------------------------------------------------
from core.corporate_actions import CorporateAction  # noqa: E402
from core.trade_ledger import CORPORATE_ACTION_COLUMNS  # noqa: E402


def _flat_df(closes):
    idx = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame({"Open": [float(c) for c in closes],
                         "Close": [float(c) for c in closes]}, index=idx)


def _hold_all(df):
    return pd.Series(1.0, index=df.index)


def test_dividend_cash_inflow_hand_calc():
    """종이 계산: day1 시가 100 에 10,000/100 = 100주 매수.
    day2(ex-date) 주당 $0.5 배당 -> 현금 +$50, NAV 는 배당 없는 경우보다 정확히 $50 크다."""
    df = _flat_df([100, 100, 100, 100])
    div = CorporateAction(symbol="T", type="cash_dividend", ex_date="2024-01-03", amount=0.5)
    base = run_ledger_backtest(df, _hold_all(df), initial_cash=10000.0)
    r = run_ledger_backtest(df, _hold_all(df), initial_cash=10000.0, corporate_actions=[div])

    assert list(base.nav) == pytest.approx([10000, 10000, 10000, 10000])
    assert list(r.nav) == pytest.approx([10000, 10000, 10050, 10050])
    assert r.nav.iloc[2] - base.nav.iloc[2] == pytest.approx(50.0)
    assert r.total_dividend_cash == pytest.approx(50.0)

    row = r.ledger[r.ledger["side"] == "dividend"].iloc[0]
    assert row["quantity"] == pytest.approx(100.0)       # 체결 전 보유 수량
    assert row["ref_open"] == pytest.approx(0.5)          # 주당 배당금
    assert row["notional"] == pytest.approx(50.0)         # 현금 유입
    assert row["fee"] == 0 and row["tax"] == 0 and row["slippage_cost"] == 0
    assert row["fill_time"] == df.index[2]
    assert r.params["dividend_cash_flow_modeled"] is True
    assert "반영했다" in r.params["dividend_note"]
    ca = r.corporate_actions
    assert list(ca.columns) == CORPORATE_ACTION_COLUMNS
    assert bool(ca.iloc[0]["applied"]) is True and ca.iloc[0]["cash_delta"] == pytest.approx(50.0)


def test_two_for_one_split_hand_calc():
    """종이 계산: 100주(취득단가 100)를 보유한 상태에서 2:1 분할 -> 200주·단가 50.
    원시 가격이 같은 날 100 -> 50 으로 반토막 나므로 NAV 는 10,000 으로 불변."""
    df = _flat_df([100, 100, 50, 50])
    split = CorporateAction(symbol="T", type="forward_split", ex_date="2024-01-03", split_ratio=2.0)
    r = run_ledger_backtest(df, _hold_all(df), initial_cash=10000.0, corporate_actions=[split])

    assert list(r.nav) == pytest.approx([10000, 10000, 10000, 10000])  # 분할 전후 NAV 불변
    assert r.daily["shares"].iloc[1] == pytest.approx(100.0)
    assert r.daily["shares"].iloc[2] == pytest.approx(200.0)           # 수량 2배
    assert r.final_cost_basis == pytest.approx(50.0)                   # 기준가 1/2
    ca = r.corporate_actions.iloc[0]
    assert (ca["shares_before"], ca["shares_after"]) == pytest.approx((100.0, 200.0))
    assert (ca["basis_before"], ca["basis_after"]) == pytest.approx((100.0, 50.0))
    assert ca["cash_delta"] == 0.0
    assert r.params["split_adjustment_modeled"] is True
    assert r.params["dividend_cash_flow_modeled"] is False  # 분할만 주면 배당은 여전히 미반영
    # 분할을 반영하지 않으면 같은 원시 가격에서 NAV 가 반토막 난다(왜곡)
    no_ca = run_ledger_backtest(df, _hold_all(df), initial_cash=10000.0)
    assert no_ca.nav.iloc[2] == pytest.approx(5000.0)


def test_reverse_split_and_split_then_dividend_same_day():
    df = _flat_df([10, 10, 100, 100])
    # 1:10 병합(비율 0.1) + 같은 날 배당 $1/주: 분할 먼저 적용 후 100주->10주, 배당 10*1=$10
    actions = [CorporateAction(symbol="T", type="reverse_split", ex_date="2024-01-03", split_ratio=0.1),
               CorporateAction(symbol="T", type="cash_dividend", ex_date="2024-01-03", amount=1.0)]
    r = run_ledger_backtest(df, _hold_all(df), initial_cash=1000.0, corporate_actions=actions)
    assert r.daily["shares"].iloc[1] == pytest.approx(100.0)   # 1000/10
    assert r.total_dividend_cash == pytest.approx(10.0)        # 10주 x $1
    assert r.final_cost_basis == pytest.approx(100.0)          # 10 / 0.1
    assert r.nav.iloc[2] == pytest.approx(1010.0)              # 10주*100 + 배당 10


def test_default_none_is_byte_identical_to_before():
    df = _df()
    pos = _pos([1, 1, 0, 0])
    a = run_ledger_backtest(df, pos, initial_cash=1100.0, fee_bps=10, tax_bps=5)
    b = run_ledger_backtest(df, pos, initial_cash=1100.0, fee_bps=10, tax_bps=5, corporate_actions=None)
    assert a.ledger.equals(b.ledger) and a.daily.equals(b.daily)
    assert a.params == b.params
    assert a.params["dividend_cash_flow_modeled"] is False
    assert a.params["corporate_actions_provided"] is False
    assert a.corporate_actions.empty and a.total_dividend_cash == 0.0
    assert list(a.ledger.columns) == ["signal_time", "fill_time", "side", "quantity", "ref_open",
                                      "fill_price", "notional", "fee", "slippage_cost", "tax",
                                      "cash_after", "shares_after", "nav_after"]


def test_empty_corporate_action_list_changes_nothing_but_flags_opt_in():
    df = _flat_df([100, 100, 100, 100])
    a = run_ledger_backtest(df, _hold_all(df), initial_cash=10000.0)
    b = run_ledger_backtest(df, _hold_all(df), initial_cash=10000.0, corporate_actions=[])
    assert list(a.nav) == pytest.approx(list(b.nav))
    assert b.params["dividend_cash_flow_modeled"] is False
    assert b.params["corporate_actions_provided"] is True


def test_unusable_actions_are_skipped_with_reasons_not_guessed():
    df = _flat_df([100, 100, 100, 100])
    actions = [
        CorporateAction(symbol="T", type="cash_dividend", ex_date=None, amount=0.5),       # 날짜 없음
        CorporateAction(symbol="T", type="cash_dividend", ex_date="2024-01-03"),           # 금액 없음
        CorporateAction(symbol="T", type="forward_split", ex_date="2024-01-03"),           # 비율 없음
        CorporateAction(symbol="T", type="unknown", ex_date="2024-01-03"),                 # 종류 모름
        CorporateAction(symbol="T", type="cash_dividend", ex_date="2030-01-03", amount=9),  # 인덱스 밖
        CorporateAction(symbol="T", type="cash_dividend", ex_date="garbage", amount=9),     # 파싱 불가
    ]
    r = run_ledger_backtest(df, _hold_all(df), initial_cash=10000.0, corporate_actions=actions)
    assert list(r.nav) == pytest.approx([10000, 10000, 10000, 10000])  # 아무것도 적용되지 않음
    assert r.params["corporate_actions_applied"] == 0
    assert r.params["corporate_actions_skipped"] == 6
    assert r.params["dividend_cash_flow_modeled"] is False
    assert not r.corporate_actions["applied"].any()
    assert len(set(r.corporate_actions["reason"])) >= 4


def test_dict_actions_accepted_and_no_shares_means_no_dividend_row():
    df = _flat_df([100, 100, 100, 100])
    div = {"symbol": "T", "type": "cash_dividend", "ex_date": "2024-01-02", "amount": 0.5}
    flat = pd.Series(0.0, index=df.index)
    r = run_ledger_backtest(df, flat, initial_cash=10000.0, corporate_actions=[div])
    assert r.total_dividend_cash == 0.0           # 보유 0주 -> 현금 유입 없음
    assert r.ledger.empty                          # 원장 행도 없음
    assert r.params["dividend_cash_flow_modeled"] is False
    assert bool(r.corporate_actions.iloc[0]["applied"]) is True  # 적용은 했으나 금액이 0


def test_cost_scenarios_pass_corporate_actions_through():
    df = _flat_df([100, 100, 100, 100])
    div = CorporateAction(symbol="T", type="cash_dividend", ex_date="2024-01-03", amount=0.5)
    res = run_cost_scenarios(df, _hold_all(df), initial_cash=10000.0, corporate_actions=[div])
    assert res["0bp"].total_dividend_cash == pytest.approx(50.0)
    assert all(r.params["dividend_cash_flow_modeled"] is True for r in res.values())
