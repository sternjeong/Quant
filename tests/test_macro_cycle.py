"""core/macro_cycle.py 단위 테스트 (모듈 G: 경기 사이클 국면 판단 + 섹터 로테이션)."""

import pandas as pd
import pytest

import core.macro_cycle as macro_cycle


def test_yoy_growth_basic():
    # 4분기 전 100 -> 지금 110 = +10%
    series = pd.Series([100.0, 101.0, 102.0, 103.0, 110.0])
    growth = macro_cycle.yoy_growth(series, periods=4)
    assert growth.iloc[-1] == pytest.approx(10.0)


def test_trend_detects_up_and_down_and_flat():
    up = pd.Series([1.0, 2.0, 3.0, 4.0])
    down = pd.Series([4.0, 3.0, 2.0, 1.0])
    flat = pd.Series([2.0, 2.0, 2.0, 2.0])

    assert macro_cycle._trend(up) == "up"
    assert macro_cycle._trend(down) == "down"
    assert macro_cycle._trend(flat) == "flat"


def test_trend_returns_none_when_insufficient_data():
    assert macro_cycle._trend(pd.Series([1.0, 2.0])) is None
    assert macro_cycle._trend(pd.Series(dtype=float)) is None


def test_determine_cycle_phase_expansion():
    gdp_growth = pd.Series([1.0, 1.5, 2.0])  # 양(+)
    unemployment = pd.Series([5.0, 4.5, 4.0, 3.8])  # 하락 추세

    result = macro_cycle.determine_cycle_phase(gdp_growth, unemployment)
    assert result["phase"] == "확장"
    assert "기술" in result["sectors"]


def test_determine_cycle_phase_slowdown():
    gdp_growth = pd.Series([1.0, 1.5, 2.0])  # 양(+)
    unemployment = pd.Series([3.5, 3.7, 3.9, 4.2])  # 상승 추세

    result = macro_cycle.determine_cycle_phase(gdp_growth, unemployment)
    assert result["phase"] == "둔화"


def test_determine_cycle_phase_contraction():
    gdp_growth = pd.Series([-1.0, -1.5, -2.0])  # 음(-)
    unemployment = pd.Series([4.0, 4.5, 5.0, 5.5])  # 상승 추세

    result = macro_cycle.determine_cycle_phase(gdp_growth, unemployment)
    assert result["phase"] == "수축"
    assert "유틸리티" in result["sectors"]


def test_determine_cycle_phase_recovery():
    gdp_growth = pd.Series([-2.0, -1.0, -0.5])  # 음(-)이지만
    unemployment = pd.Series([6.0, 5.8, 5.6, 5.4])  # 하락 추세 (저점 통과 조짐)

    result = macro_cycle.determine_cycle_phase(gdp_growth, unemployment)
    assert result["phase"] == "회복"


def test_determine_cycle_phase_none_when_insufficient_data():
    result = macro_cycle.determine_cycle_phase(pd.Series(dtype=float), pd.Series([1.0, 2.0, 3.0, 4.0]))
    assert result["phase"] is None
    assert result["sectors"] == []


def test_get_sector_rotation_table_has_all_phases():
    table = macro_cycle.get_sector_rotation_table()
    assert set(table.keys()) == set(macro_cycle.PHASES)
    for phase, info in table.items():
        assert info["sectors"]
        assert info["description"]
