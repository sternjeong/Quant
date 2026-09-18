#!/usr/bin/env python3
"""Create or explicitly submit a bounded Champion-strategy Alpaca paper plan."""
from __future__ import annotations
import argparse
import json

from core.champion_strategy import compute_core_recommendation, compute_satellite_recommendation_point_in_time
from core.paper_execution import AlpacaPaperBroker, build_order_plan


def targets(core, satellite):
    result = {ticker: core["per_ticker_weight"] for ticker in core["top4"]}
    for ticker, weight in satellite.get("per_ticker_weights", {}).items():
        result[ticker] = result.get(ticker, 0.0) + weight
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit", action="store_true", help="submit only to Alpaca paper endpoint")
    parser.add_argument("--confirm", help="required plan fingerprint for submission")
    args = parser.parse_args()
    broker = AlpacaPaperBroker.from_env()
    account = broker.account()
    if account.get("trading_blocked") or account.get("account_blocked"):
        raise SystemExit("paper account is blocked")
    core = compute_core_recommendation()
    satellite = compute_satellite_recommendation_point_in_time()
    plan = build_order_plan(targets(core, satellite), broker.positions(), float(account["equity"]))
    print(json.dumps({"core": core["top4"], "satellite": satellite.get("selected", []), "plan": plan}, ensure_ascii=False, indent=2))
    if args.submit:
        if not args.confirm:
            raise SystemExit("--submit requires --confirm PLAN_FINGERPRINT")
        broker.submit_plan(plan, args.confirm)


if __name__ == "__main__":
    main()
