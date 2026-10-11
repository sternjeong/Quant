import importlib.util
import json
import math
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "research" / "jobs" / "survivorship-bound-v1"


def _load():
    spec = importlib.util.spec_from_file_location("survivorship_bound_v1_test", JOB / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_job_json_valid():
    from core.research_jobs import Config, load_job_definitions

    cfg = Config(repo_root=ROOT, jobs_dir=ROOT / "research" / "jobs",
                 state_dir=ROOT / "data" / "research_jobs_test_state",
                 results_dir=ROOT / "data" / "research_results_test")
    valid, invalid = load_job_definitions(cfg)
    assert "survivorship-bound-v1" not in invalid, invalid.get("survivorship-bound-v1")
    job = valid["survivorship-bound-v1"]
    assert job.priority == 17
    data = json.loads((JOB / "job.json").read_text(encoding="utf-8"))
    assert data["max_memory_mb"] <= 3000
    assert data["outputs"] == ["results.json", "REPORT.md"]
    assert data["summary_from"] == "verdicts"


def test_membership_gap_hand_built_example():
    m = _load()
    dates = (date(2010, 1, 1), date(2015, 1, 1), date(2020, 1, 1))
    members = (frozenset({"A", "B", "C", "D"}), frozenset({"A", "B", "D", "E"}), frozenset({"A", "D", "E", "F"}))
    available = {"A", "D", "E", "F"}  # B, C 는 가격 없음
    stats = m.membership_gap_stats(dates, members, available, {}, date(2026, 10, 1), start_year=2010, end_year=2020)
    # 2010-01 명단 {A,B,C,D}: 결측 B,C -> f_all=0.5. 2015-01 {A,B,D,E}: 결측 B -> 0.25. 2020-01 {A,D,E,F}: 결측 없음 -> 0.
    rows_by_date = {r["date"]: r for r in stats["rebalance_rows"]}
    assert math.isclose(rows_by_date["2010-01-01"]["f_all"], 0.5)
    assert math.isclose(rows_by_date["2015-01-01"]["f_all"], 0.25)
    assert math.isclose(rows_by_date["2020-01-01"]["f_all"], 0.0)
    assert stats["n_missing_distinct"] == 2  # B, C
    # B는 2015-01 이후에도 명단에 없었던 적 없음(마지막 등장 2015-01-01 < 2026-10-01) -> 편출.
    assert "B" in stats["removed_before_end"] and "C" in stats["removed_before_end"]
    assert stats["n_removed_before_end"] == 2
    assert stats["f_top40"]["upper"] > stats["f_top40"]["central"]
    assert math.isclose(stats["f_top40"]["central"], stats["f_top40"]["upper"] / 2)
    assert stats["f_top40"]["method_ii_derivable"] is False


def test_pit_members_at_bisect():
    m = _load()
    dates = (date(2010, 1, 1), date(2015, 1, 1))
    members = (frozenset({"A"}), frozenset({"B"}))
    assert m.pit_members_at(dates, members, date(2012, 1, 1)) == frozenset({"A"})
    assert m.pit_members_at(dates, members, date(2016, 1, 1)) == frozenset({"B"})
    assert m.pit_members_at(dates, members, date(2000, 1, 1)) == frozenset()


def test_ghost_period_return_shortfall_d0_g1_reproduces_own_return():
    m = _load()
    pick_ret = 0.12
    ghost = m.ghost_period_return(pick_ret, period_years=0.5, d_pp=0.0)
    assert math.isclose(ghost, pick_ret)
    blended = m.blended_period_return(pick_ret, ghost, frac=1.0)
    assert math.isclose(blended, pick_ret)


def test_ghost_period_return_shortfall_applies_pro_rata():
    m = _load()
    # d=10%p/년, 반기(0.5년) -> 5%p 만큼 깎인다.
    ghost = m.ghost_period_return(0.10, period_years=0.5, d_pp=10.0)
    assert math.isclose(ghost, 0.10 - 0.05)


def test_ghost_period_return_distress_is_expectation_not_random():
    m = _load()
    g1 = m.ghost_period_return(0.0, period_years=0.5, q=0.05, market_ret=0.08)
    g2 = m.ghost_period_return(0.0, period_years=0.5, q=0.05, market_ret=0.08)
    assert g1 == g2  # 결정론(몬테카를로 아님)
    assert math.isclose(g1, 0.05 * -0.5 + 0.95 * 0.08)


def test_blended_period_return_caps_frac_at_1_and_0():
    m = _load()
    assert math.isclose(m.blended_period_return(0.10, -0.50, frac=2.0), -0.50)   # frac>1 -> 1
    assert math.isclose(m.blended_period_return(0.10, -0.50, frac=-1.0), 0.10)   # frac<0 -> 0


def test_scale_daily_log_returns_matches_target_total():
    m = _load()
    log_r = np.array([0.001, -0.0005, 0.0008, 0.0002])
    scaled = m.scale_daily_log_returns(log_r, target_period_ret=0.05)
    assert math.isclose(float(np.exp(scaled.sum())) - 1.0, 0.05, abs_tol=1e-9)
    # 모양(부호 패턴)은 유지된다
    assert np.array_equal(np.sign(scaled), np.sign(log_r))


def test_scale_daily_log_returns_degenerate_total_falls_back_to_uniform():
    m = _load()
    log_r = np.array([0.0, 0.0, 0.0])
    scaled = m.scale_daily_log_returns(log_r, target_period_ret=0.06)
    assert math.isclose(float(np.exp(scaled.sum())) - 1.0, 0.06, abs_tol=1e-9)
    assert math.isclose(scaled[0], scaled[1])


def test_interpolate_break_even_finds_zero_crossing():
    m = _load()
    d = [0.0, 5.0, 10.0, 20.0, 40.0]
    diff = [0.02, 0.01, -0.005, -0.02, -0.05]  # 0 과 5 사이는 양수, 5~10 사이에서 교차
    be = m.interpolate_break_even(d, diff)
    assert 5.0 < be < 10.0
    # 선형 보간 손계산: (5,0.01) -> (10,-0.005): be = 5 + (0-0.01)*(10-5)/(-0.005-0.01)
    expected = 5.0 + (0 - 0.01) * (10.0 - 5.0) / (-0.005 - 0.01)
    assert math.isclose(be, expected)


def test_interpolate_break_even_no_crossing_returns_none():
    m = _load()
    d = [0.0, 5.0, 10.0]
    diff = [0.02, 0.015, 0.01]  # 항상 양수 -> 격자 범위 밖
    assert m.interpolate_break_even(d, diff) is None


def test_judge_robust_requires_both_shortfall_and_distress_cells():
    m = _load()
    robust_key = ("upper", 2, 10.0)
    fragile_key = ("central", 1, 10.0)
    robust_distress_key = ("upper", 2, 0.05)
    ab_diff = {robust_key: 0.004, fragile_key: 0.004}
    ab_distress = {robust_distress_key: 0.004}
    sleeve_gain = {robust_key: 0.012, fragile_key: 0.012}
    sleeve_distress = {robust_distress_key: 0.012}
    out = m.judge(ab_diff, ab_distress, sleeve_gain, sleeve_distress, None, None)
    assert out["satellite_vs_spy15"] == m.ROBUST
    assert out["sleeve_35_vs_15"] == m.ROBUST


def test_judge_fragile_when_sign_flips_at_central_k1_d10():
    m = _load()
    robust_key = ("upper", 2, 10.0)
    fragile_key = ("central", 1, 10.0)
    robust_distress_key = ("upper", 2, 0.05)
    # 로버스트 칸은 문턱 미달(그래서 ROBUST 조건이 걸리지 않음), 취약 칸은 부호가 뒤집힘.
    ab_diff = {robust_key: 0.001, fragile_key: -0.001}
    ab_distress = {robust_distress_key: 0.001}
    out = m.judge(ab_diff, ab_distress, {fragile_key: -0.001, robust_key: 0.001}, {robust_distress_key: 0.001}, None, None)
    assert out["satellite_vs_spy15"] == m.FRAGILE
    assert out["sleeve_35_vs_15"] == m.FRAGILE


def test_judge_inconclusive_when_neither_condition_met():
    m = _load()
    robust_key = ("upper", 2, 10.0)
    fragile_key = ("central", 1, 10.0)
    robust_distress_key = ("upper", 2, 0.05)
    # 로버스트 칸은 문턱 미달, 취약 칸은 양수(부호 안 뒤집힘)
    ab_diff = {robust_key: 0.001, fragile_key: 0.001}
    ab_distress = {robust_distress_key: 0.001}
    out = m.judge(ab_diff, ab_distress, {fragile_key: 0.001, robust_key: 0.001}, {robust_distress_key: 0.001}, None, None)
    assert out["satellite_vs_spy15"] == m.INCONCLUSIVE


def test_judge_not_evaluable_overrides_on_noop():
    m = _load()
    robust_key = ("upper", 2, 10.0)
    fragile_key = ("central", 1, 10.0)
    robust_distress_key = ("upper", 2, 0.05)
    ab_diff = {robust_key: 0.004, fragile_key: 0.004}
    ab_distress = {robust_distress_key: 0.004}
    out = m.judge(ab_diff, ab_distress, {fragile_key: 0.004, robust_key: 0.004}, {robust_distress_key: 0.004},
                  "후보가 기준선과 매일 같음", None)
    assert out["satellite_vs_spy15"] == m.NOT_EVALUABLE
    assert out["sleeve_35_vs_15"] != m.NOT_EVALUABLE  # 다른 쪽 noop 은 독립


def test_smoke_resume_then_complete(tmp_path, monkeypatch):
    m = _load()
    monkeypatch.setenv("RESEARCH_JOB_DEADLINE_EPOCH", "0")
    args = ["--smoke", "--out", str(tmp_path / "out"), "--checkpoint", str(tmp_path / "ck")]
    assert m.main(args) == 3
    monkeypatch.delenv("RESEARCH_JOB_DEADLINE_EPOCH")
    assert m.main(args) == 0
    payload = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert payload["power"] is None and payload["power_reason"]
    assert set(payload["verdicts"]) == {"satellite_vs_spy15", "sleeve_35_vs_15"}
    assert all(v.startswith("SMOKE_ONLY(") for v in payload["verdicts"].values())
    assert (tmp_path / "out" / "REPORT.md").exists()


def test_smoke_deterministic_across_runs(tmp_path, monkeypatch):
    m = _load()
    monkeypatch.delenv("RESEARCH_JOB_DEADLINE_EPOCH", raising=False)
    a1 = ["--smoke", "--out", str(tmp_path / "out1"), "--checkpoint", str(tmp_path / "ck1")]
    a2 = ["--smoke", "--out", str(tmp_path / "out2"), "--checkpoint", str(tmp_path / "ck2")]
    assert m.main(a1) == 0
    assert m.main(a2) == 0
    p1 = json.loads((tmp_path / "out1" / "results.json").read_text(encoding="utf-8"))
    p2 = json.loads((tmp_path / "out2" / "results.json").read_text(encoding="utf-8"))
    assert p1["verdicts"] == p2["verdicts"]
    assert p1["f_top40"] == p2["f_top40"]
    assert p1["break_even_d_pp_ab"] == p2["break_even_d_pp_ab"]
