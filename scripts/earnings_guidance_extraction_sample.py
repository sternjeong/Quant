"""실제 EDGAR 보도자료 추출 표본 문서 생성기 (RES-04 1단계, 사람 검증용 표본).

사용: python scripts/earnings_guidance_extraction_sample.py [--out PATH] [--history N]

- 표본 규칙(사전 고정): 아래 TICKERS 의 각 기업에서 **가장 최근** 8-K Item 2.02 를 1건 고르고, 자동 변화 분류를
  보여주기 위해 그 직전 N건(기본 3)을 이력으로만 추출한다. 결과가 좋은 문서만 고르지 않는다.
- SEC 접속: core.earnings_events 의 User-Agent 규칙(SEC_EDGAR_USER_AGENT -> SEC_USER_AGENT -> 일반 문자열)을
  따른다. 값은 출력·문서에 기록하지 않는다. 403 이 나오면 재시도하지 않고 중단한다.
- 이 문서는 사람이 정답을 대조하기 위한 표본이며 추출 정확도를 주장하지 않는다(작성자=검증자 문제).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import earnings_events as ee  # noqa: E402

# (표시 이름, CIK). 결과를 보기 전에 정한 목록이다(대형 기술·반도체·소프트웨어·소비재·유통 혼합).
TICKERS = [
    ("NVDA", 1045810), ("CSCO", 858877), ("MU", 723125), ("ADBE", 796343), ("CRM", 1108524), ("AVGO", 1730168),
    ("LULU", 1397187), ("TXN", 97476), ("SNOW", 1640147), ("DELL", 1571996), ("BBY", 764478), ("AAPL", 320193),
]
DEFAULT_OUT = PROJECT_ROOT / "docs" / "experiment_validation" / "earnings_guidance_extraction_sample.md"


def _fmt(v: str | None, unit: str | None) -> str:
    if v is None:
        return "-"
    if unit == "currency":
        try:
            return f"{float(v):,.0f}"
        except ValueError:
            return v
    return v


def _cell(text: str, n: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).replace("|", "\\|").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _candidate_sentences(text: str, limit: int = 3) -> list[str]:
    out = []
    for line in ee.normalize_text(text).split("\n"):
        for sentence in ee._split_sentences(line):
            if re.search(r"outlook|guidance|expect", sentence, re.I) and re.search(r"[\$%]\s?\d|\d\s?(?:%|million|billion)", sentence) \
                    and not ee._DISCLAIMER_RE.search(sentence):
                out.append(sentence)
    return out[:limit]


def run(out_path: Path, history_n: int) -> int:
    client = ee.SecEdgarClient()
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    module_hash = hashlib.sha256((PROJECT_ROOT / "core" / "earnings_events.py").read_bytes()).hexdigest()[:12]
    rows = []  # 요약 표
    blocks = []
    status_counter: Counter = Counter()
    item_total = 0
    item_problem = 0
    change_counter: Counter = Counter()
    fetch_failures = []

    for ticker, cik in TICKERS:
        try:
            filings = ee.list_earnings_filings(client, cik)
        except ee.SecAccessError as exc:
            print(f"SEC 접근 차단으로 중단: {type(exc).__name__}", file=sys.stderr)
            return 2
        except ee.SecFetchError as exc:
            fetch_failures.append((ticker, "submissions", str(exc)[:120]))
            continue
        if not filings:
            fetch_failures.append((ticker, "8-K Item 2.02 없음", ""))
            continue
        latest = filings[-1]
        prior = filings[-1 - history_n:-1]
        hist_items = []
        hist_rows = []
        for f in prior:
            try:
                rel, res = ee.extract_from_filing(client, f)
            except ee.SecAccessError as exc:
                print(f"SEC 접근 차단으로 중단: {type(exc).__name__}", file=sys.stderr)
                return 2
            except ee.SecFetchError as exc:
                hist_rows.append((f, "fetch 실패", 0))
                continue
            hist_items.extend(res.items)
            hist_rows.append((f, res.status, len(res.items)))
        try:
            release, result = ee.extract_from_filing(client, latest)
        except ee.SecAccessError as exc:
            print(f"SEC 접근 차단으로 중단: {type(exc).__name__}", file=sys.stderr)
            return 2
        except ee.SecFetchError as exc:
            fetch_failures.append((ticker, latest.accession, str(exc)[:120]))
            continue
        timing = ee.classify_release_session(latest.acceptance_utc)
        entry = ee.next_executable_open(latest.acceptance_utc)
        status_counter[result.status] += 1
        item_total += len(result.items)
        changes = ee.compute_guidance_changes(result.items, hist_items)
        for c in changes:
            change_counter[c.change] += 1
        item_problem += sum(1 for i in result.items if i.problems)
        rows.append((ticker, latest, release, result, timing))

        b = [f"### {ticker} — {latest.company_name or ''} ({latest.accession})", ""]
        b.append(f"- 8-K acceptance: {latest.acceptance_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC = "
                 f"{timing.acceptance_et.strftime('%Y-%m-%d %H:%M ET')} ({timing.session}); "
                 f"다음 실행가능 시가(주말만 제외): {entry.entry_date}")
        b.append(f"- 보도자료: {release.exhibit_type} — {release.document_url}" if release else "- 보도자료: 특정 못 함")
        b.append(f"- 원문 해시(sha256, 앞 12자): {release.content_sha256[:12] if release else '-'} / "
                 f"텍스트 {len(release.text) if release else 0:,}자")
        b.append(f"- 추출 상태: **{result.status}** (item {len(result.items)}건, skipped {len(result.skipped)}건)")
        b.append(f"- 이력 릴리스(변화 비교용, 같은 방식으로 추출): " + ", ".join(
            f"{f.accession}[{st}, {n}건]" for f, st, n in hist_rows) if hist_rows else "- 이력 릴리스: 없음")
        b.append("")
        if result.items:
            b.append("| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |")
            b.append("|---|---|---|---|---|---|---|---|---|---|---|")
            for n, (item, chg) in enumerate(zip(result.items, changes), start=1):
                rec = item.to_record()
                b.append(
                    f"| {n} | {item.metric} | {item.basis} | {item.period_key or '(미확정) ' + (item.period_raw or '')} | "
                    f"{_fmt(rec['low'], item.unit)} ~ {_fmt(rec['high'], item.unit)} | "
                    f"{item.unit or '-'}{'/' + item.currency if item.currency else ''} | {item.shape} | "
                    f"{', '.join(item.flags) or '-'} | {chg.change}({chg.reason}) | {_cell(item.anchor)} | [ ] |")
            b.append("")
        if result.skipped:
            b.append("추출기가 건너뛴 후보(사유):")
            for sk in result.skipped[:5]:
                b.append(f"- `{sk.reason}` — {_cell(sk.anchor, 200)}")
            b.append("")
        if result.status != "guidance_found" and release is not None:
            cands = _candidate_sentences(release.text)
            b.append("recall 검토용: 추출기가 가이던스로 잡지 못했지만 전망 표현과 숫자가 함께 있는 문장(최대 3개)")
            b.extend([f"- {_cell(s, 260)}" for s in cands] or ["- (해당 문장 없음: 사람이 원문에서 가이던스 유무를 직접 확인)"])
            b.append("")
        blocks.append("\n".join(b))

    n_rel = len(rows)
    lines = [
        "# 가이던스 추출 품질 검증 표본 (실제 EDGAR 보도자료)",
        "",
        "상태: **검증 대기**. 이 문서는 사람이 원문과 대조해 정답을 확인하기 위한 표본이다. 추출기 작성자가 이 표를 만들었으므로 "
        "(작성자=검증자 문제) **정확도를 주장하지 않는다.** 아래 '사람 확인' 열은 비어 있다.",
        "",
        f"- 생성: {generated}, 스크립트 `scripts/earnings_guidance_extraction_sample.py`, `core/earnings_events.py` sha256 앞 12자 `{module_hash}`",
        f"- 표본 규칙(결과를 보기 전에 고정): TICKERS {len(TICKERS)}개 각각의 최신 8-K Item 2.02 1건. "
        f"직전 {history_n}건은 자동 change 계산용 이력으로만 추출했다. 문서 선택에 추출 성공 여부를 쓰지 않았다.",
        "- 이 표본은 스펙 G0(scalar 필드 exact match ≥95%, 방향 오류 0건)을 판정하기에 부족하다: 스펙은 최소 60 item, 30개 이상 서로 다른 발표, "
        "8개 이상 기업과 추출기 작성자와 다른 정답 작성자를 요구한다.",
        "- 추출기를 이 표본 결과에 맞춰 조정하지 않았다(표본 생성 전에 규칙을 고정했고, 표본 생성 이후 규칙 변경은 아래 '수정 이력'에 따로 적는다).",
        "",
        "## 요약(추출 상태 분포 — 정답 대비 정확도가 아니다)",
        "",
        f"- 대상 발표 {len(TICKERS)}건 중 본문 확보 {n_rel}건, 수집 실패 {len(fetch_failures)}건",
    ]
    for status in ("guidance_found", "guidance_language_unparsed", "no_guidance_language"):
        lines.append(f"- `{status}`: {status_counter.get(status, 0)}건")
    unknown_releases = n_rel - status_counter.get("guidance_found", 0)
    lines.append(f"- 가이던스 item을 하나도 얻지 못한 발표(= 추출 unknown 성격): {unknown_releases}/{n_rel} "
                 f"({(unknown_releases / n_rel * 100 if n_rel else 0):.0f}%). 이 중 원문에 실제로 가이던스가 없는 경우와 "
                 "추출기가 놓친 경우는 사람 확인 전에는 구분되지 않는다.")
    lines.append(f"- 추출 item 총 {item_total}건, 그중 비교 불가 문제(기간 미확정·스케일/부호 모호 등) 보유 {item_problem}건")
    lines.append("- 자동 change 분포(최신 발표 item 기준, 미검증): " + (
        ", ".join(f"{k} {v}" for k, v in sorted(change_counter.items())) if change_counter else "없음"))
    if fetch_failures:
        lines.append("- 수집 실패: " + "; ".join(f"{t}({w}) {m}" for t, w, m in fetch_failures))
    lines += ["", "## 발표별 결과", ""]
    lines.extend(blocks)
    lines += [
        "## 사람 검증 절차(제안)", "",
        "1. 정답 작성자는 추출기 작성자와 다른 사람으로 정하고, 이 표를 보기 전에 원문에서 가이던스 항목을 독립적으로 기록한다.",
        "2. 항목별로 metric, 기간, low/high, 단위·통화, basis가 원문과 일치하는지 확인하고, 거래 방향을 바꿀 수 있는 오류(스케일·기간·부호)를 따로 센다.",
        "3. 'guidance_found'가 아닌 발표는 원문에 가이던스가 실제로 없는지(진짜 unknown) 놓친 것인지 확인한다(recall).",
        "4. 결과는 관측 비율과 Wilson 신뢰구간으로 보고하고, 표본 크기가 스펙 G0 요건에 못 미치면 통과로 표시하지 않는다.",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path} (releases={n_rel}, items={item_total}, requests={client.request_count})")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--history", type=int, default=3)
    args = parser.parse_args()
    sys.exit(run(Path(args.out), args.history))
