"""Offline diagnostic helpers; no provider, trading or production imports."""
from __future__ import annotations

import re
import pandas as pd


class AuditError(ValueError):
    pass


def cache_ticker(raw):
    """Legacy lookup hint only. The raw identifier remains the audit key."""
    return re.sub(r"-\d{6}$", "", raw.strip()).replace(".", "-")


def boundaries(schedule, start="2007-01-01", end="2026-09-17"):
    """First Jan/Jul session, with the previous actual exchange session close."""
    if not schedule.index.is_unique or not schedule.index.is_monotonic_increasing:
        raise AuditError("invalid_calendar")
    rows = []
    for _, month in schedule.groupby(schedule.index.to_period("M")):
        fill = month.index[0]
        if fill.month not in (1, 7) or not pd.Timestamp(start) <= fill <= pd.Timestamp(end):
            continue
        pos = schedule.index.get_loc(fill)
        if pos == 0:
            raise AuditError("missing_previous_signal_session")
        signal = schedule.index[pos - 1]
        signal_close, fill_open = pd.Timestamp(schedule.loc[signal, "close"]), pd.Timestamp(month.iloc[0]["open"])
        if signal_close.tzinfo is None or fill_open.tzinfo is None or signal_close >= fill_open:
            raise AuditError("invalid_signal_fill_timestamps")
        rows.append({"fill_session": str(fill.date()), "signal_session": str(signal.date()),
                     "signal_close_utc": signal_close.isoformat(), "fill_open_utc": fill_open.isoformat()})
    return rows


def diagnostic_members(table, signal):
    """Date-only membership is useful for gap inventory, NOT PIT certification."""
    if not table.date.is_monotonic_increasing or not table.date.is_unique:
        raise AuditError("ambiguous_membership_dates")
    eligible = table[table.date <= pd.Timestamp(signal)]
    if eligible.empty:
        raise AuditError("no_prior_membership_snapshot")
    row = eligible.iloc[-1]
    raw = [t.strip() for t in row.tickers.split(",") if t.strip()]
    if len(raw) != len(set(raw)):
        raise AuditError("duplicate_raw_identifier")
    return str(row.date.date()), sorted(raw)


def diagnostic_shares(series, signal):
    """Observation date only, not a publication timestamp or certified shares."""
    if series.empty:
        return {"state": "empty_or_missing", "observation_date": None, "value": None}
    prior = series[series.index <= pd.Timestamp(signal)]
    if prior.empty:
        return {"state": "future_only", "observation_date": None, "value": None}
    if not prior.index.is_unique:
        return {"state": "duplicate_observation_dates", "observation_date": None, "value": None}
    value = float(prior.iloc[-1])
    if not pd.notna(value) or value <= 0 or value == float("inf"):
        return {"state": "invalid_value", "observation_date": None, "value": None}
    return {"state": "dated_prior_observation_only", "observation_date": str(prior.index[-1].date()), "value": value}


def verify_blocked_result(result, comparison):
    """Prevent an empty common sample or passing code tests becoming Day 4 PASS."""
    if result["certified_rebalances"] != 0 or result["certified_common_sessions"] != 0:
        raise AuditError("not_a_blocked_zero_coverage_audit")
    if result["day4_status"] != "BLOCKED" or result["day4_complete"] is not False:
        raise AuditError("false_completion")
    expected = {(sample, cost) for sample in ("actual_17", "proxy_17") for cost in (5, 10, 25)}
    if len(comparison) != 6 or set(zip(comparison["sample"], comparison.cost_bps)) != expected:
        raise AuditError("missing_comparison_cases")
    if not (comparison.status == "NOT_EVALUABLE").all() or not (comparison.common_sessions == 0).all():
        raise AuditError("empty_sample_not_marked")
    if not comparison[["s1_cagr", "s6_cagr", "calmar_difference"]].isna().all().all():
        raise AuditError("fabricated_performance")
    return True
