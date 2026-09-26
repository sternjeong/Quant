"""설명서 HTML 렌더러 — 과업 중심 첫 화면 + 하위 페이지(화면·잡·모듈·도구·운영·용어·변경) + 검색.

구조와 이유는 docs/HUB_GUIDE_UX_STRATEGY.md. 모양은 관제 센터 공통 디자인(hub/ui.py)을 쓰고,
설명서에만 필요한 부품(할 일 타일·단계 카드·용어 풀이 시트)만 GUIDE_CSS 로 조금 더한다(ui.py 색 변수 사용).

- 모든 텍스트는 escape 한다(설명 문구에 < > & 가 들어가도 안전). 이미 escape 된 조각을 받는 인자는 *_html.
- 자동 생성 부분(화면 목록·잡 시각·켜짐/꺼짐·최근 변경·배포 버전)은 hub/guide/live.py 에서 매번 읽는다.
- 확인일과 낡음 경고(근거 코드가 확인일 뒤에 바뀜)는 상세 페이지에, 목록에는 '코드 변경됨' 알약으로 보인다.
- 진입점: render_route(path, query) -> (HTTP 상태, Content-Type, 본문). hub/server.py 의 /guide* 라우트가 부른다.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import quote

from hub import ui
from hub.guide import live
from hub.guide.schema import GuideContent, ModuleGuide, OpsSection, Routine, ScriptGuide, Term

E = html.escape
HTML = "text/html; charset=utf-8"
JSON = "application/json; charset=utf-8"

# ---------------------------------------------------------------------------
# 설명서 전용 부품 CSS(최소) — 색은 hub/ui.py 변수만 쓴다
# ---------------------------------------------------------------------------
GUIDE_CSS = """<style>
[hidden]{display:none!important}
.gd-search{margin:6px 0 4px}
.gd-search input{width:100%;min-height:48px;padding:0 14px;background:var(--surface);border:1px solid var(--border-2);
  border-radius:var(--radius-sm);font-size:1rem;outline:none;-webkit-appearance:none;appearance:none}
.gd-search input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.gd-search input::placeholder{color:var(--text-3)}
#gd-results{margin:8px 0 0} #gd-results .meta{margin:4px 2px 8px}
.gd-tasks{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
@media(min-width:720px){.gd-tasks{grid-template-columns:repeat(4,minmax(0,1fr))}}
.gd-task{display:flex;flex-direction:column;gap:5px;min-height:100px;padding:14px;background:var(--surface);
  border:1px solid var(--border);border-radius:var(--radius);min-width:0}
.gd-task:hover{background:var(--surface-2);border-color:var(--border-2)} .gd-task:active{background:var(--surface-3)}
.gd-task .i{font-size:1.35rem;line-height:1.1}
.gd-task .t{font-weight:650;font-size:.95rem;letter-spacing:-.01em;line-height:1.3}
.gd-task .d{color:var(--text-2);font-size:.78rem;line-height:1.4;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.gd-task.hot{border-color:rgba(240,97,109,.5);background:linear-gradient(180deg,rgba(240,97,109,.08),var(--surface) 70%)}
.gd-steps{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}
.gd-step{display:flex;gap:12px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px}
.gd-step .n{flex:0 0 auto;width:28px;height:28px;border-radius:50%;display:grid;place-items:center;background:var(--accent-soft);
  color:var(--accent);font-weight:700;font-size:.85rem;margin-top:1px}
.gd-step .c{flex:1 1 auto;min-width:0} .gd-step .c p{margin:0}
.gd-steps.compact .gd-step{padding:12px 14px}
.gd-acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.gd-acts .btn,.gd-btns .btn{min-height:44px}
.gd-btns{display:flex;flex-wrap:wrap;gap:8px;margin:4px 0 14px}
.gd-body{overflow-wrap:anywhere}
.gd-body ul{margin:.2rem 0;padding-left:1.15rem} .gd-body li{margin:.35rem 0}
.gd-body pre{white-space:pre-wrap;word-break:break-word}
.gd-body .panel p + p{margin-top:.6rem}
a.term{color:inherit;text-decoration:underline dotted var(--accent);text-decoration-thickness:1.5px;text-underline-offset:3px}
.gd-sheet{position:fixed;left:0;right:0;bottom:0;z-index:30;background:var(--surface-2);border-top:1px solid var(--border-2);
  border-radius:16px 16px 0 0;padding:18px 16px calc(18px + env(safe-area-inset-bottom));box-shadow:0 -12px 40px rgba(0,0,0,.55)}
.gd-sheet-in{max-width:720px;margin:0 auto}
.gd-sheet .k{font-weight:700;font-size:1.02rem} .gd-sheet p{color:var(--text-2);margin:.4rem 0 .9rem;font-size:.92rem}
.gd-sheet .gd-acts{margin-top:0}
.gd-term,.gd-item{padding:14px;border-top:1px solid var(--border);scroll-margin-top:72px}
.list > .gd-term:first-child,.list > .gd-item:first-child{border-top:0}
.gd-term:target{background:var(--accent-soft)}
.gd-term .k,.gd-item .k{font-weight:650;font-size:.95rem;overflow-wrap:anywhere}
.gd-term p{margin:.3rem 0 0;font-size:.92rem} .gd-term .why,.gd-item .v{color:var(--text-2);font-size:.86rem}
.gd-item .v{margin-top:3px}
.gd-legend{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}
</style>"""

# 검색(인덱스를 한 번 받아 필터) + 용어 풀이 시트. 외부 라이브러리 없음. DOM 에는 textContent 로만 넣는다.
GUIDE_JS = """<script>
(function(){
  var inp=document.getElementById('gd-q'), box=document.getElementById('gd-results'), idx=null, loading=false, pend=null;
  function low(s){return (s||'').toLowerCase();}
  function load(cb){
    if(idx){cb();return;} pend=cb; if(loading) return; loading=true;
    fetch('/guide/search.json',{credentials:'same-origin'}).then(function(r){return r.json();})
      .then(function(d){idx=d; if(pend) pend();}).catch(function(){loading=false;});
  }
  function el(tag,cls,text){var e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e;}
  function show(on){document.querySelectorAll('[data-gd-hide]').forEach(function(e){e.hidden=on;});}
  function render(){
    var q=low(inp.value).trim();
    if(!q){box.textContent=''; show(false); return;}
    load(function(){
      q=low(inp.value).trim(); if(!q){box.textContent=''; show(false); return;}
      var toks=q.split(/\\s+/), hits=[];
      idx.forEach(function(it){
        if(toks.every(function(t){return it.h.indexOf(t)!==-1;})){
          var tl=low(it.t); hits.push([toks.every(function(t){return tl.indexOf(t)!==-1;})?0:1, it]);
        }
      });
      hits.sort(function(a,b){return a[0]-b[0];});
      box.textContent='';
      box.appendChild(el('p','meta', hits.length ? '검색 결과 '+hits.length+'개' : '찾는 항목이 없습니다. 다른 낱말(예: 알림, 백업, 주문)로 찾아보세요.'));
      if(hits.length){
        var list=el('div','list');
        hits.slice(0,50).forEach(function(h){
          var it=h[1], a=el('a','row'); a.href=it.u;
          var b=el('div','body'); b.appendChild(el('div','ttl',it.t)); if(it.s) b.appendChild(el('div','dsc',it.s));
          var end=el('div','end'); end.appendChild(el('span','pill plain muted',it.k)); end.appendChild(el('span','chev','\\u203a'));
          a.appendChild(b); a.appendChild(end); list.appendChild(a);
        });
        box.appendChild(list);
      }
      show(true);
    });
  }
  if(inp&&box){
    inp.addEventListener('input',render);
    inp.addEventListener('focus',function(){load(function(){});},{once:true});
    if(inp.form) inp.form.addEventListener('submit',function(ev){if(idx){ev.preventDefault();render();inp.blur();}});
    if(inp.value && !box.children.length) render();
  }
  var sheet=null;
  function close(){ if(sheet){sheet.remove(); sheet=null;} }
  document.addEventListener('click',function(ev){
    var a=ev.target.closest?ev.target.closest('a.term'):null;
    if(!a){ if(sheet && !sheet.contains(ev.target)) close(); return; }
    ev.preventDefault(); close();
    sheet=el('div','gd-sheet'); sheet.setAttribute('role','dialog'); sheet.setAttribute('aria-label','용어 풀이');
    var inner=el('div','gd-sheet-in'); inner.appendChild(el('div','k',a.getAttribute('data-t')||a.textContent));
    inner.appendChild(el('p',null,a.getAttribute('data-m')||''));
    var acts=el('div','gd-acts'); var more=el('a','btn','용어집에서 자세히'); more.href=a.href;
    var x=el('button','btn primary','닫기'); x.type='button'; x.addEventListener('click',close);
    acts.appendChild(more); acts.appendChild(x); inner.appendChild(acts); sheet.appendChild(inner); document.body.appendChild(sheet);
  });
  document.addEventListener('keydown',function(ev){ if(ev.key==='Escape') close(); });
})();
</script>"""

# ---------------------------------------------------------------------------
# 이름표·톤
# ---------------------------------------------------------------------------
JOB_CATEGORY = {  # core/process_registry.py 의 category 주석을 사람 말로
    "alert": ("알림", "실사용 신호·알림 — 끄면 그 알림이 오지 않습니다."),
    "research": ("연구", "결과가 쌓이기만 하므로 꺼도 당장 알림이 끊기지 않습니다."),
    "maintenance": ("유지보수", "캐시 예열·데이터 위생 — 끄면 다른 잡이 그 계산을 떠안을 수 있습니다."),
}
MODULE_STATUS_TONE = {"운영중": "ok", "관측 전용": "info", "실험": "warn", "도구": "muted", "보관": "muted"}
MODULE_STATUS_HELP = {
    "운영중": "실제 화면·알림에 쓰이는 중", "관측 전용": "기록만 하고 주문·결정에 연결 안 됨", "실험": "시험 중",
    "도구": "필요할 때 쓰는 계산 도구", "보관": "지금은 쓰지 않음",
}
RISK_TONE = {"읽기 전용": "ok", "파일/DB 쓰기": "warn", "주문 가능": "bad", "서버 설정 변경": "warn"}
PROBLEM_LABELS = {"error": "오류", "missed": "놓침", "overdue": "미실행"}


# ---------------------------------------------------------------------------
# 주소(슬러그)
# ---------------------------------------------------------------------------
_STREAMLIT_NAME_RE = re.compile(r"([0-9]*)[_ -]*(.*)\.py")


def streamlit_url_path(page_path: str) -> str:
    """Streamlit 이 st.Page(파일) 주소를 만드는 규칙과 같게: 파일 이름 앞 숫자·구분자를 뗀다.
    (streamlit.source_util.page_icon_and_name 과 같은 결과인지는 테스트가 대조한다)"""
    m = _STREAMLIT_NAME_RE.fullmatch(Path(page_path).name)
    return m.group(2) if m else Path(page_path).stem


def screen_slug(page_path: str) -> str:
    return streamlit_url_path(page_path)


def app_base_url() -> Optional[str]:
    """퀀트 대시보드(Streamlit) 주소 — hub/apps_registry.py 의 streamlit 슬롯 url."""
    try:
        from hub.apps_registry import SLOTS
    except Exception:  # noqa: BLE001
        return None
    for slot in SLOTS:
        if slot.id == "streamlit" and slot.url:
            return slot.url if slot.url.endswith("/") else slot.url + "/"
    return None


def screen_app_url(page_path: str) -> Optional[str]:
    """그 화면으로 바로 가는 주소. 기본 화면(오늘)은 앱 주소 그대로."""
    base = app_base_url()
    if not base:
        return None
    if page_path == live.default_page_path():
        return base
    return base + quote(streamlit_url_path(page_path))


def file_slug(path: str) -> str:
    return Path(path).name.rsplit(".", 1)[0]


def term_keys(term: str) -> list[str]:
    """'PIT (point-in-time)' -> ['PIT'], '멱등성 / client_order_id' -> ['멱등성', 'client_order_id']."""
    main = term.split(" (", 1)[0]
    return [k.strip() for k in main.split(" / ") if k.strip()]


def term_slug(term: str) -> str:
    keys = term_keys(term)
    return "t-" + (re.sub(r"[^0-9A-Za-z가-힣]+", "-", keys[0] if keys else term).strip("-").lower() or "x")


def href(section: str, slug: str = "") -> str:
    return f"/guide/{section}/{quote(slug)}" if slug else f"/guide/{section}"


# ---------------------------------------------------------------------------
# 본문 텍스트: escape + 용어 첫 등장 링크
# ---------------------------------------------------------------------------
class TermLinker:
    """한 페이지에서 용어집 용어가 처음 나올 때만 풀이 링크를 단다(escape 도 여기서 한다)."""

    def __init__(self, glossary: Iterable[Term], skip: str = ""):
        self.by_key: dict[str, Term] = {}
        for t in glossary:
            if t.term == skip:
                continue
            for k in term_keys(t.term):
                if len(k) >= 2:
                    self.by_key.setdefault(k.lower(), t)
        parts = []
        for k in sorted(self.by_key, key=len, reverse=True):
            pat = re.escape(k)
            if re.match(r"[A-Za-z0-9]", k):
                pat = r"(?<![A-Za-z0-9_])" + pat
            if re.search(r"[A-Za-z0-9]$", k):
                pat = pat + r"(?![A-Za-z0-9_])"
            parts.append(pat)
        self.rx = re.compile("|".join(parts), re.IGNORECASE) if parts else None
        self.used: set[str] = set()

    def __call__(self, text: str) -> str:
        text = str(text or "")
        if not self.rx:
            return E(text)
        out, pos = [], 0
        for m in self.rx.finditer(text):
            t = self.by_key.get(m.group(0).lower())
            if t is None or t.term in self.used:
                continue
            self.used.add(t.term)
            out.append(E(text[pos:m.start()]))
            out.append(f'<a class="term" href="/guide/glossary#{E(term_slug(t.term))}" data-t="{E(t.term)}" '
                       f'data-m="{E(t.meaning)}">{E(m.group(0))}</a>')
            pos = m.end()
        out.append(E(text[pos:]))
        return "".join(out)


def _ul(items: Iterable[str], tx: Callable[[str], str]) -> str:
    items = [i for i in items if str(i).strip()]
    return ("<ul>" + "".join(f"<li>{tx(i)}</li>" for i in items) + "</ul>") if items else ""


def _numbered(items: Iterable[str], tx: Callable[[str], str]) -> str:
    items = [i for i in items if str(i).strip()]
    return ('<ol class="gd-steps compact">' + "".join(
        f'<li class="gd-step"><div class="n">{n}</div><div class="c"><p>{tx(s)}</p></div></li>'
        for n, s in enumerate(items, 1)) + "</ol>") if items else ""


def _h2(title: str) -> str:
    return f"<h2>{E(title)}</h2>"


def _stale_notice(verified: str, paths: tuple[str, ...]) -> str:
    if live.is_stale(verified, paths):
        last = live.last_commit_date(paths)
        return ui.callout(f"이 설명을 확인한 뒤({E(verified)}) 근거 코드가 수정됐습니다({E(str(last))}). "
                          "내용이 조금 달라졌을 수 있으니 참고만 하세요. 다르면 코드가 우선입니다.", icon="⚠", tone="warn")
    return ""


def _stale_pill(verified: str, paths: tuple[str, ...]) -> str:
    return ui.pill("코드 변경됨", "warn") if live.is_stale(verified, paths) else ""


def _meta(text: str) -> str:
    return f'<p class="meta" style="margin-top:1.6rem">{E(text)}</p>'


def _first_line(text: str, n: int = 110) -> str:
    line = str(text or "").split("\n")[0]
    return line if len(line) <= n else line[: n - 1] + "…"


# ---------------------------------------------------------------------------
# 교차 링크: 본문에 나오는 화면·도구 이름 찾기
# ---------------------------------------------------------------------------
def _nav_items() -> list[tuple[str, str, str, str]]:
    """[(업무공간, path, title, icon)] — 코드(core.app_navigation)에서 자동."""
    return [(ws, p, t, i) for ws, pages in live.navigation().items() for p, t, i in pages]


def mentioned_screens(text: str) -> list[tuple[str, str, str]]:
    """본문에 '화면 제목' 처럼 따옴표로 나온 내비게이션 화면을 등장 순서대로 [(path, title, icon)]."""
    found = []
    for _, path, title, icon in _nav_items():
        pos = text.find(f"'{title}'")
        if pos != -1:
            found.append((pos, path, title, icon))
    return [(p, t, i) for _, p, t, i in sorted(found)]


GUIDE_SECTIONS = {"운영·알림": "ops", "자동 잡": "jobs", "운영 도구": "tools", "화면 안내": "screens", "용어집": "glossary"}


def mentioned_sections(text: str) -> list[tuple[str, str]]:
    """본문에 '운영·알림' 처럼 따옴표로, 또는 '운영·알림 절', '자동 잡 표' 처럼 나온 설명서 구역 [(이름, 주소)]."""
    return [(name, href(sec)) for name, sec in GUIDE_SECTIONS.items()
            if any(form in text for form in (f"'{name}'", f"{name} 절", f"{name} 표"))]


def mentioned_tools(text: str, content: GuideContent) -> list[ScriptGuide]:
    return [s for s in content.scripts if Path(s.path).name in text]


def _screen_buttons(screens: list[tuple[str, str, str]]) -> str:
    btns = []
    for path, title, icon in screens:
        url = screen_app_url(path)
        if url:
            btns.append(f'<a class="btn primary" href="{E(url)}" target="_blank" rel="noopener" data-screen="{E(path)}">'
                        f'{E(icon)} {E(title)} 열기 ↗</a>')
        btns.append(f'<a class="btn" href="{E(href("screens", screen_slug(path)))}" data-screen="{E(path)}">화면 설명</a>')
    return "".join(btns)


def _page_summary(content: GuideContent, path: str) -> str:
    g = next((p for p in content.pages if p.path == path), None)
    return (g.plain_summary or g.summary) if g else "설명 준비 중"


def _task_row(r: Routine) -> str:
    return ui.row(r.card_title or r.title, href=href("tasks", r.id), icon=r.icon or "📌", desc=r.plain_summary or r.when)


# ---------------------------------------------------------------------------
# 페이지 틀
# ---------------------------------------------------------------------------
def _page(title: str, body_html: str, crumbs: Iterable[tuple[str, str]] = ()) -> str:
    base = (("/", "개요"), ("/guide", "설명서"))
    return ui.page(title, f'<div class="gd-body">{body_html}</div>{GUIDE_JS}', active="/guide",
                   crumbs=base + tuple(crumbs), head_extra=GUIDE_CSS)


def _search_box(value: str = "", placeholder: str = "무엇이든 찾기 (예: 알림, 백업, PIT, 주문)", results_html: str = "") -> str:
    return (f'<form class="gd-search" action="/guide/search" method="get" role="search">'
            f'<input id="gd-q" name="q" type="search" value="{E(value)}" placeholder="{E(placeholder)}" '
            f'aria-label="설명서 검색" autocomplete="off" enterkeyhint="search"></form><div id="gd-results">{results_html}</div>')


def _not_found(what: str) -> tuple[int, str, str]:
    body = (f'<h1>찾을 수 없습니다</h1><p class="lead">{E(what)}</p>'
            + ui.row_list([ui.row("설명서 처음으로", href="/guide", icon="📖")]))
    return 404, HTML, _page("찾을 수 없음", body)


# ---------------------------------------------------------------------------
# 첫 화면(허브)
# ---------------------------------------------------------------------------
def _status_block() -> tuple[str, str]:
    """(HTML, 톤) — 관제 센터 개요와 같은 판정(hub.server.current_overview)을 그대로 쓴다."""
    try:
        from hub.server import current_overview

        banner, _tiles, jobs = current_overview()
    except Exception:  # noqa: BLE001 - 상태를 못 읽어도 설명서는 보여야 한다
        return ui.verdict("muted", "지금 상태를 읽지 못했습니다", "관제 센터 개요에서 확인하세요."), "muted"
    tone = next((t for t in ("bad", "warn", "ok", "muted") if f'class="verdict {t}"' in banner), "muted")
    label_to_id = {r.label: r.job_id for r in live.job_rows()}
    rows = []
    for p in (jobs.get("problems") or [])[:6]:
        jid = label_to_id.get(p.get("label", ""))
        state = p.get("state", "")
        rows.append(ui.row(p.get("label", "?"), href=href("jobs", jid) if jid else "/ops", icon="⏱", desc=p.get("text", ""),
                           end_html=ui.pill(PROBLEM_LABELS.get(state, state), "warn" if state == "overdue" else "bad")))
    if tone in ("bad", "warn"):
        rows.append(ui.row("알림이 왔을 때 할 일", href=href("tasks", "when-alert"), icon="🚨",
                           desc="알림 종류 구분 → 볼 화면 → 개발 요청까지 순서대로"))
    rows.append(ui.row("운영 상태 자세히", href="/ops", icon="🛡", desc="잡 건강·백업·서버 자원·타이머"))
    return banner + ui.row_list(rows), tone


def render_home(content: GuideContent) -> str:
    status_html, tone = _status_block()
    cards = []
    for r in content.routines:
        hot = " hot" if tone == "bad" and r.id == "when-alert" else ""
        cards.append(f'<a class="gd-task{hot}" href="{E(href("tasks", r.id))}"><span class="i" aria-hidden="true">'
                     f'{E(r.icon or "📌")}</span><span class="t">{E(r.card_title or r.title)}</span>'
                     f'<span class="d">{E(r.plain_summary or r.when)}</span></a>')
    cards.append('<a class="gd-task" href="/guide/glossary"><span class="i" aria-hidden="true">📚</span>'
                 '<span class="t">용어가 궁금해요</span><span class="d">PIT, shadow, unknown 같은 말의 뜻</span></a>')
    cards.append('<a class="gd-task" href="/guide/start"><span class="i" aria-hidden="true">👋</span>'
                 '<span class="t">처음이에요</span><span class="d">이 시스템이 무엇을 하고 무엇을 안 하는지</span></a>')

    job_rows = live.job_rows()
    on = sum(1 for r in job_rows if r.enabled)
    changes = live.recent_changes(25)

    def count(n: int) -> str:
        return ui.pill(f"{n}개", "muted", plain=True)

    lists = ui.row_list([
        ui.row("화면 안내", href=href("screens"), icon="🖥", desc="퀀트 대시보드 화면별 사용법",
               end_html=count(len(live.navigation_paths()))),
        ui.row("자동 잡", href=href("jobs"), icon="⏱", desc="언제 무엇이 저절로 도는지, 알림이 오면 할 일",
               end_html=ui.pill(f"켜짐 {on}/{len(job_rows)}", "muted", plain=True)),
        ui.row("운영·알림", href=href("ops"), icon="🛡", desc="텔레그램 명령, 알림 종류, 백업, 배포, 문제 해결",
               end_html=count(len(content.ops))),
        ui.row("운영 도구", href=href("tools"), icon="🧰", desc="서버에서 실행하는 명령(주문·검증·정리)",
               end_html=count(len(content.scripts))),
        ui.row("엔진 모듈", href=href("modules"), icon="⚙", desc="화면 뒤에서 계산하는 부품(참고용)",
               end_html=count(len(content.modules))),
        ui.row("용어집", href=href("glossary"), icon="📚", desc="낯선 말의 뜻", end_html=count(len(content.glossary))),
        ui.row("최근 변경", href=href("changes"), icon="🕘", desc="엔진이 바뀐 내역(자동)",
               end_html=ui.pill(changes[0]["date"], "muted", plain=True) if changes else ""),
    ])
    ver = live.deployed_version()
    ver_text = f'배포 버전 {ver["sha"]} · {ver["date"]}' if ver.get("available") else "배포 버전 확인 불가"
    body = (
        '<h1>사용 설명서</h1><p class="lead">하려는 일을 고르면 어느 화면에서 무엇을 누를지 순서대로 안내합니다.</p>'
        + _search_box()
        + '<div data-gd-hide>'
        + ui.section("지금 상태", status_html, cat_tag=True)
        + f'<h3 class="cat">무엇을 하려고 하나요?</h3><div class="gd-tasks">{"".join(cards)}</div>'
        + ui.callout("주문은 paper(모의투자) 전용이고, 알림과 화면의 추천은 주문을 내지 않습니다. "
                     "연구 결과는 대부분 '미입증'(아직 증거 부족)이 기본값입니다. "
                     '<a href="/guide/start" style="text-decoration:underline">처음 보는 분을 위한 안내 ›</a>', icon="💡")
        + f'<h3 class="cat">전체 목록</h3>{lists}'
        + f'<p class="stamp">{E(ver_text)}<br>화면·잡·변경 내역은 코드에서 자동으로 읽고, 나머지 설명은 코드와 대조한 날짜(확인일)를 '
          '표시합니다.</p></div>'
    )
    return ui.page("사용 설명서", f'<div class="gd-body">{body}</div>{GUIDE_JS}', active="/guide",
                   crumbs=(("/", "개요"), ("", "설명서")), head_extra=GUIDE_CSS)


# ---------------------------------------------------------------------------
# 처음 보는 분 · 할 일
# ---------------------------------------------------------------------------
def render_start(content: GuideContent) -> str:
    tx = TermLinker(content.glossary)
    paras = "".join(f'<div class="panel"><p>{tx(p)}</p></div>' for p in content.start_here) or '<div class="empty">준비 중입니다.</div>'
    body = ('<h1>처음 보는 분을 위한 안내</h1><p class="lead">이 시스템이 무엇을 하고, 무엇을 하지 않는지.</p>'
            f'{paras}<h3 class="cat">이제 할 일을 고르세요</h3>{ui.row_list(_task_row(r) for r in content.routines)}')
    return _page("처음 보는 분", body, (("", "처음 보는 분"),))


def render_task(content: GuideContent, r: Routine) -> str:
    tx = TermLinker(content.glossary)
    steps, used_screens = [], []
    for n, s in enumerate(r.steps, 1):
        screens = mentioned_screens(s)
        used_screens += [sc for sc in screens if sc not in used_screens]
        acts = _screen_buttons(screens) + "".join(
            f'<a class="btn" href="{E(href("tools", file_slug(t.path)))}">🧰 {E(t.name)}</a>' for t in mentioned_tools(s, content)
        ) + "".join(f'<a class="btn" href="{E(u)}">📖 {E(n)}</a>' for n, u in mentioned_sections(s))
        acts_html = f'<div class="gd-acts">{acts}</div>' if acts else ""
        steps.append(f'<li class="gd-step"><div class="n">{n}</div><div class="c"><p>{tx(s)}</p>{acts_html}</div></li>')
    related = ui.row_list(ui.row(t, href=href("screens", screen_slug(p)), icon=i, desc=_page_summary(content, p))
                          for p, t, i in used_screens) if used_screens else ""
    body = (f'<h1>{E(r.icon + " " if r.icon else "")}{E(r.title)}</h1>'
            + (f'<p class="lead">{tx(r.plain_summary)}</p>' if r.plain_summary else "")
            + ui.kv_table([("언제", tx(r.when)), ("단계", f"{len(r.steps)}단계")])
            + _h2("순서") + f'<ol class="gd-steps">{"".join(steps)}</ol>'
            + (_h2("주의·팁") + ui.callout(_ul(r.tips, tx), icon="⚠", tone="warn") if r.tips else "")
            + (_h2("이 일에서 쓰는 화면") + related if related else "")
            + '<h3 class="cat">다른 할 일</h3>' + ui.row_list(_task_row(o) for o in content.routines if o.id != r.id))
    return _page(r.card_title or r.title, body, (("", "할 일"),))


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
def render_screens(content: GuideContent) -> str:
    by_path = {p.path: p for p in content.pages}
    parts = []
    for ws, pages in live.navigation().items():
        rows = []
        for path, title, icon in pages:
            g = by_path.get(path)
            end = _stale_pill(g.verified, g.sources) if g else ui.pill("설명 준비 중", "warn")
            rows.append(ui.row(title, href=href("screens", screen_slug(path)), icon=icon,
                               desc=(g.plain_summary or g.summary) if g else "", end_html=end))
        parts.append(ui.section(ws, ui.row_list(rows), cat_tag=True))
    base = app_base_url()
    open_btn = (f'<div class="gd-btns"><a class="btn primary" href="{E(base)}" target="_blank" rel="noopener">'
                '퀀트 대시보드 열기 ↗</a></div>') if base else ""
    body = ('<h1>화면 안내</h1><p class="lead">퀀트 대시보드의 화면입니다. 사이드바와 같은 묶음·순서로 코드에서 자동으로 읽습니다. '
            '화면을 누르면 무엇을 누르고 무엇을 읽는지 나옵니다.</p>' + open_btn + _search_box(placeholder="화면·기능 찾기")
            + f'<div data-gd-hide>{"".join(parts)}</div>')
    return _page("화면 안내", body, (("", "화면 안내"),))


def render_screen(content: GuideContent, path: str, title: str, icon: str) -> str:
    g = next((p for p in content.pages if p.path == path), None)
    url = screen_app_url(path)
    btn = (f'<div class="gd-btns"><a class="btn primary" href="{E(url)}" target="_blank" rel="noopener">'
           f'{E(icon)} 이 화면 열기 ↗</a></div>') if url else ""
    crumbs = (("/guide/screens", "화면 안내"), ("", title))
    if g is None:
        return _page(title, f'<h1>{E(icon)} {E(title)}</h1>{btn}<div class="empty">이 화면의 설명은 준비 중입니다.</div>', crumbs)
    tx = TermLinker(content.glossary)
    # 쉬운 한 줄(plain_summary)이 있으면 그것을 먼저, 원래 요약은 그 아래 작은 글씨로. 예시는 따로 한 칸.
    lead = (f'<p class="lead" style="margin-bottom:.3rem">{tx(g.plain_summary)}</p><p class="muted" style="margin:0 0 1rem;'
            f'font-size:.88rem">{tx(g.summary)}</p>') if g.plain_summary else f'<p class="lead">{tx(g.summary)}</p>'
    glance = ui.callout(f"<b>예시</b> · {tx(g.example)}", icon="👉") if g.example else ""
    jobs = {r.job_id: r for r in live.job_rows()}
    job_rows = [_job_row(jobs[j]) for j in g.related_jobs if j in jobs]
    tasks = [r for r in content.routines if any(p == path for p, _, _ in mentioned_screens(" ".join(r.steps)))]
    body = (
        f'<h1>{E(icon)} {E(title)}</h1>{lead}{btn}'
        f'{_stale_notice(g.verified, g.sources)}{glance}'
        f'{_h2("언제 쓰나")}<p>{tx(g.when_to_use)}</p>'
        f'{_h2("사용 순서")}{_numbered(g.steps, tx)}'
        + (_h2("결과 읽는 법") + _ul(g.reading, tx) if g.reading else "")
        + (_h2("주의") + ui.callout(_ul(g.cautions, tx), icon="⚠", tone="warn") if g.cautions else "")
        + (_h2("이 화면의 데이터를 채우는 자동 잡") + ui.row_list(job_rows) if job_rows else "")
        + (_h2("이 화면을 쓰는 할 일") + ui.row_list(_task_row(r) for r in tasks) if tasks else "")
        + _meta(f"확인일 {g.verified} · 근거 {', '.join(g.sources) or '-'}")
    )
    return _page(title, body, crumbs)


# ---------------------------------------------------------------------------
# 자동 잡
# ---------------------------------------------------------------------------
def _enabled_pill(enabled: Optional[bool]) -> str:
    return ui.pill("켜짐", "ok") if enabled else (ui.pill("꺼짐", "muted") if enabled is False else ui.pill("?", "muted"))


def _job_row(r: live.JobRow) -> str:
    return ui.row(r.label, href=href("jobs", r.job_id), desc=f"{r.when_text} · {r.description}", end_html=_enabled_pill(r.enabled))


def render_jobs(content: GuideContent) -> str:
    groups: dict[str, list[live.JobRow]] = {}
    for r in live.job_rows():
        groups.setdefault(r.category, []).append(r)
    parts = []
    for cat in [c for c in JOB_CATEGORY if c in groups] + [c for c in groups if c not in JOB_CATEGORY]:
        name, help_ = JOB_CATEGORY.get(cat, (cat or "기타", ""))
        parts.append(f'<h3 class="cat">{E(name)} · {len(groups[cat])}개</h3>'
                     + (f'<p class="meta" style="margin:-.3rem 0 .6rem">{E(help_)}</p>' if help_ else "")
                     + ui.row_list(_job_row(r) for r in groups[cat]))
    body = ('<h1>자동 잡</h1><p class="lead">스케줄러가 시간이 되면 스스로 실행하는 작업입니다. 시각과 켜짐/꺼짐은 지금 서버의 실제 설정을 '
            '자동으로 읽습니다. 켜고 끄기는 텔레그램 <code>/processes</code>.</p>'
            + _search_box(placeholder="잡 찾기 (예: 백업, 브리핑, 챔피언)") + f'<div data-gd-hide>{"".join(parts)}</div>')
    return _page("자동 잡", body, (("", "자동 잡"),))


def render_job(content: GuideContent, r: live.JobRow) -> str:
    tx = TermLinker(content.glossary)
    ex = next((j for j in content.jobs if j.job_id == r.job_id), None)
    name, _ = JOB_CATEGORY.get(r.category, (r.category or "-", ""))
    rows = [("실행 시각", E(r.when_text)), ("지금 설정", _enabled_pill(r.enabled)), ("분류", E(name)),
            ("잡 이름", f"<code>{E(r.job_id)}</code>")]
    screens = [(p, t, i) for _, p, t, i in _nav_items()
               if any(g.path == p and r.job_id in g.related_jobs for g in content.pages)]
    body = (f'<h1>{E(r.label)}</h1><p class="lead">{tx(r.description)}</p>{ui.kv_table(rows)}'
            + (_h2("결과 보는 곳") + f"<p>{tx(ex.where_to_see)}</p>" if ex else "")
            + (f'<div class="gd-acts">{_screen_buttons(mentioned_screens(ex.where_to_see))}</div>'
               if ex and mentioned_screens(ex.where_to_see) else "")
            + (_h2("알림이 오거나 실패하면") + ui.callout(tx(ex.if_alert), icon="🔔") if ex and ex.if_alert else "")
            + (_h2("이 잡이 채우는 화면") + ui.row_list(
                ui.row(t, href=href("screens", screen_slug(p)), icon=i, desc=_page_summary(content, p)) for p, t, i in screens)
               if screens else "")
            + (_meta(f"확인일 {ex.verified} · 이름·시각·설명·켜짐/꺼짐은 서버 설정에서 자동") if ex else
               '<div class="empty">이 잡의 보충 설명은 준비 중입니다.</div>'))
    return _page(r.label, body, (("/guide/jobs", "자동 잡"), ("", r.label)))


# ---------------------------------------------------------------------------
# 엔진 모듈
# ---------------------------------------------------------------------------
def render_modules(content: GuideContent) -> str:
    from hub.guide.schema import GROUP_CHOICES

    parts = []
    for gname in [g for g in GROUP_CHOICES if any(m.group == g for m in content.modules)]:
        mods = sorted((m for m in content.modules if m.group == gname), key=lambda x: x.name)
        parts.append(ui.section(f"{gname} · {len(mods)}개", ui.row_list(
            ui.row(m.name, href=href("modules", file_slug(m.module)), desc=_first_line(m.what),
                   end_html=_stale_pill(m.verified, (m.module, *m.sources)) + ui.pill(m.status, MODULE_STATUS_TONE.get(m.status, "muted")))
            for m in mods), cat_tag=True))
    legend = "".join(ui.pill(s, MODULE_STATUS_TONE.get(s, "muted")) for s in MODULE_STATUS_HELP)
    legend_help = " · ".join(f"{s}: {h}" for s, h in MODULE_STATUS_HELP.items())
    body = ('<h1>엔진 모듈</h1><p class="lead">화면과 자동 잡 뒤에서 계산하는 부품입니다. 매일 볼 필요는 없고, 화면이나 알림에 '
            '나온 이름이 궁금할 때 찾아보세요.</p>'
            f'<div class="gd-legend">{legend}</div><p class="meta" style="margin-top:-.2rem">{E(legend_help)}</p>'
            + _search_box(placeholder="모듈 찾기") + f'<div data-gd-hide>{"".join(parts)}</div>')
    return _page("엔진 모듈", body, (("", "엔진 모듈"),))


def render_module(content: GuideContent, m: ModuleGuide) -> str:
    tx = TermLinker(content.glossary)
    screens = mentioned_screens(m.where_to_see + " " + m.how_to_use)
    body = (f'<h1>{E(m.name)}</h1><div class="gd-legend">{ui.pill(m.status, MODULE_STATUS_TONE.get(m.status, "muted"))}'
            f'{ui.pill(m.group, "muted", plain=True)}</div>'
            f'{_stale_notice(m.verified, (m.module, *m.sources))}'
            f'{_h2("하는 일")}<p>{tx(m.what)}</p>{_h2("어떻게 활용하나")}<p>{tx(m.how_to_use)}</p>'
            f'{_h2("결과 보는 곳")}<p>{tx(m.where_to_see)}</p>'
            + (f'<div class="gd-acts">{_screen_buttons(screens)}</div>' if screens else "")
            + (_h2("주의") + ui.callout(tx(m.cautions), icon="⚠", tone="warn") if m.cautions else "")
            + _meta(f"{m.module} · 확인일 {m.verified}"))
    return _page(m.name, body, (("/guide/modules", "엔진 모듈"), ("", m.name)))


# ---------------------------------------------------------------------------
# 운영 도구
# ---------------------------------------------------------------------------
def render_tools(content: GuideContent) -> str:
    rows = [ui.row(s.name, href=href("tools", file_slug(s.path)), desc=s.when_to_run,
                   end_html=_stale_pill(s.verified, (s.path,)) + ui.pill(s.risk, RISK_TONE.get(s.risk, "muted")))
            for s in content.scripts]
    body = ('<h1>운영 도구</h1><p class="lead">서버에서 실행하는 운영·연구 명령입니다. 오른쪽 알약이 위험도입니다 — '
            '파일을 바꾸거나 주문을 낼 수 있는지 먼저 보세요.</p>' + _search_box(placeholder="도구 찾기")
            + f'<div data-gd-hide>{ui.row_list(rows)}</div>')
    return _page("운영 도구", body, (("", "운영 도구"),))


def render_tool(content: GuideContent, s: ScriptGuide) -> str:
    tx = TermLinker(content.glossary)
    body = (f'<h1>{E(s.name)}</h1><div class="gd-legend">{ui.pill(s.risk, RISK_TONE.get(s.risk, "muted"))}</div>'
            f'{_stale_notice(s.verified, (s.path,))}'
            f'{_h2("언제 실행하나")}<p>{tx(s.when_to_run)}</p>{_h2("실행")}<pre>{E(s.command)}</pre>'
            f'{_h2("결과 읽는 법")}<p>{tx(s.what_it_prints)}</p>' + _meta(f"{s.path} · 확인일 {s.verified}"))
    return _page(s.name, body, (("/guide/tools", "운영 도구"), ("", s.name)))


# ---------------------------------------------------------------------------
# 운영·알림
# ---------------------------------------------------------------------------
def render_ops_list(content: GuideContent) -> str:
    rows = [ui.row(o.title, href=href("ops", o.id), desc=_first_line(o.body[0] if o.body else "", 90)) for o in content.ops]
    body = ('<h1>운영·알림</h1><p class="lead">텔레그램 명령, 알림 종류, 백업·워치독·배포, 문제가 생겼을 때 확인 순서.</p>'
            + _search_box(placeholder="운영 안내 찾기") + f'<div data-gd-hide>{ui.row_list(rows)}</div>')
    return _page("운영·알림", body, (("", "운영·알림"),))


def render_op(content: GuideContent, o: OpsSection) -> str:
    tx = TermLinker(content.glossary)
    paras = "".join(f"<p>{tx(p)}</p>" for p in o.body)
    items = ('<div class="list" style="margin-top:12px">' + "".join(
        f'<div class="gd-item"><div class="k"><code>{E(a)}</code></div><div class="v">{tx(b)}</div></div>' for a, b in o.items)
        + "</div>") if o.items else ""
    body = f'<h1>{E(o.title)}</h1>' + (f'<div class="panel">{paras}</div>' if paras else "") + items + _meta(f"확인일 {o.verified}")
    return _page(o.title, body, (("/guide/ops", "운영·알림"), ("", o.title)))


# ---------------------------------------------------------------------------
# 용어집 · 최근 변경 · 검색
# ---------------------------------------------------------------------------
def render_glossary(content: GuideContent) -> str:
    items = "".join(
        f'<div class="gd-term" id="{E(term_slug(t.term))}"><div class="k">{E(t.term)}</div><p>{E(t.meaning)}</p>'
        + (f'<p class="why">{E(t.why_it_matters)}</p>' if t.why_it_matters else "") + "</div>"
        for t in sorted(content.glossary, key=lambda x: x.term.lower()))
    body = ('<h1>용어집</h1><p class="lead">설명서 본문에서 점선 밑줄이 있는 말을 누르면 뜻이 바로 뜹니다. 전체 목록은 여기.</p>'
            + _search_box(placeholder="용어 찾기 (예: PIT, shadow)")
            + (f'<div data-gd-hide><div class="list">{items}</div></div>' if items else '<div class="empty">준비 중입니다.</div>'))
    return _page("용어집", body, (("", "용어집"),))


def render_changes(content: GuideContent) -> str:
    ch = live.recent_changes(25)
    ver = live.deployed_version()
    ver_html = ui.kv_table([("배포 버전", f'<code>{E(str(ver["sha"]))}</code>'), ("날짜", E(ver.get("date") or "-")),
                            ("내용", E(ver.get("subject") or "-"))]) if ver.get("available") else \
        '<div class="empty">이 서버에서는 배포 버전(git)을 읽을 수 없습니다.</div>'
    rows = ui.row_list(ui.row(c["subject"], desc=f'{c["date"]} · {c["sha"]}') for c in ch) if ch else \
        '<div class="empty">이 서버에서는 변경 내역(git)을 읽을 수 없습니다.</div>'
    body = ('<h1>최근 변경</h1><p class="lead">엔진이 업데이트되면 여기에 자동으로 나타납니다(병합 커밋 제외, 최근 25개).</p>'
            f'{ver_html}<h3 class="cat">변경 내역</h3>{rows}')
    return _page("최근 변경", body, (("", "최근 변경"),))


def search_index(content: GuideContent) -> list[dict]:
    """모든 하위 페이지 항목 — {t 제목, k 종류, s 한 줄, u 주소, h 검색용 소문자 본문}."""
    out: list[dict] = []

    def add(title: str, kind: str, summary: str, url: str, *body: str) -> None:
        hay = " ".join([title, kind, summary, *[str(b) for b in body if b]])
        out.append({"t": title, "k": kind, "s": _first_line(summary, 120), "u": url, "h": hay.lower()[:1500]})

    add("처음 보는 분을 위한 안내", "안내", "이 시스템이 무엇을 하고 무엇을 하지 않는지", "/guide/start", *content.start_here)
    for r in content.routines:
        add(r.title, "할 일", r.plain_summary or r.when, href("tasks", r.id), r.card_title, r.when, *r.steps, *r.tips)
    by_path = {p.path: p for p in content.pages}
    for ws, path, title, _icon in _nav_items():
        g = by_path.get(path)
        add(title, "화면", (g.plain_summary or g.summary) if g else "설명 준비 중", href("screens", screen_slug(path)), ws,
            *((g.summary, g.when_to_use, *g.steps, *g.reading, *g.cautions) if g else ()))
    extra = {j.job_id: j for j in content.jobs}
    for r in live.job_rows():
        ex = extra.get(r.job_id)
        add(r.label, "자동 잡", f"{r.when_text} · {r.description}", href("jobs", r.job_id), r.job_id,
            *((ex.where_to_see, ex.if_alert) if ex else ()))
    for m in content.modules:
        add(m.name, "엔진 모듈", m.what, href("modules", file_slug(m.module)), m.module, m.status, m.how_to_use, m.where_to_see)
    for s in content.scripts:
        add(s.name, "운영 도구", s.when_to_run, href("tools", file_slug(s.path)), s.path, s.risk, s.what_it_prints)
    for o in content.ops:
        add(o.title, "운영·알림", o.body[0] if o.body else "", href("ops", o.id), *o.body, *(f"{a} {b}" for a, b in o.items))
    for t in content.glossary:
        add(t.term, "용어", t.meaning, f"/guide/glossary#{term_slug(t.term)}", t.why_it_matters)
    return out


def search(content: GuideContent, q: str) -> list[dict]:
    toks = [t for t in q.lower().split() if t]
    if not toks:
        return []
    hits = [(0 if all(t in e["t"].lower() for t in toks) else 1, i, e) for i, e in enumerate(search_index(content))
            if all(t in e["h"] for t in toks)]
    return [e for _, _, e in sorted(hits, key=lambda x: (x[0], x[1]))]


def render_search(content: GuideContent, q: str) -> str:
    q = (q or "").strip()[:100]
    res = ""
    if q:
        hits = search(content, q)
        res = (f'<p class="meta">검색 결과 {len(hits)}개</p>' if hits else
               '<p class="meta">찾는 항목이 없습니다. 다른 낱말(예: 알림, 백업, 주문)로 찾아보세요.</p>')
        if hits:
            res += ui.row_list(ui.row(e["t"], href=e["u"], desc=e["s"], end_html=ui.pill(e["k"], "muted", plain=True))
                               for e in hits[:50])
    return _page("검색", "<h1>검색</h1>" + _search_box(q, results_html=res), (("", "검색"),))


# ---------------------------------------------------------------------------
# 라우터
# ---------------------------------------------------------------------------
def render_route(path: str, query: Optional[dict] = None, content: Optional[GuideContent] = None) -> tuple[int, str, str]:
    """/guide 아래 경로 하나를 그린다 -> (상태, Content-Type, 본문). path 는 URL 디코딩된 값."""
    if content is None:
        from hub.guide import build_content

        content = build_content()
    query = query or {}
    parts = [p for p in path.split("/") if p][1:]  # 'guide' 다음
    if not parts:
        return 200, HTML, render_home(content)
    if len(parts) > 2:
        return _not_found("주소가 올바르지 않습니다.")
    sec, key = parts[0], (parts[1] if len(parts) == 2 else None)

    if key is None:
        if sec == "search.json":
            body = json.dumps(search_index(content), ensure_ascii=False, separators=(",", ":"))
            # 브라우저가 HTML 로 오인해도 태그가 되지 않게 < > & 를 JSON 이스케이프(JSON.parse 결과는 같다)
            return 200, JSON, body.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
        simple = {"screens": render_screens, "jobs": render_jobs, "modules": render_modules, "tools": render_tools,
                  "ops": render_ops_list, "glossary": render_glossary, "changes": render_changes, "start": render_start,
                  "tasks": render_home}
        if sec in simple:
            return 200, HTML, simple[sec](content)
        if sec == "search":
            return 200, HTML, render_search(content, (query.get("q") or [""])[0])
        return _not_found("그런 설명서 페이지가 없습니다.")

    if sec == "tasks":
        r = next((r for r in content.routines if r.id == key), None)
        return (200, HTML, render_task(content, r)) if r else _not_found("그런 할 일이 없습니다.")
    if sec == "screens":
        item = next(((p, t, i) for _, p, t, i in _nav_items() if screen_slug(p) == key), None)
        return (200, HTML, render_screen(content, *item)) if item else _not_found("그런 화면이 없습니다.")
    if sec == "jobs":
        job = next((j for j in live.job_rows() if j.job_id == key), None)
        return (200, HTML, render_job(content, job)) if job else _not_found("그런 자동 잡이 없습니다.")
    if sec == "modules":
        m = next((m for m in content.modules if file_slug(m.module) == key), None)
        return (200, HTML, render_module(content, m)) if m else _not_found("그런 엔진 모듈 설명이 없습니다.")
    if sec == "tools":
        s = next((s for s in content.scripts if file_slug(s.path) == key), None)
        return (200, HTML, render_tool(content, s)) if s else _not_found("그런 운영 도구 설명이 없습니다.")
    if sec == "ops":
        o = next((o for o in content.ops if o.id == key), None)
        return (200, HTML, render_op(content, o)) if o else _not_found("그런 운영 안내가 없습니다.")
    return _not_found("그런 설명서 페이지가 없습니다.")


def all_routes(content: GuideContent) -> list[str]:
    """설명서의 모든 HTML 페이지 주소(디코딩된 형태) — 테스트·점검용."""
    routes = ["/guide", "/guide/start", "/guide/screens", "/guide/jobs", "/guide/modules", "/guide/tools", "/guide/ops",
              "/guide/glossary", "/guide/changes", "/guide/search"]
    routes += [f"/guide/tasks/{r.id}" for r in content.routines]
    routes += [f"/guide/screens/{screen_slug(p)}" for _, p, _, _ in _nav_items()]
    routes += [f"/guide/jobs/{r.job_id}" for r in live.job_rows()]
    routes += [f"/guide/modules/{file_slug(m.module)}" for m in content.modules]
    routes += [f"/guide/tools/{file_slug(s.path)}" for s in content.scripts]
    routes += [f"/guide/ops/{o.id}" for o in content.ops]
    return routes


def render_guide(content: GuideContent) -> str:
    """이전 이름 호환: 설명서 첫 화면."""
    return render_home(content)
