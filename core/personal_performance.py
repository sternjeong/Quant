"""현재 등록된 보유분으로 계산하는 참고 곡선. 과거 계좌 장부는 재구성하지 않는다."""

from __future__ import annotations

import math

import pandas as pd

from core.market_data import get_multiple_price_history


def current_holdings_curve(
    holdings: list[dict], sessions: pd.DatetimeIndex, *, price_fn=None,
) -> dict:
    """현재 보유 수량을 기록된 매입일부터 보유했다고 놓은 시간가중 곡선.

    매입원금은 외부 유입으로 빼므로 새 종목 추가 자체가 수익이 되지 않는다.
    과거 수량 변경·매도·현금흐름은 DB에 없으므로 실제 계좌 성과로 해석하면 안 된다.
    """
    sessions = pd.DatetimeIndex(sessions).tz_localize(None).normalize().unique().sort_values()
    if sessions.empty or not holdings:
        return {"available": False, "reason": "등록된 보유 종목이나 비교할 거래일이 없습니다."}
    rows = []
    for holding in holdings:
        ticker = str(holding.get("ticker") or "").upper().strip()
        try:
            quantity = float(holding["quantity"])
            purchase_price = float(holding["purchase_price"])
            purchase_date = pd.Timestamp(holding["purchase_date"]).normalize()
        except (KeyError, TypeError, ValueError):
            raise ValueError("보유 기록의 수량·매입가·매입일을 확인해 주세요.") from None
        if not ticker or not math.isfinite(quantity) or quantity <= 0 or not math.isfinite(purchase_price) or purchase_price <= 0:
            raise ValueError("보유 기록의 티커·수량·매입가를 확인해 주세요.")
        if purchase_date > sessions[-1]:
            continue
        first = sessions[sessions >= purchase_date]
        if first.empty:
            continue
        rows.append((ticker, quantity, purchase_price, first[0]))
    if not rows:
        return {"available": False, "reason": "이 구간에 매입한 현재 보유분이 없습니다."}

    start = min(r[3] for r in rows)
    dates = sessions[sessions >= start]
    end_exclusive = (pd.Timestamp(dates[-1]) + pd.Timedelta(days=1)).date().isoformat()
    price_fn = price_fn or get_multiple_price_history
    tickers = sorted({r[0] for r in rows})
    histories = price_fn(tickers, start=start.date().isoformat(), end=end_exclusive, interval="1d")
    close = pd.DataFrame(index=dates, columns=tickers, dtype=float)
    for ticker in tickers:
        frame = histories.get(ticker)
        if frame is None or frame.empty or "Close" not in frame:
            raise ValueError(f"{ticker} 가격이 없어 내 보유분 곡선을 계산할 수 없습니다.")
        sr = frame["Close"].copy()
        sr.index = pd.to_datetime(sr.index).tz_localize(None).normalize()
        close[ticker] = sr[~sr.index.duplicated(keep="last")].reindex(dates)

    values = pd.Series(0.0, index=dates)
    flows = pd.Series(0.0, index=dates)
    cost = 0.0
    for ticker, quantity, purchase_price, first in rows:
        held = dates[dates >= first]
        price = close.loc[held, ticker]
        if price.isna().any() or (price <= 0).any() or not price.map(math.isfinite).all():
            missing = price.index[(price.isna() | (price <= 0) | ~price.map(math.isfinite))][0]
            raise ValueError(f"{ticker} {missing.date()} 종가가 없어 내 보유분 곡선을 계산할 수 없습니다.")
        values.loc[held] += quantity * price
        flows.loc[first] += quantity * purchase_price
        cost += quantity * purchase_price

    growth = pd.Series(1.0, index=dates)
    for i in range(1, len(dates)):
        previous = float(values.iloc[i - 1])
        if previous <= 0:
            raise ValueError("보유분의 전일 평가액이 올바르지 않습니다.")
        daily = (float(values.iloc[i]) - float(flows.iloc[i])) / previous
        if not math.isfinite(daily) or daily <= 0:
            raise ValueError("보유분의 일별 수익률을 계산할 수 없습니다.")
        growth.iloc[i] = growth.iloc[i - 1] * daily
    return {"available": True, "curve": growth, "first_date": start.date().isoformat(),
            "last_date": dates[-1].date().isoformat(), "n_holdings": len(rows),
            "cost_usd": cost, "last_value_usd": float(values.iloc[-1]),
            "unrealized_pnl_usd": float(values.iloc[-1]) - cost,
            "twr_pct": (float(growth.iloc[-1]) - 1.0) * 100.0}


def normalized_return_curves(champion: pd.Series, spy: pd.Series,
                             personal: pd.Series | None = None, *, same_period: bool = False) -> dict[str, pd.Series]:
    """챔피언·SPY 자산 배수와 현재 보유분 배수를 비교용 수익률 %로 맞춘다."""
    if champion.empty or spy.empty:
        raise ValueError("비교할 챔피언·SPY 가격이 없습니다.")
    first = personal.index[0] if personal is not None and not personal.empty and same_period else champion.index[0]
    result = {}
    for name, curve in (("strategy", champion), ("spy", spy)):
        clipped = curve.loc[curve.index >= first]
        if clipped.empty or float(clipped.iloc[0]) <= 0:
            raise ValueError("비교할 기간의 기준 가격이 없습니다.")
        result[name] = (clipped / float(clipped.iloc[0]) - 1) * 100
    if personal is not None and not personal.empty:
        result["personal"] = (personal - 1) * 100
    return result
