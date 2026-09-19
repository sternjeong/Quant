"""Analytical account examples and adversarial timing tests, all synthetic/offline."""
import numpy as np
import pandas as pd
import pytest

from backtest import (BASELINES, FIVE, UNIVERSE, DataContractError, Panel, metrics,
                      month_ends, rebalance, signal_plan, simulate, target_at)
from validate_results import validate_run


def panel(opens, closes, sources=None, raw_extra=None):
    dates = pd.bdate_range("2020-01-31", periods=len(opens))
    cols = ["A", "B"][:len(opens[0])]
    op = pd.DataFrame(opens, index=dates, columns=cols, dtype=float)
    cl = pd.DataFrame(closes, index=dates, columns=cols, dtype=float)
    schedule = pd.DataFrame({"open": pd.to_datetime([f"{d:%Y-%m-%d}T14:30:00Z" for d in dates]),
                             "close": pd.to_datetime([f"{d:%Y-%m-%d}T21:00:00Z" for d in dates])}, index=dates)
    raw = {c: pd.DataFrame({"Open": op[c], "High": np.maximum(op[c], cl[c]),
                            "Low": np.minimum(op[c], cl[c]), "Close": cl[c],
                            "Adj Close": cl[c], "Volume": 10.0}, index=dates) for c in cols}
    if raw_extra:
        raw.update(raw_extra)
    src = pd.DataFrame([cols] * len(dates), index=dates, columns=cols) if sources is None else sources
    return Panel(op, cl, src, raw, schedule, cols)


@pytest.mark.parametrize("cost", [5, 10, 25])
def test_next_open_entry_does_not_earn_overnight_gap(cost):
    p = panel([[100], [109]], [[100], [110]])
    ledger, orders = simulate(p, {p.closes.index[0]: np.array([1.])}, cost)
    assert ledger.nav.iloc[-1] == pytest.approx(110 / 109 / (1 + cost / 10000))
    assert ledger.gap_pnl.iloc[-1] == 0
    assert orders.provider_open.iloc[0] == 109
    assert orders.signal_session.iloc[0] < orders.fill_session.iloc[0]
    assert ledger.nav.iloc[-1] != pytest.approx(1.1)


def test_old_holdings_earn_gap_before_rotation_and_both_legs_pay():
    p = panel([[100, 100], [100, 100], [120, 200]], [[100, 100], [100, 100], [120, 200]])
    dates = p.closes.index
    ledger, orders = simulate(p, {dates[0]: np.array([1., 0]), dates[1]: np.array([0., 1])}, 25)
    c = .0025
    assert ledger.nav.iloc[-1] == pytest.approx(1.2 * (1-c) / (1+c)**2)
    assert ledger.gap_pnl.iloc[-1] == pytest.approx(.2 / (1+c))
    last = orders[orders.fill_session == str(dates[-1].date())]
    assert set(last.side) == {"buy", "sell"}
    assert last.fee.sum() == pytest.approx(last.signed_notional.abs().sum() * c)


def test_drift_generates_turnover_even_when_target_is_unchanged():
    values, cash, delta, fee = rebalance([.75, .5], 0, [.5, .5], .001)
    assert abs(delta).sum() == pytest.approx(.25)
    assert fee == pytest.approx(.00025)
    assert cash == pytest.approx(0, abs=1e-14)
    assert values[0] == pytest.approx(values[1])


def test_cash_slots_remain_cash_and_can_liquidate():
    values, cash, _, fee = rebalance([0, 0], 1, [1/3, 0], .0025)
    assert values[0] == pytest.approx(1 / (3 + .0025))
    assert cash == pytest.approx(2 * values[0])
    new, cash_after, _, sell_fee = rebalance(values, cash, [0, 0], .0025)
    assert new.sum() == 0
    assert cash_after == pytest.approx(1 - fee - sell_fee)


def test_proxy_conversion_charges_two_legs_and_keeps_gap():
    p = panel([[100], [100], [110]], [[100], [100], [121]])
    p.sources.iloc[-1, 0] = "NEW"
    old = p.raw["A"].copy()
    old.loc[old.index[-1], ["Open", "High", "Low", "Close", "Adj Close"]] = 110
    p.raw["A"] = old
    new = old.copy()
    new.loc[new.index[-1], ["Open", "Low"]] = 10
    new.loc[new.index[-1], ["High", "Close", "Adj Close"]] = 11
    p.raw["NEW"] = new
    ledger, orders = simulate(p, {p.closes.index[0]: np.array([1.])}, 10)
    assert ledger.nav.iloc[-1] == pytest.approx(1.21 * .999 / 1.001**2)
    switch = orders[orders.reason == "proxy_conversion"]
    assert list(switch.ticker) == ["A", "NEW"]
    assert list(switch.provider_open) == [110, 10]
    assert len(switch) == 2


@pytest.mark.parametrize("failure", ["missing", "zero_volume", "nan_open", "same_time"])
def test_invalid_execution_cannot_fallback_to_close_or_later_open(failure):
    p = panel([[100], [109], [111]], [[100], [110], [112]])
    day = p.closes.index[1]
    if failure == "missing":
        p.raw["A"] = p.raw["A"].drop(day)
    elif failure == "zero_volume":
        p.raw["A"].loc[day, "Volume"] = 0
    elif failure == "nan_open":
        p.raw["A"].loc[day, "Open"] = np.nan
    else:
        p.schedule.loc[day, "open"] = p.schedule.close.iloc[0]
    with pytest.raises(DataContractError):
        simulate(p, {p.closes.index[0]: np.array([1.])}, 5)


def history():
    cols = list(dict.fromkeys(UNIVERSE + FIVE))
    return pd.DataFrame(100., index=pd.bdate_range("2019-01-02", periods=300), columns=cols)


def test_s1_keeps_negative_momentum_and_stable_ties_without_filters():
    h = history()
    h.iloc[-1] = 90
    w, _ = target_at(h, [], "S1", UNIVERSE)
    assert list(w[w > 0].index) == UNIVERSE[:4]
    assert w.sum() == 1


def test_s2_ignores_recent_21_sessions_and_uses_same_252_denominator():
    h = history()
    h.loc[h.index[-253], "XLC"] = 80
    h.loc[h.index[-22], "XLC"] = 120
    w, s = target_at(h, [], "S2", UNIVERSE)
    h.iloc[-21:] *= np.linspace(1, 10000, 21)[:, None]
    w2, s2 = target_at(h, [], "S2", UNIVERSE)
    pd.testing.assert_series_equal(w, w2)
    pd.testing.assert_series_equal(s, s2)
    assert s.XLC == pytest.approx(.5)


def test_s3_and_s5_use_fixed_cash_slots_and_strict_positive_test():
    h = history()
    h.loc[h.index[-1], ["GLD", "EFA"]] = [110, 120]
    w3, _ = target_at(h, [], "S3", UNIVERSE)
    w5, _ = target_at(h, [], "S5", UNIVERSE)
    assert w3.sum() == pytest.approx(2/17)
    assert w5.sum() == pytest.approx(2/3)
    assert w5.IEF == 0


def test_s4_is_ten_month_end_closes_not_daily_average():
    h = history()
    dates = h.groupby(h.index.to_period("M")).tail(1).index[-10:]
    h.loc[:, FIVE] = 1
    h.loc[dates, FIVE] = 100
    h.loc[dates[-1], "GLD"] = 110
    w, s = target_at(h, dates, "S4", UNIVERSE)
    assert w.GLD == .2
    assert w.sum() == .2
    assert s.GLD == pytest.approx(110/101 - 1)


@pytest.mark.parametrize("strategy", ["S1", "S2", "S3", "S4", "S5", *BASELINES])
def test_future_changes_cannot_change_past_targets(strategy):
    h = history()
    cutoff = h.index[-15]
    dates = h.groupby(h.index.to_period("M")).tail(1).index
    first = target_at(h.loc[:cutoff], dates, strategy, UNIVERSE)
    h.loc[h.index > cutoff] *= 100000
    second = target_at(h.loc[:cutoff], dates, strategy, UNIVERSE)
    for a, b in zip(first, second):
        pd.testing.assert_series_equal(a, b)


def test_future_fills_cannot_change_past_ledger_or_orders():
    p = panel([[100], [101], [102], [103]], [[100], [102], [104], [106]])
    targets = {p.closes.index[0]: np.array([1.])}
    ledger, orders = simulate(p, targets, 10)
    p.opens.iloc[-1] *= 100
    p.closes.iloc[-1] *= 10
    second, orders2 = simulate(p, targets, 10)
    pd.testing.assert_frame_equal(ledger.iloc[:-1], second.iloc[:-1])
    pd.testing.assert_frame_equal(orders, orders2)


def test_short_warmup_and_missing_signal_price_fail():
    h = history()
    with pytest.raises(DataContractError, match="warmup"):
        target_at(h.iloc[:252], [], "S1", UNIVERSE)
    h.iloc[-1, 0] = np.nan
    with pytest.raises(DataContractError, match="invalid_signal"):
        target_at(h, [], "S1", UNIVERSE)


def test_calendar_ends_do_not_turn_incomplete_month_into_signal():
    idx = pd.bdate_range("2020-01-01", "2020-03-17")
    schedule = pd.DataFrame(index=idx)
    assert list(month_ends(schedule).strftime("%Y-%m-%d")) == ["2020-01-31", "2020-02-28"]


def test_entry_cost_is_in_drawdown_and_metrics():
    p = panel([[100], [100], [100]], [[100], [100], [100]])
    ledger, orders = simulate(p, {p.closes.index[0]: np.array([1.])}, 25)
    result = metrics(ledger, orders)
    assert result["total_return"] == pytest.approx(1/1.0025 - 1)
    assert result["max_drawdown"] == pytest.approx(result["total_return"])
    assert result["order_legs"] == 1


@pytest.mark.parametrize("strategy", ["S1", "S2", "S3", "S4", "S5"])
def test_full_plan_cannot_see_changed_future_prices(strategy):
    h = history()
    dates = h.index
    schedule = pd.DataFrame({"open": pd.to_datetime([f"{d:%Y-%m-%d}T14:30:00Z" for d in dates]),
                             "close": pd.to_datetime([f"{d:%Y-%m-%d}T21:00:00Z" for d in dates])}, index=dates)
    src = pd.DataFrame([list(h.columns)] * len(h), index=dates, columns=h.columns)
    p = Panel(h.copy(), h.copy(), src, {}, schedule, UNIVERSE)
    original, _ = signal_plan(p, strategy)
    cutoff = min(original)
    p.opens.loc[p.opens.index > cutoff] *= 10000
    p.closes.loc[p.closes.index > cutoff] *= np.arange(1, len(h.columns)+1) * 100
    changed, _ = signal_plan(p, strategy)
    np.testing.assert_array_equal(original[cutoff], changed[cutoff])


@pytest.mark.parametrize("tamper", ["fee", "date", "nav", "units"])
def test_independent_replay_rejects_corrupted_orders_or_equity(tamper):
    p = panel([[100], [109], [111]], [[100], [110], [112]])
    targets = {p.closes.index[0]: np.array([1.])}
    ledger, orders = simulate(p, targets, 25)
    assert validate_run(p, ledger, orders, targets, 25)["status"] == "PASS"
    if tamper == "fee":
        orders.loc[0, "fee"] = 0
    elif tamper == "date":
        orders.loc[0, "fill_session"] = orders.signal_session.iloc[0]
    elif tamper == "units":
        orders.loc[0, "adjusted_units_delta"] *= 2
    else:
        ledger.loc[ledger.index[-1], "nav"] *= 1.1
    with pytest.raises(AssertionError):
        validate_run(p, ledger, orders, targets, 25)
