"""sector-concentrate-v1 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("sector_concentrate_v1", ROOT / "research/jobs/sector-concentrate-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _panel(n=400, k=4, seed=0):
    idx = pd.bdate_range("2000-01-03", periods=n)
    rng = np.random.default_rng(seed)
    r = pd.DataFrame(rng.normal(0.0003, 0.01, (n, k)), index=idx, columns=[f"I{j}" for j in range(k)])
    return r, r.mean(axis=1)


def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "sector-concentrate-v1" in valid, invalid.get("sector-concentrate-v1")
    job = json.loads((ROOT / "research/jobs/sector-concentrate-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 12 and job["resumable"] is True and job["max_memory_mb"] <= 1500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"


def test_pre_registered_constants():
    assert mod.CELLS == ("M6_k1", "M6_k2", "RS12_k1", "RS12_k2", "C_k1", "C_k2") and mod.N_TRIALS == 6
    assert (mod.W_M6, mod.W_RS, mod.COST_BPS, mod.CAGR_MARGIN, mod.WORST12_SLACK, mod.ALPHA_T_MIN) == (126, 252, 10.0, 0.015, 0.05, 2.0)
    assert (mod.MAIN_START, mod.MAIN_END, mod.POWER_YEARS) == ("1927-07-01", "2007-12-31", 80.5)
    assert mod.ETF_SECTORS == ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC"]
    assert mod.ETF_WINDOWS["judged"] == ("2000-01-01", "2024-09-30") and mod.ETF_SPY_MARGIN == 0.005


def test_signals_use_only_prior_data():
    r, m = _panel()
    base = mod.pick_schedule(r, m, "C", 1)
    d_rows = [d for d, _ in base]
    target = d_rows[-3]
    r2 = r.copy()
    r2.iloc[target:] = r2.iloc[target:] * -50     # 결정일 당일부터 바꿔도 그날까지의 선택은 같아야
    m2 = r2.mean(axis=1)
    alt = dict(mod.pick_schedule(r2, m2, "C", 1))
    for d, p in base:
        if d <= target:
            assert alt[d] == p
    for sig in mod.SIGNALS:
        s1 = mod.raw_signals(r, m)[sig]
        s2 = mod.raw_signals(r2, m2)[sig]
        pd.testing.assert_frame_equal(s1.iloc[:target], s2.iloc[:target])


def test_signal_definitions():
    r, m = _panel(n=300)
    s = mod.raw_signals(r, m)
    i = 299
    m6 = (1 + r.iloc[i - 125: i + 1]).prod() - 1
    np.testing.assert_allclose(s["M6"].iloc[i].to_numpy(), m6.to_numpy(), rtol=1e-9)
    rs = (1 + r.iloc[i - 251: i + 1]).prod() - (1 + m.iloc[i - 251: i + 1]).prod()
    np.testing.assert_allclose(s["RS12"].iloc[i].to_numpy(), rs.to_numpy(), rtol=1e-9)
    c = (s["M6"].iloc[i].rank(pct=True) + s["RS12"].iloc[i].rank(pct=True)) / 2
    np.testing.assert_allclose(s["C"].iloc[i].to_numpy(), c.to_numpy())
    assert s["RS12"].iloc[250].isna().all() and s["M6"].iloc[125].notna().all()


def test_top_k_selection():
    assert mod.select_top(np.array([0.1, 0.5, np.nan, 0.3]), 1) == [1]
    assert mod.select_top(np.array([0.1, 0.5, np.nan, 0.3]), 2) is None          # 유효 3 < 4
    assert mod.select_top(np.array([0.1, 0.5, 0.2, 0.3]), 2) == [1, 3]
    assert mod.select_top(np.array([0.5, 0.5, 0.1]), 1) == [0]                   # 동점은 열 순서


def test_always_fully_invested_and_costs():
    r, m = _panel()
    for k in (1, 2):
        sched = mod.pick_schedule(r, m, "M6", k)
        st = mod.simulate(r, m, sched, k)
        assert np.allclose(st["invested"].to_numpy(), 1.0)
        free = mod.simulate(r, m, sched, k, bps=0.0)
        assert (st["returns"] <= free["returns"] + 1e-15).all()
        assert st["turnover"].sum() > 0
    # 선택이 없으면(신호 없음) 시장 그대로, 비용 없음
    st = mod.simulate(r, m, [], 1)
    np.testing.assert_allclose(st["returns"].iloc[1:].to_numpy(), m.iloc[1:].to_numpy())


def test_hold_one_industry_tracks_it_after_trade_day():
    r, m = _panel(n=60)
    sched = [(21, [2])]
    st = mod.simulate(r, m, sched, 1, bps=0.0)
    np.testing.assert_allclose(st["returns"].iloc[22:].to_numpy(), r["I2"].iloc[22:].to_numpy())
    np.testing.assert_allclose(st["returns"].iloc[1:22].to_numpy(), m.iloc[1:22].to_numpy())


def test_drawdown_worst12_underwater_hand_built():
    idx = pd.date_range("2000-01-31", periods=15, freq="ME")
    v = pd.Series([1.1, 1.2, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.25, 1.3, 1.3, 1.3, 1.4, 1.5], index=idx)
    assert mod.max_drawdown(v) == pytest.approx(-0.5)
    # 12개월 창: base 1.0→1.3, 1.1→1.3, 1.2→1.4(최악 +16.7%), 0.6→1.5
    assert mod.worst_rolling_12m(v) == pytest.approx(1.4 / 1.2 - 1)
    assert mod.worst_rolling_12m(v.iloc[:5]) is None
    uw = mod.longest_underwater(v)
    assert uw["peak"] == "2000-02-29" and uw["recovered"] == "2000-09-30" and not uw["ongoing"]
    uw2 = mod.longest_underwater(pd.Series([1.0, 0.5, 0.6], index=idx[:3]))
    assert uw2["ongoing"] and uw2["recovered"] is None


def test_subperiod_logic():
    idx = pd.bdate_range("1927-07-01", "2007-12-31")
    mkt = pd.Series(0.0002, index=idx)
    s = mkt.copy()
    s[(idx >= "1947-01-01") & (idx <= "1966-12-31")] = 0.0001   # 한 구간만 짐
    rows = mod.subperiod_rows(s, mkt)
    assert [x["beat"] for x in rows] == [False, False, False, False]  # 같거나 작으면 이김 아님
    s2 = s + 0.00001
    s2[(idx >= "1947-01-01") & (idx <= "1966-12-31")] = 0.0001
    assert [x["beat"] for x in mod.subperiod_rows(s2, mkt)] == [True, False, True, True]


@pytest.mark.parametrize("st,mk,beats,t,expect", [
    ({"cagr": 0.115, "mdd": -0.8, "worst_12m": -0.70}, {"cagr": 0.10, "mdd": -0.8, "worst_12m": -0.65}, 3, 2.0, True),   # 모두 경계
    ({"cagr": 0.1149, "mdd": -0.8, "worst_12m": -0.70}, {"cagr": 0.10, "mdd": -0.8, "worst_12m": -0.65}, 3, 2.0, False),  # (a)
    ({"cagr": 0.12, "mdd": -0.81, "worst_12m": -0.70}, {"cagr": 0.10, "mdd": -0.8, "worst_12m": -0.65}, 3, 2.0, False),   # A
    ({"cagr": 0.12, "mdd": -0.8, "worst_12m": -0.701}, {"cagr": 0.10, "mdd": -0.8, "worst_12m": -0.65}, 3, 2.0, False),   # B
    ({"cagr": 0.12, "mdd": -0.8, "worst_12m": -0.6}, {"cagr": 0.10, "mdd": -0.8, "worst_12m": -0.65}, 2, 2.0, False),     # d
    ({"cagr": 0.12, "mdd": -0.8, "worst_12m": -0.6}, {"cagr": 0.10, "mdd": -0.8, "worst_12m": -0.65}, 4, 1.99, False),    # e
])
def test_pass_rule_edges(st, mk, beats, t, expect):
    subs = [{"beat": i < beats} for i in range(4)]
    ch = mod.criteria(st, mk, subs, {"alpha_t_nw6": t})
    power = mod.rp.power_report(80.5, 6)
    v = mod.cell_verdict(ch, None, 0.1, power)
    assert (v == mod.PASS) is expect
    if not expect:
        assert v in ("FAIL", "FAIL_UNDERPOWERED")
    assert mod.cell_verdict(ch, "noop", 0.1, power) == mod.NOT_EVALUABLE


def test_etf_verdict_edges():
    spy = {"cagr_after_liq": 0.08, "mdd": -0.5, "worst_12m": -0.4}
    ok = {"cagr_after_liq": 0.085, "mdd": -0.5, "worst_12m": -0.45}
    assert mod.etf_verdict(ok, spy) == mod.SUPPORTING
    assert mod.etf_verdict({**ok, "cagr_after_liq": 0.0849}, spy) == mod.NOT_SUPPORTING
    assert mod.etf_verdict({**ok, "mdd": -0.51}, spy) == mod.NOT_SUPPORTING
    assert mod.etf_verdict({**ok, "worst_12m": -0.4501}, spy) == mod.NOT_SUPPORTING


def test_target_weight_frame_forces_monthly_rebalance():
    r, _ = _panel(n=80)
    sched = [(20, [1]), (40, [1]), (60, None)]
    w = mod.target_weight_frame(r, sched, 1, "MKT")
    assert w.iloc[:20]["MKT"].eq(1.0).all()
    assert w.iloc[30]["I1"] == pytest.approx(1.0) and w.iloc[50]["I1"] == pytest.approx(1.0)
    ch = w.diff().abs().sum(axis=1) > 1e-9
    assert ch.iloc[20] and ch.iloc[40] and ch.iloc[60] and not ch.iloc[41]


def test_smoke_resume_3_then_0(tmp_path):
    out, ck = tmp_path / "o", tmp_path / "c"
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck), "--max-steps-per-run", "3"]) == 3
    assert not (out / "results.json").exists()
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck)]) == 0
    r = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert all(r["smoke_coverage"].values())
    assert set(mod.CELLS) <= set(r["verdicts"])
    assert all(r["verdicts"][c].startswith("SMOKE_ONLY(") for c in mod.CELLS)
    assert r["power"]["n_trials"] == 6 and r["power"]["years"] == 80.5
    assert (out / "results.json").stat().st_size < 200_000
    rep = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "근사" in rep and "전진 원장" in rep
