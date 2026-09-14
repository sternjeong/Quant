"""최종 '권장' 방법(sell_weight=0.5 — 이론의 전술적 성격을 과도하게 희석하지 않는 선)으로
종목별 결과 + 포트폴리오 레벨 결과 + 자산곡선을 다시 계산해 저장한다.

sell_weight를 1.0에 가깝게 올릴수록 계속 좋아지는 단조 추세가 나왔는데, 그 극한(1.0)은 "매도
신호를 사실상 무시하고 최초 매수 이후 영구 보유"가 되어 코스톨라니 이론의 국면 매매라는 정체성을
잃는다 — 그래서 0.75(그리드서치 상 최댓값)가 아니라 0.5(절반만 비중 축소)를 "권장 최종안"으로
채택하고, 0.75는 참고용 상한선으로만 리포트에 남긴다.
"""
import json
import pickle
import sys

sys.path.insert(0, "/workspaces/Quant")
import pandas as pd

from core.backtest_engine import calculate_metrics, run_buy_and_hold, compute_equity_curve
from core.market_data import get_multiple_price_history, get_price_history
from hyperparam_grid_search import classify_cycle_phase_series_param
from trend_gate_search import STYLE, START, END, WARMUP_DAYS, TUNED, build_position_trend_gated, eval_combo

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
BEST_UP, BEST_DOWN = 15.0, -25.0
FINAL_SELL_WEIGHT = 0.5


def main():
    baseline_df = pd.read_csv(f"{OUT_DIR}/summary_장기.csv").set_index("theme")
    sector_tickers = [t for t in baseline_df.index if t != "S&P500"]
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(sector_tickers, start=fetch_start, end=END, interval="1d")
    histories["S&P500"] = get_price_history("^GSPC", start=fetch_start, end=END, interval="1d")

    summary, pt = eval_combo(histories, baseline_df, TUNED, BEST_UP, BEST_DOWN, sell_weight=FINAL_SELL_WEIGHT)
    print("FINAL RECOMMENDED (sell_weight=0.5):", summary)
    pt.to_csv(f"{OUT_DIR}/final_recommended_per_ticker.csv", index=False, encoding="utf-8-sig")

    # 대표 종목 자산곡선(주간 리샘플)
    def curve_for(ticker):
        df = histories[ticker]
        phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **TUNED)
        position_full = build_position_trend_gated(phase_full, df["Close"], STYLE, BEST_UP, BEST_DOWN, FINAL_SELL_WEIGHT)
        sliced = df[df.index >= pd.Timestamp(START)]
        position = position_full.loc[sliced.index]
        return compute_equity_curve(sliced, position)

    with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
        R = json.load(f)
    sel = R["selected_labels"]

    equity_final = {}
    for key, ticker in sel.items():
        eq = curve_for(ticker)
        eq_w = eq.resample("W-FRI").last().dropna()
        equity_final[ticker] = {
            "dates": [d.strftime("%Y-%m-%d") for d in eq_w.index],
            "final": [round(float(v), 2) for v in eq_w],
        }
    with open(f"{OUT_DIR}/equity_curves_final_recommended.json", "w", encoding="utf-8") as f:
        json.dump(equity_final, f, ensure_ascii=False)

    # 포트폴리오 레벨(동일가중 50종목, sell_weight=0.5)
    daily_rets_strategy = {}
    daily_rets_bh = {}
    for ticker in sector_tickers:
        df = histories[ticker]
        phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **TUNED)
        position_full = build_position_trend_gated(phase_full, df["Close"], STYLE, BEST_UP, BEST_DOWN, FINAL_SELL_WEIGHT)
        sliced = df[df.index >= pd.Timestamp(START)]
        position = position_full.loc[sliced.index]
        executed_position = position.shift(1).fillna(0.0)
        daily_ret = sliced["Close"].pct_change().fillna(0.0)
        daily_rets_strategy[ticker] = daily_ret * executed_position
        daily_rets_bh[ticker] = daily_ret

    strat_df = pd.DataFrame(daily_rets_strategy).dropna(how="all")
    bh_df = pd.DataFrame(daily_rets_bh).reindex(strat_df.index)
    port_strategy_ret = strat_df.mean(axis=1)
    port_bh_ret = bh_df.mean(axis=1)

    def curve_from_returns(rets):
        return (1.0 + rets.fillna(0.0)).cumprod() * 100.0

    port_strategy_eq = curve_from_returns(port_strategy_ret)
    port_bh_eq = curve_from_returns(port_bh_ret)
    bench_run = run_buy_and_hold("^GSPC", port_strategy_eq.index[0].date().isoformat(), port_strategy_eq.index[-1].date().isoformat())

    no_trades = []
    port_strategy_metrics = calculate_metrics(port_strategy_eq, no_trades, port_strategy_eq.index[0], port_strategy_eq.index[-1])
    port_bh_metrics = calculate_metrics(port_bh_eq, no_trades, port_bh_eq.index[0], port_bh_eq.index[-1])
    print("portfolio strategy (0.5):", port_strategy_metrics)
    print("portfolio bh:", port_bh_metrics)
    print("sp500 bh:", bench_run.metrics)

    with open(f"{OUT_DIR}/portfolio_level_result_final.json", "w", encoding="utf-8") as f:
        json.dump({
            "portfolio_strategy": port_strategy_metrics,
            "portfolio_bh": port_bh_metrics,
            "sp500_bh": bench_run.metrics,
        }, f, ensure_ascii=False, indent=2)

    port_strategy_w = port_strategy_eq.resample("W-FRI").last().dropna()
    port_bh_w = port_bh_eq.resample("W-FRI").last().dropna()
    bench_w = bench_run.equity_curve.reindex(port_strategy_eq.index).resample("W-FRI").last().dropna()
    common = port_strategy_w.index.intersection(port_bh_w.index).intersection(bench_w.index)
    with open(f"{OUT_DIR}/portfolio_equity_curves_final.json", "w", encoding="utf-8") as f:
        json.dump({
            "dates": [d.strftime("%Y-%m-%d") for d in common],
            "strategy": [round(float(v), 2) for v in port_strategy_w.loc[common]],
            "bh": [round(float(v), 2) for v in port_bh_w.loc[common]],
            "bench": [round(float(v), 2) for v in bench_w.loc[common]],
        }, f, ensure_ascii=False)

    print("DONE")


if __name__ == "__main__":
    main()
