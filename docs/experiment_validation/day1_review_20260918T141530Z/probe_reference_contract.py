"""Offline Day 1 acceptance probes of pinned reference code, not a backtest.

Only the named function ASTs are executed. Production modules are never imported;
all provider dependencies are synthetic stubs, so no network, database or broker
operation is possible. Reproducing a defect does not pass the strategy contract.
"""
from __future__ import annotations

import ast
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
LOCK_SHA256 = "3022ec9a3169c827ccb398c309b2cd0d46be87fce7f467e1ef0a20f366f62f9e"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def reference_function(filename, name, stubs):
    tree = ast.parse((ROOT / "source" / filename).read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function],
        type_ignores=[],
    )
    namespace = {"pd": pd, **stubs}
    exec(compile(ast.fix_missing_locations(module), filename, "exec"), namespace)
    return namespace[name]


def main():
    lock_bytes = (ROOT / "snapshot_lock.json").read_bytes()
    assert sha256(lock_bytes) == LOCK_SHA256, "Published snapshot lock changed"
    lock = json.loads(lock_bytes)
    for name, expected in lock["artifacts"].items():
        assert sha256((ROOT / name).read_bytes()) == expected, name
    manifest = json.loads((ROOT / "manifest.json").read_text())
    spec = json.loads((ROOT / "spec.json").read_text())
    data_hashes = {}
    dates = {}
    for dataset in manifest["datasets"]:
        data = (ROOT / dataset["path"]).read_bytes()
        raw = gzip.decompress(data)
        assert sha256(data) == dataset["sha256"]
        assert sha256(raw) == dataset["content_sha256"]
        data_hashes[dataset["path"]] = dataset["sha256"]
        if dataset["kind"] == "etf_ohlcv":
            rows = list(csv.DictReader(io.StringIO(raw.decode())))
            dates[dataset["id"]] = sorted(row[next(iter(row))][:10] for row in rows)
    proxy = [spec["samples"]["proxy"]["mapping"].get(t, t) for t in spec["existing_17_etf"]]
    common = sorted(set.intersection(*(set(dates[t]) for t in proxy)))
    before_2016 = [d for d in common if d <= "2015-12-31"]
    assert common[0] == "2015-10-08"
    assert len(before_2016) < 253

    # Same closes and target weights, different next-session opens. The legacy
    # function has no Open input, so it cannot distinguish these fill scenarios.
    # Zero fees isolate this diagnostic; the protocol's 5/10/25 bp stays fixed.
    calculate = reference_function("champion_strategy.py", "_compute_portfolio_returns", {
        "BACKTEST_COST_BPS_PER_SIDE": 5.0,
    })
    sessions = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    closes = pd.DataFrame({"TEST": [100.0, 110.0, 110.0]}, index=sessions)
    weights = pd.DataFrame({"TEST": [1.0, 1.0, 1.0]}, index=sessions)
    legacy_return = float(calculate(closes, weights, cost_bps_per_side=0)["ret_net"].iloc[1])
    correct_open_to_close = {str(open_price): 110.0 / open_price - 1 for open_price in (100.0, 109.0)}
    assert abs(legacy_return - correct_open_to_close["109.0"]) > 0.09

    cap = reference_function("point_in_time_market_cap.py", "get_market_cap_asof", {
        "get_shares_outstanding_history": lambda *a, **kw: pd.Series(
            [1000.0], index=pd.to_datetime(["2020-01-02"])),
        "_cumulative_split_factor_after": lambda *a, **kw: 1.0,
        "get_price_history": lambda *a, **kw: pd.DataFrame(
            {"Close": [10.0]}, index=pd.to_datetime(["2019-12-31"])),
    })
    future_share_cap = cap("TEST", "2019-12-31", use_cache=False)
    assert future_share_cap == 10000.0
    members = reference_function("point_in_time_universe.py", "get_constituents_as_of", {
        "DEFAULT_CSV_PATH": "unused_stub",
        "load_historical_constituents_table": lambda *a: pd.DataFrame({
            "date": pd.to_datetime(["2020-01-02"]), "tickers_list": [["FUTURE_MEMBER"]],
        }),
    })
    future_members = members("2019-12-31")
    assert future_members == ["FUTURE_MEMBER"]

    print(json.dumps({
        "scope": "Day 1 reference acceptance only; no strategy performance or Day 2/4 audit",
        "locked_artifacts_verified": len(lock["artifacts"]),
        "published_lock_sha256": LOCK_SHA256,
        "dataset_stored_and_content_hashes_verified": len(data_hashes),
        "dataset_hashes": data_hashes,
        "dataset_inventory_sha256": sha256(json.dumps(data_hashes, sort_keys=True, separators=(",", ":")).encode()),
        "dataset_inventory_encoding": "UTF-8 compact sorted-key JSON path->stored SHA-256; no newline",
        "proxy_coverage": {
            "mapping": spec["samples"]["proxy"]["mapping"],
            "common_first_date": common[0], "common_last_date": common[-1],
            "common_rows_through_2015": len(before_2016),
            "first_possible_252_session_lookback_date": common[252],
            "calendar_12_month_anniversary": "2016-10-08",
            "decision": "B2 unresolved under either convention; dates are bounds, not adopted parameters",
        },
        "synthetic_probes": {
            "next_open_not_representable": {
                "reproduced": True, "legacy_close_return": legacy_return,
                "required_gross_return_by_next_open": correct_open_to_close,
                "fee_bps_for_diagnostic_only": 0,
            },
            "future_shares_fallback": {
                "reproduced": True, "requested_as_of": "2019-12-31",
                "only_share_observation": "2020-01-02", "returned_market_cap": future_share_cap,
            },
            "future_membership_fallback": {
                "reproduced": True, "requested_as_of": "2019-12-31",
                "only_membership_observation": "2020-01-02", "returned_members": future_members,
            },
        },
        "day_1_status": "BLOCKED",
        "interpretation": "Assertions pass by reproducing reference defects; this is not strategy acceptance",
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
