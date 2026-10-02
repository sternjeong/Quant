"""검증 연구 작업 실행기 — 저장소에 커밋된 결정론적 백테스트 스크립트를 VM 의 한가한 시간에 사람 손 없이 돌린다.

배경(2026-09-26): 사용자는 폰으로만 작업하고 Codespace 는 늘 켜 둘 수 없다. 대화·에이전트 세션이 설계한 사전 등록
검증 연구(판정 규칙이 코드에 박힌 파이썬 스크립트)는 계산이 무거워 VM 에서 돌아야 하는데, 계산 자체에는 AI 가 필요 없다.
이 모듈은 그 '연구 작업 실행기'다. 작업 계약은 docs/RESEARCH_JOBS.md 에 있다(연구 에이전트는 그 문서대로 스크립트를 맞춘다).

  - 작업 정의: research/jobs/<id>/job.json (저장소에 커밋) — load_job_definitions()/validate_job() 가 검증한다.
  - 실행: scheduler/run_scheduler.py 의 research_job_runner_job 이 창(RUN_WINDOWS) 안에서 20분마다 run_tick() 을 부른다.
    한 번에 한 작업만(파일 락), 여유(has_headroom)·디스크 확인 뒤, 남은 창 시간으로 줄인 시간 예산을 주고 nice 19 로 돌린다.
  - 상태: data/research_jobs/state.json (원자적 쓰기 + 짧은 락). 멈춘 running 은 다음 회차에 in_progress 로 복구한다.
  - 결과: data/research_results/<id>/ 보관 + data/research_results/index.html(관제 센터 '검증 연구 결과' 카드) + 텔레그램 1건
    + origin/main 의 research/results/<id>/ 에 작은 텍스트 파일만 커밋(작업트리를 건드리지 않는 git 배관, publish_files()).

주문 경로와 무관하다. 텔레그램·로그·커밋에 키가 섞이지 않도록 로그 꼬리와 요약은 redact() 를 거친다.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import html
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")

# 실행 창(KST). 01:00~02:50: 00:00~00:50 야간 잡 블록 뒤, 03:00 AI 에이전트 배치 전.
# 13:00~16:50: 한국 낮(=미국 밤) — 12:00 거장 동기화 뒤, 등록된 잡이 하나도 없고 사용자가 근무 중이라 화면을 거의 안 쓴다.
# 03:00~05:50 에이전트 배치, 06:10 paper 주문, 06:30 백업, 07:30 뉴스, 09:00 대회·09:05 워치독은 피한다.
RUN_WINDOWS: tuple[tuple[time, time], ...] = ((time(1, 0), time(2, 50)), (time(13, 0), time(16, 50)))
# 스케줄러 cron(core/job_schedule.py 와 같아야 함): 위 창 안에서 20분마다.
CRON = {"hour": "1,2,13,14,15,16", "minute": "0,20,40", "timezone": "Asia/Seoul"}

END_MARGIN_SECONDS = 120  # 창 끝나기 이만큼 전에 자식이 끝나 있어야 한다
MIN_BUDGET_SECONDS = 300  # 이보다 짧게 남으면 이번 회차는 시작하지 않는다
TERM_GRACE_SECONDS = 30  # SIGTERM 뒤 체크포인트 저장할 시간, 그 뒤 SIGKILL
MIN_FREE_DISK_MB = 2048  # 시작 전 필요한 여유 디스크
ABORT_FREE_DISK_MB = 1024  # 실행 중 이 아래로 떨어지면 양보(중단)
ABORT_AVAILABLE_MEMORY_MB = 600  # 실행 중 시스템 여유 메모리가 이 아래면 양보(중단)
DEFAULT_MAX_MEMORY_MB = 3072
DEFAULT_MAX_DISK_MB = 2048
DEFAULT_MAX_RUNS = 60  # 종료 코드 3(진행 중)을 이만큼 반복해도 안 끝나면 실패로 본다
MAX_INTERRUPTIONS = 6  # 재부팅·재배포로 끊긴 횟수 상한
POST_PUBLISH_COOLDOWN_SECONDS = 12 * 60  # 결과 push → 자동배포가 스케줄러를 재시작할 때까지 새 작업을 시작하지 않는다
LOG_TAIL_CHARS = 2000
KEEP_LOGS = 5

PUBLISH_MAX_FILE_BYTES = 256 * 1024
PUBLISH_MAX_TOTAL_BYTES = 1024 * 1024
PUBLISH_EXTENSIONS = (".json", ".md", ".csv", ".txt")
REPORT_RENDER_MAX_CHARS = 200_000

JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
STATUSES = ("pending", "running", "in_progress", "done", "failed", "cancelled", "invalid")

SECRET_PATTERNS = (
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
    r"\bghp_[A-Za-z0-9]{30,}", r"\bgithub_pat_[A-Za-z0-9_]{30,}",
    r"\bsk-ant-[A-Za-z0-9_-]{20,}", r"\bsk-[A-Za-z0-9]{32,}",
    r"\bAKIA[0-9A-Z]{16}\b", r"\bxox[baprs]-[A-Za-z0-9-]{10,}",
    r"\bAIza[0-9A-Za-z_-]{35}\b", r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b",
)
_SENSITIVE_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSPHRASE)", re.I)
_NO_CREDENTIALS = re.compile(
    r"permission denied|permission to \S+ denied|authentication failed|could not read username|"
    r"access denied|publickey|write access to repository not granted|returned error: 403|\b403\b|terminal prompts disabled",
    re.I,
)
_NON_FAST_FORWARD = re.compile(r"non-fast-forward|fetch first|rejected|failed to update ref|cannot lock ref", re.I)


# ---------------------------------------------------------------------------
# 설정·경로
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Config:
    repo_root: Path = PROJECT_ROOT
    jobs_dir: Path = PROJECT_ROOT / "research" / "jobs"
    state_dir: Path = PROJECT_ROOT / "data" / "research_jobs"
    results_dir: Path = PROJECT_ROOT / "data" / "research_results"
    publish_prefix: str = "research/results"
    python: str = sys.executable
    satellite_lab: bool = True  # 대기 작업이 없는 창을 새틀라이트 R&D 센터 심판에 쓴다(아래 _satellite_lab_turn)

    @classmethod
    def for_root(cls, root: Path) -> "Config":
        root = Path(root)
        return cls(repo_root=root, jobs_dir=root / "research" / "jobs", state_dir=root / "data" / "research_jobs",
                   results_dir=root / "data" / "research_results", satellite_lab=False)

    @property
    def state_path(self) -> Path:
        return self.state_dir / "state.json"

    def work_dir(self, job_id: str) -> Path:
        return self.state_dir / "work" / job_id

    def out_dir(self, job_id: str) -> Path:
        return self.work_dir(job_id) / "out"

    def checkpoint_dir(self, job_id: str) -> Path:
        return self.work_dir(job_id) / "checkpoint"

    def log_dir(self, job_id: str) -> Path:
        return self.state_dir / "logs" / job_id


@dataclass(frozen=True)
class JobDef:
    id: str
    title: str
    entrypoint: str
    args: tuple[str, ...]
    timeout_seconds: int
    max_attempts: int
    resumable: bool
    outputs: tuple[str, ...]
    summary_from: Optional[str]
    priority: int
    revision: str = "1"
    max_memory_mb: int = DEFAULT_MAX_MEMORY_MB
    max_disk_mb: int = DEFAULT_MAX_DISK_MB
    max_runs: int = DEFAULT_MAX_RUNS


# ---------------------------------------------------------------------------
# 비밀 가리기
# ---------------------------------------------------------------------------
def redact(text: str) -> str:
    text = str(text or "")
    for pattern in SECRET_PATTERNS:
        text = re.sub(pattern, "[가림]", text)
    text = re.sub(r"(://)[^@/\s]+@", r"\1***@", text)  # URL 안의 자격 증명
    for key, value in os.environ.items():
        if _SENSITIVE_ENV.search(key) and value and len(value) >= 8:
            text = text.replace(value, "[가림]")
    return text


def looks_secret(text: str) -> bool:
    return any(re.search(p, text or "") for p in SECRET_PATTERNS)


# ---------------------------------------------------------------------------
# 작업 정의 검증
# ---------------------------------------------------------------------------
def _safe_rel(path: str) -> bool:
    if not isinstance(path, str) or not path or path.startswith(("/", "\\")) or "\\" in path:
        return False
    parts = Path(path).parts
    return ".." not in parts and "." not in parts


def validate_job(data: object, dir_name: str, repo_root: Path = PROJECT_ROOT) -> tuple[Optional[JobDef], str]:
    """job.json 내용을 검증한다. (JobDef, "") 또는 (None, 사유)."""
    if not isinstance(data, dict):
        return None, "job.json 이 객체(JSON object)가 아닙니다"
    required = ("id", "title", "entrypoint", "args", "timeout_seconds", "max_attempts", "resumable", "outputs",
                "summary_from", "priority")
    missing = [k for k in required if k not in data]
    if missing:
        return None, f"필수 필드 없음: {', '.join(missing)}"
    job_id = data["id"]
    if not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
        return None, "id 는 소문자·숫자·. _ - 로 된 64자 이하여야 합니다"
    if job_id != dir_name:
        return None, f"id({job_id})가 폴더 이름({dir_name})과 다릅니다"
    if not isinstance(data["title"], str) or not data["title"].strip():
        return None, "title 이 비어 있습니다"
    entry = data["entrypoint"]
    if not _safe_rel(entry) or not entry.endswith(".py"):
        return None, "entrypoint 는 저장소 루트 기준 .py 상대 경로여야 합니다(.. 금지)"
    if not (Path(repo_root) / entry).is_file():
        return None, f"entrypoint 파일이 없습니다: {entry}"
    args = data["args"]
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        return None, "args 는 문자열 목록이어야 합니다"
    if any(a in ("--out", "--checkpoint") for a in args):
        return None, "args 에 --out/--checkpoint 를 넣지 마세요(실행기가 붙입니다)"

    def _int(name, lo, hi):
        value = data.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise ValueError(f"{name} 는 {lo}~{hi} 사이 정수여야 합니다")
        return value

    try:
        timeout = _int("timeout_seconds", 60, 3 * 3600)
        attempts = _int("max_attempts", 1, 10)
        priority = _int("priority", -1000, 1000)
        max_memory = _int("max_memory_mb", 256, 6144) if "max_memory_mb" in data else DEFAULT_MAX_MEMORY_MB
        max_disk = _int("max_disk_mb", 16, 20480) if "max_disk_mb" in data else DEFAULT_MAX_DISK_MB
        max_runs = _int("max_runs", 1, 500) if "max_runs" in data else DEFAULT_MAX_RUNS
    except ValueError as exc:
        return None, str(exc)
    if not isinstance(data["resumable"], bool):
        return None, "resumable 은 true/false 여야 합니다"
    outputs = data["outputs"]
    if not isinstance(outputs, list) or not outputs or not all(_safe_rel(o) for o in outputs):
        return None, "outputs 는 비어 있지 않은 상대 경로 목록이어야 합니다(.. 금지)"
    if len(set(outputs)) != len(outputs):
        return None, "outputs 에 중복이 있습니다"
    summary_from = data["summary_from"]
    if summary_from is not None and (not isinstance(summary_from, str) or not summary_from.strip()):
        return None, "summary_from 은 키 경로 문자열(예: verdicts) 또는 null 이어야 합니다"
    if summary_from and ":" in summary_from and summary_from.split(":", 1)[0] not in outputs:
        return None, "summary_from 의 파일 부분이 outputs 에 없습니다"
    if not data["resumable"] and timeout > longest_window_seconds() - END_MARGIN_SECONDS:
        return None, "재개 불가(resumable=false) 작업의 timeout_seconds 가 가장 긴 실행 창보다 깁니다"
    revision = data.get("revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, (int, str)):
        return None, "revision 은 정수 또는 문자열이어야 합니다"
    return JobDef(
        id=job_id, title=data["title"].strip(), entrypoint=entry, args=tuple(args), timeout_seconds=timeout,
        max_attempts=attempts, resumable=data["resumable"], outputs=tuple(outputs),
        summary_from=summary_from.strip() if summary_from else None, priority=priority, revision=str(revision),
        max_memory_mb=max_memory, max_disk_mb=max_disk, max_runs=max_runs,
    ), ""


def load_job_definitions(cfg: Config) -> tuple[dict[str, JobDef], dict[str, str]]:
    valid: dict[str, JobDef] = {}
    invalid: dict[str, str] = {}
    if not cfg.jobs_dir.is_dir():
        return valid, invalid
    for job_file in sorted(cfg.jobs_dir.glob("*/job.json")):
        name = job_file.parent.name
        try:
            data = json.loads(job_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            invalid[name] = f"job.json 을 읽지 못함: {type(exc).__name__}"
            continue
        job, reason = validate_job(data, name, cfg.repo_root)
        if job is None:
            invalid[name] = reason
        else:
            valid[job.id] = job
    return valid, invalid


# ---------------------------------------------------------------------------
# 상태 파일
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _flock(path: Path, blocking: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def _empty_state() -> dict:
    return {"version": 1, "jobs": {}, "runner": {}}


def load_state(cfg: Config) -> dict:
    try:
        state = json.loads(cfg.state_path.read_text(encoding="utf-8"))
        if isinstance(state, dict) and isinstance(state.get("jobs"), dict):
            state.setdefault("runner", {})
            return state
    except (OSError, ValueError):
        pass
    return _empty_state()


def save_state(cfg: Config, state: dict) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="state.", suffix=".tmp", dir=str(cfg.state_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, cfg.state_path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def edit_state(cfg: Config):
    """짧은 읽기-수정-쓰기 구간. 실행기와 관리 CLI 가 동시에 써도 서로 덮어쓰지 않게 한다."""
    with _flock(cfg.state_dir / "state.lock"):
        state = load_state(cfg)
        yield state
        save_state(cfg, state)


def _new_entry(job: JobDef) -> dict:
    return {"status": "pending", "title": job.title, "revision": job.revision, "priority": job.priority,
            "failures": 0, "runs": 0, "interruptions": 0, "last_started_at": None, "last_finished_at": None,
            "last_duration_seconds": None, "last_exit_code": None, "last_reason": None, "log_tail": "",
            "pid": None, "cancel_requested": False, "notified_signature": None, "summary": None,
            "publish": None, "result_dir": None}


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def sync_definitions(cfg: Config, state: dict, jobs: dict[str, JobDef], invalid: dict[str, str]) -> list[tuple[str, str]]:
    """정의와 상태를 맞춘다. 새로 알릴 잘못된 작업 [(id, 사유)] 를 돌려준다(같은 사유는 한 번만)."""
    to_notify = []
    for job_id, job in jobs.items():
        entry = state["jobs"].get(job_id)
        if entry is None or entry.get("status") == "invalid" or str(entry.get("revision")) != job.revision:
            if entry is not None and str(entry.get("revision")) != job.revision:
                shutil.rmtree(cfg.work_dir(job_id), ignore_errors=True)  # 정의가 바뀌면 처음부터
            state["jobs"][job_id] = _new_entry(job)
        else:
            entry.update(title=job.title, priority=job.priority)
    for job_id, reason in invalid.items():
        entry = state["jobs"].setdefault(job_id, {"status": "invalid", "title": job_id})
        if entry.get("status") in ("running",):
            continue
        entry["status"] = "invalid"
        entry["last_reason"] = reason
        sig = hashlib.sha1(reason.encode()).hexdigest()[:12]
        if entry.get("notified_signature") != sig:
            entry["notified_signature"] = sig
            to_notify.append((job_id, reason))
    return to_notify


def recover_stale(state: dict, jobs: dict[str, JobDef]) -> list[str]:
    """실행기 락을 잡은 상태에서 호출한다 — 락이 비어 있었다면 running 은 모두 죽은 실행이다."""
    recovered = []
    for job_id, entry in state["jobs"].items():
        if entry.get("status") != "running":
            continue
        entry["interruptions"] = int(entry.get("interruptions") or 0) + 1
        entry["pid"] = None
        job = jobs.get(job_id)
        if entry["interruptions"] > MAX_INTERRUPTIONS:
            entry["status"] = "failed"
            entry["last_reason"] = f"실행 중 {entry['interruptions']}번 끊김(재부팅·재배포 반복)"
        else:
            entry["status"] = "in_progress" if (job is None or job.resumable) else "pending"
            entry["last_reason"] = "이전 실행이 끊김(재부팅·재배포) — 이어서 실행 대기"
        recovered.append(job_id)
    return recovered


# ---------------------------------------------------------------------------
# 창·예산
# ---------------------------------------------------------------------------
def longest_window_seconds() -> int:
    return max((datetime.combine(datetime.min, e) - datetime.combine(datetime.min, s)).seconds for s, e in RUN_WINDOWS)


def window_end_for(now: datetime) -> Optional[datetime]:
    """now 가 실행 창 안이면 그 창의 끝(tz-aware), 아니면 None."""
    local = now.astimezone(KST)
    for start, end in RUN_WINDOWS:
        if start <= local.time() < end:
            return datetime.combine(local.date(), end, tzinfo=KST)
    return None


def budget_for(job: JobDef, now: datetime, window_end: datetime) -> tuple[int, bool]:
    """(이번 실행 시간 예산 초, 창 때문에 줄었는지)."""
    remaining = int((window_end - now).total_seconds()) - END_MARGIN_SECONDS
    budget = min(job.timeout_seconds, remaining)
    return max(budget, 0), budget < job.timeout_seconds


def pick_job(state: dict, jobs: dict[str, JobDef], now: datetime, window_end: datetime) -> tuple[Optional[JobDef], int, bool]:
    candidates = [j for j in jobs.values() if state["jobs"].get(j.id, {}).get("status") in ("pending", "in_progress")]
    for job in sorted(candidates, key=lambda j: (j.priority, j.id)):
        budget, shortened = budget_for(job, now, window_end)
        if budget < MIN_BUDGET_SECONDS:
            continue
        if not job.resumable and shortened:
            continue  # 재개 불가 작업은 한 번에 끝낼 시간이 있을 때만
        return job, budget, shortened
    return None, 0, False


# ---------------------------------------------------------------------------
# 자원 점검
# ---------------------------------------------------------------------------
def free_disk_mb(path: Path) -> Optional[float]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(path).free / 1024 / 1024
    except OSError:
        return None


def dir_size_mb(path: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(root, name)).st_size
    return total / 1024 / 1024


def tree_rss_mb(pid: int) -> Optional[float]:
    """pid 와 그 자손 프로세스의 RSS 합(MB). 리눅스가 아니면 None."""
    if not Path("/proc").is_dir():
        return None
    seen, stack, total = set(), [pid], 0.0
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            for line in Path(f"/proc/{current}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1]) / 1024
                    break
            for task in Path(f"/proc/{current}/task").iterdir():
                with contextlib.suppress(OSError, ValueError):
                    stack.extend(int(c) for c in (task / "children").read_text().split())
        except (OSError, ValueError):
            continue
    return total


def _system_available_mb() -> Optional[float]:
    from core.resource_guard import available_memory_mb

    return available_memory_mb()


# ---------------------------------------------------------------------------
# 자식 실행
# ---------------------------------------------------------------------------
@dataclass
class RunOutcome:
    exit_code: Optional[int]
    stopped_by: Optional[str]  # None | budget | cancel | job_memory | job_disk | system_memory | system_disk
    duration: float
    log_tail: str
    log_path: Optional[Path] = None


def _child_preexec() -> None:  # pragma: no cover - 자식 프로세스 안에서 돈다
    with contextlib.suppress(OSError):
        os.nice(19)


def build_command(cfg: Config, job: JobDef) -> list[str]:
    cmd = [cfg.python, str(cfg.repo_root / job.entrypoint), *job.args,
           "--out", str(cfg.out_dir(job.id)), "--checkpoint", str(cfg.checkpoint_dir(job.id))]
    ionice = shutil.which("ionice")
    if ionice:
        cmd = [ionice, "-c", "3", *cmd]  # 디스크 입출력도 가장 낮은 우선순위(idle)
    return cmd


def _kill_group(proc: subprocess.Popen, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(proc.pid, sig)


def run_child(cfg: Config, job: JobDef, budget: int, *, poll_interval: float = 5.0,
              cancel_check: Callable[[], bool] = lambda: False,
              system_memory: Callable[[], Optional[float]] = _system_available_mb) -> RunOutcome:
    cfg.out_dir(job.id).mkdir(parents=True, exist_ok=True)
    cfg.checkpoint_dir(job.id).mkdir(parents=True, exist_ok=True)
    log_dir = cfg.log_dir(job.id)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now(KST).strftime('%Y%m%d-%H%M%S')}.log"
    deadline = _time.time() + budget
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "RESEARCH_JOB_ID": job.id,
           "RESEARCH_JOB_DEADLINE_EPOCH": str(int(deadline)), "RESEARCH_JOB_TIME_BUDGET_SECONDS": str(int(budget))}
    env.pop("PYTEST_CURRENT_TEST", None)
    started = _time.time()
    stopped_by: Optional[str] = None
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(build_command(cfg, job), cwd=str(cfg.repo_root), stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, start_new_session=True, preexec_fn=_child_preexec)
        last_disk_check = 0.0
        term_sent_at: Optional[float] = None
        while True:
            try:
                proc.wait(timeout=poll_interval)
                break
            except subprocess.TimeoutExpired:
                pass
            now = _time.time()
            if term_sent_at is not None:
                if now - term_sent_at >= TERM_GRACE_SECONDS:
                    _kill_group(proc, signal.SIGKILL)
                continue
            reason = None
            if now >= deadline:
                reason = "budget"
            elif cancel_check():
                reason = "cancel"
            else:
                rss = tree_rss_mb(proc.pid)
                avail = system_memory()
                if rss is not None and rss > job.max_memory_mb:
                    reason = "job_memory"
                elif avail is not None and avail < ABORT_AVAILABLE_MEMORY_MB:
                    reason = "system_memory"
                elif now - last_disk_check >= max(30.0, poll_interval):
                    last_disk_check = now
                    free = free_disk_mb(cfg.state_dir)
                    if dir_size_mb(cfg.work_dir(job.id)) > job.max_disk_mb:
                        reason = "job_disk"
                    elif free is not None and free < ABORT_FREE_DISK_MB:
                        reason = "system_disk"
            if reason:
                stopped_by = reason
                term_sent_at = now
                _kill_group(proc, signal.SIGTERM)
        _kill_group(proc, signal.SIGKILL)  # 자식이 남긴 손자 프로세스 정리
    duration = _time.time() - started
    try:
        raw = log_path.read_bytes()[-LOG_TAIL_CHARS * 4:].decode("utf-8", "replace")
    except OSError:
        raw = ""
    _prune_logs(log_dir)
    return RunOutcome(proc.returncode, stopped_by, duration, redact(raw[-LOG_TAIL_CHARS:]), log_path)


def _prune_logs(log_dir: Path) -> None:
    logs = sorted(log_dir.glob("*.log"))
    for old in logs[:-KEEP_LOGS]:
        with contextlib.suppress(OSError):
            old.unlink()


# ---------------------------------------------------------------------------
# 결과 요약·보관·색인
# ---------------------------------------------------------------------------
def _dig(data: object, path: str) -> object:
    for part in [p for p in path.split(".") if p]:
        if isinstance(data, dict) and part in data:
            data = data[part]
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


def _short(value: object, limit: int = 120) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def extract_summary(job: JobDef, result_dir: Path, max_lines: int = 8) -> str:
    """summary_from 키 경로의 값을 짧은 여러 줄 문자열로. 없으면 빈 문자열."""
    if not job.summary_from:
        return ""
    spec = job.summary_from
    if ":" in spec:
        file_name, key_path = spec.split(":", 1)
    else:
        file_name = next((o for o in job.outputs if o.endswith(".json")), "")
        key_path = spec
    if not file_name:
        return ""
    try:
        data = json.loads((result_dir / file_name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = _dig(data, key_path)
    if value is None:
        return ""
    if isinstance(value, dict):
        lines = [f"{k}: {_short(v)}" for k, v in value.items()]
    elif isinstance(value, list):
        lines = [f"- {_short(v)}" for v in value]
    else:
        lines = [_short(value, 400)]
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"… 외 {len(lines) - max_lines}개"]
    return redact("\n".join(lines))[:900]


def store_results(cfg: Config, job: JobDef) -> tuple[Optional[Path], list[str]]:
    """out 디렉터리의 선언된 결과를 data/research_results/<id>/ 로 옮긴다. (결과 폴더, 누락 목록)."""
    out = cfg.out_dir(job.id)
    missing = [o for o in job.outputs if not (out / o).is_file()]
    if missing:
        return None, missing
    target = cfg.results_dir / job.id
    staging = cfg.results_dir / f".{job.id}.new"
    shutil.rmtree(staging, ignore_errors=True)
    for rel in job.outputs:
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / rel, dest)
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    return target, []


def _md_inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)


def markdown_to_html(md: str) -> str:
    """표준 라이브러리만으로 하는 최소 변환(제목·목록·표·코드 블록·문단). 모든 텍스트는 escape 한다."""
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    para: list[str] = []

    def flush():
        if para:
            out.append("<p>" + _md_inline(" ".join(para)) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            out.append("<pre>" + html.escape("\n".join(block)) + "</pre>")
        elif re.match(r"^#{1,6} ", stripped):
            flush()
            level = min(len(stripped) - len(stripped.lstrip("#")) + 1, 6)
            out.append(f"<h{level}>{_md_inline(stripped.lstrip('#').strip())}</h{level}>")
        elif stripped.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            i -= 1
            if rows:
                head = "".join(f"<th>{_md_inline(c)}</th>" for c in rows[0])
                body = "".join("<tr>" + "".join(f"<td>{_md_inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
                out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
        elif re.match(r"^([-*]|\d+\.) ", stripped):
            flush()
            items = []
            while i < len(lines) and re.match(r"^([-*]|\d+\.) ", lines[i].strip()):
                items.append(re.sub(r"^([-*]|\d+\.) ", "", lines[i].strip()))
                i += 1
            i -= 1
            out.append("<ul>" + "".join(f"<li>{_md_inline(t)}</li>" for t in items) + "</ul>")
        elif not stripped:
            flush()
        else:
            para.append(stripped)
        i += 1
    flush()
    return "\n".join(out)


_STATUS_LABEL = {"pending": "대기", "running": "실행 중", "in_progress": "진행 중(이어서 실행)", "done": "완료",
                 "failed": "실패", "cancelled": "취소", "invalid": "정의 오류"}

_INDEX_STYLE = """<style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e3e2dc;--ok:#1f7a3a;--bad:#b3261e;--run:#8a5a00}
@media (prefers-color-scheme: dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;--card:#20201e;--line:#34332f;--ok:#6fcf8a;--bad:#f28b82;--run:#f2c46d}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,system-ui,sans-serif;max-width:900px}
a{color:inherit}.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:12px 0}
.st{font-weight:600}.st.done{color:var(--ok)}.st.failed,.st.invalid{color:var(--bad)}.st.running,.st.in_progress{color:var(--run)}
pre{white-space:pre-wrap;overflow-x:auto;background:var(--bg);padding:8px;border-radius:6px;font-size:13px}
table{border-collapse:collapse;display:block;overflow-x:auto}td,th{border:1px solid var(--line);padding:4px 8px;text-align:left}
summary{cursor:pointer;font-weight:600}
</style>"""


def write_index(cfg: Config, state: dict, jobs: Optional[dict[str, JobDef]] = None) -> Path:
    """관제 센터 '검증 연구 결과' 카드가 보여 줄 index.html 을 다시 만든다."""
    parts = []
    entries = sorted(state.get("jobs", {}).items(), key=lambda kv: (kv[1].get("status") != "running",
                                                                     kv[1].get("priority") or 0, kv[0]))
    for job_id, entry in entries:
        status = entry.get("status", "?")
        meta = [f"시도(실패) {entry.get('failures', 0)}", f"실행 {entry.get('runs', 0)}회"]
        if entry.get("last_finished_at"):
            meta.append(f"마지막 종료 {entry['last_finished_at']}")
        if entry.get("last_duration_seconds") is not None:
            meta.append(f"소요 {int(entry['last_duration_seconds'])}초")
        body = [f'<h2>{html.escape(entry.get("title") or job_id)}</h2>',
                f'<p><span class="st {html.escape(status)}">{html.escape(_STATUS_LABEL.get(status, status))}</span>'
                f' · <span class="muted">{html.escape(job_id)} · {html.escape(" · ".join(meta))}</span></p>']
        if entry.get("last_reason"):
            body.append(f'<p class="muted">{html.escape(redact(entry["last_reason"]))}</p>')
        if entry.get("summary"):
            body.append(f"<pre>{html.escape(entry['summary'])}</pre>")
        publish = entry.get("publish") or {}
        if publish.get("status"):
            body.append(f'<p class="muted">저장소 반영: {html.escape(publish["status"])} {html.escape(publish.get("detail") or "")}</p>')
        report = cfg.results_dir / job_id / "REPORT.md"
        if status == "done" and report.is_file():
            with contextlib.suppress(OSError):
                text = report.read_text(encoding="utf-8", errors="replace")[:REPORT_RENDER_MAX_CHARS]
                body.append(f"<details open><summary>REPORT.md</summary>{markdown_to_html(redact(text))}</details>")
        if status in ("failed", "in_progress") and entry.get("log_tail"):
            body.append(f"<details><summary>로그 끝부분</summary><pre>{html.escape(entry['log_tail'][-1500:])}</pre></details>")
        parts.append('<div class="card">' + "".join(body) + "</div>")
    runner = state.get("runner", {})
    windows = ", ".join(f"{s.strftime('%H:%M')}~{e.strftime('%H:%M')}" for s, e in RUN_WINDOWS)
    page = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>검증 연구 결과</title>'
        f'{_INDEX_STYLE}</head><body><p><a href="/">&larr; 관제 센터로</a></p><h1>검증 연구 결과</h1>'
        f'<p class="muted">실행 창(KST) {windows}, 20분마다 한 작업씩. 마지막 확인 {html.escape(str(runner.get("last_tick_at") or "-"))}'
        f' — {html.escape(str(runner.get("last_tick_result") or "-"))}</p>'
        + ("".join(parts) or "<p>등록된 작업이 없습니다(research/jobs/&lt;id&gt;/job.json).</p>")
        + '<p class="muted">재시도·취소: python scripts/research_jobs_admin.py list / retry &lt;id&gt; / cancel &lt;id&gt;</p>'
        "</body></html>"
    )
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    target = cfg.results_dir / "index.html"
    tmp = target.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(target)
    return target


# ---------------------------------------------------------------------------
# 저장소 반영 (작업트리를 건드리지 않는 git 배관 — deploy/codex_telegram/runner.py push_progress_entry 와 같은 원리)
# ---------------------------------------------------------------------------
def collect_publishable(cfg: Config, job: JobDef, result_dir: Path) -> tuple[dict[str, bytes], list[str]]:
    """저장소에 올릴 작은 텍스트 파일 {저장소 경로: 내용}과 건너뛴 이유 목록."""
    files: dict[str, bytes] = {}
    skipped: list[str] = []
    total = 0
    for rel in job.outputs:
        path = result_dir / rel
        if not rel.lower().endswith(PUBLISH_EXTENSIONS):
            skipped.append(f"{rel}(텍스트 아님)")
            continue
        try:
            data = path.read_bytes()
        except OSError:
            skipped.append(f"{rel}(읽기 실패)")
            continue
        if len(data) > PUBLISH_MAX_FILE_BYTES or total + len(data) > PUBLISH_MAX_TOTAL_BYTES:
            skipped.append(f"{rel}(크기 상한 초과)")
            continue
        text = data.decode("utf-8", "replace")
        if looks_secret(text):
            skipped.append(f"{rel}(비밀처럼 보이는 내용)")
            continue
        files[f"{cfg.publish_prefix}/{job.id}/{rel}"] = data
        total += len(data)
    return files, skipped


def _git(root: Path, *args: str, env: Optional[dict] = None, input_bytes: Optional[bytes] = None,
         timeout: int = 120) -> subprocess.CompletedProcess:
    full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    return subprocess.run(["git", "-C", str(root), *args], input=input_bytes, capture_output=True,
                          env=full_env, timeout=timeout)


def _err(proc: subprocess.CompletedProcess) -> str:
    text = (proc.stderr or b"").decode("utf-8", "replace") + (proc.stdout or b"").decode("utf-8", "replace")
    return redact(text.strip())


def publish_files(repo_root: Path, files: dict[str, bytes], message: str, *, remote: str = "origin",
                  branch: str = "main", attempts: int = 3, index_dir: Optional[Path] = None) -> dict:
    """origin/<branch> 위에 files 만 바꾼 커밋 하나를 만들어 push 한다. 작업트리·HEAD·기본 인덱스는 건드리지 않는다.

    반환: {"status": "pushed"|"no-credentials"|"failed"|"skipped", "detail": str, "sha": str|None}
    non-fast-forward(그 사이 누가 push)면 다시 fetch 해서 attempts 번까지 재시도한다.
    """
    if not files:
        return {"status": "skipped", "detail": "올릴 파일 없음", "sha": None}
    repo_root = Path(repo_root)
    index_dir = Path(index_dir or tempfile.gettempdir())
    index_dir.mkdir(parents=True, exist_ok=True)
    last = ""
    for _attempt in range(attempts):
        fetch = _git(repo_root, "fetch", "--quiet", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}", timeout=180)
        if fetch.returncode != 0:
            last = _err(fetch)
            if _NO_CREDENTIALS.search(last):
                return {"status": "no-credentials", "detail": last.splitlines()[-1][:200] if last else "", "sha": None}
            continue
        base_proc = _git(repo_root, "rev-parse", f"refs/remotes/{remote}/{branch}")
        base = base_proc.stdout.decode().strip()
        if base_proc.returncode != 0 or not base:
            return {"status": "failed", "detail": f"{remote}/{branch} 를 찾지 못함", "sha": None}
        index = index_dir / f"research-publish-index-{os.getpid()}"
        env = {"GIT_INDEX_FILE": str(index)}
        try:
            if _git(repo_root, "read-tree", base, env=env).returncode != 0:
                return {"status": "failed", "detail": "트리 준비 실패", "sha": None}
            for path, data in sorted(files.items()):
                blob = _git(repo_root, "hash-object", "-w", "--stdin", input_bytes=data)
                if blob.returncode != 0:
                    return {"status": "failed", "detail": "blob 기록 실패", "sha": None}
                upd = _git(repo_root, "update-index", "--add", "--cacheinfo", f"100644,{blob.stdout.decode().strip()},{path}", env=env)
                if upd.returncode != 0:
                    return {"status": "failed", "detail": f"인덱스 갱신 실패: {path}", "sha": None}
            tree = _git(repo_root, "write-tree", env=env)
        finally:
            with contextlib.suppress(OSError):
                index.unlink()
        if tree.returncode != 0:
            return {"status": "failed", "detail": "트리 작성 실패", "sha": None}
        tree_sha = tree.stdout.decode().strip()
        base_tree = _git(repo_root, "rev-parse", f"{base}^{{tree}}").stdout.decode().strip()
        if tree_sha == base_tree:
            return {"status": "skipped", "detail": "origin 에 이미 같은 내용", "sha": base}
        commit = _git(repo_root, "-c", "user.name=quant-research-runner", "-c", "user.email=quant-research-runner@localhost",
                      "-c", "commit.gpgsign=false", "commit-tree", tree_sha, "-p", base, "-m", message)
        if commit.returncode != 0:
            return {"status": "failed", "detail": "커밋 작성 실패", "sha": None}
        new_sha = commit.stdout.decode().strip()
        push = _git(repo_root, "push", "--quiet", remote, f"{new_sha}:refs/heads/{branch}", timeout=180)
        if push.returncode == 0:
            return {"status": "pushed", "detail": f"{base[:7]}..{new_sha[:7]}", "sha": new_sha}
        last = _err(push)
        if _NO_CREDENTIALS.search(last):
            return {"status": "no-credentials", "detail": last.splitlines()[-1][:200] if last else "", "sha": None}
        if not _NON_FAST_FORWARD.search(last):
            break
    tail = last.splitlines()[-1][:200] if last else "알 수 없는 오류"
    return {"status": "failed", "detail": tail, "sha": None}


def default_publisher(cfg: Config) -> Callable[[dict[str, bytes], str], dict]:
    def _publish(files: dict[str, bytes], message: str) -> dict:
        if os.getenv("RESEARCH_JOBS_PUBLISH", "1") == "0":
            return {"status": "skipped", "detail": "RESEARCH_JOBS_PUBLISH=0", "sha": None}
        if os.getenv("PYTEST_CURRENT_TEST"):
            return {"status": "skipped", "detail": "테스트 중에는 실제 origin 에 올리지 않음", "sha": None}
        return publish_files(cfg.repo_root, files, message, index_dir=cfg.state_dir)
    return _publish


# ---------------------------------------------------------------------------
# 한 회차
# ---------------------------------------------------------------------------
_PUBLISH_NOTE = {
    "pushed": "저장소 {prefix}/{id}/ 에 반영됨",
    "no-credentials": "VM 에 push 권한이 없어 저장소 반영은 건너뜀(VM 과 관제 센터에만 있음)",
    "skipped": "저장소 반영 없음({detail})",
    "failed": "저장소 반영 실패: {detail}",
}


def _finish_message(cfg: Config, job: JobDef, summary: str, publish: dict) -> str:
    lines = [f"[검증 연구 결과] {job.title} — 완료"]
    if summary:
        lines.append(summary)
    lines.append("결과: 관제 센터 '검증 연구 결과' 카드")
    note = _PUBLISH_NOTE.get(publish.get("status"), "저장소 반영: {detail}")
    lines.append(note.format(prefix=cfg.publish_prefix, id=job.id, detail=publish.get("detail") or ""))
    return redact("\n".join(lines))[:3500]


_STOP_TEXT = {"budget": "시간 예산 초과", "cancel": "사용자 취소", "job_memory": "작업 메모리 상한 초과",
              "job_disk": "작업 디스크 상한 초과", "system_memory": "VM 여유 메모리 부족으로 양보",
              "system_disk": "VM 여유 디스크 부족으로 양보"}


def _first_error_line(log_tail: str) -> str:
    lines = [l.strip() for l in (log_tail or "").splitlines() if l.strip()]
    return lines[-1][:160] if lines else ""


def apply_outcome(cfg: Config, job: JobDef, entry: dict, outcome: RunOutcome, budget_shortened: bool,
                  notify: Callable[[str], object], publish: Callable[[dict[str, bytes], str], dict],
                  now: datetime, runner: dict) -> str:
    """실행 결과를 상태에 반영하고 알림·보관·반영을 한다. 결과 한 단어(done/in_progress/failed/...)를 돌려준다."""
    entry.update(pid=None, last_finished_at=_now_iso(now), last_duration_seconds=round(outcome.duration, 1),
                 last_exit_code=outcome.exit_code, log_tail=outcome.log_tail)
    entry["runs"] = int(entry.get("runs") or 0) + 1
    code = outcome.exit_code

    def fail(reason: str) -> str:
        entry["failures"] = int(entry.get("failures") or 0) + 1
        entry["last_reason"] = reason
        final = entry["failures"] >= job.max_attempts
        entry["status"] = "failed" if final else ("in_progress" if job.resumable else "pending")
        signature = hashlib.sha1(reason.split(":")[0].encode()).hexdigest()[:12]
        if final or entry.get("notified_signature") != signature:
            entry["notified_signature"] = signature
            head = "실패(재시도 중단)" if final else f"실패 {entry['failures']}/{job.max_attempts}회, 다음 회차에 다시 시도"
            notify(redact(f"[검증 연구 결과] {job.title} — {head}\n사유: {reason}"[:1000]))
        return "failed" if final else "retry"

    if code == 0:
        result_dir, missing = store_results(cfg, job)
        if result_dir is None:
            return fail(f"출력 누락: {', '.join(missing)}")
        summary = extract_summary(job, result_dir)
        files, skipped = collect_publishable(cfg, job, result_dir)
        stamp = now.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
        try:
            result = publish(files, f"Research job results: {job.id} ({stamp})")
        except Exception as exc:  # noqa: BLE001 — 반영 실패가 결과 보관을 막으면 안 된다
            result = {"status": "failed", "detail": f"{type(exc).__name__}", "sha": None}
        if skipped:
            result = {**result, "detail": (result.get("detail") or "") + f" (제외: {', '.join(skipped)})"}
        if result.get("status") == "pushed":
            finished = now + timedelta(seconds=outcome.duration)  # 회차 시작이 아니라 실제로 push 한 시점 기준
            runner["cooldown_until"] = (finished + timedelta(seconds=POST_PUBLISH_COOLDOWN_SECONDS)).isoformat()
        entry.update(status="done", summary=summary, publish=result, result_dir=str(result_dir),
                     last_reason=None, notified_signature=None)
        shutil.rmtree(cfg.work_dir(job.id), ignore_errors=True)
        notify(_finish_message(cfg, job, summary, result))
        return "done"
    if code == 3:
        if entry["runs"] >= job.max_runs:
            return fail(f"진행 중(3) 종료가 {entry['runs']}번 — max_runs 도달")
        entry.update(status="in_progress", last_reason="체크포인트 저장 후 정상 중단 — 다음 회차에 이어서")
        return "in_progress"
    stop = outcome.stopped_by
    if stop == "cancel":
        entry.update(status="cancelled", cancel_requested=False, last_reason="사용자 취소")
        return "cancelled"
    if stop in ("system_memory", "system_disk"):
        entry.update(status="in_progress" if job.resumable else "pending", last_reason=_STOP_TEXT[stop])
        return "yielded"
    if stop == "budget" and job.resumable and budget_shortened:
        if entry["runs"] >= job.max_runs:
            return fail(f"창 시간 부족으로 {entry['runs']}번 중단 — max_runs 도달")
        entry.update(status="in_progress", last_reason="실행 창이 끝나 중단(체크포인트로 이어서) — 스크립트가 시간 예산을 먼저 지키면 더 좋습니다")
        return "in_progress"
    if stop:
        return fail(_STOP_TEXT.get(stop, stop))
    tail = _first_error_line(outcome.log_tail)
    return fail(f"종료 코드 {code}" + (f": {tail}" if tail else ""))


def run_tick(now: Optional[datetime] = None, *, notify: Optional[Callable[[str], object]] = None,
             publish: Optional[Callable[[dict[str, bytes], str], dict]] = None, cfg: Optional[Config] = None,
             headroom: Optional[Callable[[], bool]] = None, poll_interval: float = 5.0,
             ignore_window: bool = False) -> dict:
    """한 회차: 창·락·자원 확인 → 대기 작업 하나 실행 → 결과 처리. 결과 요약 dict 를 돌려준다."""
    cfg = cfg or Config()
    now = now or datetime.now(timezone.utc)
    notify = notify or (lambda text: None)
    publish = publish or default_publisher(cfg)
    if headroom is None:
        from core.resource_guard import has_headroom as headroom
    window_end = window_end_for(now)
    if window_end is None and ignore_window:
        window_end = now + timedelta(seconds=longest_window_seconds())
    if window_end is None:
        return {"action": "skipped", "reason": "실행 창 밖"}

    with _flock(cfg.state_dir / "runner.lock", blocking=False) as got:
        if not got:
            return {"action": "skipped", "reason": "다른 작업이 실행 중"}
        jobs, invalid = load_job_definitions(cfg)
        with edit_state(cfg) as state:
            invalid_notes = sync_definitions(cfg, state, jobs, invalid)
            recovered = recover_stale(state, jobs)
            runner = state["runner"]
            runner["last_tick_at"] = _now_iso(now)
        for job_id, reason in invalid_notes:
            notify(redact(f"[검증 연구 결과] 작업 정의 오류: {job_id}\n사유: {reason}\n(docs/RESEARCH_JOBS.md 계약 참고)")[:1000])

        def _finish_tick(result: dict) -> dict:
            with edit_state(cfg) as st:
                st["runner"]["last_tick_result"] = result.get("reason") or result.get("action")
                write_index(cfg, st, jobs)
            result["recovered"] = recovered
            return result

        cooldown = runner.get("cooldown_until")
        if cooldown:
            with contextlib.suppress(ValueError):
                if datetime.fromisoformat(cooldown) > now:
                    return _finish_tick({"action": "skipped", "reason": "결과 반영 직후 재배포 대기"})
        with edit_state(cfg) as state:
            job, budget, shortened = pick_job(state, jobs, now, window_end)
        if job is None:
            if cfg.satellite_lab and os.environ.get("RESEARCH_SATELLITE_LAB", "1") != "0":
                return _finish_tick(_satellite_lab_turn(cfg, now, window_end, notify, headroom, poll_interval))
            return _finish_tick({"action": "idle", "reason": "실행할 작업 없음"})
        if not headroom():
            return _finish_tick({"action": "skipped", "reason": "VM 여유 없음(부하·메모리)"})
        free = free_disk_mb(cfg.state_dir)
        if free is not None and free < MIN_FREE_DISK_MB:
            return _finish_tick({"action": "skipped", "reason": f"여유 디스크 부족({int(free)}MB)"})

        with edit_state(cfg) as state:
            entry = state["jobs"][job.id]
            if not job.resumable:
                shutil.rmtree(cfg.work_dir(job.id), ignore_errors=True)  # 재개 불가 작업은 매번 새로
            entry.update(status="running", last_started_at=_now_iso(now), pid=os.getpid(), cancel_requested=False)

        def _cancel_requested() -> bool:
            return bool(load_state(cfg)["jobs"].get(job.id, {}).get("cancel_requested"))

        outcome = run_child(cfg, job, budget, poll_interval=poll_interval, cancel_check=_cancel_requested)
        with edit_state(cfg) as state:
            entry = state["jobs"][job.id]
            result = apply_outcome(cfg, job, entry, outcome, shortened, notify, publish, now, state["runner"])
        return _finish_tick({"action": "ran", "job_id": job.id, "result": result, "exit_code": outcome.exit_code,
                             "budget": budget, "duration": round(outcome.duration, 1)})


# ---------------------------------------------------------------------------
# 새틀라이트 R&D 센터 (2026-10-02) — 사전 등록 연구가 하나도 대기하지 않는 창에서만 돈다
# ---------------------------------------------------------------------------
SATELLITE_LAB_JOB = JobDef(
    id="satellite-lab", title="새틀라이트 R&D 센터 심판", entrypoint="scripts/satellite_lab_worker.py", args=(),
    timeout_seconds=3 * 3600, max_attempts=3, resumable=True, outputs=("status.json",), summary_from=None,
    priority=1000, max_memory_mb=4096, max_disk_mb=1024,
)
SATELLITE_LAB_BULK_NOTICE = 3  # 새 판정이 이보다 많으면 한 통으로 묶는다


def _satellite_lab_turn(cfg: Config, now: datetime, window_end: datetime, notify: Callable[[str], object],
                        headroom: Callable[[], bool], poll_interval: float) -> dict:
    """빈 창 한 회차: 심판할 후보가 있으면 계산기(scripts/satellite_lab_worker.py)를 같은 보호 장치로 돌린다.

    사전 등록 연구(research/jobs)가 언제나 먼저다 — 이 함수는 pick_job 이 아무것도 고르지 않았을 때만 불린다.
    계산기는 결과를 data/satellite_lab/registry.json 에 직접 쓰고, 여기서는 새 판정을 텔레그램으로 알린다.
    """
    from core import satellite_lab as sl

    job = SATELLITE_LAB_JOB
    try:
        if not sl.has_work():
            return {"action": "idle", "reason": "실행할 작업 없음(새틀라이트 R&D 대기 없음)"}
    except Exception as exc:  # noqa: BLE001 - 연구실 등록부 문제로 실행기 전체가 죽지 않게
        return {"action": "idle", "reason": f"새틀라이트 R&D 상태 확인 실패: {type(exc).__name__}"}
    budget, _ = budget_for(job, now, window_end)
    if budget < MIN_BUDGET_SECONDS:
        return {"action": "idle", "reason": "새틀라이트 R&D: 창에 남은 시간 부족"}
    if not headroom():
        return {"action": "skipped", "reason": "VM 여유 없음(부하·메모리)"}
    free = free_disk_mb(cfg.state_dir)
    if free is not None and free < MIN_FREE_DISK_MB:
        return {"action": "skipped", "reason": f"여유 디스크 부족({int(free)}MB)"}
    with edit_state(cfg) as state:
        state.setdefault("satellite_lab", {})["last_started_at"] = _now_iso(now)
    outcome = run_child(cfg, job, budget, poll_interval=poll_interval)
    ok = outcome.exit_code in (0, 3) or (outcome.stopped_by == "budget")
    with edit_state(cfg) as state:
        lab = state.setdefault("satellite_lab", {})
        lab.update(last_finished_at=_now_iso(), exit_code=outcome.exit_code, stopped_by=outcome.stopped_by,
                   duration=round(outcome.duration, 1), log_tail=None if ok else outcome.log_tail[-800:])
        signature = None if ok else f"{outcome.exit_code}|{outcome.stopped_by}|{_first_error_line(outcome.log_tail)}"
        repeat = signature is not None and signature == lab.get("failure_signature")
        lab["failure_signature"] = signature
    if not ok and not repeat:
        tail = _first_error_line(outcome.log_tail)
        notify(redact(f"[새틀라이트 R&D] 계산기 실패 (종료 코드 {outcome.exit_code}, {outcome.stopped_by or '-'})"
                      + (f"\n{tail}" if tail else ""))[:1000])
    _notify_satellite_verdicts(notify)
    return {"action": "ran", "job_id": job.id, "result": "ok" if ok else "failed", "exit_code": outcome.exit_code,
            "budget": budget, "duration": round(outcome.duration, 1)}


def _notify_satellite_verdicts(notify: Callable[[str], object], state_dir: Optional[Path] = None) -> int:
    from core import satellite_lab as sl

    fresh = []
    with sl.edit_registry(state_dir) as reg:
        for v in reg["variants"].values():
            if v.get("status") in (sl.STATUS_PASS, sl.STATUS_FAIL, sl.STATUS_ERROR) and not v.get("notified"):
                v["notified"] = True
                fresh.append(json.loads(json.dumps(v, default=str)))
    if not fresh:
        return 0
    passed = [v for v in fresh if v["status"] == sl.STATUS_PASS]
    if len(fresh) > SATELLITE_LAB_BULK_NOTICE:
        lines = [f"[새틀라이트 R&D] 새 판정 {len(fresh)}건 — 통과 {len(passed)}, 탈락·오류 {len(fresh) - len(passed)}"]
        lines += [f"· {v['id']} {v['spec'].get('title')}: {v['status']}" for v in fresh[:12]]
        lines.append("자세한 사유는 관제 센터 '새틀라이트 R&D 센터'에서 봅니다. 통과해도 챔피언에 자동 반영되지 않습니다.")
        notify("\n".join(lines)[:1500])
        for v in passed:
            notify(sl.notification_text(v))
    else:
        for v in fresh:
            notify(sl.notification_text(v))
    return len(fresh)


# ---------------------------------------------------------------------------
# 관리(scripts/research_jobs_admin.py)
# ---------------------------------------------------------------------------
def list_jobs(cfg: Optional[Config] = None) -> list[dict]:
    cfg = cfg or Config()
    jobs, invalid = load_job_definitions(cfg)
    state = load_state(cfg)
    rows = []
    for job_id in sorted(set(jobs) | set(invalid) | set(state["jobs"])):
        entry = state["jobs"].get(job_id, {})
        status = entry.get("status") or ("invalid" if job_id in invalid else "pending")
        if job_id in invalid:
            status = "invalid"
        rows.append({"id": job_id, "status": status, "title": entry.get("title") or (jobs[job_id].title if job_id in jobs else job_id),
                     "priority": jobs[job_id].priority if job_id in jobs else None, "failures": entry.get("failures", 0),
                     "runs": entry.get("runs", 0), "last_finished_at": entry.get("last_finished_at"),
                     "reason": invalid.get(job_id) or entry.get("last_reason"), "defined": job_id in jobs})
    return rows


def retry_job(job_id: str, *, fresh: bool = False, cfg: Optional[Config] = None) -> dict:
    cfg = cfg or Config()
    jobs, invalid = load_job_definitions(cfg)
    if job_id not in jobs:
        raise ValueError(invalid.get(job_id) or f"정의된 작업이 아닙니다: {job_id}")
    with edit_state(cfg) as state:
        entry = state["jobs"].get(job_id)
        if entry and entry.get("status") == "running":
            raise ValueError("실행 중인 작업은 재시도할 수 없습니다(먼저 cancel)")
        state["jobs"][job_id] = _new_entry(jobs[job_id])
        if fresh or (entry or {}).get("status") == "done":
            shutil.rmtree(cfg.work_dir(job_id), ignore_errors=True)
        write_index(cfg, state, jobs)
        return state["jobs"][job_id]


def cancel_job(job_id: str, *, cfg: Optional[Config] = None) -> str:
    cfg = cfg or Config()
    with edit_state(cfg) as state:
        entry = state["jobs"].get(job_id)
        if entry is None:
            raise ValueError(f"상태에 없는 작업입니다: {job_id}")
        if entry.get("status") == "running":
            entry["cancel_requested"] = True
            message = "취소 요청 — 실행기가 몇 초 안에 중단합니다"
        else:
            entry["status"] = "cancelled"
            message = "취소됨 — 다시 돌리려면 retry"
        write_index(cfg, state)
        return message
