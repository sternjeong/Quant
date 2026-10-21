"""Fail-closed source audit for the four preregistered stock-alpha proposals.

These jobs deliberately do not calculate performance. A readable file header is
neither a point-in-time certification nor a survivorship-free return history.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from core.research_power import power_line, power_report

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/research_inputs/crsp_sp500"
COMMON = {
    "daily.csv": {"permno", "date", "prc", "ret", "vol", "shrout"},
    "names.csv": {"permno", "namedt", "nameendt", "siccd", "exchcd", "shrcd"},
    "delists.csv": {"permno", "date", "dlret", "dlstcd"},
    "sp500.csv": {"permno", "start", "ending"},
    "security_map.csv": {"permno", "cik", "cusip", "start", "ending"},
    "ff5_umd_monthly.csv": {"date", "mktrf", "smb", "hml", "rmw", "cma", "umd", "rf"},
    "fx_daily.csv": {"date", "usdkrw"},
}
SIGNALS = {
    "alpha-13f-conviction-v1": {
        "13f_holdings_pit.csv": {"manager_cik", "accession", "period", "accepted_at", "permno", "cusip", "shares", "value_usd", "portfolio_value_usd", "amendment_of"},
        "splits.csv": {"permno", "ex_date", "factor"},
    },
    "alpha-cash-quality-v1": {
        "companyfacts_pit.csv": {"cik", "accession", "accepted_at", "fiscal_start", "fiscal_end", "concept", "unit", "value", "form"},
    },
    "alpha-filing-drift-v1": {
        "8k_item202_pit.csv": {"cik", "accession", "accepted_at", "items", "permno"},
        "sector_daily.csv": {"date", "sector", "return"},
        "sector_pit.csv": {"permno", "start", "ending", "sector"},
    },
    "alpha-customer-link-v1": {
        "customer_links_pit.csv": {"supplier_cik", "customer_cik", "supplier_permno", "customer_permno", "accession", "accepted_at", "fiscal_end", "revenue_share"},
    },
}
REQUIREMENTS = {
    "alpha-13f-conviction-v1": "7개 고정 운용사의 분기별 원본 주식 수·분할·정정·공개시각과 평가액 매핑률 95%",
    "alpha-cash-quality-v1": "당시 공개된 총이익·자산·영업현금흐름·순이익의 회계기간/접수시각 및 TTM 구성",
    "alpha-filing-drift-v1": "8-K Item 2.02 접수시각, 해당 시점 증권·업종 식별, 공시 후 완전한 3거래일",
    "alpha-customer-link-v1": "과거 10-K에 공개된 고객 실명·매출비중·접수시각과 양사 증권 매핑",
}


def audit_files(base: Path, required: dict[str, set[str]]) -> list[dict]:
    checks = []
    for filename, fields in required.items():
        path = base / filename
        item = {"file": filename, "status": "MISSING"}
        if path.is_file():
            try:
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    header = {name.strip().lower() for name in (next(csv.reader(handle)) or [])}
                missing = sorted(fields - header)
                item = {"file": filename, "status": "COLUMNS_MISSING" if missing else "HEADER_PRESENT", "missing_columns": missing}
            except (OSError, StopIteration, UnicodeError, csv.Error):
                item = {"file": filename, "status": "UNREADABLE"}
        checks.append(item)
    return checks


def cache_evidence(root: Path, job_id: str) -> dict:
    folder = root / "data/satellite_lab" / ("guru13f" if "13f" in job_id else "fundamentals")
    if job_id not in {"alpha-13f-conviction-v1", "alpha-cash-quality-v1"}:
        return {"legacy_cache": "no validated source cache"}
    files = list(folder.glob("*.json")) if folder.is_dir() else []
    evidence = {"legacy_cache_files": len(files), "readable_files": 0,
                "filings_or_facts": 0, "records_with_required_raw_fields": 0}
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        evidence["readable_files"] += 1
        if "13f" in job_id:
            for filing in data.get("filings", []):
                evidence["filings_or_facts"] += 1
                if filing.get("holdings") and all("shares" in h for h in filing["holdings"]):
                    evidence["records_with_required_raw_fields"] += 1
        else:
            facts = data.get("facts", {})
            evidence["filings_or_facts"] += sum(len(v) for v in facts.values() if isinstance(v, list))
            if any("cash" in key.lower() and "operat" in key.lower() for key in facts):
                evidence["records_with_required_raw_fields"] += 1
    return evidence


def write_atomic(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(path)


def main(job_id: str, argv: list[str] | None = None) -> int:
    if job_id not in SIGNALS:
        raise ValueError(job_id)
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--smoke", action="store_true")
    options = parser.parse_args(argv)
    # Smoke checks a deliberately empty temporary bundle; it never reads or
    # alters operating data and its counts never become a research result.
    base = options.checkpoint / "synthetic_empty_bundle" if options.smoke else BASE
    checks = audit_files(base, COMMON | SIGNALS[job_id])
    evidence = {} if options.smoke else cache_evidence(ROOT, job_id)
    missing = [x["file"] for x in checks if x["status"] != "HEADER_PRESENT"]
    status = "NOT_EVALUABLE_DATA" if missing else "INPUTS_PRESENT_REVIEW_REQUIRED"
    if options.smoke:
        status = "SMOKE_ONLY"
    power = power_report(14.75, 4)
    result = {
        "id": job_id + "-input-audit", "target_experiment": job_id,
        "phase": "source_eligibility_only", "smoke": options.smoke,
        "verdicts": {"primary": status}, "performance_calculated": False,
        "required_source": REQUIREMENTS[job_id], "file_checks": checks,
        "legacy_cache_evidence": evidence, "power": power,
        "power_basis": "planned 2010-01 through 2024-09 horizon; zero eligible observations certified",
        "next_gate": "Verify complete point-in-time rows, delisting returns and security identity, then implement the frozen return test under the target experiment ID.",
    }
    report = (f"# {job_id} 자료 적격성 검사\n\n"
              f"**{status}** — 전략 수익률·알파·통과 판정은 계산하지 않았다.\n\n"
              f"필수 근거: {REQUIREMENTS[job_id]}\n\n"
              f"공통: 당시 구성종목·증권 식별·상장폐지 수익·요인·환율이 모두 있어야 한다.\n\n"
              + "\n".join(f"- {x['file']}: {x['status']}" for x in checks) + "\n\n"
              + f"기존 캐시 요약: {json.dumps(evidence, ensure_ascii=False)}\n\n"
              + "계획 구간만 가정한 사전 검정력(적격 관측치 0건): " + power_line(power) + "\n\n"
              + "다음: 원본 데이터의 시점별 완전성·상장폐지 결합을 검증한 뒤 고정 규칙으로 별도 성과 작업을 실행한다.\n")
    write_atomic(options.out / "results.json", json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    write_atomic(options.out / "REPORT.md", report)
    return 0
