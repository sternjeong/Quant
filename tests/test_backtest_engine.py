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


def test_run_backtest_returns_metrics_for_all_keys():
    config = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"}]}
    run = backtest_engine.run_backtest("TEST", config, "2021-06-01", "2022-06-01")
    for key in ("cumulative_return", "cagr", "mdd", "sharpe", "win_rate", "trade_count"):
        assert key in run.metrics
    assert not run.df.empty
    assert not run.equity_curve.empty
    assert run.equity_curve.iloc[0] == pytest.approx(100.0)


def test_cap_holding_period_forces_exit_after_max_days():
    idx = pd.bdate_range("2021-01-04", periods=10)
    position = pd.Series([1.0] * 10, index=idx)  # 계속 보유 신호(예: 롱텀 컴파운더식 전략)
    capped = backtest_engine._cap_holding_period(position, max_holding_days=3)
    # 3일마다 강제 청산되고, 신호가 여전히 보유를 가리키므로 바로 다음 날 재진입한다.
    assert list(capped) == [1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0]


def test_cap_holding_period_allows_reentry_after_forced_exit():
    idx = pd.bdate_range("2021-01-04", periods=10)
    # 6일 연속 보유 신호를 3일 상한으로 캡핑하면: 3일 보유 -> 강제청산 -> 신호가 여전히 보유를
    # 가리키므로 바로 재진입 -> 다시 3일 뒤 강제청산.
    position = pd.Series([1.0] * 6 + [0.0] * 4, index=idx)
    capped = backtest_engine._cap_holding_period(position, max_holding_days=3)
    assert list(capped) == [1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0]


def test_cap_holding_period_none_is_noop():
    idx = pd.bdate_range("2021-01-04", periods=5)
    position = pd.Series([1.0] * 5, index=idx)
    assert list(backtest_engine._cap_holding_period(position, None)) == [1.0] * 5


def test_run_backtest_with_max_holding_days_forces_swing_exit():
    """스윙 트레이딩 상한(SPEC 15절) — 원래 오래 들고 가는(200일선 위 유지) 전략도 max_holding_days를
    넘기면 평균 보유일수가 그 상한을 넘지 않아야 한다."""
    config = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"}]}
    run_uncapped = backtest_engine.run_backtest("TEST", config, "2021-06-01", "2022-06-01")
    run_capped = backtest_engine.run_backtest(
        "TEST", config, "2021-06-01", "2022-06-01", max_holding_days=30
    )
    assert run_capped.metrics["trade_count"] >= run_uncapped.metrics["trade_count"]
    # 보유일수 상한이 실제로 포지션에 반영됐는지는 연속 보유 구간 길이로 직접 확인한다.
    held = run_capped.position > 0
    streak_id = (~held).cumsum()
    max_streak = held.groupby(streak_id).cumcount().add(1).where(held, 0).max()
    assert max_streak <= 30


def test_run_buy_and_hold_single_trade():
    run = backtest_engine.run_buy_and_hold("TEST", "2021-06-01", "2022-06-01")
    assert run.metrics["trade_count"] == 1
    assert run.metrics["win_rate"] in (0.0, 100.0)


def test_run_backtest_with_expression_config():
    config = {"expression": "close > sma(close, 20) and rsi(close, 14) < 70"}
    run = backtest_engine.run_backtest("TEST", config, "2021-06-01", "2022-06-01")
    for key in ("cumulative_return", "cagr", "mdd", "sharpe", "win_rate", "trade_count"):
        assert key in run.metrics
    assert not run.df.empty
    assert not run.equity_curve.empty
    assert run.equity_curve.iloc[0] == pytest.approx(100.0)


def test_run_backtest_with_invalid_expression_raises():
    from core.expression_engine import ExpressionError

    config = {"expression": "close > undefined_variable"}
    with pytest.raises(ExpressionError):
        backtest_engine.run_backtest("TEST", config, "2021-06-01", "2022-06-01")


def test_compute_regime_breakdown_covers_all_labels_and_sums_to_total_days():
    config = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"}]}
    run = backtest_engine.run_backtest("TEST", config, "2021-06-01", "2022-06-01")
    breakdown = backtest_engine.compute_regime_breakdown(run)
    assert set(breakdown.keys()) == {"강세장", "약세장", "횡보장"}
    total_days = sum(v["trading_days"] for v in breakdown.values())
    assert total_days == len(run.equity_curve)
    for v in breakdown.values():
        if v["trading_days"] == 0:
            assert v["cumulative_return"] is None
        else:
            assert isinstance(v["cumulative_return"], float)


def test_compute_regime_breakdown_empty_equity_curve_returns_empty_dict():
    empty_run = backtest_engine.BacktestRun(
        label="empty",
        ticker="TEST",
        df=pd.DataFrame(),
        position=pd.Series(dtype=float),
        equity_curve=pd.Series(dtype=float),
    )
    assert backtest_engine.compute_regime_breakdown(empty_run) == {}


def test_run_backtest_with_combined_config_and_logic():
    config_a = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"}]}
    config_b = {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 70}]}
    combined_config = {"combine": "AND", "strategies": [config_a, config_b]}

    run = backtest_engine.run_backtest("TEST", combined_config, "2021-06-01", "2022-06-01")
    for key in ("cumulative_return", "cagr", "mdd", "sharpe", "win_rate", "trade_count"):
        assert key in run.metrics
    assert not run.df.empty
    assert not run.equity_curve.empty
    assert run.equity_curve.iloc[0] == pytest.approx(100.0)

    # AND 결합이므로 결합 전략의 포지션 보유일 수는 하위 전략 중 어느 쪽보다도 많을 수 없다.
    run_a = backtest_engine.run_backtest("TEST", config_a, "2021-06-01", "2022-06-01")
    assert run.position.sum() <= run_a.position.sum()


def test_compare_with_benchmarks_has_three_runs():
    config = {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 40}]}
    results = backtest_engine.compare_with_benchmarks("TEST", config, "2021-06-01", "2022-06-01")
    assert set(results.keys()) == {"strategy", "buy_and_hold_ticker", "buy_and_hold_benchmark"}
    for run in results.values():
        assert run.metrics["cumulative_return"] is not None


def test_diagnose_strategy_health_flags_self_canceling_entry_exit():
    # 볼린저 밴드 하단(진입)은 정의상 항상 20일 이평(청산 조건)보다 낮으므로, 진입하는 바로 그 날
    # 청산 조건도 항상 같이 참이 되어 포지션이 하루도 유지되지 못하는 자기모순 설정이다.
    config = {
        "entry_stages": [
            {
                "weight": 1.0,
                "logic": "AND",
                "conditions": [{"indicator": "bollinger", "period": 20, "std_dev": 2.0, "band": "lower"}],
            }
        ],
        "exit_stages": [
            {
                "weight": 1.0,
                "logic": "AND",
                "conditions": [{"indicator": "ma_cross", "short": 1, "long": 20, "ma_type": "sma", "type": "dead"}],
            }
        ],
    }
    warnings = backtest_engine.diagnose_strategy_health(config)
    assert len(warnings) == 1
    assert "진입 당일" in warnings[0]


def test_diagnose_strategy_health_returns_empty_for_healthy_strategy():
    config = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"}]}
    assert backtest_engine.diagnose_strategy_health(config) == []


def test_save_backtest_result_persists_row(db_session, monkeypatch):
    from core.models import Strategy

    strategy = Strategy(name="테스트 전략", indicator_config="{}", source="manual")
    db_session.add(strategy)
    db_session.commit()

    # save_backtest_result 는 함수 내부에서 `from core.db import get_session` 을 매번 새로 임포트하므로,
    # core.db 모듈의 get_session 자체를 바꿔치기해야 테스트 세션이 사용된다.
    import core.db as db_module
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(db_module, "get_session", _fake_get_session)

    metrics = {
        "cumulative_return": 12.3,
        "cagr": 5.6,
        "mdd": -7.8,
        "sharpe": 0.9,
        "win_rate": 55.0,
        "trade_count": 4,
    }
    result_id = backtest_engine.save_backtest_result(
        strategy_id=strategy.id,
        ticker="TEST",
        start="2021-01-01",
        end="2022-01-01",
        metrics=metrics,
        extra_metrics={"note": "unit-test"},
    )
    assert result_id is not None

    from core.models import BacktestResult

    fetched = db_session.query(BacktestResult).filter_by(id=result_id).first()
    assert fetched is not None
    assert fetched.ticker == "TEST"
    assert fetched.cagr == 5.6


# =============================================================================
# 검증 테스트 4종 (Masters) 단위 테스트
# =============================================================================


def _rsi_config(threshold):
    return {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": threshold}]}


def test_run_sensitivity_sweep_returns_one_point_per_variant():
    variants = [(v, _rsi_config(v)) for v in (30, 40, 50, 60, 70)]
    result = backtest_engine.run_sensitivity_sweep("TEST", variants, "2021-06-01", "2022-06-01", metric="sharpe")
    assert len(result["points"]) == 5
    assert [p["param_value"] for p in result["points"]] == [30, 40, 50, 60, 70]
    assert isinstance(result["is_robust"], bool)
    assert result["max_jump"] >= 0
    assert result["metric_range"] >= 0


def test_run_sensitivity_sweep_single_variant_has_no_robustness_verdict():
    variants = [(50, _rsi_config(50))]
    result = backtest_engine.run_sensitivity_sweep("TEST", variants, "2021-06-01", "2022-06-01")
    assert len(result["points"]) == 1
    assert result["is_robust"] is None
    assert result["max_jump"] is None


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


def test_run_permutation_test_returns_distribution_and_pvalue():
    config = _rsi_config(40)
    result = backtest_engine.run_permutation_test(
        "TEST", config, "2021-06-01", "2022-06-01", n_permutations=10, metric="cumulative_return", seed=7
    )
    assert result["n_permutations"] == 10
    assert len(result["permuted_metrics"]) == 10
    assert result["actual_metric"] is not None
    assert 0.0 <= result["p_value"] <= 1.0
    assert 0.0 <= result["percentile"] <= 100.0


def test_run_permutation_test_deterministic_with_seed():
    config = _rsi_config(40)
    result_a = backtest_engine.run_permutation_test(
        "TEST", config, "2021-06-01", "2022-06-01", n_permutations=5, seed=123
    )
    result_b = backtest_engine.run_permutation_test(
        "TEST", config, "2021-06-01", "2022-06-01", n_permutations=5, seed=123
    )
    assert result_a["permuted_metrics"] == result_b["permuted_metrics"]


def test_run_partition_test_components_sum_to_total():
    idx = pd.bdate_range("2021-01-04", periods=10)
    strategy_run = backtest_engine.BacktestRun(
        label="전략",
        ticker="TEST",
        df=pd.DataFrame(index=idx),
        position=pd.Series([0, 1, 1, 1, 0, 0, 1, 1, 0, 0], index=idx, dtype=float),
        equity_curve=pd.Series(100 * np.linspace(1.0, 1.3, 10), index=idx),
    )
    benchmark_run = backtest_engine.BacktestRun(
        label="매수후보유",
        ticker="TEST",
        df=pd.DataFrame(index=idx),
        position=pd.Series([1] * 10, index=idx, dtype=float),
        equity_curve=pd.Series(100 * np.linspace(1.0, 1.5, 10), index=idx),
    )
    result = backtest_engine.run_partition_test(strategy_run, benchmark_run)
    # 정의상 total = trend + skill + bias 가 항상 성립해야 한다 (반올림 오차 허용).
    reconstructed = result["trend_log_return"] + result["skill_log_return"] + result["bias_log_return"]
    assert reconstructed == pytest.approx(result["total_log_return"], abs=1e-3)
    assert 0.0 <= result["exposure_pct"] <= 100.0


def test_run_partition_test_zero_exposure_has_no_trend_or_skill():
    idx = pd.bdate_range("2021-01-04", periods=5)
    flat_run = backtest_engine.BacktestRun(
        label="전략",
        ticker="TEST",
        df=pd.DataFrame(index=idx),
        position=pd.Series([0.0] * 5, index=idx),
        equity_curve=pd.Series([100.0] * 5, index=idx),  # 계속 관망이라 자산가치 변화 없음
    )
    benchmark_run = backtest_engine.BacktestRun(
        label="매수후보유",
        ticker="TEST",
        df=pd.DataFrame(index=idx),
        position=pd.Series([1.0] * 5, index=idx),
        equity_curve=pd.Series(100 * np.linspace(1.0, 1.2, 5), index=idx),
    )
    result = backtest_engine.run_partition_test(flat_run, benchmark_run)
    assert result["total_log_return"] == pytest.approx(0.0, abs=1e-9)
    assert result["trend_log_return"] == pytest.approx(0.0, abs=1e-9)
    assert result["skill_log_return"] == pytest.approx(0.0, abs=1e-9)


def test_run_partition_test_empty_equity_curve_returns_zeros():
    empty_run = backtest_engine.BacktestRun(
        label="empty", ticker="TEST", df=pd.DataFrame(), position=pd.Series(dtype=float), equity_curve=pd.Series(dtype=float)
    )
    result = backtest_engine.run_partition_test(empty_run, empty_run)
    assert result["total_log_return"] == 0.0
    assert result["skill_pct_of_total"] is None


def test_summarize_strategy_vs_benchmarks_flags_wins_and_losses():
    strategy_run = backtest_engine.BacktestRun(
        label="전략",
        ticker="TEST",
        df=pd.DataFrame(),
        position=pd.Series(dtype=float),
        equity_curve=pd.Series(dtype=float),
        metrics={"cumulative_return": 57.0, "cagr": 9.5, "mdd": -8.0, "sharpe": 1.24, "win_rate": 86.0, "trade_count": 44},
    )
    benchmark_run = backtest_engine.BacktestRun(
        label="매수후보유",
        ticker="TEST",
        df=pd.DataFrame(),
        position=pd.Series(dtype=float),
        equity_curve=pd.Series(dtype=float),
        metrics={"cumulative_return": 73.0, "cagr": 11.6, "mdd": -25.0, "sharpe": 0.7, "win_rate": 100.0, "trade_count": 1},
    )
    comparison = {"strategy": strategy_run, "buy_and_hold_ticker": benchmark_run}
    summary = backtest_engine.summarize_strategy_vs_benchmarks(comparison)
    # 영상 사례와 동일한 패턴: 원수익률/CAGR은 졌지만 낙폭 방어력과 위험조정수익률(샤프)은 이겼다.
    assert summary["beats_on_return"] is False
    assert summary["beats_on_cagr"] is False
    assert summary["beats_on_mdd"] is True
    assert summary["beats_on_sharpe"] is True
    assert summary["regime_breakdown"] is None


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


def test_run_backtest_with_fees_matches_manual_compute_equity_curve():
    config = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"}]}
    no_cost_run = backtest_engine.run_backtest("TEST", config, "2021-06-01", "2022-06-01")
    with_cost_run = backtest_engine.run_backtest(
        "TEST", config, "2021-06-01", "2022-06-01", fee_bps=5.0, slippage_bps=10.0
    )
    if with_cost_run.trades:  # 매매가 하나라도 있으면 비용이 있는 쪽이 더 낮아야 한다
        assert with_cost_run.equity_curve.iloc[-1] <= no_cost_run.equity_curve.iloc[-1]


# =============================================================================
# 손익비(Profit Factor) / 칼마지수(Calmar) 단위 테스트
# =============================================================================


def test_calculate_metrics_includes_profit_factor_and_calmar():
    config = {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 40}]}
    run = backtest_engine.run_backtest("TEST", config, "2021-06-01", "2022-06-01")
    assert "profit_factor" in run.metrics
    assert "calmar" in run.metrics
    assert run.metrics["profit_factor"] >= 0.0


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


def test_compute_alpha_decay_returns_expected_shape():
    config = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"}]}
    result = backtest_engine.compute_alpha_decay(
        "TEST", config, "2021-06-01", "2022-06-01", recent_months=6, metric="sharpe"
    )
    assert set(result.keys()) == {
        "full_metrics", "recent_metrics", "metric", "decay_ratio", "is_decayed", "recent_start", "recent_end",
    }
    assert result["metric"] == "sharpe"
    assert isinstance(result["is_decayed"], bool)
    assert pd.Timestamp(result["recent_start"]) < pd.Timestamp(result["recent_end"])


def test_compute_alpha_decay_flags_decay_when_recent_metric_turns_negative(monkeypatch):
    def fake_run_backtest(ticker, config, start, end, label="전략", **kwargs):
        metrics = {"sharpe": 2.0} if start == "2021-06-01" else {"sharpe": -1.0}
        idx = pd.bdate_range("2021-01-04", periods=2)
        return backtest_engine.BacktestRun(
            label=label, ticker=ticker, df=pd.DataFrame({"Close": [1.0, 2.0]}, index=idx),
            position=pd.Series([1.0, 1.0], index=idx), equity_curve=pd.Series([100.0, 101.0], index=idx),
            trades=[], metrics=metrics,
        )

    monkeypatch.setattr(backtest_engine, "run_backtest", fake_run_backtest)
    result = backtest_engine.compute_alpha_decay("TEST", {}, "2021-06-01", "2022-06-01", recent_months=6, metric="sharpe")
    assert result["is_decayed"] is True
    assert result["decay_ratio"] == pytest.approx(-0.5)


def test_compute_alpha_decay_empty_data_returns_safe_defaults(monkeypatch):
    def fake_get_price_history(ticker, start=None, end=None, interval="1d", use_cache=True, **kwargs):
        return pd.DataFrame()

    monkeypatch.setattr(backtest_engine, "get_price_history", fake_get_price_history)
    result = backtest_engine.compute_alpha_decay("NODATA", {}, "2021-06-01", "2022-06-01")
    assert result["is_decayed"] is False
    assert result["decay_ratio"] is None


def test_save_and_list_decay_checks(db_session, monkeypatch):
    from contextlib import contextmanager

    from core.models import Strategy

    strategy = Strategy(name="테스트 전략", indicator_config="{}", source="manual")
    db_session.add(strategy)
    db_session.commit()

    import core.db as db_module

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(db_module, "get_session", _fake_get_session)

    result = {
        "full_metrics": {"sharpe": 1.5},
        "recent_metrics": {"sharpe": 0.2},
        "metric": "sharpe",
        "decay_ratio": 0.13,
        "is_decayed": True,
        "recent_start": "2022-01-01",
        "recent_end": "2022-06-01",
    }
    check_id = backtest_engine.save_decay_check("TEST", result, strategy_id=strategy.id)
    assert check_id is not None

    history = backtest_engine.list_decay_checks(strategy.id)
    assert len(history) == 1
    assert history[0]["ticker"] == "TEST"
    assert history[0]["is_decayed"] is True
    assert history[0]["decay_ratio"] == pytest.approx(0.13)


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


def test_trade_count_reliability_warning_low_count_is_strong_warning():
    msg = backtest_engine.trade_count_reliability_warning(10)
    assert msg is not None and "⚠️" in msg


def test_trade_count_reliability_warning_medium_count_is_info():
    msg = backtest_engine.trade_count_reliability_warning(100)
    assert msg is not None and "ℹ️" in msg


def test_trade_count_reliability_warning_high_count_returns_none():
    assert backtest_engine.trade_count_reliability_warning(500) is None


# =============================================================================
# 전략 포트폴리오 상관관계("홀리그레일") 단위 테스트
# =============================================================================

_MA_CROSS_CONFIG = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"}]}
_RSI40_CONFIG = {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 40}]}


def test_run_strategy_portfolio_returns_one_run_per_strategy():
    strategies = [("A", "TEST", _MA_CROSS_CONFIG), ("B", "TEST", _RSI40_CONFIG)]
    runs = backtest_engine.run_strategy_portfolio(strategies, "2021-06-01", "2022-06-01")
    assert set(runs.keys()) == {"A", "B"}
    for run in runs.values():
        assert not run.df.empty


def test_compute_strategy_correlation_returns_symmetric_matrix():
    strategies = [("A", "TEST", _MA_CROSS_CONFIG), ("B", "TEST", _RSI40_CONFIG)]
    runs = backtest_engine.run_strategy_portfolio(strategies, "2021-06-01", "2022-06-01")
    corr = backtest_engine.compute_strategy_correlation(runs)
    assert list(corr.columns) == ["A", "B"]
    assert corr.loc["A", "A"] == pytest.approx(1.0)
    assert corr.loc["A", "B"] == pytest.approx(corr.loc["B", "A"])


def test_compute_strategy_correlation_identical_strategies_have_correlation_one():
    strategies = [("A", "TEST", _MA_CROSS_CONFIG), ("B", "TEST", _MA_CROSS_CONFIG)]
    runs = backtest_engine.run_strategy_portfolio(strategies, "2021-06-01", "2022-06-01")
    corr = backtest_engine.compute_strategy_correlation(runs)
    assert corr.loc["A", "B"] == pytest.approx(1.0, abs=1e-6)


def test_compute_strategy_correlation_single_strategy_returns_empty():
    strategies = [("A", "TEST", _RSI40_CONFIG)]
    runs = backtest_engine.run_strategy_portfolio(strategies, "2021-06-01", "2022-06-01")
    assert backtest_engine.compute_strategy_correlation(runs).empty


def test_compute_strategy_regime_correlation_delegates_to_market_regime(monkeypatch):
    import core.market_regime as market_regime

    def fake_regime_corr(daily_returns, benchmark_ticker="^GSPC"):
        return {"강세장": daily_returns.corr(), "약세장": pd.DataFrame(), "횡보장": pd.DataFrame()}

    monkeypatch.setattr(market_regime, "compute_regime_conditional_correlation", fake_regime_corr)

    strategies = [("A", "TEST", _MA_CROSS_CONFIG), ("B", "TEST", _RSI40_CONFIG)]
    runs = backtest_engine.run_strategy_portfolio(strategies, "2021-06-01", "2022-06-01")
    result = backtest_engine.compute_strategy_regime_correlation(runs)
    assert set(result.keys()) == {"강세장", "약세장", "횡보장"}
    assert list(result["강세장"].columns) == ["A", "B"]


def test_compute_strategy_regime_correlation_insufficient_runs_returns_empty_dict():
    strategies = [("A", "TEST", _RSI40_CONFIG)]
    runs = backtest_engine.run_strategy_portfolio(strategies, "2021-06-01", "2022-06-01")
    assert backtest_engine.compute_strategy_regime_correlation(runs) == {}


def test_save_and_list_strategy_correlation_snapshots(db_session, monkeypatch):
    from contextlib import contextmanager

    import core.db as db_module

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(db_module, "get_session", _fake_get_session)

    corr = pd.DataFrame({"A": [1.0, 0.4], "B": [0.4, 1.0]}, index=["A", "B"])
    snap_id = backtest_engine.save_strategy_correlation_snapshot(corr)
    assert snap_id is not None

    history = backtest_engine.list_strategy_correlation_snapshots()
    assert len(history) == 1
    assert history[0]["labels"] == ["A", "B"]
    assert history[0]["avg_correlation"] == pytest.approx(0.4)
    assert history[0]["max_correlation"] == pytest.approx(0.4)


def test_save_strategy_correlation_snapshot_requires_at_least_two_labels():
    corr = pd.DataFrame({"A": [1.0]}, index=["A"])
    with pytest.raises(ValueError):
        backtest_engine.save_strategy_correlation_snapshot(corr)


# =============================================================================
# 앙상블 스코어링 전략의 백테스트 엔진 연동 단위 테스트
# =============================================================================


def test_run_backtest_with_ensemble_config_computes_all_metrics():
    config = {
        "schema": "ensemble",
        "indicators": [
            {"indicator": "rsi", "weight": 1.0},
            {"indicator": "ma_spread", "short": 20, "long": 60, "weight": 1.0},
        ],
        "entry_threshold": 0.3,
        "exit_threshold": 0.1,
    }
    run = backtest_engine.run_backtest("TEST", config, "2021-06-01", "2022-06-01")
    for key in (
        "cumulative_return", "cagr", "mdd", "sharpe", "win_rate", "trade_count",
        "profit_factor", "calmar", "avg_drawdown_days",
    ):
        assert key in run.metrics
    assert not run.df.empty
    assert not run.equity_curve.empty
    assert (run.position >= 0).all() and (run.position <= 1).all()


def test_run_backtest_ensemble_size_by_score_false_is_binary_position():
    config = {
        "schema": "ensemble", "indicators": [{"indicator": "rsi"}],
        "entry_threshold": 0.3, "exit_threshold": 0.1, "size_by_score": False,
    }
    run = backtest_engine.run_backtest("TEST", config, "2021-06-01", "2022-06-01")
    assert set(run.position.unique().tolist()) <= {0.0, 1.0}


def test_run_backtest_ensemble_with_fees_does_not_crash():
    config = {"schema": "ensemble", "indicators": [{"indicator": "rsi"}], "entry_threshold": 0.3, "exit_threshold": 0.1}
    run = backtest_engine.run_backtest("TEST", config, "2021-06-01", "2022-06-01", fee_bps=5.0, slippage_bps=10.0)
    assert not run.equity_curve.empty
