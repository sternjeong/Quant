"""세션15는 "국가ETF에서는 미국섹터의 틸트가 안 통한다"를 확인했다. 그렇다면 반대로: 미국
GICS섹터가 아니라 미국 팩터ETF(가치/성장/퀄리티/모멘텀/저변동성)로 유니버스를 바꿔도 프레임워크가
여전히 통하는가? 통한다면 "미국 주식시장 자체의 구조(이 시기 강세장)"가 진짜 원동력이라는 뜻이고,
안 통한다면 "GICS 섹터라는 특정 경제적 분할" 자체에 뭔가 있다는 뜻이다.

유니버스: IWD(가치) IWF(성장) SPHQ(퀄리티) MTUM(모멘텀) USMV(저변동성) — MTUM(2013-04)이 가장
늦게 상장해 그 이후 구간만 검증 가능(세션14/15가 쓴 2015~2026과 거의 겹치는 기간)."""
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
from hypothesis_defensive_assets_bear import DEFENSIVE_ASSETS, regime_vol_scale

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
FACTOR_ETFS = ["IWD", "IWF", "SPHQ", "MTUM", "USMV"]
START, END = "2014-06-01", "2026-08-12"


def build_system(factor_df, defensive_df, use_tilt=True):
    regime, leader, market_trend = classify_regimes(factor_df)
    rp_equity = rolling_risk_parity_weights(factor_df, lookback_days=252, rebal_freq="QS")

    combined_df = pd.concat([factor_df, defensive_df], axis=1).dropna(how="any", axis=0)
    rp_extended = rolling_risk_parity_weights(combined_df, lookback_days=252, rebal_freq="QS")
    rp_extended = rp_extended.reindex(factor_df.index).ffill().bfill()

    all_cols = list(factor_df.columns) + DEFENSIVE_ASSETS
    w = pd.DataFrame(0.0, index=factor_df.index, columns=all_cols)
    for dt in factor_df.index:
        r = regime.loc[dt]
        if r == "약세장" and dt in rp_extended.index:
            w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
        else:
            base = rp_equity.loc[dt].copy()
            if r == "쏠림강세" and use_tilt:
                lead = leader.loc[dt]
                base[lead] = base[lead] + ALPHA_TILT
                base = base / base.sum()
            w.loc[dt, factor_df.columns] = base.values
    return w, regime


def main():
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    print(f"구간: {START} ~ {END}", flush=True)

    factor_hist = get_multiple_price_history(FACTOR_ETFS, start=fetch_start, end=END, interval="1d")
    factor_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in factor_hist.items() if df is not None and not df.empty}
    factor_df = pd.DataFrame(factor_rets).dropna(how="all", axis=0)

    def_hist = get_multiple_price_history(DEFENSIVE_ASSETS, start=fetch_start, end=END, interval="1d")
    def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
    defensive_df = pd.DataFrame(def_rets)

    sliced_idx = factor_df.index[(factor_df.index >= pd.Timestamp(START)) & (factor_df.index <= pd.Timestamp(END))]

    regime, leader, market_trend = classify_regimes(factor_df)
    print("국면 분포:", regime.loc[sliced_idx].value_counts().to_dict(), flush=True)
    print("쏠림강세 리더 팩터 분포:", leader.loc[sliced_idx][regime.loc[sliced_idx] == "쏠림강세"].value_counts().to_dict(), flush=True)

    all_rets = pd.concat([factor_df, defensive_df], axis=1).fillna(0.0)
    out = {}
    for name, use_tilt in [("with_tilt", True), ("no_tilt", False)]:
        w, reg = build_system(factor_df, defensive_df, use_tilt=use_tilt)
        wsum = w.loc[sliced_idx].sum(axis=1)
        max_dev = (wsum - 1.0).abs().max()
        if max_dev > 1e-6:
            raise ValueError(f"{name} 비중 정규화 버그: 최대 이탈 {max_dev}")
        executed = w.loc[sliced_idx].shift(1).fillna(0.0)
        ret = (all_rets.loc[sliced_idx] * executed).sum(axis=1)
        scale = regime_vol_scale(ret, reg.loc[sliced_idx])
        final_ret = ret * scale.shift(1).fillna(1.0)
        m, _ = metrics_from_returns(final_ret)
        print(f"[{name}]: CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}, calmar={m['calmar']}", flush=True)
        out[name] = m

    equal_w = pd.DataFrame(1.0 / len(FACTOR_ETFS), index=factor_df.index, columns=FACTOR_ETFS)
    equal_ret = (factor_df.loc[sliced_idx] * equal_w.loc[sliced_idx].shift(1).fillna(1.0 / len(FACTOR_ETFS))).sum(axis=1)
    m_equal, _ = metrics_from_returns(equal_ret)
    print("[동일가중 매수보유]:", m_equal, flush=True)
    out["equal_weight_bh"] = m_equal

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    out["sp500_bh"] = bench.metrics
    out["period"] = {"start": str(sliced_idx[0].date()), "end": str(sliced_idx[-1].date())}

    with open(f"{OUT_DIR}/hypothesis_us_factor_universe.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
