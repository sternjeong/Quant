"""Capture Day 1 evidence; never rewrite a prior snapshot or run a strategy.

Run once from the repository root using .venv/bin/python. An existing manifest
is a hard stop. Partial downloads are checkpointed individually for inspection.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def constant(path, name):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(name)


def main():
    if (OUT / "manifest.json").exists() or (OUT / "data").exists():
        raise SystemExit("Snapshot exists; inspect and resume explicitly, never overwrite.")
    started = utc_now()
    (OUT / "data").mkdir()
    (OUT / "source").mkdir()
    source_paths = [
        "docs/TWO_WEEK_STRATEGY_VALIDATION_PROTOCOL.md",
        "core/champion_strategy.py", "core/market_data.py",
        "core/point_in_time_universe.py", "core/point_in_time_market_cap.py",
        "core/strategy_tuning.py",
    ]
    sources = []
    for rel in source_paths:
        source = ROOT / rel
        target = OUT / "source" / source.name
        with target.open("xb") as handle:
            handle.write(source.read_bytes())
        sources.append({"original_path": rel, "path": str(target.relative_to(OUT)),
                        "sha256": digest(target)})
    universe = constant(ROOT / "core/champion_strategy.py", "CORE_UNIVERSE")
    # SPY is a benchmark; VOX is the only proxy explicitly authorized.
    tickers = sorted(set(universe + ["SPY", "VOX"]))
    datasets = []
    # Explicit end excludes the still-unopened 2026-09-18 US session.
    request = dict(start="2006-01-01", end="2026-09-18", interval="1d",
                   auto_adjust=False, back_adjust=False, actions=True,
                   repair=False, keepna=True, prepost=False, rounding=False,
                   ignore_tz=False, threads=False, progress=False, timeout=20,
                   multi_level_index=False)
    for ticker in tickers:
        entry = {"id": ticker, "kind": "etf_ohlcv", "provider": "Yahoo Finance",
                 "source_url": f"https://finance.yahoo.com/quote/{ticker}/history/",
                 "request": request, "query_started_at_utc": utc_now()}
        try:
            frame = yf.download(ticker, **request)
            entry["query_completed_at_utc"] = utc_now()
            if frame is None or frame.empty:
                raise ValueError("No data returned; no cache fallback used")
            required = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
            if not required.issubset(frame.columns):
                raise ValueError(f"Missing columns: {sorted(required - set(frame.columns))}")
            target = OUT / "data" / f"{ticker}.csv.gz"
            frame.index.name = "Date"
            payload = frame.to_csv(float_format="%.17g", lineterminator="\n").encode()
            with target.open("xb") as handle:
                handle.write(gzip.compress(payload, mtime=0))
            entry.update(status="captured", path=str(target.relative_to(OUT)),
                         sha256=digest(target), content_sha256=hashlib.sha256(payload).hexdigest(),
                         rows=len(frame), columns=list(frame.columns),
                         timezone=str(frame.index.tz), first_timestamp=frame.index.min().isoformat(),
                         last_timestamp=frame.index.max().isoformat(),
                         null_counts={c: int(frame[c].isna().sum()) for c in frame.columns},
                         adjustment="Provider Open/Close with auto_adjust=False; Adj Close retained separately; no transformations or fills")
        except Exception as exc:
            entry.update(status="failed", query_completed_at_utc=utc_now(),
                         error=f"{type(exc).__name__}: {exc}")
        write_json(OUT / "data" / f"{ticker}.metadata.json", entry)
        datasets.append(entry)
        print(ticker, entry["status"], entry.get("rows", 0), flush=True)
    pit = ROOT / "data/sp500_historical_constituents.csv"
    target = OUT / "data/sp500_historical_constituents.csv.gz"
    payload = pit.read_bytes()
    with target.open("xb") as handle:
        handle.write(gzip.compress(payload, mtime=0))
    frame = pd.read_csv(pit)
    datasets.append({
        "id": "sp500_membership", "kind": "local_derived_membership_evidence",
        "status": "captured_unverified_provenance", "path": str(target.relative_to(OUT)),
        "sha256": digest(target), "content_sha256": hashlib.sha256(payload).hexdigest(),
        "provider": "Local merge attributed to fja05680/sp500 in PROGRESS.md",
        "source_path": "data/sp500_historical_constituents.csv", "retrieved_at_utc": None,
        "observed_at_utc": utc_now(), "rows": len(frame),
        "first_date": str(frame.date.min()), "last_date": str(frame.date.max()),
        "source_git_commit": subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "--", str(pit.relative_to(ROOT))],
            cwd=ROOT, text=True).strip(),
        "limitations": ["Original upstream retrieval time and source revisions not recorded",
                        "Local copy time is not an upstream retrieval time",
                        "No point-in-time sector, share-publication or delisted-price panel captured"],
    })
    manifest = {
        "schema_version": 1, "status": "evidence_snapshot_not_final_freeze",
        "capture_started_at_utc": started, "capture_completed_at_utc": utc_now(),
        "code_commit_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "code_commit_scope": "Existing production/research code inspected; not a validated protocol engine",
        "protocol_source_dirty": True, "source_files": sources,
        "capture_script_sha256": digest(Path(__file__)),
        "packages": {p: importlib.metadata.version(p) for p in ["pandas", "numpy", "yfinance"]},
        "requested_tickers": tickers, "datasets": datasets,
        "data_scope": "17 existing ETF universe, SPY benchmark, authorized VOX proxy; S6 data incomplete",
        "no_backtest_executed": True,
    }
    write_json(OUT / "manifest.json", manifest)


if __name__ == "__main__":
    main()
