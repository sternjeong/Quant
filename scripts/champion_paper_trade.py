#!/usr/bin/env python3
"""Create or explicitly submit a bounded Champion-strategy Alpaca paper plan."""
from __future__ import annotations
import argparse
import json

from core.champion_strategy import (
    CHAMPION_STRATEGY_VERSION, CORE_UNIVERSE, compute_core_recommendation,
    compute_satellite_recommendation_point_in_time,
)
from core.paper_execution import (
    SLEEVE_CORE, SLEEVE_SATELLITE, AlpacaPaperBroker, RunStore, build_order_plan, plan_targets,
)


def _sleeve_of(core, satellite, positions):
    """Label each symbol core/satellite so the order gate can apply the right sleeve's hold flag.
    Core = the recommendation's targets and anything in the fixed core ETF universe; everything
    else held or targeted (individual stocks) belongs to the satellite sleeve."""
    labels = {}
    for symbol in set(positions) | set(core.get("per_ticker_weights") or {}) | set(satellite.get("per_ticker_weights") or {}):
        in_core = symbol in CORE_UNIVERSE or symbol in (core.get("per_ticker_weights") or {})
        labels[symbol] = SLEEVE_CORE if in_core else SLEEVE_SATELLITE
    return labels


def build_plan(core, satellite, positions, equity):
    """Each sleeve carries its OWN hold flag (fail-closed: missing/non-True flag = hold).

    Core on hold (unknown market filter) -> no core buys, core holdings kept.  Satellite on hold
    (no flag, or its data was unavailable) -> no satellite buys and satellite holdings kept -- they
    are not liquidated just because the satellite recommendation is missing.  One sleeve on hold
    does not stop the other.  submit_plan re-applies both flags at the POST point."""
    core_ok = core.get("new_orders_allowed") is True
    sat_ok = satellite.get("new_orders_allowed") is True
    return build_order_plan(
        plan_targets(core, satellite), positions, equity,
        new_orders_allowed=core_ok, hold_reason="" if core_ok else str(core.get("allocation_reason", "")),
        satellite_new_orders_allowed=sat_ok,
        satellite_hold_reason="" if sat_ok else str(satellite.get("allocation_reason") or "satellite new_orders_allowed flag missing/false"),
        sleeve_of=_sleeve_of(core, satellite, positions),
    )


def run(broker, core, satellite, submit=False, confirm=None, run_store=None):
    account = broker.account()
    if account.get("trading_blocked") or account.get("account_blocked"):
        raise SystemExit("paper account is blocked")
    plan = build_plan(core, satellite, broker.positions(), float(account["equity"]))
    output = {"core": core["top4"], "satellite": satellite.get("selected", []), "plan": plan}
    if submit:
        if not confirm:
            raise SystemExit("--submit requires --confirm PLAN_FINGERPRINT")
        output["results"] = broker.submit_plan(plan, confirm, run_store=run_store, strategy_version=CHAMPION_STRATEGY_VERSION)
        output["reconcile_state"] = {r.get("symbol"): r["reconcile_state"] for r in output["results"]}
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit", action="store_true", help="submit only to Alpaca paper endpoint")
    parser.add_argument("--confirm", help="required plan fingerprint for submission")
    args = parser.parse_args()
    run(AlpacaPaperBroker.from_env(), compute_core_recommendation(), compute_satellite_recommendation_point_in_time(),
        args.submit, args.confirm, RunStore())


if __name__ == "__main__":
    main()
