"""지표 조합 전략 평가 엔진 (모듈 A 백테스팅 엔진 핵심).

전략은 core/models.py::Strategy.indicator_config 에 아래 형태의 JSON으로 저장된다.

    {
        "logic": "AND",              # "AND" 또는 "OR" — 여러 조건 결합 방식
        "conditions": [
            {"indicator": "ma_cross", "short": 20, "long": 60, "type": "golden"},
            {"indicator": "rsi", "period": 14, "op": "<", "value": 30},
            {"indicator": "bollinger", "period": 20, "std_dev": 2.0,
             "band": "lower", "op": "break_below"}
        ]
    }

지원 지표(TradingView 스타일 on/off 토글에 대응):
    - ma_cross: 이동평균 교차. type="golden" 이면 단기>장기(상승 국면) 구간에서 True,
      type="dead" 이면 단기<장기(하락 국면) 구간에서 True.
    - rsi: RSI 과매수/과매도. op in {"<", "<=", ">", ">="}, value 와 비교.
    - bollinger: 볼린저밴드 이탈. band="upper"+op="break_above" 이면 종가가 상단 이탈,
      band="lower"+op="break_below" 이면 종가가 하단 이탈인 구간에서 True.
    - engulfing: 상승/하락 인걸(장악형) 캔들 패턴 이벤트. direction="bullish"|"bearish".
    - marubozu/pin_bar/doji/inside_bar/inside_bar_breakout/piercing_dark_cloud/star_pattern/
      three_soldiers_crows/three_methods: 캔들스틱 패턴 이벤트(마루보즈/핀바/도지/인사이드바(돌파)/
      관통형/모닝·이브닝스타/적삼병·흑삼병/삼법형). direction="bullish"|"bearish"
      (도지는 doji_type으로 4종 세분화).
    - level_break: 직전 N봉 지지선/저항선 돌파 이벤트. source="highest_high"|"lowest_low".
    - ma_touch: 단일 이동평균선 상향/하향 돌파(터치) 이벤트. ma_cross의 단일선 버전.

세 번째 스키마로 "직접 수식(expression)" 전략도 지원한다 (core/expression_engine.py):
    {"expression": "close > sma(close, 20) and rsi(close, 14) < 30"}
지표 토글로 표현하기 어려운 조건을 사용자가 파이썬과 비슷한 문법으로 직접 입력할 수 있다.
자세한 문법/함수 목록은 core/expression_engine.py 를 참고.

네 번째 스키마로 기존에 저장된 전략 두 개(이상)를 합쳐 만드는 "복합(전략 합성)" 전략도 지원한다:
    {"combine": "AND", "strategies": [<하위 전략 A의 indicator_config>, <하위 전략 B의 indicator_config>]}
하위 전략은 레짐/직접 수식/1:2:6 단계별/복합 중 어떤 스키마든 재귀적으로 담을 수 있다 — 각 하위 전략을
"포지션 보유 중" 불리언 시그널로 변환한 뒤(1:2:6 단계별은 비중>0을 보유로 간주) "combine"에 따라
AND(둘 다 보유 신호일 때만 보유)/OR(하나라도 보유 신호면 보유)로 결합한다. evaluate_boolean_signal()이
이 스키마를 포함해 4종 전부를 평가하는 공용 진입점이다.

여러 조건은 "logic" 에 따라 AND(전부 True)/OR(하나라도 True)로 결합되어 하루 단위의
불리언 "포지션 보유 조건" 시리즈가 된다. 이 시리즈가 True인 구간을 매수 보유,
False인 구간을 미보유로 간주하는 "레짐 추종형" 포지션 모델을 사용한다
(예: 골든크로스 구간 내내 보유하다가 데드크로스가 나면 청산).

새 지표를 추가하려면 core/indicators.py 에 계산 함수를 만들고,
아래 INDICATOR_EVALUATORS 에 "indicator" 이름 -> 평가 함수를 등록하면 된다
(엔진의 나머지 로직은 그대로 재사용됨).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

import pandas as pd

from core.indicators import (
    compute_bbw_squeeze_release,
    compute_bollinger,
    compute_doji,
    compute_double_pattern,
    compute_engulfing,
    compute_highest_high,
    compute_ichimoku,
    compute_inside_bar,
    compute_inside_bar_breakout,
    compute_lowest_low,
    compute_ma_cross,
    compute_macd,
    compute_marubozu,
    compute_mfi,
    compute_percent_b,
    compute_piercing_dark_cloud,
    compute_pin_bar,
    compute_rising_falling_three_methods,
    compute_rsi,
    compute_rsi_divergence,
    compute_star_pattern,
    compute_three_soldiers_crows,
    compute_volume_dryup_ratio,
    compute_volume_ratio,
    ema,
    sma,
)

Condition = dict[str, Any]
IndicatorConfig = dict[str, Any]


def _crossover(series: pd.Series, other: "pd.Series | float") -> pd.Series:
    """series가 other를 아래에서 위로 돌파하는 바(bar)에서 True인 이벤트 시리즈."""
    now_above = series > other
    prev_above = now_above.shift(1, fill_value=False)
    return (now_above & ~prev_above).fillna(False)


def _crossunder(series: pd.Series, other: "pd.Series | float") -> pd.Series:
    """series가 other를 위에서 아래로 이탈하는 바에서 True인 이벤트 시리즈."""
    now_below = series < other
    prev_below = now_below.shift(1, fill_value=False)
    return (now_below & ~prev_below).fillna(False)


def _eval_ma_cross(df: pd.DataFrame, cond: Condition) -> pd.Series:
    short = int(cond.get("short", 20))
    long = int(cond.get("long", 60))
    ma_type = cond.get("ma_type", "sma")
    cross = compute_ma_cross(df, short=short, long=long, ma_type=ma_type)
    if cond.get("type", "golden") == "dead":
        return ~cross["golden"].fillna(False)
    return cross["golden"].fillna(False)


_OPS: dict[str, Callable[[pd.Series, float], pd.Series]] = {
    "<": lambda s, v: s < v,
    "<=": lambda s, v: s <= v,
    ">": lambda s, v: s > v,
    ">=": lambda s, v: s >= v,
}


def _eval_rsi(df: pd.DataFrame, cond: Condition) -> pd.Series:
    period = int(cond.get("period", 14))
    op = cond.get("op", "<")
    value = float(cond.get("value", 30))
    rsi = compute_rsi(df, period=period)
    op_fn = _OPS.get(op)
    if op_fn is None:
        raise ValueError(f"지원하지 않는 연산자: {op}")
    return op_fn(rsi, value).fillna(False)


def _eval_bollinger(df: pd.DataFrame, cond: Condition) -> pd.Series:
    period = int(cond.get("period", 20))
    std_dev = float(cond.get("std_dev", 2.0))
    band = cond.get("band", "lower")
    op = cond.get("op", "break_below")
    bb = compute_bollinger(df, period=period, std_dev=std_dev)
    close = df["Close"]
    if band == "mid":
        return ((close > bb["mid"]) if op == "break_above" else (close < bb["mid"])).fillna(False)
    if band == "upper" or op == "break_above":
        return (close > bb["upper"]).fillna(False)
    return (close < bb["lower"]).fillna(False)


def _eval_bbw_squeeze_release(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """볼린저 밴드폭 스퀴즈 해제 이벤트 (스퀴즈 매매 전략의 진입 신호)."""
    return compute_bbw_squeeze_release(
        df,
        period=int(cond.get("period", 20)),
        std_dev=float(cond.get("std_dev", 2.0)),
        threshold=float(cond.get("threshold", 0.1)),
        lookback=int(cond.get("lookback", 20)),
        hold_bars=int(cond.get("hold_bars", 3)),
    )


def _eval_percent_b(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """볼린저 밴드 %B 레벨 조건 (추세추종 전략)."""
    period = int(cond.get("period", 20))
    std_dev = float(cond.get("std_dev", 2.0))
    op = cond.get("op", ">=")
    value = float(cond.get("value", 0.8))
    pb = compute_percent_b(df, period=period, std_dev=std_dev)
    op_fn = _OPS.get(op)
    if op_fn is None:
        raise ValueError(f"지원하지 않는 연산자: {op}")
    return op_fn(pb, value).fillna(False)


def _eval_mfi(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """MFI 레벨 조건 (추세추종 전략)."""
    period = int(cond.get("period", 14))
    op = cond.get("op", ">=")
    value = float(cond.get("value", 80))
    mfi = compute_mfi(df, period=period)
    op_fn = _OPS.get(op)
    if op_fn is None:
        raise ValueError(f"지원하지 않는 연산자: {op}")
    return op_fn(mfi, value).fillna(False)


def _eval_double_pattern(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """쌍바닥/쌍봉 추세 반전 패턴 이벤트."""
    pat = compute_double_pattern(
        df,
        band_period=int(cond.get("band_period", 20)),
        band_std=float(cond.get("band_std", 2.0)),
        pivot_lookback=int(cond.get("pivot_lookback", 5)),
        pattern_window=int(cond.get("pattern_window", 40)),
        volume_mult=float(cond.get("volume_mult", 1.5)),
    )
    return pat["bullish"] if cond.get("direction", "bullish") == "bullish" else pat["bearish"]


def _eval_rsi_divergence(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """가격-RSI 다이버전스 추세 반전 패턴 이벤트."""
    div = compute_rsi_divergence(
        df,
        rsi_period=int(cond.get("rsi_period", 14)),
        band_period=int(cond.get("band_period", 20)),
        pivot_lookback=int(cond.get("pivot_lookback", 5)),
        pattern_window=int(cond.get("pattern_window", 40)),
    )
    return div["bullish"] if cond.get("direction", "bullish") == "bullish" else div["bearish"]


def _eval_rsi_cross(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """RSI가 특정 레벨을 상향/하향 돌파하는 '이벤트' 바에서만 True (예: 후지모토 1단계 RSI 30 상향 돌파)."""
    period = int(cond.get("period", 14))
    level = float(cond.get("level", 30))
    direction = cond.get("direction", "up")
    rsi = compute_rsi(df, period=period)
    if direction == "down":
        return _crossunder(rsi, level)
    return _crossover(rsi, level)


def _eval_macd_cross(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """MACD선과 시그널선의 골든/데드 크로스 이벤트. zone으로 0선 위/아래 여부를 추가 필터링한다."""
    fast = int(cond.get("fast", 12))
    slow = int(cond.get("slow", 26))
    signal = int(cond.get("signal", 9))
    direction = cond.get("direction", "golden")
    zone = cond.get("zone", "any")
    macd_df = compute_macd(df, fast=fast, slow=slow, signal=signal)
    macd_line, signal_line = macd_df["macd"], macd_df["signal"]
    cross = _crossover(macd_line, signal_line) if direction == "golden" else _crossunder(macd_line, signal_line)
    if zone == "below_zero":
        cross = cross & (macd_line < 0)
    elif zone == "above_zero":
        cross = cross & (macd_line > 0)
    return cross.fillna(False)


def _eval_macd_level(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """MACD선(또는 히스토그램) 자체의 값을 기준값과 비교하는 레벨 조건 (예: MACD < 0)."""
    fast = int(cond.get("fast", 12))
    slow = int(cond.get("slow", 26))
    signal = int(cond.get("signal", 9))
    source = cond.get("source", "macd")  # "macd" | "hist"
    op = cond.get("op", "<")
    value = float(cond.get("value", 0))
    macd_df = compute_macd(df, fast=fast, slow=slow, signal=signal)
    series = macd_df["hist"] if source == "hist" else macd_df["macd"]
    op_fn = _OPS.get(op)
    if op_fn is None:
        raise ValueError(f"지원하지 않는 연산자: {op}")
    return op_fn(series, value).fillna(False)


def _ichimoku_from_cond(df: pd.DataFrame, cond: Condition) -> pd.DataFrame:
    return compute_ichimoku(
        df,
        tenkan_len=int(cond.get("tenkan_len", 9)),
        kijun_len=int(cond.get("kijun_len", 26)),
        span_b_len=int(cond.get("span_b_len", 52)),
        displacement=int(cond.get("displacement", 26)),
    )


def _eval_ichimoku_tk_state(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """전환선/기준선의 상대적 위치(국면). golden=전환선>기준선(상승국면), dead=반대."""
    ichi = _ichimoku_from_cond(df, cond)
    golden = ichi["tenkan"] > ichi["kijun"]
    return golden if cond.get("direction", "golden") == "golden" else ~golden.fillna(False)


def _eval_ichimoku_tk_cross(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """전환선이 기준선을 상향(golden)/하향(dead) 돌파하는 이벤트."""
    ichi = _ichimoku_from_cond(df, cond)
    if cond.get("direction", "golden") == "golden":
        return _crossover(ichi["tenkan"], ichi["kijun"])
    return _crossunder(ichi["tenkan"], ichi["kijun"])


def _eval_ichimoku_cloud_break(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """종가가 구름대 상단을 상향 돌파(up)/하단을 하향 이탈(down)하는 이벤트."""
    ichi = _ichimoku_from_cond(df, cond)
    close = df["Close"]
    if cond.get("direction", "up") == "up":
        return _crossover(close, ichi["cloud_top"])
    return _crossunder(close, ichi["cloud_bottom"])


def _eval_ichimoku_cloud_state(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """종가가 구름대 위(above)/아래(below)에 위치해있는 국면(레벨 조건)."""
    ichi = _ichimoku_from_cond(df, cond)
    close = df["Close"]
    if cond.get("direction", "above") == "above":
        return (close > ichi["cloud_top"]).fillna(False)
    return (close < ichi["cloud_bottom"]).fillna(False)


def _eval_engulfing(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """상승(bullish)/하락(bearish) 인걸(장악형) 캔들 패턴 이벤트."""
    eng = compute_engulfing(df)
    return eng["bullish"] if cond.get("direction", "bullish") == "bullish" else eng["bearish"]


def _eval_marubozu(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """마루보즈(장대양봉/장대음봉) 캔들 이벤트."""
    m = compute_marubozu(df, body_ratio_threshold=float(cond.get("body_ratio_threshold", 0.9)))
    return m["bullish"] if cond.get("direction", "bullish") == "bullish" else m["bearish"]


def _eval_pin_bar(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """핀바 캔들(강세/약세 반전) 이벤트."""
    p = compute_pin_bar(
        df,
        body_ratio_max=float(cond.get("body_ratio_max", 0.3)),
        wick_body_mult=float(cond.get("wick_body_mult", 2.0)),
    )
    return p["bullish"] if cond.get("direction", "bullish") == "bullish" else p["bearish"]


_DOJI_TYPES = ("standard", "long_legged", "dragonfly", "gravestone")


def _eval_doji(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """도지 캔들(일반/키다리형/잠자리형/비석형) 이벤트."""
    doji_type = cond.get("doji_type", "standard")
    if doji_type not in _DOJI_TYPES:
        raise ValueError(f"지원하지 않는 doji_type: {doji_type!r}")
    d = compute_doji(df, body_ratio_max=float(cond.get("body_ratio_max", 0.1)))
    return d[doji_type]


def _eval_inside_bar(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """인사이드바(마더 바 범위 안에 완전히 포함되는 캔들) 이벤트."""
    return compute_inside_bar(df)


def _eval_inside_bar_breakout(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """인사이드바 출현 후 마더 바 고점/저점을 종가가 돌파하는 이벤트(방향까지 판정된 상태)."""
    b = compute_inside_bar_breakout(df, lookback=int(cond.get("lookback", 5)))
    return b["bullish"] if cond.get("direction", "bullish") == "bullish" else b["bearish"]


def _eval_piercing_dark_cloud(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """관통형 캔들 패턴(상승 관통형/하락 관통형·흑운형, 볼린저 밴드 확인 포함) 이벤트."""
    p = compute_piercing_dark_cloud(
        df,
        band_period=int(cond.get("band_period", 20)),
        band_std=float(cond.get("band_std", 2.0)),
    )
    return p["bullish"] if cond.get("direction", "bullish") == "bullish" else p["bearish"]


def _eval_star_pattern(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """모닝스타(bullish)/이브닝스타(bearish) 3봉 반전 패턴 이벤트."""
    s = compute_star_pattern(
        df,
        star_body_ratio_max=float(cond.get("star_body_ratio_max", 0.3)),
        big_body_ratio_min=float(cond.get("big_body_ratio_min", 0.5)),
    )
    return s["bullish"] if cond.get("direction", "bullish") == "bullish" else s["bearish"]


def _eval_three_soldiers_crows(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """적삼병(bullish)/흑삼병(bearish) 3봉 추세 패턴 이벤트."""
    t = compute_three_soldiers_crows(df, body_ratio_min=float(cond.get("body_ratio_min", 0.6)))
    return t["bullish"] if cond.get("direction", "bullish") == "bullish" else t["bearish"]


def _eval_three_methods(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """상승/하락 삼법형(추세 지속) 패턴 이벤트."""
    t = compute_rising_falling_three_methods(
        df,
        n_pause=int(cond.get("n_pause", 3)),
        big_body_ratio_min=float(cond.get("big_body_ratio_min", 0.5)),
    )
    return t["bullish"] if cond.get("direction", "bullish") == "bullish" else t["bearish"]


def _eval_level_break(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """직전 N봉(당일 제외) 지지선/저항선 돌파 이벤트."""
    period = int(cond.get("period", 20))
    source = cond.get("source", "highest_high")
    level_fn = compute_highest_high if source == "highest_high" else compute_lowest_low
    level = level_fn(df, period=period).shift(1)
    close = df["Close"]
    if cond.get("op", "break_above") == "break_above":
        return (close > level).fillna(False)
    return (close < level).fillna(False)


def _eval_ma_touch(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """단일 이동평균선을 상향/하향 돌파(터치)하는 이벤트 (ma_cross의 단일선 버전)."""
    period = int(cond.get("period", 20))
    ma_series = ema(df["Close"], period) if cond.get("ma_type", "ema") == "ema" else sma(df["Close"], period)
    close = df["Close"]
    if cond.get("op", "break_below") == "break_above":
        return _crossover(close, ma_series)
    return _crossunder(close, ma_series)


def _eval_volume_spike(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """거래량이 직전 period일 평균 대비 mult배 이상 급증한 구간(매집/주도세력 진입 국면 포착)."""
    period = int(cond.get("period", 20))
    mult = float(cond.get("mult", 2.0))
    ratio = compute_volume_ratio(df, period=period)
    return (ratio >= mult).fillna(False)


def _eval_volume_dryup(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """거래량이 직전 lookback일 내 최고 거래량 대비 ratio 이하로 감소한 구간(눌림목 매물소화 국면 포착)."""
    lookback = int(cond.get("lookback", 10))
    ratio_threshold = float(cond.get("ratio", 0.4))
    ratio = compute_volume_dryup_ratio(df, lookback=lookback)
    return (ratio <= ratio_threshold).fillna(False)


def _eval_ichimoku_chikou_state(df: pd.DataFrame, cond: Condition) -> pd.Series:
    """후행스팬 판정: 현재 종가가 displacement 이전 종가보다 위(up)/아래(down)에 있는 국면."""
    displacement = int(cond.get("displacement", 26))
    close = df["Close"]
    chikou_ref = close.shift(displacement)
    if cond.get("direction", "up") == "up":
        return (close > chikou_ref).fillna(False)
    return (close < chikou_ref).fillna(False)


# 지표 이름 -> 평가 함수 레지스트리. 새 지표 추가 시 여기에 등록.
INDICATOR_EVALUATORS: dict[str, Callable[[pd.DataFrame, Condition], pd.Series]] = {
    "ma_cross": _eval_ma_cross,
    "rsi": _eval_rsi,
    "bollinger": _eval_bollinger,
    "rsi_cross": _eval_rsi_cross,
    "macd_cross": _eval_macd_cross,
    "macd_level": _eval_macd_level,
    "ichimoku_tk_state": _eval_ichimoku_tk_state,
    "ichimoku_tk_cross": _eval_ichimoku_tk_cross,
    "ichimoku_cloud_break": _eval_ichimoku_cloud_break,
    "ichimoku_cloud_state": _eval_ichimoku_cloud_state,
    "ichimoku_chikou_state": _eval_ichimoku_chikou_state,
    "engulfing": _eval_engulfing,
    "bbw_squeeze_release": _eval_bbw_squeeze_release,
    "percent_b": _eval_percent_b,
    "mfi": _eval_mfi,
    "double_pattern": _eval_double_pattern,
    "rsi_divergence": _eval_rsi_divergence,
    "marubozu": _eval_marubozu,
    "pin_bar": _eval_pin_bar,
    "doji": _eval_doji,
    "inside_bar": _eval_inside_bar,
    "inside_bar_breakout": _eval_inside_bar_breakout,
    "piercing_dark_cloud": _eval_piercing_dark_cloud,
    "star_pattern": _eval_star_pattern,
    "three_soldiers_crows": _eval_three_soldiers_crows,
    "three_methods": _eval_three_methods,
    "level_break": _eval_level_break,
    "ma_touch": _eval_ma_touch,
    "volume_spike": _eval_volume_spike,
    "volume_dryup": _eval_volume_dryup,
}


def evaluate_condition(df: pd.DataFrame, condition: Condition) -> pd.Series:
    """조건 하나를 df 전체 구간에 대해 평가해 불리언 Series를 반환한다."""
    indicator = condition.get("indicator")
    evaluator = INDICATOR_EVALUATORS.get(indicator)
    if evaluator is None:
        raise ValueError(f"지원하지 않는 지표: {indicator!r}")
    return evaluator(df, condition)


def describe_condition(cond: Condition) -> str:
    """조건 하나를 사람이 읽을 수 있는 한국어 문구로 바꾼다 (차트 호버 툴팁의 진입/청산 근거 표시용)."""

    def _fmt(v: float) -> str:
        return f"{v:g}"

    indicator = cond.get("indicator")
    if indicator == "ma_cross":
        short, long = cond.get("short", 20), cond.get("long", 60)
        kind = "골든크로스" if cond.get("type", "golden") == "golden" else "데드크로스"
        return f"MA{short}/MA{long} {kind} 국면"
    if indicator == "rsi":
        period = cond.get("period", 14)
        op = cond.get("op", "<")
        value = _fmt(float(cond.get("value", 30)))
        return f"RSI({period}) {op} {value}"
    if indicator == "bollinger":
        period = cond.get("period", 20)
        band = cond.get("band", "lower")
        op = cond.get("op")
        if band == "mid":
            return f"볼린저밴드({period}) 중심선 {'상향 돌파' if op == 'break_above' else '하향 이탈'}"
        if band == "upper" or op == "break_above":
            return f"볼린저밴드({period}) 상단 상향 돌파"
        return f"볼린저밴드({period}) 하단 하향 이탈"
    if indicator == "bbw_squeeze_release":
        threshold = _fmt(float(cond.get("threshold", 0.1)))
        return f"볼린저 밴드폭 스퀴즈({threshold}) 해제"
    if indicator == "percent_b":
        op = cond.get("op", ">=")
        value = _fmt(float(cond.get("value", 0.8)))
        return f"%B {op} {value}"
    if indicator == "mfi":
        period = cond.get("period", 14)
        op = cond.get("op", ">=")
        value = _fmt(float(cond.get("value", 80)))
        return f"MFI({period}) {op} {value}"
    if indicator == "double_pattern":
        direction = "쌍바닥" if cond.get("direction", "bullish") == "bullish" else "쌍봉"
        return f"{direction} 반전 패턴 확인"
    if indicator == "rsi_divergence":
        direction = "상승" if cond.get("direction", "bullish") == "bullish" else "하락"
        return f"가격-RSI {direction} 다이버전스"
    if indicator == "rsi_cross":
        period = cond.get("period", 14)
        level = _fmt(float(cond.get("level", 30)))
        direction = "상향" if cond.get("direction", "up") == "up" else "하향"
        return f"RSI({period}) {level} {direction} 돌파"
    if indicator == "macd_cross":
        direction = "골든크로스" if cond.get("direction", "golden") == "golden" else "데드크로스"
        zone_txt = {"below_zero": " (0선 아래)", "above_zero": " (0선 위)"}.get(cond.get("zone", "any"), "")
        return f"MACD {direction}{zone_txt}"
    if indicator == "macd_level":
        source = "MACD 히스토그램" if cond.get("source") == "hist" else "MACD"
        op = cond.get("op", "<")
        value = _fmt(float(cond.get("value", 0)))
        return f"{source} {op} {value}"
    if indicator == "ichimoku_tk_state":
        direction = "상회(골든)" if cond.get("direction", "golden") == "golden" else "하회(데드)"
        return f"일목 전환선이 기준선 {direction} 국면"
    if indicator == "ichimoku_tk_cross":
        direction = "골든크로스" if cond.get("direction", "golden") == "golden" else "데드크로스"
        return f"일목 전환선-기준선 {direction}"
    if indicator == "ichimoku_cloud_break":
        direction = "상단 상향 돌파" if cond.get("direction", "up") == "up" else "하단 하향 이탈"
        return f"종가가 구름대 {direction}"
    if indicator == "ichimoku_cloud_state":
        direction = "위" if cond.get("direction", "above") == "above" else "아래"
        return f"종가가 구름대 {direction}에 위치"
    if indicator == "ichimoku_chikou_state":
        displacement = cond.get("displacement", 26)
        direction = "위" if cond.get("direction", "up") == "up" else "아래"
        return f"후행스팬이 {displacement}봉 전 종가보다 {direction}"
    if indicator == "engulfing":
        direction = "상승" if cond.get("direction", "bullish") == "bullish" else "하락"
        return f"{direction} 인걸(장악형) 캔들 출현"
    if indicator == "marubozu":
        direction = "상승(장대양봉)" if cond.get("direction", "bullish") == "bullish" else "하락(장대음봉)"
        return f"{direction} 마루보즈 캔들 출현"
    if indicator == "pin_bar":
        direction = "강세" if cond.get("direction", "bullish") == "bullish" else "약세"
        return f"{direction} 핀바 캔들 출현"
    if indicator == "doji":
        names = {"standard": "일반", "long_legged": "키다리형", "dragonfly": "잠자리형", "gravestone": "비석형"}
        return f"{names.get(cond.get('doji_type', 'standard'), '일반')} 도지 캔들 출현"
    if indicator == "inside_bar":
        return "인사이드바(마더 바 범위 내 캔들) 출현"
    if indicator == "inside_bar_breakout":
        direction = "상향" if cond.get("direction", "bullish") == "bullish" else "하향"
        return f"인사이드바 이후 마더 바 {direction} 돌파"
    if indicator == "piercing_dark_cloud":
        direction = "상승 관통형" if cond.get("direction", "bullish") == "bullish" else "하락 관통형(흑운형)"
        return f"{direction} 캔들 패턴 확인"
    if indicator == "star_pattern":
        direction = "모닝스타" if cond.get("direction", "bullish") == "bullish" else "이브닝스타"
        return f"{direction} 3봉 반전 패턴 확인"
    if indicator == "three_soldiers_crows":
        direction = "적삼병" if cond.get("direction", "bullish") == "bullish" else "흑삼병"
        return f"{direction} 3봉 추세 패턴 확인"
    if indicator == "three_methods":
        direction = "상승 삼법형" if cond.get("direction", "bullish") == "bullish" else "하락 삼법형"
        return f"{direction} 추세 지속 패턴 확인"
    if indicator == "level_break":
        period = cond.get("period", 20)
        direction = "저항선(고점)" if cond.get("source", "highest_high") == "highest_high" else "지지선(저점)"
        op_txt = "상향 돌파" if cond.get("op", "break_above") == "break_above" else "하향 이탈"
        return f"최근 {period}봉 {direction} {op_txt}"
    if indicator == "ma_touch":
        period, ma_type = cond.get("period", 20), cond.get("ma_type", "ema")
        op_txt = "상향 돌파" if cond.get("op", "break_below") == "break_above" else "하향 이탈(터치)"
        return f"{str(ma_type).upper()}{period} {op_txt}"
    if indicator == "volume_spike":
        period = cond.get("period", 20)
        mult = _fmt(float(cond.get("mult", 2.0)))
        return f"거래량이 {period}일 평균 대비 {mult}배 이상 급증"
    if indicator == "volume_dryup":
        lookback = cond.get("lookback", 10)
        ratio = _fmt(float(cond.get("ratio", 0.4)))
        return f"거래량이 최근 {lookback}일 고점 대비 {ratio}배 이하로 감소"
    return indicator or "조건"


def _condition_pairs(df: pd.DataFrame, conditions: list[Condition]) -> list[tuple[str, pd.Series]]:
    """조건 목록을 (설명 문구, 불리언 Series) 쌍의 목록으로 미리 계산해둔다.

    근거 문구는 어디까지나 부가 정보이므로, 개별 조건 평가에 실패해도(예: 알 수 없는 지표)
    그 조건만 조용히 건너뛴다 — combine_conditions()가 같은 조건으로 이미 성공했다면
    (실제 백테스트 실행 경로) 여기서도 항상 성공하므로 실질적으로는 발생하지 않는다.
    """
    pairs = []
    for c in conditions:
        try:
            pairs.append((describe_condition(c), evaluate_condition(df, c)))
        except Exception:
            continue
    return pairs


def _active_reason(pairs: list[tuple[str, pd.Series]], logic: str, i: int) -> str:
    """i번째 바에서 신호가 True가 된(진입/단계진입 등) 이유를, 실제로 만족된 조건들을 나열해 만든다.

    AND 결합은 정의상 모든 조건이 동시에 참이어야 신호가 뜨므로 전부 나열하고,
    OR 결합은 실제로 참인 조건만 골라 나열한다(그래야 "왜 하필 지금 떴는지"가 드러난다).
    """
    if not pairs:
        return "조건 충족"
    if str(logic).upper() == "AND":
        active = [desc for desc, _ in pairs]
    else:
        active = [desc for desc, s in pairs if bool(s.iloc[i])]
    return " & ".join(active) if active else "조건 충족"


def _inactive_reason(pairs: list[tuple[str, pd.Series]], logic: str, i: int) -> str:
    """i번째 바에서 신호가 False로 바뀐(레짐 청산) 이유를, 더 이상 만족하지 않는 조건들을 나열해 만든다.

    AND 결합은 조건 중 하나라도 깨지면 전체가 꺼지므로 깨진 조건만 골라 나열하고,
    OR 결합은 전부 꺼져야 신호가 꺼지므로 전부 나열한다.
    """
    if not pairs:
        return "조건 해제"
    if str(logic).upper() == "AND":
        inactive = [desc for desc, s in pairs if not bool(s.iloc[i])]
    else:
        inactive = [desc for desc, _ in pairs]
    return (" & ".join(inactive) + " 조건 이탈") if inactive else "조건 해제"


def parse_indicator_config(indicator_config: str | IndicatorConfig) -> IndicatorConfig:
    """JSON 문자열 또는 dict 를 받아 dict 로 정규화한다."""
    if isinstance(indicator_config, str):
        return json.loads(indicator_config)
    return indicator_config


def combine_conditions(df: pd.DataFrame, indicator_config: str | IndicatorConfig) -> pd.Series:
    """여러 조건을 logic(AND/OR)에 따라 결합해 최종 포지션 보유 조건 Series를 만든다.

    조건이 비어있으면 항상 False(포지션 없음)를 반환한다.
    """
    config = parse_indicator_config(indicator_config)
    conditions = config.get("conditions", [])
    logic = str(config.get("logic", "AND")).upper()

    if not conditions:
        return pd.Series(False, index=df.index)

    series_list = [evaluate_condition(df, c) for c in conditions]
    combined = series_list[0]
    for s in series_list[1:]:
        combined = (combined & s) if logic == "AND" else (combined | s)
    return combined.fillna(False)


def is_expression_config(indicator_config: str | IndicatorConfig) -> bool:
    """indicator_config가 직접 수식(expression) 전략 스키마인지 판별한다.

    레짐형(conditions 키)/1:2:6 단계별(entry_stages 키)과 달리 "expression" 키가 있으면
    직접 수식 전략으로 본다 (core/expression_engine.py 참고).
    """
    config = parse_indicator_config(indicator_config)
    return isinstance(config, dict) and "expression" in config


def generate_regime_signal(df: pd.DataFrame, indicator_config: str | IndicatorConfig) -> pd.Series:
    """레짐형(AND/OR) 또는 직접 수식(expression) 전략을 평가해 불리언 Series를 반환한다.

    1:2:6 단계별(staged)/복합(combined) 전략은 evaluate_boolean_signal()을 쓰므로 여기서 다루지 않는다.
    """
    config = parse_indicator_config(indicator_config)
    if is_expression_config(config):
        from core.expression_engine import evaluate_expression

        return evaluate_expression(df, config["expression"])
    return combine_conditions(df, config)


def generate_positions(df: pd.DataFrame, indicator_config: str | IndicatorConfig) -> pd.Series:
    """조건이 True인 구간을 1(보유), False인 구간을 0(미보유)으로 하는 포지션 Series를 만든다."""
    signal = evaluate_boolean_signal(df, indicator_config)
    return signal.astype(int)


def is_staged_config(indicator_config: str | IndicatorConfig) -> bool:
    """indicator_config가 1:2:6 식 단계별(staged) 전략 스키마인지 판별한다.

    일반 AND/OR 레짐 전략(conditions 키)과 달리 "entry_stages" 키가 있으면 staged 전략으로 본다.
    """
    config = parse_indicator_config(indicator_config)
    return isinstance(config, dict) and "entry_stages" in config


def is_combined_config(indicator_config: str | IndicatorConfig) -> bool:
    """indicator_config가 복합(전략 합성) 전략 스키마인지 판별한다.

    "combine"(AND/OR)과 "strategies"(하위 전략 설정 목록) 키가 모두 있으면 복합 전략으로 본다.
    하위 전략은 레짐/직접 수식/1:2:6 단계별/복합 어떤 스키마든 재귀적으로 담을 수 있다.
    """
    config = parse_indicator_config(indicator_config)
    return isinstance(config, dict) and "combine" in config and "strategies" in config


def evaluate_boolean_signal(df: pd.DataFrame, indicator_config: str | IndicatorConfig) -> pd.Series:
    """전략 스키마 4종(레짐/직접 수식/1:2:6 단계별/복합) 전부를 판별해 '포지션 보유 중' 불리언
    시그널 하나로 통일해서 반환한다.

    복합 전략의 하위 전략을 재귀 평가할 때 쓰는 공용 진입점이다 — 하위 전략이 1:2:6 단계별이면
    비중(weight)>0인 구간을 보유로 간주해 불리언으로 단순화하고, 하위 전략이 다시 복합 전략이면
    재귀적으로 내려간다. generate_positions()와 evaluate()가 이 함수를 공통으로 사용한다.
    """
    config = parse_indicator_config(indicator_config)
    if is_combined_config(config):
        sub_configs = config.get("strategies", [])
        if not sub_configs:
            return pd.Series(False, index=df.index)
        combine_logic = str(config.get("combine", "AND")).upper()
        sub_signals = [evaluate_boolean_signal(df, sub) for sub in sub_configs]
        combined = sub_signals[0]
        for s in sub_signals[1:]:
            combined = (combined & s) if combine_logic == "AND" else (combined | s)
        return combined.fillna(False)
    if is_staged_config(config):
        weight_signal, _events = simulate_staged_positions(df, config)
        return (weight_signal > 0).fillna(False)
    return generate_regime_signal(df, config)


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: Optional[pd.Timestamp]
    entry_price: float
    exit_price: Optional[float]
    return_pct: Optional[float]
    entry_reason: Optional[str] = None  # 진입 근거 문구 (차트 호버 툴팁용, indicator_config 없으면 None)
    exit_reason: Optional[str] = None  # 청산 근거 문구 (마지막 강제 청산은 그 사실을 그대로 명시)


def extract_trades(
    df: pd.DataFrame, position: pd.Series, indicator_config: str | IndicatorConfig | None = None
) -> list[Trade]:
    """포지션 시리즈(0/1)에서 개별 매매(진입~청산) 목록을 추출한다.

    실제 체결은 신호가 발생한 다음 거래일 종가에 이루어진다고 가정한다
    (신호 당일 종가는 알 수 없다고 보고 lookahead bias를 피하기 위함).
    마지막까지 포지션이 열려있으면 마지막 거래일 종가로 강제 청산해 미실현 손익을 집계한다.

    indicator_config를 넘기면(레짐형/직접 수식 전략만 해당, 1:2:6 단계별은 simulate_staged_positions
    별도 경로 사용) 각 Trade에 진입/청산 근거 문구를 채워 넣는다 — 실제 신호가 뜬 날은 체결일(다음
    거래일)보다 하루 전이므로, 그 날짜 기준으로 어떤 조건이 참/거짓이었는지를 읽어 문구를 만든다.
    """
    close = df["Close"]
    executed_position = position.shift(1).fillna(0).astype(int)

    reason_pairs: list[tuple[str, pd.Series]] = []
    reason_logic = "AND"
    expression_text: Optional[str] = None
    combined_summary: Optional[str] = None
    if indicator_config is not None:
        config = parse_indicator_config(indicator_config)
        if is_combined_config(config):
            combine_logic = str(config.get("combine", "AND")).upper()
            n_sub = len(config.get("strategies", []))
            combined_summary = f"복합 전략({combine_logic} 결합, 하위 전략 {n_sub}개)"
        elif is_expression_config(config):
            expression_text = config.get("expression", "")
        else:
            reason_logic = str(config.get("logic", "AND")).upper()
            reason_pairs = _condition_pairs(df, config.get("conditions", []))

    def _entry_reason(signal_idx: int) -> Optional[str]:
        if indicator_config is None:
            return None
        if combined_summary is not None:
            return f"{combined_summary} 조건 충족"
        if expression_text is not None:
            return f"수식 조건 충족: {expression_text}"
        return _active_reason(reason_pairs, reason_logic, signal_idx)

    def _exit_reason(signal_idx: int) -> Optional[str]:
        if indicator_config is None:
            return None
        if combined_summary is not None:
            return f"{combined_summary} 조건 이탈"
        if expression_text is not None:
            return f"수식 조건 이탈: {expression_text}"
        return _inactive_reason(reason_pairs, reason_logic, signal_idx)

    trades: list[Trade] = []
    entry_idx: Optional[int] = None
    index_list = df.index

    for i in range(len(index_list)):
        pos = executed_position.iloc[i]
        prev_pos = executed_position.iloc[i - 1] if i > 0 else 0
        if pos == 1 and prev_pos == 0:
            entry_idx = i
        elif pos == 0 and prev_pos == 1 and entry_idx is not None:
            entry_price = float(close.iloc[entry_idx])
            exit_price = float(close.iloc[i])
            trades.append(
                Trade(
                    entry_date=index_list[entry_idx],
                    exit_date=index_list[i],
                    entry_price=entry_price,
                    exit_price=exit_price,
                    return_pct=(exit_price / entry_price - 1) * 100,
                    entry_reason=_entry_reason(entry_idx - 1),
                    exit_reason=_exit_reason(i - 1),
                )
            )
            entry_idx = None

    if entry_idx is not None:
        entry_price = float(close.iloc[entry_idx])
        exit_price = float(close.iloc[-1])
        trades.append(
            Trade(
                entry_date=index_list[entry_idx],
                exit_date=index_list[-1],
                entry_price=entry_price,
                exit_price=exit_price,
                return_pct=(exit_price / entry_price - 1) * 100,
                entry_reason=_entry_reason(entry_idx - 1),
                exit_reason=(
                    "백테스트 종료 시점 강제 청산 (조건 이탈 아님)" if indicator_config is not None else None
                ),
            )
        )

    return trades


@dataclass
class StageEvent:
    """1:2:6 식 단계별 전략의 진입/청산 이벤트 로그 (UI 표시/디버깅용)."""

    date: pd.Timestamp
    kind: str  # "entry" | "exit" | "emergency_exit" | "stop_loss" | "take_profit"
    stage: int  # 1-based 단계 번호 (entry_stages/exit_stages 의 인덱스+1)
    weight: float  # 이 이벤트로 늘거나 준 비중 (0~1)
    price: float  # 신호 발생일 종가 (참고용. 실제 체결가는 extract_staged_trades 에서 다음 거래일 종가 사용)
    reason: str = ""  # 이 단계의 조건 중 실제로 만족된 조건들을 나열한 근거 문구 (차트 호버 툴팁용)


# 진입가 기준 손절(stop_loss)의 "레벨 소스" 레지스트리. INDICATOR_EVALUATORS(불리언 반환)와 달리
# 원본 가격 레벨(숫자) 시리즈를 반환한다 — 진입 사이클이 시작되는 바에서 이 값을 스냅샷해 고정하고,
# 그 사이클이 끝날 때까지 종가가 그 레벨 아래로 내려오면 즉시 전량 청산한다.
STOP_LOSS_SOURCES: dict[str, Callable[[pd.DataFrame, dict], pd.Series]] = {
    "bollinger_mid": lambda df, p: compute_bollinger(
        df, period=int(p.get("period", 20)), std_dev=float(p.get("std_dev", 2.0))
    )["mid"],
    "lowest_low": lambda df, p: compute_lowest_low(df, period=int(p.get("period", 20))),
    "highest_high": lambda df, p: compute_highest_high(df, period=int(p.get("period", 20))),
}


def _stop_loss_level_series(df: pd.DataFrame, stop_loss_def: Optional[dict]) -> Optional[pd.Series]:
    """stop_loss 설정을 레벨(가격) 시리즈로 변환한다. 설정이 없으면 None."""
    if not stop_loss_def:
        return None
    source = stop_loss_def.get("source")
    fn = STOP_LOSS_SOURCES.get(source)
    if fn is None:
        raise ValueError(f"지원하지 않는 stop_loss source: {source!r}")
    return fn(df, stop_loss_def)


def simulate_staged_positions(
    df: pd.DataFrame, staged_config: str | IndicatorConfig
) -> tuple[pd.Series, list[StageEvent]]:
    """후지모토 시게루류 1:2:6 단계별 진입/청산 전략을 시뮬레이션한다.

    staged_config 스키마:
        {
            "entry_stages": [
                {"weight": 0.1, "logic": "AND", "conditions": [...]},
                {"weight": 0.2, "logic": "AND", "conditions": [...]},
                {"weight": 0.6, "logic": "AND", "conditions": [...]}
            ],
            "exit_stages": [ (entry_stages와 동일한 형식) ... ],
            "emergency_exit": {"logic": "AND", "conditions": [...]},  # 선택. 뜨면 단계 무관 즉시 전량 청산
            "stop_loss": {"source": "bollinger_mid", "period": 20},   # 선택. 진입가 기준 손절(아래 설명)
            "take_profit": {"multiple": 2.0}                         # 선택. 손절 대비 배수 익절(아래 설명)
        }

    stop_loss(선택): 포지션이 없다가 새로 진입하는 바("사이클 시작")에서 source가 가리키는 가격
    레벨(불리언이 아니라 숫자값 — 볼린저 중심선/최근 N봉 최저·최고가 등)을 그 순간 값으로 스냅샷해
    고정한다. 그 사이클이 끝날 때까지, 이후 지표가 어떻게 움직이든 이 고정된 레벨을 기준으로 종가가
    그 아래로 내려오면(롱 전용이므로 항상 "하향 이탈" 판정) emergency_exit과 동일한 우선순위로 즉시
    전량 청산한다. source 종류는 STOP_LOSS_SOURCES 참고("bollinger_mid"|"lowest_low"|"highest_high").

    take_profit(선택, stop_loss 필수 동반): "손절선 대비 N배" 식으로 정의되는 목표 익절가. stop_loss와
    같은 사이클 시작 바에서 `목표가 = 진입참조가 + multiple * (진입참조가 - 손절레벨)`을 스냅샷해
    고정한다. 종가가 이 목표가 이상이 되면 stop_loss와 동일한 우선순위로 즉시 전량 청산한다.
    stop_loss 없이 take_profit만 정의하면 ValueError (배수 계산의 기준이 되는 손절 거리가 없으므로).

    각 stage의 conditions는 combine_conditions()가 이해하는 문법을 그대로 쓴다
    (rsi_cross/macd_cross/ichimoku_* 등 "이벤트"성 지표를 포함해 AND/OR 조합 가능).

    진입 규칙: 중간 단계(k < 마지막)는 바로 이전 단계까지 진입된 상태에서만 순서대로 진행된다.
    마지막 단계는 이전 단계를 거치지 않고 곧바로 진입할 수 있다(강한 확인 신호가 바로 뜨면 크게 진입).
    청산 규칙: 청산 단계 k(< 마지막)는 그에 대응하는 진입 단계 k의 물량만 개별적으로 정리한다.
    "마지막" 청산 단계(exit_stages의 마지막 원소)는 항상 "잔량 전부 정리" 신호로 취급한다 — 그 조건이
    뜨면 어떤 진입 단계가 열려있는지, entry_stages/exit_stages 개수가 서로 다른지와 무관하게 현재 열린
    포지션을 전부 청산한다(entry_stages가 exit_stages보다 많아서 마지막 진입 단계로 직행한 태그의
    인덱스가 exit_stages 범위를 벗어나는 경우에도 청산이 보장되도록 하기 위함). emergency_exit 조건이
    뜨면 단계와 무관하게 즉시 전량 청산한다.

    Returns:
        (weight_signal, events)
        weight_signal: 0~1 사이의 목표 포지션 비중 시그널(신호 발생일 기준) — 다른 전략들과 동일하게
            core.backtest_engine.compute_equity_curve 가 다음 거래일부터 체결되는 것으로 처리한다.
        events: 발생한 진입/청산 이벤트 로그 (StageEvent 리스트).
    """
    config = parse_indicator_config(staged_config)
    entry_defs = config.get("entry_stages", [])
    exit_defs = config.get("exit_stages", [])
    emergency_def = config.get("emergency_exit")
    stop_loss_def = config.get("stop_loss")
    take_profit_def = config.get("take_profit")
    if take_profit_def and not stop_loss_def:
        raise ValueError("take_profit은 stop_loss와 함께 정의해야 합니다 (손절 대비 배수로 목표가를 계산).")

    if not entry_defs:
        return pd.Series(0.0, index=df.index), []

    n_entry, n_exit = len(entry_defs), len(exit_defs)
    entry_signals = [combine_conditions(df, d) for d in entry_defs]
    exit_signals = [combine_conditions(df, d) for d in exit_defs]
    emergency_signal = (
        combine_conditions(df, emergency_def) if emergency_def else pd.Series(False, index=df.index)
    )
    entry_weights = [float(d.get("weight", 0)) for d in entry_defs]

    # 이벤트 발생 시 "왜 떴는지" 문구를 즉시 만들 수 있도록, 단계별 조건-설명 쌍을 미리 계산해둔다.
    entry_pairs = [_condition_pairs(df, d.get("conditions", [])) for d in entry_defs]
    entry_logics = [str(d.get("logic", "AND")).upper() for d in entry_defs]
    exit_pairs = [_condition_pairs(df, d.get("conditions", [])) for d in exit_defs]
    exit_logics = [str(d.get("logic", "AND")).upper() for d in exit_defs]
    emergency_pairs = _condition_pairs(df, emergency_def.get("conditions", [])) if emergency_def else []
    emergency_logic = str(emergency_def.get("logic", "AND")).upper() if emergency_def else "AND"
    stop_loss_levels = _stop_loss_level_series(df, stop_loss_def)

    close = df["Close"]
    weight_signal = pd.Series(0.0, index=df.index)
    events: list[StageEvent] = []

    stage_level = 0
    open_tags: dict[int, float] = {}
    cycle_stop_level: Optional[float] = None
    cycle_tp_level: Optional[float] = None

    for i, day in enumerate(df.index):
        was_flat = not open_tags
        for k in range(1, n_entry + 1):
            if not bool(entry_signals[k - 1].iloc[i]):
                continue
            is_last = k == n_entry
            allowed = (stage_level < k) if is_last else (stage_level == k - 1)
            if allowed and k not in open_tags:
                open_tags[k] = entry_weights[k - 1]
                stage_level = max(stage_level, k)
                reason = _active_reason(entry_pairs[k - 1], entry_logics[k - 1], i)
                events.append(StageEvent(day, "entry", k, entry_weights[k - 1], float(close.iloc[i]), reason))

        if was_flat and open_tags:
            if stop_loss_levels is not None:
                level = float(stop_loss_levels.iloc[i])
                cycle_stop_level = level if pd.notna(level) else None
            if take_profit_def and cycle_stop_level is not None:
                multiple = float(take_profit_def.get("multiple", 2.0))
                entry_ref_price = float(close.iloc[i])
                cycle_tp_level = entry_ref_price + multiple * (entry_ref_price - cycle_stop_level)

        if open_tags:
            if emergency_def and bool(emergency_signal.iloc[i]):
                reason = _active_reason(emergency_pairs, emergency_logic, i)
                for k, w in sorted(open_tags.items()):
                    events.append(StageEvent(day, "emergency_exit", k, w, float(close.iloc[i]), reason))
                open_tags = {}
            elif cycle_tp_level is not None and float(close.iloc[i]) >= cycle_tp_level:
                reason = f"진입 시점 기준 목표 익절가({cycle_tp_level:.2f}) 도달"
                for k, w in sorted(open_tags.items()):
                    events.append(StageEvent(day, "take_profit", k, w, float(close.iloc[i]), reason))
                open_tags = {}
            elif cycle_stop_level is not None and float(close.iloc[i]) < cycle_stop_level:
                reason = f"진입 시점 손절 레벨({cycle_stop_level:.2f}) 하향 이탈"
                for k, w in sorted(open_tags.items()):
                    events.append(StageEvent(day, "stop_loss", k, w, float(close.iloc[i]), reason))
                open_tags = {}
            elif n_exit > 0 and bool(exit_signals[n_exit - 1].iloc[i]):
                # 마지막 청산 단계는 태그 인덱스와 무관하게 열려있는 물량을 전부 정리한다.
                reason = _active_reason(exit_pairs[n_exit - 1], exit_logics[n_exit - 1], i)
                for k, w in sorted(open_tags.items()):
                    events.append(StageEvent(day, "exit", k, w, float(close.iloc[i]), reason))
                open_tags = {}
            else:
                for k in range(1, n_exit):
                    if k in open_tags and bool(exit_signals[k - 1].iloc[i]):
                        w = open_tags.pop(k)
                        reason = _active_reason(exit_pairs[k - 1], exit_logics[k - 1], i)
                        events.append(StageEvent(day, "exit", k, w, float(close.iloc[i]), reason))

        if not open_tags:
            stage_level = 0
            cycle_stop_level = None
            cycle_tp_level = None

        weight_signal.iloc[i] = sum(open_tags.values())

    return weight_signal, events


def extract_staged_trades(df: pd.DataFrame, events: list[StageEvent]) -> list[Trade]:
    """StageEvent 로그를 미보유->진입->...->미보유 사이클 단위의 Trade(가중평균 단가)로 묶는다.

    엔진 전체의 lookahead 방지 관례에 맞춰, 이벤트가 기록된 날짜의 "다음 거래일" 종가를
    실제 체결가로 사용해 가중평균 진입/청산 단가와 수익률을 계산한다.
    """
    if not events:
        return []

    close = df["Close"]
    index_list = df.index
    date_to_pos = {d: i for i, d in enumerate(index_list)}

    def _execution_price(event_date: pd.Timestamp) -> float:
        pos = date_to_pos[event_date]
        exec_pos = min(pos + 1, len(index_list) - 1)
        return float(close.iloc[exec_pos])

    trades: list[Trade] = []
    cycle_entries: list[tuple[float, float]] = []
    cycle_exits: list[tuple[float, float]] = []
    cycle_start: Optional[pd.Timestamp] = None
    open_weight = 0.0

    for ev in events:
        price = _execution_price(ev.date)
        if ev.kind == "entry":
            if not cycle_entries:
                cycle_start = ev.date
            cycle_entries.append((ev.weight, price))
            open_weight += ev.weight
        else:
            cycle_exits.append((ev.weight, price))
            open_weight = round(open_weight - ev.weight, 10)
            if open_weight <= 1e-9:
                entry_w = sum(w for w, _ in cycle_entries)
                exit_w = sum(w for w, _ in cycle_exits)
                avg_entry = sum(w * p for w, p in cycle_entries) / entry_w if entry_w else 0.0
                avg_exit = sum(w * p for w, p in cycle_exits) / exit_w if exit_w else 0.0
                trades.append(
                    Trade(
                        entry_date=cycle_start,
                        exit_date=ev.date,
                        entry_price=avg_entry,
                        exit_price=avg_exit,
                        return_pct=(avg_exit / avg_entry - 1) * 100 if avg_entry else None,
                    )
                )
                cycle_entries, cycle_exits, open_weight = [], [], 0.0

    if cycle_entries:
        entry_w = sum(w for w, _ in cycle_entries)
        avg_entry = sum(w * p for w, p in cycle_entries) / entry_w if entry_w else 0.0
        exit_price = float(close.iloc[-1])
        trades.append(
            Trade(
                entry_date=cycle_start,
                exit_date=index_list[-1],
                entry_price=avg_entry,
                exit_price=exit_price,
                return_pct=(exit_price / avg_entry - 1) * 100 if avg_entry else None,
            )
        )

    return trades


def evaluate(ticker: str, indicator_config: str | IndicatorConfig, lookback_days: int = 400) -> dict:
    """스케줄러(모듈 C)가 매일 관심 종목을 스캔할 때 사용하는 진입점.

    가장 최근 시세로 지표를 계산해 "오늘 새로 신호가 켜졌는지"(전일 미보유 -> 금일 보유)를 확인한다.

    Returns:
        {
            "triggered": bool,       # 오늘 신호가 새로 발생했는지 여부
            "in_position": bool,     # 오늘 조건 자체 충족 여부(레짐 유지 포함)
            "as_of": str | None,     # 기준일(YYYY-MM-DD)
            "message": str,          # 알림/로그용 메시지
        }
    """
    from datetime import date, timedelta

    from core.market_data import get_price_history

    start = (date.today() - timedelta(days=lookback_days)).isoformat()
    df = get_price_history(ticker, start=start, use_cache=True)

    if df is None or df.empty or "Close" not in df.columns or len(df) < 2:
        return {
            "triggered": False,
            "in_position": False,
            "as_of": None,
            "message": f"{ticker}: 가격 데이터를 가져오지 못했습니다.",
        }

    if is_staged_config(indicator_config):
        weight_signal, _events = simulate_staged_positions(df, indicator_config)
        today_w = float(weight_signal.iloc[-1])
        yesterday_w = float(weight_signal.iloc[-2])
        today = today_w > 0
        triggered = today_w > yesterday_w + 1e-9  # 비중이 늘었으면(신규 단계 진입) 신호로 간주
    else:
        signal = evaluate_boolean_signal(df, indicator_config)
        today = bool(signal.iloc[-1])
        yesterday = bool(signal.iloc[-2])
        triggered = today and not yesterday
    as_of = pd.Timestamp(df.index[-1]).date().isoformat()

    if triggered:
        message = f"{ticker}: 전략 조건 충족(신규 진입 신호) — 기준일 {as_of}"
    elif today:
        message = f"{ticker}: 전략 조건 유지 중(신규 신호 아님) — 기준일 {as_of}"
    else:
        message = f"{ticker}: 전략 조건 미충족 — 기준일 {as_of}"

    return {
        "triggered": triggered,
        "in_position": today,
        "as_of": as_of,
        "message": message,
    }
