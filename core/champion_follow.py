"""지정일에 진입해 현 챔피언 규칙을 따랐다면의 가상 성과. 주문/원장 변경 없음."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from core import champion_performance as perf
from core import champion_strategy as cs

FOLLOW_START = "2026-10-01"
CACHE_DIR = perf.CACHE_DIR
SCHEMA = 2
# Nasdaq ECA2026-710: WBD 최종 거래 10/05, 10/06 현금 인수. 이후 값은 주가가 아니라 수령 현금이다.
WBD_CASH_MERGER = {"ticker": "WBD", "date": "2026-10-06", "last_trade": "2026-10-05",
                   "cash_per_share": 31.01666668,
                   "source": "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-710"}


def today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def quote_end(end: str) -> str:
    # 미국 당일 장중 봉은 포함하지 않는다. end는 한국 날짜, 가격 API의 종료일은 배타적이다.
    if end != today_kst().isoformat():
        return end
    ny = datetime.now(ZoneInfo("America/New_York"))
    boundary = ny.date() if (ny.hour, ny.minute) < (16, 30) else (pd.Timestamp(ny.date()) + pd.Timedelta(days=1)).date()
    return min(end, boundary.isoformat())


def params(end: str) -> dict:
    return {"start": FOLLOW_START, "end": str(end), "quote_end": quote_end(end), "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
            "schema": SCHEMA, "core_cost_bps": cs.CORE_COST_BPS_PER_SIDE,
            "satellite_cost_bps": cs.SATELLITE_COST_BPS_PER_SIDE,
            "core_weight": cs.CORE_WEIGHT, "satellite_weight": cs.SATELLITE_WEIGHT}


def _cache_path(end: str, cache_dir=None) -> Path:
    return Path(cache_dir or CACHE_DIR) / f"champion_follow_{perf.cache_key(params(end))}.json"


def load_cached(end: str, cache_dir=None):
    import json
    try:
        result = json.loads(_cache_path(end, cache_dir).read_text())
        return result if result.get("params") == params(end) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _panel(histories: dict, tickers: list[str], field: str = "Close") -> pd.DataFrame:
    # 원시 결측을 유지한다. 보유가격 누락을 ffill해 수익 0으로 만들지 않는다.
    series = {}
    for ticker in tickers:
        df = histories.get(ticker)
        if df is None or df.empty:
            continue
        col = field if field in df else "Close"
        if col not in df:
            continue
        sr = df[col].copy()
        sr.index = pd.to_datetime(sr.index).tz_localize(None).normalize()
        series[ticker] = sr[~sr.index.duplicated(keep="last")]
    return pd.DataFrame(series).sort_index()


def _require_prices(prices: pd.DataFrame, weights: pd.DataFrame) -> None:
    needed = (weights.abs() > 1e-12) | (weights.shift(1).fillna(0).abs() > 1e-12)
    values = prices.reindex(index=weights.index, columns=weights.columns)
    bad = needed & (~np.isfinite(values) | (values <= 0))
    if bad.any().any():
        dates, columns = np.where(bad.to_numpy())
        raise ValueError(f"보유 종목 가격 누락: {weights.columns[columns[0]]} {weights.index[dates[0]].date()}")


def _apply_cash_merger(histories: dict, index: pd.DatetimeIndex, selected: set[str]) -> tuple[dict, list[dict]]:
    """확인된 현금 인수대금을 평가 경로에 넣는다. 다른 결측 종목에는 적용하지 않는다."""
    action = WBD_CASH_MERGER
    ticker, day = action["ticker"], pd.Timestamp(action["date"])
    if ticker not in selected or index[-1] < day:
        return histories, []
    frame = histories.get(ticker)
    if frame is None or frame.empty or "Close" not in frame:
        raise ValueError(f"현금 인수 전 {ticker} 원가격이 없습니다")
    before = frame.loc[frame.index <= pd.Timestamp(action["last_trade"]), "Close"].dropna()
    if before.empty or not np.isfinite(before.iloc[-1]) or before.iloc[-1] <= 0:
        raise ValueError(f"현금 인수 전 {ticker} 마지막 거래가격이 없습니다")
    # 10/06의 공급자 잔존 봉은 거래 가능한 종가가 아니다. 10/07 이후 새 거래 봉이 나타나면 즉시 재검토한다.
    if (pd.to_datetime(frame.index).normalize() > day).any():
        raise ValueError(f"{ticker} 현금 인수 뒤 가격 봉이 있어 기업행동 확인이 필요합니다")
    adjusted = frame.copy()
    for session in index[index >= day]:
        adjusted.loc[session, "Close"] = action["cash_per_share"]
        if "Adj Close" in adjusted:
            adjusted.loc[session, "Adj Close"] = action["cash_per_share"]
    result = dict(histories)
    result[ticker] = adjusted.sort_index()
    return result, [dict(action, last_traded_close=float(before.iloc[-1]))]


def reselection_dates(index: pd.DatetimeIndex, start: str) -> list[pd.Timestamp]:
    """시작 거래일과 매수일+6개월마다 실제 가격 거래일에 재선정한다."""
    dates = [index[0]]
    anchor = pd.Timestamp(start)
    n = 1
    while True:
        due = anchor + pd.DateOffset(months=6 * n)
        later = index[index >= due]
        if later.empty:
            return dates
        if later[0] > dates[-1]:
            dates.append(later[0])
        n += 1


def compute_follow_performance(end: str | None = None, *, price_fn=None, core_fn=None,
                               pick_fn=None, cache_dir=None, use_cache=True) -> dict:
    """기존 코어 엔진/새틀라이트 주 추천 함수를 조합한다. 테스트는 공급자를 주입한다."""
    end = end or today_kst().isoformat()
    if pd.Timestamp(end) <= pd.Timestamp(FOLLOW_START):
        raise ValueError("시작일 다음 날부터 완료된 거래일 성과를 계산할 수 있습니다.")
    if use_cache:
        cached = load_cached(end, cache_dir)
        if cached is not None:
            return cached
    price_fn = price_fn or cs.get_multiple_price_history
    core_fn = core_fn or cs.run_core_backtest
    pick_fn = pick_fn or cs._pick_satellite_at_date
    data_end = quote_end(end)
    warmup = (pd.Timestamp(FOLLOW_START) - pd.Timedelta(days=cs.SATELLITE_BACKTEST_WARMUP_DAYS)).date().isoformat()
    tickers = list(cs.CORE_UNIVERSE) + [cs.CORE_CASH_ETF, cs.MARKET_FILTER_TICKER]
    core_hist = price_fn(tickers, start=warmup, end=data_end, interval="1d")
    raw = _panel(core_hist, tickers)
    if cs.MARKET_FILTER_TICKER not in raw:
        raise ValueError("SPY 가격이 없어 거래일과 시장필터를 확인할 수 없습니다.")
    spy = raw[cs.MARKET_FILTER_TICKER].dropna()
    if len(spy[spy.index < pd.Timestamp(FOLLOW_START)]) < cs.MARKET_FILTER_SMA_WINDOW:
        raise ValueError("시작일 시장필터에 필요한 SPY 과거 가격이 부족합니다.")
    core = core_fn(FOLLOW_START, data_end)
    idx = core["weights"].index
    if idx.empty or idx[0] != pd.Timestamp(FOLLOW_START):
        raise ValueError("10월 1일 시작 가격이 없어 이 구간을 계산할 수 없습니다.")
    if idx[-1] >= pd.Timestamp(data_end):
        raise ValueError("종료일의 미완료 가격이 포함되었습니다.")
    core_prices = _panel(core_hist, list(core["weights"].columns), cs.CORE_PRICE_FIELD)
    _require_prices(core_prices, core["weights"])
    # 실제 신호 시점의 SPY도 누락을 허용하지 않는다.
    changes = core["weights"].diff().abs().sum(axis=1) > 1e-12
    changes.iloc[0] = True
    for dt in idx[changes]:
        prior = raw.loc[raw.index < dt, cs.MARKET_FILTER_TICKER].tail(cs.MARKET_FILTER_SMA_WINDOW)
        if len(prior) < cs.MARKET_FILTER_SMA_WINDOW or prior.isna().any():
            raise ValueError(f"시장필터 가격 부족: {dt.date()}")

    log = []
    sat_tickers = set()
    for dt in reselection_dates(idx, FOLLOW_START):
        info = dict(pick_fn(dt))
        if not info.get("pool_size") or not info.get("n_with_history"):
            raise ValueError(f"새틀라이트 후보 가격 부족: {dt.date()}")
        weights = info.get("weights") or {}
        if dt > pd.Timestamp(WBD_CASH_MERGER["date"]) and weights.get(WBD_CASH_MERGER["ticker"], 0) > 0:
            raise ValueError("현금 인수 뒤 WBD 재선정은 사용할 수 없습니다")
        if any(not np.isfinite(w) or w < 0 for w in weights.values()) or sum(weights.values()) > 1.000001:
            raise ValueError("새틀라이트 비중이 올바르지 않습니다.")
        info["date"] = dt.date().isoformat()
        log.append(info)
        sat_tickers.update(weights)
    sat_tickers = sorted(sat_tickers)
    sat_hist = price_fn(sat_tickers, start=warmup, end=data_end, interval="1d") if sat_tickers else {}
    sat_hist, cash_mergers = _apply_cash_merger(sat_hist, idx, set(sat_tickers))
    sat_raw = _panel(sat_hist, sat_tickers)
    sat_prices = sat_raw.reindex(index=idx, columns=sat_tickers)
    sat_weights = perf._satellite_weights_from_log(log, sat_prices)
    _require_prices(sat_prices, sat_weights)
    fee_exempt = {action["ticker"]: action["date"] for action in cash_mergers}
    satellite = cs._compute_portfolio_returns(sat_prices, sat_weights, cs.SATELLITE_COST_BPS_PER_SIDE,
                                               fee_exempt_exit_after=fee_exempt)
    satellite.update({"tickers_ever_held": sat_tickers, "rebal_log": log,
                      "fee_exempt_exit_after": fee_exempt})
    # 빈 새틀라이트도 15% 현금으로 둔다. 코어 100%로 전환하지 않는다.
    blended = cs.CORE_WEIGHT * core["ret_net"] + cs.SATELLITE_WEIGHT * satellite["ret_net"]
    bt = {"start": FOLLOW_START, "end": data_end, "core": core, "satellite": satellite,
          "satellite_weight_applied": cs.SATELLITE_WEIGHT, "ret_net": blended}

    # 분석까지 동일한 가격 스냅샷을 쓴다(재다운로드 중 데이터가 바뀌는 불일치 방지).
    history = {**core_hist, **sat_hist}
    result = perf.analyze_backtest(bt, price_fn=lambda requested, **kwargs: {
        t: history[t] for t in requested if t in history})
    if not result["reconciliation"]["ok"]:
        raise ValueError("거래 손익과 자산곡선 검산이 일치하지 않습니다.")
    def allocation_at(i):
        rows = []
        for sleeve, frame, share in (("코어", core["weights"], cs.CORE_WEIGHT),
                                      ("새틀라이트", sat_weights, cs.SATELLITE_WEIGHT)):
            for ticker, weight in frame.iloc[i].items():
                if weight > 1e-12:
                    rows.append({"sleeve": sleeve, "ticker": str(ticker), "weight": float(weight * share)})
        for action in cash_mergers:
            if idx[i] >= pd.Timestamp(action["date"]):
                held = [r for r in rows if r["sleeve"] == "새틀라이트" and r["ticker"] == action["ticker"]]
                rows = [r for r in rows if r not in held]
        cash = max(0., 1. - sum(r["weight"] for r in rows))
        if cash > 1e-12:
            rows.append({"sleeve": "현금", "ticker": "CASH", "weight": cash})
        return rows
    for action in cash_mergers:
        event_day, ticker = action["date"], action["ticker"]
        if idx[-1] < pd.Timestamp(event_day):
            continue
        trade = next((t for t in result["trades"] if t["sleeve"] == "새틀라이트" and t["ticker"] == ticker
                      and t["buy_date"] <= event_day <= t["sell_date"]), None)
        if trade is not None:
            trade["sell_date"] = event_day
            trade["sell_price"] = round(action["cash_per_share"], 4)
            trade["holding_days"] = (pd.Timestamp(event_day) - pd.Timestamp(trade["buy_date"])).days
            trade["is_open"] = False
            price_return = action["cash_per_share"] / trade["buy_price"] - 1
            trade["price_return_pct"] = round(price_return * 100, 4)
            trade["net_return_pct"] = round(((1 + price_return) * (1 - cs.SATELLITE_COST_BPS_PER_SIDE / 10000) - 1) * 100, 4)
            spy_prices = raw[cs.MARKET_FILTER_TICKER]
            spy_entry = float(spy_prices.loc[pd.Timestamp(trade["buy_date"])])
            spy_exit = float(spy_prices.loc[pd.Timestamp(event_day)])
            trade["spy_return_pct"] = round((spy_exit / spy_entry - 1) * 100, 4)
            trade["excess_vs_spy_pct"] = round(trade["net_return_pct"] - trade["spy_return_pct"], 4)
        buy = next((e for e in result["events"] if e["sleeve"] == "새틀라이트" and e["ticker"] == ticker
                    and e["action"] == "매수"), None)
        if buy is not None:
            shares = float(buy["shares_per_capital"])
            result["events"].append({"sleeve": "새틀라이트", "ticker": ticker, "date": event_day,
                                     "action": "현금인수", "price": round(action["cash_per_share"], 4),
                                     "weight_before_pct": round(float(sat_weights.loc[pd.Timestamp(event_day), ticker]) * cs.SATELLITE_WEIGHT * 100, 4),
                                     "weight_after_pct": 0.0, "notional_x": -shares * action["cash_per_share"],
                                     "shares_per_capital": -shares})
        result["events"] = [event for event in result["events"]
                            if not (event["ticker"] == ticker and event["date"] > event_day
                                    and event["action"] in ("매도", "일부매도"))]
    result["events"].sort(key=lambda e: (e["date"], e["sleeve"], e["ticker"]))
    result["ticker_contributions"] = perf.ticker_contributions(result["trades"])
    result["summary"]["n_closed_trades"] = sum(not t["is_open"] for t in result["trades"])
    result["summary"]["n_open_trades"] = sum(t["is_open"] for t in result["trades"])
    result.update({"kind": "champion_follow", "params": params(end),
                   "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "cash_mergers": cash_mergers,
                   "initial_allocation": allocation_at(0), "latest_allocation": allocation_at(-1),
                   "next_satellite_reselection": (pd.Timestamp(log[-1]["date"]) + pd.DateOffset(months=6)).date().isoformat()})
    if use_cache:
        perf._atomic_write_json(_cache_path(end, cache_dir), result)
    return result
