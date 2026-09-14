"""H22의 기저확률 가중 시나리오를 그대로 재사용해 h24(새틀라이트 비중)와 h25(코어 필터)에 적용.

analysis/2026-08-23_expected_value_reframing_and_continuous_exposure/h22_expected_value_reweighting.py
의 SCENARIOS 딕셔너리를 그대로 복사한다(동일 기저확률, 새로 발명하지 않음). h22 자체의 코드를
import하지 않고 상수만 복사하는 이유: h22 스크립트는 자신만의 report_data 소스 경로/로딩 로직을
갖고 있어 import 시 불필요한 파일 읽기가 발생하기 때문 -- 여기서는 SCENARIOS 딕셔너리 값만 필요.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]

# H22(analysis/2026-08-23_expected_value_reframing_and_continuous_exposure/h22_expected_value_reweighting.py)
# 와 정확히 동일한 값. 재발명하지 않고 그대로 복사.
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


def window_metrics_for_episode(ep_data: dict, config_key: str) -> dict:
    """full_2019_2026은 full_period 지표, 나머지는 crisis_window 지표를 쓴다(H22와 동일 관례)."""
    if ep_data.get("crisis_window") is None:
        m = ep_data["metrics"]["full_period"][config_key] if "metrics" in ep_data else ep_data["full_period_metrics"][config_key]
    else:
        m = ep_data["metrics"]["crisis_window"][config_key] if "metrics" in ep_data else ep_data["crisis_window_metrics"][config_key]
    return m


# ---------------------------------------------------------------------------
# H24용: 새틀라이트 비중 프런티어의 기댓값
# ---------------------------------------------------------------------------
def h24_expected_value(h24_results: dict) -> dict:
    episodes = h24_results["episodes"]
    weights_list = h24_results["meta"]["satellite_weights"]
    out = {"scenarios": {}, "weights_list": weights_list}

    for scen_name, raw_w in SCENARIOS.items():
        w = normalize(raw_w)
        ev_by_weight = {}
        for sw in weights_list:
            sharpe_ev, cagr_ev = 0.0, 0.0
            crisis_mdds = []
            for ep_label, wt in w.items():
                ep = episodes[ep_label]
                use_crisis = ep["crisis_window"] is not None
                window_key = "crisis_window" if use_crisis else "full_period"
                frontier_row = next(f for f in ep["frontier"] if f["satellite_weight"] == sw)
                m = frontier_row[window_key]
                sharpe_ev += wt * m["sharpe"]
                cagr_ev += wt * m["cagr"]
                if ep_label != "full_2019_2026":
                    crisis_mdds.append(m["mdd"])
            ev_by_weight[str(sw)] = {
                "satellite_weight": sw,
                "expected_sharpe": round(sharpe_ev, 4),
                "expected_cagr_pct": round(cagr_ev, 4),
                "worst_case_crisis_mdd": round(min(crisis_mdds), 2) if crisis_mdds else None,
            }
        ranking = sorted(ev_by_weight.items(), key=lambda kv: -kv[1]["expected_sharpe"])
        out["scenarios"][scen_name] = {
            "weights_normalized": w,
            "expected_value_by_weight": ev_by_weight,
            "ranking_by_expected_sharpe": [(k, v["expected_sharpe"]) for k, v in ranking],
            "optimal_weight": ranking[0][1]["satellite_weight"],
        }
    return out


# ---------------------------------------------------------------------------
# H25용: 필터 있음/없음의 기댓값
# ---------------------------------------------------------------------------
def h25_expected_value(h25_results: dict) -> dict:
    episodes = h25_results["episodes"]
    out = {"scenarios": {}}
    configs = ["with_filter", "without_filter"]

    for scen_name, raw_w in SCENARIOS.items():
        w = normalize(raw_w)
        ev = {cfg: {"sharpe": 0.0, "cagr": 0.0} for cfg in configs}
        crisis_mdds = {cfg: [] for cfg in configs}
        for ep_label, wt in w.items():
            ep = episodes[ep_label]
            use_crisis = ep["crisis_window"] is not None
            window_key = "crisis_window" if use_crisis else "full_period"
            for cfg in configs:
                m = ep["metrics"][window_key][cfg]
                ev[cfg]["sharpe"] += wt * m["sharpe"]
                ev[cfg]["cagr"] += wt * m["cagr"]
                if ep_label != "full_2019_2026":
                    crisis_mdds[cfg].append(m["mdd"])
        for cfg in configs:
            ev[cfg]["sharpe"] = round(ev[cfg]["sharpe"], 4)
            ev[cfg]["cagr"] = round(ev[cfg]["cagr"], 4)
            ev[cfg]["worst_case_crisis_mdd"] = round(min(crisis_mdds[cfg]), 2) if crisis_mdds[cfg] else None
        ranking = sorted(ev.items(), key=lambda kv: -kv[1]["sharpe"])
        out["scenarios"][scen_name] = {
            "weights_normalized": w,
            "expected_value": ev,
            "ranking_by_expected_sharpe": [(k, v["sharpe"]) for k, v in ranking],
            "winner": ranking[0][0],
        }
    return out


def main():
    h24 = json.loads((OUT_DIR / "h24_results.json").read_text(encoding="utf-8"))
    h25 = json.loads((OUT_DIR / "h25_results.json").read_text(encoding="utf-8"))

    h24_ev = h24_expected_value(h24)
    h25_ev = h25_expected_value(h25)

    out = {
        "meta": {"scenarios": SCENARIOS, "episode_order": EPISODE_ORDER},
        "h24_expected_value": h24_ev,
        "h25_expected_value": h25_ev,
        "h24_raw": h24,
        "h25_raw": h25,
    }
    (OUT_DIR / "report_data.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("[ev] saved report_data.json")

    for scen in SCENARIOS:
        print(f"--- H24 {scen}: optimal weight = {h24_ev['scenarios'][scen]['optimal_weight']} ---")
        for k, v in h24_ev["scenarios"][scen]["ranking_by_expected_sharpe"]:
            print(f"   sw={k}: E[sharpe]={v:.4f}")
        print(f"--- H25 {scen}: winner = {h25_ev['scenarios'][scen]['winner']} ---")
        for k, v in h25_ev["scenarios"][scen]["ranking_by_expected_sharpe"]:
            print(f"   {k}: E[sharpe]={v:.4f}")


if __name__ == "__main__":
    main()
