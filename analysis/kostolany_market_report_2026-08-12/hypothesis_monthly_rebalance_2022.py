"""2022년 방어자산 블렌드가 baseline보다 나빴던 이유로 "분기 단위 리스크패리티 재계산이 TLT의
급등한 실현변동성에 너무 느리게 반응했다"고 추정했다. 재조정 주기를 분기(QS)에서 월간(MS)으로
좁히면 2022년처럼 빠르게 변하는 상황에서 방어자산 블렌드가 baseline을 따라잡거나 이기는지 확인.
(세션12에서 이미 "재조정을 자주 할수록 항상 좋지는 않다"는 걸 다른 맥락에서 배웠으므로, 이번에도
2015~2026·2000~2012 두 시대 전체에서 부작용이 없는지 같이 검증한다.)"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import numpy as np
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from rolling_risk_parity import rolling_risk_parity_weights
from portfolio_vol_targeting import metrics_from_returns
from multi_regime_multi_strategy import SECTOR_ETFS_MODERN, WARMUP_DAYS, MOMENTUM_WINDOW, ALPHA_TILT, classify_regimes
from hypothesis_defensive_assets_bear import DEFENSIVE_ASSETS, regime_vol_scale

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"


def build_weights_freq(etf_df, defensive_df, rebal_freq):
    regime, leader, market_trend = classify_regimes(etf_df)
    rp_equity = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq=rebal_freq)

    combined_df = pd.concat([etf_df, defensive_df], axis=1).dropna(how="any", axis=0)
    rp_extended = rolling_risk_parity_weights(combined_df, lookback_days=252, rebal_freq=rebal_freq)
    rp_extended = rp_extended.reindex(etf_df.index).ffill().bfill()

    all_cols = list(etf_df.columns) + DEFENSIVE_ASSETS
    w = pd.DataFrame(0.0, index=etf_df.index, columns=all_cols)
    for dt in etf_df.index:
        r = regime.loc[dt]
        if r == "약세장" and dt in rp_extended.index:
            w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
        else:
            base = rp_equity.loc[dt].copy()
            if r == "쏠림강세":
                lead = leader.loc[dt]
                base[lead] = base[lead] + ALPHA_TILT
                base = base / base.sum()
            w.loc[dt, etf_df.columns] = base.values
    return w, regime


def eval_slice(etf_df, defensive_df, w, regime, idx):
    all_rets = pd.concat([etf_df, defensive_df], axis=1).fillna(0.0)
    executed = w.loc[idx].shift(1).fillna(0.0)
    ret = (all_rets.loc[idx] * executed).sum(axis=1)
    scale = regime_vol_scale(ret, regime.loc[idx])
    final_ret = ret * scale.shift(1).fillna(1.0)
    m, _ = metrics_from_returns(final_ret)
    return m


def main():
    fetch_start = (pd.Timestamp("2000-01-03") - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    end = "2026-08-12"

    etf_hist = get_multiple_price_history(SECTOR_ETFS_MODERN, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)

    def_hist = get_multiple_price_history(DEFENSIVE_ASSETS, start=fetch_start, end=end, interval="1d")
    def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
    defensive_df = pd.DataFrame(def_rets)

    out = {}
    for freq_label, freq in [("quarterly(기존)", "QS"), ("monthly(신가설)", "MS")]:
        print(f"\n--- 재조정 주기: {freq_label} ---", flush=True)
        w, regime = build_weights_freq(etf_df, defensive_df, freq)

        idx_2022 = etf_df.index[(etf_df.index >= pd.Timestamp("2022-01-01")) & (etf_df.index <= pd.Timestamp("2022-12-31"))]
        idx_2015 = etf_df.index[(etf_df.index >= pd.Timestamp("2015-01-01")) & (etf_df.index <= pd.Timestamp("2026-08-12"))]

        m_2022 = eval_slice(etf_df, defensive_df, w, regime, idx_2022)
        m_full = eval_slice(etf_df, defensive_df, w, regime, idx_2015)
        print(f"[2022년]: CAGR={m_2022['cagr']}, MDD={m_2022['mdd']}, 샤프={m_2022['sharpe']}", flush=True)
        print(f"[2015~2026 전체]: CAGR={m_full['cagr']}, MDD={m_full['mdd']}, 샤프={m_full['sharpe']}", flush=True)
        out[freq_label] = {"y2022": m_2022, "full_2015_2026": m_full}

    bench_2022 = run_buy_and_hold("^GSPC", "2022-01-01", "2022-12-31")
    bench_full = run_buy_and_hold("^GSPC", "2015-01-01", "2026-08-12")
    out["sp500_2022"] = bench_2022.metrics
    out["sp500_full"] = bench_full.metrics
    print("S&P500(2022):", bench_2022.metrics, flush=True)

    with open(f"{OUT_DIR}/hypothesis_monthly_rebalance_2022.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
