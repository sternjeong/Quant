"""2개 신규 바스켓(EV SPAC 붐-버스트 / 희귀질환 바이오텍 촉매주)에 작업27(IREN류) 챔피언 로직을
그대로 이식 — 새 백테스트 로직 발명 없음.

analysis/2026-08-16_iren_volatile_momentum_stocks/backtest.py 의 find_common_start /
build_momentum_weights / run_rotation / donchian_trailing_stop_positions /
run_trend_following_single / run_trend_following_basket 를 import로 그대로 재사용
(basket_common.py/2026-09-14_nonai_control_basket_volatility_momentum 와 동일 패턴).
"""
import json

import numpy as np
import pandas as pd

from basket_common2 import BASKETS, BENCH, OUT_DIR, END, FEE_BPS, load_histories, closes_frame, metrics_from_returns

# 작업27 원본 챔피언 로직 재사용 (새 방법론 발명 없음). 모듈명 충돌(둘 다 "common"으로 캐시)을
# 피하려고 basket_common2.py로 별도 명명한 것은 basket_common.py와 동일한 관례.
from backtest import (  # noqa: E402
    find_common_start,
    run_rotation,
    donchian_trailing_stop_positions,
    run_trend_following_single,
    run_trend_following_basket,
)
from core.backtest_engine import run_buy_and_hold

ENTRY_WINDOW = 20
STOP_PCT = 0.15
MOM_WINDOW = 126  # IREN 연구와 동일 (6개월 웜업 후 랭킹)


def log(msg):
    print(f"[bt] {msg}", flush=True)


def basket_static_buy_hold(closes: pd.DataFrame, start: pd.Timestamp) -> tuple[dict, pd.Series]:
    """바스켓 균등가중, 최초 1회만 배분 후 리밸런싱 없음(정적 매수후보유)."""
    sliced = closes[closes.index >= start]
    n = sliced.shape[1]
    shares = (1.0 / n) / sliced.iloc[0]
    equity = (sliced * shares).sum(axis=1) * 100.0
    ret = equity.pct_change().fillna(0.0)
    return metrics_from_returns(ret)


def main():
    result = {"meta": {
        "end_date": END, "fee_bps_oneway": FEE_BPS, "round_trip_cost_pct": FEE_BPS * 2 / 100,
        "entry_window": ENTRY_WINDOW, "stop_pct": STOP_PCT, "momentum_window_days": MOM_WINDOW,
    }}

    log("SPY 벤치마크 로딩...")
    spy_hist = load_histories(BENCH)
    spy_close = closes_frame(spy_hist)["SPY"]

    for name, cfg in BASKETS.items():
        log(f"===== 바스켓: {name} ({cfg['label']}) =====")
        tickers = cfg["tickers"]
        rep = cfg["representative"]
        top_n = max(1, (len(tickers) + 1) // 2)

        hist = load_histories(tickers)
        closes = closes_frame(hist)
        listing_dates = {
            t: (closes[t].first_valid_index().date().isoformat() if closes[t].first_valid_index() is not None else None)
            for t in tickers
        }
        log(f"  상장일: {listing_dates}")

        common_start = find_common_start(closes.dropna(how="all"), MOM_WINDOW)
        log(f"  공통시작일(모멘텀 웜업 {MOM_WINDOW}거래일 확보): {common_start.date()}")

        entry = {
            "tickers": tickers,
            "representative": rep,
            "label": cfg["label"],
            "narrative": cfg["narrative"],
            "predicted_high_correlation": cfg["predicted_high_correlation"],
            "predicted_reproduce": cfg["predicted_reproduce"],
            "listing_dates": listing_dates,
            "common_start": common_start.date().isoformat(),
            "end": END,
            "top_n": top_n,
        }

        rep_bh_full = run_buy_and_hold(rep, start=listing_dates[rep], end=END, fee_bps=FEE_BPS)
        rep_close_common = closes[rep][closes.index >= common_start].dropna()
        rep_ret_common = rep_close_common.pct_change().fillna(0.0)
        rep_bh_common_m, _ = metrics_from_returns(rep_ret_common)
        entry["representative_buy_hold_full"] = {"metrics": rep_bh_full.metrics, "start": listing_dates[rep], "end": END}
        entry["representative_buy_hold_common_window"] = rep_bh_common_m
        log(f"  대표종목({rep}) 매수후보유 공통구간 샤프: {rep_bh_common_m['sharpe']}")

        m_bh, eq_bh = basket_static_buy_hold(closes, common_start)
        entry["basket_static_buy_hold"] = m_bh
        log(f"  바스켓 정적 매수후보유 샤프: {m_bh['sharpe']}")

        spy_common = spy_close[spy_close.index >= common_start].dropna()
        spy_ret = spy_common.pct_change().fillna(0.0)
        m_spy, _ = metrics_from_returns(spy_ret)
        entry["spy_buy_hold_common_window"] = m_spy

        m_rot, eq_rot, _ = run_rotation(closes, common_start, MOM_WINDOW, top_n)
        entry["momentum_rotation"] = m_rot
        log(f"  모멘텀 로테이션(top{top_n}) 샤프: {m_rot['sharpe']}")

        m_tf_single, eq_tf_single, pos_single = run_trend_following_single(
            closes[rep].dropna(), common_start, ENTRY_WINDOW, STOP_PCT
        )
        m_tf_basket, eq_tf_basket, pos_basket = run_trend_following_basket(
            closes, common_start, ENTRY_WINDOW, STOP_PCT
        )
        entry["trend_following_single"] = m_tf_single
        entry["trend_following_basket"] = m_tf_basket
        log(f"  추세추종 단일({rep}) 샤프: {m_tf_single['sharpe']}, 바스켓 샤프: {m_tf_basket['sharpe']}")

        sliced_close = closes[rep][closes.index >= common_start].dropna()
        pos_sliced = pos_single.loc[sliced_close.index]
        daily_ret = sliced_close.pct_change().fillna(0.0)
        executed = pos_sliced.shift(1).fillna(0).astype(float)
        turnover = executed.diff().abs().fillna(0.0)
        from basket_common2 import COST_RATE
        single_strat_ret = daily_ret * executed - turnover * COST_RATE
        single_strat_ret.to_csv(f"{OUT_DIR}/{name}_single_trend_ret.csv")

        n_active = pos_basket.reindex(closes.index).fillna(0).sum(axis=1).replace(0, np.nan)
        weights = pos_basket.reindex(closes.index).fillna(0).div(n_active, axis=0).fillna(0.0)
        sliced_closes = closes[closes.index >= common_start]
        w = weights.loc[sliced_closes.index]
        daily_ret_b = sliced_closes.pct_change().fillna(0.0)
        executed_w = w.shift(1).fillna(0.0)
        port_ret = (daily_ret_b * executed_w).sum(axis=1)
        cost = executed_w.diff().abs().sum(axis=1).fillna(0.0) * COST_RATE
        basket_strat_ret = port_ret - cost
        basket_strat_ret.to_csv(f"{OUT_DIR}/{name}_basket_trend_ret.csv")

        result[name] = entry

    with open(f"{OUT_DIR}/backtest_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR}/backtest_results.json")


if __name__ == "__main__":
    main()
