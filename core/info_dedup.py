"""RES-02: 정보 예산과 중복 라우터 — 사건 ID·원문 해시 유틸리티 (2026-09-22, 순수 관측 인프라).

목적: docs/INFORMATION_DECISION_ENGINE_RESEARCH.md RES-02("여러 기사를 여러 독립 근거로 세지 않는다")를 위한
최소 유틸리티. 이 모듈은 주문 경로(core.paper_execution, scripts/champion_paper_trade.py)나 스케줄러, DB를
전혀 건드리지 않는다. core.candidate_ledger / core.earnings_events / core.filing_changes 는 **읽기만** 하며
수정하지 않는다 — 이 세 모듈이 이미 정의한 필드명·해시 방식에 맞춰 값을 만들어 줄 뿐이다.

이 모듈이 하는 일
1. compute_event_id: 같은 사건(같은 accession 등)을 가리키는 서로 다른 호출이 항상 같은 문자열을 내도록 하는
   결정적 ID.
2. content_hash: core.earnings_events.PressRelease.content_sha256 / core.filing_changes.FilingChangeEvent.
   current_doc_sha256·prior_doc_sha256 와 **정확히 같은 해시 값**을 내는 함수. 아래 "해시 규칙" 절 참고.
3. populate_info_fields: 후보 행에 위 두 값을 채운다(가이던스·공시 veto shadow 야간 기록이 쓴다).
   중복 묶기·비용 집계 함수는 쓰는 곳이 없어 2026-11-15 지웠다.

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
from typing import Any, Optional

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
