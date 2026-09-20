"""h1/h2/h3/bootstrap_audit의 개별 JSON 산출물을 report_data.json 하나로 합친다(계산 로직 없음,
순수 병합 - 계산 재현성을 위해 원본 스크립트들의 출력을 그대로 보존)."""
import json
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent


def load(name):
    with open(OUT_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def main():
    h1 = load("h1_result.json")
    h2 = load("h2_result.json")
    h3 = load("h3_result.json")
    boot = load("bootstrap_audit_result.json")

    report = {
        "meta": {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "basket": h1["meta"]["basket"],
            "common_start": h1["meta"]["common_start"],
            "end": h1["meta"]["end"],
            "champion_params": {"entry_window": h1["meta"]["entry_window"], "stop_pct": h1["meta"]["stop_pct"]},
            "collar_params": {
                "put_moneyness": h1["meta"]["put_moneyness"], "call_moneyness": h1["meta"]["call_moneyness"],
                "tenor_days": h1["meta"]["tenor_days"],
            },
            "drawdown_episode": boot["meta"]["episode_window"],
        },
        "h1_spy_collar": h1,
        "h2_beta_scaled_collar": h2,
        "h3_btc_collar": h3,
        "bootstrap_audit": boot,
    }
    with open(OUT_DIR / "report_data.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print("wrote report_data.json")


if __name__ == "__main__":
    main()
