"""RES-02: 정보 예산과 중복 라우터 — 원문 중복 제거·정보 비용 집계 유틸리티 (2026-09-22, 순수 관측 인프라).

목적: docs/INFORMATION_DECISION_ENGINE_RESEARCH.md RES-02("여러 기사를 여러 독립 근거로 세지 않는다")를 위한
최소 유틸리티. 이 모듈은 주문 경로(core.paper_execution, scripts/champion_paper_trade.py)나 스케줄러, DB를
전혀 건드리지 않는다. core.candidate_ledger / core.earnings_events / core.filing_changes 는 **읽기만** 하며
수정하지 않는다 — 이 세 모듈이 이미 정의한 필드명·해시 방식에 맞춰 값을 만들어 줄 뿐이다.

이 모듈이 하는 일 4가지
1. compute_event_id: 같은 사건(같은 accession 등)을 가리키는 서로 다른 호출이 항상 같은 문자열을 내도록 하는
   결정적 ID.
2. content_hash: core.earnings_events.PressRelease.content_sha256 / core.filing_changes.FilingChangeEvent.
   current_doc_sha256·prior_doc_sha256 와 **정확히 같은 해시 값**을 내는 함수. 아래 "해시 규칙" 절 참고.
3. dedup_by_content: 같은 content_hash 를 가진 레코드를 대표 하나로 묶고 나머지를 duplicate_of 로 표시.
4. InfoCostTracker / summarize_extraction_quality: 호출 수·캐시 적중·원문 도달률·핵심필드 추출 성공률을
   정직하게 집계한다(투자 성과가 아니라 연구 도구 효율 지표).

## 해시 규칙 (기존 모듈과 반드시 일치)
core/earnings_events.py 의 ``SecDocument.content_sha256`` 과 core/filing_changes.py 의
``FilingChangeEvent.current_doc_sha256``/``prior_doc_sha256`` 은 둘 다 **잘라내지 않은 sha256 hexdigest(64자)**
를 쓴다(``hashlib.sha256(...).hexdigest()``, 앞 16자로 자르는 규칙은 이 저장소 어디에도 없다 — 캐시 파일명에
쓰는 ``hashlib.sha1(url).hexdigest()[:16]`` 은 URL 캐시 키이지 content hash 가 아니며 알고리즘도 다르다(SHA1)).
이 모듈의 ``content_hash()`` 는 두 기존 함수와 다른 규칙을 새로 만들지 않기 위해 **똑같이 잘리지 않은 sha256
hexdigest** 를 반환한다. 구체적으로 core.filing_changes 의 ``hashlib.sha256(text.encode("utf-8", "replace"))
.hexdigest()`` 와 바이트 단위로 동일한 공식을 쓰며, core.earnings_events 는 같은 공식을 raw HTTP 바이트에
적용하므로(``hashlib.sha256(raw).hexdigest()``, ``raw`` 는 ``_decode(raw)`` 로 만든 텍스트의 원본 바이트) 유효한
UTF-8 본문이면 텍스트를 다시 UTF-8 로 인코딩해도 같은 바이트 → 같은 해시가 된다(그 모듈이 cp1252 로 폴백한
드문 경우는 원문 바이트를 알지 못하는 한 재현할 수 없다 — 이는 이 모듈의 한계가 아니라 원본 인코딩이 손실된
경우의 일반적 한계다).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

# ---------------------------------------------------------------------------
# 1. event_id — 같은 사건을 가리키는 서로 다른 호출이 항상 같은 문자열을 내도록
# ---------------------------------------------------------------------------

# SEC accession number: 10자리 CIK-2자리 연도-6자리 일련번호. 대시가 있든 없든(nodash, URL 경로에서 흔함)
# 같은 사건이므로 정규화해 항상 대시 있는 정규형으로 비교한다(core.earnings_events.EarningsFiling.accession,
# core.filing_changes.FilingRecord.accession 은 대시 있는 형태를 쓴다; *_nodash 프로퍼티가 대시 없는 형태다).
_ACCESSION_RE = re.compile(r"^(\d{10})-?(\d{2})-?(\d{6})$")

EVENT_ID_PREFIX = "evt_"
EVENT_ID_HASH_LEN = 24  # core.candidate_ledger.compute_candidate_set_id 의 "prefix_" + sha256 앞 N자 관례와 동일 길이


def _normalize_doc_id(value: Any) -> str:
    """accession 이면 대시 유무와 무관하게 정규형(대시 있는 형태)으로, 아니면 trim 만 한다.

    URL·제목 대소문자는 의미가 있을 수 있어(예: S3 경로) 바꾸지 않는다.
    """
    s = str(value or "").strip()
    m = _ACCESSION_RE.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return s


def compute_event_id(source: str, doc_id_or_accession: str, ticker: str, form_or_type: str) -> str:
    """결정적 event_id. 같은 (source, accession/문서ID, ticker, form/type)을 가리키는 서로 다른 호출은
    공백·대소문자·accession 대시 표기 차이와 무관하게 항상 같은 문자열을 반환한다.

    - source, form_or_type: trim 후 소문자로 정규화(예: "SEC_EDGAR" == "sec_edgar", "8-K" == "8-k").
    - ticker: trim 후 대문자로 정규화.
    - doc_id_or_accession: accession 형식이면 대시 정규형으로, 아니면 trim 만(대소문자 보존).

    같은 accession 이라도 ticker 나 form 이 다르게 전달되면(호출부 실수) 다른 event_id 가 나온다 —
    이 함수는 입력 일관성을 검증하지 않는다. 호출부가 같은 사건에 항상 같은 4개 값을 넘겨야 한다.
    """
    key = {
        "source": str(source or "").strip().lower(),
        "doc_id": _normalize_doc_id(doc_id_or_accession),
        "ticker": str(ticker or "").strip().upper(),
        "form_or_type": str(form_or_type or "").strip().lower(),
    }
    canonical = json.dumps(key, sort_keys=True, ensure_ascii=False)
    return EVENT_ID_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:EVENT_ID_HASH_LEN]


# ---------------------------------------------------------------------------
# 2. content_hash — core.earnings_events / core.filing_changes 와 동일한 해시
# ---------------------------------------------------------------------------


def content_hash(text: str) -> str:
    """sha256 hexdigest(64자, 잘라내지 않음). core.filing_changes.build_filing_change_event 의
    ``hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()`` 와 바이트 단위로 동일한 공식이며,
    core.earnings_events.SecEdgarClient.get() 이 HTTP 원문 바이트에 적용하는 ``hashlib.sha256(raw).hexdigest()``
    와도 유효한 UTF-8 본문에서는 같은 값을 낸다(모듈 docstring의 "해시 규칙" 절 참고).

    빈 문자열/None 은 빈 바이트열의 해시를 낸다(예외를 던지지 않는다 — 결측을 조용히 다른 값으로 바꾸지 않되,
    호출부가 결측을 먼저 걸러야 한다는 뜻으로 그대로 통과시킨다).
    """
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


# ---------------------------------------------------------------------------
# 3. dedup_by_content — 같은 content_hash 를 대표 하나로 묶는다
# ---------------------------------------------------------------------------


def dedup_by_content(
    records: Sequence[dict],
    *,
    hash_field: str = "content_hash",
    id_field: str = "event_id",
) -> list[dict]:
    """같은 ``hash_field`` 값을 가진 레코드를 그룹의 첫 등장 레코드를 대표로 묶고, 나머지에
    ``duplicate_of``(대표의 ``id_field`` 값, 없으면 ``"idx:<원본 위치>"``)와 ``is_duplicate=True`` 를 채운다.

    - 원본 ``records`` 는 바꾸지 않는다(각 원소를 얕은 복사한 새 dict 리스트를 반환).
    - ``hash_field`` 값이 없거나 빈 문자열인 레코드는 비교 불가로 보고 항상 대표로 남긴다
      (``duplicate_of=None``) — 해시가 없다고 다른 레코드와 조용히 묶지 않는다.
    - 목적: "여러 기사(서로 다른 URL이지만 같은 보도자료를 전재)"가 "여러 독립 근거"로 잘못 세어지지
      않게 한다(RES-02). 이 함수는 대표가 어떤 레코드인지 정하는 정책(최신순 등)을 갖지 않는다 —
      단순히 records 순서상 먼저 나온 것을 대표로 삼는다. 순서에 의미를 주려면 호출 전에 정렬하라.
    """
    out: list[dict] = []
    first_seen: dict[str, tuple[int, dict]] = {}
    for i, r in enumerate(records):
        rec = dict(r)
        h = rec.get(hash_field)
        if not h:
            rec["duplicate_of"] = None
            rec["is_duplicate"] = False
            out.append(rec)
            continue
        if h not in first_seen:
            first_seen[h] = (i, rec)
            rec["duplicate_of"] = None
            rec["is_duplicate"] = False
        else:
            rep_idx, rep_rec = first_seen[h]
            rep_id = rep_rec.get(id_field) or f"idx:{rep_idx}"
            rec["duplicate_of"] = rep_id
            rec["is_duplicate"] = True
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# 4. InfoCostTracker — 호출 수 · 캐시 적중률 · 처리 시간 (실제 비용 계산 없음)
# ---------------------------------------------------------------------------


@dataclass
class _SourceStats:
    calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    errors: int = 0
    total_seconds: float = 0.0


class InfoCostTracker:
    """소스별(예: "sec_edgar", "news") API 호출 수·캐시 적중·처리 시간을 누적 집계한다.

    **하지 않는 것(정직하게 명시):** 이 프로젝트에는 아직 유료 정보 API가 없다(SEC EDGAR 는 무료 공개
    API이고, 뉴스 V1은 metadata-only 무료 소스만 쓴다 — docs/NEWS_RESEARCH_V1_V2.md). 따라서 이 클래스는
    달러/원화 비용이나 LLM 토큰 비용을 계산하지 않으며 그런 값을 추정해 채우지도 않는다. 집계하는 것은
    오직 "호출 몇 번, 캐시 몇 번 맞았나, 얼마나 걸렸나"라는 사실뿐이다. 유료 API/LLM 이 실제로 붙으면
    ``record_call`` 의 ``cost_usd`` 인자로 확장할 자리만 남겨 두었다(현재는 항상 None → summary 에도 None).
    """

    def __init__(self) -> None:
        self._by_source: dict[str, _SourceStats] = defaultdict(_SourceStats)

    def record_call(
        self,
        source: str,
        *,
        cache_hit: bool = False,
        elapsed_seconds: float = 0.0,
        error: bool = False,
        cost_usd: Optional[float] = None,
    ) -> None:
        """호출 1건을 기록한다. cost_usd 는 항상 무시되고 기록되지 않는다(위 클래스 docstring 참고) —
        인자로만 받아 두어 향후 실제 유료 소스가 생기면 신호를 보내지 않고도 호출부를 바꾸지 않을 수 있게 한다.
        """
        s = self._by_source[str(source or "unknown")]
        s.calls += 1
        if cache_hit:
            s.cache_hits += 1
        else:
            s.cache_misses += 1
        if error:
            s.errors += 1
        s.total_seconds += float(elapsed_seconds)

    @contextmanager
    def timed_call(self, source: str, *, cache_hit: bool = False, clock=time.monotonic):
        """``with tracker.timed_call("sec_edgar"):`` 블록의 실행 시간을 재 record_call 을 자동 호출한다.

        블록에서 예외가 나면 error=True 로 기록하고 예외를 다시 던진다(실패를 조용히 삼키지 않는다).
        """
        start = clock()
        error = False
        try:
            yield
        except Exception:
            error = True
            raise
        finally:
            self.record_call(source, cache_hit=cache_hit, elapsed_seconds=clock() - start, error=error)

    def summary(self) -> dict:
        """소스별 dict. calls/cache_hits/cache_misses/errors/total_seconds 원자료와
        cache_hit_rate/avg_seconds_per_call 파생값(호출 0건이면 None), cost_usd=None(집계하지 않음)을 담는다.
        """
        out: dict = {}
        for source, s in self._by_source.items():
            out[source] = {
                "calls": s.calls,
                "cache_hits": s.cache_hits,
                "cache_misses": s.cache_misses,
                "errors": s.errors,
                "total_seconds": s.total_seconds,
                "cache_hit_rate": (s.cache_hits / s.calls) if s.calls else None,
                "avg_seconds_per_call": (s.total_seconds / s.calls) if s.calls else None,
                "cost_usd": None,
            }
        out["_disclaimer"] = (
            "실제 유료 API/LLM 비용을 계산하지 않는다(이 프로젝트엔 아직 유료 정보 API가 없다). "
            "호출 수·캐시 적중·소요 시간만 정직하게 집계한 값이다."
        )
        return out


# ---------------------------------------------------------------------------
# 5. summarize_extraction_quality — 원문 도달률 · 핵심필드 추출 성공률
# ---------------------------------------------------------------------------

# core.earnings_events.ExtractionResult.status 값 중 "핵심필드를 얻었다"로 볼 수 있는 것
# core.filing_changes.ExtractedSection.status / SectionDiff.status 값 중 "정상 추출"로 볼 수 있는 것
DEFAULT_EXTRACTION_SUCCESS_STATUSES = frozenset({
    "guidance_found",  # core.earnings_events.ExtractionResult.status
    "ok",              # core.filing_changes.ExtractedSection.status, SectionDiff.status
})


def summarize_extraction_quality(
    records: Sequence[dict],
    *,
    fetch_field: str = "fetch_status",
    extraction_field: str = "extraction_status",
    success_statuses: Iterable[str] = DEFAULT_EXTRACTION_SUCCESS_STATUSES,
) -> dict:
    """원문 도달률(fetch 성공/시도)과 핵심필드 추출 성공률을 집계한다.

    각 record 는 다음 두 필드를 선택적으로 담은 dict 다(둘 다 이 모듈이 값을 만들지 않는다 — 호출부가
    core.earnings_events/core.filing_changes 를 실제로 호출한 뒤 그 결과의 상태를 그대로 옮겨 담아야 한다):

    - ``fetch_field``(기본 "fetch_status"): 원문 요청 시도의 결과. ``True``/``"ok"`` 는 성공, 그 외 문자열
      (예: ``"error:SecFetchError"``, ``False``)은 실패지만 "시도"로는 센다. 키가 아예 없거나 값이 None이면
      "시도하지 않음"으로 보고 분모에서 뺀다(0으로 나누거나 실패로 조용히 채우지 않는다).
    - ``extraction_field``(기본 "extraction_status"): core.earnings_events.ExtractionResult.status
      (``"guidance_found"``/``"guidance_language_unparsed"``/``"no_guidance_language"``) 또는
      core.filing_changes.ExtractedSection.status/SectionDiff.status
      (``"ok"``/``"section_not_found"``/``"reference_only"``/``"not_applicable"``/``"not_comparable"``) 값을
      그대로 넣는다. ``success_statuses`` 에 있으면 "핵심필드 추출 성공"으로 센다.

    반환 dict 는 n_records, fetch_attempted/succeeded/rate, extraction_considered/succeeded/rate,
    status_counts(원문 상태별 개수 — 어떤 실패 사유가 많은지 보는 진단용), success_statuses_used 를 담는다.
    분모가 0이면 관련 rate 는 None(0.0 이 아님 — 표본 없음과 완전 실패를 혼동하지 않는다).
    """
    success_statuses = set(success_statuses)
    fetch_attempted = fetch_succeeded = 0
    extraction_considered = extraction_succeeded = 0
    status_counts: Counter = Counter()

    for r in records:
        fs = r.get(fetch_field)
        if fs is not None:
            fetch_attempted += 1
            if fs is True or (isinstance(fs, str) and fs.strip().lower() == "ok"):
                fetch_succeeded += 1
        es = r.get(extraction_field)
        if es is not None:
            extraction_considered += 1
            status_counts[str(es)] += 1
            if es in success_statuses:
                extraction_succeeded += 1

    return {
        "n_records": len(records),
        "fetch_attempted": fetch_attempted,
        "fetch_succeeded": fetch_succeeded,
        "fetch_success_rate": (fetch_succeeded / fetch_attempted) if fetch_attempted else None,
        "extraction_considered": extraction_considered,
        "extraction_succeeded": extraction_succeeded,
        "extraction_success_rate": (extraction_succeeded / extraction_considered) if extraction_considered else None,
        "status_counts": dict(status_counts),
        "success_statuses_used": sorted(success_statuses),
    }


# ---------------------------------------------------------------------------
# 6. populate_info_fields — core.candidate_ledger.CandidateRecord 의 info_* 필드 채우기
# ---------------------------------------------------------------------------

# core.candidate_ledger.CandidateRecord 생성자 필드명 그대로(그 모듈은 수정하지 않는다 — 읽기만 하고 이름만 맞춘다).
# 주의: content hash 는 그 dataclass 에서 ``info_hash`` 라는 필드명을 쓴다(DB 컬럼명은 info_content_hash 이지만
# record_candidate_set() 이 r.info_hash -> CandidateDecision.info_content_hash 로 옮겨 적는다).
_INFO_FIELD_MAP = {
    "event_id": "event_id",
    "content_hash": "info_hash",
    "info_url": "info_url",
    "info_doc_id": "info_doc_id",
    "info_revision": "info_revision",
    "info_cost": "info_cost",
}


def populate_info_fields(
    record_kwargs: dict,
    *,
    event_id: Optional[str] = None,
    content_hash: Optional[str] = None,
    info_url: Optional[str] = None,
    info_doc_id: Optional[str] = None,
    info_revision: Optional[str] = None,
    info_cost: Optional[dict] = None,
) -> dict:
    """``core.candidate_ledger.CandidateRecord(**결과)`` 에 쓸 kwargs dict를 반환한다.

    ``record_kwargs`` 를 얕은 복사한 뒤 이 함수의 인자로 넘긴 info_* 값만(None 이 아닌 것만) 그 사본에
    CandidateRecord 의 실제 필드명으로 채워 넣는다 — ``candidate_ledger.py`` 자체는 import 도, 수정도 하지
    않는다(필드명은 이 모듈 상단의 ``_INFO_FIELD_MAP`` 에 하드코딩돼 있으며 그 모듈의 실제 dataclass 정의와
    맞는지는 tests/test_info_dedup.py 가 CandidateRecord 를 직접 생성해 확인한다).

    ``record_kwargs`` 에 이미 있던 다른 키(ticker, decision, scores 등)는 그대로 보존한다. None 으로 넘긴
    인자는 "이 값은 모른다"는 뜻이라 기존 record_kwargs 값을 지우지 않는다(부분 갱신 허용).
    """
    out = dict(record_kwargs)
    supplied = {
        "event_id": event_id,
        "content_hash": content_hash,
        "info_url": info_url,
        "info_doc_id": info_doc_id,
        "info_revision": info_revision,
        "info_cost": info_cost,
    }
    for arg_name, value in supplied.items():
        if value is not None:
            out[_INFO_FIELD_MAP[arg_name]] = value
    return out
