"""core/strategy_explainer.py 단위 테스트.

레짐/1:2:6 단계별 전략은 결정론적 요약(describe_condition 기반)이 항상 정확해야 하고,
Gemini 키가 없거나 호출이 실패해도 그 결정론적 요약이 fallback으로 그대로 반환되어야 한다.
직접 수식 전략은 결정론적 요약이 불가능하므로 Gemini 실패 시 원본 수식을 담은 안내 문구로
대체된다.
"""

import core.strategy_explainer as strategy_explainer


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


def test_describe_regime_config_and_condition():
    config = {
        "logic": "AND",
        "conditions": [
            {"indicator": "ma_cross", "short": 20, "long": 60, "type": "golden"},
            {"indicator": "rsi", "period": 14, "op": "<", "value": 30},
        ],
    }

    text = strategy_explainer.describe_regime_config(config)

    assert "MA20/MA60 골든크로스 국면" in text
    assert "RSI(14) < 30" in text
    assert "그리고" in text


def test_describe_regime_config_or_logic():
    config = {"logic": "OR", "conditions": [{"indicator": "rsi", "period": 14, "op": ">", "value": 70}]}

    text = strategy_explainer.describe_regime_config(config)

    assert "하나라도" in text


def test_describe_regime_config_empty_conditions():
    assert "조건이 설정되지 않은" in strategy_explainer.describe_regime_config({"logic": "AND", "conditions": []})


def test_describe_staged_config_includes_stage_weights_and_emergency_exit():
    config = {
        "entry_stages": [
            {"weight": 0.1, "logic": "AND", "conditions": [{"indicator": "rsi_cross", "level": 30, "direction": "up"}]},
            {"weight": 0.9, "logic": "AND", "conditions": [{"indicator": "macd_cross", "direction": "golden"}]},
        ],
        "exit_stages": [
            {"weight": 1.0, "logic": "AND", "conditions": [{"indicator": "macd_cross", "direction": "dead"}]},
        ],
        "emergency_exit": {
            "logic": "AND",
            "conditions": [{"indicator": "rsi_cross", "level": 50, "direction": "down"}],
        },
    }

    text = strategy_explainer.describe_staged_config(config)

    assert "10%" in text
    assert "90%" in text
    assert "잔량" in text
    assert "긴급청산" in text
    assert len(text.splitlines()) <= strategy_explainer._MAX_EXPLANATION_LINES


def test_explain_strategy_no_api_key_returns_deterministic_summary_for_regime(monkeypatch):
    monkeypatch.setattr(strategy_explainer.gemini_client, "has_api_key", lambda: False)
    config = {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 30}]}

    result = strategy_explainer.explain_strategy(config)

    assert result == strategy_explainer.describe_regime_config(config)


def test_explain_strategy_no_api_key_returns_placeholder_for_expression(monkeypatch):
    monkeypatch.setattr(strategy_explainer.gemini_client, "has_api_key", lambda: False)
    config = {"expression": "close > sma(close, 20)"}

    result = strategy_explainer.explain_strategy(config)

    assert "close > sma(close, 20)" in result
    assert "GEMINI_API_KEY 미설정" in result


def test_explain_strategy_uses_gemini_text_when_available(monkeypatch):
    monkeypatch.setattr(strategy_explainer.gemini_client, "has_api_key", lambda: True)
    monkeypatch.setattr(
        strategy_explainer.gemini_client,
        "generate_content",
        lambda *a, **k: _FakeResponse("이 전략은 눌림목 매수 전략입니다."),
    )
    config = {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 30}]}

    result = strategy_explainer.explain_strategy(config)

    assert result == "이 전략은 눌림목 매수 전략입니다."


def test_explain_strategy_falls_back_when_gemini_raises(monkeypatch):
    monkeypatch.setattr(strategy_explainer.gemini_client, "has_api_key", lambda: True)

    def _raise(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(strategy_explainer.gemini_client, "generate_content", _raise)
    config = {"logic": "OR", "conditions": [{"indicator": "bollinger", "period": 20, "band": "lower", "op": "break_below"}]}

    result = strategy_explainer.explain_strategy(config)

    assert result == strategy_explainer.describe_regime_config(config)


def test_explain_strategy_falls_back_when_gemini_returns_empty_text(monkeypatch):
    monkeypatch.setattr(strategy_explainer.gemini_client, "has_api_key", lambda: True)
    monkeypatch.setattr(
        strategy_explainer.gemini_client, "generate_content", lambda *a, **k: _FakeResponse("   ")
    )
    config = {"expression": "rsi(close, 14) < 30"}

    result = strategy_explainer.explain_strategy(config)

    assert "rsi(close, 14) < 30" in result


def test_explain_strategy_accepts_json_string_input(monkeypatch):
    monkeypatch.setattr(strategy_explainer.gemini_client, "has_api_key", lambda: False)

    result = strategy_explainer.explain_strategy(
        '{"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 30}]}'
    )

    assert "RSI(14) < 30" in result


def test_explain_strategy_clips_multiline_gemini_response_to_five_lines(monkeypatch):
    monkeypatch.setattr(strategy_explainer.gemini_client, "has_api_key", lambda: True)
    long_text = "\n".join(f"{i}번째 줄입니다." for i in range(1, 9))
    monkeypatch.setattr(
        strategy_explainer.gemini_client, "generate_content", lambda *a, **k: _FakeResponse(long_text)
    )
    config = {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 30}]}

    result = strategy_explainer.explain_strategy(config)

    assert len(result.splitlines()) <= strategy_explainer._MAX_EXPLANATION_LINES
    assert "1번째 줄입니다." in result
    assert "8번째 줄입니다." not in result


def test_explain_strategy_clips_prose_response_by_sentence_count(monkeypatch):
    monkeypatch.setattr(strategy_explainer.gemini_client, "has_api_key", lambda: True)
    prose = " ".join(f"문장{i}입니다." for i in range(1, 9))
    monkeypatch.setattr(
        strategy_explainer.gemini_client, "generate_content", lambda *a, **k: _FakeResponse(prose)
    )
    config = {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 30}]}

    result = strategy_explainer.explain_strategy(config)

    assert "문장1입니다." in result
    assert "문장8입니다." not in result
