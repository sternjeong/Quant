"""H1 — 시장 베타 헤지 가설 검증.

가설(H1): 개별 종목의 롱 포지션에 대해 SPY 대비 롤링 OLS 베타만큼 숏 헤지를 걸면(베타-중립
오버레이), 헤지 없는 순수 롱보다 샤프비율이 개선된다.

방법론:
  1. 종목별 일간수익률 vs SPY 일간수익률로 롤링(126거래일=약 6개월) OLS 베타를 추정한다.
     베타 = Cov(R_stock, R_mkt) / Var(R_mkt), 룩어헤드 방지를 위해 t일의 헤지비율은 t-1일까지의
     데이터로 추정한 베타를 쓴다(shift(1)).
  2. 헤지 포지션의 일간수익률 = R_stock,t − beta_{t-1} × R_mkt,t (달러중립 오버레이, 차입비용/
     공매도비용 미반영 — 08장 한계에서 명시).
  3. 헤지 전(순수 롱) vs 헤지 후(베타중립) CAGR·연변동성·샤프·MDD 비교.
  4. IREN 단독(가장 긴 이력)과 7종목 피어 바스켓(동일가중, 공통구간) 두 가지로 검증해 IREN
     한 종목만의 우연인지 확인한다.
  5. 참고용으로 "고정 베타"(전체 구간 단일 정적 베타) 헤지도 함께 계산해 롤링 베타 대비 효과를
     비교한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import (
    BTC_TICKER,
    MARKET_TICKER,
    PEER_TICKERS,
    align,
    daily_returns,
    fetch_close,
    one_factor_ols,
    perf_metrics,
    rolling_beta,
)

ROLLING_WINDOW = 126  # 약 6개월
# 2020-01-01 이전 구간은 WULF/CLSK/HUT 같은 오래된 티커의 "피벗 이전(리버스머지/합병 이전 셸기업)"
# 시기를 포함해 하루 +100%를 넘는 극단치(예: CLSK 2018-09-19 +386.7%)가 섞여 베타/변동성 추정을
# 왜곡한다(09장 한계 참고) — 전 종목 공통으로 2020-01-01부터 시작해 이 왜곡을 줄인다.
START = "2020-01-01"
END = "2026-08-19"


def hedge_single(ticker: str, window: int = ROLLING_WINDOW) -> dict | None:
    close = fetch_close(ticker, START, END)
    mkt_close = fetch_close(MARKET_TICKER, START, END)
    if close.empty or mkt_close.empty:
        return None
    r_stock, r_mkt = align(daily_returns(close), daily_returns(mkt_close))
    if len(r_stock) < window + 30:
        return None

    beta_roll = rolling_beta(r_stock, r_mkt, window).shift(1)  # 룩어헤드 방지
    valid = beta_roll.dropna().index
    r_stock_v = r_stock.reindex(valid)
    r_mkt_v = r_mkt.reindex(valid)
    beta_v = beta_roll.reindex(valid)
    # 극단치 클리핑 (분산이 아주 작은 구간에서 베타가 튀는 것 방지)
    beta_v_clipped = beta_v.clip(lower=-2.0, upper=5.0)

    unhedged_ret = r_stock_v
    hedged_ret = r_stock_v - beta_v_clipped * r_mkt_v

    # 정적(전체구간) 베타 헤지 — 참고 비교용
    alpha_static, beta_static, r2_static = one_factor_ols(r_stock.values, r_mkt.values)
    static_hedged_ret = r_stock_v - beta_static * r_mkt_v

    unhedged_metrics = perf_metrics(unhedged_ret)
    hedged_metrics = perf_metrics(hedged_ret)
    static_hedged_metrics = perf_metrics(static_hedged_ret)

    return {
        "ticker": ticker,
        "n_days": int(len(r_stock_v)),
        "start": str(valid.min().date()),
        "end": str(valid.max().date()),
        "avg_rolling_beta": round(float(beta_v_clipped.mean()), 3),
        "beta_std": round(float(beta_v_clipped.std()), 3),
        "static_full_sample_beta": round(beta_static, 3),
        "static_beta_r2": round(r2_static, 3),
        "unhedged": unhedged_metrics,
        "rolling_hedged": hedged_metrics,
        "static_hedged": static_hedged_metrics,
        "sharpe_improved_rolling": bool(hedged_metrics["sharpe"] > unhedged_metrics["sharpe"]),
        "sharpe_delta_rolling": round(hedged_metrics["sharpe"] - unhedged_metrics["sharpe"], 3),
        "mdd_improved_rolling": bool(hedged_metrics["mdd_pct"] > unhedged_metrics["mdd_pct"]),
    }


def hedge_basket(tickers: list[str], window: int = ROLLING_WINDOW) -> dict:
    """7종목 동일가중 바스켓을 하나의 합성 자산으로 만들어 같은 방식으로 검증(공통 구간)."""
    closes = {t: fetch_close(t, START, END) for t in tickers}
    closes = {t: c for t, c in closes.items() if not c.empty}
    rets = {t: daily_returns(c) for t, c in closes.items()}
    common_idx = None
    for r in rets.values():
        common_idx = r.index if common_idx is None else common_idx.intersection(r.index)
    common_idx = common_idx.sort_values()
    rets_aligned = pd.DataFrame({t: r.reindex(common_idx) for t, r in rets.items()}).dropna()
    basket_ret = rets_aligned.mean(axis=1)
    basket_ret.name = "BASKET"

    mkt_close = fetch_close(MARKET_TICKER, START, END)
    r_mkt = daily_returns(mkt_close)
    basket_ret_a, r_mkt_a = align(basket_ret, r_mkt)

    beta_roll = rolling_beta(basket_ret_a, r_mkt_a, window).shift(1)
    valid = beta_roll.dropna().index
    basket_v = basket_ret_a.reindex(valid)
    mkt_v = r_mkt_a.reindex(valid)
    beta_v = beta_roll.reindex(valid).clip(lower=-2.0, upper=5.0)

    unhedged_ret = basket_v
    hedged_ret = basket_v - beta_v * mkt_v

    unhedged_metrics = perf_metrics(unhedged_ret)
    hedged_metrics = perf_metrics(hedged_ret)

    return {
        "tickers": list(rets_aligned.columns),
        "n_days": int(len(basket_v)),
        "start": str(valid.min().date()),
        "end": str(valid.max().date()),
        "avg_rolling_beta": round(float(beta_v.mean()), 3),
        "unhedged": unhedged_metrics,
        "rolling_hedged": hedged_metrics,
        "sharpe_improved_rolling": bool(hedged_metrics["sharpe"] > unhedged_metrics["sharpe"]),
        "sharpe_delta_rolling": round(hedged_metrics["sharpe"] - unhedged_metrics["sharpe"], 3),
    }


def run() -> dict:
    iren = hedge_single("IREN")
    peers = {}
    for t in PEER_TICKERS:
        if t == "IREN":
            continue
        res = hedge_single(t)
        if res:
            peers[t] = res
    basket = hedge_basket(PEER_TICKERS)

    n_improved = sum(1 for t, r in peers.items() if r["sharpe_improved_rolling"]) + (1 if iren and iren["sharpe_improved_rolling"] else 0)
    n_total = len(peers) + (1 if iren else 0)

    return {
        "hypothesis": "H1",
        "window_days": ROLLING_WINDOW,
        "market_ticker": MARKET_TICKER,
        "iren": iren,
        "peers": peers,
        "basket": basket,
        "n_tickers_sharpe_improved": n_improved,
        "n_tickers_total": n_total,
        "verdict_hint": "채택" if n_improved > n_total / 2 and iren and iren["sharpe_improved_rolling"] else "기각",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
