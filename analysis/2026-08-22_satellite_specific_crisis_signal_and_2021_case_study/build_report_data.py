"""h14_results.json + h15_results.json -> report_data.json 조립."""
import json
import datetime
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

with open(OUT_DIR / "h14_results.json", encoding="utf-8") as f:
    h14 = json.load(f)

with open(OUT_DIR / "h15_results.json", encoding="utf-8") as f:
    h15 = json.load(f)

report_data = {
    "meta": {"generated": datetime.date.today().isoformat()},
    "h14": h14,
    "h15": h15,
}

out_path = OUT_DIR / "report_data.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(report_data, f, indent=2, ensure_ascii=False, default=str)
print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes)")
