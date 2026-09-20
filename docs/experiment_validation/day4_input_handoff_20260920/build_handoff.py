"""Export diagnostic input requests, never a certified universe or a backtest."""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
KEY_FIELDS = ["fill_session", "signal_session", "signal_close_utc", "fill_open_utc",
              "membership_snapshot_date", "raw_identifier", "cache_ticker_hint"]
BOUNDARY_FIELDS = KEY_FIELDS[:5]


def requests_from_rows(rows):
    requests, seen, boundaries = [], set(), {}
    for row in rows:
        item = {key: row[key] for key in KEY_FIELDS}
        if any(not value for value in item.values()):
            raise ValueError("empty_request_field")
        key = item["fill_session"], item["raw_identifier"]
        if key in seen:
            raise ValueError("duplicate_raw_member_boundary")
        seen.add(key)
        signal, fill = (datetime.fromisoformat(item[k]) for k in ("signal_close_utc", "fill_open_utc"))
        if signal.tzinfo is None or fill.tzinfo is None or signal >= fill:
            raise ValueError("invalid_signal_fill_timestamps")
        if not item["membership_snapshot_date"] <= item["signal_session"] < item["fill_session"]:
            raise ValueError("future_or_same_session_request")
        boundary = {key: item[key] for key in BOUNDARY_FIELDS}
        prior = boundaries.setdefault(item["fill_session"], boundary)
        if prior != boundary:
            raise ValueError("inconsistent_boundary")
        requests.append(item)
    if not requests:
        raise ValueError("empty_request_is_not_coverage")
    return sorted(requests, key=lambda r: (r["fill_session"], r["raw_identifier"]))


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def build():
    with gzip.open(BASE / "day4/member_coverage.csv.gz", "rt", newline="") as stream:
        requests = requests_from_rows(list(csv.DictReader(stream)))
    by_id, by_boundary = defaultdict(list), defaultdict(list)
    for row in requests:
        by_id[row["raw_identifier"]].append(row)
        by_boundary[row["fill_session"]].append(row)
    ids = []
    for raw, rows in sorted(by_id.items()):
        hints = sorted({r["cache_ticker_hint"] for r in rows})
        if len(hints) != 1:
            raise ValueError("inconsistent_lookup_hint")
        ids.append({"raw_identifier": raw, "cache_ticker_hint": hints[0],
                    "first_requested_signal": min(r["signal_session"] for r in rows),
                    "last_requested_signal": max(r["signal_session"] for r in rows),
                    "requested_boundaries": len(rows)})
    bounds = [{**{key: rows[0][key] for key in BOUNDARY_FIELDS}, "diagnostic_members": len(rows)}
              for _, rows in sorted(by_boundary.items())]
    (HERE / "requested_member_keys.csv.gz").write_bytes(gzip.compress(csv_bytes(requests, KEY_FIELDS), mtime=0))
    (HERE / "requested_identifiers.csv").write_bytes(csv_bytes(ids, list(ids[0])))
    (HERE / "requested_boundaries.csv").write_bytes(csv_bytes(bounds, list(bounds[0])))
    sources = ["day4/member_coverage.csv.gz", "day4/rebalance_boundaries.csv",
               "day4/RESUME_NOTE.md", "day4_resolutions.md", "day2/XNYS_sessions.csv.gz",
               "data/sp500_historical_constituents.csv.gz"]
    manifest = {"scope": "Lossless query keys from the prior unverified diagnostic inventory; not a certified universe",
                "source_files": {p: hashlib.sha256((BASE / p).read_bytes()).hexdigest() for p in sources},
                "source_path_base": "docs/experiment_validation",
                "member_boundary_requests": len(requests), "raw_identifiers": len(ids),
                "semiannual_boundaries": len(bounds), "certified_rebalances": 0,
                "day4_complete": False, "s6_backtest_executed": False,
                "authoritative_membership_reconciliation_required": True,
                "lookup_hints_are_security_ids": False}
    (HERE / "input_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
