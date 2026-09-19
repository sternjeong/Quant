"""One-time Day 2 supplement. Never rewrites the Day 1 snapshot.

PYTHONPATH=/tmp/quant-day2-calendar .venv/bin/python \
    docs/experiment_validation/day2/capture_inputs.py
Calendar generation needs exchange_calendars 4.13.2; offline audits do not.
"""
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path

import exchange_calendars as xc
import yfinance as yf

ROOT = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def save_frame(frame, name):
    payload = frame.to_csv(float_format="%.17g", lineterminator="\n").encode()
    packed = gzip.compress(payload, mtime=0)
    with (ROOT / name).open("xb") as handle:
        handle.write(packed)
    return {"path": name, "sha256": sha(packed), "content_sha256": sha(payload),
            "rows": len(frame)}


def main():
    targets = [ROOT / n for n in ("VNQ.csv.gz", "XNYS_sessions.csv.gz", "input_manifest.json")]
    if any(p.exists() for p in targets):
        raise SystemExit("Supplement already exists; do not overwrite or re-download.")
    original = json.loads((ROOT.parent / "manifest.json").read_text())
    request = next(d["request"] for d in original["datasets"] if d["id"] == "VOX")
    started = now()
    frame = yf.download("VNQ", **request)
    completed = now()
    if frame is None or frame.empty:
        raise SystemExit("VNQ returned no data; no fallback.")
    frame.index.name = "Date"
    vnq = {"id": "VNQ", "provider": "Yahoo Finance", "source_url":
           "https://finance.yahoo.com/quote/VNQ/history/", "request": request,
           "query_started_at_utc": started, "query_completed_at_utc": completed,
           "timezone": str(frame.index.tz), **save_frame(frame, "VNQ.csv.gz")}
    calendar = xc.get_calendar("XNYS", start="2006-01-01", end="2026-09-21")
    schedule = calendar.schedule[["open", "close"]].copy()
    schedule.index.name = "session"
    cal = {"id": "XNYS", "source_url":
           "https://github.com/gerrymanoim/exchange_calendars", "generated_at_utc": now(),
           "calendar": "XNYS", "range": ["2006-01-01", "2026-09-21"],
           **save_frame(schedule, "XNYS_sessions.csv.gz")}
    result = {"scope": "Day 2 supplement only; original manifest unchanged",
              "datasets": [vnq, cal], "packages": {p: importlib.metadata.version(p)
              for p in ("yfinance", "pandas", "numpy", "exchange_calendars")},
              "script_sha256": sha(Path(__file__).read_bytes())}
    with (ROOT / "input_manifest.json").open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
