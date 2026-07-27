"""core/position_sizing.py 단위 테스트."""

import numpy as np
import pandas as pd
import pytest

import core.position_sizing as position_sizing


# ----------------------------------------------------------------------------
# compute_trade_stats
# ----------------------------------------------------------------------------


class _FakeTrade:
    def __init__(self, return_pct):
        self.return_pct = return_pct


def test_compute_trade_stats_basic():
    trades = [_FakeTrade(10.0), _FakeTrade(-5.0), _FakeTrade(20.0), _FakeTrade(None)]
    stats = position_sizing.compute_trade_stats(trades)
    assert stats.trade_count == 3
    assert stats.win_rate == pytest.approx(2 / 3)
    assert stats.avg_win_pct == pytest.approx(15.0)
    assert stats.avg_loss_pct == pytest.approx(5.0)


def test_compute_trade_stats_no_completed_trades_returns_none():
    trades = [_FakeTrade(None), _FakeTrade(None)]
    assert position_sizing.compute_trade_stats(trades) is None


def test_compute_trade_stats_all_wins_has_zero_avg_loss():
    trades = [_FakeTrade(5.0), _FakeTrade(10.0)]
    stats = position_sizing.compute_trade_stats(trades)
    assert stats.win_rate == 1.0
    assert stats.avg_loss_pct == 0.0


# ----------------------------------------------------------------------------
# 방법 1: 고정 % 리스크
# ----------------------------------------------------------------------------


def test_fixed_fractional_size_computes_shares_from_stop_distance():
    result = position_sizing.fixed_fractional_size(
        account_value=10000.0, risk_pct=2.0, entry_price=100.0, stop_price=90.0
    )
    # 리스크금액 = 10000*0.02 = 200, 주당리스크 = 10 -> 20주
    assert result["risk_amount"] == pytest.approx(200.0)
    assert result["shares"] == pytest.approx(20.0)
    assert result["position_value"] == pytest.approx(2000.0)
    assert result["position_pct_of_account"] == pytest.approx(20.0)


def test_fixed_fractional_size_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        position_sizing.fixed_fractional_size(0.0, 2.0, 100.0, 90.0)
    with pytest.raises(ValueError):
        position_sizing.fixed_fractional_size(10000.0, 2.0, 100.0, 100.0)
    with pytest.raises(ValueError):
        position_sizing.fixed_fractional_size(10000.0, 2.0, -1.0, 90.0)


# ----------------------------------------------------------------------------
# 방법 2: 동일가중
# ----------------------------------------------------------------------------


def test_equal_weight_size_splits_evenly():
    result = position_sizing.equal_weight_size(10000.0, 4)
    assert result["position_value"] == pytest.approx(2500.0)
    assert result["position_pct_of_account"] == pytest.approx(25.0)


def test_equal_weight_size_rejects_invalid_n():
    with pytest.raises(ValueError):
        position_sizing.equal_weight_size(10000.0, 0)


# ----------------------------------------------------------------------------
# 방법 3: 켈리 기준
# ----------------------------------------------------------------------------


def test_kelly_fraction_positive_edge():
    # 승률 60%, 평균승리 10%, 평균손실 5% -> R=2, f* = 0.6 - 0.4/2 = 0.4
    result = position_sizing.kelly_fraction(0.6, 10.0, 5.0, safety_fraction=None)
    assert result["full_kelly"] == pytest.approx(0.4)
    assert result["recommended_fraction"] == pytest.approx(0.4)
    assert result["payoff_ratio"] == pytest.approx(2.0)


def test_kelly_fraction_half_kelly_is_half_of_full():
    result = position_sizing.kelly_fraction(0.6, 10.0, 5.0, safety_fraction=0.5)
    assert result["recommended_fraction"] == pytest.approx(result["full_kelly"] * 0.5)


def test_kelly_fraction_no_edge_clips_to_zero():
    # 승률 30%, R=1 -> f* = 0.3 - 0.7 = -0.4 (음수) -> 0으로 클립
    result = position_sizing.kelly_fraction(0.3, 5.0, 5.0)
    assert result["full_kelly"] == 0.0
    assert result["recommended_fraction"] == 0.0


def test_kelly_fraction_zero_avg_loss_returns_zero():
    result = position_sizing.kelly_fraction(0.6, 10.0, 0.0)
    assert result == {"full_kelly": 0.0, "recommended_fraction": 0.0, "payoff_ratio": None}


def test_kelly_fraction_rejects_invalid_win_rate():
    with pytest.raises(ValueError):
        position_sizing.kelly_fraction(1.5, 10.0, 5.0)


# ----------------------------------------------------------------------------
# 방법 4: 변동성 타겟팅
# ----------------------------------------------------------------------------


def test_volatility_target_weight_scales_inversely_with_asset_vol():
    low_vol_weight = position_sizing.volatility_target_weight(target_annual_vol_pct=15.0, asset_annual_vol_pct=15.0)
    high_vol_weight = position_sizing.volatility_target_weight(target_annual_vol_pct=15.0, asset_annual_vol_pct=60.0)
    assert low_vol_weight == pytest.approx(1.0)
    assert high_vol_weight == pytest.approx(0.25)
    assert high_vol_weight < low_vol_weight


def test_volatility_target_weight_capped_at_max_weight():
    weight = position_sizing.volatility_target_weight(target_annual_vol_pct=30.0, asset_annual_vol_pct=10.0, max_weight=1.0)
    assert weight == pytest.approx(1.0)  # 30/10=3.0이지만 상한 1.0으로 캡


def test_volatility_target_weight_zero_asset_vol_returns_zero():
    assert position_sizing.volatility_target_weight(15.0, 0.0) == 0.0


def test_volatility_target_weight_rejects_invalid_target():
    with pytest.raises(ValueError):
        position_sizing.volatility_target_weight(0.0, 10.0)


def test_realized_annual_volatility_pct_computes_positive_value():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2021-01-04", periods=60)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0, 0.01, 60)), index=idx)
    vol = position_sizing.realized_annual_volatility_pct(close, lookback_days=20)
    assert vol is not None
    assert vol > 0


def test_realized_annual_volatility_pct_insufficient_data_returns_none():
    close = pd.Series([100.0])
    assert position_sizing.realized_annual_volatility_pct(close) is None


def test_portfolio_volatility_target_weights_sums_to_one_and_favors_low_vol():
    idx = pd.bdate_range("2021-01-04", periods=100)
    rng = np.random.default_rng(1)
    low_vol_returns = rng.normal(0.0, 0.005, 100)
    high_vol_returns = rng.normal(0.0, 0.03, 100)
    daily_returns = pd.DataFrame({"LOW": low_vol_returns, "HIGH": high_vol_returns}, index=idx)

    weights = position_sizing.portfolio_volatility_target_weights(daily_returns)
    assert weights["LOW"] > weights["HIGH"]
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)


def test_portfolio_volatility_target_weights_empty_input_returns_empty_dict():
    assert position_sizing.portfolio_volatility_target_weights(pd.DataFrame()) == {}
