"""h3_results.json + h4_results.json을 report_data.json 하나로 합친다 (build_report.py가 이걸 읽음)."""
import json
import os
from datetime import datetime, timezone

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/h3_results.json", encoding="utf-8") as f:
    h3 = json.load(f)
with open(f"{OUT_DIR}/h4_results.json", encoding="utf-8") as f:
    h4 = json.load(f)

report_data = {
    "meta": {
        "generated": datetime.now(timezone.utc).isoformat(),
        "title": "순열검정으로 챔피언 검증하고, 퀄리티로 모멘텀을 걸러본다",
    },
    "h3": h3,
    "h4": h4,
}

with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
    json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
print(f"저장 완료: {OUT_DIR}/report_data.json")
