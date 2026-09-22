"""core/daily_briefing.py 단위 테스트.

이 모듈은 read-only 소비자라 네트워크/DB를 전혀 건드리지 않는다 — core.daily_briefing 네임스페이스로
임포트된 각 데이터 소스 함수를 monkeypatch해서 전체 데이터 시나리오/부분 데이터(결측) 시나리오를
검증한다.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

import core.daily_briefing as daily_briefing


def _full_anomalies():
    return {
        "checks": [],
        "anomalies": [
            {"severity": "critical", "check": "price_anomaly", "detail": "SPY 종가 이상"},
            {"severity": "warning", "check": "fred_cache", "detail": "DEXKOUS 캐시 stale"},
        ],
        "ok": False,
    }


def _empty_anomalies():
    return {"checks": [], "anomalies": [], "ok": True}


def _decay(flagged: bool):
    return {
        "full_metrics": {"sharpe": 1.2},
        "recent_metrics": {"sharpe": 0.3 if flagged else 1.1},
        "metric": "sharpe",
        "decay_ratio": 0.25 if flagged else 0.92,
        "is_decayed": flagged,
        "full_start": "2018-09-19",
        "full_end": "2026-09-19",
        "recent_start": "2026-03-19",
    }


def _holdings():
    return {
        "as_of": "2026-09-19",
        "core_top4": ["XLK", "XLF", "XLE", "GLD"],
        "satellite_selected": ["NVDA", "AVGO"],
        "tickers": ["AVGO", "GLD", "NVDA", "XLE", "XLF", "XLK"],
    }


def _corr_snapshots():
    return [
        {
            "id": 1,
            "labels": ["XLK", "XLF", "XLE", "GLD", "NVDA", "AVGO"],
            "avg_correlation": 0.35,
            "max_correlation": 0.71,
            "computed_at": datetime(2026, 9, 19, 0, 11),
        }
    ]


def _earnings():
    return [{"ticker": "NVDA", "earnings_date": "2026-09-22"}]


def _collar():
    return {
        "roll_date": "2026-09-01",
        "days_remaining": 12,
        "spy_at_roll": 580.0,
        "spy_now": 585.0,
        "put_strike": 550.0,
        "call_strike": 600.0,
        "implied_vol_at_roll": 0.15,
        "implied_vol_now": 0.14,
        "net_premium_pct_at_roll": 0.2,
        "mark_to_model_pnl_pct_of_satellite_notional": 0.045,
        "satellite_weight": 0.15,
    }


def _patch_all(monkeypatch, *, anomalies=None, decay=None, holdings=None, corr=None, earnings=None, collar=None,
                job_health=None, backup=None):
    monkeypatch.setattr(daily_briefing, "run_integrity_checks", lambda: anomalies if anomalies is not None else _empty_anomalies())
    monkeypatch.setattr(daily_briefing, "compute_champion_alpha_decay", lambda: decay)
    monkeypatch.setattr(daily_briefing, "get_current_holdings", lambda: holdings)
    monkeypatch.setattr(daily_briefing, "list_champion_correlation_snapshots", lambda limit=1: corr if corr is not None else [])
    monkeypatch.setattr(daily_briefing, "get_upcoming_earnings", lambda tickers, within_days=5: earnings if earnings is not None else [])
    monkeypatch.setattr(daily_briefing, "compute_live_collar_state", lambda: collar)
    # 운영 상태(잡 이력/백업)도 반드시 목킹한다 — 안 그러면 실제 DB/파일시스템(/opt/quant-backup/status.json 등)의
    # 상태가 새어 들어와 "정상 환경에서만 통과하는" 비결정적 테스트가 된다(2026-09-22: 이걸 놓쳐서 VM에서만
    # 4개가 깨졌다 — 그때 VM의 실제 백업이 마침 실패 상태였을 뿐 코드 결함은 아니었음).
    monkeypatch.setattr(daily_briefing, "compute_job_health", lambda: job_health if job_health is not None else _job_health([]))
    monkeypatch.setattr(daily_briefing, "load_backup_status", lambda: backup)


def test_patch_all_isolates_from_real_environment_state(monkeypatch, tmp_path):
    """2026-09-22 VM 사고 재현 + 고정: VM의 실제 백업이 마침 실패 상태(ok=False)였을 때, _patch_all이
    daily_briefing.load_backup_status를 목킹하지 않으면 그 실제 상태가 새어 들어와 '특이사항 없음'을
    기대하는 옛 테스트들이 VM에서만 깨졌다(로컬은 그 파일이 없어 우연히 통과했음). 이 테스트는 실제
    core.backup_status.load_backup_status가 '지저분한' 값을 돌려주도록 만들어두고도 _patch_all을 쓴
    테스트는 영향을 안 받는지 확인한다."""
    from core import backup_status

    dirty = tmp_path / "status.json"
    dirty.write_text('{"ok": false, "error": "PermissionError", "offsite_configured": true, '
                      '"last_success_epoch": 0, "last_push_success_epoch": 0}')
    monkeypatch.setattr(backup_status, "STATUS_PATH", dirty)

    _patch_all(monkeypatch, holdings=_holdings(), decay=_decay(False))
    html = daily_briefing.generate_daily_briefing_html()
    assert "특이사항 없음" in html


def test_full_data_render_includes_every_section(monkeypatch):
    _patch_all(
        monkeypatch,
        anomalies=_full_anomalies(),
        decay=_decay(False),
        holdings=_holdings(),
        corr=_corr_snapshots(),
        earnings=_earnings(),
        collar=_collar(),
    )

    html = daily_briefing.generate_daily_briefing_html()

    assert "<!doctype html>" in html.lower()
    assert "SPY 종가 이상" in html
    assert "XLK" in html and "NVDA" in html
    assert "0.35" in html  # avg correlation
    assert "2026-09-22" in html  # earnings date
    assert "days_remaining" not in html  # 내부 키명이 그대로 노출되지 않는지
    assert "12" in html  # collar days remaining somewhere
    assert "오늘 확인이 필요한 이상" in html


def test_no_holdings_yet_renders_placeholder_not_crash(monkeypatch):
    _patch_all(monkeypatch, holdings=None, decay=_decay(False))

    html = daily_briefing.generate_daily_briefing_html()

    assert "데이터 없음" in html
    assert "특이사항 없음" in html


def test_no_correlation_snapshot_yet(monkeypatch):
    _patch_all(monkeypatch, holdings=_holdings(), corr=[], decay=_decay(False))

    html = daily_briefing.generate_daily_briefing_html()

    assert "보유종목 상관관계" in html
    assert "데이터 없음" in html


def test_anomalies_absent_shows_green_status(monkeypatch):
    _patch_all(monkeypatch, anomalies=_empty_anomalies(), decay=_decay(False), holdings=_holdings())

    html = daily_briefing.generate_daily_briefing_html()

    assert "🚨" not in html
    assert "특이사항 없음" in html


def test_anomalies_present_is_most_prominent(monkeypatch):
    _patch_all(monkeypatch, anomalies=_full_anomalies(), decay=_decay(False), holdings=_holdings())

    html = daily_briefing.generate_daily_briefing_html()

    assert "🚨" in html
    assert "critical 1" in html
    assert "오늘 확인이 필요한 이상 2건" in html


def test_alpha_decay_flagged_shows_warning_status(monkeypatch):
    _patch_all(monkeypatch, anomalies=_empty_anomalies(), decay=_decay(True), holdings=_holdings())

    html = daily_briefing.generate_daily_briefing_html()

    assert "감쇠 감지" in html
    assert "알파 감쇠가 감지됨" in html


def test_alpha_decay_not_flagged_shows_ok(monkeypatch):
    _patch_all(monkeypatch, anomalies=_empty_anomalies(), decay=_decay(False), holdings=_holdings())

    html = daily_briefing.generate_daily_briefing_html()

    assert "정상" in html


def test_decay_unavailable_renders_placeholder(monkeypatch):
    _patch_all(monkeypatch, anomalies=_empty_anomalies(), decay=None, holdings=_holdings())

    html = daily_briefing.generate_daily_briefing_html()

    assert "알파 감쇠 상태" in html
    assert "데이터 없음" in html


def test_no_earnings_section_omitted_when_empty(monkeypatch):
    _patch_all(monkeypatch, holdings=_holdings(), earnings=[], decay=_decay(False))

    html = daily_briefing.generate_daily_briefing_html()

    assert "실적 발표" not in html


def test_no_collar_section_omitted_when_none(monkeypatch):
    _patch_all(monkeypatch, holdings=_holdings(), collar=None, decay=_decay(False))

    html = daily_briefing.generate_daily_briefing_html()

    assert "칼라 헤지" not in html


def test_generate_never_raises_when_every_source_throws(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(daily_briefing, "run_integrity_checks", _boom)
    monkeypatch.setattr(daily_briefing, "compute_champion_alpha_decay", _boom)
    monkeypatch.setattr(daily_briefing, "get_current_holdings", _boom)
    monkeypatch.setattr(daily_briefing, "list_champion_correlation_snapshots", _boom)
    monkeypatch.setattr(daily_briefing, "get_upcoming_earnings", _boom)
    monkeypatch.setattr(daily_briefing, "compute_live_collar_state", _boom)

    html = daily_briefing.generate_daily_briefing_html()

    assert "<!doctype html>" in html.lower()
    assert "특이사항 없음" in html


def test_send_daily_briefing_dry_run_saves_file_without_sending(monkeypatch, tmp_path):
    monkeypatch.setattr(daily_briefing, "CHAMPION_REPORT_DIR", tmp_path)
    monkeypatch.setattr(daily_briefing, "generate_daily_briefing_html", lambda: "<html>ok</html>")

    result = daily_briefing.send_daily_briefing(dry_run=True)

    assert result["sent"] is False
    assert Path(result["path"]).read_text(encoding="utf-8") == "<html>ok</html>"
    assert Path(result["path"]).parent == tmp_path


def test_send_daily_briefing_sends_document_when_not_dry_run(monkeypatch, tmp_path):
    monkeypatch.setattr(daily_briefing, "CHAMPION_REPORT_DIR", tmp_path)
    monkeypatch.setattr(daily_briefing, "generate_daily_briefing_html", lambda: "<html>ok</html>")

    import core.telegram_notify as telegram_notify

    captured = {}

    def _fake_send_document(path, caption=""):
        captured["path"] = path
        captured["caption"] = caption
        return True

    monkeypatch.setattr(telegram_notify, "send_document", _fake_send_document)

    result = daily_briefing.send_daily_briefing(dry_run=False)

    assert result["sent"] is True
    assert captured["caption"] == "📋 오늘의 브리핑"


# ---- 운영 상태(밤사이 작업 · 백업) 섹션 — 2026-09-21 추가 ------------------------------------------------------

def _job_health(problems=(), tracking=True):
    return {
        "generated_at": None, "tracking_since": object() if tracking else None, "jobs": [],
        "counts": {"ok": 10, "pending": 1, "disabled": 1, "no-history": 0, "problem": len(problems)},
        "problems": list(problems),
    }


def _problem(job_id="champion_signal_alert", state="overdue"):
    from datetime import datetime, timezone
    return {"job_id": job_id, "label": "챔피언 전략 신호 변경 알림", "state": state,
            "expected_at": datetime(2026, 9, 20, 15, 10, tzinfo=timezone.utc), "error": None}


def _backup(level="ok", lines=("마지막 백업 5시간 전",)):
    return {"level": level, "lines": list(lines)}


def test_status_line_reports_ops_problems_between_anomalies_and_decay():
    from core.daily_briefing import _RED, _status_line
    text, color = _status_line(0, False, ops_problem_count=2)
    assert "문제 2건" in text and color == _RED
    assert "이상 1건" in _status_line(1, False, ops_problem_count=2)[0]  # 데이터 이상이 우선
    assert _status_line(0, False)[0].startswith("특이사항 없음")  # 기존 호출 방식 그대로 동작


def test_ops_section_lists_problems_and_backup_lines():
    from core.daily_briefing import _ops_problems, _ops_section
    health = _job_health([_problem()])
    backup = _backup("bad", ["마지막 성공 백업이 40시간 전"])
    problems = _ops_problems(health, backup)
    assert len(problems) == 2 and problems[1].startswith("백업:")
    html = _ops_section(health, backup, problems)
    assert "챔피언 전략 신호 변경 알림" in html and "09-21 00:10 KST" in html
    assert "40시간 전" in html and "문제 1" in html


def test_ops_section_is_calm_when_everything_is_fine_and_says_when_tracking_just_started():
    from core.daily_briefing import _ops_problems, _ops_section
    health = _job_health([], tracking=False)
    backup = _backup()
    assert _ops_problems(health, backup) == []
    html = _ops_section(health, backup, [])
    assert "막 시작돼" in html and "마지막 백업 5시간 전" in html


def test_warn_level_backup_is_shown_but_does_not_count_as_a_problem():
    from core.daily_briefing import _ops_problems
    assert _ops_problems(_job_health(), _backup("warn", ["비공개 저장소 미설정"])) == []


def _stub_everything_but_ops(monkeypatch, briefing, job_health, backup):
    monkeypatch.setattr(briefing, "run_integrity_checks", lambda: {"anomalies": []})
    monkeypatch.setattr(briefing, "compute_champion_alpha_decay", lambda: None)
    monkeypatch.setattr(briefing, "get_current_holdings", lambda: None)
    monkeypatch.setattr(briefing, "list_champion_correlation_snapshots", lambda limit=1: [])
    monkeypatch.setattr(briefing, "compute_live_collar_state", lambda: None)
    monkeypatch.setattr(briefing, "compute_job_health", lambda: job_health)
    monkeypatch.setattr(briefing, "load_backup_status", lambda: backup)


def test_briefing_puts_ops_problems_first_and_healthy_ops_last(monkeypatch):
    from core import daily_briefing as briefing
    _stub_everything_but_ops(monkeypatch, briefing, _job_health([_problem()]), None)
    with_problem = briefing.generate_daily_briefing_html()
    assert "밤사이 작업/백업에 문제" in with_problem
    assert with_problem.index("운영 상태") < with_problem.index("보유")  # 문제 있으면 맨 위

    _stub_everything_but_ops(monkeypatch, briefing, _job_health([]), {
        "ok": True, "offsite_configured": True, "push_error": None, "files": 1, "bytes": 1000,
        "last_success_epoch": __import__("time").time() - 3600, "last_push_success_epoch": __import__("time").time() - 3600,
        "skipped": [], "quarantined": [],
    })
    healthy = briefing.generate_daily_briefing_html()
    assert "특이사항 없음" in healthy
    assert healthy.index("운영 상태") > healthy.index("보유")  # 정상이면 맨 아래


def test_briefing_survives_an_unreadable_job_history(monkeypatch):
    from core import daily_briefing as briefing
    _stub_everything_but_ops(monkeypatch, briefing, None, None)
    monkeypatch.setattr(briefing, "compute_job_health", lambda: (_ for _ in ()).throw(RuntimeError("db gone")))
    html = briefing.generate_daily_briefing_html()
    assert "작업 실행 이력을 읽지 못했음" in html and "백업 상태 없음" in html
