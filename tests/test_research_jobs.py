"""core/research_jobs.py — 검증 연구 작업 실행기. 실제 네트워크·실제 origin push 없이 임시 폴더·임시 git 저장소로만 검증한다."""

from __future__ import annotations

import json
import os
import signal
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

def test_windows_cover_the_day_but_avoid_other_jobs():
    at = lambda h, m: datetime(2026, 10, 20, h, m, tzinfo=rj.KST)  # noqa: E731
    assert rj.window_end_for(at(1, 30)) == at(2, 50)
    assert rj.window_end_for(at(8, 0)) == at(8, 55)
    assert rj.window_end_for(at(10, 0)) == at(11, 55)
    assert rj.window_end_for(at(13, 0)) == at(23, 55)
    assert rj.window_end_for(at(20, 0)) == at(23, 55)
    # 다른 잡이 도는 시각은 모두 창 밖: 야간 블록, 에이전트 배치, paper 주문, 백업, 새벽 미리 계산, 뉴스, 대회·아침 재추천·워치독, 거장 동기화
    for h, m in ((0, 0), (0, 10), (0, 48), (2, 50), (3, 0), (4, 30), (5, 50), (6, 10), (6, 30), (6, 40), (7, 30), (9, 0), (9, 1), (9, 5), (12, 0), (23, 55)):
        assert rj.window_end_for(at(h, m)) is None, (h, m)
    job = SCHEDULED_JOBS_BY_ID["research_job_runner"]
    assert job.cron == rj.CRON and job.process_key == "research_job_runner"
    hours = {int(h) for h in str(job.cron["hour"]).split(",")}
    assert not hours & {0, 3, 4, 5, 6}  # 깨어나는 시각도 에이전트 배치·새벽 구간에는 없다
    assert str(job.cron["minute"]) == "0,10,20,30,40,50"


def test_longest_window_is_the_afternoon_to_night_block():
    assert rj.longest_window_seconds() == 11 * 3600 + 40 * 60


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


def test_only_one_job_runs_per_tick_and_lock_blocks_a_second_runner(cfg, monkeypatch):
    monkeypatch.setenv(rj.MAX_PARALLEL_ENV, "1")  # N=1 은 예전(한 번에 한 작업, runner.lock 하나)과 같아야 한다
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


def test_child_runs_with_research_priority(cfg):
    job = _job(cfg, "nice", "import os\nprint('NICE', os.nice(0))\n")
    outcome = rj.run_child(cfg, job, 30, poll_interval=0.1, system_memory=lambda: None)
    assert "NICE 5" in outcome.log_tail


def test_memory_budget_uses_up_to_80_percent_of_vm_ram(cfg):
    job = _job(cfg, "memory-budget", OK_SCRIPT)
    assert rj._effective_job_memory_limit_mb(job, total_mb=12000, slots=1) == 9600
    assert rj._memory_reserve_mb(total_mb=12000) == 2400


def test_cpu_sampler_calculates_busy_percent(monkeypatch):
    samples = iter([(1000, 200), (1100, 220), (1200, 260)])
    monkeypatch.setattr(rj, "_read_cpu_counters", lambda: next(samples))
    sampler = rj._CpuUsageSampler()
    assert sampler.sample_percent() == 80.0
    assert sampler.sample_percent() == 60.0


def test_high_system_cpu_pauses_then_resumes_research_child(cfg, monkeypatch):
    values = iter([90.0, 90.0, 60.0, 60.0, 60.0])

    class FakeSampler:
        def sample_percent(self):
            return next(values, 60.0)

    monkeypatch.setattr(rj, "_CpuUsageSampler", FakeSampler)
    monkeypatch.setattr(rj.shutil, "which", lambda _name: None)
    forwarded = []
    real_kill_group = rj._kill_group

    def record_throttle(proc, sig):
        forwarded.append(sig)
        if sig not in (signal.SIGSTOP, signal.SIGCONT):
            real_kill_group(proc, sig)

    monkeypatch.setattr(rj, "_kill_group", record_throttle)
    script = "import signal,sys,time\nsignal.signal(signal.SIGTERM, lambda *_: sys.exit(3))\nprint('READY', flush=True)\nwhile True: time.sleep(.02)\n"
    job = _job(cfg, "cpu-throttle", script)
    checks = iter([False, False, False, False, True])
    outcome = rj.run_child(cfg, job, 30, poll_interval=0.05, cancel_check=lambda: next(checks, True), system_memory=lambda: None)
    assert outcome.stopped_by == "cancel"
    assert outcome.exit_code == 3
    assert signal.SIGSTOP in forwarded and signal.SIGCONT in forwarded


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
    # 실제 자동 배포가 이 VM 에서 도는 중이면(/opt/quant-deploy-staging 존재) 잡이 일부러 쉬므로, 그 경로만 '없음'으로 고정한다.
    real_exists = run_scheduler.os.path.exists
    monkeypatch.setattr(run_scheduler.os.path, "exists",
                        lambda p: False if str(p) == "/opt/quant-deploy-staging" else real_exists(p))
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


# ---- 동시 실행(슬롯) — 2026-10-10 ------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [(None, 3), ("1", 1), ("2", 2), ("0", 1), ("9", 4), ("x", 3)])
def test_max_parallel_default_and_clamp(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(rj.MAX_PARALLEL_ENV, raising=False)
    else:
        monkeypatch.setenv(rj.MAX_PARALLEL_ENV, raw)
    assert rj.max_parallel() == expected


def test_two_slots_never_take_the_same_job(cfg, monkeypatch):
    for job_id, prio in (("one", 1), ("two", 2), ("three", 3)):
        add_job(cfg.repo_root, job_id, OK_SCRIPT, priority=prio)
    rec = Recorder(status="skipped")
    seen = []  # (job_id, 그 순간 running 인 작업 → 슬롯)

    def fake_child(cfg_, job, budget, **kw):
        state = rj.load_state(cfg)
        running = {j: e.get("slot") for j, e in state["jobs"].items() if e.get("status") == "running"}
        seen.append((job.id, running))
        if job.id == "one":  # 슬롯 0 이 도는 동안 다음 회차가 겹쳐 들어온다
            inner = tick(cfg, rec, kst(13, 10), slots=2)
            assert inner["job_id"] == "two" and inner["slot"] == 1
        if job.id == "two":  # 두 슬롯이 다 차 있으면 세 번째 회차는 건너뛴다
            assert tick(cfg, rec, kst(13, 10), slots=2)["reason"] == "슬롯 2개가 모두 실행 중"
        return rj.RunOutcome(3, None, 1.0, "")

    monkeypatch.setattr(rj, "run_child", fake_child)
    outer = tick(cfg, rec, kst(13, 0), slots=2)
    assert outer["job_id"] == "one" and outer["slot"] == 0
    assert seen[0] == ("one", {"one": 0})
    assert seen[1] == ("two", {"one": 0, "two": 1})  # 두 번째 슬롯은 이미 running 인 작업을 고르지 않는다
    state = rj.load_state(cfg)
    assert state["jobs"]["one"]["status"] == state["jobs"]["two"]["status"] == "in_progress"
    assert state["jobs"]["three"]["status"] == "pending"
    assert state["jobs"]["one"]["run_token"] is None and state["jobs"]["one"]["interruptions"] == 0


def test_n1_runs_jobs_one_at_a_time(cfg, monkeypatch):
    monkeypatch.setenv(rj.MAX_PARALLEL_ENV, "1")
    add_job(cfg.repo_root, "one", OK_SCRIPT, priority=1)
    add_job(cfg.repo_root, "two", OK_SCRIPT, priority=2)
    rec = Recorder(status="skipped")
    inner_results = []

    def fake_child(cfg_, job, budget, **kw):
        inner_results.append(tick(cfg, rec, kst(13, 10)))
        return rj.RunOutcome(3, None, 1.0, "")

    monkeypatch.setattr(rj, "run_child", fake_child)
    assert tick(cfg, rec, kst(13, 0))["job_id"] == "one"
    assert [r["reason"] for r in inner_results] == ["다른 작업이 실행 중"]
    assert rj.load_state(cfg)["jobs"]["two"]["status"] == "pending"


def _running(state, job_id, slot, token, child_pid=None):
    state["jobs"][job_id].update(status="running", slot=slot, run_token=token, child_pid=child_pid,
                                 last_started_at=rj._now_iso(kst(13, 0)))
    state["runner"].setdefault("slots", {})[str(slot)] = {"token": token, "job_id": job_id}


def test_stale_recovery_skips_jobs_running_in_live_slots(cfg):
    for job_id in ("live", "free-slot", "wrong-token", "dead-child", "mine"):
        add_job(cfg.repo_root, job_id, OK_SCRIPT)
    jobs, _ = rj.load_job_definitions(cfg)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    with rj.edit_state(cfg) as state:
        rj.sync_definitions(cfg, state, jobs, {})
        _running(state, "live", 1, "t-live", child_pid=os.getpid())
        _running(state, "free-slot", 2, "t-free")
        _running(state, "dead-child", 3, "t-dead", child_pid=dead.pid)
        _running(state, "mine", 0, "t-mine")
        state["jobs"]["wrong-token"].update(status="running", slot=1, run_token="old-run")
    state = rj.load_state(cfg)
    with rj._flock(rj.slot_lock_path(cfg, 1), blocking=False) as g1, \
            rj._flock(rj.slot_lock_path(cfg, 3), blocking=False) as g3:
        assert g1 and g3
        recovered = rj.recover_stale(state, jobs, rj.live_run_checker(cfg, state, my_slot=0))
    # 슬롯 1 은 살아 있다(락·토큰·자식 pid) → 그대로. 슬롯 2 는 락이 비었고, 슬롯 3 은 자식이 죽었고,
    # 옛 토큰은 그 슬롯을 다른 실행이 쓰고 있고, 슬롯 0 은 지금 이 회차가 잡은 슬롯이다 → 모두 복구.
    assert sorted(recovered) == ["dead-child", "free-slot", "mine", "wrong-token"]
    assert state["jobs"]["live"]["status"] == "running" and state["jobs"]["live"].get("interruptions", 0) == 0
    assert state["jobs"]["free-slot"]["status"] == "in_progress" and state["jobs"]["free-slot"]["run_token"] is None


def test_interruption_caused_by_a_result_publish_is_not_counted(cfg):
    add_job(cfg.repo_root, "victim", OK_SCRIPT)
    jobs, _ = rj.load_job_definitions(cfg)
    state = rj._empty_state()
    rj.sync_definitions(cfg, state, jobs, {})
    _running(state, "victim", 1, "t")
    state["runner"]["last_publish_at"] = kst(13, 30).isoformat()  # 이 작업이 시작한 뒤 다른 작업이 결과를 push
    assert rj.recover_stale(state, jobs) == ["victim"]
    entry = state["jobs"]["victim"]
    assert entry["interruptions"] == 0 and entry["publish_interruptions"] == 1 and entry["status"] == "in_progress"
    _running(state, "victim", 1, "t2")
    state["jobs"]["victim"]["last_started_at"] = rj._now_iso(kst(14, 0))  # push 뒤에 시작한 실행이 끊기면 센다
    rj.recover_stale(state, jobs)
    assert state["jobs"]["victim"]["interruptions"] == 1


def test_memory_limit_is_divided_by_slots_and_start_gate(cfg):
    job = _job(cfg, "mem-div", OK_SCRIPT)
    assert rj._effective_job_memory_limit_mb(job, total_mb=12000, slots=3) == 3200
    assert rj._effective_job_memory_limit_mb(job, total_mb=12000, slots=4) == 2400
    small = rj.JobDef(**{**job.__dict__, "max_memory_mb": 1000})
    assert rj._effective_job_memory_limit_mb(small, total_mb=12000, slots=3) == 1000
    # 혼자면 예전처럼 20% 예약만, 다른 슬롯이 돌고 있으면 예약 + 이 작업 상한이 남아야 시작
    assert rj.start_memory_ok(job, 3000, 12000, others_running=0, slots=3)[0] is True
    ok, why = rj.start_memory_ok(job, 3000, 12000, others_running=1, slots=3)
    assert ok is False and "2400MB" in why and "3200MB" in why
    assert rj.start_memory_ok(job, 5700, 12000, others_running=2, slots=3)[0] is True
    assert rj.start_memory_ok(job, 2000, 12000, others_running=0, slots=3)[0] is False


def test_tick_does_not_start_a_second_slot_without_memory_for_it(cfg, monkeypatch):
    add_job(cfg.repo_root, "one", OK_SCRIPT, priority=1)
    add_job(cfg.repo_root, "two", OK_SCRIPT, priority=2)
    monkeypatch.setattr(rj, "_system_total_mb", lambda: 12000.0)
    monkeypatch.setattr(rj, "_system_available_mb", lambda: 4000.0)  # 예약 2400 은 되지만 + 3200 은 안 됨
    rec = Recorder(status="skipped")
    inner = []

    def fake_child(cfg_, job, budget, **kw):
        if job.id == "one":
            inner.append(tick(cfg, rec, kst(13, 10), slots=3))
        return rj.RunOutcome(3, None, 1.0, "")

    monkeypatch.setattr(rj, "run_child", fake_child)
    assert tick(cfg, rec, kst(13, 0), slots=3)["job_id"] == "one"
    assert inner[0]["action"] == "skipped" and "연구 메모리 여유 부족" in inner[0]["reason"]
    assert rj.load_state(cfg)["jobs"]["two"]["status"] == "pending"


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_cpu_guard_pauses_lowest_priority_first_and_resumes_in_reverse(cfg):
    clock = FakeClock()
    guards = {name: rj.CpuGuard(cfg.state_dir, name, prio, started, poll_interval=5.0, clock=clock)
              for name, prio, started in (("a", 10, 1.0), ("b", 50, 2.0), ("c", 50, 3.0))}
    paused = {name: False for name in guards}
    for g in guards.values():
        g.pid = os.getpid()  # 살아 있는 pid 로 등록

    def poll(cpu):
        clock.t += 5.0
        acted = []
        for name, g in guards.items():
            action = g.decide(cpu, paused[name])
            if action in ("pause", "resume"):
                paused[name] = action == "pause"
                acted.append((action, name))
        return acted

    assert poll(75.0) == []  # 모두 등록(사이 구간은 그대로)
    assert poll(90.0) == [("pause", "c")]  # 같은 우선순위면 늦게 시작한 쪽, 한 주기에 하나만
    assert poll(90.0) == [("pause", "b")]
    assert poll(75.0) == []
    assert poll(90.0) == [("pause", "a")]
    assert poll(60.0) == [("resume", "a")]  # 재개는 반대 순서: 우선순위가 높은 것부터
    assert poll(60.0) == [("resume", "b")]
    assert poll(60.0) == [("resume", "c")]
    guards["c"].leave()
    assert "c" not in json.loads((cfg.state_dir / "cpu_guard.json").read_text())["children"]


def test_cpu_guard_drops_dead_slots_and_falls_back_when_it_cannot_coordinate(cfg, monkeypatch):
    clock = FakeClock()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    ghost = rj.CpuGuard(cfg.state_dir, "ghost", 999, 9.0, 5.0, clock=clock)
    ghost.pid = dead.pid
    ghost.decide(75.0, False)
    live = rj.CpuGuard(cfg.state_dir, "live", 1, 1.0, 5.0, clock=clock)
    live.pid = os.getpid()
    clock.t += 5
    assert live.decide(90.0, False) == "pause"  # 죽은 슬롯이 '가장 낮은 우선순위'로 남아 차례를 막지 않는다
    monkeypatch.setattr(rj, "CPU_GUARD_LOCK_WAIT_SECONDS", 0.1)
    with rj._flock(cfg.state_dir / "cpu_guard.lock", blocking=False) as got:
        assert got
        assert live.decide(90.0, False) is None  # 조정 불가 → 호출자가 자기 자식만 보고 멈춘다


def test_publish_lock_serializes_concurrent_publishes(cfg):
    import threading
    import time

    active, peak, order = [0], [0], []
    counter = threading.Lock()

    def slow_publish(files, message):
        with counter:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        order.append(("start", message))
        time.sleep(0.2)
        order.append(("end", message))
        with counter:
            active[0] -= 1
        return {"status": "pushed", "detail": "", "sha": "x"}

    publisher = rj.serialized_publisher(cfg, slow_publish)
    threads = [threading.Thread(target=publisher, args=({"a": b"1"}, f"m{i}")) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert peak[0] == 1 and len(order) == 6
    assert all(order[i][0] == "start" and order[i + 1] == ("end", order[i][1]) for i in range(0, 6, 2))


def test_only_one_satellite_or_core_lab_turn_at_a_time(cfg):
    for name, turn in (("satellite-lab", rj._satellite_lab_turn), ("core-lab", rj._core_lab_turn)):
        with rj._flock(cfg.state_dir / f"{name}.lock", blocking=False) as got:
            assert got
            assert turn(cfg, kst(13, 0), kst(23, 55), print, lambda: True, 0.01, slot=1, token="t") is None


def test_revision_change_waits_while_the_job_is_running(cfg):
    add_job(cfg.repo_root, "rev", OK_SCRIPT)
    jobs, _ = rj.load_job_definitions(cfg)
    state = rj._empty_state()
    rj.sync_definitions(cfg, state, jobs, {})
    state["jobs"]["rev"]["status"] = "running"
    cfg.out_dir("rev").mkdir(parents=True)
    add_job(cfg.repo_root, "rev", OK_SCRIPT, revision=2)
    rj.sync_definitions(cfg, state, *rj.load_job_definitions(cfg))
    assert state["jobs"]["rev"]["status"] == "running" and cfg.out_dir("rev").is_dir()  # 다른 슬롯의 작업 폴더를 지우지 않는다


def test_scheduler_allows_n_overlapping_research_ticks(monkeypatch):
    from scheduler import run_scheduler

    monkeypatch.setenv(rj.MAX_PARALLEL_ENV, "2")
    added = []

    class _Fake:
        def add_job(self, func, trigger=None, **kw):
            added.append((kw.get("id"), kw))

        def get_jobs(self):
            return []

        def add_listener(self, *a, **k):
            return None

        def start(self):
            return None

    monkeypatch.setattr(run_scheduler, "BlockingScheduler", lambda *a, **k: _Fake())
    monkeypatch.setattr(run_scheduler, "init_db", lambda: None)
    monkeypatch.setattr(run_scheduler, "attach_job_run_listener", lambda scheduler: None)
    monkeypatch.setattr(run_scheduler, "record_registered_jobs", lambda ids: None)
    run_scheduler.main()
    kw = dict(added)["research_job_runner"]
    assert kw["max_instances"] == 2 and kw["coalesce"] is True


# ---- 미룬 결과 반영(재배포가 도는 연구를 끊지 않게) -----------------------------------------------------------------

def _fake_done(cfg, job):
    out = cfg.out_dir(job.id)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps({"verdicts": {job.id: "PASS"}}))
    (out / "REPORT.md").write_text(f"# {job.id}")
    return rj.RunOutcome(0, None, 1.0, "")


def test_finish_while_other_slot_busy_is_queued_then_combined_into_one_push(cfg, monkeypatch):
    add_job(cfg.repo_root, "long", OK_SCRIPT, priority=1)
    add_job(cfg.repo_root, "short", OK_SCRIPT, priority=2)
    rec = Recorder(status="pushed")
    during = {}

    def fake_child(cfg_, job, budget, **kw):
        if job.id == "long":
            inner = tick(cfg, rec, kst(13, 10), slots=2)
            assert inner["job_id"] == "short" and inner["result"] == "done"
            during["published"] = list(rec.published)
            during["queue"] = rj.load_state(cfg)["runner"].get("publish_queue")
            during["messages"] = list(rec.messages)
        return _fake_done(cfg, job)

    monkeypatch.setattr(rj, "run_child", fake_child)
    assert tick(cfg, rec, kst(13, 0), slots=2)["result"] == "done"
    # short 는 long 이 도는 동안 끝남 → 보관·알림은 바로, push 는 미룸
    assert during["published"] == [] and [i["job_id"] for i in during["queue"]] == ["short"]
    assert "저장소 반영은 다른 연구가 끝난 뒤 함께" in during["messages"][0]
    assert (cfg.results_dir / "short" / "REPORT.md").is_file()
    # long 이 끝날 때 다른 슬롯이 없으니 두 작업 결과를 커밋 하나로
    assert len(rec.published) == 1
    files, message = rec.published[0]
    assert set(files) == {f"research/results/{j}/{f}" for j in ("short", "long") for f in ("results.json", "REPORT.md")}
    assert "short" in message and "long" in message
    state = rj.load_state(cfg)
    assert state["runner"]["publish_queue"] == [] and state["jobs"]["short"]["publish"]["status"] == "pushed"
    assert state["runner"].get("cooldown_until")


def test_idle_tick_flushes_queue_in_one_push(cfg, monkeypatch):
    add_job(cfg.repo_root, "a", OK_SCRIPT, priority=1)
    add_job(cfg.repo_root, "b", OK_SCRIPT, priority=2)
    add_job(cfg.repo_root, "c", OK_SCRIPT, priority=3)
    rec = Recorder(status="pushed")

    def fake_child(cfg_, job, budget, **kw):
        if job.id == "a":
            tick(cfg, rec, kst(13, 10), slots=2)  # b 끝남(a 가 돌고 있어 미룸)
            tick(cfg, rec, kst(13, 15), slots=2)  # c 끝남(미룸)
            return rj.RunOutcome(3, None, 1.0, "")  # a 는 진행 중(3)으로 끝 — 직접 push 할 것이 없다
        return _fake_done(cfg, job)

    monkeypatch.setattr(rj, "run_child", fake_child)
    tick(cfg, rec, kst(13, 0), slots=2)
    assert rec.published == [] and [i["job_id"] for i in rj.load_state(cfg)["runner"]["publish_queue"]] == ["b", "c"]
    # 다른 슬롯이 모두 쉬는 다음 회차: 큐를 커밋 하나로 push 하고 재배포 대기
    result = tick(cfg, rec, kst(13, 20), slots=2)
    assert result["reason"] == "결과 반영 직후 재배포 대기"
    assert len(rec.published) == 1 and {p.split("/")[2] for p in rec.published[0][0]} == {"b", "c"}
    assert rj.load_state(cfg)["runner"]["publish_queue"] == []
    assert any("미뤄 둔 저장소 반영 완료: b, c" in m for m in rec.messages)


def _seed_queue(cfg, job_id, queued_at):
    d = cfg.results_dir / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text("{}")
    with rj.edit_state(cfg) as state:
        state["runner"]["publish_queue"] = [{"job_id": job_id, "rels": ["results.json"], "queued_at": rj._now_iso(queued_at)}]


def test_queue_safety_valve_pushes_after_12_hours_even_if_another_slot_is_busy(cfg):
    rec = Recorder(status="pushed")
    with rj.edit_state(cfg) as state:
        state["runner"]["slots"] = {"1": {"token": "t", "job_id": "other"}}
    with rj._flock(rj.slot_lock_path(cfg, 1), blocking=False) as got:
        assert got
        _seed_queue(cfg, "old", kst(13, 0) - timedelta(hours=11))
        tick(cfg, rec, kst(13, 0), slots=2)
        assert rec.published == []  # 11시간: 다른 슬롯이 돌고 있으니 기다린다
        _seed_queue(cfg, "old", kst(13, 0) - timedelta(hours=12, minutes=5))
        assert tick(cfg, rec, kst(13, 0), slots=2)["reason"] == "결과 반영 직후 재배포 대기"
    assert list(rec.published[0][0]) == ["research/results/old/results.json"]
    assert rj.load_state(cfg)["runner"]["publish_queue"] == []


def test_failed_flush_stays_queued_and_is_retried(cfg):
    rec = Recorder(status="failed")
    _seed_queue(cfg, "q", kst(13, 0))
    tick(cfg, rec, kst(13, 0), slots=2)
    tick(cfg, rec, kst(13, 10), slots=2)
    assert len(rec.published) == 2 and len(rj.load_state(cfg)["runner"]["publish_queue"]) == 1
    assert sum("미뤄 둔 저장소 반영 실패" in m for m in rec.messages) == 1  # 같은 사유는 한 번만 알린다
    rec.status = "pushed"
    tick(cfg, rec, kst(13, 20), slots=2)
    assert len(rec.published) == 3 and rj.load_state(cfg)["runner"]["publish_queue"] == []


def test_n1_never_queues_publishes(cfg, monkeypatch):
    monkeypatch.setenv(rj.MAX_PARALLEL_ENV, "1")
    add_job(cfg.repo_root, "solo", OK_SCRIPT)
    rec = Recorder(status="pushed")
    assert tick(cfg, rec, kst(13, 0))["result"] == "done"
    assert len(rec.published) == 1 and rec.published[0][1].startswith("Research job results: solo")
    assert not rj.load_state(cfg)["runner"].get("publish_queue")
    assert "다른 연구가 끝난 뒤" not in rec.messages[0]
