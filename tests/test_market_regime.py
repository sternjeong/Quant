"""core/market_regime.py 단위 테스트 (모듈 G 확장: 시장 국면 룰 기반 복합지표).

네트워크(yfinance)를 타지 않도록 core.market_data 함수를 모두 monkeypatch 로 대체한다.
"""

import numpy as np
import pandas as pd
import pytest

import core.market_regime as market_regime


def _close_series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx, name="Close")


def _uptrend_series(n: int = 300, start: float = 100.0, daily_pct: float = 0.15) -> pd.Series:
    values = [start * (1 + daily_pct / 100) ** i for i in range(n)]
    return _close_series(values)


def _downtrend_series(n: int = 300, start: float = 100.0, daily_pct: float = 0.3) -> pd.Series:
    values = [start * (1 - daily_pct / 100) ** i for i in range(n)]
    return _close_series(values)


# ----------------------------------------------------------------------------
# score_trend_position
# ----------------------------------------------------------------------------


def test_score_trend_position_above_200sma_is_bullish():
    close = _uptrend_series()
    result = market_regime.score_trend_position(close)
    assert result["above_200sma"] is True
    assert result["score"] == 25.0


def test_score_trend_position_below_200sma_is_bearish():
    close = _downtrend_series()
    result = market_regime.score_trend_position(close)
    assert result["above_200sma"] is False
    assert result["score"] == -25.0


def test_score_trend_position_insufficient_data_returns_none():
    assert market_regime.score_trend_position(_close_series([100.0] * 50)) is None


# ----------------------------------------------------------------------------
# score_ma_cross
# ----------------------------------------------------------------------------


def test_score_ma_cross_golden_when_uptrend():
    close = _uptrend_series()
    result = market_regime.score_ma_cross(close)
    assert result["golden_cross"] is True
    assert result["score"] == 25.0


def test_score_ma_cross_death_when_downtrend():
    close = _downtrend_series()
    result = market_regime.score_ma_cross(close)
    assert result["golden_cross"] is False
    assert result["score"] == -25.0


# ----------------------------------------------------------------------------
# score_drawdown
# ----------------------------------------------------------------------------


def test_score_drawdown_at_new_high_is_zero():
    close = _uptrend_series()
    result = market_regime.score_drawdown(close)
    assert result["drawdown_pct"] == pytest.approx(0.0, abs=1e-6)
    assert result["score"] == pytest.approx(0.0, abs=1e-6)
    assert result["is_bear_market_drawdown"] is False


def test_score_drawdown_at_bear_market_threshold_clips_to_min():
    # 고점 100 -> 마지막 종가 75 = -25% 낙폭 (기준 -20%보다 더 깊음 -> -25점에서 클립)
    values = [100.0] * 10 + [75.0]
    result = market_regime.score_drawdown(_close_series(values))
    assert result["drawdown_pct"] == pytest.approx(-25.0)
    assert result["score"] == pytest.approx(-25.0)
    assert result["is_bear_market_drawdown"] is True


def test_score_drawdown_partial_correction_is_linear():
    # 고점 100 -> 마지막 종가 90 = -10% 낙폭 (기준 -20%의 절반 -> -12.5점)
    values = [100.0] * 10 + [90.0]
    result = market_regime.score_drawdown(_close_series(values))
    assert result["score"] == pytest.approx(-12.5)


# ----------------------------------------------------------------------------
# score_breadth
# ----------------------------------------------------------------------------


def test_score_breadth_bullish_clips_at_70pct():
    result = market_regime.score_breadth(70.0)
    assert result["score"] == pytest.approx(25.0)
    result_extreme = market_regime.score_breadth(95.0)
    assert result_extreme["score"] == pytest.approx(25.0)
    assert result_extreme["is_overheated"] is True


def test_score_breadth_bearish_clips_at_30pct():
    result = market_regime.score_breadth(30.0)
    assert result["score"] == pytest.approx(-25.0)


def test_score_breadth_neutral_midpoint_is_zero():
    result = market_regime.score_breadth(50.0)
    assert result["score"] == pytest.approx(0.0)


# ----------------------------------------------------------------------------
# compute_market_breadth
# ----------------------------------------------------------------------------


def test_compute_market_breadth_counts_tickers_above_200sma(monkeypatch):
    histories = {
        "UP1": _uptrend_series(),
        "UP2": _uptrend_series(),
        "DOWN1": _downtrend_series(),
        "NODATA": pd.DataFrame(),
    }

    def _fake_multi(tickers, start=None, end=None, interval="1d", use_cache=True):
        return {t: (histories[t].to_frame(name="Close") if isinstance(histories[t], pd.Series) else histories[t]) for t in tickers}

    monkeypatch.setattr(market_regime, "get_multiple_price_history", _fake_multi)

    result = market_regime.compute_market_breadth(["UP1", "UP2", "DOWN1", "NODATA"])
    assert result["n_total"] == 4
    assert result["n_data_ok"] == 3
    assert result["n_above"] == 2
    assert result["pct_above_200sma"] == pytest.approx(2 / 3 * 100)


# ----------------------------------------------------------------------------
# classify_regime
# ----------------------------------------------------------------------------


def test_classify_regime_thresholds():
    assert market_regime.classify_regime(80) == "강세장"
    assert market_regime.classify_regime(-80) == "약세장"
    assert market_regime.classify_regime(0) == "중립/혼조"
    assert market_regime.classify_regime(market_regime.BULLISH_THRESHOLD) == "강세장"
    assert market_regime.classify_regime(market_regime.BEARISH_THRESHOLD) == "약세장"


# ----------------------------------------------------------------------------
# get_market_regime_snapshot (integration of the above, network mocked)
# ----------------------------------------------------------------------------


def test_get_market_regime_snapshot_strong_bull(monkeypatch):
    benchmark = _uptrend_series()
    monkeypatch.setattr(market_regime, "get_price_history", lambda *a, **k: benchmark.to_frame(name="Close"))
    monkeypatch.setattr(
        market_regime, "get_multiple_price_history",
        lambda tickers, **k: {t: _uptrend_series().to_frame(name="Close") for t in tickers},
    )

    snapshot = market_regime.get_market_regime_snapshot(["A", "B", "C"])
    assert snapshot["regime"] == "강세장"
    assert snapshot["total_score"] > market_regime.BULLISH_THRESHOLD
    assert snapshot["trend_position"]["above_200sma"] is True
    assert snapshot["ma_cross"]["golden_cross"] is True


def test_get_market_regime_snapshot_strong_bear(monkeypatch):
    benchmark = _downtrend_series()
    monkeypatch.setattr(market_regime, "get_price_history", lambda *a, **k: benchmark.to_frame(name="Close"))
    monkeypatch.setattr(
        market_regime, "get_multiple_price_history",
        lambda tickers, **k: {t: _downtrend_series().to_frame(name="Close") for t in tickers},
    )

    snapshot = market_regime.get_market_regime_snapshot(["A", "B", "C"])
    assert snapshot["regime"] == "약세장"
    assert snapshot["total_score"] < market_regime.BEARISH_THRESHOLD


def test_get_market_regime_snapshot_empty_benchmark_data(monkeypatch):
    monkeypatch.setattr(market_regime, "get_price_history", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(market_regime, "get_multiple_price_history", lambda tickers, **k: {})

    snapshot = market_regime.get_market_regime_snapshot(["A"])
    assert snapshot["trend_position"] is None
    assert snapshot["ma_cross"] is None
    assert snapshot["drawdown"] is None
    assert snapshot["regime"] == "중립/혼조"
