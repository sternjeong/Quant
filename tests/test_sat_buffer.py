"""sat-buffer-v1 (새틀라이트 순위 버퍼) 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

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
    spec = importlib.util.spec_from_file_location("sat_buffer_v1", ROOT / "research/jobs/sat-buffer-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()

# 점수: A > B > ... > L
POOL = {t: 1.0 - i * 0.05 for i, t in enumerate("ABCDEFGHIJKL")}


# ---- 계약·상수 -------------------------------------------------------------------------------------------

def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "sat-buffer-v1" in valid, invalid.get("sat-buffer-v1")
    job = json.loads((ROOT / "research/jobs/sat-buffer-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 6 and job["resumable"] is True and job["max_memory_mb"] <= 2500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert (ROOT / "research/jobs/sat-buffer-v1/SPEC.md").exists()


def test_pre_registered_constants():
    assert mod.VARIANT_RULES == {"B0": (None, (1, 7)), "K6_H6": (6, (1, 7)), "K10_H6": (10, (1, 7)),
                                 "K6_H12": (6, (1,)), "K10_H12": (10, (1,))}
    assert mod.JUDGED == ("K6_H6", "K10_H6", "K6_H12", "K10_H12")
    assert mod.N_BOOT == 1000 and mod.BLOCK_DAYS == 126 and mod.BOOT_SEED == 20261017
    assert mod.CI_LOW_FLOOR == -0.005 and mod.MDD_TOL == 0.02 and mod.SAT_WEIGHT == 0.15
    assert mod.POWER_YEARS == 14.7 and mod.N_TRIALS == 4
    assert mod.DECISION_END == "2024-09-30" and mod.HALF_SPLIT == "2017-05-31"


# ---- 유지·교체 ------------------------------------------------------------------------------------------

def test_kept_when_rank_within_k_and_active():
    held = ["E", "F", "L"]                       # 순위 5, 6, 12
    hs = {t: POOL[t] for t in held}
    picks, kept = mod.select_with_buffer(held, POOL, hs, 6)
    assert kept == ["E", "F"] and picks == ["E", "F", "A"] and len(picks) == 3


def test_replaced_when_rank_above_k():
    held = ["G", "H", "I"]                       # 순위 7, 8, 9
    picks, kept = mod.select_with_buffer(held, POOL, {t: POOL[t] for t in held}, 6)
    assert kept == [] and picks == ["A", "B", "C"]
    picks10, kept10 = mod.select_with_buffer(held, POOL, {t: POOL[t] for t in held}, 10)
    assert kept10 == ["G", "H", "I"] and picks10 == ["G", "H", "I"]


def test_replaced_when_not_trend_active():
    held = ["A", "B", "C"]
    picks, kept = mod.select_with_buffer(held, {k: v for k, v in POOL.items() if k != "B"}, {"A": 1.0, "B": None, "C": POOL["C"]}, 6)
    assert kept == ["A", "C"] and picks == ["A", "C", "D"]


def test_held_name_outside_pool_ranked_against_pool():
    pool = {k: v for k, v in POOL.items() if k != "Z"}
    # Z 는 풀 밖, 자기 가격 점수 0.76 → A(1.0)..E(0.80) 다음 = 순위 6
    assert mod.held_rank("Z", 0.76, pool) == 6
    picks, kept = mod.select_with_buffer(["Z", "K", "L"], pool, {"Z": 0.76, "K": POOL["K"], "L": POOL["L"]}, 6)
    assert kept == ["Z"] and picks == ["Z", "A", "B"]
    picks, kept = mod.select_with_buffer(["Z"], pool, {"Z": 0.76}, 5)
    assert kept == [] and picks == ["A", "B", "C"]


def test_always_three_and_b0_is_top3():
    for held in (["A", "B", "C"], ["J", "K", "L"], [], ["A"]):
        for K in (None, 3, 6, 10):
            picks, _ = mod.select_with_buffer(held, POOL, {t: POOL[t] for t in held}, K)
            assert len(picks) == 3 and len(set(picks)) == 3
    assert mod.select_with_buffer(["J", "K", "L"], POOL, {}, None)[0] == ["A", "B", "C"]
    # K=3 은 B0 와 같다
    assert set(mod.select_with_buffer(["C", "J", "K"], POOL, {t: POOL[t] for t in "CJK"}, 3)[0]) == {"A", "B", "C"}


def test_fewer_candidates_than_three():
    picks, kept = mod.select_with_buffer([], {"A": 1.0, "B": 0.5}, {}, 6)
    assert picks == ["A", "B"] and kept == []


def test_build_schedules_h12_january_only_and_buffer():
    dates = [pd.Timestamp(f"{y}-{m:02d}-02") for y in (2010, 2011, 2012) for m in (1, 7)]
    rng = np.random.default_rng(1)
    pools = {d: {t: float(rng.normal()) for t in "ABCDEFGHIJKL"} for d in dates}
    sch = mod.build_schedules(dates, pools, lambda d, t: None)
    assert [r["date"].month for r in sch["K6_H12"]] == [1, 1, 1]
    assert [r["date"].month for r in sch["K10_H12"]] == [1, 1, 1]
    assert len(sch["B0"]) == len(sch["K6_H6"]) == 6
    for r in sch["B0"]:
        assert r["picks"] == mod.ranked(pools[r["date"]])[:3]
    for name in mod.JUDGED:
        for r in sch[name]:
            assert len(r["picks"]) == 3 and set(r["kept"]) <= set(r["picks"])


def test_schedule_log_forces_reset_each_reselection():
    rows = [{"date": pd.Timestamp("2010-01-04"), "picks": ["A", "B", "C"], "kept": []},
            {"date": pd.Timestamp("2010-07-01"), "picks": ["A", "B", "C"], "kept": ["A", "B", "C"]}]
    lg = mod.schedule_log(rows)
    idx = pd.bdate_range("2010-01-04", "2010-12-31")
    core = pd.DataFrame({"X": 1.0}, index=idx)
    w = mod.tx.champion_weights(core, lg, 0.15)
    chg = w.diff().abs().sum(axis=1) > 1e-9
    assert bool(chg.loc[pd.Timestamp("2010-07-01")])
    assert abs(w.loc[pd.Timestamp("2010-07-01"), ["A", "B", "C"]].sum() - 0.15) < 1e-7


def test_schedule_stats():
    rows = [{"date": pd.Timestamp("2010-01-04"), "picks": ["A", "B", "C"]},
            {"date": pd.Timestamp("2010-07-01"), "picks": ["A", "B", "D"]},
            {"date": pd.Timestamp("2011-01-03"), "picks": ["E", "F", "G"]}]
    st = mod.schedule_stats(rows, pd.Timestamp("2011-01-03"))
    assert st["kept_per_reselection"] == [0, 2, 0] and st["mean_kept_per_reselection"] == 1.0
    assert st["n_reselections"] == 3


# ---- B0 = S-SEED-000, 미래 자료 안 씀 -------------------------------------------------------------------

def _synthetic_data():
    from core import satellite_lab as sl

    pp, poolp = sl.synthetic_providers(n_tickers=30, start="2008-01-01", end="2013-12-31", seed=3)
    pool = mod.SV._pool_wrapper(poolp, date.fromisoformat(mod.START))
    return sl, sl.build_data({"champion40"}, start="2009-12-01", end="2013-12-31", pool_provider=pool, price_provider=pp)


def test_b0_equals_run_variant_schedule():
    sl, data = _synthetic_data()
    dates, pools, extra = mod.score_inputs(data)
    b0 = mod.build_schedules(dates, pools, extra, {"B0": (None, (1, 7))})["B0"]
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    ref = sl.run_variant(spec, dict(spec["signal"]["params_grid"][0]), sl.load_signal(code), data)["schedule"]
    assert [(str(r["date"].date()), r["picks"]) for r in b0] == [(d, p) for d, p in ref]


def test_no_lookahead():
    sl, data = _synthetic_data()
    dates, pools, extra = mod.score_inputs(data)
    base = mod.build_schedules(dates, pools, extra)
    cut = pd.Timestamp("2012-01-01")
    rng = np.random.default_rng(9)
    for t, df in data.ohlcv.items():
        df = df.copy()
        m = df.index >= cut
        df.loc[m, "Close"] = df.loc[m, "Close"] * np.exp(rng.normal(0, 0.2, m.sum()))
        data.ohlcv[t] = df
    data.closes.loc[data.closes.index >= cut] *= 1.5
    d2, p2, e2 = mod.score_inputs(data)
    other = mod.build_schedules(d2, p2, e2)
    for name in mod.VARIANTS:
        a = [(r["date"], r["picks"]) for r in base[name] if r["date"] < cut]
        b = [(r["date"], r["picks"]) for r in other[name] if r["date"] < cut]
        assert a == b and a


# ---- 판정 ----------------------------------------------------------------------------------------------

def test_pass_rule_edges():
    ok = dict(diff=0.001, h1=0.001, h2=0.001, mdd_v=-0.20, mdd_0=-0.19, ci_low=-0.004)
    assert mod.decide(**ok) == mod.PASS
    assert mod.decide(**{**ok, "diff": 0.0}) == mod.FAIL
    assert mod.decide(**{**ok, "h1": 0.0}) == mod.FAIL
    assert mod.decide(**{**ok, "h2": -0.001}) == mod.FAIL
    assert mod.decide(**{**ok, "mdd_v": -0.2101}) == mod.FAIL
    assert mod.decide(**{**ok, "mdd_v": -0.2099}) == mod.PASS
    assert mod.decide(**{**ok, "ci_low": -0.005}) == mod.FAIL
    assert mod.decide(**{**ok, "ci_low": float("nan")}) == mod.NOT_EVALUABLE
    assert mod.decide(**ok, noop="same") == mod.NOT_EVALUABLE
    pw = mod.rp.power_report(14.7, 4)
    assert mod.decide(**{**ok, "diff": -0.01}, observed_ir=0.1, power=pw) in ("FAIL", "FAIL_UNDERPOWERED")


def test_bootstrap_deterministic():
    rng = np.random.default_rng(0)
    a, b = rng.normal(0.0004, 0.01, 800), rng.normal(0.0003, 0.01, 800)
    x, y = mod.block_bootstrap_diff(a, b, 252.0), mod.block_bootstrap_diff(a, b, 252.0)
    assert len(x) == 1000 and np.array_equal(x, y)


def test_smoke_resume(tmp_path):
    out, ck = tmp_path / "o", tmp_path / "c"
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck), "--max-steps-per-run", "2"]) == 3
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck)]) == 0
    r = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert set(r["verdicts"]) == set(mod.JUDGED) and all(v.startswith("SMOKE_ONLY(") for v in r["verdicts"].values())
    assert all(r["smoke_coverage"].values())
    assert (out / "results.json").stat().st_size < 200_000
    assert "power" in r and "스모크" in (out / "REPORT.md").read_text(encoding="utf-8")
