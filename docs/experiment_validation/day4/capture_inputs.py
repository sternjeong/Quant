"""Freeze diagnostic observations from existing caches without calling providers.

Cache timestamps are filesystem observations, never historic publication times.
Price inventory and boundary observations do not certify a complete price panel.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import urllib.request

import pandas as pd

from audit_contract import boundaries, cache_ticker, diagnostic_members

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent
REPO = BASE.parent.parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def csv(frame, path):
    frame.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0} if str(path).endswith(".gz") else None)


def main():
    if (ROOT / "input_manifest.json").exists():
        raise SystemExit("Frozen capture exists; do not refresh mutable caches")
    begun = datetime.now(timezone.utc).isoformat()
    schedule = pd.read_csv(BASE / "day2/XNYS_sessions.csv.gz", index_col="session", parse_dates=["session"])
    dates = boundaries(schedule)
    table = pd.read_csv(BASE / "data/sp500_historical_constituents.csv.gz", parse_dates=["date"])
    raw_ids = sorted(set(t for d in dates for t in diagnostic_members(table, d["signal_session"])[1]))
    tickers = sorted({cache_ticker(t) for t in raw_ids})
    inventory, shares, prices, sources = [], [], [], []
    for kind in ("shares", "price"):
        for ticker in tickers:
            filename = f"shares_outstanding_{ticker}.parquet" if kind == "shares" else f"{ticker}_1d.parquet"
            path = REPO / "data/cache" / filename
            row = {"kind": kind, "ticker": ticker, "original_path": str(path.relative_to(REPO)),
                   "exists": path.exists(), "rows": 0, "first_date": None, "last_date": None,
                   "columns": "", "error": None, "has_available_at": False, "has_unit_basis": False}
            if not path.exists():
                inventory.append(row)
                continue
            before = path.stat()
            data = path.read_bytes()
            if before.st_mtime_ns != path.stat().st_mtime_ns:
                raise RuntimeError(f"cache changed while reading: {filename}")
            sources.append({"path": row["original_path"], "sha256": sha(data), "bytes": len(data),
                            "filesystem_mtime_ns": before.st_mtime_ns,
                            "retrieved_at_utc": None, "available_at": None,
                            "provenance": "existing provider cache; original retrieval time not recorded"})
            row["source_sha256"] = sha(data)
            try:
                df = pd.read_parquet(io.BytesIO(data))
                row["columns"] = ",".join(map(str, df.columns))
                row["has_available_at"] = "available_at" in df.columns
                row["has_unit_basis"] = "unit_basis" in df.columns
                row["original_timezone"] = str(getattr(df.index, "tz", None))
                df.index = pd.DatetimeIndex(df.index).tz_localize(None)
                df = df.sort_index()
                row["rows"] = len(df)
                row["duplicate_dates"] = int(df.index.duplicated().sum())
                if len(df):
                    row["first_date"], row["last_date"] = str(df.index.min().date()), str(df.index.max().date())
                if kind == "shares":
                    for day, value in df["shares"].items():
                        shares.append({"ticker": ticker, "observation_date": str(day.date()), "shares": value})
                else:
                    for d in dates:
                        p = {"ticker": ticker, "fill_session": d["fill_session"]}
                        for label, session, column in [("signal_close", d["signal_session"], "Close"),
                                                       ("fill_open", d["fill_session"], "Open")]:
                            key = pd.Timestamp(session)
                            found = key in df.index and column in df.columns and df.index.is_unique
                            p[label] = float(df.loc[key, column]) if found else None
                        prices.append(p)
            except (ValueError, KeyError, TypeError) as exc:
                row["error"] = type(exc).__name__
            inventory.append(row)
    sector_path = REPO / "data/cache/sp500_universe.csv"
    data = sector_path.read_bytes()
    (ROOT / "current_sector_snapshot.csv").write_bytes(data)
    sources.append({"path": str(sector_path.relative_to(REPO)), "sha256": sha(data), "bytes": len(data),
                    "retrieved_at_utc": None, "available_at": None, "provenance": "current sector diagnostic only"})
    csv(pd.DataFrame(inventory), ROOT / "cache_inventory.csv")
    csv(pd.DataFrame(shares, columns=["ticker", "observation_date", "shares"]), ROOT / "share_observations.csv.gz")
    csv(pd.DataFrame(prices, columns=["ticker", "fill_session", "signal_close", "fill_open"]), ROOT / "price_boundary_observations.csv.gz")
    csv(pd.DataFrame(dates), ROOT / "rebalance_boundaries.csv")
    csv(pd.DataFrame([{"raw_identifier": t, "cache_ticker_hint": cache_ticker(t)} for t in raw_ids]), ROOT / "identifier_map.csv")
    # Pin the upstream README to a commit; do not replace the frozen membership data.
    external = []
    try:
        api = "https://api.github.com/repos/fja05680/sp500/commits/master"
        with urllib.request.urlopen(urllib.request.Request(api, headers={"User-Agent": "Quant-research-audit"}), timeout=20) as response:
            commit = json.load(response)["sha"]
        url = f"https://raw.githubusercontent.com/fja05680/sp500/{commit}/README.md"
        with urllib.request.urlopen(url, timeout=20) as response:
            readme = response.read()
        (ROOT / "upstream_README.md").write_bytes(readme)
        external.append({"url": url, "commit": commit, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                         "path": "upstream_README.md", "sha256": sha(readme),
                         "role": "methodology/provenance only; not point-in-time membership evidence"})
    except Exception as exc:
        external.append({"url": "https://github.com/fja05680/sp500", "error_type": type(exc).__name__})
    write_json(ROOT / "external_sources.json", external)
    derived = {p.name: sha(p.read_bytes()) for p in sorted(ROOT.iterdir()) if p.suffix in (".csv", ".gz")}
    source_map = {s["path"]: s["sha256"] for s in sources}
    write_json(ROOT / "input_manifest.json", {
        "capture_started_at_utc": begun, "capture_finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "existing local caches only; no stock-price/share-history download",
        "source_files": sources, "source_inventory_sha256": sha(json.dumps(source_map, sort_keys=True, separators=(",", ":")).encode()),
        "derived_files": derived,
        "derived_inventory_sha256": sha(json.dumps(derived, sort_keys=True, separators=(",", ":")).encode()),
        "membership_source": "../data/sp500_historical_constituents.csv.gz",
        "calendar_source": "../day2/XNYS_sessions.csv.gz",
        "limitations": ["Cache observation dates are not public availability timestamps",
                       "Ticker normalization is only a lookup hint, not security identity",
                       "Price observations are diagnostics, not an audited delisted OHLCV panel",
                       "Filesystem mtime is not retrieval/publication time",
                       "No historical universe/sector/shares/units certified"]})
    print(json.dumps({"raw_ids": len(raw_ids), "cache_tickers": len(tickers), "source_files": len(sources),
                      "share_observations": len(shares), "rebalance_boundaries": len(dates)}))


if __name__ == "__main__":
    main()
