"""h31 결과 json을 report_data.json으로 감싼다."""
import datetime
import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

h31 = json.loads((OUT_DIR / "h31_results.json").read_text(encoding="utf-8"))

out = {
    "meta": {"generated": datetime.date.today().isoformat(), "round": 15},
    "h31": h31,
}
(OUT_DIR / "report_data.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print("saved report_data.json")
