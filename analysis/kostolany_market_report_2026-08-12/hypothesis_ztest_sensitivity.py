"""가설: z≥1이라는 쏠림 판정 임계값이 "사후에 스윕해서 고른 값"이 아니라 진짜 원칙적인 기준이라면,
그 근방(z=0.5~2.0)에서도 결론(ETF 틸트가 baseline을 이긴다)이 비슷하게 유지돼야 한다. 이건 "더
좋은 값을 찾는" 스윕이 아니라 "선택한 값이 우연이 아닌지 확인하는" 민감도 분석이다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import numpy as np
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from rolling_risk_parity import rolling_risk_parity_weights
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns
from multi_regime_multi_strategy import (
    SECTOR_ETFS_MODERN, SECTOR_ETFS_LEGACY, WARMUP_DAYS, MOMENTUM_WINDOW,
    BULL_TREND_PCT, BEAR_TREND_PCT, ALPHA_TILT,
)

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"


def classify_and_run(etf_df, sliced_idx, z_threshold):
    trailing_mom = etf_df.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: (1 + x).prod() - 1, raw=True)
    market_trend = trailing_mom.mean(axis=1) * 100
    cross_mean = trailing_mom.mean(axis=1)
    cross_std = trailing_mom.std(axis=1)
    z_scores = trailing_mom.sub(cross_mean, axis=0).div(cross_std.replace(0, np.nan), axis=0)
    max_z = z_scores.max(axis=1)
    leader = z_scores.idxmax(axis=1)

    is_narrow_bull = (market_trend > BULL_TREND_PCT) & (max_z >= z_threshold)

    rp_weights = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")
    tilted = rp_weights.copy()
    for dt in etf_df.index:
        if is_narrow_bull.loc[dt]:
            w = rp_weights.loc[dt].copy()
            lead = leader.loc[dt]
            w[lead] = w[lead] + ALPHA_TILT
            tilted.loc[dt] = w / w.sum()

    def compute_ret(w_full):
        w = w_full.loc[sliced_idx]
        executed = w.shift(1).fillna(1.0 / w.shape[1])
        return (etf_df.loc[sliced_idx] * executed).sum(axis=1)

    tilt_ret = compute_ret(tilted)
    scale = vol_target_scale(tilt_ret, 18.0, 1.0, window=5)
    scaled = tilt_ret * scale.shift(1).fillna(1.0)
    m, _ = metrics_from_returns(scaled)
    narrow_pct = round(100 * is_narrow_bull.loc[sliced_idx].mean(), 1)
    return m, narrow_pct


def run_period(label, start, end, sector_etfs):
    print(f"\n{'='*15} {label} {'='*15}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(start)) & (etf_df.index <= pd.Timestamp(end))]

    results = []
    for z in [0.5, 0.75, 1.0, 1.5, 2.0]:
        m, narrow_pct = classify_and_run(etf_df, sliced_idx, z)
        print(f"z>={z}: 쏠림비율={narrow_pct}%, CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}", flush=True)
        results.append({"z_threshold": z, "narrow_bull_pct": narrow_pct, **m})

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    return {"sweep": results, "sp500_bh": bench.metrics}


def main():
    out = {}
    out["2015_2026"] = run_period("강세장 2015-2026", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2000_2012"] = run_period("약세장포함 2000-2012", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_ztest_sensitivity.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
