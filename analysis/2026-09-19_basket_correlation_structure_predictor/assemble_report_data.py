"""backtest_results.json + audit_results.json + correlation_results.json +
structural_hypothesis_results.json + 기존 6개 바스켓 참조값을 report_data.json 하나로 합친다."""
import json

from basket_common2 import BASKETS, OUT_DIR, END

IREN_JSON = "/opt/quant/analysis/2026-08-16_iren_volatile_momentum_stocks/report_data.json"
NONAI_JSON = "/opt/quant/analysis/2026-09-14_nonai_control_basket_volatility_momentum/backtest_results.json"
ERA_JSON = "/opt/quant/analysis/2026-09-17_historical_era_trend_following_extension/backtest_results.json"


def unwrap(d):
    return d["metrics"] if "metrics" in d else d


def main():
    with open(f"{OUT_DIR}/backtest_results.json", encoding="utf-8") as f:
        bt = json.load(f)
    with open(f"{OUT_DIR}/audit_results.json", encoding="utf-8") as f:
        audit = json.load(f)
    with open(f"{OUT_DIR}/correlation_results.json", encoding="utf-8") as f:
        corr = json.load(f)
    with open(f"{OUT_DIR}/structural_hypothesis_results.json", encoding="utf-8") as f:
        hyp = json.load(f)
    with open(IREN_JSON, encoding="utf-8") as f:
        iren = json.load(f)
    with open(NONAI_JSON, encoding="utf-8") as f:
        nonai = json.load(f)
    with open(ERA_JSON, encoding="utf-8") as f:
        era = json.load(f)

    existing6 = {
        "iren": {
            "label": "IREN류 비트코인채굴→AI/HPC 피벗", "tickers": ["IREN", "CIFR", "CLSK", "WULF", "HUT", "BTDR"],
            "bh": unwrap(iren["basket_static_buy_hold"]), "rot": unwrap(iren["momentum_rotation"]),
            "tf": iren["trend_following_best"]["basket"], "spy": unwrap(iren["spy_buy_hold"]),
            "common_start": iren["main_basket_start"], "end": iren["main_basket_end"],
            "source": "작업27",
        },
        "shipping": {
            "label": "해운 운임 슈퍼사이클", "tickers": nonai["shipping"]["tickers"],
            "bh": nonai["shipping"]["basket_static_buy_hold"], "rot": nonai["shipping"]["momentum_rotation"],
            "tf": nonai["shipping"]["trend_following_basket"], "spy": nonai["shipping"]["spy_buy_hold_common_window"],
            "common_start": nonai["shipping"]["common_start"], "end": nonai["shipping"]["end"],
            "source": "작업77",
        },
        "cannabis": {
            "label": "대마초 구조적 장기하락", "tickers": nonai["cannabis"]["tickers"],
            "bh": nonai["cannabis"]["basket_static_buy_hold"], "rot": nonai["cannabis"]["momentum_rotation"],
            "tf": nonai["cannabis"]["trend_following_basket"], "spy": nonai["cannabis"]["spy_buy_hold_common_window"],
            "common_start": nonai["cannabis"]["common_start"], "end": nonai["cannabis"]["end"],
            "source": "작업77",
        },
        "solar": {
            "label": "태양광/클린에너지 붐-버스트", "tickers": nonai["solar"]["tickers"],
            "bh": nonai["solar"]["basket_static_buy_hold"], "rot": nonai["solar"]["momentum_rotation"],
            "tf": nonai["solar"]["trend_following_basket"], "spy": nonai["solar"]["spy_buy_hold_common_window"],
            "common_start": nonai["solar"]["common_start"], "end": nonai["solar"]["end"],
            "source": "작업77",
        },
        "crypto_winter_2018": {
            "label": "크립토윈터 2018 (MARA/RIOT, AI피벗 이전)", "tickers": era["crypto_winter_2018"]["tickers"],
            "bh": era["crypto_winter_2018"]["basket_static_buy_hold"], "rot": era["crypto_winter_2018"]["momentum_rotation"],
            "tf": era["crypto_winter_2018"]["trend_following_basket"], "spy": era["crypto_winter_2018"]["spy_buy_hold_common_window"],
            "common_start": era["crypto_winter_2018"]["common_start"], "end": era["crypto_winter_2018"]["end"],
            "source": "작업88",
        },
        "dotcom_bubble_2000": {
            "label": "닷컴버블 2000 (생존 인터넷/통신주)", "tickers": era["dotcom_bubble_2000"]["tickers"],
            "bh": era["dotcom_bubble_2000"]["basket_static_buy_hold"], "rot": era["dotcom_bubble_2000"]["momentum_rotation"],
            "tf": era["dotcom_bubble_2000"]["trend_following_basket"], "spy": era["dotcom_bubble_2000"]["spy_buy_hold_common_window"],
            "common_start": era["dotcom_bubble_2000"]["common_start"], "end": era["dotcom_bubble_2000"]["end"],
            "source": "작업88",
        },
    }

    report = {
        "meta": {
            "generated": "2026-09-19",
            "end_date": END,
            "n_permutations": audit["meta"]["n_permutations"],
            "n_boot": audit["meta"]["n_boot"],
            "block_lengths": audit["meta"]["block_lengths"],
        },
        "existing6": existing6,
        "new_baskets": {},
        "correlation": corr,
        "hypothesis_test": hyp,
    }

    for name, cfg in BASKETS.items():
        report["new_baskets"][name] = {
            "label": cfg["label"],
            "tickers": cfg["tickers"],
            "representative": cfg["representative"],
            "narrative": cfg["narrative"],
            "predicted_high_correlation": cfg["predicted_high_correlation"],
            "predicted_reproduce": cfg["predicted_reproduce"],
            **{k: v for k, v in bt[name].items()
               if k not in ("tickers", "representative", "label", "narrative", "predicted_high_correlation", "predicted_reproduce")},
            "audit": audit[name],
        }

    with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print("[assemble] saved report_data.json")


if __name__ == "__main__":
    main()
