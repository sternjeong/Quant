"""Independent raw-ticker ledger replay. Does not call the execution engine."""
from __future__ import annotations

import numpy as np
import pandas as pd


def validate_run(panel, ledger, orders, targets, cost_bps):
    dates = ledger.index
    tickers = list(orders.ticker.unique())
    changes = pd.DataFrame(0., index=dates, columns=tickers)
    spent = pd.Series(0., index=dates)
    fee_by_day = pd.Series(0., index=dates)
    notional_by_day = pd.Series(0., index=dates)
    for order in orders.itertuples(index=False):
        signal, fill = pd.Timestamp(order.signal_session), pd.Timestamp(order.fill_session)
        assert panel.schedule.index[panel.schedule.index.get_loc(signal)+1] == fill
        assert pd.Timestamp(order.signal_close_utc) == panel.schedule.loc[signal, "close"]
        assert pd.Timestamp(order.fill_open_utc) == panel.schedule.loc[fill, "open"]
        assert pd.Timestamp(order.signal_close_utc) < pd.Timestamp(order.fill_open_utc)
        price = panel.raw[order.ticker].loc[fill]
        actual_open = price.Open * price["Adj Close"] / price.Close
        assert price.Volume > 0
        assert np.isclose(order.provider_open, price.Open, rtol=1e-13)
        assert np.isclose(order.adjusted_open, actual_open, rtol=1e-13)
        assert np.isclose(order.adjusted_units_delta * actual_open, order.signed_notional,
                          rtol=1e-12, atol=1e-15)
        assert np.isclose(order.fee, abs(order.signed_notional) * cost_bps/10000,
                          rtol=1e-12, atol=1e-15)
        assert order.side == ("buy" if order.signed_notional > 0 else "sell")
        if order.reason == "monthly_target":
            assert signal in targets
            assert order.ticker == panel.sources.loc[fill, order.slot]
        else:
            assert order.reason == "proxy_conversion"
            assert panel.sources.loc[signal, order.slot] != panel.sources.loc[fill, order.slot]
        changes.loc[fill, order.ticker] += order.adjusted_units_delta
        spent.loc[fill] += order.signed_notional + order.fee
        fee_by_day.loc[fill] += order.fee
        notional_by_day.loc[fill] += abs(order.signed_notional)
    units = changes.cumsum()
    assert units.min().min() >= -1e-10
    cash = 1 - spent.cumsum()
    assert cash.min() >= -1e-10
    close_prices = pd.DataFrame({t: panel.raw[t]["Adj Close"].reindex(dates) for t in tickers})
    open_prices = pd.DataFrame({t: (panel.raw[t].Open * panel.raw[t]["Adj Close"]
                                 / panel.raw[t].Close).reindex(dates) for t in tickers})
    # Missing prelisting prices may only meet an exactly zero, never held position.
    assert not ((units != 0) & close_prices.isna()).any().any()
    close_values = (units * close_prices).where(units != 0, 0)
    before_units = units - changes
    assert not ((before_units != 0) & open_prices.isna()).any().any()
    before_cash = cash + spent
    open_nav = before_cash + (before_units * open_prices).where(before_units != 0, 0).sum(axis=1)
    replay = cash + close_values.sum(axis=1)
    error = float(np.max(np.abs(replay / ledger.nav - 1)))
    assert error < 1e-10, error
    np.testing.assert_allclose(cash, ledger.cash, atol=1e-10, rtol=1e-10)
    np.testing.assert_allclose(fee_by_day, ledger.fee, atol=1e-12, rtol=1e-10)
    np.testing.assert_allclose(notional_by_day, ledger.notional, atol=1e-12, rtol=1e-10)
    np.testing.assert_allclose(open_nav, ledger.nav_open_before_cost, atol=1e-10, rtol=1e-10)
    np.testing.assert_allclose(notional_by_day / open_nav, ledger.turnover, atol=1e-10)
    np.testing.assert_allclose(ledger.nav.diff().iloc[1:],
                               (ledger.gap_pnl + ledger.intraday_pnl - ledger.fee).iloc[1:], atol=1e-10)
    for signal, target in targets.items():
        fill = panel.schedule.index[panel.schedule.index.get_loc(signal)+1]
        value_after = (units.loc[fill] * open_prices.loc[fill]).where(units.loc[fill] != 0, 0)
        nav_after = cash.loc[fill] + value_after.sum()
        for i, slot in enumerate(panel.closes.columns):
            ticker = panel.sources.loc[fill, slot]
            observed = value_after.get(ticker, 0) / nav_after
            assert abs(observed - target[i]) < 1e-10
        assert abs(cash.loc[fill] / nav_after - (1 - sum(target))) < 1e-10
    return {"status": "PASS", "order_legs_checked": len(orders),
            "equity_sessions_replayed": len(ledger), "max_relative_nav_replay_error": error,
            "zero_volume_fills": 0, "same_day_close_fills": 0,
            "non_next_session_fills": 0, "fee_identity_failures": 0,
            "negative_cash_or_short_positions": 0}
