"""1) TUNED+trend-gate 결합 위에 부분 비중조절(sell_weight)까지 스윕.
2) 최종 선택된 방법으로 50종목 동일가중 포트폴리오 레벨 성과(분산효과) 계산.

전부 core.backtest_engine/core.strategy_engine의 기존 계산 함수를 재사용한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, compute_equity_curve, run_buy_and_hold
from core.market_data import get_multiple_price_history, get_price_history
from core.strategy_engine import extract_trades
from hyperparam_grid_search import BASELINE, classify_cycle_phase_series_param
from trend_gate_search import STYLE, START, END, WARMUP_DAYS, TUNED, build_position_trend_gated, run_one, eval_combo

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
BEST_UP, BEST_DOWN = 15.0, -25.0


def main():
    baseline_df = pd.read_csv(f"{OUT_DIR}/summary_장기.csv").set_index("theme")
    sector_tickers = [t for t in baseline_df.index if t != "S&P500"]
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(sector_tickers, start=fetch_start, end=END, interval="1d")
    histories["S&P500"] = get_price_history("^GSPC", start=fetch_start, end=END, interval="1d")

    # --- 1) sell_weight 스윕 ---
    print("=== sell_weight sweep on TUNED+gate ===", flush=True)
    sw_rows = []
    for sw in [0.0, 0.25, 0.5, 0.75]:
        summary, _ = eval_combo(histories, baseline_df, TUNED, BEST_UP, BEST_DOWN, sell_weight=sw)
        sw_rows.append({"sell_weight": sw, **summary})
        print(sw, summary, flush=True)
    sw_df = pd.DataFrame(sw_rows)
    sw_df.to_csv(f"{OUT_DIR}/sell_weight_sweep.csv", index=False, encoding="utf-8-sig")
    best_sw_row = sw_df.sort_values("mean_sharpe", ascending=False).iloc[0]
    best_sw = float(best_sw_row["sell_weight"])
    print("best sell_weight:", best_sw, "->", best_sw_row.to_dict(), flush=True)

    # --- 2) 최종 방법(FINAL = TUNED + gate(15,-25) + best sell_weight) 결정, 종목별 결과+자산곡선 저장 ---
    final_summary, final_pt = eval_combo(histories, baseline_df, TUNED, BEST_UP, BEST_DOWN, sell_weight=best_sw)
    print("FINAL method summary:", final_summary, flush=True)
    final_pt.to_csv(f"{OUT_DIR}/final_method_per_ticker.csv", index=False, encoding="utf-8-sig")

    # 자산곡선까지 필요한 대표 종목들(원래 리포트의 best/worst/defensive/S&P500) 재계산해서 저장
    import pickle
    equity_curves_final = {}
    for ticker, df in histories.items():
        phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **TUNED)
        position_full = build_position_trend_gated(phase_full, df["Close"], STYLE, BEST_UP, BEST_DOWN, best_sw)
        sliced = df[df.index >= pd.Timestamp(START)]
        position = position_full.loc[sliced.index]
        equity_curves_final[ticker] = compute_equity_curve(sliced, position)
    with open(f"{OUT_DIR}/equity_curves_final.pkl", "wb") as f:
        pickle.dump(equity_curves_final, f)

    # --- 3) 포트폴리오 레벨(50종목 동일가중) 분산효과 ---
    print("\n=== Portfolio-level (equal-weight, 50 sector tickers) ===", flush=True)
    daily_rets_strategy = {}
    daily_rets_bh = {}
    for ticker in sector_tickers:
        df = histories[ticker]
        phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **TUNED)
        position_full = build_position_trend_gated(phase_full, df["Close"], STYLE, BEST_UP, BEST_DOWN, best_sw)
        sliced = df[df.index >= pd.Timestamp(START)]
        position = position_full.loc[sliced.index]
        executed_position = position.shift(1).fillna(0.0)
        daily_ret = sliced["Close"].pct_change().fillna(0.0)
        daily_rets_strategy[ticker] = (daily_ret * executed_position)
        daily_rets_bh[ticker] = daily_ret

    strat_df = pd.DataFrame(daily_rets_strategy).dropna(how="all")
    bh_df = pd.DataFrame(daily_rets_bh).reindex(strat_df.index)
    port_strategy_ret = strat_df.mean(axis=1)  # 동일가중 일별 리밸런싱 근사
    port_bh_ret = bh_df.mean(axis=1)

    def curve_from_returns(rets):
        eq = (1.0 + rets.fillna(0.0)).cumprod() * 100.0
        return eq

    port_strategy_eq = curve_from_returns(port_strategy_ret)
    port_bh_eq = curve_from_returns(port_bh_ret)

    bench_start = port_strategy_eq.index[0].date().isoformat()
    bench_end = port_strategy_eq.index[-1].date().isoformat()
    bench_run = run_buy_and_hold("^GSPC", bench_start, bench_end)

    no_trades = []
    port_strategy_metrics = calculate_metrics(port_strategy_eq, no_trades, port_strategy_eq.index[0], port_strategy_eq.index[-1])
    port_bh_metrics = calculate_metrics(port_bh_eq, no_trades, port_bh_eq.index[0], port_bh_eq.index[-1])

    print("portfolio strategy (equal-weight 50, daily rebal):", port_strategy_metrics)
    print("portfolio buy&hold (equal-weight 50):", port_bh_metrics)
    print("S&P500 buy&hold:", bench_run.metrics)

    import json
    with open(f"{OUT_DIR}/portfolio_level_result.json", "w", encoding="utf-8") as f:
        json.dump({
            "portfolio_strategy": port_strategy_metrics,
            "portfolio_bh": port_bh_metrics,
            "sp500_bh": bench_run.metrics,
            "final_method_params": {"zone_low": TUNED["zone_low"], "zone_high": TUNED["zone_high"],
                                     "vol_ratio_high": TUNED["vol_ratio_high"], "position_lookback": TUNED["position_lookback"],
                                     "up_th": BEST_UP, "down_th": BEST_DOWN, "sell_weight": best_sw},
        }, f, ensure_ascii=False, indent=2)

    # 자산곡선(연 1회 다운샘플)도 저장 -> 리포트 차트용
    port_strategy_w = port_strategy_eq.resample("W-FRI").last().dropna()
    port_bh_w = port_bh_eq.resample("W-FRI").last().dropna()
    bench_w = bench_run.equity_curve.reindex(port_strategy_eq.index).resample("W-FRI").last().dropna()
    common = port_strategy_w.index.intersection(port_bh_w.index).intersection(bench_w.index)
    with open(f"{OUT_DIR}/portfolio_equity_curves.json", "w", encoding="utf-8") as f:
        json.dump({
            "dates": [d.strftime("%Y-%m-%d") for d in common],
            "strategy": [round(float(v), 2) for v in port_strategy_w.loc[common]],
            "bh": [round(float(v), 2) for v in port_bh_w.loc[common]],
            "bench": [round(float(v), 2) for v in bench_w.loc[common]],
        }, f, ensure_ascii=False)

    print("DONE", flush=True)


if __name__ == "__main__":
    main()
