#!/usr/bin/env python3
"""h_corr_results.json + h_boot_perm_results.json을 report_data.json으로 병합한다(순수 조립,
재계산 없음)."""
import json
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/h_corr_results.json", encoding="utf-8") as f:
    corr = json.load(f)
with open(f"{OUT_DIR}/h_boot_perm_results.json", encoding="utf-8") as f:
    boot = json.load(f)

report_data = {
    "meta": corr["meta"],
    "episodes": corr["episodes"],
    "expected_value": corr["expected_value"],
    "case_study_2021": corr["case_study_2021"],
    "base_rate_scenarios": corr["base_rate_scenarios"],
    "bootstrap": boot["bootstrap"],
    "permutation_test_pool_corr": boot["permutation_test_pool_corr"],
    "permutation_test_holdings_corr": boot["permutation_test_holdings_corr"],
    "combined_dirichlet_x_bootstrap": boot["combined_dirichlet_x_bootstrap"],
    "boot_meta": boot["meta"],
}

with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
    json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
print("wrote report_data.json")
