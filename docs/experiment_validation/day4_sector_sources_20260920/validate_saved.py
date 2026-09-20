"""Independently reconcile this source supplement; never changes prior results."""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
REPO = BASE.parent.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((HERE / "input_manifest.json").read_text())
    for item in manifest["captured_sources"]:
        assert sha(HERE / item["path"]) == item["sha256"], item["path"]
    previous_counts = {}
    for name in ["day4/result_hashes.json", "day4_review_20260920/result_hashes.json"]:
        previous = json.loads((BASE / name).read_text())
        for path, digest in previous["artifacts"].items():
            assert sha(REPO / previous["path_base"] / path) == digest, path
        previous_counts[name] = len(previous["artifacts"])
    frozen = json.loads((BASE / "day2/audit_results.json").read_text())
    for path, digest in frozen["data_hashes"].items():
        assert sha(BASE / path) == digest, path
    content = BeautifulSoup((HERE / "msci_20230502_announcement.html").read_bytes(), "html.parser")
    text = content.select_one("pre.announcementContent").get_text()
    section = text.split("\nUSA\n", 1)[1].split("\nVIETNAM\n", 1)[0]
    records = re.findall(r"^([^\n]+)\nCURRENT GICS SUB-INDUSTRY\s+(\d{8})[^\n]*\nNEW GICS SUB-INDUSTRY\s+(\d{8})[^\n]*", section, re.M)
    rows = list(csv.DictReader((HERE / "usa_announced_code_changes.csv").open()))
    assert len(rows) == len(records) == int(re.search(r"^USA\s+(\d+)$", text, re.M)[1]) == 62
    for row, (name, old, new) in zip(rows, records):
        assert row == {"source_company_label": name.strip(), "current_subindustry_code": old,
                       "announced_new_subindustry_code": new, "sector_code_changes": str(old[:2] != new[:2])}
    diagnostics = json.loads((HERE / "source_diagnostics.json").read_text())
    assert diagnostics["usa_sector_code_changes"] == sum(old[:2] != new[:2] for _, old, new in records) == 20
    assert diagnostics["announced_at_utc"] == "2023-05-02T22:21:00+00:00"
    assert "Announcement for May 02, 2023 at 10:21 PM GMT" in text
    assert diagnostics["usable_as_s6_input"] is False and diagnostics["certified_s6_rebalances"] == 0
    comparisons = list(csv.DictReader((BASE / "day4/s1_s6_common_comparison.csv").open()))
    assert len(comparisons) == 6 and all(row["status"] == "NOT_EVALUABLE" for row in comparisons)
    assert "26 passed" in (HERE / "tests.log").read_text()
    initial = json.loads((HERE / "initial_workspace.json").read_text())
    appendable = {"PROGRESS.md", "RESUME_NOTE.md", "docs/experiment_validation/PROGRESS.md"}
    for path, record in initial["protected_files"].items():
        if path in appendable:
            original = (HERE / (path.replace("/", "__") + ".before")).read_bytes()
            assert hashlib.sha256(original).hexdigest() == record["sha256"]
            assert (REPO / path).read_bytes().startswith(original), path
        else:
            assert sha(REPO / path) == record["sha256"], path
    result = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "saved_source_consistency": "PASS",
              "day4_status": "BLOCKED", "day4_complete": False, "tests_passed": 26,
              "previous_artifacts_verified": previous_counts, "frozen_data_files_verified": len(frozen["data_hashes"]),
              "frozen_data_inventory_sha256": frozen["data_inventory_sha256"],
              "new_raw_sources_verified": 2, "new_raw_inventory_sha256": manifest["new_raw_inventory_sha256"],
              "independently_reconciled_usa_rows": len(rows), "sector_code_changes": 20,
              "preexisting_files_preserved": len(initial["protected_files"]),
              "certified_s6_rebalances": 0, "certified_s6_common_sessions": 0,
              "s1_s6_comparison_rows_not_evaluable": 6, "s6_backtest_executed": False,
              "day3_backtest_repeated": False, "previous_s1_order_check_repeated": False,
              "candidate_baseline_gate_changes": False, "completion_marker_written": False}
    print(json.dumps(result, indent=2))
    return 2 if "--require-complete" in sys.argv else 0


if __name__ == "__main__":
    raise SystemExit(main())
