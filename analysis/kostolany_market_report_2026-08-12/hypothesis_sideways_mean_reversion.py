"""코스톨라니 이론의 원래 정신(횡보/박스권에서 저평가 자산을 사서 평균회귀를 노림)은 01~05장에서
개별종목 단위로 검증돼 기각됐다. 그런데 이 리포트가 이미 확정한 국면분류는 "횡보장"(트레일링
12개월 시장추세 -5%~+5%)을 별도 상태로 잡아낸다 — 이 국면에서만, 개별종목이 아니라 섹터 ETF
로테이션 레벨에서 코스톨라니식 역발상(그 시점 횡단면 z-점수가 가장 낮은=상대적으로 가장 저평가된
섹터에 틸트)을 걸면 다른 결과가 나오는지 확인한다. 쏠림강세 틸트(리더에 +50%p)와 정확히 대칭.
"""
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
    Z_THRESHOLD, BULL_TREND_PCT, BEAR_TREND_PCT, ALPHA_TILT, classify_regimes,
)

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"


def build_variants(etf_df):
    trailing_mom = etf_df.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: (1 + x).prod() - 1, raw=True)
    cross_mean = trailing_mom.mean(axis=1)
    cross_std = trailing_mom.std(axis=1)
    z_scores = trailing_mom.sub(cross_mean, axis=0).div(cross_std.replace(0, np.nan), axis=0)
    laggard = z_scores.idxmin(axis=1)

    regime, leader, market_trend = classify_regimes(etf_df)
    rp_weights = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")

    baseline = rp_weights.copy()  # 확정 시스템: 횡보장엔 틸트 없음, 쏠림강세만 틸트
    for dt in etf_df.index:
        if regime.loc[dt] == "쏠림강세":
            w = rp_weights.loc[dt].copy()
            w[leader.loc[dt]] = w[leader.loc[dt]] + ALPHA_TILT
            baseline.loc[dt] = w / w.sum()

    contrarian = baseline.copy()  # 신가설: 횡보장엔 z최소(래거드) 섹터에 역발상 틸트 추가
    for dt in etf_df.index:
        if regime.loc[dt] == "횡보장":
            z_row = z_scores.loc[dt]
            if z_row.isna().all():
                continue
            lag = z_row.idxmin()
            w = rp_weights.loc[dt].copy()
            w[lag] = w[lag] + ALPHA_TILT
            contrarian.loc[dt] = w / w.sum()

    return baseline, contrarian, regime


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

    baseline_w, contrarian_w, regime = build_variants(etf_df)
    sideways_days = int((regime.loc[sliced_idx] == "횡보장").sum())
    print(f"횡보장 거래일수: {sideways_days}", flush=True)

    out = {"sideways_days": sideways_days}
    for name, w in [("baseline", baseline_w), ("contrarian_sideways", contrarian_w)]:
        wsum = w.loc[sliced_idx].sum(axis=1)
        max_dev = (wsum - 1.0).abs().max()
        if max_dev > 1e-6:
            raise ValueError(f"{name} 비중 정규화 버그: 최대 이탈 {max_dev}")
        executed = w.loc[sliced_idx].shift(1).fillna(1.0 / w.shape[1])
        ret = (etf_df.loc[sliced_idx] * executed).sum(axis=1)
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
    out["2000_2012"] = run_period("약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_sideways_mean_reversion.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
