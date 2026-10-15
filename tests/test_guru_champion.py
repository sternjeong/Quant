import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, job):
    spec = importlib.util.spec_from_file_location(name, ROOT / "research/jobs" / job / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load("guru_champion_v1", "guru-champion-v1")
sv, gm = mod.sv, mod.gm


@pytest.fixture(scope="module")
def smoke():
    data, per_guru, _ = mod.smoke_data()
    sch = mod.sleeve_schedules(data, per_guru)
    return data, per_guru, sch


def test_job_definition_matches_contract():
    job = json.loads((ROOT / "research/jobs/guru-champion-v1/job.json").read_text(encoding="utf-8"))
    assert job["id"] == "guru-champion-v1" and job["priority"] == 7 and job["resumable"] is True
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert job["max_memory_mb"] <= 3000 and (ROOT / job["entrypoint"]).is_file()
    assert (ROOT / "research/jobs/guru-champion-v1/SPEC.md").is_file()


def test_pre_registered_constants_are_fixed():
    assert mod.DECISION_END == "2024-09-30" and mod.H1_END == "2019-05-31" and mod.JUDGE_START == "2014-01-01"
    assert mod.MDD_TOL == 0.03 and mod.CI_LOW_FLOOR == -0.005 and mod.N_BOOT == 1000 and mod.BLOCK_DAYS == 126
    assert mod.BOOT_SEED == 20261018 and mod.CI_PCT == (5.0, 95.0) and (mod.POWER_YEARS, mod.POWER_TRIALS) == (10.75, 2)
    assert mod.JUDGED == {"C1_vs_C0": ("C1", "C0"), "D1_vs_D0": ("D1", "D0")}
    assert mod.SAT_WEIGHT == 0.15 and mod.SPY_WEIGHT == 0.85


def test_pass_rule_edges():
    d = lambda *a, **k: mod.decide(*a, **k)["verdict"]  # noqa: E731
    assert d(0.001, 0.001, 0.001, -0.30, -0.27, -0.0049) == mod.PASS           # MDD 정확히 3%p 나쁨은 허용
    assert d(0.0, 0.001, 0.001, -0.2, -0.2, 0.0) == mod.FAIL                   # 차이 0 은 > 0 아님
    assert d(0.01, 0.0, 0.01, -0.2, -0.2, 0.0) == mod.FAIL                     # 절반 0
    assert d(0.01, 0.01, 0.01, -0.3001, -0.27, 0.0) == mod.FAIL                # MDD 3%p 초과
    assert d(0.01, 0.01, 0.01, -0.2, -0.2, -0.005) == mod.FAIL                 # 하한 정확히 −0.5%p
    assert d(0.01, 0.01, 0.01, -0.2, -0.2, 0.0, "noop") == mod.NOT_EVALUABLE
    assert d(float("nan"), 0.01, 0.01, -0.2, -0.2, 0.0) == mod.NOT_EVALUABLE
    assert mod.decide(-0.01, -0.01, 0.01, -0.5, -0.2, -0.02)["failed"] == [
        "a_diff_positive", "b_both_halves_positive", "c_mdd_within_3pp", "d_boot_ci_low"]


def test_bootstrap_is_deterministic():
    rng = np.random.default_rng(0)
    a, b = rng.normal(0.0004, 0.01, 600), rng.normal(0.0003, 0.01, 600)
    x = sv.block_bootstrap_diff(a, b, 252, n_boot=200, block=mod.BLOCK_DAYS, seed=mod.BOOT_SEED)
    y = sv.block_bootstrap_diff(a, b, 252, n_boot=200, block=mod.BLOCK_DAYS, seed=mod.BOOT_SEED)
    z = sv.block_bootstrap_diff(a, b, 252, n_boot=200, block=mod.BLOCK_DAYS, seed=20261010)
    assert np.array_equal(x, y) and not np.array_equal(x, z)


def test_segments_fixed_halves():
    idx = pd.bdate_range("2014-01-02", "2026-06-30")
    s = mod.segments(idx)
    assert s["h1"][1] == pd.Timestamp("2019-05-31") and s["h2"] == (pd.Timestamp("2019-05-31"), pd.Timestamp("2024-09-30"))
    assert "post_2024_10" in s
    v = pd.Series([100.0, 120.0, 90.0, 130.0], index=pd.bdate_range("2014-01-02", periods=4))
    assert abs(mod.mdd_window(v, 100.0, v.index[-1]) - (90 / 120 - 1)) < 1e-12


def test_spy_sleeve_resets_only_in_january():
    idx = pd.bdate_range("2014-01-01", "2015-12-31")
    adj = pd.DataFrame({"SPY": np.linspace(100, 200, len(idx)), "X": 50.0, "Y": np.linspace(10, 30, len(idx))}, index=idx)
    log = [{"date": "2014-01-01", "weights": {"X": 1.0}}, {"date": "2014-07-01", "weights": {"Y": 1.0}},
           {"date": "2015-01-01", "weights": {"Y": 1.0}}, {"date": "2015-07-01", "weights": {}}]
    w = mod.spy_sleeve_weights(idx, log, adj)
    assert w.loc["2014-01-01", "SPY"] == pytest.approx(0.85) and w.loc["2014-01-01", "X"] == pytest.approx(0.15)
    g = adj.at[pd.Timestamp("2014-07-01"), "SPY"] / 100
    assert w.loc["2014-07-01", "SPY"] == pytest.approx(0.85 * g / (0.85 * g + 0.15))   # 표류 비중, SPY 몫 유지
    assert w.loc["2014-07-01", "X"] == 0 and w.loc["2014-07-01", "Y"] == pytest.approx(1 - w.loc["2014-07-01", "SPY"])
    assert w.loc["2015-01-01", "SPY"] == pytest.approx(0.85) and w.loc["2015-01-01", "Y"] == pytest.approx(0.15)
    assert w.loc["2015-07-01", "Y"] == 0 and w.loc["2015-07-01"].sum() < 1                # 빈 선정 = 현금
    changes = w.index[w.diff().abs().sum(axis=1) > 1e-12]
    assert set(changes) == {pd.Timestamp(x) for x in ("2014-07-01", "2015-01-01", "2015-07-01")}


def test_s1_picks_equal_guru_mechanism_g1(smoke):
    from core import satellite_lab as sl

    data, per_guru, sch = smoke
    spec0, sig0, p0 = mod._seed("S-SEED-000")
    spec0 = sl.validate_spec({**spec0, "pool": {"type": "sp500_pit"}})
    spec19, sig19, p19 = mod._seed("S-SEED-019")
    g1 = sl.run_variant(spec19, p19, sig19, data)["schedule"]                     # guru-mechanism-v1 의 G1 경로
    assert sch["S1"] == g1
    for d, picks in sch["S1"][8:14]:                                               # 독립 경로: 현 규칙 점수 + 거장 가점
        row = gm.build_panel_row(data, pd.Timestamp(d), spec0, sig0, p0, per_guru)
        assert picks == gm.boosted_picks(row["base"], row["eligible"], gm.g1_boost_set(row), 3)
    assert sch["S1"] != sch["S0p"]


def test_13f_filed_on_rebalance_day_is_not_used(smoke):
    from core import satellite_lab as sl

    data, _, sch = smoke
    spec0, sig0, p0 = mod._seed("S-SEED-000")
    spec0 = sl.validate_spec({**spec0, "pool": {"type": "sp500_pit"}})
    d = pd.Timestamp(sch["S0p"][10][0])
    row = gm.build_panel_row(data, d, spec0, sig0, p0, {})
    target = sorted(set(row["base"]) - set(sch["S0p"][10][1]))[0]
    cutoff = sl._prev_day(data.trading_days, d).date()

    def filing(filed):
        return {"G": [{"accession": "x", "filed": filed.isoformat(), "period": "2010-01-01",
                       "holdings": [{"name": target, "cusip": "", "ticker": target, "weight": 1.0}]}]}

    late = mod.sleeve_schedules(data, filing(d.date()))["S1"]
    early = mod.sleeve_schedules(data, filing(cutoff))["S1"]
    i = [x[0] for x in late].index(str(d.date()))
    assert target not in late[i][1] and late[i][1] == sch["S0p"][10][1]
    assert target in early[i][1]


def test_c0_equals_satellite_value_champion(smoke):
    data, _, sch = smoke
    sv_in = sv._smoke_inputs(lambda s: None)
    mine = mod._smoke_inputs(lambda s: None)
    start = pd.Timestamp(mine["start"])
    assert mine["logs"]["S0"] == mod.filter_log(sv_in["logs"]["A"], start)
    a = sv.build_weights(sv_in["core_w"], sv_in["logs"])["A"]
    c0 = mod.build_weights(mine["core_w"], mine["logs"], mine["adj"])["C0"]
    pd.testing.assert_frame_equal(c0, a.loc[start:].loc[:, c0.columns], check_freq=False)
    assert (a.loc[start:].drop(columns=c0.columns).abs().sum().sum()) == 0


def test_smoke_resume_3_then_0(tmp_path):
    cmd = [sys.executable, str(ROOT / "research/jobs/guru-champion-v1/run.py"), "--smoke",
           "--out", str(tmp_path / "out"), "--checkpoint", str(tmp_path / "ck")]
    assert subprocess.run(cmd + ["--max-sims-per-run", "3"], capture_output=True).returncode == 3
    assert subprocess.run(cmd, capture_output=True).returncode == 0
    res = json.loads((tmp_path / "out/results.json").read_text(encoding="utf-8"))
    assert set(res["verdicts"]) == {"C1_vs_C0", "D1_vs_D0"} and all(v.startswith("SMOKE_ONLY(") for v in res["verdicts"].values())
    assert (tmp_path / "out/results.json").stat().st_size < 200_000
    assert res["power"]["years"] == 10.75 and res["power"]["n_trials"] == 2
    assert "전진 원장" in (tmp_path / "out/REPORT.md").read_text(encoding="utf-8")
