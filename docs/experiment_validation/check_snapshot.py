"""Offline integrity and readiness check. This command never writes completion markers."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(root):
    root = Path(root).resolve()
    errors = []
    lock = json.loads((root / "snapshot_lock.json").read_text())
    for rel, expected in lock["artifacts"].items():
        path = (root / rel).resolve()
        if not path.is_relative_to(root):
            errors.append(f"outside_snapshot:{rel}")
        elif not path.is_file() or sha256(path) != expected:
            errors.append(f"hash_mismatch:{rel}")
    required = {"spec.json", "candidates.yaml", "manifest.json"}
    if not required.issubset(lock["artifacts"]):
        errors.append("missing_required_lock_entries")
    spec = json.loads((root / "spec.json").read_text())
    candidates = json.loads((root / "candidates.yaml").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    if [c["id"] for c in candidates["candidates"]] != [f"S{i}" for i in range(1, 7)]:
        errors.append("candidate_set_changed")
    protocol = (root / spec["protocol_snapshot"]).read_text()
    gate_text = protocol.split("## 사전 등록 선택 게이트\n", 1)[1].split("\n## VM 운용", 1)[0].strip()
    if gate_text != spec["selection_gates_verbatim"]:
        errors.append("selection_gates_changed")
    for candidate in candidates["candidates"]:
        if f'| {candidate["id"]} | {candidate["protocol_rule"]} |' not in protocol:
            errors.append(f"candidate_rule_changed:{candidate['id']}")
    execution = spec["execution"]
    if (execution["one_way_cost_bps"] != [5, 10, 25]
            or execution["same_day_close_fill_allowed"]
            or execution["signal_data_after_signal_close_allowed"]
            or execution["fill_price"] != "Open"
            or execution["fill_session"] != "strictly_next_exchange_trading_session"):
        errors.append("execution_contract_changed")
    for item in manifest["source_files"] + manifest["datasets"]:
        if "path" in item:
            if lock["artifacts"].get(item["path"]) != item["sha256"]:
                errors.append(f"manifest_lock_disagree:{item['path']}")
    blockers = [b["id"] for b in spec["unresolved_blockers"]]
    for item in manifest["datasets"]:
        if item["status"] != "captured":
            blockers.append(f"data_not_verified:{item['id']}")
    if not spec["frozen"] or spec["status"] != "frozen":
        blockers.append("spec_not_frozen")
    if manifest["status"] != "frozen":
        blockers.append("manifest_not_frozen")
    # This tool checks saved evidence, not the correctness of a future backtest.
    return {
        "evidence_integrity": "PASS" if not errors else "FAIL",
        "day_1_status": "PASS" if not errors and not blockers else "BLOCKED",
        "errors": errors, "blockers": blockers,
        "checked_artifacts": len(lock["artifacts"]),
        "market_datasets_captured": sum(d["status"] == "captured" for d in manifest["datasets"]),
        "scope": "No execution/backtest correctness claim; no completion marker written",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    result = check(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["evidence_integrity"] != "PASS":
        raise SystemExit(1)
    if args.require_complete and result["day_1_status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
