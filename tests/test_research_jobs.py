"""core/research_jobs.py — 검증 연구 작업 실행기. 실제 네트워크·실제 origin push 없이 임시 폴더·임시 git 저장소로만 검증한다."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core import research_jobs as rj
from core.job_schedule import SCHEDULED_JOBS_BY_ID
from core.process_registry import PROCESS_REGISTRY

ROOT = Path(__file__).resolve().parent.parent
KST = rj.KST
SMOKE_SRC = ROOT / "research" / "jobs" / "smoke-noop"


def kst(hour, minute=0, day=27):
    return datetime(2026, 9, day, hour, minute, tzinfo=KST)


def _job_json(job_id, **over):
    data = {"id": job_id, "title": f"작업 {job_id}", "entrypoint": f"research/jobs/{job_id}/run.py", "args": [],
            "timeout_seconds": 600, "max_attempts": 3, "resumable": True, "outputs": ["results.json", "REPORT.md"],
            "summary_from": "verdicts", "priority": 10}
    data.update(over)
    return data


def add_job(root: Path, job_id: str, script: str, **over) -> Path:
    folder = root / "research" / "jobs" / job_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.py").write_text(script)
    (folder / "job.json").write_text(json.dumps(_job_json(job_id, **over), ensure_ascii=False))
    return folder


def add_smoke(root: Path) -> None:
    dest = root / "research" / "jobs" / "smoke-noop"
    shutil.copytree(SMOKE_SRC, dest)


OK_SCRIPT = """
import argparse, json, pathlib, sys
p = argparse.ArgumentParser(); p.add_argument('--out'); p.add_argument('--checkpoint'); a = p.parse_args()
o = pathlib.Path(a.out); o.mkdir(parents=True, exist_ok=True)
(o / 'results.json').write_text(json.dumps({'verdicts': {'H1': 'PASS'}}))
(o / 'REPORT.md').write_text('# ok')
sys.exit(0)
"""
FAIL_SCRIPT = "import sys\nprint('ValueError: 데이터 없음')\nsys.exit(1)\n"


@pytest.fixture()
def cfg(tmp_path):
    return rj.Config.for_root(tmp_path)


class Recorder:
    def __init__(self, status="pushed"):
        self.messages, self.published, self.status = [], [], status

    def notify(self, text):
        self.messages.append(text)

    def publish(self, files, message):
        self.published.append((dict(files), message))
        return {"status": self.status, "detail": "abc..def", "sha": "def"}


def tick(cfg, rec, when, **kw):
    kw.setdefault("headroom", lambda: True)
    kw.setdefault("poll_interval", 0.05)
    return rj.run_tick(when, notify=rec.notify, publish=rec.publish, cfg=cfg, **kw)


# ---- 계약 검증 ----------------------------------------------------------------------------------------------

def test_valid_job_definition_is_accepted(tmp_path):
    add_job(tmp_path, "good", OK_SCRIPT)
    job, reason = rj.validate_job(_job_json("good"), "good", tmp_path)
    assert reason == "" and job.id == "good" and job.priority == 10 and job.revision == "1"


@pytest.mark.parametrize("change,needle", [
    ({"title": ""}, "title"),
    ({"id": "Bad Id"}, "id"),
    ({"id": "other"}, "폴더 이름"),
    ({"entrypoint": "../evil.py"}, "entrypoint"),
    ({"entrypoint": "research/jobs/good/none.py"}, "파일이 없습니다"),
    ({"args": ["--out", "x"]}, "--out"),
    ({"args": "x"}, "args"),
    ({"timeout_seconds": 10}, "timeout_seconds"),
    ({"max_attempts": 0}, "max_attempts"),
    ({"resumable": "yes"}, "resumable"),
    ({"outputs": []}, "outputs"),
    ({"outputs": ["/etc/passwd"]}, "outputs"),
    ({"summary_from": "other.json:verdicts"}, "summary_from"),
    ({"priority": True}, "priority"),
])
def test_invalid_job_definitions_are_rejected(tmp_path, change, needle):
    add_job(tmp_path, "good", OK_SCRIPT)
    job, reason = rj.validate_job(_job_json("good", **change), "good", tmp_path)
    assert job is None and needle in reason


def test_oneshot_job_longer_than_every_window_is_rejected(tmp_path, monkeypatch):
    from datetime import time
    monkeypatch.setattr(rj, "RUN_WINDOWS", ((time(1, 0), time(2, 50)),))
    add_job(tmp_path, "good", OK_SCRIPT)
    job, reason = rj.validate_job(_job_json("good", resumable=False, timeout_seconds=2 * 3600), "good", tmp_path)
    assert job is None and "재개 불가" in reason


def test_missing_field_and_broken_json_are_invalid(cfg):
    folder = add_job(cfg.repo_root, "broken", OK_SCRIPT)
    (folder / "job.json").write_text("{not json")
    data = _job_json("nofield")
    data.pop("priority")
    add_job(cfg.repo_root, "nofield", OK_SCRIPT)
    (cfg.jobs_dir / "nofield" / "job.json").write_text(json.dumps(data))
    valid, invalid = rj.load_job_definitions(cfg)
    assert valid == {} and "broken" in invalid and "priority" in invalid["nofield"]


def test_invalid_job_is_notified_once(cfg):
    folder = add_job(cfg.repo_root, "bad", OK_SCRIPT, timeout_seconds=1)
    rec = Recorder()
    tick(cfg, rec, kst(1, 0))
    tick(cfg, rec, kst(1, 20))
    assert len(rec.messages) == 1 and "작업 정의 오류: bad" in rec.messages[0]
    assert rj.load_state(cfg)["jobs"]["bad"]["status"] == "invalid"
    (folder / "job.json").write_text(json.dumps(_job_json("bad")))  # 고치면 대기로 돌아온다
    rj.sync_definitions(cfg, state := rj.load_state(cfg), *rj.load_job_definitions(cfg))
    assert state["jobs"]["bad"]["status"] == "pending"


# ---- 창·예산·선택 ----------------------------------------------------------------------------------------------

def test_windows_avoid_the_agent_batch_and_other_slots():
    assert rj.window_end_for(kst(1, 30)) == kst(2, 50)
    assert rj.window_end_for(kst(13, 0)) == kst(16, 50)
    for hour in (0, 3, 4, 5, 6, 7, 9, 12, 17, 23):
        assert rj.window_end_for(kst(hour, 10)) is None, hour
    assert rj.window_end_for(kst(2, 50)) is None
    job = SCHEDULED_JOBS_BY_ID["research_job_runner"]
    assert job.cron == rj.CRON and job.process_key == "research_job_runner"
    hours = {int(h) for h in str(job.cron["hour"]).split(",")}
    assert not hours & {0, 3, 4, 5, 6, 7, 9, 12}


def test_registered_in_process_registry_as_research_default_on():
    entry = PROCESS_REGISTRY["research_job_runner"]
    assert entry["category"] == "research" and entry["default_enabled"] is True and not entry.get("places_orders")


def test_budget_is_shortened_by_the_remaining_window(tmp_path):
    add_job(tmp_path, "good", OK_SCRIPT, timeout_seconds=3600)
    job, _ = rj.validate_job(_job_json("good", timeout_seconds=3600), "good", tmp_path)
    budget, shortened = rj.budget_for(job, kst(2, 20), kst(2, 50))
    assert budget == 30 * 60 - rj.END_MARGIN_SECONDS and shortened
    budget, shortened = rj.budget_for(job, kst(13, 0), kst(16, 50))
    assert budget == 3600 and not shortened


def test_pick_job_orders_by_priority_and_respects_resumability(cfg):
    add_job(cfg.repo_root, "b-late", OK_SCRIPT, priority=5)
    add_job(cfg.repo_root, "a-first", OK_SCRIPT, priority=1, resumable=False, timeout_seconds=3600)
    add_job(cfg.repo_root, "c-done", OK_SCRIPT, priority=0)
    jobs, _ = rj.load_job_definitions(cfg)
    state = rj._empty_state()
    rj.sync_definitions(cfg, state, jobs, {})
    state["jobs"]["c-done"]["status"] = "done"
    job, _, _ = rj.pick_job(state, jobs, kst(13, 0), kst(16, 50))
    assert job.id == "a-first"
    # 01:20 에는 재개 불가 1시간 작업을 끝낼 시간이 없다 → 다음 우선순위
    job, _, shortened = rj.pick_job(state, jobs, kst(2, 20), kst(2, 50))
    assert job.id == "b-late" and not shortened
    assert rj.pick_job(state, jobs, kst(2, 44), kst(2, 50))[0] is None  # 5분 미만 남음


# ---- 실행 끝까지 ---------------------------------------------------------------------------------------------

def test_smoke_job_finishes_over_two_checkpointed_runs(cfg):
    add_smoke(cfg.repo_root)
    rec = Recorder()
    first = tick(cfg, rec, kst(1, 0))
    assert first["action"] == "ran" and first["result"] == "in_progress" and first["exit_code"] == 3
    state = rj.load_state(cfg)["jobs"]["smoke-noop"]
    assert state["status"] == "in_progress" and state["failures"] == 0 and state["runs"] == 1
    assert rec.messages == []  # 진행 중은 알리지 않는다

    second = tick(cfg, rec, kst(1, 20))
    assert second["result"] == "done" and second["exit_code"] == 0
    state = rj.load_state(cfg)["jobs"]["smoke-noop"]
    assert state["status"] == "done" and state["runs"] == 2 and state["last_duration_seconds"] is not None
    stored = cfg.results_dir / "smoke-noop"
    assert json.loads((stored / "results.json").read_text())["verdicts"] == {"runner_contract": "PASS"}
    assert not cfg.work_dir("smoke-noop").exists()  # 완료되면 작업 폴더 정리

    assert len(rec.messages) == 1
    msg = rec.messages[0]
    assert "[검증 연구 결과] 실행기 스모크(계산 없음) — 완료" in msg and "runner_contract: PASS" in msg
    assert "research/results/smoke-noop/" in msg and "검증 연구 결과" in msg
    files, message = rec.published[0]
    assert set(files) == {"research/results/smoke-noop/results.json", "research/results/smoke-noop/REPORT.md"}
    assert message.startswith("Research job results: smoke-noop")

    index = (cfg.results_dir / "index.html").read_text()
    assert "실행기 스모크" in index and "runner_contract = PASS" in index and "완료" in index

    # push 직후에는 자동 배포 재시작을 기다린다
    assert tick(cfg, rec, kst(1, 25))["reason"] == "결과 반영 직후 재배포 대기"
    assert tick(cfg, rec, kst(1, 40))["action"] == "idle"


def test_only_one_job_runs_per_tick_and_lock_blocks_a_second_runner(cfg):
    add_job(cfg.repo_root, "one", OK_SCRIPT, priority=1)
    add_job(cfg.repo_root, "two", OK_SCRIPT, priority=2)
    rec = Recorder(status="skipped")
    result = tick(cfg, rec, kst(13, 0))
    assert result["job_id"] == "one"
    assert rj.load_state(cfg)["jobs"]["two"]["status"] == "pending"
    with rj._flock(cfg.state_dir / "runner.lock", blocking=False) as got:
        assert got
        assert tick(cfg, rec, kst(13, 20))["reason"] == "다른 작업이 실행 중"
    assert tick(cfg, rec, kst(13, 40))["job_id"] == "two"


def test_outside_window_and_no_headroom_skip_without_running(cfg):
    add_job(cfg.repo_root, "one", OK_SCRIPT)
    rec = Recorder()
    assert tick(cfg, rec, kst(3, 0))["reason"] == "실행 창 밖"
    assert tick(cfg, rec, kst(1, 0), headroom=lambda: False)["reason"].startswith("VM 여유 없음")
    assert rj.load_state(cfg)["jobs"]["one"]["status"] == "pending" and rec.messages == []


def test_failures_retry_and_repeated_alerts_are_suppressed(cfg):
    add_job(cfg.repo_root, "bad", FAIL_SCRIPT, max_attempts=3, resumable=False)
    rec = Recorder()
    for minute in (0, 20):
        assert tick(cfg, rec, kst(13, minute))["result"] == "retry"
    assert len(rec.messages) == 1 and "실패 1/3회" in rec.messages[0] and "종료 코드 1: ValueError: 데이터 없음" in rec.messages[0]
    assert tick(cfg, rec, kst(13, 40))["result"] == "failed"
    assert len(rec.messages) == 2 and "재시도 중단" in rec.messages[1]
    state = rj.load_state(cfg)["jobs"]["bad"]
    assert state["status"] == "failed" and state["failures"] == 3 and "ValueError" in state["log_tail"]
    assert tick(cfg, rec, kst(14, 0))["action"] == "idle"


def test_missing_outputs_count_as_failure(cfg):
    add_job(cfg.repo_root, "noout", "import sys\nsys.exit(0)\n", max_attempts=1)
    rec = Recorder()
    assert tick(cfg, rec, kst(13, 0))["result"] == "failed"
    assert "출력 누락: results.json, REPORT.md" in rec.messages[0]


def test_stale_running_is_recovered(cfg):
    add_job(cfg.repo_root, "resumable", OK_SCRIPT)
    add_job(cfg.repo_root, "oneshot", OK_SCRIPT, resumable=False)
    jobs, _ = rj.load_job_definitions(cfg)
    with rj.edit_state(cfg) as state:
        rj.sync_definitions(cfg, state, jobs, {})
        for entry in state["jobs"].values():
            entry.update(status="running", pid=999999)
    recovered = rj.recover_stale(state := rj.load_state(cfg), jobs)
    assert sorted(recovered) == ["oneshot", "resumable"]
    assert state["jobs"]["resumable"]["status"] == "in_progress" and state["jobs"]["oneshot"]["status"] == "pending"
    assert state["jobs"]["resumable"]["interruptions"] == 1
    state["jobs"]["resumable"].update(status="running", interruptions=rj.MAX_INTERRUPTIONS)
    rj.recover_stale(state, jobs)
    assert state["jobs"]["resumable"]["status"] == "failed"


def test_tick_recovers_running_left_by_a_dead_process(cfg):
    add_job(cfg.repo_root, "one", OK_SCRIPT, priority=1)
    jobs, _ = rj.load_job_definitions(cfg)
    with rj.edit_state(cfg) as state:
        rj.sync_definitions(cfg, state, jobs, {})
        state["jobs"]["one"]["status"] = "running"
    result = tick(cfg, Recorder(status="skipped"), kst(13, 0))
    assert result["recovered"] == ["one"] and result["result"] == "done"


# ---- 시간 예산·중단 ------------------------------------------------------------------------------------------

SLEEP_SCRIPT = "import time\ntime.sleep(30)\n"
GRACEFUL_SCRIPT = """
import signal, sys, time
signal.signal(signal.SIGTERM, lambda *a: sys.exit(3))
time.sleep(30)
"""


def _job(cfg, job_id, script, **over):
    add_job(cfg.repo_root, job_id, script, **over)
    return rj.load_job_definitions(cfg)[0][job_id]


def test_budget_overrun_is_terminated(cfg, monkeypatch):
    monkeypatch.setattr(rj, "TERM_GRACE_SECONDS", 1)
    job = _job(cfg, "slow", SLEEP_SCRIPT)
    outcome = rj.run_child(cfg, job, 1, poll_interval=0.1, system_memory=lambda: None)
    assert outcome.stopped_by == "budget" and outcome.exit_code not in (0, 3) and outcome.duration < 10


def test_graceful_stop_with_exit_3_is_progress(cfg):
    job = _job(cfg, "graceful", GRACEFUL_SCRIPT)
    outcome = rj.run_child(cfg, job, 1, poll_interval=0.1, system_memory=lambda: None)
    assert outcome.exit_code == 3
    entry = rj._new_entry(job)
    assert rj.apply_outcome(cfg, job, entry, outcome, True, print, Recorder().publish, kst(1, 0), {}) == "in_progress"
    assert entry["failures"] == 0


def test_window_cut_is_progress_only_for_resumable_jobs(cfg):
    job = _job(cfg, "cut", SLEEP_SCRIPT)
    killed = rj.RunOutcome(exit_code=-9, stopped_by="budget", duration=5, log_tail="")
    entry = rj._new_entry(job)
    assert rj.apply_outcome(cfg, job, entry, killed, True, print, Recorder().publish, kst(1, 0), {}) == "in_progress"
    entry = rj._new_entry(job)
    assert rj.apply_outcome(cfg, job, entry, killed, False, print, Recorder().publish, kst(1, 0), {}) == "retry"
    assert entry["last_reason"] == "시간 예산 초과"
    entry = rj._new_entry(job)
    yielded = rj.RunOutcome(exit_code=-15, stopped_by="system_memory", duration=5, log_tail="")
    assert rj.apply_outcome(cfg, job, entry, yielded, False, print, Recorder().publish, kst(1, 0), {}) == "yielded"
    assert entry["failures"] == 0


def test_system_memory_pressure_stops_the_child(cfg):
    job = _job(cfg, "mem", SLEEP_SCRIPT)
    outcome = rj.run_child(cfg, job, 60, poll_interval=0.1, system_memory=lambda: 100.0)
    assert outcome.stopped_by == "system_memory"


def test_cancel_request_stops_a_running_child_and_admin_cancel(cfg):
    job = _job(cfg, "cancel-me", SLEEP_SCRIPT)
    outcome = rj.run_child(cfg, job, 60, poll_interval=0.1, cancel_check=lambda: True, system_memory=lambda: None)
    assert outcome.stopped_by == "cancel"
    entry = rj._new_entry(job)
    assert rj.apply_outcome(cfg, job, entry, outcome, False, print, Recorder().publish, kst(1, 0), {}) == "cancelled"


def test_child_runs_with_low_priority(cfg):
    job = _job(cfg, "nice", "import os\nprint('NICE', os.nice(0))\n")
    outcome = rj.run_child(cfg, job, 30, poll_interval=0.1, system_memory=lambda: None)
    assert "NICE 19" in outcome.log_tail


def test_child_gets_contract_arguments_and_budget_env(cfg):
    script = "import os, sys\nprint('ARGS', sys.argv[1:])\nprint('BUDGET', os.environ['RESEARCH_JOB_TIME_BUDGET_SECONDS'])\n"
    job = _job(cfg, "argv", script, args=["--period", "2010-2020"])
    outcome = rj.run_child(cfg, job, 42, poll_interval=0.1, system_memory=lambda: None)
    assert "'--period', '2010-2020', '--out'" in outcome.log_tail and "'--checkpoint'" in outcome.log_tail
    assert "BUDGET 42" in outcome.log_tail


# ---- 요약·민감값·색인 -----------------------------------------------------------------------------------------

def test_summary_is_short_and_secrets_are_masked(cfg, monkeypatch):
    fake_token = "ghp_" + "a" * 36
    monkeypatch.setenv("SOME_API_KEY", "supersecretvalue123")
    job = _job(cfg, "sum", OK_SCRIPT)
    result_dir = cfg.results_dir / "sum"
    result_dir.mkdir(parents=True)
    verdicts = {f"H{i}": "PASS" for i in range(12)}
    verdicts["H0"] = f"leak {fake_token} supersecretvalue123"
    (result_dir / "results.json").write_text(json.dumps({"verdicts": verdicts}))
    summary = rj.extract_summary(job, result_dir)
    assert fake_token not in summary and "supersecretvalue123" not in summary and "[가림]" in summary
    assert summary.count("\n") <= 8 and "외 4개" in summary
    assert "***@" in rj.redact("https://user:tok@github.com/x.git")


def test_publishable_files_respect_size_extension_and_secret_rules(cfg):
    job = _job(cfg, "pub", OK_SCRIPT, outputs=["results.json", "REPORT.md", "big.csv", "plot.png", "leak.txt"])
    d = cfg.results_dir / "pub"
    d.mkdir(parents=True)
    (d / "results.json").write_text("{}")
    (d / "REPORT.md").write_text("# r")
    (d / "big.csv").write_text("x" * (rj.PUBLISH_MAX_FILE_BYTES + 1))
    (d / "plot.png").write_bytes(b"\x89PNG")
    (d / "leak.txt").write_text("sk-ant-" + "b" * 30)
    files, skipped = rj.collect_publishable(cfg, job, d)
    assert set(files) == {"research/results/pub/results.json", "research/results/pub/REPORT.md"}
    assert len(skipped) == 3


def test_markdown_render_escapes_html():
    out = rj.markdown_to_html("# 제목\n\n<script>x</script> **굵게**\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- 하나\n```\n<b>\n```")
    assert "<script>" not in out and "&lt;script&gt;" in out and "<h2>제목</h2>" in out
    assert "<table>" in out and "<td>1</td>" in out and "<li>하나</li>" in out and "<pre>&lt;b&gt;</pre>" in out


def test_revision_change_restarts_the_job(cfg):
    add_job(cfg.repo_root, "rev", OK_SCRIPT)
    tick(cfg, Recorder(status="skipped"), kst(13, 0))
    assert rj.load_state(cfg)["jobs"]["rev"]["status"] == "done"
    add_job(cfg.repo_root, "rev", OK_SCRIPT, revision=2)
    state = rj.load_state(cfg)
    rj.sync_definitions(cfg, state, *rj.load_job_definitions(cfg))
    assert state["jobs"]["rev"]["status"] == "pending" and state["jobs"]["rev"]["revision"] == "2"


# ---- 관리 CLI ---------------------------------------------------------------------------------------------

def test_admin_cli_list_retry_cancel(cfg, capsys):
    from scripts import research_jobs_admin as admin

    add_job(cfg.repo_root, "bad", FAIL_SCRIPT, max_attempts=1)
    tick(cfg, Recorder(), kst(13, 0))
    assert admin.main(["list"], cfg=cfg) == 0
    assert "bad" in capsys.readouterr().out
    assert admin.main(["retry", "bad", "--fresh"], cfg=cfg) == 0
    state = rj.load_state(cfg)["jobs"]["bad"]
    assert state["status"] == "pending" and state["failures"] == 0
    assert admin.main(["cancel", "bad"], cfg=cfg) == 0
    assert rj.load_state(cfg)["jobs"]["bad"]["status"] == "cancelled"
    assert admin.main(["retry", "nope"], cfg=cfg) == 2
    with rj.edit_state(cfg) as st:
        st["jobs"]["bad"]["status"] = "running"
    admin.main(["cancel", "bad"], cfg=cfg)
    assert rj.load_state(cfg)["jobs"]["bad"]["cancel_requested"] is True


# ---- 저장소 반영(임시 bare 저장소) --------------------------------------------------------------------------------

GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@localhost", "-c", "commit.gpgsign=false"]


def git(cwd, *args, check=True):
    return subprocess.run(["git", *GIT_ID, "-C", str(cwd), *args], capture_output=True, text=True, check=check)


@pytest.fixture()
def repos(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
    (seed / "PROGRESS.md").write_text("start\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "init")
    git(seed, "push", "-q", "origin", "HEAD:main")
    vm = tmp_path / "vm"
    subprocess.run(["git", "clone", "-q", str(origin), str(vm)], check=True, capture_output=True)
    return origin, seed, vm


def _snapshot(vm):
    return git(vm, "rev-parse", "HEAD").stdout, git(vm, "status", "--porcelain").stdout, git(vm, "diff", "--cached").stdout


def test_publish_adds_one_commit_on_origin_main_without_touching_the_worktree(repos, tmp_path):
    origin, _seed, vm = repos
    (vm / "PROGRESS.md").write_text("local uncommitted edit\n")
    (vm / "scratch.txt").write_text("untracked\n")
    before = _snapshot(vm)
    files = {"research/results/j/results.json": b'{"verdicts": {}}', "research/results/j/REPORT.md": "# 결과".encode()}
    result = rj.publish_files(vm, files, "Research job results: j", index_dir=tmp_path / "idx")
    assert result["status"] == "pushed"
    assert _snapshot(vm) == before  # 작업트리·HEAD·인덱스 그대로
    assert (vm / "PROGRESS.md").read_text() == "local uncommitted edit\n"
    shown = subprocess.run(["git", "-C", str(origin), "show", "main:research/results/j/REPORT.md"], capture_output=True, text=True)
    assert shown.stdout == "# 결과"
    log = subprocess.run(["git", "-C", str(origin), "log", "--format=%s|%an", "main"], capture_output=True, text=True).stdout
    assert log.splitlines()[0] == "Research job results: j|quant-research-runner" and len(log.splitlines()) == 2
    # 같은 내용을 다시 올리면 빈 커밋을 만들지 않는다
    assert rj.publish_files(vm, files, "again", index_dir=tmp_path / "idx")["status"] == "skipped"


def test_publish_retries_when_origin_moved_in_between(repos, tmp_path):
    origin, seed, vm = repos
    flag = tmp_path / "raced"
    hook = vm / ".git" / "hooks" / "pre-push"
    # 첫 push 직전에 다른 곳에서 main 을 한 칸 앞으로 민다 → 우리 push 는 non-fast-forward 로 거절 → 다시 fetch 해서 성공해야 한다
    hook.write_text(f"""#!/bin/sh
if [ ! -f "{flag}" ]; then
  touch "{flag}"
  cd "{seed}" && echo other >> PROGRESS.md && git -c user.name=o -c user.email=o@l add -A && \
  git -c user.name=o -c user.email=o@l -c commit.gpgsign=false commit -qm other && git push -q origin HEAD:main
fi
exit 0
""")
    hook.chmod(0o755)
    result = rj.publish_files(vm, {"research/results/j/r.json": b"{}"}, "Research job results: j", index_dir=tmp_path / "idx")
    assert result["status"] == "pushed" and flag.exists()
    log = subprocess.run(["git", "-C", str(origin), "log", "--format=%s", "main"], capture_output=True, text=True).stdout.splitlines()
    assert log[:2] == ["Research job results: j", "other"]  # 남의 커밋을 덮어쓰지 않고 그 위에 얹었다


def test_publish_detects_missing_push_credentials(repos, tmp_path):
    origin, _seed, vm = repos
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'ERROR: Permission to owner/repo.git denied to deploy key' >&2\nexit 1\n")
    hook.chmod(0o755)
    result = rj.publish_files(vm, {"research/results/j/r.json": b"{}"}, "m", index_dir=tmp_path / "idx")
    assert result["status"] == "no-credentials"


def test_no_credentials_is_written_in_the_alert(cfg):
    add_job(cfg.repo_root, "nocred", OK_SCRIPT)
    rec = Recorder(status="no-credentials")
    tick(cfg, rec, kst(13, 0))
    assert "push 권한이 없어 저장소 반영은 건너뜀" in rec.messages[0]
    assert tick(cfg, rec, kst(13, 20))["action"] == "idle"  # 반영을 안 했으니 재배포 대기도 없다


def test_default_publisher_never_pushes_under_pytest(cfg):
    assert rj.default_publisher(cfg)({"a": b"b"}, "m")["status"] == "skipped"


# ---- 스케줄러 잡 ------------------------------------------------------------------------------------------------

def test_scheduler_job_respects_toggle_and_reports_exceptions(monkeypatch, tmp_path):
    from core import process_registry
    from scheduler import run_scheduler

    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", tmp_path / "toggles.json")
    calls, failures = [], []
    monkeypatch.setattr(rj, "run_tick", lambda **kw: calls.append(kw) or {"action": "idle"})
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda job_id, err: failures.append((job_id, err)))

    process_registry.set_enabled("research_job_runner", False)
    run_scheduler.research_job_runner_job()
    assert calls == []

    process_registry.set_enabled("research_job_runner", True)
    run_scheduler.research_job_runner_job()
    assert len(calls) == 1 and failures == []

    def boom(**kw):
        raise RuntimeError("state broken")

    monkeypatch.setattr(rj, "run_tick", boom)
    run_scheduler.research_job_runner_job()
    assert failures == [("research_job_runner", "RuntimeError: state broken")]


def test_hub_report_slot_points_at_the_index(cfg):
    from hub.apps_registry import SLOTS

    slot = next(s for s in SLOTS if s.id == "report-research-results")
    assert slot.kind == "report" and slot.report_glob == "data/research_results/index.html"
    assert "data/research_results/" in (ROOT / ".gitignore").read_text()
