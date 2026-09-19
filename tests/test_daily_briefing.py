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


def _patch_all(monkeypatch, *, anomalies=None, decay=None, holdings=None, corr=None, earnings=None, collar=None):
    monkeypatch.setattr(daily_briefing, "run_integrity_checks", lambda: anomalies if anomalies is not None else _empty_anomalies())
    monkeypatch.setattr(daily_briefing, "compute_champion_alpha_decay", lambda: decay)
    monkeypatch.setattr(daily_briefing, "get_current_holdings", lambda: holdings)
    monkeypatch.setattr(daily_briefing, "list_champion_correlation_snapshots", lambda limit=1: corr if corr is not None else [])
    monkeypatch.setattr(daily_briefing, "get_upcoming_earnings", lambda tickers, within_days=5: earnings if earnings is not None else [])
    monkeypatch.setattr(daily_briefing, "compute_live_collar_state", lambda: collar)


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
