"""core/market_regime.py 단위 테스트 (모듈 G 확장: 시장 국면 룰 기반 복합지표).

네트워크(yfinance)를 타지 않도록 core.market_data 함수를 모두 monkeypatch 로 대체한다.
"""

from datetime import datetime, timedelta

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
    assert snapshot["short_term"] == {"1개월": None, "3개월": None}


# ----------------------------------------------------------------------------
# classify_period_return_regime / get_short_term_regimes (단기 국면)
# ----------------------------------------------------------------------------


def test_classify_period_return_regime_bullish_when_return_above_threshold():
    close = _close_series([100.0] * 10 + [110.0] * 15)  # 21거래일 전 대비 +10%
    result = market_regime.classify_period_return_regime(close, window_days=21)
    assert result["regime"] == "강세장"
    assert result["period_return_pct"] >= market_regime.SHORT_TERM_BULLISH_PCT


def test_classify_period_return_regime_bearish_when_return_below_threshold():
    close = _close_series([100.0] * 10 + [90.0] * 15)  # 21거래일 전 대비 -10%
    result = market_regime.classify_period_return_regime(close, window_days=21)
    assert result["regime"] == "약세장"
    assert result["period_return_pct"] <= market_regime.SHORT_TERM_BEARISH_PCT


def test_classify_period_return_regime_neutral_when_flat():
    close = _close_series([100.0] * 30)
    result = market_regime.classify_period_return_regime(close, window_days=21)
    assert result["regime"] == "중립/혼조"
    assert result["period_return_pct"] == pytest.approx(0.0)


def test_classify_period_return_regime_insufficient_data_returns_none():
    assert market_regime.classify_period_return_regime(_close_series([100.0] * 10), window_days=21) is None


def test_get_short_term_regimes_returns_both_windows():
    close = _uptrend_series(n=100, daily_pct=0.3)  # 21/63거래일 전 대비 각각 +6.6%/+20% 안팎
    result = market_regime.get_short_term_regimes(close)
    assert set(result.keys()) == {"1개월", "3개월"}
    assert result["1개월"]["regime"] == "강세장"
    assert result["3개월"]["regime"] == "강세장"


# ----------------------------------------------------------------------------
# classify_daily_regime / find_regime_segments / historical_regime_segments
# (SPEC STRATEGY_TUNING_ENGINE_SPEC.md 13.3/13.4절 -- 국면별 분리 트레이닝용 이력 라벨링)
# ----------------------------------------------------------------------------


def _steady_climb_then_crash(
    climb_days: int = 260, climb_start: float = 100.0, climb_end: float = 200.0,
    crash_days: int = 60, crash_end: float = 100.0,
) -> pd.Series:
    """꾸준히 오르다가(강세장 신호를 남길 만큼 길게) 마지막에 20%+ 급락하는(약세장 신호) 시계열."""
    climb = np.linspace(climb_start, climb_end, climb_days)
    crash = np.linspace(climb_end, crash_end, crash_days + 1)[1:]  # climb의 마지막 값과 중복 안 되게
    values = list(climb) + list(crash)
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx, name="Close")


def _synthetic_high_low(close: pd.Series, spread_pct: float = 1.0) -> tuple[pd.Series, pd.Series]:
    """종가 시계열로부터 합성 고가/저가를 만든다 (ADX 계산에 필요 — 실제 변동폭처럼 종가 주변에 ±spread_pct%)."""
    high = close * (1 + spread_pct / 100)
    low = close * (1 - spread_pct / 100)
    return high, low


def test_classify_daily_regime_labels_late_uptrend_day_as_bull():
    close = _steady_climb_then_crash()
    high, low = _synthetic_high_low(close)
    regime = market_regime.classify_daily_regime(close, high, low)
    # 급락 직전(= 상승 구간 막바지, 신고가 근처 + 200일선 위 + 뚜렷한 추세)은 강세장이어야 한다.
    pre_crash_day = close.index[259]
    assert regime.loc[pre_crash_day] == "강세장"


def test_classify_daily_regime_labels_crash_day_as_bear():
    close = _steady_climb_then_crash()
    high, low = _synthetic_high_low(close)
    regime = market_regime.classify_daily_regime(close, high, low)
    # 52주 고점 대비 -20% 이상 급락한 마지막 날은 다른 신호와 무관하게 약세장이어야 한다.
    assert regime.iloc[-1] == "약세장"
    last_close = close.iloc[-1]
    rolling_high = close.iloc[-260:].max()
    assert (last_close / rolling_high - 1) * 100 <= market_regime.BEAR_MARKET_DRAWDOWN_PCT


def test_classify_daily_regime_flat_price_is_sideways():
    # 거의 안 움직이는(횡보) 시계열 -> ADX가 낮아 "횡보장"으로 분류돼야 한다.
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    rng = np.random.default_rng(0)
    close = pd.Series(100.0 + rng.normal(0, 0.05, len(idx)), index=idx, name="Close")
    high, low = _synthetic_high_low(close, spread_pct=0.1)
    regime = market_regime.classify_daily_regime(close, high, low)
    assert regime.iloc[-1] == "횡보장"


def test_classify_daily_regime_short_history_is_all_sideways():
    close = _close_series([100.0 + i for i in range(50)])  # 200일 미만 -> SMA200/ADX 계산 불가
    high, low = _synthetic_high_low(close)
    regime = market_regime.classify_daily_regime(close, high, low)
    assert (regime == "횡보장").all()


def test_classify_daily_regime_empty_input_returns_empty_series():
    empty = pd.Series(dtype=float)
    assert market_regime.classify_daily_regime(empty, empty, empty).empty


def test_find_regime_segments_extracts_contiguous_ranges_and_drops_short_ones():
    idx = pd.date_range("2024-01-01", periods=70, freq="B")
    labels = (
        ["중립"] * 5
        + ["강세장"] * 30  # 충분히 긴 구간 -> 채택
        + ["중립"] * 5
        + ["강세장"] * 3  # min_trading_days(기본 20) 미만 -> 버려짐
        + ["약세장"] * 27
    )
    regime = pd.Series(labels, index=idx)

    bull_segments = market_regime.find_regime_segments(regime, "강세장")
    bear_segments = market_regime.find_regime_segments(regime, "약세장")

    assert len(bull_segments) == 1  # 짧은 두 번째 강세장 구간은 버려짐
    assert bull_segments[0] == (idx[5].date().isoformat(), idx[34].date().isoformat())
    assert len(bear_segments) == 1
    assert bear_segments[0] == (idx[43].date().isoformat(), idx[-1].date().isoformat())


def test_find_regime_segments_empty_input_returns_empty_list():
    assert market_regime.find_regime_segments(pd.Series(dtype=object), "강세장") == []


def test_find_regime_segments_respects_custom_min_trading_days():
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    regime = pd.Series(["강세장"] * 5 + ["중립"] * 5, index=idx)
    assert market_regime.find_regime_segments(regime, "강세장", min_trading_days=10) == []
    assert market_regime.find_regime_segments(regime, "강세장", min_trading_days=5) == [
        (idx[0].date().isoformat(), idx[4].date().isoformat())
    ]


def test_historical_regime_segments_clips_to_requested_range(monkeypatch):
    close = _steady_climb_then_crash()
    high, low = _synthetic_high_low(close)
    df = pd.DataFrame({"Close": close, "High": high, "Low": low})
    monkeypatch.setattr(market_regime, "get_price_history", lambda *a, **k: df)

    start = close.index[100].date().isoformat()
    end = close.index[-1].date().isoformat()
    segments = market_regime.historical_regime_segments(start, end)

    assert set(segments.keys()) == {"강세장", "약세장", "횡보장"}
    for seg_list in segments.values():
        for seg_start, seg_end in seg_list:
            assert pd.Timestamp(seg_start) >= pd.Timestamp(start)
            assert pd.Timestamp(seg_end) <= pd.Timestamp(end)
    assert segments["약세장"]  # 급락 구간이 요청 범위 안에 있으므로 최소 1개는 있어야 함


def test_historical_regime_segments_empty_price_data_returns_empty_lists(monkeypatch):
    monkeypatch.setattr(market_regime, "get_price_history", lambda *a, **k: pd.DataFrame())
    segments = market_regime.historical_regime_segments("2024-01-01", "2024-06-01")
    assert segments == {"강세장": [], "약세장": [], "횡보장": []}


# ----------------------------------------------------------------------------
# save_market_regime_snapshot / get_latest_market_regime_snapshot
# ----------------------------------------------------------------------------


def _patch_session(monkeypatch, db_session):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(market_regime, "get_session", _fake_get_session)


def test_get_latest_market_regime_snapshot_returns_none_when_empty(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    assert market_regime.get_latest_market_regime_snapshot() is None


def test_save_and_get_latest_market_regime_snapshot_roundtrip(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    snapshot = {
        "regime": "강세장", "total_score": 74.0,
        "trend_position": {"score": 25.0, "above_200sma": True},
        "ma_cross": {"score": 25.0, "golden_cross": True},
        "drawdown": {"score": 0.0, "drawdown_pct": 0.0},
        "breadth": {"score": 24.0, "pct_above_200sma": 69.2},
        "benchmark_ticker": "^GSPC",
    }

    row_id = market_regime.save_market_regime_snapshot(snapshot)
    assert row_id is not None

    latest = market_regime.get_latest_market_regime_snapshot()
    assert latest["regime"] == "강세장"
    assert latest["total_score"] == pytest.approx(74.0)
    assert latest["breadth"]["pct_above_200sma"] == pytest.approx(69.2)
    assert "computed_at" in latest


def test_get_latest_market_regime_snapshot_returns_most_recent(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    market_regime.save_market_regime_snapshot(
        {"regime": "약세장", "total_score": -40.0, "trend_position": None, "ma_cross": None,
         "drawdown": None, "breadth": {"score": -25.0}}
    )
    market_regime.save_market_regime_snapshot(
        {"regime": "강세장", "total_score": 50.0, "trend_position": None, "ma_cross": None,
         "drawdown": None, "breadth": {"score": 25.0}}
    )

    latest = market_regime.get_latest_market_regime_snapshot()
    assert latest["regime"] == "강세장"
    assert latest["total_score"] == pytest.approx(50.0)


# ----------------------------------------------------------------------------
# is_snapshot_stale_for_today_kst / to_kst (2026-07-15: 클라우드 배포 대응 — 별도 상시 스케줄러
# 프로세스 없이도 한국시간 자정이 지난 뒤 첫 방문이 스스로 재계산을 트리거하기 위한 판정)
# ----------------------------------------------------------------------------


def test_is_snapshot_stale_for_today_kst_true_for_old_timestamp():
    old = datetime.utcnow() - timedelta(days=2)
    assert market_regime.is_snapshot_stale_for_today_kst(old) is True


def test_is_snapshot_stale_for_today_kst_false_for_just_computed():
    now = datetime.utcnow()
    assert market_regime.is_snapshot_stale_for_today_kst(now) is False


def test_is_snapshot_stale_for_today_kst_respects_kst_day_boundary_not_utc():
    # "지금"이 UTC로는 2026-07-15 16:30(=KST 2026-07-16 01:30, 이미 다음날)인 상황을 now_kst로 주입.
    # computed_at은 UTC 2026-07-15 15:05(=KST 2026-07-16 00:05, 방금 막 자정을 넘긴 시점)에 계산된
    # 스냅샷 -> UTC 날짜만 비교했다면(둘 다 UTC 07-15) "같은 날"로 오판하지만, 실제로는 KST 기준
    # 같은 날(07-16)이므로 stale이 아니어야 한다.
    now_kst = datetime(2026, 7, 16, 1, 30, tzinfo=market_regime.KST)
    computed_at_utc = datetime(2026, 7, 15, 15, 5)
    assert market_regime.is_snapshot_stale_for_today_kst(computed_at_utc, now_kst=now_kst) is False

    # 반대로 KST로 하루 전날 계산된 스냅샷은 stale이어야 한다.
    stale_computed_at_utc = datetime(2026, 7, 14, 15, 5)  # KST 2026-07-15 00:05
    assert market_regime.is_snapshot_stale_for_today_kst(stale_computed_at_utc, now_kst=now_kst) is True


def test_to_kst_converts_naive_utc_to_kst_correctly():
    utc_dt = datetime(2026, 7, 15, 15, 0, 0)  # UTC 15:00 = KST 다음날 00:00
    kst_dt = market_regime.to_kst(utc_dt)
    assert kst_dt.year == 2026 and kst_dt.month == 7 and kst_dt.day == 16
    assert kst_dt.hour == 0


# ----------------------------------------------------------------------------
# score_vix / score_credit_spread / score_yield_curve_3m / get_advisory_risk_signals
# (2026-07-17, 심층 리스크 신호 — 참고용, 종합 점수에는 미반영)
# ----------------------------------------------------------------------------


def test_score_vix_calm_below_15_is_positive():
    result = market_regime.score_vix(pd.Series([12.0]))
    assert result["band"] == "안정(낮은 변동성)"
    assert result["score"] == 10.0


def test_score_vix_panic_above_30_is_max_penalty():
    result = market_regime.score_vix(pd.Series([45.0]))
    assert result["band"] == "패닉"
    assert result["score"] == -25.0


def test_score_vix_empty_series_returns_none():
    assert market_regime.score_vix(pd.Series(dtype=float)) is None


def test_score_credit_spread_converts_pct_to_bp_and_bands():
    # FRED BAMLH0A0HYM2는 % 단위로 온다 (4.5% == 450bp, "정상" 밴드)
    result = market_regime.score_credit_spread(pd.Series([4.5]))
    assert result["level_bp"] == pytest.approx(450.0)
    assert result["band"] == "정상"
    assert result["score"] == 0.0


def test_score_credit_spread_acute_stress_above_1000bp():
    result = market_regime.score_credit_spread(pd.Series([11.0]))
    assert result["band"] == "급성 스트레스"
    assert result["score"] == -25.0


def test_score_credit_spread_includes_20d_change_when_enough_history():
    values = [5.0] * 20 + [6.0]  # 500bp -> 600bp, +100bp
    result = market_regime.score_credit_spread(pd.Series(values))
    assert result["change_20d_bp"] == pytest.approx(100.0)


def test_score_credit_spread_empty_series_returns_none():
    assert market_regime.score_credit_spread(pd.Series(dtype=float)) is None


def test_score_yield_curve_3m_inverted_is_warning():
    result = market_regime.score_yield_curve_3m(-0.3)
    assert result["inverted"] is True
    assert result["band"] == "역전(침체 선행경보)"
    assert result["score"] == -20.0


def test_score_yield_curve_3m_normal_positive_spread():
    result = market_regime.score_yield_curve_3m(1.2)
    assert result["inverted"] is False
    assert result["band"] == "정상(우상향)"


def test_score_yield_curve_3m_none_input_returns_none():
    assert market_regime.score_yield_curve_3m(None) is None


def test_get_advisory_risk_signals_without_fred_key_still_computes_vix(monkeypatch):
    vix_close = pd.Series([18.0], index=pd.date_range("2026-06-01", periods=1))
    monkeypatch.setattr(market_regime, "get_price_history", lambda *a, **k: vix_close.to_frame(name="Close"))
    monkeypatch.setattr(market_regime.fred_data, "is_configured", lambda: False)

    result = market_regime.get_advisory_risk_signals()

    assert result["vix"]["level"] == 18.0
    assert result["credit_spread"] is None
    assert result["yield_curve_3m"] is None


def test_get_advisory_risk_signals_with_fred_key_computes_all_three(monkeypatch):
    vix_close = pd.Series([18.0], index=pd.date_range("2026-06-01", periods=1))
    monkeypatch.setattr(market_regime, "get_price_history", lambda *a, **k: vix_close.to_frame(name="Close"))
    monkeypatch.setattr(market_regime.fred_data, "is_configured", lambda: True)

    def _fake_get_series(series_id, **kwargs):
        if series_id == "BAMLH0A0HYM2":
            return pd.Series([4.5])
        if series_id == "T10Y3M":
            return pd.Series([0.8])
        return pd.Series(dtype=float)

    monkeypatch.setattr(market_regime.fred_data, "get_series", _fake_get_series)

    result = market_regime.get_advisory_risk_signals()

    assert result["vix"]["level"] == 18.0
    assert result["credit_spread"]["level_bp"] == pytest.approx(450.0)
    assert result["yield_curve_3m"]["spread_pct"] == pytest.approx(0.8)


# ----------------------------------------------------------------------------
# select_regime_for_trading (SPEC 13.9절 — 라이브 국면 판단 확정, 2026-07-17)
# ----------------------------------------------------------------------------


def _snapshot(regime: str, total_score: float) -> dict:
    return {"regime": regime, "total_score": total_score}


def test_select_regime_for_trading_unambiguous_bull():
    result = market_regime.select_regime_for_trading(_snapshot("강세장", 60.0))
    assert result == {"trading_regime": "강세장", "is_ambiguous": False, "total_score": 60.0, "snapshot": _snapshot("강세장", 60.0)}


def test_select_regime_for_trading_unambiguous_bear():
    result = market_regime.select_regime_for_trading(_snapshot("약세장", -60.0))
    assert result["trading_regime"] == "약세장"
    assert result["is_ambiguous"] is False


def test_select_regime_for_trading_neutral_leans_bull_on_nonnegative_score():
    result = market_regime.select_regime_for_trading(_snapshot("중립/혼조", 5.0))
    assert result["trading_regime"] == "강세장"
    assert result["is_ambiguous"] is True


def test_select_regime_for_trading_neutral_leans_bear_on_negative_score():
    result = market_regime.select_regime_for_trading(_snapshot("중립/혼조", -5.0))
    assert result["trading_regime"] == "약세장"
    assert result["is_ambiguous"] is True


def test_select_regime_for_trading_no_snapshot_available(monkeypatch):
    monkeypatch.setattr(market_regime, "get_latest_market_regime_snapshot", lambda: None)
    result = market_regime.select_regime_for_trading()
    assert result["trading_regime"] is None
    assert result["is_ambiguous"] is True
    assert "reason" in result


def test_select_regime_for_trading_uses_latest_snapshot_when_not_given(monkeypatch):
    monkeypatch.setattr(
        market_regime, "get_latest_market_regime_snapshot", lambda: _snapshot("강세장", 50.0)
    )
    result = market_regime.select_regime_for_trading()
    assert result["trading_regime"] == "강세장"
