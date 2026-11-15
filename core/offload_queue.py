"""클라우드 작업(offload) — 무거운 계산을 2코어 VM 대신 Claude Code 클라우드 세션에 맡기는 대기열 (2026-11-15).

대기열 = private 저장소 sternjeong/claude-offload. 작업 하나 = jobs/<id>/job.json + TASK.md (main 에 push).
main 에 push 되면 클라우드 루틴 'offload-worker' 가 실행되어 작업을 처리하고, 결과를 브랜치 claude/result-<id> 의
jobs/<id>/RESULT.md(첫 줄 status: running|done|partial|failed)와 artifacts/ 로 올린다. 코드 변경은 대상 저장소의
claude/offload-<id> 브랜치로만 간다(main 금지).
VM 셸에서는 ~/.local/bin/offload, 관제 허브에서는 '클라우드 작업' 화면(hub/offload_page.py)이 같은 형식을 쓴다.
허브는 quant 계정의 gh 인증(HTTPS)으로 data/offload_queue 에 대기열을 clone 해 읽고 쓴다.
이 모듈은 주문·전략 엔진과 무관하다.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_URL = os.environ.get("QUANT_OFFLOAD_REPO", "https://github.com/sternjeong/claude-offload.git")
QUEUE_DIR = Path(os.environ.get("QUANT_OFFLOAD_DIR", Path(__file__).resolve().parent.parent / "data" / "offload_queue"))
ROUTINE_URL = "https://claude.ai/code/routines/trig_01PyqVNrzz6iMhxaeH62TD6u"
# 클라우드 루틴 sources 에 등록된 저장소. 늘리려면 루틴(ROUTINE_URL)에도 같은 저장소를 추가해야 한다.
REPOS = ("sternjeong/Quant",)
FETCH_TTL = 60  # 초. 개요(60초 새로고침)마다 GitHub 에 가지 않게
STATUSES = ("queued", "running", "done", "partial", "failed")

_lock = threading.Lock()
_last_fetch = 0.0


class OffloadError(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    created_at: str
    repo: str
    ref: str
    timeout_min: int
    source: str
    task: str
    status: str = "queued"
    result: str = ""

    @property
    def title(self) -> str:
        first = self.task.strip().splitlines()[0] if self.task.strip() else self.id
        return first[:90] + ("…" if len(first) > 90 else "")


def _git(*args: str, timeout: int = 30, check: bool = True, input_text: Optional[str] = None) -> str:
    r = subprocess.run(["git", "-C", str(QUEUE_DIR), *args], capture_output=True, text=True, timeout=timeout,
                       input=input_text)
    if check and r.returncode != 0:
        raise OffloadError(f"git {args[0]} 실패: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def sync(force: bool = False) -> None:
    """대기열 clone 을 최신으로(없으면 만든다). FETCH_TTL 안에서는 다시 가져오지 않는다."""
    global _last_fetch
    with _lock:
        if not (QUEUE_DIR / ".git").is_dir():
            QUEUE_DIR.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["git", "clone", "-q", REPO_URL, str(QUEUE_DIR)], capture_output=True, text=True,
                               timeout=60)
            if r.returncode != 0:
                raise OffloadError(f"대기열 저장소를 가져오지 못했습니다: {r.stderr.strip()[:300]}")
            _last_fetch = 0.0
        if not force and time.time() - _last_fetch < FETCH_TTL:
            return
        _git("fetch", "-q", "--prune", "origin", "+refs/heads/main:refs/remotes/origin/main",
             "+refs/heads/claude/*:refs/remotes/origin/claude/*")
        _git("checkout", "-q", "main")
        _git("merge", "-q", "--ff-only", "origin/main")
        _last_fetch = time.time()


def _result_text(job_id: str) -> str:
    return _git("show", f"origin/claude/result-{job_id}:jobs/{job_id}/RESULT.md", check=False)


def _status_of(result: str) -> str:
    if not result:
        return "queued"
    first = result.strip().splitlines()[0] if result.strip() else ""
    status = first.removeprefix("status:").strip().lower() if first.startswith("status:") else ""
    return status if status in STATUSES else "done"


def _load_job(folder: Path, with_result: bool = True) -> Optional[Job]:
    try:
        meta = json.loads((folder / "job.json").read_text(encoding="utf-8"))
        task = (folder / "TASK.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    job = Job(id=str(meta.get("id") or folder.name), created_at=str(meta.get("created_at", "")),
              repo=str(meta.get("repo", "")), ref=str(meta.get("ref", "")),
              timeout_min=int(meta.get("timeout_min") or 50), source=str(meta.get("from", "")), task=task)
    if with_result:
        job.result = _result_text(job.id)
        job.status = _status_of(job.result)
    return job


def list_jobs(limit: int = 20) -> list[Job]:
    sync()
    folders = sorted((p for p in (QUEUE_DIR / "jobs").glob("*") if (p / "job.json").is_file()), reverse=True)
    return [j for j in (_load_job(f) for f in folders[:limit]) if j]


def get_job(job_id: str) -> Optional[Job]:
    if not job_id or "/" in job_id or job_id.startswith("."):
        return None
    sync()
    folder = QUEUE_DIR / "jobs" / job_id
    return _load_job(folder) if (folder / "job.json").is_file() else None


def artifacts(job_id: str) -> list[tuple[str, int]]:
    """결과 브랜치의 jobs/<id>/artifacts/ 파일 (이름, 바이트)."""
    out = _git("ls-tree", "-r", "-l", f"origin/claude/result-{job_id}", f"jobs/{job_id}/artifacts/", check=False)
    files = []
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 4 and parts[3].isdigit():
            files.append((path.removeprefix(f"jobs/{job_id}/artifacts/"), int(parts[3])))
    return files


def submit(task: str, *, repo: str = "", ref: str = "", timeout_min: int = 50, source: str = "hub",
           now: Optional[datetime] = None) -> Job:
    task = (task or "").strip()
    if not task or len(task) > 20000:
        raise OffloadError("작업 내용을 1~20000자로 적어 주세요.")
    if repo and repo not in REPOS:
        raise OffloadError("등록되지 않은 저장소입니다. 클라우드 루틴에 저장소를 먼저 추가해야 합니다.")
    if ref and (ref.startswith("-") or any(c.isspace() for c in ref) or len(ref) > 100):
        raise OffloadError("브랜치 이름이 올바르지 않습니다.")
    timeout_min = max(5, min(int(timeout_min or 50), 55))
    sync(force=True)
    now = now or datetime.now(timezone.utc)
    job_id = now.astimezone().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    folder = QUEUE_DIR / "jobs" / job_id
    folder.mkdir(parents=True)
    meta = {"id": job_id, "status": "queued", "created_at": now.isoformat(timespec="seconds"), "repo": repo,
            "ref": ref, "timeout_min": timeout_min, "from": source}
    (folder / "job.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "TASK.md").write_text(task + "\n", encoding="utf-8")
    with _lock:
        _git("add", f"jobs/{job_id}")
        _git("-c", "user.name=quant-hub", "-c", "user.email=quant-hub@localhost", "commit", "-q", "-m", f"job {job_id}")
        _git("push", "-q", "origin", "main", timeout=60)
    return Job(id=job_id, created_at=meta["created_at"], repo=repo, ref=ref, timeout_min=timeout_min, source=source,
               task=task)


def summary(jobs: list[Job]) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    for j in jobs:
        out[j.status] = out.get(j.status, 0) + 1
    return out
