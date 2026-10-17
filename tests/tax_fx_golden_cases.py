"""tax_fx.simulate 회귀 고정용 합성 입력(2026-10-17, 월 적립 기능 추가 전 출력을 고정).

tests/fixtures/tax_fx_golden.json 은 월 적립 기능을 넣기 전 core/tax_fx.py 로 이 사례들을 돌린 값이다.
적립금 0 이면 지금 코드도 같은 값을 내야 한다(tests/test_tax_fx_contributions.py).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def market(seed: int = 11, n: int = 900, start: str = "2019-01-02") -> tuple:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    cols = ["A", "B", "C"]
    rets = rng.normal([0.0006, 0.0002, 0.0004], [0.012, 0.009, 0.015], size=(n, 3))
    close = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=cols)
    # 분기마다 배당(조정가가 과거로 갈수록 낮다)
    adj = close.copy()
    for k in range(60, n, 63):
        adj.iloc[:k] *= 0.99
    fx = pd.Series(1100 + 100 * np.sin(np.arange(n) / 90.0) + rng.normal(0, 3, n), index=idx)
    return idx, close, adj, fx


def weights(idx: pd.DatetimeIndex, kind: str) -> pd.DataFrame:
    w = pd.DataFrame(0.0, index=idx, columns=["A", "B", "C"])
    if kind == "rotate":
        m = idx.month
        w.loc[m % 3 == 0, "A"] = 1.0
        w.loc[m % 3 == 1, ["B", "C"]] = [0.6, 0.4]
        w.loc[m % 3 == 2, ["A", "C"]] = [0.5, 0.5]
    elif kind == "cash":
        w.loc[:, ["A", "B"]] = [0.5, 0.3]  # 20% 현금 목표
        w.loc[idx.month % 4 == 0, ["A", "B", "C"]] = [0.2, 0.2, 0.4]
    elif kind == "hold":
        w["A"] = 1.0
    return w


CASES = {
    "rotate_default": ("rotate", {}),
    "rotate_krw_fifo": ("rotate", {"fx_mode": "krw_each_trade", "cost_basis": "fifo", "fx_spread": 0.01}),
    "cash_integer": ("cash", {"integer_shares": True, "initial_krw": 50_000_000}),
    "hold_harvest_gains": ("hold", {"harvest_gains": True, "initial_krw": 80_000_000}),
    "rotate_harvest_losses": ("rotate", {"harvest_losses": True, "initial_krw": 200_000_000}),
    "cash_no_reinvest": ("cash", {"reinvest_dividends": False, "apply_dividend_tax": False}),
}


def summarize(res: dict) -> dict:
    v, b = res["values_krw"], res["pre_cost_krw"]
    pick = list(range(0, len(v), 37)) + [len(v) - 1]
    return {
        "final_krw": res["final_krw"], "final_pre_cost_krw": res["final_pre_cost_krw"],
        "cagr_after": res["cagr_after"], "cagr_pre": res["cagr_pre"],
        "mdd_after": res["mdd_after"], "mdd_pre": res["mdd_pre"],
        "totals": res["totals"], "unpaid_tax_if_sold_now_krw": res["unpaid_tax_if_sold_now_krw"],
        "final_after_liquidation_krw": res["final_after_liquidation_krw"],
        "years": res["years"], "tax_payments": res["tax_payments"], "harvests": res["harvests"],
        "values_sum": float(v.sum()), "pre_sum": float(b.sum()),
        "values_pick": [float(v.iloc[i]) for i in pick], "pre_pick": [float(b.iloc[i]) for i in pick],
    }
