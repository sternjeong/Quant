import json
import datetime
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

boot = json.load(open(os.path.join(OUT_DIR, "h_bootstrap_results.json"), encoding="utf-8"))
comb = json.load(open(os.path.join(OUT_DIR, "h_combined_results.json"), encoding="utf-8"))

report = {
    "meta": {
        "generated": datetime.date.today().isoformat(),
        "episode_order": boot["meta"]["episode_order"],
    },
    "bootstrap": boot,
    "combined": comb,
}
with open(os.path.join(OUT_DIR, "report_data.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("saved report_data.json", len(json.dumps(report)))
