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

세 번째 스키마로 "직접 수식(expression)" 전략도 지원한다 (core/expression_engine.py):
    {"expression": "close > sma(close, 20) and rsi(close, 14) < 30"}
지표 토글로 표현하기 어려운 조건을 사용자가 파이썬과 비슷한 문법으로 직접 입력할 수 있다.
자세한 문법/함수 목록은 core/expression_engine.py 를 참고.

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
    compute_bollinger,
    compute_engulfing,
    compute_ichimoku,
    compute_ma_cross,
    compute_macd,
    compute_rsi,
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
    if band == "upper" or op == "break_above":
        return (close > bb["upper"]).fillna(False)
    return (close < bb["lower"]).fillna(False)


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
}


def evaluate_condition(df: pd.DataFrame, condition: Condition) -> pd.Series:
    """조건 하나를 df 전체 구간에 대해 평가해 불리언 Series를 반환한다."""
    indicator = condition.get("indicator")
    evaluator = INDICATOR_EVALUATORS.get(indicator)
    if evaluator is None:
        raise ValueError(f"지원하지 않는 지표: {indicator!r}")
    return evaluator(df, condition)


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

    1:2:6 단계별(staged) 전략은 별도 simulate_staged_positions()를 쓰므로 여기서 다루지 않는다.
    """
    config = parse_indicator_config(indicator_config)
    if is_expression_config(config):
        from core.expression_engine import evaluate_expression

        return evaluate_expression(df, config["expression"])
    return combine_conditions(df, config)


def generate_positions(df: pd.DataFrame, indicator_config: str | IndicatorConfig) -> pd.Series:
    """조건이 True인 구간을 1(보유), False인 구간을 0(미보유)으로 하는 포지션 Series를 만든다."""
    signal = generate_regime_signal(df, indicator_config)
    return signal.astype(int)


def is_staged_config(indicator_config: str | IndicatorConfig) -> bool:
    """indicator_config가 1:2:6 식 단계별(staged) 전략 스키마인지 판별한다.

    일반 AND/OR 레짐 전략(conditions 키)과 달리 "entry_stages" 키가 있으면 staged 전략으로 본다.
    """
    config = parse_indicator_config(indicator_config)
    return isinstance(config, dict) and "entry_stages" in config


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: Optional[pd.Timestamp]
    entry_price: float
    exit_price: Optional[float]
    return_pct: Optional[float]


def extract_trades(df: pd.DataFrame, position: pd.Series) -> list[Trade]:
    """포지션 시리즈(0/1)에서 개별 매매(진입~청산) 목록을 추출한다.

    실제 체결은 신호가 발생한 다음 거래일 종가에 이루어진다고 가정한다
    (신호 당일 종가는 알 수 없다고 보고 lookahead bias를 피하기 위함).
    마지막까지 포지션이 열려있으면 마지막 거래일 종가로 강제 청산해 미실현 손익을 집계한다.
    """
    close = df["Close"]
    executed_position = position.shift(1).fillna(0).astype(int)

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
            )
        )

    return trades


@dataclass
class StageEvent:
    """1:2:6 식 단계별 전략의 진입/청산 이벤트 로그 (UI 표시/디버깅용)."""

    date: pd.Timestamp
    kind: str  # "entry" | "exit" | "emergency_exit"
    stage: int  # 1-based 단계 번호 (entry_stages/exit_stages 의 인덱스+1)
    weight: float  # 이 이벤트로 늘거나 준 비중 (0~1)
    price: float  # 신호 발생일 종가 (참고용. 실제 체결가는 extract_staged_trades 에서 다음 거래일 종가 사용)


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
            "emergency_exit": {"logic": "AND", "conditions": [...]}   # 선택. 뜨면 단계 무관 즉시 전량 청산
        }

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

    if not entry_defs:
        return pd.Series(0.0, index=df.index), []

    n_entry, n_exit = len(entry_defs), len(exit_defs)
    entry_signals = [combine_conditions(df, d) for d in entry_defs]
    exit_signals = [combine_conditions(df, d) for d in exit_defs]
    emergency_signal = (
        combine_conditions(df, emergency_def) if emergency_def else pd.Series(False, index=df.index)
    )
    entry_weights = [float(d.get("weight", 0)) for d in entry_defs]

    close = df["Close"]
    weight_signal = pd.Series(0.0, index=df.index)
    events: list[StageEvent] = []

    stage_level = 0
    open_tags: dict[int, float] = {}

    for i, day in enumerate(df.index):
        for k in range(1, n_entry + 1):
            if not bool(entry_signals[k - 1].iloc[i]):
                continue
            is_last = k == n_entry
            allowed = (stage_level < k) if is_last else (stage_level == k - 1)
            if allowed and k not in open_tags:
                open_tags[k] = entry_weights[k - 1]
                stage_level = max(stage_level, k)
                events.append(StageEvent(day, "entry", k, entry_weights[k - 1], float(close.iloc[i])))

        if open_tags:
            if emergency_def and bool(emergency_signal.iloc[i]):
                for k, w in sorted(open_tags.items()):
                    events.append(StageEvent(day, "emergency_exit", k, w, float(close.iloc[i])))
                open_tags = {}
            elif n_exit > 0 and bool(exit_signals[n_exit - 1].iloc[i]):
                # 마지막 청산 단계는 태그 인덱스와 무관하게 열려있는 물량을 전부 정리한다.
                for k, w in sorted(open_tags.items()):
                    events.append(StageEvent(day, "exit", k, w, float(close.iloc[i])))
                open_tags = {}
            else:
                for k in range(1, n_exit):
                    if k in open_tags and bool(exit_signals[k - 1].iloc[i]):
                        w = open_tags.pop(k)
                        events.append(StageEvent(day, "exit", k, w, float(close.iloc[i])))

        if not open_tags:
            stage_level = 0

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
        signal = generate_regime_signal(df, indicator_config)
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
