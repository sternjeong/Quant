"""지금까지 전 구간이 무비용(수수료·스프레드 0) 가정이었다. 변동성타게팅이 실현변동성을 매일
(룩백 5일) 재계산해 노출 비중을 스케일링하므로, 겉보기보다 회전율(turnover)이 클 수 있다 —
직접 측정하고, 몇 가지 비용 수준에서 순수익이 얼마나 깎이는지, 그리고 재조정 주기를 늦추면
비용 대비 효과가 얼마나 개선되는지 확인한다.
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
from multi_regime_multi_strategy import (
    SECTOR_ETFS_MODERN, SECTOR_ETFS_LEGACY, WARMUP_DAYS, MOMENTUM_WINDOW,
    BULL_TREND_PCT, Z_THRESHOLD, ALPHA_TILT,
)

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
COST_BPS_LIST = [0.0, 2.0, 5.0, 10.0, 20.0]  # 왕복이 아니라 회전율(턴오버) 1단위당 비용(bp)


def vol_target_scale_freq(returns: pd.Series, target_vol: float, cap: float, window: int, reeval_freq: str):
    """vol_target_scale과 동일하되, reeval_freq(예: 'W'=주간, 'M'=월간)에서만 스케일을 다시
    계산하고 그 사이엔 직전 값을 유지한다 — 재조정 빈도를 낮춰 턴오버를 줄이는 실험용."""
    raw_scale = vol_target_scale(returns, target_vol, cap, window=window)
    if reeval_freq == "D":
        return raw_scale
    resampled = raw_scale.resample(reeval_freq).first()
    stepped = resampled.reindex(returns.index, method="ffill")
    return stepped


def build_weights(etf_df, sliced_idx):
    trailing_mom = etf_df.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(lambda x: (1 + x).prod() - 1, raw=True)
    market_trend = trailing_mom.mean(axis=1) * 100
    cross_mean = trailing_mom.mean(axis=1)
    cross_std = trailing_mom.std(axis=1)
    z_scores = trailing_mom.sub(cross_mean, axis=0).div(cross_std.replace(0, np.nan), axis=0)
    max_z = z_scores.max(axis=1)
    leader = z_scores.idxmax(axis=1)
    is_narrow_bull = (market_trend > BULL_TREND_PCT) & (max_z >= Z_THRESHOLD)

    rp_weights = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")
    tilted = rp_weights.copy()
    for dt in etf_df.index:
        if is_narrow_bull.loc[dt]:
            w = rp_weights.loc[dt].copy()
            lead = leader.loc[dt]
            w[lead] = w[lead] + ALPHA_TILT
            tilted.loc[dt] = w / w.sum()
    return tilted.loc[sliced_idx]


def eval_with_costs(etf_returns: pd.DataFrame, sector_weights: pd.DataFrame, target_vol: float, window: int, reeval_freq: str, cost_bps_list):
    """sector_weights(합계 1, 섹터 간 비중) x vol-target 스케일(현금 비중 조절)을 곱해 최종 일별
    포지션(섹터별 실제 노출 비중, 현금 비중은 1-sum)을 구하고, 그 노출 비중의 일별 변화량 합을
    턴오버로 계산해 비용을 차감한다."""
    executed_sector_w = sector_weights.shift(1).fillna(1.0 / sector_weights.shape[1])
    port_ret_no_scale = (etf_returns * executed_sector_w).sum(axis=1)

    scale = vol_target_scale_freq(port_ret_no_scale, target_vol, 1.0, window, reeval_freq)
    executed_scale = scale.shift(1).fillna(1.0)

    # 최종 노출 비중(섹터별) = 섹터비중 x 스케일. 현금비중 = 1 - 스케일.
    final_weights = executed_sector_w.mul(executed_scale, axis=0)
    final_weights["CASH"] = 1.0 - executed_scale

    turnover = final_weights.diff().abs().sum(axis=1).fillna(0.0)
    avg_daily_turnover_pct = round(float(turnover.mean() * 100), 3)

    port_ret = port_ret_no_scale * executed_scale

    results = {}
    for cost_bps in cost_bps_list:
        cost_ret = port_ret - turnover * (cost_bps / 10000.0)
        m, _ = metrics_from_returns(cost_ret)
        results[f"cost_{cost_bps}bps"] = m
    return results, avg_daily_turnover_pct


def run_period(label, start, end, sector_etfs):
    print(f"\n{'='*20} {label} {'='*20}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(start)) & (etf_df.index <= pd.Timestamp(end))]

    tilted_w = build_weights(etf_df, sliced_idx)

    out = {}
    for reeval_freq, freq_label in [("D", "매일"), ("W", "매주"), ("MS", "매월")]:
        res, turnover = eval_with_costs(etf_df.loc[sliced_idx], tilted_w, 18.0, 5, reeval_freq, COST_BPS_LIST)
        print(f"[{freq_label} 재조정] 일평균 턴오버 {turnover}%", flush=True)
        for k, v in res.items():
            print(f"   {k}: CAGR={v['cagr']}, MDD={v['mdd']}, 샤프={v['sharpe']}", flush=True)
        out[reeval_freq] = {"label": freq_label, "avg_daily_turnover_pct": turnover, "results": res}

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    out["sp500_bh"] = bench.metrics
    return out


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2000_2012"] = run_period("약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_transaction_costs.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
