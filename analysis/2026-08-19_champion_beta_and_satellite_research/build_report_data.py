"""h1_result_primary.json + h2_result.json(+선택적 h1_result_2015.json) -> report_data.json 조립."""
import json
import datetime
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

with open(OUT_DIR / "h1_result_primary.json", encoding="utf-8") as f:
    h1_primary = json.load(f)

h2_path = OUT_DIR / "h2_result.json"
with open(h2_path, encoding="utf-8") as f:
    h2 = json.load(f)

report_data = {
    "meta": {
        "generated": datetime.date.today().isoformat(),
        "champion_universe": [
            "XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC",
            "TLT", "IEF", "GLD", "EFA", "HYG", "DBC",
        ],
    },
    "h1": h1_primary,
    "h2": h2,
}

out_path = OUT_DIR / "report_data.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(report_data, f, indent=2, ensure_ascii=False, default=str)
print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes)")
