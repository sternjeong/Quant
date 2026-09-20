"""backtest_results.json + audit_results.json + IREN/비-AI대조군 참조값을 report_data.json 하나로
합친다. 6개 독립 시대/바스켓(IREN, 해운, 대마초, 태양광, 크립토윈터, 닷컴버블)을 한 표에 모아
"규칙이 통하는지"가 표본기간의 길이가 아니라 바스켓별 구조에 좌우된다는 종합 판단을 만든다."""
import json

from common_era import BASKETS, OUT_DIR

IREN_DIR = "/opt/quant/analysis/2026-08-16_iren_volatile_momentum_stocks"
TRACKC_AUDIT_DIR = "/opt/quant/analysis/2026-08-30_track_c_bootstrap_confidence_audit"
NONAI_DIR = "/opt/quant/analysis/2026-09-14_nonai_control_basket_volatility_momentum"


def _unwrap(d):
    return d["metrics"] if "metrics" in d else d


def main():
    with open(f"{OUT_DIR}/backtest_results.json", encoding="utf-8") as f:
        bt = json.load(f)
    with open(f"{OUT_DIR}/audit_results.json", encoding="utf-8") as f:
        audit = json.load(f)
    with open(f"{IREN_DIR}/report_data.json", encoding="utf-8") as f:
        iren = json.load(f)
    with open(f"{TRACKC_AUDIT_DIR}/audit1_results.json", encoding="utf-8") as f:
        iren_audit1 = json.load(f)
    with open(f"{NONAI_DIR}/report_data.json", encoding="utf-8") as f:
        nonai = json.load(f)

    iren_ref = {
        "era_label": "AI/HPC 피벗 (2022-05~2026-08)",
        "basket": ["IREN", "CIFR", "CLSK", "WULF", "HUT", "BTDR"],
        "common_start": iren["main_basket_start"],
        "end": iren["main_basket_end"],
        "basket_static_buy_hold": _unwrap(iren["basket_static_buy_hold"]),
        "momentum_rotation": _unwrap(iren["momentum_rotation"]),
        "trend_following_basket": iren["trend_following_best"]["basket"],
        "trend_following_single": iren["trend_following_best"]["iren_single"],
        "spy_buy_hold": _unwrap(iren["spy_buy_hold"]),
        "permutation_basket": {"percentile": 93.0, "p_value": 0.075},
        "permutation_single": {"percentile": 100.0, "p_value": 0.005},
        "bootstrap_L20": {
            "basket": iren_audit1["basket"]["bootstrap_by_block_len"]["20"],
            "single": iren_audit1["iren_single"]["bootstrap_by_block_len"]["20"],
        },
    }

    report = {
        "meta": {
            "generated": "2026-09-17",
            "n_permutations": audit["meta"]["n_permutations"],
            "n_boot": audit["meta"]["n_boot"],
            "block_lengths": audit["meta"]["block_lengths"],
        },
        "iren_reference": iren_ref,
        "baskets": {},
        "cross_era": {},
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

    # ------------------------------------------------------------------
    # 6개 독립 시대/바스켓 종합비교표 (IREN + 비-AI대조군3 + 이번 라운드 신규2)
    # ------------------------------------------------------------------
    def replicates(tf, bh, rot):
        return tf > bh and tf > rot

    cross = {}
    cross["iren_ai_pivot"] = {
        "era_label": "AI/HPC 피벗 (2022-26)", "span": "4.25년",
        "tf_sharpe": iren["trend_following_best"]["basket"]["sharpe"],
        "bh_sharpe": _unwrap(iren["basket_static_buy_hold"])["sharpe"],
        "rot_sharpe": _unwrap(iren["momentum_rotation"])["sharpe"],
        "perm_basket_p": 0.075, "perm_single_p": 0.005,
        "rep_mdd_full": None,
    }
    for name in ("shipping", "cannabis", "solar"):
        b = nonai["baskets"][name]
        cross[name] = {
            "era_label": b["label"], "span": None,
            "tf_sharpe": b["trend_following_basket"]["sharpe"],
            "bh_sharpe": b["basket_static_buy_hold"]["sharpe"],
            "rot_sharpe": b["momentum_rotation"]["sharpe"],
            "perm_basket_p": b["audit"]["permutation_basket"]["p_value"],
            "perm_single_p": b["audit"]["permutation_single"]["p_value"],
            "rep_mdd_full": None,
        }
    for name, cfg in BASKETS.items():
        b = report["baskets"][name]
        cross[name] = {
            "era_label": cfg["label"], "span": f"{cfg['load_start'][:4]}~{cfg['end'][:4]}",
            "tf_sharpe": b["trend_following_basket"]["sharpe"],
            "bh_sharpe": b["basket_static_buy_hold"]["sharpe"],
            "rot_sharpe": b["momentum_rotation"]["sharpe"],
            "perm_basket_p": b["audit"]["permutation_basket"]["p_value"],
            "perm_single_p": b["audit"]["permutation_single"]["p_value"],
            "rep_mdd_full": b["representative_full_history_max_drawdown_pct"],
        }
    for k, v in cross.items():
        v["replicates_iren_ranking"] = replicates(v["tf_sharpe"], v["bh_sharpe"], v["rot_sharpe"])

    report["cross_era"] = cross

    with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print("[assemble] saved report_data.json")
    n_replicate = sum(1 for v in cross.values() if v["replicates_iren_ranking"])
    print(f"[assemble] {n_replicate}/{len(cross)} eras replicate the IREN ranking (tf > bh and tf > rotation)")


if __name__ == "__main__":
    main()
