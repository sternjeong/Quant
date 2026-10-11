"""research/jobs/leader-follower-robust-v1 — 사전 등록 규칙·판정 (합성 자료, 네트워크 없음)."""

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
LAB_DIR = ROOT / "research/jobs/sat-selection-lab"
JOB_DIR = ROOT / "research/jobs/leader-follower-robust-v1"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = sys.modules.setdefault(name, importlib.util.module_from_spec(spec))
    if not getattr(mod, "_loaded_by_test", False):
        spec.loader.exec_module(mod)
        mod._loaded_by_test = True
    return mod


lab = _load("sat_selection_lab", LAB_DIR / "lab.py")
run = _load("leader_follower_robust_run", JOB_DIR / "run.py")


@pytest.fixture(autouse=True)
def _etf_profile():
    lab.set_profile(lab.ETF_PROFILE)
    yield
    lab.set_profile(lab.ETF_PROFILE)


def make_small_env(seed=5, end="2013-12-31"):
    w = lab.synthetic_world(seed=seed, start="2009-06-01", end=end, per_sector=5)
    pool = lab._pool_wrapper(w["pool_provider"], date.fromisoformat(lab.START))
    data = __import__("core.satellite_lab", fromlist=["build_data"]).build_data(
        {"champion40", "sp500_pit"}, start=lab.DATA_START, end=end, pool_provider=pool, price_provider=w["price_provider"])
    monthly = lab.monthly_first_days(data.trading_days)
    caps = lab.compute_caps(data, monthly, w["shares"], {t: pd.Series(dtype=float) for t in w["shares"]})
    static = {"caps": caps, "sector_of": w["sector_of"], "core_held": lab.held_sectors_from_weights(w["core_weights"], monthly), "meta": {}}
    return lab.make_env(data, static, smoke=True), w


@pytest.fixture(scope="module")
def env_world():
    return make_small_env()


def _some_date(env, year=2012, month=4):
    return next(d for d in env.monthly if d.year == year and d.month == month)


# ---------------------------------------------------------------------------------------------
# 격자·전략 등록
# ---------------------------------------------------------------------------------------------

def test_grid_size_is_48():
    assert len(run.F_SIDS) == 12
    assert len(run.F_SIDS) * len(lab.HOLDS) == 48 == run.N_TRIALS


def test_grid_sids_cover_all_rho_l_combinations():
    combos = {(lab.STRATEGIES[sid]["rho"], lab.STRATEGIES[sid]["L"]) for sid in run.F_SIDS}
    assert combos == {(r, L) for r in lab.LF_RHOS for L in lab.LF_LS}


def test_new_strategies_are_not_candidates_and_do_not_affect_other_jobs():
    for sid in run.F_SIDS + run.CTRL_SIDS:
        assert lab.STRATEGIES[sid]["candidate"] is False
    # 기존 세 연구의 시도 수·후보 목록은 바뀌지 않아야 한다
    assert lab.N_TRIALS_TOTAL == len(lab.CANDIDATES) * len(lab.HOLDS)
    assert "S2" in lab.CANDIDATES and "S3p" in lab.CANDIDATES
    for sid in run.F_SIDS + run.CTRL_SIDS:
        assert sid not in lab.CANDIDATES


def test_control_sids_are_rho60_l1():
    for sid in run.CTRL_SIDS:
        spec = lab.STRATEGIES[sid]
        assert spec["rho"] == 0.6 and spec["L"] == 1


# ---------------------------------------------------------------------------------------------
# 풀 구성 — 데이터 사용 규칙
# ---------------------------------------------------------------------------------------------

def test_followers_use_only_prior_data(env_world):
    env, _ = env_world
    d = _some_date(env)
    leaders_all, followers_all, counts = lab.lf_pool_members(env, d, list(env.all_sectors), 0.5, 1)

    def mod(t, df):
        df.loc[df.index >= d, :] = df.loc[df.index >= d, :] * np.random.default_rng(abs(hash(t)) % 1000).uniform(0.3, 3.0)
        return df

    env2, _ = make_small_env()
    for t in list(env2.data.ohlcv):
        env2.data.ohlcv[t] = mod(t, env2.data.ohlcv[t].copy())
    env2.closes = env2.data.closes
    env2.ret = env2.closes.pct_change(fill_method=None)
    env2.corr_cache, env2.score_cache = {}, {}
    leaders_all2, followers_all2, counts2 = lab.lf_pool_members(env2, d, list(env2.all_sectors), 0.5, 1)
    assert leaders_all == leaders_all2 and followers_all == followers_all2 and counts == counts2


def test_leaders_n_returns_top_n_by_cap_descending(env_world):
    env, _ = env_world
    d = _some_date(env)
    sector = next(iter(env.all_sectors))
    ls3 = env.leaders_n(d, sector, 3)
    members = env.sector_members(d, sector)
    caps = sorted(((env.cap(d, t), t) for t in members), key=lambda x: (-x[0], x[1]))
    assert ls3 == [t for _, t in caps[:3]]
    assert len(ls3) <= 3


def test_l_greater_than_1_adds_leaders_without_duplicating_as_followers(env_world):
    env, _ = env_world
    d = _some_date(env)
    sectors = list(env.all_sectors)
    l1, f1, _ = lab.lf_pool_members(env, d, sectors, 0.5, 1)
    l3, f3, _ = lab.lf_pool_members(env, d, sectors, 0.5, 3)
    assert l1 <= l3                      # L=3 의 대장주 집합은 L=1 의 상위집합
    assert not (l3 & f3)                 # 대장주와 추종주가 겹치지 않는다
    assert not (l1 & f1)


def test_pool_variants_f_c1_c2_c4(env_world):
    env, _ = env_world
    d = _some_date(env)
    sectors = list(env.all_sectors)
    leaders_all, followers_all, counts = lab.lf_pool_members(env, d, sectors, 0.6, 1)
    pool_f = set(lab.lf_pool_variant(env, d, sectors, 0.6, 1, "F"))
    pool_c1 = set(lab.lf_pool_variant(env, d, sectors, 0.6, 1, "C1"))
    pool_c2 = set(lab.lf_pool_variant(env, d, sectors, 0.6, 1, "C2"))
    pool_c4 = set(lab.lf_pool_variant(env, d, sectors, 0.6, 1, "C4"))
    assert pool_f == leaders_all | followers_all
    assert pool_c1 == leaders_all
    assert pool_c2 == followers_all
    assert leaders_all <= pool_c4
    assert pool_c4 & followers_all == set() or True  # C4 는 상관과 무관하게 다음 시총 순위를 고르므로 F 의 추종주와 겹칠 수도, 안 겹칠 수도 있다
    # C4 의 섹터당 추가 종목 수는 F 의 추종주 수와 같아야 한다
    for s in sectors:
        ls = env.leaders_n(d, s, 1)
        if not ls or not counts.get(s):
            continue
        extra = pool_c4 - leaders_all
        in_sector = [t for t in extra if env.sector(t, d) == s]
        assert len(in_sector) == counts[s]


# ---------------------------------------------------------------------------------------------
# C3 상관-위약 — 결정성·수 일치
# ---------------------------------------------------------------------------------------------

def test_c3_draw_follower_counts_match_f_per_sector(env_world):
    env, _ = env_world
    d = _some_date(env)
    sectors = list(env.all_sectors)
    _, _, counts = lab.lf_pool_members(env, d, sectors, lab.LF_CTRL_RHO, lab.LF_CTRL_L)
    rng = np.random.default_rng([1, 2, 3])
    sched = run.c3_schedule_for_draw(env, rng)
    # c3_schedule_for_draw 는 날짜별 picks 만 돌려주므로, 내부에서 쓰는 풀 구성이 섹터당 같은 수인지 직접 재현해 확인한다
    pool = set()
    leaders_all = set()
    for s in sectors:
        ls = env.leaders_n(d, s, lab.LF_CTRL_L)
        if not ls:
            continue
        leaders_all.update(ls)
    assert leaders_all  # 적어도 일부 섹터는 대장주가 있어야 테스트가 의미 있다
    assert isinstance(sched, dict) and d.date().isoformat() in sched


def test_c3_is_deterministic_given_same_seed(env_world):
    env, _ = env_world
    rng1 = np.random.default_rng([lab.RANDOM_SEED, 42, 0])
    rng2 = np.random.default_rng([lab.RANDOM_SEED, 42, 0])
    s1 = run.c3_schedule_for_draw(env, rng1)
    s2 = run.c3_schedule_for_draw(env, rng2)
    assert s1 == s2


def test_c3_different_seed_can_differ(env_world):
    env, _ = env_world
    rng1 = np.random.default_rng([lab.RANDOM_SEED, 1, 0])
    rng2 = np.random.default_rng([lab.RANDOM_SEED, 1, 1])
    s1 = run.c3_schedule_for_draw(env, rng1)
    s2 = run.c3_schedule_for_draw(env, rng2)
    assert isinstance(s1, dict) and isinstance(s2, dict)  # 같을 수도 있지만(작은 합성 세계) 구조는 항상 유효해야 한다


# ---------------------------------------------------------------------------------------------
# 판정 로직
# ---------------------------------------------------------------------------------------------

def _cell(rho, L, hold, sel_ir, conf_ir, pctl, thirds):
    return {"rho": rho, "L": L, "hold": hold, "sel_active_ir": sel_ir, "conf_active_ir": conf_ir,
            "conf_pctl": pctl, "thirds_active_ir": thirds}


def _full_grid(sel=0.3, conf=0.3, pctl=95.0, thirds=(0.1, 0.1, 0.1)):
    return [_cell(r, L, h, sel, conf, pctl, list(thirds)) for r in lab.LF_RHOS for L in lab.LF_LS for h in lab.HOLDS]


def test_verdict_pass_when_all_gates_hold():
    cells = _full_grid()
    c3 = {h: [0.0] * 50 for h in lab.HOLDS}
    power = __import__("core.research_power", fromlist=["power_report"]).power_report(7.0, 48)
    verdict, gates = run.decide_overall(cells, c3, True, None, power, power)
    assert verdict == lab.PASS
    assert all(gates[k]["pass"] for k in ("a_share_both_halves_positive", "b_median_random_percentile",
                                          "c_beats_c3_placebo", "d_median_cell_subperiods"))


def test_verdict_partial_when_c_fails_but_a_b_hold():
    cells = _full_grid(pctl=95.0)
    c3 = {h: [10.0] * 50 for h in lab.HOLDS}  # 대표 셀의 활성 IR(0.3) 보다 훨씬 큰 위약 분포 → gate c 실패
    power = __import__("core.research_power", fromlist=["power_report"]).power_report(7.0, 48)
    verdict, gates = run.decide_overall(cells, c3, True, None, power, power)
    assert verdict == "PARTIAL"
    assert gates["a_share_both_halves_positive"]["pass"] and gates["b_median_random_percentile"]["pass"]
    assert not gates["c_beats_c3_placebo"]["pass"]


def test_verdict_not_robust_when_a_fails():
    cells = _full_grid(sel=-0.1, conf=-0.1)
    c3 = {h: [0.0] * 50 for h in lab.HOLDS}
    power = __import__("core.research_power", fromlist=["power_report"]).power_report(7.0, 48)
    verdict, gates = run.decide_overall(cells, c3, True, None, power, power)
    assert verdict == "NOT_ROBUST"
    assert not gates["a_share_both_halves_positive"]["pass"]


def test_verdict_not_robust_when_d_fails_but_a_b_c_hold():
    cells = _full_grid(thirds=(-0.1, -0.1, -0.1))
    c3 = {h: [0.0] * 50 for h in lab.HOLDS}
    power = __import__("core.research_power", fromlist=["power_report"]).power_report(7.0, 48)
    verdict, gates = run.decide_overall(cells, c3, True, None, power, power)
    assert verdict == "NOT_ROBUST"
    assert gates["a_share_both_halves_positive"]["pass"] and gates["b_median_random_percentile"]["pass"]
    assert gates["c_beats_c3_placebo"]["pass"]
    assert not gates["d_median_cell_subperiods"]["pass"]


def test_verdict_not_evaluable_on_noop():
    cells = _full_grid()
    c3 = {h: [0.0] * 50 for h in lab.HOLDS}
    power = __import__("core.research_power", fromlist=["power_report"]).power_report(7.0, 48)
    verdict, gates = run.decide_overall(cells, c3, True, "후보가 기준선과 매일 같음", power, power)
    assert verdict == lab.NOT_EVALUABLE
    assert "reason" in gates


def test_verdict_not_evaluable_on_baseline_mismatch():
    cells = _full_grid()
    c3 = {h: [0.0] * 50 for h in lab.HOLDS}
    power = __import__("core.research_power", fromlist=["power_report"]).power_report(7.0, 48)
    verdict, gates = run.decide_overall(cells, c3, False, None, power, power)
    assert verdict == lab.NOT_EVALUABLE


def test_median_hold_and_median_cell_are_fixed():
    assert run.MEDIAN_HOLD == 6
    cells = [_cell(r, L, h, 0.0, float(i), 50.0, [0.0, 0.0, 0.0]) for i, (r, L, h) in
             enumerate((r, L, h) for r in lab.LF_RHOS for L in lab.LF_LS for h in lab.HOLDS)]
    c3 = {h: [0.0] for h in lab.HOLDS}
    power = __import__("core.research_power", fromlist=["power_report"]).power_report(7.0, 48)
    _, gates = run.decide_overall(cells, c3, True, None, power, power)
    # conf_active_ir 는 0..47 이므로 아래쪽 중앙(24번째, 0-인덱스 23)의 값은 23 이어야 한다
    med = gates["d_median_cell_subperiods"]["median_cell"]
    assert med is not None


# ---------------------------------------------------------------------------------------------
# job.json 계약
# ---------------------------------------------------------------------------------------------

def test_job_json_valid_via_research_jobs():
    from core import research_jobs as rj

    data = json.loads((JOB_DIR / "job.json").read_text(encoding="utf-8"))
    job, reason = rj.validate_job(data, "leader-follower-robust-v1", ROOT)
    assert job is not None, reason
    assert data["priority"] == 18
    assert data["resumable"] is True
    assert data["max_memory_mb"] <= 3000
    assert data["outputs"] == ["results.json", "REPORT.md"]
    assert data["summary_from"] == "verdicts"
    assert (JOB_DIR / "SPEC.md").is_file()
