"""관제 허브 '대회 탐색' 화면 — 매주 Claude 가 추린 해커톤·AI 대회를 'AI 자동 딸깍 / 어느 정도 신경' 으로 나눠 보여 준다.

원천(읽기 전용): /srv/contests/.scout/latest.json · status.json — deploy/contest_scout/run_scout.sh 가
ubuntu 계정으로 tmux 세션 'contest-scout' 에서 Claude 를 돌려 쓴다(매주 월 09:00 KST, quant-contest-scout.timer).
쓰기: '지금 찾기' 는 run-request 파일 하나만 만든다 — quant-contest-scout.path 가 감지해 서비스를 1회 실행한다.
"""

from __future__ import annotations

import html
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from hub import ui

SCOUT_DIR = Path(os.environ.get("QUANT_SCOUT_DIR", "/srv/contests/.scout"))
KST = timezone(timedelta(hours=9))
TIERS = (
    ("auto", "AI 자동 딸깍", "🤖", "제출물을 코딩 에이전트가 대부분 만들 수 있음 — 사람 몫은 가입·제출·녹화 정도(3시간 이하)"),
    ("light", "어느 정도만 신경", "🧑‍💻", "에이전트가 많이 하지만 아이디어·데모 영상·서류·발표에 하루~며칠은 직접 써야 함"),
)
E = html.escape


def _read(name: str) -> dict:
    try:
        data = json.loads((SCOUT_DIR / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def collect() -> dict:
    latest = _read("latest.json")
    items = [i for i in latest.get("items") or [] if isinstance(i, dict)]
    return {"latest": latest, "items": items, "status": _read("status.json"),
            "requested": (SCOUT_DIR / "run-request").exists()}


def request_run() -> Optional[str]:
    """run-request 파일을 만든다. 실패하면 사유를 돌려준다."""
    try:
        (SCOUT_DIR / "run-request").write_text(datetime.now(KST).isoformat(timespec="seconds"), encoding="utf-8")
    except OSError as exc:
        return f"요청 파일을 만들지 못했습니다: {exc}"
    return None


def _busy(data: dict) -> bool:
    return data["requested"] or data["status"].get("state") == "running"


def _kst(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value)).astimezone(KST).strftime("%m-%d %H:%M") + " KST"
    except (TypeError, ValueError):
        return "—"


def days_left(deadline: str, today: Optional[date] = None) -> Optional[int]:
    try:
        return (date.fromisoformat(str(deadline)[:10]) - (today or datetime.now(KST).date())).days
    except ValueError:
        return None


def card_badge(data: dict) -> str:
    if _busy(data):
        return ui.pill("찾는 중", "info")
    if data["status"].get("state") == "failed" and not data["items"]:
        return ui.pill("실패", "bad")
    if not data["items"]:
        return ui.pill("아직 없음", "muted")
    counts = {t: sum(1 for i in data["items"] if i.get("tier") == t) for t, *_ in TIERS}
    new = sum(1 for i in data["items"] if i.get("new"))
    return ui.pill(f"딸깍 {counts['auto']} · 신경 {counts['light']}" + (f" · 새 {new}" if new else ""), "ok")


def _item_row(item: dict, today: Optional[date]) -> str:
    left = days_left(item.get("deadline", ""), today)
    if left is None:
        end = ui.pill("마감 미정", "muted")
    elif left < 0:
        end = ui.pill("마감 지남", "muted")
    else:
        end = ui.pill("D-DAY" if left == 0 else f"D-{left}", "bad" if left <= 3 else "warn" if left <= 10 else "ok")
    if item.get("new"):
        end = ui.pill("NEW", "info") + end
    meta = " · ".join(x for x in (item.get("platform"), item.get("prize"),
                                  f"약 {item['effort_hours']}시간" if item.get("effort_hours") else "") if x)
    lines = [
        f"<b>할 일</b> {E(item.get('what_to_do') or '—')}",
        f"<b>사람 몫</b> {E(item.get('human_work') or '—')}",
        f"<b>왜 이 등급</b> {E(item.get('why') or '—')}",
        f"<b>자격</b> {E(item.get('eligibility') or '—')}"
        + (f" · <b>마감</b> {E(item.get('deadline'))} {E(item.get('deadline_note') or '')}" if item.get("deadline") else ""),
    ]
    below = '<div class="note">' + "<br>".join(lines) + "</div>"
    return ui.row(item.get("title", ""), href=item.get("url"), desc=meta, end_html=end, external=True, below_html=below)


def _run_button(data: dict) -> str:
    if _busy(data):
        return ui.pill("찾는 중 — 몇 분~수십 분 걸립니다", "info")
    return ('<form method="post" action="/contest-scout/run" style="display:inline">'
            '<button type="submit" style="background:#4c7dff;color:#fff;border:0;border-radius:8px;padding:.35rem .9rem;'
            'cursor:pointer">지금 찾기</button></form>')


def render_body(data: dict, today: Optional[date] = None, error: str = "") -> str:
    st, latest = data["status"], data["latest"]
    state = {"running": ui.pill("찾는 중", "info"), "ok": ui.pill("성공", "ok"),
             "failed": ui.pill("실패", "bad")}.get(st.get("state"), ui.pill("기록 없음", "muted"))
    out = [
        '<p class="lead">매주 월요일 09:00(KST)에 Claude 가 aichallenge4all·Devpost·Dacon·Kaggle 등을 훑어, 지금 참가할 수 있는 '
        '해커톤·AI 대회 중 해볼 만한 것을 난이도별로 추립니다. 이미 등록한 대회(AI 대회 화면)는 빼고 찾습니다.</p>',
        ui.callout(E(error), icon="⚠️", tone="bad") if error else "",
        ui.kv_table([
            ("최근 실행", f"{state} {E(st.get('message') or '')}"),
            ("시각", f"시작 {_kst(st.get('started_at'))} · 끝 {_kst(st.get('finished_at'))}"),
            ("이 목록", _kst(latest.get("generated_at")) if latest else "아직 없음"),
            ("수동 실행", _run_button(data)),
            ("진행 보기", "<code>tmux attach -t contest-scout</code> (ubuntu 계정) · 로그 "
                         f"<code>{E(st.get('log') or str(SCOUT_DIR / 'logs'))}</code>"),
        ]),
    ]
    if latest.get("notes"):
        out.append(ui.callout(E(latest["notes"]), icon="🗒"))
    for tier, title, icon, desc in TIERS:
        rows = [_item_row(i, today) for i in data["items"] if i.get("tier") == tier]
        out.append(f"<h2>{icon} {E(title)} <small>({len(rows)})</small></h2>"
                   f'<p class="subtitle">{E(desc)}</p>' + ui.row_list(rows))
    skipped = latest.get("skipped") or []
    if skipped:
        out.append("<h2>이번에 뺀 것</h2><table><tr><th>대회</th><th>사유</th></tr>" + "".join(
            f"<tr><td>{E(s.get('title', ''))}</td><td><small>{E(s.get('reason', ''))}</small></td></tr>" for s in skipped)
            + "</table>")
    if latest.get("sources_checked"):
        out.append(ui.note("확인한 곳: " + ", ".join(latest["sources_checked"])))
    return "".join(out)
