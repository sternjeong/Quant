"""Offline adversarial checks: no broker/provider imports or requests."""
import copy
import pandas as pd
import pytest

from audit_contract import (AuditError, boundaries, cache_ticker, diagnostic_members,
                            diagnostic_shares, verify_blocked_result)
from probe_legacy import run_probes


def calendar():
    idx = pd.to_datetime(["2020-06-30", "2020-07-01", "2020-07-02"])
    return pd.DataFrame({"open": [f"{d:%Y-%m-%d}T13:30:00Z" for d in idx],
                         "close": [f"{d:%Y-%m-%d}T20:00:00Z" for d in idx]}, index=idx)


def test_boundary_uses_previous_exchange_close_not_fill_day_information():
    result = boundaries(calendar(), "2020-01-01", "2020-12-31")
    assert len(result) == 1
    assert result[0]["signal_session"] == "2020-06-30"
    assert result[0]["fill_session"] == "2020-07-01"
    assert pd.Timestamp(result[0]["signal_close_utc"]) < pd.Timestamp(result[0]["fill_open_utc"])


def test_boundary_never_creates_midmonth_rebalance_when_requested_start_is_midmonth():
    assert boundaries(calendar(), "2020-07-02", "2020-12-31") == []


def test_boundary_requires_previous_session_and_timezone():
    with pytest.raises(AuditError, match="missing_previous"):
        boundaries(calendar().iloc[1:])
    schedule = calendar()
    schedule.iloc[0, 1] = "2020-06-30T20:00:00"
    with pytest.raises(AuditError, match="timestamps"):
        boundaries(schedule)


def test_membership_does_not_fallback_to_future_or_use_fill_date_addition():
    table = pd.DataFrame({"date": pd.to_datetime(["2020-06-30", "2020-07-01"]), "tickers": ["OLD", "FUTURE"]})
    assert diagnostic_members(table, "2020-06-30")[1] == ["OLD"]
    with pytest.raises(AuditError, match="no_prior"):
        diagnostic_members(table, "2020-06-29")


def test_raw_identity_is_preserved_despite_legacy_alias_collision():
    table = pd.DataFrame({"date": pd.to_datetime(["2010-01-01"]), "tickers": ["CEG-201203,CEG,BRK.B"]})
    assert diagnostic_members(table, "2010-01-04")[1] == ["BRK.B", "CEG", "CEG-201203"]
    assert cache_ticker("CEG") == cache_ticker("CEG-201203")
    assert cache_ticker("BRK.B") == "BRK-B"


def test_ambiguous_membership_dates_rejected():
    table = pd.DataFrame({"date": pd.to_datetime(["2010-01-01", "2010-01-01"]), "tickers": ["A", "B"]})
    with pytest.raises(AuditError, match="ambiguous"):
        diagnostic_members(table, "2010-01-04")


def test_future_shares_never_produce_market_cap_input():
    series = pd.Series([1000.], index=pd.to_datetime(["2022-01-01"]))
    result = diagnostic_shares(series, "2010-01-04")
    assert result == {"state": "future_only", "observation_date": None, "value": None}


def test_future_mutation_cannot_change_previous_dated_share_observation():
    series = pd.Series([100., 1000.], index=pd.to_datetime(["2010-01-01", "2022-01-01"]))
    before = diagnostic_shares(series, "2010-01-04")
    series.iloc[-1] = 1e20
    assert diagnostic_shares(series, "2010-01-04") == before
    assert before["state"] == "dated_prior_observation_only"  # Never means published/PIT.


@pytest.mark.parametrize("value", [0., -1., float("inf"), float("nan")])
def test_invalid_shares_are_not_eligible(value):
    series = pd.Series([value], index=pd.to_datetime(["2010-01-01"]))
    assert diagnostic_shares(series, "2010-01-04")["value"] is None


def blocked_fixture():
    result = {"certified_rebalances": 0, "certified_common_sessions": 0, "day4_status": "BLOCKED", "day4_complete": False}
    rows = [{"sample": sample, "cost_bps": cost, "status": "NOT_EVALUABLE", "common_sessions": 0,
             "s1_cagr": None, "s6_cagr": None, "calmar_difference": None}
            for sample in ("actual_17", "proxy_17") for cost in (5, 10, 25)]
    return result, pd.DataFrame(rows)


def test_no_coverage_is_not_completion_even_when_code_tests_pass():
    result, table = blocked_fixture()
    assert verify_blocked_result(result, table)
    for field, bad in [("day4_complete", True), ("day4_status", "PASS")]:
        changed = copy.deepcopy(result)
        changed[field] = bad
        with pytest.raises(AuditError, match="false_completion"):
            verify_blocked_result(changed, table)


def test_no_coverage_is_not_zero_return_or_duplicate_comparison():
    result, table = blocked_fixture()
    table.loc[0, "s6_cagr"] = 0.
    with pytest.raises(AuditError, match="fabricated"):
        verify_blocked_result(result, table)
    _, table = blocked_fixture()
    table.loc[0, "sample"] = "proxy_17"
    with pytest.raises(AuditError, match="missing_comparison"):
        verify_blocked_result(result, table)


def test_isolated_existing_functions_reproduce_sector_future_and_execution_defects():
    probes = run_probes()
    assert probes["current_sector_mutation"] == {"before": ["A", "C"], "after": ["A", "B"]}
    assert probes["selection_calls_market_cap_on_fill_date"] == ["2020-07-01"]
    assert probes["fill_day_close_leak"]["fill_day_close_cap"] > probes["fill_day_close_leak"]["signal_close_cap"]
    assert probes["earliest_future_members"] == ["FUTURE"]
    assert probes["earliest_future_shares_cap"] == 10000
    assert probes["close_approximation_return"] == pytest.approx(.1)
    assert probes["exact_next_open_return"] == pytest.approx(110 / 109 - 1)
