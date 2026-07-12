"""core/expression_engine.py 단위 테스트 (합성 데이터 사용, 네트워크 불필요).

직접 수식 전략 슬롯의 핵심 요구사항 두 가지를 검증한다:
1. 지원되는 변수/함수/연산자로 만든 수식이 core.indicators 의 기존 계산과 일치하는 결과를 낸다.
2. eval() 대신 ast 화이트리스트 인터프리터를 쓰므로 import/속성 접근 등 위험한 구문은 전부 차단된다.
"""

import numpy as np
import pandas as pd
import pytest

from core.expression_engine import ExpressionError, evaluate_expression, validate_syntax
from core.indicators import compute_rsi, sma


def _make_df(n=200, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    returns = rng.normal(0.0003, 0.01, n)
    close = 100 * np.cumprod(1 + returns)
    return pd.DataFrame(
        {
            "Open": close * 0.999,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": rng.integers(1_000, 10_000, n).astype(float),
        },
        index=idx,
    )


def test_simple_comparison_matches_manual_calculation():
    df = _make_df()
    signal = evaluate_expression(df, "close > open")
    assert (signal == (df["Close"] > df["Open"])).all()


def test_sma_function_matches_core_indicators():
    df = _make_df()
    signal = evaluate_expression(df, "close > sma(close, 20)")
    expected = (df["Close"] > sma(df["Close"], 20)).fillna(False)
    assert (signal == expected).all()


def test_rsi_function_matches_core_indicators():
    df = _make_df()
    signal = evaluate_expression(df, "rsi(close, 14) < 30")
    expected = (compute_rsi(df, period=14) < 30).fillna(False)
    assert (signal == expected).all()


def test_and_or_not_combination():
    df = _make_df()
    signal = evaluate_expression(df, "close > open and not (volume < 0)")
    assert (signal == (df["Close"] > df["Open"])).all()


def test_crossover_detects_upward_cross():
    idx = pd.bdate_range("2022-01-03", periods=5)
    df = pd.DataFrame(
        {
            "Open": [1, 1, 1, 1, 1],
            "High": [1, 1, 1, 1, 1],
            "Low": [1, 1, 1, 1, 1],
            "Close": [10, 9, 11, 12, 8],
            "Volume": [1, 1, 1, 1, 1],
        },
        index=idx,
    )
    signal = evaluate_expression(df, "crossover(close, 10)")
    assert list(signal) == [False, False, True, False, False]


def test_crossunder_detects_downward_cross():
    idx = pd.bdate_range("2022-01-03", periods=5)
    df = pd.DataFrame(
        {
            "Open": [1, 1, 1, 1, 1],
            "High": [1, 1, 1, 1, 1],
            "Low": [1, 1, 1, 1, 1],
            "Close": [10, 11, 9, 12, 8],
            "Volume": [1, 1, 1, 1, 1],
        },
        index=idx,
    )
    signal = evaluate_expression(df, "crossunder(close, 10)")
    assert list(signal) == [False, False, True, False, True]


def test_bollinger_and_min_max_functions_run_without_error():
    df = _make_df()
    signal = evaluate_expression(
        df, "close < bb_lower(close, 20, 2) or close > max(bb_upper(close, 20, 2), sma(close, 50))"
    )
    assert signal.dtype == bool


def test_result_dtype_is_bool():
    df = _make_df()
    signal = evaluate_expression(df, "close > sma(close, 20)")
    assert signal.dtype == bool


def test_empty_expression_raises():
    df = _make_df()
    with pytest.raises(ExpressionError):
        evaluate_expression(df, "")


def test_non_boolean_result_raises():
    df = _make_df()
    with pytest.raises(ExpressionError):
        evaluate_expression(df, "close - open")


def test_unknown_variable_raises():
    df = _make_df()
    with pytest.raises(ExpressionError):
        evaluate_expression(df, "foo > 0")


def test_unknown_function_raises():
    df = _make_df()
    with pytest.raises(ExpressionError):
        evaluate_expression(df, "unknown_func(close) > 0")


def test_string_literal_rejected():
    df = _make_df()
    with pytest.raises(ExpressionError):
        evaluate_expression(df, "close > 'oops'")


@pytest.mark.parametrize(
    "malicious_expr",
    [
        "__import__('os').system('echo hi')",
        "close.__class__",
        "[x for x in range(10)]",
        "(lambda: close)()",
        "open()",  # 파이썬 내장 open() 이 아니라 whitelist 밖의 호출이어야 함(우리 open은 변수)
        "close[0]",
        "exec('1')",
    ],
)
def test_dangerous_expressions_are_rejected(malicious_expr):
    df = _make_df()
    with pytest.raises((ExpressionError, SyntaxError)):
        evaluate_expression(df, malicious_expr)


def test_validate_syntax_passes_for_valid_expression():
    validate_syntax("close > sma(close, 20) and rsi(close, 14) < 30")


def test_validate_syntax_raises_for_invalid_expression():
    with pytest.raises(ExpressionError):
        validate_syntax("close > undefined_thing")
