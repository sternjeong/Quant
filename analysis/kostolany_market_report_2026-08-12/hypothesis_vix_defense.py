"""추세필터(200일선)와 확인형(AND) 둘 다 강세장에서 손해를 봤다 — 트레일링 12개월 국면판정이
너무 느린 신호라 빠른 조정(2018년말, 2020년 코로나)에 지각 대응했기 때문으로 추정했다. VIX는
가격도 트레일링 수익률도 아닌 완전히 다른(그리고 훨씬 빠른, 실시간에 가까운) 공포 지표다 — VIX가
표준적인 "위기" 임계값(30, 실무에서 널리 쓰는 사전 정의 기준. 20 이하=평온, 20~30=경계, 30 이상=
위기)을 넘으면 방어모드로 들어가는 오버레이가 200일선보다 반응이 빠른지, 강세장 오탐이 덜한지
확인한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import numpy as np
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from portfolio_vol_targeting import metrics_from_returns
from multi_regime_multi_strategy import SECTOR_ETFS_MODERN, SECTOR_ETFS_LEGACY, WARMUP_DAYS, MOMENTUM_WINDOW
from hypothesis_absolute_trend_filter import build_confirmed_system_return, regime_vol_scale

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
VIX_THRESHOLD = 30.0  # 실무 표준 "위기" 임계값(사전 정의, 스윕 아님)
DEFENSE_MULTIPLIERS = [1.0, 0.5, 0.25]


def run_period(label, start, end, sector_etfs):
    print(f"\n{'='*20} {label} {'='*20}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()

    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(start)) & (etf_df.index <= pd.Timestamp(end))]

    vix_hist = get_multiple_price_history(["^VIX"], start=fetch_start, end=end, interval="1d")["^VIX"]
    vix_close = vix_hist["Close"].reindex(etf_df.index).ffill()
    is_crisis = (vix_close > VIX_THRESHOLD)
    crisis_pct = round(100 * is_crisis.loc[sliced_idx].mean(), 1)
    print(f"VIX>{VIX_THRESHOLD} 비율: {crisis_pct}%", flush=True)

    port_ret, regime = build_confirmed_system_return(etf_df, sliced_idx)
    base_scale = regime_vol_scale(port_ret, regime, sliced_idx)
    is_crisis_r = is_crisis.reindex(port_ret.index).fillna(False)

    out = {"crisis_pct": crisis_pct}
    for mult in DEFENSE_MULTIPLIERS:
        defense_mult = pd.Series(1.0, index=port_ret.index)
        defense_mult[is_crisis_r] = mult
        final_scale = base_scale * defense_mult
        final_ret = (port_ret * final_scale.shift(1).fillna(1.0)).loc[sliced_idx]
        m, _ = metrics_from_returns(final_ret)
        print(f"[VIX방어배수={mult}]: CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}, calmar={m['calmar']}", flush=True)
        out[f"mult_{mult}"] = m

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    out["sp500_bh"] = bench.metrics
    return out


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2000_2012"] = run_period("약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_vix_defense.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
