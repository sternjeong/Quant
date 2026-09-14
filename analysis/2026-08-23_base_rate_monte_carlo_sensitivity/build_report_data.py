"""h30 결과 json을 report_data.json 하나로 합친다."""
import datetime
import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

h30 = json.loads((OUT_DIR / "h30_results.json").read_text(encoding="utf-8"))

out = {
    "meta": {"generated": datetime.date.today().isoformat(), "round": 15},
    "h30": h30,
}
(OUT_DIR / "report_data.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print("saved report_data.json")
