"""H26 - 전체 시스템(코어+새틀라이트) vs 코어 단독 vs 순수 SPY 매수보유, 기댓값 정면비교.

13라운드에 걸쳐 로테이션 챔피언 + 새틀라이트 시스템을 다듬어왔지만, 가장 단순한 대안(SPY 매수보유)과
정면으로 기댓값을 비교한 적이 없었다. 이 스크립트는:
  (a) 순수 SPY 매수보유
  (b) 17자산 챔피언 코어 단독 (기존 이진 시장필터 포함, 필터 자체는 건드리지 않음 - 그건 라운드12 H25 몫)
  (c) 코어 + 15% 정적 새틀라이트 (H22가 찾은 기댓값 최적 구성 "case_a_static_satellite")
를 H22와 동일한 6개 창(전체기간 2019-2026 + 2008/2022/2020/2018/2015-16 위기창)에서 비교한다.

(b)와 (c)는 이미 존재하는
analysis/2026-08-23_expected_value_reframing_and_continuous_exposure/report_data.json의
h22.raw_lookup_table에 정확히 같은 창 정의로 이미 계산되어 있으므로 재백테스트하지 않고 그대로
재사용한다(오케스트레이터 지시사항 - "if not already cleanly available... saving you a full
rebacktest"). (a) SPY 매수보유만 새로 백테스트한다.

H22의 정확히 동일한 기저확률 가중 시나리오(base/calm_heavy/crisis_heavy)를 재사용해 기대 샤프·CAGR을
계산한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))

import pandas as pd

from core.backtest_engine import calculate_metrics
from core.market_data import get_price_history

MAIN_CHECKOUT = "/workspaces/Quant"
H22_REPORT_DATA = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_expected_value_reframing_and_continuous_exposure/report_data.json"
OUT_DIR = Path(__file__).resolve().parent

# 정확히 h23_results.json/h22 raw_lookup_table이 쓴 창 정의 (meta에서 확인).
WINDOWS = {
    "full_2019_2026": ("2019-08-12", "2026-08-19"),
    "gfc_2008": ("2007-10-01", "2009-06-30"),
    "covid_2020": ("2020-02-19", "2020-04-30"),
    "bear_2022": ("2022-01-01", "2022-12-31"),
    "selloff_2018": ("2018-09-01", "2019-01-15"),
    "correction_2015_2016": ("2015-08-01", "2016-02-15"),
}

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

CONFIGS = ["spy_buyhold", "core_alone", "core_plus_satellite"]


def normalize(weights: dict) -> dict:
    s = sum(weights.values())
    return {k: v / s for k, v in weights.items()}


def run_spy_buyhold() -> dict:
    """모든 창을 커버하는 SPY 가격이력을 한번에 받아 각 창을 슬라이스한다."""
    earliest = min(pd.Timestamp(s) for s, _ in WINDOWS.values())
    latest = max(pd.Timestamp(e) for _, e in WINDOWS.values())
    hist = get_price_history("SPY", start=(earliest - pd.DateOffset(days=10)).date().isoformat(),
                              end=latest.date().isoformat(), interval="1d")
    close = hist["Close"].ffill()

    out = {}
    for ep, (start, end) in WINDOWS.items():
        idx = close.index[(close.index >= pd.Timestamp(start)) & (close.index <= pd.Timestamp(end))]
        sliced = close.loc[idx]
        equity = sliced / sliced.iloc[0] * 100.0
        metrics = calculate_metrics(equity, [], idx[0], idx[-1])
        out[ep] = {"sharpe": metrics["sharpe"], "cagr": metrics["cagr"], "mdd": metrics["mdd"]}
    return out


def load_h22_lookup() -> dict:
    d = json.loads(H22_REPORT_DATA.read_text(encoding="utf-8"))
    return d["h22"]["raw_lookup_table"]


def expected_value_table(lookup: dict, weights: dict) -> dict:
    w = normalize(weights)
    ev = {cfg: {"sharpe": 0.0, "cagr": 0.0} for cfg in CONFIGS}
    for ep, wt in w.items():
        for cfg in CONFIGS:
            m = lookup[ep][cfg]
            ev[cfg]["sharpe"] += wt * m["sharpe"]
            ev[cfg]["cagr"] += wt * m["cagr"]
    for cfg in CONFIGS:
        crisis_mdds = [lookup[ep][cfg]["mdd"] for ep in w if ep != "full_2019_2026"]
        ev[cfg]["mdd_worst_case"] = min(crisis_mdds)
    return ev


def rank(ev: dict, metric: str) -> list:
    return sorted(((cfg, v[metric]) for cfg, v in ev.items()), key=lambda x: -x[1])


def main():
    spy = run_spy_buyhold()
    h22_lookup = load_h22_lookup()

    lookup = {}
    for ep in WINDOWS:
        lookup[ep] = {
            "spy_buyhold": spy[ep],
            "core_alone": h22_lookup[ep]["core_alone"],
            "core_plus_satellite": h22_lookup[ep]["case_a_static_satellite"],
        }

    out = {"episode_windows": {k: list(v) for k, v in WINDOWS.items()}, "raw_lookup_table": lookup,
           "scenarios": {}}
    for scen_name, weights in SCENARIOS.items():
        ev = expected_value_table(lookup, weights)
        out["scenarios"][scen_name] = {
            "weights_normalized": normalize(weights),
            "expected_value": ev,
            "ranking_by_expected_sharpe": rank(ev, "sharpe"),
            "ranking_by_expected_cagr": rank(ev, "cagr"),
        }

    (OUT_DIR / "h26_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[h26] saved h26_results.json")
    for scen_name in SCENARIOS:
        print(f"--- {scen_name} ---")
        for cfg, val in out["scenarios"][scen_name]["ranking_by_expected_sharpe"]:
            print(f"  {cfg}: E[sharpe]={val:.4f}")


if __name__ == "__main__":
    main()
