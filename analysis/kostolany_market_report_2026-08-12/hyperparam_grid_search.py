"""코스톨라니 국면 판정 임계값(하이퍼파라미터)을 스윕해, 기본값 대비 평균 샤프비율이 오르고
S&P500을 이기는 조합이 있는지 탐색한다.

core.kostolany_scenario_engine/core.backtest_engine의 기존 함수(compute_position_pct_series,
compute_volume_ratio_series, build_position_from_phases, compute_equity_curve, calculate_metrics,
extract_trades)를 그대로 재사용하고, classify_cycle_phase_series만 임계값을 인자로 받는 버전으로
복제한다(모듈 상수 대신 파라미터를 쓰는 것 외 분기 로직은 완전히 동일 — 기존 함수와 대조 검증은
tests/test_kostolany_scenario_engine.py가 이미 커버하므로 이 스크립트에서는 생략).

바이앤홀드/벤치마크 지표는 파라미터와 무관하므로(스크립트가 아니라 종목·기간에만 의존) 이미 계산해
둔 summary_장기.csv를 그대로 재사용해 중복 계산을 없앤다.
"""
import itertools
import sys
import time

sys.path.insert(0, "/workspaces/Quant")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, compute_equity_curve
from core.indicators import roc
from core.kostolany_scenario_engine import (
    build_position_from_phases,
    compute_position_pct_series,
    compute_volume_ratio_series,
)
from core.market_data import get_multiple_price_history, get_price_history
from core.strategy_engine import extract_trades

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
START = "2015-01-01"
END = None
STYLE = "장기"  # 본 리포트의 기본/문제가 된 스타일을 튜닝 대상으로 선택
WARMUP_DAYS = 400

BASELINE = dict(zone_low=30.0, zone_high=70.0, trend_window=20, steep_roc=15.0,
                vol_ratio_high=1.2, vol_short=20, vol_long=60, position_lookback=252)

# 가설: A3(고점권+상승+거래량 급증)이 "매도"로 잡혀 구조적 장기상승 종목을 너무 일찍 판다 ->
# zone_high를 올리고(진짜 극단만 고점권 취급) 거래량 임계값을 높이고 lookback을 늘리는 방향을 스윕.
GRID = {
    "zone_low": [30.0, 15.0, 5.0],
    "zone_high": [70.0, 85.0, 95.0],
    "vol_ratio_high": [1.2, 1.6],
    "position_lookback": [252, 504],
}


def classify_cycle_phase_series_param(
    close: pd.Series, volume: pd.Series, *,
    zone_low: float, zone_high: float, trend_window: int, steep_roc: float,
    vol_ratio_high: float, vol_short: int, vol_long: int, position_lookback: int,
) -> pd.Series:
    position_pct = compute_position_pct_series(close, lookback=position_lookback)
    roc_pct = roc(close, trend_window)
    volume_ratio = compute_volume_ratio_series(volume, short=vol_short, long=vol_long)

    trend_up = roc_pct > 0
    is_steep = roc_pct.abs() >= steep_roc
    volume_high = volume_ratio >= vol_ratio_high

    low = position_pct <= zone_low
    high = position_pct >= zone_high
    mid = ~low & ~high

    phase = pd.Series(np.nan, index=close.index, dtype=object)
    phase[low & trend_up & volume_high.fillna(False)] = "A2"
    phase[low & trend_up & ~volume_high.fillna(False)] = "A1"
    phase[low & ~trend_up & (volume_high.fillna(False) & is_steep)] = "B3"
    phase[low & ~trend_up & ~(volume_high.fillna(False) & is_steep)] = "A1"
    phase[high & trend_up & volume_high.fillna(False)] = "A3"
    phase[high & trend_up & ~volume_high.fillna(False)] = "A2"
    phase[high & ~trend_up & volume_high.fillna(False)] = "B2"
    phase[high & ~trend_up & ~volume_high.fillna(False)] = "B1"
    phase[mid & trend_up] = "A2"
    phase[mid & ~trend_up] = "B2"

    invalid = position_pct.isna() | roc_pct.isna()
    phase[invalid] = None
    return phase


def run_one(df: pd.DataFrame, params: dict, style: str, start: str, end):
    phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **params)
    position_full = build_position_from_phases(phase_full, style)
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


def main():
    baseline_df = pd.read_csv(f"{OUT_DIR}/summary_장기.csv").set_index("theme")

    sector_tickers = [t for t in baseline_df.index if t != "S&P500"]
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    print("fetching (cached) histories...", flush=True)
    histories = get_multiple_price_history(sector_tickers, start=fetch_start, end=END, interval="1d")
    histories["S&P500"] = get_price_history("^GSPC", start=fetch_start, end=END, interval="1d")

    combos = [dict(zip(GRID.keys(), vals)) for vals in itertools.product(*GRID.values())]
    print(f"{len(combos)} combos x {len(histories)} tickers", flush=True)

    rows = []
    t0 = time.time()
    for ci, combo in enumerate(combos):
        params = dict(trend_window=BASELINE["trend_window"], steep_roc=BASELINE["steep_roc"],
                      vol_short=BASELINE["vol_short"], vol_long=BASELINE["vol_long"])
        params.update(combo)
        per_ticker = []
        for ticker, df in histories.items():
            if df is None or df.empty:
                continue
            m = run_one(df, params, STYLE, START, END)
            if m is None:
                continue
            base = baseline_df.loc[ticker]
            excess_cagr = m["cagr"] - base["bh_cagr"]
            excess_vs_bench = m["cagr"] - base["bench_cagr"]
            per_ticker.append({
                "ticker": ticker, "cagr": m["cagr"], "mdd": m["mdd"], "sharpe": m["sharpe"],
                "excess_cagr": excess_cagr, "excess_vs_bench": excess_vs_bench,
                "beats_bh": m["cumulative_return"] > base["bh_cumulative_return"],
                "beats_bench": m["cumulative_return"] > base["bench_cumulative_return"],
            })
        pt = pd.DataFrame(per_ticker)
        sector_only = pt[pt["ticker"] != "S&P500"]
        idx_row = pt[pt["ticker"] == "S&P500"].iloc[0]
        rows.append({
            **combo,
            "mean_sharpe": round(sector_only["sharpe"].mean(), 3),
            "mean_cagr": round(sector_only["cagr"].mean(), 2),
            "mean_excess_cagr_vs_bench": round(sector_only["excess_vs_bench"].mean(), 2),
            "median_excess_cagr_vs_bench": round(sector_only["excess_vs_bench"].median(), 2),
            "win_rate_vs_bh_pct": round(100 * sector_only["beats_bh"].mean(), 1),
            "win_rate_vs_bench_pct": round(100 * sector_only["beats_bench"].mean(), 1),
            "index_cagr": idx_row["cagr"], "index_sharpe": idx_row["sharpe"], "index_mdd": idx_row["mdd"],
            "index_excess_vs_bench": round(idx_row["excess_vs_bench"], 2),
        })
        elapsed = time.time() - t0
        print(f"[{ci+1}/{len(combos)}] {combo} -> sharpe={rows[-1]['mean_sharpe']} "
              f"win_bench={rows[-1]['win_rate_vs_bench_pct']}% idx_excess={rows[-1]['index_excess_vs_bench']} "
              f"({elapsed:.0f}s elapsed)", flush=True)

    result = pd.DataFrame(rows).sort_values("mean_sharpe", ascending=False).reset_index(drop=True)
    result.to_csv(f"{OUT_DIR}/hyperparam_grid_results.csv", index=False, encoding="utf-8-sig")
    print("\n=== TOP 10 by mean_sharpe ===")
    print(result.head(10).to_string())
    print("\n=== BASELINE row (for comparison) ===")
    base_mask = (
        (result["zone_low"] == BASELINE["zone_low"]) & (result["zone_high"] == BASELINE["zone_high"]) &
        (result["vol_ratio_high"] == BASELINE["vol_ratio_high"]) &
        (result["position_lookback"] == BASELINE["position_lookback"])
    )
    print(result[base_mask].to_string())
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
