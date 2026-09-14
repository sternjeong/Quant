"""세션17에서 채택한 국가 로테이션 역발상(래거드) 틸트가 z≥1.0이라는 임계값에 우연히 맞아
떨어진 사후 스윕이 아닌지 확인한다. 세션13이 섹터 쏠림틸트에 했던 것과 똑같은 방식(z=0.5~2.0
민감도 스캔)을 역발상 틸트에도 적용 — 여러 값에서 결과가 안정적이면 로버스트, 특정 값에서만
좋으면 과적합 의심."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import numpy as np
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from rolling_risk_parity import rolling_risk_parity_weights
from portfolio_vol_targeting import metrics_from_returns
from multi_regime_multi_strategy import WARMUP_DAYS, MOMENTUM_WINDOW, ALPHA_TILT, BULL_TREND_PCT, classify_regimes
from hypothesis_international_generalization import COUNTRY_ETFS, DEFENSIVE_ASSETS, FULL_START, FULL_END, regime_vol_scale

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
Z_THRESHOLDS = [0.5, 0.75, 1.0, 1.5, 2.0]


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
    market_trend = trailing_mom.mean(axis=1) * 100
    cross_mean = trailing_mom.mean(axis=1)
    cross_std = trailing_mom.std(axis=1)
    z_scores = trailing_mom.sub(cross_mean, axis=0).div(cross_std.replace(0, np.nan), axis=0)
    laggard = z_scores.idxmin(axis=1)
    max_z = z_scores.max(axis=1)

    regime, leader, _ = classify_regimes(country_df)
    rp_equity = rolling_risk_parity_weights(country_df, lookback_days=252, rebal_freq="QS")

    combined_df = pd.concat([country_df, defensive_df], axis=1).dropna(how="any", axis=0)
    rp_extended = rolling_risk_parity_weights(combined_df, lookback_days=252, rebal_freq="QS")
    rp_extended = rp_extended.reindex(country_df.index).ffill().bfill()

    all_cols = list(country_df.columns) + DEFENSIVE_ASSETS
    all_rets = pd.concat([country_df, defensive_df], axis=1).fillna(0.0)

    out = {}
    for z_thr in Z_THRESHOLDS:
        is_narrow_bull = (market_trend > BULL_TREND_PCT) & (max_z >= z_thr)
        narrow_pct = round(100 * is_narrow_bull.loc[full_idx].mean(), 1)

        w = pd.DataFrame(0.0, index=country_df.index, columns=all_cols)
        for dt in country_df.index:
            r = regime.loc[dt]
            if r == "약세장" and dt in rp_extended.index:
                w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
            else:
                base = rp_equity.loc[dt].copy()
                if is_narrow_bull.loc[dt]:
                    lag = laggard.loc[dt]
                    base[lag] = base[lag] + ALPHA_TILT
                    base = base / base.sum()
                w.loc[dt, country_df.columns] = base.values

        wsum = w.loc[full_idx].sum(axis=1)
        max_dev = (wsum - 1.0).abs().max()
        if max_dev > 1e-6:
            raise ValueError(f"z={z_thr} 비중 정규화 버그: 최대 이탈 {max_dev}")

        executed = w.loc[full_idx].shift(1).fillna(0.0)
        ret = (all_rets.loc[full_idx] * executed).sum(axis=1)
        scale = regime_vol_scale(ret, regime.loc[full_idx])
        final_ret = ret * scale.shift(1).fillna(1.0)
        m, _ = metrics_from_returns(final_ret)
        print(f"[z>={z_thr}] 쏠림비율={narrow_pct}%: CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}", flush=True)
        out[f"z_{z_thr}"] = {"narrow_bull_pct": narrow_pct, **m}

    bench = run_buy_and_hold("^GSPC", full_idx[0].date().isoformat(), full_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    out["sp500_bh"] = bench.metrics

    with open(f"{OUT_DIR}/hypothesis_country_contrarian_robustness.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
