"""Checkpointed SEC 13F share-count source extraction, not an alpha backtest."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CIKS = (
    "0001067983", "0001649339", "0001336528", "0001697748",
    "0001536411", "0001656456", "0001061768",
)
START, END = "2010-01-01", "2024-09-30"
HEADER = ["manager_cik", "accession", "form", "period", "filed", "accepted_at",
          "cusip", "name", "shares", "share_type", "value_reported", "portfolio_value_reported_equity"]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(element: ET.Element, name: str) -> str:
    for child in element.iter():
        if local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def parse_equity_shares(xml_bytes: bytes) -> tuple[list[dict], dict]:
    """Keep common-share positions; report exclusions instead of treating them as zero."""
    root = ET.fromstring(xml_bytes)
    aggregate: dict[str, dict] = {}
    counts = {"information_rows": 0, "options": 0, "principal": 0, "invalid": 0}
    for item in root.iter():
        if local_name(item.tag) != "infoTable":
            continue
        counts["information_rows"] += 1
        if child_text(item, "putCall"):
            counts["options"] += 1
            continue
        share_type = child_text(item, "sshPrnamtType").upper()
        if share_type != "SH":
            counts["principal"] += 1
            continue
        cusip = child_text(item, "cusip").upper()
        try:
            shares = float(child_text(item, "sshPrnamt"))
            value = float(child_text(item, "value"))
        except ValueError:
            counts["invalid"] += 1
            continue
        if not cusip or shares <= 0 or value < 0:
            counts["invalid"] += 1
            continue
        row = aggregate.setdefault(cusip, {"cusip": cusip, "name": child_text(item, "nameOfIssuer"),
                                           "shares": 0.0, "share_type": "SH", "value_reported": 0.0})
        row["shares"] += shares
        row["value_reported"] += value
    return list(aggregate.values()), counts


def entries_from_submissions(meta: dict, older: list[dict]) -> list[dict]:
    """Include amendments and retain the SEC acceptance time when supplied."""
    entries: dict[str, dict] = {}
    for block in [(meta.get("filings") or {}).get("recent") or {}, *older]:
        forms = block.get("form") or []
        for i, form in enumerate(forms):
            if form not in {"13F-HR", "13F-HR/A"}:
                continue
            def field(name: str) -> str:
                values = block.get(name) or []
                return str(values[i] or "") if i < len(values) else ""
            filed = field("filingDate")
            accession = field("accessionNumber")
            if not accession or not (START <= filed <= END):
                continue
            entries[accession] = {"accession": accession, "form": form, "filed": filed,
                                  "period": field("reportDate"), "accepted_at": field("acceptanceDateTime")}
    return sorted(entries.values(), key=lambda x: (x["filed"], x["accession"]))


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def fetch_entries(client, cik: str, checkpoint: Path) -> list[dict]:
    cache = checkpoint / f"submissions-{cik}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    meta = json.loads(client._get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    older = []
    for info in (meta.get("filings") or {}).get("files") or []:
        name = str(info.get("name", ""))
        if name.startswith("CIK") and name.endswith(".json"):
            older.append(json.loads(client._get(f"https://data.sec.gov/submissions/{name}")))
    entries = entries_from_submissions(meta, older)
    atomic_json(cache, entries)
    return entries


def fetch_filing(client, cik: str, item: dict) -> dict:
    accession = item["accession"]
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
    try:
        listing = json.loads(client._get(base + "/index.json"))
    except Exception as exc:
        if getattr(exc, "status", None) == 404:
            return {"source_status": "MISSING_ARCHIVE_INDEX", "item": item, "rows": []}
        raise
    names = [str(x.get("name", "")) for x in (listing.get("directory") or {}).get("item") or []]
    xmls = [x for x in names if x.lower().endswith(".xml") and "primary_doc" not in x.lower()]
    selected = next((x for x in xmls if "info" in x.lower()), xmls[0] if xmls else "")
    if not selected:
        return {"source_status": "NO_XML_INFORMATION_TABLE", "item": item, "rows": []}
    try:
        rows, counts = parse_equity_shares(client._get(base + "/" + selected))
    except ET.ParseError:
        return {"source_status": "INVALID_XML_INFORMATION_TABLE", "item": item, "rows": []}
    except Exception as exc:
        if getattr(exc, "status", None) == 404:
            return {"source_status": "MISSING_INFORMATION_XML", "item": item, "rows": []}
        raise
    total = sum(row["value_reported"] for row in rows)
    return {"source_status": "PARSED" if rows else "NO_EQUITY_ROWS", "item": item, "rows": rows,
            "portfolio_value_reported_equity": total, "counts": counts}


def write_outputs(out: Path, checkpoint: Path, manifest: list[tuple[str, dict]], *, smoke: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "13f_raw_shares.csv"
    temporary = csv_path.with_suffix(".csv.tmp")
    status_counts: dict[str, int] = {}
    rows_written = 0
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        for cik, item in manifest:
            path = checkpoint / "filings" / f"{item['accession']}.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            status = record["source_status"]
            status_counts[status] = status_counts.get(status, 0) + 1
            for row in record.get("rows", []):
                writer.writerow({"manager_cik": cik, **record["item"], **row,
                                 "portfolio_value_reported_equity": record.get("portfolio_value_reported_equity")})
                rows_written += 1
    temporary.replace(csv_path)
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    verdict = ("SMOKE_ONLY" if smoke else
               "SOURCE_EXTRACTED_PARTIAL_REVIEW_REQUIRED" if rows_written else "NOT_EVALUABLE_SOURCE_EMPTY")
    result = {"id": "alpha-13f-source-v1", "phase": "public_source_extraction_only",
              "verdicts": {"primary": verdict}, "performance_calculated": False,
              "filings_in_manifest": len(manifest), "filing_status_counts": status_counts,
              "equity_rows": rows_written, "csv_sha256": digest,
              "accepted_timestamp_filings": sum(bool(item["accepted_at"]) for _, item in manifest),
              "source_window": [START, END],
              "limitations": ["pre-2013 text-based 13F may have no XML",
                              "reported values require unit normalization before weighting",
                              "shares require split adjustment before comparing quarters",
                              "CUSIP-to-historical-security and delisting returns are absent"]}
    report = ("# 13F 공개 원본 주식 수 추출\n\n" + f"**{verdict}**; 전략 수익률·알파는 계산하지 않았다.\n\n"
              + f"대상 신고 {len(manifest)}건, SH 보유 행 {rows_written}개, 상태 {status_counts}.\n\n"
              + "원본에는 분할 조정·시점별 증권 매핑·상장폐지 수익이 없어 본 실험에 곧바로 쓸 수 없다. "
                "2013년 이전 텍스트 13F는 별도 파서가 필요할 수 있다.\n")
    atomic_json(out / "results.json", result)
    (out / "REPORT.md").write_text(report, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--smoke", action="store_true")
    opts = parser.parse_args(argv)
    if opts.smoke:
        xml = (b'<informationTable><infoTable><nameOfIssuer>Example</nameOfIssuer>'
               b'<cusip>123456789</cusip><value>100</value><shrsOrPrnAmt>'
               b'<sshPrnamt>50</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>'
               b'</shrsOrPrnAmt></infoTable></informationTable>')
        item = {"accession": "0000000000-20-000001", "form": "13F-HR", "period": "2020-03-31",
                "filed": "2020-05-15", "accepted_at": "2020-05-15T17:00:00"}
        rows, counts = parse_equity_shares(xml)
        atomic_json(opts.checkpoint / "filings" / f"{item['accession']}.json",
                    {"source_status": "PARSED", "item": item, "rows": rows,
                     "counts": counts, "portfolio_value_reported_equity": 100.0})
        write_outputs(opts.out, opts.checkpoint, [(CIKS[0], item)], smoke=True)
        return 0
    from core.filing_changes import EdgarBlocked, EdgarClient, EdgarUndeclaredUserAgent
    client = EdgarClient(record_first_seen=False)
    deadline = float(os.getenv("RESEARCH_JOB_DEADLINE_EPOCH", "inf")) - 45
    manifest: list[tuple[str, dict]] = []
    try:
        for cik in CIKS:
            if time.time() >= deadline:
                return 3
            for item in fetch_entries(client, cik, opts.checkpoint):
                manifest.append((cik, item))
                target = opts.checkpoint / "filings" / f"{item['accession']}.json"
                if target.is_file():
                    continue
                if time.time() >= deadline:
                    return 3
                atomic_json(target, fetch_filing(client, cik, item))
    except (EdgarBlocked, EdgarUndeclaredUserAgent) as exc:
        opts.out.mkdir(parents=True, exist_ok=True)
        atomic_json(opts.out / "results.json", {"id": "alpha-13f-source-v1", "phase": "source_extraction",
                    "verdicts": {"primary": "NOT_EVALUABLE_SOURCE_ACCESS"},
                    "performance_calculated": False, "error_kind": type(exc).__name__})
        (opts.out / "REPORT.md").write_text("# 13F 원본 수집\n\nSEC 접근이 차단돼 원본을 수집하지 못했다.\n", encoding="utf-8")
        (opts.out / "13f_raw_shares.csv").write_text(",".join(HEADER) + "\n", encoding="utf-8")
        return 0
    write_outputs(opts.out, opts.checkpoint, manifest, smoke=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
