"""RES-05: SEC 10-K/10-Q 공시 변화 추출과 악재 veto 후보 규칙 (shadow 전용, 가설 검증 준비).

스펙: docs/FILING_CHANGE_VETO_SPEC.md (사전 등록 초안, 미동결).

이 모듈은 다음만 한다.
1. SEC EDGAR submissions API로 10-K/10-Q 목록과 주 문서 HTML을 가져온다 (EdgarClient).
2. HTML을 텍스트로 바꾸고 Item 1A(Risk Factors)와 MD&A 유동성 소절을 추출한다. 못 찾으면 추측하지 않고
   ``section_not_found`` 로 남긴다.
3. 직전 동종 공시와 문장 단위로 신규·삭제·숫자 변화·재서술을 분리하고, 규칙 기반으로 위험 범주를 태깅한다.
   텍스트 유사도 하나로 결론 내지 않는다. 유사도는 "같은 문장의 사소한 수정" 짝짓기에만 쓴다.
4. 결과를 시간 계약 필드가 있는 FilingChangeEvent 로 만들고 JSON 으로 직렬화한다.
5. 단순 규칙 veto 후보 filing_veto() 를 제공한다.

하지 않는 것: DB 쓰기, 주문 경로 연결, LLM 호출, 과거 성과 계산. 모든 결과는 ``pit_certified=False`` 다.
이 모듈의 태그·veto 는 성과가 입증되지 않은 가설 검증용 후보 규칙이다.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone, tzinfo
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "sec_filings"

SCHEMA_VERSION = "filing-change-event-v0.1"
EXTRACTOR_VERSION = "filing-extract-v0.1"
RULES_VERSION = "risk-lexicon-v0.1"
VETO_POLICY_VERSION = "filing-veto-v0.1-hypothesis"

# User-Agent 는 환경변수에서만 읽는다: 기존 관례(core/guru_tracker.py, .env.example)의 SEC_EDGAR_USER_AGENT 를 먼저,
# 없으면 SEC_USER_AGENT, 그래도 없으면 개인정보 없는 일반 문자열. 값은 코드·로그·문서·예외 메시지에 남기지 않는다.
SEC_USER_AGENT_ENVS = ("SEC_EDGAR_USER_AGENT", "SEC_USER_AGENT")
DEFAULT_USER_AGENT = "QuantResearch personal-project"  # 개인정보 없는 일반 문자열. SEC 가 차단할 수 있다.
MAX_REQUESTS_PER_SECOND = 5
SUPPORTED_FORMS = ("10-K", "10-Q")

SECTION_RISK = "item_1a_risk_factors"
SECTION_LIQUIDITY = "mdna_liquidity"
_SECTION_MDNA = "mdna"

CATEGORY_LIQUIDITY = "liquidity_going_concern"
CATEGORY_COMPETITION = "competition"
CATEGORY_CONCENTRATION = "customer_supplier_concentration"
CATEGORY_LITIGATION = "litigation_regulatory"
CATEGORY_CYBER = "cybersecurity"
CATEGORY_ACCOUNTING = "accounting_controls_listing"

_SEVERITY_RANK = {"weak": 1, "moderate": 2, "strong": 3}


# ============================================================================
# 1. 시간 계약: 거래일 · 결정 시계 · 체결 시각
# ============================================================================

_SPECIAL_CLOSURES = frozenset(
    [date(2001, 9, 11), date(2001, 9, 12), date(2001, 9, 13), date(2001, 9, 14),
     date(2004, 6, 11), date(2007, 1, 2), date(2012, 10, 29), date(2012, 10, 30),
     date(2018, 12, 5), date(2025, 1, 9)]
)
DECISION_CLOCK_LOCAL = dtime(16, 0)  # 미국 동부 16:00. 조기 폐장일에도 고정.
FILL_CLOCK_LOCAL = dtime(9, 30)  # 다음 거래일 시가


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """weekday: 월=0. n>0 이면 n번째, n=-1 이면 마지막."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=64)
def nyse_holidays(year: int) -> frozenset:
    """NYSE 정규 휴장일 근사(2001년 이후 규칙 + 알려진 특별 휴장). 실제 거래일 목록이 있으면 그것을 우선한다."""
    hs = set()
    ny = date(year, 1, 1)
    if ny.weekday() == 6:
        hs.add(date(year, 1, 2))
    elif ny.weekday() != 5:  # 토요일이면 앞 금요일에 쉬지 않는다
        hs.add(ny)
    hs.add(_nth_weekday(year, 1, 0, 3))  # MLK
    hs.add(_nth_weekday(year, 2, 0, 3))  # Washington's Birthday
    hs.add(_easter(year) - timedelta(days=2))  # Good Friday
    hs.add(_nth_weekday(year, 5, 0, -1))  # Memorial Day
    if year >= 2022:
        hs.add(_observed(date(year, 6, 19)))  # Juneteenth
    hs.add(_observed(date(year, 7, 4)))
    hs.add(_nth_weekday(year, 9, 0, 1))  # Labor Day
    hs.add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving
    hs.add(_observed(date(year, 12, 25)))
    return frozenset(hs)


def is_trading_day(d: date, trading_days: Optional[frozenset] = None) -> bool:
    if trading_days is not None:
        return d in trading_days
    if d.weekday() >= 5:
        return False
    return d not in nyse_holidays(d.year) and d not in _SPECIAL_CLOSURES


def next_trading_day(d: date, trading_days: Optional[frozenset] = None) -> Optional[date]:
    """d 이후(d 제외) 첫 거래일. 거래일 목록이 주어졌는데 범위를 넘으면 None."""
    if trading_days is not None:
        if not trading_days:
            return None
        last = max(trading_days)
        cur = d + timedelta(days=1)
        while cur <= last:
            if cur in trading_days:
                return cur
            cur += timedelta(days=1)
        return None
    cur = d + timedelta(days=1)
    while not is_trading_day(cur):
        cur += timedelta(days=1)
    return cur


class _FallbackNewYork(tzinfo):
    """zoneinfo 를 못 쓰는 환경용 미국 동부 시간(2007년 이후 DST 규칙)."""

    def _dst_range(self, year: int):
        start = _nth_weekday(year, 3, 6, 2)  # 3월 둘째 일요일 02:00 (표준시)
        end = _nth_weekday(year, 11, 6, 1)  # 11월 첫째 일요일 02:00 (일광절약시)
        return datetime(year, start.month, start.day, 2), datetime(year, end.month, end.day, 2)

    def utcoffset(self, dt):
        return timedelta(hours=-4) if self.dst(dt) else timedelta(hours=-5)

    def dst(self, dt):
        if dt is None:
            return timedelta(0)
        naive = dt.replace(tzinfo=None)
        start, end = self._dst_range(naive.year)
        if end - timedelta(hours=1) <= naive < end and dt.fold:
            return timedelta(0)  # 11월 전환일 01:00~02:00 의 두 번째(표준시) 발생
        return timedelta(hours=1) if start <= naive < end else timedelta(0)

    def tzname(self, dt):
        return "EDT" if self.dst(dt) else "EST"

    def fromutc(self, dt):
        naive = dt.replace(tzinfo=None)
        start, end = self._dst_range(naive.year)
        # UTC 기준 경계: 시작은 표준시 02:00 = 07:00Z, 끝은 일광절약 02:00 = 06:00Z
        start_utc, end_utc = start + timedelta(hours=5), end + timedelta(hours=4)
        off = timedelta(hours=-4) if start_utc <= naive < end_utc else timedelta(hours=-5)
        fold = 1 if end_utc <= naive < end_utc + timedelta(hours=1) else 0
        return (naive + off).replace(tzinfo=self, fold=fold)


def _new_york_tz() -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # tzdata 없음
        return _FallbackNewYork()


_NY = _new_york_tz()
_UTC = timezone.utc


def _parse_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc() -> datetime:
    return datetime.now(_UTC)


def decision_and_fill_times(
    available_at: datetime, trading_days: Optional[frozenset] = None
) -> dict:
    """available_at(UTC) -> decision_cutoff / next_executable_fill (UTC ISO).

    결정 시계는 미국 동부 16:00. available_at 이 그 거래일 16:00 ET 이전(포함)이면 그날이 결정일,
    이후이거나 비거래일이면 다음 거래일이 결정일이다. 체결은 결정일 다음 거래일 09:30 ET 시가.
    """
    local = available_at.astimezone(_NY)
    day = local.date()
    if is_trading_day(day, trading_days) and local.timetz().replace(tzinfo=None) <= DECISION_CLOCK_LOCAL:
        decision_day: Optional[date] = day
    else:
        decision_day = next_trading_day(day, trading_days)
    fill_day = next_trading_day(decision_day, trading_days) if decision_day else None

    def _at(d: Optional[date], clock: dtime) -> Optional[str]:
        if d is None:
            return None
        return _iso(datetime.combine(d, clock, tzinfo=_NY))

    return {
        "decision_day": decision_day.isoformat() if decision_day else None,
        "decision_cutoff": _at(decision_day, DECISION_CLOCK_LOCAL),
        "next_executable_fill_day": fill_day.isoformat() if fill_day else None,
        "next_executable_fill": _at(fill_day, FILL_CLOCK_LOCAL),
        "calendar_basis": "trading_days_list" if trading_days is not None else "nyse_rule_approximation",
    }


def compute_time_contract(
    acceptance_utc: Optional[str],
    *,
    mode: str = "retrospective",
    assumed_latency_hours: float = 0.5,
    system_first_seen: Optional[str] = None,
    extraction_completed: Optional[str] = None,
    trading_days: Optional[Iterable[date]] = None,
) -> dict:
    """공통 시간 계약 필드를 계산한다.

    source_publication(acceptance) -> system_first_seen -> extraction_completed -> decision_cutoff
    -> next_executable_fill.

    - live: available_at = max(acceptance, system_first_seen, extraction_completed) (있는 값만).
    - retrospective(과거 재구성): system_first_seen 이 없으므로 available_at = acceptance + 가정 지연.
      이때 extraction_completed 는 실제 추출 시각이라 available_at 에 쓰지 않는다.
    어느 경우에도 PIT 인증은 하지 않는다.
    """
    if mode not in ("live", "retrospective"):
        raise ValueError("mode must be 'live' or 'retrospective'")
    td = frozenset(trading_days) if trading_days is not None else None
    acc = _parse_utc(acceptance_utc)
    fs = _parse_utc(system_first_seen)
    ex = _parse_utc(extraction_completed)
    out = {
        "source_publication": _iso(acc),
        "system_first_seen": _iso(fs),
        "extraction_completed": _iso(ex),
        "available_at": None,
        "decision_day": None,
        "decision_cutoff": None,
        "next_executable_fill_day": None,
        "next_executable_fill": None,
        "time_basis": "acceptance_missing",
        "assumed_latency_hours": None,
        "calendar_basis": "trading_days_list" if td is not None else "nyse_rule_approximation",
    }
    if acc is None:
        return out
    if mode == "retrospective":
        available = acc + timedelta(hours=float(assumed_latency_hours))
        out["time_basis"] = "retrospective_assumed_latency"
        out["assumed_latency_hours"] = float(assumed_latency_hours)
        out["system_first_seen"] = None  # 과거 재구성에서는 최초 수신 시각을 알 수 없다
    else:
        cands = [x for x in (acc, fs, ex) if x is not None]
        available = max(cands)
        out["time_basis"] = "live_observed" if fs is not None else "live_first_seen_missing"
    out["available_at"] = _iso(available)
    out.update(decision_and_fill_times(available, td))
    return out


# ============================================================================
# 2. HTML -> 텍스트
# ============================================================================

_BLOCK_TAGS = frozenset(
    ["p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section",
     "article", "hr", "blockquote", "dt", "dd", "header", "footer", "body", "html", "form", "center",
     "address", "caption", "thead", "tbody", "tfoot"]
)
_CELL_TAGS = frozenset(["td", "th"])
_SKIP_TAGS = frozenset(["script", "style", "noscript", "title", "ix:header"])
_VOID_TAGS = frozenset(["br", "hr", "img", "meta", "link", "input", "col", "area", "base", "wbr"])
_HIDDEN_STYLE_RE = re.compile(r"display\s*:\s*none", re.I)
_WS_RE = re.compile(r"[\s  -​  　﻿]+")


def _clean_line(s: str) -> str:
    return _WS_RE.sub(" ", s).strip()


class _TextExtractor(HTMLParser):
    """블록 요소는 줄바꿈, 표 셀은 공백으로 이어 붙이는 단순 텍스트 추출기(숨김·스크립트 제외)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buf: list[str] = []
        self._skip_tag: Optional[str] = None
        self._skip_depth = 0
        self._pre_depth = 0
        self._pre_buf: list[str] = []

    def _flush(self) -> None:
        line = _clean_line("".join(self._buf))
        self._buf = []
        if line:
            self.lines.append(line)

    def _flush_pre(self) -> None:
        raw = "".join(self._pre_buf)
        self._pre_buf = []
        for para in re.split(r"\n\s*\n", raw):
            line = _clean_line(para)
            if line:
                self.lines.append(line)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        style = ""
        for k, v in attrs:
            if k == "style" and v:
                style = v
        if tag not in _VOID_TAGS and (tag in _SKIP_TAGS or _HIDDEN_STYLE_RE.search(style)):
            self._skip_tag = tag
            self._skip_depth = 1
            return
        if tag == "pre":
            self._flush()
            self._pre_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._flush()
        elif tag in _CELL_TAGS:
            self._buf.append(" ")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in _VOID_TAGS or tag in _BLOCK_TAGS:
            if not self._skip_depth and tag in _BLOCK_TAGS:
                self._flush()
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth -= 1
            return
        if tag == "pre" and self._pre_depth:
            self._pre_depth -= 1
            if self._pre_depth == 0:
                self._flush_pre()
            return
        if tag in _BLOCK_TAGS:
            self._flush()
        elif tag in _CELL_TAGS:
            self._buf.append(" ")

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._pre_depth:
            self._pre_buf.append(data)
        else:
            self._buf.append(data)

    def close(self):
        super().close()
        if self._pre_depth:
            self._flush_pre()
        self._flush()


_LOOKS_HTML_RE = re.compile(r"<\s*/?\s*(?:html|body|div|p|table|tr|td|br|span|font|pre|b|i|a|h[1-6])\b", re.I)


def html_to_text(html: str) -> str:
    """HTML -> 줄바꿈으로 구분된 텍스트. 숨김(display:none, ix:header)·script·style 제외."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return "\n".join(parser.lines)


def text_from_document(raw: str) -> str:
    """HTML 이면 html_to_text, 평문이면 줄 정리만 한다."""
    if raw and _LOOKS_HTML_RE.search(raw):
        return html_to_text(raw)
    lines = (_clean_line(x) for x in (raw or "").split("\n"))
    return "\n".join(x for x in lines if x)


# ============================================================================
# 3. 섹션 추출 (Item 1A 위험 요인, MD&A 유동성)
# ============================================================================

@dataclass(frozen=True)
class ExtractOptions:
    min_risk_chars: int = 1200  # 이보다 짧은 Item 1A 본문은 정상 추출로 보지 않는다
    min_mdna_chars: int = 3000
    min_liquidity_chars: int = 300
    max_liquidity_chars: int = 60000  # 초과하면 경계 오탐(과다 추출)로 보고 추출 실패 처리
    reword_threshold: float = 0.75
    max_listed_changes: int = 300


@dataclass
class ExtractedSection:
    name: str
    status: str  # ok | section_not_found | reference_only | not_applicable
    text: str = ""
    heading: Optional[str] = None
    end_reason: Optional[str] = None
    char_count: int = 0
    word_count: int = 0
    notes: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "ExtractedSection":
        return cls(**d)


@dataclass
class _Heading:
    idx: int
    item_id: str
    title: str
    body_start: int
    raw: str


_ITEM_RE = re.compile(
    r"^\s*(?:part\s+[ivx]+\s*[,.\-–—:]?\s*)?item\s*(\d{1,2})\s*(?:([a-c])(?![a-z]))?\s*[.:\-–—)]*\s*(.*)$",
    re.I,
)
_NOT_APPLICABLE_RE = re.compile(
    r"smaller reporting compan(?:y|ies).{0,120}not required|not required.{0,120}smaller reporting|"
    r"^\W*not applicable\W*$|not applicable",
    re.I | re.S,
)
_REFERENCE_RE = re.compile(
    r"incorporated (?:herein )?by reference|no material changes?|there (?:have|has) been no material change|"
    r"(?:see|refer to) (?:the )?(?:risk factors|item 1a|part i)|"
    r"as (?:previously )?(?:disclosed|described|set forth) in (?:our|the) (?:annual report|form 10-k)|"
    r"included in (?:our )?annual report|exhibit 13",
    re.I,
)
_MDNA_TITLE_RE = re.compile(r"management\W{0,2}s?\s+discussion", re.I)
_RISK_TITLE_RE = re.compile(r"^\W*risk\s+factors", re.I)
_LIQ_ALLOWED = frozenset(
    ["liquidity", "and", "capital", "resources", "financial", "condition", "sources", "uses", "of", "cash",
     "funds", "the", "our", "company", "in", "requirements", "commitments"]
)
_MDNA_TERMINATOR_RE = re.compile(
    r"critical accounting|(?:recent|new) accounting (?:pronouncements|standards|guidance)|results of operations|"
    r"quantitative and qualitative|non-gaap|forward[- ]looking statements|^item\s*\d|^risk factors",
    re.I,
)


def _parse_item_heading(lines: list, i: int) -> Optional[_Heading]:
    m = _ITEM_RE.match(lines[i])
    if not m:
        return None
    num, letter, rest = m.group(1), (m.group(2) or ""), m.group(3).strip()
    if len(rest) > 160:
        return None
    if rest and not (rest[0].isupper() or rest[0] in "\"'“‘("):
        return None  # "Item 1A of Part II ..." 같은 본문 속 참조
    item_id = f"{int(num)}{letter.upper()}"
    body_start = i + 1
    title = rest
    if not title and i + 1 < len(lines):
        nxt = lines[i + 1]
        if len(nxt) <= 120 and not _ITEM_RE.match(nxt):
            title = nxt
            body_start = i + 2
    return _Heading(i, item_id, title, body_start, lines[i])


def _find_headings(lines: list) -> list:
    out = []
    for i in range(len(lines)):
        h = _parse_item_heading(lines, i)
        if h is not None:
            out.append(h)
    return out


def _section_from(name: str, body_lines: list, heading: Optional[str], end_reason: Optional[str]) -> ExtractedSection:
    text = "\n".join(body_lines)
    return ExtractedSection(
        name=name, status="ok", text=text, heading=heading, end_reason=end_reason,
        char_count=len(text), word_count=len(text.split()),
    )


def _best_item_body(lines: list, headings: list, item_id: str, title_ok: Callable[[str], bool]):
    """조건에 맞는 Item 머리글 후보들 중 본문이 가장 긴 것을 고른다(목차 항목은 본문이 거의 없어 탈락).

    반환: (best or None, notes). best = (heading, body_lines, end_reason)
    """
    best = None
    notes = []
    n_cand = 0
    for k, h in enumerate(headings):
        if h.item_id != item_id or not title_ok(h.title):
            continue
        n_cand += 1
        end = None
        for h2 in headings[k + 1:]:
            if h2.item_id != item_id:
                end = h2
                break
        if end is None:
            notes.append(f"candidate@{h.idx}:end_boundary_not_found")
            continue
        body = lines[h.body_start:end.idx]
        cand = (h, body, f"next_item:{end.item_id}")
        if best is None or sum(len(x) for x in body) > sum(len(x) for x in best[1]):
            best = cand
    notes.append(f"heading_candidates={n_cand}")
    return best, notes


def _classify_short(name: str, body_text: str, heading: str, notes: list) -> ExtractedSection:
    """본문이 최소 길이 미만일 때: 면제/참조/추출 실패를 구분한다(추측하지 않는다)."""
    if body_text and _REFERENCE_RE.search(body_text):
        sec = _section_from(name, body_text.split("\n"), heading, "short_body")
        sec.status = "reference_only"
        sec.notes = notes + ["short_body_with_reference_language"]
        return sec
    if body_text and _NOT_APPLICABLE_RE.search(body_text):
        sec = _section_from(name, body_text.split("\n"), heading, "short_body")
        sec.status = "not_applicable"
        sec.notes = notes + ["short_body_not_required_language"]
        return sec
    return ExtractedSection(name=name, status="section_not_found", heading=heading,
                            notes=notes + ["body_too_short_without_reference_language"])


def _is_liquidity_heading(line: str) -> bool:
    if len(line) > 100:
        return False
    toks = re.findall(r"[a-z&]+", line.lower())
    if not toks or "liquidity" not in toks:
        return False
    return all(t in _LIQ_ALLOWED or t == "&" for t in toks)


def _is_mdna_terminator(line: str) -> bool:
    if len(line) > 110 or len(line.split()) > 14:
        return False
    return bool(_MDNA_TERMINATOR_RE.search(line))


def extract_sections(doc_text: str, form: str, options: Optional[ExtractOptions] = None) -> dict:
    """텍스트(줄 단위)에서 Item 1A 위험 요인과 MD&A 유동성 소절을 추출한다.

    반환: {SECTION_RISK: ExtractedSection, SECTION_LIQUIDITY: ExtractedSection}. 못 찾으면 status
    ``section_not_found``(추측 금지). 본문이 없고 참조·면제 문구만 있으면 ``reference_only``/``not_applicable``.
    """
    opts = options or ExtractOptions()
    lines = [x for x in (_clean_line(l) for l in (doc_text or "").split("\n")) if x]
    headings = _find_headings(lines)
    out: dict = {}

    # --- Item 1A ---
    best, notes = _best_item_body(lines, headings, "1A", lambda t: bool(_RISK_TITLE_RE.search(t)))
    if best is None:
        out[SECTION_RISK] = ExtractedSection(SECTION_RISK, "section_not_found", notes=notes + ["heading_or_end_not_found"])
    else:
        h, body, end_reason = best
        body_text = "\n".join(body)
        if len(body_text) >= opts.min_risk_chars:
            sec = _section_from(SECTION_RISK, body, h.raw, end_reason)
            sec.notes = notes
            out[SECTION_RISK] = sec
        else:
            out[SECTION_RISK] = _classify_short(SECTION_RISK, body_text, h.raw, notes)

    # --- MD&A 유동성 ---
    mdna_id = "7" if form == "10-K" else "2"
    best, notes = _best_item_body(lines, headings, mdna_id, lambda t: bool(_MDNA_TITLE_RE.search(t)))
    if best is None:
        out[SECTION_LIQUIDITY] = ExtractedSection(SECTION_LIQUIDITY, "section_not_found",
                                                  notes=notes + ["mdna_heading_or_end_not_found"])
        return out
    h, mdna_lines, _ = best
    mdna_text = "\n".join(mdna_lines)
    if len(mdna_text) < opts.min_mdna_chars:
        sec = _classify_short(SECTION_LIQUIDITY, mdna_text, h.raw, notes + ["mdna_body_short"])
        if sec.status == "section_not_found":
            sec.notes.append("mdna_not_extractable")
        else:
            sec.text = ""  # 유동성 소절 본문은 없다
            sec.char_count = sec.word_count = 0
        out[SECTION_LIQUIDITY] = sec
        return out
    best_liq = None
    for j, line in enumerate(mdna_lines):
        if not _is_liquidity_heading(line):
            continue
        end_j, reason = len(mdna_lines), "mdna_end"
        for k in range(j + 1, len(mdna_lines)):
            if _is_mdna_terminator(mdna_lines[k]):
                end_j, reason = k, f"terminator:{mdna_lines[k][:60]}"
                break
        body = mdna_lines[j + 1:end_j]
        length = sum(len(x) for x in body)
        if best_liq is None or length > best_liq[0]:
            best_liq = (length, line, body, reason)
    if best_liq is None:
        out[SECTION_LIQUIDITY] = ExtractedSection(SECTION_LIQUIDITY, "section_not_found",
                                                  notes=notes + ["liquidity_heading_not_found_in_mdna"])
        return out
    length, heading, body, reason = best_liq
    if length < opts.min_liquidity_chars:
        out[SECTION_LIQUIDITY] = ExtractedSection(SECTION_LIQUIDITY, "section_not_found", heading=heading,
                                                  notes=notes + ["liquidity_body_too_short"])
    elif length > opts.max_liquidity_chars:
        out[SECTION_LIQUIDITY] = ExtractedSection(SECTION_LIQUIDITY, "section_not_found", heading=heading,
                                                  notes=notes + ["liquidity_overrun_suspected"])
    else:
        sec = _section_from(SECTION_LIQUIDITY, body, heading, reason)
        sec.notes = notes
        out[SECTION_LIQUIDITY] = sec
    return out


# ============================================================================
# 4. 문장 분리 · 정규화 · 숫자
# ============================================================================

_ABBREV = frozenset(
    ["u.s", "inc", "corp", "co", "ltd", "llc", "no", "nos", "mr", "ms", "mrs", "dr", "vs", "etc", "approx",
     "st", "jr", "sr", "l.p", "n.a", "u.k", "s.a", "fig", "cf", "e.g", "i.e", "al", "cal", "jan", "feb", "mar",
     "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "sec", "art", "para", "vol", "p.m", "a.m"]
)
_SENT_BOUNDARY = re.compile(r"([.!?][\"'”’)\]]*)\s+(?=[\"'“‘(\[]?[A-Z0-9])")
_NOISE_LINE_RE = re.compile(
    r"^(?:table of contents|index|page\s+\d+|\d{1,3}|-\s*\d{1,3}\s*-|\|?\s*\d{1,3}\s*\|?)$", re.I
)
_FOOTER_RE = re.compile(r"^.{0,90}\|\s*\d{1,3}\s*$")


def split_sentences(paragraph: str) -> list:
    out = []
    start = 0
    for m in _SENT_BOUNDARY.finditer(paragraph):
        punct = m.group(1)
        if punct.startswith("."):
            before = paragraph[start:m.start(1)]
            tok = before.split()[-1].lower().strip("\"'()[]“”‘’") if before.split() else ""
            if tok in _ABBREV or (len(tok) == 1 and tok.isalpha()):
                continue
        out.append(paragraph[start:m.end(1)].strip())
        start = m.end()
    tail = paragraph[start:].strip()
    if tail:
        out.append(tail)
    return [s for s in out if s]


_YEAR_RE = re.compile(r"(?<![\d$.,])(?:19|20)\d{2}(?![\d%.,]\d)(?!\s?(?:%|percent|million|billion|days?))")
_QUOTE_MAP = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def _norm_text(s: str) -> str:
    s = s.translate(_QUOTE_MAP).lower()
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    s = re.sub(r"(?<=\d)\.(?=\d)", "_", s)
    s = _YEAR_RE.sub("<y>", s)
    s = re.sub(r"[^a-z0-9_<>%$ ]+", " ", s)
    return " ".join(s.split())


def _skeleton(norm: str) -> str:
    return re.sub(r"\d+(?:_\d+)?", "#", norm)


@dataclass
class _Unit:
    text: str
    para: int
    norm: str
    skel: str
    tokens: frozenset


def _is_table_like(s: str) -> bool:
    core = s.replace(" ", "")
    if not core:
        return True
    alpha = sum(ch.isalpha() for ch in core)
    return alpha / len(core) < 0.4 or alpha < 3


def build_units(text: str) -> list:
    """텍스트 -> 문장 단위(문단 번호 포함). 쪽번호·머리글·숫자표 행은 버린다."""
    units = []
    para = -1
    for raw in (text or "").split("\n"):
        line = _clean_line(raw)
        if not line or _NOISE_LINE_RE.match(line) or _FOOTER_RE.match(line):
            continue
        para += 1
        for sent in split_sentences(line):
            if _is_table_like(sent) or len(sent.split()) < 2:
                continue
            norm = _norm_text(sent)
            if not norm:
                continue
            units.append(_Unit(sent, para, norm, _skeleton(norm), frozenset(re.findall(r"[a-z0-9_<>$%]+", norm))))
    return units


_NUMBER_RE = re.compile(
    r"(?P<cur>\$)?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?"
    r"(?P<unit>%|percent(?:age points?)?|trillion|billion|million|thousand|days?|weeks?|months?|years?|basis points|bps)?",
    re.I,
)
_SCALE = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}


@dataclass
class NumberMention:
    text: str
    value: float
    unit: str  # '%', 'days', 'months', 'years', 'usd', ''(단위 없음)


def extract_numbers(sentence: str) -> list:
    out = []
    for m in _NUMBER_RE.finditer(sentence):
        raw = m.group("num")
        unit = (m.group("unit") or "").lower()
        cur = bool(m.group("cur"))
        val = float(raw.replace(",", ""))
        if not unit and not cur and 1900 <= val <= 2100 and float(val).is_integer():
            continue  # 연도로 보고 제외
        if unit in _SCALE:
            val *= _SCALE[unit]
            u = "usd" if cur else unit
        elif unit in ("%", "percent", "percentage point", "percentage points"):
            u = "%"
        elif unit in ("bps", "basis points"):
            u = "bps"
        elif unit:
            u = unit.rstrip("s")
        else:
            u = "usd" if cur else ""
        out.append(NumberMention(m.group(0).strip(), val, u))
    return out


@dataclass
class NumericChange:
    old_text: str
    new_text: str
    unit: str
    old_value: float
    new_value: float
    delta: float  # 새 값 - 옛 값 (unit 이 %면 %p)
    ratio: Optional[float]  # 새/옛 - 1 (옛 값 0이면 None)
    sentence: str
    prior_sentence: str


def compare_numbers(old_sentence: str, new_sentence: str) -> list:
    """두 문장의 숫자를 위치별로 짝지어 값이 다른 것만 NumericChange 로 반환한다."""
    a, b = extract_numbers(old_sentence), extract_numbers(new_sentence)
    if len(a) != len(b):
        return []
    out = []
    for x, y in zip(a, b):
        if x.unit != y.unit or abs(x.value - y.value) > 1e-9 * max(1.0, abs(x.value)):
            ratio = None if x.value == 0 else y.value / x.value - 1.0
            out.append(NumericChange(x.text, y.text, y.unit or x.unit, x.value, y.value, y.value - x.value, ratio,
                                     new_sentence, old_sentence))
    return out


# ============================================================================
# 5. 규칙 기반 위험 태깅 (lexicon v0.1)
# ============================================================================

def _c(p: str) -> "re.Pattern":
    return re.compile(p, re.I)


_LEXICON: dict = {
    CATEGORY_LIQUIDITY: [
        (_c(r"substantial doubt"), "strong"),
        (_c(r"going[- ]concern"), "strong"),
        (_c(r"\bevents? of default\b"), "strong"),
        (_c(r"\b(?:in|into) default\b"), "strong"),
        (_c(r"\bdefault(?:ed)? (?:under|on|of)\b"), "strong"),
        (_c(r"\bcovenant (?:breach|violation|default)e?s?\b"), "strong"),
        (_c(r"\b(?:breach|violat)\w* (?:of )?(?:certain |the |our |a )?(?:financial )?covenants?\b"), "strong"),
        (_c(r"\bforbearance\b"), "strong"),
        (_c(r"\bchapter (?:11|7)\b"), "strong"),
        (_c(r"\bbankruptcy\b"), "moderate"),
        (_c(r"\binsolven\w+"), "moderate"),
        (_c(r"\b(?:additional|further) (?:capital|financing|funding|liquidity)\b"), "moderate"),
        (_c(r"\b(?:insufficient|inadequate) (?:cash|liquidity|capital|funds)\b"), "moderate"),
        (_c(r"\bliquidity (?:constraints?|shortfall|needs?|risks?)\b"), "moderate"),
        (_c(r"\bworking capital deficit\b"), "moderate"),
        (_c(r"\b(?:recurring|significant|substantial) (?:net )?(?:operating )?losses\b"), "moderate"),
        (_c(r"\bnegative (?:operating )?cash flows?\b"), "moderate"),
        (_c(r"\bsubstantial indebtedness\b"), "moderate"),
        (_c(r"\brefinanc\w+"), "weak"),
        (_c(r"\bliquidity\b"), "weak"),
    ],
    CATEGORY_COMPETITION: [
        (_c(r"\b(?:lost|losing|loss of) (?:significant |substantial |some )?market share\b"), "strong"),
        (_c(r"\bmarket share (?:has |have )?(?:declined|decreased|eroded|fallen)\b"), "strong"),
        (_c(r"\bpric(?:e|ing) pressures? (?:has|have|is|are|continued|continues)\b"), "strong"),
        (_c(r"\b(?:intense|increased|increasing|significant|strong|aggressive) (?:price |pricing )?competition\b"), "moderate"),
        (_c(r"\bnew (?:market )?entrants?\b"), "moderate"),
        (_c(r"\bcompetitive pressures?\b"), "moderate"),
        (_c(r"\bcompetitors?\b"), "weak"),
        (_c(r"\bcompet(?:e|ition|itive)\b"), "weak"),
    ],
    CATEGORY_CONCENTRATION: [
        (_c(r"\baccount(?:ed|s|ing) for (?:approximately |about |over |more than )?\d{1,3}(?:\.\d+)?\s?%"), "strong"),
        (_c(r"\b(?:sole|single)[- ](?:source|supplier|sourced)\b"), "strong"),
        (_c(r"\bconcentrat(?:ed|ion) (?:of|in|among) (?:our )?(?:customers|revenues?|sales|suppliers|vendors)\b"), "strong"),
        (_c(r"\bdepend(?:s|ent|ence)? (?:up)?on (?:a )?(?:single|limited number|small number|few)\b"), "strong"),
        (_c(r"\b(?:significant|substantial|large) (?:portion|percentage|part|amount) of our (?:revenues?|net sales|sales)\b"), "moderate"),
        (_c(r"\blimited number of (?:customers|suppliers|vendors|distributors)\b"), "moderate"),
        (_c(r"\b(?:major|key|largest|significant) (?:customers?|suppliers?|distributors?)\b"), "moderate"),
    ],
    CATEGORY_LITIGATION: [
        (_c(r"\bclass[- ]action\b"), "strong"),
        (_c(r"\bsubpoenas?\b"), "strong"),
        (_c(r"\bcivil investigative demands?\b"), "strong"),
        (_c(r"\bwells notice\b"), "strong"),
        (_c(r"\bdepartment of justice\b|\bdoj\b"), "strong"),
        (_c(r"\b(?:sec|securities and exchange commission) (?:investigation|inquiry|enforcement)\b"), "strong"),
        (_c(r"\bconsent (?:decree|order)\b"), "strong"),
        (_c(r"\bindict\w*"), "strong"),
        (_c(r"\b(?:filed|commenced|brought) (?:a |an )?(?:complaint|lawsuit|suit|action|petition)\b"), "strong"),
        (_c(r"\b(?:complaint|lawsuit|suit|action) (?:was |has been |have been )?(?:filed|brought) against\b"), "strong"),
        (_c(r"\bpatent infringement (?:lawsuit|suit|action|claims?)\b"), "strong"),
        (_c(r"\bantitrust (?:lawsuit|investigation|complaint|action)\b"), "strong"),
        (_c(r"\b(?:government|regulatory) investigations?\b"), "strong"),
        (_c(r"\blitigation\b"), "moderate"),
        (_c(r"\blawsuits?\b"), "moderate"),
        (_c(r"\blegal proceedings\b"), "moderate"),
        (_c(r"\bregulatory (?:scrutiny|action|actions|inquir\w+)\b"), "moderate"),
        (_c(r"\bpenalt(?:y|ies)\b"), "moderate"),
        (_c(r"\bfines?\b"), "moderate"),
    ],
    CATEGORY_CYBER: [
        (_c(r"\b(?:we|company) (?:have |has |had )?(?:experienced|suffered|discovered|detected|identified|were (?:the )?(?:subject|target|victim)s? of|became aware of)\b.{0,80}\b(?:cyber\w*|ransomware|data breach|security (?:incident|breach)|unauthorized access)\b"), "strong"),
        (_c(r"\b(?:cybersecurity|cyber) incident (?:occurred|in which)\b"), "strong"),
        (_c(r"\bdata breach(?:es)?\b"), "moderate"),
        (_c(r"\bcyber[- ]?attacks?\b"), "moderate"),
        (_c(r"\bransomware\b"), "moderate"),
        (_c(r"\bsecurity (?:incident|breach)(?:es)?\b"), "moderate"),
        (_c(r"\bunauthorized access\b"), "moderate"),
        (_c(r"\bcyber\w*"), "weak"),
    ],
    CATEGORY_ACCOUNTING: [
        (_c(r"\bmaterial weakness(?:es)?\b"), "strong"),
        (_c(r"\bnon-reliance\b"), "strong"),
        (_c(r"\brestat(?:e|ed|ement|ements)\b"), "strong"),
        (_c(r"\bdelist(?:ed|ing)?\b"), "strong"),
        (_c(r"\bminimum bid price\b"), "strong"),
        (_c(r"\bdeficiency (?:letter|notice)\b"), "strong"),
        (_c(r"\bsignificant deficienc\w+"), "moderate"),
        (_c(r"\binternal control over financial reporting\b"), "weak"),
    ],
}
RISK_CATEGORIES = tuple(_LEXICON.keys())

_NEGATION_BEFORE_RE = _c(
    r"\b(?:no|not|never|without|neither|nor|none|nothing|absence of|hasn't|haven't|hadn't|didn't|doesn't|don't|"
    r"wasn't|weren't|isn't|aren't|no longer|free of|free from)\b"
)
_NEGATION_AFTER_RE = _c(
    r"\b(?:has|have|had|was|were|is|are) (?:not|no longer|been (?:alleviated|resolved|dismissed|eliminated|settled|"
    r"withdrawn|cured|remedied|terminated))\b"
)
_HYP_RE = _c(
    r"\b(?:may|might|could|would|can|if|whether|potential(?:ly)?|possible|possibility|in the event|risk that|"
    r"no assurance|cannot assure|not assure|likely to|subject us to|expose us to|from time to time|future)\b"
)
_HYP_START_RE = _c(r"^\W*(?:if|should|in the event|any|failure to|our failure|unless)\b")
_ASSERT_RE = _c(
    r"\b(?:have|has|had) (?:received|been served|been named|filed|entered into|breached|failed|experienced|incurred|"
    r"concluded|identified|disclosed|reported|issued|expressed)\b|"
    r"\b(?:was|were|has been|have been) (?:filed|served|received|issued|commenced|initiated|named|identified|"
    r"breached|violated|expressed)\b|"
    r"\braises? substantial doubt|\braised substantial doubt|\bthere (?:is|was|exists) substantial doubt|"
    r"\bsubstantial doubt (?:exists|remains)\b|"
    r"\b(?:we|the company) (?:are|were|is|was) in (?:default|breach|violation)\b"
)
_SPECIFIC_RE = _c(
    r"\d|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b|"
    r"\b(?:filed|received|entered into|commenced|announced|served|issued|concluded|breached|terminated|delisted|"
    r"dismissed|settled|expressed)\b"
)


@dataclass
class TagHit:
    category: str
    severity: str
    modality: str  # asserted | hypothetical | negated | fragment
    specific: bool
    terms: list
    start: int


_MAY_MONTH_RE = re.compile(r"\bMay\b(?=\s+\d|,)|(?<=\bin )May\b|(?<=\bIn )May\b|(?<=\bof )May\b|(?<=\bsince )May\b|(?<=\buntil )May\b")


def _modality(sentence: str, match_start: int, n_words: int) -> str:
    if n_words < 6:
        return "fragment"
    sentence = _MAY_MONTH_RE.sub("Mxy", sentence)  # 월 이름 May 를 조동사 may 로 오인하지 않는다(길이 유지)
    before = sentence[:match_start]
    window = before[-80:]
    after = sentence[match_start:match_start + 120]
    if _NEGATION_BEFORE_RE.search(window) or _NEGATION_AFTER_RE.search(after):
        return "negated"
    clause = re.split(r"[;:,]", before)[-1] if re.search(r"[;:,]", before) else before
    clause = clause[-100:] if len(clause) >= 15 else before[-100:]
    hyp = bool(_HYP_RE.search(clause)) or bool(_HYP_START_RE.search(sentence))
    if not hyp:
        return "asserted"
    for m in _ASSERT_RE.finditer(sentence):
        if not _HYP_RE.search(sentence[max(0, m.start() - 40):m.start()]):
            return "asserted"
    return "hypothetical"


def tag_sentence(sentence: str) -> list:
    """한 문장의 위험 범주 태그(가장 강한 severity 1개/범주). weak 도 반환하며 호출부가 거른다."""
    n_words = len(sentence.split())
    hits = []
    for cat, rules in _LEXICON.items():
        best = None
        terms = []
        for pat, sev in rules:
            m = pat.search(sentence)
            if not m:
                continue
            if m.group(0) not in terms and len(terms) < 4:
                terms.append(m.group(0))
            if best is None or _SEVERITY_RANK[sev] > _SEVERITY_RANK[best[0]]:
                best = (sev, m.start())
        if best is None:
            continue
        hits.append(TagHit(cat, best[0], _modality(sentence, best[1], n_words),
                           bool(_SPECIFIC_RE.search(sentence)), terms, best[1]))
    return hits


@dataclass
class RiskTag:
    category: str
    severity: str
    modality: str
    specific: bool
    anchor: str
    section: str
    novelty: str  # new_category | new_asserted | new_sentence | escalated | numeric_change | removed
    is_new: bool
    prior_anchor: Optional[str] = None
    matched_terms: list = field(default_factory=list)
    paragraph_index: int = -1
    prior_category_sentence_count: int = 0
    numeric_change: Optional[dict] = None

    @classmethod
    def from_dict(cls, d: dict) -> "RiskTag":
        return cls(**d)


_BOILERPLATE_RE = _c(
    r"forward[- ]looking statements|safe harbor|private securities litigation reform act|not the only risks|"
    r"additional risks .{0,60}not (?:presently|currently) known|should carefully consider|"
    r"(?:summary of|risk factors? summary)|there can be no assurance|we cannot assure you"
)
_MNA_RE = _c(
    r"\b(?:completed|consummated|closed) (?:the |our |its )?(?:acquisition|merger|business combination)\b|"
    r"\bmerger agreement\b|\bbusiness combination\b|\bspin-?off\b|\bdivestiture\b|\bagreed to acquire\b|"
    r"\bpending (?:acquisition|merger)\b|\bwe acquired\b"
)
_ACCT_RE = _c(
    r"\bASU\s*20\d\d-\d+|\bASC\s*\d{3}\b|accounting standards update|change in accounting (?:principle|estimate)|"
    r"transition(?:ed)? to (?:U\.S\. GAAP|IFRS)|new accounting (?:standard|guidance|pronouncement)"
)


def _is_boilerplate(unit_text: str) -> bool:
    if not _BOILERPLATE_RE.search(unit_text):
        return False
    if re.search(r"\d", unit_text):
        return False
    return not any(h.modality == "asserted" and h.severity == "strong" for h in tag_sentence(unit_text))


# ============================================================================
# 6. 섹션 diff
# ============================================================================

@dataclass
class SentenceChange:
    kind: str  # new | deleted | numeric_changed | reworded
    text: str  # new/numeric_changed/reworded 는 현재 문장, deleted 는 직전 문장
    prior_text: Optional[str] = None
    paragraph_index: int = -1
    similarity: Optional[float] = None
    numeric_changes: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "SentenceChange":
        return cls(**d)


@dataclass
class SectionDiff:
    section: str
    status: str  # ok | not_comparable
    current_status: str = "section_not_found"
    prior_status: str = "section_not_found"
    current_heading: Optional[str] = None
    prior_heading: Optional[str] = None
    current_words: int = 0
    prior_words: int = 0
    length_ratio: Optional[float] = None
    counts: dict = field(default_factory=dict)
    changes: list = field(default_factory=list)
    changes_truncated: bool = False
    numeric_changes: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    removed_tags: list = field(default_factory=list)
    category_counts: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "SectionDiff":
        d = dict(d)
        d["changes"] = [SentenceChange.from_dict(x) for x in d.get("changes", [])]
        d["numeric_changes"] = [NumericChange(**x) for x in d.get("numeric_changes", [])]
        d["tags"] = [RiskTag.from_dict(x) for x in d.get("tags", [])]
        d["removed_tags"] = [RiskTag.from_dict(x) for x in d.get("removed_tags", [])]
        return cls(**d)


def _lis_length(seq: Sequence[int]) -> int:
    tails: list = []
    for x in seq:
        pos = bisect.bisect_left(tails, x)
        if pos == len(tails):
            tails.append(x)
        else:
            tails[pos] = x
    return len(tails)


def _doc_keys(text: str) -> tuple:
    units = build_units(text)
    return {u.norm for u in units}, {u.skel for u in units}


def _match_units(prior: list, curr: list, threshold: float) -> tuple:
    """정확 -> 숫자골격 -> 재서술 순 1:1 매칭. 반환: (matches{curr_idx: (kind, prior_idx, sim)}, used_prior)."""
    matches: dict = {}
    used: set = set()
    by_norm: dict = defaultdict(deque)
    for i, u in enumerate(prior):
        by_norm[u.norm].append(i)
    for j, u in enumerate(curr):
        q = by_norm.get(u.norm)
        if q:
            i = q.popleft()
            matches[j] = ("unchanged", i, 1.0)
            used.add(i)
    by_skel: dict = defaultdict(deque)
    for i, u in enumerate(prior):
        if i not in used:
            by_skel[u.skel].append(i)
    for j, u in enumerate(curr):
        if j in matches:
            continue
        q = by_skel.get(u.skel)
        if q:
            i = q.popleft()
            used.add(i)
            changes = compare_numbers(prior[i].text, u.text)
            matches[j] = ("numeric_changed" if changes else "unchanged", i, 1.0)
    rem_prior = [i for i in range(len(prior)) if i not in used]
    rem_curr = [j for j in range(len(curr)) if j not in matches]
    if rem_prior and rem_curr:
        index: dict = defaultdict(set)
        for i in rem_prior:
            for t in prior[i].tokens:
                index[t].add(i)
        limit = max(30, int(0.2 * len(rem_prior)))
        pairs = []
        for j in rem_curr:
            cj = curr[j]
            if len(cj.tokens) < 6:
                continue
            counter: Counter = Counter()
            for t in cj.tokens:
                ids = index.get(t)
                if ids and len(ids) <= limit:
                    counter.update(ids)
            for i, shared in counter.items():
                if shared < 3 or len(prior[i].tokens) < 6:
                    continue
                pj = prior[i].tokens
                sim = len(cj.tokens & pj) / len(cj.tokens | pj)
                if sim >= threshold:
                    pairs.append((sim, j, i))
        pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
        used_curr: set = set()
        for sim, j, i in pairs:
            if j in used_curr or i in used:
                continue
            used_curr.add(j)
            used.add(i)
            matches[j] = ("reworded", i, sim)
    return matches, used


def _tier_counts(units_hits: Iterable) -> tuple:
    """카테고리·severity 별 (전체, asserted) 문장 수. 반환 dict[(cat, rank)] 누적(해당 rank 이상)."""
    total: Counter = Counter()
    asserted: Counter = Counter()
    for hits in units_hits:
        for h in hits:
            r = _SEVERITY_RANK[h.severity]
            for rank in range(1, r + 1):
                total[(h.category, rank)] += 1
                if h.modality == "asserted":
                    asserted[(h.category, rank)] += 1
    return total, asserted


def diff_sections(
    prior: ExtractedSection,
    current: ExtractedSection,
    *,
    prior_doc_keys: Optional[tuple] = None,
    current_doc_keys: Optional[tuple] = None,
    options: Optional[ExtractOptions] = None,
) -> SectionDiff:
    """직전·현재 같은 절의 문장 단위 diff. 두 절이 모두 ``ok`` 가 아니면 비교하지 않는다(추측 금지).

    prior_doc_keys/current_doc_keys: (정규화 문장 집합, 숫자골격 집합). 신규 문장이 직전 문서의 다른 절에 이미
    있으면(문장 이동) 신규에서 제외해 템플릿 재구성을 신호로 오인하지 않는다.
    """
    opts = options or ExtractOptions()
    name = current.name
    sd = SectionDiff(
        section=name, status="not_comparable", current_status=current.status, prior_status=prior.status,
        current_heading=current.heading, prior_heading=prior.heading,
        current_words=current.word_count, prior_words=prior.word_count,
    )
    if current.status != "ok" or prior.status != "ok":
        if current.status != "ok":
            sd.flags.append(f"{current.status}:{name}:current")
        if prior.status != "ok":
            sd.flags.append(f"{prior.status}:{name}:prior")
        sd.notes.append("not_compared: both sections must be status=ok")
        return sd

    p_units, c_units = build_units(prior.text), build_units(current.text)
    matches, used = _match_units(p_units, c_units, opts.reword_threshold)
    p_hits = [tag_sentence(u.text) for u in p_units]
    c_hits = [tag_sentence(u.text) for u in c_units]
    p_total, p_asserted = _tier_counts(p_hits)

    prior_norms, prior_skels = prior_doc_keys if prior_doc_keys else (set(), set())
    cur_norms, cur_skels = current_doc_keys if current_doc_keys else (set(), set())

    counts = Counter()
    changes: list = []
    tags: list = []
    removed: list = []
    numeric_all: list = []
    new_texts: list = []
    para_status: dict = defaultdict(list)

    def _novelty(hit: TagHit) -> tuple:
        rank = _SEVERITY_RANK[hit.severity]
        tot = p_total[(hit.category, rank)]
        if tot == 0:
            return "new_category", tot
        if hit.modality == "asserted" and p_asserted[(hit.category, rank)] == 0:
            return "new_asserted", tot
        return "new_sentence", tot

    def _emit(hit: TagHit, u: _Unit, novelty: str, is_new: bool, prior_text=None, prior_cnt=0, numeric=None):
        if _SEVERITY_RANK[hit.severity] < _SEVERITY_RANK["moderate"]:
            return
        tags.append(RiskTag(hit.category, hit.severity, hit.modality, hit.specific, u.text, name, novelty, is_new,
                            prior_text, hit.terms, u.para, prior_cnt, numeric))

    for j, u in enumerate(c_units):
        m = matches.get(j)
        if m is None:
            if u.norm in prior_norms or u.skel in prior_skels:
                counts["moved_from_other_section"] += 1
                para_status[u.para].append("moved")
                continue
            counts["new"] += 1
            para_status[u.para].append("new")
            new_texts.append(u.text)
            changes.append(SentenceChange("new", u.text, None, u.para))
            for hit in c_hits[j]:
                novelty, tot = _novelty(hit)
                _emit(hit, u, novelty, True, None, tot)
            continue
        kind, i, sim = m
        pu = p_units[i]
        if kind == "unchanged":
            counts["unchanged"] += 1
            para_status[u.para].append("same")
        elif kind == "numeric_changed":
            counts["numeric_changed"] += 1
            para_status[u.para].append("same")
            nc = compare_numbers(pu.text, u.text)
            numeric_all.extend(nc)
            changes.append(SentenceChange("numeric_changed", u.text, pu.text, u.para, 1.0, [asdict(x) for x in nc]))
            for hit in c_hits[j]:
                _emit(hit, u, "numeric_change", False, pu.text, 0, asdict(nc[0]) if nc else None)
        else:  # reworded
            counts["reworded"] += 1
            para_status[u.para].append("same")
            nc = compare_numbers(pu.text, u.text)
            numeric_all.extend(nc)
            changes.append(SentenceChange("reworded", u.text, pu.text, u.para, round(sim, 4), [asdict(x) for x in nc]))
            prev_by_cat = {h.category: h for h in p_hits[i]}
            for hit in c_hits[j]:
                old = prev_by_cat.get(hit.category)
                if old is None:
                    novelty, tot = _novelty(hit)
                    _emit(hit, u, novelty, True, pu.text, tot)
                elif (_SEVERITY_RANK[hit.severity] > _SEVERITY_RANK[old.severity]
                      or (old.modality != "asserted" and hit.modality == "asserted")):
                    _emit(hit, u, "escalated", True, pu.text, p_total[(hit.category, _SEVERITY_RANK[hit.severity])])

    n_del = 0
    n_moved_out = 0
    for i, pu in enumerate(p_units):
        if i in used:
            continue
        if pu.norm in cur_norms or pu.skel in cur_skels:
            n_moved_out += 1
            continue
        n_del += 1
        changes.append(SentenceChange("deleted", pu.text, None, pu.para))
        for hit in p_hits[i]:
            if _SEVERITY_RANK[hit.severity] >= _SEVERITY_RANK["moderate"]:
                removed.append(RiskTag(hit.category, hit.severity, hit.modality, hit.specific, pu.text, name,
                                       "removed", False, None, hit.terms, pu.para))
    counts["deleted"] = n_del
    counts["moved_out_to_other_section"] = n_moved_out
    counts["sentences_current"] = len(c_units)
    counts["sentences_prior"] = len(p_units)

    # 문단 수준
    new_par = chg_par = 0
    for statuses in para_status.values():
        if all(s == "new" for s in statuses):
            new_par += 1
        elif any(s == "new" for s in statuses):
            chg_par += 1
    counts["paragraphs_current"] = len(para_status)
    counts["new_paragraphs"] = new_par
    counts["changed_paragraphs"] = chg_par

    sd.status = "ok"
    sd.counts = dict(counts)
    for key in ("unchanged", "numeric_changed", "reworded", "new", "deleted", "moved_from_other_section"):
        sd.counts.setdefault(key, 0)
    sd.length_ratio = (current.word_count / prior.word_count) if prior.word_count else None
    if len(changes) > opts.max_listed_changes:
        sd.changes = changes[:opts.max_listed_changes]
        sd.changes_truncated = True
    else:
        sd.changes = changes
    sd.numeric_changes = numeric_all
    sd.tags = tags
    sd.removed_tags = removed
    sd.category_counts = {
        "current": _category_counts(c_hits),
        "prior": _category_counts(p_hits),
    }

    # --- 형식 변화 플래그 ---
    n_cur = max(1, len(c_units))
    if sd.length_ratio is not None and prior.word_count >= 300 and (sd.length_ratio >= 1.5 or sd.length_ratio <= 0.67):
        sd.flags.append("length_shock")
    if counts["reworded"] / n_cur >= 0.25:
        sd.flags.append("heavy_rewording")
    matched_prior_order = [i for j, (k, i, _s) in sorted(matches.items())]
    if len(matched_prior_order) >= 20 and _lis_length(matched_prior_order) / len(matched_prior_order) < 0.6:
        sd.flags.append("reordered")
    would_new = counts["new"] + counts["moved_from_other_section"]
    if counts["moved_from_other_section"] >= 5 and counts["moved_from_other_section"] / max(1, would_new) >= 0.25:
        sd.flags.append("moved_text")
    if len(c_units) >= 20 and counts["new"] / n_cur >= 0.5:
        sd.flags.append("mostly_new_text")
    if new_texts and all(_is_boilerplate(t) for t in new_texts):
        sd.flags.append("new_text_boilerplate_only")
    return sd


def _category_counts(hits_list: list) -> dict:
    out: Counter = Counter()
    for hits in hits_list:
        for h in hits:
            if _SEVERITY_RANK[h.severity] >= _SEVERITY_RANK["moderate"]:
                out[h.category] += 1
    return dict(out)


_TEMPLATE_FLAGS = ("heavy_rewording", "reordered", "moved_text", "mostly_new_text")


# ============================================================================
# 7. 공시 레코드 · 비교 규칙
# ============================================================================

@dataclass(frozen=True)
class FilingRecord:
    cik: str  # 10자리 0패딩
    accession: str
    form: str
    filing_date: str
    acceptance_datetime: Optional[str]  # UTC ISO (YYYY-MM-DDTHH:MM:SSZ)
    report_date: Optional[str]
    primary_document: str
    ticker: Optional[str] = None
    company_name: Optional[str] = None

    @property
    def is_amendment(self) -> bool:
        return self.form.upper().endswith("/A")

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def document_url(self) -> str:
        return (f"https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/"
                f"{self.accession_nodash}/{self.primary_document}")


def parse_submissions_columns(cols: dict, *, cik: str, ticker: Optional[str] = None,
                              company_name: Optional[str] = None) -> list:
    """EDGAR submissions 의 열 지향 dict(filings.recent 또는 추가 파일)를 FilingRecord 목록으로 바꾼다."""
    acc = cols.get("accessionNumber") or []
    out = []
    for i, a in enumerate(acc):
        def col(name, default=None, _i=i):
            arr = cols.get(name)
            return arr[_i] if arr is not None and _i < len(arr) else default

        accept = _parse_utc(col("acceptanceDateTime") or None)
        out.append(FilingRecord(
            cik=str(cik).zfill(10), accession=a, form=col("form", "") or "",
            filing_date=col("filingDate", "") or "", acceptance_datetime=_iso(accept),
            report_date=col("reportDate") or None, primary_document=col("primaryDocument", "") or "",
            ticker=ticker, company_name=company_name,
        ))
    return out


def _sort_key(r: FilingRecord):
    return (r.acceptance_datetime or r.filing_date or "", r.accession)


def validate_comparison(current: FilingRecord, prior: Optional[FilingRecord]) -> Optional[str]:
    """비교 가능하면 None, 아니면 거부 사유 코드. 같은 form·같은 기업·직전 원본 공시만 허용한다."""
    if current.form not in SUPPORTED_FORMS:
        return "amendment_not_supported" if current.is_amendment else "unsupported_form"
    if prior is None:
        return "no_prior_filing"
    if prior.form not in SUPPORTED_FORMS:
        return "prior_is_amendment" if prior.is_amendment else "prior_unsupported_form"
    if prior.form != current.form:
        return "form_mismatch"
    if prior.cik != current.cik:
        return "cik_mismatch"
    if prior.accession == current.accession:
        return "same_accession"
    if current.report_date and prior.report_date:
        if prior.report_date >= current.report_date:
            return "prior_not_older"
    if current.acceptance_datetime and prior.acceptance_datetime:
        if prior.acceptance_datetime >= current.acceptance_datetime:
            return "prior_not_older"
    return None


def find_prior_filing(records: Iterable, current: FilingRecord) -> Optional[FilingRecord]:
    """current 와 같은 form·같은 CIK 인 원본 중 current 보다 앞선 가장 최근 공시. 정정본은 제외한다."""
    best = None
    for r in records:
        if r.accession == current.accession or r.cik != current.cik or r.form != current.form or r.is_amendment:
            continue
        if validate_comparison(current, r) is not None:
            continue
        if best is None or _sort_key(r) > _sort_key(best):
            best = r
    return best


def _period_gap_days(current: FilingRecord, prior: FilingRecord) -> Optional[int]:
    try:
        return (date.fromisoformat(current.report_date) - date.fromisoformat(prior.report_date)).days
    except Exception:
        return None


# ============================================================================
# 8. FilingChangeEvent
# ============================================================================

@dataclass
class FilingChangeEvent:
    """한 공시(현재)와 직전 동종 공시의 변화 기록. shadow 전용이며 PIT 인증을 하지 않는다."""

    ticker: Optional[str]
    cik: str
    form: str
    accession: str
    filing_date: str
    report_date: Optional[str]
    prior_accession: Optional[str] = None
    prior_form: Optional[str] = None
    prior_filing_date: Optional[str] = None
    prior_report_date: Optional[str] = None
    period_gap_days: Optional[int] = None
    comparison_status: str = "rejected"  # ok | rejected
    reject_reason: Optional[str] = None
    # --- 시간 계약 ---
    source_publication: Optional[str] = None
    system_first_seen: Optional[str] = None
    extraction_completed: Optional[str] = None
    available_at: Optional[str] = None
    decision_day: Optional[str] = None
    decision_cutoff: Optional[str] = None
    next_executable_fill_day: Optional[str] = None
    next_executable_fill: Optional[str] = None
    time_basis: str = "acceptance_missing"
    assumed_latency_hours: Optional[float] = None
    calendar_basis: str = "nyse_rule_approximation"
    decision_clock: str = "16:00 America/New_York, fill 09:30 next trading day"
    pit_certified: bool = False
    pit_certification_blockers: list = field(default_factory=list)
    # --- 내용 ---
    sections: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    flag_details: dict = field(default_factory=dict)
    current_doc_sha256: Optional[str] = None
    prior_doc_sha256: Optional[str] = None
    current_doc_words: int = 0
    prior_doc_words: int = 0
    notes: list = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    extractor_version: str = EXTRACTOR_VERSION
    rules_version: str = RULES_VERSION
    shadow_only: bool = True

    def new_tags(self) -> list:
        return [t for sd in self.sections.values() for t in sd.tags if t.is_new]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sections"] = {k: asdict(v) for k, v in self.sections.items()}
        return d

    def to_json(self, **kw) -> str:
        kw.setdefault("ensure_ascii", False)
        kw.setdefault("indent", 2)
        return json.dumps(self.to_dict(), **kw)

    @classmethod
    def from_dict(cls, d: dict) -> "FilingChangeEvent":
        d = dict(d)
        d["sections"] = {k: SectionDiff.from_dict(v) for k, v in (d.get("sections") or {}).items()}
        return cls(**d)

    @classmethod
    def from_json(cls, s: str) -> "FilingChangeEvent":
        return cls.from_dict(json.loads(s))


class FilingComparisonRejected(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_PIT_BLOCKERS = [
    "no_pit_certification_procedure_implemented",
    "acceptance_time_not_independently_verified",
]


def build_filing_change_event(
    current: FilingRecord,
    current_document: str,
    prior: Optional[FilingRecord],
    prior_document: Optional[str],
    *,
    mode: str = "retrospective",
    assumed_latency_hours: float = 0.5,
    system_first_seen: Optional[str] = None,
    extraction_completed: Optional[str] = None,
    trading_days: Optional[Iterable[date]] = None,
    options: Optional[ExtractOptions] = None,
    strict: bool = False,
) -> FilingChangeEvent:
    """현재·직전 공시 원문(HTML 또는 평문)으로 FilingChangeEvent 를 만든다.

    비교 규칙(validate_comparison)에 어긋나면 ``comparison_status='rejected'`` 이벤트를 반환하고(strict=True 면
    FilingComparisonRejected 를 올린다) veto 에 쓰이지 않는다.
    """
    opts = options or ExtractOptions()
    ext_done = extraction_completed
    tc = compute_time_contract(
        current.acceptance_datetime, mode=mode, assumed_latency_hours=assumed_latency_hours,
        system_first_seen=system_first_seen, extraction_completed=ext_done or _iso(_now_utc()),
        trading_days=trading_days,
    )
    ev = FilingChangeEvent(
        ticker=current.ticker, cik=current.cik, form=current.form, accession=current.accession,
        filing_date=current.filing_date, report_date=current.report_date,
        prior_accession=prior.accession if prior else None, prior_form=prior.form if prior else None,
        prior_filing_date=prior.filing_date if prior else None,
        prior_report_date=prior.report_date if prior else None,
        pit_certified=False, pit_certification_blockers=list(_PIT_BLOCKERS),
        source_publication=tc["source_publication"], system_first_seen=tc["system_first_seen"],
        extraction_completed=tc["extraction_completed"], available_at=tc["available_at"],
        decision_day=tc["decision_day"], decision_cutoff=tc["decision_cutoff"],
        next_executable_fill_day=tc["next_executable_fill_day"], next_executable_fill=tc["next_executable_fill"],
        time_basis=tc["time_basis"], assumed_latency_hours=tc["assumed_latency_hours"],
        calendar_basis=tc["calendar_basis"],
    )
    if mode == "retrospective":
        ev.pit_certification_blockers.append("historical_backfill_system_first_seen_unknown")
    elif tc["system_first_seen"] is None:
        ev.pit_certification_blockers.append("system_first_seen_missing")
    if tc["source_publication"] is None:
        ev.flags.append("acceptance_time_missing")

    reason = validate_comparison(current, prior)
    if reason is not None:
        if strict:
            raise FilingComparisonRejected(reason)
        ev.comparison_status = "rejected"
        ev.reject_reason = reason
        ev.flags.append(f"comparison_rejected:{reason}")
        return ev
    assert prior is not None and prior_document is not None
    ev.comparison_status = "ok"
    ev.period_gap_days = _period_gap_days(current, prior)
    if ev.period_gap_days is not None:
        lo, hi = (300, 430) if current.form == "10-K" else (60, 200)
        if not lo <= ev.period_gap_days <= hi:
            ev.flags.append("prior_gap_unusual")

    cur_text = text_from_document(current_document)
    pri_text = text_from_document(prior_document)
    ev.current_doc_sha256 = hashlib.sha256(current_document.encode("utf-8", "replace")).hexdigest()
    ev.prior_doc_sha256 = hashlib.sha256(prior_document.encode("utf-8", "replace")).hexdigest()
    ev.current_doc_words, ev.prior_doc_words = len(cur_text.split()), len(pri_text.split())
    if ev.prior_doc_words >= 3000 and ev.current_doc_words:
        ratio = ev.current_doc_words / ev.prior_doc_words
        if ratio >= 1.5 or ratio <= 0.67:
            ev.flags.append("doc_length_shock")

    cur_secs = extract_sections(cur_text, current.form, opts)
    pri_secs = extract_sections(pri_text, prior.form, opts)
    prior_keys, cur_keys = _doc_keys(pri_text), _doc_keys(cur_text)
    for name in (SECTION_RISK, SECTION_LIQUIDITY):
        sd = diff_sections(pri_secs[name], cur_secs[name], prior_doc_keys=prior_keys,
                           current_doc_keys=cur_keys, options=opts)
        ev.sections[name] = sd
        for f in sd.flags:
            ev.flags.append(f if ":" in f else f"{f}:{name}")

    # 문서 수준 형식 변화: 직전 문서에 없던 문장 중 기업결합·회계기준 문구
    cur_units = build_units(cur_text)
    new_doc = [u for u in cur_units if u.norm not in prior_keys[0] and u.skel not in prior_keys[1]]
    mna = [u.text for u in new_doc if _MNA_RE.search(u.text)]
    acct = [u.text for u in new_doc if _ACCT_RE.search(u.text)]
    if mna:
        ev.flags.append("business_combination_suspected")
        ev.flag_details["business_combination_suspected"] = [t[:300] for t in mna[:3]]
    if acct:
        ev.flags.append("accounting_standard_change_suspected")
        ev.flag_details["accounting_standard_change_suspected"] = [t[:300] for t in acct[:3]]
    if any(f.split(":")[0] in _TEMPLATE_FLAGS for f in ev.flags):
        ev.flags.append("template_restructure_suspected")
    ev.flags = list(dict.fromkeys(ev.flags))
    return ev


# ============================================================================
# 9. veto 후보 규칙
# ============================================================================

@dataclass(frozen=True)
class FilingVetoPolicy:
    """filing_veto 규칙 파라미터(사전 고정 대상). 기본값은 스펙 §8 규칙 v0."""

    version: str = VETO_POLICY_VERSION
    sections: tuple = (SECTION_RISK, SECTION_LIQUIDITY)
    hold_liquidity: bool = True
    hold_litigation: bool = True
    hold_concentration_increase: bool = True
    hold_competition: bool = False  # v0 에서는 진단만
    hold_cyber: bool = False
    hold_accounting_controls: bool = False
    concentration_increase_pp: float = 10.0
    require_asserted: bool = True
    require_specific_litigation: bool = True
    suppress_on_flags: tuple = ("template_restructure_suspected",)
    new_category_bypasses_suppression: bool = True
    max_event_age_days: Optional[int] = 45


@dataclass
class VetoReason:
    code: str
    category: str
    section: str
    accession: str
    form: str
    anchor: str
    prior_anchor: Optional[str]
    severity: str
    modality: str
    novelty: str
    detail: Optional[dict] = None


@dataclass
class FilingVetoDecision:
    decision: str  # hold | pass
    reasons: list = field(default_factory=list)  # hold 사유(VetoReason)
    reason_codes: list = field(default_factory=list)  # 사유 코드(pass 사유 포함)
    suppressed: list = field(default_factory=list)  # 플래그로 억제된 hold 후보(VetoReason)
    unusable_events: list = field(default_factory=list)  # [{accession, reason}]
    evaluated_accessions: list = field(default_factory=list)
    data_gaps: list = field(default_factory=list)
    policy_version: str = VETO_POLICY_VERSION
    shadow_only: bool = True
    order_path_connected: bool = False
    pit_certified: bool = False
    note: str = ("가설 검증용 후보 규칙 출력이며 성과가 입증되지 않았다. 주문·paper·운영 경로에 연결하지 않는다.")

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, **kw) -> str:
        kw.setdefault("ensure_ascii", False)
        kw.setdefault("indent", 2)
        return json.dumps(self.to_dict(), **kw)


def _reason_from(tag: RiskTag, code: str, ev: FilingChangeEvent, detail: Optional[dict] = None) -> VetoReason:
    return VetoReason(code, tag.category, tag.section, ev.accession, ev.form, tag.anchor, tag.prior_anchor,
                      tag.severity, tag.modality, tag.novelty, detail)


_GOING_CONCERN_RE = re.compile(r"substantial doubt|going[- ]concern", re.I)


def filing_veto(
    events: Iterable,
    policy: Optional[FilingVetoPolicy] = None,
    *,
    as_of: Optional[datetime] = None,
) -> FilingVetoDecision:
    """공시 변화 이벤트로 신규 진입 후보를 hold/pass 로 판정하는 **단순 규칙 후보**.

    주의: 이것은 "새로 커진 악재 공시가 이후 비용 후 성과를 나쁘게 하는가"라는 가설(H1)을 검증하기 위한 후보
    규칙이다. 성과가 입증된 규칙이 아니며(docs/FILING_CHANGE_VETO_SPEC.md 미동결), 주문 경로에 연결하지 않는다.
    반환값에는 shadow_only=True, order_path_connected=False, pit_certified=False 가 고정된다.

    규칙 v0(모두 신규 + 사실 주장(asserted) 조건):
      R1 신규 going concern·substantial doubt 문장, 또는 신규 채무불이행·약정 위반·forbearance·챕터11 문장
      R2 신규 대형 소송·조사 문장(숫자·날짜·과거형 사건 동사가 있는 문장)
      R3 고객 매출 비중 % 가 직전 대비 concentration_increase_pp 이상 증가, 또는 신규 매출 비중(%) 문장
      (경쟁·사이버·회계 통제는 정책으로 켤 때만)
    템플릿 재구성 의심 플래그가 있으면 new_category 가 아닌 태그로는 hold 하지 않는다(suppressed 에 기록).

    events: FilingChangeEvent 반복 가능. 호출자가 후보 결정 시각 이전에 이용 가능한 이벤트만 넘기거나
    as_of(UTC 시각)를 주어야 한다. as_of 가 없으면 시간 필터를 하지 않으므로 누수 책임은 호출자에게 있다.
    비교가 거부됐거나 시간 계약이 없거나 절 추출이 모두 실패한 이벤트는 사용하지 않고 pass + 사유를 남긴다.
    """
    pol = policy or FilingVetoPolicy()
    dec = FilingVetoDecision(decision="pass", policy_version=pol.version)
    as_of_utc = as_of.astimezone(_UTC) if as_of is not None else None
    usable = 0
    for ev in events:
        dec.evaluated_accessions.append(ev.accession)
        if ev.comparison_status != "ok":
            dec.unusable_events.append({"accession": ev.accession, "reason": ev.reject_reason or "rejected"})
            continue
        avail = _parse_utc(ev.available_at)
        if avail is None:
            dec.unusable_events.append({"accession": ev.accession, "reason": "time_contract_missing"})
            continue
        if as_of_utc is not None:
            if avail > as_of_utc:
                dec.unusable_events.append({"accession": ev.accession, "reason": "event_not_yet_available"})
                continue
            if pol.max_event_age_days is not None and (as_of_utc - avail) > timedelta(days=pol.max_event_age_days):
                dec.unusable_events.append({"accession": ev.accession, "reason": "event_too_old"})
                continue
        secs = [ev.sections.get(s) for s in pol.sections]
        secs = [s for s in secs if s is not None]
        if not any(s.status == "ok" for s in secs):
            dec.unusable_events.append({"accession": ev.accession, "reason": "no_section_comparable"})
            dec.data_gaps.extend(f"{ev.accession}:{f}" for s in secs for f in s.flags)
            continue
        usable += 1
        dec.data_gaps.extend(f"{ev.accession}:{f}" for s in secs if s.status != "ok" for f in s.flags)
        suppress = any(f.split(":")[0] in pol.suppress_on_flags for f in ev.flags)
        for sd in secs:
            if sd.status != "ok":
                continue
            for tag in sd.tags:
                cand = _veto_candidate(tag, ev, pol)
                if cand is None:
                    continue
                if suppress and not (pol.new_category_bypasses_suppression and tag.novelty == "new_category"):
                    dec.suppressed.append(cand)
                else:
                    dec.reasons.append(cand)
    if dec.reasons:
        dec.decision = "hold"
        dec.reason_codes = list(dict.fromkeys(r.code for r in dec.reasons))
    elif usable == 0:
        dec.reason_codes = ["no_usable_event"]
    elif dec.suppressed:
        dec.reason_codes = ["suppressed_template_restructure"]
    else:
        dec.reason_codes = ["no_qualifying_change"]
    dec.data_gaps = list(dict.fromkeys(dec.data_gaps))
    return dec


def _veto_candidate(tag: RiskTag, ev: FilingChangeEvent, pol: FilingVetoPolicy) -> Optional[VetoReason]:
    if tag.modality == "negated" or tag.modality == "fragment":
        return None
    if pol.require_asserted and tag.modality != "asserted":
        return None
    cat = tag.category
    if cat == CATEGORY_CONCENTRATION and pol.hold_concentration_increase:
        nc = tag.numeric_change
        if tag.novelty == "numeric_change" and nc and nc.get("unit") == "%":
            if nc["delta"] >= pol.concentration_increase_pp:
                return _reason_from(tag, "customer_concentration_increase", ev, nc)
            return None
        if tag.is_new and tag.severity == "strong" and re.search(r"\d\s?%", tag.anchor):
            return _reason_from(tag, "new_customer_concentration_disclosure", ev)
        return None
    if not tag.is_new or tag.severity != "strong":
        return None
    if cat == CATEGORY_LIQUIDITY and pol.hold_liquidity:
        code = "new_going_concern_language" if _GOING_CONCERN_RE.search(tag.anchor) else "new_liquidity_distress_language"
        return _reason_from(tag, code, ev)
    if cat == CATEGORY_LITIGATION and pol.hold_litigation:
        if pol.require_specific_litigation and not tag.specific:
            return None
        return _reason_from(tag, "new_major_litigation", ev)
    if cat == CATEGORY_COMPETITION and pol.hold_competition:
        return _reason_from(tag, "new_competition_pressure_language", ev)
    if cat == CATEGORY_CYBER and pol.hold_cyber:
        return _reason_from(tag, "new_cyber_incident_language", ev)
    if cat == CATEGORY_ACCOUNTING and pol.hold_accounting_controls:
        return _reason_from(tag, "new_accounting_controls_language", ev)
    return None


# ============================================================================
# 10. SEC EDGAR fetcher (submissions API + 주 문서 HTML)
# ============================================================================

_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    """core/guru_tracker.py 와 같은 방식: 프로젝트 .env 를 환경변수로 로드(값은 건드리거나 출력하지 않는다)."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # python-dotenv 없음 등
        pass


def resolve_user_agent(env: Optional[dict] = None) -> str:
    """SEC_EDGAR_USER_AGENT -> SEC_USER_AGENT -> 개인정보 없는 일반 문자열 순으로 User-Agent 를 정한다.

    env 를 주면(테스트) os.environ·.env 를 읽지 않는다. 반환값을 로그·문서에 남기지 않는다.
    """
    if env is None:
        _load_dotenv_once()
        env = os.environ
    for name in SEC_USER_AGENT_ENVS:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return DEFAULT_USER_AGENT


def user_agent_source(env: Optional[dict] = None) -> str:
    """어느 출처를 썼는지만 반환한다(환경변수 이름 또는 'default'). 값은 반환하지 않는다."""
    if env is None:
        _load_dotenv_once()
        env = os.environ
    for name in SEC_USER_AGENT_ENVS:
        if (env.get(name) or "").strip():
            return name
    return "default"


class EdgarFetchError(RuntimeError):
    """EDGAR 조회 실패. 메시지·속성에 User-Agent 값은 넣지 않는다."""

    def __init__(self, message: str, *, status: Optional[int] = None, kind: str = "http"):
        super().__init__(message)
        self.status = status
        self.kind = kind


class EdgarBlocked(EdgarFetchError):
    """403 등 SEC 가 요청을 차단했다. 재시도하지 않는다."""


class EdgarUndeclaredUserAgent(EdgarBlocked):
    """SEC 가 '미신고 자동화 도구'로 판단해 차단했다. 사용자가 회사 특정 정보가 든 User-Agent 를 환경변수로 설정해야 한다."""


class EdgarRateLimited(EdgarFetchError):
    """429 등 속도 제한이 backoff 후에도 계속됐다."""


class RateLimiter:
    """슬라이딩 윈도우: 어떤 1초 구간에도 요청 시작이 max_per_second 회를 넘지 않게 한다(상한 5)."""

    def __init__(self, max_per_second: int = MAX_REQUESTS_PER_SECOND, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        n = int(min(max_per_second, MAX_REQUESTS_PER_SECOND))
        if n < 1:
            raise ValueError("max_per_second must be >= 1")
        self.max_per_second = n
        self._window = 1.0
        self._clock, self._sleep = clock, sleep
        self._stamps: deque = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            while True:
                now = self._clock()
                while self._stamps and now - self._stamps[0] >= self._window:
                    self._stamps.popleft()
                if len(self._stamps) < self.max_per_second:
                    self._stamps.append(now)
                    return
                self._sleep(max(0.0, self._window - (now - self._stamps[0])) + 1e-3)


def _requests_get(url: str, headers: dict, timeout: float):
    import requests

    r = requests.get(url, headers=headers, timeout=timeout)
    return r.status_code, r.content, dict(r.headers)


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class EdgarClient:
    """SEC EDGAR 조회 클라이언트: User-Agent 는 환경변수만, 초당 5회 이하, 파일 캐시, 429·5xx backoff.

    - 403(미신고 자동화 도구 차단 포함)은 재시도하지 않고 EdgarBlocked/EdgarUndeclaredUserAgent 를 올린다.
    - 캐시: submissions JSON 은 TTL(기본 6시간), 문서·이전 페이지는 변하지 않으므로 무기한. 기본 위치는
      data/cache/sec_filings/ (git 무시 대상).
    - first_seen 원장(캐시 폴더의 first_seen.json)은 이 수집기가 accession 을 처음 본 시각이며 과거 백필에서는
      의미가 없다(재구성 모드에서는 사용하지 않는다).
    """

    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
    SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
    TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        *,
        user_agent: Optional[str] = None,
        http_get: Optional[Callable] = None,
        limiter: Optional[RateLimiter] = None,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        backoff_max: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        submissions_ttl_seconds: float = 6 * 3600,
        tickers_ttl_seconds: float = 7 * 24 * 3600,
        timeout: float = 30.0,
        record_first_seen: bool = True,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.user_agent_source = "explicit" if user_agent is not None else user_agent_source()
        self._ua = user_agent if user_agent is not None else resolve_user_agent()
        self._http_get = http_get or _requests_get
        self._limiter = limiter or RateLimiter(sleep=sleep)
        self.max_retries = max_retries
        self._backoff_base, self._backoff_max = backoff_base, backoff_max
        self._sleep, self._clock = sleep, clock
        self.submissions_ttl = submissions_ttl_seconds
        self.tickers_ttl = tickers_ttl_seconds
        self._timeout = timeout
        self._record_first_seen = record_first_seen
        self.requests_made = 0

    # --- 저수준 ---
    def _headers(self) -> dict:
        return {"User-Agent": self._ua, "Accept-Encoding": "gzip, deflate"}

    def _delay(self, attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(self._backoff_max, max(0.0, float(retry_after)))
            except ValueError:
                pass
        return min(self._backoff_max, self._backoff_base * (2 ** attempt))

    def _get(self, url: str) -> bytes:
        last_status: Optional[int] = None
        for attempt in range(self.max_retries + 1):
            self._limiter.wait()
            self.requests_made += 1
            try:
                status, body, headers = self._http_get(url, self._headers(), self._timeout)
            except Exception as exc:  # 연결·타임아웃
                last_status = None
                if attempt >= self.max_retries:
                    raise EdgarFetchError(f"network error after {attempt + 1} attempts: {type(exc).__name__}",
                                          kind="network") from None
                self._sleep(self._delay(attempt, None))
                continue
            if status == 200:
                return body
            head = body[:4000].decode("utf-8", "replace").lower() if body else ""
            if status == 403:
                if "undeclared automated tool" in head:
                    raise EdgarUndeclaredUserAgent(
                        "SEC blocked the request as an undeclared automated tool (403). Set SEC_EDGAR_USER_AGENT "
                        "to a User-Agent with your own contact information.", status=403, kind="undeclared_user_agent")
                raise EdgarBlocked("SEC returned 403 (blocked); not retried", status=403, kind="blocked")
            last_status = status
            if status == 429 or 500 <= status < 600:
                if attempt >= self.max_retries:
                    cls = EdgarRateLimited if status == 429 else EdgarFetchError
                    raise cls(f"HTTP {status} after {attempt + 1} attempts", status=status,
                              kind="rate_limited" if status == 429 else "http")
                self._sleep(self._delay(attempt, headers.get("Retry-After") or headers.get("retry-after")))
                continue
            raise EdgarFetchError(f"HTTP {status}", status=status, kind="http")
        raise EdgarFetchError(f"HTTP {last_status}", status=last_status)  # pragma: no cover

    def _fresh(self, path: Path, ttl: Optional[float]) -> bool:
        if not path.exists():
            return False
        if ttl is None:
            return True
        return (self._clock() - path.stat().st_mtime) <= ttl

    def _cached_bytes(self, url: str, path: Path, ttl: Optional[float]) -> bytes:
        if self._fresh(path, ttl):
            return path.read_bytes()
        body = self._get(url)
        _write_atomic(path, body)
        return body

    def _cached_json(self, url: str, path: Path, ttl: Optional[float]):
        raw = self._cached_bytes(url, path, ttl)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            try:
                path.unlink()
            except OSError:
                pass
            raise EdgarFetchError("response was not valid JSON", kind="bad_json") from None

    # --- first_seen 원장 ---
    @property
    def _first_seen_path(self) -> Path:
        return self.cache_dir / "first_seen.json"

    def _load_first_seen(self) -> dict:
        try:
            return json.loads(self._first_seen_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def first_seen(self, accession: str) -> Optional[str]:
        return self._load_first_seen().get(accession)

    def _note_first_seen(self, accessions: Iterable[str]) -> None:
        if not self._record_first_seen:
            return
        ledger = self._load_first_seen()
        now = _iso(datetime.fromtimestamp(self._clock(), _UTC))
        changed = False
        for a in accessions:
            if a and a not in ledger:
                ledger[a] = now
                changed = True
        if changed:
            _write_atomic(self._first_seen_path, json.dumps(ledger, sort_keys=True).encode("utf-8"))

    # --- 고수준 ---
    def resolve_cik(self, ticker: str) -> str:
        """티커 -> 10자리 CIK (SEC company_tickers.json). 이 파일도 www.sec.gov 라 신고된 User-Agent 가 필요할 수 있다."""
        want = re.sub(r"[.\s]", "-", ticker.strip().upper())
        data = self._cached_json(self.TICKERS_URL, self.cache_dir / "company_tickers.json", self.tickers_ttl)
        rows = data.values() if isinstance(data, dict) else data
        for row in rows:
            if re.sub(r"[.\s]", "-", str(row.get("ticker", "")).upper()) == want:
                return str(int(row["cik_str"])).zfill(10)
        raise EdgarFetchError(f"ticker not found in SEC ticker list: {ticker}", kind="ticker_not_found")

    def get_submissions(self, cik: str, *, include_older: bool = False) -> tuple:
        """(메타 dict, 열 지향 filings 목록의 리스트). include_older 면 filings.files 의 이전 페이지도 합친다."""
        cik10 = str(cik).zfill(10)
        meta = self._cached_json(self.SUBMISSIONS_URL.format(cik=cik10),
                                 self.cache_dir / "submissions" / f"CIK{cik10}.json", self.submissions_ttl)
        blocks = [meta.get("filings", {}).get("recent", {})]
        if include_older:
            for f in meta.get("filings", {}).get("files", []) or []:
                name = _safe_name(str(f.get("name", "")))
                if not name:
                    continue
                blocks.append(self._cached_json(self.SUBMISSIONS_FILE_URL.format(name=name),
                                                self.cache_dir / "submissions" / name, None))
        return meta, blocks

    def list_filings(
        self,
        *,
        ticker: Optional[str] = None,
        cik: Optional[str] = None,
        forms: Sequence[str] = SUPPORTED_FORMS,
        include_amendments: bool = False,
        include_older: bool = False,
        limit: Optional[int] = None,
    ) -> list:
        """10-K/10-Q 목록(최신순). 기본은 정정본(10-K/A 등)을 제외한다."""
        if not cik:
            if not ticker:
                raise ValueError("ticker or cik required")
            cik = self.resolve_cik(ticker)
        meta, blocks = self.get_submissions(cik, include_older=include_older)
        tickers = [str(t).upper() for t in (meta.get("tickers") or [])]
        rec_ticker = None
        if ticker and ticker.upper() in tickers:
            rec_ticker = ticker.upper()
        elif tickers:
            rec_ticker = tickers[0] if not ticker else None
        allowed = set(forms) | ({f + "/A" for f in forms} if include_amendments else set())
        recs = []
        for cols in blocks:
            recs.extend(r for r in parse_submissions_columns(cols, cik=cik, ticker=rec_ticker,
                                                             company_name=meta.get("name"))
                        if r.form in allowed and r.primary_document)
        recs.sort(key=_sort_key, reverse=True)
        self._note_first_seen(r.accession for r in recs)
        return recs[:limit] if limit else recs

    def fetch_primary_document(self, record: FilingRecord) -> str:
        """주 문서(HTML) 텍스트. 문서는 변하지 않으므로 무기한 캐시한다."""
        if not record.primary_document:
            raise EdgarFetchError("record has no primary document", kind="no_document")
        path = (self.cache_dir / "docs" / str(int(record.cik)) / record.accession_nodash
                / _safe_name(record.primary_document))
        raw = self._cached_bytes(record.document_url, path, None)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1252", errors="replace")


def build_latest_filing_change_event(
    client: EdgarClient,
    *,
    ticker: Optional[str] = None,
    cik: Optional[str] = None,
    form: str = "10-K",
    mode: str = "retrospective",
    assumed_latency_hours: float = 0.5,
    trading_days: Optional[Iterable[date]] = None,
    options: Optional[ExtractOptions] = None,
    include_older: bool = False,
) -> FilingChangeEvent:
    """가장 최근 원본 공시와 직전 동종 원본 공시를 내려받아 이벤트를 만든다(정정본 제외). DB에 쓰지 않는다."""
    recs = client.list_filings(ticker=ticker, cik=cik, forms=(form,), include_older=include_older)
    if not recs:
        raise EdgarFetchError(f"no {form} filings found", kind="no_filings")
    current = recs[0]
    prior = find_prior_filing(recs, current)
    cur_doc = client.fetch_primary_document(current)
    prior_doc = client.fetch_primary_document(prior) if prior is not None else None
    return build_filing_change_event(
        current, cur_doc, prior, prior_doc, mode=mode, assumed_latency_hours=assumed_latency_hours,
        system_first_seen=client.first_seen(current.accession) if mode == "live" else None,
        trading_days=trading_days, options=options,
    )
