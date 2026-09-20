"""h1_meta.json + h2_grid_results.json + h3_placebo_results.json + h4_bootstrap_results.json을
report_data.json으로 병합한다(순수 조립 + 표 형태 재구성, 재계산 없음)."""
from __future__ import annotations

import json
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/h1_meta.json", encoding="utf-8") as f:
    H1 = json.load(f)
with open(f"{OUT_DIR}/h2_grid_results.json", encoding="utf-8") as f:
    H2 = json.load(f)
with open(f"{OUT_DIR}/h3_placebo_results.json", encoding="utf-8") as f:
    H3 = json.load(f)
with open(f"{OUT_DIR}/h4_bootstrap_results.json", encoding="utf-8") as f:
    H4 = json.load(f)

EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]


def decision_window(ep: str) -> str:
    return "full_period" if ep == "full_2019_2026" else "crisis_window"


def baseline_table() -> dict:
    out = {}
    for ep in EPISODE_ORDER:
        w = decision_window(ep)
        windows = H2["baseline"][ep]["windows"]
        out[ep] = {
            "n_rolls": H2["baseline"][ep]["n_rolls"],
            "cum_premium_pct": H2["baseline"][ep]["cumulative_net_premium_pct_of_notional"],
            "cum_payoff_pct": H2["baseline"][ep]["cumulative_net_payoff_pct_of_notional"],
            "window_used": w,
            "core_alone": windows[w]["core_alone"],
            "unhedged_satellite": windows[w]["unhedged_satellite"],
            "collar_hedged": windows[w]["collar_hedged"],
        }
    return out


def grid_series(grid_key: str, param_key: str) -> dict:
    """h2a/h2b/h2c 그리드에서 결정창(crisis_window 또는 full_2019_2026의 full_period) sharpe만 뽑는다."""
    out = {}
    for ep in EPISODE_ORDER:
        w = decision_window(ep)
        pts = H2[grid_key][ep]
        out[ep] = [
            {
                "param": pt[param_key],
                "sharpe_collar": pt["windows"][w]["collar_hedged"]["sharpe"],
                "sharpe_unhedged": pt["windows"][w]["unhedged_satellite"]["sharpe"],
                "mdd_collar": pt["windows"][w]["collar_hedged"]["mdd"],
                "cagr_collar": pt["windows"][w]["collar_hedged"]["cagr"],
            }
            for pt in pts
        ]
    return out


def zero_cost_series() -> dict:
    out = {}
    for ep in EPISODE_ORDER:
        w = decision_window(ep)
        d = H2["h2b_zero_cost"][ep]["windows"][w]
        out[ep] = {
            "sharpe_collar": d["collar_hedged"]["sharpe"], "mdd_collar": d["collar_hedged"]["mdd"],
            "cagr_collar": d["collar_hedged"]["cagr"], "sharpe_unhedged": d["unhedged_satellite"]["sharpe"],
        }
    return out


def neighborhood_pivot() -> dict:
    """h2d(풋x콜x테너 결합그리드)를 episode -> [{put,call,tenor,sharpe_collar,sharpe_unhedged,mdd_collar}] 로 유지."""
    out = {ep: [] for ep in EPISODE_ORDER}
    for row in H2["h2d_neighborhood_grid"]:
        out[row["episode"]].append({k: v for k, v in row.items() if k != "episode"})
    return out


def permutation_table() -> dict:
    return {ep: H3["permutation"][ep] for ep in EPISODE_ORDER}


def zero_payoff_placebo_table() -> dict:
    out = {}
    for ep in EPISODE_ORDER:
        d = H3["zero_payoff_placebo"][ep]
        out[ep] = {
            "unhedged_sharpe": d["unhedged"]["sharpe"], "real_collar_sharpe": d["real_collar"]["sharpe"],
            "zero_payoff_sharpe": d["zero_payoff_placebo"]["sharpe"],
            "real_beats_placebo": d["real_collar"]["sharpe"] > d["zero_payoff_placebo"]["sharpe"],
        }
    return out


def bootstrap_ci_table() -> dict:
    variants = list(H4["meta"]["variants"].keys())
    out = {}
    for ep in EPISODE_ORDER:
        d = H4["bootstrap"][ep]
        row = {"n_obs": d["n_obs"], "window_used": d["window_used"], "by_config": {}}
        for cfg in ["unhedged_satellite"] + variants:
            c = d["by_config"][cfg]
            l20 = c["bootstrap_by_block_len"]["20"]
            row["by_config"][cfg] = {
                "point_sharpe": c["point_estimate_sharpe"],
                "ci90_L20": l20["ci90"] if l20 else None,
            }
        out[ep] = row
    return out


real_beats_placebo_count = sum(1 for v in zero_payoff_placebo_table().values() if v["real_beats_placebo"])

report_data = {
    "meta": {
        "generated": "2026-09-15",
        "episode_order": EPISODE_ORDER,
        "episodes_raw": H1["episodes"],
        "satellite_weight": H1["satellite_weight"],
        "baseline_params": H2["baseline"]["full_2019_2026"],  # placeholder replaced below
        "collar_baseline": {"put_moneyness": 1.00, "call_moneyness": 1.05, "tenor_days": 21},
        "n_permutations": H3["meta"]["n_permutations"],
        "bootstrap_n_boot": H4["meta"]["n_boot"],
        "bootstrap_block_lengths": H4["meta"]["block_lengths"],
        "variants": H4["meta"]["variants"],
        "base_rate_scenarios": H4["meta"]["base_rate_scenarios"],
    },
    "baseline_table": baseline_table(),
    "put_grid": grid_series("h2a_put_grid", "put_moneyness"),
    "call_grid": grid_series("h2b_call_grid", "call_moneyness"),
    "tenor_grid": grid_series("h2c_tenor_grid", "tenor_days"),
    "zero_cost": zero_cost_series(),
    "neighborhood_grid": neighborhood_pivot(),
    "permutation": permutation_table(),
    "zero_payoff_placebo": zero_payoff_placebo_table(),
    "real_beats_placebo_count": real_beats_placebo_count,
    "bootstrap_ci": bootstrap_ci_table(),
    "combined_dirichlet_x_bootstrap": H4["combined_dirichlet_x_bootstrap"],
}
del report_data["meta"]["baseline_params"]

with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
    json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
print("wrote report_data.json")
