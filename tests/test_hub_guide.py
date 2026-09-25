"""관제 센터 사용 설명서가 엔진과 어긋나지 않게 막는 테스트.

- 형식 테스트: 이미 적힌 항목이 올바른가. 항목을 쓰는 사람이 자기 몫을 검증할 때도 쓴다.
- coverage 테스트: 새 화면/잡/core 모듈/스크립트에 설명이 있는가, 사라진 것의 설명이 남아 있지 않은가.
  이 테스트가 실패하면 hub/guide/content_*.py 를 고쳐야 한다(`python -m hub.guide.check` 로 목록 확인).
  자동배포의 테스트 관문이 pytest 를 돌리므로, 설명이 어긋난 채로는 배포되지 않는다.
"""

from __future__ import annotations

import html
import json
import re
from urllib.parse import quote, unquote

import pytest

from hub.guide import build_content, live
from hub.guide.check import coverage_problems
from hub.guide.render import (
    all_routes, app_base_url, render_guide, render_route, screen_slug, streamlit_url_path, term_slug,
)
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
def _route(path, content=CONTENT, query=None):
    return render_route(path, query or {}, content)


def test_guide_renders_with_live_sections():
    """자동 생성 부분(화면 목록·잡 이름·시각·켜짐/꺼짐)이 새 하위 페이지에 그대로 나온다."""
    status, _, home = _route("/guide")
    assert status == 200 and "<title>사용 설명서 · Quant 관제 센터</title>" in home
    _, _, screens = _route("/guide/screens")
    for _, title, _ in (item for pages in live.navigation().values() for item in pages):
        assert html.escape(title) in screens
    _, _, jobs = _route("/guide/jobs")
    for job in live.job_rows():
        assert html.escape(job.label) in jobs
        assert html.escape(job.when_text) in jobs
    assert "켜짐" in jobs
    for path in ("/guide", "/guide/screens", "/guide/jobs"):
        assert 'name="viewport"' in _route(path)[2]  # 폰에서 보는 화면이라 필수


def test_every_guide_route_renders_with_viewport():
    routes = all_routes(CONTENT)
    assert len(routes) > 100
    for path in routes:
        status, ctype, page = _route(path)
        assert status == 200, path
        assert ctype.startswith("text/html"), path
        assert 'name="viewport"' in page, path
        assert 'href="/guide"' in page, path  # 설명서 첫 화면으로 돌아가는 길(경로·내비게이션)


def test_route_counts_cover_every_item():
    routes = set(all_routes(CONTENT))
    assert {f"/guide/screens/{screen_slug(p)}" for p in live.navigation_paths()} <= routes
    assert {f"/guide/jobs/{j}" for j in live.job_ids()} <= routes
    assert len([r for r in routes if r.startswith("/guide/modules/")]) == len(CONTENT.modules)
    assert len([r for r in routes if r.startswith("/guide/tools/")]) == len(CONTENT.scripts)
    assert len([r for r in routes if r.startswith("/guide/tasks/")]) == len(CONTENT.routines)


@pytest.mark.parametrize("path", [
    "/guide/nope", "/guide/screens/없는화면", "/guide/jobs/no_such_job", "/guide/modules/no_such", "/guide/tools/no_such",
    "/guide/ops/no_such", "/guide/tasks/no_such", "/guide/screens/today/extra",
])
def test_unknown_guide_items_are_404(path):
    status, _, page = _route(path)
    assert status == 404
    assert 'name="viewport"' in page


def test_task_screen_links_point_only_to_navigation_items():
    nav = live.navigation_paths()
    nav_slugs = {screen_slug(p) for p in nav}
    app = app_base_url()
    for r in CONTENT.routines:
        _, _, page = _route(f"/guide/tasks/{r.id}")
        for target in re.findall(r'data-screen="([^"]+)"', page):
            assert html.unescape(target) in nav, (r.id, target)
        for slug in re.findall(r'href="/guide/screens/([^"#]+)"', page):
            assert unquote(slug) in nav_slugs, (r.id, slug)
        if app:
            for url in re.findall(r'href="(' + re.escape(app) + r'[^"]*)"', page):
                tail = unquote(url[len(app):])
                assert tail == "" or tail in nav_slugs, (r.id, url)
    # 아침 루틴은 실제로 화면 링크를 단다(감지 규칙이 깨지면 여기서 드러난다)
    assert "data-screen=" in _route("/guide/tasks/daily-5min")[2]


def test_streamlit_url_paths_match_streamlit_rules():
    source_util = pytest.importorskip("streamlit.source_util")
    from pathlib import Path

    for path in live.navigation_paths():
        assert streamlit_url_path(path) == source_util.page_icon_and_name(Path(path))[1], path


def test_search_index_contains_every_item():
    status, ctype, body = _route("/guide/search.json")
    assert status == 200 and ctype.startswith("application/json")
    index = json.loads(body)
    urls = {e["u"] for e in index}
    for path in all_routes(CONTENT):
        if path.count("/") == 3:  # 항목 상세(/guide/<구역>/<항목>)
            assert quote(path, safe="/") in urls, path
    for t in CONTENT.glossary:
        assert any(e["k"] == "용어" and e["t"] == t.term for e in index), t.term
    assert all(e["h"] == e["h"].lower() for e in index)


def test_server_side_search_finds_items():
    _, _, page = _route("/guide/search", query={"q": ["백업"]})
    assert "검색 결과" in page and "/guide/ops/backup" in page
    _, _, empty = _route("/guide/search", query={"q": ["zzzz없는낱말"]})
    assert "찾는 항목이 없습니다" in empty


def test_glossary_terms_link_on_first_use():
    _, _, page = _route("/guide/tasks/read-research-infra")
    assert 'class="term"' in page and "/guide/glossary#" in page
    _, _, glossary = _route("/guide/glossary")
    for t in CONTENT.glossary:
        assert f'id="{term_slug(t.term)}"' in glossary


def test_guide_text_is_html_escaped():
    evil = "<script>alert(1)</script>"
    content = GuideContent(
        pages=(PageGuide(path="views/today.py", summary=evil, when_to_use=evil, steps=(evil,), cautions=(evil,),
                         reading=(evil,), plain_summary=evil, example=evil, verified="2026-01-01"),),
        modules=(ModuleGuide(module="core/db.py", name=evil, group="운용", status="운영중", what=evil, how_to_use=evil,
                             where_to_see=evil, cautions=evil, verified="2026-01-01"),),
        scripts=(ScriptGuide(path="scripts/agent_batch.py", name=evil, when_to_run=evil, command=evil, risk="읽기 전용",
                             what_it_prints=evil, verified="2026-01-01"),),
        jobs=(JobGuide(job_id=sorted(live.job_ids())[0], where_to_see=evil, if_alert=evil, verified="2026-01-01"),),
        glossary=(Term(evil, evil, evil),),
        routines=(Routine("r", evil, evil, (evil + " '오늘' " + evil,), (evil,), card_title=evil, icon=evil, plain_summary=evil),),
        ops=(OpsSection("o", evil, (evil,), ((evil, evil),), "2026-01-01"),), start_here=(evil,),
    )
    pages = [render_guide(content)] + [render_route(p, {}, content)[2] for p in all_routes(content)]
    pages.append(render_route("/guide/search", {"q": ["script"]}, content)[2])
    pages.append(render_route("/guide/search.json", {}, content)[2])
    for page in pages:
        assert "<script>alert(1)" not in page
    joined = "".join(pages)
    assert "&lt;script&gt;alert(1)" in joined


def test_stale_marker_appears_when_source_changed_after_verified(monkeypatch):
    monkeypatch.setattr(live, "last_commit_date", lambda paths: "2026-09-20")
    content = GuideContent(pages=(PageGuide(path="views/today.py", summary="s", when_to_use="w", steps=("a",),
                                            sources=("core/db.py",), verified="2026-09-01"),))
    slug = screen_slug("views/today.py")
    assert "근거 코드가 수정됐습니다" in render_route(f"/guide/screens/{slug}", {}, content)[2]
    assert "코드 변경됨" in render_route("/guide/screens", {}, content)[2]  # 목록에도 표시
    monkeypatch.setattr(live, "last_commit_date", lambda paths: "2026-08-01")
    assert "근거 코드가 수정됐습니다" not in render_route(f"/guide/screens/{slug}", {}, content)[2]
    assert "코드 변경됨" not in render_route("/guide/screens", {}, content)[2]


def test_guide_home_shows_status_tasks_and_version():
    _, _, page = _route("/guide")
    assert 'class="verdict' in page  # 관제 센터와 같은 판정
    for r in CONTENT.routines:
        assert f'href="/guide/tasks/{r.id}"' in page
    assert 'id="gd-q"' in page and "/guide/search" in page
    assert "배포 버전" in page


def test_guide_http_routes():
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import urlopen
    from urllib.error import HTTPError

    from hub import server

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.HubRequestHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with urlopen(base + "/guide/screens/" + quote(screen_slug("pages/11_챔피언_전략.py"))) as r:
            assert r.status == 200 and "챔피언" in r.read().decode()
        with urlopen(base + "/guide/search.json") as r:
            assert r.headers["Content-Type"].startswith("application/json")
        with pytest.raises(HTTPError) as exc:
            urlopen(base + "/guide/screens/nope")
        assert exc.value.code == 404
    finally:
        httpd.shutdown()


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
