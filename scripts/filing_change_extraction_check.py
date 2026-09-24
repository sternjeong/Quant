"""RES-05 실제 EDGAR 소규모 점검: 서로 다른 기업의 최근 공시 2개씩으로 섹션 추출 성공률과 diff 크기를 잰다.

사람 확인용 표본이며 정확도 주장이 아니다. DB에 쓰지 않고 주문 경로와 무관하다.
SEC 가 차단(403 등)하면 재시도하지 않고 그 사실만 기록한 뒤 멈춘다. User-Agent 값은 어디에도 기록하지 않는다
(사용한 환경변수 이름만 기록한다).

사용: python -m scripts.filing_change_extraction_check [--forms 10-K 10-Q] [--out docs/experiment_validation/...md]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import filing_changes as fc  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "docs" / "experiment_validation" / "filing_change_extraction_check.md"
MANUAL_MARKER = "<!-- manual-notes: 이 줄 아래는 스크립트가 다시 실행돼도 보존된다 -->"

# 산업이 다른 5개 기업. CIK 는 submissions 응답의 tickers 필드로 대조한다(불일치하면 표에 표시).
DEFAULT_COMPANIES = [
    ("AAPL", "0000320193", "대형 기술"),
    ("F", "0000037996", "제조·자동차, 금융 자회사 포함"),
    ("GME", "0001326380", "소매, 적자·구조조정 이력"),
    ("JPM", "0000019617", "대형 은행(MD&A 구조가 다름)"),
    ("PTON", "0001639825", "적자 성장주, 6월 결산"),
]


def _short(text: str, n: int = 150) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n] + "..."


def _md_cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def check_company(client, ticker: str, cik: str, form: str) -> dict:
    row = {"ticker": ticker, "cik": cik, "form": form, "error": None}
    t0 = time.time()
    recs = client.list_filings(cik=cik, forms=(form,))  # 정정본 제외
    meta_ok = bool(recs) and recs[0].ticker is not None and recs[0].ticker.upper() == ticker
    row["ticker_matches_sec_metadata"] = meta_ok
    if len(recs) < 2:
        row["error"] = f"공시 {len(recs)}개뿐이라 비교 불가"
        return row
    current = recs[0]
    prior = fc.find_prior_filing(recs, current)
    if prior is None:
        row["error"] = "직전 동종 공시 없음"
        return row
    cur_html = client.fetch_primary_document(current)
    pri_html = client.fetch_primary_document(prior)
    t1 = time.time()
    ev = fc.build_filing_change_event(current, cur_html, prior, pri_html)
    parse_s = time.time() - t1
    cur_secs = fc.extract_sections(fc.text_from_document(cur_html), form)
    pri_secs = fc.extract_sections(fc.text_from_document(pri_html), form)
    dec = fc.filing_veto([ev])
    row.update({
        "current": current.accession, "prior": prior.accession,
        "current_report": current.report_date, "prior_report": prior.report_date,
        "current_bytes": len(cur_html), "prior_bytes": len(pri_html),
        "event": ev, "cur_secs": cur_secs, "pri_secs": pri_secs, "veto": dec,
        "fetch_seconds": round(t1 - t0, 1), "process_seconds": round(parse_s, 1),
    })
    return row


def _sec_cell(sec) -> str:
    if sec.status == "ok":
        return f"ok ({sec.char_count:,}자)"
    return sec.status


def render(rows: list, forms: list, ua_source: str, requests_made: int, blocked: str | None) -> str:
    out = []
    a = out.append
    a("# 공시 변화 추출 소규모 점검 (RES-05)")
    a("")
    a("상태: **사람 확인용 표본 점검**. 추출 정확도·예측력·성과를 주장하지 않는다. 표본이 5개 기업이라 성공률의 일반화도 불가능하다. "
      "DB·주문 경로와 무관하며 shadow 준비 단계의 코드 동작 확인이다.")
    a("")
    a("## 조건")
    a("")
    a(f"- 실행일: {date.today().isoformat()}")
    a("- 도구: `scripts/filing_change_extraction_check.py` (`core/filing_changes.py`의 `EdgarClient`, `extract_sections`, `build_filing_change_event`)")
    a(f"- User-Agent 출처: 환경변수 `{ua_source}` (값은 기록하지 않는다). 초당 5회 이하, 정정본(10-K/A 등) 제외")
    a(f"- 이번 실행의 HTTP 요청 수(캐시 적중 제외): {requests_made}")
    a("- 비교: 기업마다 최근 원본 공시 2개(현재, 직전 동종). 옵션은 기본값(최소 길이 1,200자 등)")
    if blocked:
        a(f"- **SEC 접속 차단으로 점검 중단:** {blocked} (재시도하지 않음)")
    a("")
    for form in forms:
        frows = [r for r in rows if r["form"] == form]
        if not frows:
            continue
        a(f"## {form} 결과")
        a("")
        a("| 기업 | 현재 / 직전 보고기간 | Item 1A 현재 | Item 1A 직전 | 유동성 현재 | 유동성 직전 | 비고 |")
        a("|---|---|---|---|---|---|---|")
        for r in frows:
            if r.get("error"):
                a(f"| {r['ticker']} | - | - | - | - | - | 오류: {_md_cell(r['error'])} |")
                continue
            cs, ps = r["cur_secs"], r["pri_secs"]
            note = "" if r["ticker_matches_sec_metadata"] else "티커가 SEC 메타데이터와 불일치(확인 필요)"
            a(f"| {r['ticker']} | {r['current_report']} / {r['prior_report']} | {_sec_cell(cs[fc.SECTION_RISK])} | "
              f"{_sec_cell(ps[fc.SECTION_RISK])} | {_sec_cell(cs[fc.SECTION_LIQUIDITY])} | "
              f"{_sec_cell(ps[fc.SECTION_LIQUIDITY])} | {note} |")
        a("")
        # 성공률
        total = {fc.SECTION_RISK: {}, fc.SECTION_LIQUIDITY: {}}
        n_docs = 0
        for r in frows:
            if r.get("error"):
                continue
            for secs in (r["cur_secs"], r["pri_secs"]):
                n_docs += 1
                for name in total:
                    st = secs[name].status
                    total[name][st] = total[name].get(st, 0) + 1
        n_docs //= 1
        per_section_docs = n_docs // 1
        a(f"**섹션 추출 상태 집계** (공시 문서 {n_docs // 2 * 2}개 기준, 문서마다 두 절을 추출)")
        a("")
        a("| 절 | ok | reference_only | not_applicable | section_not_found | ok 비율 |")
        a("|---|---|---|---|---|---|")
        for name, d in total.items():
            n = sum(d.values())
            a(f"| {name} | {d.get('ok', 0)} | {d.get('reference_only', 0)} | {d.get('not_applicable', 0)} | "
              f"{d.get('section_not_found', 0)} | {d.get('ok', 0)}/{n} |")
        a("")
        a("**diff 크기와 이벤트 결과** (현재 vs 직전, 절이 둘 다 ok 일 때만 비교)")
        a("")
        a("| 기업 | 절 | 문장(현재/직전) | 동일 | 숫자변경 | 재서술 | 신규 | 삭제 | 이동 | 신규 태그(is_new) | 플래그 |")
        a("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in frows:
            if r.get("error"):
                continue
            ev = r["event"]
            for name in (fc.SECTION_RISK, fc.SECTION_LIQUIDITY):
                sd = ev.sections[name]
                if sd.status != "ok":
                    a(f"| {r['ticker']} | {name} | 비교 안 함 ({sd.current_status}/{sd.prior_status}) | | | | | | | | |")
                    continue
                c = sd.counts
                new_tags = [t for t in sd.tags if t.is_new]
                cats = {}
                for t in new_tags:
                    cats[t.category] = cats.get(t.category, 0) + 1
                tagtxt = ", ".join(f"{k.split('_')[0]}:{v}" for k, v in sorted(cats.items())) or "0"
                a(f"| {r['ticker']} | {name} | {c['sentences_current']}/{c['sentences_prior']} | {c['unchanged']} | "
                  f"{c['numeric_changed']} | {c['reworded']} | {c['new']} | {c['deleted']} | "
                  f"{c['moved_from_other_section']} | {tagtxt} | {_md_cell(', '.join(sd.flags)) or '-'} |")
        a("")
        a("**이벤트 수준** (veto 는 후보 규칙의 출력일 뿐이며 옳고 그름을 평가하지 않았다)")
        a("")
        a("| 기업 | 이벤트 플래그 | veto 출력(as_of 미지정) | 문서 크기(현재/직전, MB) | 조회/처리 초 |")
        a("|---|---|---|---|---|")
        for r in frows:
            if r.get("error"):
                continue
            ev, v = r["event"], r["veto"]
            a(f"| {r['ticker']} | {_md_cell(', '.join(ev.flags)) or '-'} | {v.decision} ({', '.join(v.reason_codes)}) | "
              f"{r['current_bytes'] / 1e6:.1f}/{r['prior_bytes'] / 1e6:.1f} | {r['fetch_seconds']}/{r['process_seconds']} |")
        a("")
        a("**사람이 확인할 발췌** (경계·머리글이 맞는지 눈으로 확인하는 용도)")
        a("")
        for r in frows:
            if r.get("error"):
                continue
            for label, secs in (("현재", r["cur_secs"]), ("직전", r["pri_secs"])):
                for name, sec in secs.items():
                    if sec.status == "ok":
                        a(f"- {r['ticker']} {label} `{name}`: 머리글 `{_md_cell(sec.heading or '')}`, 끝 `{_md_cell(sec.end_reason or '')}`, "
                          f"시작 \"{_md_cell(_short(sec.text, 120))}\", 끝부분 \"{_md_cell(_short(sec.text[-160:], 120))}\"")
                    else:
                        a(f"- {r['ticker']} {label} `{name}`: **{sec.status}** {_md_cell('; '.join(sec.notes))}")
            ev = r["event"]
            anchors = [t for sd in ev.sections.values() for t in sd.tags if t.is_new][:3]
            for t in anchors:
                a(f"  - 신규 태그 예 [{t.category}/{t.severity}/{t.modality}/{t.novelty}] \"{_md_cell(_short(t.anchor, 200))}\"")
        a("")
    a(MANUAL_MARKER)
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forms", nargs="+", default=["10-K"])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    client = fc.EdgarClient()
    rows, blocked = [], None
    try:
        for form in args.forms:
            for ticker, cik, _desc in DEFAULT_COMPANIES:
                try:
                    rows.append(check_company(client, ticker, cik, form))
                except (fc.EdgarBlocked, fc.EdgarRateLimited) as exc:
                    blocked = f"{type(exc).__name__} (HTTP {exc.status}, {ticker} {form})"
                    raise
                except fc.EdgarFetchError as exc:
                    rows.append({"ticker": ticker, "cik": cik, "form": form,
                                 "error": f"{type(exc).__name__}: {exc.kind}"})
                print(f"{form} {ticker}: done", flush=True)
    except (fc.EdgarBlocked, fc.EdgarRateLimited):
        print(f"BLOCKED: {blocked}", flush=True)
    text = render(rows, args.forms, client.user_agent_source, client.requests_made, blocked)
    out = Path(args.out)
    manual = ""
    if out.exists():
        old = out.read_text(encoding="utf-8")
        if MANUAL_MARKER in old:
            manual = old.split(MANUAL_MARKER, 1)[1]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + manual, encoding="utf-8")
    print(f"wrote {out}", flush=True)
    return 0 if not blocked else 2


if __name__ == "__main__":
    raise SystemExit(main())
