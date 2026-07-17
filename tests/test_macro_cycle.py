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


def test_gdp_trend_quadrant_expansion_above_trend_and_accelerating():
    # 추세(앞 8개 평균) 약 1.0, 최근 값이 추세보다 높고 가속 중
    gdp_growth = pd.Series([1.0] * 7 + [1.0, 1.5, 2.0])
    quadrant = macro_cycle._gdp_trend_quadrant(gdp_growth)
    assert quadrant["phase"] == "확장"
    assert quadrant["above_trend"] is True
    assert quadrant["momentum"] == "up"


def test_gdp_trend_quadrant_slowdown_above_trend_but_decelerating():
    gdp_growth = pd.Series([1.0] * 7 + [3.0, 2.0, 1.5])
    quadrant = macro_cycle._gdp_trend_quadrant(gdp_growth)
    assert quadrant["phase"] == "둔화"


def test_gdp_trend_quadrant_contraction_below_trend_and_decelerating():
    gdp_growth = pd.Series([1.0] * 7 + [-1.0, -1.5, -2.0])
    quadrant = macro_cycle._gdp_trend_quadrant(gdp_growth)
    assert quadrant["phase"] == "수축"
    assert quadrant["above_trend"] is False


def test_gdp_trend_quadrant_recovery_below_trend_but_accelerating():
    gdp_growth = pd.Series([1.0] * 7 + [-2.0, -1.0, -0.5])
    quadrant = macro_cycle._gdp_trend_quadrant(gdp_growth)
    assert quadrant["phase"] == "회복"


def test_gdp_trend_quadrant_none_when_insufficient_data():
    assert macro_cycle._gdp_trend_quadrant(pd.Series([1.0, 2.0, 3.0])) is None


def test_check_sahm_rule_triggered():
    # 3개월 평균 저점 대비 0.5%p 이상 상승
    unemployment = pd.Series([3.5] * 10 + [4.0, 4.3, 4.6])
    sahm = macro_cycle.check_sahm_rule(unemployment)
    assert sahm["triggered"] is True


def test_check_sahm_rule_not_triggered():
    unemployment = pd.Series([3.5] * 10 + [3.6, 3.5, 3.6])
    sahm = macro_cycle.check_sahm_rule(unemployment)
    assert sahm["triggered"] is False


def test_check_sahm_rule_none_when_insufficient_data():
    assert macro_cycle.check_sahm_rule(pd.Series([1.0, 2.0])) is None


def test_determine_cycle_phase_uses_gdp_quadrant_when_sahm_not_triggered():
    gdp_growth = pd.Series([1.0] * 7 + [1.0, 1.5, 2.0])
    unemployment = pd.Series([3.5] * 10 + [3.6, 3.5, 3.6])

    result = macro_cycle.determine_cycle_phase(gdp_growth, unemployment)
    assert result["phase"] == "확장"
    assert "기술" in result["sectors"]
    assert result["sahm_override"] is False


def test_determine_cycle_phase_sahm_override_forces_contraction():
    # GDP 사분면은 "확장"이지만 Sahm Rule이 트리거되면 "수축"으로 덮어쓴다
    gdp_growth = pd.Series([1.0] * 7 + [1.0, 1.5, 2.0])
    unemployment = pd.Series([3.5] * 10 + [4.0, 4.3, 4.6])

    result = macro_cycle.determine_cycle_phase(gdp_growth, unemployment)
    assert result["phase"] == "수축"
    assert result["sahm_override"] is True
    assert "유틸리티" in result["sectors"]


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


# ----------------------------------------------------------------------------
# interpret_yield_curve
# ----------------------------------------------------------------------------


def test_interpret_yield_curve_inverted():
    result = macro_cycle.interpret_yield_curve(-0.5)
    assert result["inverted"] is True
    assert "역전" in result["note"]


def test_interpret_yield_curve_normal():
    result = macro_cycle.interpret_yield_curve(1.2)
    assert result["inverted"] is False
    assert "정상" in result["note"]


def test_interpret_yield_curve_none_input():
    assert macro_cycle.interpret_yield_curve(None) is None


# ----------------------------------------------------------------------------
# classify_cfnai
# ----------------------------------------------------------------------------


def test_classify_cfnai_recession_risk():
    result = macro_cycle.classify_cfnai(-0.9)
    assert result["signal"] == "침체 위험 고조"


def test_classify_cfnai_overheating():
    result = macro_cycle.classify_cfnai(0.9)
    assert result["signal"] == "과열/인플레 압력"


def test_classify_cfnai_expansion_likely():
    result = macro_cycle.classify_cfnai(0.3)
    assert result["signal"] == "확장 가능성 높음"


def test_classify_cfnai_neutral():
    result = macro_cycle.classify_cfnai(0.0)
    assert result["signal"] == "중립"


def test_classify_cfnai_none_input():
    assert macro_cycle.classify_cfnai(None) is None


def test_classify_cfnai_boundary_values_are_exclusive():
    # 정확히 임계값이면 "초과/미만"이 아니므로 중립대 취급
    assert macro_cycle.classify_cfnai(macro_cycle.CFNAI_RECESSION_RISK_THRESHOLD)["signal"] == "중립"
    assert macro_cycle.classify_cfnai(macro_cycle.CFNAI_OVERHEATING_THRESHOLD)["signal"] != "과열/인플레 압력"


# ----------------------------------------------------------------------------
# compute_historical_quadrants
# ----------------------------------------------------------------------------


def test_compute_historical_quadrants_returns_recent_quarters():
    idx = pd.date_range("2015-01-01", periods=30, freq="QE")
    gdp_growth = pd.Series([1.0] * 20 + list(range(1, 11)), index=idx, dtype=float)
    df = macro_cycle.compute_historical_quadrants(gdp_growth, lookback_quarters=5)
    assert not df.empty
    assert list(df.columns) == ["quarter", "level", "trend", "momentum", "phase"]
    assert all(p in macro_cycle.PHASES for p in df["phase"])
    # look-ahead 없음: 각 행의 level은 그 시점 데이터의 마지막 값과 일치해야 함
    for _, row in df.iterrows():
        assert row["level"] == gdp_growth.loc[:row["quarter"]].iloc[-1]


def test_compute_historical_quadrants_empty_series():
    df = macro_cycle.compute_historical_quadrants(pd.Series(dtype=float))
    assert df.empty


def test_compute_historical_quadrants_insufficient_data():
    df = macro_cycle.compute_historical_quadrants(pd.Series([1.0, 2.0, 3.0]))
    assert df.empty
