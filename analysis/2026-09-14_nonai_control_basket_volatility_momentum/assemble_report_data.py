"""backtest_results.json + audit_results.json + IREN 원본 참조값을 report_data.json 하나로 합친다."""
import json

from basket_common import BASKETS, OUT_DIR, END

IREN_DIR = "/opt/quant/analysis/2026-08-16_iren_volatile_momentum_stocks"
TRACKC_AUDIT_DIR = "/opt/quant/analysis/2026-08-30_track_c_bootstrap_confidence_audit"


def main():
    with open(f"{OUT_DIR}/backtest_results.json", encoding="utf-8") as f:
        bt = json.load(f)
    with open(f"{OUT_DIR}/audit_results.json", encoding="utf-8") as f:
        audit = json.load(f)
    with open(f"{IREN_DIR}/report_data.json", encoding="utf-8") as f:
        iren = json.load(f)
    with open(f"{TRACKC_AUDIT_DIR}/audit1_results.json", encoding="utf-8") as f:
        iren_audit1 = json.load(f)

    iren_ref = {
        "basket": ["IREN", "CIFR", "CLSK", "WULF", "HUT", "BTDR"],
        "common_start": iren["main_basket_start"],
        "end": iren["main_basket_end"],
        "basket_static_buy_hold": iren["basket_static_buy_hold"],
        "momentum_rotation": iren["momentum_rotation"],
        "trend_following_basket": iren["trend_following_best"]["basket"],
        "trend_following_single": iren["trend_following_best"]["iren_single"],
        "spy_buy_hold": iren["spy_buy_hold"],
        "permutation_basket": {"percentile": 93.0, "p_value": 0.075},
        "permutation_single": {"percentile": 100.0, "p_value": 0.005},
        "bootstrap_L20": {
            "basket": iren_audit1["basket"]["bootstrap_by_block_len"]["20"],
            "single": iren_audit1["iren_single"]["bootstrap_by_block_len"]["20"],
        },
    }

    report = {
        "meta": {
            "generated": "2026-09-14",
            "end_date": END,
            "n_permutations": audit["meta"]["n_permutations"],
            "n_boot": audit["meta"]["n_boot"],
            "block_lengths": audit["meta"]["block_lengths"],
        },
        "iren_reference": iren_ref,
        "baskets": {},
    }

    for name, cfg in BASKETS.items():
        report["baskets"][name] = {
            "label": cfg["label"],
            "tickers": cfg["tickers"],
            "representative": cfg["representative"],
            "narrative": cfg["narrative"],
            **{k: v for k, v in bt[name].items() if k not in ("tickers", "representative", "label", "narrative")},
            "audit": audit[name],
        }

    with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print("[assemble] saved report_data.json")


if __name__ == "__main__":
    main()
