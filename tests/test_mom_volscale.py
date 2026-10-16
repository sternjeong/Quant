"""mom-volscale-v1 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("mom_volscale_v1", ROOT / "research/jobs/mom-volscale-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _panel(n=600, k=6, seed=0):
    idx = pd.bdate_range("2000-01-03", periods=n)
    rng = np.random.default_rng(seed)
    r = pd.DataFrame(rng.normal(0.0003, 0.01, (n, k)), index=idx, columns=[f"I{j}" for j in range(k)])
    return r, pd.Series(0.0001, index=idx)


def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "mom-volscale-v1" in valid, invalid.get("mom-volscale-v1")
    job = json.loads((ROOT / "research/jobs/mom-volscale-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 17 and job["resumable"] is True and job["max_memory_mb"] <= 1500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"


def test_pre_registered_constants():
    assert len(mod.CELLS) == 32 == mod.N_TRIALS and mod.POWER_YEARS == 41
    assert mod.SELECTION == ("1927-07-01", "1966-12-31") and mod.CONFIRMATION == ("1967-01-01", "2007-12-31")
    assert mod.CONF_HALVES == (("1967-01-01", "1986-12-31"), ("1987-01-01", "2007-12-31"))
    assert mod.VT_TARGET == {"VT12": 0.12, "VT15": 0.15, "VT20": 0.20}
    assert (mod.LOOKBACK, mod.VOL_WINDOW, mod.SMA_WINDOW, mod.FILTER_CUT, mod.EXPOSURE_CAP) == (252, 126, 200, 0.5, 1.0)
    assert (mod.COST_BPS, mod.BH_DRAG, mod.CAGR_MARGIN, mod.ROLL_SLACK, mod.ALPHA_T_MIN, mod.VOLSCALE_MIN_SLEEVES) == (
        10.0, 0.01, 0.015, 0.05, 2.0, 3)
    assert mod.BH_DATASET[1] == "6_Portfolios_ME_Prior_12_2_Daily_CSV.zip" and mod.BH_COLUMN == "BIG HiPRIOR"


def test_vol_estimate_uses_only_prior_rows():
    raw = np.random.default_rng(1).normal(0, 0.01, 400)
    d = 300
    v = mod.realized_vol(raw, d)
    alt = raw.copy()
    alt[d:] *= 50                      # 결정일 당일부터 바꿔도 같아야
    assert mod.realized_vol(alt, d) == v
    alt2 = raw.copy()
    alt2[d - 1] *= 50                  # 바로 전 행은 들어가야
    assert mod.realized_vol(alt2, d) != v
    assert math.isclose(v, np.std(raw[d - 126: d], ddof=1) * math.sqrt(252))
    assert math.isnan(mod.realized_vol(raw, 100))
    raw[250] = np.nan
    assert math.isnan(mod.realized_vol(raw, 300))


def test_exposure_cap_and_fallbacks():
    assert mod.vt_exposure(0.30, 0.15) == 0.5
    assert mod.vt_exposure(0.05, 0.15) == 1.0           # 상한 1.0(레버리지 없음)
    assert mod.vt_exposure(float("nan"), 0.15) == 1.0   # 이력 부족
    assert mod.vt_exposure(0.40, None) == 1.0           # 조정 없음


def test_filter_halves_exposure_using_prior_row():
    raw = np.r_[np.full(10, np.nan), np.random.default_rng(2).normal(0, 0.03, 290)]
    below = np.zeros(300, dtype=bool)
    below[199] = True                  # 결정일 200 의 전날
    sched = {200: [0], 250: [0], 5: None}
    e = mod.exposure_schedule(raw, below, sched, "none", "F")
    assert e == {200: 0.5, 250: 1.0, 5: 0.0}
    e_vt = mod.exposure_schedule(raw, below, sched, "VT12", "F")
    base = mod.vt_exposure(mod.realized_vol(raw, 200), 0.12)
    assert math.isclose(e_vt[200], base * 0.5) and e_vt[250] <= 1.0
    below2 = below.copy()
    below2[199], below2[200] = False, True   # 결정일 당일 값은 쓰지 않는다
    assert mod.exposure_schedule(raw, below2, sched, "none", "F")[200] == 1.0


def test_market_below_sma():
    idx = pd.bdate_range("2000-01-03", periods=260)
    m = pd.Series(np.r_[np.full(230, 0.002), np.full(30, -0.02)], index=idx)
    b = mod.market_below_sma(m, idx)
    assert not b[:199].any() and b[-1]


def test_top_k_selection_prior_data_and_ties():
    r, _ = _panel()
    s = mod.pick_schedule(r, "I2")
    rows = sorted(s)
    d = [x for x in rows if s[x] is not None][-2]
    mom = np.expm1(np.log1p(r).iloc[d - 252: d].sum()).to_numpy()
    assert set(s[d]) == set(np.argsort(-mom)[:2])
    r2 = r.copy()
    r2.iloc[d:, 0] = 0.3
    assert mod.pick_schedule(r2, "I2")[d] == s[d]
    assert mod.select_top(np.array([0.1, 0.3, 0.3, np.nan]), 2) == [1, 2]
    assert mod.select_top(np.array([np.nan, 0.3, np.nan]), 2) is None
    assert all(v is None for x, v in s.items() if x <= 252)


def test_simulate_exposure_and_cost():
    r, rf = _panel(n=80, k=2)
    idx = r.index
    d = int(mod.decision_rows(idx)[1])
    sched = {d: [0]}
    sim = mod.simulate(r, rf, sched, {d: 0.4}, 1, bps=10.0)
    assert math.isclose(sim["risky"].iloc[d], 0.4) and math.isclose(sim["turnover"].iloc[d], 0.4)
    nxt = d + 1
    exp = 0.4 * (1 + r.iloc[nxt, 0]) + 0.6 * (1 + rf.iloc[nxt]) - 1
    assert math.isclose(sim["returns"].iloc[nxt], exp, rel_tol=1e-12)
    assert math.isclose(sim["returns"].iloc[d], (1 + rf.iloc[d]) * (1 - 0.4 * 0.001) - 1, rel_tol=1e-12)
    assert sim["risky"].max() <= 1.0 + 1e-12


def test_stability_metrics():
    idx = pd.bdate_range("2000-01-03", periods=600)
    r = pd.Series(0.0, index=idx)
    r.iloc[0] = -0.10
    assert math.isclose(mod.max_drawdown(r), -0.10)          # 시작 값 1 이 첫 고점
    r2 = pd.Series(0.001, index=idx)
    r2.iloc[300] = -0.5
    w = mod.worst_rolling(r2)
    assert math.isclose(w, 0.5 * 1.001 ** 251 - 1)
    assert mod.worst_rolling(r2.iloc[:200]) is None
    st, mk = {"mdd": -0.3, "worst_252": -0.40}, {"mdd": -0.3, "worst_252": -0.36}
    assert mod.stability(st, mk) == {"A_mdd": True, "B_worst252": True}
    assert mod.stability({"mdd": -0.31, "worst_252": -0.42}, mk) == {"A_mdd": False, "B_worst252": False}


def _s(cagr, mdd=-0.3, worst=-0.3, calmar=None):
    return {"cagr": cagr, "mdd": mdd, "worst_252": worst, "calmar": calmar if calmar is not None else cagr / abs(mdd)}


def test_selection_rule_and_ties():
    mk = {"mdd": -0.5, "worst_252": -0.4}
    sel = {c: _s(0.05) for c in mod.CELLS}
    sel["I1/none/none"] = _s(0.30, mdd=-0.6)          # 수익 최고지만 A 미달
    sel["I2/VT15/F"] = _s(0.12)
    sel["BH/none/F"] = _s(0.12)                        # 동점 → 조정 없음이 먼저
    assert mod.select_cell(sel, mk) == "BH/none/F"
    sel["I4/none/none"] = _s(0.12)                     # 필터 없음이 F 보다 먼저
    assert mod.select_cell(sel, mk) == "I4/none/none"
    sel["I2/VT15/F"] = _s(0.13, worst=-0.46)           # B 미달(−0.4 − 5%p 보다 나쁨)
    assert mod.select_cell(sel, mk) == "I4/none/none"
    assert mod.select_cell({c: _s(0.1, mdd=-0.9) for c in mod.CELLS}, mk) is None


def test_primary_verdict_paths():
    rep = {"mde_ir": 0.58}
    ok = {"cagr_margin": True, "A_mdd": True, "B_worst252": True, "both_halves": True, "alpha_t": True}
    assert mod.primary_verdict("I1/none/F", ok, None, 0.7, rep) == mod.PASS
    assert mod.primary_verdict("I1/none/F", dict(ok, alpha_t=False), None, 0.3, rep) == "FAIL_UNDERPOWERED"
    assert mod.primary_verdict("I1/none/F", ok, "same", 0.7, rep) == mod.NOT_EVALUABLE
    assert mod.primary_verdict(None, None, None, None, rep) == mod.FAIL
    ch = mod.confirmation_checks({"cagr": 0.12, "mdd": -0.3, "worst_252": -0.2, "alpha_t_nw6": 2.1},
                                 {"cagr": 0.10, "mdd": -0.5, "worst_252": -0.4},
                                 [{"cagr": 0.1, "market_cagr": 0.09}, {"cagr": 0.1, "market_cagr": 0.1}])
    assert ch == {"cagr_margin": True, "A_mdd": True, "B_worst252": True, "both_halves": False, "alpha_t": True}


def test_volscale_helps_logic():
    mk = {"mdd": -0.5, "worst_252": -0.4}
    sel = {c: _s(0.05) for c in mod.CELLS}
    conf = {c: _s(0.05) for c in mod.CELLS}
    for s in mod.SLEEVES:
        sel[f"{s}/none/F"] = _s(0.10)                  # 최선 칸 → 필터 F
        sel[f"{s}/VT15/F"] = _s(0.04, calmar=0.9)      # 선택 구간 CAGR/|MDD| 최고 VT
        conf[f"{s}/none/F"] = _s(0.08, calmar=0.30)
        conf[f"{s}/VT15/F"] = _s(0.06, calmar=0.35)
    conf["BH/VT15/F"] = _s(0.06, calmar=0.30)          # 같음 → 개선 아님
    res = mod.volscale_check(sel, conf, mk)
    assert res["sleeves"]["I1"]["filter"] == "F" and res["sleeves"]["I1"]["vt_cell"] == "I1/VT15/F"
    assert res["n_improved"] == 3 and res["verdict"] == mod.HELPS
    conf["I4/VT15/F"] = _s(0.06, calmar=0.10)
    assert mod.volscale_check(sel, conf, mk)["verdict"] == mod.NOT_SHOWN
    # 소매의 A·B 통과 칸이 없으면 CAGR 최고 칸의 필터
    for c in mod.CELLS:
        if c.startswith("I1/"):
            sel[c] = _s(0.05, mdd=-0.9)
    sel["I1/VT20/none"] = _s(0.2, mdd=-0.9)
    assert mod.volscale_check(sel, conf, mk)["sleeves"]["I1"]["filter"] == "none"


def test_frontier():
    st = {"a": {"cagr": 0.10, "mdd": -0.5}, "b": {"cagr": 0.08, "mdd": -0.3}, "c": {"cagr": 0.07, "mdd": -0.4},
          "d": {"cagr": 0.10, "mdd": -0.5}}
    assert set(mod.frontier(st)) == {"a", "b", "d"}


def test_smoke_resume(tmp_path):
    out, ck = tmp_path / "out", tmp_path / "ck"
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck), "--max-steps-per-run", "2"]) == 3
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck)]) == 0
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert all(res["smoke_coverage"].values()) and res["verdicts"]["primary"].startswith("SMOKE_ONLY")
    assert len(res["cells"]) == 32 and res["power"]["n_trials"] == 32
    assert (out / "results.json").stat().st_size < 200_000
    assert "|none|" not in (out / "REPORT.md").read_text(encoding="utf-8")
