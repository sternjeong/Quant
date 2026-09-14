"""세션16이 GICS 섹터와 스타일 팩터 각각에서 프레임워크가 통함을 확인했다. 이 가설: 둘을
하나의 확장된 미국 국내 유니버스(9개 섹터 + 5개 팩터 = 14개 자산)로 합쳐 리스크패리티를 걸면
어느 한쪽만 쓰는 것보다 나은지 확인한다 — 서로 다른 두 "렌즈"(업종·스타일)로 시장을 동시에
분산하면 상관관계가 더 낮아질 수 있다는 가설. 팩터ETF(MTUM 2013-04) 제약으로 2014~2026만 검증."""
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
from hypothesis_us_factor_universe import FACTOR_ETFS, START as FACTOR_START

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
START, END = FACTOR_START, "2026-08-12"


def build_and_eval(universe_df, defensive_df, sliced_idx, label):
    regime, leader, market_trend = classify_regimes(universe_df)
    rp_equity = rolling_risk_parity_weights(universe_df, lookback_days=252, rebal_freq="QS")

    combined_df = pd.concat([universe_df, defensive_df], axis=1).dropna(how="any", axis=0)
    rp_extended = rolling_risk_parity_weights(combined_df, lookback_days=252, rebal_freq="QS")
    rp_extended = rp_extended.reindex(universe_df.index).ffill().bfill()

    all_cols = list(universe_df.columns) + DEFENSIVE_ASSETS
    w = pd.DataFrame(0.0, index=universe_df.index, columns=all_cols)
    for dt in universe_df.index:
        r = regime.loc[dt]
        if r == "약세장" and dt in rp_extended.index:
            w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
        else:
            base = rp_equity.loc[dt].copy()
            w.loc[dt, universe_df.columns] = base.values  # 세션16 발견: 틸트 없는 편이 나음(공통 적용)

    wsum = w.loc[sliced_idx].sum(axis=1)
    max_dev = (wsum - 1.0).abs().max()
    if max_dev > 1e-6:
        raise ValueError(f"{label} 비중 정규화 버그: 최대 이탈 {max_dev}")

    all_rets = pd.concat([universe_df, defensive_df], axis=1).fillna(0.0)
    executed = w.loc[sliced_idx].shift(1).fillna(0.0)
    ret = (all_rets.loc[sliced_idx] * executed).sum(axis=1)
    scale = regime_vol_scale(ret, regime.loc[sliced_idx])
    final_ret = ret * scale.shift(1).fillna(1.0)
    m, _ = metrics_from_returns(final_ret)
    print(f"[{label}]: CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}, calmar={m['calmar']}", flush=True)
    return m


def main():
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    print(f"구간: {START} ~ {END}", flush=True)

    sector_hist = get_multiple_price_history(SECTOR_ETFS_MODERN, start=fetch_start, end=END, interval="1d")
    sector_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in sector_hist.items() if df is not None and not df.empty}
    sector_df = pd.DataFrame(sector_rets).dropna(how="all", axis=0)

    factor_hist = get_multiple_price_history(FACTOR_ETFS, start=fetch_start, end=END, interval="1d")
    factor_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in factor_hist.items() if df is not None and not df.empty}
    factor_df = pd.DataFrame(factor_rets).dropna(how="all", axis=0)

    combined_universe_df = pd.concat([sector_df, factor_df], axis=1).dropna(how="any", axis=0)

    def_hist = get_multiple_price_history(DEFENSIVE_ASSETS, start=fetch_start, end=END, interval="1d")
    def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
    defensive_df = pd.DataFrame(def_rets)

    sliced_idx = combined_universe_df.index[(combined_universe_df.index >= pd.Timestamp(START)) & (combined_universe_df.index <= pd.Timestamp(END))]
    print(f"결합 유니버스 자산 수: {len(combined_universe_df.columns)}개 (섹터{len(sector_df.columns)}+팩터{len(factor_df.columns)})", flush=True)

    out = {}
    out["sector_only"] = build_and_eval(sector_df, defensive_df, sliced_idx, "섹터만(9개)")
    out["factor_only"] = build_and_eval(factor_df, defensive_df, sliced_idx, "팩터만(5개)")
    out["combined"] = build_and_eval(combined_universe_df, defensive_df, sliced_idx, "결합(14개)")

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    out["sp500_bh"] = bench.metrics
    out["period"] = {"start": str(sliced_idx[0].date()), "end": str(sliced_idx[-1].date())}

    with open(f"{OUT_DIR}/hypothesis_sector_factor_combined.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
