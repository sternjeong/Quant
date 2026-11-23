"""crash-cycle-lab — 급락 고도화 7연구 공용 모듈: 순수 함수(손 계산 답), v1 과 같은 값, 판정 규칙, 예측 파일 형식."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("crash_cycle_lab", ROOT / "research" / "jobs" / "crash-cycle-lab" / "lab.py")
lab = importlib.util.module_from_spec(spec)
sys.modules["crash_cycle_lab"] = lab
spec.loader.exec_module(lab)
v1 = lab.v1()


@pytest.fixture(scope="module")
def syn():
    data = lab.load_us(True)
    ctx = lab.us_context(data)
    return data, ctx


def _hand_rec(Lv, t0=1, tP=0, rec=6, end1=6, settled=True):
    idx = pd.bdate_range("2001-01-01", periods=len(Lv))
    Lv = np.asarray(Lv, dtype=float)
    P = float(Lv[tP])
    r = {"t0": t0, "tP": tP, "P": P, "dd0": float(Lv[t0] / P - 1), "rec": rec, "R": None if rec is None else rec - t0,
         "end1": end1, "depth_settled": settled, "y": None, "FD": None, "retriggers": []}
    lab.annotate([r], "US", idx, Lv)
    return r


# ---------------------------------------------------------------- 1~4
def test_constants():
    keys = [k for k, _s in lab.FAMILY]
    assert len(lab.FAMILY) == lab.K_FAMILY == 15
    assert len(set(keys)) == 15
    assert lab.ALPHA == 0.05 / 15
    assert lab.X_FLOOR == pytest.approx(0.0512933, abs=1e-6)
    assert len(lab.PRED_COLUMNS) == 26


def test_v1_series_matches_v1_load():
    a = lab.v1_series(lab.lab0().synthetic_data(), True)
    b = v1.load(True)
    for k in ("L", "rf", "F", "F49"):
        if b[k] is None:
            assert a[k] is None
        else:
            pd.testing.assert_series_equal(a[k], b[k])
    assert a["fin_column"] == b["fin_column"] and a["fin49_columns"] == b["fin49_columns"]


def test_pools_match_v1(syn):
    _d, ctx = syn
    eps, idx = ctx["eps"], ctx["idx"]
    for pos in (3000, 9000, 15000, 22000, ctx["last"]):
        assert [j["t0"] for j in lab.m1_pool(eps, idx[pos])] == [j["t0"] for j in v1.m1_train(eps, pos)]
        r1, t1, e1 = lab.m2_pool(eps, idx[pos])
        r2, t2, e2 = v1.m2_train(eps, pos)
        assert [j["t0"] for j in r1] == [j["t0"] for j in r2]
        assert np.array_equal(t1, t2) and np.array_equal(e1, e2)


def test_base_matches_v1_ctx(syn):
    _d, ctx = syn
    checked = 0
    for ep in ctx["eps"]:
        b1 = lab.base_m1(lab.m1_pool(ctx["eps"], ep["t0_date"]), ep["dd0"])
        b2 = lab.base_m2(*lab.m2_pool(ctx["eps"], ep["t0_date"]), 0)
        if ep["_p1"] is not None:
            for k, v in ep["_p1"]["pred"]["BASE"].items():
                assert b1[k] == pytest.approx(v, abs=1e-12)
            checked += 1
        else:
            assert b1 is None
        if ep["_p2"] is not None and ep["_p2"]["pred"]["BASE"] is not None:
            for h, v in ep["_p2"]["pred"]["BASE"].items():
                assert b2[h] == pytest.approx(v, abs=1e-12)
    assert checked > 10


# ---------------------------------------------------------------- 5~10
def test_strata():
    cases = {"1927-06-30": "pre", "1927-07-01": "A", "1966-12-31": "A", "1967-01-01": "B", "2007-12-31": "B",
             "2008-01-01": "C", "2024-09-30": "C", "2024-10-01": "X"}
    for d, s in cases.items():
        assert lab.stratum_us(d) == s
    assert lab.stratum_intl("2007-12-31") == "I1"
    assert lab.stratum_intl("2008-01-01") == "I2"
    assert lab.stratum_intl("2024-10-01") == "IX"


def test_lb_label():
    n = 400
    Lv = np.ones(n)
    idx = pd.bdate_range("2001-01-01", periods=n)

    def rec(R):
        r = {"t0": 10, "tP": 0, "P": 1.0, "dd0": -0.2, "rec": None if R is None else 10 + R, "R": R,
             "end1": 10 + (R or 756), "depth_settled": False, "y": None, "FD": None, "retriggers": []}
        lab.annotate([r], "US", idx, Lv)
        return r

    assert lab.lb_label(rec(200), idx[10 + 201]) == 0
    assert lab.lb_label(rec(300), idx[10 + 301]) == 1
    assert lab.lb_label(rec(None), idx[10 + 260]) == 1
    assert lab.lb_label(rec(None), idx[10 + 100]) is None
    assert lab.lb_label(rec(300), idx[10 + 100]) is None


def _probs(f, X):
    return [lab.sigmoid(f["b0"] + lab.eta(f, x)) for x in X]


def test_ridge_logit_hand():
    X, y = [[0], [0], [1], [1], [1]], [0, 1, 0, 1, 1]
    f0 = lab.fit_ridge_logit(X, y, 0.0)
    assert np.allclose(_probs(f0, X), [0.5, 0.5, 2 / 3, 2 / 3, 2 / 3], atol=1e-6)
    f4 = lab.fit_ridge_logit(X, y, 4.0)
    assert f4["converged"]
    assert f4["b0"] == pytest.approx(0.406066, abs=1e-5)
    assert f4["beta"][0] == pytest.approx(0.078463, abs=1e-5)
    assert np.allclose(_probs(f4, X), [0.576878] * 2 + [0.615415] * 3, atol=1e-5)
    assert lab.fit_ok(f4) is False  # n = 5 < MIN_CLS_TRAIN


def test_ridge_logit_constant_feature():
    X = [[0, 3.0], [0, 3.0], [1, 3.0], [1, 3.0], [1, 3.0]]
    y = [0, 1, 0, 1, 1]
    f = lab.fit_ridge_logit(X, y, 4.0)
    g = lab.fit_ridge_logit([[x[0]] for x in X], y, 4.0)
    assert list(f["keep"]) == [True, False]
    assert f["beta"][1] == 0.0
    assert f["b0"] == pytest.approx(g["b0"], abs=1e-12)
    assert f["beta"][0] == pytest.approx(g["beta"][0], abs=1e-12)


def test_p_center_weights():
    X = [[1.0], [1.0], [1.0], [1.0], [1.0], [1.0], [1.0]]
    y = [0, 1, 1, 0, 1, 1, 0]
    f = lab.fit_ridge_logit(X, y)
    pc = lab.p_center(f, [5.0], [x for x in X], y)
    assert pc[0] == pc[1] == pytest.approx(4 / 7)
    assert pc[0] == np.mean(y)
    assert list(lab.two_state_w([1, 1, 0, None], 0.75, 0.5)) == [1.5, 1.5, 0.5, 1.0]
    big = {"mu": np.array([0.0]), "sd": np.array([1.0]), "keep": np.array([True]), "beta": np.array([10.0]), "b0": 0.0}
    p, pi = lab.p_center(big, [1.0], [[0.0], [0.0]], [0, 1])
    assert p == 0.95 and pi == 0.5
    assert lab.p_center(big, [1.0], [[0.0], [0.0]], [1, 1]) is None
    assert lab.p_center(big, [1.0], [[0.0], [0.0]], [None, None]) is None


def test_reweight_identity(syn):
    _d, ctx = syn
    D = ctx["idx"][ctx["last"]]
    T1 = lab.m1_pool(ctx["eps"], D)
    assert lab.rw_m1(T1, -0.2, np.ones(len(T1))) == lab.base_m1(T1, -0.2)
    rows, times, events = lab.m2_pool(ctx["eps"], D)
    assert lab.rw_m2(times, events, np.ones(len(rows)), 0) == lab.base_m2(rows, times, events, 0)


# ---------------------------------------------------------------- 11~15
def test_landmark_state_yrem_hand():
    r = _hand_rec([100, 84, 80, 70, 90, 96, 101])
    s = lab.landmark_state(r, 2)
    assert (s["d"], s["m"], s["x"]) == pytest.approx((-0.30, -0.30, 0.356675), abs=1e-6)
    s = lab.landmark_state(r, 3)
    assert (s["d"], s["m"], s["x"]) == pytest.approx((-0.10, -0.30, 0.105361), abs=1e-6)
    s = lab.landmark_state(r, 4)
    assert (s["d"], s["m"], s["x"]) == pytest.approx((-0.04, -0.30, 0.051293), abs=1e-6)
    assert lab.landmark_state(r, 5) is None
    s0 = lab.landmark_state(r, 0)
    assert s0["d"] == s0["m"] == pytest.approx(r["dd0"])
    assert lab.yrem(r, 1) == pytest.approx(-0.133531, abs=1e-6)
    assert lab.yrem(r, 2) == pytest.approx(0.0)
    assert lab.yrem(r, 3) == pytest.approx(0.0)


def test_scaled_km_hand():
    F = lab.scaled_km([10, 20, 30], [1, 1, 1], [0.1, 0.2, 0.1], 0.2, hs=(20, 59, 60))
    assert F[20] == pytest.approx(2 / 3) and F[59] == pytest.approx(2 / 3) and F[60] == pytest.approx(1.0)


def test_garch_filter_hand():
    Lv = 100 * np.exp(np.cumsum([0, 0.01, -0.01, 0.02, -0.02]))
    g = lab.garch_filter(lab.logret(Lv)[1:])
    assert abs(g["mu"]) < 1e-15
    assert g["v"] == pytest.approx(2.5e-4)
    assert g["omega"] == pytest.approx(5e-6)
    assert np.allclose(g["z"], [0.632456, -0.648204, 1.326862, -1.287032], atol=1e-6)
    assert g["h_next"] == pytest.approx(2.54332e-4, abs=1e-9)


def test_simulate_from_zero_noise():
    out = lab.simulate_from(math.log(0.85), math.log(0.85), 0.001, 1e-6, 1e-4, np.zeros(5), 756, 10, np.random.default_rng(0))
    assert out["F"] == {252: 1.0, 504: 1.0, 756: 1.0, 1260: 1.0}
    for v in out["q"].values():
        assert v == pytest.approx(-0.15, abs=1e-12)


def test_simulate_deterministic_no_lookahead(syn):
    _d, ctx = syn
    Lv = ctx["Lv"].copy()
    ep = [j for j in ctx["eps"] if j["t0"] > 2000][0]
    tau, P = ep["t0"], ep["P"]
    a = lab.simulate(Lv, "US", P, tau, ep["dd0"], 0, 200)
    b = lab.simulate(Lv, "US", P, tau, ep["dd0"], 0, 200)
    Lv2 = Lv.copy()
    Lv2[tau + 1:] *= 0.5
    c = lab.simulate(Lv2, "US", P, tau, ep["dd0"], 0, 200)
    assert a == b == c


# ---------------------------------------------------------------- 16~22
def test_macro_features_hand():
    rf = pd.Series(0.002, index=pd.period_range("2000-01", "2001-12", freq="M"))
    rf[pd.Period("2000-02", "M")] = 0.004
    rf[pd.Period("2001-02", "M")] = 0.003
    mo = pd.DataFrame({"AAA": 6.0, "BAA": 7.0}, index=pd.period_range("2000-01", "2001-12", freq="M"))
    mo.loc[pd.Period("2001-02", "M"), ["AAA", "BAA"]] = [7.0, 7.9]
    f = lab.macro_features("2001-03-15", rf, mo)
    assert f["RATECHG_M"] == pytest.approx(-0.012, abs=1e-12)
    assert f["TERM"] == pytest.approx(0.034, abs=1e-12)
    assert f["DEF"] == pytest.approx(0.009, abs=1e-12)
    rf2, mo2 = rf.copy(), mo.copy()
    rf2[rf2.index >= pd.Period("2001-03", "M")] = 0.5
    mo2.loc[mo2.index >= pd.Period("2001-03", "M")] = 99.0
    assert lab.macro_features("2001-03-15", rf2, mo2) == f
    g = lab.macro_features("2000-06-15", rf, mo)
    assert math.isnan(g["RATECHG_M"]) and math.isfinite(g["TERM"])


def test_volratio_breadth_corr_hand():
    r = np.r_[np.nan, np.full(231, 0.01), np.full(21, 0.02)]
    assert lab.volratio(r, 252) == pytest.approx(1.788854, abs=1e-6)
    assert math.isnan(lab.volratio(r, 251))
    row = np.r_[[-0.2, -0.3, -0.15], [-0.1] * 7, [np.nan] * 3]
    assert lab.breadth(row[None, :], 0) == pytest.approx(0.3)
    assert math.isnan(lab.breadth(np.r_[[-0.2] * 9, [np.nan] * 4][None, :], 0))
    base = np.random.default_rng(1).normal(size=63)
    R = np.outer(base, np.arange(1, 13))
    assert lab.corr12(R, 62) == pytest.approx(1.0)
    R2 = R.copy()
    R2[:, 3] = 0.01
    assert math.isnan(lab.corr12(R2, 62))
    assert math.isnan(lab.corr12(R, 61))


def test_clusters_gap():
    items = [("1992-01-02", 1.0, "a"), ("1992-02-03", 3.0, "b"), ("1992-09-01", 5.0, "c"), ("1998-08-03", 7.0, "d")]
    cs = lab.clusters(items)
    assert [c["members"] for c in cs] == [["a", "b"], ["c"], ["d"]]
    assert [c["stratum"] for c in cs] == ["I1"] * 3
    assert [c["value"] for c in cs] == [2.0, 5.0, 7.0]


def test_judge_us():
    def mk(a, b, c):
        return {"A": a, "B": b, "C": c}

    assert lab.judge_us(mk([0.01] * 5, [0.01] * 9, [0.01] * 7))["verdict"] == "BEATS_BASELINE"
    assert lab.judge_us(mk([0.0] * 5, [0.0] * 9, [0.0] * 7))["verdict"] == "NOT_EVALUABLE"
    assert lab.judge_us(mk([0.01] * 3, [0.01] * 9, [0.01] * 7))["verdict"] == "NOT_EVALUABLE"
    j = lab.judge_us(mk([0.01] * 5, [0.01] * 9, [-0.01] * 7))
    assert j["verdict"] == "FAIL" and j["fail_kind"] == "FAIL"
    j = lab.judge_us(mk([0.05, -0.04, 0.05, -0.04, 0.05], [0.05, -0.04] * 4 + [0.05], [0.05, -0.04, 0.05, -0.04, 0.05, -0.04, 0.05]))
    assert j["verdict"] == "FAIL" and j["fail_kind"] == "FAIL_UNDERPOWERED"
    assert lab.judge_us(mk([0.01] * 5, [0.01] * 9, [0.01] * 7), "BEATS_FIXED_SPLIT")["verdict"] == "BEATS_FIXED_SPLIT"


def test_judge_intl():
    j = lab.judge_intl({"I1": [0.01] * 5, "I2": [0.01] * 6})
    assert j["verdict"] == "BEATS_BASELINE"
    assert j["p"] == pytest.approx(2 ** -11)
    assert lab.judge_intl({"I1": [0.01] * 2, "I2": [0.01] * 9})["verdict"] == "NOT_EVALUABLE"
    assert lab.judge_intl({"I1": [0.01] * 4, "I2": [0.01] * 5})["verdict"] == "NOT_EVALUABLE"


def test_recal_shift_hand():
    assert lab.recal_shift([0.5] * 4, [1, 1, 1, 0], 1.0) == pytest.approx(0.505240, abs=1e-5)
    assert lab.recal_shift([0.2] * 10, [1, 1] + [0] * 8) == pytest.approx(0.0, abs=1e-8)
    assert lab.recal_shift([0.2] * 10, [1] * 6 + [0] * 4) == pytest.approx(1.275844, abs=1e-5)
    Fi = {252: 0.3, 504: 0.25, 756: 0.6, 1260: 0.9}
    out = lab.recal_m2(Fi, {h: [(0.2, 1)] * 4 for h in lab.HZ})
    assert all(c == 0.0 for c in out["c"].values())
    vals = [out["F"][h] for h in lab.HZ]
    assert vals == sorted(vals)
    out2 = lab.recal_m2(Fi, {h: [(0.2, 1)] * 6 + [(0.2, 0)] * 4 for h in lab.HZ})
    assert out2["c"][252] == pytest.approx(1.275844, abs=1e-5)
    assert [out2["F"][h] for h in lab.HZ] == sorted(out2["F"][h] for h in lab.HZ)


def test_recal_m1_hand():
    Qi = {"0.1": -0.5, "0.25": -0.4, "0.5": -0.3, "0.75": -0.22, "0.9": -0.18}
    fd = [-0.30 + 0.01 * k for k in range(10)]
    ql = {k: [-0.30] * 10 for k in Qi}
    out = lab.recal_m1(Qi, fd, ql, -0.2)
    assert out["delta"]["0.5"] == pytest.approx(0.0225)
    vals = [out["q"][k] for k in ("0.1", "0.25", "0.5", "0.75", "0.9")]
    assert vals == sorted(vals) and all(v <= -0.2 for v in vals)
    out9 = lab.recal_m1(Qi, fd[:9], {k: v[:9] for k, v in ql.items()}, -0.2)
    assert all(d == 0.0 for d in out9["delta"].values())


# ---------------------------------------------------------------- 23~28
def test_predictions_roundtrip(tmp_path):
    rows = [{c: None for c in lab.PRED_COLUMNS} for _ in range(3)]
    for i, r in enumerate(rows):
        r.update(study="s", model=["LM", "BASE", "BASE"][i], market="US", episode_id=f"US:200{i}-01-01", t0=f"200{2 - i}-01-01",
                 era="C", landmark=[21, 0, 21][i], asof="2002-02-01", n_train=7, d_q10=-0.123456789, r_252=0.5,
                 y_depth_settled=1, y_recovered=0, judged_m1=1, judged_m2=0)
    p = tmp_path / "predictions.csv"
    lab.write_predictions(rows, p)
    text = p.read_text(encoding="utf-8")
    assert text.split("\n")[0] == ",".join(lab.PRED_COLUMNS)
    assert "-0.123457" in text
    back = lab.read_predictions(p)
    assert [r["t0"] for r in back] == ["2000-01-01", "2001-01-01", "2002-01-01"]
    for r in back:
        orig = next(o for o in rows if o["t0"] == r["t0"])
        for c in lab.PRED_COLUMNS:
            if isinstance(orig[c], float):
                assert r[c] == pytest.approx(round(orig[c], 6))
            else:
                assert r[c] == orig[c]
    big = [dict(rows[0], episode_id=f"US:{i}", t0=f"{i:06d}") for i in range(4000)]
    with pytest.raises(RuntimeError):
        lab.write_predictions(big, tmp_path / "big.csv")


def test_score_row():
    q = {"0.1": -0.4, "0.25": -0.3, "0.5": -0.25, "0.75": -0.2, "0.9": -0.17}
    F = {252: 0.4, 504: 0.6, 756: 0.8, 1260: 0.9}
    row = {"d_q10": -0.4, "d_q25": -0.3, "d_q50": -0.25, "d_q75": -0.2, "d_q90": -0.17, "r_252": 0.4, "r_504": 0.6,
           "r_756": 0.8, "r_1260": 0.9, "y_FD": -0.27, "y_depth_settled": 1, "y_R_asof": 300, "y_recovered": 1}
    s1, s2 = lab.score_row(row)
    assert s1 == pytest.approx(v1.m1_score(-0.27, q))
    assert s2 == pytest.approx(v1.brier(300, F))
    assert lab.score_row(dict(row, y_recovered=0, y_R_asof=None))[1] is None


def test_power_episode():
    p = lab.power_episode(21)
    assert p["needed_effect_sd"] == pytest.approx(0.660, abs=1e-2)
    assert p["min_p"] == 2.0 ** -21
    assert lab.power_episode(8)["min_p"] == pytest.approx(0.0039, abs=1e-4)
    assert lab.power_episode(8)["min_p"] > lab.ALPHA


def test_split_tranches():
    a = lab.split_tranches(0.5)
    b = v1.SCHEDULES["HALF6"]
    assert len(a) == len(b)
    for (o1, f1), (o2, f2) in zip(a, b):
        assert o1 == o2 and f1 == pytest.approx(f2, abs=1e-12)
    assert sum(f for _o, f in lab.split_tranches(0.37)) == pytest.approx(1.0)


def test_moodys_snapshot_schema():
    path = lab.MOODYS_CSV
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert lines[0] == "month,AAA,BAA"
    months = [ln.split(",")[0] for ln in lines[1:]]
    assert months[0] == "1919-01"
    per = pd.PeriodIndex(months, freq="M")
    assert list(per) == list(pd.period_range(per[0], per[-1], freq="M"))
    assert months[-1] >= "2026-08"
    vals = np.array([[float(x) for x in ln.split(",")[1:]] for ln in lines[1:]])
    assert np.all(vals > 0)


def test_synthetic_intl():
    d = lab.synthetic_intl()
    assert set(d) == set(lab.INTL_REGIONS)
    for key, L in d.items():
        assert (L.index.dayofweek < 5).all() and (L > 0).all()
        mc = lab.market_context(L, key)
        assert len(mc["eps"]) >= 5
        assert {r["stratum"] for r in mc["eps"]} <= {"I1", "I2", "IX"}
