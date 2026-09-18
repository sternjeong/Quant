"""Adversarial checks for saved evidence and the Day 1 completion guard."""
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parent
MODULE_SPEC = importlib.util.spec_from_file_location("day1_check", ROOT / "check_snapshot.py")
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(MODULE)


@pytest.fixture()
def snapshot(tmp_path):
    dest = tmp_path / "snapshot"
    shutil.copytree(ROOT, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return dest


def test_real_snapshot_is_intact_but_cannot_complete():
    result = MODULE.check(ROOT)
    assert result["evidence_integrity"] == "PASS"
    assert result["day_1_status"] == "BLOCKED"
    assert {"B1", "B2", "B3"}.issubset(result["blockers"])


def test_price_byte_tampering_is_detected(snapshot):
    path = snapshot / "data/SPY.csv.gz"
    path.write_bytes(path.read_bytes() + b"changed")
    result = MODULE.check(snapshot)
    assert "hash_mismatch:data/SPY.csv.gz" in result["errors"]
    assert result["day_1_status"] == "BLOCKED"


def test_missing_dataset_is_detected(snapshot):
    (snapshot / "data/XLRE.csv.gz").unlink()
    assert "hash_mismatch:data/XLRE.csv.gz" in MODULE.check(snapshot)["errors"]


def test_clearing_blockers_does_not_bypass_hash_lock(snapshot):
    path = snapshot / "spec.json"
    spec = json.loads(path.read_text())
    spec.update(frozen=True, status="frozen", unresolved_blockers=[])
    path.write_text(json.dumps(spec))
    result = MODULE.check(snapshot)
    assert "hash_mismatch:spec.json" in result["errors"]
    assert result["day_1_status"] == "BLOCKED"


def test_same_day_close_is_rejected_even_if_spec_hash_is_replaced(snapshot):
    path = snapshot / "spec.json"
    spec = json.loads(path.read_text())
    spec["execution"].update(same_day_close_fill_allowed=True, fill_price="Close")
    path.write_text(json.dumps(spec))
    lock_path = snapshot / "snapshot_lock.json"
    lock = json.loads(lock_path.read_text())
    lock["artifacts"]["spec.json"] = MODULE.sha256(path)
    lock_path.write_text(json.dumps(lock))
    assert "execution_contract_changed" in MODULE.check(snapshot)["errors"]


def test_manifest_checksum_disagreement_is_detected(snapshot):
    path = snapshot / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["datasets"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(manifest))
    assert any(e.startswith("manifest_lock_disagree:") for e in MODULE.check(snapshot)["errors"])
