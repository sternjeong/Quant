"""②(약세장엔 TLT/GLD를 리스크패리티로 섞기)는 국면 경계에서 이진(binary)으로 전환된다 —
트레일링추세가 -4.9%면 순수 섹터ETF, -5.1%면 갑자기 방어자산 섞임. 실제로는 얕은 약세장과 깊은
약세장을 구분 못 한다. 이 가설: 방어자산 비중을 트레일링추세의 "약세 정도"에 비례해 연속적으로
조절(약세장 임계값 -5%에서 시작해 -15%에서 최대 100% 블렌드에 도달하는 선형 스케일 — 두 값 모두
사전에 정한 상식적 구간, 사후 스윕 아님)한다. 이진 스위치보다 나은지 확인."""
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
    SECTOR_ETFS_MODERN, SECTOR_ETFS_LEGACY, WARMUP_DAYS, MOMENTUM_WINDOW,
    ALPHA_TILT, BEAR_TREND_PCT, classify_regimes,
)

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
DEFENSIVE_ASSETS = ["TLT", "GLD"]
SEVERITY_FULL_AT = -15.0  # 이 트레일링추세(%)에서 방어자산 블렌드 100% 도달 (사전 정의)


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

    def_hist = get_multiple_price_history(DEFENSIVE_ASSETS, start=fetch_start, end=end, interval="1d")
    def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
    defensive_df = pd.DataFrame(def_rets)

    regime, leader, market_trend = classify_regimes(etf_df)
    rp_equity = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")

    combined_df = pd.concat([etf_df, defensive_df], axis=1).dropna(how="any", axis=0)
    rp_extended = rolling_risk_parity_weights(combined_df, lookback_days=252, rebal_freq="QS")
    rp_extended = rp_extended.reindex(etf_df.index).ffill().bfill()

    severity = ((BEAR_TREND_PCT - market_trend) / (BEAR_TREND_PCT - SEVERITY_FULL_AT)).clip(lower=0.0, upper=1.0)

    all_cols = list(etf_df.columns) + DEFENSIVE_ASSETS
    binary_w = pd.DataFrame(0.0, index=etf_df.index, columns=all_cols)
    scaled_w = pd.DataFrame(0.0, index=etf_df.index, columns=all_cols)

    for dt in etf_df.index:
        r = regime.loc[dt]
        base = rp_equity.loc[dt].copy()
        if r == "쏠림강세":
            lead = leader.loc[dt]
            base[lead] = base[lead] + ALPHA_TILT
            base = base / base.sum()

        # 이진(기존 ②): 약세장이면 확장유니버스 그대로, 아니면 섹터만
        if r == "약세장" and dt in rp_extended.index:
            binary_w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
        else:
            binary_w.loc[dt, etf_df.columns] = base.values

        # 연속(신가설): severity로 base(섹터만, 쏠림틸트 포함)와 rp_extended를 블렌드
        s = severity.loc[dt]
        if s > 0 and dt in rp_extended.index:
            ext_row = rp_extended.loc[dt].reindex(all_cols).fillna(0.0)
            base_row = base.reindex(all_cols).fillna(0.0)
            scaled_w.loc[dt] = (1 - s) * base_row.values + s * ext_row.values
        else:
            scaled_w.loc[dt, etf_df.columns] = base.values

    all_rets = pd.concat([etf_df, defensive_df], axis=1).fillna(0.0)

    out = {}
    for name, w in [("binary_switch(기존②)", binary_w), ("severity_scaled(신가설)", scaled_w)]:
        wsum = w.loc[sliced_idx].sum(axis=1)
        max_dev = (wsum - 1.0).abs().max()
        if max_dev > 1e-6:
            raise ValueError(f"{name} 비중 정규화 버그: 최대 이탈 {max_dev}")
        executed = w.loc[sliced_idx].shift(1).fillna(0.0)
        ret = (all_rets.loc[sliced_idx] * executed).sum(axis=1)
        scale = regime_vol_scale(ret, regime.loc[sliced_idx])
        final_ret = ret * scale.shift(1).fillna(1.0)
        m, _ = metrics_from_returns(final_ret)
        print(f"[{name}]: CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}, calmar={m['calmar']}", flush=True)
        out[name] = m

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    out["sp500_bh"] = bench.metrics
    return out


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2006_2012"] = run_period("약세장포함 부분구간", "2006-01-01", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_severity_scaled_defense.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
