"""지금까지의 틸트는 '리더 섹터에 +50%p'만 하고 나머지는 리스크패리티 비중을 비례 축소해
자동으로 흡수했다. 대칭적으로 '꼴찌(최소 z-점수) 섹터를 명시적으로 감액'하면 더 나아지는가?
— 사후 스윕이 아니라 이미 확정한 ALPHA_TILT=0.5를 리더/래거드 사이에 어떻게 나눌지만 바꾸는
구조적 변형이다: (a) 기존(리더만 +), (b) 리더 +0.5 전부를 래거드에서만 뺌(래거드가 음수면 0
캡 후 나머지는 비례배분), (c) 리더 +0.35 / 래거드 -0.15 식으로 절반씩 나눠 분산."""
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


def build_regime(etf_df):
    trailing_mom = etf_df.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: (1 + x).prod() - 1, raw=True)
    market_trend = trailing_mom.mean(axis=1) * 100
    cross_mean = trailing_mom.mean(axis=1)
    cross_std = trailing_mom.std(axis=1)
    z_scores = trailing_mom.sub(cross_mean, axis=0).div(cross_std.replace(0, np.nan), axis=0)
    max_z = z_scores.max(axis=1)
    min_z = z_scores.min(axis=1)
    leader = z_scores.idxmax(axis=1)
    laggard = z_scores.idxmin(axis=1)
    is_narrow_bull = (market_trend > BULL_TREND_PCT) & (max_z >= Z_THRESHOLD)
    return is_narrow_bull, leader, laggard, min_z


def tilt_leader_only(rp_weights, etf_df, is_narrow_bull, leader):
    tilted = rp_weights.copy()
    for dt in etf_df.index:
        if is_narrow_bull.loc[dt]:
            w = rp_weights.loc[dt].copy()
            w[leader.loc[dt]] = w[leader.loc[dt]] + ALPHA_TILT
            tilted.loc[dt] = w / w.sum()
    return tilted


def tilt_leader_laggard_full(rp_weights, etf_df, is_narrow_bull, leader, laggard):
    """전액(ALPHA_TILT)을 래거드에서만 빼서 리더로 이동. 래거드 비중이 부족하면(0으로 캡) 남는
    부족분은 나머지 종목에서 비례로 추가 차감."""
    tilted = rp_weights.copy()
    for dt in etf_df.index:
        if is_narrow_bull.loc[dt]:
            w = rp_weights.loc[dt].copy()
            lead, lag = leader.loc[dt], laggard.loc[dt]
            take = min(ALPHA_TILT, w[lag])
            w[lag] = w[lag] - take
            remaining = ALPHA_TILT - take
            if remaining > 0:
                others = w.drop(index=[lag, lead]) if lead != lag else w.drop(index=[lag])
                if others.sum() > 0:
                    w[others.index] = w[others.index] - others / others.sum() * remaining
                    w[w < 0] = 0.0
            w[lead] = w[lead] + ALPHA_TILT
            tilted.loc[dt] = w / w.sum()
    return tilted


def tilt_leader_laggard_half(rp_weights, etf_df, is_narrow_bull, leader, laggard):
    """ALPHA_TILT를 절반씩: 리더 +ALPHA_TILT/2는 래거드에서만 빼고, 나머지 절반은 리더가
    나머지 종목들로부터 비례로 흡수(기존 방식과 동일)."""
    tilted = rp_weights.copy()
    half = ALPHA_TILT / 2.0
    for dt in etf_df.index:
        if is_narrow_bull.loc[dt]:
            w = rp_weights.loc[dt].copy()
            lead, lag = leader.loc[dt], laggard.loc[dt]
            take = min(half, w[lag])
            w[lag] = w[lag] - take
            w[lead] = w[lead] + take
            w[lead] = w[lead] + half
            tilted.loc[dt] = w / w.sum()
    return tilted


def eval_variant(etf_df, weights, sliced_idx):
    executed = weights.loc[sliced_idx].shift(1).fillna(1.0 / weights.shape[1])
    ret = (etf_df.loc[sliced_idx] * executed).sum(axis=1)
    scale = vol_target_scale(ret, 18.0, 1.0, window=5)
    m, _ = metrics_from_returns(ret * scale.shift(1).fillna(1.0))
    return m


def run_period(label, start, end, sector_etfs):
    print(f"\n{'='*20} {label} {'='*20}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(start)) & (etf_df.index <= pd.Timestamp(end))]

    is_narrow_bull, leader, laggard, min_z = build_regime(etf_df)
    rp_weights = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")

    variants = {
        "leader_only (기존 채택안)": tilt_leader_only(rp_weights, etf_df, is_narrow_bull, leader),
        "leader+laggard_full": tilt_leader_laggard_full(rp_weights, etf_df, is_narrow_bull, leader, laggard),
        "leader+laggard_half": tilt_leader_laggard_half(rp_weights, etf_df, is_narrow_bull, leader, laggard),
    }
    out = {}
    for name, w in variants.items():
        wsum = w.loc[sliced_idx].sum(axis=1)
        max_dev = (wsum - 1.0).abs().max()
        if max_dev > 1e-6:
            raise ValueError(f"{name} 비중 정규화 버그: 최대 이탈 {max_dev}")
        m = eval_variant(etf_df, w, sliced_idx)
        print(f"[{name}]: CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}, calmar={m['calmar']}", flush=True)
        out[name] = m

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    out["sp500_bh"] = bench.metrics
    return out


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2000_2012"] = run_period("약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_laggard_underweight.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
