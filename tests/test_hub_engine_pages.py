"""hub/engine_pages.py — 엔진 상세 화면(스케줄러·텔레그램 에이전트·VM 헬스체크).

예상값은 요구사항(14일 막대의 날짜별 판정 규칙, KST 기준, cron 요일 반영)에서 손으로 계산했다.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import job_health
from core.job_schedule import SCHEDULED_JOBS, SCHEDULED_JOBS_BY_ID
from core.models import SchedulerJobRun
from core.process_registry import PROCESS_REGISTRY
from hub import engine_pages as ep
from hub import server
from hub.apps_registry import AppSlot
from hub.status import UnitStatus

UTC = timezone.utc
# 2026-09-21 12:00 KST, 월요일.
NOW = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)
GRACE = timedelta(minutes=45)
# 추적 시작 2026-09-11 00:00 UTC = 09-11 09:00 KST
TRACKING = datetime(2026, 9, 11, 0, 0)
ACTIVE = UnitStatus("active", "running", "Mon 2026-09-21 01:00:00 UTC")


def _run(status, *, kst_day, hour=0, minute=30, error=None):
    """KST 날짜(09-dd)의 hh:mm 에 기록된 실행 1건(naive UTC 로 저장되는 형태)."""
    moment = datetime(2026, 9, kst_day, hour, minute, tzinfo=timezone(timedelta(hours=9))).astimezone(UTC).replace(tzinfo=None)
    return SimpleNamespace(status=status, error=error, scheduled_at=None, recorded_at=moment)


def _cells(job_id, runs=(), *, enabled=True, tracking=TRACKING):
    return [t for t, _ in ep.day_cells(SCHEDULED_JOBS_BY_ID[job_id], list(runs), tracking_since=tracking,
                                       enabled=enabled, now=NOW, grace=GRACE)]


# ---- 14일 막대 ------------------------------------------------------------------------------------------

def test_daily_job_cells_by_day():
    # 인덱스 0 = 09-08, 13 = 09-21(오늘). daily_briefing 은 매일 00:25 KST.
    runs = [_run("ok", kst_day=20), _run("error", kst_day=19, error="boom")]
    cells = _cells("daily_briefing", runs)
    assert len(cells) == 14
    assert cells[12] == "ok"      # 09-20 성공
    assert cells[11] == "bad"     # 09-19 실패
    assert cells[10] == "warn"    # 09-18 예정이었는데 기록 없음
    assert cells[13] == "warn"    # 오늘 00:25 가 45분 넘게 지났는데 기록 없음
    assert cells[3] == "none"     # 09-11 00:25 KST = 09-10 15:25 UTC, 추적 시작 전
    assert cells[4] == "warn"     # 09-12 00:25 KST 는 추적 시작 뒤
    assert cells[0] == "none"


def test_soft_failure_and_ok_same_day_is_bad():
    runs = [_run("failed", kst_day=20, minute=26), _run("ok", kst_day=20, minute=27)]
    assert _cells("daily_briefing", runs)[12] == "bad"


def test_today_before_due_is_pending_not_warning():
    # guru_holdings_sync 는 12:00 KST — 지금이 딱 12:00 이라 아직 유예 안
    cells = _cells("guru_holdings_sync")
    assert cells[13] == "none"
    assert cells[12] == "warn"


def test_weekly_kst_job_only_scheduled_on_sunday():
    # strategy_research_report: 일 00:50 KST. 09-13·09-20 이 일요일.
    cells = _cells("strategy_research_report")
    sundays = {5, 12}
    for i, tone in enumerate(cells):
        if i in sundays:
            assert tone == "warn", i
        elif i >= 3:
            assert tone == "muted", i  # 예정 없는 날


def test_weekly_new_york_job_lands_on_monday_kst():
    # weekly_threads_report: 일 20:00 America/New_York(EDT) = 월 09:00 KST → 09-14(6), 09-21(13)
    cells = _cells("weekly_threads_report")
    assert cells[6] == "warn" and cells[13] == "warn"
    assert all(t == "muted" for i, t in enumerate(cells) if i not in (6, 13) and i >= 3)


def test_weekday_job_skips_weekend_days():
    # daily_watchlist_scan: 월~금 16:30 NY = 화~토 05:30 KST. 09-20(일)·09-21(월) KST 에는 예정 없음.
    cells = _cells("daily_watchlist_scan")
    assert cells[12] == "muted" and cells[13] == "muted"
    assert cells[11] == "warn"  # 09-19(토) 05:30 KST = 금 16:30 NY


def test_disabled_job_is_muted_unless_it_has_records():
    cells = _cells("daily_briefing", [_run("ok", kst_day=20)], enabled=False)
    assert cells[12] == "ok"
    assert all(t == "muted" for i, t in enumerate(cells) if i != 12)


def test_no_tracking_at_all_means_none_not_warn():
    assert set(_cells("daily_briefing", tracking=None)) == {"none"}


# ---- 다음 예정 ------------------------------------------------------------------------------------------

def _meta(disabled=()):
    return [{"job": j, "label": j.job_id, "enabled": j.job_id not in disabled} for j in SCHEDULED_JOBS]


def test_upcoming_is_sorted_and_respects_weekday_and_enabled():
    start = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)  # 09-21 00:00 KST (월)
    items = ep.upcoming(_meta(disabled={"daily_news_digest"}), start, hours=12)
    ids = [i["job_id"] for i in items]
    times = [i["at"] for i in items]
    assert times == sorted(times)
    assert ids[0] == "daily_market_snapshot"
    assert "weekly_threads_report" in ids            # 월 09:00 KST
    assert "daily_news_digest" not in ids            # 꺼짐
    assert "strategy_research_report" not in ids     # 일요일만
    assert "paper_auto_trade" not in ids             # 화~토만
    assert all(start <= t < start + timedelta(hours=12) for t in times)


# ---- 스케줄러 화면 전체 -----------------------------------------------------------------------------------

@pytest.fixture()
def sched_db(db_session, monkeypatch):
    @contextmanager
    def _fake():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(job_health, "get_session", _fake)
    monkeypatch.setattr(job_health, "is_enabled", lambda key: key != "champion_benchmark_gap")
    return db_session


def _add(session, job_id, status, when, error=None):
    session.add(SchedulerJobRun(job_id=job_id, status=status, error=error, recorded_at=when.astimezone(UTC).replace(tzinfo=None)))
    session.commit()


def _slot(sid="scheduler"):
    return server.find_slot(sid)


def test_scheduler_page_shows_problem_sentence_and_escapes(sched_db, monkeypatch):
    monkeypatch.setitem(PROCESS_REGISTRY["daily_briefing"], "label", "<b>브리핑&</b>")
    _add(sched_db, "market_snapshot", "ok", NOW - timedelta(days=9))  # 추적 시작
    _add(sched_db, "daily_briefing", "error", NOW - timedelta(hours=11), error="<script>alert(1)</script>")
    data = ep.collect_scheduler(NOW)
    html = ep.scheduler_body(_slot(), ACTIVE, data)

    assert "<script>alert(1)</script>" not in html and "<b>브리핑" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;브리핑&amp;&lt;/b&gt;" in html
    problem = next(p for p in data["health"]["problems"] if p["job_id"] == "daily_briefing")
    assert ui_escape(job_health.describe_problem(problem)) in html  # 문장을 그대로
    assert 'class="verdict bad"' in html
    assert "마지막 실패" in html
    assert html.count('class="strip"') == len(SCHEDULED_JOBS)
    assert "/processes" in html


def ui_escape(text):
    from hub.ui import E

    return E(text)


def test_scheduler_page_ok_when_all_recent_runs_recorded(sched_db):
    health = job_health.compute_job_health(NOW)
    for e in health["jobs"]:
        if e["expected_at"] is not None:
            _add(sched_db, e["job_id"], "ok", e["expected_at"] + timedelta(minutes=1))
    html = ep.scheduler_body(_slot(), ACTIVE, ep.collect_scheduler(NOW))
    assert 'class="verdict ok"' in html
    assert "28/29" in html  # champion_benchmark_gap 만 꺼짐


def test_scheduler_stopped_service_is_bad(sched_db):
    html = ep.scheduler_body(_slot(), UnitStatus("inactive", "dead", ""), ep.collect_scheduler(NOW))
    assert 'class="verdict bad"' in html and "멈춰" in html


def test_scheduler_page_survives_db_failure(monkeypatch):
    @contextmanager
    def _broken():
        raise RuntimeError("db locked")
        yield

    monkeypatch.setattr(job_health, "get_session", _broken)
    monkeypatch.setattr(ep, "get_unit_status", lambda unit: UnitStatus("unknown", "unknown", ""))
    html = ep.render(_slot())
    assert html is not None and "확인 불가" in html
    assert "잡 목록" in html  # 이력이 없어도 잡 목록(이름·시각)은 그린다


# ---- 텔레그램 에이전트 -------------------------------------------------------------------------------------

def test_telegram_commands_follow_runner_help(tmp_path):
    fake = tmp_path / "runner.py"
    fake.write_text(
        "def ingest(command, n):\n"
        "    if command == '/x':\n        reply = 'no'\n"
        "    elif command in ('/start', '/help'):\n"
        "        reply = ('/alpha: 첫 명령\\n'\n"
        "                 f'/beta: 잡 {n}개 목록\\n'\n"
        "                 '답장하면 이어집니다.')\n",
        encoding="utf-8")
    assert ep.telegram_commands(fake) == [("/alpha", "첫 명령"), ("/beta", "잡 개 목록"), ("", "답장하면 이어집니다.")]
    real = [c for c, _ in ep.telegram_commands()]
    assert any(c.startswith("/processes") for c in real) and "/status" in real


def test_telegram_page_reads_only_activity(tmp_path, monkeypatch):
    con = sqlite3.connect(tmp_path / "queue.sqlite")
    con.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, instruction TEXT, status TEXT, created_at REAL, finished_at REAL)")
    ts = datetime.now(UTC).timestamp() - 3600
    con.execute("INSERT INTO jobs(instruction,status,created_at,finished_at) VALUES('SECRET-INSTRUCTION','blocked',?,0)", (ts,))
    con.execute("INSERT INTO jobs(instruction,status,created_at,finished_at) VALUES('다른 지시','queued',?,0)", (ts - 60,))
    con.commit()
    con.close()
    monkeypatch.setenv("QUANT_TELEGRAM_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(ep, "get_unit_status", lambda unit: ACTIVE)
    html = ep.render(_slot("codex-telegram"))
    assert "SECRET-INSTRUCTION" not in html and "다른 지시" not in html
    assert "1시간 전" in html
    assert 'class="verdict ok"' in html
    assert "/processes" in html


def test_telegram_page_without_queue_db(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_TELEGRAM_STATE_DIR", str(tmp_path / "missing"))
    monkeypatch.setattr(ep, "get_unit_status", lambda unit: UnitStatus("failed", "failed", ""))
    html = ep.render(_slot("codex-telegram"))
    assert "큐 확인 불가" in html and 'class="verdict bad"' in html


# ---- VM 헬스체크 ------------------------------------------------------------------------------------------

def test_vm_thresholds_come_from_the_script():
    assert ep.vm_thresholds() == {"disk": 85, "mem": 90, "cooldown": 21600}
    assert ep.usage_tone(85, 85) == "bad"
    assert ep.usage_tone(81, 85) == "warn"
    assert ep.usage_tone(50, 85) == "ok"
    assert ep.usage_tone(None, 85) == "muted"


def test_vm_health_over_threshold_is_bad(monkeypatch, tmp_path):
    from hub import ops_status

    (tmp_path / "disk.alerting").write_text("1")
    monkeypatch.setenv("VM_HEALTH_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(ops_status, "system_info", lambda: {
        "disk_pct": 91.0, "disk_free_gb": 4.0, "mem_avail_pct": 50.0, "load": (0.5, 0.4, 0.3), "cpus": 2,
        "uptime_days": 3.0, "reboot_required": False})
    monkeypatch.setattr(ep, "get_unit_status", lambda unit: ACTIVE if unit.endswith(".timer") else UnitStatus("inactive", "dead", ""))
    monkeypatch.setattr(ep, "_systemctl_props", lambda unit, *p: {"Result": "success"})
    html = ep.render(_slot("vm-health"))
    assert 'class="verdict bad"' in html and "임계값 초과" in html
    assert "알림 중" in html and "대기(정상)" in html  # oneshot 서비스가 꺼져 있는 건 정상


# ---- 공통 ---------------------------------------------------------------------------------------------------

def test_unknown_or_non_engine_slot_returns_none():
    assert ep.render(AppSlot(id="new-engine", title="t", description="d", unit="x.service", kind="engine")) is None
    assert ep.render(_slot("streamlit")) is None


def test_server_uses_engine_page(monkeypatch):
    monkeypatch.setattr(ep, "render", lambda slot: "<html>ENGINE</html>")
    assert server.render_status_page(_slot()) == "<html>ENGINE</html>"


@pytest.mark.parametrize("sid", ["scheduler", "codex-telegram", "vm-health"])
def test_pages_are_phone_safe(sid, monkeypatch, db_session):
    @contextmanager
    def _fake():
        yield db_session

    monkeypatch.setattr(job_health, "get_session", _fake)
    monkeypatch.setattr(ep, "get_unit_status", lambda unit: UnitStatus("unknown", "unknown", ""))
    html = ep.render(_slot(sid))
    assert html and 'name="viewport" content="width=device-width' in html
    # 화면 폭(390px)보다 큰 고정 폭·최소 폭이 없어야 가로 스크롤이 생기지 않는다.
    # (@media(min-width:…) 조건은 폭 고정이 아니라 넓은 화면용 분기라 뺀다.)
    for m in re.finditer(r"(?<![\w-])(?:min-)?width\s*:\s*(\d+)px", re.sub(r"@media\([^)]*\)", "", html)):
        assert int(m.group(1)) <= 360, m.group(0)
    assert "<table" not in html or sid == "codex-telegram"  # 표는 명령 목록 하나(폭 100%)만


def test_scheduler_rows_have_web_toggles_and_order_jobs_need_confirmation():
    """잡 행마다 켜고 끄기 버튼이 있고, 주문을 내는 잡을 켤 때는 확인 화면(/processes/confirm)을 거친다."""
    from hub import engine_pages

    on = engine_pages._toggle_form({"process_key": "daily_briefing", "enabled": True, "places_orders": False})
    assert 'action="/processes/toggle"' in on and 'name="enabled" value="0"' in on and "끄기" in on
    off = engine_pages._toggle_form({"process_key": "daily_briefing", "enabled": False, "places_orders": False})
    assert 'action="/processes/toggle"' in off and 'value="1"' in off
    order = engine_pages._toggle_form({"process_key": "paper_auto_trade", "enabled": False, "places_orders": True})
    assert 'action="/processes/confirm"' in order and "켜기…" in order


def test_hub_pages_make_no_external_requests():
    """허브는 외부 CDN 을 쓰지 않는다(stdlib 서버 · 외부 요청 없음 원칙)."""
    from hub import ui

    page = ui.page("t", "<p>x</p>")
    assert "http://" not in page and "https://" not in page
