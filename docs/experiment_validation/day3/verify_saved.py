"""Verify serialized outputs without re-running any deterministic backtest."""
from __future__ import annotations

import json
from pathlib import Path
import hashlib

import numpy as np
import pandas as pd

from backtest import BASE, BASELINES, COSTS, load_panel, metrics, month_ends, signal_plan
from run_day3 import verify_inputs, write_json
from validate_results import validate_run

ROOT = Path(__file__).resolve().parent


def main():
    manifest = json.loads((ROOT / "run_manifest.json").read_text())
    for rel, expected in manifest["implementation_and_contract_sha256"].items():
        assert hashlib.sha256((BASE / rel).read_bytes()).hexdigest() == expected, rel
    _, digest = verify_inputs()
    table = pd.read_csv(BASE / "baseline_metrics.csv", float_precision="round_trip")
    expected_runs = {(sample, strategy, cost)
                     for sample in ("actual_17", "proxy_17", "actual_5_full")
                     for strategy in ((["S4", "S5"] if sample == "actual_5_full" else [f"S{i}" for i in range(1, 6)]) + BASELINES)
                     for cost in COSTS}
    assert set(table[["sample", "strategy", "cost_bps"]].itertuples(index=False, name=None)) == expected_runs
    assert len(table) == 63
    validation, held_flags, boundaries = [], [], []
    for sample in table["sample"].unique():
        panel = load_panel(sample)
        ends = month_ends(panel.schedule)
        inside = ends[(ends >= panel.closes.index[0]) & (ends <= panel.closes.index[-1])]
        sma_ready = inside[9]
        earliest_s4 = inside[(inside >= sma_ready) & (inside >= pd.Timestamp("2007-01-01"))][0]
        common = inside[(inside >= panel.closes.index[252]) & (inside >= pd.Timestamp("2007-01-01"))][0]
        boundaries.append({"sample": sample, "price_start": str(panel.closes.index[0].date()),
                           "first_10_month_end_sma_available": str(sma_ready.date()),
                           "first_s4_signal_after_2007_lower_bound": str(earliest_s4.date()),
                           "first_common_252_signal": str(common.date()),
                           "common_first_fill": str(panel.schedule.index[panel.schedule.index.get_loc(common)+1].date()),
                           "last_stored_session": str(panel.closes.index[-1].date()),
                           "last_complete_month_signal": str(inside[-1].date()),
                           "s4_earlier_signals_excluded_for_common_comparison": int(((inside >= earliest_s4) & (inside < common)).sum())})
        for strategy in table.loc[table["sample"] == sample, "strategy"].unique():
            targets, _ = signal_plan(panel, strategy)
            for cost in COSTS:
                run_id = f"{sample}__{strategy}__{cost}bp"
                ledger = pd.read_csv(ROOT / f"{run_id}.daily.csv.gz", index_col="session",
                                     parse_dates=["session"], float_precision="round_trip")
                orders = pd.read_csv(ROOT / f"{run_id}.orders.csv.gz", float_precision="round_trip")
                audit = validate_run(panel, ledger, orders, targets, cost)
                recalculated = metrics(ledger, orders)
                saved = table[(table["sample"] == sample) & (table.strategy == strategy) & (table.cost_bps == cost)].iloc[0]
                for key, value in recalculated.items():
                    if isinstance(value, str):
                        assert saved[key] == value
                    else:
                        assert np.isclose(saved[key], value, atol=1e-12, rtol=1e-12, equal_nan=True), key
                if "XLRE" in set(orders.ticker):
                    ticker_orders = orders[orders.ticker == "XLRE"]
                    for day in panel.raw["XLRE"].index[panel.raw["XLRE"].Volume.eq(0)]:
                        if day not in ledger.index:
                            continue
                        units = ticker_orders.loc[ticker_orders.fill_session <= str(day.date()), "adjusted_units_delta"].sum()
                        held_flags.append({"run_id": run_id, "session": str(day.date()), "ticker": "XLRE",
                                           "held_adjusted_units": units,
                                           "marked_value": units * panel.raw["XLRE"].loc[day, "Adj Close"],
                                           "nav": ledger.loc[day, "nav"],
                                           "executed_legs": int((ticker_orders.fill_session == str(day.date())).sum()),
                                           "treatment": "retained provider close; execution forbidden; tradability unverified"})
                validation.append({"run_id": run_id, **audit})
        print(f"Serialized replay PASS: {sample}", flush=True)
    pd.DataFrame(held_flags).to_csv(ROOT / "zero_volume_held_marks.csv", index=False, float_format="%.17g")
    pd.DataFrame(boundaries).to_csv(ROOT / "sample_boundary_audit.csv", index=False)
    result = {"status": "PASS", "metrics_rows": len(table), "serialized_runs": len(validation),
              "data_inventory_sha256": digest, "all_costs_and_candidates_present": True,
              "same_day_close_fills": 0, "zero_volume_fills": 0, "non_next_session_fills": 0,
              "stored_metrics_recomputed_from_equity": True,
              "total_order_legs": sum(x["order_legs_checked"] for x in validation),
              "total_equity_sessions": sum(x["equity_sessions_replayed"] for x in validation),
              "max_relative_nav_replay_error": max(x["max_relative_nav_replay_error"] for x in validation),
              "runs": validation}
    write_json(ROOT / "saved_validation.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "runs"}, indent=2))


if __name__ == "__main__":
    main()
