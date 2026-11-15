"""관제 허브 '놀고 있는 AI 세션' 화면 — VM 에 떠 있는 Claude Code 대화 세션 목록, 닫기 버튼, 자동 정리 스위치.

원천: data/session_reaper/state.json(deploy/session_reaper/reaper.py 가 10분마다 씀, 읽기 전용).
쓰기: requests.json(닫기 요청 — 다음 회차(10분 안)에 수거기가 처리), toggles.json(자동 정리 켜기/끄기, 세션별 자동 정리 제외).
자동 정리는 기본 꺼짐이다. 이 화면은 프로세스에 직접 신호를 보내지 않는다(허브는 quant 계정, 세션은 다른 계정 소유).
"""

from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from hub import ui

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "session_reaper"
KEY_RE = re.compile(r"\d{1,9}-\d{1,20}")

STATUS = {
    "idle": ("놀고 있음", "warn"),
    "measuring": ("입력 없음 · CPU 재는 중", "muted"),
    "working": ("입력 없지만 혼자 일하는 중", "info"),
    "active": ("사용 중", "ok"),
    "no_tty": ("터미널 없음", "muted"),
}


def _read(name: str, default: Any) -> Any:
    try:
        data = json.loads((STATE_DIR / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _write(name: str, data: Any) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_DIR / f"{name}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_DIR / name)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def request_close(key: str, actor: str = "hub") -> None:
    reqs = _read("requests.json", {})
    reqs[key] = {"requested_at": _stamp(), "actor": actor}
    _write("requests.json", reqs)


def cancel_close(key: str) -> None:
    reqs = _read("requests.json", {})
    if reqs.pop(key, None) is not None:
        _write("requests.json", reqs)


def set_auto(on: bool, actor: str = "hub") -> None:
    toggles = _read("toggles.json", {})
    toggles.update(auto_close=bool(on), updated_at=_stamp(), actor=actor)
    _write("toggles.json", toggles)


def set_exclude(key: str, exclude: bool, actor: str = "hub") -> None:
    toggles = _read("toggles.json", {})
    toggles.setdefault("sessions", {})[key] = {"exclude": bool(exclude), "updated_at": _stamp(), "actor": actor}
    _write("toggles.json", toggles)


def collect() -> dict:
    state = _read("state.json", {})
    toggles = _read("toggles.json", {})
    return {"state_ok": bool(state), "updated_at": state.get("updated_at"), "sessions": state.get("sessions") or [],
            "totals": state.get("totals") or {}, "history": state.get("history") or [], "config": state.get("config") or {},
            "auto_close": bool(toggles.get("auto_close", False)), "excluded": {
                k for k, v in (toggles.get("sessions") or {}).items() if (v or {}).get("exclude")},
            "requests": _read("requests.json", {})}


def _kst(value: Any) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return html.escape(str(value))
    return dt.astimezone(timezone(timedelta(hours=9))).strftime("%m-%d %H:%M") + " KST"


def card_badge(data: dict) -> str:
    t = data.get("totals") or {}
    if not data.get("state_ok"):
        return ui.pill("기록 없음", "muted")
    if t.get("idle"):
        return ui.pill(f"놀고 있음 {t['idle']} · {round((t.get('idle_rss_mb') or 0) / 1024, 1)}GB", "warn")
    return ui.pill(f"세션 {t.get('sessions', 0)}", "ok")


def _form(action: str, fields: dict, label: str, tone: str) -> str:
    hidden = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(str(v))}">' for k, v in fields.items())
    return (f'<form method="post" action="{action}" style="display:inline">{hidden}'
            f'<button type="submit" style="background:{tone};color:#fff;border:0;border-radius:8px;padding:.3rem .8rem;'
            f'cursor:pointer;margin:.1rem">{label}</button></form>')


def render_body(data: dict) -> str:
    cfg = data.get("config") or {}
    t = data.get("totals") or {}
    auto = data.get("auto_close", False)
    head = (
        '<p class="lead">VM 에 떠 있는 Claude Code 대화 세션입니다. 하나가 메모리 200~400MB 를 붙잡고 있어, 잊고 둔 세션이 쌓이면 '
        '연구·서비스가 쓸 메모리가 모자랍니다. 닫아도 대화 기록은 남아 그 폴더에서 <code>claude --resume</code> 으로 다시 열 수 있습니다.</p>'
        + ui.kv_table([
            ("지금", f'세션 {t.get("sessions", 0)}개 · 메모리 약 {round((t.get("rss_mb") or 0) / 1024, 1)}GB · '
                     f'놀고 있음 {t.get("idle", 0)}개(약 {round((t.get("idle_rss_mb") or 0) / 1024, 1)}GB)'),
            ("놀고 있음 기준", f'터미널 입력 {cfg.get("idle_hours", 24):g}시간 넘게 없음 + 최근 {cfg.get("cpu_window_minutes", 60)}분 CPU 증가 '
                             f'{cfg.get("cpu_idle_seconds", 10):g}초 이하(혼자 일하는 자동 세션은 제외)'),
            ("자동 정리", (ui.pill("켜짐", "warn") if auto else ui.pill("꺼짐", "muted")) + " "
             + _form("/idle-sessions/auto", {"on": "0" if auto else "1"}, "끄기" if auto else "켜기",
                     "#5a2a2a" if auto else "#2a5a34")
             + '<br><small>켜면 10분마다 놀고 있음 세션 중 \'자동 정리 제외\'가 아닌 것을 닫고 텔레그램으로 알립니다.</small>'),
            ("마지막 확인", _kst(data.get("updated_at")) if data.get("state_ok") else "아직 기록 없음(수거기 타이머가 아직 안 돌았음)"),
        ])
    )
    rows = []
    for s in data.get("sessions") or []:
        label, tone = STATUS.get(s.get("status"), (s.get("status") or "?", "muted"))
        key = s["key"]
        where = (f'tmux <b>{html.escape(s["tmux"])}</b> · ' if s.get("tmux") else "") + f'<code>{html.escape(s.get("cwd") or "")}</code>'
        idle_h = s.get("input_idle_hours")
        idle_txt = "—" if idle_h is None else (f"{idle_h:g}시간 전" if idle_h < 48 else f"{idle_h / 24:.1f}일 전")
        growth = s.get("cpu_growth_window")
        growth_txt = "재는 중" if growth is None else f"{growth:g}초"
        pending = key in data.get("requests", {})
        excluded = key in data.get("excluded", set())
        if pending:
            action = ui.pill("닫기 요청됨 — 10분 안에 처리", "info") + _form("/idle-sessions/close", {"key": key, "cancel": "1"}, "취소", "#444")
        else:
            action = _form("/idle-sessions/close", {"key": key}, "닫기", "#5a2a2a")
        action += _form("/idle-sessions/exclude", {"key": key, "on": "0" if excluded else "1"},
                        "자동 정리 제외 해제" if excluded else "자동 정리 제외", "#444")
        rows.append(
            f'<tr><td>{where}<br><small>{html.escape(s.get("user", ""))} · pid {s["pid"]} · {html.escape(s.get("args") or "")}</small></td>'
            f'<td>{ui.pill(label, tone)}{" " + ui.pill("제외", "muted") if excluded else ""}</td>'
            f'<td><small>입력 {idle_txt}<br>CPU 증가 {growth_txt}</small></td><td>{round(s.get("rss_mb") or 0)}MB</td>'
            f'<td>{action}</td></tr>')
    table = ('<h2>세션</h2><table><tr><th>어디</th><th>상태</th><th>활동</th><th>메모리</th><th></th></tr>' + "".join(rows) + '</table>'
             ) if rows else '<h2>세션</h2><div class="empty">지금 떠 있는 Claude Code 대화 세션이 없습니다.</div>'
    hist = []
    for e in (data.get("history") or [])[:20]:
        why = "화면에서 닫기" if e.get("reason") == "requested" else "자동 정리"
        where = e.get("tmux") and f'tmux {html.escape(e["tmux"])}' or f'<code>{html.escape(e.get("cwd") or "")}</code>'
        hist.append(f'<tr><td>{where}</td><td>{why} · {html.escape(e.get("result") or "")}</td>'
                    f'<td>{round(e.get("rss_mb") or 0)}MB</td><td><small>{_kst(e.get("at"))}</small></td></tr>')
    history = ('<h2>최근 닫은 세션</h2><table><tr><th>어디</th><th>방법·결과</th><th>메모리</th><th>시각</th></tr>'
               + "".join(hist) + '</table>') if hist else ""
    tips = ui.note("닫기는 SIGTERM(10초 뒤 남아 있으면 SIGKILL)입니다. 닫기 직전에 같은 프로세스인지 다시 확인합니다. "
                   "텔레그램 봇·야간 에이전트·세션 자동 재개처럼 claude -p 로 도는 비대화 실행은 목록에 없고 건드리지 않습니다. "
                   "'혼자 일하는 중'은 사람이 입력하지 않아도 CPU 를 계속 쓰는 자동 세션이라 자동 정리 대상이 아닙니다.")
    return head + table + history + tips
