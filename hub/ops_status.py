"""관제 허브 '운영 상태' 화면 — 잡 건강·백업·서버 자원·타이머를 읽기만 해서 보여준다.

텔레그램으로만 오던 운영 신호를 허브에서도 본다. 어느 항목이 읽기에 실패해도 그 항목만 '확인 불가'로 표시하고 나머지는 그린다.
읽는 곳: core.job_health(스케줄러 잡 이력 DB), 백업 status.json(QUANT_BACKUP_STATUS_PATH, 기본 /opt/quant-backup/status.json),
/proc(uptime·meminfo)·디스크·/var/run/reboot-required, systemctl show(타이머 유닛).
"""

from __future__ import annotations

import html
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hub.status import get_unit_status

BACKUP_STATUS_PATH = Path(os.environ.get("QUANT_BACKUP_STATUS_PATH", "/opt/quant-backup/status.json"))
REBOOT_REQUIRED_PATH = Path(os.environ.get("QUANT_REBOOT_REQUIRED_PATH", "/var/run/reboot-required"))
BACKUP_STALE_HOURS = 30  # 하루 한 번 백업 + 여유
TIMERS = [
    ("quant-backup.timer", "백업"),
    ("quant-watchdog.timer", "워치독"),
    ("quant-vm-health.timer", "VM 헬스체크"),
    ("quant-auto-deploy.timer", "자동 배포"),
    ("quant-github-watch.timer", "GitHub 실패 감시"),
]
PROBLEM_LABELS = {"error": "오류", "missed": "놓침", "overdue": "미실행"}


def job_health_summary() -> dict[str, Any]:
    """{'ok': bool, 'counts': {...}, 'problems': [{'label','state','when'}], 'error': str|None}"""
    try:
        from core.job_health import compute_job_health, describe_problem

        h = compute_job_health()
        return {"ok": True, "counts": h["counts"], "error": None,
                "problems": [{"label": p["label"], "state": p["state"], "text": describe_problem(p)} for p in h["problems"]]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "counts": {}, "problems": [], "error": f"{type(exc).__name__}"}


def read_backup(path: Path = BACKUP_STATUS_PATH, now: Optional[float] = None) -> Optional[dict[str, Any]]:
    import json

    try:
        s = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    now = now or time.time()
    epoch = s.get("last_success_epoch")
    age_h = (now - epoch) / 3600 if isinstance(epoch, (int, float)) else None
    return {"last_success_at": s.get("last_success_at"), "age_hours": age_h, "stale": age_h is None or age_h > BACKUP_STALE_HOURS,
            "last_run_ok": bool(s.get("ok")), "error": s.get("error"), "offsite": bool(s.get("offsite_configured")),
            "push_error": s.get("push_error"), "drill_ok": s.get("restore_drill_ok"), "files": s.get("files")}


def system_info(root: str = "/") -> dict[str, Any]:
    info: dict[str, Any] = {}
    try:
        info["uptime_days"] = float(Path("/proc/uptime").read_text().split()[0]) / 86400
    except (OSError, ValueError, IndexError):
        info["uptime_days"] = None
    try:
        info["load"] = os.getloadavg()
        info["cpus"] = os.cpu_count()
    except OSError:
        info["load"], info["cpus"] = None, None
    try:
        du = shutil.disk_usage(root)
        info["disk_pct"] = du.used / du.total * 100
        info["disk_free_gb"] = du.free / 1e9
    except OSError:
        info["disk_pct"] = info["disk_free_gb"] = None
    try:
        mem = {k: int(v.split()[0]) for k, v in (l.split(":", 1) for l in Path("/proc/meminfo").read_text().splitlines())}
        info["mem_avail_pct"] = mem["MemAvailable"] / mem["MemTotal"] * 100
    except (OSError, ValueError, KeyError):
        info["mem_avail_pct"] = None
    info["reboot_required"] = REBOOT_REQUIRED_PATH.exists()
    return info


def _pill(text: str, tone: str) -> str:
    return f'<span class="badge {tone}">{html.escape(text)}</span>'


def _row(label: str, value: str) -> str:
    return f'<tr><th>{html.escape(label)}</th><td>{value}</td></tr>'


def _fmt(v: Optional[float], spec: str, unit: str = "") -> str:
    return "확인 불가" if v is None else format(v, spec) + unit


def jobs_badge(summary: dict[str, Any]) -> str:
    """스케줄러 카드용 배지."""
    if not summary["ok"]:
        return _pill("잡 이력 확인 불가", "unknown")
    n = summary["counts"].get("problem", 0)
    return _pill("잡 이상 없음", "active") if n == 0 else _pill(f"잡 이상 {n}개", "inactive")


def render_body(jobs: dict[str, Any], backup: Optional[dict], system: dict[str, Any], timers: list[tuple[str, str, str]]) -> str:
    parts = ['<p class="subtitle">서버가 스스로 건강한지 — 텔레그램 알림과 같은 원천을 읽어 보여줍니다.</p>']

    rows = []
    if not jobs["ok"]:
        rows.append(_row("상태", _pill("확인 불가", "unknown") + f" <small>{html.escape(jobs['error'] or '')}</small>"))
    else:
        c = jobs["counts"]
        rows.append(_row("요약", f"정상 {c.get('ok', 0)} · 대기 {c.get('pending', 0)} · 꺼짐 {c.get('disabled', 0)} · "
                                 f"이력 없음 {c.get('no-history', 0)} · <b>문제 {c.get('problem', 0)}</b>"))
        for p in jobs["problems"]:
            rows.append(_row(PROBLEM_LABELS.get(p["state"], p["state"]), html.escape(p["text"])))
    parts.append(f'<h2>스케줄러 잡 (밤사이 정말 돌았나)</h2><table>{"".join(rows)}</table>')

    rows = []
    if backup is None:
        rows.append(_row("상태", _pill("status.json 없음", "unknown") + " 백업이 아직 한 번도 안 돌았거나 경로가 다름"))
    else:
        age = backup["age_hours"]
        rows.append(_row("마지막 성공", _pill("최신" if not backup["stale"] else "오래됨", "active" if not backup["stale"] else "inactive")
                         + " " + html.escape(f"{backup['last_success_at']} ({_fmt(age, '.1f', '시간 전')})")))
        rows.append(_row("직전 실행", _pill("성공", "active") if backup["last_run_ok"] else
                         _pill("실패", "inactive") + f" <small>{html.escape(str(backup['error'] or ''))[:120]}</small>"))
        rows.append(_row("오프사이트(외부 저장소)", _pill("설정됨", "active") if backup["offsite"] else _pill("미설정", "unknown")))
        drill = backup["drill_ok"]
        rows.append(_row("복구 리허설", "기록 없음" if drill is None else _pill("통과", "active") if drill else _pill("실패", "inactive")))
    parts.append(f'<h2>백업</h2><table>{"".join(rows)}</table>')

    s = system
    load = s["load"]
    rows = [
        _row("가동 시간", _fmt(s["uptime_days"], ".1f", "일")),
        _row("부하(1/5/15분)", "확인 불가" if load is None else html.escape(" / ".join(f"{x:.2f}" for x in load) + f" (CPU {s['cpus']}개)")),
        _row("디스크", _fmt(s["disk_pct"], ".0f", f"% 사용 (여유 {_fmt(s['disk_free_gb'], '.1f', 'GB')})")),
        _row("메모리 여유", _fmt(s["mem_avail_pct"], ".0f", "%")),
        _row("재부팅 필요", _pill("필요", "inactive") + " 커널 등 업데이트 적용 대기" if s["reboot_required"] else "없음"),
    ]
    parts.append(f'<h2>서버 자원</h2><table>{"".join(rows)}</table>')

    rows = []
    for unit, label, state in timers:
        tone = "active" if state == "active" else "unknown" if state == "unknown" else "inactive"
        rows.append(_row(label, _pill(state, tone) + f" <small>{html.escape(unit)}</small>"))
    parts.append(f'<h2>예약 타이머</h2><table>{"".join(rows)}</table>')
    return "".join(parts)


def collect_timers() -> list[tuple[str, str, str]]:
    return [(u, label, get_unit_status(u).active_state) for u, label in TIMERS]
