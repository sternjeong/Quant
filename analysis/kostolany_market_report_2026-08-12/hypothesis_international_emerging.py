"""세션14는 선진국 9개국만 썼다 — 이 기간(1998~2026) 선진국 지수가 구조적으로 미국에 뒤처졌다는
"선진국 편중" 자체가 실패 원인이었을 수 있다. 신흥국(브라질·한국·대만, 그리고 신흥국 전체 EEM)을
추가하면 결과가 개선되는지 확인한다. 이 티커들은 2000~2003년부터 존재해 전체구간을 2003년 이후로
축소해야 공정 비교가 된다."""
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
from hypothesis_international_generalization import COUNTRY_ETFS as DEVELOPED, DEFENSIVE_ASSETS, ERA_SPLIT, regime_vol_scale

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
EMERGING = ["EWZ", "EWY", "EWT", "EEM"]
START, END = "2004-01-01", "2026-08-12"


def build_system(country_df, defensive_df):
    regime, leader, market_trend = classify_regimes(country_df)
    rp_equity = rolling_risk_parity_weights(country_df, lookback_days=252, rebal_freq="QS")

    combined_df = pd.concat([country_df, defensive_df], axis=1).dropna(how="any", axis=0)
    rp_extended = rolling_risk_parity_weights(combined_df, lookback_days=252, rebal_freq="QS")
    rp_extended = rp_extended.reindex(country_df.index).ffill().bfill()

    all_cols = list(country_df.columns) + DEFENSIVE_ASSETS
    w = pd.DataFrame(0.0, index=country_df.index, columns=all_cols)
    for dt in country_df.index:
        r = regime.loc[dt]
        if r == "약세장" and dt in rp_extended.index:
            w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
        else:
            base = rp_equity.loc[dt].copy()
            if r == "쏠림강세":
                lead = leader.loc[dt]
                base[lead] = base[lead] + ALPHA_TILT
                base = base / base.sum()
            w.loc[dt, country_df.columns] = base.values
    return w, regime


def run_universe(label, tickers, fetch_start):
    country_hist = get_multiple_price_history(tickers, start=fetch_start, end=END, interval="1d")
    country_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in country_hist.items() if df is not None and not df.empty}
    country_df = pd.DataFrame(country_rets).dropna(how="all", axis=0)

    def_hist = get_multiple_price_history(DEFENSIVE_ASSETS, start=fetch_start, end=END, interval="1d")
    def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
    defensive_df = pd.DataFrame(def_rets)

    sliced_idx = country_df.index[(country_df.index >= pd.Timestamp(START)) & (country_df.index <= pd.Timestamp(END))]
    w, regime = build_system(country_df, defensive_df)

    wsum = w.loc[sliced_idx].sum(axis=1)
    max_dev = (wsum - 1.0).abs().max()
    if max_dev > 1e-6:
        raise ValueError(f"{label} 비중 정규화 버그: 최대 이탈 {max_dev}")

    all_rets = pd.concat([country_df, defensive_df], axis=1).fillna(0.0)
    executed = w.loc[sliced_idx].shift(1).fillna(0.0)
    ret = (all_rets.loc[sliced_idx] * executed).sum(axis=1)
    scale = regime_vol_scale(ret, regime.loc[sliced_idx])
    final_ret = ret * scale.shift(1).fillna(1.0)
    m, _ = metrics_from_returns(final_ret)
    print(f"[{label}]: CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}, calmar={m['calmar']}", flush=True)
    return m, sliced_idx


def main():
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    print(f"구간: {START} ~ {END}", flush=True)

    m_dev, sliced_idx = run_universe("선진국9개국만(2004~)", DEVELOPED, fetch_start)
    m_all, _ = run_universe("선진국9+신흥국4(2004~)", DEVELOPED + EMERGING, fetch_start)

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)

    out = {"developed_only": m_dev, "developed_plus_emerging": m_all, "sp500_bh": bench.metrics,
           "period": {"start": str(sliced_idx[0].date()), "end": str(sliced_idx[-1].date())}}
    with open(f"{OUT_DIR}/hypothesis_international_emerging.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
