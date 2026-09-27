"""관제 허브 '지금 돌고 있는 작업' 화면(/live) — VM 에서 백그라운드로 무엇이 돌고 있고 그게 무엇인지(읽기 전용).

다섯 원천을 읽는다. 어느 하나가 실패해도 그 절만 '확인 불가'로 표시한다.
1. 서비스: systemctl show (상태·가동 시각·메모리·CPU 누적·재시작 횟수)
2. 실행 중인 스케줄러 잡: core.job_health.read_running_jobs() — 스케줄러가 잡 시작/종료 때 남기는 표시
3. 텔레그램 작업 큐: 러너 상태 DB(queue.sqlite)의 running/queued/retry/blocked 작업과 지시 요약
4. 프로세스: /proc 의 quant·ubuntu 계정 프로세스. 무엇인지 설명을 붙이고 명령줄의 비밀값은 가린다.
   code-server 의 수많은 하위 node 프로세스는 한 줄로 묶는다.
5. 곧 돌 잡: core.job_schedule 의 다음 실행 시각(12시간 이내)
"""

from __future__ import annotations

import html
import json
import os
import pwd
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
USERS = ("quant", "ubuntu")
SERVICES = [
    ("quant-scheduler.service", "스케줄러 — 야간 잡·알림·에이전트 배치를 시각에 맞춰 실행"),
    ("quant-hub.service", "관제 허브 — 지금 보고 있는 이 화면"),
    ("quant-streamlit.service", "퀀트 대시보드(Streamlit)"),
    ("codex-telegram.service", "텔레그램 러너 — 폰에서 보낸 지시를 받아 Claude/Codex 로 실행"),
    ("code-server@ubuntu.service", "브라우저 VS Code(code-server)"),
    ("nginx.service", "게이트웨이 — HTTPS·로그인"),
]
UPCOMING_HOURS = 12
_CLK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
_PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096

# (명령줄 패턴, 설명) — 위에서부터 처음 맞는 것
CLASSIFY: list[tuple[re.Pattern, str]] = [(re.compile(p), d) for p, d in [
    (r"scripts/agent_batch\.py", "AI 에이전트 야간 배치(03:00 KST) — 가설 작성·구현·검증"),
    (r"\bclaude\b.*\s-p\b.*--model\s+(\S+)", "Claude 에이전트 실행 중 (모델 {0})"),
    (r"\bclaude\b", "Claude CLI"),
    (r"\bcodex\b", "Codex CLI"),
    (r"scheduler[/.]run_scheduler", "스케줄러 본체"),
    (r"-m hub\.server|hub/server\.py", "관제 허브 서버"),
    (r"streamlit", "퀀트 대시보드(Streamlit)"),
    (r"codex_telegram/runner\.py", "텔레그램 러너"),
    (r"auto_deploy\.sh", "자동 배포 — GitHub main 새 커밋 반영"),
    (r"-m pytest|/pytest", "테스트 실행(자동 배포 관문 등)"),
    (r"unittest", "텔레그램 러너 테스트(자동 배포 관문)"),
    (r"backup_vm\.py", "VM 백업"),
    (r"watchdog\.py", "워치독 점검"),
    (r"github_watch\.py", "GitHub 실패 감시"),
    (r"vm_health_check\.sh", "VM 헬스체크"),
    (r"research_job|scripts/research", "연구 작업"),
    (r"scripts/(\S+)\.py", "스크립트 {0}"),
    (r"\bgit\b", "git 작업"),
    (r"\bgh\b", "GitHub CLI"),
    (r"code-server", "브라우저 VS Code(code-server)"),
    (r"\bsshd\b", "SSH 접속"),
    (r"^(-?bash|sh|zsh)\b", "셸"),
    (r"systemd --user|\(sd-pam\)", "사용자 systemd(내부)"),
]]
SECRET_RE = re.compile(
    r"((?:--)?(?:token|password|passwd|secret|api[-_]?key|auth)[=\s]+)\S+"
    r"|(ghp_|github_pat_|gho_|sk-ant-|sk-)[A-Za-z0-9_\-]+"
    r"|\b[A-Za-z0-9+/_\-]{40,}\b", re.I)


def redact(cmd: str) -> str:
    def sub(m):
        if m.group(1):
            return m.group(1) + "***"
        if m.group(2):
            return m.group(2) + "***"
        return "***"
    return SECRET_RE.sub(sub, cmd)


def classify(cmd: str) -> str:
    for pat, desc in CLASSIFY:
        m = pat.search(cmd)
        if m:
            return desc.format(*[g or "" for g in m.groups()]) if m.groups() else desc
    return ""


# ---------------------------------------------------------------- 1. 서비스
def service_rows() -> list[dict]:
    rows = []
    for unit, desc in SERVICES:
        row = {"unit": unit, "desc": desc, "state": "unknown"}
        try:
            out = subprocess.run(["systemctl", "show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "MainPID",
                                  "-p", "ActiveEnterTimestamp", "-p", "MemoryCurrent", "-p", "CPUUsageNSec", "-p", "NRestarts"],
                                 capture_output=True, text=True, timeout=5).stdout
            f = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
            row.update(state=f"{f.get('ActiveState', 'unknown')}/{f.get('SubState', '')}".rstrip("/"),
                       since=f.get("ActiveEnterTimestamp") or "", pid=f.get("MainPID"),
                       mem=_int(f.get("MemoryCurrent")), cpu_ns=_int(f.get("CPUUsageNSec")), restarts=_int(f.get("NRestarts")))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        rows.append(row)
    return rows


def _int(v) -> Optional[int]:
    try:
        n = int(v)
        return n if n < 2 ** 63 - 1 else None  # systemd 는 '모름'을 UINT64_MAX 로 준다
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 2. 실행 중 스케줄러 잡
def running_scheduler_jobs(now: Optional[datetime] = None) -> Optional[list[dict]]:
    try:
        from core.job_health import read_running_jobs
        from core.job_schedule import SCHEDULED_JOBS_BY_ID
        from core.process_registry import PROCESS_REGISTRY
    except Exception:  # noqa: BLE001
        return None
    now = now or datetime.now(timezone.utc)
    out = []
    for job_id, info in read_running_jobs().items():
        key = getattr(SCHEDULED_JOBS_BY_ID.get(job_id), "process_key", job_id)
        meta = PROCESS_REGISTRY.get(key, {})
        try:
            started = datetime.fromisoformat(info["started_at"])
            elapsed = (now - started).total_seconds()
        except (KeyError, ValueError):
            started, elapsed = None, None
        out.append({"job_id": job_id, "label": meta.get("label", job_id), "desc": meta.get("description", ""),
                    "started": started, "elapsed": elapsed})
    return sorted(out, key=lambda r: -(r["elapsed"] or 0))


# ---------------------------------------------------------------- 3. 텔레그램 큐
def telegram_queue_path() -> Path:
    for cfg in (PROJECT_ROOT / "deploy" / "codex_telegram" / "config.json",):
        try:
            state = json.loads(cfg.read_text(encoding="utf-8")).get("state_dir")
            if state:
                return Path(state) / "queue.sqlite"
        except (OSError, ValueError):
            pass
    return PROJECT_ROOT / ".codex-telegram-state" / "queue.sqlite"


def telegram_jobs(path: Optional[Path] = None) -> Optional[list[dict]]:
    path = path or telegram_queue_path()
    if not path.exists():
        return None
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM jobs WHERE status IN ('running','queued','retry','blocked') ORDER BY id").fetchall()
    except sqlite3.Error:
        return None
    out = []
    for r in rows:
        d = dict(r)
        out.append({"id": d.get("id"), "status": d.get("status"), "backend": d.get("backend", ""),
                    "project": d.get("project", ""), "attempts": d.get("attempts", 0),
                    "created_at": d.get("created_at"), "instruction": redact(str(d.get("instruction") or ""))[:240]})
    return out


# ---------------------------------------------------------------- 4. 프로세스
def _boot_time() -> float:
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except OSError:
        pass
    return time.time()


def process_rows(proc: Path = Path("/proc"), users: tuple = USERS, now: Optional[float] = None) -> list[dict]:
    now = now or time.time()
    boot = _boot_time()
    uids = {}
    for u in users:
        try:
            uids[pwd.getpwnam(u).pw_uid] = u
        except KeyError:
            continue
    rows = []
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            st = d.stat()
            if st.st_uid not in uids:
                continue
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            if not cmd:
                continue
            fields = (d / "stat").read_text().rsplit(")", 1)[1].split()
            ppid, utime, stime, start, rss = int(fields[1]), int(fields[11]), int(fields[12]), int(fields[19]), int(fields[21])
        except (OSError, ValueError, IndexError):
            continue
        age = max(now - (boot + start / _CLK), 1.0)
        cpu_s = (utime + stime) / _CLK
        rows.append({"pid": int(d.name), "ppid": ppid, "user": uids[st.st_uid], "age": age,
                     "cpu_pct": 100.0 * cpu_s / age, "rss_mb": rss * _PAGE / 1e6,
                     "cmd": redact(cmd)[:300], "what": classify(cmd)})
    return group_code_server(rows)


def group_code_server(rows: list[dict]) -> list[dict]:
    """code-server 하위 node 프로세스(확장·언어 서버 등 수십 개)를 한 줄로 묶는다."""
    cs = [r for r in rows if "code-server" in r["cmd"] and "sudo" not in r["cmd"]]
    rest = [r for r in rows if r not in cs]
    if len(cs) > 1:
        main = min(cs, key=lambda r: r["pid"])
        rest.append({**main, "cmd": f"code-server 외 하위 프로세스 {len(cs) - 1}개", "what": "브라우저 VS Code(code-server)",
                     "rss_mb": sum(r["rss_mb"] for r in cs), "cpu_pct": sum(r["cpu_pct"] for r in cs), "grouped": len(cs)})
    elif cs:
        rest.extend(cs)
    return sorted(rest, key=lambda r: (-r["cpu_pct"], r["pid"]))


# ---------------------------------------------------------------- 5. 곧 돌 잡
def upcoming_jobs(now: Optional[datetime] = None, hours: int = UPCOMING_HOURS) -> Optional[list[dict]]:
    try:
        from apscheduler.triggers.cron import CronTrigger

        from core.job_schedule import SCHEDULED_JOBS
        from core.process_registry import PROCESS_REGISTRY, is_enabled
    except Exception:  # noqa: BLE001
        return None
    now = now or datetime.now(timezone.utc)
    out = []
    for job in SCHEDULED_JOBS:
        nxt = CronTrigger(**job.cron).get_next_fire_time(None, now)
        if nxt and nxt <= now + timedelta(hours=hours):
            meta = PROCESS_REGISTRY.get(job.process_key, {})
            out.append({"job_id": job.job_id, "label": meta.get("label", job.job_id), "at": nxt,
                        "enabled": is_enabled(job.process_key)})
    return sorted(out, key=lambda r: r["at"])


# ---------------------------------------------------------------- 렌더링
def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _dur(sec: Optional[float]) -> str:
    if sec is None:
        return "—"
    sec = int(sec)
    if sec < 60:
        return f"{sec}초"
    if sec < 3600:
        return f"{sec // 60}분"
    if sec < 86400:
        return f"{sec // 3600}시간 {sec % 3600 // 60}분"
    return f"{sec // 86400}일 {sec % 86400 // 3600}시간"


def _pill(text: str, tone: str) -> str:
    return f'<span class="badge {tone}">{_e(text)}</span>'


def card_badge() -> str:
    jobs = running_scheduler_jobs() or []
    tq = telegram_jobs() or []
    running_tg = sum(1 for j in tq if j["status"] == "running")
    parts = []
    if jobs:
        parts.append(f"잡 {len(jobs)}개 실행 중")
    if running_tg:
        parts.append(f"텔레그램 작업 {running_tg}개")
    return _pill(" · ".join(parts) if parts else "대기 중", "active" if parts else "unknown")


def render_body(services: list[dict], jobs: Optional[list[dict]], tq: Optional[list[dict]],
                procs: list[dict], upcoming: Optional[list[dict]]) -> str:
    kst = lambda d: d.astimezone(KST).strftime("%m-%d %H:%M") if d else "—"  # noqa: E731
    parts = ['<p class="subtitle">VM 에서 지금 백그라운드로 돌고 있는 것과 곧 돌 것. 15초마다 새로고침. 읽기 전용.</p>']

    rows = []
    if jobs is None:
        rows.append('<tr><td colspan="3">확인 불가</td></tr>')
    for j in jobs or []:
        rows.append(f'<tr><th>{_e(j["label"])}<br><small>{_e(j["job_id"])}</small></th>'
                    f'<td>{_pill(_dur(j["elapsed"]) + "째", "active")} <small>{kst(j["started"])} KST 시작</small>'
                    f'<br><small>{_e(j["desc"][:200])}</small></td></tr>')
    parts.append('<h2>지금 실행 중인 스케줄러 잡</h2><table>'
                 + ("".join(rows) or '<tr><td>없음 — 스케줄러는 다음 예약 시각까지 대기 중입니다.</td></tr>') + '</table>')

    rows = []
    if tq is None:
        rows.append('<tr><td>텔레그램 러너 상태 파일을 읽지 못했습니다.</td></tr>')
    for t in tq or []:
        tone = {"running": "active", "blocked": "inactive"}.get(t["status"], "unknown")
        rows.append(f'<tr><th>#{_e(t["id"])} {_pill(t["status"], tone)}<br><small>{_e(t["backend"])} · 시도 {_e(t["attempts"])}</small></th>'
                    f'<td>{_e(t["instruction"])}<br><small>{_e(t["project"])}</small></td></tr>')
    parts.append('<h2>텔레그램 작업 큐 <small>(폰에서 보낸 지시)</small></h2><table>'
                 + ("".join(rows) or '<tr><td>진행·대기 중인 작업 없음</td></tr>') + '</table>')

    rows = []
    for s in services:
        tone = "active" if s["state"].startswith("active") else "unknown" if s["state"] == "unknown" else "inactive"
        extra = []
        if s.get("mem"):
            extra.append(f"메모리 {s['mem'] / 1e6:.0f}MB")
        if s.get("cpu_ns"):
            extra.append(f"CPU 누적 {_dur(s['cpu_ns'] / 1e9)}")
        if s.get("restarts"):
            extra.append(f"재시작 {s['restarts']}회")
        rows.append(f'<tr><th>{_e(s["desc"])}<br><small>{_e(s["unit"])}</small></th>'
                    f'<td>{_pill(s["state"], tone)} <small>{_e(s.get("since", ""))}</small><br><small>{_e(" · ".join(extra))}</small></td></tr>')
    parts.append(f'<h2>서비스</h2><table>{"".join(rows)}</table>')

    rows = []
    for p in procs:
        rows.append(f'<tr><th>{_e(p["what"] or "기타")}<br><small>PID {p["pid"]} · {_e(p["user"])} · {_dur(p["age"])}째</small></th>'
                    f'<td><small>CPU {p["cpu_pct"]:.1f}% · 메모리 {p["rss_mb"]:.0f}MB</small><br>'
                    f'<code style="font-size:.72rem;color:#9aa0a8;word-break:break-all">{_e(p["cmd"])}</code></td></tr>')
    parts.append(f'<h2>프로세스 <small>({len(procs)}개, CPU 는 시작 이후 평균)</small></h2><table>'
                 + ("".join(rows) or '<tr><td>확인 불가</td></tr>') + '</table>')

    rows = []
    if upcoming is None:
        rows.append('<tr><td>확인 불가</td></tr>')
    for u in upcoming or []:
        rows.append(f'<tr><th>{kst(u["at"])} KST</th><td>{_e(u["label"])} '
                    + (_pill("켜짐", "active") if u["enabled"] else _pill("꺼짐 — 건너뜀", "unknown")) + '</td></tr>')
    parts.append(f'<h2>앞으로 {UPCOMING_HOURS}시간 안에 돌 잡</h2><table>'
                 + ("".join(rows) or '<tr><td>없음</td></tr>') + '</table>')
    return "".join(parts)


def collect_and_render() -> str:
    try:
        procs = process_rows()
    except OSError:
        procs = []
    return render_body(service_rows(), running_scheduler_jobs(), telegram_jobs(), procs, upcoming_jobs())
