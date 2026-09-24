"""스케줄러 잡 스케줄 표 — core.job_health가 "지금쯤 마지막으로 돌았어야 할 시각"을 계산하는 근거.

scheduler/run_scheduler.py의 main()이 실제로 등록하는 잡과 정확히 같아야 한다 — tests/test_job_health.py가
main()을 가짜 스케줄러로 실행해서 (id, cron 필드, 프로세스 키)가 이 표와 일치하는지 검증한다. 잡을 추가/변경하면
이 표도 같이 고쳐야 테스트가 통과한다(그래서 표가 조용히 낡아갈 수 없다).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduledJob:
    job_id: str  # APScheduler job id
    process_key: str  # core.process_registry 키 — 꺼져 있으면(is_enabled False) 안 돈 게 정상이다
    cron: dict  # CronTrigger 인자(timezone 포함)


SCHEDULED_JOBS: tuple[ScheduledJob, ...] = (
    ScheduledJob('daily_watchlist_scan', 'watchlist_scan', {'day_of_week': 'mon-fri', 'hour': 16, 'minute': 30, 'timezone': 'America/New_York'}),
    ScheduledJob('weekly_threads_report', 'threads_weekly_report', {'day_of_week': 'sun', 'hour': 20, 'minute': 0, 'timezone': 'America/New_York'}),
    ScheduledJob('daily_market_snapshot', 'market_snapshot', {'hour': 0, 'minute': 0, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('nightly_strategy_tuning', 'strategy_nightly_tuning', {'hour': 0, 'minute': 5, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('champion_signal_alert', 'champion_signal_alert', {'hour': 0, 'minute': 10, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('champion_correlation_snapshot', 'champion_correlation_snapshot', {'hour': 0, 'minute': 11, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('champion_ledger_record', 'champion_ledger_record', {'hour': 0, 'minute': 12, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('champion_benchmark_gap', 'champion_benchmark_gap', {'hour': 0, 'minute': 13, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('champion_rebalance_reminder', 'champion_rebalance_reminder', {'hour': 0, 'minute': 15, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('champion_earnings_reminder', 'champion_earnings_reminder', {'hour': 0, 'minute': 16, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('champion_alpha_decay', 'champion_alpha_decay', {'hour': 0, 'minute': 18, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('champion_weekly_report', 'champion_weekly_report', {'day_of_week': 'sun', 'hour': 20, 'minute': 20, 'timezone': 'America/New_York'}),
    ScheduledJob('fred_indicator_prewarm', 'fred_indicator_prewarm', {'hour': 0, 'minute': 20, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('data_integrity_check', 'data_integrity_check', {'hour': 0, 'minute': 22, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('daily_briefing', 'daily_briefing', {'hour': 0, 'minute': 25, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('daily_news_digest', 'daily_news_digest', {'hour': 7, 'minute': 30, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('candidate_ledger_record', 'candidate_ledger_record', {'hour': 0, 'minute': 27, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('candidate_ledger_outcome_update', 'candidate_ledger_outcome_update', {'hour': 0, 'minute': 28, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('guidance_shadow_record', 'guidance_shadow_record', {'hour': 0, 'minute': 30, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('filing_veto_shadow_record', 'filing_veto_shadow_record', {'hour': 0, 'minute': 32, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('account_snapshot_sync', 'account_snapshot_sync', {'hour': 0, 'minute': 35, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('alpaca_verification_bootstrap', 'alpaca_verification_bootstrap', {'hour': 0, 'minute': 40, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('cost_calibration_refresh', 'cost_calibration_refresh', {'hour': 0, 'minute': 42, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('variant_shadow_record', 'variant_shadow_record', {'hour': 0, 'minute': 44, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('strategy_research_report', 'strategy_research_report', {'day_of_week': 'sun', 'hour': 0, 'minute': 50, 'timezone': 'Asia/Seoul'}),
    ScheduledJob('guru_holdings_sync', 'guru_holdings_sync', {'hour': 12, 'minute': 0, 'timezone': 'Asia/Seoul'}),
)

SCHEDULED_JOBS_BY_ID = {job.job_id: job for job in SCHEDULED_JOBS}
