"""H5 최종 채택안(target_vol=12%, cap=1.0, 무레버리지) 자산곡선을 리포트용으로 저장."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, run_buy_and_hold
from core.market_data import get_multiple_price_history, get_price_history
from hyperparam_grid_search import classify_cycle_phase_series_param
from trend_gate_search import STYLE, START, END, WARMUP_DAYS, TUNED, build_position_trend_gated
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
BEST_UP, BEST_DOWN = 15.0, -25.0
FINAL_SELL_WEIGHT = 0.5
TARGET_VOL, CAP = 12.0, 1.0


def main():
    baseline_df = pd.read_csv(f"{OUT_DIR}/summary_장기.csv").set_index("theme")
    sector_tickers = [t for t in baseline_df.index if t != "S&P500"]
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(sector_tickers, start=fetch_start, end=END, interval="1d")

    daily_rets_strategy = {}
    for ticker in sector_tickers:
        df = histories[ticker]
        phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **TUNED)
        position_full = build_position_trend_gated(phase_full, df["Close"], STYLE, BEST_UP, BEST_DOWN, FINAL_SELL_WEIGHT)
        sliced = df[df.index >= pd.Timestamp(START)]
        position = position_full.loc[sliced.index]
        executed_position = position.shift(1).fillna(0.0)
        daily_ret = sliced["Close"].pct_change().fillna(0.0)
        daily_rets_strategy[ticker] = daily_ret * executed_position

    strat_df = pd.DataFrame(daily_rets_strategy).dropna(how="all")
    port_strategy_ret = strat_df.mean(axis=1)

    scale = vol_target_scale(port_strategy_ret, TARGET_VOL, CAP)
    scaled_rets = port_strategy_ret * scale.shift(1).fillna(1.0)
    vt_metrics, vt_eq = metrics_from_returns(scaled_rets)
    no_overlay_metrics, no_overlay_eq = metrics_from_returns(port_strategy_ret)

    bench_run = run_buy_and_hold("^GSPC", vt_eq.index[0].date().isoformat(), vt_eq.index[-1].date().isoformat())

    print("vol-targeted portfolio strategy:", vt_metrics)
    print("no-overlay portfolio strategy:", no_overlay_metrics)
    print("S&P500 buy&hold:", bench_run.metrics)

    with open(f"{OUT_DIR}/vol_target_final_result.json", "w", encoding="utf-8") as f:
        json.dump({
            "vol_targeted": vt_metrics,
            "no_overlay": no_overlay_metrics,
            "sp500_bh": bench_run.metrics,
            "params": {"target_vol": TARGET_VOL, "cap": CAP},
        }, f, ensure_ascii=False, indent=2)

    vt_w = vt_eq.resample("W-FRI").last().dropna()
    no_w = no_overlay_eq.resample("W-FRI").last().dropna()
    bench_w = bench_run.equity_curve.reindex(vt_eq.index).resample("W-FRI").last().dropna()
    common = vt_w.index.intersection(no_w.index).intersection(bench_w.index)
    with open(f"{OUT_DIR}/vol_target_equity_curves.json", "w", encoding="utf-8") as f:
        json.dump({
            "dates": [d.strftime("%Y-%m-%d") for d in common],
            "strategy": [round(float(v), 2) for v in vt_w.loc[common]],
            "bh": [round(float(v), 2) for v in no_w.loc[common]],
            "bench": [round(float(v), 2) for v in bench_w.loc[common]],
        }, f, ensure_ascii=False)
    print("DONE")


if __name__ == "__main__":
    main()
