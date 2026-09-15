"""h1_h2/h3/h4/h5 산출물을 report_data.json 하나로 통합."""
import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

with open(OUT_DIR / "h1_h2_results.json", encoding="utf-8") as f:
    h1h2 = json.load(f)
with open(OUT_DIR / "h3_results.json", encoding="utf-8") as f:
    h3 = json.load(f)
with open(OUT_DIR / "h4_results.json", encoding="utf-8") as f:
    h4 = json.load(f)
with open(OUT_DIR / "h5_results.json", encoding="utf-8") as f:
    h5 = json.load(f)

report_data = {
    "meta": {
        "generated": "2026-09-14",
        "basket": h1h2["meta"]["basket"],
        "entry_window": h1h2["meta"]["entry_window"],
        "stop_pct": h1h2["meta"]["stop_pct"],
        "common_start": h1h2["meta"]["common_start"],
        "end": h1h2["meta"]["end"],
    },
    "h1_h2": h1h2["h1_h2_results"],
    "h3": h3["h3_results"],
    "h4": h4["episodes"],
    "h5": h5["h5_results"],
}

with open(OUT_DIR / "report_data.json", "w", encoding="utf-8") as f:
    json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
print("[build_report_data] saved report_data.json")
