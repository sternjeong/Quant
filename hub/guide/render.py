"""설명서 HTML 렌더러. 모든 텍스트는 escape 한다(설명 문구에 < > & 가 들어가도 안전)."""

from __future__ import annotations

import html
from typing import Iterable

from hub.guide import live
from hub.guide.schema import GuideContent, ModuleGuide, PageGuide

E = html.escape

GUIDE_STYLE = """
<style>
  :root { color-scheme: dark; }
  * { box-sizing:border-box; }
  body { background:#0f1115; color:#e6e6e6; margin:0; line-height:1.6;
         font-family:-apple-system,"Segoe UI","Noto Sans KR",sans-serif; }
  .wrap { max-width:960px; margin:0 auto; padding:1.2rem 1rem 4rem; }
  a { color:#7aa2ff; }
  h1 { font-size:1.55rem; margin:.4rem 0 .2rem; }
  h2 { font-size:1.25rem; margin:2.2rem 0 .6rem; padding-top:.6rem; border-top:1px solid #2a2e37; }
  h3 { font-size:1.02rem; margin:0 0 .3rem; }
  p { margin:.35rem 0; }
  .sub { color:#9aa0a8; margin:0 0 1rem; }
  .meta { color:#8a919c; font-size:.8rem; }
  nav.toc { display:flex; flex-wrap:wrap; gap:.4rem; margin:.8rem 0 1rem; }
  nav.toc a { background:#181b21; border:1px solid #2a2e37; border-radius:999px; padding:.35rem .8rem;
              text-decoration:none; font-size:.85rem; color:#cfd6e4; }
  input.q { width:100%; padding:.75rem .9rem; background:#181b21; color:inherit; border:1px solid #2a2e37;
            border-radius:10px; font-size:1rem; margin:.4rem 0 .6rem; }
  details.entry { background:#181b21; border:1px solid #2a2e37; border-radius:12px; margin:.55rem 0; }
  details.entry > summary { cursor:pointer; padding:.8rem 1rem; list-style:none; }
  details.entry > summary::-webkit-details-marker { display:none; }
  details.entry > summary .t { font-weight:600; }
  details.entry > summary .s { display:block; color:#9aa0a8; font-size:.86rem; margin-top:.15rem; }
  details.entry[open] > summary { border-bottom:1px solid #2a2e37; }
  .body { padding:.7rem 1rem .9rem; }
  .body h4 { font-size:.82rem; color:#8fb0ff; margin:.9rem 0 .25rem; letter-spacing:.02em; }
  .body ul, .body ol { margin:.2rem 0 .2rem 1.1rem; padding:0; }
  .body li { margin:.2rem 0; }
  .pill { display:inline-block; font-size:.7rem; padding:.1rem .5rem; border-radius:999px; margin-left:.4rem;
          background:#26304a; color:#a9c0ff; font-weight:600; vertical-align:middle; }
  .pill.ok { background:#123d24; color:#4ade80; } .pill.off { background:#3d1212; color:#f87171; }
  .pill.warn { background:#4a3a12; color:#fbbf24; } .pill.mute { background:#2a2e37; color:#c9c9c9; }
  .stale { background:#3a2e12; border:1px solid #6b5416; color:#fbbf24; border-radius:8px; padding:.4rem .7rem;
           font-size:.82rem; margin:.5rem 0; }
  .callout { background:#141b2d; border:1px solid #2a3a63; border-radius:10px; padding:.7rem 1rem; margin:.7rem 0; }
  table { width:100%; border-collapse:collapse; font-size:.86rem; }
  th, td { text-align:left; padding:.5rem .5rem; border-bottom:1px solid #22262e; vertical-align:top; }
  th { color:#8a919c; font-weight:600; font-size:.78rem; }
  .scroll { overflow-x:auto; }
  code { background:#0b0d11; border:1px solid #2a2e37; border-radius:6px; padding:.05rem .35rem; font-size:.85em; }
  pre { background:#0b0d11; border:1px solid #2a2e37; border-radius:8px; padding:.6rem .8rem; overflow-x:auto;
        font-size:.83rem; margin:.4rem 0; }
  .risk-쓰기, .risk-주문 { color:#fbbf24; }
</style>
"""

FILTER_JS = """
<script>
(function(){
  var q=document.getElementById('q'); if(!q) return;
  q.addEventListener('input', function(){
    var t=q.value.trim().toLowerCase();
    document.querySelectorAll('details.entry').forEach(function(d){
      var hit = !t || d.textContent.toLowerCase().indexOf(t) !== -1;
      d.style.display = hit ? '' : 'none';
      if (t && hit) d.open = true;
    });
    document.querySelectorAll('tr.jobrow').forEach(function(r){
      r.style.display = (!t || r.textContent.toLowerCase().indexOf(t) !== -1) ? '' : 'none';
    });
  });
})();
</script>
"""


def _ul(items: Iterable[str], ordered: bool = False) -> str:
    items = [i for i in items if str(i).strip()]
    if not items:
        return ""
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{E(i)}</li>" for i in items) + f"</{tag}>"


def _section(title: str, body: str, ident: str) -> str:
    return f'<h2 id="{E(ident)}">{E(title)}</h2>{body}'


def _stale_notice(verified: str, paths: tuple[str, ...]) -> str:
    stale = live.is_stale(verified, paths)
    if stale:
        last = live.last_commit_date(paths)
        return (f'<div class="stale">⚠ 이 설명을 확인한 뒤({E(verified)}) 근거 코드가 수정됐습니다({E(str(last))}). '
                "내용이 조금 달라졌을 수 있으니 참고만 하세요.</div>")
    return ""


def _page_entry(g: PageGuide, title: str, icon: str) -> str:
    parts = [f'<h4>언제 쓰나</h4><p>{E(g.when_to_use)}</p>', f"<h4>사용 순서</h4>{_ul(g.steps, ordered=True)}"]
    if g.reading:
        parts.append(f"<h4>결과 읽는 법</h4>{_ul(g.reading)}")
    if g.cautions:
        parts.append(f"<h4>주의</h4>{_ul(g.cautions)}")
    if g.related_jobs:
        parts.append("<h4>이 화면의 데이터를 채우는 자동 잡</h4><p>" + ", ".join(f"<code>{E(j)}</code>" for j in g.related_jobs) + "</p>")
    parts.append(f'<p class="meta">확인일 {E(g.verified)} · 근거 {E(", ".join(g.sources)) or "-"}</p>')
    return (
        f'<details class="entry" id="page-{E(g.path)}"><summary><span class="t">{E(icon)} {E(title)}</span>'
        f'<span class="s">{E(g.summary)}</span></summary><div class="body">'
        f'{_stale_notice(g.verified, g.sources)}{"".join(parts)}</div></details>'
    )


_STATUS_PILL = {"운영중": "ok", "관측 전용": "warn", "실험": "warn", "도구": "mute", "보관": "mute"}


def _module_entry(m: ModuleGuide) -> str:
    parts = [f"<h4>하는 일</h4><p>{E(m.what)}</p>", f"<h4>어떻게 활용하나</h4><p>{E(m.how_to_use)}</p>",
             f"<h4>결과 보는 곳</h4><p>{E(m.where_to_see)}</p>"]
    if m.cautions:
        parts.append(f"<h4>주의</h4><p>{E(m.cautions)}</p>")
    parts.append(f'<p class="meta"><code>{E(m.module)}</code> · 확인일 {E(m.verified)}</p>')
    return (
        f'<details class="entry"><summary><span class="t">{E(m.name)}</span>'
        f'<span class="pill {_STATUS_PILL.get(m.status, "mute")}">{E(m.status)}</span>'
        f'<span class="s">{E(m.what.split(chr(10))[0][:90])}</span></summary><div class="body">'
        f'{_stale_notice(m.verified, (m.module, *m.sources))}{"".join(parts)}</div></details>'
    )


def render_guide(content: GuideContent) -> str:
    nav = live.navigation()
    page_by_path = {p.path: p for p in content.pages}
    job_extra = {j.job_id: j for j in content.jobs}
    ver = live.deployed_version()
    ver_text = f'{ver["sha"]} · {ver["date"]}' if ver.get("available") else "버전 확인 불가"

    toc = [("start", "처음 보는 분"), ("routines", "상황별 사용법"), ("screens", "화면 안내"), ("jobs", "자동 잡"),
           ("modules", "엔진 모듈"), ("scripts", "운영 도구"), ("ops", "운영·알림"), ("glossary", "용어집"), ("changes", "최근 변경")]
    out = [
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">',
        f"<title>Quant 사용 설명서</title>{GUIDE_STYLE}</head><body><div class=\"wrap\">",
        '<p><a href="/">&larr; 관제 센터로</a></p><h1>📖 Quant 사용 설명서</h1>',
        f'<p class="sub">이 서버에서 돌아가는 퀀트 대시보드와 엔진을 어떻게 쓰는지, 각 부분이 무엇인지 정리한 안내서입니다. '
        f'화면·잡·최근 변경은 코드에서 자동으로 읽어 오므로 항상 현재 상태입니다. 배포 버전 <code>{E(ver_text)}</code></p>',
        '<nav class="toc">' + "".join(f'<a href="#{i}">{E(t)}</a>' for i, t in toc) + "</nav>",
        '<input id="q" class="q" type="search" placeholder="🔎 검색 (예: 챔피언, PIT, 백업, 텔레그램)" autocomplete="off">',
    ]

    # 처음 보는 분
    start = "".join(f"<p>{E(p)}</p>" for p in content.start_here) or "<p>준비 중입니다.</p>"
    out.append(_section("처음 보는 분을 위한 안내", f'<div class="callout">{start}</div>', "start"))

    # 상황별 사용법
    r_html = []
    for r in content.routines:
        tips = f"<h4>팁</h4>{_ul(r.tips)}" if r.tips else ""
        r_html.append(
            f'<details class="entry"><summary><span class="t">{E(r.title)}</span><span class="s">{E(r.when)}</span></summary>'
            f'<div class="body"><h4>순서</h4>{_ul(r.steps, ordered=True)}{tips}</div></details>'
        )
    out.append(_section("상황별 사용법", "".join(r_html) or "<p>준비 중입니다.</p>", "routines"))

    # 화면 안내 (업무공간별, 자동 목록)
    s_html = []
    for ws, pages in nav.items():
        s_html.append(f'<h3 style="margin-top:1.1rem">{E(ws)}</h3>')
        for path, title, icon in pages:
            g = page_by_path.get(path)
            if g:
                s_html.append(_page_entry(g, title, icon))
            else:
                s_html.append(f'<details class="entry"><summary><span class="t">{E(icon)} {E(title)}</span>'
                              '<span class="pill warn">설명 준비 중</span></summary></details>')
    out.append(_section("화면 안내", "".join(s_html), "screens"))

    # 자동 잡 표
    rows = []
    for r in live.job_rows():
        st = ('<span class="pill ok">켜짐</span>' if r.enabled else
              '<span class="pill off">꺼짐</span>' if r.enabled is False else '<span class="pill mute">?</span>')
        ex = job_extra.get(r.job_id)
        see = E(ex.where_to_see) if ex else "-"
        alert = f"<br><span class='meta'>알림이 오면: {E(ex.if_alert)}</span>" if ex and ex.if_alert else ""
        rows.append(
            f'<tr class="jobrow"><td>{E(r.when_text)}</td><td><b>{E(r.label)}</b>{st}<br>'
            f'<span class="meta">{E(r.description)}</span></td><td>{E(r.category)}</td><td>{see}{alert}</td></tr>'
        )
    jobs_html = ('<p class="meta">스케줄러가 시간이 되면 스스로 실행합니다. 켜짐/꺼짐은 지금 서버의 실제 설정입니다'
                 ' (텔레그램 <code>/processes</code> 로 바꿀 수 있습니다).</p><div class="scroll"><table>'
                 '<tr><th>실행 시각</th><th>잡</th><th>분류</th><th>결과 보는 곳</th></tr>' + "".join(rows) + "</table></div>")
    out.append(_section("자동으로 도는 잡", jobs_html, "jobs"))

    # 엔진 모듈 (그룹별)
    m_html = []
    for group in sorted({m.group for m in content.modules}):
        m_html.append(f'<h3 style="margin-top:1.1rem">{E(group)}</h3>')
        m_html.extend(_module_entry(m) for m in sorted((m for m in content.modules if m.group == group), key=lambda x: x.name))
    out.append(_section("엔진 모듈", "".join(m_html) or "<p>준비 중입니다.</p>", "modules"))

    # 스크립트
    sc = []
    for s in content.scripts:
        sc.append(
            f'<details class="entry"><summary><span class="t">{E(s.name)}</span>'
            f'<span class="pill {"warn" if s.risk != "읽기 전용" else "ok"}">{E(s.risk)}</span>'
            f'<span class="s">{E(s.when_to_run)}</span></summary><div class="body">'
            f'{_stale_notice(s.verified, (s.path,))}<h4>실행</h4><pre>{E(s.command)}</pre>'
            f'<h4>결과 읽는 법</h4><p>{E(s.what_it_prints)}</p>'
            f'<p class="meta"><code>{E(s.path)}</code> · 확인일 {E(s.verified)}</p></div></details>'
        )
    out.append(_section("운영 도구", "".join(sc) or "<p>준비 중입니다.</p>", "scripts"))

    # 운영
    ops = []
    for o in content.ops:
        items = ("<table>" + "".join(f"<tr><td><code>{E(a)}</code></td><td>{E(b)}</td></tr>" for a, b in o.items) + "</table>") if o.items else ""
        ops.append(
            f'<details class="entry"><summary><span class="t">{E(o.title)}</span></summary><div class="body">'
            f'{"".join(f"<p>{E(p)}</p>" for p in o.body)}{items}<p class="meta">확인일 {E(o.verified)}</p></div></details>'
        )
    out.append(_section("운영·알림", "".join(ops) or "<p>준비 중입니다.</p>", "ops"))

    # 용어집
    g = "".join(
        f'<tr><td><b>{E(t.term)}</b></td><td>{E(t.meaning)}'
        f'{("<br><span class=meta>" + E(t.why_it_matters) + "</span>") if t.why_it_matters else ""}</td></tr>'
        for t in sorted(content.glossary, key=lambda x: x.term)
    )
    out.append(_section("용어집", f'<div class="scroll"><table>{g}</table></div>' if g else "<p>준비 중입니다.</p>", "glossary"))

    # 최근 변경
    ch = live.recent_changes(25)
    ch_html = ("<div class=\"scroll\"><table><tr><th>날짜</th><th>커밋</th><th>내용</th></tr>" +
               "".join(f"<tr><td>{E(c['date'])}</td><td><code>{E(c['sha'])}</code></td><td>{E(c['subject'])}</td></tr>" for c in ch) +
               "</table></div>") if ch else "<p class=\"meta\">이 서버에서는 변경 내역(git)을 읽을 수 없습니다.</p>"
    out.append(_section("최근 변경", '<p class="meta">엔진이 업데이트되면 여기에 자동으로 나타납니다.</p>' + ch_html, "changes"))

    out.append(f'<p class="meta" style="margin-top:2.5rem">이 설명서는 화면·잡·변경 내역을 코드에서 자동으로 읽고, '
               f'나머지 설명은 코드와 대조한 날짜(확인일)를 표시합니다. 근거 코드가 그 뒤에 바뀌면 ⚠ 표시가 뜹니다.</p>')
    out.append(f"</div>{FILTER_JS}</body></html>")
    return "".join(out)
