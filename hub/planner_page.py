"""관제 허브 '할 일' 화면 — 오늘 / 이번 주 / 나중 할 일과 AI 대회 마감을 한 화면에(core/planner.py).

라우트(hub/server.py): GET /planner (?area= 분야 거르기, ?edit=<id> 고치기, ?msg=)
                       POST /planner/add, /planner/update, /planner/done, /planner/undo, /planner/delete, /planner/notion,
                            /planner/dismiss (시그널 확인함), /planner/submitted (대회 제출 완료), /planner/refresh (시그널 재계산)
자동 항목(대회·주식 시그널)은 고칠 수 없다 — 대회는 '제출 완료', 시그널은 '확인함'으로만 지운다.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from core import planner as pl
from hub import ui

E = html.escape

AREA_ICONS = {"AI 대회": "🏁", "프로젝트": "🛠", "주식": "📈", "기타": "📌"}
SIGNAL_ICONS = {"sell": "🔻", "review": "🔍", "signal": "📡", "rebalance": "🔄"}

FORM_CSS = """<style>
.pform{display:grid;grid-template-columns:1fr 1fr;gap:10px 12px}
.pform .full{grid-column:1/-1}
.pform label{display:block;color:var(--text-2);font-size:.8rem;margin-bottom:.3rem}
.pform input,.pform select,.pform textarea{width:100%;min-height:44px;padding:.55rem .7rem;border:1px solid var(--border-2);
  border-radius:10px;background:var(--surface-2);box-sizing:border-box}
.pform textarea{min-height:70px}
.quick{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.quick button{min-height:32px;padding:0 10px;font-size:.8rem}
.ptabs{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 10px}
.ptabs a{padding:.4rem .75rem;border-radius:999px;border:1px solid var(--border-2);color:var(--text-2);font-size:.84rem}
.ptabs a.on{background:var(--surface-3);color:var(--text)}
.row form{margin:0}
.row .btn.sm{min-height:36px;padding:0 10px;font-size:.82rem}
.ttl a.lnk{color:var(--accent);font-weight:500;font-size:.84rem}
.ok-msg{color:var(--ok);margin:.4rem 0}.err-msg{color:var(--bad);margin:.4rem 0}
@media(max-width:520px){.pform{grid-template-columns:1fr}}
</style>"""

QUICK_JS = """<script>
function plDue(n){var d=new Date(Date.now()+9*3600e3+n*864e5);
document.getElementById('pl-due').value=d.toISOString().slice(0,10);return false}
</script>"""


def _counts(b: pl.Buckets) -> tuple[int, int, int]:
    return len(b.overdue), len(b.today), len(b.week)


def card_badge(b: Optional[pl.Buckets] = None) -> str:
    try:
        pl.refresh_signals()  # 오래됐을 때만 별도 프로세스로 다시 만든다(기다리지 않음)
    except Exception:  # noqa: BLE001
        pass
    try:
        b = b or pl.buckets()
    except Exception:  # noqa: BLE001 - 개요는 할 일 파일 문제와 무관하게 떠야 한다
        return ui.pill("확인 불가", "muted")
    overdue, today, week = _counts(b)
    pills = []
    if overdue:
        pills.append(ui.pill(f"지남 {overdue}", "bad"))
    if today:
        pills.append(ui.pill(f"오늘 {today}", "warn"))
    if week:
        pills.append(ui.pill(f"이번 주 {week}", "info"))
    return "".join(pills) or ui.pill("급한 일 없음", "ok")


def notion_badge() -> str:
    return ui.pill("바로가기", "info")


def _dday(t: pl.Task, today) -> str:
    left = t.days_left(today)
    if t.done:
        return ui.pill("완료", "ok")
    if left is None:
        return ui.pill("언젠가", "muted")
    if left < 0:
        return ui.pill(f"{-left}일 지남", "bad")
    if left == 0:
        return ui.pill("오늘", "warn")
    return ui.pill(f"D-{left}", "warn" if left <= 2 else "info")


def _button(action: str, task_id: str, label: str, *, area: str = "", confirm: str = "", primary: bool = False) -> str:
    onsubmit = f' onsubmit="return confirm(\'{E(confirm)}\')"' if confirm else ""
    return (f'<form method="post" action="/planner/{action}"{onsubmit}>'
            f'<input type="hidden" name="id" value="{E(task_id)}"><input type="hidden" name="area" value="{E(area)}">'
            f'<button class="btn sm{" primary" if primary else ""}" type="submit">{E(label)}</button></form>')


def _task_row(t: pl.Task, today, area: str) -> str:
    bits = [t.area]
    if t.project:
        bits.append(t.project)
    if t.due:
        bits.append(t.due[5:].replace("-", "/") + f"({'월화수목금토일'[t.due_date().weekday()]})" if t.due_date() else t.due)
    if t.repeat:
        bits.append(pl.REPEATS.get(t.repeat, t.repeat))
    if t.origin:
        bits.append(f"기록: {t.origin}")
    if t.note:
        first = t.note.strip().splitlines()[0]
        bits.append(first[:80] + ("…" if len(first) > 80 else ""))
    link = ""
    if t.link and t.source == "signal":
        link = f' <a class="lnk" href="{E(t.link)}" target="_blank" rel="noopener">앱 ↗</a>'
    elif t.link and t.source != "contest":
        ext = t.link.startswith("http")
        target = ' target="_blank" rel="noopener"' if ext else ""
        label = "Notion ↗" if "notion." in t.link else ("열기 ↗" if ext else "열기")
        link = f' <a class="lnk" href="{E(t.link)}"{target}>{label}</a>'
    if t.source == "contest":
        end = (_dday(t, today) + f'<a class="btn sm" href="{E(t.link)}">대회</a>'
               + _button("submitted", t.id, "제출 완료", area=area, primary=True,
                         confirm="이 대회를 '제출 완료'로 바꿀까요? 할 일 목록에서 사라집니다."))
    elif t.source == "signal":
        end = _dday(t, today) + _button("dismiss", t.id, "확인함", area=area, primary=True)
    elif t.done:
        end = _dday(t, today) + _button("undo", t.id, "되돌리기", area=area)
    else:
        end = (_dday(t, today) + f'<a class="btn sm" href="/planner?edit={E(t.id)}" aria-label="고치기">⋯</a>'
               + _button("done", t.id, "다음 회차" if t.repeat else "완료", area=area, primary=True))
    icon = SIGNAL_ICONS.get(t.kind, "📈") if t.source == "signal" else AREA_ICONS.get(t.area, "•")
    return ui.row(t.title, icon=icon, desc=" · ".join(bits), end_html=end,
                  title_extra_html=link)


def _add_form(values: Optional[dict] = None, *, edit: Optional[pl.Task] = None) -> str:
    v = values or (edit.to_json() if edit else {})
    action = "update" if edit else "add"
    areas = "".join(f'<option{" selected" if v.get("area") == a else ""}>{E(a)}</option>' for a in pl.AREAS)
    repeats = "".join(f'<option value="{k}"{" selected" if v.get("repeat", "") == k else ""}>{E(lbl)}</option>'
                      for k, lbl in pl.REPEATS.items())
    hidden = f'<input type="hidden" name="id" value="{E(edit.id)}">' if edit else ""
    quick = "" if edit else ('<div class="quick">' + "".join(
        f'<button class="btn" type="button" onclick="return plDue({n})">{lbl}</button>'
        for n, lbl in ((0, "오늘"), (1, "내일"), (3, "3일 뒤"), (7, "1주 뒤"))) + "</div>")
    extra = ""
    if edit:
        extra = ('<p style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">'
                 '<button class="btn primary" type="submit">저장</button><a class="btn" href="/planner">취소</a></p></form>'
                 + _button("delete", edit.id, "이 할 일 삭제", confirm="이 할 일을 지울까요? 되살릴 수 없습니다."))
    else:
        extra = '<p style="margin-top:10px"><button class="btn primary" type="submit">+ 할 일 추가</button></p></form>'
    return (f'<form class="panel" method="post" action="/planner/{action}" autocomplete="off">{hidden}'
            '<div class="pform">'
            f'<div class="full"><label for="pl-title">할 일</label><input id="pl-title" name="title" required maxlength="200" '
            f'placeholder="예: 대회 시연 녹화 영상 찍기" value="{E(v.get("title", ""))}"{"" if edit else " autofocus"}></div>'
            f'<div><label for="pl-area">분야</label><select id="pl-area" name="area">{areas}</select></div>'
            f'<div><label for="pl-due">마감</label><input id="pl-due" name="due" type="date" value="{E(v.get("due", ""))}">{quick}</div>'
            f'<div><label for="pl-project">대회·저장소·종목 (선택)</label><input id="pl-project" name="project" maxlength="80" '
            f'placeholder="arbiter-hacks-v1, Quant, NVDA" value="{E(v.get("project", ""))}"></div>'
            f'<div><label for="pl-repeat">반복</label><select id="pl-repeat" name="repeat">{repeats}</select></div>'
            f'<div class="full"><label for="pl-link">링크 (Notion 페이지 등, 선택)</label><input id="pl-link" name="link" '
            f'placeholder="https://www.notion.so/..." value="{E(v.get("link", ""))}"></div>'
            f'<div class="full"><label for="pl-note">메모 (선택)</label><textarea id="pl-note" name="note" maxlength="2000">'
            f'{E(v.get("note", ""))}</textarea></div>'
            f'</div>{extra}')


def _notion_form() -> str:
    current = pl.notion_url()
    shown = "" if current == pl.DEFAULT_NOTION_URL else current
    return ('<details class="panel" style="margin-top:10px"><summary>Notion 바로가기 주소 바꾸기</summary>'
            '<form method="post" action="/planner/notion" class="pform" style="margin-top:10px">'
            '<div class="full"><label for="pl-notion">개요의 Notion 슬롯이 열 주소 (비우면 notion.so — 마지막으로 연 워크스페이스)</label>'
            f'<input id="pl-notion" name="url" placeholder="https://www.notion.so/내-워크스페이스/..." value="{E(shown)}"></div>'
            '<div><button class="btn" type="submit">저장</button></div></form></details>')


def render_body(*, area: str = "", edit_id: str = "", message: str = "", error: str = "",
                values: Optional[dict] = None, now: Optional[datetime] = None) -> str:
    today = pl.today_kst(now)
    b = pl.buckets(now=now)
    if area in pl.AREAS:
        for name in ("overdue", "today", "week", "later", "someday", "done"):
            setattr(b, name, [t for t in getattr(b, name) if t.area == area])
    overdue, today_n, week_n = _counts(b)
    if overdue:
        tone, title = "bad", f"기한이 지난 일 {overdue}개"
        sub = "완료했으면 '완료', 미뤄야 하면 ⋯ 에서 마감을 바꾸세요. 대회는 AI 대회 화면에서 상태를 '제출 완료'로."
    elif today_n:
        tone, title, sub = "warn", f"오늘 할 일 {today_n}개", f"7일 안에 마감인 일은 {week_n}개입니다."
    elif week_n:
        tone, title, sub = "ok", "오늘 마감인 일은 없습니다", f"7일 안에 마감인 일 {week_n}개."
    else:
        tone, title, sub = "ok", "급한 일이 없습니다", "새 할 일은 아래에서 추가하세요."
    tiles = ui.stats([
        ui.stat("기한 지남", str(overdue), "", "bad" if overdue else "ok"),
        ui.stat("오늘", str(today_n), today.strftime("%m/%d") + f"({'월화수목금토일'[today.weekday()]})",
                "warn" if today_n else "ok"),
        ui.stat("이번 주", str(week_n), f"7일 안 · ~{pl.week_end(today):%m/%d}", ""),
        ui.stat("나중·언젠가", str(len(b.later) + len(b.someday)), "", ""),
    ])
    tabs = '<div class="ptabs">' + "".join(
        f'<a class="{"on" if a == area else ""}" href="/planner{"?area=" + quote(a) if a else ""}">'
        f'{E(AREA_ICONS.get(a, "") + " " + a if a else "전체")}</a>' for a in ("",) + pl.AREAS) + "</div>"
    msg = (f'<p class="err-msg" role="alert">{E(error)}</p>' if error else "") + \
          (f'<p class="ok-msg">{E(message)}</p>' if message else "")

    edit = next((t for t in pl.list_tasks() if t.id == edit_id), None) if edit_id else None
    if edit:
        form_html = ui.section("할 일 고치기", _add_form(values, edit=edit))
    else:
        form_html = (f'<details class="panel"{" open" if values or error else ""} style="margin:12px 0">'
                     '<summary><b>+ 새 할 일</b></summary><div style="margin-top:10px">'
                     f'{_add_form(values)}</div></details>')

    def sec(name: str, items: list[pl.Task], empty_hidden: bool = True) -> str:
        if not items and empty_hidden:
            return ""
        return ui.section(f"{name} ({len(items)})", ui.row_list(_task_row(t, today, area) for t in items))

    lists = (sec("⚠ 기한 지남", b.overdue) + sec("오늘", b.today, empty_hidden=False) + sec("이번 주 (7일 안)", b.week, False)
             + sec("나중", b.later) + sec("언젠가 (마감 없음)", b.someday) + sec("최근 완료", b.done[:20]))
    return (f'{msg}{ui.verdict(tone, title, sub)}{tiles}{form_html}{tabs}{lists}'
            f'{_signals_note()}{ui.callout(AUTO_HELP, icon="💡")}{_notion_form()}')


AUTO_HELP = ("따로 적지 않아도 자동으로 보이는 항목: 🏁 아직 제출하지 않은 <a href=\"/contests\">AI 대회</a>(메모의 할 일·사람 몫 포함 — "
             "제출했으면 '제출 완료'), 🔻 보유 종목 매도·🔍 재검토(포트폴리오 보유 × 최신 챔피언 추천), 📡 관심종목 타점, "
             "🔄 다음 코어 리밸런싱. 시그널은 '확인함'으로 지웁니다. 주문은 하지 않습니다.")


def _signals_note() -> str:
    st = pl.signals_status()
    if st["generated_at"] is None:
        text = "주식 시그널을 처음 계산하는 중입니다(1분 안쪽). 잠시 뒤 새로고침하세요." if st["running"] else "주식 시그널 파일이 아직 없습니다."
    else:
        text = f"주식 시그널: {st['age_min']}분 전 계산" + (" · 지금 다시 계산 중" if st["running"] else " · 30분마다 자동 갱신")
    errs = "".join(ui.note(e, "warn") for e in st["errors"][:3])
    button = ('<form method="post" action="/planner/refresh" style="display:inline;margin-left:8px">'
              '<button class="btn sm" type="submit">지금 다시 계산</button></form>')
    return f'<p class="meta" style="margin-top:14px">{E(text)}{button}</p>{errs}'


def _one(form: dict, key: str) -> str:
    return (form.get(key) or [""])[0]


def handle_post(path: str, form: dict) -> tuple[str, Optional[str], dict]:
    """(돌아갈 주소, 오류 문구 또는 None, 폼 값). 오류면 서버가 같은 화면을 오류와 함께 다시 그린다."""
    action = path.removeprefix("/planner/")
    area = _one(form, "area")
    back = "/planner" + (f"?area={quote(area)}" if area in pl.AREAS and action in ("done", "undo", "dismiss") else "")
    fields = {k: _one(form, k) for k in ("title", "area", "due", "project", "link", "note", "repeat")}
    try:
        if action == "add":
            t = pl.add_task(**fields)
            return f"/planner?msg={quote(f'추가했습니다: {t.title}')}", None, {}
        if action == "update":
            pl.update_task(_one(form, "id"), **fields)
            return f"/planner?msg={quote('저장했습니다.')}", None, {}
        if action == "done":
            pl.set_done(_one(form, "id"), True)
            return back, None, {}
        if action == "undo":
            pl.set_done(_one(form, "id"), False)
            return back, None, {}
        if action == "delete":
            pl.delete_task(_one(form, "id"))
            return f"/planner?msg={quote('삭제했습니다.')}", None, {}
        if action == "dismiss":
            pl.dismiss(_one(form, "id"))
            return back, None, {}
        if action == "submitted":
            item = _one(form, "id")
            if not item.startswith("contest:"):
                raise pl.PlannerError("대회 항목이 아닙니다.")
            pl.mark_contest_submitted(item.removeprefix("contest:"))
            return f"/planner?msg={quote('대회를 제출 완료로 바꿨습니다.')}", None, {}
        if action == "refresh":
            pl.refresh_signals(force=True)
            return f"/planner?msg={quote('주식 시그널을 다시 계산합니다. 1분쯤 뒤 새로고침하세요.')}", None, {}
        if action == "notion":
            pl.set_notion_url(_one(form, "url"))
            return f"/planner?msg={quote('Notion 주소를 저장했습니다.')}", None, {}
    except pl.PlannerError as exc:
        return "/planner" + (f"?edit={_one(form, 'id')}" if action == "update" else ""), str(exc), fields
    return "/planner", "알 수 없는 요청입니다.", {}


def handle_api(action: str, form: dict) -> tuple[int, dict]:
    """VM 안의 Claude·Codex 세션이 `plan` 명령으로 부르는 API(로컬 직접 접속만 — server.py 가 확인).

    add: key·title 필수, area·due·project·link·note·origin 선택 → 같은 key 의 열린 할 일은 갱신
    done: key → 그 할 일 완료(파기)
    list: project 선택 → 열린 할 일(직접 기록 + 세션 기록)
    """
    try:
        if action == "add":
            task, created = pl.upsert_by_key(_one(form, "key"), _one(form, "title"), area=_one(form, "area") or "기타",
                                             due=_one(form, "due"), project=_one(form, "project"), link=_one(form, "link"),
                                             note=_one(form, "note"), origin=_one(form, "origin"))
            return 200, {"ok": True, "created": created, "task": task.to_json()}
        if action == "done":
            return 200, {"ok": True, "closed": pl.done_by_key(_one(form, "key"))}
        if action == "list":
            project = _one(form, "project").strip().lower()
            items = [t.to_json() for t in pl.list_tasks() if not t.done
                     and (not project or project in (t.project or "").lower() or project in (t.key or ""))]
            return 200, {"ok": True, "tasks": items}
    except pl.PlannerError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "unknown action"}


HEAD_EXTRA = FORM_CSS + QUICK_JS
