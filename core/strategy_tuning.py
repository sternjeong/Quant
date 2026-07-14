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

import copy
import itertools
import json
import random
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

from core import screener, valuation
from core.backtest_engine import compare_with_benchmarks, diagnose_strategy_health, run_backtest
from core.db import get_session
from core.indicators import sma
from core.macro_cycle import SECTOR_ROTATION
from core.market_data import get_price_history
from core.models import StrategyTuningResult, StrategyTuningRun

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

    expression(직접 수식) 전략은 튜닝 가능한 파라미터를 식별할 수 없어 원본 그대로 1개만 반환한다.
    """
    if "expression" in base_config:
        return [copy.deepcopy(base_config)]

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


# ----------------------------------------------------------------------------
# 4. train/test 분리 튜닝 (5절 확정 — 75/25, 샤프 최대화, 매매<5 및 자기모순 조합 배제)
# ----------------------------------------------------------------------------

_DEFAULT_TRAIN_RATIO = 0.75
_MIN_TRADE_COUNT = 5


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

    results = []
    for ticker in tickers_df["ticker"]:
        style_row = styles_by_ticker.get(ticker, {})
        style_type = style_row.get("style_type") or "성장주"
        try:
            result = tune_strategy_for_ticker(
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
) -> int:
    """표본 추출 -> 배치 튜닝 -> 저장까지 한 번에 수행한다 (job_manager 백그라운드 실행 진입점).

    UI에서 인라인 클로저 대신 이 함수 하나를 job_manager.start()에 넘기면, 완료 후에는 반환된
    run_id로 core.db에서 결과를 다시 조회하기만 하면 되므로 지역변수 소실 문제(PROGRESS.md에 기록된
    기존 버그 패턴)를 원천적으로 피할 수 있다.
    """
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
