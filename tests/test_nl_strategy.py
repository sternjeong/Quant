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


def test_looks_like_staged_strategy_recognizes_new_bollinger_strategy_keywords():
    """진입≠청산 조건이라 레짐(logic/conditions) 스키마로 표현 불가능한 볼린저 응용 전략들은
    반드시 staged 파서로 라우팅돼야 한다 (없으면 AI가 표현 불가능한 스키마를 억지로 채우게 됨)."""
    assert nl_strategy._looks_like_staged_strategy("볼린저 밴드 스퀴즈 매매 전략입니다") is True
    assert nl_strategy._looks_like_staged_strategy("밴드폭 지표가 하단 기준선 아래로 하락") is True
    assert nl_strategy._looks_like_staged_strategy("상승 다이버전스가 발생했습니다") is True
    assert nl_strategy._looks_like_staged_strategy("쌍바닥형 패턴을 확인합니다") is True
    assert nl_strategy._looks_like_staged_strategy("쌍봉형 패턴이 나오면") is True
    # 단순 골든크로스 설명은 여전히 레짐형으로 남아야 한다(오탐지 방지)
    assert nl_strategy._looks_like_staged_strategy("이동평균 골든크로스가 뜨면 매수합니다") is False


def test_staged_schema_includes_new_bollinger_indicators_and_stop_loss():
    indicator_enum = nl_strategy.STAGE_CONDITION_PROPERTIES["indicator"]["enum"]
    for name in ("bbw_squeeze_release", "percent_b", "mfi", "double_pattern", "rsi_divergence"):
        assert name in indicator_enum

    band_enum = nl_strategy.STAGE_CONDITION_PROPERTIES["band"]["enum"]
    assert "mid" in band_enum

    stop_loss_schema = nl_strategy.STAGED_INDICATOR_CONFIG_SCHEMA["properties"]["indicator_config"]["properties"][
        "stop_loss"
    ]
    assert set(stop_loss_schema["properties"]["source"]["enum"]) == {
        "bollinger_mid",
        "lowest_low",
        "highest_high",
    }
    # stop_loss는 emergency_exit과 마찬가지로 선택 항목이어야 한다(모든 전략에 필요한 게 아니므로)
    required = nl_strategy.STAGED_INDICATOR_CONFIG_SCHEMA["properties"]["indicator_config"]["required"]
    assert "stop_loss" not in required


def test_staged_schema_includes_volume_indicators():
    """core.strategy_engine에는 이미 구현돼 있던 volume_spike/volume_dryup가 해석기 스키마에
    빠져 있던 갭(2026-07-17 발견) — 스크립트에 "거래량 급증/고갈"이 나와도 매핑할 방법이 없었다."""
    indicator_enum = nl_strategy.STAGE_CONDITION_PROPERTIES["indicator"]["enum"]
    assert "volume_spike" in indicator_enum
    assert "volume_dryup" in indicator_enum
    assert "mult" in nl_strategy.STAGE_CONDITION_PROPERTIES
    assert "ratio" in nl_strategy.STAGE_CONDITION_PROPERTIES


def test_split_batch_scripts_separates_on_dash_delimiter():
    text = "스크립트 하나\n---\n스크립트 둘\n----\n스크립트 셋\n"
    assert nl_strategy.split_batch_scripts(text) == ["스크립트 하나", "스크립트 둘", "스크립트 셋"]


def test_split_batch_scripts_single_script_without_delimiter():
    assert nl_strategy.split_batch_scripts("구분선 없는 스크립트 하나") == ["구분선 없는 스크립트 하나"]


def test_split_batch_scripts_drops_empty_segments():
    text = "스크립트 하나\n---\n\n---\n스크립트 둘"
    assert nl_strategy.split_batch_scripts(text) == ["스크립트 하나", "스크립트 둘"]


def test_generate_strategies_from_scripts_continues_after_one_failure(monkeypatch):
    """스크립트 하나의 해석이 실패해도 나머지 스크립트 처리가 이어져야 한다."""

    def fake_interpret(raw_text: str) -> dict:
        if "실패" in raw_text:
            raise RuntimeError("의도된 실패")
        return {
            "name": "정상 전략",
            "description": "설명",
            "indicator_config": {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 30}]},
        }

    def fake_sanity(indicator_config, sample_tickers, start, end):
        return {"passed": True, "total_trades": 10, "avg_excess_return": 1.5}

    monkeypatch.setattr(nl_strategy, "interpret_strategy_text", fake_interpret)
    monkeypatch.setattr(nl_strategy, "_sanity_backtest_config", fake_sanity)
    monkeypatch.setattr(
        "core.strategy_tuning.sample_universe",
        lambda n: __import__("pandas").DataFrame({"ticker": ["AAPL"]}),
    )

    results = nl_strategy.generate_strategies_from_scripts(["실패할 스크립트", "정상 스크립트"])

    assert len(results) == 2
    assert results[0]["ok"] is False
    assert "실패" in results[0]["error"]
    assert results[1]["ok"] is True
    assert results[1]["sanity"]["passed"] is True
