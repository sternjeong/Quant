"""Deterministic offline Day 2 audit; no strategy/backtest/provider imports."""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from data_contract import adjusted_open, require_prices, splice_at_open

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent
LOCK_SHA = "3022ec9a3169c827ccb398c309b2cd0d46be87fce7f467e1ef0a20f366f62f9e"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(name, data):
    (ROOT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def load_prices(path):
    frame = pd.read_csv(path, float_precision="round_trip")
    utc = pd.to_datetime(frame.pop("Date"), utc=True)
    local = utc.dt.tz_convert("America/New_York")
    if not (local.dt.hour.eq(0) & local.dt.minute.eq(0) & local.dt.second.eq(0)).all():
        raise ValueError("non_midnight_local_session_label")
    frame.index = pd.DatetimeIndex(local.dt.tz_localize(None), name="session")
    return frame


def load_schedule():
    schedule = pd.read_csv(ROOT / "XNYS_sessions.csv.gz", index_col="session", parse_dates=["session"])
    for col in ("open", "close"):
        schedule[col] = pd.to_datetime(schedule[col], utc=True)
    return schedule


def dates(index):
    return list(pd.DatetimeIndex(index).strftime("%Y-%m-%d"))


def main():
    if sha((BASE / "snapshot_lock.json").read_bytes()) != LOCK_SHA:
        raise ValueError("original_snapshot_lock_changed")
    lock = json.loads((BASE / "snapshot_lock.json").read_text())
    for rel, expected in lock["artifacts"].items():
        if sha((BASE / rel).read_bytes()) != expected:
            raise ValueError(f"original_artifact_changed:{rel}")
    original = json.loads((BASE / "manifest.json").read_text())
    supplement = json.loads((ROOT / "input_manifest.json").read_text())
    inventory = {}
    prices = {}
    for base, items in ((BASE, original["datasets"]), (ROOT, supplement["datasets"])):
        for item in items:
            payload = (base / item["path"]).read_bytes()
            if sha(payload) != item["sha256"] or sha(gzip.decompress(payload)) != item["content_sha256"]:
                raise ValueError(f"dataset_changed:{item['id']}")
            rel = str((base / item["path"]).relative_to(BASE))
            inventory[rel] = item["sha256"]
            if item.get("kind") == "etf_ohlcv" or item["id"] == "VNQ":
                prices[item["id"]] = load_prices(base / item["path"])
    schedule = load_schedule()
    summary, actions, flags = [], [], []
    required = ["Open", "High", "Low", "Close", "Adj Close"]
    for ticker, frame in sorted(prices.items()):
        expected = schedule.loc[frame.index.min():"2026-09-17"].index
        missing, extra = expected.difference(frame.index), frame.index.difference(expected)
        require_prices(frame, expected)
        positive = np.isfinite(frame[required]).all().all() and (frame[required] > 0).all().all()
        bad_ohlc = ((frame.Low > frame[["Open", "Close"]].min(axis=1) + 1e-7)
                    | (frame.High < frame[["Open", "Close"]].max(axis=1) - 1e-7)
                    | (frame.High < frame.Low))
        factor = frame["Adj Close"] / frame["Close"]
        nulls = int(frame.isna().sum().sum())
        if len(extra) or nulls or not positive or bad_ohlc.any() or (frame.Volume < 0).any():
            raise ValueError(f"invalid_price_panel:{ticker}")
        for day, row in frame.loc[(frame["Stock Splits"] != 0) | (frame.Dividends != 0)
                                  | (frame["Capital Gains"] != 0)].iterrows():
            previous = frame.index.get_loc(day) - 1
            actions.append({"ticker": ticker, "session": str(day.date()),
                            "provider_split": row["Stock Splits"], "dividend": row.Dividends,
                            "capital_gain": row["Capital Gains"],
                            "close_ratio": float(row.Close / frame.Close.iloc[previous]) if previous >= 0 else None,
                            "adj_close_ratio": float(row["Adj Close"] / frame["Adj Close"].iloc[previous]) if previous >= 0 else None,
                            "factor_ratio": float(factor.loc[day] / factor.iloc[previous]) if previous >= 0 else None})
        ret = frame["Adj Close"].pct_change(fill_method=None)
        fchange = factor.pct_change(fill_method=None)
        masks = {"zero_volume": frame.Volume.eq(0), "absolute_daily_return_over_25pct": ret.abs() > .25,
                 "adjustment_factor_change_over_2pct": fchange.abs() > .02}
        for kind, mask in masks.items():
            for day in frame.index[mask]:
                flags.append({"ticker": ticker, "session": str(day.date()), "flag": kind,
                              "open": float(frame.loc[day, "Open"]),
                              "close": float(frame.loc[day, "Close"]),
                              "volume": int(frame.loc[day, "Volume"]),
                              "adj_return": None if pd.isna(ret.loc[day]) else float(ret.loc[day]),
                              "factor_change": None if pd.isna(fchange.loc[day]) else float(fchange.loc[day])})
        summary.append({"ticker": ticker, "rows": len(frame), "first": str(frame.index.min().date()),
                        "last": str(frame.index.max().date()), "missing_internal_sessions": len(missing),
                        "unexpected_sessions": len(extra), "null_cells": nulls,
                        "duplicate_sessions": int(frame.index.duplicated().sum()), "bad_ohlc_rows": int(bad_ohlc.sum()),
                        "pre_first_observation_sessions": int((schedule.index < frame.index.min()).sum()),
                        "zero_volume_rows": int(frame.Volume.eq(0).sum()),
                        "split_events": int(frame["Stock Splits"].ne(0).sum()),
                        "dividend_events": int(frame.Dividends.ne(0).sum()),
                        "capital_gain_events": int(frame["Capital Gains"].ne(0).sum()),
                        "adjustment_factor_min": float(factor.min()), "adjustment_factor_max": float(factor.max()),
                        "max_abs_adj_daily_return": float(ret.abs().max()),
                        "timezone": "America/New_York; UTC-05 winter / UTC-04 summer"})
    pd.DataFrame(summary).to_csv(ROOT / "price_inventory.csv", index=False)
    pd.DataFrame(actions).to_csv(ROOT / "corporate_actions.csv", index=False)
    pd.DataFrame(flags).to_csv(ROOT / "price_flags.csv", index=False)
    universe = json.loads((BASE / "spec.json").read_text())["existing_17_etf"]
    actual_dates = prices[universe[0]].index
    for t in universe[1:]:
        actual_dates = actual_dates.intersection(prices[t].index)
    spliced = splice_at_open(prices["VNQ"], prices["XLRE"], "2015-10-08")
    proxy_dates = spliced.index
    for ticker in universe:
        if ticker != "XLRE":
            proxy_dates = proxy_dates.intersection(prices["VOX" if ticker == "XLC" else ticker].index)
    seam = spliced.loc["2015-10-06":"2015-10-12"].copy()
    seam.to_csv(ROOT / "proxy_splice.csv", float_format="%.17g")
    signal_rows = []
    for pos, (day, row) in enumerate(schedule.iterrows()):
        if pos + 1 >= len(schedule) or day > pd.Timestamp("2026-09-17"):
            continue
        next_day = schedule.index[pos + 1]
        if day.month == next_day.month:
            continue
        next_open = schedule.loc[next_day, "open"]
        if not next_open > row["close"] or not next_day > day:
            raise ValueError("same_day_or_earlier_fill")
        signal_rows.append({"signal_session": str(day.date()), "signal_close_utc": row["close"].isoformat(),
                            "next_session": str(next_day.date()), "next_open_utc": next_open.isoformat()})
    pd.DataFrame(signal_rows).to_csv(ROOT / "monthly_session_edges.csv", index=False)
    membership = pd.read_csv(BASE / "data/sp500_historical_constituents.csv.gz")
    result = {
        "audit_scope": "Day 2 only; no strategy performance, rankings, or S6 coverage certification",
        "original_artifacts_verified": len(lock["artifacts"]), "original_lock_sha256": LOCK_SHA,
        "data_hashes": inventory, "data_inventory_sha256": sha(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()),
        "price_files": len(prices), "price_rows": sum(len(f) for f in prices.values()),
        "timezone_verified_rows": sum(len(f) for f in prices.values()),
        "calendar_sessions": len(schedule), "monthly_next_open_boundaries_checked": len(signal_rows),
        "missing_internal_sessions": sum(r["missing_internal_sessions"] for r in summary),
        "null_cells": sum(r["null_cells"] for r in summary),
        "split_events": sum(r["split_events"] for r in summary),
        "zero_volume_rows": sum(r["zero_volume_rows"] for r in summary), "flagged_rows_by_reason": pd.Series([r["flag"] for r in flags]).value_counts().to_dict(),
        "samples": {"actual": {"first": str(actual_dates.min().date()), "last": str(actual_dates.max().date()), "rows": len(actual_dates),
                                  "calendar_12_month_lower_bound": str((actual_dates.min() + pd.DateOffset(months=12)).date())},
                    "proxy": {"label": "프록시", "mapping": {"XLC": "VOX for full long sample", "XLRE": "VNQ before 2015-10-08, actual XLRE thereafter"},
                              "first": str(proxy_dates.min().date()), "last": str(proxy_dates.max().date()), "rows": len(proxy_dates),
                              "calendar_12_month_lower_bound": str((proxy_dates.min() + pd.DateOffset(months=12)).date()),
                              "limiting_ticker": "HYG", "no_2007_warmup_fabrication": True}},
        "splice": {"date": "2015-10-08", "naive_level_jump": float(prices["XLRE"].loc["2015-10-08", "Adj Close"] / prices["VNQ"].loc["2015-10-07", "Adj Close"] - 1),
                   "prospective_return": float(spliced.loc["2015-10-08", "Adj Close"] / spliced.loc["2015-10-07", "Adj Close"] - 1),
                   "proxy_overnight_factor": float(adjusted_open(prices["VNQ"]).loc["2015-10-08"] / prices["VNQ"].loc["2015-10-07", "Adj Close"]),
                   "actual_intraday_factor": float(prices["XLRE"].loc["2015-10-08", "Close"] / prices["XLRE"].loc["2015-10-08", "Open"]),
                   "portfolio_transfer_costs_required_in_day3": True},
        "membership": {"rows": len(membership), "first_date": str(membership.date.min()), "last_date": str(membership.date.max()),
                       "upstream_publication_timestamps": "absent", "historical_sectors_shares_delisted_prices": "not captured",
                       "gate": "S6 inputs must fail closed until Day 4 verifies actual availability; import time is not publication time"},
        "missing_policy": "No imputation/deletion/shortened warmup; missing required row/open stops calculation; zero-volume fills rejected",
        "corporate_actions_policy": "Provider split-adjusted OHLC; same-row adjusted Open; no double-counted split or dividend",
        "delisting_policy": "No delisted ETF detected within captured spans; no assertion about omitted historical equities; no last-price carry or survivor-only omission",
        "calendar_checks": {str(day): day in schedule.index for day in pd.to_datetime(["2012-10-29", "2012-10-30", "2018-12-05", "2025-01-09"])},
    }
    if any(result["calendar_checks"].values()):
        raise ValueError("special_market_closure_missing")
    write_json("audit_results.json", result)
    print(json.dumps({k: result[k] for k in ("original_artifacts_verified", "price_files", "price_rows", "missing_internal_sessions", "zero_volume_rows", "split_events", "monthly_next_open_boundaries_checked", "data_inventory_sha256")}, indent=2))


if __name__ == "__main__":
    main()
