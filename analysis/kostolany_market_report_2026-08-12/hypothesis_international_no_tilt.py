"""세션14에서 국가ETF 유니버스는 쏠림강세가 51.6%로 미국 섹터(20~30%대)보다 훨씬 잦았다 — 국가간
모멘텀 로테이션에 틸트를 거는 게 오히려 해가 됐을 가능성을 의심했지만 확인하지 않았다. 이 가설:
쏠림틸트를 뺀 "순수" 리스크패리티+국면별변동성타게팅+약세장방어블렌드만으로 국가ETF 유니버스를
다시 테스트해, 국제화 실패의 원인이 (a)리스크패리티 엔진 자체인지 (b)쏠림틸트인지 분해한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import numpy as np
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from rolling_risk_parity import rolling_risk_parity_weights
from portfolio_vol_targeting import metrics_from_returns
from multi_regime_multi_strategy import WARMUP_DAYS, MOMENTUM_WINDOW, ALPHA_TILT, classify_regimes
from hypothesis_international_generalization import COUNTRY_ETFS, DEFENSIVE_ASSETS, FULL_START, FULL_END, ERA_SPLIT, regime_vol_scale

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"


def main():
    fetch_start = (pd.Timestamp(FULL_START) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()

    country_hist = get_multiple_price_history(COUNTRY_ETFS, start=fetch_start, end=FULL_END, interval="1d")
    country_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in country_hist.items() if df is not None and not df.empty}
    country_df = pd.DataFrame(country_rets).dropna(how="all", axis=0)

    def_hist = get_multiple_price_history(DEFENSIVE_ASSETS, start=fetch_start, end=FULL_END, interval="1d")
    def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
    defensive_df = pd.DataFrame(def_rets)

    full_idx = country_df.index[(country_df.index >= pd.Timestamp(FULL_START)) & (country_df.index <= pd.Timestamp(FULL_END))]

    regime, leader, market_trend = classify_regimes(country_df)
    rp_equity = rolling_risk_parity_weights(country_df, lookback_days=252, rebal_freq="QS")

    combined_df = pd.concat([country_df, defensive_df], axis=1).dropna(how="any", axis=0)
    rp_extended = rolling_risk_parity_weights(combined_df, lookback_days=252, rebal_freq="QS")
    rp_extended = rp_extended.reindex(country_df.index).ffill().bfill()

    all_cols = list(country_df.columns) + DEFENSIVE_ASSETS

    # 변형1: 틸트 포함(세션14와 동일, 비교용 재계산)
    with_tilt_w = pd.DataFrame(0.0, index=country_df.index, columns=all_cols)
    # 변형2: 틸트 없음(순수 리스크패리티 + 약세장 방어블렌드만)
    no_tilt_w = pd.DataFrame(0.0, index=country_df.index, columns=all_cols)

    for dt in country_df.index:
        r = regime.loc[dt]
        if r == "약세장" and dt in rp_extended.index:
            with_tilt_w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
            no_tilt_w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
        else:
            base = rp_equity.loc[dt].copy()
            no_tilt_w.loc[dt, country_df.columns] = base.values
            if r == "쏠림강세":
                lead = leader.loc[dt]
                w = base.copy()
                w[lead] = w[lead] + ALPHA_TILT
                w = w / w.sum()
                with_tilt_w.loc[dt, country_df.columns] = w.values
            else:
                with_tilt_w.loc[dt, country_df.columns] = base.values

    all_rets = pd.concat([country_df, defensive_df], axis=1).fillna(0.0)

    out = {}
    for name, w in [("with_tilt", with_tilt_w), ("no_tilt", no_tilt_w)]:
        wsum = w.loc[full_idx].sum(axis=1)
        max_dev = (wsum - 1.0).abs().max()
        if max_dev > 1e-6:
            raise ValueError(f"{name} 비중 정규화 버그: 최대 이탈 {max_dev}")
        executed = w.shift(1).fillna(0.0)
        ret = (all_rets * executed).sum(axis=1)
        scale = regime_vol_scale(ret, regime)
        final_ret = ret * scale.shift(1).fillna(1.0)

        era_results = {}
        for era_label, era_idx in [
            ("1998_2012", full_idx[full_idx <= pd.Timestamp(ERA_SPLIT)]),
            ("2013_2026", full_idx[full_idx > pd.Timestamp(ERA_SPLIT)]),
            ("full_1998_2026", full_idx),
        ]:
            m, _ = metrics_from_returns(final_ret.loc[era_idx])
            era_results[era_label] = m
            print(f"[{name}][{era_label}]: CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}", flush=True)
        out[name] = era_results

    bench_full = run_buy_and_hold("^GSPC", full_idx[0].date().isoformat(), full_idx[-1].date().isoformat())
    print("S&P500(전체):", bench_full.metrics, flush=True)
    out["sp500_full"] = bench_full.metrics

    with open(f"{OUT_DIR}/hypothesis_international_no_tilt.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
