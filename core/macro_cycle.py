"""모듈 G: 경기 사이클 국면 판단 + 섹터 로테이션.

실질 GDP 증가율(YoY)과 실업률 추세로 4국면(회복/확장/둔화/수축) 경기 사이클을 간이 추정하고,
국면별로 역사적으로 아웃퍼폼하는 섹터를 보여준다(널리 알려진 정적 프레임워크 - 특정 데이터
제공자의 실시간 판단이 아니라 참고용 경험칙임을 UI에 명시한다).
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

PHASES = ["회복", "확장", "둔화", "수축"]

# 국면별 아웃퍼폼 섹터 (전형적인 경기 사이클 섹터 로테이션 이론 기준)
SECTOR_ROTATION: dict[str, list[str]] = {
    "회복": ["금융", "산업재", "임의소비재", "부동산"],
    "확장": ["기술", "임의소비재", "산업재", "소재"],
    "둔화": ["에너지", "소재", "필수소비재"],
    "수축": ["유틸리티", "헬스케어", "필수소비재"],
}

PHASE_DESCRIPTIONS: dict[str, str] = {
    "회복": "경기 저점을 지나 성장률이 반등하기 시작하는 국면. 실업률은 아직 높지만 개선 조짐을 보입니다.",
    "확장": "성장률과 고용이 함께 개선되는 국면. 경기 사이클의 중심부입니다.",
    "둔화": "성장률은 여전히 플러스지만 둔화되기 시작하는 국면(과열/피크 이후).",
    "수축": "성장률이 마이너스로 전환되고 실업률이 상승하는 침체 국면입니다.",
}


def yoy_growth(series: pd.Series, periods: int = 4) -> pd.Series:
    """전년동기 대비(YoY) 증가율(%)을 계산한다.

    Args:
        series: 시계열 (예: 분기 GDP -> periods=4, 월별 지표 -> periods=12)
        periods: 1년 전 시점과의 차이를 구하기 위한 관측치 개수
    """
    s = series.dropna()
    return (s / s.shift(periods) - 1) * 100


def _trend(series: pd.Series, window: int = 3) -> Optional[str]:
    """최근 window개 관측치의 방향(up/down/flat)을 반환한다. 데이터가 부족하면 None."""
    s = series.dropna()
    if len(s) < window + 1:
        return None
    diffs = s.iloc[-window:].diff().dropna()
    if diffs.empty:
        return None
    avg_diff = diffs.mean()
    if avg_diff > 0:
        return "up"
    if avg_diff < 0:
        return "down"
    return "flat"


def determine_cycle_phase(gdp_growth: pd.Series, unemployment: pd.Series) -> dict:
    """실질 GDP 증가율(YoY %)과 실업률 시계열로 경기 사이클 국면을 추정한다.

    간이 규칙(4국면 프레임워크):
        확장: 성장률 > 0 이고 실업률이 상승하지 않음(하락/횡보)
        둔화: 성장률 > 0 이지만 실업률이 상승 전환 (피크 이후)
        수축: 성장률 <= 0 이고 실업률이 상승세
        회복: 성장률 <= 0 이지만 실업률이 하락/횡보 (저점 통과 조짐)

    데이터가 부족하면 phase=None 을 반환한다.

    Returns:
        {"phase": str|None, "description": str, "sectors": list[str]}
    """
    gdp_s = gdp_growth.dropna()
    unemp_trend = _trend(unemployment)

    if gdp_s.empty or unemp_trend is None:
        return {"phase": None, "description": "판단에 필요한 데이터가 부족합니다.", "sectors": []}

    growth_positive = gdp_s.iloc[-1] > 0

    if growth_positive and unemp_trend != "up":
        phase = "확장"
    elif growth_positive and unemp_trend == "up":
        phase = "둔화"
    elif not growth_positive and unemp_trend == "up":
        phase = "수축"
    else:
        phase = "회복"

    return {
        "phase": phase,
        "description": PHASE_DESCRIPTIONS[phase],
        "sectors": SECTOR_ROTATION[phase],
    }


def get_sector_rotation_table() -> dict[str, dict]:
    """모든 국면에 대한 섹터 로테이션 참고표를 반환한다 (대시보드에 통째로 보여줄 때 사용)."""
    return {phase: {"sectors": SECTOR_ROTATION[phase], "description": PHASE_DESCRIPTIONS[phase]} for phase in PHASES}
