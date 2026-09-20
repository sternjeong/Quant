"""합성 Black-Scholes 풋/칼라 오버레이 — 일반화 버전.

core.champion_strategy.build_collar_overlay_returns 는 SPY/VIX 전용으로 하드코딩돼 있다(라이브
엔진이 실제로 그렇게만 쓰이기 때문). 이 리서치는 (1) 같은 헤지를 트랙C 바스켓에 통째로 적용하고,
(2) 기초자산을 SPY가 아니라 BTC-USD로 바꿔보는 대조실험까지 해야 해서, 기초자산/변동성 시계열을
인자로 받는 일반화 버전이 필요하다.

새 옵션가격 이론을 만들지 않는다 — core.champion_strategy.bs_put_price/bs_call_price/
_fedfunds_rate_asof(Black-Scholes 폐형식 공식 + FRED 무위험금리 조회)를 그대로 import해서 쓰고,
롤 스케줄(매월 첫 거래일, core.backtest_engine._first_trading_day_of_month_mask)도 그대로 재사용한다.
이 파일이 새로 추가하는 것은 "기초자산·변동성 시계열을 바꿔 끼울 수 있게" 만든 얇은 래퍼뿐이다.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/opt/quant")

import numpy as np
import pandas as pd

from core.backtest_engine import _first_trading_day_of_month_mask
from core.champion_strategy import bs_put_price, bs_call_price, _fedfunds_rate_asof

DEFAULT_TENOR_DAYS = 21  # core.champion_strategy.COLLAR_TENOR_DAYS 와 동일(약 1개월)


def build_overlay_returns(
    trading_index: pd.DatetimeIndex,
    spot: pd.Series,
    vol_frac: pd.Series,
    mode: str = "collar",
    put_moneyness: float = 1.00,
    call_moneyness: float = 1.05,
    tenor_days: int = DEFAULT_TENOR_DAYS,
    fallback_vol: float = 0.20,
) -> dict:
    """월별 롤링 합성 풋(mode="put") 또는 칼라(mode="put"+콜매도="collar")의 일별 오버레이 수익률.

    spot: 기초자산 종가 시계열(임의 인덱스, trading_index로 reindex+ffill됨).
    vol_frac: "연율화 변동성(소수, 예 0.293)" 시계열 — SPY의 경우 VIX/100, BTC의 경우 실현변동성
    (BTC는 상장 옵션 기반 VIX 대용치를 이 저장소에서 조회할 인프라가 없어, 21일 롤링 실현변동성을
    내재변동성의 대리치로 쓴다 — 근사치라는 점을 리포트에 명시한다).
    Returns: {"overlay_ret": pd.Series(trading_index), "roll_log": [...]}
    """
    px = pd.DataFrame({"spot": spot, "vol": vol_frac}).reindex(trading_index).ffill()

    roll_mask = _first_trading_day_of_month_mask(trading_index)
    roll_dates = list(trading_index[roll_mask])
    if len(roll_dates) == 0 or roll_dates[0] != trading_index[0]:
        roll_dates = [trading_index[0]] + roll_dates

    overlay_ret = pd.Series(0.0, index=trading_index)
    roll_log = []
    for rd in roll_dates:
        pos = trading_index.get_loc(rd)
        exp_pos = min(pos + tenor_days, len(trading_index) - 1)
        expiry = trading_index[exp_pos]
        S0 = float(px.loc[rd, "spot"])
        sigma_raw = px.loc[rd, "vol"]
        sigma = float(sigma_raw) if pd.notna(sigma_raw) and sigma_raw > 0 else fallback_vol
        r = _fedfunds_rate_asof(rd)
        T = tenor_days / 252.0
        K_put = S0 * put_moneyness
        put0 = bs_put_price(S0, K_put, T, r, sigma)
        S_T = float(px.loc[expiry, "spot"])
        put_payoff = max(K_put - S_T, 0.0)

        premium_pct_debit = -put0 / S0
        payoff_pct_credit = put_payoff / S0
        K_call = None
        call0 = None
        if mode == "collar":
            K_call = S0 * call_moneyness
            call0 = bs_call_price(S0, K_call, T, r, sigma)
            call_payoff = max(S_T - K_call, 0.0)
            premium_pct_debit += call0 / S0
            payoff_pct_credit -= call_payoff / S0

        overlay_ret.loc[rd] += premium_pct_debit
        overlay_ret.loc[expiry] += payoff_pct_credit
        roll_log.append({
            "roll_date": str(rd.date()), "expiry_date": str(expiry.date()),
            "S0": round(S0, 4), "S_T": round(S_T, 4), "sigma": round(sigma, 4), "r": round(r, 4),
            "K_put": round(K_put, 4), "K_call": round(K_call, 4) if K_call is not None else None,
            "put_premium_pct": round(put0 / S0, 5),
            "call_premium_pct": round(call0 / S0, 5) if call0 is not None else None,
            "net_premium_pct_debit": round(premium_pct_debit, 5),
            "payoff_pct_credit": round(payoff_pct_credit, 5),
        })
    return {"overlay_ret": overlay_ret, "roll_log": roll_log}


def rolling_beta(asset_ret: pd.Series, mkt_ret: pd.Series, window: int = 126,
                  min_beta: float = 0.5, max_beta: float = 8.0) -> pd.Series:
    """자산 일별수익률의 시장(SPY) 대비 롤링 베타(단순 OLS 기울기 = cov/var), t시점까지의 과거
    window일만 사용(선행편향 없음). 소형/고변동성 종목 베타 추정치는 노이즈가 커서(작업28에서도
    같은 문제 지적) [min_beta, max_beta]로 윈저라이즈한다."""
    a = asset_ret.reindex(mkt_ret.index).fillna(0.0)
    m = mkt_ret.fillna(0.0)
    cov = a.rolling(window).cov(m)
    var = m.rolling(window).var()
    beta = (cov / var).clip(lower=min_beta, upper=max_beta)
    return beta
