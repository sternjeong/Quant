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
    SLEEVE_CORE, SLEEVE_RESEARCH, SLEEVE_SATELLITE, AlpacaPaperBroker, RunStore, build_order_plan, plan_targets,
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


def build_plan(core, satellite, positions, equity, research=None):
    """Each sleeve carries its OWN hold flag (fail-closed: missing/non-True flag = hold).

    Core on hold (unknown market filter) -> no core buys, core holdings kept.  Satellite on hold
    (no flag, or its data was unavailable) -> no satellite buys and satellite holdings kept -- they
    are not liquidated just because the satellite recommendation is missing.  One sleeve on hold
    does not stop the other.  submit_plan re-applies both flags at the POST point.

    ``research`` (core.research_sleeve.compute_research_targets) adds promoted hypotheses as a third
    sleeve: champion targets are scaled by (1 - research weight) so the total stays <= 100%.  Symbols
    already owned by core/satellite keep that label (their hold flags win).  research=None keeps the
    plan byte-identical to the champion-only plan."""
    core_ok = core.get("new_orders_allowed") is True
    sat_ok = satellite.get("new_orders_allowed") is True
    targets = plan_targets(core, satellite)
    sleeve_of = _sleeve_of(core, satellite, positions)
    extra = {}
    if research is not None:
        r_targets = research.get("targets") or {}
        used = sum(r_targets.values())
        if used > 0:
            targets = {k: v * (1 - used) for k, v in targets.items()}
            for sym, w in r_targets.items():
                targets[sym] = targets.get(sym, 0.0) + w
                if sym not in CORE_UNIVERSE and sym not in (core.get("per_ticker_weights") or {}) \
                        and sym not in (satellite.get("per_ticker_weights") or {}):
                    sleeve_of[sym] = SLEEVE_RESEARCH
        extra = {"research_new_orders_allowed": research.get("new_orders_allowed") is True,
                 "research_hold_reason": str(research.get("hold_reason") or "")}
    return build_order_plan(
        targets, positions, equity,
        new_orders_allowed=core_ok, hold_reason="" if core_ok else str(core.get("allocation_reason", "")),
        satellite_new_orders_allowed=sat_ok,
        satellite_hold_reason="" if sat_ok else str(satellite.get("allocation_reason") or "satellite new_orders_allowed flag missing/false"),
        sleeve_of=sleeve_of, **extra,
    )


def tradability_warnings(plan, tradability_fn):
    """Pre-order check (roadmap P1): buy symbols the broker reports as not tradable.  Informational --
    the plan itself is unchanged; a lookup failure is reported separately, never as 'untradable'."""
    buys = [o["symbol"] for o in plan["orders"] if o["side"] == "buy"]
    if not buys or tradability_fn is None:
        return {"checked": False, "untradable_buys": [], "lookup_failed": []}
    report = tradability_fn(buys)
    return {"checked": True, "report": report,
            "untradable_buys": sorted(s for s, r in report.items() if r["verdict"] in ("not_tradable", "inactive", "not_found")),
            "lookup_failed": sorted(s for s, r in report.items() if r["verdict"] == "lookup_failed")}


def run(broker, core, satellite, submit=False, confirm=None, run_store=None, tradability_fn=None, research=None):
    account = broker.account()
    if account.get("trading_blocked") or account.get("account_blocked"):
        raise SystemExit("paper account is blocked")
    plan = build_plan(core, satellite, broker.positions(), float(account["equity"]), research)
    output = {"core": core["top4"], "satellite": satellite.get("selected", []), "plan": plan, "research": research,
              "tradability": tradability_warnings(plan, tradability_fn)}
    if output["tradability"]["untradable_buys"]:
        print(f"WARNING: not tradable at broker: {output['tradability']['untradable_buys']}")
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
    from core.alpaca_market_meta import check_tradability
    from core.research_sleeve import compute_research_targets

    run(AlpacaPaperBroker.from_env(), compute_core_recommendation(), compute_satellite_recommendation_point_in_time(),
        args.submit, args.confirm, RunStore(), tradability_fn=check_tradability, research=compute_research_targets())


if __name__ == "__main__":
    main()
