"""core/nl_strategy.py 단위 테스트 — staged(1:2:6) 전략의 진입/청산 자기모순 자동교정 로직."""

import json

import core.nl_strategy as nl_strategy


class _FakeResponse:
    def __init__(self, payload: dict):
        self.text = json.dumps(payload, ensure_ascii=False)


def _staged_payload(marker: str) -> dict:
    return {
        "name": f"전략-{marker}",
        "description": f"설명-{marker}",
        "indicator_config": {
            "entry_stages": [
                {"weight": 0.1, "logic": "AND", "conditions": [{"indicator": "rsi_cross", "level": 30, "direction": "up"}]}
            ],
            "exit_stages": [
                {"weight": 0.1, "logic": "AND", "conditions": [{"indicator": "rsi_cross", "level": 70, "direction": "down"}]}
            ],
        },
    }


def test_no_api_key_returns_template_with_empty_warnings(monkeypatch):
    monkeypatch.setattr(nl_strategy.gemini_client, "has_api_key", lambda: False)

    result = nl_strategy._interpret_staged_strategy_text("아무 텍스트")

    assert result["health_warnings"] == []
    assert "entry_stages" in result["indicator_config"]


def test_ai_call_failure_falls_back_with_empty_warnings(monkeypatch):
    monkeypatch.setattr(nl_strategy.gemini_client, "has_api_key", lambda: True)

    def _raise(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(nl_strategy.gemini_client, "generate_content", _raise)

    result = nl_strategy._interpret_staged_strategy_text("아무 텍스트")

    assert result["health_warnings"] == []
    assert "[AI 호출 실패:" in result["description"]


def test_clean_result_on_first_attempt_does_not_retry(monkeypatch):
    monkeypatch.setattr(nl_strategy.gemini_client, "has_api_key", lambda: True)
    calls = []

    def _fake_generate(**kwargs):
        calls.append(kwargs)
        return _FakeResponse(_staged_payload("ok"))

    monkeypatch.setattr(nl_strategy.gemini_client, "generate_content", _fake_generate)
    monkeypatch.setattr(nl_strategy, "_check_entry_exit_overlap", lambda config: [])

    result = nl_strategy._interpret_staged_strategy_text("전략 설명")

    assert len(calls) == 1
    assert result["name"] == "전략-ok"
    assert result["health_warnings"] == []


def test_self_correction_retry_succeeds_on_second_attempt(monkeypatch):
    monkeypatch.setattr(nl_strategy.gemini_client, "has_api_key", lambda: True)
    responses = [_staged_payload("bad"), _staged_payload("good")]
    calls = []

    def _fake_generate(**kwargs):
        calls.append(kwargs["contents"])
        return _FakeResponse(responses[len(calls) - 1])

    monkeypatch.setattr(nl_strategy.gemini_client, "generate_content", _fake_generate)

    # 첫 응답만 자기모순 경고, 두 번째 응답은 정상으로 판정
    call_count = {"n": 0}

    def _check(config):
        call_count["n"] += 1
        return ["진입일=청산일이 100%로 나왔습니다"] if call_count["n"] == 1 else []

    monkeypatch.setattr(nl_strategy, "_check_entry_exit_overlap", _check)

    result = nl_strategy._interpret_staged_strategy_text("전략 설명")

    assert len(calls) == 2
    assert "직전 시도 검증 실패" in calls[1]
    assert "진입일=청산일이 100%로 나왔습니다" in calls[1]
    assert result["name"] == "전략-good"
    assert result["health_warnings"] == []


def test_self_correction_exhausted_surfaces_warnings(monkeypatch):
    monkeypatch.setattr(nl_strategy.gemini_client, "has_api_key", lambda: True)

    def _fake_generate(**kwargs):
        return _FakeResponse(_staged_payload("still-bad"))

    monkeypatch.setattr(nl_strategy.gemini_client, "generate_content", _fake_generate)
    monkeypatch.setattr(
        nl_strategy, "_check_entry_exit_overlap", lambda config: ["진입일=청산일이 100%로 나왔습니다"]
    )

    result = nl_strategy._interpret_staged_strategy_text("전략 설명")

    assert result["health_warnings"] == ["진입일=청산일이 100%로 나왔습니다"]
    assert result["description"].startswith("⚠️ 자동 정합성 검증에 실패했습니다")


def test_check_entry_exit_overlap_swallows_exceptions(monkeypatch):
    def _raise(config):
        raise RuntimeError("데이터 조회 실패")

    monkeypatch.setattr(nl_strategy, "diagnose_strategy_health", _raise, raising=False)
    import core.backtest_engine as backtest_engine

    monkeypatch.setattr(backtest_engine, "diagnose_strategy_health", _raise)

    assert nl_strategy._check_entry_exit_overlap({"entry_stages": [], "exit_stages": []}) == []
