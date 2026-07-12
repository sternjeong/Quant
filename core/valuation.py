"""모듈 F: 밸류에이션 도구.

한 종목에 대해 여러 밸류에이션 방법론(DCF, DDM, PER/PBR 상대가치, EV/EBITDA, PEG, Graham Number)을
동시에 계산해서 비교할 수 있게 한다. 특정 방법론이 "정답"이 아니라, 여러 기법의 결과를 나란히 놓고
사용자가 직접 판단하는 것이 목표(SPEC.md 모듈 F 참고).

설계 원칙 (core.nl_strategy / core.screener 와 동일):
- 외부 데이터 조회(fetch_valuation_inputs)만 네트워크를 타고, 나머지 계산 함수는 순수 함수라 단위
  테스트가 쉽다.
- 입력값이 없거나(예: 배당을 안 주는 종목의 DDM) 계산이 불가능하면 예외 대신 None을 반환한다.
- PER/PBR 히스토리 밴드는 분기별 실제 EPS/BVPS 데이터가 유료라, 현재 EPS/BVPS를 과거 주가에
  적용하는 근사치를 사용한다(업계에서도 흔히 쓰는 간이 방식). UI에 근사치임을 명시한다.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import yfinance as yf

from core.market_data import get_price_history


def fetch_valuation_inputs(ticker: str) -> dict:
    """yfinance .info 에서 밸류에이션 계산에 필요한 입력값을 모은다.

    조회 실패/누락된 값은 None (예외를 던지지 않음).
    """
    keys = [
        "currentPrice",
        "regularMarketPrice",
        "trailingEps",
        "bookValue",
        "trailingPE",
        "priceToBook",
        "dividendRate",
        "freeCashflow",
        "sharesOutstanding",
        "totalDebt",
        "totalCash",
        "enterpriseValue",
        "ebitda",
        "earningsGrowth",
        "sector",
        "longName",
    ]
    result: dict = {k: None for k in keys}
    result["ticker"] = ticker
    try:
        info = yf.Ticker(ticker).info
        for k in keys:
            result[k] = info.get(k)
        if result["currentPrice"] is None:
            result["currentPrice"] = result.get("regularMarketPrice")
    except Exception:
        pass
    return result


# ----------------------------------------------------------------------------
# 개별 방법론 (순수 함수 - 값이 없으면 None 반환, 예외 없음)
# ----------------------------------------------------------------------------


def dcf_intrinsic_value(
    fcf: Optional[float],
    shares_outstanding: Optional[float],
    growth_rate: float = 0.08,
    discount_rate: float = 0.10,
    terminal_growth: float = 0.025,
    years: int = 5,
) -> Optional[float]:
    """잉여현금흐름(FCF) 기반 DCF로 주당 내재가치를 추정한다.

    growth_rate 로 향후 years 년 FCF를 성장시켜 discount_rate 로 현재가치 할인하고,
    이후는 terminal_growth 로 영구성장(Gordon growth)한다고 가정한 터미널 가치를 더한다.
    """
    if not fcf or not shares_outstanding or fcf <= 0 or shares_outstanding <= 0:
        return None
    if discount_rate <= terminal_growth:
        return None  # 할인율이 영구성장률보다 낮으면 모델이 발산

    pv_sum = 0.0
    projected_fcf = fcf
    for year in range(1, years + 1):
        projected_fcf *= 1 + growth_rate
        pv_sum += projected_fcf / ((1 + discount_rate) ** year)

    terminal_value = (projected_fcf * (1 + terminal_growth)) / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1 + discount_rate) ** years)

    enterprise_value = pv_sum + pv_terminal
    return enterprise_value / shares_outstanding


def ddm_intrinsic_value(
    dividend_per_share: Optional[float],
    required_return: float = 0.09,
    growth_rate: float = 0.03,
) -> Optional[float]:
    """배당할인모형(Gordon Growth Model)으로 주당 내재가치를 추정한다."""
    if not dividend_per_share or dividend_per_share <= 0:
        return None
    if required_return <= growth_rate:
        return None
    next_dividend = dividend_per_share * (1 + growth_rate)
    return next_dividend / (required_return - growth_rate)


def per_relative_value(eps: Optional[float], peer_per: Optional[float]) -> Optional[float]:
    """동종업계 평균 PER을 EPS에 적용한 상대가치."""
    if not eps or not peer_per or eps <= 0:
        return None
    return eps * peer_per


def pbr_relative_value(book_value_per_share: Optional[float], peer_pbr: Optional[float]) -> Optional[float]:
    """동종업계 평균 PBR을 BVPS에 적용한 상대가치."""
    if not book_value_per_share or not peer_pbr or book_value_per_share <= 0:
        return None
    return book_value_per_share * peer_pbr


def ev_ebitda_relative_value(
    ebitda: Optional[float],
    peer_multiple: Optional[float],
    net_debt: Optional[float],
    shares_outstanding: Optional[float],
) -> Optional[float]:
    """동종업계 평균 EV/EBITDA 배수를 적용해 EV를 구하고, 순부채를 빼서 주당 가치로 환산한다."""
    if not ebitda or not peer_multiple or not shares_outstanding or shares_outstanding <= 0:
        return None
    implied_ev = ebitda * peer_multiple
    equity_value = implied_ev - (net_debt or 0)
    return equity_value / shares_outstanding


def peg_ratio(per: Optional[float], earnings_growth_pct: Optional[float]) -> Optional[float]:
    """PEG = PER / (연간 이익성장률, %). 1.0 근방이면 성장 대비 적정가로 흔히 해석된다."""
    if not per or not earnings_growth_pct or earnings_growth_pct <= 0:
        return None
    return per / earnings_growth_pct


def graham_number(eps: Optional[float], book_value_per_share: Optional[float]) -> Optional[float]:
    """벤저민 그레이엄의 안전마진 공식: sqrt(22.5 * EPS * BVPS)."""
    if not eps or not book_value_per_share or eps <= 0 or book_value_per_share <= 0:
        return None
    return (22.5 * eps * book_value_per_share) ** 0.5


# ----------------------------------------------------------------------------
# 종합
# ----------------------------------------------------------------------------


def compute_all_valuations(ticker: str, assumptions: Optional[dict] = None, inputs: Optional[dict] = None) -> dict:
    """한 종목에 대해 모든 방법론을 계산해서 한번에 반환한다 (UI 탭/카드 비교용).

    Args:
        ticker: 종목 티커
        assumptions: DCF/DDM 가정치 오버라이드
            {"dcf_growth_rate", "dcf_discount_rate", "dcf_terminal_growth", "dcf_years",
             "ddm_required_return", "ddm_growth_rate", "peer_per", "peer_pbr", "peer_ev_ebitda"}
        inputs: fetch_valuation_inputs(ticker) 결과를 미리 전달(테스트/재사용 시). None이면 새로 조회.

    Returns:
        {"ticker", "current_price", "methods": {method_name: {"value": float|None, "label": str}}}
    """
    assumptions = assumptions or {}
    data = inputs if inputs is not None else fetch_valuation_inputs(ticker)

    earnings_growth_pct = (data.get("earningsGrowth") or 0) * 100 if data.get("earningsGrowth") is not None else None

    methods = {
        "dcf": {
            "label": "DCF (현금흐름할인)",
            "value": dcf_intrinsic_value(
                data.get("freeCashflow"),
                data.get("sharesOutstanding"),
                growth_rate=assumptions.get("dcf_growth_rate", 0.08),
                discount_rate=assumptions.get("dcf_discount_rate", 0.10),
                terminal_growth=assumptions.get("dcf_terminal_growth", 0.025),
                years=assumptions.get("dcf_years", 5),
            ),
        },
        "ddm": {
            "label": "DDM (배당할인모형)",
            "value": ddm_intrinsic_value(
                data.get("dividendRate"),
                required_return=assumptions.get("ddm_required_return", 0.09),
                growth_rate=assumptions.get("ddm_growth_rate", 0.03),
            ),
        },
        "per_relative": {
            "label": "PER 상대가치",
            "value": per_relative_value(data.get("trailingEps"), assumptions.get("peer_per", data.get("trailingPE"))),
        },
        "pbr_relative": {
            "label": "PBR 상대가치",
            "value": pbr_relative_value(data.get("bookValue"), assumptions.get("peer_pbr", data.get("priceToBook"))),
        },
        "ev_ebitda": {
            "label": "EV/EBITDA 상대가치",
            "value": ev_ebitda_relative_value(
                data.get("ebitda"),
                assumptions.get(
                    "peer_ev_ebitda",
                    (data["enterpriseValue"] / data["ebitda"])
                    if data.get("enterpriseValue") and data.get("ebitda")
                    else None,
                ),
                (data.get("totalDebt") or 0) - (data.get("totalCash") or 0),
                data.get("sharesOutstanding"),
            ),
        },
        "graham_number": {
            "label": "그레이엄 넘버",
            "value": graham_number(data.get("trailingEps"), data.get("bookValue")),
        },
    }

    peg = {
        "label": "PEG 비율",
        "value": peg_ratio(data.get("trailingPE"), earnings_growth_pct),
    }

    return {
        "ticker": ticker,
        "name": data.get("longName"),
        "sector": data.get("sector"),
        "current_price": data.get("currentPrice"),
        "methods": methods,
        "peg": peg,
    }


# ----------------------------------------------------------------------------
# PER/PBR 히스토리 밴드 + 피어 비교
# ----------------------------------------------------------------------------


def get_valuation_band(ticker: str, years: int = 5, inputs: Optional[dict] = None) -> pd.DataFrame:
    """PER/PBR 히스토리 밴드 차트용 데이터를 만든다.

    현재 EPS/BVPS를 과거 주가에 그대로 적용한 근사치이다(분기별 실제 EPS 이력은 무료로 구하기 어려움).
    Returns:
        columns: Close, PER, PBR (DatetimeIndex)
    """
    data = inputs if inputs is not None else fetch_valuation_inputs(ticker)
    eps = data.get("trailingEps")
    bvps = data.get("bookValue")

    start = pd.Timestamp.today() - pd.DateOffset(years=years)
    df = get_price_history(ticker, start=start.strftime("%Y-%m-%d"))
    if df.empty:
        return pd.DataFrame(columns=["Close", "PER", "PBR"])

    result = pd.DataFrame(index=df.index)
    result["Close"] = df["Close"]
    result["PER"] = df["Close"] / eps if eps else None
    result["PBR"] = df["Close"] / bvps if bvps else None
    return result


def get_peer_comparison(tickers: list[str]) -> pd.DataFrame:
    """여러 종목의 밸류에이션 멀티플을 나란히 비교하는 테이블을 만든다."""
    rows = []
    for ticker in tickers:
        data = fetch_valuation_inputs(ticker)
        ev_ebitda = (
            data["enterpriseValue"] / data["ebitda"] if data.get("enterpriseValue") and data.get("ebitda") else None
        )
        rows.append(
            {
                "ticker": ticker,
                "name": data.get("longName"),
                "sector": data.get("sector"),
                "per": data.get("trailingPE"),
                "pbr": data.get("priceToBook"),
                "ev_ebitda": ev_ebitda,
                "current_price": data.get("currentPrice"),
            }
        )
    return pd.DataFrame(rows)
