"""세션13에서 채택한 "약세장엔 TLT/GLD를 리스크패리티로 섞는다"는 결과가 여러 해를 뭉뚱그린
평균 통계였다. 2022년은 실제 역사에서 채권-주식 상관관계가 무너진 유명한 사례다(연준 급격한
금리인상으로 주식과 채권이 동시에 하락 — "60/40 포트폴리오 최악의 해" 중 하나로 꼽힘). 방어자산
블렌드가 하필 이 해에는 안 통했을 수 있다 — 평균이 좋다고 최악의 개별 사례에서도 좋다는 뜻은
아니므로 반드시 따로 확인한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from portfolio_vol_targeting import metrics_from_returns
from multi_regime_multi_strategy import SECTOR_ETFS_MODERN, WARMUP_DAYS, MOMENTUM_WINDOW, classify_regimes
from hypothesis_defensive_assets_bear import build_weights, regime_vol_scale, DEFENSIVE_ASSETS

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
YEAR_START, YEAR_END = "2022-01-01", "2022-12-31"


def main():
    fetch_start = (pd.Timestamp(YEAR_START) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    etf_hist = get_multiple_price_history(SECTOR_ETFS_MODERN, start=fetch_start, end=YEAR_END, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(YEAR_START)) & (etf_df.index <= pd.Timestamp(YEAR_END))]
    print(f"2022년 구간: {sliced_idx[0].date()} ~ {sliced_idx[-1].date()}, {len(sliced_idx)}거래일", flush=True)

    def_hist = get_multiple_price_history(DEFENSIVE_ASSETS, start=fetch_start, end=YEAR_END, interval="1d")
    def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
    defensive_df = pd.DataFrame(def_rets)

    tlt_2022 = defensive_df["TLT"].loc[sliced_idx]
    gld_2022 = defensive_df["GLD"].loc[sliced_idx]
    tlt_cum = round(100 * ((1 + tlt_2022).prod() - 1), 2)
    gld_cum = round(100 * ((1 + gld_2022).prod() - 1), 2)
    print(f"2022년 TLT 누적수익률: {tlt_cum}%, GLD 누적수익률: {gld_cum}%", flush=True)

    regime, leader, market_trend = classify_regimes(etf_df)
    bear_days_2022 = int((regime.loc[sliced_idx] == "약세장").sum())
    print(f"2022년 약세장 국면 거래일수: {bear_days_2022}/{len(sliced_idx)}", flush=True)

    ext_w, regime2 = build_weights(etf_df, defensive_df)
    avg_defensive_weight = ext_w.loc[sliced_idx, DEFENSIVE_ASSETS].sum(axis=1).mean()
    print(f"2022년 평균 방어자산(TLT+GLD) 비중: {round(100*avg_defensive_weight,1)}%", flush=True)

    # baseline: 섹터ETF만
    from rolling_risk_parity import rolling_risk_parity_weights
    from multi_regime_multi_strategy import ALPHA_TILT
    rp_base = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")
    base_w = rp_base.copy()
    for dt in etf_df.index:
        if regime.loc[dt] == "쏠림강세":
            w = rp_base.loc[dt].copy()
            w[leader.loc[dt]] = w[leader.loc[dt]] + ALPHA_TILT
            base_w.loc[dt] = w / w.sum()
    base_ret = (etf_df.loc[sliced_idx] * base_w.loc[sliced_idx].shift(1).fillna(1.0 / base_w.shape[1])).sum(axis=1)
    base_scale = regime_vol_scale(base_ret, regime.loc[sliced_idx])
    m_base, _ = metrics_from_returns(base_ret * base_scale.shift(1).fillna(1.0))
    print("[baseline: 섹터ETF만]:", m_base, flush=True)

    all_rets = pd.concat([etf_df, defensive_df], axis=1).fillna(0.0)
    ext_executed = ext_w.loc[sliced_idx].shift(1).fillna(0.0)
    ext_ret = (all_rets.loc[sliced_idx] * ext_executed).sum(axis=1)
    ext_scale = regime_vol_scale(ext_ret, regime2.loc[sliced_idx])
    m_ext, _ = metrics_from_returns(ext_ret * ext_scale.shift(1).fillna(1.0))
    print("[방어자산 블렌드 포함]:", m_ext, flush=True)

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)

    out = {
        "tlt_2022_return_pct": tlt_cum, "gld_2022_return_pct": gld_cum,
        "bear_days_2022": bear_days_2022, "total_days_2022": len(sliced_idx),
        "avg_defensive_weight_pct": round(100 * avg_defensive_weight, 1),
        "baseline": m_base, "defensive_blend": m_ext, "sp500_bh": bench.metrics,
    }
    with open(f"{OUT_DIR}/hypothesis_2022_stress_case.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
