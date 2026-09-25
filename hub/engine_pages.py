"""관제 센터 엔진 상세 화면 — kind="engine" 슬롯(/status/<slot>)을 눌렀을 때 내용 있는 화면을 보여 준다(2026-09-25).

hub.server.render_status_page 가 먼저 render(slot) 을 부르고, None 이면 공통 화면(유닛 이름·시작 시각)을 쓴다.
모든 화면은 hub/ui.py 부품만 쓴다(폰 390px 기준, 가로 스크롤 없음).

- scheduler: 서비스 상태 + core.job_health 판정, 지표 타일, 앞으로 12시간 예정, 잡별 14일 실행 막대(DB 읽기만).
- codex-telegram: 서비스 상태·가동 시간, runner.py 의 /help 문구를 코드에서 읽은 명령 목록, 큐 DB 의 마지막 활동 시각과
  작업 상태별 개수(지시 원문·메시지·토큰은 읽지도 보여 주지도 않는다).
- vm-health: 타이머·서비스 상태, 지금 디스크·메모리·부하(ops_status.system_info), vm_health_check.sh 의 실제 임계값.

어느 부분이 읽기에 실패해도 그 부분만 '확인 불가'로 그리고 화면은 죽지 않는다.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from hub import ui
from hub.status import UnitStatus, get_unit_status

E = ui.E
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = PROJECT_ROOT / "deploy" / "codex_telegram" / "runner.py"
TELEGRAM_CONFIG_PATH = PROJECT_ROOT / "deploy" / "codex_telegram" / "config.json"
TELEGRAM_STATE_DEFAULT = "/opt/quant/.codex-telegram-state"
VM_HEALTH_SCRIPT = PROJECT_ROOT / "deploy" / "vm_health_check.sh"
VM_HEALTH_TIMER_UNIT = "quant-vm-health.timer"
REFRESH_SECONDS = 60
STRIP_DAYS = 14
UPCOMING_HOURS = 12
ERROR_MAX = 140
UTC = timezone.utc
KST = timezone(timedelta(hours=9))

# runner.py PROCESS_CATEGORIES 와 같은 순서·이름(텔레그램 /processes 에서 보는 묶음과 맞춘다).
CATEGORIES = (("alert", "🔔 알림"), ("research", "🔬 연구·기록"), ("maintenance", "🧰 유지보수"))
RESULT_PILLS = {
    "ok": ("성공", "ok"), "error": ("실패", "bad"), "missed": ("놓침", "bad"), "overdue": ("미실행", "warn"),
    "pending": ("대기", "info"), "no-history": ("이력 없음", "muted"),
}
BAD_STATUSES = ("error", "failed", "missed")


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------
def render(slot) -> Optional[str]:
    """슬롯 전용 화면 HTML. 전용 화면이 없는 슬롯(또는 engine 이 아닌 슬롯)은 None — 서버가 공통 화면을 쓴다."""
    if getattr(slot, "kind", None) != "engine":
        return None
    fn = RENDERERS.get(getattr(slot, "id", ""))
    if fn is None:
        return None
    try:
        return fn(slot)
    except Exception:  # noqa: BLE001 — 전용 화면이 깨져도 서버의 공통 화면으로 떨어지고 페이지는 열린다
        return None


def _unit_pill(status: UnitStatus, *, oneshot: bool = False) -> tuple[str, str]:
    if not status.is_known:
        return ui.pill("확인 불가", "muted"), "muted"
    if status.is_active:
        return ui.pill("실행 중", "ok"), "ok"
    if status.active_state == "failed":
        return ui.pill("실패", "bad"), "bad"
    if oneshot and status.active_state == "inactive":
        return ui.pill("대기(정상)", "muted"), "ok"  # 한 번 돌고 끝나는 서비스는 평소에 꺼져 있는 게 정상
    return ui.pill("멈춤", "bad"), "bad"


_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\s+([A-Za-z+\-0-9]+))?")


def parse_systemd_time(text: str) -> Optional[datetime]:
    """'Thu 2026-09-25 03:00:00 UTC' 같은 systemd 시각 → tz-aware. 모르는 시간대 약어는 이 서버의 현지 시각으로 본다."""
    m = _TS_RE.search(text or "")
    if not m:
        return None
    naive = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    zone = (m.group(2) or "").upper()
    if zone in ("UTC", "GMT", "Z"):
        return naive.replace(tzinfo=UTC)
    if zone == "KST":
        return naive.replace(tzinfo=KST)
    return naive.astimezone()


def _kst(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(KST)


def _kst_text(moment: Optional[datetime], fmt: str = "%m-%d %H:%M") -> str:
    return "—" if moment is None else _kst(moment).strftime(fmt) + " KST"


def _duration(delta: timedelta) -> str:
    mins = max(0, int(delta.total_seconds() // 60))
    days, rem = divmod(mins, 1440)
    hours, m = divmod(rem, 60)
    if days:
        return f"{days}일 {hours}시간"
    if hours:
        return f"{hours}시간 {m}분"
    return f"{m}분"


def _systemctl_props(unit: str, *props: str) -> dict[str, str]:
    """읽기 전용 systemctl show. 실패하면 빈 dict."""
    args = ["systemctl", "show", unit]
    for p in props:
        args += ["-p", p]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=5, check=True).stdout
    except (subprocess.SubprocessError, OSError):
        return {}
    return dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)


def _stamp(now: datetime) -> str:
    return f'<p class="stamp">마지막 갱신 {_kst_text(now, "%Y-%m-%d %H:%M:%S")} · {REFRESH_SECONDS}초마다 자동 새로고침</p>'


def _page(slot, body: str) -> str:
    head = f'<h1>{E(slot.title)}</h1><p class="lead">{E(slot.description)}</p>'
    return ui.page(slot.title, head + body, crumbs=(("/", "개요"), ("", slot.category)), refresh=REFRESH_SECONDS)


# ---------------------------------------------------------------------------
# 스케줄러
# ---------------------------------------------------------------------------
def _trigger(job):
    from apscheduler.triggers.cron import CronTrigger

    return CronTrigger(**job.cron)


def fires_between(job, start: datetime, end: datetime) -> list[datetime]:
    """[start, end) 사이의 예정 시각(tz-aware). cron 의 요일·시간대를 그대로 따른다."""
    trig = _trigger(job)
    out: list[datetime] = []
    current = trig.get_next_fire_time(None, start)
    while current is not None and current < end:
        if current >= start:
            out.append(current)
        current = trig.get_next_fire_time(current, current + timedelta(seconds=1))
    return out


def _run_day(run) -> "datetime.date":
    moment = run.scheduled_at or run.recorded_at
    return _kst(moment).date()


def day_cells(job, runs: list, *, tracking_since: Optional[datetime], enabled: bool, now: datetime,
              grace: timedelta, days: int = STRIP_DAYS) -> list[tuple[str, str]]:
    """잡 하나의 최근 days 일(KST, 오래된 날 → 오늘) 칸. [(tone, 툴팁)].

    기록이 있으면 그날 실패·놓침이 하나라도 있으면 bad, 아니면 ok. 기록이 없으면: 꺼진 잡이면 muted(꺼짐),
    그날 예정이 없었으면 muted(예정 없음), 추적 시작 전 예정이면 none(추적 이전), 아직 유예 시간 안이면 none(대기),
    그 밖에는 warn(예정이었는데 기록 없음). tracking_since 는 naive UTC 또는 tz-aware.
    """
    by_day: dict = {}
    for r in runs:
        by_day.setdefault(_run_day(r), []).append(r)
    since = None
    if tracking_since is not None:
        since = tracking_since if tracking_since.tzinfo else tracking_since.replace(tzinfo=UTC)
    today = _kst(now).date()
    cells = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        label = f"{day:%m-%d}"
        day_runs = by_day.get(day, [])
        if day_runs:
            if any(r.status in BAD_STATUSES for r in day_runs):
                cells.append(("bad", f"{label} 실패·놓침"))
            else:
                cells.append(("ok", f"{label} 성공"))
            continue
        if not enabled:
            cells.append(("muted", f"{label} 꺼짐"))
            continue
        start = datetime(day.year, day.month, day.day, tzinfo=KST)
        fires = fires_between(job, start, start + timedelta(days=1))
        if not fires:
            cells.append(("muted", f"{label} 예정 없음"))
        elif since is None or all(f < since for f in fires):
            cells.append(("none", f"{label} 추적 이전"))
        elif any(f + grace > now for f in fires):
            cells.append(("none", f"{label} 예정 {_kst(fires[0]):%H:%M} (아직)"))
        else:
            cells.append(("warn", f"{label} 예정이었는데 기록 없음"))
    return cells


def upcoming(jobs_meta: list[dict], now: datetime, hours: int = UPCOMING_HOURS) -> list[dict]:
    """켜진 잡의 [now, now+hours) 예정. 시각 순."""
    out = []
    for m in jobs_meta:
        if not m["enabled"]:
            continue
        for f in fires_between(m["job"], now, now + timedelta(hours=hours)):
            out.append({"at": f, "label": m["label"], "job_id": m["job"].job_id})
    return sorted(out, key=lambda x: (x["at"], x["label"]))


def _in_text(delta: timedelta) -> str:
    return f"{_duration(delta)} 후"


def collect_scheduler(now: Optional[datetime] = None) -> dict[str, Any]:
    """스케줄러 화면 데이터. 부분 실패는 error 키에 담고 나머지는 계속 채운다."""
    from core import job_health
    from core.job_schedule import SCHEDULED_JOBS
    from core.models import SchedulerJobRun
    from core.process_registry import PROCESS_REGISTRY

    now = now or datetime.now(UTC)
    data: dict[str, Any] = {"now": now, "health": None, "health_error": None, "runs": {}, "runs_error": None}
    try:
        data["health"] = job_health.compute_job_health(now)
    except Exception as exc:  # noqa: BLE001
        data["health_error"] = type(exc).__name__
    try:
        cutoff = (now - timedelta(days=STRIP_DAYS + 1)).astimezone(UTC).replace(tzinfo=None)
        with job_health.get_session() as session:
            rows = (session.query(SchedulerJobRun.job_id, SchedulerJobRun.status, SchedulerJobRun.error,
                                  SchedulerJobRun.scheduled_at, SchedulerJobRun.recorded_at)
                    .filter(SchedulerJobRun.recorded_at >= cutoff)
                    .order_by(SchedulerJobRun.recorded_at.asc()).all())
        for r in rows:
            data["runs"].setdefault(r.job_id, []).append(r)
    except Exception as exc:  # noqa: BLE001
        data["runs_error"] = type(exc).__name__

    health_by_id = {e["job_id"]: e for e in (data["health"] or {}).get("jobs", [])}
    meta = []
    for job in SCHEDULED_JOBS:
        reg = PROCESS_REGISTRY.get(job.process_key, {})
        entry = health_by_id.get(job.job_id)
        if entry is not None:
            enabled = entry["state"] != "disabled"
        else:
            try:
                enabled = job_health.is_enabled(job.process_key)
            except Exception:  # noqa: BLE001
                enabled = True
        meta.append({"job": job, "label": reg.get("label", job.job_id), "category": reg.get("category", ""),
                     "enabled": enabled, "health": entry,
                     "grace": job_health.GRACE_OVERRIDES.get(job.job_id, job_health.DEFAULT_GRACE)})
    data["jobs"] = meta
    return data


def _scheduler_verdict(unit: UnitStatus, data: dict) -> str:
    health = data["health"]
    if health is None:
        if unit.is_known and not unit.is_active:
            return ui.verdict("bad", "스케줄러가 멈춰 있습니다", "잡 이력도 읽지 못했습니다. 텔레그램으로 개발 요청을 보내 확인하세요.")
        return ui.verdict("muted", "확인 불가", f"잡 이력 DB 를 읽지 못했습니다({data['health_error']}).")
    counts = health["counts"]
    hard = counts.get("error", 0) + counts.get("missed", 0)
    late = counts.get("overdue", 0)
    problems = "".join(ui.callout(E(_describe(p)), icon="!", tone="bad" if p["state"] != "overdue" else "warn")
                       for p in health["problems"])
    if unit.is_known and not unit.is_active:
        return ui.verdict("bad", "스케줄러가 멈춰 있습니다", "지금은 어떤 잡도 돌지 않습니다.") + problems
    if hard:
        return ui.verdict("bad", f"문제 잡 {hard + late}개", "가장 최근 예정 실행이 실패했거나 놓쳤습니다.") + problems
    if late:
        return ui.verdict("warn", f"주의: 기록 없는 잡 {late}개", "예정 시각이 지났는데 실행 기록이 없습니다.") + problems
    if not unit.is_known:
        return ui.verdict("muted", "서비스 상태 확인 불가", "잡 기록은 정상입니다. VM 에서 열면 서비스 상태가 보입니다.")
    return ui.verdict("ok", "정상", "스케줄러가 돌고 있고 최근 예정된 잡이 모두 기록됐습니다.")


def _describe(entry: dict) -> str:
    from core.job_health import describe_problem

    return describe_problem(entry)


def _last_failure(runs: list) -> Optional[str]:
    for r in reversed(runs):
        if r.status in BAD_STATUSES:
            text = (r.error or ("실행 시각을 놓침" if r.status == "missed" else "오류 내용 없음")).replace("\n", " ")
            if len(text) > ERROR_MAX:
                text = text[:ERROR_MAX] + "…"
            return f"마지막 실패 {_kst_text(r.recorded_at)}: {text}"
    return None


def _job_row(m: dict, data: dict) -> str:
    from hub.guide.live import format_when

    job, entry = m["job"], m["health"]
    runs = data["runs"].get(job.job_id, [])
    onoff = ui.pill("켜짐", "ok") if m["enabled"] else ui.pill("꺼짐", "muted")
    if entry is None:
        result = ui.pill("확인 불가", "muted")
    elif entry["state"] == "disabled":
        result = ""
    else:
        text, tone = RESULT_PILLS.get(entry["state"], (entry["state"], "muted"))
        result = ui.pill(text, tone)
    below = ""
    if data["runs_error"] is None:
        tracking = (data["health"] or {}).get("tracking_since")
        cells = day_cells(job, runs, tracking_since=tracking, enabled=m["enabled"], now=data["now"], grace=m["grace"])
        below = ui.strip(cells, f"{STRIP_DAYS}일 전", "오늘")
        failure = _last_failure(runs)
        if failure:
            below += ui.note(failure, "bad")
    return ui.row(m["label"], desc=format_when(job.cron), end_html=onoff + result, below_html=below)


def render_scheduler(slot) -> str:
    now = datetime.now(UTC)
    unit = get_unit_status(slot.unit)
    try:
        data = collect_scheduler(now)
    except Exception as exc:  # noqa: BLE001 — 스케줄 표·레지스트리 import 실패까지 막는다
        body = ui.verdict("muted", "확인 불가", f"잡 정보를 읽지 못했습니다({type(exc).__name__}).") + _stamp(now)
        return _page(slot, body)
    return _page(slot, scheduler_body(slot, unit, data))


def scheduler_body(slot, unit: UnitStatus, data: dict) -> str:
    now, jobs, health = data["now"], data["jobs"], data["health"]
    parts = [_scheduler_verdict(unit, data)]

    on = sum(1 for m in jobs if m["enabled"])
    day_ago = (now - timedelta(hours=24)).astimezone(UTC).replace(tzinfo=None)
    recent = [r for runs in data["runs"].values() for r in runs if r.recorded_at >= day_ago]
    ok_n = sum(1 for r in recent if r.status == "ok")
    bad_n = sum(1 for r in recent if r.status in BAD_STATUSES)
    try:
        nxt = upcoming(jobs, now, hours=24 * 8)[:1]
    except Exception:  # noqa: BLE001
        nxt = []
    if data["runs_error"]:
        runs_tile = ui.stat("최근 24시간", "—", "이력 확인 불가", "muted")
    else:
        runs_tile = ui.stat("최근 24시간", f"{ok_n}회 성공", f"실패·놓침 {bad_n}회", "bad" if bad_n else "ok")
    if nxt:
        next_tile = ui.stat("다음 실행", _kst(nxt[0]["at"]).strftime("%H:%M"), nxt[0]["label"])
    else:
        next_tile = ui.stat("다음 실행", "—", "켜진 잡 없음", "muted")
    tracking = (health or {}).get("tracking_since")
    if tracking:
        track_tile = ui.stat("이력 추적 시작", _kst(tracking).strftime("%m-%d"), _kst(tracking).strftime("%Y-%m-%d부터"))
    else:
        track_tile = ui.stat("이력 추적 시작", "—", "기록 없음", "muted")
    parts.append(ui.stats([
        ui.stat("켜진 잡", f"{on}/{len(jobs)}", "켜짐 / 전체", "ok" if on else "muted"),
        runs_tile, next_tile, track_tile,
    ]))
    svc_pill, _ = _unit_pill(unit)
    since = parse_systemd_time(unit.since) if unit.since else None
    svc_desc = f"{slot.unit} · 시작 {_kst_text(since)}" if since else slot.unit
    parts.append(ui.row_list([ui.row("스케줄러 서비스", icon="⏱", desc=svc_desc, end_html=svc_pill)]))

    try:
        soon = upcoming(jobs, now)
    except Exception:  # noqa: BLE001
        soon = None
    if soon is None:
        soon_html = '<div class="empty">예정 시각을 계산하지 못했습니다.</div>'
    elif not soon:
        soon_html = f'<div class="empty">앞으로 {UPCOMING_HOURS}시간 안에 도는 잡이 없습니다.</div>'
    else:
        soon_html = ui.row_list(ui.row(s["label"], desc=_kst_text(s["at"]), end_html=ui.pill(_in_text(s["at"] - now), "info", plain=True))
                                for s in soon)
    parts.append(ui.section(f"다음 예정 (앞으로 {UPCOMING_HOURS}시간)", soon_html))

    if data["runs_error"]:
        parts.append(ui.callout(E(f"실행 이력을 읽지 못해 14일 막대를 그리지 못했습니다({data['runs_error']})."), icon="!", tone="warn"))
    legend = ("막대 한 칸이 하루(KST)입니다. 초록=성공, 빨강=실패·놓침, 노랑=예정이었는데 기록 없음, 어두운 회색=예정 없음·꺼짐, "
              "옅은 칸=이력 추적 이전 또는 아직 예정 시각 전.")
    parts.append(ui.section("잡 목록", f'<p class="muted" style="font-size:.84rem">{E(legend)}</p>'))
    for key, title in CATEGORIES:
        group = [m for m in jobs if m["category"] == key]
        if group:
            parts.append(ui.section(title, ui.row_list(_job_row(m, data) for m in group), cat_tag=True))
    others = [m for m in jobs if m["category"] not in dict(CATEGORIES)]
    if others:
        parts.append(ui.section("기타", ui.row_list(_job_row(m, data) for m in others), cat_tag=True))

    parts.append(ui.callout(
        "잡을 켜고 끄려면 텔레그램에서 <code>/processes</code> 를 보내고 버튼을 누르세요. "
        "꺼진 잡은 예정 시각에 건너뜁니다.", icon="💬"))
    parts.append(_stamp(now))
    return "".join(parts)


# ---------------------------------------------------------------------------
# 텔레그램 에이전트
# ---------------------------------------------------------------------------
def _flatten_str(node) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "\x00" for v in node.values)
    return None


def telegram_commands(path: Path = RUNNER_PATH) -> list[tuple[str, str]]:
    """runner.py 의 /help 응답 문구를 코드에서 읽어 [(명령, 설명)] 으로. 명령이 바뀌면 자동으로 따라온다.

    f-string 자리(예: 잡 개수)는 비워 둔다. 읽지 못하면 빈 목록.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return []
    text = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        consts = [c.value for comp in node.test.comparators for c in ast.walk(comp) if isinstance(c, ast.Constant)]
        if "/help" not in consts:
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "reply" for t in stmt.targets):
                text = _flatten_str(stmt.value)
        if text:
            break
    if not text:
        return []
    out = []
    for line in text.split("\n"):
        line = re.sub(r"\s{2,}", " ", line.replace("\x00", "")).strip()
        if not line:
            continue
        if line.startswith("/") and ": " in line:
            cmd, desc = line.split(": ", 1)
        elif ": " in line and len(line.split(": ", 1)[0]) <= 12:
            cmd, desc = line.split(": ", 1)
        else:
            cmd, desc = "", line
        out.append((cmd.strip(), desc.strip()))
    return out


def telegram_state_dir() -> Path:
    env = os.environ.get("QUANT_TELEGRAM_STATE_DIR")
    if env:
        return Path(env)
    try:
        cfg = json.loads(TELEGRAM_CONFIG_PATH.read_text(encoding="utf-8"))
        return Path(cfg.get("state_dir") or TELEGRAM_STATE_DEFAULT)
    except (OSError, ValueError, AttributeError):
        return Path(TELEGRAM_STATE_DEFAULT)


def telegram_activity(state_dir: Optional[Path] = None) -> dict[str, Any]:
    """큐 DB(queue.sqlite)에서 마지막 활동 시각과 상태별 작업 수만 읽는다. 지시 원문·메시지·토큰 컬럼은 읽지 않는다."""
    db_path = (state_dir or telegram_state_dir()) / "queue.sqlite"
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return {"ok": False}
    try:
        last = con.execute("SELECT MAX(MAX(created_at, finished_at)) FROM jobs").fetchone()[0]
        counts = dict(con.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
        week = con.execute("SELECT COUNT(*) FROM jobs WHERE created_at >= ?",
                           (datetime.now(UTC).timestamp() - 7 * 86400,)).fetchone()[0]
    except sqlite3.Error:
        return {"ok": False}
    finally:
        con.close()
    last_at = datetime.fromtimestamp(last, UTC) if last else None
    return {"ok": True, "last_at": last_at, "counts": counts, "week": week}


def render_telegram(slot) -> str:
    now = datetime.now(UTC)
    unit = get_unit_status(slot.unit)
    pill, tone = _unit_pill(unit)
    title = {"ok": "실행 중", "bad": "멈춰 있습니다", "muted": "상태 확인 불가"}[tone]
    sub = {"ok": "텔레그램 지시를 받을 수 있습니다.",
           "bad": "지금은 텔레그램 지시가 처리되지 않습니다. systemd 가 30초 뒤 자동으로 다시 시작합니다.",
           "muted": "VM 에서 열면 실제 서비스 상태가 보입니다."}[tone]
    parts = [ui.verdict(tone, title, sub)]

    since = parse_systemd_time(unit.since) if unit.since and unit.is_active else None
    act = telegram_activity()
    counts = act.get("counts", {}) if act["ok"] else {}
    waiting = counts.get("queued", 0) + counts.get("retry", 0)
    parts.append(ui.stats([
        ui.stat("가동 시간", _duration(now - since) if since else "—", f"시작 {_kst_text(since)}" if since else "시작 시각 없음",
                "ok" if since else "muted"),
        ui.stat("마지막 활동", ui.relative_age((now - act["last_at"]).total_seconds() / 3600) if act.get("last_at") else "—",
                _kst_text(act.get("last_at")) if act.get("last_at") else ("기록 없음" if act["ok"] else "큐 확인 불가"),
                "" if act["ok"] else "muted"),
        ui.stat("대기·실행", f"{waiting} · {counts.get('running', 0)}" if act["ok"] else "—", "대기 · 실행 중 작업",
                "" if act["ok"] else "muted"),
        ui.stat("차단(blocked)", str(counts.get("blocked", 0)) if act["ok"] else "—",
                f"최근 7일 접수 {act['week']}건" if act["ok"] else "큐 확인 불가",
                ("warn" if counts.get("blocked") else "ok") if act["ok"] else "muted"),
    ]))
    parts.append(ui.row_list([ui.row("텔레그램 에이전트 서비스", icon="💬", desc=slot.unit, end_html=pill)]))

    cmds = telegram_commands()
    if cmds:
        rows = [(c, E(d)) for c, d in cmds if c]
        notes = [d for c, d in cmds if not c]
        table = ui.kv_table(rows)
        extra = "".join(f'<p class="muted" style="font-size:.84rem">{E(n)}</p>' for n in notes)
        parts.append(ui.section("이 에이전트로 할 수 있는 일", extra + table))
        parts.append('<p class="meta">텔레그램 /help 와 같은 목록을 runner.py 에서 바로 읽어 옵니다.</p>')
    else:
        parts.append(ui.section("이 에이전트로 할 수 있는 일",
                                '<div class="empty">명령 목록을 읽지 못했습니다. 텔레그램에서 /help 를 보내 보세요.</div>'))
    parts.append(_stamp(now))
    return _page(slot, "".join(parts))


# ---------------------------------------------------------------------------
# VM 헬스체크
# ---------------------------------------------------------------------------
def vm_thresholds(path: Path = VM_HEALTH_SCRIPT) -> dict[str, int]:
    """vm_health_check.sh 의 기본 임계값(디스크·메모리 %, 재알림 쿨다운 초). 읽지 못하면 스크립트 문서의 기본값."""
    found = {"disk": 85, "mem": 90, "cooldown": 21600}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return found
    for key, var in (("disk", "DISK_THRESHOLD_PERCENT"), ("mem", "MEM_THRESHOLD_PERCENT"), ("cooldown", "ALERT_COOLDOWN_SECONDS")):
        m = re.search(rf'{var}="\$\{{{var}:-(\d+)\}}"', text)
        if m:
            found[key] = int(m.group(1))
    return found


def usage_tone(pct: Optional[float], threshold: int) -> str:
    """헬스체크와 같은 기준: 임계값 이상이면 bad(알림 대상), 임계값 5%p 아래부터 warn."""
    if pct is None:
        return "muted"
    if pct >= threshold:
        return "bad"
    if pct >= threshold - 5:
        return "warn"
    return "ok"


def vm_alerting(state_dir: Optional[Path] = None) -> dict[str, bool]:
    d = state_dir or Path(os.environ.get("VM_HEALTH_STATE_DIR", "/opt/quant/.vm-health-state"))
    return {k: (d / f"{k}.alerting").exists() for k in ("disk", "mem")}


def render_vm_health(slot) -> str:
    from hub import ops_status

    now = datetime.now(UTC)
    th = vm_thresholds()
    try:
        s = ops_status.system_info()
    except Exception:  # noqa: BLE001
        s = {"disk_pct": None, "disk_free_gb": None, "mem_avail_pct": None, "load": None, "cpus": None,
             "uptime_days": None, "reboot_required": False}
    svc = get_unit_status(slot.unit)
    timer = get_unit_status(VM_HEALTH_TIMER_UNIT)
    tprops = _systemctl_props(VM_HEALTH_TIMER_UNIT, "LastTriggerUSec", "NextElapseUSecRealtime")
    sprops = _systemctl_props(slot.unit, "Result")
    alerting = vm_alerting()

    disk = s.get("disk_pct")
    mem_used = None if s.get("mem_avail_pct") is None else 100 - s["mem_avail_pct"]
    disk_tone, mem_tone = usage_tone(disk, th["disk"]), usage_tone(mem_used, th["mem"])
    svc_pill, svc_tone = _unit_pill(svc, oneshot=True)
    timer_pill, timer_tone = _unit_pill(timer)
    last_failed = sprops.get("Result") not in (None, "", "success")

    if svc_tone == "bad" or last_failed:
        verdict = ui.verdict("bad", "헬스체크가 실패했습니다", "마지막 점검 실행이 실패로 끝났습니다.")
    elif timer_tone == "bad":
        verdict = ui.verdict("bad", "헬스체크 타이머가 꺼져 있습니다", "디스크·메모리 점검이 돌지 않습니다.")
    elif "bad" in (disk_tone, mem_tone):
        verdict = ui.verdict("bad", "임계값 초과", "디스크나 메모리가 헬스체크 알림 기준을 넘었습니다.")
    elif "warn" in (disk_tone, mem_tone) or s.get("reboot_required"):
        verdict = ui.verdict("warn", "주의", "임계값에 가깝거나 재부팅이 필요합니다.")
    elif timer_tone == "muted":
        verdict = ui.verdict("muted", "서비스 상태 확인 불가", "지금 자원 수치는 아래와 같습니다. VM 에서 열면 타이머 상태가 보입니다.")
    else:
        verdict = ui.verdict("ok", "정상", "헬스체크가 15분마다 돌고 있고 자원이 기준 안에 있습니다.")

    load = s.get("load")
    cpus = s.get("cpus") or 0
    load_tile = (ui.stat("부하(1분)", f"{load[0]:.2f}", f"CPU {cpus}개 · 5분 {load[1]:.2f}")
                 if load else ui.stat("부하(1분)", "—", "확인 불가", "muted"))
    tiles = ui.stats([
        ui.stat("디스크 사용", "—" if disk is None else f"{disk:.0f}%",
                f"알림 {th['disk']}% · 여유 {s['disk_free_gb']:.1f}GB" if s.get("disk_free_gb") is not None else f"알림 {th['disk']}%",
                disk_tone),
        ui.stat("메모리 사용", "—" if mem_used is None else f"{mem_used:.0f}%", f"알림 {th['mem']}%", mem_tone),
        load_tile,
        ui.stat("재부팅", "필요" if s.get("reboot_required") else "불필요",
                "업데이트 적용 대기" if s.get("reboot_required") else
                (f"가동 {s['uptime_days']:.1f}일" if s.get("uptime_days") is not None else ""),
                "warn" if s.get("reboot_required") else "ok"),
    ])

    last = parse_systemd_time(tprops.get("LastTriggerUSec", ""))
    nxt = parse_systemd_time(tprops.get("NextElapseUSecRealtime", ""))
    rows = [
        ui.row("점검 타이머", icon="⏲", desc=f"{VM_HEALTH_TIMER_UNIT} · 부팅 5분 뒤, 이후 15분마다", end_html=timer_pill),
        ui.row("점검 서비스", icon="🩺", desc=f"{slot.unit} · 한 번 돌고 끝나는 서비스",
               end_html=ui.pill("마지막 실패", "bad") if last_failed else svc_pill),
    ]
    if last or nxt:
        rows.append(ui.row("점검 시각", icon="🕒", desc=f"마지막 {_kst_text(last)} · 다음 {_kst_text(nxt)}"))
    alert_rows = [
        ui.row(label, desc=f"기준 {th[key]}% 이상이면 텔레그램 알림",
               end_html=ui.pill("알림 중", "bad") if alerting[key] else ui.pill("알림 없음", "ok"))
        for key, label in (("disk", "디스크(/) 알림"), ("mem", "메모리 알림"))
    ]
    hours = th["cooldown"] // 3600
    how = (f"15분마다 디스크(/) 사용률 {th['disk']}%·메모리 사용률 {th['mem']}% 이상인지 확인해 넘으면 텔레그램으로 알리고, "
           f"계속 넘어 있으면 {hours}시간에 한 번만 다시 알리며, 기준 아래로 돌아오면 '복구됨'을 한 번 보냅니다. 부하와 재부팅 필요는 알리지 않습니다(재부팅 필요 14일 방치는 워치독이 알림).")
    body = (verdict + tiles + ui.section("서비스", ui.row_list(rows)) + ui.section("알림 상태", ui.row_list(alert_rows))
            + ui.callout(E(how), icon="ℹ") + _stamp(now))
    return _page(slot, body)


RENDERERS = {"scheduler": render_scheduler, "codex-telegram": render_telegram, "vm-health": render_vm_health}
