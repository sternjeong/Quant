"""h20_results.json / h21_results.json을 report_data.json 하나로 묶는다 (원자료 재계산 없음)."""
import json
import datetime
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

h20 = json.loads((OUT_DIR / "h20_results.json").read_text(encoding="utf-8"))
h21 = json.loads((OUT_DIR / "h21_results.json").read_text(encoding="utf-8"))

report_data = {
    "meta": {"generated": datetime.date.today().isoformat()},
    "h20": h20,
    "h21": h21,
}

with open(OUT_DIR / "report_data.json", "w", encoding="utf-8") as f:
    json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
print("SAVED report_data.json")
