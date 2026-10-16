"""signal-swap-v1 (순위 신호 바꾸기) 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    name = "signal_swap_v1"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "research/jobs/signal-swap-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "signal-swap-v1" in valid, invalid.get("signal-swap-v1")
    job = json.loads((ROOT / "research/jobs/signal-swap-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 13 and job["resumable"] is True and job["max_memory_mb"] <= 2500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert (ROOT / "research/jobs/signal-swap-v1/SPEC.md").exists()


def test_pre_registered_constants():
    assert mod.CORE_VARIANTS == {"K12": (252, "zero"), "K6": (126, "zero"), "KRS": (252, "spy")}
    assert mod.SAT_VARIANTS == {"S12": 252, "S6": 126}
    assert len(mod.CANDIDATES) == mod.N_TRIALS == 6
    assert mod.BASELINES == {"A": "A_K12_S12", "B": "B_S12"}
    assert mod.N_BOOT == 1000 and mod.BLOCK_DAYS == 126 and mod.BOOT_SEED == 20261022
    assert mod.MDD_TOLERANCE == 0.02 and mod.CI_LOW_FLOOR == -0.005 and mod.LONGRUN_T_MIN == 2.0
    assert mod.WINDOWS["judged"] == ("2010-01-04", "2024-09-30") and mod.WINDOWS["h1"][1] == "2017-05-31"
    assert mod.POWER_YEARS == 14.7 and mod.SAT_WEIGHT == 0.15


def _path(idx, segments):
    """segments: [(행 수, 일별 수익)] — 마지막 구간이 남은 행을 채운다."""
    r = np.zeros(len(idx))
    pos = 0
    for n, x in segments:
        r[pos: pos + n] = x
        pos += n
    return 100 * np.cumprod(1 + r)


def _hand_data():
    idx = pd.bdate_range("2018-01-01", "2019-12-31")
    n = len(idx)
    cut = n - 140  # 2019 하반기 이전까지 강하다가 최근 126행은 하락
    closes = pd.DataFrame({
        "FADE": _path(idx, [(cut, 0.003), (n - cut, -0.0015)]),       # 12개월 +, 6개월 −
        "RISE": _path(idx, [(cut, -0.0005), (n - cut, 0.002)]),       # 6개월 +
        "SLOW": _path(idx, [(n, 0.0002)]),                            # +, SPY 보다 낮음
        "FAST": _path(idx, [(n, 0.0012)]),                            # SPY 보다 높음
        "BIL": _path(idx, [(n, 0.00005)]),
    }, index=idx)
    spy = pd.Series(_path(idx, [(n, 0.0008)]), index=idx)
    return closes, spy


def _row(w, d):
    r = w.loc[d]
    return {c: round(float(v), 6) for c, v in r.items() if v > 0}


def test_core_variant_eligibility_and_ranking():
    closes, spy = _hand_data()
    d = pd.Timestamp("2019-12-02")
    k12 = _row(mod.core_variant_weights(closes, spy, "K12"), d)
    k6 = _row(mod.core_variant_weights(closes, spy, "K6"), d)
    krs = _row(mod.core_variant_weights(closes, spy, "KRS"), d)
    # K12: 252 수익 > 0 인 FADE·FAST·SLOW (RISE 는 12개월 −?) — 계산으로 확인
    m12 = closes.drop(columns="BIL").pct_change(252, fill_method=None).loc["2019-11-29"]
    assert set(k12) - {"BIL"} == set(m12[m12 > 0].index)
    assert "FADE" in k12 and "FADE" not in k6 and "RISE" in k6
    # KRS: SPY 252 수익보다 높은 자산만 — SLOW(양수지만 SPY 아래) 빠짐
    assert "SLOW" in k12 and "SLOW" not in krs and "FAST" in krs
    for w in (k12, k6, krs):
        assert abs(sum(w.values()) - 1.0) < 1e-9 and all(v in (0.25,) for t, v in w.items() if t != "BIL")


def test_k12_equals_live_core_weights():
    from core.champion_strategy import _build_core_weights

    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2012-01-01", "2016-12-31")
    cols = [f"E{i}" for i in range(9)] + ["BIL"]
    closes = pd.DataFrame(50 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, (len(idx), len(cols))), axis=0)), index=idx, columns=cols)
    spy = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, len(idx)))), index=idx)
    mine = mod.core_variant_weights(closes, spy, "K12")
    live = _build_core_weights(closes, spy, cash_ticker="BIL")
    assert np.abs(mine.to_numpy() - live[mine.columns].to_numpy()).max() < 1e-12
    assert (spy < spy.rolling(200).mean()).any()  # 시장 필터 경로도 지남


def test_core_no_lookahead():
    closes, spy = _hand_data()
    d = pd.Timestamp("2019-07-01")
    base = {v: mod.core_variant_weights(closes, spy, v).loc[d] for v in mod.CORE_VARIANTS}
    c2, s2 = closes.copy(), spy.copy()
    c2.loc[d:] *= np.linspace(0.2, 5, len(c2.loc[d:]))[:, None]
    s2.loc[d:] *= 3
    for v in mod.CORE_VARIANTS:
        assert (mod.core_variant_weights(c2, s2, v).loc[d] == base[v]).all()


def test_satellite_s6_ranks_by_126_rows():
    from core import satellite_lab as sl

    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    sig = sl.load_signal(code)
    idx = pd.bdate_range("2017-01-01", "2019-06-30")
    n = len(idx)
    mk = lambda c: pd.DataFrame({"Close": c}, index=idx)  # noqa: E731
    # 둘 다 마지막 날 새 고점(추세 활성). LONG: 12개월 크고 6개월 작음, SHORT: 반대
    long_ = _path(idx, [(n - 130, 0.004), (125, 0.0003), (5, 0.01)])
    short = _path(idx, [(n - 130, -0.001), (125, 0.003), (5, 0.01)])
    prices = {"LONG": mk(long_), "SHORT": mk(short)}
    s12 = sig(prices, idx[-1], {"mom_window": mod.SAT_VARIANTS["S12"]})
    s6 = sig(prices, idx[-1], {"mom_window": mod.SAT_VARIANTS["S6"]})
    assert set(s12) == set(s6) == {"LONG", "SHORT"}
    assert s12["LONG"] > s12["SHORT"] and s6["SHORT"] > s6["LONG"]
    assert abs(s6["SHORT"] - (short[-1] / short[-1 - 126] - 1)) < 1e-12
    assert mod.sat_params("S12") == dict(spec["signal"]["params_grid"][0])


def test_s12_equals_s_seed_000_and_s6_differs():
    from core import satellite_lab as sl

    pp, poolp = sl.synthetic_providers(n_tickers=20, start="2008-01-01", end="2014-12-31", seed=7)
    pool = mod.SV._pool_wrapper(poolp, date(2010, 1, 1))
    data = sl.build_data({"champion40"}, start="2009-12-01", end="2014-12-31", pool_provider=pool, price_provider=pp)
    spec, signal, params = mod.SV._incumbent()
    sp = json.loads(json.dumps(spec))
    sp["pool"] = {"type": "champion40"}
    ref = mod.SV.schedule_to_log(sl.run_variant(sp, params, signal, data)["schedule"])
    assert mod.sat_schedule(data, "S12") == ref
    s6 = mod.sat_schedule(data, "S6")
    assert [r["date"] for r in s6] == [r["date"] for r in ref] and s6 != ref


def test_longrun_weights_match_lab_and_krs_hurdle():
    lab = mod.LAB
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("1930-01-01", "1936-12-31")
    rets = pd.DataFrame(rng.normal(0.0003, 0.01, (len(idx), 6)), index=idx, columns=list("ABCDEF"))
    mkt = rets.mean(axis=1) + rng.normal(0, 0.002, len(idx))
    assert np.allclose(mod.longrun_weights(rets, mkt, "K12").to_numpy(), lab.target_weights(rets, mkt, lab.Rule()).to_numpy())
    assert np.allclose(mod.longrun_weights(rets, mkt, "K6").to_numpy(), lab.target_weights(rets, mkt, lab.Rule(lookback=126)).to_numpy())
    w = mod.longrun_weights(rets, mkt, "KRS")
    mom = np.expm1(np.log1p(rets).rolling(252).sum())
    mm = np.expm1(np.log1p(mkt).rolling(252).sum())
    firsts = np.where(lab.month_first_mask(idx))[0]
    for i in firsts[firsts > 260]:
        held = set(w.columns[w.iloc[i] > 0])
        elig = set(mom.columns[mom.iloc[i - 1] > mm.iloc[i - 1]])
        assert held <= elig


ARGS = dict(d_judged=0.01, d_h1=0.005, d_h2=0.002, mdd_cand=-0.30, mdd_base=-0.29, ci_low=-0.004)
LR_OK = {"cagr": 0.12, "cagr_k12": 0.12, "alpha_t": 2.0}


@pytest.mark.parametrize("over,lr,expect,miss", [
    ({}, None, mod.PASS, []),
    ({}, LR_OK, mod.PASS, []),
    ({"d_judged": 0.0}, None, mod.FAIL, ["a_judged_diff_gt_0"]),
    ({"d_h2": 0.0}, None, mod.FAIL, ["b_both_halves_gt_0"]),
    ({"mdd_cand": -0.3101}, None, mod.FAIL, ["c_mdd_not_worse_than_2pp"]),
    ({"mdd_cand": -0.3099}, None, mod.PASS, []),
    ({"ci_low": -0.005}, None, mod.FAIL, ["d_boot_ci90_low_gt_minus_0.5pp"]),
    ({}, {"cagr": 0.1199, "cagr_k12": 0.12, "alpha_t": 3.0}, mod.FAIL, ["e_longrun_cagr_ge_k12"]),
    ({}, {"cagr": 0.13, "cagr_k12": 0.12, "alpha_t": 1.99}, mod.FAIL, ["f_longrun_alpha_t_ge_2"]),
    ({}, {"cagr": float("nan"), "cagr_k12": 0.12, "alpha_t": 3.0}, mod.NOT_EVALUABLE, ["longrun_non_finite"]),
    ({"ci_low": float("nan")}, None, mod.NOT_EVALUABLE, ["non_finite"]),
])
def test_pass_rule_edges(over, lr, expect, miss):
    v, m = mod.decide(**{**ARGS, **over}, longrun=lr)
    assert v == expect and m == miss


def test_noop_is_not_evaluable():
    assert mod.decide(**ARGS, longrun=LR_OK, noop="identical")[0] == mod.NOT_EVALUABLE


def test_smoke_resume_3_then_0(tmp_path):
    out, ck = tmp_path / "o", tmp_path / "c"
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck), "--max-sims-per-run", "5"]) == 3
    assert not (out / "results.json").exists()
    assert (ck / "longrun.pkl").exists() and (ck / "inputs.pkl").exists()
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck)]) == 0
    r = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert all(r["smoke_coverage"].values())
    assert set(r["verdicts"]) == set(mod.CANDIDATES)
    assert all(v.startswith("SMOKE_ONLY(") for v in r["verdicts"].values())
    assert (out / "results.json").stat().st_size < 200_000
    rep = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "생존편향" in rep and "자격 기준만" in rep
