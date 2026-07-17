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
    assert set(breakdown.keys()) == {"강세장", "약세장", "중립"}
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
