"""SEC EDGAR 8-K Item 2.02 실적 보도자료 수집 + 규칙 기반 발행사 가이던스 추출 (RES-04 1단계).

사전 등록 스펙: docs/EARNINGS_GUIDANCE_EXPERIMENT_SPEC.md. 이 모듈은 **주문 경로·DB·스케줄러와 연결되지
않는** 연구용 순수 모듈이다(개별주 위성 shadow 실험 전용). 성과·정확도를 주장하지 않는다.

구성
1. fetcher: SEC submissions API로 8-K Item 2.02 목록과 acceptance 시각을 받고, filing 인덱스에서 EX-99.1
   보도자료 본문을 받는다. 요청 규칙: User-Agent 는 환경변수 SEC_EDGAR_USER_AGENT(기존 관례, core/guru_tracker.py 와
   동일), 없으면 SEC_USER_AGENT, 그래도 없으면 개인정보 없는 일반 문자열이며 값을 코드·로그·오류 메시지·캐시에
   남기지 않는다. 초당 5회 이하, 파일 캐시, 5xx/429/네트워크 오류에만 지수 백오프 재시도. 403(차단)은 재시도하지
   않고 SecAccessError 로 즉시 중단한다.
2. 추출기(순수 함수, LLM 호출 없음): 보도자료 텍스트에서 가이던스 문장·표를 찾아 구조화 필드로 추출한다.
   애매하면 추측하지 않고 건너뛴 이유를 남긴다.
3. 변화 분류(순수 함수): 같은 기업·metric·basis·대상 기간의 직전 발행사 가이던스와 비교해
   raised/lowered/maintained/initiated/withdrawn/unknown 을 계산한다. 다른 기간끼리 비교는 거부한다.
   방향(raised/lowered/maintained)은 **연간 가이던스의 같은 회계연도 재발표**끼리만 낸다(정책 annual_same_fy_v1).
   분기·반기 가이던스는 방향을 내지 않고 unknown(quarterly_not_comparable 등)이다. 판정 근거(비교 방식, 직전
   항목 accession·시각·period_key, 세분화 사유)는 GuidanceChange 의 추가 필드와 evidence() 에 남는다.
4. 시각 처리(순수 함수): acceptance 시각을 뉴욕 장전/장중/장후로 분류하고 다음 실행가능 시가를 계산한다.

컨센서스는 사용하지 않는다(PIT 확보 전 금지). 추출은 규칙 기반이며 LLM 사용 시 역할·제약은 스펙 9절을 따른다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Optional, Sequence
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "sec_edgar"

# 읽는 순서: 기존 프로젝트 관례(core/guru_tracker.py, .env.example)인 SEC_EDGAR_USER_AGENT 먼저, 없으면
# SEC_USER_AGENT. 값에는 사용자의 연락처가 들어갈 수 있어 어디에도 출력·기록하지 않는다.
USER_AGENT_ENVS = ("SEC_EDGAR_USER_AGENT", "SEC_USER_AGENT")
# 개인정보가 없는 일반 문자열. SEC 는 연락처 없는 User-Agent 를 www.sec.gov 에서 403 으로 막을 수 있다
# (2026-09-21 이 환경 관측). 그 경우 실행 환경(.env 포함)에 위 환경변수를 설정해야 한다.
DEFAULT_USER_AGENT = "QuantResearch personal-project"
_DOTENV_LOADED = False

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
SEC_HOST = "https://www.sec.gov"

MAX_REQUESTS_PER_SECOND = 5
DEFAULT_MIN_INTERVAL_SECONDS = 0.25  # 초당 4회 -> 5회 상한을 안전하게 넘지 않음
SUBMISSIONS_TTL_SECONDS = 6 * 3600
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRY_AFTER_SECONDS = 60.0

NY_TZ = ZoneInfo("America/New_York")
MARKET_OPEN_ET = dtime(9, 30)
MARKET_CLOSE_ET = dtime(16, 0)
DEFAULT_ENTRY_LATENCY_MINUTES = 15


# ---------------------------------------------------------------------------
# 1. fetcher
# ---------------------------------------------------------------------------


class SecFetchError(RuntimeError):
    """SEC 요청 실패(404, 재시도 소진 등)."""


class SecAccessError(SecFetchError):
    """403 등 접근 차단. 재시도하지 않는다(재시도는 차단을 악화시킬 뿐이다)."""


def _ensure_dotenv_loaded() -> None:
    """core/db.py 등 기존 코드와 같은 방식(python-dotenv load_dotenv, 이미 있는 환경변수는 덮어쓰지 않음)."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # python-dotenv 없음 등: 환경변수만 쓴다
        pass


def get_user_agent() -> str:
    """User-Agent 를 SEC_EDGAR_USER_AGENT -> SEC_USER_AGENT -> 개인정보 없는 일반 문자열 순으로 고른다.

    반환값(사용자 연락처일 수 있음)은 출력·로그·문서에 남기지 않는다.
    """
    _ensure_dotenv_loaded()
    for name in USER_AGENT_ENVS:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return DEFAULT_USER_AGENT


def _pad_cik(cik) -> str:
    digits = re.sub(r"\D", "", str(cik))
    if not digits:
        raise ValueError(f"CIK 형식이 아닙니다: {cik!r}")
    return digits.zfill(10)


def _accession_nodash(accession: str) -> str:
    return accession.replace("-", "")


@dataclass(frozen=True)
class SecDocument:
    url: str
    text: str
    fetched_at: datetime  # UTC. system_first_seen 의 근거(소급 수집이면 실제 수신 시각이 아님)
    from_cache: bool
    content_sha256: str


class _RateLimiter:
    """요청 사이 최소 간격을 보장한다. clock/sleep 주입으로 테스트한다."""

    def __init__(self, min_interval: float, clock: Callable[[], float], sleep: Callable[[float], None]):
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: Optional[float] = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last is not None:
                remaining = self._last + self._min_interval - now
                if remaining > 0:
                    self._sleep(remaining)
                    now = self._clock()
            self._last = now


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _looks_like_block_page(text: str) -> bool:
    head = text[:3000].lower()
    return "undeclared automated tool" in head or "request rate threshold" in head


class SecEdgarClient:
    """SEC EDGAR 공개 자료용 얇은 HTTP 클라이언트(캐시·요청 간격·재시도)."""

    def __init__(
        self,
        *,
        cache_dir: Optional[Path] = None,
        user_agent: Optional[str] = None,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        max_attempts: int = 4,
        base_delay_seconds: float = 1.0,
        timeout_seconds: float = 20.0,
        submissions_ttl_seconds: Optional[float] = SUBMISSIONS_TTL_SECONDS,
        session=None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if min_interval_seconds < 1.0 / MAX_REQUESTS_PER_SECOND:
            raise ValueError(f"요청 간격은 초당 {MAX_REQUESTS_PER_SECOND}회 이하가 되도록 "
                             f"{1.0 / MAX_REQUESTS_PER_SECOND:.2f}초 이상이어야 합니다.")
        if max_attempts < 1:
            raise ValueError("max_attempts 는 1 이상이어야 합니다.")
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.user_agent = (user_agent or get_user_agent()).strip() or DEFAULT_USER_AGENT
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.timeout_seconds = timeout_seconds
        self.submissions_ttl_seconds = submissions_ttl_seconds
        self._session = session
        self._sleep = sleep
        self._now = now
        self._limiter = _RateLimiter(min_interval_seconds, clock, sleep)
        self.request_count = 0  # 실제 네트워크 요청 시도 횟수(캐시 적중 제외)

    # -- cache ---------------------------------------------------------
    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        tail = re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1])[:60] or "index"
        base = self.cache_dir / f"{digest}_{tail}"
        return base.with_name(base.name + ".body"), base.with_name(base.name + ".meta.json")

    def _read_cache(self, url: str, ttl_seconds: Optional[float]) -> Optional[SecDocument]:
        body_path, meta_path = self._cache_paths(url)
        if not body_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(meta["fetched_at"])
            raw = body_path.read_bytes()
        except (OSError, ValueError, KeyError):
            return None
        if ttl_seconds is not None and (self._now() - fetched_at).total_seconds() > ttl_seconds:
            return None
        return SecDocument(url=url, text=_decode(raw), fetched_at=fetched_at, from_cache=True,
                           content_sha256=hashlib.sha256(raw).hexdigest())

    def _write_cache(self, url: str, raw: bytes, fetched_at: datetime) -> None:
        body_path, meta_path = self._cache_paths(url)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(raw)
            meta_path.write_text(json.dumps({"url": url, "fetched_at": fetched_at.isoformat()}), encoding="utf-8")
        except OSError:
            pass  # 캐시 실패는 수집 실패가 아니다

    # -- http ----------------------------------------------------------
    def _get_session(self):
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _backoff(self, attempt: int, retry_after: Optional[str]) -> float:
        delay = self.base_delay_seconds * (2 ** (attempt - 1))
        if retry_after:
            try:
                delay = max(delay, min(float(retry_after), _MAX_RETRY_AFTER_SECONDS))
            except ValueError:
                pass
        return delay

    def get(self, url: str, *, ttl_seconds: Optional[float] = None, use_cache: bool = True) -> SecDocument:
        """URL 본문을 받는다. ttl_seconds=None 이면 캐시를 영구 유효로 본다(accession 문서는 불변)."""
        if use_cache:
            cached = self._read_cache(url, ttl_seconds)
            if cached is not None:
                return cached
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        last_error: Optional[str] = None
        for attempt in range(1, self.max_attempts + 1):
            self._limiter.wait()
            self.request_count += 1
            try:
                resp = self._get_session().get(url, headers=headers, timeout=self.timeout_seconds)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt == self.max_attempts:
                    break
                self._sleep(self._backoff(attempt, None))
                continue
            status = resp.status_code
            if status == 200:
                raw = resp.content
                text = _decode(raw)
                if _looks_like_block_page(text):
                    raise SecAccessError(f"SEC 차단 페이지 응답(HTTP 200): {url}")
                fetched_at = self._now()
                if use_cache:
                    self._write_cache(url, raw, fetched_at)
                return SecDocument(url=url, text=text, fetched_at=fetched_at, from_cache=False,
                                   content_sha256=hashlib.sha256(raw).hexdigest())
            if status == 403:
                raise SecAccessError(
                    f"HTTP 403(접근 차단): {url} - 재시도하지 않는다. SEC 는 연락처가 포함된 User-Agent 를 요구할 수 "
                    f"있다. 실행 환경에 {' 또는 '.join(USER_AGENT_ENVS)} 를 설정하라(값은 기록하지 않는다).")
            if status == 404:
                raise SecFetchError(f"HTTP 404: {url}")
            if status in _RETRYABLE_STATUS:
                last_error = f"HTTP {status}"
                if attempt == self.max_attempts:
                    break
                self._sleep(self._backoff(attempt, resp.headers.get("Retry-After")))
                continue
            raise SecFetchError(f"예상하지 못한 HTTP {status}: {url}")
        raise SecFetchError(f"재시도 {self.max_attempts}회 소진: {url} ({last_error})")

    # -- SEC endpoints -------------------------------------------------
    def fetch_submissions(self, cik) -> dict:
        url = SEC_SUBMISSIONS_URL.format(cik=_pad_cik(cik))
        return json.loads(self.get(url, ttl_seconds=self.submissions_ttl_seconds).text)

    def fetch_submissions_page(self, name: str) -> dict:
        return json.loads(self.get(SEC_SUBMISSIONS_PAGE_URL.format(name=name),
                                   ttl_seconds=self.submissions_ttl_seconds).text)


# ---------------------------------------------------------------------------
# 2. 8-K Item 2.02 목록
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EarningsFiling:
    cik: str  # 10자리
    ticker: Optional[str]
    company_name: Optional[str]
    accession: str  # 하이픈 포함
    form: str  # "8-K" 또는 "8-K/A"
    items: tuple[str, ...]
    filing_date: date
    report_date: Optional[date]
    acceptance_utc: datetime  # EDGAR acceptance 시각(UTC, tz-aware)
    primary_document: str

    @property
    def folder_url(self) -> str:
        return f"{SEC_ARCHIVES_BASE}/{int(self.cik)}/{_accession_nodash(self.accession)}"

    @property
    def index_url(self) -> str:
        return f"{self.folder_url}/{self.accession}-index.htm"

    @property
    def primary_document_url(self) -> str:
        return f"{self.folder_url}/{self.primary_document}"


def _parse_acceptance(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_submissions_earnings_filings(
    submissions: dict,
    *,
    extra_pages: Sequence[dict] = (),
    include_amendments: bool = False,
    since: Optional[date] = None,
    until: Optional[date] = None,
) -> list[EarningsFiling]:
    """submissions JSON(및 과거 페이지)에서 8-K Item 2.02 를 골라 acceptance 시각 순(오름차순)으로 반환한다.

    acceptanceDateTime 이 없거나 해석할 수 없는 행은 PIT 시각을 알 수 없어 제외한다.
    """
    cik = _pad_cik(submissions.get("cik", ""))
    tickers = submissions.get("tickers") or []
    ticker = tickers[0] if tickers else None
    name = submissions.get("name")
    wanted_forms = {"8-K", "8-K/A"} if include_amendments else {"8-K"}

    blocks = [(submissions.get("filings") or {}).get("recent") or {}]
    blocks.extend(extra_pages)
    seen: set[str] = set()
    out: list[EarningsFiling] = []
    for block in blocks:
        accessions = block.get("accessionNumber") or []
        for i, accession in enumerate(accessions):
            if accession in seen:
                continue

            def col(key):
                values = block.get(key) or []
                return values[i] if i < len(values) else None

            form = col("form")
            if form not in wanted_forms:
                continue
            items = tuple(s.strip() for s in (col("items") or "").split(",") if s.strip())
            if "2.02" not in items:
                continue
            acceptance = _parse_acceptance(col("acceptanceDateTime"))
            filing_date = _parse_date(col("filingDate"))
            if acceptance is None or filing_date is None:
                continue
            if since is not None and filing_date < since:
                continue
            if until is not None and filing_date > until:
                continue
            seen.add(accession)
            out.append(EarningsFiling(
                cik=cik, ticker=ticker, company_name=name, accession=accession, form=form, items=items,
                filing_date=filing_date, report_date=_parse_date(col("reportDate")),
                acceptance_utc=acceptance, primary_document=col("primaryDocument") or ""))
    out.sort(key=lambda f: (f.acceptance_utc, f.accession))
    return out


def list_earnings_filings(
    client: SecEdgarClient,
    cik,
    *,
    since: Optional[date] = None,
    until: Optional[date] = None,
    include_amendments: bool = False,
) -> list[EarningsFiling]:
    """CIK 의 8-K Item 2.02 목록. since 가 recent 범위보다 이르면 과거 submissions 페이지도 받는다.

    since=None 이면 filings.recent(최근 약 1,000건)만 본다.
    """
    data = client.fetch_submissions(cik)
    recent_dates = ((data.get("filings") or {}).get("recent") or {}).get("filingDate") or []
    pages: list[dict] = []
    if since is not None and recent_dates and since.isoformat() < min(recent_dates):
        for meta in (data.get("filings") or {}).get("files", []) or []:
            if meta.get("filingTo") and meta["filingTo"] < since.isoformat():
                continue
            if until is not None and meta.get("filingFrom") and meta["filingFrom"] > until.isoformat():
                continue
            pages.append(client.fetch_submissions_page(meta["name"]))
    return parse_submissions_earnings_filings(
        data, extra_pages=pages, include_amendments=include_amendments, since=since, until=until)


# ---------------------------------------------------------------------------
# 3. filing 인덱스 / 보도자료 본문
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FilingDocument:
    seq: str
    description: str
    filename: str
    doc_type: str
    url: str


def _resolve_doc_href(href: str) -> str:
    href = href.strip()
    if "/ix?" in href:  # 인라인 XBRL 뷰어 링크: /ix?doc=/Archives/...
        params = parse_qs(urlparse(href).query)
        if params.get("doc"):
            href = params["doc"][0]
    if href.startswith("http"):
        return href
    if not href.startswith("/"):
        href = "/" + href
    return SEC_HOST + href


def parse_filing_index_html(html: str) -> list[FilingDocument]:
    """`<accession>-index.htm` 의 Document Format Files 표에서 문서 목록(Type 포함)을 읽는다."""
    import lxml.html

    if not html or not html.strip():
        return []
    root = lxml.html.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", html))
    docs: list[FilingDocument] = []
    for table in root.xpath('//table[contains(@class, "tableFile")]'):
        header = [th.text_content().strip().lower() for th in table.xpath('.//tr[1]/th')]
        if "type" not in header or "document" not in header:
            continue
        idx = {name: header.index(name) for name in ("seq", "description", "document", "type") if name in header}
        for tr in table.xpath(".//tr[td]"):
            tds = tr.xpath("./td")
            if len(tds) <= max(idx["document"], idx["type"]):
                continue
            link = tds[idx["document"]].xpath(".//a")
            cell = tds[idx["document"]].text_content().replace("\xa0", " ").strip()
            if not cell:
                continue
            filename = cell.split()[0]  # 실제 페이지는 "file.htm  iXBRL" 처럼 표식이 붙는다
            href = link[0].get("href") if link else None
            docs.append(FilingDocument(
                seq=tds[idx["seq"]].text_content().strip() if "seq" in idx else "",
                description=tds[idx["description"]].text_content().strip() if "description" in idx else "",
                filename=filename,
                doc_type=tds[idx["type"]].text_content().strip(),
                url=_resolve_doc_href(href) if href else ""))
    return docs


_EXHIBIT_NAME_RE = re.compile(r"ex[-_]?99[-_.]?0?1", re.I)


def select_press_release_exhibit(docs: Sequence[FilingDocument]) -> Optional[FilingDocument]:
    """EX-99.1 (없으면 EX-99)만 보도자료로 본다. EX-99.2 이상은 추측하지 않는다.

    Type 열이 비어 있는 경우에만 파일명(ex99-1 등)으로 보조 판정한다.
    """
    for wanted in ("EX-99.1", "EX-99"):
        for d in docs:
            if d.doc_type.strip().upper() == wanted and d.url:
                return d
    for d in docs:
        if not d.doc_type.strip() and _EXHIBIT_NAME_RE.search(d.filename) and d.url:
            return d
    return None


@dataclass(frozen=True)
class PressRelease:
    filing: EarningsFiling
    exhibit_type: str  # "EX-99.1" / "EX-99" / "8-K(primary)"
    document_url: str
    text: str
    fetched_at: datetime
    content_sha256: str


def fetch_press_release(client: SecEdgarClient, filing: EarningsFiling) -> Optional[PressRelease]:
    """filing 의 EX-99.1 보도자료 본문을 텍스트로 받는다. 없으면 8-K 본문(primary)으로 대체하고 표시한다.

    요청은 인덱스 1회 + 문서 1회(캐시 적중 시 0회). 본문을 특정할 수 없으면 None.
    """
    index_doc = client.get(filing.index_url)  # accession 문서는 불변 -> 영구 캐시
    exhibit = select_press_release_exhibit(parse_filing_index_html(index_doc.text))
    if exhibit is not None:
        doc = client.get(exhibit.url)
        return PressRelease(filing, exhibit.doc_type.strip().upper() or "EX-99.1", exhibit.url,
                            html_to_text(doc.text), doc.fetched_at, doc.content_sha256)
    if filing.primary_document:
        doc = client.get(filing.primary_document_url)
        return PressRelease(filing, "8-K(primary)", filing.primary_document_url,
                            html_to_text(doc.text), doc.fetched_at, doc.content_sha256)
    return None


# ---------------------------------------------------------------------------
# 4. HTML -> 텍스트
# ---------------------------------------------------------------------------

_BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "table", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
               "center", "blockquote", "section", "article", "pre"}
_SYMBOL_ONLY_CELL = re.compile(r"^[\$€£%\)\(]+$")


def _cell_text(el) -> str:
    return re.sub(r"\s+", " ", (el.text_content() or "").replace("\xa0", " ")).strip()


def _merge_symbol_cells(cells: list[str]) -> list[str]:
    """SEC 표는 '$', '%', ')' 가 별도 셀인 경우가 많다. 이웃 셀에 붙이고 빈 셀을 없앤다."""
    cells = [c for c in cells if c]
    out: list[str] = []
    pending_prefix = ""
    for c in cells:
        if _SYMBOL_ONLY_CELL.match(c) and c in {"$", "€", "£", "("}:
            pending_prefix += c
            continue
        if _SYMBOL_ONLY_CELL.match(c) and out and c in {"%", ")"}:
            out[-1] = out[-1] + c
            continue
        out.append(pending_prefix + c)
        pending_prefix = ""
    if pending_prefix:
        out.append(pending_prefix)
    return out


def html_to_text(html: str) -> str:
    """SEC 보도자료 HTML 을 줄 단위 텍스트로 바꾼다. 표의 행은 ' | ' 로 셀을 이은 한 줄이 된다."""
    import lxml.html

    if not html or not html.strip():
        return ""
    root = lxml.html.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", html))
    for el in root.xpath('//script|//style|//head|//comment()'):
        el.drop_tree()
    for el in root.xpath('//*[contains(translate(@style, " ", ""), "display:none")]'):
        el.drop_tree()
    for tr in list(root.iter("tr")):
        cells = _merge_symbol_cells([_cell_text(td) for td in tr.xpath("./td|./th")])
        line = " | ".join(cells)
        for child in list(tr):
            tr.remove(child)
        tr.text = line
    for el in root.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag == "br":
            el.tail = "\n" + (el.tail or "")
        elif tag in _BLOCK_TAGS:
            el.text = "\n" + (el.text or "")
            el.tail = "\n" + (el.tail or "")
    text = root.text_content().replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


# ---------------------------------------------------------------------------
# 5. 시각 처리 (장전/장중/장후, 다음 실행가능 시가)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReleaseTiming:
    acceptance_utc: datetime
    acceptance_et: datetime
    session: str  # "pre_market" / "regular" / "after_hours" / "non_trading_day"


def _is_trading_day(d: date, trading_days: Optional[frozenset]) -> bool:
    if trading_days is not None:
        return d in trading_days
    return d.weekday() < 5  # 달력이 없으면 주말만 제외(휴장일 미반영)


def classify_release_session(acceptance_utc: datetime, trading_days: Optional[Sequence[date]] = None) -> ReleaseTiming:
    """acceptance 시각(UTC)을 뉴욕 시각으로 바꿔 장전/장중/장후/비거래일로 분류한다."""
    if acceptance_utc.tzinfo is None:
        raise ValueError("acceptance_utc 는 tz-aware 여야 합니다.")
    et = acceptance_utc.astimezone(NY_TZ)
    days = frozenset(trading_days) if trading_days is not None else None
    if not _is_trading_day(et.date(), days):
        session = "non_trading_day"
    elif et.time() < MARKET_OPEN_ET:
        session = "pre_market"
    elif et.time() < MARKET_CLOSE_ET:
        session = "regular"
    else:
        session = "after_hours"
    return ReleaseTiming(acceptance_utc=acceptance_utc.astimezone(timezone.utc), acceptance_et=et, session=session)


def decision_cutoff(*times: Optional[datetime]) -> datetime:
    """source_publication / system_first_seen / extraction_completed 중 가장 늦은 시각(None 은 무시)."""
    valid = [t for t in times if t is not None]
    if not valid:
        raise ValueError("시각이 하나 이상 필요합니다.")
    if any(t.tzinfo is None for t in valid):
        raise ValueError("모든 시각은 tz-aware 여야 합니다.")
    return max(valid).astimezone(timezone.utc)


@dataclass(frozen=True)
class ExecutableEntry:
    entry_date: date
    entry_open_et: datetime
    calendar: str  # "trading_days_provided" / "weekday_only(holidays_not_excluded)"


def next_executable_open(
    available_at_utc: datetime,
    trading_days: Optional[Sequence[date]] = None,
    *,
    latency_minutes: int = DEFAULT_ENTRY_LATENCY_MINUTES,
) -> ExecutableEntry:
    """available_at + latency **이후에** 처음 열리는 정규장 시가(strict)의 날짜.

    같은 날 09:30 이 지났거나 09:30 정각이면 다음 거래일 시가다. trading_days 가 없으면 주말만 제외한다.
    """
    if available_at_utc.tzinfo is None:
        raise ValueError("available_at_utc 는 tz-aware 여야 합니다.")
    threshold = available_at_utc.astimezone(NY_TZ) + timedelta(minutes=latency_minutes)
    days = frozenset(trading_days) if trading_days is not None else None
    d = threshold.date()
    for _ in range(400):
        if _is_trading_day(d, days):
            open_et = datetime.combine(d, MARKET_OPEN_ET, tzinfo=NY_TZ)
            if open_et > threshold:
                return ExecutableEntry(
                    entry_date=d, entry_open_et=open_et,
                    calendar="trading_days_provided" if days is not None else "weekday_only(holidays_not_excluded)")
        d += timedelta(days=1)
    raise ValueError("다음 거래일을 찾지 못했습니다(trading_days 범위를 확인하세요).")


# ---------------------------------------------------------------------------
# 6. 가이던스 추출 (규칙 기반, 순수 함수)
# ---------------------------------------------------------------------------

_CHAR_MAP = str.maketrans({
    "–": "-", "—": "-", "‑": "-", "‒": "-", "−": "-", " ": " ", " ": " ",
    " ": " ", "“": '"', "”": '"', "’": "'", "‘": "'",
})


def normalize_text(text: str) -> str:
    return text.translate(_CHAR_MAP)


_SCALES = {"trillion": Decimal("1e12"), "billion": Decimal("1e9"), "bn": Decimal("1e9"), "b": Decimal("1e9"),
           "million": Decimal("1e6"), "mm": Decimal("1e6"), "m": Decimal("1e6"),
           "thousand": Decimal("1e3"), "k": Decimal("1e3")}
_TABLE_SCALES = {"thousands": "thousand", "millions": "million", "billions": "billion"}

_CURRENCY_MAP = {"$": "USD", "us$": "USD", "usd": "USD", "c$": "CAD", "cad": "CAD", "a$": "AUD",
                 "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP"}

_CUR = r"(?:US\s?\$|C\s?\$|A\s?\$|\$|€|£|USD\b|EUR\b|GBP\b|CAD\b)"
_AMOUNT_RE = re.compile(
    r"(?P<lp>\(\s*)?"
    r"(?P<neg>(?<![\w%)])-(?=[$€£\d(]))?"
    r"(?P<cur>" + _CUR + r"\s*)?"
    r"(?P<lp2>\(\s*)?"
    r"(?P<neg2>-(?=\d))?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<rp>\))?"
    r"(?:\s*(?P<scale>trillion|billion|million|thousand|bn|mm)\b|(?P<scale2>[MBK])\b)?"
    r"(?:\s*(?P<pct>%|percent\b|per\s?cent\b))?"
    r"(?:\s*(?P<bps>bps\b|basis\s+points?\b))?",
    re.I)
_TOLERANCE_RE = re.compile(r"^\s*,?\s*(?:plus or minus|\+/-|\+-|±)\s*(\d+(?:\.\d+)?)\s*(?:%|percent\b)", re.I)
_PER_SHARE_RIGHT_RE = re.compile(r"^\s*[,(]?\s*(?:per|a)\s+(?:diluted\s+|basic\s+)?(?:common\s+)?share", re.I)
_CURRENCY_WORD_RE = re.compile(r"^\s*(?:u\.?s\.?\s+)?(dollars?|euros?|pounds?)\b", re.I)

_METRIC_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("eps", re.compile(
        r"(?:eps\b|earnings per(?: diluted| basic)?(?: common)? share|"
        r"(?:net )?(?:income|earnings|loss) per(?: diluted| basic)?(?: common)? share|"
        r"per(?: diluted| basic)?(?: common)? share)", re.I)),
    ("operating_margin", re.compile(r"operating (?:income |profit )?margin", re.I)),
    ("gross_margin", re.compile(r"gross (?:profit )?margin", re.I)),
    ("operating_income", re.compile(r"operating (?:income|profit|loss)|(?:income|loss) from operations", re.I)),
    ("ebitda", re.compile(r"ebitda", re.I)),
    ("revenue", re.compile(r"(?:revenues?|net sales|sales)", re.I)),
]
_CURRENCY_METRICS = {"revenue", "operating_income", "ebitda"}
_PERCENT_METRICS = {"gross_margin", "operating_margin", "revenue_growth"}
_GROWTH_WORDS_RE = re.compile(r"\b(?:growth|grow\w*|increase\w*|up)\b", re.I)

_CUE_RE = re.compile(
    r"\b(?:expect\w*|anticipat\w+|outlook|guidance|guid(?:e|es|ed|ing)|forecast\w*|project(?:s|ed|ing|ion|ions)?|"
    r"target(?:s|ed|ing)?|range of|will be (?:in the range|between)|to be (?:in the range|between))\b", re.I)
_DISCLAIMER_RE = re.compile(r"forward[- ]looking|safe harbor|risks? and uncertaint|undertakes? no obligation", re.I)
_HEADING_RE = re.compile(r"\b(?:outlook|guidance|financial targets|business outlook)\b", re.I)
_TABLE_SCALE_RE = re.compile(r"\bin\s+(thousands|millions|billions)\b", re.I)

_CHANGE_VERB_RE = re.compile(
    r"\b(?:rais\w*|lower\w*|reduc\w*|cut\w*|trim\w*|lift\w*|increas\w*|decreas\w*|revis\w*|updat\w*|boost\w*|"
    r"narrow\w*|widen\w*|adjust\w*|improv\w*)\b", re.I)

# 직전/실적 참조 표지: (정규식, 표지와 금액 사이에 허용하는 최대 글자 수)
_PRIOR_MARKS: list[tuple[re.Pattern, int]] = [
    (re.compile(r"\bprevious(?:ly)?\b", re.I), 30),
    (re.compile(r"\bprior\b", re.I), 30),
    (re.compile(r"\bcompared\s+(?:to|with)\b", re.I), 30),
    (re.compile(r"\bversus\b|\bvs\.?", re.I), 20),
    (re.compile(r"\blast\s+(?:quarter|year|month)\b", re.I), 20),
    (re.compile(r"\boriginal(?:ly)?\b", re.I), 30),
    (re.compile(r"\binitial(?:ly)?\s+(?:guided|guidance|outlook|expected)\b", re.I), 30),
    (re.compile(r"\b(?:was|were)\b", re.I), 14),
    (re.compile(r"\bhad\s+(?:been|expected|guided)\b", re.I), 20),
    (re.compile(r"\b(?:exceed\w*|surpass\w*|beat)\b", re.I), 60),
    (re.compile(r"\b(?:high|low|top|upper|lower|bottom)\s+end\b|\bmidpoint\b", re.I), 60),
]

_ACT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("withdraw", re.compile(
        r"\b(?:withdr(?:aw|ew|awn|awing|aws)|suspend\w*|discontinu\w+|no longer (?:provid\w+|issu\w+|expect\w* to provid\w+))\b"
        r"(?:\W+\w+){0,6}?\W+(?:guidance|outlook|forecast)|(?:guidance|outlook|forecast)\W+(?:\w+\W+){0,4}?"
        r"(?:withdrawn|suspended|discontinued)", re.I)),
    ("initiate", re.compile(
        r"\b(?:initiat\w+|introduc\w+|issu\w+|provid\w+)\b(?:\W+\w+){0,3}?\W+(?:initial|first|new)\W+(?:\w+\W+){0,3}?"
        r"(?:guidance|outlook)|\binitial\s+(?:full[- ]year\s+)?(?:guidance|outlook)", re.I)),
    ("raise", re.compile(
        r"\b(?:rais(?:e|es|ed|ing)|lift(?:s|ed|ing)?|boost(?:s|ed|ing)?|increas(?:e|es|ed|ing)|hik(?:e|es|ed|ing))\b"
        r"(?:\W+\w+){0,6}?\W+(?:outlook|guidance|forecast|expectations?|targets?)"
        r"|(?:outlook|guidance|forecast|expectations?)\W+(?:\w+\W+){0,3}?(?:raised|increased|lifted|boosted)", re.I)),
    ("lower", re.compile(
        r"\b(?:lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|cut(?:s|ting)?|trim(?:s|med|ming)?|decreas(?:e|es|ed|ing))\b"
        r"(?:\W+\w+){0,6}?\W+(?:outlook|guidance|forecast|expectations?|targets?)"
        r"|(?:outlook|guidance|forecast|expectations?)\W+(?:\w+\W+){0,3}?(?:lowered|reduced|cut|trimmed|decreased)",
        re.I)),
    ("maintain", re.compile(
        r"\b(?:reaffirm\w*|reiterat\w+|maintain\w*|confirm\w*|unchanged|continues? to expect|still expects?)\b", re.I)),
]

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
_ORD = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}


@dataclass(frozen=True)
class PeriodMatch:
    start: int
    end: int
    key: Optional[str]  # None 이면 연도 등을 알 수 없음
    raw: str
    reason: Optional[str] = None


def _year(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    value = value.lstrip("'")
    if len(value) == 2:
        return 2000 + int(value)
    return int(value)


def _prefix(word: Optional[str]) -> str:
    return "CY" if word and word.lower() in {"calendar", "cy"} else "FY"


_PERIOD_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("end_date", re.compile(
        r"\b(?P<what>quarter|fiscal year|year|period)\s+(?:ending|ended|ends)\s+(?P<mon>" + "|".join(_MONTHS) +
        r")\s+(?P<day>\d{1,2}),?\s+(?P<yr>(?:19|20)\d{2})", re.I)),
    ("ord_q_first", re.compile(
        r"\b(?P<fy>fiscal|calendar)?\s*(?P<yr>(?:19|20)\d{2})\s+(?P<ord>first|second|third|fourth)[- ]quarter\b", re.I)),
    ("ord_q", re.compile(
        r"\b(?P<ord>first|second|third|fourth|1st|2nd|3rd|4th)[- ]quarter"
        r"(?:\s+(?:of|for|in))?(?:\s+(?P<fy>fiscal|calendar))?(?:\s+year)?(?:\s+(?P<yr>(?:19|20)\d{2}|'\d{2}))?", re.I)),
    ("q_code", re.compile(
        r"\bQ(?P<q>[1-4])(?:\s+of)?(?:\s*(?P<fyw>FY|fiscal|CY|calendar)\s*(?P<yr1>(?:19|20)?\d{2})(?!\d)"
        r"|\s*'(?P<yr3>\d{2})|\s+(?P<yr2>(?:19|20)\d{2}))?", re.I)),
    ("half", re.compile(
        r"\b(?P<half>first|second)\s+half(?:\s+of)?(?:\s+(?P<fy>fiscal|calendar))?(?:\s+(?:year\s+)?(?P<yr>(?:19|20)\d{2}))?", re.I)),
    ("full_year", re.compile(
        r"\b(?:full[- ]year|for the year|year)\s+(?:of\s+)?(?P<fy>fiscal|calendar)?\s*(?:year\s+)?(?P<yr>(?:19|20)\d{2}|'\d{2})", re.I)),
    ("fy_code", re.compile(
        r"\b(?P<fyw>FY|fiscal(?:\s+year)?|calendar(?:\s+year)?|CY)\s*'?(?P<yr>(?:19|20)\d{2}|\d{2})(?!\d)", re.I)),
]


def find_periods(text: str) -> list[PeriodMatch]:
    """텍스트 안의 대상 기간 표현을 위치와 함께 찾는다. 겹치는 표현은 먼저 정의된 패턴이 우선한다."""
    found: list[PeriodMatch] = []

    def overlaps(s, e):
        return any(not (e <= p.start or s >= p.end) for p in found)

    for name, pat in _PERIOD_PATTERNS:
        for m in pat.finditer(text):
            if overlaps(m.start(), m.end()):
                continue
            raw = m.group(0).strip()
            key: Optional[str] = None
            reason: Optional[str] = None
            gd = m.groupdict()
            if name == "end_date":
                what = gd["what"].lower()
                tag = "QEND" if what == "quarter" else ("YEND" if "year" in what else "PEND")
                key = f"{tag}:{int(gd['yr']):04d}-{_MONTHS[gd['mon'].lower()]:02d}-{int(gd['day']):02d}"
            elif name in {"ord_q_first", "ord_q"}:
                q = _ORD[gd["ord"].lower()]
                y = _year(gd.get("yr"))
                if y is None:
                    reason = f"period_year_missing:Q{q}"
                else:
                    key = f"{_prefix(gd.get('fy'))}{y}Q{q}"
            elif name == "q_code":
                q = int(gd["q"])
                y = _year(gd.get("yr1") or gd.get("yr2") or gd.get("yr3"))
                if y is None:
                    reason = f"period_year_missing:Q{q}"
                else:
                    key = f"{_prefix(gd.get('fyw'))}{y}Q{q}"
            elif name == "half":
                h = 1 if gd["half"].lower() == "first" else 2
                y = _year(gd.get("yr"))
                if y is None:
                    reason = f"period_year_missing:H{h}"
                else:
                    key = f"{_prefix(gd.get('fy'))}{y}H{h}"
            elif name in {"full_year", "fy_code"}:
                y = _year(gd.get("yr"))
                key = f"{_prefix(gd.get('fy') or gd.get('fyw'))}{y}" if y else None
            found.append(PeriodMatch(m.start(), m.end(), key, raw, reason))
    found.sort(key=lambda p: p.start)
    return found


@dataclass(frozen=True)
class GuidanceItem:
    """규칙으로 추출한 발행사 가이던스 1건. 수치는 Decimal(통화 금액은 스케일 반영 후 기준통화 단위)."""

    cik: Optional[str]
    accession: Optional[str]
    acceptance_utc: Optional[datetime]
    source_url: Optional[str]
    metric: str  # revenue/revenue_growth/eps/gross_margin/operating_margin/operating_income/ebitda/all
    basis: str  # gaap/non_gaap/unspecified
    period_key: Optional[str]
    period_raw: Optional[str]
    shape: str  # range/point/lower_bound/upper_bound/withdrawn
    low: Optional[Decimal]
    high: Optional[Decimal]
    unit: Optional[str]  # currency/per_share/percent
    currency: Optional[str]
    anchor: str
    flags: tuple[str, ...] = ()
    stated_action: Optional[str] = None  # raise/lower/maintain/withdraw/initiate (발행사 문구)
    prior_stated: Optional[tuple[Optional[Decimal], Optional[Decimal]]] = None  # 같은 문장에 적힌 직전 (low, high)

    @property
    def midpoint(self) -> Optional[Decimal]:
        if self.low is None or self.high is None:
            return self.low if self.low is not None else self.high
        return (self.low + self.high) / 2

    @property
    def problems(self) -> tuple[str, ...]:
        """비교에 쓸 수 없는 이유(빈 튜플이면 비교 가능)."""
        out = [f for f in self.flags if f in _BLOCKING_FLAGS]
        if self.shape != "withdrawn" and self.period_key is None:
            out.append("period_unresolved")
        return tuple(out)

    def to_record(self) -> dict:
        def num(v):
            return None if v is None else format(v.normalize(), "f")
        return {
            "cik": self.cik, "accession": self.accession,
            "acceptance_utc": self.acceptance_utc.isoformat() if self.acceptance_utc else None,
            "source_url": self.source_url, "metric": self.metric, "basis": self.basis,
            "period_key": self.period_key, "period_raw": self.period_raw, "shape": self.shape,
            "low": num(self.low), "high": num(self.high), "unit": self.unit, "currency": self.currency,
            "anchor": self.anchor, "flags": list(self.flags), "stated_action": self.stated_action,
            "prior_stated": None if self.prior_stated is None else [num(self.prior_stated[0]), num(self.prior_stated[1])],
        }


_BLOCKING_FLAGS = {"scale_ambiguous", "sign_ambiguous", "range_order_suspicious", "currency_ambiguous"}


@dataclass(frozen=True)
class SkippedCandidate:
    anchor: str
    reason: str


@dataclass
class ExtractionResult:
    items: list[GuidanceItem] = field(default_factory=list)
    skipped: list[SkippedCandidate] = field(default_factory=list)
    # "guidance_found" / "guidance_language_unparsed" / "no_guidance_language"
    status: str = "no_guidance_language"


@dataclass
class _Amount:
    start: int
    end: int
    value: Decimal
    currency: Optional[str]
    scale: Optional[Decimal]
    scale_word: Optional[str]
    is_pct: bool
    negative: bool
    has_cur: bool
    bps: bool


def _parse_amounts(text: str) -> list[_Amount]:
    out: list[_Amount] = []
    for m in _AMOUNT_RE.finditer(text):
        try:
            value = Decimal(m.group("num").replace(",", ""))
        except InvalidOperation:
            continue
        scale_word = (m.group("scale") or m.group("scale2") or "").lower() or None
        cur_raw = (m.group("cur") or "").strip().replace(" ", "").lower()
        negative = bool(m.group("neg") or m.group("neg2") or ((m.group("lp") or m.group("lp2")) and m.group("rp")))
        end = m.end()
        currency = _CURRENCY_MAP.get(cur_raw) if cur_raw else None
        if currency is None and not cur_raw:
            cw = _CURRENCY_WORD_RE.match(text[end:])
            if cw:
                word = cw.group(1).lower()
                currency = "USD" if word.startswith("dollar") else ("EUR" if word.startswith("euro") else "GBP")
        out.append(_Amount(m.start(), end, -value if negative else value, currency,
                           _SCALES.get(scale_word) if scale_word else None, scale_word,
                           bool(m.group("pct")), negative, bool(cur_raw), bool(m.group("bps"))))
    return out


def _is_strong(a: _Amount) -> bool:
    return a.has_cur or a.is_pct or a.scale is not None


def _split_sentences(line: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z$\"'(])", line)
    return [p.strip() for p in parts if p.strip()]


def _detect_action(sentence: str) -> Optional[str]:
    hits = [name for name, pat in _ACT_PATTERNS if pat.search(sentence)]
    if "withdraw" in hits:
        return "withdraw"
    directional = [h for h in hits if h in {"raise", "lower"}]
    if len(directional) == 2:
        return None  # 상향과 하향이 한 문장에 섞임 -> 문구 기준 방향 없음
    if directional:
        return directional[0]
    for name in ("initiate", "maintain"):
        if name in hits:
            return name
    return None


def _detect_metric(window: str, right: str) -> Optional[str]:
    best: Optional[tuple[int, str]] = None
    for name, pat in _METRIC_PATTERNS:
        for m in pat.finditer(window):
            if best is None or m.end() > best[0] or (m.end() == best[0] and name in {"operating_margin", "gross_margin"}):
                best = (m.end(), name)
    if best is not None:
        return best[1]
    if _PER_SHARE_RIGHT_RE.match(right):
        return "eps"
    for name, pat in _METRIC_PATTERNS:
        if name != "eps" and pat.search(right[:40]):
            return name
    return None


def _detect_basis(metric: str, context: str) -> str:
    low = context.lower()
    non_gaap = bool(re.search(r"non-?\s?gaap|adjusted", low))
    gaap = bool(re.search(r"(?<!non-)(?<!non )\bgaap\b", low))
    if metric == "revenue":
        return "non_gaap" if non_gaap and not gaap else "gaap" if gaap and not non_gaap else "unspecified"
    if non_gaap and gaap:
        return "unspecified"
    if non_gaap:
        return "non_gaap"
    if gaap:
        return "gaap"
    return "unspecified"


_RESULT_RIGHT_RE = re.compile(
    r"^\s*,?\s*(?:which\s+)?(?:was\s+|is\s+)?(?:above|below|exceed\w*|surpass\w*|beat|"
    r"at the (?:high|low|top|bottom|upper|lower) end|within)\b", re.I)


def _is_prior_reference(left: str, sentence_before: str, right: str = "") -> bool:
    """금액 문맥이 '직전 값/실적 참조'인지. left 는 이 금액 바로 앞(직전 금액 끝 이후)의 텍스트."""
    if _RESULT_RIGHT_RE.match(right):
        return True  # "$1.3 billion exceeded the high end of ..." : 실적 값
    tail = left[-90:]
    for pat, gap in _PRIOR_MARKS:
        for m in pat.finditer(tail):
            if len(tail) - m.end() <= gap:
                return True
    m = re.search(r"\bfrom\s*$", left)
    if m and not re.search(r"\brang\w*\s+from\s*$", left, re.I):
        if _CHANGE_VERB_RE.search(sentence_before) or _AMOUNT_RE.search(sentence_before):
            return True
    return False


def _has_metric_and_number(text: str) -> bool:
    return any(p.search(text) for _, p in _METRIC_PATTERNS)


@dataclass
class _Cand:
    low: Decimal
    high: Decimal
    shape: str
    start: int
    end: int
    unit_pct: bool
    currency: Optional[str]
    scale_status: str  # explicit / table_header / not_needed / ambiguous
    per_share: bool
    negative_explicit: bool
    flags: list[str]
    from_tolerance: bool = False


def _build_candidates(sentence: str, scale_hint: Optional[str]) -> list[_Cand]:
    amounts = [a for a in _parse_amounts(sentence) if not a.bps]
    cands: list[_Cand] = []
    used: set[int] = set()
    change_before = lambda pos: bool(_CHANGE_VERB_RE.search(sentence[:pos]))  # noqa: E731
    for i, a in enumerate(amounts):
        if i in used:
            continue
        right = sentence[a.end:]
        tol = _TOLERANCE_RE.match(right) if _is_strong(a) else None
        if tol:
            pct = Decimal(tol.group(1))
            base = a.value * (a.scale or Decimal(1))
            if a.is_pct:
                base = a.value
            lo, hi = base * (1 - pct / 100), base * (1 + pct / 100)
            for j in range(i + 1, len(amounts)):
                if amounts[j].start >= a.end and amounts[j].start < a.end + tol.end():
                    used.add(j)
            cands.append(_Cand(lo, hi, "range", a.start, a.end + tol.end(), a.is_pct, a.currency,
                               "explicit" if a.scale else "ambiguous", bool(_PER_SHARE_RIGHT_RE.match(sentence[a.end + tol.end():])),
                               a.negative, ["range_from_tolerance"], True))
            continue
        nxt = amounts[i + 1] if i + 1 < len(amounts) else None
        joined = False
        if nxt is not None and (i + 1) not in used:
            gap = sentence[a.end:nxt.start]
            between = bool(re.search(r"\bbetween\s*$", sentence[max(0, a.start - 25):a.start], re.I))
            sep_ok = bool(re.match(r"^\s*(?:-|to|through)\s*$", gap, re.I)) or (between and bool(re.match(r"^\s*and\s*$", gap, re.I)))
            transition = (not cands and bool(re.match(r"^\s*to\s*$", gap, re.I)) and bool(re.search(r"\bfrom\s*$", sentence[max(0, a.start - 15):a.start], re.I))
                          and change_before(a.start) and not re.search(r"\brang\w*\s+from\s*$", sentence[max(0, a.start - 25):a.start], re.I))
            first_ok = _is_strong(a) or (nxt.is_pct and not a.has_cur) or bool(_PER_SHARE_RIGHT_RE.match(sentence[nxt.end:]))
            second_ok = _is_strong(nxt) or bool(_PER_SHARE_RIGHT_RE.match(sentence[nxt.end:]))
            if sep_ok and not transition and first_ok and second_ok and not nxt.bps:
                joined = True
        if joined:
            used.add(i + 1)
            lo_a, hi_a = a, nxt
            flags: list[str] = []
            pct = lo_a.is_pct or hi_a.is_pct
            cur = hi_a.currency or lo_a.currency
            if lo_a.currency and hi_a.currency and lo_a.currency != hi_a.currency:
                flags.append("currency_ambiguous")
            lo_scale, hi_scale = lo_a.scale, hi_a.scale
            if lo_scale is None and hi_scale is not None and not pct and (lo_a.has_cur or hi_a.has_cur):
                lo_scale = hi_scale  # "$1.20 to $1.25 billion": 스케일 공유
            if hi_scale is None and lo_scale is not None and not pct:
                hi_scale = lo_scale
            scale_status = "explicit" if (lo_scale or hi_scale) else "not_needed"
            lo_v = lo_a.value * (lo_scale or Decimal(1)) if not pct else lo_a.value
            hi_v = hi_a.value * (hi_scale or Decimal(1)) if not pct else hi_a.value
            if lo_v > hi_v:
                flags.append("range_order_suspicious")
            cands.append(_Cand(lo_v, hi_v, "range", a.start, nxt.end, pct, cur, scale_status,
                               bool(_PER_SHARE_RIGHT_RE.match(sentence[nxt.end:])),
                               lo_a.negative or hi_a.negative, flags))
            continue
        if not _is_strong(a) and not _PER_SHARE_RIGHT_RE.match(right):
            continue  # 연도·일자 같은 단독 맨숫자는 후보가 아니다
        left = sentence[max(0, a.start - 30):a.start]
        shape = "point"
        if re.search(r"(?:at least|no less than|not less than|greater than|more than|in excess of|minimum of|over)\s*(?:approximately\s*|about\s*)?$", left, re.I):
            shape = "lower_bound"
        elif re.search(r"(?:up to|no more than|not more than|at most|less than|under|below|maximum of)\s*(?:approximately\s*|about\s*)?$", left, re.I):
            shape = "upper_bound"
        scale_status = "explicit" if a.scale else "not_needed"
        value = a.value if a.is_pct else a.value * (a.scale or Decimal(1))
        cands.append(_Cand(value, value, shape, a.start, a.end, a.is_pct, a.currency, scale_status,
                           bool(_PER_SHARE_RIGHT_RE.match(right)), a.negative, []))
    return cands


def _apply_scale_hint(c: _Cand, scale_hint: Optional[str]) -> None:
    if c.scale_status == "explicit" or c.unit_pct or c.per_share:
        return
    if scale_hint:
        mult = _SCALES[_TABLE_SCALES[scale_hint]]
        c.low, c.high = c.low * mult, c.high * mult
        c.scale_status = "table_header"


def _choose_period(periods: list[PeriodMatch], cand_start: int, context_period: Optional[PeriodMatch]) -> Optional[PeriodMatch]:
    left = [p for p in periods if p.end <= cand_start]
    if left:
        return left[-1]
    right = [p for p in periods if p.start >= cand_start]
    if right:
        return right[0]
    return context_period


def _clip(text: str, n: int = 600) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _sentence_items(
    sentence: str,
    *,
    scale_hint: Optional[str],
    context_period: Optional[PeriodMatch],
    section_active: bool,
    meta: dict,
    anchor_prefix: str = "",
) -> tuple[list[GuidanceItem], list[SkippedCandidate], bool]:
    """문장 1개(표는 행 1개)에서 가이던스 item 을 추출한다. 반환: (items, skipped, guidance_language)."""
    items: list[GuidanceItem] = []
    skipped: list[SkippedCandidate] = []
    anchor = _clip(anchor_prefix + sentence)
    if _DISCLAIMER_RE.search(sentence):
        return items, skipped, False
    cue = bool(_CUE_RE.search(sentence))
    if not cue and not section_active:
        return items, skipped, False

    action = _detect_action(sentence)
    periods = find_periods(sentence)

    # 철회 문장: 수치 없이 가이던스를 중단한다는 진술
    if action == "withdraw" and not re.search(r"\bnot\s+withdr|\bno\s+obligation", sentence, re.I):
        p = periods[0] if periods else context_period
        items.append(GuidanceItem(
            meta.get("cik"), meta.get("accession"), meta.get("acceptance_utc"), meta.get("source_url"),
            "all", "unspecified", p.key if p else None, p.raw if p else None, "withdrawn", None, None, None, None,
            anchor, () if p and p.key else ("period_unresolved",), "withdraw"))
        return items, skipped, True

    cands = _build_candidates(sentence, scale_hint)
    language = bool(cands) or (cue and _has_metric_and_number(sentence))
    prev_end = 0
    last_metric: Optional[str] = None
    resolved: list[tuple[_Cand, str, str, bool, Optional[PeriodMatch], list[str]]] = []
    priors: list[tuple[str, tuple[Decimal, Decimal]]] = []
    for c in cands:
        left = sentence[prev_end:c.start]
        right = sentence[c.end:]
        prev_end = c.end
        prior = _is_prior_reference(left, sentence[:c.start], right)
        metric = _detect_metric(left[-80:], right)
        if metric is None and last_metric is not None and re.fullmatch(
                r"[\s,;]*(?:(?:to|and|or|from|of|at|approximately|about|around)[\s,;]*)*", left, re.I):
            metric = last_metric  # "raises outlook from $4.7 billion to $4.9 billion": 연결어만 있으면 앞 지표를 잇는다
        if metric is None:
            continue  # 지표를 알 수 없는 숫자(예: 전년 대비 %)는 기록하지 않는다
        last_metric = metric
        if c.unit_pct and metric == "revenue":
            metric = "revenue_growth" if _GROWTH_WORDS_RE.search(left[-40:] + " " + right[:30]) else "revenue"
        problems: list[str] = list(c.flags)
        # 단위 정합성
        if metric == "eps":
            if c.unit_pct or c.scale_status == "explicit":
                skipped.append(SkippedCandidate(anchor, "eps_unit_mismatch"))
                continue
        elif metric in _CURRENCY_METRICS:
            if c.unit_pct and metric == "revenue":
                skipped.append(SkippedCandidate(anchor, "percent_without_growth_context"))
                continue
            if c.unit_pct or c.per_share:
                skipped.append(SkippedCandidate(anchor, f"{metric}_unit_mismatch"))
                continue
        elif metric in _PERCENT_METRICS:
            if not c.unit_pct:
                skipped.append(SkippedCandidate(anchor, f"{metric}_needs_percent"))
                continue
        if prior:
            priors.append((metric, (c.low, c.high)))
            continue
        if metric in _CURRENCY_METRICS:
            _apply_scale_hint(c, scale_hint)
        if metric in _CURRENCY_METRICS and c.scale_status not in {"explicit", "table_header"}:
            problems.append("scale_ambiguous")
        if metric in {"eps", "operating_income", "ebitda"} and not c.negative_explicit and \
                re.search(r"\blosse?s?\b", left[-40:] + " " + right[:25], re.I):
            problems.append("sign_ambiguous")
        basis = _detect_basis(metric, left[-80:] + " " + right[:40])
        period = _choose_period(periods, c.start, context_period)
        resolved.append((c, metric, basis, c.negative_explicit, period, problems))
    # 같은 (metric, period)에 서로 다른 새 값이 둘 이상이면 새 값을 특정할 수 없다
    groups: dict[tuple, list] = {}
    for entry in resolved:
        c, metric, basis, _neg, period, _pr = entry
        groups.setdefault((metric, basis, period.key if period else None), []).append(entry)
    for key, entries in groups.items():
        distinct = {(e[0].low, e[0].high, e[0].shape) for e in entries}
        if len(distinct) > 1:
            skipped.append(SkippedCandidate(anchor, "multiple_candidates_same_metric_period"))
            continue
        c, metric, basis, _neg, period, problems = entries[0]
        flags = list(problems)
        if period is not None and period.key is None:
            flags.append(period.reason or "period_unresolved")
        elif period is None:
            flags.append("period_missing")
        prior_match = next((v for (m, v) in priors if m == metric), None)
        unit = "percent" if metric in _PERCENT_METRICS else ("per_share" if metric == "eps" else "currency")
        items.append(GuidanceItem(
            meta.get("cik"), meta.get("accession"), meta.get("acceptance_utc"), meta.get("source_url"),
            metric, basis, period.key if period else None, period.raw if period else None, c.shape,
            None if c.shape == "upper_bound" else c.low, None if c.shape == "lower_bound" else c.high,
            unit, None if unit == "percent" else c.currency, anchor, tuple(dict.fromkeys(flags)), action,
            prior_match))
    if not items and not skipped and priors:
        skipped.append(SkippedCandidate(anchor, "ignored:prior_or_actual_reference_only"))
    elif not items and not skipped and language and cue:
        skipped.append(SkippedCandidate(anchor, "guidance_language_without_parsable_values"))
    return items, skipped, language


_HEADING_VERB_RE = re.compile(
    r"\b(?:expect\w*|anticipat\w+|withdr\w+|rais\w+|lower\w+|provid\w+|reaffirm\w*|updat\w+|suspend\w*|is|are|will|has|have|"
    r"we|the company)\b", re.I)


def _looks_like_heading(line: str) -> bool:
    """'Fourth Quarter Fiscal 2026 Outlook' 같은 짧은 제목 줄. 문장(동사·마침표)은 제목으로 보지 않는다."""
    return (len(line) <= 120 and bool(_HEADING_RE.search(line)) and not line.endswith(".")
            and not _HEADING_VERB_RE.search(line)
            and not re.search(r"\d[\d,]*\.?\d*\s*(?:%|million|billion)", line, re.I))


def extract_guidance(
    text: str,
    *,
    cik: Optional[str] = None,
    accession: Optional[str] = None,
    acceptance_utc: Optional[datetime] = None,
    source_url: Optional[str] = None,
) -> ExtractionResult:
    """보도자료 텍스트에서 발행사 가이던스를 규칙으로 추출한다(LLM 없음, 순수 함수).

    문장은 예상·전망 표현(expects/outlook/guidance 등)이 있어야 하고, 실적 참조("exceeded the high end")나
    직전 값("from", "compared to prior")은 새 가이던스로 세지 않는다. 표는 Outlook/Guidance 제목 아래의
    행만 본다. 못 읽은 후보는 skipped 에 이유와 함께 남긴다.
    """
    meta = {"cik": _pad_cik(cik) if cik else None, "accession": accession,
            "acceptance_utc": acceptance_utc, "source_url": source_url}
    result = ExtractionResult()
    lines = [ln.strip() for ln in normalize_text(text).split("\n") if ln.strip()]
    scale_hint: Optional[str] = None
    hint_line = -10**6
    section_until = -1
    context_period: Optional[PeriodMatch] = None
    header_periods: list[PeriodMatch] = []
    heading_text = ""
    language_seen = False

    for idx, line in enumerate(lines):
        m = _TABLE_SCALE_RE.search(line)
        if m:
            scale_hint, hint_line = m.group(1).lower(), idx
        elif idx - hint_line > 30:
            scale_hint = None
        is_table = " | " in line
        if not is_table and _looks_like_heading(line):
            section_until = idx + 25
            heading_text = line
            pers = [p for p in find_periods(line)]
            context_period = pers[0] if pers else None
            header_periods = []
            if not m:
                scale_hint = None
            continue
        section_active = idx <= section_until
        if is_table:
            if not section_active:
                continue
            cells = [c.strip() for c in line.split(" | ")]
            if not any(_has_metric_and_number(c) for c in cells):
                row_periods = [p for c in cells for p in find_periods(c)[:1]]
                if row_periods:  # 열 제목 행(기간만 있는 행)
                    header_periods = row_periods
                continue
            if not _has_metric_and_number(cells[0]):
                continue
            label, rest = cells[0], cells[1:]
            row_text = label + " " + " ".join(rest)
            prefix = f"[{_clip(heading_text, 100)}] "
            if len(header_periods) > 1:
                cands = _build_candidates(row_text, scale_hint)
                if len(cands) == len(header_periods):  # 열마다 값 하나씩: 순서대로 기간을 붙인다
                    for col_period, c in zip(header_periods, cands):
                        its, sk, lang = _sentence_items(
                            label + " " + row_text[c.start:c.end], scale_hint=scale_hint, context_period=col_period,
                            section_active=True, meta=meta, anchor_prefix=f"{prefix}{col_period.raw}: ")
                        result.items.extend(its), result.skipped.extend(sk)
                        language_seen = language_seen or lang
                    continue
                ctx = None  # 열 수와 값 수가 안 맞으면 어느 열인지 추측하지 않는다
            else:
                ctx = header_periods[0] if header_periods else context_period
            its, sk, lang = _sentence_items(
                row_text, scale_hint=scale_hint, context_period=ctx, section_active=True, meta=meta,
                anchor_prefix=prefix)
            result.items.extend(its), result.skipped.extend(sk)
            language_seen = language_seen or lang
            continue
        if section_active and len(line) <= 80 and not line.endswith(".") and not _has_metric_and_number(line):
            pers = find_periods(line)
            if pers:  # 표 안의 기간 소제목 한 줄("Third Quarter Fiscal 2026")
                context_period, header_periods = pers[0], []
                continue
        for sentence in _split_sentences(line):
            its, sk, lang = _sentence_items(
                sentence, scale_hint=scale_hint, context_period=context_period if section_active else None,
                section_active=section_active, meta=meta)
            result.items.extend(its), result.skipped.extend(sk)
            language_seen = language_seen or lang

    if result.items:
        result.status = "guidance_found"
    elif any(not sk.reason.startswith("ignored:") for sk in result.skipped) or language_seen:
        result.status = "guidance_language_unparsed"
    else:
        result.status = "no_guidance_language"
    return result


# ---------------------------------------------------------------------------
# 7. 변화 분류 (순수 함수)
# ---------------------------------------------------------------------------

CHANGE_LABELS = ("raised", "lowered", "maintained", "initiated", "withdrawn", "unknown")

# 비교 정책(스펙 3절 '비교 정책', 2026-09-25 사전 문서화 후 구현). 방향 판정(raised/lowered/maintained)은
# **연간(회계연도) 가이던스를 같은 연도끼리** 비교할 때만 낸다. 분기·반기 가이던스는 매 발표가 새 기간을 가리키므로
# 같은 기간의 직전 값이 없고, 다른 기간끼리(예: Q3 가이던스 vs Q2 가이던스)의 비교는 계절성·성장에 오염되므로
# 방향을 만들지 않는다(unknown + quarterly_not_comparable). 이 정책은 수익 데이터를 보기 전에 고정했다.
COMPARISON_POLICY = "annual_same_fy_v1"
COMPARISON_ANNUAL_SAME_FY = "annual_same_fy"
COMPARISON_ISSUER_STATEMENT = "issuer_statement"
COMPARISON_COMPLETE_HISTORY = "complete_history"
COMPARISON_NONE = "not_compared"

PERIOD_ANNUAL = "annual"
PERIOD_QUARTERLY = "quarterly"
PERIOD_HALF = "half_year"
PERIOD_OTHER = "other"

_ANNUAL_KEY_RE = re.compile(r"^(?P<fam>FY|CY)(?P<yr>\d{4})$")
_ANNUAL_YEND_RE = re.compile(r"^YEND:(?P<yr>\d{4})-\d{2}-\d{2}$")
_QUARTER_KEY_RE = re.compile(r"^(?:(?:FY|CY)\d{4}Q[1-4]|QEND:\d{4}-\d{2}-\d{2})$")
_HALF_KEY_RE = re.compile(r"^(?:FY|CY)\d{4}H[12]$")


def period_type(period_key: Optional[str]) -> Optional[str]:
    """정규화된 period_key 의 기간 종류. annual(FY2026·CY2026·YEND:2026-12-31) / quarterly(FY2026Q3·QEND:...) /
    half_year(FY2026H2) / other(PEND 등). None 이면 기간 미확정."""
    if not period_key:
        return None
    if _ANNUAL_KEY_RE.match(period_key) or _ANNUAL_YEND_RE.match(period_key):
        return PERIOD_ANNUAL
    if _QUARTER_KEY_RE.match(period_key):
        return PERIOD_QUARTERLY
    if _HALF_KEY_RE.match(period_key):
        return PERIOD_HALF
    return PERIOD_OTHER


def _annual_year(period_key: Optional[str]) -> Optional[tuple[str, int]]:
    """연간 period_key -> (표기 계열, 연도). 계열(FY/CY/YEND)이 다르면 서로 비교하지 않는다."""
    if not period_key:
        return None
    m = _ANNUAL_KEY_RE.match(period_key)
    if m:
        return m.group("fam"), int(m.group("yr"))
    m = _ANNUAL_YEND_RE.match(period_key)
    if m:
        return "YEND", int(m.group("yr"))
    return None


_NOT_COMPARABLE_REASON = {
    PERIOD_QUARTERLY: "quarterly_not_comparable",
    PERIOD_HALF: "half_year_not_comparable",
    PERIOD_OTHER: "period_type_not_comparable",
}


@dataclass(frozen=True)
class GuidanceChange:
    change: str  # CHANGE_LABELS 중 하나
    reason: str  # 판정 근거/unknown 이유 코드(기존 코드 유지 — guidance_shadow 가 그대로 쓴다)
    current: GuidanceItem
    previous: Optional[GuidanceItem] = None
    mid_change: Optional[Decimal] = None  # mid_new - mid_old (같은 단위)
    mid_change_pct: Optional[Decimal] = None  # mid_change / |mid_old| * 100 (mid_old != 0)
    width_old: Optional[Decimal] = None
    width_new: Optional[Decimal] = None
    flags: tuple[str, ...] = ()
    # --- 2026-09-25 추가(추가만, 기존 필드 의미 불변) ---
    reason_detail: Optional[str] = None  # 세분화된 사유(no_prior_same_fy, quarterly_not_comparable, unit_mismatch ...)
    comparison_method: Optional[str] = None  # annual_same_fy / issuer_statement / complete_history / not_compared
    period_type: Optional[str] = None  # annual / quarterly / half_year / other / None(미확정)
    policy: Optional[str] = None  # 판정에 쓴 비교 정책 버전(COMPARISON_POLICY)

    # 판정 근거: 비교에 실제로 쓴 직전 항목. 비교하지 않았으면 None.
    @property
    def previous_accession(self) -> Optional[str]:
        return self.previous.accession if self.previous is not None else None

    @property
    def previous_acceptance_utc(self) -> Optional[datetime]:
        return self.previous.acceptance_utc if self.previous is not None else None

    @property
    def previous_period_key(self) -> Optional[str]:
        return self.previous.period_key if self.previous is not None else None

    def evidence(self) -> dict:
        """판정 근거 요약(직렬화 가능한 dict). 원문 anchor 는 current/previous 레코드에 있다."""
        prev_at = self.previous_acceptance_utc
        return {
            "policy": self.policy,
            "comparison_method": self.comparison_method,
            "period_type": self.period_type,
            "reason": self.reason,
            "reason_detail": self.reason_detail or self.reason,
            "current_accession": self.current.accession,
            "current_period_key": self.current.period_key,
            "previous_accession": self.previous_accession,
            "previous_acceptance_utc": prev_at.isoformat() if prev_at else None,
            "previous_period_key": self.previous_period_key,
        }


def _basis_class(item: GuidanceItem) -> str:
    if item.metric == "revenue":
        return "non_gaap" if item.basis == "non_gaap" else "reported"
    return item.basis


def _reference(item: GuidanceItem) -> Optional[Decimal]:
    return item.midpoint


def _width(item: GuidanceItem) -> Optional[Decimal]:
    if item.shape == "range" and item.low is not None and item.high is not None:
        return item.high - item.low
    return Decimal(0) if item.shape == "point" else None


def _unknown(current, previous, reason, flags=(), *, detail=None, ptype=None) -> GuidanceChange:
    return GuidanceChange("unknown", reason, current, previous, flags=tuple(flags), reason_detail=detail or reason,
                          comparison_method=COMPARISON_NONE, period_type=ptype, policy=COMPARISON_POLICY)


def find_previous_guidance(current: GuidanceItem, history: Sequence[GuidanceItem]) -> Optional[GuidanceItem]:
    """같은 기업·metric·basis·대상 기간이고 acceptance 시각이 더 이른 가이던스 중 가장 최근 것."""
    if current.acceptance_utc is None or current.period_key is None:
        return None
    best: Optional[GuidanceItem] = None
    for h in history:
        if h.accession is not None and h.accession == current.accession:
            continue
        if h.cik != current.cik or h.metric != current.metric or _basis_class(h) != _basis_class(current):
            continue
        if h.acceptance_utc is None or h.acceptance_utc >= current.acceptance_utc:
            continue
        if h.shape != "withdrawn" and h.period_key != current.period_key:
            continue
        if h.shape == "withdrawn":
            continue
        if best is None or h.acceptance_utc > best.acceptance_utc:
            best = h
    return best


def compare_guidance(
    current: GuidanceItem,
    previous: Optional[GuidanceItem],
    *,
    history_complete: bool = False,
) -> GuidanceChange:
    """현재 가이던스를 직전 발행사 가이던스와 비교해 change 를 분류한다(정책 COMPARISON_POLICY).

    - 방향(raised/lowered/maintained)은 연간 가이던스를 같은 회계연도(period_key 동일)의 직전 발표와 비교할
      때만 낸다(comparison_method='annual_same_fy').
    - 분기·반기 등 연간이 아닌 기간은 직전 값이 있어도 방향을 내지 않는다(unknown, quarterly_not_comparable 등).
    - previous 는 같은 기업·metric·basis·대상 기간이어야 한다. 다르면 unknown 이다. previous 가 None 이고
      history_complete 가 False 면 '직전 가이던스가 없었음'을 확인할 수 없어 unknown 이다(발행사가 최초
      가이던스임을 밝힌 경우 제외). 연간 항목의 이 경우 세부 사유는 no_prior_same_fy 다.
    - 철회(withdrawn)는 비교가 아니라 발행사 진술이므로 기간 종류와 무관하게 withdrawn 이다.
    """
    ptype = period_type(current.period_key)
    if current.shape == "withdrawn":
        return GuidanceChange("withdrawn", "issuer_withdrew_guidance", current, previous,
                              reason_detail="issuer_withdrew_guidance", comparison_method=COMPARISON_ISSUER_STATEMENT,
                              period_type=ptype, policy=COMPARISON_POLICY)
    if current.problems:
        return _unknown(current, previous, "current_not_comparable:" + ",".join(current.problems), ptype=ptype)
    if ptype != PERIOD_ANNUAL:
        code = _NOT_COMPARABLE_REASON.get(ptype, "period_type_not_comparable")
        flags = ("same_period_previous_available",) if previous is not None else ()
        # 비교에 쓰지 않은 직전 항목은 근거로 남기지 않는다(previous=None) — 쓰지 않은 값을 근거처럼 보이지 않게.
        return _unknown(current, None, code, flags, ptype=ptype)
    if previous is None:
        if history_complete:
            return GuidanceChange("initiated", "no_previous_guidance_in_complete_history", current,
                                  reason_detail="no_previous_guidance_in_complete_history",
                                  comparison_method=COMPARISON_COMPLETE_HISTORY, period_type=ptype,
                                  policy=COMPARISON_POLICY)
        if current.stated_action == "initiate":
            return GuidanceChange("initiated", "issuer_stated_initial_guidance", current,
                                  reason_detail="issuer_stated_initial_guidance",
                                  comparison_method=COMPARISON_ISSUER_STATEMENT, period_type=ptype,
                                  policy=COMPARISON_POLICY)
        return _unknown(current, None, "no_previous_in_retrieved_history", detail="no_prior_same_fy", ptype=ptype)
    if previous.shape == "withdrawn":
        return GuidanceChange("initiated", "reinstated_after_withdrawal", current, previous,
                              reason_detail="reinstated_after_withdrawal",
                              comparison_method=COMPARISON_ISSUER_STATEMENT, period_type=ptype,
                              policy=COMPARISON_POLICY)
    if previous.problems:
        return _unknown(current, previous, "previous_not_comparable:" + ",".join(previous.problems), ptype=ptype)
    if previous.cik != current.cik:
        return _unknown(current, previous, "different_company", ptype=ptype)
    if previous.metric != current.metric:
        return _unknown(current, previous, "different_metric", ptype=ptype)
    if _basis_class(previous) != _basis_class(current):
        return _unknown(current, previous, "basis_mismatch", ptype=ptype)
    if previous.period_key != current.period_key:
        return _unknown(current, previous, "different_period", ptype=ptype)
    if previous.unit != current.unit:
        return _unknown(current, previous, "unit_or_currency_mismatch", detail="unit_mismatch", ptype=ptype)
    if previous.currency != current.currency:
        return _unknown(current, previous, "unit_or_currency_mismatch", detail="currency_mismatch", ptype=ptype)
    if previous.acceptance_utc is None or current.acceptance_utc is None \
            or previous.acceptance_utc >= current.acceptance_utc:
        return _unknown(current, previous, "previous_not_before_current", ptype=ptype)
    bounds = {"lower_bound", "upper_bound"}
    if (previous.shape in bounds or current.shape in bounds) and previous.shape != current.shape and \
            not ({previous.shape, current.shape} <= {"range", "point"}):
        return _unknown(current, previous, "bound_type_mismatch", ptype=ptype)
    mid_new, mid_old = _reference(current), _reference(previous)
    if mid_new is None or mid_old is None:
        return _unknown(current, previous, "missing_values", ptype=ptype)

    flags: list[str] = []
    delta = mid_new - mid_old
    pct = (delta / abs(mid_old) * 100) if mid_old != 0 else None
    if current.low is not None and previous.low is not None and current.high is not None and previous.high is not None:
        low_d, high_d = current.low - previous.low, current.high - previous.high
        if (low_d > 0 and high_d < 0) or (low_d < 0 and high_d > 0):
            flags.append("mixed_direction")
        if delta == 0 and (low_d != 0 or high_d != 0):
            flags.append("width_changed")
        same_bounds = low_d == 0 and high_d == 0
    else:
        same_bounds = delta == 0
    if delta > 0:
        label = "raised"
    elif delta < 0:
        label = "lowered"
    else:
        label = "maintained" if (same_bounds or "width_changed" in flags) else "unknown"

    stated = current.stated_action
    if stated in {"raise", "lower", "maintain"}:
        expected = {"raise": "raised", "lower": "lowered", "maintain": "maintained"}[stated]
        if expected != label:
            code = f"issuer_wording_conflicts_with_computed:{stated}->{label}"
            return GuidanceChange("unknown", code, current, previous, delta, pct, _width(previous), _width(current),
                                  tuple(flags) + ("stated_action_conflict",), reason_detail=code,
                                  comparison_method=COMPARISON_ANNUAL_SAME_FY, period_type=ptype,
                                  policy=COMPARISON_POLICY)
    return GuidanceChange(label, "midpoint_comparison", current, previous, delta, pct, _width(previous),
                          _width(current), tuple(flags), reason_detail="midpoint_comparison",
                          comparison_method=COMPARISON_ANNUAL_SAME_FY, period_type=ptype, policy=COMPARISON_POLICY)


def _superseded_annual(current: GuidanceItem, release_items: Sequence[GuidanceItem]) -> Optional[GuidanceItem]:
    """같은 발표 안에 같은 metric·basis 의 **바로 다음 연도** 연간 항목이 있으면 그 항목을 돌려준다.

    회사는 진행 중인(또는 다음) 회계연도를 가이던스한다. 같은 보도자료에서 FY2027 가이던스와 FY2026 수치가 함께
    나오면 FY2026 쪽은 끝난 연도의 실적·비교열일 가능성이 커서, 이를 직전 FY2026 가이던스와 비교하면 '실적 대
    가이던스'가 방향으로 오염된다(실제 표본: CSCO 8월 발표의 FY2027 가이던스 표 안 FY2026 실적 행).
    """
    cur = _annual_year(current.period_key)
    if cur is None:
        return None
    for other in release_items:
        if other is current or other.problems or other.shape == "withdrawn":
            continue
        if other.cik != current.cik or other.metric != current.metric or _basis_class(other) != _basis_class(current):
            continue
        if other.accession != current.accession:
            continue
        oth = _annual_year(other.period_key)
        # 바로 다음 연도(+1)만 본다. +2 이상은 장기 목표(예: CRM 의 FY2030 매출 목표)일 수 있어 근거로 쓰지 않는다.
        if oth is not None and oth[0] == cur[0] and oth[1] == cur[1] + 1:
            return other
    return None


def compute_guidance_changes(
    current_items: Sequence[GuidanceItem],
    history: Sequence[GuidanceItem],
    *,
    history_complete: bool = False,
) -> list[GuidanceChange]:
    """현재 발표의 각 item 을 history 의 직전 가이던스와 비교한다(정책 COMPARISON_POLICY).

    같은 발표에 바로 다음 연도의 연간 항목이 함께 있는 연간 항목은 끝난 연도의 실적·비교열로 보고 비교하지 않는다
    (unknown, annual_period_superseded_in_release).
    """
    out: list[GuidanceChange] = []
    for c in current_items:
        later = _superseded_annual(c, current_items) if c.shape != "withdrawn" and not c.problems else None
        if later is not None:
            out.append(_unknown(c, None, "annual_period_superseded_in_release",
                                (f"later_fy_in_release:{later.period_key}",), ptype=PERIOD_ANNUAL))
            continue
        out.append(compare_guidance(c, find_previous_guidance(c, history), history_complete=history_complete))
    return out


def extract_from_filing(client: SecEdgarClient, filing: EarningsFiling) -> tuple[Optional[PressRelease], ExtractionResult]:
    """filing 의 보도자료를 받아 가이던스를 추출한다(네트워크 필요)."""
    release = fetch_press_release(client, filing)
    if release is None:
        return None, ExtractionResult(status="no_guidance_language")
    result = extract_guidance(release.text, cik=filing.cik, accession=filing.accession,
                              acceptance_utc=filing.acceptance_utc, source_url=release.document_url)
    return release, result
