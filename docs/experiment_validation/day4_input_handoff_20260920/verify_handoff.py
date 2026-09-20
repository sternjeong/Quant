"""Independent saved-file reconciliation; deliberately cannot certify Day 4."""
import csv
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
REPO = BASE.parent.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as stream:
        return list(csv.DictReader(stream))


def verify():
    manifest = json.loads((HERE / "input_manifest.json").read_text())
    for path, expected in manifest["source_files"].items():
        assert digest(BASE / path) == expected, path
    source = read_csv(BASE / "day4/member_coverage.csv.gz")
    requests = read_csv(HERE / "requested_member_keys.csv.gz")
    columns = ("fill_session", "signal_session", "signal_close_utc", "fill_open_utc",
               "membership_snapshot_date", "raw_identifier", "cache_ticker_hint")
    expected = Counter(tuple(row[col] for col in columns) for row in source)
    actual = Counter(tuple(row[col] for col in columns) for row in requests)
    assert actual == expected and set(actual.values()) == {1}
    assert len(requests) == manifest["member_boundary_requests"] == 20156
    grouped, by_id = defaultdict(list), defaultdict(list)
    for row in requests:
        grouped[row["fill_session"]].append(row)
        by_id[row["raw_identifier"]].append(row)
    schedule = read_csv(BASE / "day2/XNYS_sessions.csv.gz")
    sessions = [row["session"] for row in schedule]
    schedule_by_date = {row["session"]: row for row in schedule}
    constituents = read_csv(BASE / "data/sp500_historical_constituents.csv.gz")
    boundaries = read_csv(HERE / "requested_boundaries.csv")
    assert len(boundaries) == len(grouped) == manifest["semiannual_boundaries"] == 40
    assert len({r["fill_session"] for r in boundaries}) == 40
    for row in boundaries:
        fill, signal = row["fill_session"], row["signal_session"]
        assert sessions[sessions.index(fill) - 1] == signal
        assert datetime.fromisoformat(row["signal_close_utc"]) == datetime.fromisoformat(schedule_by_date[signal]["close"])
        assert datetime.fromisoformat(row["fill_open_utc"]) == datetime.fromisoformat(schedule_by_date[fill]["open"])
        assert int(row["diagnostic_members"]) == len(grouped[fill])
        prior = max((r for r in constituents if r["date"] <= signal), key=lambda r: r["date"])
        assert row["membership_snapshot_date"] == prior["date"]
        assert sorted(r["raw_identifier"] for r in grouped[fill]) == sorted(t.strip() for t in prior["tickers"].split(",") if t.strip())
    identifiers = read_csv(HERE / "requested_identifiers.csv")
    assert len(identifiers) == len(by_id) == manifest["raw_identifiers"] == 949
    assert len({r["raw_identifier"] for r in identifiers}) == 949
    for row in identifiers:
        original = by_id[row["raw_identifier"]]
        assert {r["cache_ticker_hint"] for r in original} == {row["cache_ticker_hint"]}
        assert int(row["requested_boundaries"]) == len(original)
        assert row["first_requested_signal"] == min(r["signal_session"] for r in original)
        assert row["last_requested_signal"] == max(r["signal_session"] for r in original)
    previous_counts = {}
    for name in ("day4/result_hashes.json", "day4_review_20260920/result_hashes.json", "day4_sector_sources_20260920/result_hashes.json"):
        previous = json.loads((BASE / name).read_text())
        for path, expected_hash in previous["artifacts"].items():
            assert digest(REPO / previous["path_base"] / path) == expected_hash, path
        previous_counts[name] = len(previous["artifacts"])
    frozen = json.loads((BASE / "day2/audit_results.json").read_text())
    for path, expected_hash in frozen["data_hashes"].items():
        assert digest(BASE / path) == expected_hash, path
    raw_count = 0
    for receipt in json.loads((HERE / "source_access.json").read_text()):
        if "path" in receipt:
            assert digest(HERE / receipt["path"]) == receipt["sha256"]
            raw_count += 1
    initial = json.loads((HERE / "initial_workspace.json").read_text())
    appendable = {"PROGRESS.md", "RESUME_NOTE.md", "docs/experiment_validation/PROGRESS.md", "docs/experiment_validation/RESUME_NOTE.md"}
    for path, record in initial["protected_files"].items():
        if path in appendable:
            original = (HERE / (path.replace("/", "__") + ".before")).read_bytes()
            assert hashlib.sha256(original).hexdigest() == record["sha256"]
            assert (REPO / path).read_bytes().startswith(original), path
        else:
            assert digest(REPO / path) == record["sha256"], path
    for name in ("PROGRESS.md", "docs/experiment_validation/PROGRESS.md"):
        assert "DAY_4_COMPLETE" not in (REPO / name).read_text()
    comparison = read_csv(BASE / "day4/s1_s6_common_comparison.csv")
    assert len(comparison) == 6 and all(r["status"] == "NOT_EVALUABLE" for r in comparison)
    assert manifest["day4_complete"] is False and manifest["certified_rebalances"] == 0
    assert "24 passed" in (HERE / "tests.log").read_text()
    return {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "handoff_consistency": "PASS",
            "diagnostic_member_keys_verified": len(requests), "raw_identifiers_preserved": len(identifiers),
            "calendar_boundaries_verified": len(boundaries), "prior_artifacts_verified": previous_counts,
            "frozen_data_files_verified": len(frozen["data_hashes"]),
            "frozen_data_inventory_sha256": frozen["data_inventory_sha256"],
            "documentation_sources_verified": raw_count, "preexisting_files_preserved": len(initial["protected_files"]),
            "tests_passed": 24, "day4_status": "BLOCKED", "day4_complete": False,
            "certified_rebalances": 0, "certified_common_sessions": 0,
            "comparisons_not_evaluable": 6, "s6_backtest_executed": False,
            "day3_backtest_repeated": False, "new_strategy_interpretations": False}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
    raise SystemExit(2 if "--require-complete" in sys.argv else 0)
