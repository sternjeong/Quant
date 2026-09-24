"""backtest_engine 옵트인 execution_model 연결 + 손계산 대조 + 기업행동 테스트.

기대값은 종이 계산으로 독립 산출한 하드코딩 값이며 구현 함수를 재사용하지 않는다.
"""

import numpy as np
import pandas as pd
import pytest

import core.backtest_engine as be
from core.trade_ledger import adjust_ohlc_by_adj_close


def _idx(n):
    return pd.bdate_range("2024-01-01", periods=n)


def test_default_path_bit_identical_with_and_without_new_params():
    rng = np.random.default_rng(3)
    idx = _idx(60)
    close = 100 * np.cumprod(1 + rng.normal(0, 0.01, 60))
    df = pd.DataFrame({"Open": close * 0.998, "Close": close}, index=idx)
    pos = pd.Series((np.arange(60) % 10 < 5).astype(float), index=idx)
    a = be.compute_equity_curve(df, pos, fee_bps=3, slippage_bps=2)
    b = be.compute_equity_curve(df, pos, fee_bps=3, slippage_bps=2, execution_model=None, tax_bps=50)
    c = be.compute_equity_curve(df, pos, fee_bps=3, slippage_bps=2, execution_model="close")
    assert a.equals(b) and a.equals(c)


def test_unknown_execution_model_raises():
    idx = _idx(3)
    df = pd.DataFrame({"Open": [1.0] * 3, "Close": [1.0] * 3}, index=idx)
    with pytest.raises(ValueError):
        be.compute_equity_curve(df, pd.Series([1.0] * 3, index=idx), execution_model="bogus")


def test_gap_down_hand_calc_and_side_by_side():
    idx = _idx(4)
    df = pd.DataFrame({"Open": [100, 90, 95, 80.0], "Close": [100, 95, 85, 80.0]}, index=idx)
    pos = pd.Series([1, 0, 0, 0], index=idx, dtype=float)
    # 종이 계산: day1 시가 90 매수(900/90=10주), day1 종가 95 -> 950,
    # day1 신호 0 -> day2 시가 95 전량 매도 -> 현금 950 이후 고정
    led = be.compute_equity_curve(df, pos, initial_value=900.0, execution_model="next_open_ledger")
    assert list(led) == pytest.approx([900, 950, 950, 950])
    # 기존 경로: day1 종가수익 -5% 만 반영 -> 855, 이후 포지션 0
    base = be.compute_equity_curve(df, pos, initial_value=900.0)
    assert list(base) == pytest.approx([900, 855, 855, 855])
    cmp = be.compare_execution_models(df, pos, initial_value=900.0)
    assert list(cmp["diff"]) == pytest.approx([0, 95, 95, 95])
    assert cmp["max_abs_diff"] == pytest.approx(95.0)
    assert cmp["final_diff_pct"] == pytest.approx(950 / 855 - 1)
    assert set(cmp["scenario_nav"]) == {"0bp", "5bp", "10bp", "25bp"}
    assert list(cmp["scenario_nav"]["0bp"]) == pytest.approx([900, 950, 950, 950])
    # 비용이 클수록 최종 NAV 는 작아야 한다
    fin = [cmp["scenario_nav"][k].iloc[-1] for k in ("0bp", "5bp", "10bp", "25bp")]
    assert fin == sorted(fin, reverse=True)


def test_gap_up_fee_slippage_tax_hand_calc():
    idx = _idx(4)
    df = pd.DataFrame({"Open": [100, 110, 120, 90.0], "Close": [100, 120, 100, 90.0]}, index=idx)
    pos = pd.Series([1, 1, 0, 0], index=idx, dtype=float)
    # 종이 계산 (정수 주, 수수료 10bp, 슬리피지 100bp, 세금 50bp, 초기 1100):
    # 매수 day1: 체결가 110*1.01=111.1, 가능수량 1100/(111.1*1.001)=9.89 -> 9주
    #   대금 999.9, 수수료 0.9999, 현금 1100-999.9-0.9999=99.1001, 슬리피지비용 9*110*0.01=9.9
    # day1 종가 120: NAV=99.1001+1080=1179.1001
    # 매도 day3(신호 day2): 체결가 90*0.99=89.1, 대금 801.9, 수수료 0.8019, 세금 801.9*0.005=4.0095
    #   현금 99.1001+801.9-0.8019-4.0095=896.1887, 슬리피지비용 9*90*0.01=8.1
    from core.trade_ledger import run_ledger_backtest
    res = run_ledger_backtest(df, pos, initial_cash=1100.0, fee_bps=10, slippage_bps=100,
                              tax_bps=50, integer_shares=True)
    assert list(res.nav) == pytest.approx([1100, 1179.1001, 9 * 100 + 99.1001, 896.1887], abs=1e-6)
    assert res.total_fee == pytest.approx(1.8018, abs=1e-9)
    assert res.total_tax == pytest.approx(4.0095, abs=1e-9)
    assert res.total_slippage_cost == pytest.approx(18.0, abs=1e-9)
    # 엔진 진입점 경유도 같은 NAV
    eq = be.compute_equity_curve(df, pos, initial_value=1100.0, fee_bps=10, slippage_bps=100,
                                 execution_model="next_open_ledger", tax_bps=50)
    # 소수 주 허용 경로는 정수 주와 다르므로 마지막 값이 정수주 값보다 다르다는 것만 확인하지 않고
    # 소수주 손계산: 수량 1100/(111.1*1.001), 현금 0, 매도 대금 q*89.1*(1-0.001-0.005)
    q = 1100 / (111.1 * 1.001)
    assert eq.iloc[-1] == pytest.approx(q * 89.1 * (1 - 0.001 - 0.005), rel=1e-9)
    assert eq.iloc[-1] == pytest.approx(1100 / 111.2111 * 89.1 * 0.994, rel=1e-9)


def _split_df():
    # 2:1 분할이 day2 에 발생. 미조정 가격은 day2 부터 절반.
    idx = _idx(5)
    return pd.DataFrame({
        "Open": [100, 101, 50.5, 51.5, 52.5],
        "High": [101, 103, 52, 53, 54.0],
        "Low": [99, 100, 50, 51, 52.0],
        "Close": [100, 102, 51, 52, 53.0],
        "Adj Close": [50, 51, 51, 52, 53.0],
    }, index=idx)


def test_unadjusted_split_distorts_nav():
    df = _split_df()
    pos = pd.Series([1.0] * 5, index=df.index)
    # 종이 계산: day1 시가 101 매수 1000/101주. day1 종가 102 -> 1009.90099, day2 종가 51 -> 504.950495
    r = be.compute_equity_curve(df, pos, initial_value=1000.0, execution_model="next_open_ledger")
    assert r.iloc[1] == pytest.approx(1009.90099, abs=1e-4)
    assert r.iloc[2] == pytest.approx(504.950495, abs=1e-4)  # 실제 자산은 변하지 않았는데 -50%
    base = be.compute_equity_curve(df, pos, initial_value=1000.0)
    assert base.iloc[2] / base.iloc[1] - 1 == pytest.approx(-0.5, abs=1e-9)


def test_adjusted_prices_make_nav_continuous_across_split():
    df = _split_df()
    adj = adjust_ohlc_by_adj_close(df)
    # 조정 결과(종이 계산): 비율 0.5,0.5,1,1,1
    assert list(adj["Open"]) == pytest.approx([50, 50.5, 50.5, 51.5, 52.5])
    assert list(adj["Close"]) == pytest.approx([50, 51, 51, 52, 53])
    assert list(adj["High"]) == pytest.approx([50.5, 51.5, 52, 53, 54])
    assert list(adj["Low"]) == pytest.approx([49.5, 50, 50, 51, 52])
    assert list(df["Close"]) == [100, 102, 51, 52, 53]  # 입력 불변
    pos = pd.Series([1.0] * 5, index=df.index)
    nav = be.compute_equity_curve(adj, pos, initial_value=1000.0, execution_model="next_open_ledger")
    # day1 시가 50.5 매수 1000/50.5주 -> 종가마다 1000*close/50.5
    assert list(nav) == pytest.approx([1000, 1009.90099, 1009.90099, 1029.70297, 1049.50495], abs=1e-4)
    assert nav.iloc[2] == pytest.approx(nav.iloc[1])  # 분할 전후 연속


def test_adjust_requires_adj_close():
    with pytest.raises(ValueError):
        adjust_ohlc_by_adj_close(pd.DataFrame({"Open": [1.0], "Close": [1.0]}))


def test_meta_states_dividends_not_modeled():
    df = _split_df()
    pos = pd.Series([1.0] * 5, index=df.index)
    raw = be.compare_execution_models(df, pos)
    assert raw["meta"]["dividend_cash_flow_modeled"] is False
    assert "미반영" in raw["meta"]["dividend_note"]
    adj = be.compare_execution_models(adjust_ohlc_by_adj_close(df), pos,
                                      price_basis="adjusted OHLC (Adj Close/Close ratio applied to Open/High/Low/Close)")
    assert adj["meta"]["dividend_cash_flow_modeled"] is False
    assert "재투자" in adj["meta"]["dividend_note"]


def _mock_history(monkeypatch, df):
    def fake(ticker, start=None, end=None, interval="1d", use_cache=True, **kw):
        out = df.copy()
        if start:
            out = out[out.index >= pd.Timestamp(start)]
        if end:
            out = out[out.index <= pd.Timestamp(end)]
        return out
    monkeypatch.setattr(be, "get_price_history", fake)


def _synth(n=400):
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2021-01-04", periods=n)
    c = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    return pd.DataFrame({"Open": c * 0.999, "High": c * 1.01, "Low": c * 0.99, "Close": c,
                         "Adj Close": c * 0.98, "Volume": 1e6}, index=idx)


def test_run_backtest_default_unchanged_and_opt_in_meta(monkeypatch):
    _mock_history(monkeypatch, _synth())
    cfg = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"}]}
    d = be.run_backtest("T", cfg, "2021-06-01", "2022-06-01")
    d2 = be.run_backtest("T", cfg, "2021-06-01", "2022-06-01", execution_model=None, adjust_prices=False)
    assert d.equity_curve.equals(d2.equity_curve) and d.execution_meta == {}
    o = be.run_backtest("T", cfg, "2021-06-01", "2022-06-01", execution_model="next_open_ledger",
                        fee_bps=5, tax_bps=10, adjust_prices=True)
    assert o.execution_meta["execution_model"] == "next_open_ledger"
    assert o.execution_meta["dividend_cash_flow_modeled"] is False
    assert o.equity_curve.iloc[0] == pytest.approx(100.0)
    assert not o.equity_curve.equals(d.equity_curve)
    with pytest.raises(ValueError):
        be.run_backtest("T", cfg, "2021-06-01", "2022-06-01", execution_model="next_open_ledger",
                        monthly_contribution=10)
