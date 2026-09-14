"""진짜 아웃오브샘플 검증: 지금까지 쓴 두 시대(2000~2012, 2015~2026) "사이"에 있는 2013~2014년은
이 리포트의 어떤 설계 결정(z≥1, 시장추세 ±5%, 틸트 50%p, 목표변동성 18%, 룩백 5일)에도 전혀 쓰이지
않은 순수 홀드아웃 구간이다. 이미 확정된(더 이상 조정하지 않는) 파라미터를 그대로 이 구간에
적용해서 결과를 "미리 보지 않고" 확인한다 — 이게 진짜 아웃오브샘플 검증이다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import numpy as np
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from rolling_risk_parity import rolling_risk_parity_weights
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns
from multi_regime_multi_strategy import WARMUP_DAYS, MOMENTUM_WINDOW, BULL_TREND_PCT, Z_THRESHOLD, ALPHA_TILT

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
SECTOR_ETFS_LEGACY = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU"]
START, END = "2013-01-01", "2014-12-31"


def main():
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    etf_hist = get_multiple_price_history(SECTOR_ETFS_LEGACY, start=fetch_start, end=END, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(START)) & (etf_df.index <= pd.Timestamp(END))]
    print(f"홀드아웃 구간: {sliced_idx[0].date()} ~ {sliced_idx[-1].date()}, {len(sliced_idx)}거래일", flush=True)

    trailing_mom = etf_df.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: (1 + x).prod() - 1, raw=True)
    market_trend = trailing_mom.mean(axis=1) * 100
    cross_mean = trailing_mom.mean(axis=1)
    cross_std = trailing_mom.std(axis=1)
    z_scores = trailing_mom.sub(cross_mean, axis=0).div(cross_std.replace(0, np.nan), axis=0)
    max_z = z_scores.max(axis=1)
    leader = z_scores.idxmax(axis=1)
    is_narrow_bull = (market_trend > BULL_TREND_PCT) & (max_z >= Z_THRESHOLD)
    print("쏠림강세 비율:", round(100 * is_narrow_bull.loc[sliced_idx].mean(), 1), "%", flush=True)
    print("리더 섹터 분포:", leader.loc[sliced_idx][is_narrow_bull.loc[sliced_idx]].value_counts().to_dict(), flush=True)

    rp_weights = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")
    tilted = rp_weights.copy()
    for dt in etf_df.index:
        if is_narrow_bull.loc[dt]:
            w = rp_weights.loc[dt].copy()
            lead = leader.loc[dt]
            w[lead] = w[lead] + ALPHA_TILT
            tilted.loc[dt] = w / w.sum()

    def compute_ret(w_full):
        w = w_full.loc[sliced_idx]
        executed = w.shift(1).fillna(1.0 / w.shape[1])
        return (etf_df.loc[sliced_idx] * executed).sum(axis=1)

    rp_ret = compute_ret(rp_weights)
    tilt_ret = compute_ret(tilted)

    m_rp_raw, _ = metrics_from_returns(rp_ret)
    m_tilt_raw, _ = metrics_from_returns(tilt_ret)
    print("[baseline, 오버레이 없음]:", m_rp_raw, flush=True)
    print("[틸트, 오버레이 없음]:", m_tilt_raw, flush=True)

    scale_rp = vol_target_scale(rp_ret, 18.0, 1.0, window=5)
    m_rp, _ = metrics_from_returns(rp_ret * scale_rp.shift(1).fillna(1.0))
    scale_tilt = vol_target_scale(tilt_ret, 18.0, 1.0, window=5)
    m_tilt, _ = metrics_from_returns(tilt_ret * scale_tilt.shift(1).fillna(1.0))
    print("[baseline+변동성타게팅]:", m_rp, flush=True)
    print("[틸트+변동성타게팅]:", m_tilt, flush=True)

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)

    with open(f"{OUT_DIR}/hypothesis_holdout_bridge.json", "w", encoding="utf-8") as f:
        json.dump({
            "period": {"start": str(sliced_idx[0].date()), "end": str(sliced_idx[-1].date())},
            "narrow_bull_pct": round(100 * is_narrow_bull.loc[sliced_idx].mean(), 1),
            "rp_final": m_rp, "tilt_final": m_tilt, "sp500_bh": bench.metrics,
        }, f, ensure_ascii=False, indent=2)
    print("DONE")


if __name__ == "__main__":
    main()
