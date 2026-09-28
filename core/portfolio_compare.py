"""이름 붙여 저장해 둔 여러 포트폴리오를 나란히 비교한다 (2026-09-28 추가).

목적(사용자 표현): "내 포트폴리오 A를 고집했으면 지금 얼마인지, 그냥 S&P500을 샀으면, 그냥 META를 샀으면 —
저장해두고 나중에 확인해서 전략을 따르는 게 맞았는지 판단하겠다."

설계 요점 (docs/PORTFOLIO_COMPARISON_SPEC.md):
  - "그냥 SPY를 샀다면"도 **티커 한 개짜리 포트폴리오**로 담는다. 벤치마크라는 별도 개념을 만들지 않는다.
  - 일별 스냅샷 표를 두지 않고 거래 + 과거 시세로 **매번 다시 계산**한다. 중간에 빠진 날이나 낡은 스냅샷 때문에
    틀릴 일이 없다.
  - 나중에 매수·매도를 덧붙일 수 있으므로 **시간가중수익률(TWR)**을 함께 낸다 — 돈을 언제 더 넣었는지가
    성적에 섞이지 않아야 포트폴리오끼리 공정하게 비교된다.
  - 달러 기준과 원화 환산을 둘 다 낸다(환율은 이미 매일 받는 FRED DEXKOUS).

정직하게 알아둘 것: **배당은 반영하지 않는다**(가격만 본다). SPY처럼 배당이 있는 쪽이 실제보다 낮게 보인다.
수수료·세금은 입력한 fee_usd만 반영한다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import pandas as pd

from core.db import get_session
from core.models import TrackedPortfolio, TrackedPortfolioTrade

KINDS = ("actual", "benchmark")
KIND_LABELS = {"actual": "내 선택", "benchmark": "가정(그냥 샀다면)"}
FX_SERIES_ID = "DEXKOUS"  # 원/달러


# ---- 저장·조회 -----------------------------------------------------------------------------------

def create_portfolio(name: str, started_on: date, kind: str = "actual", note: str | None = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("이름을 입력하세요.")
    if kind not in KINDS:
        raise ValueError(f"kind는 {KINDS} 중 하나여야 합니다.")
    with get_session() as session:
        if session.query(TrackedPortfolio).filter(TrackedPortfolio.name == name).first():
            raise ValueError(f"'{name}' 이름이 이미 있습니다.")
        row = TrackedPortfolio(name=name, kind=kind, started_on=started_on, note=(note or "").strip() or None)
        session.add(row)
        session.flush()
        return row.id


def add_trade(portfolio_id: int, ticker: str, trade_date: date, shares: float,
              price_usd: float, fee_usd: float = 0.0, note: str | None = None) -> int:
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("티커를 입력하세요.")
    if shares == 0:
        raise ValueError("주수는 0이 될 수 없습니다(매수는 양수, 매도는 음수).")
    if price_usd <= 0:
        raise ValueError("단가는 0보다 커야 합니다.")
    with get_session() as session:
        if not session.get(TrackedPortfolio, portfolio_id):
            raise ValueError("그런 포트폴리오가 없습니다.")
        row = TrackedPortfolioTrade(
            portfolio_id=portfolio_id, ticker=ticker, trade_date=trade_date,
            shares=float(shares), price_usd=float(price_usd), fee_usd=float(fee_usd or 0.0),
            note=(note or "").strip() or None,
        )
        session.add(row)
        session.flush()
        return row.id


def list_portfolios(include_archived: bool = False) -> list[dict]:
    with get_session() as session:
        query = session.query(TrackedPortfolio)
        if not include_archived:
            query = query.filter(TrackedPortfolio.archived_at.is_(None))
        rows = query.order_by(TrackedPortfolio.started_on.asc(), TrackedPortfolio.id.asc()).all()
        return [{"id": r.id, "name": r.name, "kind": r.kind, "started_on": r.started_on,
                 "note": r.note, "archived_at": r.archived_at} for r in rows]


def list_trades(portfolio_id: int) -> list[dict]:
    with get_session() as session:
        rows = (session.query(TrackedPortfolioTrade)
                .filter(TrackedPortfolioTrade.portfolio_id == portfolio_id)
                .order_by(TrackedPortfolioTrade.trade_date.asc(), TrackedPortfolioTrade.id.asc()).all())
        return [{"id": r.id, "ticker": r.ticker, "trade_date": r.trade_date, "shares": r.shares,
                 "price_usd": r.price_usd, "fee_usd": r.fee_usd, "note": r.note} for r in rows]


def delete_trade(trade_id: int) -> bool:
    with get_session() as session:
        row = session.get(TrackedPortfolioTrade, trade_id)
        if row is None:
            return False
        session.delete(row)
        return True


def archive_portfolio(portfolio_id: int, archived: bool = True) -> bool:
    """지우지 않고 목록에서만 내린다 — 과거 기록을 남겨두는 게 이 기능의 목적이기 때문."""
    with get_session() as session:
        row = session.get(TrackedPortfolio, portfolio_id)
        if row is None:
            return False
        row.archived_at = datetime.utcnow() if archived else None
        return True


def shares_for_amount(price_usd: float, amount_usd: float) -> float:
    """'그냥 SPY에 1,000달러 넣었다면' → 주수. 소수점 주식을 허용한다(ETF 비교 목적이라 반올림이 오히려 왜곡)."""
    if price_usd <= 0:
        raise ValueError("단가는 0보다 커야 합니다.")
    return round(amount_usd / price_usd, 6)


# ---- 평가 ---------------------------------------------------------------------------------------

def _holdings_over_time(trades: list[dict], index: pd.DatetimeIndex) -> pd.DataFrame:
    """날짜별 보유 주수(티커별 누적). 거래가 없는 날은 직전 보유가 이어진다."""
    tickers = sorted({t["ticker"] for t in trades})
    holdings = pd.DataFrame(0.0, index=index, columns=tickers)
    for trade in trades:
        stamp = pd.Timestamp(trade["trade_date"])
        # 거래일이 휴장일이면 그 다음 거래일부터 반영한다(그날 가격이 없으므로).
        positions = index[index >= stamp]
        if len(positions) == 0:
            continue
        holdings.loc[positions[0]:, trade["ticker"]] += trade["shares"]
    return holdings


def _external_flows(trades: list[dict], index: pd.DatetimeIndex) -> pd.Series:
    """날짜별 외부 유입액(매수 대금 + 수수료 − 매도 대금). TWR에서 이 부분을 빼야 수익률이 왜곡되지 않는다."""
    flows = pd.Series(0.0, index=index)
    for trade in trades:
        stamp = pd.Timestamp(trade["trade_date"])
        positions = index[index >= stamp]
        if len(positions) == 0:
            continue
        flows.loc[positions[0]] += trade["shares"] * trade["price_usd"] + trade["fee_usd"]
    return flows


def _chained_twr(values: pd.Series, flows: pd.Series) -> pd.Series:
    """일별 연결 시간가중수익률 누적곡선(시작=1.0).

    r(t) = (V(t) − F(t)) / V(t−1) − 1 을 이어 붙인다. 첫날은 투입만 있고 평가 변화가 없으므로 1.0에서 시작한다.
    V(t−1)이 0이면(아직 아무것도 안 산 구간) 그날은 수익률 0으로 둔다 — 0으로 나눌 수 없고, 실제로도 변화가 없다.
    """
    growth = []
    running = 1.0
    previous_value = None
    for stamp in values.index:
        value, flow = values.loc[stamp], flows.loc[stamp]
        if previous_value is None or previous_value <= 0:
            daily = 0.0
        else:
            daily = (value - flow) / previous_value - 1.0
        running *= (1.0 + daily)
        growth.append(running)
        previous_value = value
    return pd.Series(growth, index=values.index)


def evaluate_portfolio(
    portfolio: dict,
    trades: list[dict],
    prices: dict[str, pd.DataFrame],
    fx: Optional[pd.Series] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """한 포트폴리오의 곡선과 현재 수치. 시세를 직접 받지 않고 주입받아 테스트·캐시가 쉽다.

    prices: {티커: 일봉 DataFrame(Close 포함, 날짜 인덱스)}
    fx: 원/달러 시계열(없으면 원화 값은 None)
    """
    result: dict[str, Any] = {
        "id": portfolio["id"], "name": portfolio["name"], "kind": portfolio["kind"],
        "started_on": portfolio["started_on"], "error": None,
        "curve_usd": pd.Series(dtype=float), "curve_krw": pd.Series(dtype=float),
        "value_usd": None, "cost_usd": None, "return_pct_usd": None, "twr_pct_usd": None,
        "value_krw": None, "cost_krw": None, "return_pct_krw": None, "twr_pct_krw": None,
        "tickers": sorted({t["ticker"] for t in trades}),
    }
    if not trades:
        result["error"] = "거래가 없습니다. 티커·주수·단가를 추가하세요."
        return result

    frames = {ticker: prices.get(ticker) for ticker in result["tickers"]}
    missing = [ticker for ticker, frame in frames.items() if frame is None or frame.empty]
    if missing:
        result["error"] = f"시세를 받지 못한 종목: {', '.join(missing)}"
        return result

    closes = pd.DataFrame({ticker: frame["Close"] for ticker, frame in frames.items()}).sort_index()
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    start = pd.Timestamp(portfolio["started_on"])
    end = pd.Timestamp(today or date.today())
    closes = closes.loc[(closes.index >= start) & (closes.index <= end)]
    if closes.empty:
        result["error"] = "시작일 이후 시세가 없습니다(시작일이 미래이거나 너무 최근일 수 있습니다)."
        return result
    closes = closes.ffill()

    holdings = _holdings_over_time(trades, closes.index)
    flows = _external_flows(trades, closes.index)
    values = (holdings * closes[holdings.columns]).sum(axis=1)

    result["curve_usd"] = (_chained_twr(values, flows) - 1.0) * 100.0
    result["value_usd"] = float(values.iloc[-1])
    result["cost_usd"] = float(flows.sum())
    result["twr_pct_usd"] = float(result["curve_usd"].iloc[-1])
    if result["cost_usd"] > 0:
        result["return_pct_usd"] = (result["value_usd"] / result["cost_usd"] - 1.0) * 100.0

    if fx is not None and not fx.empty:
        rates = fx.copy()
        rates.index = pd.to_datetime(rates.index).tz_localize(None)
        rates = rates.reindex(closes.index).ffill().bfill()
        if rates.notna().any():
            values_krw = values * rates
            flows_krw = flows * rates
            result["curve_krw"] = (_chained_twr(values_krw, flows_krw) - 1.0) * 100.0
            result["value_krw"] = float(values_krw.iloc[-1])
            result["cost_krw"] = float(flows_krw.sum())
            result["twr_pct_krw"] = float(result["curve_krw"].iloc[-1])
            if result["cost_krw"] > 0:
                result["return_pct_krw"] = (result["value_krw"] / result["cost_krw"] - 1.0) * 100.0
    return result


def evaluate_all(today: Optional[date] = None, include_archived: bool = False) -> list[dict[str, Any]]:
    """저장된 포트폴리오 전부를 평가한다. 시세·환율은 여기서 한 번에 받아 재사용한다."""
    from core.fred_data import get_series
    from core.market_data import get_multiple_price_history

    portfolios = list_portfolios(include_archived=include_archived)
    if not portfolios:
        return []
    trades_by_portfolio = {p["id"]: list_trades(p["id"]) for p in portfolios}
    tickers = sorted({t["ticker"] for trades in trades_by_portfolio.values() for t in trades})
    earliest = min(p["started_on"] for p in portfolios)

    prices: dict[str, pd.DataFrame] = {}
    if tickers:
        prices = get_multiple_price_history(tickers, start=earliest.isoformat())
    try:
        fx = get_series(FX_SERIES_ID, start=earliest.isoformat())
    except Exception:  # noqa: BLE001 — 환율을 못 받아도 달러 기준은 보여준다
        fx = pd.Series(dtype=float)

    return [evaluate_portfolio(p, trades_by_portfolio[p["id"]], prices, fx, today) for p in portfolios]
