"""core/rolling_eval.py — 여러 시작일 × 월 적립 비교(2026-10-17)."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from core import rolling_eval as re_
from core import tax_fx as tx


def _panels(n_years=6, start="2015-01-02", seed=1, strat_drift=0.0006, spy_drift=0.0003):
    idx = pd.bdate_range(start, periods=int(252 * n_years))
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 0.008, len(idx))
    spy = 100 * np.exp(np.cumsum(spy_drift + noise))
    x = 100 * np.exp(np.cumsum(strat_drift + noise))  # 같은 잡음, 다른 기울기
    close = pd.DataFrame({"SPY": spy, "X": x}, index=idx)
    return {"close": close, "adj": close.copy(), "fx": pd.Series(1200.0, index=idx)}


CFG = tx.AccountConfig(initial_krw=10_000_000, monthly_contribution_krw=150_000)


def test_rolling_windows_monthly_first_trading_days():
    days = pd.bdate_range("2010-01-04", "2014-06-30")
    w = re_.rolling_windows(days, 3, step="M")
    assert w[0] == (pd.Timestamp("2010-01-04"), pd.Timestamp("2013-01-04"))  # 시작 + 3년 이하 마지막 거래일
    assert all(s.day <= 4 and s == days[days >= s.replace(day=1)][0] for s, _ in w)
    assert w[-1][0] == pd.Timestamp("2011-06-01")  # 2014-06-01 + 3년 이 데이터 안에서 끝나는 마지막 시작
    assert len(w) == 18
    q = re_.rolling_windows(days, 3, step="Q")
    assert [str(s.date()) for s, _ in q][:3] == ["2010-01-04", "2010-04-01", "2010-07-01"]
    lim = re_.rolling_windows(days, 1, first_start="2011-02-15", last_start="2011-05-02")
    assert [str(s.date()) for s, _ in lim] == ["2011-03-01", "2011-04-01", "2011-05-02"]
    # 데이터 첫날이 그달 중간이면 시작으로 치지 않는다
    assert re_.rolling_windows(pd.bdate_range("2010-01-15", "2012-03-01"), 1)[0][0] == pd.Timestamp("2010-02-01")


def test_benchmark_gets_identical_contributions_and_dominant_strategy_wins():
    p = _panels()
    wins = re_.rolling_windows(p["close"].index, 2, step="Q")
    strat = tx.buy_and_hold_weights(p["close"].index, "X")
    res = re_.evaluate_windows(strat, p, wins, CFG)
    assert res["complete"] and res["done"] == len(wins) and res["new_sims"] == 2 * len(wins)
    for r in res["rows"]:
        assert r["strategy"]["total_contributed_krw"] == r["benchmark"]["total_contributed_krw"]
        assert r["strategy"]["total_contributed_krw"] > 10_000_000
    s = re_.summarize(res)
    assert s["share_terminal_win"] == 1.0 and s["p10_diff_irr"] > 0
    assert s["effective_independent_windows"] == pytest.approx(s["span_years"] / 2, rel=0.05)
    assert "overlap" in s["overlap_caveat"]
    # 반대로 기울기가 낮은 전략은 진다
    q = _panels(strat_drift=0.0, spy_drift=0.0006)
    lose = re_.summarize(re_.evaluate_windows(lambda a, b: tx.buy_and_hold_weights(q["close"].loc[a:b].index, "X"),
                                              q, wins, lambda a, b: CFG))
    assert lose["share_terminal_win"] == 0.0 and lose["worst_window"]["diff_irr"] < 0


def test_same_strategy_as_benchmark_ties():
    p = _panels(strat_drift=0.0003)
    wins = re_.rolling_windows(p["close"].index, 2, step="A")
    res = re_.evaluate_windows(tx.buy_and_hold_weights(p["close"].index, "SPY"), p, wins, CFG)
    for r in res["rows"]:
        assert r["diff_terminal_krw"] == pytest.approx(0.0, abs=1e-6) and not r["win"]


def test_resume_from_cache_dict_and_file(tmp_path):
    p = _panels()
    wins = re_.rolling_windows(p["close"].index, 2, step="A")
    strat = tx.buy_and_hold_weights(p["close"].index, "X")
    path = tmp_path / "ck" / "win.pkl"
    first = re_.evaluate_windows(strat, p, wins, CFG, cache_path=path, fingerprint="v1", max_new=3)
    assert not first["complete"] and first["pending"] > 0 and path.exists()
    second = re_.evaluate_windows(strat, p, wins, CFG, cache_path=path, fingerprint="v1")
    assert second["complete"] and second["new_sims"] == 2 * len(wins) - first["new_sims"]
    full = re_.evaluate_windows(strat, p, wins, CFG)
    assert [r["diff_irr"] for r in second["rows"]] == pytest.approx([r["diff_irr"] for r in full["rows"]])
    # 지문이 다르면 캐시를 버린다
    again = re_.evaluate_windows(strat, p, wins, CFG, cache_path=path, fingerprint="v2", max_new=0)
    assert again["done"] == 0
    # dict 캐시 + 시간 한도
    cache: dict = {}
    r1 = re_.evaluate_windows(strat, p, wins, CFG, cache=cache, deadline=time.monotonic() - 1)
    assert r1["done"] == 0 and not r1["complete"]
    r2 = re_.evaluate_windows(strat, p, wins, CFG, cache=cache)
    r3 = re_.evaluate_windows(strat, p, wins, CFG, cache=cache, max_new=0)
    assert r2["complete"] and r3["complete"] and r3["new_sims"] == 0
    # 기준 캐시를 다른 전략과 함께 쓴다
    shared: dict = {}
    re_.evaluate_windows(strat, p, wins, CFG, benchmark_cache=shared)
    other = re_.evaluate_windows(tx.buy_and_hold_weights(p["close"].index, "SPY"), p, wins, CFG, benchmark_cache=shared)
    assert other["new_sims"] == len(wins)


def test_index_sim_contribution_math():
    idx = pd.bdate_range("2020-01-01", "2020-04-30")  # 1/1 시작 → 2/3, 3/2, 4/1 적립
    r = pd.DataFrame({"A": 0.0, "B": 0.0}, index=idx)
    r.loc["2020-01-15", "A"] = 1.0  # A 두 배
    out = re_.index_sim(r, {"A": 0.5, "B": 0.5}, 0.1, initial=100.0)
    assert out["total_contributed"] == pytest.approx(130.0)
    # 1/15 뒤 A 100 B 50, 2/3 적립 10 → 모자란 B 에만
    assert out["values"].loc["2020-02-03"] == pytest.approx(160.0)
    assert out["terminal"] == pytest.approx(180.0)
    pr = re_.index_sim(r, {"A": 0.5, "B": 0.5}, 0.1, initial=100.0, policy="pro_rata")
    assert pr["terminal"] == pytest.approx(180.0)
    # 비용 10bp: 첫 매수 100 × 0.001, 적립 30 × 0.001
    c = re_.index_sim(r, {"A": 0.5, "B": 0.5}, 0.1, initial=100.0, cost_bps=10)
    assert c["terminal"] < out["terminal"]
    # 시간가중 지수 = 적립과 무관한 전략 수익
    assert out["twr_index"].iloc[-1] == pytest.approx(1.5)
    no = re_.index_sim(r, {"A": 0.5, "B": 0.5}, 0.0, initial=100.0)
    assert no["terminal"] == pytest.approx(150.0) and no["total_contributed"] == 100.0


def test_index_sim_matches_tax_fx_pre_cost_baseline():
    rng = np.random.default_rng(4)
    idx = pd.bdate_range("2018-01-02", periods=700)
    r = pd.DataFrame(rng.normal(0.0004, 0.01, (len(idx), 3)), index=idx, columns=["A", "B", "C"])
    w = pd.DataFrame(0.0, index=idx, columns=["A", "B", "C"])
    w.loc[idx.month % 2 == 0, ["A", "B"]] = [0.6, 0.3]
    w.loc[idx.month % 2 == 1, ["B", "C"]] = [0.5, 0.5]
    out = re_.index_sim(r, w, 0.015, initial=1.0)
    lev = (1 + r).cumprod()
    cfg = tx.AccountConfig(initial_krw=10_000_000, monthly_contribution_krw=150_000)
    s = tx.simulate(w, lev, lev, pd.Series(1300.0, index=idx), cfg)
    assert out["values"].iloc[-1] * 10_000_000 == pytest.approx(s["final_pre_cost_krw"], rel=1e-9)


def test_index_sim_approximate_tax_applied():
    idx = pd.bdate_range("2015-01-02", periods=252 * 5)
    r = pd.DataFrame({"A": 0.0008, "B": 0.0002}, index=idx)
    w = pd.DataFrame(0.0, index=idx, columns=["A", "B"])
    w.loc[idx.year % 2 == 0, "A"] = 1.0  # 해마다 바꿔 이익을 실현
    w.loc[idx.year % 2 == 1, "B"] = 1.0
    out = re_.index_sim(r, w, 0.015, approx_tax=True)
    t = out["approx_tax"]
    assert t["label"].startswith("APPROXIMATE")
    assert t["monthly_contribution_krw"] == pytest.approx(150_000)
    assert t["tax"]["capital_gains_tax_krw"] > 0 and t["no_tax"]["capital_gains_tax_krw"] == 0
    assert t["tax"]["terminal_after_liquidation_krw"] < t["no_tax"]["terminal_after_liquidation_krw"]
    assert t["irr_tax_drag"] > 0
    # 세금 없는 근사 계좌(수수료 0) = 세전 가벼운 시뮬레이터
    assert t["no_tax"]["terminal_ratio"] == pytest.approx(out["terminal"], rel=1e-9)
    assert out["approx_tax"] is not None and re_.index_sim(r, w, 0.015)["approx_tax"] is None
