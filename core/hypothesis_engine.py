"""가설 백테스트 엔진 — 동결된 스펙+신호 코드를 받아 일별 순수익 시계열을 만든다(토큰 0, 결정론).

체결 모델(프로젝트 관례와 같다: 오늘 정한 비중은 내일부터 실현, weights.shift(1)):
- 리밸런싱일 d 의 종가까지 데이터로 score() 를 호출하고, 그 비중은 d 다음 거래일 수익부터 적용한다.
- 리밸런싱 사이에는 보유 비중이 가격에 따라 표류한다(매일 목표로 되돌리지 않는다). 미배분 비중은 현금(수익 0).
- 비용 = 리밸런싱 회전율(목표 − 표류 비중의 절대값 합) × 편도 bp, 적용일 수익에서 차감.
- 보유 종목의 가격이 빠진 날(상장폐지 등)은 수익 0 으로 두고 missing_price_days 로 센다.

한계(결과에 그대로 남긴다): sp500_pit 는 과거 구성종목 목록을 쓰지만 폐지 종목의 가격이 무료 소스에 없으면
후보에서 빠진다 → 생존편향이 남는다(price_coverage 로 표시). 배당은 조정 종가(Adj Close)가 있으면 그것으로 반영한다.
"""

from __future__ import annotations

import csv
import math
import re
import types
from bisect import bisect_right
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SP500_CSV = PROJECT_ROOT / "data" / "sp500_historical_constituents.csv"
WARMUP_DAYS = 420          # 신호 계산용 선행 이력(달력일)
TRADING_DAYS = 252
DEFAULT_ONE_WAY_BPS = 25.0  # core.trade_ledger.COST_SCENARIOS_BPS["25bp"] (보수 가정)
_DELISTED = re.compile(r"-\d{6}$")

PriceProvider = Callable[[str, str, str], pd.DataFrame]


class SignalError(RuntimeError):
    pass


def load_signal(code: str) -> Callable:
    """동결된 신호 코드 원문을 격리된 모듈 네임스페이스에서 실행해 score 함수를 돌려준다."""
    mod = types.ModuleType("hypothesis_signal")
    try:
        exec(compile(code, "<hypothesis_signal>", "exec"), mod.__dict__)  # noqa: S102 — Critic 통과·동결된 코드만
    except Exception as exc:  # noqa: BLE001
        raise SignalError(f"신호 코드 로드 실패: {type(exc).__name__}: {exc}") from exc
    fn = mod.__dict__.get("score")
    if not callable(fn):
        raise SignalError("신호 코드에 score(prices, as_of, params) 함수가 없음")
    return fn


def price_symbol(raw: str) -> str:
    """구성종목 CSV 표기('BF.B', 'AAL-199702') → yfinance 표기('BF-B', 'AAL')."""
    return _DELISTED.sub("", raw).replace(".", "-")


@lru_cache(maxsize=1)
def _sp500_rows() -> tuple[tuple[date, ...], tuple[frozenset, ...]]:
    dates, members = [], []
    with SP500_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dates.append(date.fromisoformat(row["date"]))
            members.append(frozenset(price_symbol(t) for t in row["tickers"].split(",") if t))
    return tuple(dates), tuple(members)


def resolve_universe(spec: dict) -> tuple[list[str], Callable[[date], set]]:
    """(가격을 받을 전체 종목, as_of → 그날 편입 종목 집합)."""
    uni = spec["universe"]
    if uni["type"] == "list":
        tickers = list(uni["tickers"])
        return tickers, lambda d: set(tickers)
    if uni["type"] == "etf_core":
        from core.champion_strategy import CORE_UNIVERSE

        tickers = list(CORE_UNIVERSE)
        return tickers, lambda d: set(tickers)
    dates, members = _sp500_rows()
    start = date.fromisoformat(spec["period"]["start"])
    end = date.fromisoformat(spec["period"]["end"]) if spec["period"].get("end") else date.today()
    lo, hi = max(bisect_right(dates, start) - 1, 0), bisect_right(dates, end)
    everyone = sorted(set().union(*members[lo:hi]))

    def members_at(d: date) -> set:
        i = bisect_right(dates, d) - 1
        return set(members[i]) if i >= 0 else set()

    return everyone, members_at


def load_prices(tickers: list[str], start: date, end: date, provider: Optional[PriceProvider] = None) -> dict[str, pd.DataFrame]:
    """종목별 일봉. 조회 실패·빈 결과는 조용히 빠진다(커버리지로 드러남)."""
    if provider is None:
        from core.candidate_ledger import default_price_provider as provider
    out = {}
    s, e = (start - timedelta(days=WARMUP_DAYS)).isoformat(), (end + timedelta(days=1)).isoformat()
    for t in tickers:
        try:
            df = provider(t, s, e)
        except Exception:  # noqa: BLE001
            continue
        if df is not None and not df.empty and "Close" in df:
            df = df.copy()
            df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
            out[t] = df.sort_index()
    return out


def rebalance_dates(days: pd.DatetimeIndex, rule: str) -> list[pd.Timestamp]:
    """기간(주/월)의 마지막 거래일."""
    key = days.to_period("W") if rule == "weekly" else days.to_period("M")
    s = pd.Series(days, index=days)
    return list(s.groupby(key).max())


def select_weights(scores: dict, top_k: int, max_weight: float, eligible: set) -> dict[str, float]:
    ranked = sorted(((float(v), k) for k, v in scores.items()
                     if k in eligible and v is not None and math.isfinite(float(v)) and float(v) > 0), reverse=True)
    picks = [k for _, k in ranked[:top_k]]
    if not picks:
        return {}
    w = min(1.0 / len(picks), max_weight)
    return {k: w for k in picks}


def backtest(spec: dict, params: dict, signal: Callable, prices: dict[str, pd.DataFrame],
             members_at: Callable[[date], set], one_way_bps: float = DEFAULT_ONE_WAY_BPS) -> dict[str, Any]:
    start = pd.Timestamp(spec["period"]["start"])
    end = pd.Timestamp(spec["period"]["end"]) if spec["period"].get("end") else None
    col = {t: ("Adj Close" if "Adj Close" in df and df["Adj Close"].notna().any() else "Close") for t, df in prices.items()}
    panel = pd.DataFrame({t: df[col[t]] for t, df in prices.items()}).sort_index()
    if panel.empty:
        raise SignalError("가격 데이터가 없음")
    rets = panel.pct_change(fill_method=None)
    days = panel.index[(panel.index >= start) & ((panel.index <= end) if end is not None else True)]
    if len(days) < 30:
        raise SignalError("백테스트 구간 거래일이 30일 미만")
    rebal = set(rebalance_dates(days, spec["portfolio"]["rebalance"]))
    pf = spec["portfolio"]

    holdings: dict[str, float] = {}   # 현재 표류 비중(자산 대비)
    pending: Optional[dict] = None    # 오늘 종가에 정한 목표 → 내일 적용
    daily, turnovers, n_rebal, missing, n_members, n_priced = [], [], 0, 0, 0, 0
    weights_log = []
    for d in days:
        r_day, cost = 0.0, 0.0
        if pending is not None:
            turnover = sum(abs(pending.get(k, 0.0) - holdings.get(k, 0.0)) for k in set(pending) | set(holdings))
            cost = turnover * one_way_bps / 1e4
            turnovers.append(turnover)
            holdings, pending = dict(pending), None
        if holdings:
            grown = {}
            for k, w in holdings.items():
                r = rets.at[d, k] if k in rets.columns else float("nan")
                if pd.isna(r):
                    missing += 1
                    r = 0.0
                r_day += w * r
                grown[k] = w * (1 + r)
            total = 1 + r_day
            holdings = {k: v / total for k, v in grown.items()} if total > 0 else {}
        daily.append(r_day - cost)
        if d in rebal:
            members = members_at(d.date())
            eligible = {t for t in members if t in prices and pd.notna(panel.at[d, t])}
            n_members += len(members)
            n_priced += len(eligible)
            truncated = {t: prices[t].loc[:d] for t in eligible}
            try:
                scores = signal(truncated, d, dict(params)) or {}
            except Exception as exc:  # noqa: BLE001
                raise SignalError(f"{d.date()} score() 실패: {type(exc).__name__}: {exc}") from exc
            pending = select_weights(scores, pf["top_k"], pf["max_weight"], eligible)
            n_rebal += 1
            weights_log.append((d.date().isoformat(), pending))
    series = pd.Series(daily, index=days, name="net_return")
    return {"returns": series, "n_rebalances": n_rebal, "avg_turnover": (sum(turnovers) / len(turnovers)) if turnovers else 0.0,
            "missing_price_days": missing, "price_coverage": (n_priced / n_members) if n_members else None,
            "last_weights": weights_log[-1] if weights_log else None, "one_way_bps": one_way_bps}


def stats(r: pd.Series) -> dict[str, Any]:
    r = r.dropna()
    n = len(r)
    if n < 2:
        return {"n_days": n}
    mean, sd = float(r.mean()), float(r.std(ddof=1))
    eq = (1 + r).cumprod()
    mdd = float((eq / eq.cummax() - 1).min())
    sr = mean / sd if sd > 0 else 0.0
    z = (r - mean) / sd if sd > 0 else r * 0
    return {"n_days": n, "mean_daily": mean, "sd_daily": sd, "sharpe_daily": sr, "sharpe_annual": sr * math.sqrt(TRADING_DAYS),
            "ann_return": float(eq.iloc[-1] ** (TRADING_DAYS / n) - 1), "ann_vol": sd * math.sqrt(TRADING_DAYS),
            "max_drawdown": mdd, "skew": float((z ** 3).mean()), "kurtosis": float((z ** 4).mean())}
