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
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from core import gemini_client, market_regime, nl_strategy, point_in_time_universe, screener, valuation
from core.backtest_engine import compare_with_benchmarks, diagnose_strategy_health, run_backtest
from core.db import get_session
from core.expression_engine import ExpressionError, validate_syntax
from core.indicators import sma
from core.macro_cycle import SECTOR_ROTATION
from core.market_data import get_price_history
from core.models import Strategy, StrategyTuningResult, StrategyTuningRun
from core.strategy_engine import describe_condition, is_expression_config, is_staged_config

# ----------------------------------------------------------------------------
# 1. 100종목 섹터 균등 표본
# ----------------------------------------------------------------------------


def sample_universe(
    n: int = 100,
    use_cache: bool = True,
    random_seed: Optional[int] = None,
    as_of_date: Optional[str | date | datetime] = None,
) -> pd.DataFrame:
    """S&P500 유니버스에서 섹터별로 균등 배분된 n종목 표본을 추출한다.

    시총 상위 n개를 그냥 뽑으면 빅테크 섹터로 편중되어(STRATEGY_TUNING_ENGINE_SPEC.md 5절 결정)
    섹터별 스타일 비교가 무의미해지므로, 섹터마다 기본 할당량(n // 섹터수)을 배분하고 나머지는
    섹터 전체 시가총액 합이 큰 섹터부터 1개씩 더 배분한다.

    random_seed가 None이면(기본값) 섹터별 할당량을 시가총액 상위 순으로 결정론적으로 채운다(기존
    동작 그대로 — 대화형 UI에서 같은 n을 여러 번 눌러도 항상 같은 표본이 나와야 함). random_seed를
    주면(2026-07-15 추가, 야간 반복 미세튜닝에서 매번 다른 표본을 탐색하기 위함) 섹터별 할당량 안에서
    시드 기반 무작위 추출로 바꾼다 — 그래도 재현 가능하도록 같은 시드면 항상 같은 표본이 나온다.

    as_of_date를 주면(2026-07-17 추가, survivorship bias 완화 — PROGRESS.md 백로그 1번)
    "지금 시점 S&P500"이 아니라 `core.point_in_time_universe`가 제공하는 그 시점 실제 편입종목
    목록으로 후보를 제한한다(`core/point_in_time_universe.py` 참고, fja05680/sp500 CSV 기반).
    이렇게 하면 학습 시작 시점 이후 지수에서 편출된 종목(예: GE, 인텔)도 표본에 남을 수 있다.
    단, 상장폐지까지 간 종목은 yfinance 자체에 가격 데이터가 없어 여전히 빠질 수 있다(알려진 한계,
    PROGRESS.md 백로그 1번 참고). None이면(기본값) 기존과 동일하게 현재 S&P500 전체가 후보다.

    Returns:
        columns: ticker, sector(GICS 영문), market_cap. 시가총액 내림차순 정렬.
    """
    universe = screener.get_universe(use_cache=use_cache)

    if as_of_date is not None:
        pit_tickers = set(point_in_time_universe.get_constituents_as_of(as_of_date))
        current_sector_map = dict(zip(universe["Symbol"], universe["Sector"]))
        universe = pd.DataFrame(
            {
                "Symbol": sorted(pit_tickers),
                "Sector": [current_sector_map.get(t, "Unknown") for t in sorted(pit_tickers)],
            }
        )

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

    picked = []
    for s in sectors:
        sector_df = df[df["sector"] == s]
        quota = min(quotas.get(s, base_quota), len(sector_df))
        if random_seed is None:
            picked.append(sector_df.sort_values("market_cap", ascending=False).head(quota))
        else:
            picked.append(sector_df.sample(n=quota, random_state=random_seed))
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
    # 볼린저 응용 매매법 4종(2026-07-15 신규 지표: bbw_squeeze_release/double_pattern/
    # rsi_divergence)이 쓰는 롤링 윈도우 봉 수. 기존 이평 기간류와 같은 스타일 배수로 스케일한다.
    "lookback",
    "hold_bars",
    "band_period",
    "pivot_lookback",
    "pattern_window",
    "rsi_period",
}
_THRESHOLD_LIKE_KEYS = {"value", "level"}
# 항상 양수인 작은 스케일 비율/승수류. RSI 0~100 스케일용 _THRESHOLD_LIKE_KEYS의 delta 로직(10.0 또는
# 0.1 고정폭)을 그대로 쓰면 volume_mult(기본 1.5)가 delta=10.0을 맞아 [0, 11.5]처럼 말이 안 되는
# 범위가 나오므로, 원래 값에 비례하는 폭으로 흔든다(항상 양수 유지).
_RATIO_LIKE_KEYS = {"threshold", "volume_mult"}

_CATEGORY_LABELS = {"period": "기간", "band": "볼린저폭", "threshold": "임계값", "ratio": "비율", "weight": "비중배분"}
STYLE_TYPES: list[str] = list(_STYLE_PERIOD_MULTIPLIERS.keys())

_MIN_WEIGHTED_STAGES = 2  # stage가 1개뿐이면 정규화 시 항상 1.0으로 고정돼 탐색할 의미가 없음


def _key_category(key: str) -> Optional[str]:
    """숫자 파라미터 키를 4개 분류(기간/볼린저폭/임계값/비율) 중 하나로 판별한다. 튜닝 대상이
    아니면 None (build_param_grid와 describe_tunable_params가 같은 분류 기준을 공유)."""
    if key in _PERIOD_LIKE_KEYS:
        return "period"
    if key in {"std_dev", "band_std"}:
        return "band"
    if key in _THRESHOLD_LIKE_KEYS:
        return "threshold"
    if key in _RATIO_LIKE_KEYS:
        return "ratio"
    return None


def _value_range_for_style(category: str, val: float, lo_mult: float, hi_mult: float) -> tuple[float, float]:
    """분류별 (하한, 상한) 탐색 범위. period만 스타일 배수(lo_mult/hi_mult)를 실제로 사용하고,
    나머지 분류는 스타일과 무관하게 원본값 기준 고정 폭으로 흔든다(build_param_grid와 동일 공식)."""
    if category == "period":
        lo = max(2, round(val * lo_mult))
        hi = max(lo + 1, round(val * hi_mult))
        return lo, hi
    if category == "band":
        return max(0.5, round(val - 0.5, 1)), min(4.0, round(val + 0.5, 1))
    if category == "threshold":
        delta = 10.0 if val > 1 else 0.1
        return max(0.0, round(val - delta, 2)), round(val + delta, 2)
    if category in ("ratio", "weight"):
        # weight(stage 진입/청산 비중)도 같은 폭으로 독립적으로 흔든다 — 실제 채택 시 stage 목록
        # 단위 합계가 1.0이 되도록 되돌리는 재정규화는 build_param_grid의 _normalize_stage_weights가
        # 후보 생성 후 별도로 처리한다(사용자 확정 — 배분 비율만 탐색하고 총 진입/청산 비중은 항상
        # 100%로 고정해 레버리지/미투자 왜곡을 막음).
        delta = max(round(val * 0.3, 3), 0.02)
        return max(0.01, round(val - delta, 3)), round(val + delta, 3)
    raise ValueError(f"알 수 없는 분류: {category}")


def _round_original(category: str, val: float) -> float:
    if category == "period":
        return int(round(val))
    if category == "band":
        return round(val, 1)
    if category == "threshold":
        return round(val, 2)
    if category in ("ratio", "weight"):
        return round(val, 3)
    raise ValueError(f"알 수 없는 분류: {category}")


def _weight_stage_lists(base_config: dict, path: tuple = ()) -> dict[tuple, list[tuple[int, float]]]:
    """entry_stages/exit_stages 중 weight가 숫자인 stage가 2개 이상인 목록만 골라
    {stage_path: [(stage_index, weight), ...]}로 반환한다 (탐색 축 생성과 재정규화가 공유하는 대상
    판별 로직 — 두 곳이 서로 다른 stage 집합을 고르면 재정규화가 탐색하지 않은 stage까지 건드리게 됨).

    복합(combine+strategies) 전략은 하위 전략마다 독립된 entry_stages/exit_stages를 가질 수 있어
    "strategies" 리스트를 재귀적으로 내려가며 각 하위 전략의 stage_key 앞에 위치 경로(예:
    ("strategies", 0, "entry_stages"))를 붙여 키로 쓴다 — 상위 트리에서 다시 같은 자리를 찾을 수
    있어야 _weight_axis_values/_normalize_stage_weights가 정확한 stage를 건드릴 수 있다."""
    result: dict[tuple, list[tuple[int, float]]] = {}
    for stage_key in ("entry_stages", "exit_stages"):
        stages = base_config.get(stage_key) or []
        numeric = [
            (si, stage["weight"])
            for si, stage in enumerate(stages)
            if isinstance(stage.get("weight"), (int, float)) and not isinstance(stage.get("weight"), bool)
        ]
        if len(numeric) >= _MIN_WEIGHTED_STAGES:
            result[(*path, stage_key)] = numeric
    strategies = base_config.get("strategies")
    if isinstance(strategies, list):
        for si, sub in enumerate(strategies):
            if isinstance(sub, dict):
                result.update(_weight_stage_lists(sub, (*path, "strategies", si)))
    return result


def _weight_axis_values(base_config: dict) -> list[tuple[tuple, str, list]]:
    """build_param_grid가 쓰는 (path, key, values) 축 형식으로 각 stage의 weight 탐색 후보를 만든다.
    실제 채택 시 합계를 1.0으로 되돌리는 정규화는 여기서 하지 않는다(_normalize_stage_weights가
    후보 생성 후 담당) — 여기서는 다른 비율류 파라미터와 동일하게 원본 ±30% 축만 만든다."""
    axes: list[tuple[tuple, str, list]] = []
    for stage_path, numeric_stages in _weight_stage_lists(base_config).items():
        for si, val in numeric_stages:
            lo, hi = _value_range_for_style("weight", val, 0.0, 0.0)  # weight는 스타일 배수 무관
            values = sorted({lo, _round_original("weight", val), hi})
            axes.append(((*stage_path, si), "weight", values))
    return axes


def _normalize_stage_weights(candidate: dict) -> None:
    """entry_stages/exit_stages 각각 안의 weight 합이 1.0(=100% 진입/청산)이 되도록 제자리에서
    재조정한다. weight를 서로 독립적으로 흔들면 합이 깨져(예: 총 93%만 투자되거나 108% 레버리지)
    "몇 단계에 걸쳐 전량 진입/청산"이라는 전략 의미가 왜곡되므로, 배분 비율만 탐색하고 총량은 항상
    100%로 고정한다(2026-07-15 사용자 확정 — 원본 합계가 1.0이 아닌 경우에도 튜닝 후에는 항상
    1.0으로 맞춘다). 복합 전략은 하위 전략별로 독립적으로 정규화한다."""
    for stage_path, numeric_stages in _weight_stage_lists(candidate).items():
        total = sum(w for _, w in numeric_stages)
        if total <= 0:
            continue
        stages = _get_by_path(candidate, stage_path)
        for si, w in numeric_stages:
            stages[si]["weight"] = round(w / total, 4)


def _format_path(path: tuple) -> str:
    """(path 튜플)을 "entry_stages[0].conditions[1]" 형태의 읽기 쉬운 문자열로 변환 (미리보기 UI용)."""
    parts: list[str] = []
    for key in path:
        if isinstance(key, int):
            parts[-1] = f"{parts[-1]}[{key}]"
        else:
            parts.append(str(key))
    return ".".join(parts)


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
    strategies = config.get("strategies")
    if isinstance(strategies, list):
        for si, sub in enumerate(strategies):
            if isinstance(sub, dict):
                yield from _iter_condition_paths(sub, (*path, "strategies", si))


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
            category = _key_category(key)
            if category is None:
                continue
            lo, hi = _value_range_for_style(category, val, lo_mult, hi_mult)
            values = sorted({lo, _round_original(category, val), hi})
            axis_values.append((path, key, values))

    axis_values.extend(_weight_axis_values(base_config))

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
        _normalize_stage_weights(candidate)
        candidates.append(candidate)

    original = copy.deepcopy(base_config)
    if original not in candidates:
        candidates.append(original)  # 튜닝이 원본보다 나빠지지 않게 항상 비교 기준으로 포함

    return candidates


def describe_tunable_params(base_config: dict) -> list[dict]:
    """실행 전 미리보기용 — build_param_grid가 실제로 건드릴 숫자 파라미터와, 6개 스타일별 예상
    탐색 범위를 후보를 만들지 않고 계산만 한다(같은 분류/범위 공식을 재사용하므로 build_param_grid
    결과와 항상 일치). JSON 스키마(레짐/1:2:6) 전용 — expression은 Gemini 판별이 필요해
    describe_tunable_params_expression()으로 분리.

    weight 항목은 표시된 범위 그대로 채택되지 않는다 — build_param_grid가 후보 생성 후 같은
    entry_stages/exit_stages 안 weight 합계를 항상 1.0(=100%)으로 재정규화하므로, 실제 채택되는
    값은 여기 표시된 (하한, 상한) 부근에서 다른 stage의 채택값에 따라 소폭 밀릴 수 있다.

    Returns:
        [{"path", "indicator", "key", "original", "category", "style_ranges": {스타일: (하한, 상한)}}, ...]
    """
    if "expression" in base_config:
        return []
    rows = []
    for path, cond in _iter_condition_paths(base_config):
        indicator = cond.get("indicator", "")
        for key, val in cond.items():
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                continue
            category = _key_category(key)
            if category is None:
                continue
            style_ranges = {
                style: _value_range_for_style(category, val, lo_mult, hi_mult)
                for style, (lo_mult, hi_mult) in _STYLE_PERIOD_MULTIPLIERS.items()
            }
            rows.append(
                {
                    "path": _format_path(path),
                    "indicator": indicator,
                    "key": key,
                    "original": _round_original(category, val),
                    "category": _CATEGORY_LABELS[category],
                    "style_ranges": style_ranges,
                }
            )

    for stage_path, numeric_stages in _weight_stage_lists(base_config).items():
        for si, val in numeric_stages:
            style_ranges = {style: _value_range_for_style("weight", val, 0.0, 0.0) for style in STYLE_TYPES}
            rows.append(
                {
                    "path": _format_path((*stage_path, si)),
                    "indicator": "",
                    "key": "weight",
                    "original": _round_original("weight", val),
                    "category": _CATEGORY_LABELS["weight"],
                    "style_ranges": style_ranges,
                }
            )
    return rows


# train/test 분리에 쓰는 공용 상수. 아래 3b절의 tune_expression_strategy_for_ticker()가 기본 인자
# 값으로 참조하므로(함수 정의 시점에 평가됨) 그 정의보다 앞에 있어야 한다 — 원래 "4. train/test
# 분리 튜닝" 절에 있었으나 3b절 추가로 앞당김(NameError 방지, 값 자체는 그대로).
_DEFAULT_TRAIN_RATIO = 0.75
_MIN_TRADE_COUNT = 5
_SWING_MAX_HOLDING_DAYS = 126  # 스윙 트레이딩 보유기간 상한(약 6개월 거래일, SPEC 15절) — tune_strategy_for_group(max_holding_days=...)에 넘기는 권장 기본값


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
#
# (2026-07-15 갱신) 이 절의 숫자 식별/치환 로직(identify_tunable_numbers, _build_expression_param_
# grid)은 그대로 유효하지만, "종목 하나에 대해 1단계->2단계를 진행하는" 진입점이었던
# tune_expression_strategy_for_ticker()는 제거되었다. 튜닝 방식이 종목별 개별 탐색에서 스타일
# 그룹 단위 풀링 탐색으로 바뀌면서(4b절 tune_strategy_for_group 참고), 그 진입점 역할은
# tune_strategy_for_group()이 대신하고, 구조 변경 escape hatch는 레짐/1:2:6까지 포함하도록
# 일반화된 generate_structural_variants_for_config()(3c절)로 옮겨졌다.
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


def _expression_style_range(
    original: float, suggested_min: float, suggested_max: float, lo_mult: float, hi_mult: float
) -> tuple[float, float]:
    """Gemini가 제안한 의미론적 범위와 기존 스타일 배수 범위를 함께 반영(둘 다 벗어나지 않게 더
    넓은 쪽을 취함 — 스타일 방향성은 유지하면서 Gemini의 의미 판단도 존중). _build_expression_
    param_grid와 describe_tunable_params_expression이 동일한 공식을 공유한다."""
    lo = min(suggested_min, original * lo_mult) if original else suggested_min
    hi = max(suggested_max, original * hi_mult) if original else suggested_max
    return round(lo, 2), round(hi, 2)


def describe_tunable_params_expression(tunables: list[dict]) -> list[dict]:
    """실행 전 미리보기용 — identify_tunable_numbers()가 이미 식별한 숫자들에 대해, 6개 스타일별
    예상 탐색 범위를 계산한다(_build_expression_param_grid와 동일 공식). Gemini 호출(비용 발생)은
    이 함수가 아니라 identify_tunable_numbers()가 하므로, 호출부가 결과를 캐시해 재사용해야 한다.

    Returns:
        [{"text", "role", "original", "style_ranges": {스타일: (하한, 상한)}}, ...]
    """
    rows = []
    for t in tunables:
        original = t["value"]
        style_ranges = {
            style: _expression_style_range(original, t["suggested_min"], t["suggested_max"], lo_mult, hi_mult)
            for style, (lo_mult, hi_mult) in _STYLE_PERIOD_MULTIPLIERS.items()
        }
        rows.append({"text": t["text"], "role": t.get("role", ""), "original": original, "style_ranges": style_ranges})
    return rows


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
        lo, hi = _expression_style_range(original, t["suggested_min"], t["suggested_max"], lo_mult, hi_mult)
        values = sorted({lo, round(float(original), 2), hi})
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


# ----------------------------------------------------------------------------
# 3c. "구조 자체를 바꾸는" escape hatch를 레짐(AND/OR)·1:2:6 단계별 전략까지 확장
# (2026-07-15 사용자 확정) — 위 3b절에서는 직접 수식 전략에만 있던 마지막 수단을, 그룹 단위
# 풀링 트레이닝(아래 4b절)으로도 test 구간에서 벤치마크를 못 이길 때 모든 전략 유형에 쓸 수 있게
# 한다. "백본 유지" 원칙 자체가 이 escape hatch에서는 예외라는 점, 1회성(반복 진화 없음)이라는
# 원칙은 3b절과 동일하게 유지한다. nl_strategy.py가 이미 검증해둔 INDICATOR_CONFIG_SCHEMA /
# STAGED_INDICATOR_CONFIG_SCHEMA를 그대로 재사용해 Gemini가 항상 실행 가능한 구조로만 응답하게
# 강제한다(새 스키마를 중복 정의하지 않음).
# ----------------------------------------------------------------------------

_STRUCTURAL_VARIANT_JSON_SYSTEM_PROMPT = """\
너는 퀀트 트레이딩 전략을 개선하는 어시스턴트다.

사용자가 원본 전략의 조건(JSON)과 종목 스타일을 준다. 이 전략과 같은 매매 아이디어를 유지하되,
지표 구성이나 조건 로직이 다른 대안을 제안해라 — 숫자 파라미터만 바꾸는 게 아니라 지표를
교체하거나, 조건을 추가/삭제하거나, and/or 결합을 바꾸는 식으로 구조 자체가 달라야 한다.
종목 스타일에 맞는 방향으로 제안한다(예: 주도주는 짧은 홀딩·모멘텀 추종, 방어주는 낮은 매매빈도).
1:2:6 단계별 전략이면 단계 수와 weight(비중 배분) 구조는 그대로 두고 각 단계의 조건(지표 구성)만
바꿔라 — weight 배분 자체를 바꾸는 것은 이 요청의 범위가 아니다.
"""


def _variants_wrapper_schema(item_schema: dict) -> dict:
    """단일 전략 스키마를 "여러 개를 배열로 반환"하는 스키마로 감싼다 (1회 호출로 n개를 받기 위함)."""
    return {"type": "object", "properties": {"variants": {"type": "array", "items": item_schema}}, "required": ["variants"]}


def _generate_structural_variants_json(
    base_config: dict, style_type: str, schema_note: str, item_schema: dict, required_keys: tuple[str, ...], n: int
) -> list[dict]:
    if not gemini_client.has_api_key():
        return []
    contents = (
        f"원본 전략 조건({schema_note}, JSON): {json.dumps(base_config, ensure_ascii=False)}\n"
        f"종목 스타일: {style_type}\n\n이 전략과 같은 매매 아이디어를 유지하되 지표 구성/조건 로직이 "
        f"다른 대안을 최대 {n}개 제안해줘."
    )
    try:
        response = gemini_client.generate_content(
            models=gemini_client.COMPLEX_TASK_MODELS,
            contents=contents,
            system_instruction=_STRUCTURAL_VARIANT_JSON_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=_variants_wrapper_schema(item_schema),
        )
        text = response.text
        if not text:
            return []
        raw_variants = json.loads(text).get("variants", [])
    except Exception:
        return []

    valid: list[dict] = []
    for v in raw_variants:
        if not isinstance(v, dict) or not all(k in v for k in required_keys):
            continue
        valid.append(v)
        if len(valid) >= n:
            break
    return valid


# ----------------------------------------------------------------------------
# 3d. 결정론적 국면 스위치 변형 (직접 수식 전용, SPEC 12절 — 2026-07-15)
#
# 11.3/9절 데모에서 공통으로 드러난 문제: 원본 백본(주로 평균회귀형 진입)은 조정 없이 밀어 올리는
# 강세장에서 신호가 거의 안 뜨거나(AND 결합) 반등 초반만 먹고 나온다(대칭적으로 이른 청산). 근본
# 원인은 "국면 무감각" — 전체 기간에 같은 조건 하나를 그대로 적용하기 때문이다.
#
# core.expression_engine에 이미 sma/highest가 있어 새 지표 없이 "(A and B) or (C and D)" 형태의
# 국면 스위치를 한 줄 수식으로 표현할 수 있다. 단 이 중첩 논리는 직접 수식 스키마에서만 가능하고
# (레짐/1:2:6은 flat AND/OR라 표현 불가) — 9절과 같은 이유로 이번에도 직접 수식 전략에만 적용한다.
#
# Gemini의 창의적 제안(위 3c절)과 달리 이 변형은 고정 템플릿으로 결정론적으로 생성한다(재현 가능,
# 매번 다른 제안이 나오지 않음). 생성된 수식의 숫자(200/60 포함)는 기존 _build_expression_param_
# grid()가 원본 진입 조건의 숫자들과 함께 그대로 스타일별로 튜닝하므로 별도 튜닝 경로가 필요 없다.
# ----------------------------------------------------------------------------

_REGIME_TREND_MA_PERIOD = 200  # 종목 자체 상승추세 판정 기준 이동평균 기간
_REGIME_BREAKOUT_LOOKBACK = 60  # 추세추종 진입에 쓰는 신고가 롤링 구간(일)


def _build_regime_switch_variant(
    expression: str,
    trend_ma_period: int = _REGIME_TREND_MA_PERIOD,
    breakout_lookback: int = _REGIME_BREAKOUT_LOOKBACK,
) -> Optional[str]:
    """원본 진입 조건에 결정론적 국면 스위치를 씌운다: 종목이 자체 상승추세(종가가 이동평균 위)면
    신고가 돌파(추세추종)로 진입하고, 그 외에는 원본 진입 조건을 그대로 쓴다.

    결합 결과가 실행 불가능하면(원본 조건 자체가 이미 유효했다면 사실상 발생하지 않지만 방어적으로)
    None을 반환해 호출부가 이 후보를 조용히 건너뛰게 한다.
    """
    candidate = (
        f"(close > sma(close, {trend_ma_period}) and close >= highest(close, {breakout_lookback})) "
        f"or (close <= sma(close, {trend_ma_period}) and ({expression}))"
    )
    try:
        validate_syntax(candidate)
    except ExpressionError:
        return None
    return candidate


def generate_structural_variants_for_config(
    base_config: dict, style_type: str, n: int = _MAX_STRUCTURAL_VARIANTS
) -> list[dict]:
    """base_config와 같은 스키마 유형(expression/레짐/1:2:6)의 구조가 다른 대안을 최대 n개 제안받는다.

    tune_strategy_for_group()이 그룹 단위 튜닝으로도 test 구간을 못 이길 때만 호출하는 escape
    hatch다. 직접 수식은 기존 generate_structural_variants()(Gemini 제안)에 결정론적 국면 스위치
    변형(위 3d절)을 하나 더 추가하고, 레짐/1:2:6은 nl_strategy.py의 기존 스키마를 재사용한 JSON
    기반 생성으로 대응한다.
    """
    if is_expression_config(base_config):
        expression = base_config.get("expression", "")
        variants = [{"expression": v} for v in generate_structural_variants(expression, style_type, n)]
        regime_variant = _build_regime_switch_variant(expression)
        if regime_variant is not None:
            variants.append({"expression": regime_variant})
        return variants
    if is_staged_config(base_config):
        return _generate_structural_variants_json(
            base_config, style_type, "1:2:6 단계별",
            nl_strategy.STAGED_INDICATOR_CONFIG_SCHEMA["properties"]["indicator_config"],
            ("entry_stages", "exit_stages"), n,
        )
    return _generate_structural_variants_json(
        base_config, style_type, "레짐(AND/OR)",
        nl_strategy.INDICATOR_CONFIG_SCHEMA["properties"]["indicator_config"],
        ("logic", "conditions"), n,
    )


def _outperforms_both_benchmarks(test_comparison: dict) -> bool:
    """test 구간에서 전략이 종목 매수보유 + S&P500 매수보유를 CAGR 기준으로 둘 다 이겼는지."""
    strat = test_comparison.get("strategy", {}).get("cagr", 0.0)
    ticker_bh = test_comparison.get("buy_and_hold_ticker", {}).get("cagr", 0.0)
    bench_bh = test_comparison.get("buy_and_hold_benchmark", {}).get("cagr", 0.0)
    return strat > ticker_bh and strat > bench_bh


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


# ----------------------------------------------------------------------------
# 4b. 스타일 그룹 단위 풀링 트레이닝 (2026-07-15 사용자 확정 — 튜닝 방식 변경)
#
# 기존에는 종목마다 따로 파라미터를 탐색했다(위 tune_strategy_for_ticker를 종목 수만큼 독립 호출).
# 이제는 먼저 종목을 스타일(주도주/성장주/가치주/경기민감주/경기방어주/퀄리티 컴파운더)로 나누고,
# "이 스타일 그룹에 공통으로 잘 맞는 설정 하나"를 그 그룹에 속한 종목 전체의 train 데이터를 함께
# 써서 찾는다. 같은 그룹의 종목들은 결과적으로 tuned_config가 서로 동일해진다 — 종목 하나에만
# 우연히 잘 맞는(과최적화된) 설정이 아니라 그 스타일 전반에 통하는 설정을 찾는 것이 목적이기 때문.
#
# "어떻게 해서든 이기게" 요청에 대해서는 사용자에게 직접 확인해 아래 방향으로 확정했다:
#   - train/test 분리는 절대 어기지 않는다. test(out-of-sample) 구간 성과는 최종 검증에만 쓰고,
#     후보 선택(어떤 파라미터가 "그룹에 좋은가")에는 test 구간 데이터를 전혀 참조하지 않는다.
#     그래야 여기서 나온 "이겼다"는 결과가 실전(라이브)에서도 재현될 가능성이 있다. test 구간
#     성과를 선택 기준에 섞으면 답을 보고 답을 고르는 것(데이터 스누핑)이 되어, 이 백테스트에서는
#     항상 이긴 것처럼 보이지만 실제 미래 성과와는 무관해진다 — 그래서 이 방식은 채택하지 않았다.
#   - 대신 "탐색을 최대한 넓혀서" 이길 확률을 높인다: ①그룹 전체에서 평균 샤프지수를 최대화하는
#     숫자 파라미터를 찾고(아래 _select_best_group_config), ②그래도 그룹 평균이 test 구간에서
#     S&P500을 못 이기면, 3c절로 확장된 generate_structural_variants_for_config()로 레짐/1:2:6/
#     직접수식 관계없이 구조가 다른 대안을 1회성으로 시도한다(반복 진화는 안 함 — 3b/3c절과 동일한
#     과최적화 통제 원칙).
#   - 그래도 못 이기는 그룹/종목이 있으면 숨기지 않고 정직하게 보고한다(health_warnings와 별개로
#     UI가 종목별 CAGR을 그대로 보여주므로 자동으로 드러남).
# ----------------------------------------------------------------------------

_MIN_GROUP_COVERAGE_RATIO = 0.5  # 후보가 그룹을 대표한다고 인정하려면 최소 이 비율 이상 종목에서 유효해야 함
_WALK_FORWARD_FOLDS = 3  # train 구간을 몇 개의 하위 구간(폴드)으로 나눠 독립 평가할지 (SPEC 11.2절)
_ROBUSTNESS_PENALTY_WEIGHT = 0.5  # 폴드 간 표준편차에 곱하는 패널티 가중치 (뾰족한 피크 후보 배제)
_TRAINING_REGIMES = ["약세장", "강세장", "횡보장"]  # SPEC 13절 — 스타일 그룹마다 국면별로 따로 트레이닝(2026-07-17부터 3분류)


def _group_min_required(group_size: int) -> int:
    """최소 커버리지 개수 (올림 — 예: 3개의 50%는 최소 2개 필요). 그룹 종목 수/폴드 개수 양쪽에 공용."""
    return max(1, math.ceil(group_size * _MIN_GROUP_COVERAGE_RATIO))


def _split_into_folds(start: str, end: str, n_folds: int) -> list[tuple[str, str]]:
    """구간을 n_folds개의 연속된 균등 하위 구간(폴드)으로 나눈다 (겹침 없이 앞에서부터 순서대로).

    마지막 폴드는 나눗셈 나머지를 흡수해 정확히 end까지 이어지게 한다.
    """
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    total_days = max(1, (end_ts - start_ts).days)
    fold_days = max(1, total_days // n_folds)
    folds = []
    for i in range(n_folds):
        fold_start = start_ts + timedelta(days=i * fold_days)
        fold_end = end_ts if i == n_folds - 1 else fold_start + timedelta(days=fold_days - 1)
        folds.append((fold_start.date().isoformat(), fold_end.date().isoformat()))
    return folds


def _candidate_group_train_sharpe(
    tickers: list[str], candidate: dict, train_start: str, train_end: str, max_holding_days: Optional[int] = None
) -> Optional[float]:
    """후보 config를 그룹 전체 종목의 train 구간에 적용해 평균 샤프지수를 계산한다.

    한 종목에만 잘 맞고 나머지에는 안 맞는(과최적화된) 후보를 그룹 대표로 뽑지 않기 위해, 그룹의
    최소 절반 이상 종목에서 매매 횟수 조건을 만족하는 유효한 결과가 나와야만 점수를 매긴다
    (부족하면 None을 반환해 이 후보를 탈락시킨다).

    max_holding_days가 주어지면(스윙 트레이딩 모드, SPEC 15절) 그 상한을 넘겨 강제 청산한 결과로
    샤프지수를 계산한다 — 탐색 단계부터 "6개월 안에 강제로 잘렸을 때" 성과로 후보를 고르게 된다.
    """
    sharpes = []
    for ticker in tickers:
        try:
            run = run_backtest(
                ticker, candidate, train_start, train_end, label="train", max_holding_days=max_holding_days
            )
        except Exception:
            continue
        if run.metrics.get("trade_count", 0) < _MIN_TRADE_COUNT:
            continue
        sharpes.append(run.metrics.get("sharpe", 0.0))
    if len(sharpes) < _group_min_required(len(tickers)):
        return None
    return sum(sharpes) / len(sharpes)


def _candidate_group_walkforward_score(
    tickers: list[str], candidate: dict, folds: list[tuple[str, str]], max_holding_days: Optional[int] = None
) -> Optional[dict]:
    """후보를 폴드마다 독립적으로 평가해(각 폴드의 그룹 평균 샤프지수) "평균 − 표준편차×가중치"로
    점수를 매긴다(SPEC 11.2절 — 다중 구간 워크포워드 + 안정성 점수). 특정 폴드(특정 시기)에만
    우연히 맞는 후보(폴드 간 표준편차가 큰, 뾰족한 피크 = 전형적 overfitting 신호)에 패널티를 줘서
    여러 시기에 걸쳐 일관되게 괜찮은("평평한 고원") 후보를 우선한다. 유효 폴드 수가 최소 커버리지
    미달이면 None(그룹 커버리지와 동일한 `_group_min_required` 기준 재사용).
    """
    fold_sharpes = [
        s
        for s in (
            _candidate_group_train_sharpe(tickers, candidate, fs, fe, max_holding_days) for fs, fe in folds
        )
        if s is not None
    ]
    if len(fold_sharpes) < _group_min_required(len(folds)):
        return None
    mean_sharpe = sum(fold_sharpes) / len(fold_sharpes)
    variance = sum((s - mean_sharpe) ** 2 for s in fold_sharpes) / len(fold_sharpes)
    std_sharpe = math.sqrt(variance)
    score = mean_sharpe - _ROBUSTNESS_PENALTY_WEIGHT * std_sharpe
    return {
        "fold_sharpes": [round(s, 3) for s in fold_sharpes],
        "mean_sharpe": round(mean_sharpe, 3),
        "std_sharpe": round(std_sharpe, 3),
        "score": round(score, 3),
    }


def _select_best_group_config_walkforward(
    tickers: list[str], candidates: list[dict], folds: list[tuple[str, str]], max_holding_days: Optional[int] = None
) -> tuple[Optional[dict], list[dict]]:
    """폴드 목록(연속된 날짜 구간들)을 독립적으로 평가해, 폴드 간 점수(위 함수)가 가장 높은 후보를
    고른다. 단일 구간 평가보다 특정 시기에만 맞는 과최적화 후보를 더 잘 걸러낸다 — 단, 이게 "미래
    시장을 이긴다"는 보장은 아니다(SPEC 11.3절 실증 데모: 더 안정적인 후보를 골랐음에도 최종
    홀드아웃에서는 원본보다 나빴던 사례 참고).

    folds는 달력을 등분한 구간(`_split_into_folds`, 국면 구분 없는 기존 방식)일 수도, 실제 국면
    구간(`_train_folds_for_regime`, SPEC 13.4절)일 수도 있다 — 이 함수는 폴드가 어떻게 만들어졌는지
    모른 채 순서대로 독립 평가만 한다.

    Returns:
        (best_config 또는 유효 후보가 없으면 None, 점수 내림차순 트레일 리스트). 트레일의 각 항목은
        {"config", "fold_sharpes", "mean_sharpe", "std_sharpe", "score"} — 튜닝 리포트(UI)가 그대로
        표로 보여줘 "어떤 파라미터를 왜 채택했는지" 근거를 남긴다.
    """
    trail: list[dict] = []
    for candidate in candidates:
        try:
            if diagnose_strategy_health(candidate):
                continue  # 진입=청산 자기모순 등 구조적 결함은 그룹 대표 후보에서 배제 (종목과 무관한 정적 특성)
        except Exception:
            continue
        scored = _candidate_group_walkforward_score(tickers, candidate, folds, max_holding_days)
        if scored is None:
            continue
        trail.append({"config": candidate, **scored})

    trail.sort(key=lambda t: t["score"], reverse=True)
    best_config = trail[0]["config"] if trail else None
    return best_config, trail


def _evaluate_group_config_on_test(
    tickers: list[str], config: dict, test_start: str, test_end: str, max_holding_days: Optional[int] = None
) -> dict[str, dict]:
    """확정된 그룹 config를 종목별로 test(out-of-sample) 구간에서 개별 평가한다 (선택에는 관여하지
    않고 최종 검증/보고 전용 — train/test 분리 원칙)."""
    per_ticker = {}
    for ticker in tickers:
        try:
            comparison = compare_with_benchmarks(ticker, config, test_start, test_end, max_holding_days=max_holding_days)
            per_ticker[ticker] = {
                "strategy": comparison["strategy"].metrics,
                "buy_and_hold_ticker": comparison["buy_and_hold_ticker"].metrics,
                "buy_and_hold_benchmark": comparison["buy_and_hold_benchmark"].metrics,
            }
        except Exception as e:  # noqa: BLE001 - 종목 하나의 조회 실패가 그룹 전체를 막지 않게 함
            per_ticker[ticker] = {"error": str(e)}
    return per_ticker


def _train_folds_for_regime(train_start: str, train_end: str, regime: str) -> list[tuple[str, str]]:
    """train 구간 안에서 실제로 해당 국면(약세장/강세장)이었던 연속 구간들을 워크포워드 폴드로
    변환한다 (SPEC 13.4절 — core.market_regime.historical_regime_segments 재사용, 새 선택 로직
    불필요). 20 거래일 미만인 짧은 구간은 이미 그 함수에서 걸러진다."""
    segments = market_regime.historical_regime_segments(train_start, train_end)
    return segments.get(regime, [])


def _evaluate_group_config_on_regime_matched_test(
    tickers: list[str], config: dict, test_start: str, test_end: str, regime: str, max_holding_days: Optional[int] = None
) -> Optional[dict]:
    """test 구간 안에서 config가 학습된 국면과 같은 국면의 가장 긴 연속 구간 하나만 골라 평가한다
    (SPEC 13.6절, 2026-07-17 정정 — 이제 tune_strategy_for_group의 주 test 평가 그 자체다.
    "약세장에서 학습한 설정을 강세장 데이터로 검증할 이유가 없다"는 사용자 확정 원칙).

    여러 조각을 이어붙이지(stitch) 않고 가장 긴 단일 구간만 쓴다 — 불연속 구간을 이으면 그 사이
    갭에서 포지션이 어떻게 되는지 정의가 모호해져 4b/11절의 정직성 원칙을 해칠 위험이 있다. 이
    함수 자체는 선택(어떤 파라미터를 채택할지)에 관여하지 않는 순수 평가용이다(선택은 train 구간
    워크포워드 점수로만 한다, 4b/11절 원칙 유지). 해당 국면 구간이 test 안에 없으면 None.
    """
    segments = market_regime.historical_regime_segments(test_start, test_end).get(regime, [])
    if not segments:
        return None
    seg_start, seg_end = max(segments, key=lambda s: (pd.Timestamp(s[1]) - pd.Timestamp(s[0])).days)
    per_ticker = _evaluate_group_config_on_test(tickers, config, seg_start, seg_end, max_holding_days)
    mean_excess = _group_mean_excess_return(per_ticker)
    return {
        "segment_start": seg_start,
        "segment_end": seg_end,
        "mean_excess_return": round(mean_excess, 2) if mean_excess != float("-inf") else None,
        "per_ticker": per_ticker,
    }


def _group_mean_excess_return(per_ticker_test: dict[str, dict]) -> float:
    """그룹의 test 구간 평균 초과수익(전략 CAGR - S&P500 매수보유 CAGR). 유효한 종목이 하나도
    없으면 -inf (구조 변경 escape hatch가 항상 트리거되게 해, 실패를 조용히 넘기지 않는다)."""
    values = [
        tc["strategy"].get("cagr", 0.0) - tc["buy_and_hold_benchmark"].get("cagr", 0.0)
        for tc in per_ticker_test.values()
        if "error" not in tc
    ]
    return sum(values) / len(values) if values else float("-inf")


def tune_strategy_for_group(
    tickers: list[str],
    base_config: dict,
    style_type: str,
    start: str,
    end: str,
    train_ratio: float = _DEFAULT_TRAIN_RATIO,
    intensity: str = _DEFAULT_INTENSITY,
    regime: Optional[str] = None,
    max_holding_days: Optional[int] = None,
) -> dict:
    """스타일 그룹(예: 경기방어주 17종목) 전체를 하나의 데이터셋으로 묶어 공통 설정 하나를 찾는다.

    max_holding_days(SPEC 15절, 스윙 트레이딩 모드)를 주면 train 탐색·test 검증 모두 그 보유기간
    상한을 강제한 결과로 이뤄진다(`_SWING_MAX_HOLDING_DAYS`=126거래일이 기본 권장값). None이면
    기존과 동일하게 보유기간 제약 없이 탐색한다(하위호환).

    regime이 None이면(레거시/기본 경로) train 구간을 `_WALK_FORWARD_FOLDS`개의 달력 등분 폴드로
    나눠 평가한다(10/11절 기존 방식). regime이 "약세장"/"강세장"이면 대신 train 구간 안에서 실제로
    그 국면이었던 연속 구간들만 폴드로 써서 독립 탐색한다(SPEC 13절 — S&P500 기준 국면별 분리
    트레이닝). 두 경로 모두 폴드별 그룹 평균 샤프지수의 평균-표준편차 점수를 목적함수로 삼는다
    (_select_best_group_config_walkforward, SPEC 11.2절). test 구간에서는 확정된 공통 config를
    종목별로 개별 평가해 보고한다. 그룹 평균이 test 구간에서 S&P500을 못 이기면
    generate_structural_variants_for_config()로 구조가 다른 대안을 1회성으로 시도한다(레짐/1:2:6/
    직접수식 공통 — 3c절). test 구간 데이터는 최종 검증에만 쓰고 선택 기준에는 쓰지 않는다(4b절
    상단 설계 노트 참고, 11.2절/13.6절에서도 원칙 유지 확인).

    Returns:
        {"style_type", "tickers", "trained_regime", "group_config", "backbone_changed",
         "group_mean_excess_return", "group_win_ratio", "health_warnings", "per_ticker_train_metrics",
         "per_ticker_test_comparison", "tuning_trail", "insufficient_regime_data",
         "regime_matched_test"} — tuning_trail은 채택된 config를 낳은 탐색의 후보별 폴드 점수
        리포트(점수 내림차순). insufficient_regime_data는 regime이 지정됐는데 train 구간 안에 해당
        국면 구간이 하나도 없어(예: 5년 이력에 뚜렷한 약세장이 없음) 폴백으로 원본 config를 그대로
        썼다는 표시(SPEC 13.5절).

        regime이 지정되면(SPEC 13.6절, 2026-07-17 정정) group_mean_excess_return/group_win_ratio/
        per_ticker_test_comparison은 test 구간 전체가 아니라 **그 국면과 같은 test 구간 내 가장 긴
        연속 구간에서만** 평가한 값이다 — "약세장에서 학습한 설정을 강세장 데이터로 검증할 이유가
        없다"는 사용자 확정 원칙. 그런 구간이 test 안에 아예 없으면 group_mean_excess_return=None
        ("검증 불가", 조용히 다른 데이터로 대체하지 않음). regime_matched_test는 그 구간의 시작/
        종료일(segment_start/segment_end)을 보여주는 참고용 필드로, 내용은 per_ticker_test_
        comparison과 사실상 같다(regime=None이면 항상 None).
    """
    train_start, train_end, test_start, test_end = train_test_split_dates(start, end, train_ratio)

    if regime is None:
        train_folds = _split_into_folds(train_start, train_end, _WALK_FORWARD_FOLDS)
    else:
        train_folds = _train_folds_for_regime(train_start, train_end, regime)
    insufficient_regime_data = regime is not None and not train_folds

    def _evaluate_on_test(config: dict) -> tuple[dict[str, dict], float, Optional[dict]]:
        """regime이 없으면(레거시) test 구간 전체로, 있으면 test 구간 중 같은 국면의 가장 긴 연속
        구간 하나로만 평가한다(SPEC 13.6절 2026-07-17 정정 — 국면 불일치 데이터로 검증 안 함)."""
        if regime is None:
            per_ticker = _evaluate_group_config_on_test(tickers, config, test_start, test_end, max_holding_days)
            return per_ticker, _group_mean_excess_return(per_ticker), None
        matched = _evaluate_group_config_on_regime_matched_test(
            tickers, config, test_start, test_end, regime, max_holding_days
        )
        if matched is None or matched.get("mean_excess_return") is None:
            return (matched or {}).get("per_ticker", {}), float("-inf"), matched
        return matched["per_ticker"], matched["mean_excess_return"], matched

    def _search_and_evaluate(config: dict) -> tuple[dict, dict[str, dict], float, list[dict], Optional[dict]]:
        candidates = build_param_grid(config, style_type, intensity)
        if train_folds:
            chosen, trail = _select_best_group_config_walkforward(tickers, candidates, train_folds, max_holding_days)
        else:
            chosen, trail = None, []
        if chosen is None:
            chosen = copy.deepcopy(config)
        per_ticker, mean_excess, matched = _evaluate_on_test(chosen)
        return chosen, per_ticker, mean_excess, trail, matched

    best_config, per_ticker_test, mean_excess, tuning_trail, regime_matched_test = _search_and_evaluate(base_config)
    backbone_changed = False

    if mean_excess <= 0:
        try:
            variants = generate_structural_variants_for_config(base_config, style_type)
        except Exception:
            variants = []
        for variant_config in variants:
            try:
                cand_config, cand_test, cand_excess, cand_trail, cand_matched = _search_and_evaluate(variant_config)
            except Exception:
                continue
            if cand_excess > mean_excess:
                best_config, per_ticker_test, mean_excess, tuning_trail, regime_matched_test = (
                    cand_config, cand_test, cand_excess, cand_trail, cand_matched
                )
                backbone_changed = True

    per_ticker_train_metrics: dict[str, Optional[dict]] = {}
    for ticker in tickers:
        try:
            run = run_backtest(
                ticker, best_config, train_start, train_end, label="train", max_holding_days=max_holding_days
            )
            per_ticker_train_metrics[ticker] = run.metrics
        except Exception:
            per_ticker_train_metrics[ticker] = None

    valid_test = {t: tc for t, tc in per_ticker_test.items() if "error" not in tc}
    win_count = sum(
        1
        for tc in valid_test.values()
        if tc["strategy"].get("cagr", 0.0) > tc["buy_and_hold_ticker"].get("cagr", 0.0)
        and tc["strategy"].get("cagr", 0.0) > tc["buy_and_hold_benchmark"].get("cagr", 0.0)
    )

    try:
        health_warnings = diagnose_strategy_health(best_config)
    except Exception:
        health_warnings = []

    return {
        "style_type": style_type,
        "tickers": tickers,
        "trained_regime": regime,
        "group_config": best_config,
        "backbone_changed": backbone_changed,
        "group_mean_excess_return": round(mean_excess, 2) if mean_excess != float("-inf") else None,
        "group_win_ratio": round(win_count / len(valid_test), 2) if valid_test else None,
        "health_warnings": health_warnings,
        "per_ticker_train_metrics": per_ticker_train_metrics,
        "per_ticker_test_comparison": per_ticker_test,
        "tuning_trail": tuning_trail,
        "insufficient_regime_data": insufficient_regime_data,
        "regime_matched_test": regime_matched_test,
    }


def run_batch_tuning(
    base_config: dict,
    tickers_df: pd.DataFrame,
    start: str,
    end: str,
    train_ratio: float = _DEFAULT_TRAIN_RATIO,
    intensity: str = _DEFAULT_INTENSITY,
    max_holding_days: Optional[int] = None,
) -> list[dict]:
    """전체 파이프라인: 스타일 분류 -> 스타일×국면 그룹 단위 풀링 트레이닝 -> 종목별 결과로 펼쳐서 반환.

    max_holding_days(SPEC 15절, 스윙 트레이딩 모드)를 주면 모든 스타일×국면 그룹의 탐색·검증에
    그 보유기간 상한이 강제된다(`_SWING_MAX_HOLDING_DAYS`=126거래일이 권장값). None이면 기존과
    동일하게 보유기간 제약 없이 탐색한다(하위호환).

    2026-07-15부터 종목마다 따로 탐색하지 않고(위 4b절 tune_strategy_for_group 참고), 같은
    스타일의 종목을 하나의 그룹으로 묶어 공통 설정을 찾는다. 2026-07-16부터(SPEC 13절)는 그 스타일
    그룹마다 S&P500 기준 실제 약세장/강세장 구간의 데이터로 **따로** 트레이닝해 국면별 config를
    각각 만든다 — 같은 스타일·같은 국면끼리는 tuned_config가 서로 동일하지만, 같은 스타일이어도
    학습국면이 다르면 tuned_config가 달라진다(종목마다 이제 결과가 2행 나온다).

    Returns:
        종목별 dict 리스트(ticker/style_type/sector/style_scores/tuned_config/train_metrics/
        test_comparison/excess_return/health_warnings/backbone_changed/tuning_trail/trained_regime/
        insufficient_regime_data/regime_matched_test). 그룹 자체가 실패해도(예: 데이터 조회 전면
        실패) 그 그룹 종목들만 {"ticker", "style_type", "sector", "trained_regime", "error"}로
        기록되고 다른 그룹/국면은 계속 진행된다.
    """
    styles_df = compute_style_scores(tickers_df, start, end)
    styles_by_ticker = styles_df.set_index("ticker").to_dict("index") if not styles_df.empty else {}

    tickers_by_style: dict[str, list[str]] = {}
    for ticker in tickers_df["ticker"]:
        style_type = styles_by_ticker.get(ticker, {}).get("style_type") or "성장주"
        tickers_by_style.setdefault(style_type, []).append(ticker)

    results: list[dict] = []
    for style_type, group_tickers in tickers_by_style.items():
        for regime in _TRAINING_REGIMES:
            try:
                group_result = tune_strategy_for_group(
                    group_tickers, base_config, style_type, start, end,
                    train_ratio=train_ratio, intensity=intensity, regime=regime,
                    max_holding_days=max_holding_days,
                )
            except Exception as e:  # noqa: BLE001 - 그룹/국면 하나의 실패가 나머지를 막지 않게 함
                for ticker in group_tickers:
                    results.append(
                        {
                            "ticker": ticker,
                            "style_type": style_type,
                            "sector": styles_by_ticker.get(ticker, {}).get("sector"),
                            "trained_regime": regime,
                            "error": str(e),
                        }
                    )
                continue

            for ticker in group_tickers:
                test_comparison = group_result["per_ticker_test_comparison"].get(ticker, {})
                if "error" in test_comparison:
                    results.append(
                        {
                            "ticker": ticker,
                            "style_type": style_type,
                            "sector": styles_by_ticker.get(ticker, {}).get("sector"),
                            "trained_regime": regime,
                            "error": test_comparison["error"],
                        }
                    )
                    continue
                strategy_cagr = test_comparison["strategy"].get("cagr", 0.0)
                benchmark_cagr = test_comparison["buy_and_hold_benchmark"].get("cagr", 0.0)
                results.append(
                    {
                        "ticker": ticker,
                        "style_type": style_type,
                        "sector": styles_by_ticker.get(ticker, {}).get("sector"),
                        "style_scores": styles_by_ticker.get(ticker, {}).get("style_scores"),
                        "tuned_config": group_result["group_config"],
                        "train_metrics": group_result["per_ticker_train_metrics"].get(ticker),
                        "test_comparison": test_comparison,
                        "excess_return": round(strategy_cagr - benchmark_cagr, 2),
                        "health_warnings": group_result["health_warnings"],
                        "backbone_changed": group_result["backbone_changed"],
                        "tuning_trail": group_result.get("tuning_trail", []),
                        "trained_regime": regime,
                        "insufficient_regime_data": group_result.get("insufficient_regime_data", False),
                        "regime_matched_test": group_result.get("regime_matched_test"),
                    }
                )
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
    max_holding_days: Optional[int] = None,
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
            max_holding_days=max_holding_days,
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
                    tuning_trail=(
                        json.dumps(r["tuning_trail"], ensure_ascii=False) if r.get("tuning_trail") else None
                    ),
                    trained_regime=r.get("trained_regime"),
                    insufficient_regime_data=bool(r.get("insufficient_regime_data", False)),
                    regime_matched_test=(
                        json.dumps(r["regime_matched_test"], ensure_ascii=False)
                        if r.get("regime_matched_test")
                        else None
                    ),
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
    universe_as_of_date: Optional[str | date | datetime] = None,
    max_holding_days: Optional[int] = None,
) -> int:
    """표본 추출(또는 직접 지정한 종목) -> 배치 튜닝 -> 저장까지 한 번에 수행한다 (job_manager
    백그라운드 실행 진입점).

    max_holding_days(SPEC 15절)를 주면 배치 전체가 스윙 트레이딩 보유기간 상한 하에서 탐색/검증되고,
    그 값이 StrategyTuningRun에 함께 저장돼 나중에 "이 배치는 스윙 모드였는지"를 알 수 있다.

    tickers_df가 주어지면(사용자가 UI에서 직접 담은 종목) sample_universe()에 의한 자동 섹터 균등
    표본 추출을 건너뛰고 그대로 사용한다(universe_n은 이 경우 무시됨).

    universe_as_of_date를 주면(2026-07-17 추가, survivorship bias 완화 — PROGRESS.md 백로그
    1번) sample_universe()에 그대로 전달해 "지금 시점 S&P500"이 아니라 그 시점 point-in-time
    편입종목만 후보로 삼는다. tickers_df가 주어지면(수동 선택) 이 값은 무시된다. 기본값 None이면
    기존과 동일하게 현재 S&P500 전체가 후보다(하위호환).

    UI에서 인라인 클로저 대신 이 함수 하나를 job_manager.start()에 넘기면, 완료 후에는 반환된
    run_id로 core.db에서 결과를 다시 조회하기만 하면 되므로 지역변수 소실 문제(PROGRESS.md에 기록된
    기존 버그 패턴)를 원천적으로 피할 수 있다.
    """
    if tickers_df is None:
        tickers_df = sample_universe(universe_n, as_of_date=universe_as_of_date)
    results = run_batch_tuning(
        base_config, tickers_df, start, end, train_ratio=train_ratio, intensity=intensity,
        max_holding_days=max_holding_days,
    )
    return save_tuning_run(
        base_config, tickers_df, start, end, train_ratio, intensity, results,
        base_strategy_id=base_strategy_id, max_holding_days=max_holding_days,
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
                "max_holding_days": r.max_holding_days,
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
                "tuning_trail": json.loads(res.tuning_trail) if res.tuning_trail else [],
                "trained_regime": res.trained_regime,
                "insufficient_regime_data": bool(res.insufficient_regime_data),
                "regime_matched_test": json.loads(res.regime_matched_test) if res.regime_matched_test else None,
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
            "max_holding_days": run.max_holding_days,
            "created_at": run.created_at,
            "results": results,
        }


def get_top_tuning_results(base_strategy_id: int, limit: int = 10) -> list[dict]:
    """base_strategy_id로 지금까지 쌓인 모든 StrategyTuningRun을 통틀어, test 구간 초과수익
    (excess_return)이 가장 높은 종목별 결과 상위 limit개를 반환한다 (2026-07-15, 야간 반복
    미세튜닝 리더보드용 — 매일 밤 여러 번 실행되며 계속 누적되는 실행 이력 전체에서 지금까지 발견된
    최선의 결과를 보여준다).

    error가 있거나 excess_return이 없는(계산 실패) 결과는 제외한다.

    Returns:
        [{"ticker", "sector", "style_type", "trained_regime", "excess_return", "tuned_config",
          "test_comparison", "backbone_changed", "run_id", "run_intensity", "run_created_at",
          "run_start_date", "run_end_date", "train_ratio"}, ...]
        (excess_return 내림차순). run_start_date/run_end_date/train_ratio는 상세보기에서
        train_test_split_dates()로 test 구간을 다시 계산해 차트를 그릴 때 쓴다.
    """
    with get_session() as session:
        rows = (
            session.query(StrategyTuningResult, StrategyTuningRun)
            .join(StrategyTuningRun, StrategyTuningResult.run_id == StrategyTuningRun.id)
            .filter(StrategyTuningRun.base_strategy_id == base_strategy_id)
            .filter(StrategyTuningResult.excess_return.isnot(None))
            .filter(StrategyTuningResult.error.is_(None))
            .order_by(StrategyTuningResult.excess_return.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "ticker": res.ticker,
                "sector": res.sector,
                "style_type": res.style_type,
                "trained_regime": res.trained_regime,
                "excess_return": res.excess_return,
                "base_config": json.loads(run.base_config) if run.base_config else {},
                "tuned_config": json.loads(res.tuned_config) if res.tuned_config else None,
                "test_comparison": json.loads(res.test_comparison) if res.test_comparison else None,
                "backbone_changed": bool(res.backbone_changed),
                "run_id": run.id,
                "run_intensity": run.intensity,
                "run_created_at": run.created_at,
                "run_start_date": run.start_date.isoformat(),
                "run_end_date": run.end_date.isoformat(),
                "train_ratio": run.train_ratio,
            }
            for res, run in rows
        ]


# ----------------------------------------------------------------------------
# 7b. 라이브 국면 판단 -> 세 전략(약세장용/강세장용/횡보장용) 중 하나 선택 (SPEC 13.9절,
# 2026-07-17 도입, 2026-07-17 3분류로 확장)
# ----------------------------------------------------------------------------

_LIVE_REGIME_LOOKBACK_DAYS = market_regime.DEFAULT_LOOKBACK_DAYS


def select_live_strategy(bear_strategy_id: int, bull_strategy_id: int, sideways_strategy_id: int) -> dict:
    """지금 국면(S&P500 기준)에 맞는 전략을 전략 라이브러리에서 하나 골라 반환한다.

    국면별로 분리 트레이닝한 세 전략(run_batch_tuning의 결과를 저장한 것)을 실제로 어느 시점에
    어느 걸 쓸지 정하는 용도다. 학습 때 폴드를 나눈 것과 똑같은 규칙
    (core.market_regime.classify_daily_regime — 낙폭 -20% 이하는 약세장, ADX<20은 횡보장, 나머지는
    200일선 기준 강세장/약세장)을 벤치마크의 가장 최근 날짜에 그대로 적용해 "지금" 국면을 정한다.
    학습과 실전 판단이 서로 다른 기준을 쓰면 학습된 전략이 실제로는 안 맞는 국면에 배정될 수 있어,
    두 곳 모두 같은 classify_daily_regime을 재사용한다(get_market_regime_snapshot의 4신호 종합
    점수 체계와는 별개 — 그쪽은 매크로 대시보드의 "오늘 국면" 표시용이고 이 함수와는 무관).

    Returns:
        {"trading_regime", "selected_strategy_id", "selected_strategy_name", "selected_config"} —
        벤치마크 가격 데이터를 가져오지 못하면(trading_regime 포함) 전부 None, 대신 "reason"에
        이유를 담는다.
    """
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=_LIVE_REGIME_LOOKBACK_DAYS)).isoformat()
    df = get_price_history(market_regime.DEFAULT_BENCHMARK_TICKER, start=start, end=end, use_cache=True)
    if df is None or df.empty:
        return {
            "trading_regime": None,
            "selected_strategy_id": None,
            "selected_strategy_name": None,
            "selected_config": None,
            "reason": "벤치마크 가격 데이터를 가져올 수 없습니다.",
        }

    regime_series = market_regime.classify_daily_regime(df["Close"], df["High"], df["Low"])
    if regime_series.empty:
        return {
            "trading_regime": None,
            "selected_strategy_id": None,
            "selected_strategy_name": None,
            "selected_config": None,
            "reason": "국면을 판단할 가격 데이터가 부족합니다.",
        }

    trading_regime = regime_series.iloc[-1]
    strategy_id = {"약세장": bear_strategy_id, "강세장": bull_strategy_id, "횡보장": sideways_strategy_id}[trading_regime]
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            return {
                "trading_regime": trading_regime,
                "selected_strategy_id": None,
                "selected_strategy_name": None,
                "selected_config": None,
            }
        return {
            "trading_regime": trading_regime,
            "selected_strategy_id": strategy.id,
            "selected_strategy_name": strategy.name,
            "selected_config": json.loads(strategy.indicator_config),
        }


# ----------------------------------------------------------------------------
# 7c. 종목 자체 추세 기준 분류(상승/하락/횡보) + 라이브 선택 (SPEC 14절, 2026-07-17)
#
# 13절의 국면(약세장/강세장)은 S&P500 "지수"의 날짜별 흐름을 기준으로 학습 데이터를 나눴다 — 그런데
# 조회 구간에 따라 test 구간(마지막 25%)에 지수 차원의 약세장이 아예 없을 수 있어(실측으로 확인,
# STRATEGY_TUNING_ENGINE_SPEC.md 13.6절 정정 사례 참고) 그 경우 약세장 config를 out-of-sample로
# 검증할 방법이 없었다. 사용자가 대안으로, 지수가 아니라 "종목 자체"가 그 표본기간 동안 상승/하락/
# 횡보 중 어느 흐름이었는지로 종목을 3개 데이터셋으로 나눠 각각 따로 연구하자고 요청 — 어떤 기간을
# 잡아도 그 안에서 오른 종목/내린 종목/횡보한 종목은 항상 섞여 있으므로(지수 자체의 방향과 무관하게)
# 13절이 겪은 "그 국면 데이터가 아예 없다" 문제를 원천적으로 피할 수 있다.
# ----------------------------------------------------------------------------

_TREND_BULLISH_CAGR_PCT = 10.0
_TREND_BEARISH_CAGR_PCT = -10.0
_LIVE_TREND_LOOKBACK_CALENDAR_DAYS = 182  # 약 6개월 - _MOMENTUM_LOOKBACK_DAYS(126거래일)와 같은 취지


def classify_ticker_trend(df: pd.DataFrame) -> Optional[str]:
    """가격 이력 하나의 구간 전체 CAGR로, 그 구간 동안 종목이 상승/하락/횡보 중 어느 흐름이었는지
    분류한다 (SPEC 14절, 라이브 판단용 — select_strategy_for_ticker_trend 참고). CAGR >= 10%면
    "상승", <= -10%면 "하락", 그 사이는 "횡보"(위임받은 기술 판단 — 개별 종목은 지수보다 변동성이
    커서 13절의 지수용 임계값보다 넉넉히 잡음). 데이터가 없거나 구간이 하루 이하면 None.

    학습 데이터셋 구성(classify_tickers_by_trend)에는 이 절대 임계값 방식을 쓰지 않는다 — 아래 참고.
    """
    cagr = _ticker_cagr(df)
    if cagr is None:
        return None
    if cagr >= _TREND_BULLISH_CAGR_PCT:
        return "상승"
    if cagr <= _TREND_BEARISH_CAGR_PCT:
        return "하락"
    return "횡보"


def _ticker_cagr(df: pd.DataFrame) -> Optional[float]:
    """가격 이력 구간 전체의 CAGR(%)을 계산한다. 데이터가 없거나 구간이 하루 이하면 None."""
    if df is None or df.empty or "Close" not in df.columns:
        return None
    close = df["Close"].dropna()
    if len(close) < 2:
        return None
    start_price, end_price = float(close.iloc[0]), float(close.iloc[-1])
    if start_price <= 0:
        return None
    years = (close.index[-1] - close.index[0]).days / 365.25
    if years <= 0:
        return None
    return ((end_price / start_price) ** (1 / years) - 1) * 100


def classify_tickers_by_trend(tickers: list[str], start: str, end: str) -> dict[str, str]:
    """종목 목록을 그 구간 CAGR의 **상대적 순위(3분위)**로 상승/횡보/하락 3그룹으로 나눈다
    (학습 데이터셋 구성용 — SPEC 14절).

    classify_ticker_trend()의 절대 임계값(±10%) 대신 상대 순위를 쓰는 이유: S&P500 현재
    구성종목만 표본으로 삼으면 생존편향 때문에(성과가 나빠 지수에서 빠진 종목은 애초에 표본에
    없음) 수년 단위 CAGR이 절대적으로 마이너스인 종목이 실제로 거의 없다(실측 확인 — 10년 표본
    40종목 중 CAGR<=-10%가 0개였음). 상대 순위를 쓰면 시장이 전반적으로 강세였든 아니었든 세
    그룹이 항상 채워진다("상대적으로 부진했던 종목"이라는 의미로 재정의).

    하위 1/3 = "하락", 상위 1/3 = "상승", 중간 = "횡보". 조회 실패/데이터 부족 종목은 결과에서
    제외한다. 유효 종목이 3개 미만이면 3분위를 나눌 수 없어 전부 "횡보"로 처리한다.
    """
    cagrs: dict[str, float] = {}
    for ticker in tickers:
        try:
            df = get_price_history(ticker, start=start, end=end, use_cache=True)
        except Exception:
            continue
        cagr = _ticker_cagr(df)
        if cagr is not None:
            cagrs[ticker] = cagr

    if len(cagrs) < 3:
        return {t: "횡보" for t in cagrs}

    ranks = pd.Series(cagrs).rank(pct=True)
    result: dict[str, str] = {}
    for ticker, pct_rank in ranks.items():
        if pct_rank <= 1 / 3:
            result[ticker] = "하락"
        elif pct_rank > 2 / 3:
            result[ticker] = "상승"
        else:
            result[ticker] = "횡보"
    return result


def select_strategy_for_ticker_trend(
    ticker: str,
    bear_strategy_id: int,
    bull_strategy_id: int,
    sideways_strategy_id: int,
    lookback_days: int = _LIVE_TREND_LOOKBACK_CALENDAR_DAYS,
) -> dict:
    """지금 이 종목이 최근 lookback_days(기본 약 6개월)일 동안 상승/하락/횡보 중 어느 흐름인지 보고,
    그에 맞는 전략(하락장용/상승장용/횡보장용)을 전략 라이브러리에서 골라 반환한다 (SPEC 14절).

    select_live_strategy()(13.9절, S&P500 지수 기준)와 다르게 "지금 시장 전체가 어떤가"가 아니라
    "지금 이 종목이 어떤 흐름인가"를 본다. 학습(classify_ticker_trend)은 표본기간 전체(수년)로
    분류하지만, 실전 판단은 최근 구간만 봐야 "지금" 상태를 반영하므로 lookback을 짧게 잡는다 —
    학습과 판단의 기간이 다른 것은 의도된 설계다.

    Returns:
        {"trend", "selected_strategy_id", "selected_strategy_name", "selected_config"} — 최근
        가격 데이터를 가져오지 못하면 전부 None.
    """
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=lookback_days)).isoformat()
    try:
        df = get_price_history(ticker, start=start, end=end, use_cache=True)
    except Exception:
        df = None
    trend = classify_ticker_trend(df) if df is not None else None
    if trend is None:
        return {"trend": None, "selected_strategy_id": None, "selected_strategy_name": None, "selected_config": None}

    strategy_id = {"하락": bear_strategy_id, "상승": bull_strategy_id, "횡보": sideways_strategy_id}[trend]
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            return {"trend": trend, "selected_strategy_id": None, "selected_strategy_name": None, "selected_config": None}
        return {
            "trend": trend,
            "selected_strategy_id": strategy.id,
            "selected_strategy_name": strategy.name,
            "selected_config": json.loads(strategy.indicator_config),
        }


# ----------------------------------------------------------------------------
# 8. 튜닝 전/후 파라미터 diff — 야간 반복 미세튜닝 리더보드 상세보기용 (2026-07-16)
# ----------------------------------------------------------------------------


def describe_tuning_diff(base_config: dict, tuned_config: dict) -> dict:
    """base_config(백본 원본) 대비 tuned_config(채택된 튜닝 결과)에서 실제로 값이 바뀐 조건/비중만
    골라낸다. describe_tunable_params()와 같은 위치 판별 로직(_iter_condition_paths/
    _weight_stage_lists)을 재사용해 build_param_grid가 실제로 건드리는 자리만 비교한다.

    구조 변경(generate_structural_variants_for_config 채택, backbone_changed=True)으로 조건 개수/
    종류 자체가 달라져 같은 경로를 tuned_config에서 찾을 수 없는 경우는 조용히 건너뛴다(added/
    removed 조건까지 비교하는 것은 이번 범위 밖 — 호출부가 backbone_changed 플래그로 이 사실을
    별도로 안내해야 한다).

    Returns:
        JSON 스키마(레짐/1:2:6): {"schema": "json", "unchanged": bool,
            "changes": [{"path", "kind": "condition"|"weight", "indicator", "before", "after"}, ...]}
            (kind="condition"이면 before/after가 core.strategy_engine.describe_condition()이 만든
            한국어 문구, kind="weight"면 "진입 2단계 비중 20%"처럼 비율 문구)
        직접 수식(expression): {"schema": "expression", "unchanged": bool,
            "changes": [{"before": str, "after": str}]} (수식 전체 전/후만 비교 — 숫자 단위 위치
            정보는 튜닝 시점 이후 저장되지 않아 부분 diff가 불가능함)
    """
    if "expression" in base_config:
        before_expr = base_config.get("expression", "")
        after_expr = (tuned_config or {}).get("expression", before_expr)
        if before_expr == after_expr:
            return {"schema": "expression", "unchanged": True, "changes": []}
        return {
            "schema": "expression",
            "unchanged": False,
            "changes": [{"before": before_expr, "after": after_expr}],
        }

    changes: list[dict] = []
    for path, base_cond in _iter_condition_paths(base_config):
        try:
            tuned_cond = _get_by_path(tuned_config, path)
        except (KeyError, IndexError, TypeError):
            continue
        if not isinstance(tuned_cond, dict):
            continue
        before_desc = describe_condition(base_cond)
        after_desc = describe_condition(tuned_cond)
        if before_desc != after_desc:
            changes.append(
                {
                    "path": _format_path(path),
                    "kind": "condition",
                    "indicator": base_cond.get("indicator", ""),
                    "before": before_desc,
                    "after": after_desc,
                }
            )

    stage_labels = {"entry_stages": "진입", "exit_stages": "청산"}
    for stage_path, numeric_stages in _weight_stage_lists(base_config).items():
        for si, before_w in numeric_stages:
            try:
                after_w = _get_by_path(tuned_config, stage_path)[si]["weight"]
            except (KeyError, IndexError, TypeError):
                continue
            if round(float(before_w), 4) != round(float(after_w), 4):
                label = stage_labels[stage_path[-1]]
                changes.append(
                    {
                        "path": _format_path((*stage_path, si)),
                        "kind": "weight",
                        "indicator": "",
                        "before": f"{label} {si + 1}단계 비중 {before_w * 100:.0f}%",
                        "after": f"{label} {si + 1}단계 비중 {after_w * 100:.0f}%",
                    }
                )

    return {"schema": "json", "unchanged": not changes, "changes": changes}


def summarize_tuning_diff(diff: dict, backbone_changed: bool = False) -> str:
    """describe_tuning_diff() 결과를 사람이 읽는 한국어 자연어 설명으로 요약한다.

    결정론적으로만 만든다(Gemini 호출 없음) — 리더보드에서 결과를 열 때마다 비용/지연 없이 바로
    보여줄 수 있어야 하므로, describe_condition() 등 기존 결정론적 문구 생성기만 조합해서 쓴다.
    """
    prefix = (
        "⚠️ 파라미터 조정만으로는 test 구간을 이기지 못해 구조 자체가 다른 전략(조건/지표 변경)으로 "
        "교체됐습니다. 아래 비교는 같은 위치의 조건만 대응시킨 것이라 일부만 반영됐을 수 있습니다.\n\n"
        if backbone_changed
        else ""
    )

    if diff["unchanged"]:
        return prefix + (
            "이 종목/스타일에서는 원본 전략 그대로가 test 구간에서 가장 나아, 파라미터를 바꾸지 않고 "
            "원본을 그대로 채택했습니다."
        )

    if diff["schema"] == "expression":
        c = diff["changes"][0]
        return prefix + (
            "수식 안의 숫자(기간/임계값 등)가 이 종목/스타일에 맞게 조정됐습니다.\n"
            f"- 이전: {c['before']}\n- 이후: {c['after']}"
        )

    lines = []
    for c in diff["changes"]:
        if c["kind"] == "weight":
            lines.append(f"- {c['before']} → {c['after']}")
        else:
            lines.append(f"- {c['indicator']}: {c['before']} → {c['after']}")
    return prefix + "이 종목/스타일에 맞춰 다음 조건/비중이 조정됐습니다:\n" + "\n".join(lines)


# ----------------------------------------------------------------------------
# 6. 백지 상태 전략 자동 생성 + 교차 검증 (2026-07-14 사용자 확정)
#
# 지금까지의 튜닝(1~5절)은 항상 "백본 전략"(유튜브 해석/라이브러리 저장)이 있다는 전제였다. 이 절은
# 그 전제 없이 종목/기간만 주어지면 거래량+가격지표를 조합한 전략을 처음부터 생성해 S&P500/매수보유를
# 아웃퍼폼하는 것을 목표로 탐색하고, 찾은 전략을 다른 종목에 그대로(재튜닝 없이) 적용해 일반화
# 여부를 보여준다. Gemini로 서로 다른 아이디어의 후보를 1회성으로 여러 개 제안받은 뒤(생성), 각
# 후보를 기존 tune_strategy_for_ticker()로 평가해(검증 — 3b절의 expression 숫자 미세튜닝 경로를
# 그대로 통과하므로 새 검증 파이프라인을 만들지 않는다) 가장 좋은 것을 채택한다 — "제안은 Gemini,
# 채택은 실측 백테스트"라는 3b절의 기존 설계 원칙을 그대로 따른다.
# ----------------------------------------------------------------------------

_STRATEGY_GENERATION_SYSTEM_PROMPT = """\
너는 퀀트 트레이딩 전략을 백지 상태에서 설계하는 어시스턴트다.

사용자가 알려준 문법(변수/함수/연산자)만 사용해서, 서로 다른 매매 아이디어(추세추종, 평균회귀,
거래량 돌파, 모멘텀, 변동성 축소 후 확장 등)를 가진 완전히 독립적인 후보 전략을 n개 제안해라.
각 후보는 파이썬과 비슷한 문법의 완전한 불리언 수식 하나여야 한다(and/or/not, 비교 연산자 필수).

**최소 2개 이상은 거래량(volume)을 반드시 포함해야 한다** — 예: 거래량이 20일 평균 대비 급증,
가격 상승과 거래량 증가가 동시에 발생, 저거래량 횡보 후 거래량 동반 돌파 등.

설명이나 마크다운 없이 완전한 수식 문자열만 배열에 담아 반환한다.
"""

_STRATEGY_GENERATION_SCHEMA = {
    "type": "object",
    "properties": {"strategies": {"type": "array", "items": {"type": "string"}}},
    "required": ["strategies"],
}

# Gemini 키가 없거나 생성이 실패했을 때 쓰는 기본 후보 세트. 거래량을 포함한 후보를 절반 포함해
# "거래량 및 여러 수치들을 조합"하라는 요청을 키 없이도 최소한으로 충족한다.
_FALLBACK_CANDIDATE_EXPRESSIONS = [
    "close > sma(close, 20) and volume > sma(volume, 20)",
    "crossover(sma(close, 20), sma(close, 60)) and volume > sma(volume, 20) * 1.2",
    "close < bb_lower(close, 20, 2) and rsi(close, 14) < 35",
    "rsi(close, 14) < 30 and close > sma(close, 200)",
    "crossover(macd_line(close), macd_signal(close)) and volume > sma(volume, 20)",
    "close > highest(high, 20) and volume > sma(volume, 20) * 1.5",
]

_DEFAULT_N_CANDIDATES = 6


def generate_candidate_strategies(n: int = _DEFAULT_N_CANDIDATES) -> list[str]:
    """Gemini로 백지 상태에서 서로 다른 아이디어의 후보 전략(expression) 문자열 n개를 생성한다.

    키 없음/호출 실패/응답 전부 문법 오류면 빈 리스트를 반환한다(예외를 던지지 않음) — 호출부가
    _FALLBACK_CANDIDATE_EXPRESSIONS로 대체한다.
    """
    if not gemini_client.has_api_key():
        return []

    from core.expression_engine import FUNCTIONS, VARIABLE_COLUMNS

    grammar_note = (
        f"변수: {', '.join(sorted(VARIABLE_COLUMNS))} / 함수: {', '.join(sorted(FUNCTIONS))} "
        "/ 비교연산자: < <= > >= == != / 논리연산자: and or not"
    )
    contents = f"서로 다른 아이디어의 매매 전략 후보를 {n}개 제안해줘.\n사용 가능한 문법: {grammar_note}"

    try:
        response = gemini_client.generate_content(
            models=gemini_client.COMPLEX_TASK_MODELS,
            contents=contents,
            system_instruction=_STRATEGY_GENERATION_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=_STRATEGY_GENERATION_SCHEMA,
        )
        text = response.text
        if not text:
            return []
        raw = json.loads(text).get("strategies", [])
    except Exception:
        return []

    valid: list[str] = []
    for expr in raw:
        if not isinstance(expr, str):
            continue
        try:
            validate_syntax(expr)
        except ExpressionError:
            continue
        valid.append(expr)
        if len(valid) >= n:
            break
    return valid


def generate_and_backtest_strategy(
    ticker: str,
    start: str,
    end: str,
    train_ratio: float = _DEFAULT_TRAIN_RATIO,
    intensity: str = _DEFAULT_INTENSITY,
    n_candidates: int = _DEFAULT_N_CANDIDATES,
) -> dict:
    """종목/기간만으로 백지 상태에서 전략을 생성하고 train/test로 검증해 최선의 결과를 반환한다.

    1) 이 종목의 스타일(주도주/성장주/...)을 먼저 판별한다(2절 compute_style_scores 재사용) —
       이후 숫자 파라미터 미세튜닝 방향을 그 스타일에 맞춘다.
    2) generate_candidate_strategies()로 서로 다른 아이디어의 후보를 얻는다(실패 시 폴백 세트).
    3) 각 후보를 tune_strategy_for_ticker()로 그대로 평가한다 — expression 스키마이므로 내부에서
       build_param_grid가 자동으로 _build_expression_param_grid 경로(Gemini 숫자 미세튜닝)를 타
       숫자까지 다듬어진 상태로 train/test 검증까지 끝난 결과를 돌려준다(새 검증 로직 없음).
    4) test 구간 초과수익이 가장 높은 후보를 채택한다.

    Returns:
        tune_strategy_for_ticker()와 동일한 dict + "style_type"/"style_scores"/
        "candidates_tried"(시도한 후보 요약 리스트)/"outperforms_both"(test 구간에서 종목
        매수보유+S&P500을 둘 다 이겼는지) 키가 추가됨.
    """
    single_df = pd.DataFrame({"ticker": [ticker], "sector": [None]})
    styles_df = compute_style_scores(single_df, start, end)
    style_row = styles_df.iloc[0] if not styles_df.empty else None
    style_type = style_row["style_type"] if style_row is not None else "성장주"
    style_scores = style_row["style_scores"] if style_row is not None else None

    try:
        raw_candidates = generate_candidate_strategies(n_candidates)
    except Exception:
        raw_candidates = []
    if not raw_candidates:
        raw_candidates = list(_FALLBACK_CANDIDATE_EXPRESSIONS)

    best: Optional[dict] = None
    tried: list[dict] = []
    for expr in raw_candidates:
        try:
            validate_syntax(expr)
        except ExpressionError:
            continue
        try:
            result = tune_strategy_for_ticker(
                ticker, {"expression": expr}, style_type, start, end, train_ratio, intensity
            )
        except Exception:
            continue
        tried.append(
            {
                "expression": expr,
                "train_sharpe": (result.get("train_metrics") or {}).get("sharpe", 0.0),
                "test_excess_return": result.get("excess_return", 0.0),
            }
        )
        if best is None or result.get("excess_return", float("-inf")) > best.get("excess_return", float("-inf")):
            best = result

    if best is None:
        # 전부 실패한 극단적 경우(문법 오류/데이터 조회 실패 등)에도 항상 결과를 낸다.
        fallback_expr = _FALLBACK_CANDIDATE_EXPRESSIONS[0]
        best = tune_strategy_for_ticker(
            ticker, {"expression": fallback_expr}, style_type, start, end, train_ratio, intensity
        )
        tried.append(
            {"expression": fallback_expr, "train_sharpe": None, "test_excess_return": best.get("excess_return", 0.0)}
        )

    best["style_type"] = style_type
    best["style_scores"] = style_scores
    best["candidates_tried"] = tried
    best["outperforms_both"] = _outperforms_both_benchmarks(best["test_comparison"])
    return best


def cross_validate_on_tickers(config: dict, tickers: list[str], start: str, end: str) -> list[dict]:
    """생성된 전략을 다른 종목들에 재튜닝 없이 그대로 적용해 일반화 여부를 확인한다.

    각 종목의 스타일도 함께 태깅해(2절 재사용) save_tuning_run()이 그대로 받을 수 있는
    StrategyTuningResult 형태로 반환한다. train_metrics는 재튜닝을 하지 않았으므로 None이고,
    비교는 전체 [start, end] 기간을 그대로 사용한다(이미 확정된 전략을 다른 종목에서 그대로
    관찰하는 것이라 별도로 train/test를 나눌 이유가 없음).
    """
    if not tickers:
        return []

    styles_df = compute_style_scores(
        pd.DataFrame({"ticker": tickers, "sector": [None] * len(tickers)}), start, end
    )
    styles_by_ticker = styles_df.set_index("ticker").to_dict("index") if not styles_df.empty else {}

    results = []
    for t in tickers:
        style_row = styles_by_ticker.get(t, {})
        try:
            comparison = compare_with_benchmarks(t, config, start, end)
            strategy_metrics = comparison["strategy"].metrics
            benchmark_metrics = comparison["buy_and_hold_benchmark"].metrics
            results.append(
                {
                    "ticker": t,
                    "sector": style_row.get("sector"),
                    "style_type": style_row.get("style_type"),
                    "style_scores": style_row.get("style_scores"),
                    "tuned_config": config,
                    "train_metrics": None,
                    "test_comparison": {
                        "strategy": strategy_metrics,
                        "buy_and_hold_ticker": comparison["buy_and_hold_ticker"].metrics,
                        "buy_and_hold_benchmark": benchmark_metrics,
                    },
                    "excess_return": round(strategy_metrics.get("cagr", 0.0) - benchmark_metrics.get("cagr", 0.0), 2),
                    "health_warnings": [],
                }
            )
        except Exception as e:  # noqa: BLE001 - 종목 하나의 실패가 나머지를 막지 않게 함
            results.append(
                {
                    "ticker": t,
                    "sector": style_row.get("sector"),
                    "style_type": style_row.get("style_type"),
                    "error": str(e),
                }
            )
    return results


def run_and_save_generation(
    ticker: str,
    cross_validate_tickers: list[str],
    start: str,
    end: str,
    train_ratio: float = _DEFAULT_TRAIN_RATIO,
    intensity: str = _DEFAULT_INTENSITY,
    n_candidates: int = _DEFAULT_N_CANDIDATES,
) -> int:
    """백지 상태 전략 생성 + 교차 검증 + 저장까지 한 번에 수행한다 (job_manager 백그라운드 진입점).

    생성 대상(primary) 종목 결과를 StrategyTuningResult 1행으로, cross_validate_tickers 결과를
    나머지 행으로 담아 기존 save_tuning_run()/get_tuning_run()을 그대로 재사용한다 — "다종목
    미세튜닝" 탭의 결과 렌더링을 이 기능에도 그대로 쓸 수 있게 하기 위함(base_strategy_id는 항상
    None — 라이브러리 백본이 아니라 이 실행에서 새로 생성된 전략이므로).
    """
    primary_result = generate_and_backtest_strategy(ticker, start, end, train_ratio, intensity, n_candidates)
    generated_config = primary_result["tuned_config"]

    primary_sector = screener.get_fundamentals(ticker).get("sector")
    primary_row = {
        "ticker": ticker,
        "sector": primary_sector,
        "style_type": primary_result.get("style_type"),
        "style_scores": primary_result.get("style_scores"),
        "tuned_config": primary_result.get("tuned_config"),
        "train_metrics": primary_result.get("train_metrics"),
        "test_comparison": primary_result.get("test_comparison"),
        "excess_return": primary_result.get("excess_return"),
        "health_warnings": primary_result.get("health_warnings"),
    }

    cross_rows = cross_validate_on_tickers(generated_config, cross_validate_tickers, start, end)
    results = [primary_row, *cross_rows]

    tickers_df = pd.DataFrame(
        {"ticker": [ticker, *cross_validate_tickers], "sector": [None] * (1 + len(cross_validate_tickers))}
    )
    return save_tuning_run(
        generated_config, tickers_df, start, end, train_ratio, intensity, results, base_strategy_id=None
    )


# ----------------------------------------------------------------------------
# 6. 야간 CI 튜닝 결과(리더보드 JSON) 신선도 조회 — 전 페이지 공통 상단 배지용
# ----------------------------------------------------------------------------

_CI_LEADERBOARD_PATH = Path(__file__).resolve().parent.parent / "data" / "nightly_tuning_leaderboard.json"


def get_ci_leaderboard_freshness() -> dict[str, Any]:
    """`data/nightly_tuning_leaderboard.json`(GitHub Actions가 커밋)의 최신 실행 시각을 반환.

    파일 전체를 파싱해야 하지만 상위 K(50)개로 캡핑돼 있어 수백 KB 수준(실측 파싱 <5ms)이라
    앱 전역 배지(core.theme.apply_theme, 모든 페이지에서 매 렌더마다 호출)에서 불러도 체감
    로딩 지연이 없다. 그래도 페이지 전환마다 매번 다시 읽지 않도록 호출부(theme.py)에서
    st.cache_data로 짧게(수 분) 캐싱해 쓴다.
    """
    if not _CI_LEADERBOARD_PATH.exists():
        return {"exists": False, "latest_run_at": None, "count": 0, "hours_since": None}
    try:
        records = json.loads(_CI_LEADERBOARD_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"exists": False, "latest_run_at": None, "count": 0, "hours_since": None}

    latest: Optional[datetime] = None
    for r in records:
        raw = r.get("run_created_at")
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        if latest is None or ts > latest:
            latest = ts

    # run_created_at은 StrategyTuningRun.created_at(기본값 datetime.utcnow, tz 정보 없음)이 그대로
    # JSON에 직렬화된 것이라 UTC 기준으로 비교해야 한다(로컬 시간대와 섞으면 KST 기준 +9시간 오차).
    hours_since = (datetime.utcnow() - latest).total_seconds() / 3600 if latest else None
    return {
        "exists": True,
        "latest_run_at": latest,
        "count": len(records),
        "hours_since": hours_since,
    }
