"""사용자 지적: 시대를 관통하는 "하나의" 시스템보다, 국면마다 진짜 다른 전략(방어자산 포함,
추세이탈시 실제로 이탈)을 쓰는 게 맞다. 지금까지 확정한 시스템은 약세장에서도 "섹터 ETF 안에서
변동성타게팅만 타이트하게" 했을 뿐 — 실제로 주식을 떠난 적이 없다. 이건 08장에서 전혀 시도하지
않은 새 알파 소스다: 시장(SPY) 가격이 200일 이동평균 아래로 떨어지면 그 자체를 별도 방어 신호로
써서 노출을 실제로 줄인다(Faber 2007 절대추세필터, 확정 시스템의 "상대적 쏠림" z-점수 신호와는
완전히 다른 신호 — 가격 레벨 기반).

설계: 확정 시스템(국면분류+리스크패리티+쏠림틸트+국면별 변동성타게팅)의 최종 스케일에, SPY가
200일 이평선 아래인 날에는 추가로 방어배수(0.5)를 곱한다. 사후 스윕이 아님을 보이기 위해
0.25/0.5/0.75 세 배수 모두 테스트."""
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
DEFENSE_MULTIPLIERS = [1.0, 0.75, 0.5, 0.25]  # 1.0 = 필터 없음(기존 확정 시스템)
TREND_MA_DAYS = 200


def build_confirmed_system_return(etf_df, sliced_idx):
    """확정 시스템: 국면분류 + 리스크패리티 + 쏠림틸트, 국면별 변동성타게팅 적용 전 '원시' 포트수익률."""
    regime, leader, market_trend = classify_regimes(etf_df)
    rp_weights = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")

    tilted = rp_weights.copy()
    for dt in etf_df.index:
        if regime.loc[dt] == "쏠림강세":
            w = rp_weights.loc[dt].copy()
            w[leader.loc[dt]] = w[leader.loc[dt]] + ALPHA_TILT
            tilted.loc[dt] = w / w.sum()

    executed = tilted.shift(1).fillna(1.0 / tilted.shape[1])
    port_ret = (etf_df * executed).sum(axis=1)
    return port_ret, regime


def regime_vol_scale(port_ret, regime, sliced_idx):
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

    spy_hist = get_multiple_price_history(["SPY"], start=fetch_start, end=end, interval="1d")["SPY"]
    spy_close = spy_hist["Close"].reindex(etf_df.index).ffill()
    spy_ma200 = spy_close.rolling(TREND_MA_DAYS, min_periods=TREND_MA_DAYS).mean()
    is_below_ma = (spy_close < spy_ma200)
    below_pct = round(100 * is_below_ma.loc[sliced_idx].mean(), 1)
    print(f"SPY 200일선 아래 비율: {below_pct}%", flush=True)

    port_ret, regime = build_confirmed_system_return(etf_df, sliced_idx)
    base_scale = regime_vol_scale(port_ret, regime, sliced_idx)

    out = {"below_ma_pct": below_pct}
    for mult in DEFENSE_MULTIPLIERS:
        defense_mult = pd.Series(1.0, index=port_ret.index)
        defense_mult[is_below_ma.reindex(port_ret.index).fillna(False)] = mult
        final_scale = base_scale * defense_mult
        final_ret = (port_ret * final_scale.shift(1).fillna(1.0)).loc[sliced_idx]
        m, _ = metrics_from_returns(final_ret)
        print(f"[방어배수={mult}]: CAGR={m['cagr']}, MDD={m['mdd']}, 샤프={m['sharpe']}, calmar={m['calmar']}", flush=True)
        out[f"mult_{mult}"] = m

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    out["sp500_bh"] = bench.metrics
    return out


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2000_2012"] = run_period("약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_absolute_trend_filter.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
