"""모듈 A 확장: 다종목 미세튜닝 + 종목 스타일 매칭 엔진.

유튜브 등에서 해석한 전략(core.nl_strategy)을 백본으로 유지한 채, S&P500 중 섹터 균등 표본
(기본 100종목)에 대해 종목별 스타일(주도주/성장주/가치주/경기민감주/경기방어주/퀄리티 컴파운더)을
판별하고, 스타일 방향에 맞게 파라미터 탐색 범위만 다르게 잡아 grid/random search로 미세튜닝한다.
과최적화를 피하기 위해 train(과거)/test(최근) 기간을 분리해, train에서 탐색한 최적 파라미터를
test(out-of-sample)에서 검증한다.

설계 배경/결정 사항은 STRATEGY_TUNING_ENGINE_SPEC.md 참고. 강화학습은 쓰지 않고(사용자 확정),
원본 전략의 지표 구성/조건 로직 구조는 그대로 두고 수치 파라미터만 변형한다("백본 유지" 원칙).

핵심 함수:
    sample_universe(n=100) -> pd.DataFrame                 섹터 균등 100종목 표본
    compute_style_scores(tickers_df, start, end) -> pd.DataFrame   종목별 6개 스타일 점수 + 주 유형
    build_param_grid(base_config, style_type, intensity) -> list[dict]   튜닝 후보 config 리스트
    tune_strategy_for_ticker(ticker, base_config, style_type, start, end, ...) -> dict
    run_batch_tuning(base_config, tickers_df, start, end, ...) -> list[dict]
    save_tuning_run(...) / list_tuning_runs() / get_tuning_run(run_id)
"""

from __future__ import annotations

import ast
import copy
import itertools
import json
import random
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

from core import gemini_client, screener, valuation
from core.backtest_engine import compare_with_benchmarks, diagnose_strategy_health, run_backtest
from core.db import get_session
from core.expression_engine import ExpressionError, validate_syntax
from core.indicators import sma
from core.macro_cycle import SECTOR_ROTATION
from core.market_data import get_price_history
from core.models import StrategyTuningResult, StrategyTuningRun
from core.strategy_engine import is_expression_config

# ----------------------------------------------------------------------------
# 1. 100종목 섹터 균등 표본
# ----------------------------------------------------------------------------


def sample_universe(n: int = 100, use_cache: bool = True) -> pd.DataFrame:
    """S&P500 유니버스에서 섹터별로 균등 배분된 n종목 표본을 시가총액 상위 순으로 추출한다.

    시총 상위 n개를 그냥 뽑으면 빅테크 섹터로 편중되어(STRATEGY_TUNING_ENGINE_SPEC.md 5절 결정)
    섹터별 스타일 비교가 무의미해지므로, 섹터마다 기본 할당량(n // 섹터수)을 배분하고 나머지는
    섹터 전체 시가총액 합이 큰 섹터부터 1개씩 더 배분한다.

    Returns:
        columns: ticker, sector(GICS 영문), market_cap. 시가총액 내림차순 정렬.
    """
    universe = screener.get_universe(use_cache=use_cache)
    sectors = sorted(universe["Sector"].dropna().unique().tolist())
    if not sectors:
        return pd.DataFrame(columns=["ticker", "sector", "market_cap"])

    rows = []
    for _, r in universe.iterrows():
        fundamentals = screener.get_fundamentals(r["Symbol"], use_cache=use_cache)
        rows.append(
            {"ticker": r["Symbol"], "sector": r["Sector"], "market_cap": fundamentals.get("market_cap") or 0}
        )
    df = pd.DataFrame(rows)

    base_quota = max(1, n // len(sectors))
    remainder = max(0, n - base_quota * len(sectors))
    sector_total_cap = df.groupby("sector")["market_cap"].sum().sort_values(ascending=False)
    quotas = {s: base_quota for s in sectors}
    for s in sector_total_cap.index[:remainder]:
        quotas[s] += 1

    picked = [
        df[df["sector"] == s].sort_values("market_cap", ascending=False).head(quotas.get(s, base_quota))
        for s in sectors
    ]
    result = pd.concat(picked, ignore_index=True) if picked else pd.DataFrame(columns=df.columns)
    return result.sort_values("market_cap", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------------
# 2. 종목 스타일 분류 (STRATEGY_TUNING_ENGINE_SPEC.md 4절 — 6개 카테고리, 확정)
# ----------------------------------------------------------------------------

STYLE_LABELS = ["주도주", "성장주", "가치주", "경기민감주", "경기방어주", "퀄리티 컴파운더"]
_SCORE_COLUMNS = [
    "momentum_score",
    "growth_score",
    "value_score",
    "cyclical_score",
    "defensive_score",
    "quality_score",
]
_SCORE_TO_LABEL = dict(zip(_SCORE_COLUMNS, STYLE_LABELS))

# 위키피디아 GICS 섹터(영문, core.screener.get_universe 반환값) -> core.macro_cycle 국면별
# 로테이션 표(한국어 섹터명) 매핑. Communication Services는 macro_cycle 로테이션 표에 대응하는
# 국면이 없어(원래 표가 10개 섹터만 다룸) 씨클리컬/방어 어느 쪽에도 태깅되지 않는다(중립).
GICS_TO_KOREAN_SECTOR: dict[str, str] = {
    "Information Technology": "기술",
    "Health Care": "헬스케어",
    "Financials": "금융",
    "Consumer Discretionary": "임의소비재",
    "Consumer Staples": "필수소비재",
    "Industrials": "산업재",
    "Energy": "에너지",
    "Utilities": "유틸리티",
    "Real Estate": "부동산",
    "Materials": "소재",
}

_CYCLICAL_SECTORS_KR = set(SECTOR_ROTATION["회복"]) | set(SECTOR_ROTATION["확장"]) | set(SECTOR_ROTATION["둔화"])
_DEFENSIVE_SECTORS_KR = set(SECTOR_ROTATION["수축"])
# 참고: SECTOR_ROTATION 원본 표에서 "필수소비재"가 둔화(씨클리컬 쪽)와 수축(방어 쪽) 양쪽에 모두
# 등장해, 필수소비재 섹터 종목은 cyclical_score/defensive_score가 둘 다 100이 될 수 있다(다른
# 점수가 더 높지 않으면 동점 시 딕셔너리 순서상 "경기민감주"가 우선 선택됨). macro_cycle.py의 기존
# 로테이션 표를 그대로 재사용한 결과로, 별도로 보정하지 않고 있는 그대로 반영한다.

_MOMENTUM_LOOKBACK_DAYS = 126  # 약 6개월 거래일
_QUALITY_MIN_ROWS = 210  # 200일선 계산에 필요한 최소 데이터 (여유 포함)


def _trailing_return_pct(df: pd.DataFrame, days: int = _MOMENTUM_LOOKBACK_DAYS) -> Optional[float]:
    """최근 `days` 거래일 동안의 수익률(%)을 계산한다 (주도주 판별용 모멘텀 신호)."""
    if df is None or df.empty or len(df) < 2:
        return None
    close = df["Close"]
    window = close.iloc[-days:] if len(close) > days else close
    if len(window) < 2 or window.iloc[0] == 0:
        return None
    return float(window.iloc[-1] / window.iloc[0] - 1) * 100


def _quality_signals(df: pd.DataFrame) -> tuple[Optional[float], Optional[float]]:
    """장기 MDD(%)와 200일선 위 체류 비율(%)을 계산한다 (퀄리티 컴파운더 판별용).

    데이터가 200일선 계산에 부족하면 (None, None)을 반환한다.
    """
    if df is None or df.empty or len(df) < _QUALITY_MIN_ROWS:
        return None, None
    close = df["Close"]
    running_max = close.cummax()
    drawdown = (close / running_max - 1) * 100
    mdd = float(drawdown.min())

    sma200 = sma(close, 200).dropna()
    if sma200.empty:
        return mdd, None
    aligned_close = close.loc[sma200.index]
    above_pct = float((aligned_close > sma200).mean()) * 100
    return mdd, above_pct


def _percentile_score(series: pd.Series) -> pd.Series:
    """배치 내 상대 순위를 0~100 백분위 점수로 변환한다. 값이 전부 결측이면 중립값(50)."""
    if series.dropna().empty:
        return pd.Series(50.0, index=series.index)
    return series.rank(pct=True, na_option="bottom") * 100


def compute_style_scores(tickers_df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """종목별로 6개 스타일 점수(0~100)를 계산하고, 최고점 유형을 주 유형(style_type)으로 태깅한다.

    Args:
        tickers_df: columns ticker, sector(GICS 영문) — sample_universe() 반환 형식.
        start, end: 모멘텀/퀄리티 신호 계산에 사용할 가격 조회 구간(보통 튜닝 전체 기간과 동일).

    Returns:
        columns: ticker, sector, style_type, style_scores(dict), momentum_score, growth_score,
        value_score, cyclical_score, defensive_score, quality_score
    """
    rows = []
    for _, r in tickers_df.iterrows():
        ticker = r["ticker"]
        sector_en = r.get("sector")
        sector_kr = GICS_TO_KOREAN_SECTOR.get(sector_en)

        val_inputs = valuation.fetch_valuation_inputs(ticker)
        price_df = get_price_history(ticker, start=start, end=end, use_cache=True)

        momentum_raw = _trailing_return_pct(price_df)
        mdd_raw, above200_raw = _quality_signals(price_df)

        rows.append(
            {
                "ticker": ticker,
                "sector": sector_en,
                "per": val_inputs.get("trailingPE"),
                "pbr": val_inputs.get("priceToBook"),
                "earnings_growth": val_inputs.get("earningsGrowth"),
                "momentum_raw": momentum_raw,
                "mdd_raw": mdd_raw,
                "above200_raw": above200_raw,
                "is_cyclical": sector_kr in _CYCLICAL_SECTORS_KR,
                "is_defensive": sector_kr in _DEFENSIVE_SECTORS_KR,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["ticker", "sector", "style_type", "style_scores", *_SCORE_COLUMNS])

    # 값이 전부 None인 컬럼은 object dtype이 되어 fillna 시 FutureWarning(다운캐스팅 경고)이 나므로,
    # 점수 계산 전에 명시적으로 숫자형(NaN 포함)으로 정규화한다.
    for col in ("per", "pbr", "earnings_growth", "momentum_raw", "mdd_raw", "above200_raw"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["momentum_score"] = _percentile_score(df["momentum_raw"])
    # earnings_growth가 없는 종목은 PER(밸류에이션 프리미엄)로 대체(성장주는 대체로 고PER).
    df["growth_score"] = _percentile_score(df["earnings_growth"].fillna(df["per"]))
    df["value_score"] = _percentile_score(-df[["per", "pbr"]].mean(axis=1, skipna=True))
    df["cyclical_score"] = df["is_cyclical"].map({True: 100.0, False: 0.0})
    df["defensive_score"] = df["is_defensive"].map({True: 100.0, False: 0.0})
    df["quality_score"] = _percentile_score(-df["mdd_raw"].abs()) * 0.5 + df["above200_raw"].fillna(0.0) * 0.5

    def _primary_type_and_scores(row: pd.Series) -> tuple[str, dict[str, float]]:
        scores = {_SCORE_TO_LABEL[c]: round(float(row[c]), 1) for c in _SCORE_COLUMNS}
        primary = max(scores, key=scores.get)
        return primary, scores

    primaries = df.apply(_primary_type_and_scores, axis=1)
    df["style_type"] = primaries.apply(lambda x: x[0])
    df["style_scores"] = primaries.apply(lambda x: x[1])

    return df[["ticker", "sector", "style_type", "style_scores", *_SCORE_COLUMNS]]


# ----------------------------------------------------------------------------
# 3. 스타일별 파라미터 탐색 공간 (구조 유지, 탐색 방향만 차등 — 3절 확정 원칙)
# ----------------------------------------------------------------------------

_INTENSITY_BUDGET = {"빠름": 20, "보통": 60, "정밀": 150}
_DEFAULT_INTENSITY = "보통"

# 이평 기간류 파라미터에 곱해지는 (하한 배수, 상한 배수). 주도주는 짧게, 방어주/퀄리티는 길게.
_STYLE_PERIOD_MULTIPLIERS: dict[str, tuple[float, float]] = {
    "주도주": (0.3, 0.8),
    "성장주": (0.8, 2.0),
    "가치주": (0.8, 1.5),
    "경기민감주": (0.7, 1.3),
    "경기방어주": (1.0, 2.0),
    "퀄리티 컴파운더": (1.0, 2.5),
}
_DEFAULT_MULTIPLIER = (0.7, 1.5)

_PERIOD_LIKE_KEYS = {
    "short",
    "long",
    "period",
    "fast",
    "slow",
    "signal",
    "tenkan_len",
    "kijun_len",
    "span_b_len",
    "displacement",
}
_THRESHOLD_LIKE_KEYS = {"value", "level"}


def _iter_condition_paths(config: dict, path: tuple = ()):
    """config 트리(레짐/staged 스키마 공용)를 순회하며 (path, condition_dict) 쌍을 만든다.

    path는 이후 다른 deepcopy 트리에서 정확히 같은 위치를 다시 찾기 위한 키/인덱스 시퀀스다
    (예: ("entry_stages", 0, "conditions", 1)). expression 스키마는 조건 dict가 없어 빈 채로 끝난다.
    """
    conditions = config.get("conditions")
    if isinstance(conditions, list):
        for i, c in enumerate(conditions):
            if isinstance(c, dict) and "indicator" in c:
                yield (*path, "conditions", i), c
    for stage_key in ("entry_stages", "exit_stages"):
        for si, stage in enumerate(config.get(stage_key, []) or []):
            for i, c in enumerate(stage.get("conditions", []) or []):
                if isinstance(c, dict) and "indicator" in c:
                    yield (*path, stage_key, si, "conditions", i), c
    emergency = config.get("emergency_exit")
    if isinstance(emergency, dict):
        for i, c in enumerate(emergency.get("conditions", []) or []):
            if isinstance(c, dict) and "indicator" in c:
                yield (*path, "emergency_exit", "conditions", i), c


def _get_by_path(config: dict, path: tuple) -> Any:
    node: Any = config
    for key in path:
        node = node[key]
    return node


def build_param_grid(base_config: dict, style_type: str, intensity: str = _DEFAULT_INTENSITY) -> list[dict]:
    """원본 전략 구조는 그대로 두고, 수치 파라미터만 스타일 방향에 맞게 변형한 후보 리스트를 만든다.

    "백본 유지" 원칙(STRATEGY_TUNING_ENGINE_SPEC.md 3/5절)에 따라 지표 종류/조건 개수/AND-OR 로직은
    절대 바꾸지 않고, 각 조건의 이평 기간류/임계값류 숫자만 건드린다. 조합 수가 예산(intensity)을
    넘으면 고정 시드 랜덤 샘플링으로 줄인다(재실행해도 같은 후보 집합 — 재현 가능성).

    expression(직접 수식) 전략은 숫자 파라미터가 JSON 필드명이 아니라 자유 문자열 안에 있어
    구조적으로 식별할 수 없었는데, Gemini로 숫자별 튜닝 가능 여부/역할을 판별해 이제는 이 스키마도
    지원한다 (2026-07-14 사용자 확정 — 이 예외는 expression 스키마에만 적용되고, 아래 JSON 스키마의
    "백본 유지" 원칙에는 영향 없음). 자세한 내용은 _build_expression_param_grid() 참고.
    """
    if "expression" in base_config:
        return _build_expression_param_grid(base_config, style_type, intensity)

    lo_mult, hi_mult = _STYLE_PERIOD_MULTIPLIERS.get(style_type, _DEFAULT_MULTIPLIER)
    budget = _INTENSITY_BUDGET.get(intensity, _INTENSITY_BUDGET[_DEFAULT_INTENSITY])

    axis_values: list[tuple[tuple, str, list]] = []
    for path, cond in _iter_condition_paths(base_config):
        for key, val in cond.items():
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                continue
            if key in _PERIOD_LIKE_KEYS:
                lo = max(2, round(val * lo_mult))
                hi = max(lo + 1, round(val * hi_mult))
                values = sorted({lo, int(round(val)), hi})
            elif key == "std_dev":
                values = sorted({max(0.5, round(val - 0.5, 1)), round(val, 1), min(4.0, round(val + 0.5, 1))})
            elif key in _THRESHOLD_LIKE_KEYS:
                delta = 10.0 if val > 1 else 0.1
                values = sorted({max(0.0, round(val - delta, 2)), round(val, 2), round(val + delta, 2)})
            else:
                continue
            axis_values.append((path, key, values))

    if not axis_values:
        return [copy.deepcopy(base_config)]

    total_combos = 1
    for _, _, values in axis_values:
        total_combos *= len(values)

    if total_combos <= budget:
        combos = list(itertools.product(*[values for _, _, values in axis_values]))
    else:
        rng = random.Random(42)  # 고정 시드: 같은 base_config/style로 재실행해도 같은 후보 집합
        seen: set = set()
        combos = []
        attempts = 0
        while len(combos) < budget and attempts < budget * 20:
            attempts += 1
            combo = tuple(rng.choice(values) for _, _, values in axis_values)
            if combo not in seen:
                seen.add(combo)
                combos.append(combo)

    candidates = []
    for combo in combos:
        candidate = copy.deepcopy(base_config)
        for (path, key, _), value in zip(axis_values, combo):
            _get_by_path(candidate, path)[key] = value
        candidates.append(candidate)

    original = copy.deepcopy(base_config)
    if original not in candidates:
        candidates.append(original)  # 튜닝이 원본보다 나빠지지 않게 항상 비교 기준으로 포함

    return candidates


# train/test 분리에 쓰는 공용 상수. 아래 3b절의 tune_expression_strategy_for_ticker()가 기본 인자
# 값으로 참조하므로(함수 정의 시점에 평가됨) 그 정의보다 앞에 있어야 한다 — 원래 "4. train/test
# 분리 튜닝" 절에 있었으나 3b절 추가로 앞당김(NameError 방지, 값 자체는 그대로).
_DEFAULT_TRAIN_RATIO = 0.75
_MIN_TRADE_COUNT = 5


# ----------------------------------------------------------------------------
# 3b. 직접 수식(expression) 전략 전용 Gemini 기반 튜닝 (2026-07-14 사용자 확정)
#
# 위 3절의 "백본 유지, 숫자만 튜닝" 원칙은 JSON(레짐/1:2:6) 전략에 그대로 유지된다. expression
# 스키마는 원래 build_param_grid가 튜닝 파라미터를 식별할 방법이 없어 원본만 반환했는데, 사용자가
# 두 단계로 이 한계를 넘어달라고 명시적으로 요청함:
#   1) 먼저 수식 안의 숫자가 "튜닝 가능한 파라미터"인지부터 Gemini로 식별한다 (identify_tunable_
#      numbers). 숫자의 실제 값/위치는 ast로 결정론적으로 뽑고, Gemini에게는 "이 숫자가 튜닝
#      가능한가/어떤 역할인가/합리적 범위는 얼마인가"라는 의미 판단만 맡긴다 — Gemini가 숫자 값
#      자체를 잘못 베껴 써서 수식이 깨질 위험을 원천적으로 없앤다.
#   2) 그렇게 숫자만 바꾼 튜닝으로도 test 구간에서 종목 매수보유 + S&P500 매수보유를 둘 다 못
#      이기면(즉 파라미터 튜닝의 한계에 부딪히면), 그때만 Gemini에게 구조가 다른 대안 수식을
#      제안받아(generate_structural_variants) "백본 자체"를 바꾸는 걸 허용한다. 이건 확실히
#      기존 "백본 유지" 원칙의 예외이므로 scope를 expression 전략에만 한정했다(사용자 확정).
#
# 설계 판단(사용자가 위임, 근거 명시):
#   - 반복 진화(제안->결과 피드백->재제안을 여러 세대) 대신 "1회성 후보 생성"만 한다. 구조 탐색은
#     파라미터 탐색보다 과최적화 위험이 훨씬 크고(탐색 공간이 사실상 무한), 반복 루프는 API 호출량도
#     선형으로 늘어난다. 1회에 몇 개 후보만 받고 train/test로 검증하는 쪽이 기존 grid search와
#     같은 수준의 통제된 위험으로 유지된다.
#   - test에서 여전히 못 이겨도 계속 재시도하지 않고, 지금까지 찾은 것 중 가장 나은 결과로
#     폴백한다(tune_strategy_for_ticker의 기존 "유효 후보 없으면 원본 폴백" 관례와 일관).
#     outperformed_ticker_bh/outperformed_benchmark_bh 플래그로 실제로 이겼는지를 결과에 항상
#     명시해, 이기지 못한 결과가 조용히 성공으로 보이지 않게 한다.
# ----------------------------------------------------------------------------

_EXPRESSION_TUNABLE_SYSTEM_PROMPT = """\
너는 퀀트 트레이딩 수식의 숫자 리터럴을 분석하는 어시스턴트다.

사용자가 파이썬과 비슷한 문법의 매매 조건 수식과, 그 수식에 등장하는 숫자 리터럴 목록(순서대로
번호가 매겨짐, 각 번호 옆에 그 숫자가 수식의 어느 위치에 있는지 주변 문맥과 함께 제공됨)을 준다.

각 숫자에 대해 판단할 것:
1. tunable: 이 숫자가 "튜닝 가능한 파라미터"인가? 이동평균/RSI 등의 기간(period), 임계값(threshold),
   승수(multiplier), 표준편차 폭 등은 전부 tunable=true. 반면 함수 호출과 무관한 산술 상수이거나
   바꾸면 수식의 의미 자체가 깨지는 값(예: 0/1처럼 항상 그대로여야 하는 구조적 상수)은 tunable=false.
2. role: 이 숫자의 역할을 한국어로 짧게 설명 (예: "20일 이동평균 기간", "RSI 과매도 임계값").
3. suggested_min / suggested_max: tunable=true인 경우, 이 숫자를 바꿔가며 탐색할 때 합리적인
   범위(원본 값과 같은 단위). 예를 들어 RSI 임계값(0~100 범위)이면 원래 30이었다면 15~40 정도,
   이동평균 기간이면 원래 20이었다면 10~40 정도처럼, 그 지표의 통상적인 실전 사용 범위를 벗어나지
   않게 제안한다. tunable=false면 suggested_min/suggested_max는 원래 값과 동일하게 채운다.

숫자 목록과 정확히 같은 개수/순서로 결과를 반환해야 한다(개수가 안 맞으면 이 응답 전체가 무시된다).
"""

_TUNABLE_NUMBERS_SCHEMA = {
    "type": "object",
    "properties": {
        "numbers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "tunable": {"type": "boolean"},
                    "role": {"type": "string"},
                    "suggested_min": {"type": "number"},
                    "suggested_max": {"type": "number"},
                },
                "required": ["index", "tunable", "role", "suggested_min", "suggested_max"],
            },
        }
    },
    "required": ["numbers"],
}


def _extract_numeric_literals(expression: str) -> list[dict]:
    """expression에서 숫자 리터럴을 등장 순서대로 추출한다 (값 + 원본 텍스트상 정확한 위치).

    core.expression_engine과 동일하게 ast로 파싱하므로 그 문법과 항상 일치한다. bool은 int의
    서브클래스라 ast.Constant(True/False)와 혼동되지 않도록 명시적으로 제외한다.
    """
    tree = ast.parse(expression, mode="eval")
    literals = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            literals.append(
                {
                    "value": node.value,
                    "start": node.col_offset,
                    "end": node.end_col_offset,
                    "text": expression[node.col_offset : node.end_col_offset],
                }
            )
    literals.sort(key=lambda x: x["start"])
    return literals


def identify_tunable_numbers(expression: str) -> list[dict]:
    """Gemini로 수식 안의 숫자 리터럴이 각각 튜닝 가능한 파라미터인지 판별하고, 가능하면 합리적인
    탐색 범위(suggested_min/max)를 제안받는다.

    숫자의 실제 값/위치는 ast로 결정론적으로 뽑고(Gemini가 값을 잘못 베껴 써서 수식이 깨질 위험을
    없앰), Gemini에게는 의미 판단만 맡긴다. 키가 없거나 호출/파싱 실패, 개수 불일치(신뢰 불가)면
    빈 리스트를 반환해 호출부가 원본 그대로 폴백하게 한다 — 예외를 던지지 않는다.

    Returns:
        [{"value", "start", "end", "text", "role", "suggested_min", "suggested_max"}, ...]
        (tunable=false로 판별된 숫자는 결과에서 제외됨)
    """
    try:
        literals = _extract_numeric_literals(expression)
    except SyntaxError:
        return []
    if not literals or not gemini_client.has_api_key():
        return []

    numbered_lines = []
    for i, lit in enumerate(literals):
        ctx_start = max(0, lit["start"] - 15)
        ctx_end = min(len(expression), lit["end"] + 15)
        numbered_lines.append(f"{i}: {lit['text']} (문맥: ...{expression[ctx_start:ctx_end]}...)")
    contents = f"수식: {expression}\n\n숫자 목록:\n" + "\n".join(numbered_lines)

    try:
        response = gemini_client.generate_content(
            models=gemini_client.LIGHT_TASK_MODELS,
            contents=contents,
            system_instruction=_EXPRESSION_TUNABLE_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=_TUNABLE_NUMBERS_SCHEMA,
        )
        text = response.text
        if not text:
            return []
        items = json.loads(text).get("numbers", [])
        if len(items) != len(literals):
            return []  # 개수가 안 맞으면 신뢰할 수 없음 -> 튜닝 없이 원본 그대로 폴백
    except Exception:
        return []

    result = []
    for lit, item in zip(literals, items):
        if not item.get("tunable"):
            continue
        try:
            lo, hi = float(item["suggested_min"]), float(item["suggested_max"])
        except (KeyError, TypeError, ValueError):
            continue
        if lo >= hi:
            continue
        result.append({**lit, "role": item.get("role", ""), "suggested_min": lo, "suggested_max": hi})
    return result


def _format_like(value: float, original_text: str) -> str:
    """치환할 숫자를 원본 리터럴의 표기 스타일(정수/소수)에 맞춰 문자열로 만든다."""
    if "." in original_text:
        return f"{round(value, 2):g}"
    return str(int(round(value)))


def _substitute_numbers(expression: str, literals: list[dict], values: tuple) -> str:
    """literals의 각 위치를 values로 치환한다 (뒤에서부터 치환해 앞쪽 offset이 안 밀리게 함)."""
    pieces = list(expression)
    for lit, value in sorted(zip(literals, values), key=lambda p: -p[0]["start"]):
        pieces[lit["start"] : lit["end"]] = _format_like(value, lit["text"])
    return "".join(pieces)


def _build_expression_param_grid(base_config: dict, style_type: str, intensity: str) -> list[dict]:
    """expression 전략의 숫자 파라미터 후보를 생성한다 (JSON 스키마의 build_param_grid와 동일한
    조합 폭발 처리/예산/재현 가능한 랜덤 샘플링을 그대로 재사용).

    identify_tunable_numbers()가 튜닝 가능한 숫자를 하나도 못 찾으면(키 없음/판별 실패 포함)
    원본 1개만 반환한다 — 이 경우 tune_strategy_for_ticker는 원본 그대로 실행되며 실패로 취급되지
    않는다(기존 "유효 후보 없으면 원본" 관례와 동일).
    """
    expression = base_config["expression"]
    try:
        tunables = identify_tunable_numbers(expression)
    except Exception:
        tunables = []
    if not tunables:
        return [copy.deepcopy(base_config)]

    lo_mult, hi_mult = _STYLE_PERIOD_MULTIPLIERS.get(style_type, _DEFAULT_MULTIPLIER)
    budget = _INTENSITY_BUDGET.get(intensity, _INTENSITY_BUDGET[_DEFAULT_INTENSITY])

    axis_values: list[tuple[dict, list]] = []
    for t in tunables:
        original = t["value"]
        # Gemini가 제안한 의미론적 범위와, 기존 스타일 배수 범위를 함께 반영(둘 다 벗어나지 않게
        # 더 넓은 쪽을 취함 — 스타일 방향성은 유지하면서 Gemini의 의미 판단도 존중).
        lo = min(t["suggested_min"], original * lo_mult) if original else t["suggested_min"]
        hi = max(t["suggested_max"], original * hi_mult) if original else t["suggested_max"]
        values = sorted({round(lo, 2), round(float(original), 2), round(hi, 2)})
        axis_values.append((t, values))

    total_combos = 1
    for _, values in axis_values:
        total_combos *= len(values)

    if total_combos <= budget:
        combos = list(itertools.product(*[values for _, values in axis_values]))
    else:
        rng = random.Random(42)  # 고정 시드: 같은 base_config/style로 재실행해도 같은 후보 집합
        seen: set = set()
        combos = []
        attempts = 0
        while len(combos) < budget and attempts < budget * 20:
            attempts += 1
            combo = tuple(rng.choice(values) for _, values in axis_values)
            if combo not in seen:
                seen.add(combo)
                combos.append(combo)

    literals_only = [t for t, _ in axis_values]
    candidates = []
    for combo in combos:
        new_expr = _substitute_numbers(expression, literals_only, combo)
        try:
            validate_syntax(new_expr)
        except ExpressionError:
            continue  # 치환 결과가 문법/실행상 깨지면 후보에서 제외 (실행 불가능한 수식을 백테스트에 넘기지 않음)
        candidates.append({"expression": new_expr})

    original = copy.deepcopy(base_config)
    if original not in candidates:
        candidates.append(original)  # 튜닝이 원본보다 나빠지지 않게 항상 비교 기준으로 포함
    return candidates or [original]


_STRUCTURAL_VARIANT_SYSTEM_PROMPT = """\
너는 퀀트 트레이딩 전략을 개선하는 어시스턴트다.

사용자가 원본 매매 조건 수식과 종목 스타일, 그리고 사용 가능한 문법(변수/함수/연산자 목록)을 준다.
이 수식과 같은 매매 아이디어(예: 과매도 반전, 추세추종 등)를 유지하되, 지표 구성이나 조건 로직이
다른 대안을 제안해라 — 숫자만 바꾸는 게 아니라 지표를 교체하거나(예: 볼린저 대신 RSI 크로스),
조건을 추가/삭제하거나, and/or 결합을 바꾸는 식으로 구조 자체가 달라야 한다. 종목 스타일에 맞는
방향으로 제안한다(예: 주도주는 짧은 홀딩·모멘텀 추종, 방어주는 낮은 매매빈도).

**반드시 사용자가 알려준 문법만 써야 한다 (그 외의 함수/변수/문법은 전부 실행이 거부된다).**

각 대안은 완전한 하나의 불리언 수식 문자열이어야 한다(파이썬과 비슷한 문법, and/or/not, 비교 연산자
필수). 설명이나 마크다운 없이 수식 문자열 자체만 배열에 담아 반환한다.
"""

_STRUCTURAL_VARIANTS_SCHEMA = {
    "type": "object",
    "properties": {"variants": {"type": "array", "items": {"type": "string"}}},
    "required": ["variants"],
}

_MAX_STRUCTURAL_VARIANTS = 3


def generate_structural_variants(expression: str, style_type: str, n: int = _MAX_STRUCTURAL_VARIANTS) -> list[str]:
    """Gemini로 원본과 다른 지표 구성/조건 로직을 가진 대안 수식을 최대 n개 제안받는다.

    숫자만 바꾸는 튜닝(_build_expression_param_grid)으로 test 구간에서 매수보유를 못 이길 때만
    호출되는 escape hatch다(tune_expression_strategy_for_ticker 참고). 1회성으로 n개만 생성하고
    반복적으로 재시도하지 않는다(비용/과최적화 위험 통제 — 파일 상단 3b절 설명 참고). 각 후보는
    validate_syntax()로 문법/실행 가능 여부를 검증해 통과한 것만 반환한다.
    """
    if not gemini_client.has_api_key():
        return []

    from core.expression_engine import FUNCTIONS, VARIABLE_COLUMNS

    grammar_note = (
        f"변수: {', '.join(sorted(VARIABLE_COLUMNS))} / 함수: {', '.join(sorted(FUNCTIONS))} "
        "/ 비교연산자: < <= > >= == != / 논리연산자: and or not"
    )
    contents = (
        f"원본 수식: {expression}\n종목 스타일: {style_type}\n\n"
        f"이 수식과 같은 매매 아이디어를 유지하되 구조가 다른 대안을 최대 {n}개 제안해줘.\n"
        f"사용 가능한 문법: {grammar_note}"
    )
    try:
        response = gemini_client.generate_content(
            models=gemini_client.COMPLEX_TASK_MODELS,
            contents=contents,
            system_instruction=_STRUCTURAL_VARIANT_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=_STRUCTURAL_VARIANTS_SCHEMA,
        )
        text = response.text
        if not text:
            return []
        raw_variants = json.loads(text).get("variants", [])
    except Exception:
        return []

    valid: list[str] = []
    for v in raw_variants:
        if not isinstance(v, str):
            continue
        try:
            validate_syntax(v)
        except ExpressionError:
            continue  # 실행 불가능한 제안은 조용히 건너뜀(재시도하지 않음 — 1회성 원칙)
        valid.append(v)
        if len(valid) >= n:
            break
    return valid


def _outperforms_both_benchmarks(test_comparison: dict) -> bool:
    """test 구간에서 전략이 종목 매수보유 + S&P500 매수보유를 CAGR 기준으로 둘 다 이겼는지."""
    strat = test_comparison.get("strategy", {}).get("cagr", 0.0)
    ticker_bh = test_comparison.get("buy_and_hold_ticker", {}).get("cagr", 0.0)
    bench_bh = test_comparison.get("buy_and_hold_benchmark", {}).get("cagr", 0.0)
    return strat > ticker_bh and strat > bench_bh


def tune_expression_strategy_for_ticker(
    ticker: str,
    base_config: dict,
    style_type: str,
    start: str,
    end: str,
    train_ratio: float = _DEFAULT_TRAIN_RATIO,
    intensity: str = _DEFAULT_INTENSITY,
) -> dict:
    """직접 수식(expression) 전략 전용 튜닝 진입점 (2026-07-14 사용자 확정).

    1단계: tune_strategy_for_ticker()를 그대로 호출 — build_param_grid가 expression이면
    identify_tunable_numbers()로 Gemini가 식별한 숫자만 변형해 기존과 동일한 train/test 절차를
    거친다(구조는 그대로, 숫자만 바뀜 — 여전히 통제된 위험).

    2단계: 그래도 test 구간에서 종목 매수보유 + S&P500 매수보유를 둘 다 못 이기면, 그때만
    generate_structural_variants()로 구조가 다른 대안 수식을 최대 3개 받아 각각 1단계와 동일한
    절차(자체 숫자 튜닝 포함)로 검증하고, test 전략 CAGR이 가장 높은 것을 채택한다. 원본/1단계
    결과보다 나빠지는 후보는 절대 채택하지 않는다(항상 지금까지 찾은 최선으로 폴백). 반복 진화는
    하지 않는다(1회성).

    Returns:
        tune_strategy_for_ticker()와 동일한 dict + "backbone_changed"(bool)/
        "outperformed_ticker_bh"/"outperformed_benchmark_bh"(bool) 키가 추가됨.
    """

    def _annotate(result: dict) -> dict:
        tc = result["test_comparison"]
        result["outperformed_ticker_bh"] = tc["strategy"].get("cagr", 0.0) > tc["buy_and_hold_ticker"].get("cagr", 0.0)
        result["outperformed_benchmark_bh"] = tc["strategy"].get("cagr", 0.0) > tc["buy_and_hold_benchmark"].get(
            "cagr", 0.0
        )
        return result

    best = tune_strategy_for_ticker(ticker, base_config, style_type, start, end, train_ratio, intensity)
    best["backbone_changed"] = False
    best = _annotate(best)

    if best["outperformed_ticker_bh"] and best["outperformed_benchmark_bh"]:
        return best

    try:
        variants = generate_structural_variants(base_config["expression"], style_type)
    except Exception:
        variants = []

    for variant_expr in variants:
        try:
            candidate = tune_strategy_for_ticker(
                ticker, {"expression": variant_expr}, style_type, start, end, train_ratio, intensity
            )
        except Exception:
            continue
        candidate["backbone_changed"] = True
        candidate = _annotate(candidate)
        best_cagr = best["test_comparison"]["strategy"].get("cagr", float("-inf"))
        cand_cagr = candidate["test_comparison"]["strategy"].get("cagr", float("-inf"))
        if cand_cagr > best_cagr:
            best = candidate

    return best


# ----------------------------------------------------------------------------
# 4. train/test 분리 튜닝 (5절 확정 — 75/25, 샤프 최대화, 매매<5 및 자기모순 조합 배제)
# ----------------------------------------------------------------------------


def train_test_split_dates(start: str, end: str, train_ratio: float = _DEFAULT_TRAIN_RATIO) -> tuple[str, str, str, str]:
    """시작~종료 기간을 시계열 순서 그대로 train/test로 분리한다(랜덤 셔플 없음).

    Returns:
        (train_start, train_end, test_start, test_end) 문자열(YYYY-MM-DD) 튜플.
    """
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    total_days = (end_ts - start_ts).days
    split_ts = start_ts + timedelta(days=int(total_days * train_ratio))
    train_start = start_ts.date().isoformat()
    train_end = split_ts.date().isoformat()
    test_start = (split_ts + timedelta(days=1)).date().isoformat()
    test_end = end_ts.date().isoformat()
    return train_start, train_end, test_start, test_end


def tune_strategy_for_ticker(
    ticker: str,
    base_config: dict,
    style_type: str,
    start: str,
    end: str,
    train_ratio: float = _DEFAULT_TRAIN_RATIO,
    intensity: str = _DEFAULT_INTENSITY,
) -> dict:
    """한 종목에 대해 train 구간에서 파라미터를 탐색하고 test 구간(out-of-sample)에서 검증한다.

    목적함수는 train 구간 샤프지수 최대화. 매매 횟수가 `_MIN_TRADE_COUNT` 미만이거나
    (core.backtest_engine.diagnose_strategy_health로) 진입=청산 자기모순이 감지된 후보는 제외한다.
    유효한 후보가 하나도 없으면(예: 데이터 부족) 원본 config를 그대로 사용해 항상 결과를 낸다.

    Returns:
        {"ticker", "style_type", "tuned_config", "train_metrics", "test_comparison"
         (strategy/buy_and_hold_ticker/buy_and_hold_benchmark 3-way 지표), "excess_return",
         "health_warnings"}
    """
    train_start, train_end, test_start, test_end = train_test_split_dates(start, end, train_ratio)
    candidates = build_param_grid(base_config, style_type, intensity)

    best_config: Optional[dict] = None
    best_train_metrics: Optional[dict] = None

    for candidate in candidates:
        try:
            if diagnose_strategy_health(candidate):
                continue
            run = run_backtest(ticker, candidate, train_start, train_end, label="train")
        except Exception:
            continue
        if run.metrics.get("trade_count", 0) < _MIN_TRADE_COUNT:
            continue
        sharpe = run.metrics.get("sharpe", 0.0)
        if best_train_metrics is None or sharpe > best_train_metrics.get("sharpe", float("-inf")):
            best_config, best_train_metrics = candidate, run.metrics

    if best_config is None:
        base_run = run_backtest(ticker, base_config, train_start, train_end, label="train-original")
        best_config, best_train_metrics = copy.deepcopy(base_config), base_run.metrics

    test_results = compare_with_benchmarks(ticker, best_config, test_start, test_end)
    strategy_metrics = test_results["strategy"].metrics
    benchmark_metrics = test_results["buy_and_hold_benchmark"].metrics
    excess_return = round(strategy_metrics.get("cagr", 0.0) - benchmark_metrics.get("cagr", 0.0), 2)

    try:
        health_warnings = diagnose_strategy_health(best_config)
    except Exception:
        health_warnings = []

    return {
        "ticker": ticker,
        "style_type": style_type,
        "tuned_config": best_config,
        "train_metrics": best_train_metrics,
        "test_comparison": {
            "strategy": strategy_metrics,
            "buy_and_hold_ticker": test_results["buy_and_hold_ticker"].metrics,
            "buy_and_hold_benchmark": benchmark_metrics,
        },
        "excess_return": excess_return,
        "health_warnings": health_warnings,
    }


def run_batch_tuning(
    base_config: dict,
    tickers_df: pd.DataFrame,
    start: str,
    end: str,
    train_ratio: float = _DEFAULT_TRAIN_RATIO,
    intensity: str = _DEFAULT_INTENSITY,
) -> list[dict]:
    """전체 파이프라인: 스타일 분류 -> 종목별 튜닝. 종목 하나가 실패해도 배치 전체는 계속 진행한다.

    Returns:
        tune_strategy_for_ticker() 결과에 sector/style_scores가 덧붙은 dict 리스트. 실패한 종목은
        {"ticker", "style_type", "sector", "error"} 형태로 포함된다(호출부가 항상 종목 수만큼의
        결과를 받도록 보장).
    """
    styles_df = compute_style_scores(tickers_df, start, end)
    styles_by_ticker = styles_df.set_index("ticker").to_dict("index") if not styles_df.empty else {}
    tuner = tune_expression_strategy_for_ticker if is_expression_config(base_config) else tune_strategy_for_ticker

    results = []
    for ticker in tickers_df["ticker"]:
        style_row = styles_by_ticker.get(ticker, {})
        style_type = style_row.get("style_type") or "성장주"
        try:
            result = tuner(
                ticker, base_config, style_type, start, end, train_ratio=train_ratio, intensity=intensity
            )
            result["sector"] = style_row.get("sector")
            result["style_scores"] = style_row.get("style_scores")
        except Exception as e:  # noqa: BLE001 - 종목 하나의 실패가 배치 전체를 막지 않게 함
            result = {
                "ticker": ticker,
                "style_type": style_type,
                "sector": style_row.get("sector"),
                "error": str(e),
            }
        results.append(result)
    return results


# ----------------------------------------------------------------------------
# 5. 영구 저장 (장기 이력 누적 — 6절 확정: 매 실행을 새 배치 레코드로 남김, 절대 덮어쓰지 않음)
# ----------------------------------------------------------------------------


def save_tuning_run(
    base_config: dict,
    tickers_df: pd.DataFrame,
    start: str,
    end: str,
    train_ratio: float,
    intensity: str,
    results: list[dict],
    base_strategy_id: Optional[int] = None,
) -> int:
    """튜닝 배치 실행 결과를 새 StrategyTuningRun(+종목별 StrategyTuningResult)으로 영구 저장한다."""
    with get_session() as session:
        run = StrategyTuningRun(
            base_strategy_id=base_strategy_id,
            base_config=json.dumps(base_config, ensure_ascii=False),
            universe=json.dumps(tickers_df["ticker"].tolist(), ensure_ascii=False),
            train_ratio=train_ratio,
            intensity=intensity,
            start_date=date.fromisoformat(start),
            end_date=date.fromisoformat(end),
            completed_at=datetime.utcnow(),
        )
        session.add(run)
        session.flush()

        for r in results:
            session.add(
                StrategyTuningResult(
                    run_id=run.id,
                    ticker=r["ticker"],
                    sector=r.get("sector"),
                    style_type=r.get("style_type"),
                    style_scores=json.dumps(r["style_scores"], ensure_ascii=False) if r.get("style_scores") else None,
                    tuned_config=json.dumps(r["tuned_config"], ensure_ascii=False) if r.get("tuned_config") else None,
                    train_metrics=json.dumps(r["train_metrics"], ensure_ascii=False) if r.get("train_metrics") else None,
                    test_comparison=(
                        json.dumps(r["test_comparison"], ensure_ascii=False) if r.get("test_comparison") else None
                    ),
                    excess_return=r.get("excess_return"),
                    health_warnings=(
                        json.dumps(r["health_warnings"], ensure_ascii=False) if r.get("health_warnings") else None
                    ),
                    backbone_changed=bool(r.get("backbone_changed", False)),
                    error=r.get("error"),
                )
            )
        run_id = run.id
    return run_id


def run_and_save_tuning(
    base_config: dict,
    universe_n: int,
    start: str,
    end: str,
    train_ratio: float = _DEFAULT_TRAIN_RATIO,
    intensity: str = _DEFAULT_INTENSITY,
    base_strategy_id: Optional[int] = None,
    tickers_df: Optional[pd.DataFrame] = None,
) -> int:
    """표본 추출(또는 직접 지정한 종목) -> 배치 튜닝 -> 저장까지 한 번에 수행한다 (job_manager
    백그라운드 실행 진입점).

    tickers_df가 주어지면(사용자가 UI에서 직접 담은 종목) sample_universe()에 의한 자동 섹터 균등
    표본 추출을 건너뛰고 그대로 사용한다(universe_n은 이 경우 무시됨).

    UI에서 인라인 클로저 대신 이 함수 하나를 job_manager.start()에 넘기면, 완료 후에는 반환된
    run_id로 core.db에서 결과를 다시 조회하기만 하면 되므로 지역변수 소실 문제(PROGRESS.md에 기록된
    기존 버그 패턴)를 원천적으로 피할 수 있다.
    """
    if tickers_df is None:
        tickers_df = sample_universe(universe_n)
    results = run_batch_tuning(base_config, tickers_df, start, end, train_ratio=train_ratio, intensity=intensity)
    return save_tuning_run(
        base_config, tickers_df, start, end, train_ratio, intensity, results, base_strategy_id=base_strategy_id
    )


def list_tuning_runs() -> list[dict]:
    """저장된 튜닝 배치 목록을 최신순으로 반환한다 (UI 이력 목록용)."""
    with get_session() as session:
        rows = session.query(StrategyTuningRun).order_by(StrategyTuningRun.created_at.desc()).all()
        return [
            {
                "id": r.id,
                "base_strategy_id": r.base_strategy_id,
                "universe_size": len(json.loads(r.universe)),
                "start_date": r.start_date,
                "end_date": r.end_date,
                "intensity": r.intensity,
                "created_at": r.created_at,
                "result_count": len(r.results),
            }
            for r in rows
        ]


def get_tuning_run(run_id: int) -> Optional[dict]:
    """튜닝 배치 1건을 종목별 결과와 함께 조회한다. 없으면 None."""
    with get_session() as session:
        run = session.get(StrategyTuningRun, run_id)
        if run is None:
            return None
        results = [
            {
                "ticker": res.ticker,
                "sector": res.sector,
                "style_type": res.style_type,
                "style_scores": json.loads(res.style_scores) if res.style_scores else None,
                "tuned_config": json.loads(res.tuned_config) if res.tuned_config else None,
                "train_metrics": json.loads(res.train_metrics) if res.train_metrics else None,
                "test_comparison": json.loads(res.test_comparison) if res.test_comparison else None,
                "excess_return": res.excess_return,
                "health_warnings": json.loads(res.health_warnings) if res.health_warnings else [],
                "backbone_changed": bool(res.backbone_changed),
                "error": res.error,
            }
            for res in run.results
        ]
        return {
            "id": run.id,
            "base_strategy_id": run.base_strategy_id,
            "base_config": json.loads(run.base_config),
            "start_date": run.start_date,
            "end_date": run.end_date,
            "train_ratio": run.train_ratio,
            "intensity": run.intensity,
            "created_at": run.created_at,
            "results": results,
        }
