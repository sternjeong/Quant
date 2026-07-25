"""core/kostolany_scenario_engine.py 단위 테스트.

핵심 검증 포인트:
1) classify_cycle_phase_series(벡터화·rolling)가 core.kostolany_cycle.classify_cycle_phase(단일
   시점) 스냅샷 로직과 매 시점 동일한 국면을 내는지(파라미터화 대조 테스트).
2) build_position_from_phases가 STYLE_PHASE_STATUS의 buy/hold/sell 매핑을 정확히 0/1로 변환하는지.
3) run_kostolany_scenario가 국면 신호에 따라 실제로 시장에 들어갔다 나왔다 하며, 계속 매수 국면인
   합성 데이터에서는 매수 후 보유와 동일한 결과를 내는지(가장 단순한 회귀 케이스).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import core.backtest_engine as backtest_engine
import core.kostolany_cycle as kostolany_cycle
import core.kostolany_scenario_engine as engine


def _price_volume(n: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    # 추세 + 노이즈가 섞인 합성 가격 (양수 유지)
    trend = np.linspace(50, 150, n)
    noise = rng.normal(0, 3, n).cumsum() * 0.1
    close = pd.Series(np.clip(trend + noise, 5, None), index=idx, name="Close")
    volume = pd.Series(rng.integers(800_000, 1_200_000, n).astype(float), index=idx, name="Volume")
    return close, volume


@pytest.fixture(autouse=True)
def _fake_benchmark_price_history(monkeypatch):
    """run_kostolany_scenario는 매번 S&P500 매수보유 벤치마크도 함께 계산한다(2026-07-21 추가) —
    유닛테스트가 실제 yfinance 네트워크를 타지 않도록 core.backtest_engine.get_price_history를
    합성 데이터로 대체한다 (core.backtest_engine.run_buy_and_hold이 내부에서 이 함수를 쓴다)."""

    def fake_get_price_history(ticker, start=None, end=None, use_cache=True, interval="1d"):
        idx = pd.date_range("2019-01-01", periods=800, freq="B")
        close = pd.Series(np.linspace(3000, 4500, 800), index=idx, name="Close")
        df = pd.DataFrame({"Close": close})
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            df = df[df.index <= pd.Timestamp(end)]
        return df

    monkeypatch.setattr(backtest_engine, "get_price_history", fake_get_price_history)


class TestClassifyCyclePhaseSeriesParity:
    @pytest.mark.parametrize("seed", [0, 1, 2])
    def test_matches_snapshot_classifier_at_every_valid_point(self, seed):
        close, volume = _price_volume(500, seed=seed)
        phase_series = engine.classify_cycle_phase_series(close, volume)

        # 넉넉히 뒤쪽 100개 지점만 표본 검사 (앞쪽은 rolling warmup으로 값이 None일 수 있음).
        for i in range(len(close) - 100, len(close)):
            snapshot = kostolany_cycle.classify_cycle_phase(close.iloc[: i + 1], volume.iloc[: i + 1])
            expected = snapshot["phase"] if snapshot is not None else None
            actual = phase_series.iloc[i]
            actual = None if (actual is None or (isinstance(actual, float) and np.isnan(actual))) else actual
            assert actual == expected, f"seed={seed} i={i}: expected {expected}, got {actual}"


class TestBuildPositionFromPhases:
    def test_buy_and_hold_phases_map_to_position_one(self):
        idx = pd.date_range("2024-01-01", periods=6, freq="B")
        # 장기: A1=buy(1), A2=hold(직전유지=1), A3=sell(0), B1=sell(0), B2=hold(직전유지=0), B3=buy(1)
        phase = pd.Series(["A1", "A2", "A3", "B1", "B2", "B3"], index=idx)
        position = engine.build_position_from_phases(phase, style="장기")
        assert list(position) == [1.0, 1.0, 0.0, 0.0, 0.0, 1.0]

    def test_swing_style_differs_on_a1_a2(self):
        # 스윙: A1=hold(직전유지, 시작이라 0), A2=buy(1) -> 장기(A1=buy=1, A2=hold=직전유지=1)와 달라야 함
        idx = pd.date_range("2024-01-01", periods=2, freq="B")
        phase = pd.Series(["A1", "A2"], index=idx)
        long_term = engine.build_position_from_phases(phase, style="장기")
        swing = engine.build_position_from_phases(phase, style="스윙")
        assert list(long_term) == [1.0, 1.0]
        assert list(swing) == [0.0, 1.0]

    def test_none_phase_treated_as_hold_carry_forward(self):
        idx = pd.date_range("2024-01-01", periods=3, freq="B")
        phase = pd.Series([None, "A1", None], index=idx)
        position = engine.build_position_from_phases(phase, style="장기")
        assert list(position) == [0.0, 1.0, 1.0]


class TestRunKostolanyScenario:
    def test_empty_df_returns_empty_run(self):
        run = engine.run_kostolany_scenario(pd.DataFrame(), label="테스트")
        assert run.df.empty
        assert run.metrics["trade_count"] == 0

    def test_low_zone_dip_then_rally_triggers_buy_and_stays_invested(self):
        # 저점권(52주 최저 근처)까지 눌린 뒤 다시 오르는 구간: 저점권 진입 시 A1(buy) 신호가 떠야
        # 하고, 그 뒤로는 hold(직전 상태 유지)로 계속 시장에 남아 있어야 한다.
        idx = pd.date_range("2020-01-01", periods=400, freq="B")
        decline = np.linspace(150, 100, 260)
        rally = np.linspace(100, 150, 140)
        close = pd.Series(np.concatenate([decline, rally]), index=idx, name="Close")
        volume = pd.Series([1_000_000.0] * 400, index=idx, name="Volume")
        df = pd.DataFrame({"Close": close, "Volume": volume})

        run = engine.run_kostolany_scenario(df, label="합성", style="장기", start="2021-01-15")
        assert not run.df.empty
        assert (run.position == 1.0).mean() > 0.7
        assert run.metrics["trade_count"] >= 1

    def test_sell_phase_exits_market(self):
        # 고점권에서 거래량 급증 + 상승 -> A3(과열/매도검토) -> 포지션 0이 존재해야 한다.
        idx = pd.date_range("2020-01-01", periods=320, freq="B")
        base = np.concatenate([np.linspace(100, 100, 300), np.linspace(100, 200, 20)])
        close = pd.Series(base, index=idx, name="Close")
        volume = pd.Series([1_000_000.0] * 300 + [5_000_000.0] * 20, index=idx, name="Volume")
        df = pd.DataFrame({"Close": close, "Volume": volume})

        run = engine.run_kostolany_scenario(df, label="합성", style="장기", start="2021-01-01")
        assert (run.position == 0.0).any()

    def test_benchmark_fields_are_populated(self):
        close, volume = _price_volume(400, seed=1)
        df = pd.DataFrame({"Close": close, "Volume": volume})
        run = engine.run_kostolany_scenario(df, label="합성", style="장기", start="2021-01-01")

        assert not run.benchmark_equity_curve.empty
        assert run.benchmark_metrics["trade_count"] == 1  # 매수 후 보유는 항상 매매 1건
        assert run.benchmark_ticker == "^GSPC"


class TestWarmupBeforeAnalysisStart:
    """run_ticker_scenario/run_theme_scenario가 국면 판정용 warmup을 분석 시작일(start) 이전에
    실제로 더 받아오는지 검증한다 (2026-07-25 발견 및 수정 — 이 warmup 없이 start부터 바로 받아오면
    분석 구간 맨 앞부분의 rolling 윈도가 아직 안 채워져 국면 판정이 왜곡됐었다)."""

    def test_run_ticker_scenario_fetches_warmup_before_start(self, monkeypatch):
        captured = {}

        def fake_get_price_history(ticker, start=None, end=None, interval="1d"):
            captured["start"] = start
            close, volume = _price_volume(50)
            return pd.DataFrame({"Close": close, "Volume": volume})

        monkeypatch.setattr(engine, "get_price_history", fake_get_price_history)
        engine.run_ticker_scenario("AAPL", style="장기", start="2023-06-01")

        expected_fetch_start = (
            pd.Timestamp("2023-06-01") - pd.DateOffset(days=engine.WARMUP_DAYS)
        ).date().isoformat()
        assert captured["start"] == expected_fetch_start

    def test_run_theme_scenario_fetches_warmup_before_start(self, monkeypatch):
        captured = {}

        def fake_combined(proxies, start=None, end=None):
            captured["start"] = start
            return _price_volume(50)

        monkeypatch.setattr(engine, "_combined_close_volume", fake_combined)
        engine.run_theme_scenario("테스트", ["XLK"], style="장기", start="2023-06-01")

        expected_fetch_start = (
            pd.Timestamp("2023-06-01") - pd.DateOffset(days=engine.WARMUP_DAYS)
        ).date().isoformat()
        assert captured["start"] == expected_fetch_start

    def test_run_ticker_scenario_analysis_window_still_starts_at_requested_start(self, monkeypatch):
        """warmup을 더 받아오더라도 실제 표시되는 분석 구간(run.df)은 요청한 start부터여야 한다."""

        def fake_get_price_history(ticker, start=None, end=None, interval="1d"):
            close, volume = _price_volume(500)
            return pd.DataFrame({"Close": close, "Volume": volume})

        monkeypatch.setattr(engine, "get_price_history", fake_get_price_history)
        run = engine.run_ticker_scenario("AAPL", style="장기", start="2021-06-15")
        assert run.df.index[0] >= pd.Timestamp("2021-06-15")


class TestRunThemeScenarios:
    def test_uses_theme_universe_and_returns_sorted_by_excess_return(self, monkeypatch):
        close, volume = _price_volume(400, seed=42)

        def fake_combined(proxies, start=None, end=None):
            return close, volume

        monkeypatch.setattr(engine, "_combined_close_volume", fake_combined)
        small_universe = {"테마A": ["AAA"], "테마B": ["BBB"]}
        df = engine.run_theme_scenarios(style="장기", theme_universe=small_universe, start="2021-01-01")

        assert set(df["theme"]) == {"테마A", "테마B"}
        assert list(df["excess_return"]) == sorted(df["excess_return"], reverse=True)
        assert {"bench_cumulative_return", "bench_cagr", "bench_mdd", "excess_return_vs_benchmark"}.issubset(df.columns)
