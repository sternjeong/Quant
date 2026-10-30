"""수동 실제 계좌 장부와 같은 외부 현금흐름을 넣은 비교 계좌.

시작 잔고는 해당 거래일 종가 기준이다. 이후 사건은 입력일 종가 평가에
반영하며, 휴장일 입출금은 다음 완료된 거래일에 반영한다. 매매는 체결가를
입력받고 입출금과 구분한다. 현재 보유 CRUD를 과거 거래로 역추정하지 않는다.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from core import champion_strategy as cs
from core.db import get_session
from core.filing_changes import is_trading_day
from core.market_data import get_multiple_price_history
from core.models import PortfolioPerformanceBaseline, PortfolioPerformanceEvent

KINDS = ("DEPOSIT", "WITHDRAW", "BUY", "SELL", "DIVIDEND")


def last_completed_us_session() -> date:
    now = datetime.now(ZoneInfo("America/New_York"))
    day = now.date() if (now.hour, now.minute) >= (16, 30) else now.date() - timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


def _positive(value, name: str) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name}은 0보다 큰 숫자여야 합니다.") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name}은 0보다 큰 숫자여야 합니다.")
    return value


def _positions(rows: list[dict]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker or ticker in result:
            raise ValueError("시작 잔고는 티커당 한 줄이어야 합니다.")
        result[ticker] = _positive(row.get("quantity"), f"{ticker} 수량")
    return result


def load_ledger() -> dict | None:
    with get_session() as session:
        baseline = session.query(PortfolioPerformanceBaseline).order_by(PortfolioPerformanceBaseline.id).first()
        if baseline is None:
            return None
        events = session.query(PortfolioPerformanceEvent).order_by(
            PortfolioPerformanceEvent.as_of, PortfolioPerformanceEvent.id).all()
        return {"as_of": baseline.as_of.isoformat(), "cash_usd": baseline.cash_usd,
                "positions": json.loads(baseline.positions_json),
                "events": [{"id": e.id, "as_of": e.as_of.isoformat(), "kind": e.kind,
                            "ticker": e.ticker, "quantity": e.quantity, "price_usd": e.price_usd,
                            "amount_usd": e.amount_usd, "fee_usd": e.fee_usd} for e in events]}


def save_baseline(as_of: date, cash_usd: float, positions: list[dict]) -> None:
    """장부가 비어 있을 때만 시작 잔고를 만든다. 자동으로 현재 과거를 추정하지 않는다."""
    if not isinstance(as_of, date) or not date(2026, 10, 1) <= as_of <= date.today():
        raise ValueError("시작일은 2026-10-01부터 오늘 사이여야 합니다.")
    if not is_trading_day(as_of):
        raise ValueError("시작 잔고는 완료된 미국 거래일 날짜로 입력해 주세요.")
    if as_of > last_completed_us_session():
        raise ValueError("아직 미국 종가가 완료되지 않은 날입니다. 마지막 완료 거래일을 선택해 주세요.")
    if not math.isfinite(float(cash_usd)) or float(cash_usd) < 0:
        raise ValueError("시작 현금은 0 이상이어야 합니다.")
    clean = _positions(positions)
    if not clean and cash_usd <= 0:
        raise ValueError("시작 보유 또는 현금이 필요합니다.")
    with get_session() as session:
        if session.query(PortfolioPerformanceBaseline).first() is not None:
            raise ValueError("시작 잔고가 이미 있습니다. 기존 장부를 먼저 확인해 주세요.")
        session.add(PortfolioPerformanceBaseline(as_of=as_of, cash_usd=float(cash_usd),
                    positions_json=json.dumps(clean, sort_keys=True)))


def delete_baseline_without_events() -> None:
    """잘못 입력한 시작 잔고만 되돌린다. 사건이 있으면 장부를 보호한다."""
    with get_session() as session:
        if session.query(PortfolioPerformanceEvent).first() is not None:
            raise ValueError("이후 사건이 있어 시작 잔고를 지울 수 없습니다. 마지막 사건부터 삭제해 주세요.")
        row = session.query(PortfolioPerformanceBaseline).first()
        if row is not None:
            session.delete(row)


def _apply_event(cash: float, positions: dict[str, float], event: dict) -> tuple[float, dict[str, float]]:
    kind = event["kind"]
    if kind not in KINDS:
        raise ValueError("입금·출금·매수·매도 중 하나를 고르세요.")
    positions = dict(positions)
    if kind in ("DEPOSIT", "WITHDRAW", "DIVIDEND"):
        amount = _positive(event.get("amount_usd"), "입출금액")
        if kind == "DIVIDEND" and not str(event.get("ticker") or "").strip():
            raise ValueError("배당 종목 티커가 필요합니다.")
        cash += -amount if kind == "WITHDRAW" else amount
    else:
        ticker = str(event.get("ticker") or "").strip().upper()
        if not ticker:
            raise ValueError("매매 티커가 필요합니다.")
        quantity = _positive(event.get("quantity"), "매매 수량")
        price = _positive(event.get("price_usd"), "체결 단가")
        fee = float(event.get("fee_usd") or 0)
        if not math.isfinite(fee) or fee < 0:
            raise ValueError("매매 비용은 0 이상이어야 합니다.")
        if kind == "BUY":
            cash -= quantity * price + fee
            positions[ticker] = positions.get(ticker, 0) + quantity
        else:
            if positions.get(ticker, 0) + 1e-8 < quantity:
                raise ValueError(f"{ticker} 매도 수량이 보유 수량보다 많습니다.")
            positions[ticker] = positions.get(ticker, 0) - quantity
            if positions[ticker] < 1e-8:
                positions.pop(ticker)
            cash += quantity * price - fee
    if cash < -0.005:
        raise ValueError("현금이 부족합니다. 외부 입금이 있었다면 입금 사건부터 기록해 주세요.")
    return max(0.0, cash), positions


def append_event(as_of: date, kind: str, *, amount_usd: float | None = None,
                 ticker: str | None = None, quantity: float | None = None,
                 price_usd: float | None = None, fee_usd: float = 0.0) -> int:
    ledger = load_ledger()
    if ledger is None:
        raise ValueError("먼저 실제 계좌의 시작 잔고를 기록해 주세요.")
    if not isinstance(as_of, date) or as_of <= date.fromisoformat(ledger["as_of"]) or as_of > date.today():
        raise ValueError("사건 날짜는 시작일 이후부터 오늘 사이여야 합니다.")
    if ledger["events"] and as_of < date.fromisoformat(ledger["events"][-1]["as_of"]):
        raise ValueError("거래는 날짜순으로 입력해 주세요. 마지막 사건은 삭제해 바로잡을 수 있습니다.")
    if kind in ("BUY", "SELL") and not is_trading_day(as_of):
        raise ValueError("매수·매도는 미국 거래일에 기록해 주세요.")
    event = {"as_of": as_of.isoformat(), "kind": kind, "amount_usd": amount_usd,
             "ticker": ticker, "quantity": quantity, "price_usd": price_usd, "fee_usd": fee_usd}
    cash, positions = float(ledger["cash_usd"]), _positions([
        {"ticker": t, "quantity": q} for t, q in ledger["positions"].items()])
    for old in ledger["events"]:
        cash, positions = _apply_event(cash, positions, old)
    _apply_event(cash, positions, event)
    with get_session() as session:
        row = PortfolioPerformanceEvent(as_of=as_of, kind=kind, amount_usd=amount_usd,
                                        ticker=str(ticker or "").upper() or None, quantity=quantity,
                                        price_usd=price_usd, fee_usd=fee_usd)
        session.add(row)
        session.flush()
        return row.id


def delete_last_event() -> None:
    with get_session() as session:
        row = session.query(PortfolioPerformanceEvent).order_by(PortfolioPerformanceEvent.as_of.desc(),
                                                                  PortfolioPerformanceEvent.id.desc()).first()
        if row is None:
            raise ValueError("삭제할 사건이 없습니다.")
        session.delete(row)


def account_curve(ledger: dict, sessions: pd.DatetimeIndex, *, price_fn=None) -> dict:
    """시작 잔고와 체결 기록으로 현금을 포함한 실제 계좌 종가 곡선을 만든다."""
    sessions = pd.DatetimeIndex(sessions).tz_localize(None).normalize().unique().sort_values()
    start = pd.Timestamp(ledger["as_of"])
    if start not in sessions:
        raise ValueError("시작 잔고 날짜가 완료된 미국 거래일이 아닙니다.")
    dates = sessions[sessions >= start]
    events_by_day: dict[pd.Timestamp, list[dict]] = {}
    for event in ledger["events"]:
        when = pd.Timestamp(event["as_of"])
        if event["kind"] in ("BUY", "SELL") and when not in sessions:
            raise ValueError(f"{event['as_of']} 매매는 미국 거래일에 기록해야 합니다.")
        eligible = dates[dates >= when]
        if len(eligible):
            events_by_day.setdefault(eligible[0], []).append(event)
    tickers = sorted(set(ledger["positions"]) | {str(e.get("ticker")) for e in ledger["events"]
                                                    if e["kind"] in ("BUY", "SELL") and pd.Timestamp(e["as_of"]) <= dates[-1]})
    price_fn = price_fn or get_multiple_price_history
    histories = price_fn(tickers, start=start.date().isoformat(),
                         end=(dates[-1] + pd.Timedelta(days=1)).date().isoformat(), interval="1d") if tickers else {}
    close = pd.DataFrame(index=dates, columns=tickers, dtype=float)
    for ticker in tickers:
        frame = histories.get(ticker)
        if frame is None or frame.empty or "Close" not in frame:
            raise ValueError(f"{ticker} 종가가 없어 실제 계좌를 평가할 수 없습니다.")
        series = frame["Close"].copy()
        series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
        close[ticker] = series[~series.index.duplicated(keep="last")].reindex(dates)
    positions = {t: float(q) for t, q in ledger["positions"].items()}
    cash = float(ledger["cash_usd"])
    nav = pd.Series(index=dates, dtype=float)
    flows = pd.Series(0.0, index=dates)
    ticker_pnl = {ticker: 0.0 for ticker in tickers}
    previous_qty = dict(positions)
    previous_close = None
    for day in dates:
        bought_minus_sold = {ticker: 0.0 for ticker in tickers}
        for event in events_by_day.get(day, []):
            cash, positions = _apply_event(cash, positions, event)
            if event["kind"] == "DEPOSIT":
                flows[day] += float(event["amount_usd"])
            elif event["kind"] == "WITHDRAW":
                flows[day] -= float(event["amount_usd"])
            elif event["kind"] == "DIVIDEND":
                ticker = str(event["ticker"]).upper()
                ticker_pnl[ticker] = ticker_pnl.get(ticker, 0.0) + float(event["amount_usd"])
            elif event["kind"] in ("BUY", "SELL"):
                ticker = event["ticker"]
                sign = 1 if event["kind"] == "BUY" else -1
                bought_minus_sold[ticker] += sign * float(event["quantity"]) * float(event["price_usd"]) + float(event.get("fee_usd") or 0)
        value = cash
        for ticker, quantity in positions.items():
            price = float(close.loc[day, ticker])
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"{ticker} {day.date()} 종가가 없어 실제 계좌를 평가할 수 없습니다.")
            value += quantity * price
        if previous_close is not None:
            for ticker in tickers:
                before = float(previous_qty.get(ticker, 0))
                after = float(positions.get(ticker, 0))
                if before or after or bought_minus_sold[ticker]:
                    prior = float(previous_close[ticker]) if before else 0.0
                    current = float(close.loc[day, ticker]) if after else 0.0
                    if (before and (not math.isfinite(prior) or prior <= 0)) or (after and (not math.isfinite(current) or current <= 0)):
                        raise ValueError(f"{ticker} {day.date()} 종가가 없어 손익을 계산할 수 없습니다.")
                    ticker_pnl[ticker] += after * current - before * prior - bought_minus_sold[ticker]
        nav[day] = value
        previous_qty = dict(positions)
        previous_close = close.loc[day]
    start_value = float(nav.iloc[0])
    if start_value <= 0:
        raise ValueError("시작 계좌 평가액이 0 이하입니다.")
    profit = float(nav.iloc[-1] - start_value - flows.sum())
    if abs(sum(ticker_pnl.values()) - profit) > max(0.01, abs(profit) * 1e-8):
        raise ValueError("실제 계좌의 종목별 손익과 전체 손익이 일치하지 않습니다.")
    return {"nav": nav, "flows": flows, "start_value": start_value, "profit_usd": profit,
            "ticker_pnl": ticker_pnl, "cash_usd": cash, "positions": positions}


def matched_benchmarks(champion: pd.Series, spy: pd.Series, account: dict,
                       *, daily_allocation: list[dict] | None = None,
                       ticker_pnl_daily: list[dict] | None = None) -> dict:
    """실제 계좌와 같은 날 같은 외부 자금만 챔피언·SPY에 투자한다.

    챔피언 추가 진입에는 그날 목표 위험자산 비중별 편도 비용을 적용한다.
    출금에는 비례 매도 비용을 적용한다. SPY는 기존 비교처럼 비용이 없다.
    """
    dates = account["nav"].index
    inception = champion.index[0]
    curves = {"champion": champion.reindex(dates), "spy": spy.reindex(dates)}
    for key, curve in curves.items():
        if curve.isna().any() or (curve <= 0).any():
            raise ValueError(f"{key} 비교 계좌의 가격 배수가 부족합니다.")
    fee_by_day = {}
    fee_by_ticker = {}
    for row in daily_allocation or []:
        day = pd.Timestamp(row["date"])
        fee_by_ticker[day] = {(p["sleeve"], p["ticker"]): float(p["weight"]) *
                              (cs.CORE_COST_BPS_PER_SIDE / 10000 if p["sleeve"] == "코어" else
                               cs.SATELLITE_COST_BPS_PER_SIDE / 10000 if p["sleeve"] == "새틀라이트" else 0)
                              for p in row["allocation"]}
        fee_by_day[day] = sum(fee_by_ticker[day].values())
    if daily_allocation is None and float(account["flows"].abs().sum()) > 0:
        raise ValueError("챔피언 추가 투자 비용을 계산할 날짜별 배분이 없습니다. 챔피언 성과를 다시 계산해 주세요.")
    if any(day not in fee_by_day for day in dates[account["flows"] != 0]):
        raise ValueError("입출금일의 챔피언 배분이 없습니다. 챔피언 성과를 다시 계산해 주세요.")
    if dates[0] > inception and daily_allocation is not None and dates[0] not in fee_by_day:
        raise ValueError("시작일의 챔피언 배분이 없습니다. 챔피언 성과를 다시 계산해 주세요.")
    initial_champion_fee = (float(account["start_value"]) * fee_by_day[dates[0]]
                            if dates[0] > inception and daily_allocation is not None else 0.0)
    output = {}
    champion_units_before = {}
    for name, curve in curves.items():
        start_amount = float(account["start_value"]) - initial_champion_fee if name == "champion" else float(account["start_value"])
        units = start_amount / float(curve.iloc[0])
        values = pd.Series(index=dates, dtype=float)
        for day in dates:
            if name == "champion":
                champion_units_before[day] = units
            value = units * float(curve.loc[day])
            flow = float(account["flows"].loc[day])
            if flow > 0:
                fee = fee_by_day.get(day, 0.0) if name == "champion" else 0.0
                units += flow * (1 - fee) / float(curve.loc[day])
                value += flow * (1 - fee)
            elif flow < 0:
                fee = fee_by_day.get(day, 0.0) if name == "champion" else 0.0
                proceeds_needed = -flow
                sold = proceeds_needed / (1 - fee)
                if sold > value + 0.005:
                    raise ValueError(f"{name} 비교 계좌가 {day.date()} 출금액을 충당할 수 없습니다.")
                units -= sold / float(curve.loc[day])
                value -= sold
            values[day] = value
        output[name] = values
    output["personal"] = account["nav"]
    output["net_deposits_usd"] = float(account["start_value"] + account["flows"].sum())
    output["profit_usd"] = {name: float(series.iloc[-1] - output["net_deposits_usd"])
                            for name, series in output.items() if name in ("personal", "champion", "spy")}
    if ticker_pnl_daily is not None:
        from core.champion_performance import series_from_json
        pnl_by_ticker = {}
        for row in ticker_pnl_daily:
            key = (row["sleeve"], row["ticker"])
            daily = series_from_json(row["pnl_x"]).reindex(dates).fillna(0.0)
            pnl_by_ticker[key] = sum(float(daily.loc[day]) * champion_units_before[day] for day in dates[1:])
        for day in dates:
            flow = float(account["flows"].loc[day])
            if flow:
                fee = fee_by_day[day]
                gross_sold = -flow / (1 - fee) if flow < 0 else 0.0
                amount = flow if flow > 0 else gross_sold
                for key, rate in fee_by_ticker[day].items():
                    pnl_by_ticker[key] = pnl_by_ticker.get(key, 0.0) - amount * rate
        if initial_champion_fee:
            for key, rate in fee_by_ticker[dates[0]].items():
                pnl_by_ticker[key] = pnl_by_ticker.get(key, 0.0) - float(account["start_value"]) * rate
        if abs(sum(pnl_by_ticker.values()) - output["profit_usd"]["champion"]) > max(0.02, abs(output["profit_usd"]["champion"]) * 1e-6):
            raise ValueError("추가 투자 후 챔피언 종목별 손익과 자산곡선이 일치하지 않습니다.")
        output["champion_ticker_pnl"] = pnl_by_ticker
    return output
