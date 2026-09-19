"""Audit captured Day 4 evidence offline. Never executes S6 or writes completion."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from audit_contract import cache_ticker, diagnostic_members, diagnostic_shares, verify_blocked_result
from probe_legacy import run_probes

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "input_manifest.json").read_text())
    for name, expected in manifest["derived_files"].items():
        assert sha(ROOT / name) == expected, name
    previous = json.loads((BASE / "day3/result_hashes.json").read_text())
    for name, expected in previous["artifacts"].items():
        assert sha(BASE / name) == expected, name
    table = pd.read_csv(BASE / "data/sp500_historical_constituents.csv.gz", parse_dates=["date"])
    dates = pd.read_csv(ROOT / "rebalance_boundaries.csv").to_dict("records")
    inventory = pd.read_csv(ROOT / "cache_inventory.csv").fillna("")
    inventory_map = {(r["kind"], r["ticker"]): r for r in inventory.to_dict("records")}
    share_data = pd.read_csv(ROOT / "share_observations.csv.gz", parse_dates=["observation_date"])
    shares = {t: g.set_index("observation_date").shares for t, g in share_data.groupby("ticker")}
    prices = pd.read_csv(ROOT / "price_boundary_observations.csv.gz")
    price_map = {(r["ticker"], r["fill_session"]): r for r in prices.to_dict("records")}
    sector = pd.read_csv(ROOT / "current_sector_snapshot.csv")
    assert not {"available_at", "effective_at"}.issubset(sector.columns), "new PIT evidence: review before continuing"
    assert not inventory.has_available_at.any(), "new publication metadata: review before continuing"
    sector_map = sector.set_index("Symbol").Sector.to_dict()
    aliases = pd.read_csv(ROOT / "identifier_map.csv")
    alias_counts = Counter(aliases.cache_ticker_hint)
    rows, periods = [], []
    for d in dates:
        snapshot, ids = diagnostic_members(table, d["signal_session"])
        block = []
        for raw in ids:
            ticker = cache_ticker(raw)
            obs = diagnostic_shares(shares.get(ticker, pd.Series(dtype=float)), d["signal_session"])
            share_cache, price_cache = inventory_map[("shares", ticker)], inventory_map[("price", ticker)]
            price = price_map.get((ticker, d["fill_session"]), {})
            row = {**d, "membership_snapshot_date": snapshot, "raw_identifier": raw, "cache_ticker_hint": ticker,
                   "multiple_raw_ids_share_ticker": alias_counts[ticker] > 1,
                   "sector_in_current_cache": ticker in sector_map,
                   "current_sector_diagnostic_only": sector_map.get(ticker, ""),
                   "share_cache_exists": share_cache["exists"], "share_cache_rows": share_cache["rows"],
                   "share_first_observation": share_cache["first_date"], "share_state": obs["state"],
                   "share_dated_observation": obs["observation_date"], "share_dated_value": obs["value"],
                   "would_use_future_share_fallback": obs["state"] == "future_only",
                   "price_cache_exists": price_cache["exists"], "price_cache_rows": price_cache["rows"],
                   "price_first_date": price_cache["first_date"], "price_last_date": price_cache["last_date"],
                   "signal_close_in_cache": pd.notna(price.get("signal_close")) and price.get("signal_close", 0) > 0,
                   "fill_open_in_cache": pd.notna(price.get("fill_open")) and price.get("fill_open", 0) > 0,
                   "membership_publication_verified": False, "historical_sector_verified": False,
                   "share_publication_verified": False, "security_identity_and_units_verified": False,
                   "delisting_and_full_price_path_verified": False, "pit_eligible": False}
            rows.append(row)
            block.append(row)
        counts = Counter(r["share_state"] for r in block)
        periods.append({**d, "membership_snapshot_date": snapshot, "members": len(ids),
                        "missing_or_empty_shares": counts["empty_or_missing"], "future_only_shares": counts["future_only"],
                        "dated_prior_shares_without_publication": counts["dated_prior_observation_only"],
                        "not_in_current_sector_cache": sum(not r["sector_in_current_cache"] for r in block),
                        "missing_cached_signal_close": sum(not r["signal_close_in_cache"] for r in block),
                        "missing_cached_fill_open": sum(not r["fill_open_in_cache"] for r in block),
                        "ambiguous_ticker_members": sum(r["multiple_raw_ids_share_ticker"] for r in block),
                        "certified_members": 0, "status": "BLOCKED_INPUT_PROVENANCE"})
    detail = pd.DataFrame(rows)
    detail.to_csv(ROOT / "member_coverage.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    pd.DataFrame(periods).to_csv(ROOT / "rebalance_coverage.csv", index=False)
    aliases[aliases.cache_ticker_hint.map(alias_counts) > 1].to_csv(ROOT / "ambiguous_identifiers.csv", index=False)
    # Reuse saved S1 accounts: inspect timing and costs, never rerun Day 3.
    schedule = pd.read_csv(BASE / "day2/XNYS_sessions.csv.gz", index_col="session")
    next_session = dict(zip(schedule.index[:-1], schedule.index[1:]))
    comparison, s1checks = [], []
    for sample in ("actual_17", "proxy_17"):
        for cost in (5, 10, 25):
            stem = BASE / "day3" / f"{sample}__S1__{cost}bp"
            daily_path, order_path = Path(str(stem) + ".daily.csv.gz"), Path(str(stem) + ".orders.csv.gz")
            daily, orders = pd.read_csv(daily_path), pd.read_csv(order_path)
            timing_errors = sum(next_session.get(r.signal_session) != r.fill_session for r in orders.itertuples())
            close_errors = sum(pd.Timestamp(r.signal_close_utc) != pd.Timestamp(schedule.loc[r.signal_session, "close"]) for r in orders.itertuples())
            open_errors = sum(pd.Timestamp(r.fill_open_utc) != pd.Timestamp(schedule.loc[r.fill_session, "open"]) for r in orders.itertuples())
            fee_error = float((orders.fee - orders.signed_notional.abs() * cost / 10000).abs().max())
            assert timing_errors == close_errors == open_errors == 0 and fee_error < 1e-12
            s1checks.append({"sample": sample, "cost_bps": cost, "orders": len(orders), "non_next_session": timing_errors,
                             "wrong_signal_close": close_errors, "wrong_fill_open": open_errors, "max_fee_error": fee_error,
                             "daily_sha256": sha(daily_path), "orders_sha256": sha(order_path)})
            comparison.append({"sample": sample, "cost_bps": cost, "s1_saved_return_sessions": len(daily) - 1,
                               "s1_first_return_session": daily.session.iloc[1], "s1_last_session": daily.session.iloc[-1],
                               "s6_certified_sessions": 0, "common_sessions": 0, "status": "NOT_EVALUABLE",
                               "s1_cagr": None, "s6_cagr": None, "calmar_difference": None,
                               "reason": "no_certified_s6_input_panel"})
    comparison = pd.DataFrame(comparison)
    comparison.to_csv(ROOT / "s1_s6_common_comparison.csv", index=False)
    probes = run_probes()
    write_json(ROOT / "legacy_probes.json", probes)
    result = {"day": 4, "day4_status": "BLOCKED", "day4_complete": False,
              "audited_at_utc": datetime.now(timezone.utc).isoformat(),
              "prior_artifacts_verified": len(previous["artifacts"]),
              "frozen_data_inventory_sha256": previous["data_inventory_sha256"],
              "diagnostic_input_inventory_sha256": manifest["derived_inventory_sha256"],
              "historical_membership_rows": len(table), "membership_first_date": str(table.date.min().date()),
              "membership_last_date": str(table.date.max().date()), "membership_columns": table.columns.tolist(),
              "rebalance_boundaries": len(dates), "member_boundary_rows": len(detail),
              "raw_identifiers": len(aliases), "cache_ticker_hints": len(alias_counts),
              "ambiguous_cache_ticker_hints": sum(n > 1 for n in alias_counts.values()),
              "cache_inventory_counts": {k: {"expected": len(g), "existing": int(g.exists.sum()),
                    "nonempty": int((g.rows > 0).sum()), "publication_timestamp_columns": int(g.has_available_at.sum())}
                    for k, g in inventory.groupby("kind")},
              "member_boundary_share_states": detail.share_state.value_counts().to_dict(),
              "member_boundary_missing_current_sector": int((~detail.sector_in_current_cache).sum()),
              "member_boundary_missing_cached_signal_close": int((~detail.signal_close_in_cache).sum()),
              "member_boundary_missing_cached_fill_open": int((~detail.fill_open_in_cache).sum()),
              "certified_rebalances": 0, "certified_common_sessions": 0, "s6_orders_executed": 0,
              "s6_same_day_close_fill_audit": "NOT_RUN_NO_CERTIFIED_INPUTS",
              "s1_saved_order_checks": s1checks,
              "pass_conditions": {"pit_universe_and_ranking_inputs_certified": False,
                     "s6_next_open_costed_replay": False, "s1_common_date_comparison": False},
              "blockers": ["D4-P1: membership dates lack historical availability and revision evidence",
                           "D4-P2: current sectors cannot certify historical sector quotas",
                           "D4-P3: share observations lack publication time and verified price/share units",
                           "D4-P4: ticker reuse/delisted security identity and full price paths unverified"],
              "selection": "No ranking or S6 replacement decision; six candidates and all gates unchanged"}
    verify_blocked_result(result, comparison)
    write_json(ROOT / "audit_results.json", result)
    print(json.dumps({k: result[k] for k in ["day4_status", "rebalance_boundaries", "member_boundary_rows", "raw_identifiers", "certified_rebalances", "member_boundary_share_states"]}))
    if args.require_complete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
