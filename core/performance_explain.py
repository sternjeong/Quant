"""성과 선의 일별 움직임을 종목 손익과 함께 읽는 표시용 계산."""

from __future__ import annotations

import math

import pandas as pd

from core.champion_performance import series_from_json
from core.market_data import get_multiple_price_history


def champion_components(result: dict, start: str, capital: float) -> dict:
    """선택 시작일 종가를 원금으로 둔 챔피언 NAV·티커별 일별 손익."""
    growth = series_from_json(result["curves"]["strategy"])
    first = pd.Timestamp(start)
    if first not in growth.index or float(growth.loc[first]) <= 0:
        raise ValueError("챔피언 움직임을 계산할 시작일이 없습니다.")
    dates = growth.index[growth.index >= first]
    scale = float(capital) / float(growth.loc[first])
    nav = growth.loc[dates] * scale
    daily = {}
    for item in result.get("ticker_pnl_daily") or []:
        key = (item["sleeve"], item["ticker"])
        values = series_from_json(item["pnl_x"]).reindex(dates).fillna(0.0) * scale
        values.iloc[0] = 0.0
        if values.abs().sum() > 1e-8:
            daily[key] = values
    pnl = pd.DataFrame(daily, index=dates)
    active = champion_active(result, dates, pnl.columns)
    _verify_daily(nav, pd.Series(0.0, index=dates), pnl)
    return {"nav": nav, "flows": pd.Series(0.0, index=dates), "pnl": pnl,
            "active": active, "label": "챔피언"}


def champion_active(result: dict, dates: pd.DatetimeIndex, columns) -> pd.DataFrame:
    """각 수익일의 전일 챔피언 목표 배분에서 실제로 보유한 티커."""
    allocations = {pd.Timestamp(row["date"]): row["allocation"]
                   for row in result.get("daily_allocation") or []}
    active = pd.DataFrame(False, index=dates, columns=columns)
    for i, day in enumerate(dates[1:], start=1):
        held = {(row["sleeve"], row["ticker"]) for row in allocations.get(dates[i - 1], [])
                if row["sleeve"] != "현금" and float(row["weight"]) > 0}
        for key in held:
            if key in active:
                active.loc[day, key] = True
    return active


def spy_components(result: dict, start: str, capital: float) -> dict:
    growth = series_from_json(result["curves"]["spy"])
    first = pd.Timestamp(start)
    if first not in growth.index or float(growth.loc[first]) <= 0:
        raise ValueError("SPY 움직임을 계산할 시작일이 없습니다.")
    nav = growth.loc[growth.index >= first] * (float(capital) / float(growth.loc[first]))
    pnl = pd.DataFrame({"SPY": nav.diff().fillna(0.0)}, index=nav.index)
    return {"nav": nav, "flows": pd.Series(0.0, index=nav.index), "pnl": pnl,
            "active": pd.DataFrame(True, index=nav.index, columns=pnl.columns), "label": "SPY"}


def personal_components(personal: dict) -> dict:
    nav = personal["daily_values"]
    return {"nav": nav, "flows": personal["daily_flows"],
            "pnl": personal["daily_ticker_pnl"], "active": personal["daily_active"],
            "label": "내 현재 보유분 (추정)"}


def _verify_daily(nav: pd.Series, flows: pd.Series, pnl: pd.DataFrame) -> None:
    expected = nav.diff().fillna(0.0) - flows
    expected.iloc[0] = 0.0
    actual = pnl.sum(axis=1).reindex(nav.index).fillna(0.0)
    difference = (actual - expected).abs().max()
    if difference > max(0.02, float(nav.max()) * 1e-6):
        raise ValueError("종목별 일별 손익과 성과 선이 일치하지 않습니다.")


def movement_summary(components: dict, direction: str = "하락일",
                     *, ticker_returns: pd.DataFrame | None = None) -> dict:
    """선의 상승·하락일에 손익을 분해하고, 전체 기간의 일별 기여 상관을 표시한다.

    상관은 보유 거래일의 티커 종가 수익률과 선의 일별 수익률의 피어슨 r.
    표본 5일 미만·상수열은 숨긴다. 영향은 선택한 날의 실제 손익이며 인과 추정이 아니다.
    """
    if direction not in ("하락일", "상승일", "전체"):
        raise ValueError("하락일·상승일·전체 중에서 선택해 주세요.")
    nav = components["nav"].astype(float)
    flows = components["flows"].reindex(nav.index).fillna(0.0).astype(float)
    pnl = components["pnl"].reindex(nav.index).fillna(0.0).astype(float)
    active = components["active"].reindex(index=nav.index, columns=pnl.columns).fillna(False)
    if len(nav) < 2:
        return {"n_days": 0, "net_move_usd": 0.0, "rows": [], "direction": direction}
    _verify_daily(nav, flows, pnl)
    change = nav.diff() - flows
    change.iloc[0] = 0.0
    period_days = nav.index[1:]
    if direction == "하락일":
        chosen = period_days[change.loc[period_days] < -1e-8]
    elif direction == "상승일":
        chosen = period_days[change.loc[period_days] > 1e-8]
    else:
        chosen = period_days
    total_abs = float(pnl.loc[chosen].abs().sum().sum()) if len(chosen) else 0.0
    full_return = (change / nav.shift(1)).loc[period_days]
    rows = []
    for key in pnl.columns:
        selected = pnl.loc[chosen, key] if len(chosen) else pd.Series(dtype=float)
        observed = period_days[active.loc[period_days, key].astype(bool)]
        ticker = key[1] if isinstance(key, tuple) else key
        own = (ticker_returns[ticker].reindex(observed) if ticker_returns is not None and ticker in ticker_returns
               else pd.Series(float("nan"), index=observed))
        other = full_return.loc[observed]
        valid = own.notna() & other.notna() & own.map(math.isfinite) & other.map(math.isfinite)
        n = int(valid.sum())
        corr = float(own.loc[valid].corr(other.loc[valid])) if n >= 5 and own.loc[valid].nunique() > 1 and other.loc[valid].nunique() > 1 else None
        amount = float(selected.sum())
        if not selected.abs().sum() and n == 0:
            continue
        rows.append({"ticker": ticker,
                     "sleeve": key[0] if isinstance(key, tuple) else "",
                     "pnl_usd": amount,
                     "impact_share_pct": float(selected.abs().sum()) / total_abs * 100 if total_abs else 0.0,
                     "correlation_r": corr, "n_observed": n})
    rows.sort(key=(lambda row: row["pnl_usd"] if direction == "하락일" else
                   -row["pnl_usd"] if direction == "상승일" else -abs(row["pnl_usd"])))
    net = float(change.loc[chosen].sum()) if len(chosen) else 0.0
    if abs(sum(row["pnl_usd"] for row in rows) - net) > max(0.02, abs(net) * 1e-6):
        raise ValueError("선택한 날짜의 종목별 영향 합과 성과 선이 일치하지 않습니다.")
    return {"n_days": len(chosen), "net_move_usd": net, "rows": rows, "direction": direction}


def price_correlation_rows(ticker_returns: pd.DataFrame, target: pd.Series,
                           *, min_obs: int = 5) -> list[dict]:
    """SPY 등 비교선과 후보 종목 가격의 동행만 표시한다. ETF 내부 손익으로 해석하지 않는다."""
    target = target.astype(float)
    rows = []
    for ticker in ticker_returns:
        own = ticker_returns[ticker].reindex(target.index)
        valid = own.notna() & target.notna() & own.map(math.isfinite) & target.map(math.isfinite)
        n = int(valid.sum())
        corr = float(own.loc[valid].corr(target.loc[valid])) if n >= min_obs and own.loc[valid].nunique() > 1 and target.loc[valid].nunique() > 1 else None
        rows.append({"ticker": ticker, "correlation_r": corr, "n_observed": n})
    return sorted(rows, key=lambda row: (row["correlation_r"] is None,
                                          -abs(row["correlation_r"] or 0), row["ticker"]))


def ticker_price_trends(tickers: list[str], sessions: pd.DatetimeIndex, *, price_fn=None) -> dict:
    """선택 티커 종가를 각 티커가 관측되는 첫 거래일에 0%로 맞춘다. 결측을 메우지 않는다."""
    if not tickers:
        return {"curves": {}, "daily_returns": pd.DataFrame(), "missing": []}
    dates = pd.DatetimeIndex(sessions).tz_localize(None).normalize().unique().sort_values()
    if dates.empty:
        raise ValueError("종목 가격을 비교할 거래일이 없습니다.")
    price_fn = price_fn or get_multiple_price_history
    histories = price_fn(tickers, start=dates[0].date().isoformat(),
                         end=(dates[-1] + pd.Timedelta(days=1)).date().isoformat(), interval="1d")
    curves = {}
    daily_returns = {}
    missing = []
    for ticker in tickers:
        frame = histories.get(ticker)
        if frame is None or frame.empty or "Close" not in frame:
            missing.append(ticker)
            continue
        close = frame["Close"].copy()
        close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
        close = close[~close.index.duplicated(keep="last")].reindex(dates)
        close = close.where((close > 0) & close.map(math.isfinite))
        available = close.dropna()
        if available.empty:
            missing.append(ticker)
            continue
        first = available.index[0]
        curves[ticker] = (close.loc[first:] / float(available.iloc[0]) - 1) * 100
        daily_returns[ticker] = close.pct_change(fill_method=None)
    return {"curves": curves, "daily_returns": pd.DataFrame(daily_returns, index=dates), "missing": missing}
