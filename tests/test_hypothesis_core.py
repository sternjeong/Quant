"""가설 스펙·레지스트리·엔진·심판 — 기대값은 손계산 또는 정의에서 직접 도출."""

import json
import math
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import hypothesis_engine as he
from core import hypothesis_judge as hj
from core import hypothesis_registry as reg
from core import hypothesis_spec as hs
from core.models import Base


def spec(**over):
    s = {"id": "H-20261001-001", "source": "test", "thesis": "t",
         "universe": {"type": "list", "tickers": ["aaa", "BBB"]},
         "signal": {"params_grid": [{"k": 1}, {"k": 2}]},
         "portfolio": {"top_k": 1, "rebalance": "monthly", "max_weight": 0.25},
         "period": {"start": "2020-01-01"}, "kill_criteria": {"min_rebalances": 12, "max_drawdown": 0.5}}
    s.update(over)
    return s


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


# ---------------- spec ----------------
def test_spec_normalizes_and_counts_trials():
    out = hs.validate(spec())
    assert out["universe"]["tickers"] == ["AAA", "BBB"] and hs.n_trials(out) == 2


def test_spec_reports_all_errors_at_once():
    with pytest.raises(hs.SpecError) as e:
        hs.validate(spec(id="bad", portfolio={"top_k": 0, "rebalance": "daily", "max_weight": 0.5},
                         signal={"params_grid": [{}] * 9}))
    msg = str(e.value)
    for part in ("id:", "top_k", "rebalance", "max_weight", "params_grid"):
        assert part in msg


# ---------------- registry ----------------
def test_lifecycle_and_trial_counter_never_decreases(db):
    reg.register_draft(spec(), session=db)
    assert reg.funnel(session=db)["cumulative_trials"] == 0  # draft 는 세지 않음
    reg.freeze("H-20261001-001", "def score(p,a,k): return {}", session=db)
    reg.transition("H-20261001-001", reg.FAIL, "x", session=db)
    assert reg.funnel(session=db)["cumulative_trials"] == 2  # 실패해도 남는다
    with pytest.raises(reg.TransitionError):
        reg.transition("H-20261001-001", reg.SHADOW, session=db)
    with pytest.raises(reg.TransitionError):
        reg.register_draft(spec(), session=db)  # 동결 후 스펙 변경 불가
    h = reg.get("H-20261001-001", session=db)
    assert h["signal_code"].startswith("def score") and len(h["spec_hash"]) == 64


def test_weekly_freeze_cap_uses_kst_week(db, monkeypatch):
    monkeypatch.setattr(reg, "WEEKLY_FREEZE_CAP", 2)
    mon = datetime(2026, 10, 4, 15, 30)  # = 2026-10-05 00:30 KST (월)
    for i in (1, 2, 3):
        reg.register_draft(spec(id=f"H-20261005-00{i}"), session=db)
    reg.freeze("H-20261005-001", "", session=db, now=mon)
    reg.freeze("H-20261005-002", "", session=db, now=mon)
    with pytest.raises(reg.CapReached):
        reg.freeze("H-20261005-003", "", session=db, now=mon)
    reg.freeze("H-20261005-003", "", session=db, now=datetime(2026, 10, 11, 15, 30))  # 다음 주 월요일 KST


def test_shadow_cap(db, monkeypatch):
    monkeypatch.setattr(reg, "SHADOW_CAP", 1)
    for i in (1, 2):
        hid = f"H-20261001-00{i}"
        reg.register_draft(spec(id=hid), session=db)
        reg.freeze(hid, "", session=db)
        reg.transition(hid, reg.PASS, session=db)
    reg.transition("H-20261001-001", reg.SHADOW, session=db)
    with pytest.raises(reg.CapReached):
        reg.transition("H-20261001-002", reg.SHADOW, session=db)


# ---------------- engine ----------------
def _px(closes, start="2020-01-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes}, index=idx)


def test_backtest_hand_computed_next_day_application_and_cost():
    # A 는 매일 +1%, B 는 0%. 신호는 항상 A 를 고른다. 월말 리밸런싱, 비용 편도 100bp.
    n = 70
    prices = {"A": _px([100 * 1.01 ** i for i in range(n)]), "B": _px([100.0] * n)}
    s = hs.validate(spec(universe={"type": "list", "tickers": ["A", "B"]},
                         portfolio={"top_k": 1, "rebalance": "monthly", "max_weight": 0.25}))
    res = he.backtest(s, {}, lambda p, d, k: {"A": 1.0, "B": 0.5}, prices, lambda d: {"A", "B"}, one_way_bps=100)
    r = res["returns"]
    first_rebal = he.rebalance_dates(r.index, "monthly")[0]
    i = r.index.get_loc(first_rebal)
    assert (r.iloc[: i + 1] == 0).all()                           # 결정일 당일까지는 미보유
    assert r.iloc[i + 1] == pytest.approx(0.25 * 0.01 - 0.25 * 0.01)  # 다음날: 비중 25% 수익 − 회전 0.25×100bp
    assert r.iloc[i + 2] > 0 and res["n_rebalances"] == len(he.rebalance_dates(r.index, "monthly"))


def test_signal_only_sees_data_up_to_as_of():
    seen = []
    prices = {"A": _px([100.0 + i for i in range(60)])}
    s = hs.validate(spec(universe={"type": "list", "tickers": ["A"]}))
    def sig(p, as_of, k):
        seen.append(p["A"].index.max() <= as_of)
        return {"A": 1.0}
    he.backtest(s, {}, sig, prices, lambda d: {"A"})
    assert seen and all(seen)


def test_load_signal_requires_score():
    assert he.load_signal("def score(p, a, k):\n    return {'X': 1}\n")({}, None, {}) == {"X": 1}
    with pytest.raises(he.SignalError):
        he.load_signal("x = 1")


def test_price_symbol_mapping():
    assert he.price_symbol("BF.B") == "BF-B" and he.price_symbol("AAL-199702") == "AAL"


# ---------------- judge ----------------
def test_expected_max_sr_grows_with_trials():
    v = (0.5 / math.sqrt(252)) ** 2
    assert hj.expected_max_sr(1, v) == 0.0
    assert 0 < hj.expected_max_sr(10, v) < hj.expected_max_sr(100, v)


def test_dsr_penalizes_same_sharpe_more_trials():
    v = (0.5 / math.sqrt(252)) ** 2
    sr = 1.0 / math.sqrt(252)
    one = hj.deflated_sharpe(sr, 2520, 0, 3, 1, v)["dsr"]
    many = hj.deflated_sharpe(sr, 2520, 0, 3, 200, v)["dsr"]
    assert one > 0.99 and many < one   # 10년 연샤프 1.0: 1회면 확실, 200회 시도면 할인


def _market(n=900, seed=0):
    rng = np.random.default_rng(seed)
    spy = 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, n))
    return _px(list(spy), "2019-01-01")


def test_judge_fails_market_clone_and_passes_nothing_by_luck():
    spy = _market()
    code = "def score(p, a, k):\n    return {t: 1.0 for t in p}\n"
    s = hs.validate(spec(universe={"type": "list", "tickers": ["SPYCLONE"]}, period={"start": "2019-06-01"},
                         signal={"params_grid": [{}]}))
    provider = lambda t, a, b: spy  # noqa: E731 — 모든 종목이 SPY 와 동일
    res = hj.judge({"spec": s, "signal_code": code}, cumulative_trials=1, prior_srs=[], price_provider=provider,
                   champion_corr_fn=None, cost=(0.0, "test"))
    assert res["verdict"] == "fail"
    assert any("SPY 상관" in x for x in res["reasons"])
    assert res["n_trials_total"] == 1 and res["sr_variance_source"].startswith("assumed")


def test_judge_frozen_error_retries_then_fails(db):
    reg.register_draft(spec(), session=db)
    reg.freeze("H-20261001-001", "not python (", session=db)
    for attempt in (1, 2):
        out = hj.judge_frozen("H-20261001-001", session=db, champion_corr_fn=None)
        assert out["status"] == "error" and out["attempt"] == attempt
    assert hj.judge_frozen("H-20261001-001", session=db, champion_corr_fn=None)["status"] == "failed_after_errors"
    assert reg.get("H-20261001-001", session=db)["status"] == reg.FAIL


# ---------------- judge 강건성 ----------------
def test_breakeven_bps_hand_computed():
    # 순수익 합 0.02, 총회전율 4, 가정 편도 25bp → 총수익 0.02 + 4×0.0025 = 0.03 → 0.03/4 = 75bp
    net = pd.Series([0.01, 0.01])
    assert hj.breakeven_bps(net, 4.0, 25.0) == pytest.approx(75.0)
    assert hj.breakeven_bps(net, 0.0, 25.0) is None


def test_drop_top_months_exposes_few_month_edge():
    idx = pd.bdate_range("2018-01-01", "2021-12-31")
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.0, 0.005, len(idx)), index=idx)
    for m in ("2018-03", "2019-07", "2020-11"):
        r[r.index.to_period("M") == pd.Period(m)] += 0.01  # 세 달에만 큰 초과수익
    full = he.stats(r)["sharpe_annual"]
    out = hj.drop_top_months(r)
    assert out["applicable"] and {d["month"] for d in out["dropped"]} == {"2018-03", "2019-07", "2020-11"}
    assert full > 0.5 and out["sharpe_annual"] < hj.ROBUST_KEEP * full
    assert hj.drop_top_months(r.loc[:"2019-06"])["applicable"] is False  # 18개월 < 24


def test_neighbor_params_scales_numbers_only():
    got = hj.neighbor_params({"lookback": 60, "z": 1.0, "flag": True, "name": "x", "neg": -2})
    assert {"lookback": 30, "z": 1.0, "flag": True, "name": "x", "neg": -2} in got
    assert {"lookback": 90, "z": 1.0, "flag": True, "name": "x", "neg": -2} in got
    assert {"lookback": 60, "z": 0.5, "flag": True, "name": "x", "neg": -2} in got
    assert len(got) == 4
    assert hj.neighbor_params({"n": 1}) == [{"n": 2}]  # 1×0.5 → 1(최소) 는 원래와 같아 뺀다
    assert hj.neighbor_params({"top": 2, "a": 1, "b": 1, "c": 1}) == [{"top": 1, "a": 1, "b": 1, "c": 1},
                                                                      {"top": 3, "a": 1, "b": 1, "c": 1},
                                                                      {"top": 2, "a": 2, "b": 1, "c": 1},
                                                                      {"top": 2, "a": 1, "b": 2, "c": 1}]  # 앞 3개 키만


def _cliff_setup():
    spy = _market(n=1300, seed=3)
    n = len(spy)
    rng = np.random.default_rng(4)
    good = _px(list(100 * np.cumprod(1 + 0.0008 + rng.normal(0, 0.01, n))), "2019-01-01")
    bad = _px(list(100 * np.cumprod(1 - 0.0008 + rng.normal(0, 0.01, n))), "2019-01-01")
    data = {"SPY": spy, "GOOD": good, "BAD": bad}
    return (lambda t, a, b: data[t]), data


def test_judge_rejects_parameter_cliff():
    provider, _ = _cliff_setup()
    code = "def score(p, a, k):\n    return {'GOOD': 1.0} if k['lookback'] == 60 else {'BAD': 1.0}\n"
    s = hs.validate(spec(universe={"type": "list", "tickers": ["GOOD", "BAD"]}, period={"start": "2019-06-01"},
                         signal={"params_grid": [{"lookback": 60}]}))
    res = hj.judge({"spec": s, "signal_code": code}, cumulative_trials=1, prior_srs=[], price_provider=provider,
                   champion_corr_fn=None, cost=(0.0, "test"))
    assert res["stats"]["sharpe_annual"] > 0
    assert [x["params"]["lookback"] for x in res["param_neighbors"]] == [30, 90]
    assert all(x["sharpe_annual"] < 0 for x in res["param_neighbors"])
    assert any("파라미터 이웃" in x for x in res["reasons"])
    assert res["n_trials_total"] == 1  # 이웃은 시도 수에 들어가지 않는다


def test_judge_robust_signal_passes_neighbor_and_breakeven_checks():
    provider, _ = _cliff_setup()
    code = "def score(p, a, k):\n    return {'GOOD': 1.0}\n"
    s = hs.validate(spec(universe={"type": "list", "tickers": ["GOOD", "BAD"]}, period={"start": "2019-06-01"},
                         signal={"params_grid": [{"lookback": 60}]}))
    res = hj.judge({"spec": s, "signal_code": code}, cumulative_trials=1, prior_srs=[], price_provider=provider,
                   champion_corr_fn=None, cost=(25.0, "test"))
    assert not any("파라미터 이웃" in x or "손익분기" in x for x in res["reasons"])
    assert res["breakeven_one_way_bps"] > 2 * 25.0


def test_judge_rejects_thin_cost_margin():
    provider, _ = _cliff_setup()
    # 매주 GOOD/BAD 를 번갈아 담는다 → 회전율이 커서 25bp 에서 손익분기 여유가 없다
    code = ("def score(p, a, k):\n"
            "    return {'GOOD': 1.0} if a.isocalendar()[1] % 2 == 0 else {'BAD': 1.0}\n")
    s = hs.validate(spec(universe={"type": "list", "tickers": ["GOOD", "BAD"]}, period={"start": "2019-06-01"},
                         signal={"params_grid": [{}]}, portfolio={"top_k": 1, "rebalance": "weekly", "max_weight": 0.25}))
    res = hj.judge({"spec": s, "signal_code": code}, cumulative_trials=1, prior_srs=[], price_provider=provider,
                   champion_corr_fn=None, cost=(25.0, "test"))
    assert res["breakeven_one_way_bps"] is not None and res["breakeven_one_way_bps"] < 50.0
    assert any("손익분기" in x for x in res["reasons"])


# ---------------- judge OOS 분리 ----------------
def test_holdout_split_needs_enough_is_and_oos():
    long_idx = pd.bdate_range("2015-01-01", "2024-12-31")
    split = hj.holdout_split(long_idx)
    assert split == pd.Timestamp("2022-12-31")
    assert hj.holdout_split(pd.bdate_range("2021-01-01", "2024-12-31")) is None  # IS 2년 < 3년
    assert hj.holdout_split(pd.DatetimeIndex([])) is None


def test_judge_selects_on_is_only_and_fails_on_oos():
    n = 2100
    idx = pd.bdate_range("2016-01-01", periods=n)
    split = idx[-1] - pd.DateOffset(years=hj.HOLDOUT_YEARS)
    rng = np.random.default_rng(7)
    drift_a = np.where(idx < split, 0.0015, -0.0015)   # IS 에서 좋고 OOS 에서 나쁨
    drift_b = np.where(idx < split, 0.0003, 0.0030)    # IS 에서 덜 좋고 OOS 에서 매우 좋음(전체 기간이면 B 가 이긴다)
    a = _px(list(100 * np.cumprod(1 + drift_a + rng.normal(0, 0.01, n))), "2016-01-01")
    b = _px(list(100 * np.cumprod(1 + drift_b + rng.normal(0, 0.01, n))), "2016-01-01")
    spy = _px(list(100 * np.cumprod(1 + rng.normal(0.0003, 0.01, n))), "2016-01-01")
    data = {"A": a, "B": b, "SPY": spy}
    code = "def score(p, a, k):\n    return {'A': 1.0} if k['pick'] == 1 else {'B': 1.0}\n"
    s = hs.validate(spec(universe={"type": "list", "tickers": ["A", "B"]}, period={"start": "2016-06-01"},
                         signal={"params_grid": [{"pick": 1}, {"pick": 2}]}))
    res = hj.judge({"spec": s, "signal_code": code}, cumulative_trials=2, prior_srs=[],
                   price_provider=lambda t, x, y: data[t], champion_corr_fn=None, cost=(0.0, "test"))
    assert res["best_params"] == {"pick": 1}                       # OOS 를 보지 않고 IS 로 골랐다
    assert res["holdout"]["split"] is not None
    assert res["holdout"]["oos_stats"]["sharpe_annual"] < 0
    assert any(x.startswith("OOS(") for x in res["reasons"])
    assert not any("OOS 분리 없음" in w for w in res["warnings"])
