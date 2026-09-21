"""스케줄러 잡 실행 이력 기록 + "밤사이 작업이 정말 돌았는가" 판정 (2026-09-21 추가).

배경: 예전에는 잡이 돌았는지/실패했는지 볼 곳이 저널 로그밖에 없었다 — 야간 미세튜닝이 한 번도 안 돌았던 것도 한참 뒤
우연히 발견했다. 사용자는 폰으로만 운영하므로 "조용한 실패"가 가장 위험하다.

구성:
  - job_run_listener(event): APScheduler 이벤트(EXECUTED/ERROR/MISSED)를 scheduler_job_runs 테이블에 한 줄씩 남긴다.
    scheduler.run_scheduler.main()이 attach_job_run_listener(scheduler)로 단다(잡 함수를 하나도 고치지 않는다).
  - compute_job_health(): core.job_schedule의 스케줄 표로 "지금쯤 마지막으로 돌았어야 할 시각"을 계산하고, 그 뒤의 실행 기록과
    맞춰서 잡마다 ok / error / missed / overdue / pending / disabled / no-history 로 판정한다. 브리핑과 워치독이 쓴다.

한계(솔직하게): "돌았는가"를 보장할 뿐 "결과가 좋았는가"는 아니다 — 잡 함수가 내부에서 예외를 삼키면 ok로 남는다.
결과의 신선도는 core.data_integrity가 따로 본다. 이력 추적을 시작한 시점 이전의 실행 예정은 no-history로 두어 배포 직후
오경보를 내지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.triggers.cron import CronTrigger

from core.db import get_session
from core.job_schedule import SCHEDULED_JOBS, ScheduledJob
from core.models import SchedulerJobRun
from core.process_registry import PROCESS_REGISTRY, is_enabled

# 실행 예정 시각에서 이만큼 지나도 기록이 없으면 overdue. 잡은 끝날 때 기록되므로 오래 도는 잡은 따로 늘려준다.
DEFAULT_GRACE = timedelta(minutes=45)
GRACE_OVERRIDES = {"nightly_strategy_tuning": timedelta(hours=6)}  # 00:05 시작, 최대 04:00까지 반복
LOOKBACK_DAYS = 8  # 주간 잡(일요일)의 직전 예정 시각까지 찾을 수 있는 폭
KEEP_DAYS = 90
KST_OFFSET = timedelta(hours=9)

PROBLEM_STATES = ("error", "missed", "overdue")

EVENT_MASK = EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED


def _naive_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def record_job_run(job_id: str, status: str, *, error: str | None = None, scheduled_at: datetime | None = None) -> None:
    with get_session() as session:
        session.add(SchedulerJobRun(
            job_id=job_id,
            status=status,
            error=error[:500] if error else None,
            scheduled_at=_naive_utc(scheduled_at) if scheduled_at else None,
        ))


def job_run_listener(event) -> None:
    """APScheduler 리스너. 기록 실패가 스케줄러를 죽이면 안 되므로 어떤 예외도 삼키고 출력만 한다."""
    try:
        if event.code == EVENT_JOB_MISSED:
            status, error = "missed", None
        elif getattr(event, "exception", None):
            status, error = "error", f"{type(event.exception).__name__}: {event.exception}"
        else:
            status, error = "ok", None
        record_job_run(event.job_id, status, error=error, scheduled_at=getattr(event, "scheduled_run_time", None))
    except Exception as exc:  # noqa: BLE001
        print(f"[job_health] 실행 이력 기록 실패(무시): {exc}")


def prune_old_runs(days: int = KEEP_DAYS) -> int:
    cutoff = datetime.utcnow() - timedelta(days=days)
    with get_session() as session:
        return session.query(SchedulerJobRun).filter(SchedulerJobRun.recorded_at < cutoff).delete()


def attach_job_run_listener(scheduler) -> None:
    scheduler.add_listener(job_run_listener, EVENT_MASK)
    try:
        prune_old_runs()
    except Exception as exc:  # noqa: BLE001
        print(f"[job_health] 오래된 이력 정리 실패(무시): {exc}")


def last_expected_fire(job: ScheduledJob, now: datetime) -> datetime | None:
    """now(UTC, tz-aware) 이전에 이 잡이 마지막으로 실행됐어야 하는 시각. 최근 LOOKBACK_DAYS 안에 없으면 None."""
    trigger = CronTrigger(**job.cron)
    current = trigger.get_next_fire_time(None, now - timedelta(days=LOOKBACK_DAYS))
    previous = None
    while current is not None and current <= now:
        previous = current
        current = trigger.get_next_fire_time(current, current + timedelta(seconds=1))
    return previous


def _kst_label(moment: datetime | None) -> str:
    if moment is None:
        return "?"
    return (_naive_utc(moment) + KST_OFFSET).strftime("%m-%d %H:%M KST")


def compute_job_health(now: datetime | None = None) -> dict:
    """잡마다 상태를 판정한다. now는 tz-aware UTC(기본: 지금).

    반환: {"generated_at", "tracking_since", "jobs": [잡별 dict], "counts": {상태: 개수, "problem": 문제 개수}, "problems": [문제 잡 dict]}
    """
    now = now or datetime.now(timezone.utc)
    now_naive = _naive_utc(now)
    jobs: list[dict] = []
    with get_session() as session:
        first = session.query(SchedulerJobRun.recorded_at).order_by(SchedulerJobRun.recorded_at.asc()).first()
        tracking_since = first[0] if first else None
        for job in SCHEDULED_JOBS:
            label = PROCESS_REGISTRY.get(job.process_key, {}).get("label", job.job_id)
            entry = {"job_id": job.job_id, "process_key": job.process_key, "label": label,
                     "expected_at": None, "last_status": None, "last_recorded_at": None, "error": None}
            latest = (session.query(SchedulerJobRun).filter(SchedulerJobRun.job_id == job.job_id)
                      .order_by(SchedulerJobRun.recorded_at.desc()).first())
            if latest is not None:
                entry.update(last_status=latest.status, last_recorded_at=latest.recorded_at, error=latest.error)

            if not is_enabled(job.process_key):
                entry["state"] = "disabled"
                jobs.append(entry)
                continue
            expected = last_expected_fire(job, now)
            entry["expected_at"] = expected
            if expected is None:
                entry["state"] = "no-history"
                jobs.append(entry)
                continue
            expected_naive = _naive_utc(expected)
            run = (session.query(SchedulerJobRun)
                   .filter(SchedulerJobRun.job_id == job.job_id,
                           SchedulerJobRun.recorded_at >= expected_naive - timedelta(minutes=1))
                   .order_by(SchedulerJobRun.recorded_at.desc()).first())
            if run is not None:
                # 기록이 있으면 그게 증거다 — 추적 시작 시점과 상관없이 그대로 판정한다.
                entry.update(last_status=run.status, last_recorded_at=run.recorded_at, error=run.error)
                entry["state"] = {"ok": "ok", "error": "error", "missed": "missed"}.get(run.status, "error")
            elif tracking_since is None or expected_naive < tracking_since:
                entry["state"] = "no-history"  # 이력 추적을 시작하기 전의 예정 시각 — 안 돈 건지 알 수 없으니 오경보 금지
            elif now_naive <= expected_naive + GRACE_OVERRIDES.get(job.job_id, DEFAULT_GRACE):
                entry["state"] = "pending"
            else:
                entry["state"] = "overdue"
            jobs.append(entry)

    counts = {state: 0 for state in ("ok", "error", "missed", "overdue", "pending", "disabled", "no-history")}
    for entry in jobs:
        counts[entry["state"]] += 1
    counts["problem"] = sum(counts[s] for s in PROBLEM_STATES)
    return {
        "generated_at": now,
        "tracking_since": tracking_since,
        "jobs": jobs,
        "counts": counts,
        "problems": [entry for entry in jobs if entry["state"] in PROBLEM_STATES],
    }


def describe_problem(entry: dict) -> str:
    """사람이 읽는 한 줄(폰 텔레그램용). 예정 시각은 한국시간으로."""
    when = _kst_label(entry.get("expected_at"))
    if entry["state"] == "error":
        return f"{entry['label']} — 실행 중 오류 (예정 {when}): {(entry.get('error') or '')[:120]}"
    if entry["state"] == "missed":
        return f"{entry['label']} — 실행 시각을 놓침 (예정 {when})"
    return f"{entry['label']} — 실행 기록 없음 (예정 {when}, 스케줄러가 꺼져 있었을 수 있음)"
