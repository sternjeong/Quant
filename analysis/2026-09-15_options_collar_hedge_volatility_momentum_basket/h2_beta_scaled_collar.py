"""H2 - 베타 스케일링 반박가설: SPY 노셔널을 1:1이 아니라 바스켓의 실측 베타만큼 키우면 나아지는가.

H1은 SPY 칼라를 "바스켓 1달러당 SPY옵션 1달러 노셔널"로 얹었다. 그런데 트랙C 작업27이 이미
실측한 이 바스켓의 베타는 2.5~6.1배(평균 4.3배 안팎)로 시장베타보다 훨씬 크다 — 즉 1:1 노셔널은
바스켓의 실제 달러 변동성 익스포저에 비해 구조적으로 과소헤지일 수 있다는 반박가설. 트레일링
126거래일 롤링 베타(collar_engine.rolling_beta, 다음 롤까지 그 시점 베타로 고정 — 실제 옵션 계약을
매월 초 그 시점 베타 추정치로 사이징하는 것과 동일한 논리, 선행편향 없음)로 오버레이 노셔널을
매월 재조정한 버전을 H1의 1:1 칼라와 비교한다.

주의(사전 명시): 베타가 크다고 해서 헤지가 반드시 나아지는 건 아니다 — H1이 이미 보여준 대로 이
바스켓의 최악 낙폭이 SPY와 디커플링된 고유(idiosyncratic) 이벤트라면, SPY 노셔널을 아무리 키워도
SPY 자체가 안 움직이는 구간에서는 프리미엄 드래그만 커지고 방어력은 그대로일 수 있다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/opt/quant")

import numpy as np
import pandas as pd

from common import (
    OUT_DIR, PIVOT_BASKET, END, ENTRY_WINDOW, STOP_PCT, MOM_WARMUP_DAYS,
    load_histories, closes_frame, find_common_start, run_trend_following_basket_returns,
    metrics_from_returns, equity_from_returns, max_drawdown_episode, log,
)
from collar_engine import build_overlay_returns, rolling_beta


def slice_metrics(ret: pd.Series, start: str, end: str) -> dict:
    w = ret[(ret.index >= start) & (ret.index <= end)]
    if len(w) < 5:
        return {"n_obs": len(w)}
    m = metrics_from_returns(w)
    m["n_obs"] = len(w)
    return m


def main():
    log("데이터 로딩...")
    hist = load_histories(PIVOT_BASKET, start="2020-01-01", end=END)
    closes = closes_frame(hist)
    common_start = find_common_start(closes, MOM_WARMUP_DAYS)
    basket_ret = run_trend_following_basket_returns(closes, common_start, ENTRY_WINDOW, STOP_PCT)
    trading_index = basket_ret.index
    basket_equity = equity_from_returns(basket_ret)

    # 바스켓 "보유중" 여부와 무관하게, 바스켓의 실현수익률(가격변화 자체, 무포지션일 때도 베타는
    # 기초자산군의 시장민감도라 전략수익률이 아니라 원자산 가격수익률로 추정하는 게 더 안정적)
    basket_price_ret = closes[PIVOT_BASKET].pct_change().mean(axis=1).reindex(trading_index).fillna(0.0)

    from core.market_data import get_price_history
    spy_close = get_price_history("SPY", start="2020-01-01", end=END, use_cache=True)["Close"]
    vix_close = get_price_history("^VIX", start="2020-01-01", end=END, use_cache=True)["Close"]
    spy_ret = spy_close.pct_change().reindex(trading_index).fillna(0.0)
    vol_frac = (vix_close / 100.0).reindex(trading_index.union(vix_close.index)).ffill()

    beta = rolling_beta(basket_price_ret, spy_ret, window=126)
    log(f"베타 분포: min={beta.min():.2f} median={beta.median():.2f} mean={beta.mean():.2f} max={beta.max():.2f}")

    collar = build_overlay_returns(trading_index, spy_close, vol_frac, mode="collar")
    overlay_ret = collar["overlay_ret"].reindex(trading_index).fillna(0.0)

    # 각 롤 시점의 베타값으로 그 롤 구간(프리미엄 진입일 + 만기 페이오프일) 전체를 고정 사이징
    roll_dates = pd.to_datetime([r["roll_date"] for r in collar["roll_log"]])
    expiry_dates = pd.to_datetime([r["expiry_date"] for r in collar["roll_log"]])
    beta_scale = pd.Series(1.0, index=trading_index)
    for rd, ed in zip(roll_dates, expiry_dates):
        b = beta.asof(rd)
        b = float(b) if pd.notna(b) else 1.0
        if rd in beta_scale.index:
            beta_scale.loc[rd] = b
        if ed in beta_scale.index:
            beta_scale.loc[ed] = b

    ret_naive = basket_ret + overlay_ret  # H1과 동일(1:1)
    ret_beta_scaled = basket_ret + overlay_ret * beta_scale

    configs = {"unhedged": basket_ret, "collar_1x_notional": ret_naive, "collar_beta_scaled": ret_beta_scaled}
    full_metrics = {k: metrics_from_returns(v) for k, v in configs.items()}
    log(f"전체기간: {full_metrics}")

    episode = max_drawdown_episode(basket_equity)
    ep_start, ep_end = episode["peak_date"], episode["recovery_date"]
    episode_metrics = {k: slice_metrics(v, ep_start, ep_end) for k, v in configs.items()}
    log(f"낙폭구간: {episode_metrics}")

    result = {
        "meta": {"beta_window": 126, "beta_min_cap": 0.5, "beta_max_cap": 8.0},
        "beta_stats": {
            "min": round(float(beta.min()), 2), "median": round(float(beta.median()), 2),
            "mean": round(float(beta.mean()), 2), "max": round(float(beta.max()), 2),
            "n_rolls_used": len(roll_dates),
        },
        "full_period": full_metrics,
        "drawdown_episode": {"window": episode, **episode_metrics},
    }
    with open(f"{OUT_DIR}/h2_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    ret_df = pd.DataFrame({k: v for k, v in configs.items()})
    ret_df.to_csv(f"{OUT_DIR}/h2_daily_returns.csv", encoding="utf-8-sig")

    log("H2 완료.")
    return result


if __name__ == "__main__":
    main()
