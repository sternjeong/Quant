"""Adversarial Day 2 guards: timing, future data, missing prices, proxy seams."""
import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_contract import (DataContractError, adjusted_open, latest_known,
                           market_cap_asof, next_open_order, require_prices, splice_at_open)
from run_audit import load_prices, load_schedule

ROOT = Path(__file__).resolve().parent
SIGNAL = "2019-12-31T21:00:00Z"


def record(value=1000, effective="2019-12-30T20:00:00Z", available="2019-12-30T20:00:00Z", basis="pre-split"):
    return dict(value=value, effective_at=effective, available_at=available, unit_basis=basis)


def bars(dates, values):
    frame = pd.DataFrame({c: values for c in ["Open", "High", "Low", "Close", "Adj Close"]}, index=pd.to_datetime(dates))
    frame["Volume"] = 100
    return frame


def reference(name, filename, stubs):
    tree = ast.parse((ROOT.parent / "source" / filename).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    namespace = {"pd": pd, **stubs}
    exec(compile(ast.fix_missing_locations(module), filename, "exec"), namespace)
    return namespace[name]


def test_reference_future_shares_defect_reproduced_and_research_guard_rejects():
    legacy = reference("get_market_cap_asof", "point_in_time_market_cap.py", {
        "get_shares_outstanding_history": lambda *a, **k: pd.Series([1000.], index=pd.to_datetime(["2020-01-02"])),
        "_cumulative_split_factor_after": lambda *a, **k: 1.,
        "get_price_history": lambda *a, **k: pd.DataFrame({"Close": [10.]}, index=pd.to_datetime(["2019-12-31"])),
    })
    assert legacy("TEST", "2019-12-31") == 10000
    with pytest.raises(DataContractError, match="no_point_in_time_record"):
        market_cap_asof([record(effective="2020-01-02T15:00Z", available="2020-01-02T15:00Z")], record(value=10), SIGNAL)


def test_future_extreme_share_values_cannot_change_historical_market_cap():
    past = record()
    future = record(value=1e15, effective="2020-01-02T15:00Z", available="2020-01-02T15:00Z")
    assert market_cap_asof([future, past], record(value=10), SIGNAL) == 10000


@pytest.mark.parametrize("available", [None, "2019-12-30", "2020-01-02T15:00Z"])
def test_unknown_naive_or_late_publication_rejected(available):
    with pytest.raises(DataContractError):
        market_cap_asof([record(available=available)], record(value=10), SIGNAL)


def test_future_price_and_inconsistent_split_units_rejected():
    with pytest.raises(DataContractError, match="no_point_in_time_record"):
        market_cap_asof([record()], record(value=10, available="2020-01-02T15:00Z"), SIGNAL)
    with pytest.raises(DataContractError, match="inconsistent_share_units"):
        market_cap_asof([record()], record(value=10, basis="post-split"), SIGNAL)


def test_missing_and_ambiguous_membership_never_fall_back_to_future():
    for records in ([], [record(effective="2020-01-02T15:00Z", available="2020-01-02T15:00Z")], [record(), record(value=999)]):
        with pytest.raises(DataContractError):
            latest_known(records, SIGNAL)


@pytest.mark.parametrize("bad", [np.nan, np.inf, 0., -1.])
def test_invalid_open_is_not_replaced_by_close(bad):
    frame = bars(["2020-01-02"], [100.])
    frame.loc[pd.Timestamp("2020-01-02"), "Open"] = bad
    with pytest.raises(DataContractError):
        require_prices(frame, frame.index)


def test_missing_next_open_does_not_skip_to_next_available_price():
    schedule = load_schedule()
    prices = bars(["2020-01-02", "2020-01-06"], [100., 110.])
    with pytest.raises(DataContractError, match="missing_price_session"):
        next_open_order("2020-01-02", schedule, prices)


def test_gap_sensitive_fill_is_different_from_reference_close_to_close():
    schedule = load_schedule()
    prices = bars(["2020-01-02", "2020-01-03"], [100., 110.])
    prices.loc[pd.Timestamp("2020-01-03"), "Open"] = 109.
    order = next_open_order("2020-01-02", schedule, prices)
    assert order["fill_session"] == "2020-01-03"
    assert order["provider_open"] == 109.
    legacy = reference("_compute_portfolio_returns", "champion_strategy.py", {"BACKTEST_COST_BPS_PER_SIDE": 5.})
    close = prices[["Close"]].rename(columns={"Close": "TEST"})
    weights = close * 0 + 1.
    old = float(legacy(close, weights, cost_bps_per_side=0)["ret_net"].iloc[1])
    assert old == pytest.approx(.1)
    assert 110 / order["provider_open"] - 1 == pytest.approx(.00917431192660545)
    assert abs(old - (110 / order["provider_open"] - 1)) > .09


@pytest.mark.parametrize("signal,fill,utc_hour", [("2024-03-08", "2024-03-11", 13), ("2024-11-01", "2024-11-04", 14), ("2024-11-29", "2024-12-02", 14), ("2025-01-08", "2025-01-10", 14)])
def test_weekend_dst_early_close_and_special_holiday(signal, fill, utc_hour):
    order = next_open_order(signal, load_schedule(), bars([fill], [100.]))
    assert order["fill_session"] == fill
    assert pd.Timestamp(order["fill_open_utc"]).hour == utc_hour
    if signal == "2024-11-29":
        assert pd.Timestamp(order["signal_close_utc"]).hour == 18


def test_actual_zero_volume_fill_is_rejected():
    prices = load_prices(ROOT.parent / "data/XLRE.csv.gz")
    with pytest.raises(DataContractError, match="zero_volume"):
        next_open_order("2015-10-13", load_schedule(), prices)


def test_adjusted_open_preserves_intraday_ratio_without_double_dividend():
    prices = bars(["2020-01-02"], [100.])
    prices["Adj Close"] = 80.
    prices["Open"] = 90.
    assert adjusted_open(prices).iloc[0] == 72.
    assert prices["Adj Close"].iloc[0] / adjusted_open(prices).iloc[0] == pytest.approx(100 / 90)


def test_splice_uses_proxy_overnight_actual_intraday_and_no_future_backscale():
    proxy = bars(["2015-10-07", "2015-10-08", "2015-10-09"], [100., 110., 111.])
    actual = bars(["2015-10-08", "2015-10-09"], [55., 60.])
    proxy.loc[pd.Timestamp("2015-10-08"), "Open"] = 102.
    actual.loc[pd.Timestamp("2015-10-08"), "Open"] = 50.
    result = splice_at_open(proxy, actual, "2015-10-08")
    assert result["Adj Close"].iloc[0] == 100.
    assert result["Adj Close"].iloc[1] / 100 == pytest.approx(1.02 * 1.10)
    actual.loc[pd.Timestamp("2015-10-09"), "Adj Close"] = 1e9
    changed = splice_at_open(proxy, actual, "2015-10-08")
    pd.testing.assert_frame_equal(result.iloc[:2], changed.iloc[:2])


def test_real_splice_does_not_bridge_unrelated_etf_price_levels():
    proxy = load_prices(ROOT / "VNQ.csv.gz")
    actual = load_prices(ROOT.parent / "data/XLRE.csv.gz")
    result = splice_at_open(proxy, actual, "2015-10-08")
    expected = (adjusted_open(proxy).loc["2015-10-08"] / proxy.loc["2015-10-07", "Adj Close"]
                * actual.loc["2015-10-08", "Close"] / actual.loc["2015-10-08", "Open"])
    assert result.loc["2015-10-08", "Adj Close"] / result.loc["2015-10-07", "Adj Close"] == pytest.approx(expected)
