"""직접 수식(커스텀 표현식) 전략 (모듈 A 확장): 지표 토글/자연어 해석으로 표현하기 어려운
조건을 사용자가 파이썬과 비슷한 문법의 불리언 수식으로 직접 입력할 수 있게 한다.

예:
    "close > sma(close, 20) and rsi(close, 14) < 30"
    "crossover(macd_line(close), macd_signal(close)) and close > bb_mid(close, 20)"

파이썬 eval()을 그대로 쓰면 임의 코드 실행(OWASP Top 10 A03: Injection) 위험이 있으므로,
ast 모듈로 수식을 파싱한 뒤 허용된 노드 종류/변수/함수만 재귀적으로 직접 평가하는 화이트리스트
인터프리터를 구현한다. import/속성 접근(attribute)/subscript/lambda/함수 정의 등은 전부 차단된다
— 이 인터프리터가 실제로 실행할 수 있는 것은 아래 VARIABLES/FUNCTIONS 에 등록된 것뿐이다.

core.strategy_engine 이 이해하는 indicator_config 스키마의 세 번째 형태로 취급된다:
    {"expression": "close > sma(close, 20) and rsi(close, 14) < 30"}
(레짐형 "conditions"/1:2:6 단계별 "entry_stages" 와 마찬가지로 core/models.py::Strategy.indicator_config
에 JSON 문자열로 그대로 저장된다.)
"""

from __future__ import annotations

import ast
from typing import Any, Callable

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands
from ta.volume import MFIIndicator


class ExpressionError(ValueError):
    """수식 파싱/평가 실패 시 사용자에게 그대로 보여줄 한국어 메시지를 담는다."""


# ==========================================================================
# 사용 가능한 함수 (전부 pandas Series 또는 스칼라를 받아 Series/스칼라를 반환)
# ==========================================================================

def _sma(series: pd.Series, period: int) -> pd.Series:
    period = int(period)
    return series.rolling(window=period, min_periods=period).mean()


def _ema(series: pd.Series, period: int) -> pd.Series:
    period = int(period)
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    return RSIIndicator(close=series, window=int(period)).rsi()


def _macd_line(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    return MACD(close=series, window_fast=int(fast), window_slow=int(slow), window_sign=int(signal)).macd()


def _macd_signal(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    return MACD(close=series, window_fast=int(fast), window_slow=int(slow), window_sign=int(signal)).macd_signal()


def _macd_hist(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    return MACD(close=series, window_fast=int(fast), window_slow=int(slow), window_sign=int(signal)).macd_diff()


def _bb_upper(series: pd.Series, period: int = 20, std: float = 2.0) -> pd.Series:
    return BollingerBands(close=series, window=int(period), window_dev=float(std)).bollinger_hband()


def _bb_mid(series: pd.Series, period: int = 20, std: float = 2.0) -> pd.Series:
    return BollingerBands(close=series, window=int(period), window_dev=float(std)).bollinger_mavg()


def _bb_lower(series: pd.Series, period: int = 20, std: float = 2.0) -> pd.Series:
    return BollingerBands(close=series, window=int(period), window_dev=float(std)).bollinger_lband()


def _bbw(series: pd.Series, period: int = 20, std: float = 2.0) -> pd.Series:
    """볼린저 밴드폭 = (상단-하단)/중심선. 변동성이 줄면(스퀴즈) 값도 작아진다."""
    bb = BollingerBands(close=series, window=int(period), window_dev=float(std))
    return (bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg()


def _percent_b(series: pd.Series, period: int = 20, std: float = 2.0) -> pd.Series:
    """볼린저 밴드 %B = (종가-하단)/(상단-하단). 1 이상=상단 밖, 0 이하=하단 밖."""
    bb = BollingerBands(close=series, window=int(period), window_dev=float(std))
    return (series - bb.bollinger_lband()) / (bb.bollinger_hband() - bb.bollinger_lband())


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 14) -> pd.Series:
    """MFI(자금흐름지수) — 거래량을 반영한 RSI 격 모멘텀 지표."""
    return MFIIndicator(high=high, low=low, close=close, volume=volume, window=int(period)).money_flow_index()


def _stdev(series: pd.Series, period: int) -> pd.Series:
    period = int(period)
    return series.rolling(window=period, min_periods=period).std()


def _highest(series: pd.Series, period: int) -> pd.Series:
    period = int(period)
    return series.rolling(window=period, min_periods=period).max()


def _lowest(series: pd.Series, period: int) -> pd.Series:
    period = int(period)
    return series.rolling(window=period, min_periods=period).min()


def _as_series(value: "pd.Series | float", like: pd.Series) -> pd.Series:
    return value if isinstance(value, pd.Series) else pd.Series(value, index=like.index)


def _crossover(a: "pd.Series | float", b: "pd.Series | float") -> pd.Series:
    """a가 b를 아래에서 위로 돌파하는 바(bar)에서 True인 이벤트 시리즈."""
    like = a if isinstance(a, pd.Series) else b
    if not isinstance(like, pd.Series):
        raise ExpressionError("crossover()의 인자 중 최소 하나는 시계열(가격/지표)이어야 합니다.")
    a_s, b_s = _as_series(a, like), _as_series(b, like)
    now_above = a_s > b_s
    prev_above = now_above.shift(1, fill_value=False)
    return (now_above & ~prev_above).fillna(False)


def _crossunder(a: "pd.Series | float", b: "pd.Series | float") -> pd.Series:
    """a가 b를 위에서 아래로 이탈하는 바에서 True인 이벤트 시리즈."""
    like = a if isinstance(a, pd.Series) else b
    if not isinstance(like, pd.Series):
        raise ExpressionError("crossunder()의 인자 중 최소 하나는 시계열(가격/지표)이어야 합니다.")
    a_s, b_s = _as_series(a, like), _as_series(b, like)
    now_below = a_s < b_s
    prev_below = now_below.shift(1, fill_value=False)
    return (now_below & ~prev_below).fillna(False)


def _abs(x: "pd.Series | float") -> "pd.Series | float":
    return x.abs() if isinstance(x, pd.Series) else abs(x)


def _min(a: "pd.Series | float", b: "pd.Series | float") -> "pd.Series | float":
    return np.minimum(a, b) if isinstance(a, pd.Series) or isinstance(b, pd.Series) else min(a, b)


def _max(a: "pd.Series | float", b: "pd.Series | float") -> "pd.Series | float":
    return np.maximum(a, b) if isinstance(a, pd.Series) or isinstance(b, pd.Series) else max(a, b)


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "sma": _sma,
    "ema": _ema,
    "rsi": _rsi,
    "macd_line": _macd_line,
    "macd_signal": _macd_signal,
    "macd_hist": _macd_hist,
    "bb_upper": _bb_upper,
    "bb_mid": _bb_mid,
    "bb_lower": _bb_lower,
    "bbw": _bbw,
    "percent_b": _percent_b,
    "mfi": _mfi,
    "stdev": _stdev,
    "highest": _highest,
    "lowest": _lowest,
    "crossover": _crossover,
    "crossunder": _crossunder,
    "abs": _abs,
    "min": _min,
    "max": _max,
}

VARIABLE_COLUMNS: dict[str, str] = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
}

_ALLOWED_COMPARE_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}

_ALLOWED_BINOPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}


class _SafeEvaluator:
    """ast 트리를 화이트리스트 노드만 재귀적으로 직접 평가한다 (eval() 미사용)."""

    def __init__(self, df: pd.DataFrame):
        self._df = df

    def run(self, expression: str) -> Any:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            raise ExpressionError(f"수식 문법 오류: {e.msg}") from e
        return self._visit(tree.body)

    def _visit(self, node: ast.AST) -> Any:
        if isinstance(node, ast.BoolOp):
            values = [self._visit(v) for v in node.values]
            use_and = isinstance(node.op, ast.And)
            result = values[0]
            for v in values[1:]:
                result = (result & v) if use_and else (result | v)
            return result

        if isinstance(node, ast.UnaryOp):
            operand = self._visit(node.operand)
            if isinstance(node.op, ast.Not):
                return ~operand if isinstance(operand, pd.Series) else (not operand)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return operand
            raise ExpressionError("지원하지 않는 단항 연산자입니다.")

        if isinstance(node, ast.BinOp):
            op_fn = _ALLOWED_BINOPS.get(type(node.op))
            if op_fn is None:
                raise ExpressionError("지원하지 않는 산술 연산자입니다 (+, -, *, / 만 가능합니다).")
            return op_fn(self._visit(node.left), self._visit(node.right))

        if isinstance(node, ast.Compare):
            left = self._visit(node.left)
            result = None
            for op, comparator in zip(node.ops, node.comparators):
                op_fn = _ALLOWED_COMPARE_OPS.get(type(op))
                if op_fn is None:
                    raise ExpressionError(
                        "지원하지 않는 비교 연산자입니다 (<, <=, >, >=, ==, != 만 가능합니다)."
                    )
                right = self._visit(comparator)
                piece = op_fn(left, right)
                result = piece if result is None else (result & piece)
                left = right
            return result

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ExpressionError("함수 호출 형태만 지원합니다 (예: sma(close, 20)).")
            func_name = node.func.id
            func = FUNCTIONS.get(func_name)
            if func is None:
                raise ExpressionError(
                    f"알 수 없는 함수 '{func_name}'입니다. 사용 가능한 함수: {', '.join(sorted(FUNCTIONS))}"
                )
            if any(isinstance(a, ast.Starred) for a in node.args):
                raise ExpressionError("가변 인자(*args)는 지원하지 않습니다.")
            args = [self._visit(a) for a in node.args]
            kwargs: dict[str, Any] = {}
            for kw in node.keywords:
                if kw.arg is None:
                    raise ExpressionError("**kwargs 형태는 지원하지 않습니다.")
                kwargs[kw.arg] = self._visit(kw.value)
            try:
                return func(*args, **kwargs)
            except ExpressionError:
                raise
            except TypeError as e:
                raise ExpressionError(f"'{func_name}' 함수의 인자가 올바르지 않습니다: {e}") from e

        if isinstance(node, ast.Name):
            key = node.id.lower()
            column = VARIABLE_COLUMNS.get(key)
            if column is None:
                raise ExpressionError(
                    f"알 수 없는 변수 '{node.id}'입니다. 사용 가능한 변수: {', '.join(sorted(VARIABLE_COLUMNS))}"
                )
            if column not in self._df.columns:
                raise ExpressionError(f"'{column}' 데이터가 없어 '{node.id}'를 사용할 수 없습니다.")
            return self._df[column]

        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or isinstance(node.value, (int, float)):
                return node.value
            raise ExpressionError("문자열/None 등은 수식에 사용할 수 없습니다 (숫자만 가능합니다).")

        raise ExpressionError(f"지원하지 않는 문법입니다 ({type(node).__name__}).")


def evaluate_expression(df: pd.DataFrame, expression: str) -> pd.Series:
    """수식 문자열을 df(OHLCV) 위에서 평가해 불리언 Series(포지션 보유 조건)를 반환한다.

    최상위 결과가 bool 스칼라 또는 bool dtype Series 가 아니면(예: 비교 연산자 없이
    "close - open" 처럼 숫자식만 쓴 경우) ExpressionError 를 던진다.
    """
    if not expression or not expression.strip():
        raise ExpressionError("수식이 비어 있습니다.")

    result = _SafeEvaluator(df).run(expression)

    if isinstance(result, pd.Series) and pd.api.types.is_bool_dtype(result):
        return result.reindex(df.index).fillna(False)
    if isinstance(result, bool):
        return pd.Series(result, index=df.index)

    raise ExpressionError(
        "수식 결과가 참/거짓이 아닙니다. 비교 연산자(>, <, >=, <=, ==, !=)와 and/or로 조건식을 만들어주세요."
    )


_SYNTAX_CHECK_DF: pd.DataFrame | None = None


def _synthetic_ohlcv_df() -> pd.DataFrame:
    """문법 사전 검증용 합성 OHLCV DataFrame (네트워크 없이 빠르게 함수 실행 가능 여부만 확인)."""
    global _SYNTAX_CHECK_DF
    if _SYNTAX_CHECK_DF is not None:
        return _SYNTAX_CHECK_DF
    rng = np.random.default_rng(0)
    n = 300
    idx = pd.bdate_range("2023-01-02", periods=n)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    open_ = close + rng.normal(0, 0.5, n)
    volume = rng.integers(1_000, 10_000, n).astype(float)
    _SYNTAX_CHECK_DF = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=idx
    )
    return _SYNTAX_CHECK_DF


def validate_syntax(expression: str) -> None:
    """실제 종목 데이터 없이 합성 데이터로 수식을 미리 실행해 문법/변수/함수 오류를 빠르게 잡는다.

    성공하면 아무것도 반환하지 않고, 문제가 있으면 ExpressionError 를 던진다
    (호출부는 이를 잡아 st.error 등으로 그대로 보여주면 된다).
    """
    evaluate_expression(_synthetic_ohlcv_df(), expression)
