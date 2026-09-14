"""세션13까지의 모든 검증은 미국 GICS 섹터 ETF라는 단일 유니버스, 두 개의 (겹치는) 시대에서만
이뤄졌다 — "미국 섹터의 특이성"이 아니라 진짜 일반적 원칙인지 확인된 적이 없다. 이 가설: 확정된
시스템(리스크패리티+국면별변동성타게팅+쏠림틸트+약세장 방어자산블렌드)을 국가별 ETF(미국 섹터가
아니라 나라별 지수) 유니버스에 그대로 적용한다 — 완전히 다른 자산군(국가지수), 완전히 다른 위기
역사(1997~98 아시아 외환위기 — 이 리포트가 한 번도 다룬 적 없는 사건)를 포함하는 1996년부터의
장기 구간에서 프레임워크 자체가 일반화되는지 확인한다.

유니버스: EWJ(일본) EWG(독일) EWU(영국) EWA(호주) EWC(캐나다) EWH(홍콩) EWS(싱가포르) EWQ(프랑스)
EWL(스위스) — 전부 1996-03-18부터 존재해 같은 시작점을 공유하는 선진국 위주 9개국."""
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

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
COUNTRY_ETFS = ["EWJ", "EWG", "EWU", "EWA", "EWC", "EWH", "EWS", "EWQ", "EWL"]
DEFENSIVE_ASSETS = ["TLT", "GLD"]
FULL_START, FULL_END = "1998-01-01", "2026-08-12"
ERA_SPLIT = "2012-12-31"


def regime_vol_scale(port_ret, regime):
    vol_target_by_regime = regime.map({"약세장": 12.0, "횡보장": 18.0, "광범위강세": 18.0, "쏠림강세": 18.0}).fillna(18.0)
    realized_vol = port_ret.rolling(5, min_periods=5).std() * np.sqrt(252) * 100
    tv = vol_target_by_regime.reindex(port_ret.index)
    scale = (tv / realized_vol).clip(upper=1.0).fillna(1.0)
    return scale


def metrics_for_slice(ret, idx):
    m, _ = metrics_from_returns(ret.loc[idx])
    return m


def main():
    fetch_start = (pd.Timestamp(FULL_START) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()

    country_hist = get_multiple_price_history(COUNTRY_ETFS, start=fetch_start, end=FULL_END, interval="1d")
    country_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in country_hist.items() if df is not None and not df.empty}
    country_df = pd.DataFrame(country_rets).dropna(how="all", axis=0)

    def_hist = get_multiple_price_history(DEFENSIVE_ASSETS, start=fetch_start, end=FULL_END, interval="1d")
    def_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in def_hist.items() if df is not None and not df.empty}
    defensive_df = pd.DataFrame(def_rets)

    full_idx = country_df.index[(country_df.index >= pd.Timestamp(FULL_START)) & (country_df.index <= pd.Timestamp(FULL_END))]
    print(f"전체 구간: {full_idx[0].date()} ~ {full_idx[-1].date()}, {len(full_idx)}거래일", flush=True)

    regime, leader, market_trend = classify_regimes(country_df)
    print("국면 분포(전체):", regime.loc[full_idx].value_counts().to_dict(), flush=True)
    print("쏠림강세 리더 국가 분포:", leader.loc[full_idx][regime.loc[full_idx] == "쏠림강세"].value_counts().to_dict(), flush=True)

    rp_equity = rolling_risk_parity_weights(country_df, lookback_days=252, rebal_freq="QS")

    combined_df = pd.concat([country_df, defensive_df], axis=1).dropna(how="any", axis=0)
    rp_extended = rolling_risk_parity_weights(combined_df, lookback_days=252, rebal_freq="QS")
    rp_extended = rp_extended.reindex(country_df.index).ffill().bfill()

    all_cols = list(country_df.columns) + DEFENSIVE_ASSETS
    system_w = pd.DataFrame(0.0, index=country_df.index, columns=all_cols)
    equal_w = pd.DataFrame(1.0 / len(COUNTRY_ETFS), index=country_df.index, columns=COUNTRY_ETFS)

    for dt in country_df.index:
        r = regime.loc[dt]
        if r == "약세장" and dt in rp_extended.index:
            system_w.loc[dt, rp_extended.columns] = rp_extended.loc[dt].values
        else:
            w = rp_equity.loc[dt].copy()
            if r == "쏠림강세":
                lead = leader.loc[dt]
                w[lead] = w[lead] + ALPHA_TILT
                w = w / w.sum()
            system_w.loc[dt, country_df.columns] = w.values

    wsum = system_w.loc[full_idx].sum(axis=1)
    max_dev = (wsum - 1.0).abs().max()
    print(f"[검증] 비중 합계 최대 이탈: {max_dev:.6f}", flush=True)
    if max_dev > 1e-6:
        raise ValueError(f"비중 정규화 버그: 최대 이탈 {max_dev}")

    all_rets = pd.concat([country_df, defensive_df], axis=1).fillna(0.0)
    system_executed = system_w.shift(1).fillna(0.0)
    system_ret = (all_rets * system_executed).sum(axis=1)
    system_scale = regime_vol_scale(system_ret, regime)
    system_final = system_ret * system_scale.shift(1).fillna(1.0)

    equal_executed = equal_w.shift(1).fillna(1.0 / len(COUNTRY_ETFS))
    equal_ret = (country_df * equal_executed).sum(axis=1)

    out = {}
    for era_label, era_idx in [
        ("1998_2012", full_idx[full_idx <= pd.Timestamp(ERA_SPLIT)]),
        ("2013_2026", full_idx[full_idx > pd.Timestamp(ERA_SPLIT)]),
        ("full_1998_2026", full_idx),
    ]:
        m_system = metrics_for_slice(system_final, era_idx)
        m_equal = metrics_for_slice(equal_ret, era_idx)
        bench = run_buy_and_hold("^GSPC", era_idx[0].date().isoformat(), era_idx[-1].date().isoformat())
        print(f"\n--- {era_label} ({era_idx[0].date()}~{era_idx[-1].date()}) ---", flush=True)
        print("[국가ETF 확정시스템]:", m_system, flush=True)
        print("[국가ETF 동일가중 매수보유]:", m_equal, flush=True)
        print("S&P500:", bench.metrics, flush=True)
        out[era_label] = {"system": m_system, "equal_weight_bh": m_equal, "sp500_bh": bench.metrics}

    out["regime_distribution"] = {str(k): int(v) for k, v in regime.loc[full_idx].value_counts().items()}
    out["narrow_bull_leader_distribution"] = {str(k): int(v) for k, v in leader.loc[full_idx][regime.loc[full_idx] == "쏠림강세"].value_counts().items()}

    with open(f"{OUT_DIR}/hypothesis_international_generalization.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
