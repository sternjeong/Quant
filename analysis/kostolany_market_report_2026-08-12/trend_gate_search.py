"""추세 필터(trend-gate) 하이브리드 전략 탐색.

가설(본 리포트 09장 결론): 코스톨라니 국면 매매의 실패는 "구조적으로 계속 우상향하는 종목"을 A3
국면에서 조기에 파는 데서 온다. 그렇다면 "장기(252일) 추세가 이미 강하게 위/아래로 확정된 구간에서는
국면 신호를 무시하고 추세를 그냥 따라가고(강한 상승->매도신호 무시, 강한 하락->매수신호 무시),
추세가 뚜렷하지 않은 구간(진짜 '박스권/순환' 구간)에서만 코스톨라니 국면을 그대로 따른다"는 필터를
결합하면 더 나아지는가?

core.kostolany_scenario_engine/core.backtest_engine의 기존 함수(compute_position_pct_series,
compute_volume_ratio_series, calculate_metrics, compute_equity_curve)를 그대로 재사용하고,
classify_cycle_phase_series_param(hyperparam_grid_search.py에서 이미 검증된 파라미터화 버전)도
그대로 가져다 쓴다. 새로 추가하는 부분은 "status(buy/hold/sell)에 장기추세 게이트를 씌우는 로직"뿐이다.
"""
import itertools
import sys
import time

sys.path.insert(0, "/workspaces/Quant")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, compute_equity_curve
from core.indicators import roc
from core.kostolany_cycle import STYLE_PHASE_STATUS
from core.market_data import get_multiple_price_history, get_price_history
from core.strategy_engine import extract_trades
from hyperparam_grid_search import BASELINE, classify_cycle_phase_series_param

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
START = "2015-01-01"
END = None
STYLE = "장기"
WARMUP_DAYS = 400
TREND_GATE_WINDOW = 252  # 국면 판정용 20일 ROC와는 별개 — "구조적 추세" 여부를 보는 장기 지표

TUNED = dict(zone_low=30.0, zone_high=95.0, vol_ratio_high=1.6,
             position_lookback=252, trend_window=BASELINE["trend_window"],
             steep_roc=BASELINE["steep_roc"], vol_short=BASELINE["vol_short"], vol_long=BASELINE["vol_long"])


def build_position_trend_gated(
    phase: pd.Series, close: pd.Series, style: str,
    up_th: float | None, down_th: float | None, sell_weight: float = 0.0,
    gate_window: int = TREND_GATE_WINDOW,
) -> pd.Series:
    """국면->buy/hold/sell 매핑에 장기추세 게이트를 씌운다.

    up_th가 아니면(None) 상승 게이트 없음. 아니면 ROC(gate_window) > up_th인 구간에서는 "매도" 신호를
    무시(직전 포지션 유지 = hold 취급)한다. down_th도 대칭으로 "매수" 신호를 무시한다.
    sell_weight>0이면 "매도"를 완전 청산(0) 대신 그 비중만 남기고 축소한다(부분 비중조절).
    """
    status_map = STYLE_PHASE_STATUS[style]
    status = phase.map(lambda p: status_map.get(p) if p else None)

    long_roc = roc(close, gate_window)
    if up_th is not None:
        strong_up = (long_roc > up_th).fillna(False)
        status = status.mask(strong_up & (status == "sell"), "hold")
    if down_th is not None:
        strong_down = (long_roc < down_th).fillna(False)
        status = status.mask(strong_down & (status == "buy"), "hold")

    sell_value = sell_weight
    signal = status.map({"buy": 1.0, "sell": sell_value})
    return signal.ffill().fillna(0.0)


def run_one(df, params, style, start, end, up_th, down_th, sell_weight=0.0):
    phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **params)
    position_full = build_position_trend_gated(phase_full, df["Close"], style, up_th, down_th, sell_weight)
    sliced = df.copy()
    if start:
        sliced = sliced[sliced.index >= pd.Timestamp(start)]
    if end:
        sliced = sliced[sliced.index <= pd.Timestamp(end)]
    if sliced.empty:
        return None
    position = position_full.loc[sliced.index]
    equity_curve = compute_equity_curve(sliced, position)
    trades = extract_trades(sliced, position)
    metrics = calculate_metrics(equity_curve, trades, sliced.index[0], sliced.index[-1])
    return metrics


def eval_combo(histories, baseline_df, params, up_th, down_th, sell_weight=0.0):
    rows = []
    for ticker, df in histories.items():
        if df is None or df.empty:
            continue
        m = run_one(df, params, STYLE, START, END, up_th, down_th, sell_weight)
        if m is None:
            continue
        base = baseline_df.loc[ticker]
        rows.append({
            "ticker": ticker, "sector": base["sector"], "cagr": m["cagr"], "mdd": m["mdd"], "sharpe": m["sharpe"],
            "excess_cagr": m["cagr"] - base["bh_cagr"], "excess_vs_bench": m["cagr"] - base["bench_cagr"],
            "beats_bh": m["cumulative_return"] > base["bh_cumulative_return"],
            "beats_bench": m["cumulative_return"] > base["bench_cumulative_return"],
        })
    pt = pd.DataFrame(rows)
    sector_only = pt[pt["ticker"] != "S&P500"]
    idx_row = pt[pt["ticker"] == "S&P500"].iloc[0]
    return {
        "mean_sharpe": round(sector_only["sharpe"].mean(), 3),
        "mean_cagr": round(sector_only["cagr"].mean(), 2),
        "mean_excess_cagr_vs_bench": round(sector_only["excess_vs_bench"].mean(), 2),
        "median_excess_cagr_vs_bench": round(sector_only["excess_vs_bench"].median(), 2),
        "win_rate_vs_bh_pct": round(100 * sector_only["beats_bh"].mean(), 1),
        "win_rate_vs_bench_pct": round(100 * sector_only["beats_bench"].mean(), 1),
        "index_cagr": idx_row["cagr"], "index_sharpe": idx_row["sharpe"], "index_mdd": idx_row["mdd"],
        "index_excess_vs_bench": round(idx_row["excess_vs_bench"], 2),
    }, pt


def main():
    baseline_df = pd.read_csv(f"{OUT_DIR}/summary_장기.csv").set_index("theme")
    sector_tickers = [t for t in baseline_df.index if t != "S&P500"]
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(sector_tickers, start=fetch_start, end=END, interval="1d")
    histories["S&P500"] = get_price_history("^GSPC", start=fetch_start, end=END, interval="1d")

    # --- STEP 1: 추세게이트 단독 (기본 zone/volume 파라미터 위에서) ---
    up_options = [None, 15.0, 25.0, 35.0, 50.0]
    down_options = [None, -15.0, -25.0, -35.0]
    combos = list(itertools.product(up_options, down_options))
    print(f"STEP1: {len(combos)} trend-gate combos on BASELINE params", flush=True)
    step1_rows = []
    t0 = time.time()
    for i, (up_th, down_th) in enumerate(combos):
        summary, _ = eval_combo(histories, baseline_df, BASELINE, up_th, down_th)
        step1_rows.append({"up_th": up_th, "down_th": down_th, **summary})
        print(f"[{i+1}/{len(combos)}] up={up_th} down={down_th} -> sharpe={summary['mean_sharpe']} "
              f"win_bench={summary['win_rate_vs_bench_pct']}% idx_excess={summary['index_excess_vs_bench']} "
              f"({time.time()-t0:.0f}s)", flush=True)
    step1_df = pd.DataFrame(step1_rows).sort_values("mean_sharpe", ascending=False).reset_index(drop=True)
    step1_df.to_csv(f"{OUT_DIR}/trend_gate_step1_baseline_params.csv", index=False, encoding="utf-8-sig")
    print("\n=== STEP1 TOP 8 (baseline zone/vol params + trend gate) ===")
    print(step1_df.head(8).to_string())

    best1 = step1_df.iloc[0]
    best_up = None if pd.isna(best1["up_th"]) else float(best1["up_th"])
    best_down = None if pd.isna(best1["down_th"]) else float(best1["down_th"])

    # --- STEP 2: 같은 추세게이트를 TUNED(고점권 95%/거래량 1.6배) 파라미터 위에도 적용 (결합 효과) ---
    print(f"\nSTEP2: best trend-gate (up={best_up}, down={best_down}) on TUNED params", flush=True)
    combined_summary, combined_pt = eval_combo(histories, baseline_df, TUNED, best_up, best_down)
    print("combined (tuned params + trend gate):", combined_summary)
    combined_pt.to_csv(f"{OUT_DIR}/trend_gate_step2_combined_per_ticker.csv", index=False, encoding="utf-8-sig")

    # 비교용: TUNED 단독(게이트 없음), 게이트만(BASELINE 파라미터) 도 함께 저장
    tuned_only_summary, _ = eval_combo(histories, baseline_df, TUNED, None, None)
    gate_only_summary, _ = eval_combo(histories, baseline_df, BASELINE, best_up, best_down)

    with open(f"{OUT_DIR}/trend_gate_step2_summary.json", "w", encoding="utf-8") as f:
        import json
        json.dump({
            "best_up_th": best_up, "best_down_th": best_down,
            "tuned_only": tuned_only_summary,
            "gate_only": gate_only_summary,
            "combined": combined_summary,
        }, f, ensure_ascii=False, indent=2)

    print("\ntuned_only:", tuned_only_summary)
    print("gate_only:", gate_only_summary)
    print("combined:", combined_summary)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
