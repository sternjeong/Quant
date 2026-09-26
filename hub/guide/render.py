"""설명서 HTML 렌더러. 모든 텍스트는 escape 한다(설명 문구에 < > & 가 들어가도 안전).

화면 구성(자세한 이유는 hub/guide/ui.py):
  상단 고정 바(검색 + 섹션 탭) → 과업 진입점 → 섹션 하나씩. 폰에서 한 화면에 한 가지만 보이게 한다.
  내용 자체는 content_*.py 와 live.py 에서 그대로 가져온다. 여기서는 배치와 표시만 정한다.
"""

from __future__ import annotations

import html
from typing import Iterable

from hub.guide import live
from hub.guide.schema import GuideContent, ModuleGuide, PageGuide
from hub.guide.ui import GUIDE_JS, GUIDE_STYLE, JS_FLAG

E = html.escape

# 섹션 탭: (id, 탭 이름, 섹션 제목, 한 줄 안내)
SECTIONS = (
    ("start", "시작", "처음 보는 분을 위한 안내", "이 시스템이 무엇이고 무엇부터 보면 되는지."),
    ("routines", "이럴 땐", "상황별 사용법", "'지금 이거 어떻게 하더라' 할 때 순서대로 따라 하는 곳."),
    ("screens", "화면", "화면 안내", "대시보드의 각 화면을 언제 열고 무엇을 보나. 목록은 코드에서 자동으로 읽습니다."),
    ("jobs", "자동 잡", "자동으로 도는 잡", "서버가 스스로 돌리는 작업과 결과 보는 곳. 시각·켜짐 상태는 지금 서버의 실제 설정입니다."),
    ("modules", "엔진", "엔진 모듈", "계산·판단을 담당하는 부분들. 그룹으로 좁혀 보세요."),
    ("scripts", "도구", "운영 도구", "필요할 때 직접 실행하는 명령."),
    ("ops", "운영", "운영·알림", "텔레그램 명령, 알림 읽는 법, 백업, 배포, 문제 해결."),
    ("glossary", "용어", "용어집", "모르는 말이 나왔을 때."),
    ("changes", "변경", "최근 변경", "엔진이 업데이트되면 여기에 자동으로 나타납니다."),
)


def _ul(items: Iterable[str], ordered: bool = False) -> str:
    items = [i for i in items if str(i).strip()]
    if not items:
        return ""
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{E(i)}</li>" for i in items) + f"</{tag}>"


def _stale_notice(verified: str, paths: tuple[str, ...]) -> str:
    stale = live.is_stale(verified, paths)
    if stale:
        last = live.last_commit_date(paths)
        return (f'<div class="stale">⚠ 이 설명을 확인한 뒤({E(verified)}) 근거 코드가 수정됐습니다({E(str(last))}). '
                "내용이 조금 달라졌을 수 있으니 참고만 하세요.</div>")
    return ""


def _entry(summary: str, body: str, ident: str = "", extra: str = "") -> str:
    """접었다 펴는 카드 하나. 카드 단위가 곧 검색 단위다."""
    ident_attr = f' id="{E(ident)}"' if ident else ""
    return (f'<details class="entry"{ident_attr}{extra}><summary>{summary}</summary>'
            f'<div class="body">{body}</div></details>')


def _page_entry(g: PageGuide, title: str, icon: str) -> str:
    parts = [f'<h4>언제 쓰나</h4><p>{E(g.when_to_use)}</p>', f"<h4>사용 순서</h4>{_ul(g.steps, ordered=True)}"]
    if g.reading:
        parts.append(f"<h4>결과 읽는 법</h4>{_ul(g.reading)}")
    if g.cautions:
        parts.append(f"<h4>주의</h4>{_ul(g.cautions)}")
    if g.related_jobs:
        parts.append("<h4>이 화면의 데이터를 채우는 자동 잡</h4><p>"
                     + ", ".join(f"<code>{E(j)}</code>" for j in g.related_jobs) + "</p>")
    parts.append(f'<p class="meta">확인일 {E(g.verified)} · 근거 {E(", ".join(g.sources)) or "-"}</p>')
    summary = (f'<span class="t">{E(icon)} {E(title)}</span><span class="s">{E(g.summary)}</span>')
    return _entry(summary, _stale_notice(g.verified, g.sources) + "".join(parts), f"page-{g.path}")


_STATUS_PILL = {"운영중": "ok", "관측 전용": "warn", "실험": "warn", "도구": "mute", "보관": "mute"}


def _module_entry(m: ModuleGuide) -> str:
    parts = [f"<h4>하는 일</h4><p>{E(m.what)}</p>", f"<h4>어떻게 활용하나</h4><p>{E(m.how_to_use)}</p>",
             f"<h4>결과 보는 곳</h4><p>{E(m.where_to_see)}</p>"]
    if m.cautions:
        parts.append(f"<h4>주의</h4><p>{E(m.cautions)}</p>")
    parts.append(f'<p class="meta"><code>{E(m.module)}</code> · 확인일 {E(m.verified)}</p>')
    summary = (f'<span class="t">{E(m.name)}</span>'
               f'<span class="pill {_STATUS_PILL.get(m.status, "mute")}">{E(m.status)}</span>'
               f'<span class="s">{E(m.what.split(chr(10))[0][:90])}</span>')
    body = _stale_notice(m.verified, (m.module, *m.sources)) + "".join(parts)
    return _entry(summary, body, extra=f' data-group-of="{E(m.group)}"')


def _section(ident: str, title: str, lead: str, body: str) -> str:
    return (f'<section class="sec" id="sec-{E(ident)}"><h2 id="{E(ident)}">{E(title)}</h2>'
            f'<p class="sec-lead">{E(lead)}</p>{body}</section>')


def _table(head: tuple[str, ...], rows: Iterable[str]) -> str:
    """폰에서는 카드처럼 쌓이는 표(td 에 data-label 필요)."""
    th = "".join(f"<th>{E(h)}</th>" for h in head)
    return f'<div class="scroll"><table class="stack"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _quick_links(content: GuideContent) -> str:
    """과업 중심 진입점. 문구는 content 의 상황별 사용법에서 그대로 온다(손으로 적지 않는다)."""
    quick = "".join(
        f'<button type="button" data-goto="routines" data-open="routine-{E(r.id)}">{E(r.title)}</button>'
        for r in content.routines
    )
    return f'<p class="meta">이럴 때 뭘 누르나</p><div class="quick">{quick}</div>' if quick else ""


def _start_body(content: GuideContent, ver_text: str) -> str:
    text = "".join(f"<p>{E(p)}</p>" for p in content.start_here) or "<p>준비 중입니다.</p>"
    how = ("<h4>이 설명서 쓰는 법</h4><ul>"
           "<li>맨 위 검색창에 아는 단어를 넣으면 모든 섹션에서 한꺼번에 찾습니다.</li>"
           "<li>검색창 아래 탭으로 원하는 묶음만 봅니다. 카드를 누르면 자세한 설명이 펼쳐집니다.</li>"
           "<li>화면 목록·자동 잡·최근 변경·배포 버전은 코드에서 그때그때 읽어 오므로 항상 현재 상태입니다.</li>"
           "</ul>")
    return (f'{_quick_links(content)}<div class="callout">{text}</div>{how}'
            f'<p class="meta">배포 버전 <code style="white-space:nowrap">{E(ver_text)}</code></p>')


def _routines_body(content: GuideContent) -> str:
    out = []
    for r in content.routines:
        tips = f"<h4>팁</h4>{_ul(r.tips)}" if r.tips else ""
        summary = f'<span class="t">{E(r.title)}</span><span class="s">{E(r.when)}</span>'
        out.append(_entry(summary, f"<h4>순서</h4>{_ul(r.steps, ordered=True)}{tips}", f"routine-{r.id}"))
    return "".join(out) or "<p>준비 중입니다.</p>"


def _screens_body(content: GuideContent) -> str:
    page_by_path = {p.path: p for p in content.pages}
    out = []
    for ws, pages in live.navigation().items():
        out.append(f"<h3>{E(ws)}</h3>")
        for path, title, icon in pages:
            g = page_by_path.get(path)
            if g:
                out.append(_page_entry(g, title, icon))
            else:
                out.append(_entry(f'<span class="t">{E(icon)} {E(title)}</span>'
                                  '<span class="pill warn">설명 준비 중</span>',
                                  "<p>아직 설명이 없습니다.</p>"))
    return "".join(out)


def _jobs_body(content: GuideContent) -> str:
    job_extra = {j.job_id: j for j in content.jobs}
    rows = []
    for r in live.job_rows():
        st = ('<span class="pill ok">켜짐</span>' if r.enabled else
              '<span class="pill off">꺼짐</span>' if r.enabled is False else '<span class="pill mute">?</span>')
        ex = job_extra.get(r.job_id)
        see = E(ex.where_to_see) if ex else "-"
        alert = f"<br><span class='meta'>알림이 오면: {E(ex.if_alert)}</span>" if ex and ex.if_alert else ""
        rows.append(
            f'<tr class="row"><td data-label="실행 시각">{E(r.when_text)}</td>'
            f'<td data-label="잡"><b>{E(r.label)}</b>{st}<br><span class="meta">{E(r.description)}</span></td>'
            f'<td data-label="분류">{E(r.category)}</td>'
            f'<td data-label="결과 보는 곳">{see}{alert}</td></tr>'
        )
    note = ('<p class="meta">켜짐/꺼짐은 텔레그램 <code>/processes</code> 로 바꿀 수 있습니다.</p>')
    return note + _table(("실행 시각", "잡", "분류", "결과 보는 곳"), rows)


def _modules_body(content: GuideContent) -> str:
    groups = sorted({m.group for m in content.modules})
    if not groups:
        return "<p>준비 중입니다.</p>"
    chips = ['<div class="chips"><button type="button" data-group="*" class="on">'
             f"전체 {len(content.modules)}</button>"]
    out = []
    for group in groups:
        mods = sorted((m for m in content.modules if m.group == group), key=lambda x: x.name)
        chips.append(f'<button type="button" data-group="{E(group)}">{E(group)} {len(mods)}</button>')
        out.append(f'<h3 data-group-of="{E(group)}">{E(group)}</h3>')
        out.extend(_module_entry(m) for m in mods)
    chips.append("</div>")
    return "".join(chips) + "".join(out)


def _scripts_body(content: GuideContent) -> str:
    out = []
    for s in content.scripts:
        summary = (f'<span class="t">{E(s.name)}</span>'
                   f'<span class="pill {"warn" if s.risk != "읽기 전용" else "ok"}">{E(s.risk)}</span>'
                   f'<span class="s">{E(s.when_to_run)}</span>')
        body = (f'{_stale_notice(s.verified, (s.path,))}<h4>실행</h4><pre>{E(s.command)}</pre>'
                f'<h4>결과 읽는 법</h4><p>{E(s.what_it_prints)}</p>'
                f'<p class="meta"><code>{E(s.path)}</code> · 확인일 {E(s.verified)}</p>')
        out.append(_entry(summary, body))
    return "".join(out) or "<p>준비 중입니다.</p>"


def _ops_body(content: GuideContent) -> str:
    out = []
    for o in content.ops:
        items = _table(("이름", "설명"),
                       [f'<tr class="row"><td data-label="이름"><code>{E(a)}</code></td>'
                        f'<td data-label="설명">{E(b)}</td></tr>' for a, b in o.items]) if o.items else ""
        body = "".join(f"<p>{E(p)}</p>" for p in o.body) + items + f'<p class="meta">확인일 {E(o.verified)}</p>'
        out.append(_entry(f'<span class="t">{E(o.title)}</span>', body, f"ops-{o.id}"))
    return "".join(out) or "<p>준비 중입니다.</p>"


def _glossary_body(content: GuideContent) -> str:
    rows = [
        f'<tr class="row"><td data-label="용어"><b>{E(t.term)}</b></td><td data-label="뜻">{E(t.meaning)}'
        f'{("<br><span class=meta>" + E(t.why_it_matters) + "</span>") if t.why_it_matters else ""}</td></tr>'
        for t in sorted(content.glossary, key=lambda x: x.term)
    ]
    return _table(("용어", "뜻"), rows) if rows else "<p>준비 중입니다.</p>"


def _changes_body() -> str:
    ch = live.recent_changes(25)
    if not ch:
        return '<p class="meta">이 서버에서는 변경 내역(git)을 읽을 수 없습니다.</p>'
    rows = [f'<tr class="row"><td data-label="날짜">{E(c["date"])}</td>'
            f'<td data-label="커밋"><code>{E(c["sha"])}</code></td>'
            f'<td data-label="내용">{E(c["subject"])}</td></tr>' for c in ch]
    return _table(("날짜", "커밋", "내용"), rows)


def _count(body: str) -> int:
    """탭에 붙일 항목 수. 카드가 있으면 카드 수, 표만 있는 섹션이면 줄 수."""
    cards = body.count('<details class="entry"')
    return cards or body.count('<tr class="row"')


def render_guide(content: GuideContent) -> str:
    ver = live.deployed_version()
    ver_text = f'{ver["sha"]} · {ver["date"]}' if ver.get("available") else "버전 확인 불가"

    bodies = {
        "start": _start_body(content, ver_text),
        "routines": _routines_body(content),
        "screens": _screens_body(content),
        "jobs": _jobs_body(content),
        "modules": _modules_body(content),
        "scripts": _scripts_body(content),
        "ops": _ops_body(content),
        "glossary": _glossary_body(content),
        "changes": _changes_body(),
    }

    tabs = []
    for ident, tab, _title, _lead in SECTIONS:
        n = _count(bodies[ident])
        num = f'<span class="n">{n}</span>' if n else ""
        tabs.append(f'<a href="#{E(ident)}" data-sec="{E(ident)}">{E(tab)}{num}</a>')

    out = [
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">',
        f"<title>Quant 사용 설명서</title>{JS_FLAG}{GUIDE_STYLE}</head><body><div class=\"wrap\">",
        '<p class="meta"><a href="/">&larr; 관제 센터로</a></p><h1>📖 Quant 사용 설명서</h1>',
        '<p class="sub">이 서버의 퀀트 대시보드와 엔진 사용법입니다. 찾는 말을 검색하거나, 아래 탭에서 골라 보세요.</p>',
        '<div class="bar">',
        '<input id="q" class="q" type="search" placeholder="🔎 검색 (예: 챔피언, PIT, 백업, 텔레그램)" autocomplete="off">',
        '<nav class="tabs">' + "".join(tabs) + "</nav>",
        "</div>",
        '<p id="qinfo"></p>',
        "<main>",
    ]
    for ident, _tab, title, lead in SECTIONS:
        out.append(_section(ident, title, lead, bodies[ident]))
    out.append("</main>")
    out.append('<p class="meta" style="margin-top:2.5rem">이 설명서는 화면·잡·변경 내역을 코드에서 자동으로 읽고, '
               '나머지 설명은 코드와 대조한 날짜(확인일)를 표시합니다. 근거 코드가 그 뒤에 바뀌면 ⚠ 표시가 뜹니다.</p>')
    out.append('<button type="button" id="totop" class="totop" title="맨 위로">↑</button>')
    out.append(f"</div>{GUIDE_JS}</body></html>")
    return "".join(out)
