"""h35_results.json + h36_results.json(+ h36_expected_value.json) + H34의 5행 통합표를 합쳐
report_data.json을 만든다."""
from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
WORKTREE_ROOT = OUT_DIR.parent.parent
H34_DIR = WORKTREE_ROOT / "analysis/2026-08-24_bootstrap_confidence_audit_remaining_verdicts"

h35 = json.loads((OUT_DIR / "h35_results.json").read_text(encoding="utf-8"))
h36 = json.loads((OUT_DIR / "h36_results.json").read_text(encoding="utf-8"))
h36_ev = json.loads((OUT_DIR / "h36_expected_value.json").read_text(encoding="utf-8"))
h34_prior = json.loads((H34_DIR / "report_data.json").read_text(encoding="utf-8"))

PRIOR_UNIFIED = h34_prior["unified_confidence_table"]

c = h35["combined_h25_without_filter_vs_with_filter"]


def grade(wr):
    if wr >= 0.90:
        return "robust"
    if wr >= 0.70:
        return "moderate"
    if wr >= 0.50:
        return "weak"
    return "reversed"


h25_row = {
    "id": "H25",
    "round": 20,
    "label": "이진 시장필터 제거(무필터) vs 필터 유지(현 챔피언)",
    "recommendation": "무필터(상시 완전투자)가 필터 유지를 이긴다",
    "weighting_only_win_rate": c["weighting_only_win_rate_challenger"],
    "combined_win_rate": c["combined_win_rate_challenger"],
    "combined_gap_ci90": c["combined_gap_challenger_minus_baseline"]["ci90"],
    "source": "H35 (이번 라운드, 신규)",
    "combined_grade": grade(c["combined_win_rate_challenger"]),
    "weighting_only_grade": grade(c["weighting_only_win_rate_challenger"]),
}

unified_6 = PRIOR_UNIFIED + [h25_row]

out = {
    "meta": {
        "generated": "2026-08-30",
        "round": 20,
        "n_boot": h35["meta"]["n_boot"],
        "n_draws": h35["meta"]["n_draws"],
        "block_lengths": h35["meta"]["block_lengths"],
        "episode_order": h35["meta"]["episode_order"],
        "base_rates": h35["meta"]["base_rates"],
        "h36_satellite_weights": h36["meta"]["satellite_weights"],
    },
    "h35": h35,
    "h36": h36,
    "h36_expected_value": h36_ev,
    "unified_confidence_table": unified_6,
}
(OUT_DIR / "report_data.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
print("saved report_data.json, unified table rows:", len(unified_6))
print("H25 row:", json.dumps(h25_row, indent=2, ensure_ascii=False))
