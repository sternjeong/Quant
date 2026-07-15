"""전략의 지표 조합(indicator_config)을 사람이 읽는 상세 한국어 설명으로 바꾼다.

전략이 "생성/저장되는 시점"에 한 번만 호출해 Strategy.description 에 함께 저장하는 용도다
(core/nl_strategy.py 의 자연어 해석 경로는 이미 파싱과 동시에 description을 만들므로 그대로 두고,
이 모듈은 나머지 저장 경로 — 지표 토글/직접 수식/미세튜닝 결과 — 를 위한 것).

호출부(app/pages/1_백테스팅.py)는 "전략 저장" 버튼 클릭 시 딱 한 번만 explain_strategy()를 불러
description 컬럼에 함께 저장한다. 그 이후로는 DB에 저장된 값을 그대로 읽어 쓸 뿐 다시 생성하지
않는다 — 즉 "설명 페어가 아직 없을 때(=지금 막 생성하는 전략)"만 이 모듈이 호출된다.

레짐(AND/OR)/1:2:6 단계별 전략은 core.strategy_engine.describe_condition()으로 조건별 한국어 문구를
이미 정확하게 만들 수 있으므로, 그 문구들을 근거로 삼아 Gemini에게 "매수/매도 신호를 지어내지 말고"
자연스러운 설명 문단으로 다듬게 한다(환각 방지). 직접 수식(expression) 전략은 임의의 파이썬형 수식이라
결정론적 요약이 불가능해 Gemini에게 수식 자체를 설명하게 한다. 두 경우 모두 GEMINI_API_KEY가 없거나
호출이 실패하면 결정론적 조건 요약(또는 원본 수식)을 그대로 반환한다(오프라인에서도 최소 동작 보장).
"""

from __future__ import annotations

import json
import re

from core import gemini_client
from core.strategy_engine import (
    IndicatorConfig,
    describe_condition,
    is_expression_config,
    is_staged_config,
    parse_indicator_config,
)

_MAX_EXPLANATION_LINES = 5

_POLISH_SYSTEM_PROMPT = """\
당신은 퀀트 애널리스트입니다. 아래에는 이미 정확하게 정리된 매매 전략의 진입/청산 조건 요약과
원본 조건 JSON이 주어집니다. 이를 바탕으로 이 전략이 실제로 어떤 시장 상황을 노리는 전략인지
사람이 한눈에 읽을 수 있도록 한국어로 최대 5줄 이내로 간결하고 깔끔하게 설명하세요.

반드시 지킬 것:
- 최대 5줄(문장)을 넘기지 말 것 — 장황한 서술 대신 핵심만 압축할 것.
- 주어진 조건 요약에 없는 새로운 지표/조건을 지어내지 말 것.
- 조건 요약에 나온 지표/파라미터 숫자를 임의로 바꾸지 말 것.
- 조건을 빠짐없이 반영하되, 필요하면 한 줄에 여러 조건을 압축해서라도 5줄을 넘기지 말 것.
- 수식/조건 문구를 그대로 반복하지 말고, 그것이 "무엇을 의미하는지"(예: 상승 추세 전환 후 조정 시
  진입하는 눌림목 전략 등)를 간단히 풀어서 설명할 것.
"""

_EXPRESSION_SYSTEM_PROMPT = """\
당신은 퀀트 애널리스트입니다. 사용자가 파이썬과 비슷한 문법으로 작성한 주식 매매 조건 수식을 보고,
이 수식이 실제로 어떤 상황에서 매수 신호(True)가 되는지 한국어로 최대 5줄 이내로 간결하고 깔끔하게
설명하세요. 전문 용어(이동평균, RSI 등)가 나오면 짧게 풀어 설명하되 장황하게 늘리지 말 것. 수식
자체를 그대로 반복하지 말고 "무엇을 의미하는지"에 집중하세요.
"""


def _clip_to_max_lines(text: str, max_lines: int = _MAX_EXPLANATION_LINES) -> str:
    """설명이 항상 최대 max_lines줄(또는 문장) 이내로 끝나도록 코드에서 한 번 더 강제한다.

    프롬프트 지시만으로는 AI가 매번 지키지는 않는다는 것이 이 프로젝트에서 이미 실증됨(진입=청산
    자기모순 버그 때 self.nl_strategy가 프롬프트 경고만으로는 부족해 자기교정 재시도를 추가했던 것과
    같은 이유) — 그래서 줄 수 제한은 프롬프트뿐 아니라 여기서도 한 번 더 강제한다. 개행이 있는
    응답(결정론적 fallback 등)은 줄 단위로, 개행 없는 산문형 응답(Gemini가 흔히 반환하는 형태)은
    문장 단위로 잘라 5개까지만 남긴다.
    """
    text = text.strip()
    if not text:
        return text
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        return "\n".join(lines[:max_lines])
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) <= max_lines:
        return text
    return " ".join(sentences[:max_lines])


def describe_regime_config(config: IndicatorConfig) -> str:
    """레짐(AND/OR) 전략의 조건들을 결정론적인 한국어 문단으로 요약한다."""
    logic = str(config.get("logic", "AND")).upper()
    conds = [describe_condition(c) for c in config.get("conditions", [])]
    if not conds:
        return "조건이 설정되지 않은 전략입니다."
    joiner = " 그리고 " if logic == "AND" else " 또는 "
    cond_text = joiner.join(conds)
    all_or_any = "모두" if logic == "AND" else "하나라도"
    return (
        f"다음 조건이 {all_or_any} 충족되는 동안 매수 포지션을 보유합니다: {cond_text}. "
        f"조건이 더 이상 충족되지 않으면 청산합니다."
    )


def _describe_stage_compact(stage: dict) -> str:
    weight_pct = f"{float(stage.get('weight', 0)) * 100:.0f}%"
    logic = str(stage.get("logic", "AND")).upper()
    joiner = "+" if logic == "AND" else "/"
    conds = [describe_condition(c) for c in stage.get("conditions", [])]
    cond_text = joiner.join(conds) if conds else "조건 없음"
    return f"{cond_text}({weight_pct})"


def describe_staged_config(config: IndicatorConfig) -> str:
    """1:2:6 식 단계별(staged) 전략을 결정론적인 한국어 요약으로 만든다.

    최종 설명이 5줄 이내로 나오도록(explain_strategy의 줄 수 제약과 일치), 단계 수와 무관하게
    방향(진입/청산)당 한 줄로 압축한다 — 예전에는 단계마다 줄을 하나씩 써서 3단계+3단계 전략이면
    그것만으로 벌써 6줄이 넘었다.
    """
    entry_stages = config.get("entry_stages", [])
    exit_stages = config.get("exit_stages", [])
    lines = ["신호가 겹칠수록 비중을 단계적으로 늘려가며 분할 진입/청산합니다."]
    if entry_stages:
        lines.append("진입: " + " → ".join(_describe_stage_compact(s) for s in entry_stages))
    if exit_stages:
        exit_text = " → ".join(_describe_stage_compact(s) for s in exit_stages)
        lines.append(f"청산: {exit_text} (마지막 단계 도달 시 잔량 전량 청산)")
    emergency = config.get("emergency_exit")
    if emergency:
        logic = str(emergency.get("logic", "AND")).upper()
        joiner = "+" if logic == "AND" else "/"
        conds = [describe_condition(c) for c in emergency.get("conditions", [])]
        lines.append(f"긴급청산: {joiner.join(conds)} 시 단계 무관 즉시 전량 청산")
    return "\n".join(lines)


def _fallback_expression_description(expression: str) -> str:
    return (
        "[자동 설명 생성 실패 - GEMINI_API_KEY 미설정 또는 API 오류] 아래 수식이 True가 되는 날 매수 "
        f"포지션에 진입하고, False가 되면 청산합니다: {expression}"
    )


def explain_strategy(indicator_config: str | IndicatorConfig) -> str:
    """indicator_config를 보고 상세한 한국어 설명을 생성한다.

    전략을 라이브러리에 "저장"하는 시점에 한 번만 호출할 것 — 이미 저장된 전략을 불러오거나
    반복해서 백테스트를 돌릴 때는 DB에 저장된 description을 그대로 재사용하고 이 함수를 다시
    호출하지 않는다.
    """
    config = parse_indicator_config(indicator_config)

    if is_expression_config(config):
        expression = config.get("expression", "")
        base_summary: str | None = None
        gemini_prompt = expression
        system_prompt = _EXPRESSION_SYSTEM_PROMPT
        fallback = _fallback_expression_description(expression)
    else:
        base_summary = (
            describe_staged_config(config) if is_staged_config(config) else describe_regime_config(config)
        )
        gemini_prompt = f"[조건 요약]\n{base_summary}\n\n[원본 조건 JSON]\n{json.dumps(config, ensure_ascii=False)}"
        system_prompt = _POLISH_SYSTEM_PROMPT
        fallback = base_summary

    if not gemini_client.has_api_key():
        return _clip_to_max_lines(fallback)

    try:
        response = gemini_client.generate_content(
            gemini_client.LIGHT_TASK_MODELS, gemini_prompt, system_instruction=system_prompt
        )
        text = (response.text or "").strip()
        return _clip_to_max_lines(text) if text else _clip_to_max_lines(fallback)
    except Exception:
        return _clip_to_max_lines(fallback)
