"""sat-stagger-v1 (새틀라이트 엇갈린 재선정) 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

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
    spec = importlib.util.spec_from_file_location("sat_stagger_v1", ROOT / "research/jobs/sat-stagger-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "sat-stagger-v1" in valid, invalid.get("sat-stagger-v1")
    job = json.loads((ROOT / "research/jobs/sat-stagger-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 10 and job["resumable"] is True and job["max_memory_mb"] <= 2500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert (ROOT / "research/jobs/sat-stagger-v1/SPEC.md").exists()


def test_pre_registered_constants():
    assert mod.SLEEVES == {"G1": ((1, 7),), "G2": ((1, 7), (4, 10)), "G3": ((1, 7), (3, 9), (5, 11))}
    assert mod.JUDGED == ("G2", "G3") and mod.N_TRIALS == 2 and mod.POWER_YEARS == 14.2
    assert mod.DIFF_FLOOR == -0.003 and mod.SD_REDUCTION == 0.20 and mod.MDD_TOL == 0.01 and mod.ROLL_DAYS == 126
    assert mod.SAT_WEIGHT == 0.15 and mod.JUDGE_START == "2010-07-01"
    assert mod.DECISION_END == "2024-09-30" and mod.HALF_SPLIT == "2017-05-31"
    assert mod.PHASES == {f"P{m}": ((m, m + 6),) for m in range(1, 7)}


# ---- 일정 -------------------------------------------------------------------------------------------------

DATES = [pd.Timestamp(f"{y}-{m:02d}-01") for y in (2010, 2011) for m in range(1, 13)]


def test_sub_sleeve_calendars():
    assert [d.month for d in mod.sleeve_dates(DATES, (4, 10))] == [4, 10, 4, 10]
    for n, sleeves in mod.SLEEVES.items():
        months = sorted(m for s in sleeves for m in s)
        assert len(set(months)) == len(months)          # 하위 슬리브 달이 겹치지 않음
        assert all(b - a == 6 for a, b in sleeves)      # 각 하위 슬리브는 6개월 보유


def _picks(seed=0):
    rng = np.random.default_rng(seed)
    names = list("ABCDEFGH")
    return {d: list(rng.choice(names, 3, replace=False)) for d in DATES}


def test_weights_sum_and_cash_before_first_month():
    picks = _picks()
    for n, sleeves in mod.SLEEVES.items():
        lg = mod.combined_log(picks, sleeves, DATES)
        assert lg[0]["date"] == "2010-01-01"
        first = sum(lg[0]["weights"].values())
        assert first == pytest.approx(1.0 / len(sleeves))          # 1월에는 1·7월 슬리브만 투자, 나머지 현금
        later = [r for r in lg if pd.Timestamp(r["date"]) >= pd.Timestamp("2010-07-01")]
        assert later and all(sum(r["weights"].values()) == pytest.approx(1.0) for r in later)
        idx = pd.bdate_range("2010-01-01", "2011-12-30")
        w = mod.tx.champion_weights(pd.DataFrame({"X": 1.0}, index=idx), lg, mod.SAT_WEIGHT)
        sat = w.drop(columns="X").sum(axis=1)
        assert sat.loc["2010-07-01":].round(12).eq(0.15).all()
        months = {pd.Timestamp(r["date"]).month for r in lg}
        assert months == {m for s in sleeves for m in s}


def test_each_sub_sleeve_keeps_its_own_picks_and_overlap_adds():
    picks = {d: ["A", "B", "C"] for d in DATES}
    picks[pd.Timestamp("2010-04-01")] = ["A", "D", "E"]
    lg = {r["date"]: r["weights"] for r in mod.combined_log(picks, mod.SLEEVES["G2"], DATES)}
    w = lg["2010-04-01"]
    assert w["A"] == pytest.approx(0.5 / 3 * 2) and w["B"] == pytest.approx(0.5 / 3) and w["D"] == pytest.approx(0.5 / 3)
    # 7월: 1·7월 슬리브만 바꿈, 4·10월 슬리브(A,D,E)는 그대로
    picks[pd.Timestamp("2010-07-01")] = ["F", "G", "H"]
    lg = {r["date"]: r["weights"] for r in mod.combined_log(picks, mod.SLEEVES["G2"], DATES)}
    assert set(lg["2010-07-01"]) == {"A", "D", "E", "F", "G", "H"}
    assert "2010-05-03" not in lg and "2010-02-01" not in lg   # 재선정 없는 달은 기록 없음


def test_empty_pick_is_cash():
    picks = {d: ["A"] for d in DATES}
    picks[pd.Timestamp("2010-03-01")] = []
    lg = {r["date"]: r["weights"] for r in mod.combined_log(picks, mod.SLEEVES["G3"], DATES)}
    assert sum(lg["2010-03-01"].values()) == pytest.approx(1 / 3)


# ---- S-SEED-000 재현 ------------------------------------------------------------------------------------

def _synthetic_data():
    from core import satellite_lab as sl

    pp, poolp = sl.synthetic_providers(n_tickers=30, start="2008-01-01", end="2012-12-31", seed=3)
    pool = mod.SV._pool_wrapper(poolp, date.fromisoformat(mod.START))
    return sl, sl.build_data({"champion40"}, start="2009-12-01", end="2012-12-31", pool_provider=pool, price_provider=pp)


def test_picks_equal_s_seed_000_and_g1_equals_satellite_value_v1():
    sl, data = _synthetic_data()
    dates = mod.sim_dates(data.trading_days)
    assert dates[0].month == 1 and dates[0].year == 2010
    picks = mod.picks_by_date(data, dates)
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    params, signal = dict(spec["signal"]["params_grid"][0]), sl.load_signal(code)
    # 각 하위 슬리브 날짜의 선택 = S-SEED-000 을 그 날짜에 돌린 것(월간 달력으로 run_variant)
    monthly = json.loads(json.dumps(spec))
    monthly["portfolio"]["hold_months"] = 1
    ref = {d: p for d, p in sl.run_variant(monthly, params, signal, data)["schedule"]}
    for d, p in picks.items():
        assert ref[str(d.date())] == p
    # G1 = satellite-value-v1 의 챔피언 새틀라이트 기록(A)
    g1 = mod.combined_log(picks, mod.SLEEVES["G1"], dates)
    assert g1 == mod.SV._schedules(data)["A"]


# ---- 롤링 지표·판정 ---------------------------------------------------------------------------------------

def test_rolling_dispersion_hand_built():
    idx = pd.bdate_range("2010-01-01", periods=10)
    v = pd.Series([1, 1.1, 1.21, 1.0, 1.0, 1.5, 1.5, 1.5, 1.2, 1.2], index=idx, dtype=float)
    st = mod.rolling_stats(v, idx[0], idx[-1], window=3)
    r = np.array([1.0 / 1 - 1, 1.0 / 1.1 - 1, 1.5 / 1.21 - 1, 1.5 / 1.0 - 1, 1.5 / 1.0 - 1, 1.2 / 1.5 - 1, 1.2 / 1.5 - 1])
    assert st["n"] == 7 and st["sd"] == pytest.approx(np.std(r, ddof=1)) and st["worst"] == pytest.approx(r.min())
    st2 = mod.rolling_stats(v, idx[2], idx[-1], window=3)    # 창은 판정 구간 안에서만
    assert st2["n"] == 5


def test_gross_values_drift_and_cash():
    idx = pd.bdate_range("2010-01-01", periods=3)
    adj = pd.DataFrame({"A": [1.0, 2.0, 2.0]}, index=idx)
    w = pd.DataFrame({"A": [0.5, 0.5, 0.5]}, index=idx)
    assert mod.gross_values(w, adj).tolist() == pytest.approx([1.0, 1.5, 1.5])


def test_pass_rule_edges():
    ok = dict(diff=-0.003, h1=-0.003, h2=0.0, sd_v=0.08, sd_0=0.10, worst_v=-0.29, worst_0=-0.30, mdd_v=-0.21, mdd_0=-0.20)
    assert mod.decide(**ok) == mod.PASS
    assert mod.decide(**{**ok, "diff": -0.0031}) == mod.FAIL
    assert mod.decide(**{**ok, "h1": -0.0031}) == mod.FAIL
    assert mod.decide(**{**ok, "h2": -0.0031}) == mod.FAIL
    assert mod.decide(**{**ok, "sd_v": 0.0801}) == mod.FAIL
    assert mod.decide(**{**ok, "worst_v": -0.30}) == mod.FAIL
    assert mod.decide(**{**ok, "mdd_v": -0.2101}) == mod.FAIL
    assert mod.decide(**{**ok, "sd_0": float("nan")}) == mod.NOT_EVALUABLE
    assert mod.decide(**ok, noop="same") == mod.NOT_EVALUABLE
    pw = mod.rp.power_report(14.2, 2)
    assert mod.decide(**{**ok, "diff": -0.01}, observed_ir=0.1, power=pw) in ("FAIL", "FAIL_UNDERPOWERED")


def test_smoke_resume(tmp_path):
    out, ck = tmp_path / "o", tmp_path / "c"
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck), "--max-steps-per-run", "3"]) == 3
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck)]) == 0
    r = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert set(r["verdicts"]) == set(mod.JUDGED) and all(v.startswith("SMOKE_ONLY(") for v in r["verdicts"].values())
    assert all(r["smoke_coverage"].values()) and len(r["phase_diagnostic"]["per_phase"]) == 6
    assert (out / "results.json").stat().st_size < 200_000
    assert "power" in r and "스모크" in (out / "REPORT.md").read_text(encoding="utf-8")
