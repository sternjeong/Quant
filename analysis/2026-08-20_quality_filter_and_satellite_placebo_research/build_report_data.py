"""h8_results.json + h9_results.json을 report_data.json으로 합친다(선행 라운드의
build_report_data.py와 동일 패턴)."""
import json
from datetime import timezone, datetime
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

with open(OUT_DIR / "h8_results.json", encoding="utf-8") as f:
    h8 = json.load(f)
with open(OUT_DIR / "h9_results.json", encoding="utf-8") as f:
    h9 = json.load(f)

report_data = {
    "meta": {"generated": datetime.now(timezone.utc).date().isoformat() + " (UTC)"},
    "h8": h8,
    "h9": h9,
}

with open(OUT_DIR / "report_data.json", "w", encoding="utf-8") as f:
    json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
print(f"작성 완료: {OUT_DIR / 'report_data.json'}")
