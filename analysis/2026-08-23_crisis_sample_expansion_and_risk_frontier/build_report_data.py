"""h18_results.json / h19_results.json을 report_data.json 하나로 묶는다 (원자료 재계산 없음)."""
import json
import datetime
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

h18 = json.loads((OUT_DIR / "h18_results.json").read_text(encoding="utf-8"))
h19 = json.loads((OUT_DIR / "h19_results.json").read_text(encoding="utf-8"))

report_data = {
    "meta": {"generated": datetime.date.today().isoformat()},
    "h18": h18,
    "h19": h19,
}

with open(OUT_DIR / "report_data.json", "w", encoding="utf-8") as f:
    json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
print("SAVED report_data.json")
