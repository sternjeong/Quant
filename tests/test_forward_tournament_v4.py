"""앞으로 토너먼트 v4 — 원화 적립 계좌 원장(적립·공제 안 되돌림·연초 되돌림·200일선 다리·세금)."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from core import forward_tournament_v4 as ft4


def _hist(days, spy, sso, bil):
    return {t: pd.DataFrame({"Close": s, "Adj Close": s}, index=days) for t, s in (("SPY", spy), ("SSO", sso), ("BIL", bil))}


def _market(n=520, start="2026-01-02", drift=0.0008, seed=3):
    days = pd.bdate_range(start, periods=n)
    r = np.random.default_rng(seed).normal(drift, 0.008, n)
    spy = 100 * np.cumprod(1 + r)
    sso = 50 * np.cumprod(1 + 2 * r)
    bil = 90 * np.cumprod(np.full(n, 1 + 0.0001))
    return days, spy, sso, bil


def _run(tmp_path, days, spy, sso, bil, upto, fx=1400.0, armed="2026-11-12"):
    p = tmp_path / "ledger.jsonl"
    (tmp_path / "armed.json").write_text('{"start_not_before": "%s"}' % armed)
    hist = _hist(days, spy, sso, bil)
    fxs = pd.Series(fx, index=pd.bdate_range("2025-01-01", days[-1]))
    for d in upto:
        cut = {t: df.loc[:d] for t, df in hist.items()}
        ft4.record(path=p, price_fn=lambda _t, cut=cut: cut, fx_fn=lambda: fxs,
                   now=datetime(d.year, d.month, d.day, 23, 0, tzinfo=timezone.utc))
    return p


def test_starts_on_armed_date_with_lump_and_monthly(tmp_path):
    days, spy, sso, bil = _market(n=300, start="2026-01-02")
    upto = [d for d in days if d >= pd.Timestamp("2026-11-10")]
    p = _run(tmp_path, days, spy, sso, bil, upto)
    rows = ft4.load_ledger(p)
    assert rows[0]["date"] == "2026-11-12"
    b0 = rows[-1]["accounts"]["B0"]
    months = {d[:7] for d, _ in b0["flows"]}
    assert b0["flows"][0][1] == ft4.LUMP_KRW + ft4.MONTHLY_KRW
    assert len(b0["flows"]) == len(months)
    for a in ft4.ARMS:
        assert rows[-1]["accounts"][a]["contributed"] == b0["contributed"]
    w = rows[0]["snap"]["L20A"]["weights"]
    assert w["SSO"] == pytest.approx(0.20, abs=0.002)


def test_catches_up_missed_days_and_never_rewrites(tmp_path):
    days, spy, sso, bil = _market(n=240, start="2026-03-02")
    p = _run(tmp_path, days, spy, sso, bil, [days[-1]], armed="2026-11-12")
    n1 = len(ft4.load_ledger(p))
    assert n1 > 1
    p = _run(tmp_path, days, spy, sso, bil, [days[-1]], armed="2026-11-12")
    assert len(ft4.load_ledger(p)) == n1


def test_allowance_rebalance_is_tax_free_and_annual_pays_tax():
    px, fx = {"SPY": 100.0, "SSO": 100.0, "BIL": 100.0}, 1000.0
    a = ft4.new_account()
    a["year"] = 2027
    a["units"] = {"SPY": 400.0, "SSO": 200.0}
    a["basis"] = {"SPY": 30_000_000.0, "SSO": 5_000_000.0}  # SSO 이익 1,500만 원
    day = pd.Timestamp("2027-12-01")
    lvl = pd.Series(100.0, index=pd.bdate_range("2027-01-01", day))
    ev = ft4.step("L20A", a, day, px, fx, first=False, new_month=True, spy_level=lvl)
    assert any("공제" in e for e in ev)
    assert a["tax_paid"] == pytest.approx(0.0, abs=1.0)
    assert a["year_gain"] == pytest.approx(ft4.ALLOWANCE, rel=1e-6)
    b = ft4.new_account()
    b["year"] = 2028
    b["units"] = {"SPY": 400.0, "SSO": 200.0}
    b["basis"] = {"SPY": 30_000_000.0, "SSO": 5_000_000.0}
    ft4.step("L20Y", b, pd.Timestamp("2028-01-03"), px, fx, first=False, new_month=True, spy_level=lvl)
    assert b["tax_paid"] > 0
    v = ft4.total_value(b, px, fx)
    assert ft4._value(b, "SSO", px, fx) / v == pytest.approx(0.20, abs=0.01)


def test_band_filter_switches_leg_to_bil_below_sma(tmp_path):
    days = pd.bdate_range("2026-01-02", periods=330)
    spy = np.r_[np.linspace(100, 140, 250), np.linspace(140, 95, 80)]
    sso = spy / 2
    bil = np.full(len(days), 90.0)
    p = _run(tmp_path, days, spy, sso, bil, [days[-1]], armed="2026-09-01")
    rows = ft4.load_ledger(p)
    assert rows[0]["accounts"]["L20F"]["leg"] == "SSO"
    assert rows[-1]["accounts"]["L20F"]["leg"] == "BIL"
    assert any("BIL" in e for r in rows for e in r["events"].get("L20F", []))


def test_evaluate_waits_252_days_then_judges(tmp_path):
    days, spy, sso, bil = _market(n=700, start="2025-06-02")
    p = _run(tmp_path, days, spy, sso, bil, [days[-1]], armed="2025-06-02")
    rows = ft4.load_ledger(p)
    early = ft4.evaluate(rows[:100])
    assert early["verdict"] == "IN_PROGRESS" and "verdict" not in early["candidates"]["L20A"]
    full = ft4.evaluate(rows)
    assert full["verdict"] == "JUDGED"
    for a in ft4.JUDGED:
        assert full["candidates"][a]["verdict"] in ("PASS", "FAIL")
        assert full["candidates"][a]["irr"] is not None
    st = ft4.refresh_status(path=p, status_path=tmp_path / "status.json")
    assert ft4.load_status(tmp_path / "status.json")["records"] == st["records"]


def test_page_row_and_audit_check(monkeypatch):
    from hub import satellite_lab_page as page
    from core import engine_audit as ea

    assert "기록 대기" in page.render_tournament_v4_row({"records": 0, "registered": "2026-11-12", "min_days": 252})
    assert "확인 불가" in page.render_tournament_v4_row({"error": "OSError"})
    html = page.render_tournament_v4_row({"records": 3, "start": "2026-11-12", "last": "2026-11-16", "min_days": 252,
                                          "status": {"days": 3, "candidates": {"B0": {"label": "SPY 만", "liq_krw": 1e7, "contributed": 1.015e7},
                                                                               "L20A": {"label": "x", "liq_krw": 1.01e7, "liq_vs_b0_krw": 1e5}}}})
    assert "SPY 대비 10만" in html
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    monkeypatch.setattr(ft4, "load_ledger", lambda: [])
    monkeypatch.setattr(ft4, "load_armed", lambda: {})
    assert ea.check_forward_tournament_v4(now)["status"] == ea.OK
    assert ea.check_forward_tournament_v4(datetime(2026, 12, 1, tzinfo=timezone.utc))["status"] == ea.WARN


def test_v4_runs_after_v3_and_failure_is_isolated(tmp_path, monkeypatch):
    from core import forward_tournament as ft
    from core import forward_tournament_v2 as ft2
    from core import forward_tournament_v3 as ft3
    from core import process_registry, rnd_topics
    from scheduler import run_scheduler

    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", tmp_path / "toggles.json")
    monkeypatch.setattr(rnd_topics, "is_on", lambda key: True)
    calls, failures = [], []
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda job, msg: failures.append((job, msg)))
    for name, mod in (("v1", ft), ("v2", ft2), ("v3", ft3)):
        monkeypatch.setattr(mod, "record", lambda *a, name=name, **k: calls.append(name) or {"recorded": True, "errors": {}})
    monkeypatch.setattr(ft2, "refresh_status", lambda *a, **k: {})
    monkeypatch.setattr(ft3, "refresh_status", lambda *a, **k: {})
    monkeypatch.setattr(ft4, "refresh_status", lambda *a, **k: {})
    monkeypatch.setattr(ft4, "record", lambda *a, **k: calls.append("v4") or {"recorded": True})
    run_scheduler.forward_tournament_record_job()
    assert calls == ["v1", "v2", "v3", "v4"] and failures == []

    def boom(*a, **k):
        raise ValueError("broke")

    calls.clear()
    monkeypatch.setattr(ft4, "record", boom)
    run_scheduler.forward_tournament_record_job()
    assert calls == ["v1", "v2", "v3"] and failures == [("forward_tournament_v4_record", "ValueError: broke")]
