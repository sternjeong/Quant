"""지금까지 변동성타게팅의 cap은 항상 1.0(레버리지 없음)이었다. '쏠림강세'로 판정된, 즉 이미
방향성 신호에 어느 정도 확신이 있는 날에 한해서만 cap을 살짝 높이면(1.1/1.25/1.5) 위험조정
수익이 개선되는지, 아니면 MDD가 신호 오탐 시 감내 못할 수준으로 커지는지 확인한다.
쏠림강세가 아닌 날은 항상 cap=1.0(레버리지 없음)으로 고정 — '확신 있을 때만 상한을 푼다'는
원 가설 그대로 구현."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import numpy as np
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from rolling_risk_parity import rolling_risk_parity_weights
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns
from multi_regime_multi_strategy import (
    SECTOR_ETFS_MODERN, SECTOR_ETFS_LEGACY, WARMUP_DAYS, MOMENTUM_WINDOW,
    BULL_TREND_PCT, Z_THRESHOLD, ALPHA_TILT,
)

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
LEVERAGE_CAPS = [1.0, 1.1, 1.25, 1.5]


def build_tilted(etf_df):
    trailing_mom = etf_df.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: (1 + x).prod() - 1, raw=True)
    market_trend = trailing_mom.mean(axis=1) * 100
    cross_mean = trailing_mom.mean(axis=1)
    cross_std = trailing_mom.std(axis=1)
    z_scores = trailing_mom.sub(cross_mean, axis=0).div(cross_std.replace(0, np.nan), axis=0)
    max_z = z_scores.max(axis=1)
    leader = z_scores.idxmax(axis=1)
    is_narrow_bull = (market_trend > BULL_TREND_PCT) & (max_z >= Z_THRESHOLD)

    rp_weights = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")
    tilted = rp_weights.copy()
    for dt in etf_df.index:
        if is_narrow_bull.loc[dt]:
            w = rp_weights.loc[dt].copy()
            w[leader.loc[dt]] = w[leader.loc[dt]] + ALPHA_TILT
            tilted.loc[dt] = w / w.sum()
    return tilted, is_narrow_bull


def eval_variable_cap(etf_df, tilted_w, is_narrow_bull, sliced_idx, leverage_cap):
    """쏠림강세인 날만 vol_target cap을 leverage_cap으로, 그 외엔 1.0으로 매일 적용."""
    executed_w = tilted_w.loc[sliced_idx].shift(1).fillna(1.0 / tilted_w.shape[1])
    ret = (etf_df.loc[sliced_idx] * executed_w).sum(axis=1)

    scale_normal = vol_target_scale(ret, 18.0, 1.0, window=5)
    scale_levered = vol_target_scale(ret, 18.0, leverage_cap, window=5)
    is_bull = is_narrow_bull.loc[sliced_idx].reindex(ret.index).fillna(False)
    scale = scale_levered.where(is_bull, scale_normal)

    executed_scale = scale.shift(1).fillna(1.0)
    final_ret = ret * executed_scale
    m, _ = metrics_from_returns(final_ret)
    return m


def run_period(label, start, end, sector_etfs):
    print(f"\n{'='*20} {label} {'='*20}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(start)) & (etf_df.index <= pd.Timestamp(end))]

    tilted_w, is_narrow_bull = build_tilted(etf_df)

    out = {}
    for cap in LEVERAGE_CAPS:
        m = eval_variable_cap(etf_df, tilted_w, is_narrow_bull, sliced_idx, cap)
        print(f"[레버리지cap={cap}]: CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}, calmar={m['calmar']}", flush=True)
        out[f"cap_{cap}"] = m

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    out["sp500_bh"] = bench.metrics
    return out


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2000_2012"] = run_period("약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_leverage_sensitivity.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
