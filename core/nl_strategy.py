"""자연어 전략 등록 (모듈 A): 유튜버 스크립트 등 자연어 설명을 지표 조합 JSON으로 해석.

Gemini API(GEMINI_API_KEY)가 설정되어 있으면 이를 사용해 텍스트를 해석하고,
키가 없거나 호출에 실패하면 간단한 키워드 기반 규칙으로 대체(fallback)한다
(오프라인/무료 환경에서도 최소한의 기능은 동작하도록 하기 위함).

core.strategy_engine 이 이해하는 indicator_config 스키마로 변환하는 것이 목표.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from core import gemini_client

INDICATOR_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "전략에 어울리는 짧은 한국어 이름 (예: '골든크로스+RSI 눌림목')",
        },
        "description": {
            "type": "string",
            "description": "이 전략이 어떤 조건인지에 대한 한국어 설명 (사용자에게 보여줄 해석 결과)",
        },
        "indicator_config": {
            "type": "object",
            "properties": {
                "logic": {"type": "string", "enum": ["AND", "OR"]},
                "conditions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "indicator": {
                                "type": "string",
                                "enum": ["ma_cross", "rsi", "bollinger", "engulfing"],
                            },
                            "short": {"type": "integer"},
                            "long": {"type": "integer"},
                            "ma_type": {"type": "string", "enum": ["sma", "ema"]},
                            "type": {"type": "string", "enum": ["golden", "dead"]},
                            "period": {"type": "integer"},
                            "op": {
                                "type": "string",
                                "enum": ["<", "<=", ">", ">=", "break_above", "break_below"],
                            },
                            "value": {"type": "number"},
                            "std_dev": {"type": "number"},
                            "band": {"type": "string", "enum": ["upper", "lower"]},
                            "direction": {
                                "type": "string",
                                "enum": ["bullish", "bearish"],
                                "description": "engulfing 전용. 상승/하락 인걸 캔들",
                            },
                        },
                        "required": ["indicator"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["logic", "conditions"],
            "additionalProperties": False,
        },
    },
    "required": ["name", "description", "indicator_config"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
당신은 주식 매매 전략을 분석하는 퀀트 애널리스트입니다.
사용자가 유튜브 등에서 본 매매 전략 설명(자연어)을 붙여넣으면, 이를 아래 3개 지표의 조합으로 해석해서
JSON으로 반환하세요.

지원 지표:
- ma_cross: 이동평균 교차. 파라미터: short(단기기간), long(장기기간), ma_type("sma"|"ema", 기본 sma),
  type("golden"=단기가 장기 위에 있는 상승 국면, "dead"=단기가 장기 아래인 하락 국면)
- rsi: RSI 과매수/과매도. 파라미터: period(기본 14), op("<","<=",">",">="), value(기준값, 0~100)
- bollinger: 볼린저밴드 이탈. 파라미터: period(기본 20), std_dev(기본 2.0), band("upper"|"lower"),
  op("break_above"|"break_below")
- engulfing: 상승/하락 인걸(장악형) 캔들 패턴 이벤트(1회성). direction="bullish"(상승 인걸)|
  "bearish"(하락 인걸). "장악형", "인걸 캔들", "감싸는 캔들" 등의 표현이 나오면 이 지표를 쓴다.

여러 조건은 logic("AND" 또는 "OR")으로 결합합니다.
텍스트에서 언급되지 않은 구체적인 숫자(기간 등)는 널리 쓰이는 기본값(단기 20/장기 60, RSI 14,
과매도 30/과매수 70, 볼린저 20기간/2표준편차)을 사용하세요.
전략명은 핵심 조건을 조합해 간결하게 한국어로 생성하세요 (예: "골든크로스+RSI 눌림목").
"""

# ==========================================================================
# 1:2:6 식 단계별(staged) 전략 스키마: 후지모토 시게루류처럼 신호가 겹칠 때마다
# 비중을 늘려가며 분할 진입/청산하는 고급 전략용. 일반 레짐(logic/conditions) 스키마로는
# 표현할 수 없는 "단계별 비중 배분"을 지원한다 (core.strategy_engine.simulate_staged_positions 참고).
# ==========================================================================

STAGE_CONDITION_PROPERTIES: dict[str, Any] = {
    "indicator": {
        "type": "string",
        "enum": [
            "ma_cross",
            "rsi",
            "bollinger",
            "rsi_cross",
            "macd_cross",
            "macd_level",
            "ichimoku_tk_state",
            "ichimoku_tk_cross",
            "ichimoku_cloud_break",
            "ichimoku_cloud_state",
            "ichimoku_chikou_state",
            "engulfing",
            "bbw_squeeze_release",
            "percent_b",
            "mfi",
            "double_pattern",
            "rsi_divergence",
        ],
    },
    "short": {"type": "integer"},
    "long": {"type": "integer"},
    "ma_type": {"type": "string", "enum": ["sma", "ema"]},
    "type": {"type": "string", "enum": ["golden", "dead"]},
    "period": {"type": "integer"},
    "op": {"type": "string", "enum": ["<", "<=", ">", ">=", "break_above", "break_below"]},
    "value": {"type": "number"},
    "std_dev": {"type": "number"},
    "band": {"type": "string", "enum": ["upper", "lower", "mid"]},
    "level": {"type": "number", "description": "rsi_cross 의 기준 레벨 (예: 30, 50, 70)"},
    "direction": {
        "type": "string",
        "enum": ["up", "down", "golden", "dead", "above", "below", "bullish", "bearish"],
        "description": "이벤트/국면의 방향. rsi_cross·ichimoku_cloud_break/chikou_state는 up|down, "
        "macd_cross·ichimoku_tk_state/tk_cross는 golden|dead, ichimoku_cloud_state는 above|below, "
        "engulfing·double_pattern·rsi_divergence는 bullish|bearish",
    },
    "fast": {"type": "integer", "description": "MACD 단기 EMA 기간 (기본 12)"},
    "slow": {"type": "integer", "description": "MACD 장기 EMA 기간 (기본 26)"},
    "signal": {"type": "integer", "description": "MACD 시그널선 기간 (기본 9)"},
    "zone": {
        "type": "string",
        "enum": ["any", "below_zero", "above_zero"],
        "description": "macd_cross 가 발생한 위치를 0선 기준으로 추가 제한 (기본 any)",
    },
    "source": {"type": "string", "enum": ["macd", "hist"], "description": "macd_level 이 비교할 값"},
    "tenkan_len": {"type": "integer", "description": "일목균형표 전환선 기간 (기본 9)"},
    "kijun_len": {"type": "integer", "description": "일목균형표 기준선 기간 (기본 26)"},
    "span_b_len": {"type": "integer", "description": "일목균형표 선행스팬B 기간 (기본 52)"},
    "displacement": {"type": "integer", "description": "일목균형표 구름대/후행스팬 이동 기간 (기본 26)"},
    "threshold": {"type": "number", "description": "bbw_squeeze_release의 스퀴즈 판정 기준 밴드폭 (기본 0.1, 종목마다 다름)"},
    "lookback": {"type": "integer", "description": "bbw_squeeze_release가 최근 스퀴즈 여부를 확인하는 봉 수 (기본 20)"},
    "hold_bars": {"type": "integer", "description": "bbw_squeeze_release 이벤트가 유지되는 봉 수 (기본 3)"},
    "band_period": {"type": "integer", "description": "double_pattern/rsi_divergence의 볼린저/중심선 기간 (기본 20)"},
    "band_std": {"type": "number", "description": "double_pattern의 볼린저 표준편차 배수 (기본 2.0)"},
    "pivot_lookback": {"type": "integer", "description": "double_pattern/rsi_divergence의 스윙 고점/저점 확정 좌우 봉 수 (기본 5)"},
    "pattern_window": {"type": "integer", "description": "double_pattern/rsi_divergence에서 패턴 성립~확인 돌파까지 허용 봉 수 (기본 40)"},
    "volume_mult": {"type": "number", "description": "double_pattern 확인 돌파 시 요구되는 평균 거래량 대비 배수 (기본 1.5)"},
    "rsi_period": {"type": "integer", "description": "rsi_divergence가 사용하는 RSI 기간 (기본 14)"},
}

STAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "weight": {
            "type": "number",
            "description": "이 단계에서 새로 투입/청산하는 비중 (0~1, 예: 0.1=10%). 보통 1:2:6 비율(0.1/0.2/0.6)을 쓴다",
        },
        "logic": {"type": "string", "enum": ["AND", "OR"]},
        "conditions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": STAGE_CONDITION_PROPERTIES,
                "required": ["indicator"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["weight", "logic", "conditions"],
    "additionalProperties": False,
}

STAGED_INDICATOR_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "전략에 어울리는 짧은 한국어 이름"},
        "description": {"type": "string", "description": "이 전략이 어떤 조건인지에 대한 한국어 설명"},
        "indicator_config": {
            "type": "object",
            "properties": {
                "entry_stages": {"type": "array", "minItems": 1, "items": STAGE_SCHEMA},
                "exit_stages": {"type": "array", "minItems": 1, "items": STAGE_SCHEMA},
                "emergency_exit": {
                    "type": "object",
                    "properties": {
                        "logic": {"type": "string", "enum": ["AND", "OR"]},
                        "conditions": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": STAGE_CONDITION_PROPERTIES,
                                "required": ["indicator"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["logic", "conditions"],
                    "additionalProperties": False,
                },
                "stop_loss": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["bollinger_mid", "lowest_low", "highest_high"],
                            "description": "손절 레벨의 기준. bollinger_mid=진입 시점 볼린저 중심선 "
                            "가격, lowest_low=진입 시점 기준 최근 period봉 중 최저 저가, "
                            "highest_high=최근 period봉 중 최고 고가(숏 방향 참고용, 이 엔진은 "
                            "롱온리라 실제로는 거의 안 씀)",
                        },
                        "period": {"type": "integer", "description": "기준 계산 기간 (기본 20)"},
                        "std_dev": {"type": "number", "description": "bollinger_mid일 때 표준편차 배수 (기본 2.0)"},
                    },
                    "required": ["source"],
                    "additionalProperties": False,
                },
            },
            "required": ["entry_stages", "exit_stages"],
            "additionalProperties": False,
        },
    },
    "required": ["name", "description", "indicator_config"],
    "additionalProperties": False,
}

STAGED_SYSTEM_PROMPT = """\
당신은 주식 매매 전략을 분석하는 퀀트 애널리스트입니다.
사용자가 붙여넣은 매매 전략 설명은 "신호가 여러 개 겹칠 때마다 비중을 단계적으로 늘려가며
분할 진입/청산"하는 고급(staged) 전략입니다 (예: 일본 투자자 후지모토 시게루의 1:2:6 매매법 —
RSI 신호 하나로는 10%만 정찰병 진입, MACD까지 겹치면 20% 추가, 일목균형표 구름대까지 뚫으며
완전히 안착(삼역호전)하면 나머지 60%를 크게 진입. 청산도 같은 순서로 단계적으로 비중을 던다).

아래 스키마에 맞는 JSON으로 반환하세요:
- indicator_config.entry_stages: 진입 단계 배열. 각 단계는 weight(이 단계에서 늘어나는 비중, 보통
  1:2:6 비율인 0.1/0.2/0.6), logic("AND"/"OR"), conditions(아래 지표 조합) 을 가진다.
  마지막 단계는 이전 단계를 거치지 않고 신호가 한번에 강하게 뜨면 곧바로 진입할 수 있다
  (예: 삼역호전처럼 강한 확인 신호).
- indicator_config.exit_stages: 청산 단계 배열 (entry_stages와 동일한 형식). 각 단계는 그에
  대응하는 진입 비중만 개별적으로 정리하며, 마지막 청산 단계가 뜨면 잔량을 전부 정리한다.
- indicator_config.emergency_exit: 설명에 "여러 청산 신호가 동시에 뜨면/겹치면 즉시 전량 청산"
  같은 문구가 조금이라도 있으면 반드시 채워야 한다(생략 금지). 해당되는 청산 조건들을 그대로
  conditions에 넣고 logic="AND"로 묶는다. 이게 없으면 잔량이 마지막 청산 단계까지 계속 보유되어
  버려, 설명된 "동시 신호 시 즉시 청산" 동작이 재현되지 않는다.
- indicator_config.stop_loss: 설명에 "손절선은 진입 시점의 ~"처럼 **진입한 순간의 가격 수준을
  기준으로 고정되는** 손절을 언급하면 채운다(예: "진입 시점 중심선 가격대 아래", "이전 저점/고점
  아래"). source="bollinger_mid"(중심선)|"lowest_low"(최근 저점, 롱 진입용)|"highest_high"(최근
  고점, 숏 방향 참고용)를 상황에 맞게 고르고 period를 지정한다. 이 손절은 진입 그 순간의 값을
  스냅샷해 고정하는 것이지, 매일 다시 계산되는 이동 지표가 아니다 — 그런 "고정 레벨" 손절이 설명에
  없으면 stop_loss를 채우지 말고 생략한다(추측으로 넣지 말 것).

한 단계(entry_stages/exit_stages/emergency_exit 각 원소)의 조건 여러 개가 "동시에"/"함께"/"~이면서"
확인되어야 한다고 설명돼 있으면(예: "MACD 골든크로스가 뜨고 동시에 RSI가 30 위"), 그 조건들을 절대
누락하지 말고 conditions 배열에 전부 넣어 logic="AND"로 묶어라. 한 조건이라도 빠뜨리면 안 된다.

**중요 — 청산 조건이 진입 조건보다 항상 더 쉽게 만족되면 안 된다.** 예를 들어 진입 조건이 "종가가
볼린저 밴드 하단보다 낮다"인데 청산/emergency_exit 조건을 "종가가 20일 이동평균(중심선)보다
낮다"로 만들면, 밴드 하단은 정의상 항상 중심선보다 낮으므로 진입하는 바로 그 날 청산 조건도 항상
동시에 참이 되어 포지션이 단 하루도 유지되지 못한다(수익률이 항상 0%가 됨). 청산 조건은 반드시
진입 조건보다 "더 강한 반전"을 요구해야 한다 — 진입이 하단 이탈이면 청산은 상단 돌파나 반대 방향
이벤트(데드크로스 등)처럼 진입 조건과 겹치지 않는 조건을 골라라.

사용 가능한 지표(각 condition의 "indicator" 필드):
- ma_cross / rsi / bollinger: 기존 레짐형 지표 (기존과 동일한 파라미터)
- rsi_cross: RSI가 특정 level을 돌파하는 "이벤트". direction="up"(상향 돌파)|"down"(하향 돌파),
  period(기본14), level(기본30)
- macd_cross: MACD선-시그널선 골든/데드 크로스 이벤트. direction="golden"|"dead",
  zone="any"|"below_zero"|"above_zero" (0선 아래/위에서 발생한 크로스만 인정),
  fast(12)/slow(26)/signal(9)
- macd_level: MACD선(또는 히스토그램 source="hist") 값 자체를 비교하는 레벨 조건. op, value
- ichimoku_tk_state: 전환선-기준선의 상대적 위치(국면, 레벨). direction="golden"(전환선>기준선)|"dead"
- ichimoku_tk_cross: 전환선이 기준선을 돌파하는 이벤트. direction="golden"|"dead"
- ichimoku_cloud_break: 종가가 구름대 상단/하단을 "돌파/이탈하는 그 순간"(1회성 이벤트). direction="up"|"down"
- ichimoku_cloud_state: 종가가 구름대 위/아래에 "계속 머물러 있는 국면"(지속 상태, 매일 True/False).
  direction="above"|"below"
- ichimoku_chikou_state: 후행스팬(현재 종가 vs displacement일 전 종가) 국면. direction="up"|"down"
- engulfing: 상승/하락 인걸(장악형) 캔들 패턴 이벤트(1회성, 두 봉으로 완성). direction="bullish"(상승
  인걸)|"bearish"(하락 인걸). "장악형", "인걸 캔들", "감싸는 캔들" 등의 표현이 나오면 이 지표를 쓴다 —
  캔들 패턴을 표현할 다른 방법이 없다고 다른 지표(rsi/bollinger 등)로 억지로 대체하지 말 것.
- bollinger의 band에 "mid"(중심선)도 쓸 수 있다. op="break_above"(상향 돌파)|"break_below"(하향
  이탈). "볼린저 밴드 중심선을 상승/하락 돌파하면 매수/매도"처럼 익절·청산 조건에 자주 등장한다.
- bbw_squeeze_release: 볼린저 밴드폭이 좁아졌다가(스퀴즈) 다시 넓어지기 시작하는 이벤트. "스퀴즈",
  "밴드폭", "밴드 너비"가 언급되면 이 지표를 쓴다. threshold(스퀴즈 판정 기준값, 언급 없으면 0.1),
  lookback(스퀴즈였는지 확인하는 기간, 기본 20), hold_bars(해제 이후 며칠까지 같은 신호로 볼지, 기본
  3 — "스퀴즈 해제 확인 후 밴드 돌파 시 진입"처럼 2단계 확인을 하나의 AND 조건으로 묶을 때 쓴다).
- percent_b: 볼린저 밴드 %B(가격이 밴드 내 어디 있는지, 0~1 범위 밖으로도 나갈 수 있음). "퍼센트비",
  "%b"가 언급되면 사용. op/value로 비교(예: 상단 근접 ">= 0.8").
- mfi: 거래량을 반영한 RSI 격 지표(자금흐름지수). "MFI"가 언급되면 사용. op/value로 비교(예: 과매수
  ">= 80", 과매도 "<= 20").
- double_pattern: 쌍바닥(direction="bullish")/쌍봉(direction="bearish") 추세 반전 패턴 이벤트. "쌍바닥",
  "쌍봉", "이중 바닥/천장" 등이 언급되면 사용. 밴드 위치 제약(첫 저점/고점이 밴드 밖, 둘째가 밴드 안)과
  거래량 급증 확인까지 지표 내부에서 전부 판정하므로, 별도 조건으로 쪼개려 하지 말고 이 지표 하나로
  표현한다.
- rsi_divergence: 가격과 RSI의 고점/저점 방향이 반대인 다이버전스 추세 반전 이벤트. direction="bullish"
  (상승 다이버전스)|"bearish"(하락 다이버전스). "다이버전스"가 언급되면 사용.

ichimoku_cloud_break vs ichimoku_cloud_state 선택 기준: 설명에 "뚫다/돌파하다/이탈하다"처럼 특정
시점의 사건을 가리키면 반드시 ichimoku_cloud_break(이벤트)를 쓴다. "위에 있다/유지한다"처럼 지속되는
상태를 가리킬 때만 ichimoku_cloud_state를 쓴다. 애매하면 이벤트(_break/_cross)를 우선한다 — 단계별
전략은 "그 신호가 뜨는 순간" 비중을 늘리는 구조이므로 상태(state)를 쓰면 원래 의도보다 훨씬 이른/늦은
시점에 반복적으로 조건이 참이 되어 버린다.

각 단계의 conditions 는 여러 조건을 AND/OR로 조합할 수 있다 (예: MACD 골든크로스 + RSI>30 동시 조건).
텍스트에 구체적 수치가 없으면 널리 쓰이는 기본값(RSI 14/30/70, MACD 12/26/9, 일목균형표 9/26/52/26)을 쓰고,
비중이 명시되지 않으면 1:2:6(0.1/0.2/0.6) 비율을 기본으로 사용하세요.

**중요 — 각 조건 객체에는 그 "indicator" 값에 실제로 쓰이는 필드만 채워라.** 예를 들어 bollinger
조건에 kijun_len/span_b_len/displacement(일목균형표 전용) 같은 무관한 필드를 같이 채우면 안 된다.
직전에 다른 지표를 검토했다고 해서 그 필드들을 남겨두지 말 것 — 그 지표에 정의되지 않은 필드는
전부 생략한다.
"""


_STAGED_HINT_KEYWORDS = (
    "1:2:6", "1대2대6", "1대 2대 6", "일목균형표", "이치모쿠", "단계별", "분할매매", "분할 매매",
    # 진입≠청산 조건이라 레짐(logic/conditions) 스키마로 표현 불가능한 볼린저 응용 전략들
    "스퀴즈", "밴드폭", "밴드 너비", "퍼센트비", "%b", "다이버전스", "쌍바닥", "쌍봉",
)


def _looks_like_staged_strategy(raw_text: str) -> bool:
    """1:2:6 식 단계별(staged) 전략 설명인지 키워드로 추정한다.

    명시적으로 "1:2:6"/"일목균형표" 등을 언급하거나, RSI+MACD+일목균형표(또는 이치모쿠) 세 지표를
    동시에 언급하면 단계별 전략으로 판단한다 (단일 지표만 언급되면 기존 레짐형 해석을 그대로 쓴다).
    """
    text = raw_text.lower()
    if any(kw in raw_text or kw.lower() in text for kw in _STAGED_HINT_KEYWORDS):
        return True
    mentions_rsi = "rsi" in text
    mentions_macd = "macd" in text
    mentions_ichimoku = "일목균형표" in raw_text or "이치모쿠" in raw_text or "ichimoku" in text
    return mentions_rsi and mentions_macd and mentions_ichimoku


def _fujimoto_staged_template() -> dict:
    """후지모토 시게루류 1:2:6(RSI+MACD+일목균형표) 매매법의 표준 staged_config 템플릿.

    AI 호출이 불가능할 때(GEMINI_API_KEY 미설정/실패) 이 전략류 텍스트에 대한 합리적인
    기본값으로 사용한다. 사용자는 저장 후 전략 관리 화면에서 세부 파라미터를 조정할 수 있다.
    """
    entry_stages = [
        {
            "weight": 0.1,
            "logic": "AND",
            "conditions": [{"indicator": "rsi_cross", "period": 14, "level": 30, "direction": "up"}],
        },
        {
            "weight": 0.2,
            "logic": "AND",
            "conditions": [
                {"indicator": "macd_cross", "direction": "golden", "zone": "below_zero"},
                {"indicator": "rsi", "period": 14, "op": ">", "value": 30},
            ],
        },
        {
            "weight": 0.6,
            "logic": "AND",
            "conditions": [
                {"indicator": "ichimoku_tk_state", "direction": "golden"},
                {"indicator": "ichimoku_cloud_break", "direction": "up"},
                {"indicator": "ichimoku_chikou_state", "direction": "up"},
            ],
        },
    ]
    exit_stages = [
        {
            "weight": 0.1,
            "logic": "AND",
            "conditions": [{"indicator": "macd_cross", "direction": "dead", "zone": "any"}],
        },
        {
            "weight": 0.2,
            "logic": "AND",
            "conditions": [{"indicator": "rsi_cross", "period": 14, "level": 50, "direction": "down"}],
        },
        {
            "weight": 0.6,
            "logic": "AND",
            "conditions": [{"indicator": "ichimoku_cloud_break", "direction": "down"}],
        },
    ]
    emergency_exit = {
        "logic": "AND",
        "conditions": [
            {"indicator": "macd_cross", "direction": "dead", "zone": "any"},
            {"indicator": "rsi_cross", "period": 14, "level": 50, "direction": "down"},
        ],
    }
    return {
        "name": "1:2:6 단계별 매매법(RSI+MACD+일목균형표)",
        "description": (
            "[자동 해석 실패 - 키워드 기반 대체 로직 사용] GEMINI_API_KEY가 설정되지 않았거나 API "
            "호출에 실패해, 후지모토 시게루류 1:2:6 단계별 매매법의 표준 템플릿을 그대로 사용했습니다. "
            "1단계(10%): RSI가 30을 상향 돌파. 2단계(+20%): 0선 아래에서 MACD 골든크로스 + RSI>30. "
            "3단계(+60%, 직행 가능): 전환선>기준선 + 종가가 구름대 상단 돌파 + 후행스팬 상승 확인(삼역호전). "
            "청산은 MACD 데드크로스(1) → RSI 50 하향 이탈(2) → 구름대 하단 이탈(3, 잔량 전부 정리) 순서이며, "
            "MACD 데드크로스와 RSI 50 이탈이 동시에 뜨면 즉시 전량 청산합니다. "
            "필요시 전략 관리 화면에서 세부 조건/기간을 직접 수정해주세요."
        ),
        "indicator_config": {
            "entry_stages": entry_stages,
            "exit_stages": exit_stages,
            "emergency_exit": emergency_exit,
        },
    }


def _fallback_parse(raw_text: str) -> dict:
    """Claude API 없이 키워드 매칭으로 최소한의 조건을 추출하는 대체 로직."""
    text = raw_text.lower()
    conditions: list[dict] = []
    name_parts: list[str] = []

    if "골든크로스" in raw_text or "golden" in text or "이동평균" in raw_text or "ma cross" in text:
        conditions.append({"indicator": "ma_cross", "short": 20, "long": 60, "ma_type": "sma", "type": "golden"})
        name_parts.append("골든크로스")
    if "데드크로스" in raw_text or "dead cross" in text:
        conditions.append({"indicator": "ma_cross", "short": 20, "long": 60, "ma_type": "sma", "type": "dead"})
        name_parts.append("데드크로스")
    if "rsi" in text or "과매도" in raw_text or "과매수" in raw_text:
        if "과매수" in raw_text and "과매도" not in raw_text:
            conditions.append({"indicator": "rsi", "period": 14, "op": ">", "value": 70})
            name_parts.append("RSI 과매수")
        else:
            conditions.append({"indicator": "rsi", "period": 14, "op": "<", "value": 30})
            name_parts.append("RSI 눌림목")
    if "볼린저" in raw_text or "bollinger" in text:
        if "상단" in raw_text or "upper" in text:
            conditions.append(
                {"indicator": "bollinger", "period": 20, "std_dev": 2.0, "band": "upper", "op": "break_above"}
            )
            name_parts.append("볼린저 상단 돌파")
        else:
            conditions.append(
                {"indicator": "bollinger", "period": 20, "std_dev": 2.0, "band": "lower", "op": "break_below"}
            )
            name_parts.append("볼린저 하단 이탈")

    if not conditions:
        # 아무 키워드도 못 찾으면 기본 골든크로스 전략으로 후보 생성
        conditions.append({"indicator": "ma_cross", "short": 20, "long": 60, "ma_type": "sma", "type": "golden"})
        name_parts.append("후보")

    name = "+".join(name_parts) if name_parts else "후보1"
    description = (
        "[자동 해석 실패 - 키워드 기반 대체 로직 사용] "
        "GEMINI_API_KEY가 설정되지 않았거나 API 호출에 실패해 간단한 키워드 매칭으로 조건을 추정했습니다. "
        "필요시 아래 조건을 직접 수정해주세요."
    )
    return {
        "name": name,
        "description": description,
        "indicator_config": {"logic": "AND", "conditions": conditions},
    }


_MAX_SANE_CONDITIONS = 6
_MAX_SANE_STAGES = 6


def _stage_list_is_sane(stages: Any) -> bool:
    if not isinstance(stages, list) or not stages or len(stages) > _MAX_SANE_STAGES:
        return False
    for stage in stages:
        conditions = stage.get("conditions") if isinstance(stage, dict) else None
        if not isinstance(conditions, list) or not conditions or len(conditions) > _MAX_SANE_CONDITIONS:
            return False
    return True


def _staged_config_is_sane(indicator_config: dict) -> bool:
    """AI 응답이 반복 루프 등으로 폭주(예: 동일 조건 수십~수백 개 중복)하지 않았는지 최소 검증한다.

    response_json_schema의 maxItems가 이 모델에서는 API 400 에러를 유발해 쓸 수 없어(문서와 달리
    실제로 거부됨), 대신 파싱 후 결과 크기를 검사하는 방식으로 동일한 안전장치를 구현한다.
    """
    if not _stage_list_is_sane(indicator_config.get("entry_stages")):
        return False
    if not _stage_list_is_sane(indicator_config.get("exit_stages")):
        return False
    emergency = indicator_config.get("emergency_exit")
    if emergency is not None:
        conditions = emergency.get("conditions") if isinstance(emergency, dict) else None
        if not isinstance(conditions, list) or len(conditions) > _MAX_SANE_CONDITIONS:
            return False
    return True


def interpret_strategy_text(raw_text: str) -> dict:
    """자연어 전략 설명을 지표 조합 조건으로 해석한다.

    일반 전략(레짐형: 이동평균 교차/RSI/볼린저 AND·OR 조합)과 후지모토 시게루류 1:2:6 단계별(staged)
    전략을 모두 지원한다. _looks_like_staged_strategy() 로 둘 중 어떤 스키마로 해석할지 판단한다.

    Returns:
        {"name": str, "description": str, "indicator_config": {...}}
        (레짐형이면 indicator_config={"logic":..., "conditions":[...]}
         staged형이면 indicator_config={"entry_stages":[...], "exit_stages":[...], "emergency_exit":{...}})

    GEMINI_API_KEY가 없거나 호출이 실패하면 키워드 기반 대체 로직으로 폴백한다 (예외를 던지지 않음).
    """
    if _looks_like_staged_strategy(raw_text):
        return _interpret_staged_strategy_text(raw_text)

    if not gemini_client.has_api_key():
        return _fallback_parse(raw_text)

    try:
        response = gemini_client.generate_content(
            models=gemini_client.COMPLEX_TASK_MODELS,
            contents=f"다음 매매 전략 설명을 분석해서 지표 조합으로 변환해줘:\n\n{raw_text}",
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=INDICATOR_CONFIG_SCHEMA,
        )
        text = response.text
        if not text:
            return _fallback_parse(raw_text)
        parsed = json.loads(text)
        # 최소한의 유효성 검증 (반복 루프 등으로 폭주한 응답은 조건 개수 상한으로 걸러낸다)
        conditions = parsed.get("indicator_config", {}).get("conditions")
        if not conditions or len(conditions) > _MAX_SANE_CONDITIONS:
            return _fallback_parse(raw_text)
        return parsed
    except Exception as e:
        fallback = _fallback_parse(raw_text)
        fallback["description"] = f"[AI 호출 실패: {e}] " + fallback["description"]
        return fallback


def _check_entry_exit_overlap(indicator_config: dict) -> list[str]:
    """생성된 staged 전략이 "진입 당일 바로 청산되는" 자기모순 구조인지 실제 백테스트로 검증한다.

    프롬프트(STAGED_SYSTEM_PROMPT)에 "청산 조건이 진입 조건보다 쉽게 만족되면 안 된다"고 문구로
    지시해도 AI가 지키지 않는 경우가 실제로 있었다(예: 진입=볼린저 하단 이탈, 청산/emergency_exit=
    종가가 20일 이평 아래 → 하단 이탈 시점엔 이미 20일 이평 아래이므로 진입 당일 항상 동시에 참).
    프롬프트 지시만으로는 보장이 안 되므로, core.backtest_engine.diagnose_strategy_health로 대표
    종목(AAPL) 백테스트를 직접 돌려 "진입일=청산일" 비율을 경험적으로 확인한다.
    """
    from core.backtest_engine import diagnose_strategy_health

    try:
        return diagnose_strategy_health(indicator_config)
    except Exception:
        return []


_MAX_STAGED_ATTEMPTS = 2  # 최초 생성 1회 + 자기교정 재시도 1회


def _interpret_staged_strategy_text(raw_text: str) -> dict:
    """1:2:6 식 단계별 전략 설명을 staged_config 로 해석한다 (AI 우선, 실패 시 후지모토 템플릿).

    생성 직후 _check_entry_exit_overlap()으로 "진입 당일 바로 청산" 자기모순 여부를 실제로 검증한다.
    문제가 발견되면 그 진단 결과를 그대로 AI에게 되돌려주며 한 번 더 생성을 시도한다(자기교정).
    재시도까지 실패하면 결과는 그대로 반환하되 health_warnings/description에 경고를 남겨 호출부
    (UI)가 절대 조용히 넘어가지 못하게 한다 — 프롬프트 지시만 믿지 않고 결과를 항상 검증한다.
    """
    if not gemini_client.has_api_key():
        template = _fujimoto_staged_template()
        template["health_warnings"] = []
        return template

    contents = f"다음 매매 전략 설명을 분석해서 1:2:6 단계별 지표 조합으로 변환해줘:\n\n{raw_text}"
    parsed: Optional[dict] = None
    warnings: list[str] = []

    for attempt in range(_MAX_STAGED_ATTEMPTS):
        try:
            response = gemini_client.generate_content(
                models=gemini_client.COMPLEX_TASK_MODELS,
                contents=contents,
                system_instruction=STAGED_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_json_schema=STAGED_INDICATOR_CONFIG_SCHEMA,
            )
            text = response.text
            if not text:
                template = _fujimoto_staged_template()
                template["health_warnings"] = []
                return template
            parsed = json.loads(text)
            # 최소한의 유효성 검증 (반복 루프 등으로 폭주한 응답은 조건/단계 개수 상한으로 걸러낸다)
            if not _staged_config_is_sane(parsed.get("indicator_config", {})):
                template = _fujimoto_staged_template()
                template["health_warnings"] = []
                return template
        except Exception as e:
            fallback = _fujimoto_staged_template()
            fallback["description"] = f"[AI 호출 실패: {e}] " + fallback["description"]
            fallback["health_warnings"] = []
            return fallback

        warnings = _check_entry_exit_overlap(parsed["indicator_config"])
        if not warnings:
            parsed["health_warnings"] = []
            return parsed

        if attempt + 1 < _MAX_STAGED_ATTEMPTS:
            contents = (
                f"다음 매매 전략 설명을 분석해서 1:2:6 단계별 지표 조합으로 변환해줘:\n\n{raw_text}\n\n"
                "--- 직전 시도 검증 실패 ---\n"
                f"방금 생성한 조건으로 실제 백테스트를 해보니 다음 문제가 발견됐다: {warnings[0]}\n"
                "즉 진입 조건이 참인 날에 청산(exit_stages) 또는 긴급청산(emergency_exit) 조건도 항상 "
                "같이 참이 되어버리는 구조다(예: 진입이 볼린저 하단 이탈인데 청산이 이평선 아래처럼 "
                "진입 조건에 포함되는 더 느슨한 상태 조건이면 항상 동시에 참이 된다). 청산 조건을 진입 "
                "조건과 절대 겹치지 않는, 반대 방향의 신호(과매수 반전, 반대 방향 크로스 이벤트 등)로 "
                "다시 설계해서 같은 스키마의 JSON을 처음부터 다시 생성해줘."
            )

    # 재시도까지 실패 — 결과는 반환하되 경고를 명시적으로 붙여 호출부가 놓칠 수 없게 한다.
    assert parsed is not None
    parsed["health_warnings"] = warnings
    parsed["description"] = "⚠️ 자동 정합성 검증에 실패했습니다(진입/청산 조건이 겹칠 수 있음). " + parsed["description"]
    return parsed


_WS_RE = re.compile(r"\s+")


def suggest_candidate_name(existing_names: list[str]) -> str:
    """기존 전략명과 겹치지 않는 '후보N' 이름을 생성한다 (전략명 자동 생성 실패 시 등에 사용)."""
    n = 1
    existing = set(existing_names)
    while f"후보{n}" in existing:
        n += 1
    return f"후보{n}"
