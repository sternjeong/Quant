"""관제 허브 'AI 대회' 섹션 — 대회 목록·새 대회 만들기·대회별 관리(core/contests.py).

라우트(hub/server.py): GET /contests, /contests/new, /contests/<slug>
                       POST /contests/new, /contests/<slug>/update, /contests/<slug>/repo
대회 카드의 'VS Code에서 열기'는 code-server(code. 하위 도메인)를 그 대회 폴더로 연다.
"""

from __future__ import annotations

import html
from typing import Optional

from core import contests as ct

FORM_CSS = """
<style>
  .form label { display:block; font-size:.78rem; color:#9aa0a8; margin:.8rem 0 .3rem; }
  .form input, .form select, .form textarea { width:100%; max-width:520px; box-sizing:border-box; padding:.55rem .7rem;
    background:#0f1115; color:#e6e6e6; border:1px solid #2a2e37; border-radius:8px; font-size:.95rem; }
  .form textarea { min-height:90px; }
  .btn { display:inline-block; background:#4c7dff; color:#fff; border:0; border-radius:8px; padding:.55rem 1.1rem;
    font-size:.9rem; cursor:pointer; text-decoration:none; margin:.3rem .4rem .3rem 0; }
  .btn.ghost { background:#232733; }
  .err { color:#f87171; margin:.6rem 0; }
  .dday { font-weight:700; }
  .dday.hot { color:#f87171; } .dday.warm { color:#fbbf24; } .dday.cool { color:#4ade80; }
</style>
"""


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def code_server_base() -> str:
    from hub.apps_registry import SLOTS

    slot = next((s for s in SLOTS if s.id == "code-server"), None)
    return (slot.url if slot and slot.url else "https://code.hessejeong.duckdns.org/")


def dday_html(c: ct.Contest) -> str:
    left = c.days_left()
    if left is None:
        return '<span class="dday">마감 미정</span>'
    if left < 0:
        return f'<span class="dday">마감 지남({-left}일 전)</span>'
    tone = "hot" if left <= 1 else "warm" if left <= 7 else "cool"
    return f'<span class="dday {tone}">{"D-DAY" if left == 0 else f"D-{left}"}</span>'


def repo_html(c: ct.Contest) -> str:
    if c.repo_status == "created" and c.repo:
        return f'<a class="back" href="https://github.com/{_e(c.repo)}" target="_blank" rel="noopener">{_e(c.repo)}</a> (private)'
    if c.repo_status.startswith("failed:"):
        return f'<span class="badge inactive">저장소 생성 실패</span> <small>{_e(c.repo_status[7:])}</small>'
    return '<span class="badge unknown">저장소 대기</span>'


def card_badge() -> str:
    items = [c for c in ct.list_contests() if c.status != "종료"]
    if not items:
        ok, _ = ct.root_status()
        return '<span class="badge unknown">' + ("대회 없음" if ok else "설정 필요") + '</span>'
    nxt = next((c for c in items if c.days_left() is not None and c.days_left() >= 0), None)
    tail = f" · 다음 마감 D-{nxt.days_left()}" if nxt else ""
    return f'<span class="badge active">진행 {len(items)}개{_e(tail)}</span>'


def render_list(page_style: str) -> str:
    ok, why = ct.root_status()
    cards = []
    for c in ct.list_contests():
        cards.append(
            f'<a class="card" href="/contests/{_e(c.slug)}"><h2>{_e(c.title)}<span class="kind">{_e(c.platform)}</span></h2>'
            f'<p>{dday_html(c)} · {_e(c.status)}{" · " + _e(c.deadline) + " KST" if c.deadline else ""}</p>'
            f'<p><small>{_e(c.slug)}</small></p></a>')
    setup = "" if ok else f'<p class="err">⚠️ {_e(why)}</p>'
    body = ('<p><a class="back" href="/">&larr; 관제 센터로</a></p><h1>AI 대회</h1>'
            '<p class="subtitle">대회마다 작업 폴더 + GitHub private 저장소 하나. 카드를 누르면 관리 화면, 거기서 VS Code 로 넘어갑니다.</p>'
            f'{setup}<p><a class="btn" href="/contests/new">+ 새 대회</a></p>'
            f'<div class="grid">{"".join(cards) or "<p>아직 등록한 대회가 없습니다.</p>"}</div>')
    return _page("AI 대회", body, page_style)


def render_new(page_style: str, error: str = "", values: Optional[dict] = None) -> str:
    v = values or {}
    opts = "".join(f'<option{" selected" if v.get("platform") == p else ""}>{p}</option>' for p in ct.PLATFORMS)
    body = ('<p><a class="back" href="/contests">&larr; 대회 목록</a></p><h1>새 대회</h1>'
            + (f'<p class="err">{_e(error)}</p>' if error else "") +
            '<form class="form" method="post" action="/contests/new">'
            f'<label>대회 이름</label><input name="title" required value="{_e(v.get("title"))}">'
            f'<label>폴더·저장소 이름 (영문 소문자·숫자·하이픈, 저장소는 contest-이름)</label>'
            f'<input name="slug" required pattern="[a-z0-9][a-z0-9-]{{1,40}}" placeholder="kaggle-titanic" value="{_e(v.get("slug"))}">'
            f'<label>플랫폼</label><select name="platform">{opts}</select>'
            f'<label>대회 링크</label><input name="url" type="url" placeholder="https://" value="{_e(v.get("url"))}">'
            f'<label>마감 (KST, 날짜만 또는 날짜+시각)</label><input name="deadline" placeholder="2026-11-30 또는 2026-11-30T09:00" value="{_e(v.get("deadline"))}">'
            f'<label>메모</label><textarea name="memo">{_e(v.get("memo"))}</textarea>'
            '<p><button class="btn" type="submit">폴더 + private 저장소 만들기</button></p>'
            '<p><small>뼈대(README·data/·notebooks/·src/·submissions/·.gitignore·requirements.txt)를 넣고 첫 커밋 후 GitHub 에 푸시합니다. 10~20초 걸릴 수 있습니다.</small></p>'
            '</form>')
    return _page("새 대회", body, page_style)


def render_detail(slug: str, page_style: str, error: str = "") -> Optional[str]:
    c = ct.load(slug)
    if c is None:
        return None
    status_opts = "".join(f'<option{" selected" if c.status == s else ""}>{s}</option>' for s in ct.STATUSES)
    plat_opts = "".join(f'<option{" selected" if c.platform == p else ""}>{p}</option>' for p in ct.PLATFORMS)
    retry = "" if c.repo_status == "created" else (
        f'<form method="post" action="/contests/{_e(slug)}/repo" style="display:inline">'
        '<button class="btn ghost" type="submit">GitHub 저장소 다시 만들기</button></form>')
    body = (f'<p><a class="back" href="/contests">&larr; 대회 목록</a></p><h1>{_e(c.title)}</h1>'
            f'<p class="subtitle">{dday_html(c)} · {_e(c.platform)} · {_e(c.status)}</p>'
            + (f'<p class="err">{_e(error)}</p>' if error else "") +
            f'<p><a class="btn" href="{_e(ct.code_server_url(c, code_server_base()))}" target="_blank" rel="noopener">VS Code 에서 열기</a>'
            + (f'<a class="btn ghost" href="{_e(c.url)}" target="_blank" rel="noopener">대회 페이지</a>' if c.url else "") + retry + '</p>'
            '<table>'
            f'<tr><th>저장소</th><td>{repo_html(c)}</td></tr>'
            f'<tr><th>폴더</th><td><small>{_e(c.path)}</small></td></tr>'
            f'<tr><th>마감</th><td>{_e(c.deadline or "미정")} KST</td></tr>'
            '</table>'
            f'<h2>정보 수정</h2><form class="form" method="post" action="/contests/{_e(slug)}/update">'
            f'<label>대회 이름</label><input name="title" value="{_e(c.title)}">'
            f'<label>상태</label><select name="status">{status_opts}</select>'
            f'<label>플랫폼</label><select name="platform">{plat_opts}</select>'
            f'<label>대회 링크</label><input name="url" value="{_e(c.url)}">'
            f'<label>마감 (KST)</label><input name="deadline" value="{_e(c.deadline)}">'
            f'<label>메모</label><textarea name="memo">{_e(c.memo)}</textarea>'
            '<p><button class="btn" type="submit">저장</button> <small>contest.json 에 저장됩니다(커밋은 VS Code 에서).</small></p></form>')
    return _page(c.title, body, page_style)


def _page(title: str, body: str, page_style: str) -> str:
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(title)}</title>{page_style}{FORM_CSS}</head><body>{body}</body></html>')


def _one(form: dict, key: str) -> str:
    return (form.get(key) or [""])[0]


def handle_post(path: str, form: dict) -> tuple[str, Optional[str]]:
    """POST 처리. (리다이렉트 경로, 오류 메시지). 오류면 호출자가 같은 화면을 오류와 함께 다시 그린다."""
    if path == "/contests/new":
        try:
            c = ct.create_contest(_one(form, "slug").strip(), _one(form, "title"), _one(form, "platform"),
                                  _one(form, "url"), _one(form, "deadline"), _one(form, "memo"))
        except ct.ContestError as exc:
            return "/contests/new", str(exc)
        return f"/contests/{c.slug}", None
    parts = path.strip("/").split("/")
    if len(parts) == 3 and parts[0] == "contests" and ct.SLUG_RE.match(parts[1]):
        slug, action = parts[1], parts[2]
        try:
            if action == "update":
                ct.update(slug, **{k: _one(form, k) for k in ("title", "status", "platform", "url", "deadline", "memo")})
            elif action == "repo":
                c = ct.create_repo(slug)
                if c.repo_status != "created":
                    return f"/contests/{slug}", "저장소 생성 실패: " + c.repo_status[7:]
            else:
                return "/contests", "알 수 없는 요청"
        except ct.ContestError as exc:
            return f"/contests/{slug}", str(exc)
        return f"/contests/{slug}", None
    return "/contests", "알 수 없는 요청"
