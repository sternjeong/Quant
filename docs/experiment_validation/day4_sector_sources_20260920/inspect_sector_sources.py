"""Offline source diagnostics, never an S6 universe or sector input adapter.

The issuer names in this MSCI announcement are not security identifiers. Its
MSCI effective date must not be assigned to S&P constituents. No trading,
prices, ranking, sector backfill or network requests occur in this module.
"""
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re


class AnnouncementParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.found = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "pre" and "announcementContent" in dict(attrs).get("class", "").split():
            self.active = True
            self.found += 1

    def handle_endtag(self, tag):
        if tag == "pre":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)


def inspect(payload):
    parser = AnnouncementParser()
    parser.feed(payload.decode("utf-8"))
    if parser.found != 1 or parser.active:
        raise ValueError("one complete announcement required")
    text = "".join(parser.parts)
    required = [
        "THIS IS AN ANNOUNCEMENT FOR THE MSCI GLOBAL STANDARD INDEXES",
        "subject to change before implementation",
        "Friday, March 17, 2023 in GICS Direct",
        "effective June 01, 2023",
        "May 31, 2023.",
    ]
    if any(item not in text for item in required):
        raise ValueError("unrecognized announcement scope or timeline")
    stamp = re.search(r"^Announcement for (.+?) GMT\s*$", text, re.M)
    if stamp is None:
        raise ValueError("missing public timestamp")
    announced = datetime.strptime(stamp[1], "%B %d, %Y at %I:%M %p").replace(tzinfo=timezone.utc)
    summary = re.search(r"^USA\s+(\d+)\s*$", text, re.M)
    body = re.search(r"^USA\s*\n(.*?)^VIETNAM\s*$", text, re.M | re.S)
    if summary is None or body is None:
        raise ValueError("missing USA count or section boundary")
    lines = [line.strip() for line in body[1].splitlines() if line.strip()]
    if len(lines) != int(summary[1]) * 3 or not lines:
        raise ValueError("incomplete USA records")
    rows = []
    for pos in range(0, len(lines), 3):
        old = re.fullmatch(r"CURRENT GICS SUB-INDUSTRY\s+(\d{8})\s+.+", lines[pos + 1])
        new = re.fullmatch(r"NEW GICS SUB-INDUSTRY\s+(\d{8})\s+.+", lines[pos + 2])
        if old is None or new is None:
            raise ValueError("invalid GICS code record")
        rows.append({"source_company_label": lines[pos], "current_subindustry_code": old[1],
                     "announced_new_subindustry_code": new[1],
                     "sector_code_changes": old[1][:2] != new[1][:2]})
    if len({row["source_company_label"] for row in rows}) != len(rows):
        raise ValueError("duplicate company label")
    metadata = {
        "source_scope": "MSCI_GLOBAL_STANDARD_INDEXES",
        "announced_at_utc": announced.isoformat(),
        "source_status": "ANNOUNCED_SUBJECT_TO_REVISION",
        "msci_effective_date": "2023-06-01",
        "msci_after_close_date": "2023-05-31",
        "separately_referenced_gics_direct_spdji_after_close_date": "2023-03-17",
        "effective_intraday_timestamp_certified": False,
        "usa_declared_count": int(summary[1]), "usa_parsed_count": len(rows),
        "usa_sector_code_changes": sum(row["sector_code_changes"] for row in rows),
        "sector_code_transition_counts": dict(sorted(Counter(
            row["current_subindustry_code"][:2] + "->" + row["announced_new_subindustry_code"][:2]
            for row in rows if row["sector_code_changes"]).items())),
        "certified_s6_members": 0, "certified_s6_rebalances": 0,
        "usable_as_s6_input": False,
        "blocking_reasons": ["different index universe", "preliminary event list, not full sector history",
                             "no stable security identifiers", "no S&P-specific final company classification chain",
                             "no shares, units, delisting or execution price inputs"],
    }
    return metadata, rows


def main():
    folder = Path(__file__).resolve().parent
    payload = (folder / "msci_20230502_announcement.html").read_bytes()
    receipts = json.loads((folder / "source_access.json").read_text())
    receipt = next(item for item in receipts if item["path"] == "msci_20230502_announcement.html")
    if hashlib.sha256(payload).hexdigest() != receipt["sha256"]:
        raise ValueError("source bytes changed")
    metadata, rows = inspect(payload)
    metadata["source_sha256"] = receipt["sha256"]
    for name in ("source_diagnostics.json", "usa_announced_code_changes.csv"):
        if (folder / name).exists():
            raise SystemExit("Existing diagnostics preserved; do not repeat a completed extraction")
    with (folder / "usa_announced_code_changes.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (folder / "source_diagnostics.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
