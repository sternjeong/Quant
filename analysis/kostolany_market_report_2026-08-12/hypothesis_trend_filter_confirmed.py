"""hypothesis_absolute_trend_filter.py 후속: 200일선 단독 신호는 강세장(2015~26)에서 손해,
약세장 포함 구간(2000~12)에서 이득 — 정반대로 갈렸다. 강세장 손실의 원인은 십중팔구 '일시적
눌림목'에서도 방어모드로 들어가는 오탐(false positive)이다. 이미 있는 국면분류의 '약세장'
판정(트레일링 12개월 수익률 < -5%)과 200일선 이탈을 AND로 묶으면(둘 다 동의해야 방어 모드) 강세장의
오탐을 걸러내면서 약세장의 방어효과는 유지되는지 확인한다 — 사후에 짜맞춘 규칙이 아니라 이미
확정된 두 신호(추세강도 기반 국면분류, 가격레벨 기반 200일선)의 논리적 AND일 뿐이다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import numpy as np
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from portfolio_vol_targeting import metrics_from_returns
from multi_regime_multi_strategy import SECTOR_ETFS_MODERN, SECTOR_ETFS_LEGACY, WARMUP_DAYS, MOMENTUM_WINDOW
from hypothesis_absolute_trend_filter import build_confirmed_system_return, regime_vol_scale, TREND_MA_DAYS

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
DEFENSE_MULTIPLIERS = [1.0, 0.5, 0.25]


def run_period(label, start, end, sector_etfs):
    print(f"\n{'='*20} {label} {'='*20}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()

    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(start)) & (etf_df.index <= pd.Timestamp(end))]

    spy_hist = get_multiple_price_history(["SPY"], start=fetch_start, end=end, interval="1d")["SPY"]
    spy_close = spy_hist["Close"].reindex(etf_df.index).ffill()
    spy_ma200 = spy_close.rolling(TREND_MA_DAYS, min_periods=TREND_MA_DAYS).mean()
    is_below_ma = (spy_close < spy_ma200)

    port_ret, regime = build_confirmed_system_return(etf_df, sliced_idx)
    base_scale = regime_vol_scale(port_ret, regime, sliced_idx)

    is_bear_regime = (regime == "약세장").reindex(port_ret.index).fillna(False)
    is_below_ma_r = is_below_ma.reindex(port_ret.index).fillna(False)
    confirmed_trigger = is_bear_regime & is_below_ma_r
    trig_pct = round(100 * confirmed_trigger.loc[sliced_idx].mean(), 1)
    standalone_pct = round(100 * is_below_ma_r.loc[sliced_idx].mean(), 1)
    print(f"200일선 이탈 단독: {standalone_pct}% / 약세장+200일선 동시확인: {trig_pct}%", flush=True)

    out = {"standalone_pct": standalone_pct, "confirmed_pct": trig_pct}
    for mult in DEFENSE_MULTIPLIERS:
        defense_mult = pd.Series(1.0, index=port_ret.index)
        defense_mult[confirmed_trigger] = mult
        final_scale = base_scale * defense_mult
        final_ret = (port_ret * final_scale.shift(1).fillna(1.0)).loc[sliced_idx]
        m, _ = metrics_from_returns(final_ret)
        print(f"[확인방어배수={mult}]: CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}, calmar={m['calmar']}", flush=True)
        out[f"mult_{mult}"] = m

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    out["sp500_bh"] = bench.metrics
    return out


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2000_2012"] = run_period("약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_trend_filter_confirmed.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
