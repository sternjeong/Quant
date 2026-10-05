"""내 계좌 세금 플래너(core/tax_planner.py) — 원화 취득가, 매도별 차익, 공제 잔액, 연말 제안, 입력 저장."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from core import tax_planner as tp

FX = pd.Series([1000.0, 1200.0, 1300.0], index=pd.to_datetime(["2025-01-02", "2025-06-02", "2026-10-02"]))


def _holdings():
    return [
        {"ticker": "AAA", "quantity": 10, "purchase_price": 100.0, "purchase_date": date(2025, 1, 10)},
        {"ticker": "AAA", "quantity": 10, "purchase_price": 120.0, "purchase_date": date(2025, 7, 1)},
        {"ticker": "BBB", "quantity": 5, "purchase_price": 200.0, "purchase_date": date(2025, 1, 10)},
    ]


def test_positions_use_purchase_date_fx_and_average_cost():
    pos = {p["ticker"]: p for p in tp.positions(_holdings(), {"AAA": 150.0, "BBB": 150.0}, FX, fee_rate=0.0)}
    a = pos["AAA"]
    assert a["shares"] == 20
    assert a["cost_krw"] == pytest.approx(10 * 100 * 1000 + 10 * 120 * 1200)
    assert a["gain_krw"] == pytest.approx(20 * 150 * 1300 - a["cost_krw"])  # 환율 이익도 과세 대상
    assert pos["BBB"]["gain_krw"] == pytest.approx(5 * 150 * 1300 - 5 * 200 * 1000)


def test_sell_estimates_and_year_summary():
    pos = tp.positions(_holdings(), {"AAA": 150.0, "BBB": 150.0}, FX, fee_rate=0.0)
    rows = [{"ticker": "AAA", "action": "매도", "shares": 4}, {"ticker": "BBB", "action": "전량 매도", "shares": 5},
            {"ticker": "CCC", "action": "매수", "shares": 3}]
    est = {e["ticker"]: e for e in tp.sell_estimates(rows, pos)}
    assert set(est) == {"AAA", "BBB"}
    aaa = next(p for p in pos if p["ticker"] == "AAA")
    assert est["AAA"]["gain_krw"] == pytest.approx(4 * aaa["gain_per_share_krw"])
    s = tp.year_summary(1_000_000, 2_000_000, 2026)
    assert s["deduction_left_krw"] == 0 and s["tax_krw"] == pytest.approx(500_000 * 0.22) and s["due"] == "2027-05-31"
    assert tp.year_summary(None, 0, 2026)["deduction_left_krw"] == 2_500_000


def test_gain_harvest_fills_deduction_only_late_in_year():
    pos = tp.positions(_holdings(), {"AAA": 150.0, "BBB": 150.0}, FX, fee_rate=0.0)
    early = tp.harvest_suggestions(pos, 0.0, date(2026, 10, 5))
    late = tp.harvest_suggestions(pos, 0.0, date(2026, 12, 10))
    assert early["kind"] == "gain" and not early["actionable"] and late["actionable"]
    assert 0 < sum(r["realize_krw"] for r in late["rows"]) <= 2_500_000
    assert all(r["ticker"] == "AAA" for r in late["rows"])  # 이익 난 종목만


def test_loss_harvest_when_over_deduction():
    pos = tp.positions(_holdings(), {"AAA": 150.0, "BBB": 100.0}, FX, fee_rate=0.0)  # BBB 손실
    sug = tp.harvest_suggestions(pos, 3_000_000, date(2026, 12, 10))
    assert sug["kind"] == "loss" and sug["rows"][0]["ticker"] == "BBB"
    assert sum(-r["realize_krw"] for r in sug["rows"]) <= 500_000 + 1
    assert sug["tax_saved_krw"] > 0


def test_realized_input_round_trip(tmp_path):
    p = tmp_path / "tax_year.json"
    assert tp.load_realized(2026, p) is None
    tp.save_realized(2026, 1_234_000, p)
    assert tp.load_realized(2026, p) == 1_234_000


def test_year_end_reminder_window():
    assert tp.year_end_reminder_line(date(2026, 10, 5)) is None
    assert tp.year_end_reminder_line(date(2026, 11, 20))
    assert tp.year_end_reminder_line(date(2026, 12, 28)) is None
