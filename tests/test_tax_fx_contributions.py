"""core/tax_fx.py 월 적립: 적립금 0의 운용 경로 보존, 청산 회계, 적립 정책·XIRR·취득가."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core import tax_fx as tx
from tests import tax_fx_golden_cases as g

GOLDEN = Path(__file__).parent / "fixtures" / "tax_fx_golden.json"


def _close(a, b, tol=1e-12):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        for k in a:
            _close(a[k], b[k], tol)
    elif isinstance(a, list):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            _close(x, y, tol)
    elif isinstance(a, float) or isinstance(b, float):
        if np.isnan(a) and np.isnan(b):
            return
        assert a == pytest.approx(b, rel=tol, abs=1e-6 * tol), (a, b)
    else:
        assert a == b


@pytest.mark.parametrize("name", list(g.CASES))
def test_zero_contribution_preserves_account_path_with_corrected_exit(name):
    gold = json.loads(GOLDEN.read_text())[name]
    idx, close, adj, fx = g.market()
    kind, over = g.CASES[name]
    res = tx.simulate(g.weights(idx, kind), close, adj, fx, tx.AccountConfig(**over))
    summary = g.summarize(res)
    # 2026-10-22에 종료 청산 회계만 수정했다. 과거 golden은 운용 중 경로의 회귀 기준이다.
    for key in ("unpaid_tax_if_sold_now_krw", "final_after_liquidation_krw"):
        summary.pop(key)
        gold.pop(key)
    _close(summary, gold)
    assert res["total_contributed_krw"] == res["config"]["initial_krw"]
    assert float(res["contributions_krw"].sum()) == 0.0
    assert res["terminal_after_liquidation_krw"] == res["final_after_liquidation_krw"]
    assert res["unpaid_tax_if_sold_now_krw"] == pytest.approx(
        res["unpaid_prior_year_tax_krw"] + res["liquidation_current_year_tax_krw"])
    assert res["final_after_liquidation_krw"] == pytest.approx(
        res["final_krw"] - res["unpaid_tax_if_sold_now_krw"]
        - res["liquidation_trade_fees_krw"] - res["liquidation_fx_cost_krw"])


def _cfg(**kw):
    base = dict(fee_rate=0.0, fx_spread=0.0, apply_tax=False, apply_dividend_tax=False, initial_krw=1_000_000)
    return tx.AccountConfig(**{**base, **kw})


def test_contribution_days_first_trading_day_of_each_month_after_start():
    idx = pd.bdate_range("2022-01-03", "2022-04-15")
    d = idx[tx.contribution_days(idx)]
    assert [str(x.date()) for x in d] == ["2022-02-01", "2022-03-01", "2022-04-01"]


def test_allocate_underweight_first_by_shortfall_and_remainder_pro_rata():
    # 목표 50/50, 지금 A 600 B 300, 새 돈 100 → 총 1000, 모자람 A 0 B 200 → 전부 B
    a = tx.allocate_contribution("underweight_first", np.array([0.5, 0.5]), np.array([600.0, 300.0]), 1000.0, 100.0, 100.0)
    assert a == pytest.approx([0.0, 100.0])
    # 모자람 A 50 B 150, 새 돈 100 → 25 / 75
    a = tx.allocate_contribution("underweight_first", np.array([0.5, 0.5]), np.array([450.0, 350.0]), 1000.0, 200.0, 100.0)
    assert a == pytest.approx([25.0, 75.0])
    # 현금 목표 20%: 총 1000, 현금 300(새 돈 100 포함) → 쓸 수 있는 돈 = min(100, 300 − 200) = 100
    a = tx.allocate_contribution("underweight_first", np.array([0.4, 0.4]), np.array([400.0, 300.0]), 1000.0, 300.0, 100.0)
    assert a == pytest.approx([0.0, 100.0])
    # 현금이 이미 목표 이하면 사지 않는다
    a = tx.allocate_contribution("underweight_first", np.array([0.4, 0.4]), np.array([450.0, 400.0]), 1000.0, 150.0, 100.0)
    assert a == pytest.approx([0.0, 0.0])
    # 모자람 합보다 쓸 돈이 많으면(수치상) 남는 돈은 목표 비중대로
    a = tx.allocate_contribution("underweight_first", np.array([0.75, 0.25]), np.array([0.0, 0.0]), 100.0, 300.0, 300.0)
    assert a.sum() == pytest.approx(300.0) and a == pytest.approx([225.0, 75.0])


def test_allocate_pro_rata_and_bad_policy():
    a = tx.allocate_contribution("pro_rata", np.array([0.6, 0.2]), np.array([10.0, 900.0]), 1000.0, 100.0, 100.0)
    assert a == pytest.approx([60.0, 20.0])  # 현금 목표 20% 는 현금으로
    with pytest.raises(ValueError):
        tx.allocate_contribution("nope", np.array([1.0]), np.array([0.0]), 1.0, 1.0, 1.0)
    i3 = pd.bdate_range("2022-01-03", periods=3)
    one = pd.DataFrame({"A": 1.0}, index=i3)
    with pytest.raises(ValueError):
        tx.simulate(one, one, one, pd.Series(1000.0, index=i3), _cfg(contribution_policy="x"))


def _two_asset_drift():
    """A 는 1월에 두 배, B 는 그대로 → 2월 첫날 A 과체중."""
    idx = pd.bdate_range("2022-01-03", "2022-03-15")
    a = np.where(idx < "2022-01-20", 100.0, 200.0)
    close = pd.DataFrame({"A": a, "B": 100.0}, index=idx)
    w = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    return idx, close, w


def test_underweight_first_buys_only_the_underweight_holding():
    idx, close, w = _two_asset_drift()
    res = tx.simulate(w, close, close, pd.Series(1000.0, index=idx), _cfg(monthly_contribution_krw=100_000))
    # 처음 1,000,000원 = 1000달러 → A 5주 B 5주. 2월 1일 A 1000 B 500, 새 돈 100달러 → 전부 B
    feb = pd.Timestamp("2022-02-01")
    assert res["contributions_krw"].loc[feb] == 100_000
    assert res["values_krw"].loc[feb] == pytest.approx((1000 + 500 + 100) * 1000)
    assert res["total_contributed_krw"] == pytest.approx(1_000_000 + 2 * 100_000)
    # 세전 기준선도 같은 돈을 받는다(비용 없음 → 계좌와 같다)
    assert res["final_pre_cost_krw"] == pytest.approx(res["final_krw"], rel=1e-12)
    # 매도가 없으므로 실현 이익 0
    assert sum(r["realized_gain_krw"] for r in res["years"]) == 0


def test_pro_rata_vs_underweight_first_share_counts():
    idx, close, w = _two_asset_drift()
    fx = pd.Series(1000.0, index=idx)
    res_u = tx.simulate(w, close, close, fx, _cfg(monthly_contribution_krw=100_000, apply_tax=True))
    res_p = tx.simulate(w, close, close, fx, _cfg(monthly_contribution_krw=100_000, apply_tax=True,
                                                  contribution_policy="pro_rata"))
    # 3월 1일 이후 A 가격 200 그대로 → 두 정책의 최종값은 같고(가격 변화 없음) 미실현 이익도 같다
    assert res_u["final_krw"] == pytest.approx(res_p["final_krw"])
    # pro_rata 는 A 를 2월·3월에 50달러씩 더 산다 → A 평균 취득가가 다르다 → 청산 세금 계산의 미실현 이익은 같지만 보유 구성은 다르다
    # 구성 차이는 A 가격이 오르면 드러난다
    close2 = close.copy()
    close2.loc[close2.index >= "2022-03-10", "A"] = 300.0
    u = tx.simulate(w, close2, close2, fx, _cfg(monthly_contribution_krw=100_000))
    p = tx.simulate(w, close2, close2, fx, _cfg(monthly_contribution_krw=100_000, contribution_policy="pro_rata"))
    # A 주수: underweight_first 5주, pro_rata 5 + 0.25 + 0.25 = 5.5주 → 3/10 이후 차이 = 0.5 × 100달러
    assert (p["final_krw"] - u["final_krw"]) == pytest.approx(0.5 * 100 * 1000)


def test_contribution_and_rebalance_same_day_adds_cash_first_and_sells_less():
    idx, close, w = _two_asset_drift()
    w = w.copy()
    w.loc[w.index >= "2022-02-01", ["A", "B"]] = [0.4, 0.6]  # 2월 1일에 목표도 바뀐다
    fx = pd.Series(1000.0, index=idx)
    c0 = tx.simulate(w, close, close, fx, _cfg(apply_tax=True))
    c1 = tx.simulate(w, close, close, fx, _cfg(apply_tax=True, monthly_contribution_krw=300_000))
    feb = pd.Timestamp("2022-02-01")
    # 적립 없음: 총 1500 → A 목표 600, A 1000 에서 400 매도. 적립 300: 총 1800 → A 목표 720, 280 매도
    g0 = next(r for r in c0["years"] if r["year"] == 2022)["realized_gain_krw"]
    g1 = next(r for r in c1["years"] if r["year"] == 2022)["realized_gain_krw"]
    # A 취득가 100, 매도가 200 → 400달러 = 2주, 280달러 = 1.4주, 차익 = 주수 × 100달러 × 1000원
    assert g0 == pytest.approx(2 * 100 * 1000)
    assert g1 == pytest.approx(1.4 * 100 * 1000)
    assert c1["values_krw"].loc[feb] == pytest.approx(1_800_000)


def test_contributions_converted_with_fx_spread_in_usd_hold_and_kept_krw_in_each_trade():
    idx, close, w = _two_asset_drift()
    fx = pd.Series(1000.0, index=idx)
    hold = tx.simulate(w, close, close, fx, _cfg(fx_spread=0.01, monthly_contribution_krw=101_000))
    # 처음 목돈 환전 비용은 기존대로 totals 에 넣지 않는다, 적립금 환전 비용만 1,000원 × 2번
    assert hold["totals"]["fx_cost_krw"] == pytest.approx(2 * 101_000 * 0.01 / 1.01)
    each = tx.simulate(w, close, close, fx, _cfg(fx_mode="krw_each_trade", fx_spread=0.01, monthly_contribution_krw=101_000))
    assert each["total_contributed_krw"] == pytest.approx(1_202_000)
    assert each["final_krw"] < each["total_contributed_krw"] + 1_000_000  # 다 투자되고 남은 원화 현금 거의 없음
    assert each["values_krw"].iloc[-1] > 0


def test_xirr_hand_computed():
    t0, t1, t2 = pd.Timestamp("2021-01-01"), pd.Timestamp("2022-01-01"), pd.Timestamp("2023-01-01")  # 365일씩
    assert tx.xirr([(t0, -100.0), (t1, 110.0)]) == pytest.approx(0.10, abs=1e-10)
    # −1000 오늘, −1000 1년 뒤, +2310 2년 뒤 → (1+r)² + (1+r) = 2.31 → 1+r = 1.1
    flows = [(t0, -1000.0), (t1, -1000.0), (t2, 2310.0)]
    assert tx.xirr(flows) == pytest.approx(0.10, abs=1e-10)
    assert np.isnan(tx.xirr([(t0, -1.0)]))


def test_irr_after_liquidation_matches_cash_flows():
    idx = pd.bdate_range("2021-01-04", "2023-12-29")
    a = 100 * np.exp(np.linspace(0, 0.6, len(idx)))
    close = pd.DataFrame({"A": a}, index=idx)
    fx = pd.Series(1200.0, index=idx)
    cfg = tx.AccountConfig(initial_krw=10_000_000, monthly_contribution_krw=150_000)
    res = tx.simulate(tx.buy_and_hold_weights(idx, "A"), close, close, fx, cfg)
    flows = [(idx[0], -10_000_000.0)] + [(d, -150_000.0) for d in idx[tx.contribution_days(idx)]]
    flows.append((idx[-1], res["terminal_after_liquidation_krw"]))
    r = res["irr_after_liquidation"]
    t0 = idx[0]
    npv = sum(v / (1 + r) ** ((d - t0).days / 365.0) for d, v in flows)
    assert abs(npv) < 1e-3
    assert res["total_contributed_krw"] == pytest.approx(10_000_000 + 35 * 150_000)
    # 시간가중 지수는 적립금과 무관: 같은 계좌를 적립 없이 굴린 지수와 거의 같다(수수료·스프레드 비례라 비슷)
    base = tx.simulate(tx.buy_and_hold_weights(idx, "A"), close, close, fx, tx.AccountConfig(initial_krw=10_000_000))
    assert res["twr_index"].iloc[-1] == pytest.approx(base["twr_index"].iloc[-1], rel=2e-3)
    # 적립 없는 계좌의 IRR 은 청산 후 연수익률(365일 기준)과 같다
    yrs = (idx[-1] - idx[0]).days / 365.0
    assert base["irr_after_liquidation"] == pytest.approx((base["final_after_liquidation_krw"] / 10_000_000) ** (1 / yrs) - 1, rel=1e-9)


@pytest.mark.parametrize("basis", ["average", "fifo"])
def test_tax_lots_with_contributions(basis):
    idx = pd.bdate_range("2022-01-03", "2022-03-31")
    px = np.where(idx < "2022-02-01", 100.0, np.where(idx < "2022-03-01", 200.0, 400.0))
    close = pd.DataFrame({"A": px}, index=idx)
    fx = pd.Series(1000.0, index=idx)
    w = pd.DataFrame({"A": 1.0}, index=idx)
    w.loc[w.index >= "2022-03-15", "A"] = 0.5  # 3/15 에 절반 매도
    res = tx.simulate(w, close, close, fx, _cfg(apply_tax=True, cost_basis=basis, monthly_contribution_krw=200_000))
    # 보유: 10주 @100, 2/1 1주 @200, 3/1 0.5주 @400 → 11.5주, 3/15 가치 4600달러 → 2300달러(5.75주) 매도
    sold = 5.75
    cost = 5.75 * (1000 + 200 + 200) / 11.5 if basis == "average" else 5.75 * 100
    gain = (sold * 400 - cost) * 1000
    r = next(x for x in res["years"] if x["year"] == 2022)["realized_gain_krw"]
    assert r == pytest.approx(gain)


def test_contribution_baseline_path_matches_old_baseline_when_flows_are_zero():
    idx, close, adj, fx = g.market()
    w = g.weights(idx, "cash")
    old = tx.simulate(w, close, adj, fx, tx.AccountConfig())["pre_cost_krw"]
    change = w.diff().abs().sum(axis=1) > 1e-9
    change.iloc[0] = True
    tr = adj.reindex(index=idx, columns=w.columns).pct_change(fill_method=None).fillna(0.0)
    new = tx._pre_cost_with_contributions(w, change, tr, fx, 30_000_000, np.zeros(len(idx)), "underweight_first")
    assert np.allclose(new.to_numpy(), old.to_numpy(), rtol=1e-12, atol=0)
