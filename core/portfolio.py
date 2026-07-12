"""모듈 H: 포트폴리오 관리.

실제 보유 종목/수량/매입가를 입력하면 손익, 리스크(변동성/상관관계/섹터 집중도)를 계산하고,
AI가 포트폴리오에 대한 코멘트를 생성한다.

계산 함수(compute_*)는 순수 함수로 만들어 단위 테스트가 쉽고, get_portfolio_* 함수가 DB/시장데이터
조회와 조합해 실제 사용 흐름을 제공한다. 섹터 정보는 core.screener.get_fundamentals 를 재사용해
yfinance 조회 로직을 중복 구현하지 않는다 (README 개발 컨벤션: 공용 로직은 core/에, 재사용).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from typing import Any, Optional

import pandas as pd

from core import gemini_client
from core.db import get_session
from core.market_data import get_latest_price, get_multiple_price_history
from core.models import PortfolioHolding
from core.screener import get_fundamentals

TRADING_DAYS_PER_YEAR = 252

SYSTEM_PROMPT = """\
당신은 개인 투자자의 포트폴리오를 분석하는 투자 어드바이저입니다.
주어진 보유 종목별 손익 현황과 리스크 지표(변동성, 섹터 집중도)를 바탕으로,
과도한 집중 위험이나 눈에 띄는 손익 특이사항을 짚어주는 3~5문장의 한국어 코멘트를 작성하세요.
투자 조언이 아니라 참고용 관찰임을 유지하고, 특정 종목 매수/매도를 직접 권유하지 마세요.
"""


# ----------------------------------------------------------------------------
# 보유 종목 CRUD
# ----------------------------------------------------------------------------


def add_holding(ticker: str, quantity: float, purchase_price: float, purchase_date: date) -> int:
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("티커를 입력해주세요.")
    if quantity <= 0:
        raise ValueError("보유 수량은 0보다 커야 합니다.")
    if purchase_price <= 0:
        raise ValueError("매입 단가는 0보다 커야 합니다.")

    with get_session() as session:
        holding = PortfolioHolding(
            ticker=ticker, quantity=quantity, purchase_price=purchase_price, purchase_date=purchase_date
        )
        session.add(holding)
        session.flush()
        return holding.id


def update_holding(
    holding_id: int,
    quantity: Optional[float] = None,
    purchase_price: Optional[float] = None,
    purchase_date: Optional[date] = None,
) -> None:
    with get_session() as session:
        holding = session.get(PortfolioHolding, holding_id)
        if holding is None:
            raise ValueError(f"보유 종목(id={holding_id})을 찾을 수 없습니다.")
        if quantity is not None:
            holding.quantity = quantity
        if purchase_price is not None:
            holding.purchase_price = purchase_price
        if purchase_date is not None:
            holding.purchase_date = purchase_date


def remove_holding(holding_id: int) -> None:
    with get_session() as session:
        holding = session.get(PortfolioHolding, holding_id)
        if holding is not None:
            session.delete(holding)


def list_holdings() -> list[dict]:
    with get_session() as session:
        rows = session.query(PortfolioHolding).order_by(PortfolioHolding.purchase_date.desc()).all()
        return [
            {
                "id": r.id,
                "ticker": r.ticker,
                "quantity": r.quantity,
                "purchase_price": r.purchase_price,
                "purchase_date": r.purchase_date,
            }
            for r in rows
        ]


# ----------------------------------------------------------------------------
# 손익 계산
# ----------------------------------------------------------------------------


def compute_pnl(holdings: list[dict], current_prices: dict[str, Optional[float]]) -> pd.DataFrame:
    """보유 종목 리스트 + 현재가로 손익 테이블을 계산한다 (순수 함수).

    Args:
        holdings: [{"ticker", "quantity", "purchase_price"}, ...]
        current_prices: {ticker: 현재가 or None}

    Returns:
        columns: ticker, quantity, purchase_price, current_price, cost_basis, market_value,
                 pnl, pnl_pct, weight_pct
    """
    rows = []
    for h in holdings:
        price = current_prices.get(h["ticker"])
        cost_basis = h["quantity"] * h["purchase_price"]
        market_value = h["quantity"] * price if price is not None else None
        pnl = (market_value - cost_basis) if market_value is not None else None
        pnl_pct = (pnl / cost_basis * 100) if pnl is not None and cost_basis else None
        rows.append(
            {
                "ticker": h["ticker"],
                "quantity": h["quantity"],
                "purchase_price": h["purchase_price"],
                "current_price": price,
                "cost_basis": cost_basis,
                "market_value": market_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            }
        )

    df = pd.DataFrame(
        rows,
        columns=["ticker", "quantity", "purchase_price", "current_price", "cost_basis", "market_value", "pnl", "pnl_pct"],
    )
    total_value = df["market_value"].sum(skipna=True) if not df.empty else 0
    df["weight_pct"] = (df["market_value"] / total_value * 100) if total_value else None
    return df


def get_portfolio_pnl() -> pd.DataFrame:
    """DB에 저장된 보유 종목의 실시간 손익 테이블을 계산한다."""
    holdings = list_holdings()
    if not holdings:
        return compute_pnl([], {})
    tickers = sorted({h["ticker"] for h in holdings})
    current_prices = {t: get_latest_price(t) for t in tickers}
    return compute_pnl(holdings, current_prices)


# ----------------------------------------------------------------------------
# 리스크 지표: 변동성 / 상관관계 / 섹터 집중도
# ----------------------------------------------------------------------------


def compute_daily_returns(price_histories: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """{ticker: OHLCV DataFrame} -> 일간 수익률 DataFrame (컬럼=티커, 공통 거래일만 정렬)."""
    returns = {}
    for ticker, df in price_histories.items():
        if df is not None and not df.empty and "Close" in df.columns:
            returns[ticker] = df["Close"].pct_change().dropna()
    if not returns:
        return pd.DataFrame()
    return pd.DataFrame(returns).dropna(how="any")


def compute_portfolio_volatility(daily_returns: pd.DataFrame, weights: dict[str, float]) -> Optional[float]:
    """연환산 포트폴리오 변동성(%). weights는 {ticker: 비중(0~1)}."""
    if daily_returns.empty:
        return None
    aligned_weights = pd.Series({t: weights.get(t, 0.0) for t in daily_returns.columns})
    portfolio_returns = daily_returns.mul(aligned_weights, axis=1).sum(axis=1)
    return float(portfolio_returns.std() * (TRADING_DAYS_PER_YEAR ** 0.5) * 100)


def compute_correlation_matrix(daily_returns: pd.DataFrame) -> pd.DataFrame:
    """종목 간 일간수익률 상관계수 행렬."""
    if daily_returns.empty:
        return pd.DataFrame()
    return daily_returns.corr()


def compute_sector_concentration(holdings_with_value: list[dict], sectors: dict[str, Optional[str]]) -> dict[str, float]:
    """{"섹터": 비중(%)}. 섹터를 확인하지 못한 종목은 '기타'로 묶는다."""
    totals: dict[str, float] = defaultdict(float)
    grand_total = 0.0
    for h in holdings_with_value:
        value = h.get("market_value") or 0.0
        sector = sectors.get(h["ticker"]) or "기타"
        totals[sector] += value
        grand_total += value
    if grand_total == 0:
        return {}
    return {sector: value / grand_total * 100 for sector, value in totals.items()}


def get_portfolio_risk(pnl_df: Optional[pd.DataFrame] = None, lookback_days: int = 365) -> dict[str, Any]:
    """실시간 데이터를 조회해 변동성/상관관계/섹터 집중도를 한번에 계산한다."""
    if pnl_df is None:
        pnl_df = get_portfolio_pnl()

    if pnl_df.empty:
        return {"volatility": None, "correlation": pd.DataFrame(), "sector_concentration": {}}

    tickers = pnl_df["ticker"].tolist()
    start = (pd.Timestamp.today() - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    price_histories = get_multiple_price_history(tickers, start=start)
    daily_returns = compute_daily_returns(price_histories)

    weights = {
        row["ticker"]: (row["weight_pct"] / 100 if pd.notna(row["weight_pct"]) else 0.0)
        for _, row in pnl_df.iterrows()
    }
    volatility = compute_portfolio_volatility(daily_returns, weights)
    correlation = compute_correlation_matrix(daily_returns)

    sectors = {t: get_fundamentals(t).get("sector") for t in tickers}
    sector_concentration = compute_sector_concentration(pnl_df.to_dict("records"), sectors)

    return {"volatility": volatility, "correlation": correlation, "sector_concentration": sector_concentration}


# ----------------------------------------------------------------------------
# AI 코멘트
# ----------------------------------------------------------------------------


def _fallback_comment(pnl_df: pd.DataFrame, risk: dict[str, Any]) -> str:
    if pnl_df.empty:
        return "등록된 보유 종목이 없습니다. 먼저 보유 종목을 추가해주세요."

    total_value = pnl_df["market_value"].sum(skipna=True)
    total_cost = pnl_df["cost_basis"].sum(skipna=True)
    total_pnl = total_value - total_cost if total_value else None
    total_pnl_pct = (total_pnl / total_cost * 100) if total_pnl is not None and total_cost else None

    lines = ["[자동 생성 실패 - 규칙 기반 요약] GEMINI_API_KEY가 없거나 호출에 실패해 간단한 통계만 보여드립니다."]
    if total_pnl_pct is not None:
        lines.append(f"전체 평가손익은 {total_pnl_pct:+.1f}% ({total_pnl:+,.0f}달러)입니다.")

    sector_concentration = risk.get("sector_concentration") or {}
    if sector_concentration:
        top_sector, top_pct = max(sector_concentration.items(), key=lambda kv: kv[1])
        if top_pct >= 40:
            lines.append(f"'{top_sector}' 섹터 비중이 {top_pct:.1f}%로 상당히 집중되어 있습니다.")

    if risk.get("volatility") is not None:
        lines.append(f"최근 1년 기준 연환산 포트폴리오 변동성은 약 {risk['volatility']:.1f}%입니다.")

    return " ".join(lines)


def generate_portfolio_comment(pnl_df: pd.DataFrame, risk: dict[str, Any]) -> str:
    """포트폴리오 손익/리스크에 대한 AI 코멘트를 생성한다.

    GEMINI_API_KEY가 없거나 호출이 실패하면 _fallback_comment 로 대체한다 (예외를 던지지 않음).
    """
    if not gemini_client.has_api_key():
        return _fallback_comment(pnl_df, risk)

    try:
        holdings_summary = pnl_df[["ticker", "weight_pct", "pnl_pct"]].to_dict("records") if not pnl_df.empty else []
        payload = {
            "holdings": holdings_summary,
            "volatility_annualized_pct": risk.get("volatility"),
            "sector_concentration_pct": risk.get("sector_concentration"),
        }

        response = gemini_client.generate_content(
            models=gemini_client.LIGHT_TASK_MODELS,
            contents=f"다음 포트폴리오 데이터를 분석해줘:\n\n{json.dumps(payload, ensure_ascii=False)}",
            system_instruction=SYSTEM_PROMPT,
        )
        text = response.text
        return text if text else _fallback_comment(pnl_df, risk)
    except Exception as e:
        return f"[AI 호출 실패: {e}] " + _fallback_comment(pnl_df, risk)
