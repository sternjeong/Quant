"""관제 센터 사용 설명서가 엔진과 어긋나지 않게 막는 테스트.

- 형식 테스트: 이미 적힌 항목이 올바른가. 항목을 쓰는 사람이 자기 몫을 검증할 때도 쓴다.
- coverage 테스트: 새 화면/잡/core 모듈/스크립트에 설명이 있는가, 사라진 것의 설명이 남아 있지 않은가.
  이 테스트가 실패하면 hub/guide/content_*.py 를 고쳐야 한다(`python -m hub.guide.check` 로 목록 확인).
  자동배포의 테스트 관문이 pytest 를 돌리므로, 설명이 어긋난 채로는 배포되지 않는다.
"""

from __future__ import annotations

import html
import re

import pytest

from hub.guide import build_content, live, render_guide_page
from hub.guide.check import coverage_problems
from hub.guide.render import SECTIONS, render_guide
from hub.guide.schema import (
    GuideContent, JobGuide, ModuleGuide, OpsSection, PageGuide, Routine, ScriptGuide, Term, validate_entries,
)

CONTENT = build_content()


# ---------------------------------------------------------------------------
# 형식
# ---------------------------------------------------------------------------
def test_entries_are_well_formed():
    problems = validate_entries(CONTENT)
    assert problems == [], "설명 항목 형식 문제:\n" + "\n".join(problems)


def test_validate_catches_bad_entries():
    bad = GuideContent(
        pages=(PageGuide(path="pages/없는_화면.py", summary="", when_to_use="x", steps=(), sources=("no/such/file.py",), verified="2026-13-45"),),
        modules=(ModuleGuide(module="core/none.py", name="n", group="엉뚱", status="엉뚱", what="w", how_to_use="h", where_to_see="s", verified="2999-01-01"),),
        scripts=(ScriptGuide(path="scripts/none.py", name="n", when_to_run="w", command="c", risk="엉뚱", what_it_prints="p", verified="2026-01-01"),),
        jobs=(JobGuide(job_id="j", where_to_see="", verified="2026-01-01"),),
        internal_modules={"core/gone.py": ""},
    )
    text = "\n".join(validate_entries(bad))
    for needle in ("summary", "steps", "근거 파일이 없습니다", "verified", "group", "status", "risk", "where_to_see", "core/gone.py"):
        assert needle in text, needle


def test_duplicate_keys_are_reported():
    dup = GuideContent(glossary=(Term("PIT", "a"), Term("PIT", "b")))
    assert any("중복" in p for p in validate_entries(dup))


# ---------------------------------------------------------------------------
# 렌더링
# ---------------------------------------------------------------------------
def test_guide_renders_with_live_sections():
    page = render_guide_page()
    assert "<title>Quant 사용 설명서</title>" in page
    for _, title, _ in (item for pages in live.navigation().values() for item in pages):
        assert title in page
    for job in live.job_rows():
        assert job.label in page
    assert 'name="viewport"' in page  # 폰에서 보는 화면이라 필수


def test_guide_text_is_html_escaped():
    evil = "<script>alert(1)</script>"
    content = GuideContent(
        pages=(PageGuide(path="views/today.py", summary=evil, when_to_use=evil, steps=(evil,), cautions=(evil,), verified="2026-01-01"),),
        modules=(ModuleGuide(module="core/db.py", name=evil, group="운용", status="운영중", what=evil, how_to_use=evil, where_to_see=evil, verified="2026-01-01"),),
        glossary=(Term(evil, evil, evil),), routines=(Routine("r", evil, evil, (evil,), (evil,)),),
        ops=(OpsSection("o", evil, (evil,), ((evil, evil),), "2026-01-01"),), start_here=(evil,),
    )
    page = render_guide(content)
    assert "<script>alert(1)" not in page
    assert "&lt;script&gt;alert(1)" in page


def test_stale_marker_appears_when_source_changed_after_verified(monkeypatch):
    monkeypatch.setattr(live, "last_commit_date", lambda paths: "2026-09-20")
    content = GuideContent(pages=(PageGuide(path="views/today.py", summary="s", when_to_use="w", steps=("a",),
                                            sources=("core/db.py",), verified="2026-09-01"),))
    assert "근거 코드가 수정됐습니다" in render_guide(content)
    monkeypatch.setattr(live, "last_commit_date", lambda paths: "2026-08-01")
    assert "근거 코드가 수정됐습니다" not in render_guide(content)


def test_stale_marker_is_silent_when_git_is_unavailable(monkeypatch):
    monkeypatch.setattr(live, "last_commit_date", lambda paths: None)
    assert live.is_stale("2026-01-01", ("core/db.py",)) is None


def test_format_when_converts_us_jobs_to_kst():
    text = live.format_when({"day_of_week": "mon-fri", "hour": 16, "minute": 30, "timezone": "America/New_York"})
    assert text.startswith("월~금 16:30 America/New_York") and "KST" in text
    assert live.format_when({"hour": 0, "minute": 27, "timezone": "Asia/Seoul"}) == "매일 00:27 KST"


def test_every_scheduled_job_row_has_registry_state():
    for row in live.job_rows():
        assert row.enabled is not None, f"{row.job_id}: process_registry 에 항목이 없습니다"
        assert row.description.strip(), f"{row.job_id}: 레지스트리 description 이 비어 있습니다"


def test_guide_route_and_home_card_exist():
    from hub import server

    assert "/guide" in server.render_dashboard("localhost")
    assert "Quant 사용 설명서" in server.render_dashboard("localhost") or "사용 설명서" in server.render_dashboard("localhost")


# ---------------------------------------------------------------------------
# coverage — 엔진이 바뀌면 설명도 바꿔야 한다는 것을 강제한다
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("category", [
    "설명이 없는 화면", "사라진 화면의 설명(지우세요)",
    "설명도 내부 분류도 없는 core 모듈", "사라진 core 모듈의 설명(지우세요)", "모듈이 설명과 내부 목록에 동시에 있음",
    "설명도 내부 분류도 없는 scripts", "사라진 스크립트의 설명(지우세요)",
    "결과 보는 곳 설명이 없는 자동 잡", "사라진 잡의 설명(지우세요)", "화면이 가리키는 잡이 존재하지 않음",
    "레지스트리에 설명이 없는 잡",
])
def test_coverage(category):
    items = coverage_problems(CONTENT).get(category, [])
    assert items == [], (
        f"[{category}] {len(items)}개: {items}\n"
        "→ hub/guide/content_*.py 를 고치세요. 목록 확인: python -m hub.guide.check"
    )


# ---------------------------------------------------------------------------
# UI/UX — 폰에서 찾기 쉬운 배치. 재배치는 해도 설명이 사라지면 안 된다.
# ---------------------------------------------------------------------------
def _content_texts(content):
    """content_*.py 에 적힌 사람이 쓴 문구를 전부 모은다(화면에 남아 있어야 하는 것들)."""
    out: list[str] = list(content.start_here)
    for p in content.pages:
        out += [p.summary, p.when_to_use, *p.steps, *p.reading, *p.cautions]
    for m in content.modules:
        out += [m.name, m.what, m.how_to_use, m.where_to_see] + ([m.cautions] if m.cautions else [])
    for s in content.scripts:
        out += [s.name, s.when_to_run, s.command, s.what_it_prints, s.risk]
    for j in content.jobs:
        out += [j.where_to_see] + ([j.if_alert] if j.if_alert else [])
    for t in content.glossary:
        out += [t.term, t.meaning] + ([t.why_it_matters] if t.why_it_matters else [])
    for r in content.routines:
        out += [r.title, r.when, *r.steps, *r.tips]
    for o in content.ops:
        out += [o.title, *o.body] + [x for pair in o.items for x in pair]
    return [x for x in out if str(x).strip()]


def test_no_content_disappears_from_the_page():
    """UI 를 바꿔도 사람이 쓴 설명은 한 글자도 화면에서 빠지지 않아야 한다."""
    page = render_guide_page()
    missing = [t for t in _content_texts(CONTENT) if html.escape(t) not in page]
    assert missing == [], f"렌더링에서 사라진 설명 {len(missing)}개: {missing[:5]}"


def test_every_section_has_a_tab_and_a_body():
    page = render_guide_page()
    for ident, tab, title, lead in SECTIONS:
        assert f'id="sec-{ident}"' in page, f"{ident} 섹션이 없습니다"
        assert f'data-sec="{ident}"' in page, f"{ident} 탭이 없습니다"
        assert html.escape(title) in page and html.escape(lead) in page
        assert html.escape(tab) in page
    assert page.count('<section class="sec"') == len(SECTIONS)


def test_sections_are_one_at_a_time_but_readable_without_js():
    """JS 가 돌면 한 섹션씩(폰), JS 가 없으면 전부 펼쳐진 한 장의 문서."""
    page = render_guide_page()
    assert 'document.documentElement.className="js"' in page
    assert "html.js main > section.sec { display:none; }" in page
    assert "html.js main > section.sec.on { display:block; }" in page
    # JS 없이 섹션을 숨기는 규칙이 있으면 안 된다.
    assert "\n  main > section.sec { display:none" not in page


def test_tables_stack_on_narrow_phones():
    page = render_guide_page()
    assert "@media (max-width:620px)" in page
    for table in re.findall(r"<table[^>]*>", page):
        assert 'class="stack"' in table, f"폰용 표 클래스가 없습니다: {table}"
    bare = [td for td in re.findall(r"<td(?![^>]*data-label)[^>]*>", page)]
    assert bare == [], f"data-label 없는 셀 {len(bare)}개 (폰에서 무슨 값인지 안 보입니다)"


def test_quick_entry_points_open_real_routines():
    """'바로 가기' 버튼은 실제로 존재하는 상황별 사용법 카드를 연다."""
    page = render_guide_page()
    targets = set(re.findall(r'data-open="(routine-[^"]+)"', page))
    assert targets, "과업 중심 진입점이 없습니다"
    for r in CONTENT.routines:
        assert f"routine-{r.id}" in targets
        assert f'id="routine-{r.id}"' in page


def test_search_box_covers_cards_and_table_rows():
    page = render_guide_page()
    assert 'id="q"' in page and 'id="qinfo"' in page
    assert "details.entry" in page and "tr.row" in page  # 검색 JS 가 두 가지를 모두 훑는다
    assert page.count('<details class="entry"') >= len(CONTENT.pages) + len(CONTENT.routines)
    assert page.count('<tr class="row"') >= len(CONTENT.glossary)


def test_no_external_assets_are_loaded():
    """허브는 stdlib 서버다. 외부 CDN·프레임워크를 끌어오면 안 된다."""
    page = render_guide_page()
    assert "<script src" not in page and "<link" not in page
    assert "@import" not in page
    # 설명 문구 안의 주소는 괜찮다. 태그가 바깥에서 무언가를 불러오는 것만 막는다.
    assert re.search(r'(src|href)="https?://', page) is None
