"""②(약세장에 TLT/GLD를 리스크패리티로 "섞는" 방식)와는 다른 구조: Antonacci류 듀얼모멘텀처럼
자산군 단위에서 아예 "스위치"한다 — SPY 자체의 트레일링 12개월 절대모멘텀이 플러스면 평소처럼
섹터 로테이션 시스템 100%, 마이너스면 그날그날 TLT/GLD 중 모멘텀이 더 센(둘 다 마이너스면 현금)
쪽으로 100% 전환. 블렌드(리스크패리티로 섞기)보다 하드 스위치가 더 나은지 비교."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import numpy as np
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from rolling_risk_parity import rolling_risk_parity_weights
from portfolio_vol_targeting import metrics_from_returns
from multi_regime_multi_strategy import (
    SECTOR_ETFS_MODERN, SECTOR_ETFS_LEGACY, WARMUP_DAYS, MOMENTUM_WINDOW, ALPHA_TILT, classify_regimes,
)

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
DEFENSIVE_ASSETS = ["TLT", "GLD"]


def regime_vol_scale(port_ret, regime):
    vol_target_by_regime = regime.map({"약세장": 12.0, "횡보장": 18.0, "광범위강세": 18.0, "쏠림강세": 18.0}).fillna(18.0)
    realized_vol = port_ret.rolling(5, min_periods=5).std() * np.sqrt(252) * 100
    tv = vol_target_by_regime.reindex(port_ret.index)
    scale = (tv / realized_vol).clip(upper=1.0).fillna(1.0)
    return scale


def run_period(label, start, end, sector_etfs):
    print(f"\n{'='*20} {label} {'='*20}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()

    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(start)) & (etf_df.index <= pd.Timestamp(end))]

    def_hist = get_multiple_price_history(DEFENSIVE_ASSETS + ["SPY"], start=fetch_start, end=end, interval="1d")
    def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
    defensive_df = pd.DataFrame(def_rets).reindex(etf_df.index)

    spy_mom = (1 + defensive_df["SPY"]).rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: x.prod() - 1, raw=True)
    tlt_mom = (1 + defensive_df["TLT"]).rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: x.prod() - 1, raw=True)
    gld_mom = (1 + defensive_df["GLD"]).rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: x.prod() - 1, raw=True)
    is_risk_off = spy_mom <= 0
    best_defensive = pd.concat({"TLT": tlt_mom, "GLD": gld_mom}, axis=1).idxmax(axis=1)
    defensive_positive = pd.concat({"TLT": tlt_mom, "GLD": gld_mom}, axis=1).max(axis=1) > 0

    regime, leader, market_trend = classify_regimes(etf_df)
    rp_weights = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")
    risk_on_w = rp_weights.copy()
    for dt in etf_df.index:
        if regime.loc[dt] == "쏠림강세":
            w = rp_weights.loc[dt].copy()
            w[leader.loc[dt]] = w[leader.loc[dt]] + ALPHA_TILT
            risk_on_w.loc[dt] = w / w.sum()

    all_assets = list(etf_df.columns) + DEFENSIVE_ASSETS
    switch_w = pd.DataFrame(0.0, index=etf_df.index, columns=all_assets)
    for dt in etf_df.index:
        if is_risk_off.loc[dt]:
            if defensive_positive.loc[dt]:
                switch_w.loc[dt, best_defensive.loc[dt]] = 1.0
            # 둘 다 마이너스면 전량 현금(비중 0, 그대로 둠)
        else:
            switch_w.loc[dt, etf_df.columns] = risk_on_w.loc[dt].values

    switch_pct = round(100 * is_risk_off.loc[sliced_idx].mean(), 1)
    print(f"리스크오프(SPY 12개월모멘텀<=0) 비율: {switch_pct}%", flush=True)

    all_rets = pd.concat([etf_df, defensive_df[DEFENSIVE_ASSETS]], axis=1).fillna(0.0)

    # baseline(확정 시스템, 섹터ETF만, 약세장도 섹터ETF 안에서)
    base_ret = (etf_df.loc[sliced_idx] * risk_on_w.loc[sliced_idx].shift(1).fillna(1.0 / risk_on_w.shape[1])).sum(axis=1)
    base_scale = regime_vol_scale(base_ret, regime.loc[sliced_idx])
    m_base, _ = metrics_from_returns(base_ret * base_scale.shift(1).fillna(1.0))
    print("[baseline: 확정 시스템]:", m_base, flush=True)

    switch_executed = switch_w.loc[sliced_idx].shift(1).fillna(0.0)
    switch_ret = (all_rets.loc[sliced_idx] * switch_executed).sum(axis=1)
    switch_scale = regime_vol_scale(switch_ret, regime.loc[sliced_idx])
    m_switch, _ = metrics_from_returns(switch_ret * switch_scale.shift(1).fillna(1.0))
    print("[듀얼모멘텀 하드스위치]:", m_switch, flush=True)

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)

    return {"switch_pct": switch_pct, "baseline": m_base, "dual_momentum_switch": m_switch, "sp500_bh": bench.metrics}


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2006_2012"] = run_period("약세장포함 부분구간", "2006-01-01", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_dual_momentum_switch.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
