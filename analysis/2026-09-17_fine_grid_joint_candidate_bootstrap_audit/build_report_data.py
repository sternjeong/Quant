#!/usr/bin/env python3
"""h37_results.json을 report_data.json으로 정리 — 계산 재실행 없이 순수 재구성."""
import json
import os
from datetime import date, timezone, datetime

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/h37_results.json", encoding="utf-8") as f:
    R = json.load(f)

EP_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
ALL_CONFIGS = ["m12_monthly", "m12_quarterly", "m14_quarterly", "m15_quarterly", "m16_quarterly"]

boot = R["h2_h3_bootstrap_summary"]
combined = R["h2_h3_combined_propagation"]
h4 = R["h4_grid_percentile"]
h1 = R["h1_reproducibility"]

# grade helper (this program's convention: >=90 robust, 70-90 moderate, 50-70 weak, <50 reversed)
def grade_of(win_rate):
    if win_rate >= 0.90:
        return "robust"
    if win_rate >= 0.70:
        return "moderate"
    if win_rate >= 0.50:
        return "weak"
    return "reversed"

unified_rows = []
for scen in ("base", "calm_heavy", "crisis_heavy"):
    for base_cfg in ("m12_monthly", "m12_quarterly"):
        for cand in ("m14_quarterly", "m15_quarterly", "m16_quarterly"):
            c = combined[scen][base_cfg][cand]
            unified_rows.append({
                "scenario": scen, "baseline": base_cfg, "candidate": cand,
                "weighting_only_win_rate": c["weighting_only_win_rate_challenger"],
                "sampling_only_win_rate": c["sampling_only_win_rate_challenger"],
                "combined_win_rate": c["combined_win_rate_challenger"],
                "combined_gap_ci90": c["combined_gap_challenger_minus_baseline"]["ci90"],
                "grade": grade_of(c["combined_win_rate_challenger"]),
            })

# aggregate: min/max/mean combined win rate per candidate across all 6 (3 scenario x 2 baseline) comparisons
agg = {}
for cand in ("m14_quarterly", "m15_quarterly", "m16_quarterly"):
    wins = [r["combined_win_rate"] for r in unified_rows if r["candidate"] == cand]
    agg[cand] = {"min": round(min(wins), 4), "max": round(max(wins), 4),
                 "mean": round(sum(wins) / len(wins), 4), "n_comparisons": len(wins)}

report = {
    "meta": {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "round_label": "트랙D 21라운드(H37) — 리서치 에이전트 B 무인 야간 실행",
        "episode_order": EP_ORDER,
        "n_boot": R["n_boot"], "block_lengths": R["block_lengths"], "seed": R["seed"],
        "n_draws": 10000,
        "configs": R["configs"],
        "total_runtime_sec": R["total_runtime_sec"],
    },
    "h1_reproducibility": h1,
    "bootstrap_summary": boot,
    "combined_propagation": combined,
    "unified_rows": unified_rows,
    "candidate_aggregate": agg,
    "h4_grid_percentile": h4,
}

with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)

print("report_data.json written.")
print(json.dumps(agg, indent=1))
