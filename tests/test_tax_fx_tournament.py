"""세후·환전 후 계산(core/tax_fx.py)과 앞으로 토너먼트(core/forward_tournament.py)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from core import forward_tournament as ft
from core import tax_fx as tx


def _market(n=600, start="2020-01-02", growth=0.0008):
    idx = pd.bdate_range(start, periods=n)
    a = 100 * np.exp(np.cumsum(np.full(n, growth)))
    close = pd.DataFrame({"A": a, "B": a[::-1].copy()}, index=idx)
    adj = close.copy()
    fx = pd.Series(1000.0, index=idx)
    return idx, close, adj, fx


def test_buy_and_hold_no_tax_until_sold_and_matches_pre_cost_without_costs():
    idx, close, adj, fx = _market()
    w = tx.buy_and_hold_weights(idx, "A")
    res = tx.simulate(w, close, adj, fx, tx.AccountConfig(fee_rate=0.0, fx_spread=0.0, initial_krw=10_000_000))
    assert res["totals"]["capital_gains_tax_krw"] == 0  # 팔지 않으면 양도세 없음(이연)
    assert res["final_krw"] == pytest.approx(res["final_pre_cost_krw"], rel=1e-6)
    gain = res["final_krw"] - 10_000_000
    assert res["unpaid_tax_if_sold_now_krw"] == pytest.approx(max(0, gain - 2_500_000) * 0.22, rel=1e-6)


def test_annual_tax_on_realized_gains_with_deduction():
    idx, close, adj, fx = _market(n=700, start="2021-01-04")  # 2023-09 까지 — 2022년 이익의 세금은 2023-05 에 낸다
    # 매년 1월 첫 거래일에 A ↔ B 를 바꿔 이익을 실현
    w = pd.DataFrame(0.0, index=idx, columns=["A", "B"])
    for y in sorted(set(idx.year)):
        w.loc[w.index.year == y, "A" if y % 2 else "B"] = 1.0
    res = tx.simulate(w, close, adj, fx, tx.AccountConfig(fee_rate=0.0, fx_spread=0.0, initial_krw=100_000_000))
    y2022 = next(r for r in res["years"] if r["year"] == 2022)  # 2022-01 첫 거래일에 A 를 팔아 2021년 상승분 실현
    assert y2022["realized_gain_krw"] > 2_500_000
    assert y2022["tax_krw"] == pytest.approx((y2022["realized_gain_krw"] - 2_500_000) * 0.22)
    assert any(p["for_year"] == 2022 and p["date"].startswith("2023-05") for p in res["tax_payments"])


def test_fx_each_trade_costs_more_than_holding_usd():
    idx, close, adj, fx = _market()
    w = pd.DataFrame(0.0, index=idx, columns=["A", "B"])
    w.loc[w.index.month % 2 == 0, "A"] = 1.0
    w.loc[w.index.month % 2 == 1, "B"] = 1.0
    hold = tx.simulate(w, close, adj, fx, tx.AccountConfig(fx_mode="usd_hold", fx_spread=0.0005))
    each = tx.simulate(w, close, adj, fx, tx.AccountConfig(fx_mode="krw_each_trade", fx_spread=0.01))
    assert each["totals"]["fx_cost_krw"] > 10 * hold["totals"]["fx_cost_krw"]
    assert each["final_krw"] < hold["final_krw"]


def test_dividend_reconstructed_and_withheld():
    idx = pd.bdate_range("2022-01-03", periods=10)
    close = pd.DataFrame({"A": [100.0] * 10}, index=idx)
    adj = close.copy()
    adj.iloc[:5] = 98.0  # 5번째 날 2% 배당 → 조정가 과거값이 낮다
    res = tx.simulate(tx.buy_and_hold_weights(idx, "A"), close, adj, pd.Series(1000.0, index=idx),
                      tx.AccountConfig(fee_rate=0.0, fx_spread=0.0, initial_krw=1_000_000))
    assert res["totals"]["dividend_tax_krw"] > 0
    assert res["final_krw"] > 1_000_000  # 배당의 85% 가 현금으로 남는다


def test_fifo_and_average_cost_basis_differ():
    pos_a, pos_f = tx._Pos(), tx._Pos()
    pos_a.buy(1, 100, "average")
    pos_a.buy(1, 200, "average")
    pos_f.buy(1, 100, "fifo")
    pos_f.buy(1, 200, "fifo")
    assert pos_a.sell(1) == pytest.approx(150) and pos_f.sell(1) == pytest.approx(100)


# ---------------------------------------------------------------- 토너먼트
def _rows(days, weights_by_cid):
    return [{"date": str(d.date()), "weights": weights_by_cid} for d in days]


def test_tournament_waits_then_judges_against_baseline():
    idx = pd.bdate_range("2026-10-06", periods=300)
    rets = pd.DataFrame({"X": 0.001, "Y": 0.0003, "SPY": 0.0005, "IEF": 0.0001, "BIL": 0.0001}, index=idx)
    weights = {cid: {"Y": 1.0} for cid in ft.CANDIDATES}
    weights["T2"] = {"X": 1.0}
    rows = _rows(idx, weights)
    early = ft.evaluate(rows[:30], rets)
    assert early["candidates"]["T2"]["verdict"].startswith("판정 전") and early["candidates"]["T0"]["verdict"] == "기준선"
    full = ft.evaluate(rows, rets)
    assert full["candidates"]["T2"]["excess_vs_T0"] > 0
    assert full["candidates"]["T1"]["verdict"] == "FAIL"  # 기준선과 똑같으면 초과 0 → 실패
    rng = np.random.default_rng(1)
    noisy = rets.copy()
    noisy["X"] = 0.0003 + rng.normal(0, 0.03, len(idx))
    assert ft.evaluate(rows, noisy)["candidates"]["T2"]["verdict"] in ("PASS", "FAIL")


def test_tournament_record_append_only(tmp_path, monkeypatch):
    led = tmp_path / "l.jsonl"
    idx = pd.bdate_range("2025-01-01", "2026-10-05")
    rng = np.random.default_rng(2)

    def price_fn(tickers):
        out = {}
        for t in tickers:
            c = 50 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(idx))))
            out[t] = pd.DataFrame({"Close": c, "Adj Close": c}, index=idx)
        return out

    first = ft.record(path=led, price_fn=price_fn)
    again = ft.record(path=led, price_fn=price_fn)
    assert first["recorded"] and not again["recorded"]
    row = ft.load_ledger(led)[0]
    assert set(row["weights"]) == set(ft.CANDIDATES)
    assert all(abs(sum(w.values()) - 1.0) < 1e-6 for w in row["weights"].values())


def test_tournament_record_job_registered_and_topic_switch():
    from core import rnd_topics
    from core.job_schedule import SCHEDULED_JOBS_BY_ID
    from core.process_registry import PROCESS_REGISTRY

    assert SCHEDULED_JOBS_BY_ID["forward_tournament_record"].cron == {"hour": 0, "minute": 39, "timezone": "Asia/Seoul"}
    assert PROCESS_REGISTRY["forward_tournament_record"]["default_enabled"] is True
    assert "forward_tournament" in rnd_topics.TOPICS


def test_tax_page_is_in_navigation():
    from core.app_navigation import all_pages

    assert any(p.path == "pages/16_세후_수익_계산.py" for p in all_pages())
