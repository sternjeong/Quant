"""core/backtest_engine.py 단위 테스트.

네트워크(yfinance) 호출을 피하기 위해 core.backtest_engine.get_price_history 를
monkeypatch 하여 합성 OHLCV 데이터를 반환하도록 한다.
"""

import numpy as np
import pandas as pd
import pytest

import core.backtest_engine as backtest_engine


def _make_df(n=500, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=n)
    returns = rng.normal(0.0005, 0.01, n)
    close = 100 * np.cumprod(1 + returns)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Adj Close": close,
            "Volume": 1_000_000,
        },
        index=idx,
    )


@pytest.fixture(autouse=True)
def _mock_price_history(monkeypatch):
    df = _make_df()

    def _fake_get_price_history(ticker, start=None, end=None, interval="1d", use_cache=True, **kwargs):
        out = df.copy()
        if start:
            out = out[out.index >= pd.Timestamp(start)]
        if end:
            out = out[out.index <= pd.Timestamp(end)]
        return out

    monkeypatch.setattr(backtest_engine, "get_price_history", _fake_get_price_history)
    yield


def test_run_buy_and_hold_single_trade():
    run = backtest_engine.run_buy_and_hold("TEST", "2021-06-01", "2022-06-01")
    assert run.metrics["trade_count"] == 1
    assert run.metrics["win_rate"] in (0.0, 100.0)


def test_compute_drawdown_series_is_always_non_positive_and_zero_at_new_highs():
    idx = pd.bdate_range("2022-01-03", periods=6)
    equity = pd.Series([100, 110, 90, 95, 120, 100], index=idx, dtype=float)
    drawdown = backtest_engine.compute_drawdown_series(equity)
    assert (drawdown <= 0).all()
    # 신고점을 갱신한 시점(100, 110, 120)은 낙폭이 0이어야 한다.
    assert drawdown.iloc[0] == pytest.approx(0.0)
    assert drawdown.iloc[1] == pytest.approx(0.0)
    assert drawdown.iloc[4] == pytest.approx(0.0)
    # 90은 직전 신고점 110 대비 -18.18%
    assert drawdown.iloc[2] == pytest.approx((90 / 110 - 1) * 100)


def test_compute_drawdown_series_empty_returns_empty():
    result = backtest_engine.compute_drawdown_series(pd.Series(dtype=float))
    assert result.empty


def test_compute_monthly_returns_pivots_by_year_and_month():
    idx = pd.bdate_range("2021-11-01", "2022-02-28")
    rng = np.random.default_rng(3)
    equity = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, len(idx))), index=idx)
    table = backtest_engine.compute_monthly_returns(equity)
    assert set(table.columns) == set(range(1, 13))
    assert set(table.index) == {2021, 2022}
    # 첫 관측월(2021-11)은 비교할 직전 달이 없어 NaN이어야 한다.
    assert pd.isna(table.loc[2021, 11])
    # 그 외 관측된 달(2021-12, 2022-01, 2022-02)은 값이 있어야 한다.
    assert not pd.isna(table.loc[2021, 12])
    assert not pd.isna(table.loc[2022, 1])
    assert not pd.isna(table.loc[2022, 2])


def test_compute_monthly_returns_insufficient_data_returns_empty_df():
    idx = pd.bdate_range("2022-01-03", periods=5)
    equity = pd.Series([100, 101, 102, 101, 103], index=idx, dtype=float)
    result = backtest_engine.compute_monthly_returns(equity)
    assert result.empty


# =============================================================================
# 검증 테스트 4종 (Masters) 단위 테스트
# =============================================================================


def _rsi_config(threshold):
    return {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": threshold}]}


def test_shuffle_daily_bars_keeps_dates_and_permutes_close_ratios():
    raw = _make_df()
    window_start, window_end = raw.index[300], raw.index[-1]
    rng = np.random.default_rng(42)
    synthetic = backtest_engine._shuffle_daily_bars(raw, window_start, window_end, rng)

    # 인덱스(날짜)는 그대로, 값만 바뀐다.
    assert list(synthetic.index) == list(raw.index)
    before = raw[(raw.index < window_start)]
    pd.testing.assert_frame_equal(synthetic.loc[before.index], before)

    window_mask = (raw.index >= window_start) & (raw.index <= window_end)
    original_close = raw.loc[window_mask, "Close"].to_numpy()
    synthetic_close = synthetic.loc[window_mask, "Close"].to_numpy()
    assert not np.allclose(original_close, synthetic_close)  # 순서가 섞였으니 값도 달라져야 함

    # 일별 종가 변화율(비율) 집합 자체는 원본과 동일해야 한다 (순서만 바뀌었을 뿐 개별 값은 보존).
    prev_close = raw["Close"].shift(1)
    original_ratios = (raw.loc[window_mask, "Close"] / prev_close.loc[window_mask]).sort_values().to_numpy()
    synthetic_prev_close = synthetic["Close"].shift(1)
    synthetic_ratios = (
        (synthetic.loc[window_mask, "Close"] / synthetic_prev_close.loc[window_mask]).sort_values().to_numpy()
    )
    np.testing.assert_allclose(original_ratios, synthetic_ratios, rtol=1e-9)


# =============================================================================
# 거래비용(수수료/슬리피지) 단위 테스트
# =============================================================================


def test_compute_equity_curve_no_cost_by_default():
    idx = pd.bdate_range("2021-01-04", periods=5)
    df = pd.DataFrame({"Close": [100.0, 101.0, 102.0, 103.0, 104.0]}, index=idx)
    position = pd.Series([0, 1, 1, 0, 0], index=idx, dtype=float)
    baseline = backtest_engine.compute_equity_curve(df, position)
    zero_cost = backtest_engine.compute_equity_curve(df, position, fee_bps=0.0, slippage_bps=0.0)
    pd.testing.assert_series_equal(baseline, zero_cost)


def test_compute_equity_curve_cost_reduces_return_on_position_change():
    idx = pd.bdate_range("2021-01-04", periods=5)
    df = pd.DataFrame({"Close": [100.0, 101.0, 102.0, 103.0, 104.0]}, index=idx)
    position = pd.Series([0, 1, 1, 0, 0], index=idx, dtype=float)  # 진입 1회 + 청산 1회 = 회전율 2회
    no_cost = backtest_engine.compute_equity_curve(df, position)
    with_cost = backtest_engine.compute_equity_curve(df, position, fee_bps=50.0, slippage_bps=50.0)
    assert with_cost.iloc[-1] < no_cost.iloc[-1]


def test_compute_equity_curve_cost_is_zero_when_position_never_changes():
    idx = pd.bdate_range("2021-01-04", periods=5)
    df = pd.DataFrame({"Close": [100.0, 101.0, 102.0, 103.0, 104.0]}, index=idx)
    flat_position = pd.Series([0.0] * 5, index=idx)
    curve = backtest_engine.compute_equity_curve(df, flat_position, fee_bps=100.0, slippage_bps=100.0)
    assert curve.iloc[-1] == pytest.approx(100.0)


def test_simulate_contribution_equity_cost_reduces_total_vs_no_cost():
    idx = pd.bdate_range("2021-01-04", periods=6)
    df = pd.DataFrame({"Close": [100.0, 101.0, 100.0, 105.0, 100.0, 110.0]}, index=idx)
    position = pd.Series([0, 1, 0, 1, 0, 1], index=idx, dtype=float)  # 자주 바뀌는 시그널 -> 회전율 큼
    no_cost, _ = backtest_engine.simulate_contribution_equity(df, position, monthly_contribution=0.0)
    with_cost, _ = backtest_engine.simulate_contribution_equity(
        df, position, monthly_contribution=0.0, fee_bps=100.0, slippage_bps=100.0
    )
    assert with_cost.iloc[-1] < no_cost.iloc[-1]


# =============================================================================
# 손익비(Profit Factor) / 칼마지수(Calmar) 단위 테스트
# =============================================================================


def test_calculate_metrics_profit_factor_from_trade_returns():
    from core.strategy_engine import Trade

    idx = pd.bdate_range("2021-01-04", periods=3)
    equity_curve = pd.Series([100.0, 110.0, 95.0], index=idx)
    trades = [
        Trade(entry_date=idx[0], exit_date=idx[1], entry_price=100.0, exit_price=110.0, return_pct=10.0),
        Trade(entry_date=idx[1], exit_date=idx[2], entry_price=110.0, exit_price=95.0, return_pct=-5.0),
    ]
    metrics = backtest_engine.calculate_metrics(equity_curve, trades, idx[0], idx[-1])
    assert metrics["profit_factor"] == pytest.approx(2.0)  # 10 / 5


def test_calculate_metrics_profit_factor_capped_when_no_losing_trades():
    from core.strategy_engine import Trade

    idx = pd.bdate_range("2021-01-04", periods=3)
    equity_curve = pd.Series([100.0, 110.0, 121.0], index=idx)
    trades = [
        Trade(entry_date=idx[0], exit_date=idx[1], entry_price=100.0, exit_price=110.0, return_pct=10.0),
        Trade(entry_date=idx[1], exit_date=idx[2], entry_price=110.0, exit_price=121.0, return_pct=10.0),
    ]
    metrics = backtest_engine.calculate_metrics(equity_curve, trades, idx[0], idx[-1])
    assert metrics["profit_factor"] == backtest_engine._RATIO_METRIC_CAP


def test_calculate_metrics_empty_curve_defaults_include_new_keys():
    metrics = backtest_engine.calculate_metrics(pd.Series(dtype=float), [], "2021-01-01", "2021-06-01")
    assert metrics["profit_factor"] == 0.0
    assert metrics["calmar"] == 0.0


def test_compute_calmar_no_drawdown_cases():
    assert backtest_engine._compute_calmar(20.0, 0.0) == backtest_engine._RATIO_METRIC_CAP
    assert backtest_engine._compute_calmar(-5.0, 0.0) == 0.0
    assert backtest_engine._compute_calmar(20.0, -10.0) == pytest.approx(2.0)


# =============================================================================
# 전략 수명 / 알파 감쇠 모니터링 단위 테스트
# =============================================================================


# =============================================================================
# 평균 낙폭 지속기간(avg_drawdown_days) 단위 테스트
# =============================================================================


def test_calculate_metrics_avg_drawdown_days_with_one_closed_drawdown():
    idx = pd.date_range("2021-01-01", periods=4, freq="D")
    equity = pd.Series([100.0, 90.0, 95.0, 100.0], index=idx)  # day1 낙폭 시작, day3 신고점 복귀
    metrics = backtest_engine.calculate_metrics(equity, [], idx[0], idx[-1])
    assert metrics["avg_drawdown_days"] == pytest.approx(2.0)


def test_calculate_metrics_avg_drawdown_days_excludes_unclosed_drawdown():
    idx = pd.date_range("2021-01-01", periods=4, freq="D")
    equity = pd.Series([100.0, 90.0, 85.0, 80.0], index=idx)  # 끝까지 회복 못 함
    metrics = backtest_engine.calculate_metrics(equity, [], idx[0], idx[-1])
    assert metrics["avg_drawdown_days"] == 0.0


def test_calculate_metrics_avg_drawdown_days_no_drawdown_is_zero():
    idx = pd.date_range("2021-01-01", periods=4, freq="D")
    equity = pd.Series([100.0, 101.0, 102.0, 103.0], index=idx)
    metrics = backtest_engine.calculate_metrics(equity, [], idx[0], idx[-1])
    assert metrics["avg_drawdown_days"] == 0.0


def test_calculate_metrics_avg_drawdown_days_averages_multiple_closed_drawdowns():
    idx = pd.date_range("2021-01-01", periods=8, freq="D")
    # 낙폭1: day1~day2(2일), 신고점 복귀 day3. 낙폭2: day5~day6(2일), 신고점 복귀 day7.
    equity = pd.Series([100.0, 90.0, 95.0, 101.0, 101.0, 95.0, 98.0, 102.0], index=idx)
    metrics = backtest_engine.calculate_metrics(equity, [], idx[0], idx[-1])
    assert metrics["avg_drawdown_days"] == pytest.approx(2.0)


# =============================================================================
# 매매 횟수 통계적 신뢰도 경고 단위 테스트
# =============================================================================


# =============================================================================
# 전략 포트폴리오 상관관계("홀리그레일") 단위 테스트
# =============================================================================

_MA_CROSS_CONFIG = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"}]}
_RSI40_CONFIG = {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 40}]}


# =============================================================================
# 앙상블 스코어링 전략의 백테스트 엔진 연동 단위 테스트
# =============================================================================


# =============================================================================
# 팩터 분해 (compute_factor_returns / run_factor_regression) 단위 테스트
# =============================================================================


# =============================================================================
# 몬테카를로 시뮬레이션 (run_monte_carlo_simulation) 단위 테스트
# =============================================================================


