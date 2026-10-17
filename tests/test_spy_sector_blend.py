"""spy-sector-blend-v1 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load("spy_sector_blend_v1_t", "research/jobs/spy-sector-blend-v1/run.py")
ft3 = mod.ft3
mv = mod.mv


def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "spy-sector-blend-v1" in valid, invalid.get("spy-sector-blend-v1")
    job = json.loads((ROOT / "research/jobs/spy-sector-blend-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 20 and job["resumable"] is True and job["max_memory_mb"] <= 2000
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert (ROOT / "research/jobs/spy-sector-blend-v1/SPEC.md").exists()


def test_pre_registered_constants():
    assert mod.WS == (0.15, 0.30, 0.50, 0.70, 1.00) and mod.N_TRIALS == 5
    assert (mod.POWER_YEARS_L, mod.POWER_YEARS_E) == (41, 24.7)
    assert mod.SELECTION == ("1927-07-01", "1966-12-31") and mod.CONFIRMATION == ("1967-01-01", "2007-12-31")
    assert mod.CONF_HALVES == {"h1": ("1967-01-01", "1986-12-31"), "h2": ("1987-01-01", "2007-12-31")}
    assert (mod.L_CAGR_MARGIN, mod.ROLL_SLACK, mod.ALPHA_T_MIN, mod.COST_BPS) == (0.01, 0.05, 2.0, 10.0)
    assert (mod.E_AFTER_TAX_MARGIN, mod.E_MDD_TOL, mod.E_BOOT_FLOOR) == (0.005, 0.03, -0.005)
    assert (mod.N_BOOT, mod.BLOCK_DAYS, mod.BOOT_SEED) == (1000, 126, 20261030)
    w = mod.etf_windows(False)
    assert w["judged"] == ("2000-01-03", "2024-09-30") and w["h1"][1] == "2012-06-30" and w["post"][0] == "2024-10-01"
    assert (ft3.VT_TARGET, ft3.VT_WINDOW, ft3.SC2_TOP, ft3.SC2_LOOKBACK) == (0.20, 126, 2, 252)


# ---------------------------------------------------------------- 섞기 산식
def _ref_blend(a, b, w, bps):
    """테스트용 독립 구현(값으로 추적)."""
    idx = a.index
    va, vb, out = w, 1 - w, []
    for i in range(len(idx)):
        prev = va + vb
        va, vb = va * (1 + a.iloc[i]), vb * (1 + b.iloc[i])
        tot = va + vb
        if i > 0 and idx[i].year != idx[i - 1].year:
            t = (abs(va - w * tot) + abs(vb - (1 - w) * tot)) / tot
            tot *= 1 - t * bps / 1e4
            va, vb = w * tot, (1 - w) * tot
        out.append(tot / prev - 1)
    return pd.Series(out, index=idx)


def _two_series(n=700, seed=1):
    idx = pd.bdate_range("2019-06-03", periods=n)
    rng = np.random.default_rng(seed)
    return (pd.Series(rng.normal(0.0008, 0.012, n), index=idx), pd.Series(rng.normal(0.0003, 0.008, n), index=idx))


def test_blend_math_and_annual_rebalance():
    a, b = _two_series()
    for w in (0.15, 0.5, 1.0):
        r, turn = mod.blend(a, b, w)
        assert np.allclose(r.to_numpy(), _ref_blend(a, b, w, 10.0).to_numpy(), atol=1e-14)
        assert np.allclose(r.to_numpy(), mod.lab.blend_returns(a, b, w).to_numpy(), atol=1e-14)   # 기존 산식과 같음
        # 재조정은 해가 바뀌는 첫 거래일에만
        yr = a.index.year
        assert set(turn[turn > 0].index) <= {a.index[i] for i in range(1, len(yr)) if yr[i] != yr[i - 1]}
    r1, t1 = mod.blend(a, b, 1.0)
    assert np.allclose(r1.to_numpy(), a.to_numpy()) and t1.sum() == 0          # w=100% 는 소매 그대로, 재조정 없음
    # 비용 = 회전율 × 10bp: 비용 0 과 10bp 의 누적 차이가 회전율에 비례
    r0, t0 = mod.blend(a, b, 0.5, bps=0.0)
    r10, t10 = mod.blend(a, b, 0.5)
    assert t10.sum() > 0 and (t0 > 0).equals(t10 > 0)
    first = t10[t10 > 0].index[0]
    assert t0.loc[first] == pytest.approx(t10.loc[first])                        # 첫 재조정까지는 같은 경로
    assert r0.loc[first] - r10.loc[first] == pytest.approx(t10.loc[first] * 10 / 1e4 * (1 + r0.loc[first]), rel=1e-6)
    # 일정한 수익이면 첫 해 끝 재조정 전 비중이 표류한 대로
    c = pd.Series(0.001, index=a.index)
    z = pd.Series(0.0, index=a.index)
    rc, tc = mod.blend(c, z, 0.5, bps=0.0)
    n0 = int((a.index.year == a.index[0].year).sum())
    va = 0.5 * 1.001 ** n0
    assert tc.iloc[n0] == pytest.approx(abs(va * 1.001 - 0.5 * (va * 1.001 + 0.5)) / (va * 1.001 + 0.5) * 2, rel=1e-9)


# ---------------------------------------------------------------- 소매 = mom-volscale-v1 I2/VT20/none
def test_long_sleeve_equals_mom_volscale_cell():
    data = mod.synthetic_long()
    sim = mod.long_sleeve(data)
    ref = mv.sleeve_stage(data, "I2")["cells"]["I2/VT20/none"]["windows"]
    for key, (a, b) in {"confirmation": mod.CONFIRMATION, "recent": mod.RECENT}.items():
        mine = mv.stats(sim, data["mkt"], data["rf"], a, b)
        for k in ("cagr", "mdd", "worst_252", "avg_exposure", "turnover_per_year", "alpha_t_nw6"):
            assert mine[k] == pytest.approx(ref[key][k], rel=1e-12, abs=1e-12), (key, k)
    assert sim["risky"].max() <= 1.0 + 1e-9 and sim["risky"].min() < 0.99      # 변동성 맞춤이 실제로 걸린다


# ---------------------------------------------------------------- SC2VT20 = forward_tournament_v3 정의
def _etf_prices(n=1000, seed=3):
    idx = pd.bdate_range("2015-01-02", periods=n)
    rng = np.random.default_rng(seed)
    cols = list(mod.ETF_MENU) + [mod.SPY]
    mk = rng.normal(0.0004, 0.014, n)
    trend = rng.normal(0, 0.0007, (n // 120 + 1, len(cols)))[np.arange(n) // 120]
    ret = mk[:, None] * np.linspace(0.7, 1.3, len(cols)) + trend + rng.normal(0, 0.009, (n, len(cols)))
    adj = pd.DataFrame(50 * (1 + ret).cumprod(axis=0), index=idx, columns=cols)
    adj.loc[idx < idx[400], "XLC"] = np.nan                                       # 늦게 상장
    adj.loc[idx < idx[300], "XLRE"] = np.nan
    adj["BIL"] = (90 * (1 + 0.00008) ** np.arange(n))
    adj.loc[idx < idx[500], "BIL"] = np.nan
    close = adj * 0.995
    return {"adj": adj, "close": close, "fx": pd.Series(1200.0, index=idx), "source": "t", "missing": []}


def test_sc2vt20_sleeve_equals_forward_tournament_definition():
    inp = _etf_prices()
    prep = mod.etf_prepare(inp)
    dec = mod.sleeve_decisions(prep)
    total = prep["total"]
    assert len(dec) > 30
    seen_scaled = seen_short = seen_new = False
    for d in dec:
        i = d["i"]
        sc2 = ft3.sc2_target(total.iloc[: i + 1])
        win = ft3.sc2_backfill_window(total.iloc[: i + 1])
        expo, vol = ft3.vol_exposure(win)
        assert d["weights"] == pytest.approx(sc2["weights"], abs=1e-15) and d["picks"] == sc2["picks"], d["date"]
        assert d["exposure"] == pytest.approx(expo, abs=1e-12) and d["n_window"] == len(win)
        assert (d["vol"] is None) == (vol is None)
        if vol is not None:
            assert d["vol"] == pytest.approx(vol, abs=1e-12)
        seen_scaled |= expo < 0.999
        seen_short |= len(win) < 126 and expo == 1.0
        seen_new |= any(p in ("XLC", "XLRE") for p in sc2["picks"])
    assert seen_scaled and seen_short                                              # 노출 상한·126개 미만 노출 1.0 둘 다 지난다
    first_xlc = total["XLC"].first_valid_index()
    for d in dec:                                                                  # 252행 전 XLC/XLRE 는 후보가 아니다
        if pd.Timestamp(d["date"]) < total.index[total.index.get_loc(first_xlc) + 253]:
            assert "XLC" not in d["picks"]


def test_etf_weights_reset_only_in_january_and_bil():
    inp = _etf_prices(n=1300)
    prep = mod.etf_prepare(inp)
    dec = mod.sleeve_decisions(prep)
    w = 0.3
    idx = prep["adj"].index
    start = str(idx[idx.to_period("M") == idx[420].to_period("M")][0].date())       # 월 첫 거래일
    jan = [d for d in dec if pd.Timestamp(d["date"]).month == 1 and pd.Timestamp(d["date"]) > pd.Timestamp(start)]
    assert jan
    W, meta = mod.build_etf_weights(prep, dec, w, start, None)
    assert (W.sum(axis=1) <= 1 + 1e-12).all() and (W >= -1e-15).all().all()
    by_date = {d["date"]: d for d in dec}
    # 시작일: SPY (1−w) + 소매 w (SPY 대체가 아니면 SPY 열은 정확히 1−w)
    d0 = by_date[start]
    r0 = W.loc[pd.Timestamp(start)]
    sleeve0 = w
    assert r0.sum() == pytest.approx(1.0 if d0["bil"] else 1.0 - (1 - d0["exposure"]) * w, abs=1e-6)
    if "SPY" not in d0["weights"]:
        assert r0["SPY"] == pytest.approx(1 - w, abs=1e-6)
        assert r0[[c for c in W.columns if c in d0["weights"]]].sum() == pytest.approx(w * d0["exposure"], abs=1e-6)
        if d0["bil"]:
            assert r0["BIL"] == pytest.approx(w * (1 - d0["exposure"]), abs=1e-6)
    # 1월이 아닌 결정일에는 SPY 몫이 (1−w) 로 되돌아가지 않고 표류한 값 — 1월에는 다시 (1−w)
    j = next(d for d in jan if "SPY" not in d["weights"])
    assert W.loc[pd.Timestamp(j["date"]), "SPY"] == pytest.approx(1 - w, abs=1e-6)
    nonjan = [d for d in dec if pd.Timestamp(d["date"]).month not in (1,) and pd.Timestamp(d["date"]) > pd.Timestamp(start)
              and pd.Timestamp(d["date"]) < pd.Timestamp(j["date"]) and "SPY" not in d["weights"]]
    assert nonjan and any(abs(W.loc[pd.Timestamp(d["date"]), "SPY"] - (1 - w)) > 1e-4 for d in nonjan)
    assert sleeve0 > 0 and meta["sleeve_turnover_per_year"] > 0
    # BIL 상장 전(결정일 bil=False)에는 BIL 비중 0, 남는 몫은 현금
    early = [d for d in dec if not d["bil"] and pd.Timestamp(d["date"]) >= pd.Timestamp(start)]
    assert early and all(W.loc[pd.Timestamp(d["date"]), "BIL"] == 0 for d in early)
    with pytest.raises(ValueError):
        mod.build_etf_weights(prep, dec, w, str(idx[idx.to_period("M") == idx[420].to_period("M")][2].date()), None)


# ---------------------------------------------------------------- 선택·판정
def _st(cagr, mdd, worst, **kw):
    d = {"cagr": cagr, "mdd": mdd, "worst_252": worst, "alpha_t_nw6": 3.0, "alpha_annual": 0.02, "appraisal_ir": 0.9}
    d.update(kw)
    return d


MKT = _st(0.10, -0.50, -0.40)


def test_selection_rule_ties_and_stability():
    sel = {"w15": _st(0.11, -0.45, -0.38), "w30": _st(0.12, -0.45, -0.38), "w50": _st(0.14, -0.55, -0.38),   # w50 A 미달
           "w70": _st(0.13, -0.45, -0.38), "w100": _st(0.15, -0.45, -0.46)}                                    # w100 B 미달(-0.40-0.05=-0.45)
    assert mod.select_w(sel, MKT) == "w70"
    sel["w100"] = _st(0.15, -0.50, -0.45)                                    # 경계값: A 같음, B 정확히 -5%p → 통과
    assert mod.select_w(sel, MKT) == "w100"
    sel["w30"] = _st(0.15, -0.45, -0.38)                                     # 동점이면 작은 w
    assert mod.select_w(sel, MKT) == "w30"
    assert mod.select_w({c: _st(0.2, -0.9, -0.9) for c in sel}, MKT) is None


def _fake_L(conf_cagr=0.12):
    cells, w_cagr = {}, {"w15": 0.11, "w30": 0.13, "w50": 0.12, "w70": 0.115, "w100": 0.10}
    for c, cg in w_cagr.items():
        win = {k: _st(cg, -0.45, -0.38) for k in mod.L_WINDOWS}
        win["confirmation"] = _st(conf_cagr + (0.001 if c == "w30" else 0.0), -0.45, -0.38)
        cells[c] = {"windows": win, "noop_vs_market": None}
    mk = {k: _st(0.10, -0.50, -0.40) for k in mod.L_WINDOWS}
    return {"cells": cells, "market": mk}


def test_selection_uses_selection_window_only():
    power = mod.rp.power_report(41, 5)
    base = mod.judge_long(_fake_L(), power)
    assert base["chosen"] == "w30"
    # 확인·하위·2008~ 값을 어떻게 바꿔도 고른 w 는 그대로, 선택 구간 값만 바꾸면 달라진다
    L = _fake_L(conf_cagr=0.30)
    for c in L["cells"].values():
        c["windows"]["recent"] = _st(-0.5, -0.9, -0.9)
        c["windows"]["h1"] = _st(-0.5, -0.9, -0.9)
    assert mod.judge_long(L, power)["chosen"] == "w30"
    L2 = _fake_L()
    L2["cells"]["w50"]["windows"]["selection"] = _st(0.20, -0.45, -0.38)
    assert mod.judge_long(L2, power)["chosen"] == "w50"


def _conf(**kw):
    c = _st(0.11, -0.50, -0.45)
    c.update(kw)
    return c


HALVES = [{"cagr": 0.12, "market_cagr": 0.10}, {"cagr": 0.12, "market_cagr": 0.10}]


def test_long_pass_rule_edges():
    ok = mod.confirmation_checks(_conf(alpha_t_nw6=2.0), MKT, HALVES)           # 전부 정확히 경계값
    assert all(v is True for v in ok.values()), ok
    assert mod.confirmation_checks(_conf(cagr=0.1099), MKT, HALVES)["cagr_margin"] is False
    assert mod.confirmation_checks(_conf(mdd=-0.5001), MKT, HALVES)["A_mdd"] is False
    assert mod.confirmation_checks(_conf(worst_252=-0.4501), MKT, HALVES)["B_worst252"] is False
    assert mod.confirmation_checks(_conf(alpha_t_nw6=1.99), MKT, HALVES)["alpha_t"] is False
    tie = [{"cagr": 0.10, "market_cagr": 0.10}, HALVES[1]]
    assert mod.confirmation_checks(_conf(), MKT, tie)["both_halves"] is False   # 같으면 미달(엄격)
    assert mod.confirmation_checks(_conf(cagr=float("nan")), MKT, HALVES)["cagr_margin"] is None


def test_etf_pass_rule_edges():
    spy = {"cagr_after_liq": 0.10, "mdd": -0.30}
    cand = {"cagr_after_liq": 0.105, "mdd": -0.33}
    ok = mod.etf_checks(cand, spy, [0.11, 0.12], [0.10, 0.11], -0.0049)
    assert all(v is True for v in ok.values()), ok
    assert mod.etf_checks({**cand, "cagr_after_liq": 0.1049}, spy, [0.11, 0.12], [0.10, 0.11], 0.0)["after_tax_margin"] is False
    assert mod.etf_checks({**cand, "mdd": -0.3301}, spy, [0.11, 0.12], [0.10, 0.11], 0.0)["mdd_within_3pp"] is False
    assert mod.etf_checks(cand, spy, [0.10, 0.12], [0.10, 0.11], 0.0)["both_halves"] is False
    assert mod.etf_checks(cand, spy, [0.11, 0.12], [0.10, 0.11], -0.005)["boot_low"] is False        # 하한은 엄격히 >
    assert mod.etf_checks(cand, spy, [0.11, 0.12], [0.10, 0.11], None)["boot_low"] is None


def test_verdict_paths_and_overall_mapping():
    p = mod.rp.power_report(41, 5)
    good = {"a": True, "b": True}
    assert mod.verdict_long(None, None, None, None, p) == "FAIL"
    assert mod.verdict_long("w30", good, "same", 1.0, p) == "NOT_EVALUABLE"
    assert mod.verdict_long("w30", good, None, 1.0, p) == "PASS_LONGRUN"
    assert mod.verdict_long("w30", {"a": True, "b": False}, None, 0.1, p) == "FAIL_UNDERPOWERED"
    assert mod.verdict_long("w30", {"a": True, "b": None}, None, 5.0, p) == "FAIL"
    assert mod.verdict_etf(None, None, None, None, p) == "NOT_JUDGED"
    assert mod.verdict_etf("w30", good, None, 1.0, p) == "PASS_ETF"
    assert mod.verdict_etf("w30", {"a": False}, "same", 1.0, p) == "NOT_EVALUABLE"
    assert mod.overall_verdict("PASS_LONGRUN", "PASS_ETF") == "BOTH_PASS"
    assert mod.overall_verdict("PASS_LONGRUN", "FAIL") == "LONGRUN_ONLY"
    assert mod.overall_verdict("FAIL_UNDERPOWERED", "PASS_ETF") == "ETF_ONLY"
    assert mod.overall_verdict("FAIL", "NOT_JUDGED") == "NEITHER"
    assert mod.overall_verdict("NOT_EVALUABLE", "NOT_EVALUABLE") == "NEITHER"


def test_bootstrap_deterministic_and_matches_satellite_value():
    rng = np.random.default_rng(0)
    a, b = rng.normal(0.0006, 0.01, 800), rng.normal(0.0004, 0.01, 800)
    x = mod.block_bootstrap_diff(a, b, 252, n_boot=60)
    assert np.array_equal(x, mod.block_bootstrap_diff(a, b, 252, n_boot=60))
    assert not np.array_equal(x, mod.block_bootstrap_diff(a, b, 252, n_boot=60, seed=1))
    sv = _load("ssb_sat_value_t", "research/jobs/satellite-value-v1/run.py")
    ref = sv.block_bootstrap_diff(a, b, 252, n_boot=60, block=mod.BLOCK_DAYS, seed=mod.BOOT_SEED)
    assert np.allclose(mod.block_bootstrap_diff(a, b, 252, n_boot=60), ref)


def test_smoke_resume(tmp_path):
    out, ck = tmp_path / "out", tmp_path / "ck"
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck), "--max-steps-per-run", "3"]) == 3
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck)]) == 0
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert all(res["smoke_coverage"].values()) and res["verdicts"]["overall"].startswith("SMOKE_ONLY")
    assert len(res["part_L"]["cells"]) == 5 and res["power"]["part_L"]["n_trials"] == 5 and res["power"]["part_E"]["n_trials"] == 1
    assert (out / "results.json").stat().st_size < 200_000
    assert "스모크" in (out / "REPORT.md").read_text(encoding="utf-8")
