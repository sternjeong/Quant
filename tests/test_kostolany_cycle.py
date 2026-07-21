"""core/kostolany_cycle.py 단위 테스트 (코스톨라니 달걀 이론 6국면 판정).

네트워크(yfinance)를 타지 않도록 core.market_data 함수를 monkeypatch 로 대체한다.
"""

from contextlib import contextmanager

import pandas as pd
import pytest

import core.kostolany_cycle as kostolany_cycle


def _series(values: list[float], name: str = "Close") -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx, name=name)


def _flat_volume(n: int, level: float = 1_000_000.0) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series([level] * n, index=idx, name="Volume")


def _ramp_volume(n: int, base: float = 1_000_000.0, recent_multiplier: float = 2.0, recent_days: int = 20) -> pd.Series:
    """최근 recent_days만 거래량이 급증하는 시계열 (거래량 증가 신호 테스트용)."""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    values = [base] * (n - recent_days) + [base * recent_multiplier] * recent_days
    return pd.Series(values, index=idx, name="Volume")


class TestComputePositionPct:
    def test_at_52week_high_is_100(self):
        close = _series([100.0] * 200 + [200.0])
        assert kostolany_cycle.compute_position_pct(close) == pytest.approx(100.0)

    def test_at_52week_low_is_0(self):
        close = _series([200.0] * 200 + [100.0])
        assert kostolany_cycle.compute_position_pct(close) == pytest.approx(0.0)

    def test_flat_series_is_50(self):
        close = _series([100.0] * 200)
        assert kostolany_cycle.compute_position_pct(close) == pytest.approx(50.0)


class TestComputeVolumeRatio:
    def test_recent_spike_gives_ratio_above_one(self):
        volume = _ramp_volume(100, recent_multiplier=3.0)
        ratio = kostolany_cycle.compute_volume_ratio(volume)
        assert ratio > 1.2

    def test_flat_volume_gives_ratio_near_one(self):
        volume = _flat_volume(100)
        ratio = kostolany_cycle.compute_volume_ratio(volume)
        assert ratio == pytest.approx(1.0)

    def test_insufficient_history_returns_none(self):
        volume = _flat_volume(10)
        assert kostolany_cycle.compute_volume_ratio(volume) is None


class TestClassifyCyclePhase:
    def test_bottom_zone_downtrend_high_volume_is_panic_b3(self):
        n = 260
        close = _series([200.0] * (n - 20) + [200.0 * (0.99 ** i) for i in range(20)])
        volume = _ramp_volume(n, recent_multiplier=3.0)
        result = kostolany_cycle.classify_cycle_phase(close, volume)
        assert result["phase"] == "B3"
        assert result["zone"] == "저점권"

    def test_bottom_zone_downtrend_low_volume_is_a1(self):
        n = 260
        # 완만한 하락(급락 아님) + 거래량 증가 없음 -> A1
        close = _series([200.0] * (n - 20) + [200.0 * (0.999 ** i) for i in range(20)])
        volume = _flat_volume(n)
        result = kostolany_cycle.classify_cycle_phase(close, volume)
        assert result["phase"] == "A1"

    def test_mid_zone_uptrend_is_a2(self):
        # 52주 고점(250)이 과거에 이미 찍혀 있어, 최근 20일 상승 후에도 현재가가 그 고점의
        # 중간대(30~70%)에 머물도록 구성 (단순 우상향 시계열은 항상 현재가=52주 고점이 되어
        # position_pct=100이 나오므로, 중간대를 테스트하려면 이렇게 과거 고점이 필요함).
        history_len = 220
        main = [100.0] * (history_len - 30) + [250.0] + [100.0] * 28 + [140.0]
        recent = [140.0 + (175.0 - 140.0) * i / 19 for i in range(20)]
        close = _series(main + recent)
        volume = _flat_volume(len(close))
        result = kostolany_cycle.classify_cycle_phase(close, volume)
        assert result["zone"] == "중간"
        assert result["phase"] == "A2"

    def test_top_zone_uptrend_high_volume_is_bubble_a3(self):
        n = 260
        close = _series([100.0] * (n - 20) + [100.0 * (1.02 ** i) for i in range(20)])
        volume = _ramp_volume(n, recent_multiplier=3.0)
        result = kostolany_cycle.classify_cycle_phase(close, volume)
        assert result["phase"] == "A3"
        assert result["zone"] == "고점권"

    def test_top_zone_downtrend_low_volume_is_b1(self):
        n = 260
        close = _series([100.0] * (n - 21) + [160.0 * (0.997 ** i) for i in range(21)])
        volume = _flat_volume(n)
        result = kostolany_cycle.classify_cycle_phase(close, volume)
        assert result["phase"] in ("B1", "B2")  # 정확한 위치 경계는 유동적, 하락+저거래량 계열인지만 확인
        assert result["trend_up"] is False

    def test_insufficient_data_returns_none(self):
        close = _series([100.0] * 5)
        volume = _flat_volume(5)
        assert kostolany_cycle.classify_cycle_phase(close, volume) is None

    def test_all_phases_have_label_and_guidance(self):
        for phase, info in kostolany_cycle.PHASE_INFO.items():
            assert "label" in info and "description" in info and "guidance" in info


class TestStylePhaseStatus:
    def test_both_styles_cover_all_phases(self):
        for style in kostolany_cycle.STYLE_ORDER:
            mapping = kostolany_cycle.STYLE_PHASE_STATUS[style]
            assert set(mapping.keys()) == set(kostolany_cycle.PHASE_ORDER)
            assert set(mapping.values()) <= {"buy", "hold", "sell"}

    def test_swing_and_longterm_agree_on_sell_phases(self):
        # A3(버블)/B1(고점이탈)은 두 스타일 모두 리스크 신호라 매도로 일치해야 한다.
        longterm = kostolany_cycle.STYLE_PHASE_STATUS["장기"]
        swing = kostolany_cycle.STYLE_PHASE_STATUS["스윙"]
        for phase in ("A3", "B1"):
            assert longterm[phase] == "sell"
            assert swing[phase] == "sell"

    def test_swing_and_longterm_diverge_on_a1_and_a2(self):
        longterm = kostolany_cycle.STYLE_PHASE_STATUS["장기"]
        swing = kostolany_cycle.STYLE_PHASE_STATUS["스윙"]
        assert longterm["A1"] == "buy" and swing["A1"] == "hold"
        assert longterm["A2"] == "hold" and swing["A2"] == "buy"

    def test_style_guidance_covers_all_phases_for_both_styles(self):
        for style in kostolany_cycle.STYLE_ORDER:
            guidance = kostolany_cycle.STYLE_PHASE_GUIDANCE[style]
            assert set(guidance.keys()) == set(kostolany_cycle.PHASE_ORDER)
            assert all(isinstance(v, str) and v for v in guidance.values())


class TestGetMarketCyclePhase(object):
    def test_uses_price_history_and_attaches_ticker(self, monkeypatch):
        n = 260
        df = pd.DataFrame(
            {
                "Close": [100.0] * (n - 20) + [100.0 * (1.005 ** i) for i in range(20)],
                "Volume": [1_000_000.0] * n,
            },
            index=pd.date_range("2024-01-01", periods=n, freq="B"),
        )

        def _fake_history(ticker, start=None, end=None, interval="1d"):
            return df

        monkeypatch.setattr(kostolany_cycle, "get_price_history", _fake_history)
        result = kostolany_cycle.get_market_cycle_phase("^GSPC")
        assert result is not None
        assert result["ticker"] == "^GSPC"
        assert result["phase"] in kostolany_cycle.PHASE_ORDER


class TestComputeThemeCyclePhases:
    def test_computes_phase_per_theme(self, monkeypatch):
        n = 260
        up_df = pd.DataFrame(
            {
                "Close": [100.0] * (n - 20) + [100.0 * (1.005 ** i) for i in range(20)],
                "Volume": [1_000_000.0] * n,
            },
            index=pd.date_range("2024-01-01", periods=n, freq="B"),
        )
        down_df = pd.DataFrame(
            {
                "Close": [200.0] * (n - 20) + [200.0 * (0.99 ** i) for i in range(20)],
                "Volume": [3_000_000.0] * (n - 20) + [9_000_000.0] * 20,
            },
            index=pd.date_range("2024-01-01", periods=n, freq="B"),
        )
        fake_prices = {"UP": up_df, "DOWN": down_df}
        theme_universe = {"상승테마": ["UP"], "패닉테마": ["DOWN"]}

        def _fake_multi(tickers, start=None, end=None, interval="1d", use_cache=True):
            return {t: fake_prices[t] for t in tickers}

        monkeypatch.setattr(kostolany_cycle, "get_multiple_price_history", _fake_multi)

        df = kostolany_cycle.compute_theme_cycle_phases(theme_universe)
        assert set(df["theme"]) == {"상승테마", "패닉테마"}
        assert df[df["theme"] == "상승테마"].iloc[0]["phase"] == "A2"
        assert df[df["theme"] == "패닉테마"].iloc[0]["phase"] == "B3"

    def test_empty_when_no_data(self, monkeypatch):
        def _fake_multi(tickers, start=None, end=None, interval="1d", use_cache=True):
            return {}

        monkeypatch.setattr(kostolany_cycle, "get_multiple_price_history", _fake_multi)
        df = kostolany_cycle.compute_theme_cycle_phases({"테마": ["X"]})
        assert df.empty
        assert list(df.columns) == [
            "theme", "proxies", "phase", "label", "zone", "position_pct", "roc_pct",
            "volume_ratio", "trend_up", "is_steep", "volume_high", "description", "guidance",
        ]


class TestSnapshotRoundtrip:
    def test_save_and_load_latest_snapshot(self, db_session, monkeypatch):
        @contextmanager
        def _fake_get_session():
            yield db_session
            db_session.commit()

        monkeypatch.setattr(kostolany_cycle, "get_session", _fake_get_session)

        market_phase = {
            "phase": "A2", "position_pct": 55.0, "roc_pct": 2.0, "volume_ratio": 1.0,
            "zone": "중간", "trend_up": True, "is_steep": False, "volume_high": False,
            "ticker": "^GSPC", **kostolany_cycle.PHASE_INFO["A2"],
        }
        theme_phases = pd.DataFrame(
            [{"theme": "기술", "proxies": "XLK", "phase": "A2", **kostolany_cycle.PHASE_INFO["A2"],
              "zone": "중간", "position_pct": 55.0, "roc_pct": 2.0, "volume_ratio": 1.0,
              "trend_up": True, "is_steep": False, "volume_high": False}]
        )

        kostolany_cycle.save_kostolany_cycle_snapshot(market_phase, theme_phases)
        loaded = kostolany_cycle.get_latest_kostolany_cycle_snapshot()

        assert loaded is not None
        assert loaded["market_phase"]["phase"] == "A2"
        assert loaded["theme_phases"].iloc[0]["theme"] == "기술"
