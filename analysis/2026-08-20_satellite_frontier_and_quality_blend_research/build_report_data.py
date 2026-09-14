"""h5_results.json + h6_results.json을 report_data.json으로 합친다(H1/H2 라운드의
build_report_data.py와 동일 패턴)."""
import json
from datetime import date, timezone, datetime
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

with open(OUT_DIR / "h5_results.json", encoding="utf-8") as f:
    h5 = json.load(f)
with open(OUT_DIR / "h6_results.json", encoding="utf-8") as f:
    h6 = json.load(f)

report_data = {
    "meta": {"generated": datetime.now(timezone.utc).date().isoformat() + " (UTC)"},
    "h5": h5,
    "h6": h6,
}

with open(OUT_DIR / "report_data.json", "w", encoding="utf-8") as f:
    json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
print(f"작성 완료: {OUT_DIR / 'report_data.json'}")
