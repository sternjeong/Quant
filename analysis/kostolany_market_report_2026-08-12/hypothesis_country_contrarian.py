"""세션15는 국가ETF 로테이션에서 리더추격(모멘텀) 틸트가 잡음이었음을 확인했다. 국가 지수는
학계에서 종목 단위보다 더 긴 호흡의 평균회귀(country value/reversal) 효과가 보고된 사례가 있다
(예: AQR의 국가가치 연구). 순수 리스크패리티(틸트 없음, 세션15의 최선안)에 리더 대신 래거드(횡단면
z 최소 국가)로 틸트를 걸면 — 즉 코스톨라니식 역발상을 국가 로테이션 레벨에서 재시도하면 — 다른
결과가 나오는지 확인한다. 세션13에서 미국 섹터 로테이션 레벨의 역발상은 명확히 기각됐지만, 그때와
지금은 유니버스 성격이 다르다(모멘텀 자체가 이미 국가 레벨에선 안 통했으므로)."""
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

    trailing_mom = country_df.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: (1 + x).prod() - 1, raw=True)
    cross_mean = trailing_mom.mean(axis=1)
    cross_std = trailing_mom.std(axis=1)
    z_scores = trailing_mom.sub(cross_mean, axis=0).div(cross_std.replace(0, np.nan), axis=0)
    laggard = z_scores.idxmin(axis=1)

    regime, leader, market_trend = classify_regimes(country_df)
    rp_equity = rolling_risk_parity_weights(country_df, lookback_days=252, rebal_freq="QS")

    combined_df = pd.concat([country_df, defensive_df], axis=1).dropna(how="any", axis=0)
    rp_extended = rolling_risk_parity_weights(combined_df, lookback_days=252, rebal_freq="QS")
    rp_extended = rp_extended.reindex(country_df.index).ffill().bfill()

    all_cols = list(country_df.columns) + DEFENSIVE_ASSETS

    no_tilt_w = pd.DataFrame(0.0, index=country_df.index, columns=all_cols)
    contrarian_w = pd.DataFrame(0.0, index=country_df.index, columns=all_cols)

    for dt in country_df.index:
        r = regime.loc[dt]
        if r == "약세장" and dt in rp_extended.index:
            no_tilt_w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
            contrarian_w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
        else:
            base = rp_equity.loc[dt].copy()
            no_tilt_w.loc[dt, country_df.columns] = base.values
            if r == "쏠림강세":
                lag = laggard.loc[dt]
                w = base.copy()
                w[lag] = w[lag] + ALPHA_TILT
                w = w / w.sum()
                contrarian_w.loc[dt, country_df.columns] = w.values
            else:
                contrarian_w.loc[dt, country_df.columns] = base.values

    all_rets = pd.concat([country_df, defensive_df], axis=1).fillna(0.0)

    out = {}
    for name, w in [("no_tilt(세션15 최선안)", no_tilt_w), ("contrarian_laggard_tilt(신가설)", contrarian_w)]:
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

    with open(f"{OUT_DIR}/hypothesis_country_contrarian.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
