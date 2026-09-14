"""H29 - 챔피언 리밸런싱 주기(현재 월간) 기댓값 재검증.

작업19가 고른 "월간 리밸런싱"은 그 이후 한 번도 재스윕된 적이 없다(H27이 룩백을 재검증한 것과
동일한 논리로, 이번엔 리밸런싱 빈도가 대상). champion_strategy.build_champion_weights는
_first_trading_day_of_month_mask로 리밸런싱일을 고정하므로, 여기서는 그 대신 "N거래일마다"
리밸런싱하는 커스텀 마스크로 교체해 주간(5)/격주(10)/월간(21)/6주(30)/분기(63) 5개 빈도를
스윕한다. 거래비용은 champion_strategy.compute_portfolio_returns의 기존 관례(왕복0.1% = 편도
5bp, 비중변화 절대값 기준)를 그대로 재사용하므로 빈도가 늘수록 회전율이 늘어 비용이 자동으로
더 많이 반영된다 - 별도 보정 불필요.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))
sys.path.insert(0, "/workspaces/Quant/analysis/2026-08-19_champion_beta_and_satellite_research")

import pandas as pd

from core.backtest_engine import calculate_metrics
from champion_strategy import (  # noqa: E402
    CHAMPION_UNIVERSE, MARKET_FILTER_TICKER, MARKET_FILTER_MA, MARKET_FILTER_SCALE_BELOW,
    MOMENTUM_WINDOW, TOP_N, WARMUP_DAYS,
    fetch_champion_histories, _closes_from_histories, compute_portfolio_returns,
)

OUT_DIR = Path(__file__).resolve().parent

WINDOWS = {
    "full_2019_2026": ("2019-08-12", "2026-08-19"),
    "gfc_2008": ("2007-10-01", "2009-06-30"),
    "covid_2020": ("2020-02-19", "2020-04-30"),
    "bear_2022": ("2022-01-01", "2022-12-31"),
    "selloff_2018": ("2018-09-01", "2019-01-15"),
    "correction_2015_2016": ("2015-08-01", "2016-02-15"),
}

# 리밸런싱 빈도(거래일 간격) - 주간/격주/월간(기존)/6주/분기
FREQUENCIES = {"weekly_5d": 5, "biweekly_10d": 10, "monthly_21d": 21, "sixweek_30d": 30, "quarterly_63d": 63}

SCENARIOS = {
    "base": {
        "full_2019_2026": 0.50, "gfc_2008": 0.03, "covid_2020": 0.04,
        "bear_2022": 0.10, "selloff_2018": 0.16, "correction_2015_2016": 0.17,
    },
    "calm_heavy": {
        "full_2019_2026": 0.65, "gfc_2008": 0.015, "covid_2020": 0.02,
        "bear_2022": 0.065, "selloff_2018": 0.12, "correction_2015_2016": 0.13,
    },
    "crisis_heavy": {
        "full_2019_2026": 0.35, "gfc_2008": 0.06, "covid_2020": 0.07,
        "bear_2022": 0.14, "selloff_2018": 0.19, "correction_2015_2016": 0.19,
    },
}


def normalize(weights: dict) -> dict:
    s = sum(weights.values())
    return {k: v / s for k, v in weights.items()}


def n_day_rebal_mask(index: pd.DatetimeIndex, n: int) -> pd.Series:
    """인덱스 0번째 거래일부터 n거래일 간격으로 True (월간 기존 관례의 "월별 첫 거래일" 대신
    "N거래일마다"로 일반화한 버전 - 주간처럼 달력 경계가 없는 빈도를 다루기 위한 자연스러운
    확장). 첫날은 항상 True."""
    mask = pd.Series(False, index=index)
    mask.iloc[0] = True
    mask.iloc[n::n] = True
    return mask


def build_weights_with_frequency(
    closes: pd.DataFrame, market_close: pd.Series, rebal_days: int,
) -> pd.DataFrame:
    """champion_strategy.build_champion_weights와 동일한 로직, 리밸런싱 마스크만 교체."""
    momentum = closes.pct_change(MOMENTUM_WINDOW)
    is_rebal = n_day_rebal_mask(closes.index, rebal_days)
    sma200 = market_close.rolling(MARKET_FILTER_MA, min_periods=MARKET_FILTER_MA).mean()

    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_weights = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]
            mom = momentum.loc[signal_date]
            candidates = mom[mom > 0].sort_values(ascending=False)
            picks = candidates.index[:TOP_N]
            w = pd.Series(0.0, index=closes.columns)
            if len(picks) > 0:
                w[picks] = 1.0 / TOP_N
            if signal_date in sma200.index and not pd.isna(sma200.loc[signal_date]):
                if market_close.loc[signal_date] < sma200.loc[signal_date]:
                    w = w * MARKET_FILTER_SCALE_BELOW
            last_weights = w
        weights.iloc[i] = last_weights.values
    return weights


def run_champion_with_frequency(start: str, end: str, rebal_days: int) -> dict:
    tickers = list(CHAMPION_UNIVERSE)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = fetch_champion_histories(fetch_start, end, tickers)
    closes_all = _closes_from_histories(histories, tickers + [MARKET_FILTER_TICKER])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    market_close = closes_all[MARKET_FILTER_TICKER]

    weights_full = build_weights_with_frequency(closes, market_close, rebal_days)

    sliced_idx = closes.index[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
    closes_sliced = closes.loc[sliced_idx]
    weights_sliced = weights_full.loc[sliced_idx]

    result = compute_portfolio_returns(closes_sliced, weights_sliced)
    metrics = calculate_metrics(result["equity_net"], [], sliced_idx[0], sliced_idx[-1])
    avg_annual_turnover = result["turnover"].mean() * 252
    return {"sharpe": metrics["sharpe"], "cagr": metrics["cagr"], "mdd": metrics["mdd"],
            "avg_annual_turnover_pct": round(float(avg_annual_turnover) * 100, 1)}


def main():
    lookup = {ep: {} for ep in WINDOWS}
    t0 = time.time()
    for freq_name, rebal_days in FREQUENCIES.items():
        for ep, (start, end) in WINDOWS.items():
            lookup[ep][freq_name] = run_champion_with_frequency(start, end, rebal_days)
        print(f"[h29] {freq_name} ({rebal_days}d) done at t={time.time()-t0:.1f}s", flush=True)

    out = {"episode_windows": {k: list(v) for k, v in WINDOWS.items()}, "frequencies": FREQUENCIES,
           "raw_lookup_table": lookup, "scenarios": {}}

    for scen_name, weights in SCENARIOS.items():
        w = normalize(weights)
        ev = {}
        for freq_name in FREQUENCIES:
            sharpe_ev, cagr_ev = 0.0, 0.0
            for ep, wt in w.items():
                m = lookup[ep][freq_name]
                sharpe_ev += wt * m["sharpe"]
                cagr_ev += wt * m["cagr"]
            crisis_mdds = [lookup[ep][freq_name]["mdd"] for ep in w if ep != "full_2019_2026"]
            ev[freq_name] = {
                "rebal_days": FREQUENCIES[freq_name],
                "expected_sharpe": round(sharpe_ev, 4),
                "expected_cagr_pct": round(cagr_ev, 4),
                "mdd_worst_case": round(min(crisis_mdds), 2),
                "avg_annual_turnover_pct_full_period": lookup["full_2019_2026"][freq_name]["avg_annual_turnover_pct"],
            }
        ranking = sorted(ev.items(), key=lambda kv: -kv[1]["expected_sharpe"])
        out["scenarios"][scen_name] = {
            "weights_normalized": w, "expected_value": ev,
            "ranking_by_expected_sharpe": [(k, v["expected_sharpe"]) for k, v in ranking],
        }

    (OUT_DIR / "h29_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[h29] saved h29_results.json")
    for scen_name in SCENARIOS:
        print(f"--- {scen_name} ranking ---")
        for k, v in out["scenarios"][scen_name]["ranking_by_expected_sharpe"]:
            print(f"  {k}: E[sharpe]={v:.4f}")


if __name__ == "__main__":
    main()
