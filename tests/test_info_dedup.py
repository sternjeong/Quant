"""core/info_dedup.py 테스트 (RES-02: 원문 중복 제거·정보 비용 집계 유틸리티).

이 모듈은 관측 전용이며 주문 경로·DB·스케줄러를 건드리지 않는다. 여기서는 다음을 확인한다.
1. compute_event_id 가 accession 표기 차이(대시 유무·대소문자)와 무관하게 결정적인지.
2. content_hash 가 core.earnings_events / core.filing_changes 의 실제 해시 함수와 (그 함수를 직접 호출해서)
   바이트 단위로 일치하는지 — 새 해시 규칙을 만들지 않았다는 것을 실증한다.
3. dedup_by_content 의 대표/중복 표시가 정확한지.
4. InfoCostTracker 가 호출·캐시 적중·오류·소요시간을 정확히 누적하는지.
5. summarize_extraction_quality 가 실제 core.earnings_events.ExtractionResult.status 값으로 계산한 비율과
   일치하는지.
6. populate_info_fields 가 core.candidate_ledger.CandidateRecord 를 실제로 생성할 수 있는 kwargs 를 만드는지.

예상값은 구현이 아니라 요구사항(결정적 ID 정의, 해시 정의, 비율 산수)에서 손으로 정했다.
"""

import hashlib

import pytest

from core import earnings_events as ee
from core import filing_changes as fc
from core import info_dedup
from core.candidate_ledger import CandidateRecord


# ---------------------------------------------------------------------------
# compute_event_id
# ---------------------------------------------------------------------------


def test_compute_event_id_same_accession_dash_and_nodash_and_case_are_identical():
    a = info_dedup.compute_event_id("sec_edgar", "0000320193-24-000123", "AAPL", "8-K")
    b = info_dedup.compute_event_id("SEC_EDGAR", "000032019324000123", "aapl", "8-k")
    assert a == b
    assert a.startswith("evt_")


def test_compute_event_id_differs_by_ticker_or_form_or_accession():
    base = info_dedup.compute_event_id("sec_edgar", "0000320193-24-000123", "AAPL", "8-K")
    assert base != info_dedup.compute_event_id("sec_edgar", "0000320193-24-000123", "MSFT", "8-K")
    assert base != info_dedup.compute_event_id("sec_edgar", "0000320193-24-000123", "AAPL", "10-K")
    assert base != info_dedup.compute_event_id("sec_edgar", "0000320193-24-000456", "AAPL", "8-K")


def test_compute_event_id_is_stable_across_repeated_calls():
    calls = {info_dedup.compute_event_id("sec_edgar", "0000320193-24-000123", "AAPL", "8-K") for _ in range(5)}
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# content_hash — 기존 모듈의 실제 해시 함수와 직접 대조
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status=200, body=b""):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = {}


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, url, headers=None, timeout=None):
        return self.responses.pop(0)


def test_content_hash_matches_earnings_events_sec_document_hash(tmp_path):
    body = "Item 2.02 Results of Operations.\nRevenue was $1.2 billion, up from $1.0 billion."
    client = ee.SecEdgarClient(
        cache_dir=tmp_path / "cache", session=_FakeSession([_FakeResponse(200, body)]),
        user_agent="test-agent (no real contact)",
    )
    doc = client.get("https://www.sec.gov/Archives/edgar/data/1/000001-26-000001-index.htm")
    # 손계산 대조
    assert doc.content_sha256 == hashlib.sha256(body.encode("utf-8")).hexdigest()
    # 실제 SecDocument.content_sha256 과 info_dedup.content_hash 가 일치하는지
    assert info_dedup.content_hash(doc.text) == doc.content_sha256
    assert len(info_dedup.content_hash(doc.text)) == 64  # 잘라내지 않은 sha256 hexdigest


def test_content_hash_matches_filing_changes_event_hash():
    current_doc = "<html><body><p>Item 1A. Risk Factors</p><p>We face intense competition in our markets.</p></body></html>"
    prior_doc = "<html><body><p>Item 1A. Risk Factors</p><p>We face competition in our markets.</p></body></html>"
    current = fc.FilingRecord(
        cik="0000000001", accession="0000000001-26-000002", form="10-K", filing_date="2026-03-01",
        acceptance_datetime="2026-03-01T21:00:00Z", report_date="2025-12-31", primary_document="doc.htm")
    prior = fc.FilingRecord(
        cik="0000000001", accession="0000000001-25-000002", form="10-K", filing_date="2025-03-01",
        acceptance_datetime="2025-03-01T21:00:00Z", report_date="2024-12-31", primary_document="doc.htm")

    ev = fc.build_filing_change_event(current, current_doc, prior, prior_doc, mode="retrospective")

    assert ev.comparison_status == "ok"  # 비교가 거부되면 해시 필드가 안 채워지므로 먼저 확인
    assert ev.current_doc_sha256 == hashlib.sha256(current_doc.encode("utf-8", "replace")).hexdigest()
    assert ev.current_doc_sha256 == info_dedup.content_hash(current_doc)
    assert ev.prior_doc_sha256 == info_dedup.content_hash(prior_doc)


def test_content_hash_differs_for_different_text_and_is_deterministic():
    a = info_dedup.content_hash("text one")
    b = info_dedup.content_hash("text two")
    assert a != b
    assert a == info_dedup.content_hash("text one")


# ---------------------------------------------------------------------------
# dedup_by_content
# ---------------------------------------------------------------------------


def test_dedup_by_content_groups_same_hash_and_flags_duplicate_of_representative():
    h1 = info_dedup.content_hash("same press release, mirrored on two wires")
    h2 = info_dedup.content_hash("a genuinely different press release")
    records = [
        {"event_id": "e1", "content_hash": h1, "url": "https://wire-a.example.com/1"},
        {"event_id": "e2", "content_hash": h1, "url": "https://wire-b.example.com/1-mirror"},
        {"event_id": "e3", "content_hash": h2, "url": "https://wire-a.example.com/2"},
    ]
    out = info_dedup.dedup_by_content(records)

    assert out[0]["duplicate_of"] is None and out[0]["is_duplicate"] is False
    assert out[1]["duplicate_of"] == "e1" and out[1]["is_duplicate"] is True
    assert out[2]["duplicate_of"] is None and out[2]["is_duplicate"] is False
    # 원본은 바꾸지 않는다
    assert "duplicate_of" not in records[0]
    assert "duplicate_of" not in records[1]


def test_dedup_by_content_missing_hash_is_never_grouped():
    records = [{"event_id": "e1"}, {"event_id": "e2"}, {"event_id": "e3", "content_hash": ""}]
    out = info_dedup.dedup_by_content(records)
    assert all(r["duplicate_of"] is None and r["is_duplicate"] is False for r in out)


def test_dedup_by_content_falls_back_to_positional_id_when_no_event_id_field():
    h = info_dedup.content_hash("x")
    records = [{"content_hash": h}, {"content_hash": h}]
    out = info_dedup.dedup_by_content(records)
    assert out[0]["duplicate_of"] is None
    assert out[1]["duplicate_of"] == "idx:0"


# ---------------------------------------------------------------------------
# InfoCostTracker
# ---------------------------------------------------------------------------


def test_info_cost_tracker_accumulates_calls_cache_hits_and_errors_per_source():
    tracker = info_dedup.InfoCostTracker()
    tracker.record_call("sec_edgar", cache_hit=True, elapsed_seconds=0.5)
    tracker.record_call("sec_edgar", cache_hit=False, elapsed_seconds=1.5)
    tracker.record_call("news", cache_hit=False, elapsed_seconds=2.0, error=True)

    summary = tracker.summary()

    sec = summary["sec_edgar"]
    assert sec["calls"] == 2
    assert sec["cache_hits"] == 1
    assert sec["cache_misses"] == 1
    assert sec["errors"] == 0
    assert sec["cache_hit_rate"] == pytest.approx(0.5)
    assert sec["total_seconds"] == pytest.approx(2.0)
    assert sec["avg_seconds_per_call"] == pytest.approx(1.0)
    assert sec["cost_usd"] is None  # 실제 비용 계산은 하지 않는다(명시적 요구사항)

    news = summary["news"]
    assert news["calls"] == 1
    assert news["errors"] == 1
    assert news["cache_hit_rate"] == pytest.approx(0.0)

    assert "_disclaimer" in summary


def test_info_cost_tracker_summary_has_no_calls_yet_is_empty_but_not_erroring():
    tracker = info_dedup.InfoCostTracker()
    summary = tracker.summary()
    assert summary == {"_disclaimer": summary["_disclaimer"]}


def test_info_cost_tracker_timed_call_records_elapsed_and_reraises_on_error():
    tracker = info_dedup.InfoCostTracker()
    ticks = iter([100.0, 102.5])

    with pytest.raises(ValueError):
        with tracker.timed_call("sec_edgar", clock=lambda: next(ticks)):
            raise ValueError("boom")

    summary = tracker.summary()
    assert summary["sec_edgar"]["calls"] == 1
    assert summary["sec_edgar"]["errors"] == 1
    assert summary["sec_edgar"]["total_seconds"] == pytest.approx(2.5)


def test_info_cost_tracker_timed_call_success_records_cache_hit_flag():
    tracker = info_dedup.InfoCostTracker()
    ticks = iter([0.0, 0.1])
    with tracker.timed_call("news", cache_hit=True, clock=lambda: next(ticks)):
        pass
    summary = tracker.summary()
    assert summary["news"]["cache_hits"] == 1
    assert summary["news"]["errors"] == 0


# ---------------------------------------------------------------------------
# summarize_extraction_quality — 실제 core.earnings_events 상태값으로 검증
# ---------------------------------------------------------------------------


def test_summarize_extraction_quality_matches_hand_calculated_rates_with_real_statuses():
    found = ee.extract_guidance("For the full year 2026, we expect revenue of $4.4 to $4.5 billion.")
    not_found = ee.extract_guidance("This press release describes our new office location.")
    assert found.status == "guidance_found"
    assert not_found.status == "no_guidance_language"

    records = [
        {"fetch_status": "ok", "extraction_status": found.status},
        {"fetch_status": "ok", "extraction_status": not_found.status},
        {"fetch_status": "error:SecFetchError"},  # 시도했지만 원문을 못 받아 extraction_status 없음
        {"extraction_status": found.status},  # fetch 시도 여부를 모르는 레코드(과거 백필 등) -> fetch 분모 제외
    ]

    out = info_dedup.summarize_extraction_quality(records)

    assert out["n_records"] == 4
    assert out["fetch_attempted"] == 3
    assert out["fetch_succeeded"] == 2
    assert out["fetch_success_rate"] == pytest.approx(2 / 3)
    assert out["extraction_considered"] == 3
    assert out["extraction_succeeded"] == 2
    assert out["extraction_success_rate"] == pytest.approx(2 / 3)
    assert out["status_counts"] == {"guidance_found": 2, "no_guidance_language": 1}
    assert "guidance_found" in out["success_statuses_used"]


def test_summarize_extraction_quality_recognizes_filing_changes_ok_status():
    current_doc = "<html><body>" + "<p>Filler paragraph without headings.</p>" * 5 + "</body></html>"
    sections = fc.extract_sections(fc.text_from_document(current_doc), "10-K")
    assert sections[fc.SECTION_RISK].status == "section_not_found"  # 실제 함수가 낸 진짜 실패 상태

    records = [
        {"fetch_status": "ok", "extraction_status": "ok"},
        {"fetch_status": "ok", "extraction_status": sections[fc.SECTION_RISK].status},
    ]
    out = info_dedup.summarize_extraction_quality(records)
    assert out["extraction_succeeded"] == 1
    assert out["extraction_success_rate"] == pytest.approx(0.5)
    assert out["status_counts"]["section_not_found"] == 1


def test_summarize_extraction_quality_empty_records_returns_none_rates_not_zero():
    out = info_dedup.summarize_extraction_quality([])
    assert out["n_records"] == 0
    assert out["fetch_success_rate"] is None
    assert out["extraction_success_rate"] is None


# ---------------------------------------------------------------------------
# populate_info_fields — core.candidate_ledger.CandidateRecord 와 실제로 맞물리는지
# ---------------------------------------------------------------------------


def test_populate_info_fields_builds_a_constructible_candidate_record():
    base_kwargs = {"ticker": "aapl", "decision": "held", "decision_reason": "no_new_orders_allowed"}
    h = info_dedup.content_hash("press release body text")
    eid = info_dedup.compute_event_id("sec_edgar", "0000320193-26-000010", "AAPL", "8-K")

    kwargs = info_dedup.populate_info_fields(
        base_kwargs, event_id=eid, content_hash=h,
        info_url="https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/ex991.htm",
        info_doc_id="0000320193-26-000010", info_revision="1",
        info_cost={"source": "sec_edgar", "calls": 1},
    )
    record = CandidateRecord(**kwargs)

    assert record.event_id == eid
    assert record.info_hash == h  # CandidateRecord 필드명은 info_hash (DB 컬럼명 info_content_hash 와 다름)
    assert record.info_url.endswith("ex991.htm")
    assert record.info_doc_id == "0000320193-26-000010"
    assert record.info_revision == "1"
    assert record.info_cost == {"source": "sec_edgar", "calls": 1}
    assert record.decision_reason == "no_new_orders_allowed"  # 기존 키 보존
    assert record.ticker == "AAPL"  # CandidateRecord.__post_init__ 이 대문자화(원 동작 그대로)


def test_populate_info_fields_none_arguments_preserve_existing_values_and_do_not_mutate_input():
    base = {"ticker": "MSFT", "decision": "rejected", "event_id": "keep-me"}
    out = info_dedup.populate_info_fields(base, content_hash="abc123")

    assert out["event_id"] == "keep-me"  # event_id=None 으로 호출 -> 기존 값 보존
    assert out["info_hash"] == "abc123"
    assert base == {"ticker": "MSFT", "decision": "rejected", "event_id": "keep-me"}  # 원본 불변

    record = CandidateRecord(**out)
    assert record.event_id == "keep-me"
    assert record.info_hash == "abc123"
