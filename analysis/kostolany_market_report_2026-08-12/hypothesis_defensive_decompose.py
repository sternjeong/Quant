"""hypothesis_defensive_assets_bear.py에서 TLT+GLD를 묶어서 약세장에 추가했더니 작지만 일관된
개선이 있었다. 어느 쪽이 기여했는지(TLT만? GLD만? 둘 다?) 분해해서 블랙박스로 남기지 않는다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from portfolio_vol_targeting import metrics_from_returns
from multi_regime_multi_strategy import SECTOR_ETFS_MODERN, SECTOR_ETFS_LEGACY, WARMUP_DAYS, MOMENTUM_WINDOW
from hypothesis_defensive_assets_bear import build_weights, regime_vol_scale

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"


def run_period(label, start, end, sector_etfs, defensive_sets):
    print(f"\n{'='*20} {label} {'='*20}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(start)) & (etf_df.index <= pd.Timestamp(end))]

    out = {}
    for name, assets in defensive_sets.items():
        def_hist = get_multiple_price_history(assets, start=fetch_start, end=end, interval="1d")
        def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
        defensive_df = pd.DataFrame(def_rets)

        w, regime = build_weights(etf_df, defensive_df)
        all_rets = pd.concat([etf_df, defensive_df], axis=1).fillna(0.0)
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
    defensive_sets = {"TLT_only": ["TLT"], "GLD_only": ["GLD"], "TLT_GLD": ["TLT", "GLD"]}
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN, defensive_sets)
    out["2006_2012"] = run_period("약세장포함 부분구간", "2006-01-01", "2012-12-31", SECTOR_ETFS_LEGACY, defensive_sets)
    with open(f"{OUT_DIR}/hypothesis_defensive_decompose.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
