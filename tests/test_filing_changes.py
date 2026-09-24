"""core/filing_changes.py 오프라인 테스트 (직접 작성한 합성 fixture, 네트워크 없음).

예상값은 구현이 아니라 요구사항(문장 분리·분류 정의, 시간 계약, 비교 규칙)에서 손으로 정했다.
실제 SEC 문서로 정확도를 검증한 것이 아니다. 성과·정확도 증거로 쓰지 않는다.
"""

import json
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import filing_changes as fc
from core.filing_changes import (
    ExtractOptions,
    FilingChangeEvent,
    FilingComparisonRejected,
    FilingRecord,
    FilingVetoPolicy,
    SECTION_LIQUIDITY,
    SECTION_RISK,
    build_filing_change_event,
    compute_time_contract,
    extract_sections,
    filing_veto,
    find_prior_filing,
    html_to_text,
    validate_comparison,
)

OPTS = ExtractOptions(min_risk_chars=150, min_mdna_chars=200, min_liquidity_chars=100)
CIK = "0000000001"


# ---------------------------------------------------------------------------
# fixture 조립
# ---------------------------------------------------------------------------

def _p(*sentences: str) -> str:
    return "<p>" + " ".join(sentences) + "</p>"


def _doc_10k(
    risk_paras,
    *,
    heading="split",  # split | upper | plain | none
    business_extra="",
    legal_extra="",
    liquidity_paras=None,
    footers=False,
    toc=True,
):
    parts = ['<html><body><div style="display:none"><ix:header>Item 1A. Risk Factors hidden junk text</ix:header></div>']
    if toc:
        parts.append(
            "<p>Table of Contents</p><table>"
            "<tr><td>Item 1.</td><td>Business</td><td>3</td></tr>"
            "<tr><td>Item 1A.</td><td>Risk Factors</td><td>12</td></tr>"
            "<tr><td>Item 1B.</td><td>Unresolved Staff Comments</td><td>25</td></tr>"
            "<tr><td>Item 7.</td><td>Management&#8217;s Discussion and Analysis</td><td>30</td></tr>"
            "<tr><td>Item 7A.</td><td>Quantitative and Qualitative Disclosures About Market Risk</td><td>40</td></tr>"
            "</table>"
        )
    parts.append("<p>PART I</p><p>Item 1. Business</p>")
    parts.append(_p("Acme Corp designs and sells industrial widgets to customers in many countries."))
    if business_extra:
        parts.append(_p(business_extra))
    if heading == "split":
        parts.append("<div>Item 1A.</div><div>Risk Factors</div>")
    elif heading == "upper":
        parts.append("<p>ITEM 1A - RISK FACTORS</p>")
    elif heading == "plain":
        parts.append("<p>Item 1A. Risk Factors</p>")
    for i, para in enumerate(risk_paras):
        parts.append(para)
        if footers and i % 2 == 0:
            parts.append("<p>Acme Corp | 2024 Form 10-K | 14</p><p>14</p><p>Table of Contents</p>")
    parts.append("<p>Item 1B. Unresolved Staff Comments</p><p>None.</p>")
    parts.append("<p>Item 2. Properties</p>" + _p("We lease our headquarters and one factory."))
    parts.append("<p>Item 3. Legal Proceedings</p>" + _p(legal_extra or "We are not currently party to material legal proceedings."))
    parts.append("<p>PART II</p><p>Item 5. Market for Registrant&#8217;s Common Equity</p>" + _p("Our stock trades on an exchange."))
    parts.append("<p>Item 7. Management&#8217;s Discussion and Analysis of Financial Condition and Results of Operations</p>")
    parts.append("<p>Overview</p>" + _p("Revenue for the year was in line with our expectations and management remained focused on operating margins."))
    if liquidity_paras is not None:
        parts.append("<p>Liquidity and Capital Resources</p>")
        parts.extend(liquidity_paras)
    parts.append("<p>Critical Accounting Policies</p>" + _p("Revenue is recognized when control transfers to the customer under standard contract terms."))
    parts.append("<p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p>" + _p("We are exposed to modest currency risk."))
    parts.append("<p>Item 8. Financial Statements</p></body></html>")
    return "".join(parts)


P1 = _p("Our results depend on economic conditions.",
        "Demand for our products may decline during a recession or a period of reduced consumer spending.")
P2 = _p("We face intense competition in each of our markets and expect competitive pressures to continue in the coming years.",
        "Competitors may introduce lower priced products that could reduce our sales.")
P3_PRIOR = _p("We depend on a limited number of suppliers for key components of our products.",
              "One customer accounted for 12% of our net sales in fiscal 2023.")
P3_CUR = _p("We depend on a limited number of suppliers for key components of our products.",
            "One customer accounted for 27% of our net sales in fiscal 2024.")
P4 = _p("We may need additional financing to fund our operations and growth plans.",
        "There can be no assurance that financing will be available on acceptable terms.")
P5_PRIOR = _p("We are subject to legal proceedings from time to time in the ordinary course of business.",
              "Our credit facility permits borrowings of up to $500 million until 2027.")
P5_CUR = _p("We are subject to legal proceedings from time to time in the ordinary course of business.",
            "Our credit facility permits borrowings of up to $300 million until 2027.")
P7 = _p("Our headquarters lease expires in 2029 and we may be unable to renew it on favorable terms.")

C_SUBPOENA = "In March 2024 we received a subpoena from the Department of Justice requesting documents relating to our sales practices."
C_GOING_CONCERN = "Our independent auditors have expressed substantial doubt about our ability to continue as a going concern."
C_CLASS_ACTION_HYP = "We may become subject to class action lawsuits that could result in substantial costs."

LIQ_PRIOR = [
    _p("As of December 31, 2023 we had cash and cash equivalents of $120 million.",
       "Our revolving credit facility matures in 2027 and we were in compliance with its terms."),
    _p("We believe our existing cash will be sufficient to fund operations for at least the next twelve months."),
]
LIQ_CUR = [
    _p("As of December 31, 2024 we had cash and cash equivalents of $45 million.",
       "Our revolving credit facility matures in 2027 and we were in compliance with its terms."),
    _p("We believe our existing cash will be sufficient to fund operations for at least the next twelve months."),
    _p("We entered into a forbearance agreement with our lenders in February 2025 after failing to meet the leverage covenant."),
]


def _rec(acc, form, filed, accept, report, *, cik=CIK, ticker="ACME"):
    return FilingRecord(cik=cik, accession=acc, form=form, filing_date=filed, acceptance_datetime=accept,
                        report_date=report, primary_document="x.htm", ticker=ticker)


PRIOR_REC = _rec("0000000001-24-000010", "10-K", "2024-03-01", "2024-03-01T21:00:00Z", "2023-12-31")
CUR_REC = _rec("0000000001-25-000012", "10-K", "2025-03-03", "2025-03-03T21:30:00Z", "2024-12-31")


def _base_event(**kw):
    prior = _doc_10k([P1, P2, P3_PRIOR, P4, P5_PRIOR, P7], liquidity_paras=LIQ_PRIOR)
    cur = _doc_10k(
        [P1, P2, P3_CUR, P4, P5_CUR, _p(C_SUBPOENA), _p(C_GOING_CONCERN), _p(C_CLASS_ACTION_HYP)],
        liquidity_paras=LIQ_CUR,
    )
    return build_filing_change_event(CUR_REC, cur, PRIOR_REC, prior, options=OPTS, **kw), cur, prior


# ---------------------------------------------------------------------------
# HTML -> 텍스트
# ---------------------------------------------------------------------------

def test_html_to_text_skips_hidden_and_joins_table_cells():
    html = ('<html><head><title>t</title><style>p{}</style></head><body>'
            '<div style="display:none"><ix:header>SECRET HIDDEN</ix:header></div>'
            '<script>var x = "SCRIPT";</script>'
            '<table><tr><td>Item&nbsp;1A.</td><td>Risk Factors</td><td>12</td></tr></table>'
            '<p>First&nbsp;paragraph <b>bold</b> end.</p><div>Item 1A.</div><div>Risk Factors</div></body></html>')
    text = html_to_text(html)
    assert "SECRET" not in text and "SCRIPT" not in text and "t\n" not in text.split("\n")[0:1]
    lines = text.split("\n")
    assert lines[0] == "Item 1A. Risk Factors 12"
    assert "First paragraph bold end." in lines
    assert lines[-2:] == ["Item 1A.", "Risk Factors"]


def test_text_from_document_plain_text_passthrough():
    assert fc.text_from_document("a  b\n\n  c d ") == "a b\nc d"


# ---------------------------------------------------------------------------
# 문장 분리 · 숫자
# ---------------------------------------------------------------------------

def test_split_sentences_keeps_abbreviations():
    s = "Revenue from the U.S. and Canada rose 5%. Costs fell, e.g., in Asia. See Inc. filings."
    assert fc.split_sentences(s) == [
        "Revenue from the U.S. and Canada rose 5%.",
        "Costs fell, e.g., in Asia.",
        "See Inc. filings.",
    ]


def test_extract_numbers_units_and_years():
    nums = fc.extract_numbers("We had $1,250.5 million in cash, 12% growth over 30 days in 2024.")
    assert [(n.value, n.unit) for n in nums] == [(1250.5e6, "usd"), (12.0, "%"), (30.0, "day")]


def test_compare_numbers_pairs_by_position():
    ch = fc.compare_numbers("One customer accounted for 12% of net sales.", "One customer accounted for 27% of net sales.")
    assert len(ch) == 1 and ch[0].unit == "%" and ch[0].delta == pytest.approx(15.0) and ch[0].ratio == pytest.approx(1.25)
    assert fc.compare_numbers("Cash of $5.0 million.", "Cash of $5 million.") == []


# ---------------------------------------------------------------------------
# 섹션 추출
# ---------------------------------------------------------------------------

def test_extract_sections_skips_toc_and_hidden_and_ends_at_next_item():
    doc = _doc_10k([P1, P2, P3_PRIOR, P4, P5_PRIOR, P7], liquidity_paras=LIQ_PRIOR)
    secs = extract_sections(html_to_text(doc), "10-K", OPTS)
    risk = secs[SECTION_RISK]
    assert risk.status == "ok"
    assert risk.text.startswith("Our results depend on economic conditions.")
    assert "headquarters lease expires" in risk.text
    assert "hidden junk" not in risk.text and "Unresolved Staff" not in risk.text
    assert "Acme Corp designs" not in risk.text  # Item 1 본문은 포함되지 않는다
    assert risk.end_reason == "next_item:1B"
    liq = secs[SECTION_LIQUIDITY]
    assert liq.status == "ok" and liq.heading == "Liquidity and Capital Resources"
    assert "cash and cash equivalents of $120 million" in liq.text
    assert "Revenue is recognized" not in liq.text  # Critical Accounting 에서 끝난다
    assert "Revenue for the year" not in liq.text  # Overview 는 유동성 소절이 아니다
    assert liq.end_reason.startswith("terminator:Critical Accounting")


@pytest.mark.parametrize("heading", ["upper", "plain", "split"])
def test_extract_sections_heading_styles(heading):
    doc = _doc_10k([P1, P2, P3_PRIOR, P4], heading=heading, liquidity_paras=LIQ_PRIOR)
    assert extract_sections(html_to_text(doc), "10-K", OPTS)[SECTION_RISK].status == "ok"


def test_section_not_found_when_heading_missing():
    doc = _doc_10k([P1, P2, P3_PRIOR, P4], heading="none", liquidity_paras=LIQ_PRIOR, toc=False)
    secs = extract_sections(html_to_text(doc), "10-K", OPTS)
    assert secs[SECTION_RISK].status == "section_not_found"
    assert secs[SECTION_RISK].text == ""
    assert secs[SECTION_LIQUIDITY].status == "ok"  # 다른 절은 독립적으로 추출


def test_section_not_found_when_only_toc_entry_exists():
    doc = _doc_10k([], heading="none", liquidity_paras=None)
    secs = extract_sections(html_to_text(doc), "10-K", OPTS)
    assert secs[SECTION_RISK].status == "section_not_found"  # 목차 항목 본문은 비어 있다
    assert secs[SECTION_LIQUIDITY].status == "section_not_found"  # 유동성 소절 머리글이 없다
    assert "liquidity_heading_not_found_in_mdna" in secs[SECTION_LIQUIDITY].notes


def test_reference_only_and_not_applicable_are_not_guessed_as_sections():
    q = html_to_text(
        "<p>PART II</p><p>Item 1. Legal Proceedings</p><p>None.</p><p>Item 1A. Risk Factors</p>"
        "<p>There have been no material changes to the risk factors disclosed in our Annual Report on Form 10-K.</p>"
        "<p>Item 2. Unregistered Sales of Equity Securities</p><p>None.</p>"
    )
    assert extract_sections(q, "10-Q", OPTS)[SECTION_RISK].status == "reference_only"
    k = html_to_text("<p>Item 1A. Risk Factors</p><p>Not required for smaller reporting companies.</p>"
                     "<p>Item 1B. Unresolved Staff Comments</p><p>None.</p>")
    assert extract_sections(k, "10-K", OPTS)[SECTION_RISK].status == "not_applicable"


def test_short_body_without_reference_language_is_not_found():
    t = html_to_text("<p>Item 1A. Risk Factors</p><p>Some short words only.</p><p>Item 1B. Unresolved Staff Comments</p>")
    sec = extract_sections(t, "10-K", OPTS)[SECTION_RISK]
    assert sec.status == "section_not_found" and "body_too_short_without_reference_language" in sec.notes


def test_cross_reference_line_is_not_a_heading():
    body = _p("Please see Item 1A of Part I for more detail.") + "<p>Item 1A of this report discusses our risks in depth and more.</p>"
    doc = _doc_10k([P1, P2, body, P3_PRIOR], liquidity_paras=LIQ_PRIOR)
    risk = extract_sections(html_to_text(doc), "10-K", OPTS)[SECTION_RISK]
    assert risk.status == "ok" and "Item 1A of this report" in risk.text  # 본문 속 참조가 절을 끊지 않는다


def test_10q_mdna_liquidity_uses_part1_item2():
    t = html_to_text(
        "<p>PART I</p><p>Item 1. Financial Statements</p><p>Statements follow.</p>"
        "<p>Item 2. Management&#8217;s Discussion and Analysis of Financial Condition and Results of Operations</p>"
        "<p>Overview</p>" + _p("Quarterly revenue was steady and management is focused on margin improvement across all segments.") +
        "<p>Liquidity</p>" + _p("We had cash of $45 million at quarter end and no outstanding borrowings under our facility.") +
        _p("We expect operating cash flow to fund capital spending during the next twelve months without new financing.") +
        "<p>Item 3. Quantitative and Qualitative Disclosures About Market Risk</p><p>Not material.</p>"
        "<p>PART II</p><p>Item 1A. Risk Factors</p><p>No material changes.</p>"
        "<p>Item 2. Unregistered Sales of Equity Securities</p><p>None.</p>"
    )
    secs = extract_sections(t, "10-Q", OPTS)
    assert secs[SECTION_LIQUIDITY].status == "ok" and "cash of $45 million" in secs[SECTION_LIQUIDITY].text
    assert secs[SECTION_LIQUIDITY].end_reason == "mdna_end"  # 유동성 소절이 MD&A(Item 3 직전)의 끝까지


@pytest.mark.parametrize("line,expected", [
    ("Liquidity and Capital Resources", True), ("Liquidity", True),
    ("Financial Condition, Liquidity and Capital Resources", True),
    ("Capital Resources and Liquidity", True),
    ("Our liquidity is adequate", False), ("Liquidity risk management policies", False),
])
def test_liquidity_heading_detection(line, expected):
    assert fc._is_liquidity_heading(line) is expected


# ---------------------------------------------------------------------------
# diff: 신규 / 삭제 / 숫자 변화 분리
# ---------------------------------------------------------------------------

def test_diff_separates_new_deleted_and_numeric_changes():
    ev, cur_html, _ = _base_event()
    assert ev.comparison_status == "ok"
    sd = ev.sections[SECTION_RISK]
    assert sd.status == "ok"
    c = sd.counts
    # 손계산: 직전 11문장 = 동일 8 + 숫자변경 2 + 삭제 1, 현재 13문장 = 동일 8 + 숫자변경 2 + 신규 3
    assert (c["sentences_prior"], c["sentences_current"]) == (11, 13)
    assert (c["unchanged"], c["numeric_changed"], c["new"], c["deleted"], c["reworded"]) == (8, 2, 3, 1, 0)
    kinds = {}
    for ch in sd.changes:
        kinds.setdefault(ch.kind, []).append(ch)
    assert {x.text for x in kinds["new"]} == {C_SUBPOENA, C_GOING_CONCERN, C_CLASS_ACTION_HYP}
    assert [x.text for x in kinds["deleted"]] == ["Our headquarters lease expires in 2029 and we may be unable to renew it on favorable terms."]
    nums = {x.text: x.numeric_changes[0] for x in kinds["numeric_changed"]}
    cust = nums["One customer accounted for 27% of our net sales in fiscal 2024."]
    assert (cust["old_value"], cust["new_value"], cust["unit"], cust["delta"]) == (12.0, 27.0, "%", 15.0)
    fac = nums["Our credit facility permits borrowings of up to $300 million until 2027."]
    assert (fac["old_value"], fac["new_value"], fac["unit"]) == (5e8, 3e8, "usd")
    assert len(sd.numeric_changes) == 2
    # 연도 롤오버(fiscal 2023 -> 2024)는 숫자 변화로 잡히지 않는다: 숫자 변경은 위 2건뿐


def test_new_sentence_tags_carry_anchor_and_novelty():
    ev, cur_html, _ = _base_event()
    text = html_to_text(cur_html)
    tags = {t.anchor: t for t in ev.sections[SECTION_RISK].tags}
    sub = tags[C_SUBPOENA]
    assert (sub.category, sub.severity, sub.modality, sub.specific, sub.novelty, sub.is_new) == \
        (fc.CATEGORY_LITIGATION, "strong", "asserted", True, "new_category", True)
    gc = tags[C_GOING_CONCERN]
    assert (gc.category, gc.severity, gc.modality, gc.novelty, gc.is_new) == \
        (fc.CATEGORY_LIQUIDITY, "strong", "asserted", "new_category", True)
    hyp = tags[C_CLASS_ACTION_HYP]
    assert hyp.modality == "hypothetical" and hyp.is_new and hyp.category == fc.CATEGORY_LITIGATION
    cust = tags["One customer accounted for 27% of our net sales in fiscal 2024."]
    assert cust.novelty == "numeric_change" and not cust.is_new and cust.numeric_change["delta"] == 15.0
    for t in ev.new_tags():
        assert t.anchor in text  # anchor 는 제공 원문의 문장 그대로다
    # 삭제 문장의 태그는 removed_tags 로 분리(여기서는 없음)
    assert ev.sections[SECTION_RISK].removed_tags == []


def test_liquidity_subsection_diff_flags_new_forbearance():
    ev, _, _ = _base_event()
    sd = ev.sections[SECTION_LIQUIDITY]
    assert sd.status == "ok"
    assert sd.counts["new"] == 1 and sd.counts["numeric_changed"] == 1 and sd.counts["deleted"] == 0
    tag = [t for t in sd.tags if t.is_new][0]
    assert tag.category == fc.CATEGORY_LIQUIDITY and tag.severity == "strong" and tag.modality == "asserted"
    assert "forbearance agreement" in tag.anchor
    cash = [c for c in sd.numeric_changes if c.unit == "usd"][0]
    assert (cash.old_value, cash.new_value) == (120e6, 45e6)


def test_escalated_reworded_sentence_hypothetical_to_asserted():
    prior_para = _p("Our recurring losses could raise substantial doubt about our ability to continue as a going concern.")
    cur_para = _p("Our recurring losses raise substantial doubt about our ability to continue as a going concern.")
    filler = [_p(*(_filler_sentences(4, 11)))]
    prior = _doc_10k(filler + [prior_para], liquidity_paras=LIQ_PRIOR)
    cur = _doc_10k(filler + [cur_para], liquidity_paras=LIQ_PRIOR)
    ev = build_filing_change_event(CUR_REC, cur, PRIOR_REC, prior, options=OPTS)
    sd = ev.sections[SECTION_RISK]
    assert sd.counts["reworded"] == 1 and sd.counts["new"] == 0
    tag = [t for t in sd.tags if t.is_new][0]
    assert tag.novelty == "escalated" and tag.modality == "asserted"
    assert tag.prior_anchor.startswith("Our recurring losses could raise")
    assert filing_veto([ev]).decision == "hold"


def _filler_sentences(n, seed):
    rnd = random.Random(seed)
    vocab = ("harbor copper meadow lantern orchid granite pillow velvet anchor ribbon saddle timber marble "
             "pepper walnut thistle quartz bridge willow cinder falcon juniper kettle mosaic nectar oyster "
             "parcel quiver ripple sandal tundra umber violet wagon yarrow zephyr blossom canyon dune ember "
             "fjord glacier hazel island jasmine kelp lagoon maple nutmeg opal prairie quill raven summit").split()
    out = []
    for _ in range(n):
        words = rnd.sample(vocab, 12)
        out.append("The " + " ".join(words) + " remained stable throughout the period.")
    return out


# ---------------------------------------------------------------------------
# 템플릿·형식만 바뀐 경우는 신호가 아니다
# ---------------------------------------------------------------------------

SUBPOENA_PRIOR = "In March 2023 we received a subpoena from the Department of Justice requesting documents relating to our sales practices."


def test_template_only_change_is_not_a_signal():
    p8_prior = _p("Results for fiscal 2023 were affected by supply constraints across several regions of the world.")
    p8_cur = _p("Results for fiscal 2024 were affected by supply constraints across several regions of the world.")
    p2_cur = _p("We face intense competition in all of our markets and expect competitive pressures to continue in the coming years.",
                "Competitors may introduce lower priced products that could reduce our sales.")
    prior = _doc_10k([P1, P2, p8_prior, P3_PRIOR, P4], legal_extra=SUBPOENA_PRIOR, liquidity_paras=LIQ_PRIOR)
    # 현재: 머리글 표기 변경, 쪽번호·머리글 줄, 재서술 1건, 연도 롤오버, 소환장 문장이 Item 3 에서 Item 1A 로 이동
    cur = _doc_10k([P1, p2_cur, p8_cur, P3_PRIOR, P4, _p(SUBPOENA_PRIOR)], heading="upper", footers=True,
                   legal_extra="See the discussion in Item 1A.", liquidity_paras=LIQ_PRIOR)
    ev = build_filing_change_event(CUR_REC, cur, PRIOR_REC, prior, options=OPTS)
    sd = ev.sections[SECTION_RISK]
    assert sd.status == "ok"
    assert (sd.counts["new"], sd.counts["deleted"], sd.counts["numeric_changed"]) == (0, 0, 0)
    assert sd.counts["reworded"] == 1
    assert sd.counts["moved_from_other_section"] == 1  # 소환장 문장은 직전 문서 다른 절에 이미 있었다
    assert [t for t in sd.tags if t.is_new] == []
    dec = filing_veto([ev])
    assert dec.decision == "pass" and dec.reason_codes == ["no_qualifying_change"]
    # 섹션만 비교했다면 소환장 문장이 신규 대형 소송으로 잡혔을 것이다(이동 검사가 없는 경우의 대조군)
    naive = fc.diff_sections(
        extract_sections(html_to_text(prior), "10-K", OPTS)[SECTION_RISK],
        extract_sections(html_to_text(cur), "10-K", OPTS)[SECTION_RISK], options=OPTS)
    assert naive.counts["new"] == 1


def test_heavy_rewording_sets_template_flag_and_suppresses_non_new_category_veto():
    fill = _filler_sentences(20, 3)
    prior_par = _p(*fill) + _p("A securities class action was filed against us in 2022 and remains pending in federal court.")
    reworded = [s.replace("remained stable", "stayed stable") for s in fill[:10]] + fill[10:]
    new_sent = "In June 2024 a second class action was filed against us by a group of former customers in state court."
    cur_par = _p(*reworded) + _p("A securities class action was filed against us in 2022 and remains pending in federal court.") + _p(new_sent)
    prior = _doc_10k([prior_par], liquidity_paras=LIQ_PRIOR)
    cur = _doc_10k([cur_par], liquidity_paras=LIQ_PRIOR)
    ev = build_filing_change_event(CUR_REC, cur, PRIOR_REC, prior, options=OPTS)
    sd = ev.sections[SECTION_RISK]
    assert sd.counts["reworded"] == 10 and sd.counts["new"] == 1
    assert "heavy_rewording" in sd.flags
    assert "template_restructure_suspected" in ev.flags
    tag = [t for t in sd.tags if t.is_new][0]
    assert tag.novelty == "new_sentence"  # 직전에도 사실 서술 소송 문장이 있었다
    dec = filing_veto([ev])
    assert dec.decision == "pass" and dec.reason_codes == ["suppressed_template_restructure"]
    assert [r.anchor for r in dec.suppressed] == [new_sent]
    assert filing_veto([ev], FilingVetoPolicy(suppress_on_flags=())).decision == "hold"


def test_new_category_is_not_suppressed_by_template_flag():
    fill = _filler_sentences(20, 5)
    reworded = [s.replace("remained stable", "stayed stable") for s in fill[:10]] + fill[10:]
    prior = _doc_10k([_p(*fill)], liquidity_paras=LIQ_PRIOR)
    cur = _doc_10k([_p(*reworded), _p(C_GOING_CONCERN)], liquidity_paras=LIQ_PRIOR)
    ev = build_filing_change_event(CUR_REC, cur, PRIOR_REC, prior, options=OPTS)
    assert "template_restructure_suspected" in ev.flags
    dec = filing_veto([ev])
    assert dec.decision == "hold" and dec.reason_codes == ["new_going_concern_language"]


def test_length_shock_and_boilerplate_only_flags():
    fill_prior = _filler_sentences(25, 21)  # 약 25*15 = 375 단어
    fill_more = _filler_sentences(30, 22)
    boiler = "This section contains forward-looking statements that are subject to risks and uncertainties."
    prior = _doc_10k([_p(*fill_prior)], liquidity_paras=LIQ_PRIOR)
    cur = _doc_10k([_p(*fill_prior), _p(*fill_more), _p(boiler)], liquidity_paras=LIQ_PRIOR)
    ev = build_filing_change_event(CUR_REC, cur, PRIOR_REC, prior, options=OPTS)
    sd = ev.sections[SECTION_RISK]
    assert sd.length_ratio > 1.5 and "length_shock" in sd.flags
    only_boiler = _doc_10k([_p(*fill_prior), _p(boiler)], liquidity_paras=LIQ_PRIOR)
    ev2 = build_filing_change_event(CUR_REC, only_boiler, PRIOR_REC, prior, options=OPTS)
    assert "new_text_boilerplate_only" in ev2.sections[SECTION_RISK].flags


def test_business_combination_and_accounting_standard_flags_from_new_doc_text():
    prior = _doc_10k([P1, P2, P3_PRIOR, P4], liquidity_paras=LIQ_PRIOR)
    cur = _doc_10k([P1, P2, P3_PRIOR, P4], liquidity_paras=LIQ_PRIOR,
                   business_extra="In 2024 we completed the acquisition of Widget Holdings Inc. and integrated its operations. "
                                  "We adopted ASU 2023-07 during fiscal 2024 with no material effect.")
    ev = build_filing_change_event(CUR_REC, cur, PRIOR_REC, prior, options=OPTS)
    assert "business_combination_suspected" in ev.flags and "accounting_standard_change_suspected" in ev.flags
    assert "completed the acquisition" in ev.flag_details["business_combination_suspected"][0]
    assert ev.sections[SECTION_RISK].counts["new"] == 0  # 위험 절 자체는 그대로


# ---------------------------------------------------------------------------
# 비교 규칙
# ---------------------------------------------------------------------------

def test_validate_comparison_rejects_mixed_forms_amendments_and_other_companies():
    k24 = _rec("A-1", "10-K", "2024-03-01", "2024-03-01T21:00:00Z", "2023-12-31")
    k25 = _rec("A-2", "10-K", "2025-03-03", "2025-03-03T21:30:00Z", "2024-12-31")
    q25 = _rec("A-3", "10-Q", "2025-05-05", "2025-05-05T20:00:00Z", "2025-03-31")
    k24a = _rec("A-4", "10-K/A", "2024-06-01", "2024-06-01T20:00:00Z", "2023-12-31")
    other = _rec("B-1", "10-K", "2024-03-01", "2024-03-01T21:00:00Z", "2023-12-31", cik="0000000002")
    assert validate_comparison(k25, k24) is None
    assert validate_comparison(q25, k25) == "form_mismatch"
    assert validate_comparison(k25, q25) == "form_mismatch"
    assert validate_comparison(k24a, k24) == "amendment_not_supported"
    assert validate_comparison(k25, k24a) == "prior_is_amendment"
    assert validate_comparison(k25, other) == "cik_mismatch"
    assert validate_comparison(k25, k25) == "same_accession"
    assert validate_comparison(k24, k25) == "prior_not_older"
    assert validate_comparison(k25, None) == "no_prior_filing"


def test_find_prior_filing_skips_amendments_and_other_forms():
    k23 = _rec("A-0", "10-K", "2023-03-01", "2023-03-01T21:00:00Z", "2022-12-31")
    k24 = _rec("A-1", "10-K", "2024-03-01", "2024-03-01T21:00:00Z", "2023-12-31")
    k24a = _rec("A-4", "10-K/A", "2024-06-01", "2024-06-01T20:00:00Z", "2023-12-31")
    q24 = _rec("A-5", "10-Q", "2024-11-05", "2024-11-05T20:00:00Z", "2024-09-30")
    k25 = _rec("A-2", "10-K", "2025-03-03", "2025-03-03T21:30:00Z", "2024-12-31")
    q25 = _rec("A-3", "10-Q", "2025-05-05", "2025-05-05T20:00:00Z", "2025-03-31")
    recs = [k23, k24, k24a, q24, k25, q25]
    assert find_prior_filing(recs, k25).accession == "A-1"  # 10-K/A(더 최근)·10-Q 가 아니라 직전 10-K 원본
    assert find_prior_filing(recs, q25).accession == "A-5"  # 10-Q 는 직전 10-Q
    assert find_prior_filing([k24a, q24], k25) is None
    assert find_prior_filing(recs, k23) is None  # 미래 공시를 직전으로 쓰지 않는다


def test_build_event_rejected_for_form_mismatch_and_amendment():
    prior = _doc_10k([P1, P2, P3_PRIOR, P4], liquidity_paras=LIQ_PRIOR)
    q_rec = _rec("A-3", "10-Q", "2025-05-05", "2025-05-05T20:00:00Z", "2025-03-31")
    ev = build_filing_change_event(q_rec, prior, PRIOR_REC, prior, options=OPTS)
    assert ev.comparison_status == "rejected" and ev.reject_reason == "form_mismatch"
    assert ev.sections == {} and "comparison_rejected:form_mismatch" in ev.flags
    assert ev.pit_certified is False
    with pytest.raises(FilingComparisonRejected) as ei:
        build_filing_change_event(q_rec, prior, PRIOR_REC, prior, options=OPTS, strict=True)
    assert ei.value.reason == "form_mismatch"
    amend = _rec("A-9", "10-K/A", "2025-06-01", "2025-06-01T20:00:00Z", "2024-12-31")
    assert build_filing_change_event(amend, prior, PRIOR_REC, prior, options=OPTS).reject_reason == "amendment_not_supported"
    assert filing_veto([ev]).reason_codes == ["no_usable_event"]


def test_prior_gap_unusual_flag():
    prior_rec = _rec("A-0", "10-K", "2022-03-01", "2022-03-01T21:00:00Z", "2021-12-31")  # 간격 1095일
    doc = _doc_10k([P1, P2, P3_PRIOR, P4], liquidity_paras=LIQ_PRIOR)
    ev = build_filing_change_event(CUR_REC, doc, prior_rec, doc, options=OPTS)
    assert ev.period_gap_days == 1096 and "prior_gap_unusual" in ev.flags
    ok = build_filing_change_event(CUR_REC, doc, PRIOR_REC, doc, options=OPTS)
    assert ok.period_gap_days == 366 and "prior_gap_unusual" not in ok.flags


def test_section_not_found_event_is_not_compared_and_not_vetoed():
    prior = _doc_10k([P1, P2, P3_PRIOR, P4], liquidity_paras=None)
    cur = _doc_10k([], heading="none", liquidity_paras=None)
    ev = build_filing_change_event(CUR_REC, cur, PRIOR_REC, prior, options=OPTS)
    sd = ev.sections[SECTION_RISK]
    assert sd.status == "not_comparable" and sd.changes == [] and sd.tags == []
    assert f"section_not_found:{SECTION_RISK}:current" in sd.flags
    assert f"section_not_found:{SECTION_RISK}:current" in ev.flags
    dec = filing_veto([ev])
    assert dec.decision == "pass" and dec.reason_codes == ["no_usable_event"]
    assert dec.unusable_events == [{"accession": ev.accession, "reason": "no_section_comparable"}]
    assert any(SECTION_RISK in g for g in dec.data_gaps)


# ---------------------------------------------------------------------------
# 시간 계약
# ---------------------------------------------------------------------------

def _tc(accept, **kw):
    kw.setdefault("assumed_latency_hours", 0.5)
    return compute_time_contract(accept, **kw)


def test_time_contract_regular_hours_filing_same_day_decision_next_open_fill():
    # 2025-10-31(금) 06:01 EDT 접수 + 0.5시간 -> 같은 날 16:00 EDT(20:00Z) 결정, 다음 거래일 월요일 09:30 EST(14:30Z) 체결
    t = _tc("2025-10-31T10:01:26.000Z")
    assert t["source_publication"] == "2025-10-31T10:01:26Z"
    assert t["available_at"] == "2025-10-31T10:31:26Z"
    assert (t["decision_day"], t["decision_cutoff"]) == ("2025-10-31", "2025-10-31T20:00:00Z")
    assert (t["next_executable_fill_day"], t["next_executable_fill"]) == ("2025-11-03", "2025-11-03T14:30:00Z")
    assert t["time_basis"] == "retrospective_assumed_latency" and t["system_first_seen"] is None


def test_time_contract_after_close_filing_moves_to_next_trading_day():
    t = _tc("2025-05-02T21:15:00.000Z")  # 금 17:15 EDT
    assert (t["decision_cutoff"], t["next_executable_fill"]) == ("2025-05-05T20:00:00Z", "2025-05-06T13:30:00Z")


def test_time_contract_skips_good_friday_and_thanksgiving():
    t = _tc("2025-04-17T21:30:00Z")  # 목 17:30 EDT, 다음날 성금요일 휴장
    assert (t["decision_day"], t["next_executable_fill_day"]) == ("2025-04-21", "2025-04-22")
    assert (t["decision_cutoff"], t["next_executable_fill"]) == ("2025-04-21T20:00:00Z", "2025-04-22T13:30:00Z")
    t2 = _tc("2025-11-26T22:00:00Z")  # 수 17:00 EST, 목 추수감사절
    assert (t2["decision_cutoff"], t2["next_executable_fill"]) == ("2025-11-28T21:00:00Z", "2025-12-01T14:30:00Z")


def test_time_contract_dst_start_straddle():
    t = _tc("2025-03-07T21:30:00Z")  # 금 16:30 EST(서머타임 시작 이틀 전) -> 월 16:00 EDT = 20:00Z
    assert (t["decision_cutoff"], t["next_executable_fill"]) == ("2025-03-10T20:00:00Z", "2025-03-11T13:30:00Z")


def test_time_contract_cutoff_boundary_inclusive():
    on = _tc("2025-06-10T20:00:00Z", assumed_latency_hours=0)  # 정확히 16:00:00 EDT
    after = _tc("2025-06-10T20:00:01Z", assumed_latency_hours=0)
    assert on["decision_day"] == "2025-06-10" and on["next_executable_fill"] == "2025-06-11T13:30:00Z"
    assert after["decision_day"] == "2025-06-11" and after["next_executable_fill"] == "2025-06-12T13:30:00Z"


def test_time_contract_weekend_filing():
    t = _tc("2025-08-02T15:00:00Z", assumed_latency_hours=0)  # 토요일
    assert (t["decision_day"], t["next_executable_fill_day"]) == ("2025-08-04", "2025-08-05")


def test_time_contract_live_mode_uses_max_of_publication_first_seen_extraction():
    t = compute_time_contract("2025-10-31T10:01:26.000Z", mode="live",
                              system_first_seen="2025-11-03T15:00:00Z", extraction_completed="2025-11-03T15:05:00Z")
    assert t["available_at"] == "2025-11-03T15:05:00Z" and t["time_basis"] == "live_observed"
    assert (t["decision_cutoff"], t["next_executable_fill"]) == ("2025-11-03T21:00:00Z", "2025-11-04T14:30:00Z")
    t2 = compute_time_contract("2025-10-31T10:01:26.000Z", mode="live", extraction_completed="2025-10-31T10:20:00Z")
    assert t2["time_basis"] == "live_first_seen_missing" and t2["available_at"] == "2025-10-31T10:20:00Z"


def test_time_contract_uses_actual_trading_day_list_when_given():
    days = [date(2025, 10, 31), date(2025, 11, 4)]  # 11-03 을 비거래일로 가정
    t = _tc("2025-10-31T10:01:26.000Z", trading_days=days)
    assert t["next_executable_fill"] == "2025-11-04T14:30:00Z" and t["calendar_basis"] == "trading_days_list"
    beyond = _tc("2025-11-04T10:00:00Z", trading_days=days)
    assert beyond["next_executable_fill"] is None  # 목록 밖은 추측하지 않는다


def test_time_contract_missing_acceptance():
    t = _tc(None)
    assert t["available_at"] is None and t["decision_cutoff"] is None and t["time_basis"] == "acceptance_missing"


def test_nyse_holiday_rules():
    h25 = fc.nyse_holidays(2025)
    assert {date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17), date(2025, 4, 18), date(2025, 5, 26),
            date(2025, 6, 19), date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25)} == set(h25)
    assert date(2026, 7, 3) in fc.nyse_holidays(2026)  # 7/4 토요일 -> 금요일 관측
    assert fc.is_trading_day(date(2021, 12, 31))  # 2022-01-01 토요일은 앞 금요일에 쉬지 않는다
    assert not fc.is_trading_day(date(2027, 12, 24))  # 크리스마스 토요일 -> 금요일 관측
    assert not fc.is_trading_day(date(2025, 1, 9))  # 카터 추모 특별 휴장
    assert fc._easter(2025) == date(2025, 4, 20) and fc._easter(2024) == date(2024, 3, 31)


def test_fallback_new_york_tz_matches_zoneinfo():
    zi = pytest.importorskip("zoneinfo")
    real = zi.ZoneInfo("America/New_York")
    fb = fc._FallbackNewYork()
    for iso in ["2025-03-09T06:59:00+00:00", "2025-03-09T07:00:00+00:00", "2025-11-02T05:59:00+00:00",
                "2025-11-02T06:00:00+00:00", "2025-07-01T12:00:00+00:00", "2025-01-15T12:00:00+00:00"]:
        dt = datetime.fromisoformat(iso)
        assert dt.astimezone(fb).utcoffset() == dt.astimezone(real).utcoffset(), iso


def test_event_time_fields_and_pit_not_certified():
    ev, _, _ = _base_event()
    assert ev.source_publication == "2025-03-03T21:30:00Z"
    assert ev.available_at == "2025-03-03T22:00:00Z" and ev.assumed_latency_hours == 0.5
    # 2025-03-03(월) 16:30 EST 접수 -> 화요일 16:00 EST(21:00Z) 결정 -> 수요일 09:30 EST(14:30Z) 체결
    assert ev.decision_cutoff == "2025-03-04T21:00:00Z" and ev.next_executable_fill == "2025-03-05T14:30:00Z"
    assert ev.pit_certified is False and ev.pit_certification_blockers
    assert "historical_backfill_system_first_seen_unknown" in ev.pit_certification_blockers
    assert ev.time_basis == "retrospective_assumed_latency" and ev.system_first_seen is None
    live = build_filing_change_event(CUR_REC, _doc_10k([P1, P2, P3_CUR, P4]), PRIOR_REC,
                                     _doc_10k([P1, P2, P3_PRIOR, P4]), options=OPTS, mode="live",
                                     system_first_seen="2025-03-04T15:00:00Z", extraction_completed="2025-03-04T15:02:00Z")
    assert live.available_at == "2025-03-04T15:02:00Z" and live.time_basis == "live_observed"
    assert live.pit_certified is False


# ---------------------------------------------------------------------------
# veto 규칙
# ---------------------------------------------------------------------------

def test_filing_veto_holds_with_reasons_and_anchors():
    ev, cur_html, _ = _base_event()
    dec = filing_veto([ev])
    assert dec.decision == "hold"
    assert set(dec.reason_codes) == {"new_going_concern_language", "new_major_litigation",
                                     "new_liquidity_distress_language", "customer_concentration_increase"}
    text = html_to_text(cur_html)
    by_code = {r.code: r for r in dec.reasons}
    assert by_code["new_going_concern_language"].anchor == C_GOING_CONCERN
    assert by_code["new_major_litigation"].anchor == C_SUBPOENA
    assert "forbearance agreement" in by_code["new_liquidity_distress_language"].anchor
    assert by_code["new_liquidity_distress_language"].section == SECTION_LIQUIDITY
    cust = by_code["customer_concentration_increase"]
    assert cust.anchor == "One customer accounted for 27% of our net sales in fiscal 2024."
    assert cust.prior_anchor == "One customer accounted for 12% of our net sales in fiscal 2023."
    assert cust.detail["delta"] == 15.0
    for r in dec.reasons:
        assert r.anchor in text and r.accession == CUR_REC.accession and r.form == "10-K"
    # 가정 문장(class action may)은 신규여도 hold 사유가 아니다
    assert all(r.anchor != C_CLASS_ACTION_HYP for r in dec.reasons)
    assert (dec.shadow_only, dec.order_path_connected, dec.pit_certified) == (True, False, False)
    assert "입증되지 않았다" in dec.note


def test_filing_veto_policy_toggles_and_thresholds():
    ev, _, _ = _base_event()
    only_lit = FilingVetoPolicy(hold_liquidity=False, hold_concentration_increase=False)
    assert filing_veto([ev], only_lit).reason_codes == ["new_major_litigation"]
    none = FilingVetoPolicy(hold_liquidity=False, hold_litigation=False, hold_concentration_increase=False)
    d = filing_veto([ev], none)
    assert d.decision == "pass" and d.reason_codes == ["no_qualifying_change"]
    strict_pp = FilingVetoPolicy(hold_liquidity=False, hold_litigation=False, concentration_increase_pp=20.0)
    assert filing_veto([ev], strict_pp).decision == "pass"  # 15%p 증가는 20%p 문턱 미만
    loose = FilingVetoPolicy(hold_liquidity=False, hold_litigation=False, concentration_increase_pp=15.0)
    assert filing_veto([ev], loose).reason_codes == ["customer_concentration_increase"]  # 경계 포함(>=)


def test_filing_veto_ignores_negated_and_hypothetical_going_concern_language():
    neg = "There is no substantial doubt about our ability to continue as a going concern."
    hyp = "If we cannot obtain financing, there could be substantial doubt about our ability to continue as a going concern."
    prior = _doc_10k([P1, P2, P3_PRIOR, P4], liquidity_paras=LIQ_PRIOR)
    cur = _doc_10k([P1, P2, P3_PRIOR, P4, _p(neg), _p(hyp)], liquidity_paras=LIQ_PRIOR)
    ev = build_filing_change_event(CUR_REC, cur, PRIOR_REC, prior, options=OPTS)
    mods = {t.anchor: t.modality for t in ev.sections[SECTION_RISK].tags}
    assert mods[neg] == "negated" and mods[hyp] == "hypothetical"
    d = filing_veto([ev])
    assert d.decision == "pass" and d.reason_codes == ["no_qualifying_change"]
    # 정책에서 asserted 요구를 끄면 가정 문장은 hold 사유가 된다(부정 문장은 여전히 아니다)
    d2 = filing_veto([ev], FilingVetoPolicy(require_asserted=False))
    assert d2.decision == "hold" and [r.anchor for r in d2.reasons] == [hyp]


def test_filing_veto_time_gating_with_as_of():
    ev, _, _ = _base_event()
    avail = datetime(2025, 3, 3, 22, 0, tzinfo=timezone.utc)
    early = filing_veto([ev], as_of=avail - timedelta(minutes=1))
    assert early.decision == "pass" and early.reason_codes == ["no_usable_event"]
    assert early.unusable_events == [{"accession": ev.accession, "reason": "event_not_yet_available"}]
    assert filing_veto([ev], as_of=avail).decision == "hold"
    assert filing_veto([ev], as_of=avail + timedelta(days=45)).decision == "hold"
    late = filing_veto([ev], as_of=avail + timedelta(days=46))
    assert late.decision == "pass" and late.unusable_events[0]["reason"] == "event_too_old"
    assert filing_veto([ev], FilingVetoPolicy(max_event_age_days=None), as_of=avail + timedelta(days=400)).decision == "hold"


def test_filing_veto_with_no_events_and_missing_time_contract():
    assert filing_veto([]).reason_codes == ["no_usable_event"]
    ev, _, _ = _base_event()
    ev.available_at = None
    d = filing_veto([ev])
    assert d.decision == "pass" and d.unusable_events[0]["reason"] == "time_contract_missing"


def test_filing_veto_docstring_states_hypothesis_status():
    doc = fc.filing_veto.__doc__
    assert "입증된 규칙이 아니" in doc and "가설" in doc and "주문 경로에 연결하지 않는다" in doc


# ---------------------------------------------------------------------------
# JSON 직렬화 · 비밀 정보
# ---------------------------------------------------------------------------

def test_event_json_roundtrip_and_fields():
    ev, _, _ = _base_event()
    data = json.loads(ev.to_json())
    assert data["pit_certified"] is False and data["shadow_only"] is True
    assert data["schema_version"] == fc.SCHEMA_VERSION and data["rules_version"] == fc.RULES_VERSION
    for key in ("source_publication", "system_first_seen", "extraction_completed", "available_at",
                "decision_cutoff", "next_executable_fill"):
        assert key in data
    again = FilingChangeEvent.from_json(ev.to_json())
    assert again.to_dict() == ev.to_dict()
    assert isinstance(again.sections[SECTION_RISK].tags[0], fc.RiskTag)


def test_module_and_tests_contain_no_email_addresses():
    pattern = re.compile(r"[A-Za-z0-9._%+-]+" + "@" + r"[A-Za-z0-9-]+\.[A-Za-z]{2,}")
    for path in (Path(fc.__file__), Path(__file__)):
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name


# ---------------------------------------------------------------------------
# fetcher (가짜 HTTP, 네트워크 없음)
# ---------------------------------------------------------------------------

class _FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def _make_client(tmp_path, routes, *, clock=None, ua="TestAgent unit-test", **kw):
    """routes: url -> bytes | (status, bytes[, headers]) | list(순서대로 소진) | Exception. 호출 기록은 calls."""
    clock = clock or _FakeClock()
    calls = []

    def http_get(url, headers, timeout):
        calls.append((url, dict(headers)))
        r = routes[url]
        if isinstance(r, list):
            r = r.pop(0) if len(r) > 1 else r[0]
        if isinstance(r, Exception):
            raise r
        if isinstance(r, bytes):
            return 200, r, {}
        status, body = r[0], r[1]
        return status, body, (r[2] if len(r) > 2 else {})

    client = fc.EdgarClient(tmp_path / "cache", user_agent=ua, http_get=http_get,
                            limiter=fc.RateLimiter(5, clock=clock.now, sleep=clock.sleep),
                            sleep=lambda s: clock.sleeps.append(("backoff", s)), clock=clock.now, **kw)
    client.calls = calls
    client.fake_clock = clock
    return client


SUB_URL = "https://data.sec.gov/submissions/CIK0000000001.json"
OLD_URL = "https://data.sec.gov/submissions/CIK0000000001-submissions-001.json"


def _submissions_payload():
    recent = {
        "accessionNumber": ["0000000001-25-000030", "0000000001-25-000020", "0000000001-25-000012", "0000000001-24-000010"],
        "filingDate": ["2025-05-05", "2025-06-02", "2025-03-03", "2024-03-01"],
        "reportDate": ["2025-03-31", "2024-12-31", "2024-12-31", "2023-12-31"],
        "acceptanceDateTime": ["2025-05-05T20:00:00.000Z", "2025-06-02T13:00:00.000Z",
                               "2025-03-03T21:30:00.000Z", "2024-03-01T21:00:00.000Z"],
        "form": ["10-Q", "10-K/A", "10-K", "10-K"],
        "primaryDocument": ["q.htm", "ka.htm", "k25.htm", "k24.htm"],
    }
    older = {
        "accessionNumber": ["0000000001-23-000005"], "filingDate": ["2023-03-01"], "reportDate": ["2022-12-31"],
        "acceptanceDateTime": ["2023-03-01T21:00:00.000Z"], "form": ["10-K"], "primaryDocument": ["k23.htm"],
    }
    meta = {"cik": "1", "name": "Acme Corp", "tickers": ["ACME"],
            "filings": {"recent": recent, "files": [{"name": "CIK0000000001-submissions-001.json"}]}}
    return json.dumps(meta).encode(), json.dumps(older).encode()


def test_resolve_user_agent_env_precedence_and_default():
    assert fc.resolve_user_agent({"SEC_EDGAR_USER_AGENT": "AgentA test", "SEC_USER_AGENT": "AgentB test"}) == "AgentA test"
    assert fc.resolve_user_agent({"SEC_USER_AGENT": "AgentB test"}) == "AgentB test"
    assert fc.resolve_user_agent({"SEC_EDGAR_USER_AGENT": "  ", "SEC_USER_AGENT": ""}) == "QuantResearch personal-project"
    assert fc.resolve_user_agent({}) == fc.DEFAULT_USER_AGENT == "QuantResearch personal-project"
    assert "@" not in fc.DEFAULT_USER_AGENT
    assert fc.user_agent_source({"SEC_USER_AGENT": "x y"}) == "SEC_USER_AGENT"
    assert fc.user_agent_source({"SEC_EDGAR_USER_AGENT": "x y"}) == "SEC_EDGAR_USER_AGENT"
    assert fc.user_agent_source({}) == "default"


def test_rate_limiter_never_exceeds_five_per_second_and_clamps():
    clock = _FakeClock()
    lim = fc.RateLimiter(50, clock=clock.now, sleep=clock.sleep)
    assert lim.max_per_second == 5
    stamps = []
    for _ in range(23):
        lim.wait()
        stamps.append(clock.now())
    for i in range(len(stamps) - 5):
        assert stamps[i + 5] - stamps[i] >= 1.0  # 어떤 연속 6번째 요청도 첫 요청 뒤 1초 이상
    assert clock.now() - stamps[0] >= (23 // 5 - 1)  # 실제로 지연이 발생했다
    with pytest.raises(ValueError):
        fc.RateLimiter(0)


def test_client_sends_user_agent_header_and_never_leaks_it_in_errors(tmp_path):
    ua = "TestAgent secret-marker-123"
    client = _make_client(tmp_path, {SUB_URL: (403, b"<html>Your Request Originates from an Undeclared Automated Tool</html>")},
                          ua=ua)
    with pytest.raises(fc.EdgarUndeclaredUserAgent) as ei:
        client.get_submissions("0000000001")
    assert "secret-marker" not in str(ei.value) and ei.value.status == 403
    assert len(client.calls) == 1  # 차단은 재시도하지 않는다
    assert client.calls[0][1]["User-Agent"] == ua
    assert client.user_agent_source == "explicit"


def test_client_403_other_and_404_are_not_retried(tmp_path):
    c = _make_client(tmp_path, {SUB_URL: (403, b"forbidden")})
    with pytest.raises(fc.EdgarBlocked):
        c.get_submissions("1")
    assert len(c.calls) == 1
    c2 = _make_client(tmp_path / "b", {SUB_URL: (404, b"nope")})
    with pytest.raises(fc.EdgarFetchError) as ei:
        c2.get_submissions("1")
    assert ei.value.status == 404 and len(c2.calls) == 1


def test_client_backoff_on_429_and_5xx_then_success(tmp_path):
    main, _ = _submissions_payload()
    c = _make_client(tmp_path, {SUB_URL: [(429, b"slow down"), (503, b"busy"), (200, main)]})
    meta, blocks = c.get_submissions("1")
    assert meta["name"] == "Acme Corp" and len(c.calls) == 3
    assert [s for s in c.fake_clock.sleeps if isinstance(s, tuple)] == [("backoff", 2.0), ("backoff", 4.0)]


def test_client_honors_retry_after_and_gives_up_after_max_retries(tmp_path):
    c = _make_client(tmp_path, {SUB_URL: [(429, b"x", {"Retry-After": "7"})]}, )
    with pytest.raises(fc.EdgarRateLimited):
        c.get_submissions("1")
    assert len(c.calls) == 4  # 최초 1회 + 재시도 3회
    assert [s for s in c.fake_clock.sleeps if isinstance(s, tuple)] == [("backoff", 7.0)] * 3
    c2 = _make_client(tmp_path / "n", {SUB_URL: [OSError("boom")]})
    with pytest.raises(fc.EdgarFetchError) as ei:
        c2.get_submissions("1")
    assert ei.value.kind == "network" and len(c2.calls) == 4


def test_client_requests_are_rate_limited_across_calls(tmp_path):
    main, older = _submissions_payload()
    c = _make_client(tmp_path, {SUB_URL: main, OLD_URL: older})
    c.list_filings(cik="1", include_older=True)
    assert c.requests_made == 2
    times = []
    lim = fc.RateLimiter(5, clock=c.fake_clock.now, sleep=c.fake_clock.sleep)
    for _ in range(12):
        lim.wait()
        times.append(c.fake_clock.now())
    assert all(times[i + 5] - times[i] >= 1.0 for i in range(len(times) - 5))


def test_list_filings_excludes_amendments_by_default_and_sorts_latest_first(tmp_path):
    main, older = _submissions_payload()
    c = _make_client(tmp_path, {SUB_URL: main, OLD_URL: older})
    recs = c.list_filings(cik="1")
    assert [(r.form, r.accession) for r in recs] == [
        ("10-Q", "0000000001-25-000030"), ("10-K", "0000000001-25-000012"), ("10-K", "0000000001-24-000010")]
    assert all(not r.is_amendment for r in recs) and recs[0].ticker == "ACME" and recs[0].cik == CIK
    assert recs[1].acceptance_datetime == "2025-03-03T21:30:00Z" and recs[1].report_date == "2024-12-31"
    assert recs[1].document_url == "https://www.sec.gov/Archives/edgar/data/1/000000000125000012/k25.htm"
    with_a = c.list_filings(cik="1", include_amendments=True, forms=("10-K",))
    assert [r.form for r in with_a] == ["10-K/A", "10-K", "10-K"] and with_a[0].is_amendment
    assert len(c.list_filings(cik="1", forms=("10-K",), include_older=True)) == 3
    assert c.list_filings(cik="1", limit=1)[0].form == "10-Q"


def test_cache_prevents_repeat_requests_and_respects_ttl(tmp_path):
    main, _ = _submissions_payload()
    c = _make_client(tmp_path, {SUB_URL: main}, submissions_ttl_seconds=100)
    c.list_filings(cik="1")
    c.list_filings(cik="1")
    assert len(c.calls) == 1
    import os as _os
    p = tmp_path / "cache" / "submissions" / "CIK0000000001.json"
    _os.utime(p, (c.fake_clock.now() - 500, c.fake_clock.now() - 500))
    c.list_filings(cik="1")
    assert len(c.calls) == 2  # TTL 만료 후 재조회


def test_document_fetch_is_cached_forever_and_decodes_fallback(tmp_path):
    main, _ = _submissions_payload()
    doc_url = "https://www.sec.gov/Archives/edgar/data/1/000000000125000012/k25.htm"
    c = _make_client(tmp_path, {SUB_URL: main, doc_url: "<html>café</html>".encode("cp1252")})
    rec = c.list_filings(cik="1")[1]
    assert c.fetch_primary_document(rec) == "<html>café</html>"
    c.fake_clock.t += 10 ** 8
    assert c.fetch_primary_document(rec) == "<html>café</html>"
    assert sum(1 for u, _h in c.calls if u == doc_url) == 1


def test_first_seen_ledger_records_first_observation_only(tmp_path):
    main, _ = _submissions_payload()
    c = _make_client(tmp_path, {SUB_URL: main}, submissions_ttl_seconds=0)
    c.list_filings(cik="1")
    first = c.first_seen("0000000001-25-000012")
    assert first is not None and first.endswith("Z")
    c.fake_clock.t += 5000
    c.list_filings(cik="1")
    assert c.first_seen("0000000001-25-000012") == first  # 처음 본 시각은 바뀌지 않는다
    assert c.first_seen("nope") is None


def test_resolve_cik_from_ticker_file(tmp_path):
    payload = json.dumps({"0": {"cik_str": 1, "ticker": "ACME", "title": "Acme"},
                          "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire"}}).encode()
    c = _make_client(tmp_path, {fc.EdgarClient.TICKERS_URL: payload})
    assert c.resolve_cik("acme") == "0000000001"
    assert c.resolve_cik("BRK.B") == "0001067983"
    with pytest.raises(fc.EdgarFetchError):
        c.resolve_cik("ZZZZ")


def test_build_latest_event_end_to_end_with_fake_http(tmp_path):
    main, older = _submissions_payload()
    prior_html = _doc_10k([P1, P2, P3_PRIOR, P4, P5_PRIOR, P7], liquidity_paras=LIQ_PRIOR)
    cur_html = _doc_10k([P1, P2, P3_CUR, P4, P5_CUR, _p(C_SUBPOENA)], liquidity_paras=LIQ_CUR)
    routes = {
        SUB_URL: main,
        "https://www.sec.gov/Archives/edgar/data/1/000000000125000012/k25.htm": cur_html.encode(),
        "https://www.sec.gov/Archives/edgar/data/1/000000000124000010/k24.htm": prior_html.encode(),
    }
    c = _make_client(tmp_path, routes)
    ev = fc.build_latest_filing_change_event(c, cik="1", form="10-K", options=OPTS)
    assert (ev.accession, ev.prior_accession, ev.form, ev.prior_form) == (
        "0000000001-25-000012", "0000000001-24-000010", "10-K", "10-K")
    assert ev.comparison_status == "ok" and ev.ticker == "ACME" and ev.pit_certified is False
    assert filing_veto([ev]).decision == "hold"
    urls = [u for u, _h in c.calls]
    assert not any("ka.htm" in u or "q.htm" in u for u in urls)  # 10-K/A·10-Q 문서는 받지 않는다
    with pytest.raises(fc.EdgarFetchError) as ei:
        fc.build_latest_filing_change_event(_make_client(tmp_path / "e", {SUB_URL: main}), cik="1", form="20-F")
    assert ei.value.kind == "no_filings"


def test_first_filing_without_prior_is_rejected_not_guessed(tmp_path):
    main, _ = _submissions_payload()
    cur_url = "https://www.sec.gov/Archives/edgar/data/1/000000000124000010/k24.htm"
    c = _make_client(tmp_path, {SUB_URL: main, cur_url: _doc_10k([P1, P2, P3_PRIOR, P4]).encode()})
    recs = c.list_filings(cik="1", forms=("10-K",))
    oldest = recs[-1]
    assert find_prior_filing(recs, oldest) is None
    ev = build_filing_change_event(oldest, c.fetch_primary_document(oldest), None, None, options=OPTS)
    assert ev.reject_reason == "no_prior_filing" and ev.comparison_status == "rejected"
