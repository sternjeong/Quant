#!/usr/bin/env python3
"""h34_results.json + H33/H33b 기존 결과를 합쳐 report_data.json을 만든다."""
import datetime
import json
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
H33_DIR = "/workspaces/Quant/analysis/2026-08-23_block_bootstrap_sample_error_quantification"

with open(f"{OUT_DIR}/h34_results.json", encoding="utf-8") as f:
    H34 = json.load(f)

with open(f"{H33_DIR}/h33_results.json", encoding="utf-8") as f:
    H33 = json.load(f)

with open(f"{H33_DIR}/h33b_results.json", encoding="utf-8") as f:
    H33B = json.load(f)

# unified confidence table
def grade(win_rate):
    if win_rate is None:
        return "n/a"
    if win_rate >= 0.90:
        return "robust"
    if win_rate >= 0.70:
        return "moderate"
    if win_rate >= 0.50:
        return "weak"
    return "reversed"


UNIFIED = [
    {
        "id": "H22", "round": 18, "label": "정적보유 새틀라이트(15%) vs 코어 단독",
        "recommendation": "정적보유 새틀라이트 15% 채택",
        "weighting_only_win_rate": H33B["weighting_only_H30_style"]["win_rate"]["case_a_static_satellite"],
        "combined_win_rate": H33B["combined_weighting_x_sampling"]["win_rate"]["case_a_static_satellite"],
        "combined_gap_ci90": H33B["combined_weighting_x_sampling"]["gap_static_minus_core"]["ci90"],
        "source": "H33/H33b (2026-08-23, 이전 라운드에서 이미 완료)",
    },
    {
        "id": "H26", "round": 19, "label": "챔피언+새틀라이트(시스템) vs SPY 매수보유",
        "recommendation": "시스템(챔피언+새틀라이트)이 SPY 매수보유를 이긴다",
        "weighting_only_win_rate": H34["combined_h26_system_vs_spy"]["weighting_only_win_rate_challenger"],
        "combined_win_rate": H34["combined_h26_system_vs_spy"]["combined_win_rate_challenger"],
        "combined_gap_ci90": H34["combined_h26_system_vs_spy"]["combined_gap_challenger_minus_baseline"]["ci90"],
        "source": "H34 (이번 라운드, 신규)",
    },
    {
        "id": "H26b", "round": 19, "label": "챔피언 코어 단독 vs SPY 매수보유 (부가)",
        "recommendation": "코어 단독도 SPY 매수보유를 이긴다",
        "weighting_only_win_rate": H34["combined_h26_core_alone_vs_spy"]["weighting_only_win_rate_challenger"],
        "combined_win_rate": H34["combined_h26_core_alone_vs_spy"]["combined_win_rate_challenger"],
        "combined_gap_ci90": H34["combined_h26_core_alone_vs_spy"]["combined_gap_challenger_minus_baseline"]["ci90"],
        "source": "H34 (이번 라운드, 부가 비교)",
    },
    {
        "id": "H28", "round": 19, "label": "변동성타겟팅 오버레이 없음 vs 있음",
        "recommendation": "변동성타겟팅 오버레이 없음(기각) 유지",
        "weighting_only_win_rate": 1 - H34["combined_h28_vol_targeted_vs_no_overlay"]["weighting_only_win_rate_challenger"],
        "combined_win_rate": 1 - H34["combined_h28_vol_targeted_vs_no_overlay"]["combined_win_rate_challenger"],
        "combined_gap_ci90": [-H34["combined_h28_vol_targeted_vs_no_overlay"]["combined_gap_challenger_minus_baseline"]["ci90"][1],
                                -H34["combined_h28_vol_targeted_vs_no_overlay"]["combined_gap_challenger_minus_baseline"]["ci90"][0]],
        "source": "H34 (이번 라운드, 신규)",
    },
    {
        "id": "H32", "round": 19, "label": "분기 리밸런싱 vs 월간 리밸런싱 (룩백 12개월 고정)",
        "recommendation": "분기 리밸런싱으로 전환",
        "weighting_only_win_rate": H34["combined_h32_quarterly_vs_monthly"]["weighting_only_win_rate_challenger"],
        "combined_win_rate": H34["combined_h32_quarterly_vs_monthly"]["combined_win_rate_challenger"],
        "combined_gap_ci90": H34["combined_h32_quarterly_vs_monthly"]["combined_gap_challenger_minus_baseline"]["ci90"],
        "source": "H34 (이번 라운드, 신규)",
    },
]
for row in UNIFIED:
    row["combined_grade"] = grade(row["combined_win_rate"])
    row["weighting_only_grade"] = grade(row["weighting_only_win_rate"])

report_data = {
    "meta": {
        "generated": datetime.date.today().isoformat(),
        "n_boot": H34["meta"]["n_boot"],
        "n_draws": H34["meta"]["n_draws"],
        "block_lengths": H34["meta"]["block_lengths"],
        "episode_order": H34["meta"]["episode_order"],
        "base_rates": H34["meta"]["base_rates"],
        "total_runtime_sec": H34["total_runtime_sec"],
    },
    "h34": H34,
    "h33": H33,
    "h33b": H33B,
    "unified_confidence_table": UNIFIED,
}

with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
    json.dump(report_data, f, indent=2, ensure_ascii=False)
print("[build_report_data] saved report_data.json")
