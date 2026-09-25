"""(2026-09-25) RES-02 info_dedup 연결 테스트: 가이던스 shadow·공시 veto shadow 의 후보 행에 event_id·content_hash.

요구사항(독립적으로 정한 기대값):
    - 같은 accession(같은 8-K/10-K)은 다른 날·다른 실행에서 기록돼도 같은 event_id 로 원장에 남는다.
    - 다른 accession 은 다른 event_id.
    - 근거 공시가 없는 후보는 event_id 를 지어내지 않는다(None).
    - content_hash 는 원문 sha256 을 그대로 옮긴다(새 해시 규칙을 만들지 않는다).
    - veto·원전략 결정은 바뀌지 않는다.
네트워크는 쓰지 않는다.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from core import filing_veto_shadow as fvs
from core import guidance_shadow as gs
from core.earnings_events import GuidanceChange, GuidanceItem
from core.filing_changes import FilingChangeEvent, SECTION_RISK, SectionDiff
from core.info_dedup import compute_event_id
from core.models import CandidateDecision

SHA_A = "a" * 64
SHA_B = "b" * 64


def _guidance_obs(ticker, accession, accepted, sha):
    item = GuidanceItem(
        cik="0000000001", accession=accession, acceptance_utc=accepted, source_url=f"https://example.test/{accession}.htm",
        metric="revenue", basis="gaap", period_key="FY2026", period_raw="fiscal 2026", shape="range",
        low=Decimal("100"), high=Decimal("110"), unit="currency", currency="USD", anchor="outlook")
    return gs.GuidanceObservation(ticker, GuidanceChange(change="raised", reason="midpoint_comparison", current=item),
                                  accepted, content_sha256=sha)


def _sat(tickers, as_of):
    return {"as_of": as_of.isoformat(), "selected": list(tickers),
            "per_ticker_weights": {t: 0.05 for t in tickers}, "sizing_method": "equal", "new_orders_allowed": True}


def test_same_8k_gets_same_event_id_across_days(db_session):
    accepted = datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)
    acc = "0000000001-26-000042"
    events = {"AAA": [_guidance_obs("AAA", acc, accepted, SHA_A)]}

    # 같은 8-K 가 이틀 연속 관측 창 안에 있다(두 날 모두 기록된다).
    gs.record_guidance_shadow(date(2026, 6, 3), session=db_session, satellite_result=_sat(["AAA", "BBB"], date(2026, 6, 3)),
                              events_by_ticker=events)
    gs.record_guidance_shadow(date(2026, 6, 4), session=db_session, satellite_result=_sat(["AAA", "BBB"], date(2026, 6, 4)),
                              events_by_ticker=events)

    rows = db_session.query(CandidateDecision).filter_by(source=gs.GUIDANCE_SHADOW_SOURCE).all()
    aaa = [r for r in rows if r.ticker == "AAA"]
    bbb = [r for r in rows if r.ticker == "BBB"]
    assert len(aaa) == 2
    expected = compute_event_id("sec_edgar", acc.replace("-", ""), "aaa", "8-K")  # 대시·대소문자 표기와 무관
    assert {r.event_id for r in aaa} == {expected}
    assert {r.info_content_hash for r in aaa} == {SHA_A}
    assert {r.info_doc_id for r in aaa} == {acc}
    assert all(r.event_id is None and r.info_content_hash is None for r in bbb)  # 근거 없음 -> 지어내지 않음


def test_different_8k_gets_different_event_id():
    feat_a = gs.compute_guidance_feature("AAA", "2026-06-10", [_guidance_obs(
        "AAA", "0000000001-26-000001", datetime(2026, 6, 1, tzinfo=timezone.utc), SHA_A)])
    feat_b = gs.compute_guidance_feature("AAA", "2026-06-10", [_guidance_obs(
        "AAA", "0000000001-26-000002", datetime(2026, 6, 2, tzinfo=timezone.utc), SHA_B)])
    ka = gs.guidance_info_kwargs({"ticker": "AAA"}, "AAA", feat_a)
    kb = gs.guidance_info_kwargs({"ticker": "AAA"}, "AAA", feat_b)
    assert ka["event_id"] != kb["event_id"]
    assert ka["info_hash"] == SHA_A and kb["info_hash"] == SHA_B
    assert "event_id" not in gs.guidance_feature_to_scores(feat_a)  # scores 에는 섞지 않는다


def _filing_event(ticker, accession, available_at, sha):
    risk = SectionDiff(section=SECTION_RISK, status="ok", current_status="ok", prior_status="ok", tags=[])
    return FilingChangeEvent(
        ticker=ticker, cik="0000000456", form="10-K", accession=accession, filing_date="2026-09-01",
        report_date="2026-06-30", prior_accession=f"{accession}-P", prior_form="10-K", prior_filing_date="2025-09-01",
        comparison_status="ok", available_at=available_at, sections={SECTION_RISK: risk}, current_doc_sha256=sha)


def test_same_10k_gets_same_event_id_across_days_in_filing_veto_shadow(db_session):
    acc = "0000000456-26-000010"

    def provider(ticker, cutoff):
        return [_filing_event(ticker, acc, "2026-09-15T21:00:00Z", SHA_B)] if ticker == "ZETA" else []

    for d in (date(2026, 9, 21), date(2026, 9, 22)):
        fvs.record_filing_veto_shadow(d, session=db_session, satellite_result={
            "as_of": d.isoformat(), "selected": ["ZETA", "OMEGA"], "sizing_method": "equal"}, event_provider=provider)

    rows = db_session.query(CandidateDecision).filter_by(source=fvs.SHADOW_SOURCE).all()
    zeta = [r for r in rows if r.ticker == "ZETA"]
    omega = [r for r in rows if r.ticker == "OMEGA"]
    assert len(zeta) == 2
    expected = compute_event_id("sec_edgar", acc, "ZETA", "10-K")
    assert {r.event_id for r in zeta} == {expected}
    assert {r.info_content_hash for r in zeta} == {SHA_B}
    assert {r.decision for r in zeta} == {"selected"}  # veto 판정(여기선 pass)은 바뀌지 않는다
    assert all(r.event_id is None for r in omega)


def test_filing_primary_event_is_most_recent_usable():
    old = _filing_event("ZETA", "0000000456-26-000001", "2026-08-01T21:00:00Z", SHA_A)
    new = _filing_event("ZETA", "0000000456-26-000002", "2026-09-15T21:00:00Z", SHA_B)
    kw = fvs.filing_info_kwargs({"ticker": "ZETA"}, "ZETA", [old, new], [old, new])
    assert kw["info_doc_id"] == "0000000456-26-000002"
    assert kw["info_hash"] == SHA_B
    assert fvs.filing_info_kwargs({"ticker": "ZETA"}, "ZETA", [], []) == {"ticker": "ZETA"}
