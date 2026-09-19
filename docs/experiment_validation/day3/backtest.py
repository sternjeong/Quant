"""Offline Day 3 research. No provider, production strategy, DB or broker imports."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "day2"))
from data_contract import DataContractError, adjusted_open, next_open_order, require_prices, splice_at_open
from run_audit import load_prices, load_schedule

UNIVERSE = ["XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE",
            "XLK", "XLU", "TLT", "IEF", "GLD", "EFA", "HYG", "DBC"]
FIVE = ["SPY", "EFA", "IEF", "GLD", "DBC"]
BASELINES = ["SPY_buy_hold", "SPY_IEF_60_40", "candidate_universe_equal_weight"]
COSTS = [5, 10, 25]
SWITCH = pd.Timestamp("2015-10-08")
END = pd.Timestamp("2026-09-17")


@dataclass
class Panel:
    opens: pd.DataFrame
    closes: pd.DataFrame
    sources: pd.DataFrame
    raw: dict
    schedule: pd.DataFrame
    universe: list


def month_ends(schedule):
    idx = schedule.index
    return idx[:-1][idx[:-1].to_period("M") != idx[1:].to_period("M")]


def load_panel(sample):
    raw = {p.name.split(".")[0]: load_prices(p) for p in (BASE / "data").glob("*.csv.gz")
           if p.name != "sp500_historical_constituents.csv.gz"}
    raw["VNQ"] = load_prices(BASE / "day2/VNQ.csv.gz")
    schedule = load_schedule()
    universe = FIVE if sample == "actual_5_full" else UNIVERSE
    columns = list(dict.fromkeys(universe + FIVE))
    opens, closes, sources = {}, {}, {}
    for slot in columns:
        source = "VOX" if sample == "proxy_17" and slot == "XLC" else slot
        if sample == "proxy_17" and slot == "XLRE":
            spliced = splice_at_open(raw["VNQ"], raw["XLRE"], SWITCH)
            opens[slot], closes[slot], sources[slot] = (
                spliced["Adjusted Open"], spliced["Adj Close"], spliced["source"])
        else:
            frame = raw[source]
            opens[slot], closes[slot] = adjusted_open(frame), frame["Adj Close"]
            sources[slot] = pd.Series(source, index=frame.index)
    start = max(series.index.min() for series in closes.values())
    sessions = schedule.loc[start:END].index
    for series in [*opens.values(), *closes.values()]:
        if not sessions.isin(series.index).all():
            raise DataContractError("missing_common_session")
    op = pd.DataFrame({k: v.loc[sessions] for k, v in opens.items()})
    cl = pd.DataFrame({k: v.loc[sessions] for k, v in closes.items()})
    src = pd.DataFrame({k: v.loc[sessions] for k, v in sources.items()})
    for ticker in set(src.to_numpy().ravel()):
        used = src.index[(src == ticker).any(axis=1)]
        require_prices(raw[ticker], used)
    return Panel(op, cl, src, raw, schedule, universe)


def target_at(history, completed_month_ends, strategy, universe):
    """Only the caller-supplied price prefix is visible. No rounding before ranks."""
    if history.empty or not np.isfinite(history.to_numpy()).all() or (history <= 0).any().any():
        raise DataContractError("invalid_signal_history")
    weights = pd.Series(0.0, index=history.columns)
    scores = pd.Series(np.nan, index=history.columns)
    if strategy == "SPY_buy_hold":
        weights["SPY"] = 1.0
    elif strategy == "SPY_IEF_60_40":
        weights[["SPY", "IEF"]] = [.6, .4]
    elif strategy == "candidate_universe_equal_weight":
        weights[universe] = 1 / len(universe)
    elif strategy == "S4":
        dates = pd.DatetimeIndex(completed_month_ends)
        dates = dates[(dates >= history.index[0]) & (dates <= history.index[-1])]
        if len(dates) < 10:
            raise DataContractError("insufficient_sma_warmup")
        average = history.loc[dates[-10:], FIVE].mean()
        score = history[FIVE].iloc[-1] / average - 1
        scores[FIVE] = score
        weights[score.index[score > 0]] = 1 / 5
    else:
        if len(history) < 253:
            raise DataContractError("insufficient_252_session_warmup")
        assets = FIVE if strategy == "S5" else universe
        numerator = history[assets].iloc[-22 if strategy == "S2" else -1]
        score = numerator / history[assets].iloc[-253] - 1
        scores[assets] = score
        if strategy in ("S1", "S2"):
            selected = score.sort_values(ascending=False, kind="stable").index[:4]
            weights[selected] = 1 / 4
        elif strategy == "S3":
            weights[score.index[score > 0]] = 1 / len(universe)
        elif strategy == "S5":
            selected = score[score > 0].sort_values(ascending=False, kind="stable").index[:3]
            weights[selected] = 1 / 3
        else:
            raise ValueError(f"unknown_strategy:{strategy}")
    return weights, scores


def signal_plan(panel, strategy):
    ends = month_ends(panel.schedule)
    eligible = ends[(ends >= panel.closes.index[252]) & (ends >= pd.Timestamp("2007-01-01"))
                    & (ends < panel.closes.index[-1])]
    eligible = eligible[eligible.isin(panel.closes.index)]
    if strategy == "SPY_buy_hold":
        eligible = eligible[:1]
    targets, rows = {}, []
    for day in eligible:
        weights, scores = target_at(panel.closes.loc[:day], ends, strategy, panel.universe)
        targets[day] = weights.to_numpy()
        fill = panel.schedule.index[panel.schedule.index.get_loc(day) + 1]
        if strategy == "S4":
            history_start = ends[(ends >= panel.closes.index[0]) & (ends <= day)][-10]
            history_end = day
        elif strategy.startswith("S") and strategy not in BASELINES:
            loc = panel.closes.index.get_loc(day)
            history_start = panel.closes.index[loc - 252]
            history_end = panel.closes.index[loc - 21] if strategy == "S2" else day
        else:
            history_start = history_end = day
        for slot in weights.index:
            rows.append({"strategy": strategy, "signal_session": day, "fill_session": fill,
                         "signal_close_utc": panel.schedule.loc[day, "close"],
                         "history_start": history_start, "history_end": history_end,
                         "slot": slot, "source_at_signal": panel.sources.loc[day, slot],
                         "score": scores[slot], "target_weight": weights[slot],
                         "target_cash_weight": 1 - weights.sum()})
    if not targets:
        raise DataContractError("no_warmed_signal")
    return targets, rows


def rebalance(values, cash, weights, rate):
    """Unique self-financing solution, long only, with fee on actual dollar deltas."""
    values, weights = np.asarray(values, dtype=float), np.asarray(weights, dtype=float)
    if (values.shape != weights.shape or not np.isfinite(values).all()
            or not np.isfinite(weights).all() or not np.isfinite(cash)
            or (values < 0).any() or cash < -1e-12 or (weights < 0).any()
            or weights.sum() > 1 + 1e-12 or not 0 <= rate < 1):
        raise ValueError("invalid_account_or_target")
    equity = values.sum() + cash
    low, high = 0.0, equity
    for _ in range(60):
        after = (low + high) / 2
        residual = after + rate * np.abs(weights * after - values).sum() - equity
        if residual > 0:
            high = after
        else:
            low = after
    target = weights * ((low + high) / 2)
    delta = target - values
    fee = rate * np.abs(delta).sum()
    remaining_cash = cash - delta.sum() - fee
    if remaining_cash < -1e-10 * max(1, equity):
        raise ValueError("negative_cash_after_cost")
    return target, remaining_cash, delta, fee


def simulate(panel, targets, cost_bps):
    idx, columns = panel.closes.index, panel.closes.columns
    op, cl = panel.opens.to_numpy(), panel.closes.to_numpy()
    src = panel.sources.to_numpy()
    rate = cost_bps / 10000
    initial_day = min(targets)
    start = idx.get_loc(initial_day)
    units, cash = np.zeros(len(columns)), 1.0
    equity = 1.0
    fills = {panel.schedule.index[panel.schedule.index.get_loc(d) + 1]: (d, w)
             for d, w in targets.items()}
    orders, ledger = [], [{"session": initial_day, "nav": 1.0, "cash": 1.0,
                          "nav_open_before_cost": 1.0, "fee": 0.0, "notional": 0.0,
                          "turnover": 0.0, "gap_pnl": 0.0, "intraday_pnl": 0.0}]

    def record(day, signal, slot, ticker, signed_notional, reason):
        info = next_open_order(signal, panel.schedule, panel.raw[ticker])
        if info["fill_session"] != str(day.date()):
            raise DataContractError("not_exact_next_open")
        orders.append({**info, "slot": slot, "ticker": ticker, "reason": reason,
                       "side": "buy" if signed_notional > 0 else "sell",
                       "signed_notional": signed_notional,
                       "adjusted_units_delta": signed_notional / info["adjusted_open"],
                       "cost_bps": cost_bps, "fee": abs(signed_notional) * rate})

    for pos in range(start + 1, len(idx)):
        day = idx[pos]
        values = units * op[pos]
        before = float(cash + values.sum())
        gap_pnl = before - equity
        fee, notional = 0.0, 0.0
        for col in np.flatnonzero(src[pos] != src[pos - 1]):
            if values[col] == 0:
                continue
            old = float(values[col])
            new = old * (1 - rate) / (1 + rate)
            record(day, idx[pos - 1], columns[col], src[pos - 1, col], -old, "proxy_conversion")
            record(day, idx[pos - 1], columns[col], src[pos, col], new, "proxy_conversion")
            fee += rate * (old + new)
            notional += old + new
            values[col] = new
        if day in fills:
            signal, target_weights = fills[day]
            values, cash, delta, rebalance_fee = rebalance(values, cash, target_weights, rate)
            fee += rebalance_fee
            notional += np.abs(delta).sum()
            for col in np.flatnonzero(delta != 0):
                record(day, signal, columns[col], src[pos, col], float(delta[col]), "monthly_target")
        units = values / op[pos]
        close_values = units * cl[pos]
        equity = float(cash + close_values.sum())
        intraday = float((close_values - values).sum())
        if abs(equity - (before - fee + intraday)) > 1e-10 * max(1, before):
            raise ValueError("accounting_identity_failed")
        ledger.append({"session": day, "nav": equity, "cash": cash,
                       "nav_open_before_cost": before, "fee": fee, "notional": notional,
                       "turnover": notional / before, "gap_pnl": gap_pnl, "intraday_pnl": intraday})
    return pd.DataFrame(ledger).set_index("session"), pd.DataFrame(orders)


def metrics(ledger, orders):
    nav = ledger.nav
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    returns = nav.pct_change(fill_method=None).iloc[1:]
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1)
    mdd = float((nav / nav.cummax() - 1).min())
    std = float(returns.std(ddof=1))
    return {"initial_signal_session": str(nav.index[0].date()),
            "first_fill_session": str(nav.index[1].date()), "end_session": str(nav.index[-1].date()),
            "return_sessions": len(returns), "elapsed_years": years, "final_nav": nav.iloc[-1],
            "total_return": nav.iloc[-1] - 1, "cagr": cagr, "max_drawdown": mdd,
            "calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
            "sharpe_rf0": float(returns.mean()) / std * np.sqrt(252) if std else np.nan,
            "annualized_volatility": std * np.sqrt(252), "fees_initial_capital_units": ledger.fee.sum(),
            "two_way_turnover_sum": ledger.turnover.sum(),
            "annualized_two_way_turnover": ledger.turnover.sum() / years,
            "order_legs": len(orders), "rebalance_sessions": orders.fill_session.nunique() if len(orders) else 0,
            "proxy_conversion_legs": int(orders.reason.eq("proxy_conversion").sum()) if len(orders) else 0}
