"""통합 v3 시스템(쏠림강세 리더틸트 + 약세장 TLT/GLD 편입, 둘 다 이번 라운드에서 검증됨)을
세션12의 진짜 홀드아웃 구간(2013~2014, 어떤 파라미터 결정에도 안 쓰인 구간)에 다시 적용해 이번에
새로 추가한 조각(방어자산 편입)까지 포함해도 아웃오브샘플에서 무너지지 않는지 확인한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from portfolio_vol_targeting import metrics_from_returns
from multi_regime_multi_strategy import SECTOR_ETFS_LEGACY, WARMUP_DAYS, MOMENTUM_WINDOW, ALPHA_TILT, classify_regimes
from rolling_risk_parity import rolling_risk_parity_weights
from hypothesis_defensive_assets_bear import build_weights, regime_vol_scale, DEFENSIVE_ASSETS

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
START, END = "2013-01-01", "2014-12-31"


def main():
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    etf_hist = get_multiple_price_history(SECTOR_ETFS_LEGACY, start=fetch_start, end=END, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(START)) & (etf_df.index <= pd.Timestamp(END))]
    print(f"홀드아웃 구간: {sliced_idx[0].date()} ~ {sliced_idx[-1].date()}, {len(sliced_idx)}거래일", flush=True)

    def_hist = get_multiple_price_history(DEFENSIVE_ASSETS, start=fetch_start, end=END, interval="1d")
    def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
    defensive_df = pd.DataFrame(def_rets)

    # baseline: 세션11/12가 쓰던 확정 시스템(섹터ETF만, 쏠림틸트, 국면별 변동성타게팅)
    regime_only, leader_only, _ = classify_regimes(etf_df)
    rp_base = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")
    base_w = rp_base.copy()
    for dt in etf_df.index:
        if regime_only.loc[dt] == "쏠림강세":
            w = rp_base.loc[dt].copy()
            w[leader_only.loc[dt]] = w[leader_only.loc[dt]] + ALPHA_TILT
            base_w.loc[dt] = w / w.sum()
    base_ret = (etf_df.loc[sliced_idx] * base_w.loc[sliced_idx].shift(1).fillna(1.0 / base_w.shape[1])).sum(axis=1)
    base_scale = regime_vol_scale(base_ret, regime_only.loc[sliced_idx])
    base_final = base_ret * base_scale.shift(1).fillna(1.0)
    m_base, _ = metrics_from_returns(base_final)
    print("[baseline: 확정 시스템(섹터ETF만)]:", m_base, flush=True)

    # v3: 쏠림틸트 + 약세장 TLT/GLD 편입
    ext_w, regime = build_weights(etf_df, defensive_df)
    all_rets = pd.concat([etf_df, defensive_df], axis=1).fillna(0.0)
    ext_executed = ext_w.loc[sliced_idx].shift(1).fillna(0.0)
    ext_ret = (all_rets.loc[sliced_idx] * ext_executed).sum(axis=1)
    ext_scale = regime_vol_scale(ext_ret, regime.loc[sliced_idx])
    ext_final = ext_ret * ext_scale.shift(1).fillna(1.0)
    m_ext, _ = metrics_from_returns(ext_final)
    print("[v3 통합: 쏠림틸트+약세장 방어자산]:", m_ext, flush=True)

    bear_days = int((regime.loc[sliced_idx] == "약세장").sum())
    print(f"약세장 거래일수: {bear_days} / 총 {len(sliced_idx)}일", flush=True)

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)

    out = {
        "period": {"start": str(sliced_idx[0].date()), "end": str(sliced_idx[-1].date())},
        "bear_days": bear_days, "baseline": m_base, "v3_integrated": m_ext, "sp500_bh": bench.metrics,
    }
    with open(f"{OUT_DIR}/hypothesis_integrated_v3_holdout.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
