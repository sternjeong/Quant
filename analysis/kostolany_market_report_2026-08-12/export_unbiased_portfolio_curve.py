import sys
sys.path.insert(0, "/workspaces/Quant")
import json
import pickle
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.position_sizing import portfolio_volatility_target_weights
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"

with open(f"{OUT_DIR}/unbiased_kostolany_portfolio_curves.pkl", "rb") as f:
    d = pickle.load(f)

port_strategy_ret_eq = d["port_strategy_ret_eq"]
bench_eq = d["bench_eq"]

# 최선안: risk-parity 가중 + vol-target(15, cap=1.0) — 원본 종목별 daily_rets가 필요하므로 재계산
# (risk-parity 시리즈를 pkl에 저장 안 해뒀어서 여기서 다시 로드)
import pickle as pkl
with open(f"{OUT_DIR}/momentum_rotation_unbiased_curves.pkl", "rb") as f:
    unbiased_meta = pkl.load(f)
ok_tickers = unbiased_meta["ok_tickers"]

from core.market_data import get_multiple_price_history
from hyperparam_grid_search import classify_cycle_phase_series_param
from trend_gate_search import STYLE, START, END, WARMUP_DAYS, TUNED, build_position_trend_gated

fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
histories = get_multiple_price_history(ok_tickers, start=fetch_start, end=END, interval="1d")

daily_rets_strategy = {}
for ticker, df in histories.items():
    if df is None or df.empty or len(df) < WARMUP_DAYS:
        continue
    phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **TUNED)
    position_full = build_position_trend_gated(phase_full, df["Close"], STYLE, 15.0, -25.0, 0.5)
    sliced = df[df.index >= pd.Timestamp(START)]
    position = position_full.reindex(sliced.index).fillna(0.0)
    executed_position = position.shift(1).fillna(0.0)
    daily_ret = sliced["Close"].pct_change().fillna(0.0)
    daily_rets_strategy[ticker] = daily_ret * executed_position

strat_df = pd.DataFrame(daily_rets_strategy)
rp_weights = portfolio_volatility_target_weights(strat_df.dropna(how="all", axis=0))
w = pd.Series(rp_weights)
port_rp_ret = (strat_df[w.index] * w).sum(axis=1)

scale = vol_target_scale(port_rp_ret, 15.0, 1.0)
scaled = port_rp_ret * scale.shift(1).fillna(1.0)
m_final, eq_final = metrics_from_returns(scaled)
print("최종안(리스크패리티+vol15):", m_final)

bench_run_metrics = run_buy_and_hold("^GSPC", eq_final.index[0].date().isoformat(), eq_final.index[-1].date().isoformat())
print("S&P500:", bench_run_metrics.metrics)

eq_w = eq_final.resample("W-FRI").last().dropna()
bench_w = bench_run_metrics.equity_curve.reindex(eq_final.index).resample("W-FRI").last().dropna()
common = eq_w.index.intersection(bench_w.index)

with open(f"{OUT_DIR}/unbiased_portfolio_final_curve.json", "w", encoding="utf-8") as f:
    json.dump({
        "dates": [dt.strftime("%Y-%m-%d") for dt in common],
        "strategy": [round(float(v), 2) for v in eq_w.loc[common]],
        "bh": [round(float(v), 2) for v in eq_w.loc[common]],
        "bench": [round(float(v), 2) for v in bench_w.loc[common]],
    }, f, ensure_ascii=False)

with open(f"{OUT_DIR}/unbiased_portfolio_final_result.json", "w", encoding="utf-8") as f:
    json.dump({"final": m_final, "sp500_bh": bench_run_metrics.metrics}, f, ensure_ascii=False, indent=2)

print("saved")
