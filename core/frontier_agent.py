"""알파·프런티어 목표 에이전트 (2026-11-10, 사용자 요청: "에이전트 하나를 담당해서 goal 로 설정한 후 계속해서 어떻게 해서든
alpha 를 찾거나 적어도 최적의 프런티어를 만들도록").

하는 일(주 4회, 05:00 KST, AI 연구 배치 시간 창 안):
  1. [결정론] 지금까지의 모든 검증 연구 결과(research/results/*)·목표 문서(research/frontier/FRONTIER.md)·대기 중 연구를 모아
     작업 폴더 research/frontier/work/<날짜>/context.md 를 만든다.
  2. [에이전트] Claude 가 결과를 읽고 FRONTIER.md 새 판(목표 대비 현재 최선의 후보·세후 수익/낙폭 프런티어·다음 가설)을 쓰고,
     필요하면 새 검증 연구 하나를 docs/RESEARCH_JOBS.md 계약대로 work/<날짜>/<id>/ 에 만든다(스모크만 직접 돌림).
  3. [결정론 관문] 새 연구가 있으면 id·job.json 검증, 금지 코드 검사, 저장소와 같은 구조의 임시 폴더에서 --smoke 실행(비밀값 없는 환경).
     모두 통과하면 research/jobs/<id>/ 와 새 FRONTIER.md 를 origin/main 에 한 커밋으로 올린다(작업트리·HEAD 는 건드리지 않음,
     core.research_jobs.publish_files). VM 연구 실행기가 나중에 전체 계산을 한다 — 결과를 보기 전에 규칙이 커밋되므로 사전 등록이 지켜진다.
안전장치: 쓰기는 research/frontier/work/** 만 허용(그 밖 변경은 core.agent_batch._guard 가 되돌림), 대기 중 프런티어 연구가
MAX_PENDING 개 이상이면 새로 만들지 않음, 우선순위는 MIN_PRIORITY 이상(사람이 올린 연구 뒤), 주문·브로커·엔진 변경 경로 없음.
엔진(챔피언 전략) 반영은 언제나 사용자 확인 뒤 별도 작업이다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from core import agent_batch as ab
from core import agent_budget as budget
from core import research_jobs as rj

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTIER_DIR = PROJECT_ROOT / "research" / "frontier"
FRONTIER_DOC = FRONTIER_DIR / "FRONTIER.md"
WORK_DIR = FRONTIER_DIR / "work"
PROMPT = PROJECT_ROOT / "research" / "agent_prompts" / "frontier.md"
ROLE = "frontier"

ID_RE = re.compile(r"^frontier-[a-z0-9][a-z0-9-]{2,40}-v\d+$")
MAX_PENDING = 2               # 아직 결과가 없는 프런티어 연구가 이만큼 있으면 새로 만들지 않는다
MIN_PRIORITY = 60
MAX_TIMEOUT_S = 3600
MAX_MEMORY_MB = 1500
MAX_RUNS = 40
SMOKE_TIMEOUT_S = 900
REQUIRED_FILES = ("job.json", "run.py", "SPEC.md")
# 연구 코드에 있으면 안 되는 것: 외부 프로세스·소켓·메일·쓰기 HTTP·삭제·주문 경로
FORBIDDEN = [
    (re.compile(r"\bsubprocess\b|\bos\.system\b|\bos\.popen\b"), "외부 프로세스 실행"),
    (re.compile(r"\bsocket\b|\bsmtplib\b"), "소켓·메일"),
    (re.compile(r"requests\.(post|put|patch|delete)\b|urlopen\([^)]*data="), "쓰기 HTTP 요청"),
    (re.compile(r"shutil\.rmtree|os\.remove\(|os\.unlink\(|\.unlink\("), "파일 삭제"),
    (re.compile(r"paper_auto_trade|alpaca_trade|submit_order|broker|telegram", re.I), "주문·알림 경로"),
    (re.compile(r"\bgit\b\s*(push|commit)|publish_files"), "저장소 쓰기"),
]


# ---------------------------------------------------------------- 상태·문맥
def _kst_day(now: datetime) -> str:
    return budget.kst(now).strftime("%Y%m%d")


def frontier_job_ids(repo_root: Path = PROJECT_ROOT) -> list[str]:
    jobs = repo_root / "research" / "jobs"
    return sorted(p.name for p in jobs.glob("frontier-*") if p.is_dir()) if jobs.is_dir() else []


def pending_frontier_jobs(repo_root: Path = PROJECT_ROOT, cfg: Optional[rj.Config] = None) -> list[str]:
    """결과 폴더가 아직 없는 프런티어 연구(실행 대기·실행 중·이어하기)."""
    results = repo_root / "research" / "results"
    return [j for j in frontier_job_ids(repo_root) if not (results / j / "results.json").is_file()]


def _verdict_line(path: Path) -> str:
    try:
        v = json.loads(path.read_text(encoding="utf-8")).get("verdicts")
    except (OSError, ValueError):
        return "(결과 읽기 실패)"
    return json.dumps(v, ensure_ascii=False)[:400] if v is not None else "(verdicts 없음)"


def results_digest(repo_root: Path = PROJECT_ROOT) -> str:
    """모든 연구 결과 한 줄 요약: id · 제목 · 판정. 오래된 것부터."""
    results, jobs = repo_root / "research" / "results", repo_root / "research" / "jobs"
    rows = []
    for d in sorted(results.glob("*")) if results.is_dir() else []:
        rj_path = d / "results.json"
        if not rj_path.is_file():
            continue
        title = ""
        try:
            title = json.loads((jobs / d.name / "job.json").read_text(encoding="utf-8")).get("title", "")
        except (OSError, ValueError):
            pass
        mtime = datetime.fromtimestamp(rj_path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append((mtime, f"- `{d.name}` ({mtime}) {title}\n  판정: {_verdict_line(rj_path)}"))
    rows.sort()
    return "\n".join(r for _, r in rows)


def write_context(work: Path, now: datetime, repo_root: Path = PROJECT_ROOT) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    pend = pending_frontier_jobs(repo_root)
    lines = [f"# 프런티어 에이전트 문맥 — {budget.kst(now):%Y-%m-%d %H:%M} KST (자동 생성)", "",
             f"작업 폴더: `{work.relative_to(repo_root)}` — 여기에만 쓸 수 있다.",
             f"대기 중(결과 없음) 프런티어 연구: {', '.join(pend) or '없음'} (최대 {MAX_PENDING}개 — 이미 꽉 차면 새 연구를 만들지 말 것)",
             f"이미 있는 프런티어 연구: {', '.join(frontier_job_ids(repo_root)) or '없음'}", "",
             "## 모든 검증 연구 결과 (오래된 순, id · 날짜 · 제목 · 판정)", "",
             "자세한 내용은 `research/results/<id>/REPORT.md`, 규칙은 `research/jobs/<id>/SPEC.md` 를 읽는다.", "",
             results_digest(repo_root)]
    path = work / "context.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def prompt_for(work: Path, now: datetime, repo_root: Path = PROJECT_ROOT) -> str:
    rel = work.relative_to(repo_root)
    allow_new = len(pending_frontier_jobs(repo_root)) < MAX_PENDING
    return (f"오늘은 {budget.kst(now):%Y-%m-%d} (KST). 먼저 `{rel}/context.md` 와 `research/frontier/FRONTIER.md` 를 읽어라.\n"
            f"1) `{rel}/FRONTIER.md` 에 목표 문서의 새 판을 써라(전체 문서, 형식은 기존 FRONTIER.md 와 같게).\n"
            + (f"2) 새 검증 연구가 가장 큰 정보 가치를 줄 때만 하나를 `{rel}/<id>/` 에 job.json·run.py·SPEC.md 로 만들고 "
               f"`python {rel}/<id>/run.py --smoke --out {rel}/<id>/_smoke_out --checkpoint {rel}/<id>/_smoke_ck` 로 스모크를 통과시켜라. "
               "id 는 frontier-<짧은-이름>-v1 형식. job.json 의 entrypoint 는 research/jobs/<id>/run.py 로 적는다(관문이 그 자리로 옮긴다).\n"
               if allow_new else
               "2) 대기 중 프런티어 연구가 이미 꽉 찼다. 이번에는 새 연구를 만들지 말고 문서만 갱신하라.\n")
            + f"3) 마지막에 `{rel}/journal.md` 에 이번에 무엇을 읽고 무엇을 판단했는지 10줄 안으로 적어라.")


def tools(work: Path, repo_root: Path = PROJECT_ROOT) -> list[str]:
    rel = work.relative_to(repo_root)
    return ["Read", "Glob", "Grep", "WebSearch", "WebFetch", f"Write({rel}/**)", f"Edit({rel}/**)",
            f"Bash(python {rel}/:*)", f"Bash(python -m pytest {rel}:*)"]


# ---------------------------------------------------------------- 결정론 관문
def static_problems(job_dir: Path) -> list[str]:
    out = []
    for py in sorted(job_dir.rglob("*.py")):
        if any(part.startswith("_smoke") for part in py.parts):
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        for rx, why in FORBIDDEN:
            if rx.search(text):
                out.append(f"{py.name}: {why}")
    return out


def normalize_job(data: dict, job_id: str) -> dict:
    """우선순위·자원 상한을 관문이 강제한다(에이전트가 적은 값보다 보수적으로)."""
    d = dict(data)
    d["id"] = job_id
    d["entrypoint"] = f"research/jobs/{job_id}/run.py"
    d["priority"] = max(int(d.get("priority", MIN_PRIORITY) or MIN_PRIORITY), MIN_PRIORITY)
    d["timeout_seconds"] = min(int(d.get("timeout_seconds", MAX_TIMEOUT_S) or MAX_TIMEOUT_S), MAX_TIMEOUT_S)
    d["max_memory_mb"] = min(int(d.get("max_memory_mb", MAX_MEMORY_MB) or MAX_MEMORY_MB), MAX_MEMORY_MB)
    d["max_runs"] = min(int(d.get("max_runs", MAX_RUNS) or MAX_RUNS), MAX_RUNS)
    t = str(d.get("title", "")).strip()
    d["title"] = t if t.startswith("[프런티어]") else f"[프런티어] {t}"
    return d


def _job_files(job_dir: Path) -> dict[str, bytes]:
    files = {}
    for p in sorted(job_dir.rglob("*")):
        rel = p.relative_to(job_dir)
        if p.is_file() and not any(part.startswith(("_smoke", "__pycache__")) for part in rel.parts) and p.suffix != ".pyc":
            files[str(rel)] = p.read_bytes()
    return files


def staging_root(job_id: str, files: dict[str, bytes], repo_root: Path = PROJECT_ROOT) -> Path:
    """저장소와 같은 구조의 임시 폴더: 최상위 폴더는 심볼릭 링크, research/jobs 는 기존 연구 링크 + 새 연구 실제 사본."""
    root = Path(tempfile.mkdtemp(prefix="frontier-stage-"))
    for p in repo_root.iterdir():
        if p.name in ("research", ".git"):
            continue
        (root / p.name).symlink_to(p)
    (root / "research").mkdir()
    for p in (repo_root / "research").iterdir():
        if p.name != "jobs":
            (root / "research" / p.name).symlink_to(p)
    jobs = root / "research" / "jobs"
    jobs.mkdir()
    for p in (repo_root / "research" / "jobs").iterdir():
        if p.name != job_id:
            (jobs / p.name).symlink_to(p)
    dest = jobs / job_id
    for rel, data in files.items():
        f = dest / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    return root


def run_smoke(root: Path, job: dict, timeout: int = SMOKE_TIMEOUT_S) -> tuple[bool, str]:
    out, ck = root / "_out", root / "_ck"
    cmd = [sys.executable, str(root / job["entrypoint"]), *job.get("args", []), "--out", str(out), "--checkpoint", str(ck), "--smoke"]
    try:
        proc = subprocess.run(cmd, cwd=root, env=ab._child_env(), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"스모크 {timeout}초 초과"
    if proc.returncode != 0:
        return False, f"스모크 종료 코드 {proc.returncode}: {(proc.stderr or proc.stdout or '')[-400:]}"
    missing = [o for o in job.get("outputs", []) if not (out / o).is_file()]
    if missing:
        return False, f"스모크 출력 없음: {missing}"
    return True, (proc.stdout or "")[-300:]


def gate(job_dir: Path, repo_root: Path = PROJECT_ROOT) -> tuple[Optional[dict], dict[str, bytes], str]:
    """(정규화된 job.json, 올릴 파일, 사유). 실패면 job 이 None."""
    job_id = job_dir.name
    if not ID_RE.match(job_id):
        return None, {}, f"id 형식 아님: {job_id}"
    if (repo_root / "research" / "jobs" / job_id).exists() or (repo_root / "research" / "results" / job_id).exists():
        return None, {}, f"이미 있는 id: {job_id}"
    missing = [f for f in REQUIRED_FILES if not (job_dir / f).is_file()]
    if missing:
        return None, {}, f"파일 없음: {missing}"
    try:
        raw = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, {}, f"job.json 읽기 실패: {exc}"
    if not isinstance(raw, dict):
        return None, {}, "job.json 이 객체가 아님"
    probs = static_problems(job_dir)
    if probs:
        return None, {}, "금지 코드: " + "; ".join(probs[:5])
    job = normalize_job(raw, job_id)
    files = _job_files(job_dir)
    files["job.json"] = (json.dumps(job, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    root = staging_root(job_id, files, repo_root)
    try:
        jd, why = rj.validate_job(job, job_id, repo_root=root)
        if jd is None:
            return None, {}, f"job.json 검증 실패: {why}"
        ok, msg = run_smoke(root, job)
        if not ok:
            return None, {}, msg
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return job, files, "ok"


# ---------------------------------------------------------------- 실행
def run(*, now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        runner: Optional[Callable[..., dict]] = None, publish: Optional[Callable[..., dict]] = None,
        notify: Optional[Callable[[str], Any]] = None, repo_root: Path = PROJECT_ROOT) -> dict:
    now = now_fn()
    ok, why = budget.can_launch(ROLE, now)
    if not ok:
        return {"status": "skipped", "reason": why}
    work = WORK_DIR / _kst_day(now) if repo_root == PROJECT_ROOT else repo_root / "research" / "frontier" / "work" / _kst_day(now)
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    write_context(work, now, repo_root)
    cfg = budget.effective(ROLE)
    system = PROMPT.read_text(encoding="utf-8") if PROMPT.is_file() else ""
    before = ab._porcelain()
    timeout = min(cfg.timeout_sec, budget.seconds_until_hard_stop(now))
    res = (runner or ab.claude_runner)(ROLE, prompt_for(work, now, repo_root), tools(work, repo_root), cfg, timeout, system=system)
    reverted = ab._guard(before)
    budget.record({"at": budget.kst(now).isoformat(), "role": ROLE, "target": work.name, "model": cfg.model,
                   "ok": res.get("ok"), "limited": res.get("limited"), "timed_out": res.get("timed_out"),
                   "cost_usd": res.get("cost_usd"), "turns": res.get("turns"), "duration_s": res.get("duration_s"),
                   "reverted": reverted})
    files: dict[str, bytes] = {}
    log: list[str] = []
    new_doc = work / "FRONTIER.md"
    if new_doc.is_file() and new_doc.stat().st_size > 200:
        files["research/frontier/FRONTIER.md"] = new_doc.read_bytes()
    journal = work / "journal.md"
    if journal.is_file():
        files[f"research/frontier/journal/{work.name}.md"] = journal.read_bytes()
    promoted = []
    if len(pending_frontier_jobs(repo_root)) < MAX_PENDING:
        for d in sorted(p for p in work.iterdir() if p.is_dir() and p.name.startswith("frontier-")):
            job, jf, msg = gate(d, repo_root)
            if job is None:
                log.append(f"관문 탈락 {d.name}: {msg}")
                continue
            for rel, data in jf.items():
                files[f"research/jobs/{d.name}/{rel}"] = data
            promoted.append(d.name)
            break                                   # 한 번에 하나만
    pub = {"status": "skipped", "detail": "올릴 것 없음"}
    if files:
        msg = f"Frontier agent {work.name}: " + (f"register {', '.join(promoted)}" if promoted else "update FRONTIER.md")
        pub = (publish or rj.publish_files)(repo_root, files, msg + "\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    result = {"status": "ran", "agent": {k: res.get(k) for k in ("ok", "limited", "timed_out", "turns", "duration_s")},
              "reverted": reverted, "promoted": promoted, "log": log, "publish": pub.get("status"), "files": sorted(files)}
    if notify:
        lines = [f"[프런티어 에이전트] {budget.kst(now):%m-%d} 실행 · 에이전트 {'성공' if res.get('ok') else '실패'}"
                 + (" (사용량 한도)" if res.get("limited") else ""),
                 f"새 연구: {', '.join(promoted) or '없음'} · 문서 갱신: {'예' if 'research/frontier/FRONTIER.md' in files else '아니오'} · 저장소 반영: {pub.get('status')}"]
        lines += [f"- {x}" for x in log[:5]]
        if reverted:
            lines.append(f"- 경고: 허용 범위 밖 변경 되돌림 {reverted[:3]}")
        notify("\n".join(lines))
    return result


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="알파·프런티어 목표 에이전트 1회 실행")
    ap.add_argument("--gate", help="에이전트 없이 이 폴더의 연구만 관문 검사(올리지 않음)")
    a = ap.parse_args(argv)
    if a.gate:
        job, _files, why = gate(Path(a.gate).resolve())
        print(json.dumps({"ok": job is not None, "reason": why, "job": job}, ensure_ascii=False, indent=2))
        return 0 if job is not None else 1
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass
    claude = os.environ.get("CLAUDE_BIN", "/usr/local/bin/claude")
    if not Path(claude).exists():
        print(f"Claude CLI 없음({claude}) — 건너뜀")
        return 0
    try:
        from core.telegram_notify import send_message
    except Exception:  # noqa: BLE001
        send_message = None
    print(json.dumps(run(notify=send_message), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
