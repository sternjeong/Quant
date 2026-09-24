"""core/guru_schedule.py — 거장 포트폴리오 자동 추적 배치 테스트.

실제 네트워크(SEC EDGAR/ARK/yfinance)는 타지 않는다 — guru_tracker 의 조회 함수를 전부
가짜로 갈아끼우고, DB 는 tests/conftest.py 의 임시 SQLite 세션을 쓴다.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

import core.guru_schedule as guru_schedule
import core.guru_tracker as guru_tracker
from core.models import GuruHolding

UTC = timezone.utc
NOW = datetime(2026, 9, 24, 3, 0, tzinfo=UTC)

GURUS = {
    "워런 버핏": {"cik": "0001067983", "fund_name": "Berkshire Hathaway", "source": "13F"},
    "캐시 우드": {"cik": "0001697748", "fund_name": "ARK Investment Management", "source": "ark_daily"},
}


@pytest.fixture()
def env(db_session, monkeypatch, tmp_path):
    """DB 세션 + 상태파일을 임시 경로로 격리하고, 거장 목록을 2명(13F 1명/ARK 1명)으로 고정."""

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(guru_tracker, "get_session", _fake_get_session)
    monkeypatch.setattr(guru_tracker, "get_all_gurus", lambda: dict(GURUS))
    monkeypatch.setattr(guru_schedule, "SYNC_STATE_PATH", tmp_path / "guru_sync_state.json")
    return db_session


def _row(name, ticker, weight=10.0):
    return guru_tracker.HoldingRow(ticker=ticker, name=name, shares=100.0, value=1_000.0, weight_pct=weight)


def _patch_sources(monkeypatch, *, thirteen_f=None, ark=None, accession="0001-24-000001", filing_date="2026-08-14"):
    def _fake_13f(cik, resolve_tickers=True):
        return (thirteen_f if thirteen_f is not None else [_row("APPLE INC", "AAPL")]), filing_date

    def _fake_ark(fund_ticker):
        return (ark if ark is not None else [_row("TESLA INC", "TSLA")]), "2026-09-23"

    monkeypatch.setattr(guru_tracker, "fetch_latest_13f_holdings", _fake_13f)
    monkeypatch.setattr(guru_tracker, "fetch_ark_fund_holdings", _fake_ark)
    monkeypatch.setattr(
        guru_tracker,
        "_find_latest_13f_filing",
        lambda cik: {"accession": accession, "filing_date": filing_date, "cik": cik},
    )


def _run(**kwargs):
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("notify", False)
    kwargs.setdefault("sleep_fn", lambda _s: None)
    return guru_schedule.sync_all_gurus(**kwargs)


def _entry(result, guru_name):
    return next(r for r in result["results"] if r["guru_name"] == guru_name)


# ---- 기본 동작 ------------------------------------------------------------------------------


def test_first_run_syncs_every_guru(env, monkeypatch):
    _patch_sources(monkeypatch)
    result = _run()

    assert result["n_total"] == 2
    assert result["n_synced"] == 2
    assert result["n_failed"] == 0
    assert _entry(result, "워런 버핏")["filing_date"] == "2026-08-14"
    assert set(guru_tracker.get_synced_guru_names()) == {"워런 버핏", "캐시 우드"}


def test_one_guru_failing_does_not_stop_the_others(env, monkeypatch):
    _patch_sources(monkeypatch)

    def _boom(cik, resolve_tickers=True):
        raise RuntimeError("SEC 503")

    monkeypatch.setattr(guru_tracker, "fetch_latest_13f_holdings", _boom)

    result = _run()

    assert result["n_failed"] == 1 and result["n_synced"] == 1
    assert _entry(result, "워런 버핏")["status"] == "failed"
    assert "RuntimeError" in _entry(result, "워런 버핏")["reason"]
    # 실패한 거장 뒤의 ARK 는 정상적으로 저장됐어야 한다.
    assert [h["ticker"] for h in guru_tracker.get_guru_holdings("캐시 우드")] == ["TSLA"]


# ---- 13F 스킵 로직 --------------------------------------------------------------------------


def test_13f_is_not_reparsed_within_the_check_interval(env, monkeypatch):
    _patch_sources(monkeypatch)
    _run()

    parsed = {"n": 0}

    def _counting_13f(cik, resolve_tickers=True):
        parsed["n"] += 1
        return [_row("APPLE INC", "AAPL")], "2026-08-14"

    monkeypatch.setattr(guru_tracker, "fetch_latest_13f_holdings", _counting_13f)
    monkeypatch.setattr(
        guru_tracker,
        "_find_latest_13f_filing",
        lambda cik: pytest.fail("간격이 지나기 전에는 SEC submissions 도 조회하면 안 된다"),
    )

    result = _run(now=NOW + timedelta(days=1))

    assert parsed["n"] == 0
    assert _entry(result, "워런 버핏")["status"] == "skipped"
    assert "미경과" in _entry(result, "워런 버핏")["reason"]


def test_13f_skips_parsing_when_the_accession_has_not_changed(env, monkeypatch):
    _patch_sources(monkeypatch)
    _run()

    parsed = {"n": 0}

    def _counting_13f(cik, resolve_tickers=True):
        parsed["n"] += 1
        return [_row("APPLE INC", "AAPL")], "2026-08-14"

    monkeypatch.setattr(guru_tracker, "fetch_latest_13f_holdings", _counting_13f)

    later = NOW + timedelta(days=guru_schedule.THIRTEEN_F_CHECK_INTERVAL_DAYS + 1)
    result = _run(now=later)

    assert parsed["n"] == 0, "같은 accession 이면 infoTable 을 다시 파싱하면 안 된다"
    assert _entry(result, "워런 버핏")["status"] == "skipped"
    assert "새 13F 공시 없음" in _entry(result, "워런 버핏")["reason"]


def test_13f_reparses_when_a_new_filing_appears(env, monkeypatch):
    _patch_sources(monkeypatch)
    _run()

    _patch_sources(
        monkeypatch,
        thirteen_f=[_row("MICROSOFT CORP", "MSFT")],
        accession="0001-24-000002",
        filing_date="2026-11-14",
    )
    later = NOW + timedelta(days=guru_schedule.THIRTEEN_F_CHECK_INTERVAL_DAYS + 1)
    result = _run(now=later)

    entry = _entry(result, "워런 버핏")
    assert entry["status"] == "synced" and entry["filing_date"] == "2026-11-14"
    assert [h["ticker"] for h in guru_tracker.get_guru_holdings("워런 버핏")] == ["MSFT"]


def test_force_reparses_even_without_a_new_filing(env, monkeypatch):
    _patch_sources(monkeypatch)
    _run()

    parsed = {"n": 0}

    def _counting_13f(cik, resolve_tickers=True):
        parsed["n"] += 1
        return [_row("APPLE INC", "AAPL")], "2026-08-14"

    monkeypatch.setattr(guru_tracker, "fetch_latest_13f_holdings", _counting_13f)
    result = _run(now=NOW + timedelta(hours=1), force=True)

    assert parsed["n"] == 1
    assert result["n_synced"] == 2


# ---- ARK 는 매일 ----------------------------------------------------------------------------


def test_ark_is_refreshed_on_every_run(env, monkeypatch):
    _patch_sources(monkeypatch)
    _run()

    fetched = {"n": 0}

    def _counting_ark(fund_ticker):
        fetched["n"] += 1
        return [_row("TESLA INC", "TSLA")], "2026-09-24"

    monkeypatch.setattr(guru_tracker, "fetch_ark_fund_holdings", _counting_ark)
    result = _run(now=NOW + timedelta(days=1))

    assert fetched["n"] == 1, "ARK 는 매일 CSV 가 갱신되므로 간격 게이트를 걸면 안 된다"
    assert _entry(result, "캐시 우드")["status"] == "synced"


# ---- 멱등 ------------------------------------------------------------------------------------


def test_repeated_syncs_do_not_accumulate_duplicate_rows(env, monkeypatch):
    _patch_sources(monkeypatch)
    for day in range(3):
        _run(now=NOW + timedelta(days=day), force=True)

    rows = env.query(GuruHolding).all()
    assert len(rows) == 2, "거장 2명 × 보유 1종목 = 2행이어야 한다 (중복 누적 없음)"
    assert sorted(r.ticker for r in rows) == ["AAPL", "TSLA"]


# ---- 변동 알림 -------------------------------------------------------------------------------


def test_no_notification_on_the_very_first_sync(env, monkeypatch):
    _patch_sources(monkeypatch)
    sent = []
    result = _run(notify=True, notify_fn=sent.append)

    assert sent == [], "최초 동기화는 전 종목이 신규로 보이므로 알리지 않는다"
    assert result["n_notified"] == 0


def test_notifies_one_summary_per_guru_on_new_and_closed_positions(env, monkeypatch):
    _patch_sources(monkeypatch)
    _run()

    _patch_sources(
        monkeypatch,
        thirteen_f=[_row("MICROSOFT CORP", "MSFT")],
        accession="0001-24-000002",
        filing_date="2026-11-14",
    )
    sent = []
    later = NOW + timedelta(days=guru_schedule.THIRTEEN_F_CHECK_INTERVAL_DAYS + 1)
    result = _run(now=later, notify=True, notify_fn=sent.append)

    assert result["n_notified"] == 1 and len(sent) == 1, "거장당 요약 1건만 보낸다"
    assert "워런 버핏" in sent[0]
    assert "MSFT" in sent[0] and "AAPL" in sent[0]
    entry = _entry(result, "워런 버핏")
    assert entry["added"] == ["MSFT"] and entry["removed"] == ["AAPL"]


def test_notification_failure_does_not_break_the_sync(env, monkeypatch):
    _patch_sources(monkeypatch)
    _run()

    _patch_sources(
        monkeypatch,
        thirteen_f=[_row("MICROSOFT CORP", "MSFT")],
        accession="0001-24-000002",
        filing_date="2026-11-14",
    )

    def _broken(_text):
        raise RuntimeError("telegram down")

    later = NOW + timedelta(days=guru_schedule.THIRTEEN_F_CHECK_INTERVAL_DAYS + 1)
    result = _run(now=later, notify=True, notify_fn=_broken)

    assert _entry(result, "워런 버핏")["status"] == "synced"
    assert "RuntimeError" in _entry(result, "워런 버핏")["notify_error"]


# ---- rate limit / 상태 조회 -------------------------------------------------------------------


def test_sleeps_between_gurus_to_respect_the_sec_rate_limit(env, monkeypatch):
    _patch_sources(monkeypatch)
    slept = []
    _run(sleep_fn=slept.append)

    assert slept, "거장 사이에 SEC rate limit 대기가 있어야 한다"
    assert all(s >= guru_schedule.SEC_REQUEST_INTERVAL for s in slept)
    assert guru_schedule.SEC_REQUEST_INTERVAL >= 0.2, "SEC 초당 5회 이하 = 최소 0.2초 간격"


def test_auto_sync_status_reports_last_and_next_run(env, monkeypatch):
    _patch_sources(monkeypatch)
    _run()

    status = guru_schedule.get_auto_sync_status(now=NOW)

    assert status["last_run_at"] is not None
    assert status["next_run_at"] is not None
    # NOW 자체가 정확히 12:00 KST 라 다음 발화가 같은 순간일 수 있다(APScheduler 는 now 이상을 반환).
    assert status["next_run_at"] >= status["last_run_at"]
    assert status["next_run_at"].hour == 12  # KST 12:00 잡
    assert status["gurus"]["캐시 우드"]["filing_date"] == "2026-09-23"


def test_auto_sync_status_is_empty_before_any_run(env):
    status = guru_schedule.get_auto_sync_status(now=NOW)
    assert status["last_run_at"] is None and status["gurus"] == {}


# ---- 스케줄러 배선 ---------------------------------------------------------------------------


def test_disabled_job_returns_without_syncing(monkeypatch, capsys):
    from scheduler import run_scheduler

    monkeypatch.setattr(guru_schedule, "sync_all_gurus", lambda *a, **k: pytest.fail("꺼진 잡이 돌면 안 된다"))
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: False)
    monkeypatch.setattr(
        run_scheduler, "report_job_failure",
        lambda *a, **k: pytest.fail("꺼진 잡이 실패를 보고하면 안 된다"),
    )

    run_scheduler.guru_holdings_sync_job()

    assert "건너뜀" in capsys.readouterr().out


def test_job_exception_is_swallowed_and_reported(monkeypatch):
    from scheduler import run_scheduler

    def boom(*a, **k):
        raise RuntimeError("guru boom")

    reported = []
    monkeypatch.setattr(guru_schedule, "sync_all_gurus", boom)
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: True)
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda key, err: reported.append((key, err)))

    run_scheduler.guru_holdings_sync_job()  # 예외가 새면 APScheduler 잡이 죽는다

    assert reported == [("guru_holdings_sync", "RuntimeError: guru boom")]


def test_job_is_registered_in_schedule_and_process_registry():
    from core.job_schedule import SCHEDULED_JOBS_BY_ID
    from core.process_registry import PROCESS_REGISTRY

    job = SCHEDULED_JOBS_BY_ID["guru_holdings_sync"]
    assert job.process_key == "guru_holdings_sync"
    # 00:00~00:32 KST 야간 블록을 피하고 ARK CSV 공개(미 동부 저녁) 이후인 12:00 KST.
    assert job.cron == {"hour": 12, "minute": 0, "timezone": "Asia/Seoul"}
    assert PROCESS_REGISTRY["guru_holdings_sync"]["default_enabled"] is True


def test_job_does_not_collide_with_another_scheduled_slot():
    from core.job_schedule import SCHEDULED_JOBS

    slots = [(j.cron.get("hour"), j.cron.get("minute"), j.cron.get("timezone"), j.cron.get("day_of_week"))
             for j in SCHEDULED_JOBS]
    assert len(slots) == len(set(slots)), "두 잡이 같은 슬롯을 점유하면 안 된다"
