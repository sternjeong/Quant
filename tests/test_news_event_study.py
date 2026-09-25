"""core/news_event_study.py — 진입 규칙(PIT)과 표본 기준을 손계산으로 검증."""

import pandas as pd
import pytest

from core import news_event_study as nes


def _px(n=40):
    idx = pd.bdate_range("2026-01-05", periods=n)
    return pd.DataFrame({"Open": [100.0] * n, "Close": [101.0] * n}, index=idx)


def test_entry_before_and_after_open():
    days = _px().index
    # 2026-01-05 월: 14:00Z = 09:00 ET(장 전) → 당일, 15:00Z = 10:00 ET(장중) → 다음 날
    assert nes.entry_index("2026-01-05T14:00:00Z", days) == 0
    assert nes.entry_index("2026-01-05T15:00:00Z", days) == 1
    assert nes.entry_index("2026-01-10T12:00:00Z", days) == 5  # 토요일 → 월요일
    assert nes.entry_index("2030-01-01T00:00:00Z", days) is None


def test_same_day_articles_collapse_and_min_sample():
    px = {"AAPL": _px()}
    arts = [{"published_at": "2026-01-05T14:00:00Z", "symbols": ["AAPL"]},
            {"published_at": "2026-01-05T14:20:00Z", "symbols": ["AAPL"]}]
    r = nes.event_study(arts, px)
    assert r["n_events"] == 1
    assert r["horizons"]["1d"]["event_mean_pct"] is None  # n<30
    assert r["horizons"]["1d"]["baseline_mean_pct"] == pytest.approx(1.0)


def test_excess_computed_when_enough_events():
    px = _px(60)
    px.iloc[:35, px.columns.get_loc("Close")] = 103.0  # 이벤트 날만 +3%
    arts = [{"published_at": f"{d.date()}T13:00:00Z", "symbols": ["X"]} for d in px.index[:35]]
    r = nes.event_study(arts, {"X": px})["horizons"]["1d"]
    assert r["status"] == "ok" and r["n"] == 35
    assert r["event_mean_pct"] == pytest.approx(3.0)
    assert r["baseline_mean_pct"] == pytest.approx((35 * 3 + 25 * 1) / 60, abs=1e-3)
