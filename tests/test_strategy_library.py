"""core/strategy_library.py 의 순수 함수(DB 접근 없음) 단위 테스트.

detect_strategy_type/validate_indicator_config 가 레짐(regime)/1:2:6 단계별(staged)/
직접 수식(expression) 세 스키마를 모두 올바르게 판별·검증하는지 확인한다.
"""

import json

import pytest

from core.strategy_library import detect_strategy_type, validate_indicator_config


def test_detect_strategy_type_regime():
    config = {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 30}]}
    assert detect_strategy_type(json.dumps(config)) == "regime"


def test_detect_strategy_type_staged():
    config = {"entry_stages": [{"weight": 1.0, "logic": "AND", "conditions": [{"indicator": "rsi"}]}], "exit_stages": []}
    assert detect_strategy_type(json.dumps(config)) == "staged"


def test_detect_strategy_type_expression():
    config = {"expression": "close > sma(close, 20)"}
    assert detect_strategy_type(json.dumps(config)) == "expression"


def test_detect_strategy_type_invalid_json_falls_back_to_regime():
    assert detect_strategy_type("not json") == "regime"


def test_validate_indicator_config_accepts_valid_expression():
    parsed = validate_indicator_config(json.dumps({"expression": "close > sma(close, 20)"}))
    assert parsed["expression"] == "close > sma(close, 20)"


def test_validate_indicator_config_rejects_empty_expression():
    with pytest.raises(ValueError):
        validate_indicator_config(json.dumps({"expression": "   "}))


def test_validate_indicator_config_rejects_bad_expression_syntax():
    with pytest.raises(ValueError):
        validate_indicator_config(json.dumps({"expression": "close > undefined_variable"}))


def test_validate_indicator_config_accepts_valid_regime():
    parsed = validate_indicator_config(
        json.dumps({"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14}]})
    )
    assert parsed["logic"] == "AND"


def test_validate_indicator_config_rejects_missing_conditions():
    with pytest.raises(ValueError):
        validate_indicator_config(json.dumps({"logic": "AND"}))
