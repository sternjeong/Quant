"""H27 - 챔피언 모멘텀 랭킹 룩백기간(현재 12개월) 기댓값 재검증.

작업19가 고른 12개월(12-1 모멘텀 팩터 관행) 룩백을 재스윕한 적이 없다. 이 스크립트는 3/6/9/12/15/18
개월 룩백으로 17자산 챔피언(기존 이진 시장필터 포함, 필터 자체는 라운드12 H25 몫이라 건드리지 않음)을
H26/H22와 동일한 6개 창에서 백테스트하고, 동일한 기저확률 가중 시나리오로 기댓값 샤프/CAGR을 계산한다.

champion_strategy.py의 build_champion_weights/compute_portfolio_returns를 momentum_window 파라미터를
바꿔가며 직접 호출한다(run_champion은 momentum_window를 노출하지 않으므로 그 내부 로직을 그대로 재사용).
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
    CHAMPION_UNIVERSE, MARKET_FILTER_TICKER, fetch_champion_histories,
    _closes_from_histories, build_champion_weights, compute_portfolio_returns,
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

LOOKBACK_MONTHS = [3, 6, 9, 12, 15, 18]
TRADING_DAYS_PER_MONTH = 21
MAX_LOOKBACK_DAYS = max(LOOKBACK_MONTHS) * TRADING_DAYS_PER_MONTH
EXTRA_WARMUP_DAYS = MAX_LOOKBACK_DAYS + 60  # 여유

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


def run_champion_with_lookback(start: str, end: str, momentum_window_days: int) -> dict:
    """champion_strategy 빌딩블록을 momentum_window만 바꿔 직접 호출."""
    tickers = list(CHAMPION_UNIVERSE)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=EXTRA_WARMUP_DAYS * 1.6)).date().isoformat()
    histories = fetch_champion_histories(fetch_start, end, tickers)
    closes_all = _closes_from_histories(histories, tickers + [MARKET_FILTER_TICKER])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    market_close = closes_all[MARKET_FILTER_TICKER]

    weights_full = build_champion_weights(closes, market_close, momentum_window=momentum_window_days)

    sliced_idx = closes.index[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
    closes_sliced = closes.loc[sliced_idx]
    weights_sliced = weights_full.loc[sliced_idx]

    result = compute_portfolio_returns(closes_sliced, weights_sliced)
    metrics = calculate_metrics(result["equity_net"], [], sliced_idx[0], sliced_idx[-1])
    return metrics


def main():
    lookup = {ep: {} for ep in WINDOWS}
    t0 = time.time()
    for months in LOOKBACK_MONTHS:
        window_days = months * TRADING_DAYS_PER_MONTH
        for ep, (start, end) in WINDOWS.items():
            m = run_champion_with_lookback(start, end, window_days)
            lookup[ep][str(months)] = {"sharpe": m["sharpe"], "cagr": m["cagr"], "mdd": m["mdd"]}
        print(f"[h27] lookback={months}m done at t={time.time()-t0:.1f}s")

    out = {"episode_windows": {k: list(v) for k, v in WINDOWS.items()}, "lookback_months": LOOKBACK_MONTHS,
           "raw_lookup_table": lookup, "scenarios": {}}

    for scen_name, weights in SCENARIOS.items():
        w = normalize(weights)
        ev = {}
        for months in LOOKBACK_MONTHS:
            key = str(months)
            sharpe_ev, cagr_ev = 0.0, 0.0
            for ep, wt in w.items():
                m = lookup[ep][key]
                sharpe_ev += wt * m["sharpe"]
                cagr_ev += wt * m["cagr"]
            crisis_mdds = [lookup[ep][key]["mdd"] for ep in w if ep != "full_2019_2026"]
            ev[key] = {"months": months, "expected_sharpe": round(sharpe_ev, 4),
                       "expected_cagr_pct": round(cagr_ev, 4), "mdd_worst_case": round(min(crisis_mdds), 2)}
        ranking = sorted(ev.items(), key=lambda kv: -kv[1]["expected_sharpe"])
        out["scenarios"][scen_name] = {
            "weights_normalized": w, "expected_value": ev,
            "ranking_by_expected_sharpe": [(k, v["expected_sharpe"]) for k, v in ranking],
        }

    (OUT_DIR / "h27_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[h27] saved h27_results.json")
    for scen_name in SCENARIOS:
        print(f"--- {scen_name} ranking ---")
        for k, v in out["scenarios"][scen_name]["ranking_by_expected_sharpe"]:
            print(f"  lookback={k}m: E[sharpe]={v:.4f}")


if __name__ == "__main__":
    main()
