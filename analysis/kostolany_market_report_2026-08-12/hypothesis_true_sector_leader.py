"""직전 대화에서 지적된 방법론 허점을 바로잡은 재검증: "대장주" 틸트는 유니버스 전체에서 무작위로
모멘텀 상위 종목을 고른 게 아니라, 국면 감지로 식별된 "그 쏠림 섹터 안에서" 그 시점 모멘텀이 가장
센 종목(들)이어야 한다. yfinance 실제 GICS 섹터로 매핑한 종목 목록(fetch_sector_mapping.py 결과)을
써서 이번에는 제대로 검증한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pickle
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
STOCK_TOP_K_IN_SECTOR = 1  # 그 섹터 "대장주" 1종목(가장 문자 그대로의 해석)


def run_period(label, start, end, sector_etfs, unbiased_pkl, sector_map_key):
    print(f"\n{'='*20} {label} ({start}~{end}) {'='*20}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()

    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)

    with open(unbiased_pkl, "rb") as f:
        meta = pickle.load(f)
    ok_tickers = meta["ok_tickers"]
    with open(f"{OUT_DIR}/sector_mapping.json", encoding="utf-8") as f:
        sector_map = json.load(f)[sector_map_key]

    stock_hist = get_multiple_price_history(ok_tickers, start=fetch_start, end=end, interval="1d")
    stock_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in stock_hist.items()
                  if df is not None and not df.empty and len(df) > WARMUP_DAYS}
    stock_df = pd.DataFrame(stock_rets).reindex(etf_df.index)

    # 섹터ETF -> 그 섹터에 속한(실제 GICS 매핑) 종목 리스트
    etf_to_stocks: dict[str, list[str]] = {etf: [] for etf in sector_etfs}
    for ticker, info in sector_map.items():
        etf = info.get("etf")
        if etf in etf_to_stocks and ticker in stock_df.columns:
            etf_to_stocks[etf].append(ticker)
    print("섹터ETF -> 종목 수:", {k: len(v) for k, v in etf_to_stocks.items()}, flush=True)

    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(start)) & (etf_df.index <= pd.Timestamp(end))]

    # --- 국면 판정(기존과 동일) ---
    trailing_mom_etf = etf_df.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: (1 + x).prod() - 1, raw=True)
    market_trend = trailing_mom_etf.mean(axis=1) * 100
    cross_mean = trailing_mom_etf.mean(axis=1)
    cross_std = trailing_mom_etf.std(axis=1)
    z_scores = trailing_mom_etf.sub(cross_mean, axis=0).div(cross_std.replace(0, np.nan), axis=0)
    max_z = z_scores.max(axis=1)
    leader_etf = z_scores.idxmax(axis=1)
    is_narrow_bull = (market_trend > BULL_TREND_PCT) & (max_z >= Z_THRESHOLD)

    # --- 개별종목 트레일링 모멘텀(룩어헤드 없음) ---
    trailing_mom_stock = stock_df.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: (1 + x).prod() - 1, raw=True)

    rp_weights = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")

    all_assets = list(etf_df.columns) + list(stock_df.columns)
    baseline_w = pd.DataFrame(0.0, index=etf_df.index, columns=all_assets)
    etf_tilt_w = pd.DataFrame(0.0, index=etf_df.index, columns=all_assets)
    true_leader_w = pd.DataFrame(0.0, index=etf_df.index, columns=all_assets)

    fallback_count = 0
    for dt in etf_df.index:
        base = rp_weights.loc[dt]
        baseline_w.loc[dt, etf_df.columns] = base.values

        if is_narrow_bull.loc[dt]:
            lead_etf = leader_etf.loc[dt]
            # etf_tilt: 쏠림 섹터 ETF 자체에 추가비중(이전과 동일, 대조군)
            w1 = base.copy()
            w1[lead_etf] = w1[lead_etf] + ALPHA_TILT
            w1 = w1 / w1.sum()  # 정규화된 값을 w1 자체에 반영 — 아래 fallback 분기에서도 이 값을 재사용하므로 중요
            etf_tilt_w.loc[dt, etf_df.columns] = w1.values

            # true_leader: 그 섹터 "안에서" 트레일링 모멘텀 1위 종목에 추가비중
            candidates = etf_to_stocks.get(lead_etf, [])
            mom_today = trailing_mom_stock.loc[dt, candidates].dropna() if candidates else pd.Series(dtype=float)
            positive = mom_today[mom_today > 0].sort_values(ascending=False)
            if len(positive) > 0:
                top_stock = positive.index[0]
                w2 = base * (1 - ALPHA_TILT)
                true_leader_w.loc[dt, etf_df.columns] = w2.values
                true_leader_w.loc[dt, top_stock] = ALPHA_TILT
            else:
                # 그 섹터에 후보 종목이 없거나 전부 모멘텀<=0이면 ETF 자체에 배정(대조군과 동일 처리)
                fallback_count += 1
                true_leader_w.loc[dt, etf_df.columns] = w1.values
        else:
            etf_tilt_w.loc[dt, etf_df.columns] = base.values
            true_leader_w.loc[dt, etf_df.columns] = base.values

    print(f"'섹터 내 후보 없음' fallback 발생일: {fallback_count}", flush=True)

    full_rets = pd.concat([etf_df, stock_df], axis=1).fillna(0.0)

    def eval_variant(w_full, name):
        wsum = w_full.loc[sliced_idx].sum(axis=1)
        max_dev = (wsum - 1.0).abs().max()
        print(f"[검증] {name} 비중 합계 이탈: {max_dev:.6f}", flush=True)
        assert max_dev < 1e-6, f"{name} 정규화 버그"
        w = w_full.loc[sliced_idx]
        executed = w.shift(1).fillna(0.0)
        ret = (full_rets.loc[sliced_idx] * executed).sum(axis=1)
        m_raw, _ = metrics_from_returns(ret)
        scale = vol_target_scale(ret, 18.0, 1.0, window=5)
        m_final, eq = metrics_from_returns(ret * scale.shift(1).fillna(1.0))
        print(f"[{name}] 오버레이 없음:", m_raw, flush=True)
        print(f"[{name}] 변동성타게팅 적용:", m_final, flush=True)
        return m_raw, m_final, eq

    results = {}
    curves = {}
    for w_full, name in [(baseline_w, "baseline"), (etf_tilt_w, "etf_tilt"), (true_leader_w, "true_sector_leader")]:
        m_raw, m_final, eq = eval_variant(w_full, name)
        results[name] = {"no_overlay": m_raw, "final": m_final}
        curves[name] = eq

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)

    return {"results": results, "sp500_bh": bench.metrics, "fallback_days": fallback_count,
            "narrow_bull_days": int(is_narrow_bull.loc[sliced_idx].sum())}, curves


def main():
    out = {}
    curves_all = {}
    out["2015_2026"], curves_all["2015_2026"] = run_period(
        "강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN,
        f"{OUT_DIR}/momentum_rotation_unbiased_curves.pkl", "bull_2015",
    )
    out["2000_2012"], curves_all["2000_2012"] = run_period(
        "약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY,
        f"{OUT_DIR}/bear_market_robustness_curves.pkl", "bear_2000",
    )
    with open(f"{OUT_DIR}/hypothesis_true_sector_leader.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(f"{OUT_DIR}/hypothesis_true_sector_leader_curves.pkl", "wb") as f:
        pickle.dump(curves_all, f)
    print("\nDONE")


if __name__ == "__main__":
    main()
