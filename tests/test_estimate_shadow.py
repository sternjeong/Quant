"""core/estimate_shadow.py — 애널리스트 추정치 매일 기록. yfinance 는 가짜(네트워크 없음)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from core import estimate_shadow as es


class FakeAnalysis:
    _earnings_trend = [{"period": "0q", "endDate": "2026-12-31"}, {"period": "+1q", "endDate": "2027-03-31"}]


class FakeTicker:
    def __init__(self, symbol, bump=0.0, broken=()):
        self.symbol = symbol
        self.bump = bump
        self.broken = set(broken)
        self._analysis = FakeAnalysis()

    def _maybe(self, name, value):
        if name in self.broken:
            raise RuntimeError("boom")
        return value

    @property
    def eps_trend(self):
        df = pd.DataFrame({"current": [1.0 + self.bump, 4.2], "7daysAgo": [0.98, 4.1], "30daysAgo": [float("nan"), 4.0],
                           "currency": ["USD", "USD"]}, index=pd.Index(["0q", "0y"], name="period"))
        return self._maybe("eps_trend", df)

    @property
    def eps_revisions(self):
        return self._maybe("eps_revisions", pd.DataFrame({"upLast7days": [2], "downLast30days": [1]},
                                                         index=pd.Index(["0q"], name="period")))

    @property
    def earnings_estimate(self):
        return self._maybe("earnings_estimate", pd.DataFrame({"avg": [1.0], "numberOfAnalysts": [12]},
                                                             index=pd.Index(["0q"], name="period")))

    @property
    def revenue_estimate(self):
        return self._maybe("revenue_estimate", pd.DataFrame())

    @property
    def recommendations_summary(self):
        return self._maybe("recommendations_summary",
                           pd.DataFrame({"period": ["0m", "-1m"], "strongBuy": [5, 4], "buy": [10, 10], "hold": [3, 4]}))

    @property
    def analyst_price_targets(self):
        return self._maybe("analyst_price_targets", {"current": 100.0, "mean": 120.5, "high": float("inf")})


def _clock():
    t = {"v": 0.0}

    def clock():
        return t["v"]

    def sleep(s):
        t["v"] += s

    return clock, sleep, t


NOW = datetime(2026, 11, 9, 22, 5, tzinfo=timezone.utc)   # = 2026-11-10 07:05 KST


def _fetch(factory):
    return lambda tk: es.fetch_yfinance(tk, ticker_factory=factory)


def test_fetch_yfinance_normalizes_and_isolates_item_errors():
    got = es.fetch_yfinance("AAA", ticker_factory=lambda s: FakeTicker(s, broken={"eps_revisions"}))
    assert got["eps_trend"][0]["period"] == "0q" and got["eps_trend"][0]["current"] == 1.0
    assert got["eps_trend"][0]["30daysAgo"] is None                       # NaN → None
    assert got["eps_revisions"] is None and got["_errors"] == {"eps_revisions": "RuntimeError"}
    assert got["revenue_estimate"] is None                                # 빈 표 → None
    assert got["price_targets"] == [{"current": 100.0, "mean": 120.5, "high": None}]
    assert got["period_end_dates"][0] == {"period": "0q", "endDate": "2026-12-31"}
    assert got["recommendations_summary"][1]["strongBuy"] == 4
    json.dumps(got)                                                       # 그대로 JSON 저장 가능


def test_record_appends_and_never_overwrites(tmp_path):
    db = tmp_path / "e.sqlite"
    clock, sleep, _ = _clock()
    s1 = es.record(tickers=["AAA", "BBB"], path=db, fetch=_fetch(lambda s: FakeTicker(s)), now=lambda: NOW,
                   clock=clock, sleep=sleep)
    assert s1["ok"] and s1["record_date"] == "2026-11-10" and s1["n_ok"] == 2
    assert s1["inserted"] == 2 * 6                                        # revenue_estimate 는 비어서 빠짐
    # 같은 날 다시: 값이 바뀌어도 이미 있는 종목은 건너뛰고 덮어쓰지 않는다
    s2 = es.record(tickers=["AAA", "BBB", "CCC"], path=db, fetch=_fetch(lambda s: FakeTicker(s, bump=9.0)), now=lambda: NOW,
                   clock=clock, sleep=sleep)
    assert s2["n_already"] == 2 and s2["n_ok"] == 1 and s2["inserted"] == 6
    hist = es.load_history("AAA", "eps_trend", path=db)
    assert len(hist) == 1 and hist[0]["payload"][0]["current"] == 1.0
    # 다음 날은 새 줄로 덧붙는다
    s3 = es.record(tickers=["AAA"], path=db, fetch=_fetch(lambda s: FakeTicker(s, bump=0.5)),
                   now=lambda: datetime(2026, 11, 10, 22, 5, tzinfo=timezone.utc), clock=clock, sleep=sleep)
    assert s3["record_date"] == "2026-11-11" and s3["inserted"] == 6
    hist = es.load_history("AAA", "eps_trend", path=db)
    assert [h["record_date"] for h in hist] == ["2026-11-10", "2026-11-11"]
    assert [h["payload"][0]["current"] for h in hist] == [1.0, 1.5]
    cov = es.coverage(path=db)
    assert cov["days"] == 2 and cov["tickers"] == 3 and cov["last_run"]["record_date"] == "2026-11-11"
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 3


def test_record_time_limit_and_rotation(tmp_path):
    clock, sleep, _ = _clock()
    names = [f"T{i}" for i in range(10)]
    s = es.record(tickers=names, path=tmp_path / "e.sqlite", fetch=_fetch(lambda x: FakeTicker(x)), now=lambda: NOW,
                  clock=clock, sleep=sleep, pause=1.0, max_seconds=3.5)
    assert s["timed_out"] and s["n_ok"] == 4 and s["n_skipped_time"] == 6 and s["ok"]
    a, b = es.rotate(names, date(2026, 11, 10)), es.rotate(names, date(2026, 11, 11))
    assert sorted(a) == names and a[0] != b[0]
    assert es.rotate([], date(2026, 1, 1)) == []


def test_record_aborts_on_leading_failures_and_isolates_later_ones(tmp_path):
    clock, sleep, _ = _clock()

    def always_fail(tk):
        raise ConnectionError("blocked")

    s = es.record(tickers=[f"T{i}" for i in range(40)], path=tmp_path / "a.sqlite", fetch=always_fail, now=lambda: NOW,
                  clock=clock, sleep=sleep)
    assert s["aborted"] and not s["ok"] and s["n_failed"] == es.ABORT_AFTER_FIRST_FAILURES
    assert s["errors"] == {"ConnectionError": es.ABORT_AFTER_FIRST_FAILURES}

    def some_fail(tk):
        if tk == "BAD":
            raise ValueError("x")
        if tk == "EMPTY":
            return {k: None for k in es.KINDS}
        return es.fetch_yfinance(tk, ticker_factory=lambda x: FakeTicker(x))

    s = es.record(tickers=["AAA", "BAD", "EMPTY", "ZZZ"], path=tmp_path / "b.sqlite", fetch=some_fail, now=lambda: NOW,
                  clock=clock, sleep=sleep)
    assert s["ok"] and s["n_ok"] == 2 and s["n_failed"] == 1 and s["n_empty"] == 1 and not s["aborted"]
    assert "기록 2" in es.format_summary(s)


def test_default_tickers_uses_current_sp500():
    names = es.default_tickers(date(2026, 11, 10))
    assert 450 <= len(names) <= es.MAX_TICKERS and "AAPL" in names and names == sorted(names)


def test_scheduler_job_calls_record_and_reports_failure(monkeypatch):
    from scheduler import run_scheduler as rs

    calls, failures = [], []
    monkeypatch.setattr(rs, "is_enabled", lambda key: True)
    monkeypatch.setattr(rs, "report_job_failure", lambda key, msg: failures.append((key, msg)))
    monkeypatch.setattr(es, "record", lambda: calls.append(1) or {"ok": False, "record_date": "2026-11-10", "errors": {"X": 1}})
    rs.estimate_shadow_record_job()
    assert calls == [1] and failures and failures[0][0] == "estimate_shadow_record"

    monkeypatch.setattr(es, "record", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    rs.estimate_shadow_record_job()                                       # 예외가 새지 않는다
    assert failures[-1] == ("estimate_shadow_record", "RuntimeError: boom")

    monkeypatch.setattr(rs, "is_enabled", lambda key: False)
    calls.clear()
    rs.estimate_shadow_record_job()
    assert calls == []


def test_registered_in_registry_and_schedule():
    from core.job_schedule import SCHEDULED_JOBS_BY_ID
    from core.process_registry import PROCESS_REGISTRY

    job = SCHEDULED_JOBS_BY_ID["estimate_shadow_record"]
    assert job.cron == {"hour": 7, "minute": 5, "timezone": "Asia/Seoul"}
    assert PROCESS_REGISTRY["estimate_shadow_record"]["default_enabled"] is True
