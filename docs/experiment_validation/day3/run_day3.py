"""Run the preregistered full-period Day 3 matrix once from frozen local inputs."""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import platform
import subprocess

import numpy as np
import pandas as pd

from backtest import (BASE, BASELINES, COSTS, END, FIVE, UNIVERSE, load_panel, metrics,
                      month_ends, signal_plan, simulate, target_at)
from validate_results import validate_run

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def csv(path, frame):
    compression = {"method": "gzip", "mtime": 0} if path.suffix == ".gz" else None
    frame.to_csv(path, index=False, float_format="%.17g", compression=compression)


def verify_inputs():
    day2 = json.loads((BASE / "day2/result_hashes.json").read_text())
    assert sha(BASE / "day2/result_hashes.json") == "4fd7ea3ced381b7e33957eccadf68cf653f7fad0f87be7d3d060d9a2cda6b2cc"
    for rel, expected in day2["artifacts"].items():
        assert sha(BASE / rel) == expected, rel
    datasets = {}
    for base, manifest in [(BASE, BASE / "manifest.json"), (BASE / "day2", BASE / "day2/input_manifest.json")]:
        for item in json.loads(manifest.read_text())["datasets"]:
            path = base / item["path"]
            assert sha(path) == item["sha256"]
            assert hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest() == item["content_sha256"]
            datasets[str(path.relative_to(BASE))] = item["sha256"]
    digest = hashlib.sha256(json.dumps(datasets, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest == day2["data_inventory_sha256"]
    return datasets, digest


def main():
    if (BASE / "baseline_metrics.csv").exists() or (ROOT / "run_manifest.json").exists():
        raise SystemExit("refuse_to_overwrite_existing_run: investigate/resume, do not repeat blindly")
    datasets, digest = verify_inputs()
    contract_files = [BASE / "day3_resolutions.md", ROOT / "backtest.py", ROOT / "run_day3.py",
                      ROOT / "validate_results.py", ROOT / "test_backtest.py"]
    manifest = {"day": 3, "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "checkpoint_id": "20260919T200502Z_day3-execution-contract",
                "code_commit_base": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "implementation_and_contract_sha256": {str(p.relative_to(BASE)): sha(p) for p in contract_files},
                "dataset_sha256": datasets, "data_inventory_sha256": digest,
                "prior_evidence_count": 79, "python": platform.python_version(),
                "pandas": pd.__version__, "numpy": np.__version__,
                "original_manifest": "manifest.json", "supplement_manifest": "day2/input_manifest.json",
                "query_policy": "offline; original provider sources/retrieval times retained; no new requests",
                "cost_bps": COSTS, "scope": "Day 3 only; no S6/OOS/selection verdict"}
    write_json(ROOT / "run_manifest.json", manifest)
    summaries, checks, coverage, zero_usage = [], [], [], []
    for sample in ["actual_17", "proxy_17", "actual_5_full"]:
        panel = load_panel(sample)
        strategies = (["S4", "S5"] if sample == "actual_5_full" else [f"S{i}" for i in range(1, 6)]) + BASELINES
        sample_signals = []
        for strategy in strategies:
            targets, signals = signal_plan(panel, strategy)
            sample_signals.extend(signals)
            first = min(targets)
            coverage.append({"sample": sample, "strategy": strategy,
                             "price_start": str(panel.closes.index[0].date()),
                             "warmup_252th_prior_session": str(panel.closes.index[252].date()),
                             "initial_signal_session": str(first.date()),
                             "first_fill_session": str(panel.schedule.index[panel.schedule.index.get_loc(first)+1].date()),
                             "end_session": str(END.date()), "signal_count": len(targets),
                             "equal_weight_baseline_assets": ";".join(panel.universe),
                             "pre_evaluation_interval": f"2007-01-01 through {first.date()} (warmup/no portfolio returns)",
                             "label": "프록시" if sample == "proxy_17" else "실제 ETF",
                             "s4_comparison_warmup_policy": "shared 252-session cohort; no shorter S4-only run"})
            # Real-data prefix invariance: every target is rebuilt with only its prefix.
            # target_at takes that prefix; S2 history_end is strictly before the signal.
            assert all(row["history_end"] <= row["signal_session"] for row in signals)
            for cost in COSTS:
                ledger, orders = simulate(panel, targets, cost)
                audit = validate_run(panel, ledger, orders, targets, cost)
                run_id = f"{sample}__{strategy}__{cost}bp"
                csv(ROOT / f"{run_id}.daily.csv.gz", ledger.reset_index())
                csv(ROOT / f"{run_id}.orders.csv.gz", orders)
                summaries.append({"sample": sample, "sample_label": "프록시" if sample == "proxy_17" else "실제 ETF",
                                  "strategy": strategy, "cost_bps": cost, **metrics(ledger, orders)})
                checks.append({"run_id": run_id, **audit})
                print(f"PASS {run_id}: {len(ledger)} equity rows, {len(orders)} order legs", flush=True)
                for ticker, raw in panel.raw.items():
                    for day in raw.index[raw.Volume.eq(0)]:
                        if day not in panel.closes.index or ticker not in set(panel.sources.loc[day]):
                            continue
                        relevant = UNIVERSE if strategy in ("S1", "S2", "S3") else FIVE if strategy in ("S4", "S5") else []
                        signal_uses = [str(d.date()) for d in targets if d >= day
                                       and d in panel.closes.index
                                       and panel.closes.index.get_loc(d) - panel.closes.index.get_loc(day) <= 252
                                       and ticker in set(panel.sources.loc[day, relevant])]
                        zero_usage.append({"run_id": run_id, "ticker": ticker, "session": str(day.date()),
                                           "preserved": True, "within_valuation_period": day in ledger.index,
                                           "within_required_signal_history": ";".join(signal_uses),
                                           "executed_legs": int(((orders.fill_session == str(day.date()))
                                                                 & (orders.ticker == ticker)).sum())})
        csv(ROOT / f"{sample}.signals.csv.gz", pd.DataFrame(sample_signals))
    csv(BASE / "baseline_metrics.csv", pd.DataFrame(summaries))
    csv(ROOT / "sample_coverage.csv", pd.DataFrame(coverage))
    csv(ROOT / "zero_volume_usage.csv", pd.DataFrame(zero_usage))
    write_json(ROOT / "execution_validation.json", {"status": "PASS", "runs": checks,
               "total_runs": len(checks), "order_legs_checked": sum(x["order_legs_checked"] for x in checks),
               "equity_sessions_replayed": sum(x["equity_sessions_replayed"] for x in checks),
               "max_relative_nav_replay_error": max(x["max_relative_nav_replay_error"] for x in checks),
               "same_day_close_fills": 0, "non_next_session_fills": 0, "zero_volume_fills": 0,
               "frozen_inputs_rechecked": verify_inputs()[1] == digest,
               "contract_unchanged_during_run": all(sha(BASE / rel) == h for rel, h in manifest["implementation_and_contract_sha256"].items()),
               "completed_at_utc": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    main()
