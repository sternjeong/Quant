"""core/paper_tracking.py — 기대값은 손계산."""

from datetime import date, timedelta

import pytest

from core import paper_tracking as pt


def d(i):
    return date(2026, 10, 1) + timedelta(days=i)


def test_intervals_and_gap_hand_computed():
    paper = [(d(0), 100.0), (d(1), 101.0), (d(3), 101.0)]         # +1%, 0%
    champ = [(d(1), 2.0), (d(2), 1.0), (d(3), -1.0)]              # 구간2 = 1.01*0.99-1 = -0.01%
    r = pt.compute_tracking(paper, champ)
    assert r["n_intervals"] == 2
    assert r["intervals"][0]["diff_pct_points"] == pytest.approx(-1.0)
    assert r["intervals"][1]["ledger_days"] == 2
    assert r["intervals"][1]["champion_return_pct"] == pytest.approx(-0.01)
    assert r["paper_cum_return_pct"] == pytest.approx(1.0)
    assert r["champion_cum_return_pct"] == pytest.approx((1.02 * 0.9999 - 1) * 100, abs=1e-3)
    assert r["tracking_error_annual_pct"] is None and r["te_status"] == "insufficient_sample"


def test_interval_without_ledger_is_skipped_and_te_needs_20():
    assert pt.compute_tracking([(d(0), 100.0), (d(1), 101.0)], [])["n_intervals"] == 0
    paper = [(d(i), 100.0 * (1.001 ** i)) for i in range(22)]
    champ = [(d(i), 0.1) for i in range(1, 22)]
    r = pt.compute_tracking(paper, champ)
    assert r["n_intervals"] == 21
    assert r["tracking_error_annual_pct"] == pytest.approx(0.0, abs=1e-6)  # 완전 추종 → 0


def test_refresh_reads_db_and_saves(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.models import AccountSnapshot, Base, ChampionLedgerEntry

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    db.add_all([AccountSnapshot(as_of=d(0), source="alpaca_paper", equity=100.0, n_positions=2, drift_summary="{}"),
                AccountSnapshot(as_of=d(1), source="alpaca_paper", equity=102.0, n_positions=2,
                                drift_summary='{"max_abs_drift_pct_points": 3.5}'),
                ChampionLedgerEntry(entry_date=d(1), realized_return_pct=1.0)])
    db.commit()
    r = pt.refresh_paper_tracking(session=db, save_path=tmp_path / "t.json")
    assert r["cum_gap_pct_points"] == pytest.approx(1.0)
    assert r["context"]["following"] is True and r["context"]["latest_drift"]["max_abs_drift_pct_points"] == 3.5
    assert (tmp_path / "t.json").exists()
    assert "괴리 +1.00%p" in pt.summarize(r)
