#!/usr/bin/env python3
"""Inspect and manually close Alpaca *paper* execution runs (core.paper_execution.RunStore).

A run stays open until every order of its stored plan is terminal at the broker.  If the broker
lookup keeps failing (or an order never settles) the run would stay open forever and later
submissions keep resuming the old plan.  This tool is the operator's way out:

  python scripts/paper_run_admin.py list  [--status open|closed|all] [--limit N] [--json]
  python scripts/paper_run_admin.py close --run-id r00012 --reason "why" [--force] [--actor NAME]
  python scripts/paper_run_admin.py audit [--run-id r00012]

``close`` asks the broker about every order of the run.  If any order is still unsettled (open,
partly working, unknown status) or cannot be verified (lookup error / no API credentials) the close
is refused (exit code 2) unless --force is given.  Every close and every refused close is written
to the audit log.  After a close the next submission opens a NEW run id (all order ids change).

API credentials are read only from ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET and never
printed.  The run database is QUANT_PAPER_RUN_DB or data/paper_runs.db (override with --db).

Exit codes: 0 ok, 1 usage/lookup error (unknown run, already closed, empty reason), 2 refused.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.paper_execution import (  # noqa: E402
    AlpacaPaperBroker, RunCloseError, RunCloseRefused, RunStore, _short,
)

EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    """Run row without the raw broker account id (only its short hash, as used in client_order_id)."""
    out = {k: v for k, v in row.items() if k != "account"}
    out["account_hash"] = _short(row["account"])
    return out


def _print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(no runs)")
        return
    header = f"{'run_id':<8} {'status':<7} {'acct':<9} {'orders':>6}  {'created_at':<19}  {'closed_at':<19}  version / close reason"
    print(header)
    for r in rows:
        tail = r["strategy_version"]
        if r["status"] == "closed":
            how = "FORCED " if r["forced"] else ""
            tail += f"  | {how}{r['close_action'] or 'closed(no audit)'}: {r['close_reason'] or '-'} [{r['closed_by'] or '-'}]"
        print(f"{r['run_id']:<8} {r['status']:<7} {r['account_hash']:<9} {r['n_orders']:>6}  "
              f"{str(r['created_at']):<19}  {str(r['closed_at'] or '-'):<19}  {tail}")


def cmd_list(store: RunStore, args: argparse.Namespace) -> int:
    status = None if args.status == "all" else args.status
    rows = [_public_row(r) for r in store.list_runs(status=status, limit=args.limit)]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        _print_table(rows)
    return EXIT_OK


def cmd_close(store: RunStore, args: argparse.Namespace, broker: Any) -> int:
    if broker is None:
        try:
            broker = AlpacaPaperBroker.from_env()
        except ValueError:
            broker = None
            print("WARNING: no paper API credentials in the environment -- broker state cannot be verified; "
                  "the close needs --force.", file=sys.stderr)
    try:
        result = store.manual_close(args.run_id, args.reason, broker=broker, force=args.force, actor=args.actor)
    except RunCloseRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        for r in exc.check["orders"]:
            print(f"  {r['client_order_id']}  {r['symbol']:<6} {r['side']:<4} {r['state']:<12} "
                  f"{r.get('broker_status') or r.get('detail') or ''}", file=sys.stderr)
        return EXIT_REFUSED
    except (RunCloseError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if result["forced"]:
        print(f"WARNING: closed with --force despite {len(result['warnings'])} unconfirmed order(s):")
        for w in result["warnings"]:
            print(f"  {w['client_order_id']}  {w['symbol']}  {w['state']}  {w.get('broker_status') or w.get('detail') or ''}")
    print(f"closed {result['run_id']} (reason: {result['reason']}); the next submission opens a new run id.")
    return EXIT_OK


def cmd_audit(store: RunStore, args: argparse.Namespace) -> int:
    try:
        rows = store.audit_log(args.run_id)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", help="run database path (default: QUANT_PAPER_RUN_DB or data/paper_runs.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list execution runs, newest first")
    p_list.add_argument("--status", choices=["open", "closed", "all"], default="all")
    p_list.add_argument("--limit", type=int)
    p_list.add_argument("--json", action="store_true")

    p_close = sub.add_parser("close", help="manually close an open run (audited)")
    p_close.add_argument("--run-id", required=True, help="e.g. r00012")
    p_close.add_argument("--reason", required=True, help="why this run is being closed (recorded in the audit log)")
    p_close.add_argument("--force", action="store_true", help="close even if the broker shows unsettled/unverifiable orders")
    p_close.add_argument("--actor", default="cli", help="who is closing it (recorded in the audit log)")

    p_audit = sub.add_parser("audit", help="show the close / refused-close audit log")
    p_audit.add_argument("--run-id")
    return parser


def main(argv: list[str] | None = None, *, broker: Any = None) -> int:
    args = build_parser().parse_args(argv)
    store = RunStore(args.db)
    if args.command == "list":
        return cmd_list(store, args)
    if args.command == "close":
        return cmd_close(store, args, broker)
    return cmd_audit(store, args)


if __name__ == "__main__":
    sys.exit(main())
