"""H3 - 테마 특정 반박가설: SPY 대신 BTC-USD를 기초자산으로 쓰는 합성 칼라가 이 바스켓을 더 잘 헤지하는가.

작업28(트랙C 세 번째 리포트, 2026-08-19)의 H2가 이미 "이 바스켓은 시장(SPY) 노출보다 비트코인
노출이 더 많은 설명력을 가진 종목이 7개 중 4개"라는 걸 회귀로 확인했었다. H1(이 리포트)은 그
연장선에서 SPY 기반 칼라가 바스켓 자체의 최악 낙폭구간(2025-10-15~2026-03-31, -71%)을 전혀 못
잡는다는 걸 실측으로 재확인했는데, 그 구간에 SPY는 겨우 -5.0% 빠진 반면(H1 로그) BTC-USD는
-43.4% 빠졌다 — 같은 구간에서 훨씬 더 큰 공행성을 보인다. 이 스크립트는 "그렇다면 SPY가 아니라
BTC를 기초자산으로 쓰는 칼라가 실제로 더 잘 방어하는가"를 직접 백테스트로 검증한다.

한계(사전 명시): BTC는 상장 옵션 기반 VIX류 내재변동성 지수를 이 저장소 인프라로 조회할 수
없어(Deribit DVOL 등은 무료 API가 아님), 21일 롤링 실현변동성을 내재변동성의 대리치로 쓴다 —
실현변동성은 미래 변동성의 완벽한 예측치가 아니고 특히 변동성 급등 국면 초입에는 후행하는
경향이 있어, SPY 버전(VIX라는 진짜 선행 지표를 쓰는 버전)보다 구조적으로 불리한 조건에서
경쟁하게 된다는 점을 결과 해석 시 감안해야 한다.
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
from collar_engine import build_overlay_returns


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

    from core.market_data import get_price_history
    spy_close = get_price_history("SPY", start="2020-01-01", end=END, use_cache=True)["Close"]
    vix_close = get_price_history("^VIX", start="2020-01-01", end=END, use_cache=True)["Close"]
    btc_close = get_price_history("BTC-USD", start="2020-01-01", end=END, use_cache=True)["Close"]

    vol_frac_spy = (vix_close / 100.0).reindex(trading_index.union(vix_close.index)).ffill()
    # BTC 21일 롤링 실현변동성(연율화, 로그수익률 표준편차) - 내재변동성 대리치(위 docstring 한계 참고)
    btc_logret = np.log(btc_close).diff()
    btc_realized_vol = (btc_logret.rolling(21).std() * np.sqrt(252)).reindex(
        trading_index.union(btc_close.index)).ffill()

    spy_collar = build_overlay_returns(trading_index, spy_close, vol_frac_spy, mode="collar")
    btc_collar = build_overlay_returns(trading_index, btc_close, btc_realized_vol, mode="collar")

    ret_spy = basket_ret + spy_collar["overlay_ret"].reindex(trading_index).fillna(0.0)
    ret_btc = basket_ret + btc_collar["overlay_ret"].reindex(trading_index).fillna(0.0)

    configs = {"unhedged": basket_ret, "collar_spy": ret_spy, "collar_btc": ret_btc}
    full_metrics = {k: metrics_from_returns(v) for k, v in configs.items()}
    log(f"전체기간: {full_metrics}")

    episode = max_drawdown_episode(basket_equity)
    ep_start, ep_end = episode["peak_date"], episode["recovery_date"]
    episode_metrics = {k: slice_metrics(v, ep_start, ep_end) for k, v in configs.items()}
    log(f"낙폭구간: {episode_metrics}")

    # 참고용: BTC/SPY 자체가 그 구간에 얼마나 빠졌는지(왜 결과가 이렇게 나왔는지 설명용 맥락)
    spy_dd = float(spy_close[ep_start:ep_end].min() / spy_close.asof(ep_start) - 1) * 100
    btc_dd = float(btc_close[ep_start:ep_end].min() / btc_close.asof(ep_start) - 1) * 100

    result = {
        "meta": {"btc_vol_proxy": "21d rolling realized vol (annualized)", "tenor_days": 21},
        "full_period": full_metrics,
        "drawdown_episode": {
            "window": episode, "spy_drawdown_in_window_pct": round(spy_dd, 2),
            "btc_drawdown_in_window_pct": round(btc_dd, 2), **episode_metrics,
        },
        "btc_roll_log_sample": btc_collar["roll_log"][:6],
    }
    with open(f"{OUT_DIR}/h3_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    ret_df = pd.DataFrame({k: v for k, v in configs.items()})
    ret_df.to_csv(f"{OUT_DIR}/h3_daily_returns.csv", encoding="utf-8-sig")

    log("H3 완료.")
    return result


if __name__ == "__main__":
    main()
