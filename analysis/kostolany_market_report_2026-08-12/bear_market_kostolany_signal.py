"""마지막 남은 질문: 2000~2012년(닷컴버블+금융위기) 약세장 포함 구간에서 코스톨라니 신호 자체가
순수 매수보유보다 나은가? 지금까지는 신호 없이 순수 매수보유로만 이 구간을 테스트했다.

같은 생존편향 없는 55종목 유니버스에 E4 코스톨라니 전략(튜닝된 임계값 + 추세게이트 + 부분
비중조절)을 그대로 적용해 리스크패리티+변동성타게팅과 결합, 신호 없는 버전과 비교한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import pickle
import json
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from core.position_sizing import portfolio_volatility_target_weights
from hyperparam_grid_search import classify_cycle_phase_series_param
from trend_gate_search import TUNED, build_position_trend_gated
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
START, END = "2000-01-03", "2012-12-31"
BEST_UP, BEST_DOWN = 15.0, -25.0
FINAL_SELL_WEIGHT = 0.5
STYLE = "장기"
WARMUP_DAYS = 400


def main():
    with open(f"{OUT_DIR}/bear_market_robustness_curves.pkl", "rb") as f:
        meta = pickle.load(f)
    ok_tickers = meta["ok_tickers"]
    print(f"유니버스: {len(ok_tickers)}종목", flush=True)

    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(ok_tickers, start=fetch_start, end=END, interval="1d")

    daily_rets_strategy = {}
    daily_rets_bh = {}
    for t, df in histories.items():
        if df is None or df.empty or len(df) < WARMUP_DAYS:
            continue
        phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **TUNED)
        position_full = build_position_trend_gated(phase_full, df["Close"], STYLE, BEST_UP, BEST_DOWN, FINAL_SELL_WEIGHT)
        sliced = df[df.index >= pd.Timestamp(START)]
        if sliced.empty:
            continue
        position = position_full.reindex(sliced.index).fillna(0.0)
        executed_position = position.shift(1).fillna(0.0)
        daily_ret = sliced["Close"].pct_change().fillna(0.0)
        daily_rets_strategy[t] = daily_ret * executed_position
        daily_rets_bh[t] = daily_ret

    strat_df = pd.DataFrame(daily_rets_strategy)
    bh_df = pd.DataFrame(daily_rets_bh)
    print(f"계산 완료: {strat_df.shape[1]}종목", flush=True)

    bench = run_buy_and_hold("^GSPC", START, END)

    # 동일가중 비교
    m_strat_eq, _ = metrics_from_returns(strat_df.mean(axis=1, skipna=True))
    m_bh_eq, _ = metrics_from_returns(bh_df.mean(axis=1, skipna=True))
    print("\n[동일가중] 전략:", m_strat_eq)
    print("[동일가중] 매수보유:", m_bh_eq)

    # 리스크패리티 + 변동성타게팅
    rp_w_strat = pd.Series(portfolio_volatility_target_weights(strat_df.dropna(how="all", axis=0)))
    rp_w_bh = pd.Series(portfolio_volatility_target_weights(bh_df.dropna(how="all", axis=0)))
    port_strat = (strat_df[rp_w_strat.index] * rp_w_strat).sum(axis=1)
    port_bh = (bh_df[rp_w_bh.index] * rp_w_bh).sum(axis=1)

    m_strat_rp, _ = metrics_from_returns(port_strat)
    m_bh_rp, _ = metrics_from_returns(port_bh)
    print("\n[리스크패리티] 전략:", m_strat_rp)
    print("[리스크패리티] 매수보유:", m_bh_rp)

    results = {}
    for window, tv in [(20, 20.0), (5, 20.0)]:
        scale_s = vol_target_scale(port_strat, tv, 1.0, window=window)
        m_s, _ = metrics_from_returns(port_strat * scale_s.shift(1).fillna(1.0))
        scale_b = vol_target_scale(port_bh, tv, 1.0, window=window)
        m_b, _ = metrics_from_returns(port_bh * scale_b.shift(1).fillna(1.0))
        print(f"\n[리스크패리티+vol(window={window},target={tv})] 전략:", m_s)
        print(f"[리스크패리티+vol(window={window},target={tv})] 매수보유:", m_b)
        results[f"w{window}_tv{tv}"] = {"strategy": m_s, "bh": m_b}

    print("\nS&P500(2000~2012):", bench.metrics)

    with open(f"{OUT_DIR}/bear_market_signal_comparison.json", "w", encoding="utf-8") as f:
        json.dump({
            "equal_strategy": m_strat_eq, "equal_bh": m_bh_eq,
            "riskparity_strategy": m_strat_rp, "riskparity_bh": m_bh_rp,
            "vol_target": results, "sp500_bh": bench.metrics,
        }, f, ensure_ascii=False, indent=2)
    print("DONE")


if __name__ == "__main__":
    main()
