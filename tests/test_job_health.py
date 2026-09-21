"""core/job_health.py — 스케줄러 잡 실행 이력 기록과 "밤사이 정말 돌았나" 판정."""

from __future__ import annotations

import inspect
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED, JobExecutionEvent
from apscheduler.triggers.cron import CronTrigger

from core import job_health
from core.job_schedule import SCHEDULED_JOBS, SCHEDULED_JOBS_BY_ID
from core.models import SchedulerJobRun

UTC = timezone.utc
# 2026-09-21 12:00 KST (일요일 아님: 월요일). 직전 KST 자정 블록은 09-21 00:xx KST = 09-20 15:xx UTC.
NOW = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)


@pytest.fixture()
def health_session(db_session, monkeypatch):
    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(job_health, "get_session", _fake_get_session)
    monkeypatch.setattr(job_health, "is_enabled", lambda key: key != "strategy_nightly_tuning")
    return db_session


def _add_run(session, job_id, status="ok", recorded_at=None, error=None):
    session.add(SchedulerJobRun(job_id=job_id, status=status, error=error,
                                recorded_at=(recorded_at or NOW).astimezone(UTC).replace(tzinfo=None)))
    session.commit()


def _state(health, job_id):
    return next(j for j in health["jobs"] if j["job_id"] == job_id)["state"]


# ---- 리스너 -------------------------------------------------------------------------------------------------

def _event(code, job_id="daily_briefing", exception=None):
    return JobExecutionEvent(code, job_id, "default", datetime(2026, 9, 20, 15, 25, tzinfo=UTC), exception=exception)


def test_listener_records_ok_error_and_missed(health_session):
    job_health.job_run_listener(_event(EVENT_JOB_EXECUTED))
    job_health.job_run_listener(_event(EVENT_JOB_ERROR, exception=ValueError("boom")))
    job_health.job_run_listener(_event(EVENT_JOB_MISSED))

    rows = health_session.query(SchedulerJobRun).order_by(SchedulerJobRun.id).all()
    assert [r.status for r in rows] == ["ok", "error", "missed"]
    assert rows[1].error == "ValueError: boom" and rows[0].error is None
    assert rows[0].scheduled_at == datetime(2026, 9, 20, 15, 25)  # naive UTC로 저장


def test_listener_never_raises_even_if_the_db_write_fails(monkeypatch, capsys):
    @contextmanager
    def _broken():
        raise RuntimeError("db down")
        yield

    monkeypatch.setattr(job_health, "get_session", _broken)
    job_health.job_run_listener(_event(EVENT_JOB_EXECUTED))  # 예외가 새면 스케줄러가 죽는다
    assert "실행 이력 기록 실패" in capsys.readouterr().out


def test_prune_old_runs_removes_only_rows_older_than_the_retention(health_session):
    old = datetime.now(UTC) - timedelta(days=job_health.KEEP_DAYS + 5)
    _add_run(health_session, "daily_briefing", recorded_at=old)
    _add_run(health_session, "daily_briefing", recorded_at=datetime.now(UTC))
    assert job_health.prune_old_runs() == 1
    assert health_session.query(SchedulerJobRun).count() == 1


# ---- 마지막 예정 시각 계산 --------------------------------------------------------------------------------------

def test_last_expected_fire_for_a_nightly_kst_job():
    job = SCHEDULED_JOBS_BY_ID["champion_signal_alert"]  # 00:10 KST
    assert job_health.last_expected_fire(job, NOW) == datetime(2026, 9, 20, 15, 10, tzinfo=UTC)


def test_last_expected_fire_for_a_weekday_only_job_over_the_weekend():
    job = SCHEDULED_JOBS_BY_ID["daily_watchlist_scan"]  # 평일 16:30 ET
    saturday = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    fire = job_health.last_expected_fire(job, saturday)
    assert fire.astimezone(CronTrigger(**job.cron).timezone).strftime("%a %H:%M") == "Fri 16:30"


def test_last_expected_fire_for_a_weekly_job_looks_back_far_enough():
    job = SCHEDULED_JOBS_BY_ID["weekly_threads_report"]  # 일요일 20:00 ET
    fire = job_health.last_expected_fire(job, datetime(2026, 9, 24, 12, 0, tzinfo=UTC))  # 목요일
    assert fire.astimezone(CronTrigger(**job.cron).timezone).strftime("%a %H:%M") == "Sun 20:00"


# ---- 판정 ---------------------------------------------------------------------------------------------------

def test_everything_is_no_history_before_any_run_was_ever_recorded(health_session):
    health = job_health.compute_job_health(NOW)
    assert health["tracking_since"] is None
    assert {j["state"] for j in health["jobs"] if j["state"] != "disabled"} == {"no-history"}
    assert health["counts"]["problem"] == 0  # 배포 직후 오경보 금지


def test_a_job_that_ran_after_its_expected_time_is_ok(health_session):
    _add_run(health_session, "champion_signal_alert", recorded_at=datetime(2026, 9, 20, 15, 12, tzinfo=UTC))
    health = job_health.compute_job_health(NOW)
    assert _state(health, "champion_signal_alert") == "ok"


def test_error_and_missed_are_reported_as_problems_with_readable_lines(health_session):
    _add_run(health_session, "champion_signal_alert", "error", datetime(2026, 9, 20, 15, 11, tzinfo=UTC), error="KeyError: 'AAPL'")
    _add_run(health_session, "champion_ledger_record", "missed", datetime(2026, 9, 20, 15, 13, tzinfo=UTC))
    health = job_health.compute_job_health(NOW)

    assert _state(health, "champion_signal_alert") == "error"
    assert _state(health, "champion_ledger_record") == "missed"
    lines = [job_health.describe_problem(p) for p in health["problems"]]
    assert any("KeyError: 'AAPL'" in line and "09-21 00:10 KST" in line for line in lines)  # 예정 시각은 한국시간
    assert any("놓침" in line for line in lines)


def test_a_later_success_overrides_an_earlier_error_in_the_same_window(health_session):
    _add_run(health_session, "champion_signal_alert", "error", datetime(2026, 9, 20, 15, 11, tzinfo=UTC))
    _add_run(health_session, "champion_signal_alert", "ok", datetime(2026, 9, 20, 15, 20, tzinfo=UTC))
    assert _state(job_health.compute_job_health(NOW), "champion_signal_alert") == "ok"


def test_no_record_after_the_grace_period_is_overdue_but_within_it_is_pending(health_session):
    _add_run(health_session, "daily_market_snapshot", recorded_at=datetime(2026, 9, 20, 15, 1, tzinfo=UTC))  # 추적 시작점
    health = job_health.compute_job_health(NOW)
    assert _state(health, "champion_signal_alert") == "overdue"  # 예정 15:10 UTC, 이미 12시간 지남
    assert health["counts"]["problem"] >= 1

    just_after = datetime(2026, 9, 20, 15, 30, tzinfo=UTC)  # 예정 후 20분 — 유예 안
    assert _state(job_health.compute_job_health(just_after), "champion_signal_alert") == "pending"


def test_disabled_jobs_are_never_problems(health_session):
    _add_run(health_session, "daily_market_snapshot", recorded_at=datetime(2026, 9, 20, 14, 0, tzinfo=UTC))
    health = job_health.compute_job_health(NOW)
    assert _state(health, "nightly_strategy_tuning") == "disabled"  # fixture: 이 잡만 꺼짐
    assert all(p["job_id"] != "nightly_strategy_tuning" for p in health["problems"])


def test_expected_time_before_tracking_started_is_no_history(health_session):
    _add_run(health_session, "daily_market_snapshot", recorded_at=datetime(2026, 9, 21, 2, 0, tzinfo=UTC))  # 추적은 방금 시작
    health = job_health.compute_job_health(NOW)
    assert _state(health, "champion_signal_alert") == "no-history"
    assert health["counts"]["problem"] == 0


def test_long_running_jobs_get_a_longer_grace(monkeypatch, health_session):
    monkeypatch.setattr(job_health, "is_enabled", lambda key: True)  # 튜닝도 켬
    _add_run(health_session, "daily_market_snapshot", recorded_at=datetime(2026, 9, 20, 14, 0, tzinfo=UTC))
    two_hours_after = datetime(2026, 9, 20, 17, 5, tzinfo=UTC)  # 예정 15:05 UTC + 2시간
    assert _state(job_health.compute_job_health(two_hours_after), "nightly_strategy_tuning") == "pending"
    assert _state(job_health.compute_job_health(two_hours_after), "champion_signal_alert") == "overdue"


# ---- 스케줄 표 ↔ 실제 스케줄러 등록 일치 -------------------------------------------------------------------------

class _FakeScheduler:
    def __init__(self, *args, **kwargs):
        self.jobs = []
        self.listeners = []

    def add_job(self, func, trigger=None, id=None, **kwargs):
        self.jobs.append((func, trigger, id))

    def add_listener(self, callback, mask=None):
        self.listeners.append((callback, mask))

    def start(self):
        return None


def test_schedule_table_matches_what_main_really_registers(monkeypatch):
    from scheduler import run_scheduler

    fake = _FakeScheduler()
    monkeypatch.setattr(run_scheduler, "BlockingScheduler", lambda *a, **k: fake)
    monkeypatch.setattr(run_scheduler, "init_db", lambda: None)
    monkeypatch.setattr(job_health, "prune_old_runs", lambda: 0)

    run_scheduler.main()

    registered = {job_id: (func, trigger) for func, trigger, job_id in fake.jobs}
    assert set(registered) == set(SCHEDULED_JOBS_BY_ID), "잡을 추가/삭제했다면 core/job_schedule.py도 고쳐야 한다"
    for job in SCHEDULED_JOBS:
        func, trigger = registered[job.job_id]
        expected = CronTrigger(**job.cron)
        assert str(trigger) == str(expected), job.job_id
        assert str(trigger.timezone) == str(expected.timezone), job.job_id
        # 표의 process_key가 실제 잡 함수의 is_enabled 가드와 같아야 꺼진 잡을 오경보로 세지 않는다
        assert re.search(rf'is_enabled\(\s*"{re.escape(job.process_key)}"\s*\)', inspect.getsource(func)), job.job_id


def test_main_attaches_the_run_listener_for_all_three_event_kinds(monkeypatch):
    from scheduler import run_scheduler

    fake = _FakeScheduler()
    monkeypatch.setattr(run_scheduler, "BlockingScheduler", lambda *a, **k: fake)
    monkeypatch.setattr(run_scheduler, "init_db", lambda: None)
    monkeypatch.setattr(job_health, "prune_old_runs", lambda: 0)
    run_scheduler.main()

    assert len(fake.listeners) == 1
    callback, mask = fake.listeners[0]
    assert callback is job_health.job_run_listener
    assert mask & EVENT_JOB_EXECUTED and mask & EVENT_JOB_ERROR and mask & EVENT_JOB_MISSED
