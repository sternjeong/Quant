"""H1 - SPY 기반 합성 칼라 헤지를 트랙C 변동성모멘텀 바스켓 챔피언에 직접 이식.

작업48(analysis/2026-08-30_synthetic_options_tail_hedge)과 작업49가 이미 옵션 칼라 헤지를 백테스트
했지만, 그건 트랙D의 "point-in-time 추세추종 새틀라이트"(15%만 편입되는 위성 슬리브)에 적용한
것이었다 — 트랙C 자신의 IREN류 바스켓 챔피언(20일 돈치안+15%트레일링스탑, 100% 노셔널로 그 자체가
전략인 구성)에는 아직 한 번도 이식된 적이 없다. 이 스크립트가 그 갭을 메운다.

core.champion_strategy.bs_put_price/bs_call_price/_fedfunds_rate_asof 를 그대로 재사용하는
collar_engine.build_overlay_returns 로 SPY 종가+VIX/100(대리 내재변동성)+FRED 금리 기반 월간
롤링 풋/칼라를 만들고, 바스켓 챔피언의 일별 수익률에 100% 노셔널로 얹는다(이 바스켓 자체가
전략이므로 satellite_weight 같은 축소 없이 1:1).

비교 대상:
  - unhedged: 바스켓 챔피언 그대로
  - protective_put: ATM 풋만 매수(콜 매도 없음)
  - collar: ATM 풋 매수 + 5% OTM 콜 매도(core.champion_strategy 라이브 엔진과 동일 파라미터)

평가 구간: 전체 공통구간(2022-05-19~) + 이 바스켓 자체의 최악 낙폭 구간(공인된 2008/2020 위기
표본이 없어 데이터 주도로 정의, common.max_drawdown_episode).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/opt/quant")

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
    log(f"공통 시작일: {common_start.date()}")

    basket_ret = run_trend_following_basket_returns(closes, common_start, ENTRY_WINDOW, STOP_PCT)
    trading_index = basket_ret.index
    basket_equity = equity_from_returns(basket_ret)

    log("SPY 칼라 오버레이(collar) 구축...")
    from core.market_data import get_price_history
    spy_close = get_price_history("SPY", start="2020-01-01", end=END, use_cache=True)["Close"]
    vix_close = get_price_history("^VIX", start="2020-01-01", end=END, use_cache=True)["Close"]
    vol_frac = (vix_close / 100.0).reindex(trading_index.union(vix_close.index)).ffill()

    collar = build_overlay_returns(trading_index, spy_close, vol_frac, mode="collar")
    put_only = build_overlay_returns(trading_index, spy_close, vol_frac, mode="put")

    ret_unhedged = basket_ret
    ret_put = basket_ret + put_only["overlay_ret"].reindex(trading_index).fillna(0.0)
    ret_collar = basket_ret + collar["overlay_ret"].reindex(trading_index).fillna(0.0)

    configs = {"unhedged": ret_unhedged, "protective_put": ret_put, "collar": ret_collar}

    full_metrics = {k: metrics_from_returns(v) for k, v in configs.items()}
    log(f"전체기간 지표: {full_metrics}")

    # 이 바스켓 자체의 최악 낙폭 구간을 무헤지 챔피언 기준으로 정의(사후 유리 구간 임의선정 방지)
    episode = max_drawdown_episode(basket_equity)
    log(f"바스켓 자체 최악낙폭 구간: {episode}")
    ep_start, ep_end = episode["peak_date"], episode["recovery_date"]
    episode_metrics = {k: slice_metrics(v, ep_start, ep_end) for k, v in configs.items()}
    log(f"낙폭구간 지표: {episode_metrics}")

    equities = {k: equity_from_returns(v) for k, v in configs.items()}

    result = {
        "meta": {
            "basket": PIVOT_BASKET, "common_start": str(common_start.date()), "end": END,
            "entry_window": ENTRY_WINDOW, "stop_pct": STOP_PCT,
            "put_moneyness": 1.00, "call_moneyness": 1.05, "tenor_days": 21,
        },
        "full_period": full_metrics,
        "drawdown_episode": {"window": episode, **episode_metrics},
        "collar_roll_log_sample": collar["roll_log"][:6],
        "n_rolls": len(collar["roll_log"]),
    }
    with open(f"{OUT_DIR}/h1_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    # 부트스트랩/리포트에서 재사용할 일별수익률 시계열 저장
    ret_df = pd.DataFrame({k: v for k, v in configs.items()})
    ret_df.to_csv(f"{OUT_DIR}/h1_daily_returns.csv", encoding="utf-8-sig")
    eq_df = pd.DataFrame({k: v for k, v in equities.items()})
    eq_df.to_csv(f"{OUT_DIR}/h1_equity_curves.csv", encoding="utf-8-sig")

    log("H1 완료.")
    return result


if __name__ == "__main__":
    main()
