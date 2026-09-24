"""신규 모듈: 종목 발굴 (스크리닝 기반 유니버스 선정).

배경: core.strategy_tuning 은 이미 고정된 S&P500 종목 집합에 대해 진입/청산 타이밍을 최적화한다.
하지만 S&P500 생존 종목들은 이미 지난 5년간 큰 상승을 겪은 경우가 많아, 타이밍보다 "어떤 종목을
보유할지" 고르는 쪽(발굴/스크리닝)이 더 중요할 수 있다는 문제의식에서 만든 독립 모듈이다.

core.strategy_tuning 의 튜닝 파이프라인과는 얽히지 않는다 (import 하지 않음) — 이 모듈은
현재 시점 유니버스에서 모멘텀/성장/가치/퀄리티 4개 팩터의 percentile 점수를 합성해 상위 종목을
뽑아내는 독립적인 스크리닝 도구다.

core/ 관례: streamlit 을 import 하지 않는다 (UI는 app/pages/5_종목_스크리닝.py 에서 담당).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from core import screener, valuation
from core.market_data import get_price_history

# 모멘텀 계산(최대 252거래일=약 12개월)에 필요한 여유를 둔 조회 시작일 오프셋(일).
_MOMENTUM_LOOKBACK_DAYS = 400

# IBD 스타일 가중 ROC(core.sector_strength.ROC_WEIGHTS 와 동일 가중치): 최근 3개월에 가장 큰 비중을
# 주되, 6/9/12개월도 함께 반영해 단기 노이즈에만 휘둘리지 않게 한다.
ROC_WEIGHTS: list[tuple[int, float]] = [(63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2)]

# 종합 점수 가중치 기본값. 근거:
# - momentum(0.30): 추세 추종 관점에서 여전히 가장 강력한 단일 팩터(IBD/퀀트 리서치에서 널리 검증).
# - growth(0.30): "어떤 종목을 살지"가 핵심 문제의식이므로, 이미 싼 게 아니라 향후 이익 성장이
#   기대되는 종목을 잡아내는 것도 momentum 만큼 중요하게 취급.
# - value(0.25): 밸류에이션 과열을 걸러내는 안전장치. 성장/모멘텀만 보면 고평가 함정에 빠지기 쉬움.
# - quality(0.15): 재무 건전성(FCF, 레버리지)은 하방 리스크 관리용 보조 지표라 비중은 가장 낮게.
DEFAULT_WEIGHTS: dict[str, float] = {"momentum": 0.30, "growth": 0.30, "value": 0.25, "quality": 0.15}

RESULT_COLUMNS = [
    "ticker",
    "name",
    "sector",
    "composite_score",
    "momentum_score",
    "growth_score",
    "value_score",
    "quality_score",
    "trailing_pe",
    "price_to_book",
    "earnings_growth",
    "market_cap",
]


# 업종 내 percentile 을 신뢰하려면 업종당 유효(비결측) 표본이 최소 이만큼은 있어야 한다.
# 미달 업종은 전체 유니버스 percentile 로 대체하되 `sector_rank_fallback` 플래그로 명시한다.
MIN_SECTOR_VALID = 3

FACTORS = ("momentum", "growth", "value", "quality")

# RESULT_COLUMNS 는 기존 호환 필드. 아래 확장 컬럼은 그 뒤에 덧붙인다.
EXTRA_COLUMNS = (
    [f"{f}_missing" for f in FACTORS]
    + [f"{f}_contrib" for f in FACTORS]
    + ["missing_factors", "n_missing_factors", "sector_rank_fallback", "fallback_flags", "data_errors"]
)

PIT_META = {
    "pit_verified": False,
    "pit_note": (
        "as_of_date 는 현재 S&P500 구성종목을 과거 구성원 목록으로 걸러낼 뿐, 재무값/가격/시가총액은 "
        "현재 시점 스냅샷이다. 진정한 point-in-time(당시 공시 가능 데이터) 검증이 아니며 백테스트에 쓰면 "
        "look-ahead·생존편향이 남는다."
    ),
}


def _percentile_score(series: pd.Series) -> pd.Series:
    """0~100 percentile 점수(값이 클수록 좋음). 결측은 최하위(0점) — 호출부에서 결측 플래그를 별도로 낸다."""
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() == 0:
        return pd.Series(0.0, index=series.index)
    ranked = s.rank(pct=True, na_option="top") * 100
    return ranked.fillna(0.0)


def _sector_percentile(
    values: pd.Series, sectors: pd.Series, min_valid: int = MIN_SECTOR_VALID
) -> tuple[pd.Series, pd.Series]:
    """지표별 업종 내 percentile(0~100, 유효값 사이 순위). 결측은 0점.

    업종 내 유효 표본이 min_valid 미만이면 전체 유니버스 유효값 기준 percentile 로 대체하고,
    대체된 행은 두번째 반환 Series(bool)에서 True 로 표시한다(결측 행은 대체 대상 아님).
    """
    v = pd.to_numeric(values, errors="coerce")
    sec = sectors.fillna("__UNKNOWN__")
    score = pd.Series(0.0, index=v.index)
    fallback = pd.Series(False, index=v.index)
    global_rank = v.rank(pct=True) * 100  # NaN 은 NaN 유지
    for _, idx in sec.groupby(sec).groups.items():
        grp = v.loc[idx]
        valid = grp.dropna()
        if valid.empty:
            continue
        if len(valid) >= min_valid:
            score.loc[valid.index] = valid.rank(pct=True) * 100
        else:
            score.loc[valid.index] = global_rank.loc[valid.index]
            fallback.loc[valid.index] = True
    return score.fillna(0.0), fallback


def _momentum_raw(price_df: pd.DataFrame) -> Optional[float]:
    """IBD 스타일 가중 ROC(%). 이력이 63거래일 미만이면 None, 그 사이면 확보된 구간만 재정규화."""
    if price_df is None or price_df.empty or "Close" not in price_df.columns:
        return None
    close = price_df["Close"].dropna()
    usable = [(w, weight) for w, weight in ROC_WEIGHTS if len(close) >= w + 1]
    if not usable:
        return None
    weight_sum = sum(weight for _, weight in usable)
    total = 0.0
    for window, weight in usable:
        past = close.iloc[-(window + 1)]
        now = close.iloc[-1]
        if past == 0 or pd.isna(past) or pd.isna(now):
            continue
        r = (now / past - 1.0) * 100.0
        total += r * (weight / weight_sum)
    return total


def _quality_raw(
    fcf: Optional[float], market_cap: Optional[float], total_cash: Optional[float], total_debt: Optional[float]
) -> Optional[float]:
    """FCF 수익률(fcf/market_cap, %)과 레버리지 프록시(cash/debt)를 결합한 원점수.

    두 신호가 모두 있으면 평균, 하나만 있으면 그것만 사용, 둘 다 없으면 None(-> percentile 최하위).
    - FCF 수익률: %(예: 5.0 = 5%) 그대로 사용.
    - 레버리지 프록시: total_debt == 0 이면 무차입으로 최상급 취급(10.0으로 캡). 그 외에는
      total_cash/total_debt 비율(10.0으로 캡, 높을수록 안전 — cash가 debt를 크게 웃도는 경우 과도한
      가중을 막기 위한 상한).
    두 신호의 값 범위(%수익률 vs 비율)가 서로 다르지만, 이 값은 percentile 순위 계산에만 쓰이므로
    절대 스케일 차이 자체는 랭킹에 큰 영향을 주지 않는다(각 개별 신호 내에서는 랭킹이 일관됨).
    """
    fcf_yield = None
    if fcf is not None and market_cap not in (None, 0):
        try:
            fcf_yield = (float(fcf) / float(market_cap)) * 100.0
        except (TypeError, ZeroDivisionError, ValueError):
            fcf_yield = None

    leverage_proxy = None
    if total_debt is not None:
        try:
            total_debt = float(total_debt)
            if total_debt == 0:
                leverage_proxy = 10.0
            elif total_cash is not None:
                leverage_proxy = min(float(total_cash) / total_debt, 10.0)
        except (TypeError, ZeroDivisionError, ValueError):
            leverage_proxy = None

    parts = [v for v in (fcf_yield, leverage_proxy) if v is not None]
    if not parts:
        return None
    return float(np.mean(parts))


def _value_raw(per: Optional[float], pbr: Optional[float], earnings_growth: Optional[float]) -> Optional[float]:
    """PER/PBR/PEG 를 결합한 "저평가일수록 큰 값"인 원점수.

    - 적자 기업(PER<=0 또는 None)은 PER 기반 밸류에이션 지표 자체가 무의미하므로, PBR 등 나머지
      지표가 있어도 통째로 None(-> percentile 최하위) 처리한다 — PER 없이 PBR만으로 부분 점수를
      주면 "적자인데 저PBR"인 기업이 부당하게 가치주로 우대받을 수 있기 때문(명세의 "적자 기업은
      최하위 취급" 요구사항).
    - 흑자 기업은 PER/PBR/PEG(계산 가능하면) 를 함께 평균한다. 각 지표는 "낮을수록 좋음"이므로
      부호를 뒤집어(-per 등) 평균 낸다.
    """
    if per is None or per <= 0:
        return None

    inv_parts = [-per]
    if pbr is not None and pbr > 0:
        inv_parts.append(-pbr)
    peg = valuation.peg_ratio(per, earnings_growth * 100.0) if earnings_growth is not None else None
    if peg is not None and peg > 0:
        inv_parts.append(-peg)
    return float(np.mean(inv_parts))


def discover_candidates(
    universe_n: Optional[int] = None,
    weights: dict = DEFAULT_WEIGHTS,
    sector_filter: Optional[list[str]] = None,
    top_n: int = 30,
    use_cache: bool = True,
    as_of_date: Optional[str] = None,
) -> pd.DataFrame:
    """모멘텀/성장/가치/퀄리티 4팩터 percentile 합성 점수로 종목을 발굴한다.

    Args:
        universe_n: 유니버스를 앞에서부터 n개로 제한(None이면 S&P500 전체 — 실네트워크 호출 시 느림).
        weights: {"momentum", "growth", "value", "quality"} 가중치 dict. 기본값 DEFAULT_WEIGHTS.
        sector_filter: GICS 섹터명(core.screener.get_universe()의 Sector 컬럼 값) 목록으로 제한.
        top_n: 반환할 상위 종목 수.
        use_cache: screener/valuation/market_data 캐시 사용 여부.
        as_of_date: (선택) core.point_in_time_universe 와 연동할 미래 확장 포인트("YYYY-MM-DD").
            지정 시 과거 구성원 목록으로 필터링만 한다. 재무/가격은 현재 스냅샷이므로 진정한 PIT 가
            아니다 — 결과 `df.attrs["meta"]["pit_verified"]` 는 항상 False. 필터 실패 시
            meta["as_of_filter_error"] 에 기록되고 현재 유니버스로 진행한다.

    Returns:
        columns: ticker, name, sector, composite_score, momentum_score, growth_score, value_score,
        quality_score, trailing_pe, price_to_book, earnings_growth, market_cap
        + 확장: {factor}_missing, {factor}_contrib, missing_factors, n_missing_factors,
        sector_rank_fallback, fallback_flags, data_errors. 점수는 지표별 업종 내 percentile 순위 합성.
        메타는 df.attrs["meta"]. (composite_score 내림차순 정렬, 상위 top_n행). 펀더멘털/가격 데이터가 전부 없는 종목은 제외.
    """
    universe = screener.get_universe(use_cache=use_cache)
    if universe is None or universe.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    if sector_filter:
        universe = universe[universe["Sector"].isin(sector_filter)]

    meta = dict(PIT_META)
    meta.update({"as_of_date": as_of_date, "as_of_filter_applied": False, "as_of_filter_error": None})
    if as_of_date:
        try:
            from core.point_in_time_universe import get_constituents_as_of

            allowed = set(get_constituents_as_of(as_of_date))
            universe = universe[universe["Symbol"].isin(allowed)]
            meta["as_of_filter_applied"] = True
        except Exception as e:  # 조용히 넘기지 않고 메타에 기록(현재 유니버스로 진행했음을 명시)
            meta["as_of_filter_error"] = f"{type(e).__name__}: {e}"

    if universe_n is not None:
        universe = universe.head(universe_n)

    price_start = (date.today() - timedelta(days=_MOMENTUM_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    rows = []
    for _, r in universe.iterrows():
        ticker = r["Symbol"]
        sector = r.get("Sector")

        fundamentals: dict = {}
        val_inputs: dict = {}
        price_df = pd.DataFrame()
        errors: list[str] = []
        try:
            fundamentals = screener.get_fundamentals(ticker, use_cache=use_cache) or {}
        except Exception:
            fundamentals = {}
            errors.append("fundamentals")
        try:
            val_inputs = valuation.fetch_valuation_inputs(ticker, use_cache=use_cache) or {}
        except Exception:
            val_inputs = {}
            errors.append("valuation_inputs")
        try:
            price_df = get_price_history(ticker, start=price_start, use_cache=use_cache)
        except Exception:
            price_df = pd.DataFrame()
            errors.append("price_history")

        if not fundamentals and not val_inputs and (price_df is None or price_df.empty):
            continue  # 완전 데이터 실패 종목은 순위 계산에서 제외(다른 종목 처리는 계속)

        flags: list[str] = []
        name = val_inputs.get("longName")
        if not name:
            name = fundamentals.get("name")
            flags.append("name_from_fundamentals")
            if not name:
                name = ticker
                flags.append("name_is_ticker")
        per = val_inputs.get("trailingPE")
        pbr = val_inputs.get("priceToBook")
        earnings_growth = val_inputs.get("earningsGrowth")
        market_cap = val_inputs.get("marketCap")
        if not market_cap and fundamentals.get("market_cap"):
            market_cap = fundamentals.get("market_cap")
            flags.append("market_cap_from_fundamentals")
        elif not market_cap:
            market_cap = None
        sec_val = val_inputs.get("sector")
        if sec_val:
            row_sector = sec_val
        elif sector:
            row_sector = sector
            flags.append("sector_from_universe")
        else:
            row_sector = fundamentals.get("sector")
            if row_sector:
                flags.append("sector_from_fundamentals")
        if per is not None and per <= 0:
            flags.append("value_loss_making")  # 적자: value 는 결측이 아니라 의도된 최하위
        n_roc = 0
        if price_df is not None and not price_df.empty and "Close" in price_df.columns:
            n_close = len(price_df["Close"].dropna())
            n_roc = sum(1 for w, _ in ROC_WEIGHTS if n_close >= w + 1)
            if 0 < n_roc < len(ROC_WEIGHTS):
                flags.append("momentum_partial_window")
        fcf = val_inputs.get("freeCashflow")
        if (fcf is None) != (val_inputs.get("totalDebt") is None):
            flags.append("quality_partial_signal")

        rows.append(
            {
                "ticker": ticker,
                "name": name,
                "sector": row_sector,
                "momentum_raw": _momentum_raw(price_df),
                "growth_raw": earnings_growth,
                "value_raw": _value_raw(per, pbr, earnings_growth),
                "quality_raw": _quality_raw(fcf, market_cap, val_inputs.get("totalCash"), val_inputs.get("totalDebt")),
                "trailing_pe": per,
                "price_to_book": pbr,
                "earnings_growth": earnings_growth,
                "market_cap": market_cap,
                "_flags": flags,
                "_errors": errors,
            }
        )

    if not rows:
        empty = pd.DataFrame(columns=RESULT_COLUMNS + EXTRA_COLUMNS)
        empty.attrs["meta"] = meta
        return empty

    df = pd.DataFrame(rows)

    fb_any = pd.Series(False, index=df.index)
    for f in FACTORS:
        raw = pd.to_numeric(df[f"{f}_raw"], errors="coerce")
        df[f"{f}_missing"] = raw.isna()
        df[f"{f}_score"], fb = _sector_percentile(raw, df["sector"])
        df[f"{f}_sector_fb"] = fb
        fb_any |= fb

    w = weights or DEFAULT_WEIGHTS
    for f in FACTORS:
        df[f"{f}_contrib"] = df[f"{f}_score"] * w.get(f, 0.0)
    df["composite_score"] = sum(df[f"{f}_contrib"] for f in FACTORS)

    df["missing_factors"] = df.apply(lambda r: [f for f in FACTORS if r[f"{f}_missing"]], axis=1)
    df["n_missing_factors"] = df["missing_factors"].apply(len)
    df["sector_rank_fallback"] = fb_any

    def _all_flags(r):
        fl = list(r["_flags"])
        fl += [f"{f}_sector_rank_fallback" for f in FACTORS if r[f"{f}_sector_fb"]]
        return fl

    df["fallback_flags"] = df.apply(_all_flags, axis=1)
    df["data_errors"] = df["_errors"]

    meta["score_method"] = "sector_percentile_rank_weighted_sum"
    meta["missing_policy"] = "결측 팩터는 0점(최하위) 처리하되 *_missing/missing_factors 로 명시"
    meta["min_sector_valid"] = MIN_SECTOR_VALID
    meta["n_scored"] = int(len(df))

    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    out = df[RESULT_COLUMNS + EXTRA_COLUMNS].head(top_n).reset_index(drop=True)
    out.attrs["meta"] = meta
    return out
