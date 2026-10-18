"""contrib-reval-longrun-v1 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core import rolling_eval as re_
from core import tax_fx as tx

ROOT = Path(__file__).resolve().parents[1]


def _load():
    name = "contrib_reval_longrun_v1"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "research/jobs/contrib-reval-longrun-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


m = _load()


@pytest.fixture(scope="module")
def data():
    return m.synthetic_data()


@pytest.fixture(scope="module")
def sl(data):
    return m.prepare(data)


def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert m.JOB_ID in valid, invalid.get(m.JOB_ID)
    job = json.loads((ROOT / "research/jobs/contrib-reval-longrun-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 24 and job["resumable"] is True and job["max_memory_mb"] <= 2500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert (ROOT / "research/jobs/contrib-reval-longrun-v1/SPEC.md").exists()


def test_pre_registered_constants():
    assert m.STRATEGIES == ("CORE", "I2", "I2VT20", "MB30", "MB50", "BH50", "L15F") and m.N_TRIALS == 7
    assert m.SCENARIOS == {"A": 0.0, "B": 0.015, "C": 0.05} and m.PRIMARY == "B"
    assert m.TAX_INITIAL_KRW == {"A": 10_000_000, "B": 10_000_000, "C": 3_000_000}
    assert m.HORIZONS == (10, 20) and m.JUDGED_SETS == ("selection", "confirmation")
    assert (m.SEL_FIRST_START, m.SEL_END_CUTOFF, m.CONF_FIRST_START, m.CONF_END_CUTOFF, m.POST_FIRST_END) == (
        "1927-07-01", "1966-12-31", "1967-01-01", "2007-12-31", "2008-01-01")
    assert (m.WIN_SHARE_MIN, m.MEDIAN_IRR_MIN, m.P10_IRR_MIN, m.MDD_TOL) == (0.70, 0.005, -0.015, 0.05)
    assert m.TAX_START_MONTHS == (1, 4, 7, 10) and m.POLICY == "underweight_first" and m.POWER_YEARS == 41
    assert m.TAX_FX == 1300.0 and m.BH_DRAG == 0.01 and m.COST_BPS == 10.0
    assert m.COMPOSITION["MB30"] == {"MKT": 0.70, "I2VT20": 0.30} and m.COMPOSITION["L15F"] == {"MKT": 0.85, "LEG": 0.15}


# --- 세전 소매 수익 = 원래 연구 함수 ------------------------------------------------------------------

def test_sleeve_returns_equal_source_jobs(data, sl):
    lab, MV, MP = m.lab, m.MV, m.MP
    ind, rf, mkt = data["ind12"], data["rf"], data["mkt"]
    core = lab.strategy_returns(ind, rf, lab.target_weights(ind, mkt, lab.Rule()))
    pd.testing.assert_series_equal(sl["sleeve_r"]["CORE"], core.fillna(0.0), check_names=False)
    sched = MV.pick_schedule(ind, "I2")
    raw = MV.raw_sleeve(ind, rf, sched, 2)
    below = MV.market_below_sma(mkt, ind.index)
    for v, col in (("none", "I2"), ("VT20", "I2VT20")):
        exp = MV.exposure_schedule(raw, below, sched, v, "none")
        src = MV.simulate(ind, rf, sched, exp, 2)["returns"]
        pd.testing.assert_series_equal(sl["sleeve_r"][col], src, check_names=False)
    pd.testing.assert_series_equal(sl["sleeve_r"]["BIG"], MP.apply_drag(data["bh"].fillna(0.0), 0.01), check_names=False)
    pd.testing.assert_series_equal(sl["sleeve_r"]["MKT"], mkt.fillna(0.0), check_names=False)


def _daily(values: pd.Series) -> pd.Series:
    return values.pct_change().iloc[1:]


def test_blends_equal_source_blend_without_contributions(sl):
    a, b = "1931-03-01", "1952-08-31"
    r = sl["sleeve_r"].loc[a:b]
    for name, sleeve, w in (("MB30", "I2VT20", 0.30), ("BH50", "BIG", 0.50)):
        got = m.continuous_returns(sl, name, a, b).iloc[1:]
        # blend_returns 는 첫 행 수익부터 표류 — index_sim 은 첫날 종가에 산다 → 둘째 행부터 같은 계좌
        src = m.MP.blend(r[sleeve].iloc[1:], r["MKT"].iloc[1:], w)    # mom-proxy-v1 = lab.blend_returns, 1월 재조정 10bp
        assert np.allclose(got.to_numpy(), src.to_numpy(), atol=2e-8)


def test_l15f_equals_lev_base_long_run_path(data, sl):
    a, b = "1931-03-01", "1952-08-31"
    p0 = m.LB.long_run_path(data["mkt"], data["rf"], 0.15, True, start=a, end=b, bps=0.0)
    leg0, _, _ = m.leg_returns(data["mkt"], data["rf"], bps=0.0)
    r = pd.DataFrame({"MKT": data["mkt"], "LEG": leg0}).loc[a:b]
    w = sl["sleeve_w"]["L15F"].loc[r.index[0]: r.index[-1]]
    v = re_.index_sim(r, w, 0.0, initial=1.0, cost_bps=0.0)["values"]
    assert np.allclose(_daily(v).to_numpy(), p0["returns"].iloc[1:].to_numpy(), atol=1e-7)
    # 10bp: 비용 배분 방식만 달라 아주 작은 차이
    p = m.LB.long_run_path(data["mkt"], data["rf"], 0.15, True, start=a, end=b)
    got = m.continuous_returns(sl, "L15F", a, b)
    assert abs((1 + got).prod() / (1 + p["returns"]).prod() - 1) < 2e-3


# --- 적립 = index_sim ---------------------------------------------------------------------------------

def test_contributions_go_through_index_sim(sl):
    s, e = pd.Timestamp("1950-01-03"), pd.Timestamp("1959-12-31")
    pre = m.pre_window(sl, "MB50", s, e, 0.015)
    r = sl["sleeve_r"].loc[s:e, ["MKT", "I2VT20"]]
    ref = re_.index_sim(r, sl["sleeve_w"]["MB50"].loc[s:e], 0.015, policy="underweight_first", initial=1.0, cost_bps=10.0)
    assert pre["terminal"] == pytest.approx(ref["terminal"]) and pre["irr"] == pytest.approx(ref["irr"])
    months = int(tx.contribution_days(r.index).sum())
    assert pre["contributed"] == pytest.approx(1 + 0.015 * months)
    bench = m.pre_window(sl, "MKT", s, e, 0.015)
    assert bench["contributed"] == pre["contributed"]
    assert m.pre_window(sl, "MKT", s, e, 0.0)["contributed"] == 1.0


def test_tax_arm_matches_approx_tax_sim_and_factor(sl):
    s, e = pd.Timestamp("1950-01-03"), pd.Timestamp("1956-12-31")
    w = sl["tax_w"]["I2"].loc[s:e]
    w = w.loc[:, w.abs().sum() > 0]
    r = sl["under_r"].loc[s:e, list(w.columns)]
    ref = re_.approx_tax_sim(r, w, 0.015, policy="underweight_first", cost_bps=10.0, initial_krw=10_000_000)
    got = m.tax_arm(r, w, 0.015, 10_000_000)
    assert got["terminal_after_liquidation_krw"] == pytest.approx(ref["tax"]["terminal_after_liquidation_krw"])
    assert got["capital_gains_tax_krw"] > 0
    # 세금 없는 쪽: index_sim(10bp) ≈ tax_fx 세금 없음(10bp)
    nt = re_.index_sim(r, w, 0.015, initial=1.0, cost_bps=10.0)
    assert nt["terminal"] * 10_000_000 == pytest.approx(ref["no_tax"]["terminal_after_liquidation_krw"], rel=2e-3)
    pre = m.pre_window(sl, "I2", s, e, 0.015)
    t = m.tax_window(sl, "I2", s, e, 0.015, 10_000_000, pre)
    assert 0 < t["factor"] < 1 and t["terminal"] < pre["terminal"] and t["irr"] < pre["irr"]
    # 시장 그냥 보유: 보유표 = 소매 표 → 세전이 같다
    pm = m.pre_window(sl, "MKT", s, e, 0.015)
    tm = m.tax_window(sl, "MKT", s, e, 0.015, 10_000_000, pm)
    assert tm["frame_pre_irr"] == pytest.approx(pm["irr"], abs=1e-9)


def test_tax_frames_rows_sum_to_one_and_follow_rules(sl):
    for name, W in sl["tax_w"].items():
        assert np.allclose(W.sum(axis=1), 1.0, atol=1e-7), name
        assert (W.to_numpy() >= -1e-12).all(), name
    idx = sl["under_r"].index
    d = m.MV.decision_rows(idx)[30]
    mb = sl["tax_w"]["MB30"].iloc[d]
    assert mb["MKT"] == pytest.approx(0.70 + 0.30 * sl["tax_w"]["I2VT20"].iloc[d]["MKT"], abs=1e-7)
    l15 = sl["tax_w"]["L15F"]
    assert np.allclose(l15["MKT"], 0.85, atol=1e-7) and np.allclose(l15["X2"] + l15["RF"], 0.15, atol=1e-7)


# --- 구간 집합 -------------------------------------------------------------------------------------

def test_window_sets_respect_cutoffs():
    days = pd.bdate_range("1926-07-01", "2026-08-31")
    sets = m.window_sets(days)
    for h in (10, 20):
        sel, conf, post = sets["selection"][h], sets["confirmation"][h], sets["post2008"][h]
        assert sel and conf and post
        assert all(s >= pd.Timestamp("1927-07-01") and e <= pd.Timestamp("1966-12-31") for s, e in sel)
        assert all(s >= pd.Timestamp("1967-01-01") and e <= pd.Timestamp("2007-12-31") for s, e in conf)
        assert all(e >= pd.Timestamp("2008-01-01") for s, e in post)
        assert str(sel[0][0].date()) == "1927-07-01" and str(conf[0][0].date()) == "1967-01-02"
        keys = [set(x) for x in (sel, conf, post)]
        assert not (keys[0] & keys[1]) and not (keys[1] & keys[2])
        # 1967 을 걸치는 구간은 빠진다
        assert not any(s < pd.Timestamp("1967-01-01") and e > pd.Timestamp("1966-12-31") for s, e in sel + conf + post)
        # 매달 시작 + 끝이 시작 + h년 이하
        assert all((e - s).days <= h * 366 for s, e in sel)
    assert sets["selection"][10][-1][0].strftime("%Y-%m") == "1957-01"  # 끝 1966-12-30 ≤ 기준일
    assert sets["confirmation"][20][-1][0].strftime("%Y-%m") == "1987-12"
    assert len(sets["selection"][10]) == 355 and len(sets["confirmation"][10]) == 372
    sampled = [s for s, _ in sets["confirmation"][10] if m.tax_sampled(s)]
    assert len(sampled) == 124 and {s.month for s in sampled} == {1, 4, 7, 10}


# --- 판정 ------------------------------------------------------------------------------------------

def _good():
    return {"n": 50, "share_win": 0.8, "median_diff_irr": 0.01, "p10_diff_irr": -0.005,
            "median_mdd_tw": -0.40, "median_bench_mdd_tw": -0.38}


def test_verdict_requires_both_sets_and_both_horizons():
    power = m.rp.power_report(41, 7)
    after = {ws: {h: _good() for h in (10, 20)} for ws in ("selection", "confirmation")}
    out = m.rule_outcome(after)
    assert out["passed"] is True and m.verdict_for(out, None, 0.5, power) == m.PASS
    for ws in ("selection", "confirmation"):
        for h in (10, 20):
            for key, bad in (("share_win", 0.69), ("median_diff_irr", 0.004), ("p10_diff_irr", -0.016),
                             ("median_mdd_tw", -0.4301)):
                a2 = {w: {hh: dict(_good()) for hh in (10, 20)} for w in ("selection", "confirmation")}
                a2[ws][h][key] = bad
                o = m.rule_outcome(a2)
                assert o["passed"] is False, (ws, h, key)
                assert m.verdict_for(o, None, 0.05, power) == "FAIL_UNDERPOWERED"
                assert m.verdict_for(o, None, 5.0, power) == "FAIL"
    a3 = {"selection": {10: _good(), 20: _good()}, "confirmation": {10: _good(), 20: {"n": 0}}}
    assert m.rule_outcome(a3)["passed"] is None
    assert m.verdict_for(m.rule_outcome(a3), None, 0.5, power) == m.NOT_EVALUABLE
    assert m.verdict_for(out, "noop", 0.5, power) == m.NOT_EVALUABLE
    # 경계값은 통과
    edge = {ws: {h: {"n": 5, "share_win": 0.70, "median_diff_irr": 0.005, "p10_diff_irr": -0.015,
                     "median_mdd_tw": -0.45, "median_bench_mdd_tw": -0.40} for h in (10, 20)} for ws in ("selection", "confirmation")}
    assert m.rule_outcome(edge)["passed"] is True


def test_pair_rows_after_tax_uses_subsample_and_pre_tax_mdd():
    def row(h, s, e, irr, term, mdd, tax):
        return {"h": h, "start": s, "end": e, "pre": {"irr": irr, "terminal": term, "mdd_tw": mdd, "contributed": 1.0},
                "tax": None if tax is None else {"irr": tax[0], "terminal": tax[1], "frame_pre_irr": irr}}
    k1, k2 = "10|1950-01-03|1959-12-31", "10|1950-02-01|1960-02-01"
    st = {"rows": {k1: row(10, "1950-01-03", "1959-12-31", 0.10, 3.0, -0.3, (0.09, 2.8)),
                   k2: row(10, "1950-02-01", "1960-02-01", 0.10, 3.0, -0.3, None)}}
    bm = {"rows": {k1: row(10, "1950-01-03", "1959-12-31", 0.08, 2.5, -0.2, (0.075, 2.4)),
                   k2: row(10, "1950-02-01", "1960-02-01", 0.08, 2.5, -0.2, None)}}
    pre = m.pair_rows(st, bm, 10, False)
    aft = m.pair_rows(st, bm, 10, True)
    assert len(pre) == 2 and len(aft) == 1
    assert aft[0]["diff_irr"] == pytest.approx(0.015) and aft[0]["strategy"]["mdd_tw"] == -0.3 and aft[0]["win"]
    c = m.compact(aft, 10)
    assert c["n"] == 1 and c["median_tax_drag"] == pytest.approx(0.01) and c["median_bench_tax_drag"] == pytest.approx(0.005)
