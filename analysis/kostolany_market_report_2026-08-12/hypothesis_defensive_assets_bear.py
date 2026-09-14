"""사용자 지적: 약세장 전략은 단순히 "같은 섹터 ETF들 안에서 변동성타게팅만 타이트하게" 하는 게
아니라, 진짜 다른 자산(채권·금)으로 갈아탈 수 있어야 진짜 "다른 전략"이다. 확정 시스템은 약세장에도
계속 섹터 ETF(=주식) 안에만 머문다 — 2008년처럼 주식이 전부 같이 무너지는 상황에선 무력하다.

이 가설: 약세장(트레일링 12개월 수익률 < -5%) 국면에서만 리스크패리티 유니버스에 TLT(장기국채)와
GLD(금)를 추가한다(그 외 국면은 기존처럼 섹터ETF만). 리스크패리티(inverse-vol)가 자동으로 그
시점에 변동성이 낮고 방어력이 있는 자산에 비중을 더 싣게 된다 — 어떤 자산이 좋을지 사후에 고르는
게 아니라 리스크패리티 메커니즘 자체에 맡긴다.

데이터 제약: GLD는 2004-11-18부터, TLT는 2002-07-30부터 존재 — 2000~2012 구간은 전체가 아니라
2006~2012(모멘텀 워밍업 포함 안전마진)로 축소해서 확정 시스템과 공정 비교."""
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


def build_weights(etf_df, defensive_df):
    regime, leader, market_trend = classify_regimes(etf_df)

    rp_equity = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")

    combined_df = pd.concat([etf_df, defensive_df], axis=1).dropna(how="any", axis=0)
    rp_extended = rolling_risk_parity_weights(combined_df, lookback_days=252, rebal_freq="QS")
    rp_extended = rp_extended.reindex(etf_df.index).fillna(method="ffill").fillna(method="bfill")

    all_cols = list(etf_df.columns) + list(defensive_df.columns)
    final_w = pd.DataFrame(0.0, index=etf_df.index, columns=all_cols)

    for dt in etf_df.index:
        r = regime.loc[dt]
        if r == "약세장" and dt in rp_extended.index:
            final_w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
        else:
            w = rp_equity.loc[dt].copy()
            if r == "쏠림강세":
                lead = leader.loc[dt]
                w[lead] = w[lead] + ALPHA_TILT
                w = w / w.sum()
            final_w.loc[dt, etf_df.columns] = w.values
    return final_w, regime


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

    def_hist = get_multiple_price_history(DEFENSIVE_ASSETS, start=fetch_start, end=end, interval="1d")
    def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
    defensive_df = pd.DataFrame(def_rets)

    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(start)) & (etf_df.index <= pd.Timestamp(end))]

    # baseline: 확정 시스템(섹터ETF만, 약세장도 섹터ETF 안에서 방어)
    regime_only, leader_only, _ = classify_regimes(etf_df)
    rp_base = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")
    base_w = rp_base.copy()
    for dt in etf_df.index:
        if regime_only.loc[dt] == "쏠림강세":
            w = rp_base.loc[dt].copy()
            w[leader_only.loc[dt]] = w[leader_only.loc[dt]] + ALPHA_TILT
            base_w.loc[dt] = w / w.sum()
    base_ret = (etf_df.loc[sliced_idx] * base_w.loc[sliced_idx].shift(1).fillna(1.0 / base_w.shape[1])).sum(axis=1)
    base_scale = regime_vol_scale(base_ret, regime_only.loc[sliced_idx])
    base_final = base_ret * base_scale.shift(1).fillna(1.0)
    m_base, _ = metrics_from_returns(base_final)
    print("[baseline: 확정 시스템(섹터ETF만)]:", m_base, flush=True)

    # 신가설: 약세장 국면엔 TLT/GLD 포함
    ext_w, regime = build_weights(etf_df, defensive_df)
    all_rets = pd.concat([etf_df, defensive_df], axis=1).fillna(0.0)
    ext_executed = ext_w.loc[sliced_idx].shift(1).fillna(0.0)
    ext_ret = (all_rets.loc[sliced_idx] * ext_executed).sum(axis=1)
    ext_scale = regime_vol_scale(ext_ret, regime.loc[sliced_idx])
    ext_final = ext_ret * ext_scale.shift(1).fillna(1.0)
    m_ext, _ = metrics_from_returns(ext_final)
    print("[신가설: 약세장에 TLT/GLD 포함]:", m_ext, flush=True)

    bear_days = int((regime.loc[sliced_idx] == "약세장").sum())
    print(f"약세장 거래일수: {bear_days}", flush=True)

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)

    return {"baseline": m_base, "defensive_ext": m_ext, "bear_days": bear_days, "sp500_bh": bench.metrics}


def main():
    out = {}
    out["2015_2026"] = run_period("강세장(TLT/GLD 전기간 존재)", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2006_2012"] = run_period("약세장포함 부분구간(GLD 존재기간)", "2006-01-01", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_defensive_assets_bear.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
