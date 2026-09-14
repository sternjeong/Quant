"""H28 - 코어(17자산 챔피언) 레벨 변동성타겟팅 오버레이의 기댓값 재검증.

작업20-21(Track B No.06)이 발견한 "포트폴리오 레벨 변동성타겟팅은 샤프를 살짝 깎지만 MDD를
크게 줄인다"는 결과를, 작업39(H22)가 확립한 기저확률 가중 기댓값 렌즈로 재검증한다. 라운드11이
새틀라이트 스위치류(전부 이 모양 - 최악은 개선, 평균은 악화)가 전부 기댓값에서 진다는 걸 확인했으니,
같은 모양이 챔피언 코어 노출 자체에도 적용되는지, 아니면 연속 스칼라라 다르게 나오는지 확인.

방법:
  - 17자산 챔피언(기존 이진 시장필터 포함, 필터 자체는 손대지 않음 - 라운드12 H25 몫)을
    champion_strategy.py 그대로 재사용해 일별 순수익률(net, 비용반영)을 뽑는다.
  - kostolany_market_report_2026-08-12/portfolio_vol_targeting.py의 vol_target_scale() 함수를
    그대로 재사용(target_vol=18%, cap=1.0 - momentum_rotation_vol_target_final.json에 기록된
    원 라운드의 최종 채택 파라미터)해서 일별 수익률에 오버레이를 씌운다(20일 실현변동성 기준,
    1일 시차로 lookahead 방지).
  - 6개 창(전체+5개 위기) 각각에서 오버레이 有/無 두 가지를 계산하고, H22와 동일한 3개 시나리오
    (base/calm_heavy/crisis_heavy) 가중치로 기댓값 샤프/CAGR을 계산한다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))
sys.path.insert(0, "/workspaces/Quant/analysis/2026-08-19_champion_beta_and_satellite_research")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics
from champion_strategy import run_champion  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent

WINDOWS = {
    "full_2019_2026": ("2019-08-12", "2026-08-19"),
    "gfc_2008": ("2007-10-01", "2009-06-30"),
    "covid_2020": ("2020-02-19", "2020-04-30"),
    "bear_2022": ("2022-01-01", "2022-12-31"),
    "selloff_2018": ("2018-09-01", "2019-01-15"),
    "correction_2015_2016": ("2015-08-01", "2016-02-15"),
}

TRADING_DAYS = 252
TARGET_VOL_ANNUAL = 18.0  # momentum_rotation_vol_target_final.json 채택값
VOL_CAP = 1.0
VOL_WINDOW = 20

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


def vol_target_scale(daily_ret: pd.Series, target_vol_annual: float, cap: float,
                      window: int = VOL_WINDOW, floor: float = 0.0) -> pd.Series:
    realized_vol = daily_ret.rolling(window, min_periods=window).std() * np.sqrt(TRADING_DAYS)
    scale = (target_vol_annual / 100.0) / realized_vol
    return scale.clip(lower=floor, upper=cap).fillna(1.0)


def metrics_from_returns(rets: pd.Series) -> dict:
    eq = (1.0 + rets.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    return calculate_metrics(eq, [], eq.index[0], eq.index[-1])


def run_window(start: str, end: str) -> dict:
    """전체기간(2019-2026 시작)부터 champion을 돌려 20일 vol 추정에 충분한 워밍업을 확보한다.

    champion_strategy.run_champion은 이미 WARMUP_DAYS=400 만큼 가격 데이터를 더 당겨오지만,
    vol_target_scale의 20일 롤링은 그 슬라이스된 구간(start~end) 첫날부터 필요하므로,
    위기 구간(예: 2008)은 그 구간 시작일보다 앞선 넉넉한 fetch_start가 이미 champion 내부에서
    확보된다 - run_champion(start,end)를 그대로 호출하면 슬라이스가 start부터라 vol window
    앞쪽 20일이 NaN->scale=1.0(fillna)로 처리되는데, 이는 h22/h27과 동일하게 "창 시작 시점에는
    사전 정보가 없다"는 자연스러운 경계 조건이라 그대로 둔다(다른 H들도 동일 관례).
    """
    r = run_champion(start, end)
    net_ret = r["ret_net"]

    no_overlay_metrics = calculate_metrics(r["equity_net"], [], net_ret.index[0], net_ret.index[-1])

    scale = vol_target_scale(net_ret, TARGET_VOL_ANNUAL, VOL_CAP)
    scaled_ret = net_ret * scale.shift(1).fillna(1.0)
    vol_targeted_metrics = metrics_from_returns(scaled_ret)

    return {
        "no_overlay": {"sharpe": no_overlay_metrics["sharpe"], "cagr": no_overlay_metrics["cagr"],
                        "mdd": no_overlay_metrics["mdd"]},
        "vol_targeted": {"sharpe": vol_targeted_metrics["sharpe"], "cagr": vol_targeted_metrics["cagr"],
                          "mdd": vol_targeted_metrics["mdd"]},
        "avg_scale_applied": round(float(scale.mean()), 4),
        "pct_days_scaled_down": round(float((scale < 0.999).mean() * 100), 2),
    }


def main():
    lookup = {}
    t0 = time.time()
    for ep, (start, end) in WINDOWS.items():
        lookup[ep] = run_window(start, end)
        print(f"[h28] {ep} done at t={time.time()-t0:.1f}s: "
              f"no_overlay sharpe={lookup[ep]['no_overlay']['sharpe']:.3f} mdd={lookup[ep]['no_overlay']['mdd']:.2f} | "
              f"vol_targeted sharpe={lookup[ep]['vol_targeted']['sharpe']:.3f} mdd={lookup[ep]['vol_targeted']['mdd']:.2f}",
              flush=True)

    out = {
        "episode_windows": {k: list(v) for k, v in WINDOWS.items()},
        "params": {"target_vol_annual": TARGET_VOL_ANNUAL, "cap": VOL_CAP, "vol_window_days": VOL_WINDOW},
        "raw_lookup_table": lookup,
        "scenarios": {},
    }

    configs = ["no_overlay", "vol_targeted"]
    for scen_name, weights in SCENARIOS.items():
        w = normalize(weights)
        ev = {cfg: {"sharpe": 0.0, "cagr": 0.0} for cfg in configs}
        for ep, wt in w.items():
            for cfg in configs:
                ev[cfg]["sharpe"] += wt * lookup[ep][cfg]["sharpe"]
                ev[cfg]["cagr"] += wt * lookup[ep][cfg]["cagr"]
        for cfg in configs:
            crisis_mdds = [lookup[ep][cfg]["mdd"] for ep in w if ep != "full_2019_2026"]
            ev[cfg]["mdd_worst_case"] = min(crisis_mdds)
            ev[cfg]["sharpe"] = round(ev[cfg]["sharpe"], 4)
            ev[cfg]["cagr"] = round(ev[cfg]["cagr"], 4)
            ev[cfg]["mdd_worst_case"] = round(ev[cfg]["mdd_worst_case"], 2)
        ranking = sorted(ev.items(), key=lambda kv: -kv[1]["sharpe"])
        out["scenarios"][scen_name] = {
            "weights_normalized": w, "expected_value": ev,
            "ranking_by_expected_sharpe": [(k, v["sharpe"]) for k, v in ranking],
        }

    (OUT_DIR / "h28_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[h28] saved h28_results.json")
    for scen_name in SCENARIOS:
        print(f"--- {scen_name} ---")
        for cfg, val in out["scenarios"][scen_name]["ranking_by_expected_sharpe"]:
            print(f"  {cfg}: E[sharpe]={val:.4f}")


if __name__ == "__main__":
    main()
