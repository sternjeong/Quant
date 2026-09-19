"""Offline research input guards. No production imports, providers or broker calls."""
from __future__ import annotations

import math
import pandas as pd


class DataContractError(ValueError):
    pass


def aware(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise DataContractError("missing_or_naive_availability_timestamp")
    return stamp.tz_convert("UTC")


def latest_known(records, signal_close):
    """Reject unknown publication time; never select the earliest future record."""
    cutoff = aware(signal_close)
    eligible = []
    for row in records:
        effective, available = aware(row.get("effective_at")), aware(row.get("available_at"))
        if effective <= cutoff and available <= cutoff:
            eligible.append((effective, available, row))
    if not eligible:
        raise DataContractError("no_point_in_time_record")
    eligible.sort(key=lambda item: (item[0], item[1]))
    if len(eligible) > 1 and eligible[-1][:2] == eligible[-2][:2]:
        raise DataContractError("ambiguous_point_in_time_record")
    return eligible[-1][2]


def market_cap_asof(share_records, price_record, signal_close):
    """Require contemporaneous share units; never multiply future split factors.

    unit_basis is a verified common share-unit identifier, not a provider label.
    A split between the records requires an audited conversion before this call.
    """
    shares = latest_known(share_records, signal_close)
    price = latest_known([price_record], signal_close)
    if not shares.get("unit_basis") or shares["unit_basis"] != price.get("unit_basis"):
        raise DataContractError("unverified_or_inconsistent_share_units")
    values = [float(shares["value"]), float(price["value"])]
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise DataContractError("invalid_market_cap_inputs")
    return values[0] * values[1]


def require_prices(frame, sessions):
    """No fill, missing-session drop, or shortened warmup is permitted."""
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise DataContractError("duplicate_or_unsorted_sessions")
    if not pd.Index(sessions).isin(frame.index).all():
        raise DataContractError("missing_price_session")
    result = frame.loc[sessions, ["Open", "High", "Low", "Close", "Adj Close"]]
    if result.isna().any().any() or not result.map(lambda v: math.isfinite(v) and v > 0).all().all():
        raise DataContractError("missing_or_invalid_price")
    return result


def adjusted_open(frame):
    require_prices(frame, frame.index)
    return frame["Open"] * (frame["Adj Close"] / frame["Close"])


def next_open_order(signal_session, schedule, prices):
    """Resolve exact next exchange session, never next available price row."""
    day = pd.Timestamp(signal_session)
    if day not in schedule.index:
        raise DataContractError("not_an_exchange_session")
    pos = schedule.index.get_loc(day)
    if pos + 1 >= len(schedule):
        raise DataContractError("next_session_outside_calendar")
    next_day = schedule.index[pos + 1]
    require_prices(prices, [next_day])
    if not math.isfinite(float(prices.loc[next_day, "Volume"])) or prices.loc[next_day, "Volume"] <= 0:
        raise DataContractError("unverified_execution_on_zero_volume_session")
    signal = aware(schedule.loc[day, "close"])
    fill = aware(schedule.loc[next_day, "open"])
    if fill <= signal:
        raise DataContractError("same_day_or_earlier_fill")
    return {"signal_session": str(day.date()), "signal_close_utc": signal.isoformat(),
            "fill_session": str(next_day.date()), "fill_open_utc": fill.isoformat(),
            "provider_open": float(prices.loc[next_day, "Open"]),
            "adjusted_open": float(adjusted_open(prices.loc[[next_day]]).iloc[0])}


def splice_at_open(proxy, actual, switch_date):
    """Prospective price-coordinate splice; NOT a cost-free portfolio trade.

    First actual-day overnight uses proxy close->proxy open. After switching,
    use actual open->close. Never use actual's first close to scale prior rows.
    """
    switch = pd.Timestamp(switch_date)
    if switch not in proxy.index or switch not in actual.index:
        raise DataContractError("missing_splice_open")
    before = proxy.loc[proxy.index < switch]
    after = actual.loc[actual.index >= switch]
    if before.empty or after.empty:
        raise DataContractError("insufficient_splice_history")
    proxy_open = adjusted_open(proxy.loc[[switch]]).iloc[0]
    scale = proxy_open / adjusted_open(after).iloc[0]
    return pd.DataFrame({
        "Adj Close": pd.concat([before["Adj Close"], after["Adj Close"] * scale]),
        "Adjusted Open": pd.concat([adjusted_open(before), adjusted_open(after) * scale]),
        "source": ["VNQ"] * len(before) + ["XLRE"] * len(after),
    })
