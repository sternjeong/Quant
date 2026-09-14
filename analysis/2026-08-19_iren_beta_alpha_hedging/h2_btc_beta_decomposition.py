"""H2 — 테마 베타(비트코인) 분해 가설 검증.

가설(H2): 비트코인 채굴 → AI/HPC 피벗 종목군의 수익률은 시장 베타보다 비트코인 가격 익스포저가
더 큰(또는 비슷한 수준의) 설명력을 가질 수 있다. 시장수익률(SPY)과 BTC수익률(BTC-USD) 두 요인에
동시 회귀시켜 각 요인의 설명력(R²)과 잔차(고유 알파 성분)를 계산하고, 시장 베타 헤지와 BTC 베타
헤지 중 어느 쪽이 더 "노이즈"를 제거하고 고유 알파를 드러내는지(=헤지 후 잔차의 샤프가 더
높아지는지) 비교한다.

방법론:
  1. 전체 구간 정적 회귀 3종: (a) 시장만, (b) BTC만, (c) 시장+BTC 동시 — 각각의 R²를 비교한다.
  2. 롤링(126거래일) 시장+BTC 동시회귀로 시간에 따른 베타 변화를 추정(룩어헤드 방지, t-1까지
     데이터로 t일 헤지비율 결정).
  3. 헤지 시뮬레이션 3종: 시장만 헤지, BTC만 헤지, 시장+BTC 동시 헤지 — 헤지 후 잔차 수익률의
     샤프비율을 비교해 어느 헤지가 "고유 알파"를 가장 잘 드러내는지(=헤지 후 샤프가 가장 높은지)
     판정한다.
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
    two_factor_ols,
)

ROLLING_WINDOW = 126
START = "2020-01-01"  # H1과 동일한 이유로 셸기업/피벗이전 극단치 구간을 배제 (09장 한계 참고)
END = "2026-08-19"


def _rolling_two_factor_betas(y: pd.Series, x1: pd.Series, x2: pd.Series, window: int) -> pd.DataFrame:
    """루프 기반 롤링 이변량 OLS (window마다 lstsq). 데이터 크기가 작아(<3000행) 충분히 빠르다."""
    idx = y.index
    n = len(idx)
    b1_arr = np.full(n, np.nan)
    b2_arr = np.full(n, np.nan)
    yv, x1v, x2v = y.values, x1.values, x2.values
    for i in range(window, n):
        sl = slice(i - window, i)
        try:
            _, b1, b2, _ = two_factor_ols(yv[sl], x1v[sl], x2v[sl])
            b1_arr[i] = b1
            b2_arr[i] = b2
        except Exception:
            pass
    return pd.DataFrame({"beta_mkt": b1_arr, "beta_btc": b2_arr}, index=idx)


def analyze_ticker(ticker: str) -> dict | None:
    close = fetch_close(ticker, START, END)
    mkt_close = fetch_close(MARKET_TICKER, START, END)
    btc_close = fetch_close(BTC_TICKER, START, END)
    if close.empty or mkt_close.empty or btc_close.empty:
        return None
    r_stock, r_mkt, r_btc = align(daily_returns(close), daily_returns(mkt_close), daily_returns(btc_close))
    if len(r_stock) < ROLLING_WINDOW + 30:
        return None

    # --- 정적(전체구간) 회귀 3종 ---
    a_mkt, b_mkt, r2_mkt = one_factor_ols(r_stock.values, r_mkt.values)
    a_btc, b_btc, r2_btc = one_factor_ols(r_stock.values, r_btc.values)
    a_both, bb_mkt, bb_btc, r2_both = two_factor_ols(r_stock.values, r_mkt.values, r_btc.values)

    # --- 롤링 이변량 베타 (헤지 시뮬레이션용, shift(1)로 룩어헤드 방지) ---
    roll = _rolling_two_factor_betas(r_stock, r_mkt, r_btc, ROLLING_WINDOW).shift(1)
    roll_beta_mkt_only = None
    from common import rolling_beta
    beta_mkt_only_roll = rolling_beta(r_stock, r_mkt, ROLLING_WINDOW).shift(1)
    beta_btc_only_roll = rolling_beta(r_stock, r_btc, ROLLING_WINDOW).shift(1)

    valid = roll.dropna().index.intersection(beta_mkt_only_roll.dropna().index).intersection(beta_btc_only_roll.dropna().index)
    r_stock_v = r_stock.reindex(valid)
    r_mkt_v = r_mkt.reindex(valid)
    r_btc_v = r_btc.reindex(valid)
    bmkt2f = roll["beta_mkt"].reindex(valid).clip(-2, 5)
    bbtc2f = roll["beta_btc"].reindex(valid).clip(-2, 5)
    bmkt1f = beta_mkt_only_roll.reindex(valid).clip(-2, 5)
    bbtc1f = beta_btc_only_roll.reindex(valid).clip(-2, 5)

    unhedged_ret = r_stock_v
    mkt_hedged_ret = r_stock_v - bmkt1f * r_mkt_v
    btc_hedged_ret = r_stock_v - bbtc1f * r_btc_v
    both_hedged_ret = r_stock_v - bmkt2f * r_mkt_v - bbtc2f * r_btc_v

    unhedged_m = perf_metrics(unhedged_ret)
    mkt_hedged_m = perf_metrics(mkt_hedged_ret)
    btc_hedged_m = perf_metrics(btc_hedged_ret)
    both_hedged_m = perf_metrics(both_hedged_ret)

    sharpes = {
        "unhedged": unhedged_m["sharpe"],
        "market_hedge": mkt_hedged_m["sharpe"],
        "btc_hedge": btc_hedged_m["sharpe"],
        "both_hedge": both_hedged_m["sharpe"],
    }
    best_hedge = max(("market_hedge", "btc_hedge", "both_hedge"), key=lambda k: sharpes[k])

    return {
        "ticker": ticker,
        "n_days": int(len(r_stock)),
        "start": str(r_stock.index.min().date()),
        "end": str(r_stock.index.max().date()),
        "static_regression": {
            "market_only": {"alpha_daily_pct": round(a_mkt * 100, 4), "beta": round(b_mkt, 3), "r2": round(r2_mkt, 3)},
            "btc_only": {"alpha_daily_pct": round(a_btc * 100, 4), "beta": round(b_btc, 3), "r2": round(r2_btc, 3)},
            "market_and_btc": {
                "alpha_daily_pct": round(a_both * 100, 4),
                "beta_mkt": round(bb_mkt, 3),
                "beta_btc": round(bb_btc, 3),
                "r2": round(r2_both, 3),
            },
            "r2_incremental_from_btc": round(r2_both - r2_mkt, 3),
            "btc_explains_more_than_market": bool(r2_btc > r2_mkt),
        },
        "hedge_simulation": {
            "n_days": int(len(r_stock_v)),
            "start": str(valid.min().date()),
            "end": str(valid.max().date()),
            "unhedged": unhedged_m,
            "market_hedge": mkt_hedged_m,
            "btc_hedge": btc_hedged_m,
            "both_hedge": both_hedged_m,
            "sharpes": sharpes,
            "best_hedge": best_hedge,
        },
    }


def run() -> dict:
    iren = analyze_ticker("IREN")
    peers = {}
    for t in PEER_TICKERS:
        if t == "IREN":
            continue
        res = analyze_ticker(t)
        if res:
            peers[t] = res

    all_results = ({"IREN": iren} if iren else {}) | peers
    n_btc_wins_r2 = sum(1 for r in all_results.values() if r["static_regression"]["btc_explains_more_than_market"])
    avg_r2_mkt = float(np.mean([r["static_regression"]["market_only"]["r2"] for r in all_results.values()]))
    avg_r2_btc = float(np.mean([r["static_regression"]["btc_only"]["r2"] for r in all_results.values()]))
    avg_r2_both = float(np.mean([r["static_regression"]["market_and_btc"]["r2"] for r in all_results.values()]))
    best_hedge_counts: dict[str, int] = {}
    for r in all_results.values():
        bh = r["hedge_simulation"]["best_hedge"]
        best_hedge_counts[bh] = best_hedge_counts.get(bh, 0) + 1

    return {
        "hypothesis": "H2",
        "window_days": ROLLING_WINDOW,
        "iren": iren,
        "peers": peers,
        "summary": {
            "n_tickers": len(all_results),
            "n_btc_r2_greater_than_market_r2": n_btc_wins_r2,
            "avg_r2_market_only": round(avg_r2_mkt, 3),
            "avg_r2_btc_only": round(avg_r2_btc, 3),
            "avg_r2_market_and_btc": round(avg_r2_both, 3),
            "best_hedge_vote_counts": best_hedge_counts,
        },
        "verdict_hint": "채택" if n_btc_wins_r2 > len(all_results) / 2 else "기각",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
