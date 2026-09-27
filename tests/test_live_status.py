"""관제 센터 '지금 돌고 있는 작업'(/live) — 실행 중 잡 표시·텔레그램 큐·프로세스 설명·비밀값 가림."""

import getpass
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core import job_health
from hub import live_status as ls


@pytest.fixture()
def running_path(tmp_path, monkeypatch):
    monkeypatch.setattr(job_health, "RUNNING_JOBS_PATH", tmp_path / "running.json")
    return tmp_path / "running.json"


def test_listener_marks_started_and_finished(running_path):
    from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_SUBMITTED

    class Ev:
        def __init__(self, code):
            self.code, self.job_id, self.exception, self.scheduled_run_time = code, "agent_batch", None, None

    job_health.job_run_listener(Ev(EVENT_JOB_SUBMITTED))
    assert list(job_health.read_running_jobs()) == ["agent_batch"]
    job_health.mark_job_finished("agent_batch")  # EXECUTED 경로의 표시 제거(DB 기록은 별도 테스트가 다룸)
    assert job_health.read_running_jobs() == {}


def test_stale_marker_from_dead_scheduler_is_ignored(running_path):
    running_path.write_text(json.dumps({"x": {"started_at": "2026-09-27T00:00:00+00:00", "pid": 999999999}}))
    assert job_health.read_running_jobs() == {}


def test_running_jobs_have_label_and_elapsed(running_path):
    started = datetime.now(timezone.utc) - timedelta(minutes=12)
    running_path.write_text(json.dumps({"agent_batch": {"started_at": started.isoformat(), "pid": os.getpid()}}))
    rows = ls.running_scheduler_jobs()
    assert rows[0]["label"] == "AI 에이전트 야간 배치" and 700 < rows[0]["elapsed"] < 740


def test_telegram_queue_reads_active_jobs_and_redacts(tmp_path):
    db = tmp_path / "queue.sqlite"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, project TEXT, instruction TEXT, status TEXT, attempts INT, backend TEXT)")
        c.executemany("INSERT INTO jobs VALUES(?,?,?,?,?,?)", [
            (1, "quant", "차트 고쳐줘 token=abc123", "running", 1, "claude"),
            (2, "quant", "끝난 일", "done", 1, "claude"),
            (3, "quant", "다음 일", "queued", 0, "codex")])
    rows = ls.telegram_jobs(db)
    assert [r["id"] for r in rows] == [1, 3]
    assert "abc123" not in rows[0]["instruction"] and "token=***" in rows[0]["instruction"]
    assert ls.telegram_jobs(tmp_path / "none.sqlite") is None


@pytest.mark.parametrize("cmd, expect", [
    ("/opt/quant/.venv/bin/python /opt/quant/scripts/agent_batch.py", "AI 에이전트 야간 배치"),
    ("/usr/local/bin/claude -p --output-format json --model opus --max-turns 25", "Claude 에이전트 실행 중 (모델 opus)"),
    ("/opt/quant/.venv/bin/python -m hub.server", "관제 허브 서버"),
    ("/opt/quant/.venv/bin/python scheduler/run_scheduler.py", "스케줄러 본체"),
    ("/usr/bin/python3 /opt/quant/deploy/codex_telegram/runner.py --config x", "텔레그램 러너"),
    ("/opt/quant/.venv/bin/python -m pytest /opt/quant/tests -q", "테스트 실행"),
    ("python scripts/news_event_study.py AAPL", "스크립트 news_event_study"),
])
def test_classify(cmd, expect):
    assert ls.classify(cmd).startswith(expect)


def test_redact_hides_tokens_and_long_secrets():
    s = ls.redact("gh --token ghp_ABCDEF1234567890 x --password hunter2 " + "A" * 48 + " sk-ant-xyz")
    assert "ghp_ABCDEF" not in s and "hunter2" not in s and "A" * 48 not in s and "sk-ant-xyz" not in s
    assert ls.redact("python -m hub.server") == "python -m hub.server"


def test_process_rows_reads_proc_for_current_user():
    rows = ls.process_rows(users=(getpass.getuser(),))
    me = [r for r in rows if r["pid"] == os.getpid()]
    assert me and me[0]["rss_mb"] > 0 and "pytest" in me[0]["cmd"] and me[0]["what"].startswith("테스트")


def test_code_server_children_are_grouped():
    rows = [{"pid": i, "ppid": 1, "user": "ubuntu", "age": 10, "cpu_pct": 1.0, "rss_mb": 10.0,
             "cmd": f"/usr/lib/code-server/lib/node x{i}", "what": ""} for i in range(10, 15)]
    rows.append({"pid": 99, "ppid": 1, "user": "quant", "age": 10, "cpu_pct": 0.5, "rss_mb": 5.0, "cmd": "python -m hub.server", "what": "허브"})
    out = ls.group_code_server(rows)
    assert len(out) == 2
    cs = next(r for r in out if r.get("grouped"))
    assert cs["grouped"] == 5 and cs["rss_mb"] == pytest.approx(50.0) and "하위 프로세스 4개" in cs["cmd"]


def test_page_renders_all_sections(running_path):
    from hub import server

    html = server.render_live_page()
    for title in ("지금 실행 중인 스케줄러 잡", "텔레그램 작업 큐", "서비스", "프로세스", "시간 안에 돌 잡"):
        assert title in html
    assert 'http-equiv="refresh" content="15"' in html
    assert "지금 돌고 있는 작업" in server.render_dashboard("h")
