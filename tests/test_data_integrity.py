"""core/data_integrity.py 단위 테스트.

네트워크(yfinance/FRED API) 호출을 피하기 위해 fetch_fn/cache_dir/rows를 모두 주입해서 합성
데이터로만 검사한다 (tests/test_champion_strategy.py와 동일한 관례 — 실제 core.market_data/
core.fred_data/core.db는 건드리지 않는다).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core import data_integrity


def _ohlcv(dates: pd.DatetimeIndex, closes: list[float]) -> pd.DataFrame:
    closes = np.array(closes, dtype=float)
    return pd.DataFrame(
        {"Open": closes, "High": closes * 1.001, "Low": closes * 0.999, "Close": closes, "Volume": 1_000_000},
        index=dates,
    )


def _recent_bdates(n: int, end: datetime) -> pd.DatetimeIndex:
    return pd.bdate_range(end=pd.Timestamp(end).normalize(), periods=n)


# ---------------------------------------------------------------------------
# check_price_anomalies
# ---------------------------------------------------------------------------

def test_price_anomalies_clean_data_reports_ok():
    today = datetime(2026, 9, 19, 9, 0, 0)
    dates = _recent_bdates(10, today)
    closes = list(np.linspace(100, 105, 10))

    def fetch_fn(tickers, start):
        return {t: _ohlcv(dates, closes) for t in tickers}

    findings = data_integrity.check_price_anomalies(tickers=["AAA"], fetch_fn=fetch_fn, today=today)
    assert len(findings) == 1
    assert findings[0]["check"] == "price_ok"
    assert findings[0]["severity"] == "info"


def test_price_anomalies_zero_or_negative_close():
    today = datetime(2026, 9, 19, 9, 0, 0)
    dates = _recent_bdates(5, today)
    closes = [100, 101, 0, 102, 103]

    def fetch_fn(tickers, start):
        return {t: _ohlcv(dates, closes) for t in tickers}

    findings = data_integrity.check_price_anomalies(tickers=["BBB"], fetch_fn=fetch_fn, today=today)
    checks = {f["check"] for f in findings}
    assert "price_zero_or_negative" in checks
    critical = [f for f in findings if f["check"] == "price_zero_or_negative"]
    assert critical[0]["severity"] == "critical"
    assert critical[0]["ticker"] == "BBB"


def test_price_anomalies_return_spike():
    today = datetime(2026, 9, 19, 9, 0, 0)
    dates = _recent_bdates(5, today)
    # 마지막 구간에서 하루만에 100% 급등 (>50% 임계값 초과)
    closes = [100, 101, 100, 102, 205]

    def fetch_fn(tickers, start):
        return {t: _ohlcv(dates, closes) for t in tickers}

    findings = data_integrity.check_price_anomalies(tickers=["CCC"], fetch_fn=fetch_fn, today=today)
    checks = {f["check"] for f in findings}
    assert "price_return_spike" in checks


def test_price_anomalies_duplicate_index():
    today = datetime(2026, 9, 19, 9, 0, 0)
    dates = _recent_bdates(5, today)
    df = _ohlcv(dates, [100, 101, 102, 103, 104])
    df = pd.concat([df, df.iloc[[-1]]])  # 마지막 날짜 중복

    def fetch_fn(tickers, start):
        return {t: df for t in tickers}

    findings = data_integrity.check_price_anomalies(tickers=["DDD"], fetch_fn=fetch_fn, today=today)
    checks = {f["check"] for f in findings}
    assert "price_duplicate_index" in checks


def test_price_anomalies_stale_data():
    today = datetime(2026, 9, 19, 9, 0, 0)
    stale_end = today - timedelta(days=10)
    dates = _recent_bdates(5, stale_end)
    closes = [100, 101, 102, 103, 104]

    def fetch_fn(tickers, start):
        return {t: _ohlcv(dates, closes) for t in tickers}

    findings = data_integrity.check_price_anomalies(tickers=["EEE"], fetch_fn=fetch_fn, today=today)
    checks = {f["check"] for f in findings}
    assert "price_stale" in checks


def test_price_anomalies_missing_data():
    today = datetime(2026, 9, 19, 9, 0, 0)

    def fetch_fn(tickers, start):
        return {t: pd.DataFrame() for t in tickers}

    findings = data_integrity.check_price_anomalies(tickers=["FFF"], fetch_fn=fetch_fn, today=today)
    checks = {f["check"] for f in findings}
    assert "price_missing" in checks


def test_price_anomalies_no_tickers():
    findings = data_integrity.check_price_anomalies(tickers=[], fetch_fn=lambda t, s: {}, today=datetime(2026, 9, 19))
    assert findings[0]["check"] == "price_ok"


# ---------------------------------------------------------------------------
# check_fred_cache_anomalies
# ---------------------------------------------------------------------------

def test_fred_cache_no_files_reports_ok(tmp_path):
    findings = data_integrity.check_fred_cache_anomalies(cache_dir=tmp_path, today=datetime(2026, 9, 19))
    assert len(findings) == 1
    assert findings[0]["check"] == "fred_cache_ok"


def test_fred_cache_fresh_daily_series_ok(tmp_path):
    today = datetime(2026, 9, 19)
    df = pd.DataFrame({"value": [1.0, 2.0]}, index=pd.to_datetime(["2026-09-17", "2026-09-18"]))
    df.to_csv(tmp_path / "fred_T10Y2Y.csv")

    findings = data_integrity.check_fred_cache_anomalies(cache_dir=tmp_path, today=today)
    assert findings[0]["check"] == "fred_cache_ok"


def test_fred_cache_stale_daily_series_flagged(tmp_path):
    today = datetime(2026, 9, 19)
    df = pd.DataFrame({"value": [1.0]}, index=pd.to_datetime(["2026-08-01"]))  # >10일 전
    df.to_csv(tmp_path / "fred_T10Y2Y.csv")

    findings = data_integrity.check_fred_cache_anomalies(cache_dir=tmp_path, today=today)
    checks = {f["check"] for f in findings}
    assert "fred_cache_stale" in checks


def test_fred_cache_monthly_series_lenient_threshold(tmp_path):
    """월별 시리즈(FEDFUNDS)는 40일 지연 정도는 정상 발표 주기 범위 내라 stale 처리하지 않는다."""
    today = datetime(2026, 9, 19)
    stale_date = today - timedelta(days=40)
    df = pd.DataFrame({"value": [5.0]}, index=[stale_date])
    df.to_csv(tmp_path / "fred_FEDFUNDS.csv")

    findings = data_integrity.check_fred_cache_anomalies(cache_dir=tmp_path, today=today)
    assert findings[0]["check"] == "fred_cache_ok"


def test_fred_cache_empty_file_flagged(tmp_path):
    path = tmp_path / "fred_UNRATE.csv"
    path.write_text("")

    findings = data_integrity.check_fred_cache_anomalies(cache_dir=tmp_path, today=datetime(2026, 9, 19))
    checks = {f["check"] for f in findings}
    assert "fred_cache_empty" in checks
    assert findings[0]["severity"] == "critical"


def test_fred_cache_malformed_file_flagged(tmp_path):
    path = tmp_path / "fred_CPIAUCSL.csv"
    path.write_text("not,a,valid\ncsv,,,,,")

    findings = data_integrity.check_fred_cache_anomalies(cache_dir=tmp_path, today=datetime(2026, 9, 19))
    checks = {f["check"] for f in findings}
    assert "fred_cache_malformed" in checks or "fred_cache_empty" in checks


# ---------------------------------------------------------------------------
# check_news_digest_anomalies
# ---------------------------------------------------------------------------

def test_news_digest_no_rows_reports_ok():
    findings = data_integrity.check_news_digest_anomalies(rows=[])
    assert findings[0]["check"] == "news_digest_ok"


def test_news_digest_clean_rows_ok():
    rows = [
        {"ticker": "AAPL", "summary": "정상 요약입니다.", "source_links": json.dumps([{"title": "a", "url": "http://x"}])},
    ]
    findings = data_integrity.check_news_digest_anomalies(rows=rows)
    assert findings[0]["check"] == "news_digest_ok"


def test_news_digest_empty_summary_flagged():
    rows = [{"ticker": "AAPL", "summary": "   ", "source_links": "[]"}]
    findings = data_integrity.check_news_digest_anomalies(rows=rows)
    checks = {f["check"] for f in findings}
    assert "news_digest_empty_summary" in checks


def test_news_digest_invalid_json_links_flagged():
    rows = [{"ticker": "AAPL", "summary": "요약", "source_links": "not json"}]
    findings = data_integrity.check_news_digest_anomalies(rows=rows)
    checks = {f["check"] for f in findings}
    assert "news_digest_invalid_links" in checks


def test_news_digest_non_list_json_flagged():
    rows = [{"ticker": "AAPL", "summary": "요약", "source_links": json.dumps({"not": "a list"})}]
    findings = data_integrity.check_news_digest_anomalies(rows=rows)
    checks = {f["check"] for f in findings}
    assert "news_digest_invalid_links" in checks


# ---------------------------------------------------------------------------
# run_integrity_checks (통합)
# ---------------------------------------------------------------------------

def test_run_integrity_checks_all_clean_is_ok(tmp_path):
    today = datetime(2026, 9, 19, 9, 0, 0)
    dates = _recent_bdates(10, today)
    closes = list(np.linspace(100, 105, 10))

    def fetch_fn(tickers, start):
        return {t: _ohlcv(dates, closes) for t in tickers}

    result = data_integrity.run_integrity_checks(
        price_fetch_fn=fetch_fn,
        price_tickers=["AAA", "BBB"],
        fred_cache_dir=tmp_path,
        news_rows=[],
        today=today,
    )
    assert result["ok"] is True
    assert result["anomalies"] == []
    assert len(result["checks"]) == 3  # price_ok, fred_cache_ok, news_digest_ok


def test_run_integrity_checks_collects_anomalies(tmp_path):
    today = datetime(2026, 9, 19, 9, 0, 0)
    dates = _recent_bdates(5, today)
    closes = [100, 101, 0, 102, 103]  # 0원 종가 -> critical

    def fetch_fn(tickers, start):
        return {t: _ohlcv(dates, closes) for t in tickers}

    result = data_integrity.run_integrity_checks(
        price_fetch_fn=fetch_fn,
        price_tickers=["ZZZ"],
        fred_cache_dir=tmp_path,
        news_rows=[{"ticker": "AAPL", "summary": "", "source_links": "[]"}],
        today=today,
    )
    assert result["ok"] is False
    checks = {a["check"] for a in result["anomalies"]}
    assert "price_zero_or_negative" in checks
    assert "news_digest_empty_summary" in checks


def test_format_anomaly_telegram_message_groups_by_severity():
    anomalies = [
        {"check": "price_zero_or_negative", "severity": "critical", "detail": "AAA critical detail", "ticker": "AAA"},
        {"check": "price_stale", "severity": "warning", "detail": "BBB warning detail", "ticker": "BBB"},
    ]
    message = data_integrity.format_anomaly_telegram_message(anomalies)
    assert "critical 1건" in message
    assert "warning 1건" in message
    assert "AAA critical detail" in message
    assert "BBB warning detail" in message


# ---------------------------------------------------------------------------
# scheduler job: 텔레그램은 anomalies가 있을 때만 전송
# ---------------------------------------------------------------------------

def test_data_integrity_check_job_notifies_only_on_anomaly(monkeypatch):
    import scheduler.run_scheduler as run_scheduler

    sent = []
    monkeypatch.setattr(run_scheduler, "send_message", sent.append)

    # anomalies 없음 -> 알림 생략
    monkeypatch.setattr(
        "core.data_integrity.run_integrity_checks",
        lambda: {"checks": [{"check": "price_ok", "severity": "info", "detail": "ok", "ticker": None}], "anomalies": [], "ok": True},
    )
    run_scheduler.data_integrity_check_job()
    assert sent == []

    # anomalies 있음 -> 알림 전송
    monkeypatch.setattr(
        "core.data_integrity.run_integrity_checks",
        lambda: {
            "checks": [{"check": "price_zero_or_negative", "severity": "critical", "detail": "AAA 이상", "ticker": "AAA"}],
            "anomalies": [{"check": "price_zero_or_negative", "severity": "critical", "detail": "AAA 이상", "ticker": "AAA"}],
            "ok": False,
        },
    )
    run_scheduler.data_integrity_check_job()
    assert len(sent) == 1
    assert "AAA 이상" in sent[0]
