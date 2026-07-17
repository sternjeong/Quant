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

# 자산군 성향 참고 노트(2026-07-16 딥서치 기반 추가). Merrill Lynch Investment Clock(성장갭×인플레이션
# 2축, reflation/recovery/overheat/stagflation 4국면)이 가장 널리 인용되는 자산배분 프레임워크지만,
# 이 모듈의 4국면(회복/확장/둔화/수축)은 GDP 추세×모멘텀만 쓰고 인플레이션 축이 없어 축 자체가
# 달라 ML 모델과 1:1로 대응시키지 않는다. 대신 여러 경기순환 투자 자료에서 공통적으로 언급되는
# "국면별 자산군 성향"을 일반화해 참고용으로만 제공한다 — 특정 모델의 확정 규칙이 아님을 UI에도
# 명시.
ASSET_CLASS_NOTES: dict[str, str] = {
    "회복": "주식이 채권 대비 상대적으로 강세를 보이기 시작하는 경향이 있습니다(경기민감주 중심).",
    "확장": "주식이 가장 강한 성과를 내는 경향이 있는 국면입니다. 후반부로 갈수록 원자재도 강세를 보일 수 있습니다.",
    "둔화": "원자재/인플레이션 헤지 자산이 상대적으로 선호되고, 채권 금리는 상승 압력을 받는 경향이 있습니다.",
    "수축": "현금/채권 등 방어적 자산이 상대적으로 선호되는 경향이 있습니다.",
}

# ----------------------------------------------------------------------------
# 보조 확인 신호 1: 장단기 금리차(10Y-2Y, FRED T10Y2Y) — 역전(음수)은 역사적으로 매우 신뢰도 높은
# 침체 "선행" 지표다(뉴욕 연준 리서치 기준 1955년 이후 모든 미국 침체에 앞서 역전 발생, 평균 약
# 15개월·범위 6~24개월 선행). GDP/실업률 기반 판정과 달리 침체가 "언제 올지"가 아니라 "올 가능성이
# 커졌는지"를 알려주는 선행 신호라 현재 국면 판정에 직접 섞지 않고 별도 경고로만 노출한다.
# ----------------------------------------------------------------------------


def interpret_yield_curve(spread: Optional[float]) -> Optional[dict]:
    """10년-2년 국채금리차(%p)로 수익률곡선 역전 여부를 판정한다.

    Returns: {"inverted": bool, "spread": float, "note": str}. spread가 None이면 None.
    """
    if spread is None:
        return None
    inverted = spread < 0
    note = (
        "장단기 금리차가 역전(음수)돼 있습니다. 1955년 이후 모든 미국 침체에 앞서 이 역전이 나타났고, "
        "평균 약 15개월(6~24개월 범위) 뒤 침체로 이어진 경우가 많았습니다 — 다만 최근에는 역전 후 "
        "예상보다 오래 침체가 안 오거나 지연되는 경우도 있어 절대적 시점 예측 지표는 아닙니다."
        if inverted
        else "장단기 금리차가 정상(양수) 범위입니다. 역전 상태가 아니라는 것은 이 지표 기준으로는 "
        "가까운 시일 내 침체 경고 신호가 없다는 뜻입니다."
    )
    return {"inverted": inverted, "spread": spread, "note": note}


# ----------------------------------------------------------------------------
# 보조 확인 신호 2: 시카고 연은 전국활동지수(CFNAI, FRED "CFNAI") — 85개 월별 지표를 가중평균한
# 종합 경기활동 지수(0=추세 성장률, 표준편차 1로 정규화). 노이즈가 커서 원계열 대신 3개월 이동평균
# (CFNAI-MA3)을 쓰는 게 시카고 연은의 공식 해석 방식이다. 임계값도 시카고 연은이 직접 제시한 값을
# 그대로 사용:
#   - CFNAI-MA3 < -0.70: 확장 국면 이후라면 침체 가능성 고조
#   - CFNAI-MA3 > -0.70 (수축 이후): 회복 가능성 고조, > +0.20: 뚜렷한 확장 가능성
#   - CFNAI-MA3 > +0.70 (확장 2년 이상 지속 시): 인플레이션 압력 고조 — 이 조건(확장 지속기간)까지는
#     이 함수가 추적하지 않아 +0.70 초과를 그냥 "과열/인플레이션 압력 우려"로만 단순화해 표시한다.
# ----------------------------------------------------------------------------

CFNAI_RECESSION_RISK_THRESHOLD = -0.70
CFNAI_EXPANSION_LIKELY_THRESHOLD = 0.20
CFNAI_OVERHEATING_THRESHOLD = 0.70


def classify_cfnai(cfnai_ma3: Optional[float]) -> Optional[dict]:
    """CFNAI-MA3(3개월 이동평균) 값으로 시카고 연은이 제시한 경기 신호를 판정한다.

    Returns: {"value": float, "signal": str, "note": str}. cfnai_ma3가 None이면 None.
    """
    if cfnai_ma3 is None:
        return None
    if cfnai_ma3 < CFNAI_RECESSION_RISK_THRESHOLD:
        signal, note = "침체 위험 고조", "CFNAI-MA3가 -0.70 미만입니다. 확장기 이후라면 침체 가능성이 높아진 구간입니다."
    elif cfnai_ma3 > CFNAI_OVERHEATING_THRESHOLD:
        signal, note = "과열/인플레 압력", "CFNAI-MA3가 +0.70을 초과했습니다. 장기간 확장 중이라면 인플레이션 압력이 커질 수 있는 구간입니다."
    elif cfnai_ma3 > CFNAI_EXPANSION_LIKELY_THRESHOLD:
        signal, note = "확장 가능성 높음", "CFNAI-MA3가 +0.20을 초과했습니다. 추세 이상의 확장이 진행 중일 가능성이 높습니다."
    else:
        signal, note = "중립", "CFNAI-MA3가 중립 범위(-0.70~+0.20)입니다. 경기가 추세 성장률 안팎에서 움직이고 있습니다."
    return {"value": cfnai_ma3, "signal": signal, "note": note}


# ----------------------------------------------------------------------------
# 역사적 국면 타임라인(최근 N분기) — "지금 국면"만 보여주면 판정 근거를 신뢰하기 어렵다는 문제를
# 보완하기 위해, 과거 각 분기에 같은 로직(_gdp_trend_quadrant)을 적용했다면 어떤 국면으로 잡혔을지
# 표로 보여준다. 미래 데이터를 안 쓰므로(각 분기 시점까지의 데이터만 사용) look-ahead bias 없음.
# ----------------------------------------------------------------------------


def compute_historical_quadrants(gdp_growth: pd.Series, lookback_quarters: int = 12) -> pd.DataFrame:
    """최근 lookback_quarters개 분기 각각에 대해, 그 시점까지의 데이터만으로 GDP 사분면을 재계산한다.

    Returns:
        columns: quarter(Timestamp), level, trend, momentum, phase
        데이터가 부족한 분기는 결과에서 제외한다(빈 DataFrame 가능).
    """
    s = gdp_growth.dropna()
    if s.empty:
        return pd.DataFrame(columns=["quarter", "level", "trend", "momentum", "phase"])

    rows = []
    n = len(s)
    start_idx = max(GDP_TREND_WINDOW_QUARTERS, n - lookback_quarters)
    for i in range(start_idx, n):
        window = s.iloc[: i + 1]
        quadrant = _gdp_trend_quadrant(window)
        if quadrant is None:
            continue
        rows.append(
            {
                "quarter": s.index[i],
                "level": quadrant["level"],
                "trend": quadrant["trend"],
                "momentum": quadrant["momentum"],
                "phase": quadrant["phase"],
            }
        )
    return pd.DataFrame(rows)


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


GDP_TREND_WINDOW_QUARTERS = 8  # 추세(잠재)성장률로 볼 이동평균 구간 (2년치 분기 데이터)
GDP_MOMENTUM_WINDOW_QUARTERS = 2  # 가속/감속 판정에 쓰는 최근 구간
SAHM_RULE_THRESHOLD_PP = 0.5  # Sahm Rule: 실업률 3개월 평균이 최근 12개월 저점 대비 이 이상 오르면 침체 신호
SAHM_LOOKBACK_MONTHS = 12


def _gdp_trend_quadrant(gdp_growth: pd.Series) -> Optional[dict]:
    """GDP YoY 증가율을 "추세 대비 레벨" × "모멘텀(가속/감속)" 두 축으로 사분면화한다.

    Eurostat Business Cycle Clock / 업계 투자시계(Fidelity, BCA Research 등)에서 쓰는 방식과 동일한
    골자: 실업률(후행지표) 대신 GDP 증가율 시계열 하나로 레벨과 모멘텀을 함께 본다.
        - 레벨: 최근 증가율이 자체 추세(GDP_TREND_WINDOW_QUARTERS 이동평균, "잠재성장률" 근사)보다
          높은지(above_trend)
        - 모멘텀: 최근 GDP_MOMENTUM_WINDOW_QUARTERS 구간의 방향(up=가속/down=감속/flat)

    Returns: {"phase": str, "above_trend": bool, "level": float, "trend": float, "momentum": str}
        데이터 부족(추세 계산에 필요한 최소 관측치 미달)이면 None.
    """
    s = gdp_growth.dropna()
    if len(s) < GDP_TREND_WINDOW_QUARTERS:
        return None
    momentum = _trend(s, window=GDP_MOMENTUM_WINDOW_QUARTERS)
    if momentum is None:
        return None

    trend = float(s.iloc[-GDP_TREND_WINDOW_QUARTERS:].mean())
    level = float(s.iloc[-1])
    above_trend = level > trend
    accelerating = momentum == "up"

    if above_trend and accelerating:
        phase = "확장"
    elif above_trend and not accelerating:
        phase = "둔화"
    elif not above_trend and accelerating:
        phase = "회복"
    else:
        phase = "수축"

    return {"phase": phase, "above_trend": above_trend, "level": level, "trend": trend, "momentum": momentum}


def check_sahm_rule(unemployment: pd.Series) -> Optional[dict]:
    """Sahm Rule로 실시간 침체 신호를 판정한다 (Claudia Sahm, 연준 이코노미스트 고안).

    실업률 3개월 이동평균이 최근 SAHM_LOOKBACK_MONTHS(12개월) 저점 대비
    SAHM_RULE_THRESHOLD_PP(0.5%p) 이상 올랐으면 트리거된다. 월별 데이터라 GDP(분기, 공표 지연)보다
    최신성이 높아 국면 판정의 침체 확인용 보조 신호로 쓴다 — 이 값 자체로 국면을 정하지 않고, 트리거
    시에만 "수축"으로 덮어쓴다(과거 모든 미국 침체를 실시간에 가깝게 정확히 잡아낸 것으로 검증된 지표).

    Returns: {"triggered": bool, "current_3mo_avg": float, "recent_low": float, "delta_pp": float}
        데이터가 부족하면 None.
    """
    s = unemployment.dropna()
    if len(s) < 3:
        return None
    three_mo_avg = s.rolling(3).mean().dropna()
    if three_mo_avg.empty:
        return None
    current = float(three_mo_avg.iloc[-1])
    window = three_mo_avg.iloc[-SAHM_LOOKBACK_MONTHS:] if len(three_mo_avg) > SAHM_LOOKBACK_MONTHS else three_mo_avg
    recent_low = float(window.min())
    delta = current - recent_low
    return {
        "triggered": delta >= SAHM_RULE_THRESHOLD_PP,
        "current_3mo_avg": current,
        "recent_low": recent_low,
        "delta_pp": delta,
    }


def determine_cycle_phase(gdp_growth: pd.Series, unemployment: pd.Series) -> dict:
    """실질 GDP 증가율(YoY %) 시계열의 "추세 대비 레벨×모멘텀" 사분면으로 경기 사이클 국면을 추정하고,
    실업률 기반 Sahm Rule을 침체 확인용 오버레이로 적용한다.

    방법론(2026-07-16 딥서치 기반 개선 — 기존에는 GDP 증가율 부호 + 실업률 추세 두 축을 썼으나,
    실업률은 후행지표라 피크 이후 국면 전환(둔화)을 늦게 잡는 문제가 있었다):
        1. 주축: GDP 증가율이 자체 추세(2년 이동평균)보다 높은지(above_trend) × 가속/감속(momentum)
           → 4사분면 (확장/둔화/회복/수축), 실업률에 의존하지 않음 (_gdp_trend_quadrant 참고)
        2. 오버레이: Sahm Rule이 트리거되면(실업률 3개월 평균이 12개월 저점 대비 +0.5%p 이상) 사분면
           결과와 무관하게 "수축"으로 덮어쓴다 — 월별 실업률이 분기·공표지연 있는 GDP보다 최신이라
           국면 전환을 더 빨리 확인해주는 용도.

    데이터가 부족하면 phase=None 을 반환한다.

    Returns:
        {"phase": str|None, "description": str, "sectors": list[str], "quadrant": dict|None,
         "sahm_rule": dict|None, "sahm_override": bool}
    """
    quadrant = _gdp_trend_quadrant(gdp_growth)
    sahm = check_sahm_rule(unemployment)

    if quadrant is None:
        return {
            "phase": None,
            "description": "판단에 필요한 데이터가 부족합니다.",
            "sectors": [],
            "quadrant": None,
            "sahm_rule": sahm,
            "sahm_override": False,
        }

    phase = quadrant["phase"]
    sahm_override = bool(sahm and sahm["triggered"] and phase != "수축")
    if sahm_override:
        phase = "수축"

    return {
        "phase": phase,
        "description": PHASE_DESCRIPTIONS[phase],
        "sectors": SECTOR_ROTATION[phase],
        "quadrant": quadrant,
        "sahm_rule": sahm,
        "sahm_override": sahm_override,
    }


def get_sector_rotation_table() -> dict[str, dict]:
    """모든 국면에 대한 섹터 로테이션 참고표를 반환한다 (대시보드에 통째로 보여줄 때 사용)."""
    return {phase: {"sectors": SECTOR_ROTATION[phase], "description": PHASE_DESCRIPTIONS[phase]} for phase in PHASES}
