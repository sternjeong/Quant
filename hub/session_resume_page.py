"""관제 허브 '세션 자동 재개' 화면 — 사용량 한도로 멈춘 Claude/Codex 대화 세션 목록과 켜기/끄기.

원천: data/session_resume/state.json(deploy/session_resume/resumer.py 가 5분마다 씀, 읽기 전용).
쓰기: data/session_resume/toggles.json — 전체 스위치와 세션별 스위치. 기록이 없으면 켜짐이 기본이다.
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hub import ui

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "session_resume"

STATUS = {
    "waiting": ("초기화 대기", "warn"),
    "resuming": ("이어서 진행 중", "info"),
    "resumed": ("이어서 진행됨", "ok"),
    "continued": ("직접 이어 감", "muted"),
    "off": ("꺼짐", "muted"),
    "gave_up": ("여러 번 실패 — 중단", "bad"),
    "expired": ("너무 오래됨 — 자동 재개 안 함", "muted"),
}


def _read(name: str, default: Any) -> Any:
    try:
        data = json.loads((STATE_DIR / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def load_toggles() -> dict:
    return _read("toggles.json", {})


def set_toggle(key: Optional[str], on: bool, actor: str = "hub") -> None:
    """key=None 이면 전체 스위치. 원자적으로 덮어쓴다(재개기는 읽기만 한다)."""
    toggles = load_toggles()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if key is None:
        toggles.update(enabled=bool(on), updated_at=stamp, actor=actor)
    else:
        toggles.setdefault("sessions", {})[key] = {"enabled": bool(on), "updated_at": stamp, "actor": actor}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_DIR / "toggles.json.tmp"
    tmp.write_text(json.dumps(toggles, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_DIR / "toggles.json")


def collect() -> dict:
    state = _read("state.json", {})
    toggles = load_toggles()
    sessions = sorted((state.get("sessions") or {}).values(), key=lambda e: e.get("stopped_at") or "", reverse=True)
    return {"state_ok": bool(state), "updated_at": state.get("updated_at"), "enabled": bool(toggles.get("enabled", True)),
            "sessions": sessions, "history": state.get("history") or [], "toggles": toggles.get("sessions") or {}}


def _kst(value: Any) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return html.escape(str(value))
    from datetime import timedelta

    return (dt.astimezone(timezone(timedelta(hours=9)))).strftime("%m-%d %H:%M") + " KST"


def card_badge(data: dict) -> str:
    if not data.get("enabled"):
        return ui.pill("꺼짐", "muted")
    rows = data.get("sessions") or []
    running = sum(1 for e in rows if e.get("status") == "resuming")
    waiting = sum(1 for e in rows if e.get("status") == "waiting")
    if running:
        return ui.pill(f"진행 중 {running}", "info")
    if waiting:
        return ui.pill(f"대기 {waiting}", "warn")
    return ui.pill("켜짐", "ok")


def _button(action_key: str, on: bool) -> str:
    label, val, tone = ("끄기", "0", "#5a2a2a") if on else ("켜기", "1", "#2a5a34")
    return (f'<form method="post" action="/session-resume/toggle" style="display:inline">'
            f'<input type="hidden" name="key" value="{html.escape(action_key)}"><input type="hidden" name="on" value="{val}">'
            f'<button type="submit" style="background:{tone};color:#fff;border:0;border-radius:8px;padding:.35rem .9rem;'
            f'cursor:pointer">{label}</button></form>')


def _where(e: dict) -> str:
    cwd = e.get("cwd") or ""
    return f'{html.escape(e.get("backend", "").capitalize())} · {html.escape(e.get("user", ""))} · <code>{html.escape(cwd)}</code>'


def render_body(data: dict) -> str:
    master = data.get("enabled", True)
    head = (
        '<p class="lead">Claude Code·Codex 대화 세션이 사용량 한도("You\'ve hit your limit")로 멈추면, 한도가 초기화된 뒤 '
        'VM 이 같은 세션을 자동으로 이어서 진행시킵니다. 5분마다 확인하고, 시작·완료·실패는 텔레그램으로 알립니다.</p>'
        + ui.kv_table([
            ("전체 자동 재개", (ui.pill("켜짐", "ok") if master else ui.pill("꺼짐", "muted")) + " " + _button("*", master)),
            ("마지막 확인", _kst(data.get("updated_at")) if data.get("state_ok") else "아직 기록 없음(재개기 타이머가 아직 안 돌았음)"),
        ])
    )
    rows = []
    for e in data.get("sessions") or []:
        label, tone = STATUS.get(e.get("status"), (e.get("status") or "?", "muted"))
        on = bool((data["toggles"].get(e["key"]) or {}).get("enabled", True))
        when = (f'멈춤 {_kst(e.get("stopped_at"))}<br>초기화 {_kst(e.get("reset_at"))}'
                f'<br>재개 예정 {_kst(e.get("due_at"))}')
        extra = f'<br><small>{html.escape(e["note"])}</small>' if e.get("note") else ""
        unit = f'<br><small>로그: <code>journalctl -u {html.escape(e["unit"])}</code></small>' if e.get("unit") else ""
        rows.append(
            f'<tr><td><b>{html.escape(e.get("title") or e.get("session_id", ""))}</b><br><small>{_where(e)}</small>'
            f'<br><small>세션 <code>{html.escape(e.get("session_id", ""))}</code></small></td>'
            f'<td>{ui.pill(label, tone)}<br><small>시도 {int(e.get("attempts") or 0)}회</small>{extra}{unit}</td>'
            f'<td><small>{when}</small></td><td>{_button(e["key"], on)}</td></tr>')
    table = ('<h2>한도로 멈춘 세션</h2><table><tr><th>세션</th><th>상태</th><th>시각</th><th>자동 재개</th></tr>'
             + "".join(rows) + '</table>') if rows else '<h2>한도로 멈춘 세션</h2><div class="empty">지금 한도로 멈춘 세션이 없습니다.</div>'
    hist = []
    for e in (data.get("history") or [])[:20]:
        label, tone = STATUS.get(e.get("status"), (e.get("status") or "?", "muted"))
        hist.append(f'<tr><td>{html.escape(e.get("title") or "")}<br><small>{_where(e)}</small></td>'
                    f'<td>{ui.pill(label, tone)}</td><td><small>{_kst(e.get("finished_at"))}</small></td></tr>')
    history = ('<h2>최근 기록</h2><table><tr><th>세션</th><th>결과</th><th>시각</th></tr>' + "".join(hist) + '</table>') if hist else ""
    tips = ui.note("세션별로 끄면 그 세션만 건너뛰고, 전체를 끄면 모두 멈춥니다(아무것도 지우지 않음). 자동 재개된 대화는 같은 세션 기록에 "
                   "이어 쓰이므로 VS Code 의 Claude/Codex 대화 목록에서 그 세션을 다시 열면 이어진 내용이 보입니다. 원래 세션의 권한 모드를 "
                   "그대로 쓰고 넓히지 않습니다. 초기화 후 36시간이 지난 오래된 세션은 깨우지 않습니다.")
    return head + table + history + tips
