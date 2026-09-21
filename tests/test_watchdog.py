"""deploy/watchdog.py — 앱과 독립적인 아침 점검: 문제 있을 때만 알린다."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import backup_status

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "watchdog.py"
spec = importlib.util.spec_from_file_location("watchdog", SCRIPT)
watchdog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog)

NOW = datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc)  # 09:05 KST


def _iso(moment: datetime) -> str:
    return moment.replace(tzinfo=None).isoformat(sep=" ")


@pytest.fixture
def app(tmp_path, monkeypatch):
    root = tmp_path / "app"
    (root / "data" / "cache" / "champion_reports").mkdir(parents=True)
    monkeypatch.setattr(backup_status, "STATUS_PATH", tmp_path / "no-backup-status.json")  # 기본: 백업 미설치
    return root


def _make_db(app: Path, rows: list[tuple[str, str, datetime]] | None):
    conn = sqlite3.connect(app / "data" / "quant.db")
    if rows is not None:
        conn.execute("CREATE TABLE scheduler_job_runs (id INTEGER PRIMARY KEY, job_id TEXT, status TEXT, "
                     "scheduled_at TEXT, error TEXT, recorded_at TEXT)")
        conn.executemany("INSERT INTO scheduler_job_runs (job_id, status, recorded_at) VALUES (?,?,?)",
                         [(j, s, _iso(t)) for j, s, t in rows])
    conn.commit()
    conn.close()


def _briefing(app: Path, age_hours: float):
    path = app / "data" / "cache" / "champion_reports" / "daily_briefing_2026-09-20.html"
    path.write_text("<html></html>")
    stamp = (NOW - timedelta(hours=age_hours)).timestamp()
    os.utime(path, (stamp, stamp))


def _run(app: Path, **kwargs):
    alerts: list[str] = []
    problems = watchdog.run_watchdog(app, alert=alerts.append, now=lambda: NOW, **kwargs)
    return problems, alerts


def test_healthy_night_is_silent(app):
    _make_db(app, [("daily_briefing", "ok", NOW - timedelta(hours=8)), ("champion_signal_alert", "ok", NOW - timedelta(hours=8))])
    _briefing(app, age_hours=8)
    problems, alerts = _run(app)
    assert problems == [] and alerts == []


def test_scheduler_silence_is_detected_once_history_exists(app):
    _make_db(app, [("daily_briefing", "ok", NOW - timedelta(hours=60))])  # 이력은 있었는데 26시간 넘게 없음
    problems, alerts = _run(app)
    assert any("스케줄러가 최근 26시간 동안" in p for p in problems)
    assert len(alerts) == 1 and "[워치독]" in alerts[0]


def test_no_history_yet_is_not_an_alarm(app):
    _make_db(app, [])  # 테이블은 있지만 비어 있음 — 추적 시작 전
    assert _run(app)[0] == []
    (app / "data" / "quant.db").unlink()
    _make_db(app, None)  # 테이블 자체가 없음(옛 스키마)
    assert _run(app)[0] == []


def test_error_and_missed_jobs_are_named(app):
    _make_db(app, [
        ("champion_signal_alert", "error", NOW - timedelta(hours=9)),
        ("champion_ledger_record", "missed", NOW - timedelta(hours=9)),
        ("daily_briefing", "ok", NOW - timedelta(hours=9)),
        ("old_job", "error", NOW - timedelta(hours=50)),  # 창 밖 — 무시
    ])
    problems, _ = _run(app)
    joined = "\n".join(problems)
    assert "champion_signal_alert" in joined and "오류" in joined
    assert "champion_ledger_record" in joined and "놓침" in joined
    assert "old_job" not in joined


def test_missing_briefing_is_flagged_only_when_briefings_existed_before(app):
    _make_db(app, [("daily_briefing", "ok", NOW - timedelta(hours=8))])
    assert _run(app)[0] == []  # 브리핑 파일이 한 번도 없는 환경 — 판정 안 함
    _briefing(app, age_hours=40)
    problems, _ = _run(app)
    assert any("브리핑이 40시간째" in p for p in problems)


def test_bad_backup_is_flagged_but_missing_remote_is_not(app, tmp_path, monkeypatch):
    _make_db(app, [("daily_briefing", "ok", NOW - timedelta(hours=8))])
    _briefing(app, age_hours=8)
    status_path = tmp_path / "status.json"
    monkeypatch.setattr(backup_status, "STATUS_PATH", status_path)
    base = {"ok": True, "error": None, "push_error": None, "files": 10, "bytes": 100, "skipped": [], "quarantined": [],
            "last_success_epoch": NOW.timestamp() - 3600, "last_push_success_epoch": None}

    status_path.write_text(json.dumps({**base, "offsite_configured": False}))
    assert _run(app)[0] == []  # 원격 미설정은 브리핑에서만 보여준다

    status_path.write_text(json.dumps({**base, "offsite_configured": False, "last_success_epoch": NOW.timestamp() - 50 * 3600}))
    problems, alerts = _run(app)
    assert any("백업" in p and "50시간" in p for p in problems) and len(alerts) == 1


def test_dry_run_reports_but_never_alerts(app):
    _make_db(app, [("champion_signal_alert", "error", NOW - timedelta(hours=9))])
    problems, alerts = _run(app, dry_run=True)
    assert problems and alerts == []


def test_missing_db_file_is_a_problem(app):
    problems, _ = _run(app)
    assert any("DB 파일이 없음" in p for p in problems)


def test_main_exit_codes(app, monkeypatch, capsys):
    monkeypatch.setattr(watchdog, "APP_DIR", app)
    _make_db(app, [("daily_briefing", "ok", datetime.now(timezone.utc) - timedelta(hours=2))])
    assert watchdog.main(["--dry-run"]) == 0
    assert "이상 없음" in capsys.readouterr().out
    conn = sqlite3.connect(app / "data" / "quant.db")
    conn.execute("INSERT INTO scheduler_job_runs (job_id, status, recorded_at) VALUES ('x','error',?)", (_iso(datetime.now(timezone.utc)),))
    conn.commit()
    conn.close()
    assert watchdog.main(["--dry-run"]) == 1
