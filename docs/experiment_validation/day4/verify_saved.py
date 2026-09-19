"""Independent saved-file reconciliation. Audit PASS does not mean Day 4 PASS."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    inputs = json.loads((ROOT / "input_manifest.json").read_text())
    for rel, value in inputs["derived_files"].items():
        assert digest(ROOT / rel) == value, rel
    prior = json.loads((BASE / "day3/result_hashes.json").read_text())
    for rel, value in prior["artifacts"].items():
        assert digest(BASE / rel) == value, rel
    detail = pd.read_csv(ROOT / "member_coverage.csv.gz", keep_default_na=False)
    coverage = pd.read_csv(ROOT / "rebalance_coverage.csv")
    membership = pd.read_csv(BASE / "data/sp500_historical_constituents.csv.gz")
    schedule = pd.read_csv(BASE / "day2/XNYS_sessions.csv.gz", index_col="session")
    for p in coverage.itertuples():
        group = detail[detail.fill_session == p.fill_session]
        prior_rows = membership[membership.date <= p.signal_session]
        expected_ids = sorted(s.strip() for s in prior_rows.iloc[-1].tickers.split(",") if s.strip())
        assert sorted(group.raw_identifier.tolist()) == expected_ids
        assert len(group) == p.members
        assert group.membership_snapshot_date.nunique() == 1
        assert group.membership_snapshot_date.iloc[0] == prior_rows.iloc[-1].date
        pos = schedule.index.get_loc(p.fill_session)
        assert schedule.index[pos - 1] == p.signal_session
        assert pd.Timestamp(schedule.loc[p.signal_session, "close"]) == pd.Timestamp(p.signal_close_utc)
        assert pd.Timestamp(schedule.loc[p.fill_session, "open"]) == pd.Timestamp(p.fill_open_utc)
    # Independent backward as-of join, rather than reusing diagnostic_shares.
    obs = pd.read_csv(ROOT / "share_observations.csv.gz", parse_dates=["observation_date"])
    obs = obs.rename(columns={"ticker": "cache_ticker_hint"})
    left = detail.copy()
    left["signal_date"] = pd.to_datetime(left.signal_session)
    merged = pd.merge_asof(left.sort_values("signal_date"), obs.sort_values("observation_date"),
                          left_on="signal_date", right_on="observation_date", by="cache_ticker_hint", direction="backward")
    observed = merged.observation_date.notna()
    assert (merged.loc[observed, "share_state"] == "dated_prior_observation_only").all()
    assert np.allclose(merged.loc[observed, "share_dated_value"].astype(float), merged.loc[observed, "shares"], rtol=0, atol=0)
    assert (merged.loc[observed, "share_dated_observation"] == merged.loc[observed, "observation_date"].dt.strftime("%Y-%m-%d")).all()
    first = obs.groupby("cache_ticker_hint").observation_date.min()
    first_for_row = merged.cache_ticker_hint.map(first)
    future_only = ~observed & first_for_row.notna()
    assert (first_for_row[future_only] > merged.loc[future_only, "signal_date"]).all()
    assert (merged.loc[future_only, "share_state"] == "future_only").all()
    assert (merged.loc[~observed & ~future_only, "share_state"] == "empty_or_missing").all()
    assert (merged.loc[~observed, "share_dated_value"] == "").all()
    assert not detail.pit_eligible.any()
    for field in ["membership_publication_verified", "historical_sector_verified", "share_publication_verified",
                  "security_identity_and_units_verified", "delisting_and_full_price_path_verified"]:
        assert not detail[field].any()
    result = json.loads((ROOT / "audit_results.json").read_text())
    assert result["member_boundary_rows"] == len(detail) == coverage.members.sum()
    assert result["member_boundary_share_states"] == detail.share_state.value_counts().to_dict()
    assert result["certified_common_sessions"] == result["certified_rebalances"] == 0
    assert result["day4_status"] == "BLOCKED" and result["day4_complete"] is False
    comparison = pd.read_csv(ROOT / "s1_s6_common_comparison.csv")
    assert len(comparison) == 6
    assert set(zip(comparison["sample"], comparison.cost_bps)) == {(s, c) for s in ("actual_17", "proxy_17") for c in (5, 10, 25)}
    assert comparison[["s1_cagr", "s6_cagr", "calmar_difference"]].isna().all().all()
    assert (comparison.common_sessions == 0).all() and (comparison.status == "NOT_EVALUABLE").all()
    assert all(r["non_next_session"] == r["wrong_signal_close"] == r["wrong_fill_open"] == 0 for r in result["s1_saved_order_checks"])
    assert all(r["max_fee_error"] < 1e-12 for r in result["s1_saved_order_checks"])
    for file in (BASE / "PROGRESS.md", BASE.parent.parent / "PROGRESS.md"):
        assert "DAY_4_COMPLETE" not in file.read_text().splitlines(), "premature Day 4 completion marker"
    return {"saved_audit_consistency": "PASS", "day4_status": "BLOCKED", "day4_complete": False,
            "verified_at_utc": datetime.now(timezone.utc).isoformat(), "prior_evidence_verified": len(prior["artifacts"]),
            "rebalance_boundaries_verified": len(coverage), "member_rows_independently_reconciled": len(detail),
            "backward_asof_share_rows": int(observed.sum()), "future_only_share_rows": int(future_only.sum()),
            "missing_share_rows": int((~observed & ~future_only).sum()), "s1_saved_orders_checked": sum(r["orders"] for r in result["s1_saved_order_checks"]),
            "comparison_rows_not_evaluable": len(comparison), "frozen_data_inventory_sha256": result["frozen_data_inventory_sha256"],
            "diagnostic_input_inventory_sha256": result["diagnostic_input_inventory_sha256"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    result = verify()
    print(json.dumps(result, indent=2))
    if args.require_complete:
        raise SystemExit(2 if not result["day4_complete"] else 0)
