"""research/jobs/sat-selection-lab + sat-{pool,leader,follower}[-crsp]-v1 — 규칙·판정·CRSP 자료 계층 (합성 자료, 네트워크 없음)."""

import importlib.util
import json
import math
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
LAB_DIR = ROOT / "research/jobs/sat-selection-lab"
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
crsp = _load("sat_selection_crsp", LAB_DIR / "crsp.py")

from core import research_power as rp  # noqa: E402
from core import satellite_lab as sl  # noqa: E402


@pytest.fixture(autouse=True)
def _etf_profile():
    lab.set_profile(lab.ETF_PROFILE)
    yield
    lab.set_profile(lab.ETF_PROFILE)


# ---------------------------------------------------------------------------------------------
# 합성 환경
# ---------------------------------------------------------------------------------------------

def make_small_env(modify=None, end="2013-12-31"):
    w = lab.synthetic_world(seed=3, start="2009-06-01", end=end, per_sector=5)
    provider = w["price_provider"]
    if modify is not None:
        def provider(t, s, e, _orig=w["price_provider"]):  # noqa: E306
            return modify(t, _orig(t, s, e).copy())
    pool = lab._pool_wrapper(w["pool_provider"], date.fromisoformat(lab.START))
    data = sl.build_data({"champion40", "sp500_pit"}, start=lab.DATA_START, end=end, pool_provider=pool, price_provider=provider)
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
# 선정 규칙
# ---------------------------------------------------------------------------------------------

def test_no_lookahead_changing_data_from_rebalance_date_does_not_change_plans(env_world):
    env, _ = env_world
    d = _some_date(env)

    def mod(t, df):
        df.loc[df.index >= d, :] = df.loc[df.index >= d, :] * np.random.default_rng(abs(hash(t)) % 1000).uniform(0.3, 3.0)
        return df

    env2, _ = make_small_env(modify=mod)
    for sid in ("B0", "S1_100", "S2", "S2p", "S3", "S3p", "S4", "S4c"):
        a, b = lab.plan_at(env, sid, d), lab.plan_at(env2, sid, d)
        for k in ("pool", "picks", "cands", "leaders", "held"):
            assert a[k] == b[k], (sid, k)


def test_leader_is_largest_pit_cap_in_sector(env_world):
    env, _ = env_world
    for d in [x for x in env.monthly if x.month == 7][:4]:
        leaders = env.leaders(d, set(env.all_sectors))
        assert leaders
        for sec, t in leaders.items():
            peers = [x for x in env.members(d) if env.sector(x, d) == sec]
            assert env.cap(d, t) == max(env.cap(d, x) for x in peers)
            assert all(env.cap(d, x) <= env.cap(d, t) for x in peers)


def test_followers_use_only_prior_data_and_threshold(env_world):
    env, _ = env_world
    d = _some_date(env, 2012, 7)
    sec, leader = next(iter(env.leaders(d, set(env.all_sectors)).items()))
    peers = [x for x in env.sector_members(d, sec) if x != leader and env.cap(d, x) < env.cap(d, leader)]
    corr = env.corr_table(d, leader, peers)
    i = env.pos(d)
    for t, c in corr.items():
        manual = env.ret[[leader, t]].iloc[i - lab.CORR_WINDOW:i].dropna().corr().iloc[0, 1]
        assert c == pytest.approx(manual, abs=1e-6)
    f6 = env.followers(d, sec, leader, 0.6)
    f7 = env.followers(d, sec, leader, 0.7)
    assert set(f7) <= set(f6) and all(v >= 0.6 for v in f6.values()) and all(v >= 0.7 for v in f7.values())
    assert set(f6) == {t for t, c in corr.items() if c >= 0.6}
    assert all(env.cap(d, t) < env.cap(d, leader) for t in f6)
    # 상관 창은 d 이전 행만: 마지막 행의 날짜는 d 보다 앞선다
    assert env.days[i - 1] < d


def test_s4_gap_sign_and_ranking_hand_example():
    assert lab.catchup_gap(0.20, 0.05) == pytest.approx(0.15)
    assert lab.catchup_gap(0.20, 0.25) == pytest.approx(-0.05)
    gaps = {"A": 0.15, "B": -0.05, "C": 0.02, "D": 0.30, "E": 0.15}
    assert lab.rank_by_gap(gaps) == ["D", "A", "E"]          # 동점은 티커순
    assert lab.rank_by_gap({"B": -0.05, "C": -0.2}) == ["B", "C"]   # 음수 격차도 담는다(양수 조건 없음)
    assert lab.is_safe(0.03, 0.02) and lab.is_safe(0.03, 0.02 * 1.5 / 1.5 * 1.5) and not lab.is_safe(0.031, 0.02)
    assert not lab.is_safe(None, 0.02) and not lab.is_safe(0.01, float("nan"))


def test_s4_plan_picks_follow_gap_ranking(env_world):
    env, _ = env_world
    checked = 0
    for d in env.monthly:
        rec = lab.plan_at(env, "S4", d)
        if rec["fallback"] or len(rec["cands"]) < 2 or not rec["picks"]:
            continue
        gaps = {f: lab.catchup_gap(env.ret_window(d, L, 63), env.ret_window(d, f, 63)) for f, L in rec["cands"].items()
                if env.ret_window(d, L, 63) is not None and env.ret_window(d, f, 63) is not None}
        assert rec["picks"] == lab.rank_by_gap(gaps)
        for f, L in rec["cands"].items():     # 후보 조건: 상관 ≥ 0.7, 추세 활성, 안전
            assert f in env.inc_scores(d, [f])
            assert lab.is_safe(env.vol_window(d, f, 63), env.vol_window(d, L, 63))
        checked += 1
    assert checked >= 1


def test_fallback_when_core_holds_no_sector(env_world):
    env, _ = env_world
    empties = [d for d in env.monthly if not env.core_held.get(d.date().isoformat())]
    assert empties, "합성 코어는 섹터를 안 드는 달이 있어야 한다"
    d = empties[3]
    base = env.b0(d)[1]
    for sid in ("S2", "S3", "S4", "S4c"):
        rec = lab.plan_at(env, sid, d)
        assert rec["fallback"] is True and rec["picks"] == base, sid
    for sid in ("S2p", "S3p", "S1_100"):
        assert lab.plan_at(env, sid, d)["fallback"] is False
    held = [d for d in env.monthly if env.core_held.get(d.date().isoformat())][5]
    assert lab.plan_at(env, "S2", held)["fallback"] is False
    assert set(lab.plan_at(env, "S2", held)["leaders"]) <= set(env.core_held[held.date().isoformat()])


def test_baseline_plan_matches_lab_engine_incumbent(env_world):
    env, _ = env_world
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    out = sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), env.data)
    engine = {d: p for d, p in out["schedule"]}
    plan = lab.build_plan(env, "B0")
    for d in [x for x in env.monthly if x.month in (1, 7)]:
        if d.date().isoformat() in engine:
            assert plan[d.date().isoformat()]["picks"] == engine[d.date().isoformat()], d


def test_hold_dates_and_grid():
    days = pd.bdate_range("2010-01-01", "2012-12-31")
    m = lab.monthly_first_days(days, "2010-01-01")
    assert [d.month for d in lab.hold_dates(m, 12)] == [1, 1, 1]
    assert {d.month for d in lab.hold_dates(m, 6)} == {1, 7} and {d.month for d in lab.hold_dates(m, 3)} == {1, 4, 7, 10}
    assert len(lab.hold_dates(m, 1)) == 36 and lab.HOLDS == (1, 3, 6, 12)


# ---------------------------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------------------------

POWER = rp.power_report(7.35, 32)
GOOD = dict(noop_reason=None, baseline_ok=True, chosen=6, conf_active_ir=0.9, conf_sharpe=1.2, rand_threshold=1.0,
            conf_irs={3: 0.4, 6: 0.9, 12: 0.2}, cand_conf_mdd=-0.25, base_conf_mdd=-0.22, power_conf=POWER)


def test_hold_is_chosen_only_from_selection_half():
    assert lab.choose_hold({1: 0.1, 3: 0.5, 6: 0.4, 12: float("nan")}) == 3
    assert lab.choose_hold({1: 0.5, 3: 0.5, 6: 0.1, 12: 0.0}) == 1                # 동률은 짧은 쪽
    assert lab.choose_hold({1: float("nan"), 3: float("nan")}) is None
    idx = pd.bdate_range("2010-02-01", "2024-12-31")
    rng = np.random.default_rng(1)
    a = pd.Series(rng.normal(0, 0.01, len(idx)), index=idx)
    base = pd.Series(rng.normal(0, 0.01, len(idx)), index=idx)
    b = a.copy()
    b[b.index > pd.Timestamp(lab.SELECTION_END)] += 0.05            # 선정 구간 뒤 자료만 크게 바꾼다
    sa, sb = lab._stats_block(a, base, "sel"), lab._stats_block(b, base, "sel")
    assert sa["active_ir"] == sb["active_ir"] and sa["sharpe"] == sb["sharpe"]
    assert lab._stats_block(a, base, "conf")["active_ir"] != lab._stats_block(b, base, "conf")["active_ir"]


def test_verdict_pass_and_each_gate_failure():
    v, g = lab.decide(**GOOD)
    assert v == lab.PASS and all(g[k] for k in ("a_active_positive", "b_beats_random_p95", "c_neighbors", "d_mdd_ok"))
    for patch, gate in (({"conf_active_ir": -0.1}, "a_active_positive"), ({"conf_sharpe": 0.99}, "b_beats_random_p95"),
                        ({"conf_irs": {3: -0.1, 6: 0.9, 12: 0.2}}, "c_neighbors"), ({"cand_conf_mdd": -0.2701}, "d_mdd_ok")):
        v, g = lab.decide(**{**GOOD, **patch})
        assert v in (lab.FAIL, lab.FAIL_UNDERPOWERED) and g[gate] is False, gate


def test_verdict_edges_equalities_and_underpowered():
    v, _ = lab.decide(**{**GOOD, "conf_sharpe": 1.0})                         # p95 와 같으면 통과
    assert v == lab.PASS
    v, _ = lab.decide(**{**GOOD, "cand_conf_mdd": -0.27, "base_conf_mdd": -0.22})   # 정확히 5%p 나쁘면 통과
    assert v == lab.PASS
    v, _ = lab.decide(**{**GOOD, "conf_active_ir": 0.0})                      # 0 은 '> 0' 아님
    assert v == lab.FAIL                                                       # 관측 IR ≤ 0 → 판별 불가가 아니라 FAIL
    mde = POWER["mde_ir"]
    v, _ = lab.decide(**{**GOOD, "conf_sharpe": 0.1, "conf_active_ir": mde / 2})   # 양수지만 MDE 미만에서 (b) 탈락
    assert v == lab.FAIL_UNDERPOWERED
    v, _ = lab.decide(**{**GOOD, "conf_sharpe": 0.1, "conf_active_ir": mde * 1.5})
    assert v == lab.FAIL


def test_verdict_not_evaluable_cases():
    assert lab.decide(**{**GOOD, "noop_reason": "same"})[0] == lab.NOT_EVALUABLE
    assert lab.decide(**{**GOOD, "baseline_ok": False})[0] == lab.NOT_EVALUABLE
    assert lab.decide(**{**GOOD, "chosen": None})[0] == lab.NOT_EVALUABLE
    assert lab.decide(**{**GOOD, "conf_sharpe": float("nan")})[0] == lab.NOT_EVALUABLE
    assert lab.decide(**{**GOOD, "rand_threshold": None})[0] == lab.NOT_EVALUABLE


def test_neighbor_rule_interior_and_edge():
    assert lab.neighbor_holds(3) == ([1, 6], "both") and lab.neighbor_holds(6) == ([3, 12], "both")
    assert lab.neighbor_holds(1) == ([3, 6], "any") and lab.neighbor_holds(12) == ([6, 3], "any")
    assert lab.neighbors_pass(6, {3: 0.1, 12: -0.1})[0] is False
    assert lab.neighbors_pass(1, {3: -0.1, 6: 0.2})[0] is True        # 끝: 안쪽 두 격자 중 하나 이상
    assert lab.neighbors_pass(12, {6: -0.1, 3: -0.2})[0] is False


def test_trial_count_and_job_coverage():
    assert lab.N_TRIALS_TOTAL == 32 and len(lab.CANDIDATES) == 8
    base = [s for j in ("sat-pool-v1", "sat-leader-v1", "sat-follower-v1") for s in lab.JOB_STRATEGIES[j]]
    assert sorted(base) == sorted(lab.CANDIDATES)
    assert lab.JOB_BACKEND["sat-pool-crsp-v1"] == "crsp" and lab.JOB_BACKEND["sat-pool-v1"] == "yahoo_pit"


def test_baseline_reproduction_check():
    idx = pd.bdate_range("2010-07-02", "2024-10-07")
    r = pd.Series(np.random.default_rng(2).normal(0.0005, 0.01, len(idx)), index=idx)
    ours = lab.check_baseline_reproduction(r, 0.0)["ours"]
    assert lab.check_baseline_reproduction(r, ours + 0.04)["status"] == "OK"
    out = lab.check_baseline_reproduction(r, ours + 0.06)
    assert out["status"] == "MISMATCH" and out["diff"] == pytest.approx(-0.06)
    assert lab.check_baseline_reproduction(r, None)["status"] == "UNVERIFIED"


def test_noop_candidate_is_not_evaluable_via_guard():
    x = pd.Series(np.zeros(100))
    assert rp.noop_guard(x.to_numpy()) is not None


# ---------------------------------------------------------------------------------------------
# 작업 정의
# ---------------------------------------------------------------------------------------------

JOB_IDS = {"sat-pool-v1": 11, "sat-leader-v1": 12, "sat-follower-v1": 13, "sat-pool-crsp-v1": 14, "sat-leader-crsp-v1": 15,
           "sat-follower-crsp-v1": 16}


@pytest.mark.parametrize("job_id,priority", JOB_IDS.items())
def test_job_json_contract(job_id, priority):
    from core import research_jobs as rj

    data = json.loads((ROOT / "research/jobs" / job_id / "job.json").read_text(encoding="utf-8"))
    job, reason = rj.validate_job(data, job_id, ROOT)
    assert job is not None, reason
    # CRSP 작업은 단독 재시도(메모리 상한 초과 시 혼자 다시 돎)가 의미 있도록 6000MB까지 허용한다(2026-10-11 사용자 승인).
    mem_cap = 6000 if job_id.endswith("-crsp-v1") else 3000
    assert data["priority"] == priority and data["resumable"] is True and data["max_memory_mb"] <= mem_cap
    assert data["outputs"] == ["results.json", "REPORT.md"] and data["summary_from"] == "verdicts"
    assert (ROOT / "research/jobs" / job_id / "SPEC.md").is_file()


def test_missing_crsp_exits_zero_with_not_evaluable_data(tmp_path):
    if (crsp.CRSP_DIR / "daily.csv").exists():
        pytest.skip("실제 CRSP 파일이 있는 환경")
    p = subprocess.run([sys.executable, str(ROOT / "research/jobs/sat-pool-crsp-v1/run.py"), "--out", str(tmp_path / "o"),
                        "--checkpoint", str(tmp_path / "c")], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-500:]
    res = json.loads((tmp_path / "o/results.json").read_text(encoding="utf-8"))
    assert res["verdicts"] == {"study": "NOT_EVALUABLE_DATA"}
    assert "daily.csv" in (tmp_path / "o/REPORT.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# CRSP 자료 계층
# ---------------------------------------------------------------------------------------------

def test_ff12_known_sics():
    cases = {2086: "NoDur", 2000: "NoDur", 3711: "Durbl", 3310: "Manuf", 3523: "Manuf", 1311: "Enrgy", 2911: "Enrgy", 2821: "Chems",
             2834: "Hlth", 8062: "Hlth", 3571: "BusEq", 7372: "BusEq", 3674: "BusEq", 4813: "Telcm", 4911: "Utils", 5411: "Shops",
             6021: "Money", 6798: "Money", 7000: "Other", 1000: "Other", 0: "Other", None: "Other", "3571": "BusEq"}
    for sic, name in cases.items():
        assert crsp.ff12_from_sic(sic) == name, sic
    assert set(crsp.FF12_NAMES) == {crsp.ff12_from_sic(s) for s in range(0, 10000, 7)}


def _write_tiny(dirpath, *, shift_after=None):
    days = pd.bdate_range("1990-01-02", "1990-06-29")
    rows = []
    for permno, ret, prc, shr in ((1, 0.01, 20.0, 1000.0), (2, 0.0, -10.0, 500.0), (3, 0.002, 30.0, 200.0), (4, 0.003, 15.0, 100.0)):
        for d in days:
            r, p = ret, prc
            if shift_after is not None and d >= shift_after:
                r, p = 0.2, 99.0
            rows.append((permno, d.strftime("%Y%m%d"), p, r, 1e5, shr))
    daily = pd.DataFrame(rows, columns=["permno", "date", "prc", "ret", "vol", "shrout"])
    daily = daily[~((daily.permno == 1) & (pd.to_datetime(daily.date) > pd.Timestamp("1990-04-30")))]   # permno 1 은 4/30 에 거래 종료
    daily.loc[(daily.permno == 3) & (daily.date == "19900115"), "ret"] = -99.0                         # 특수 코드 → 그날 수익 0
    daily.to_csv(dirpath / "daily.csv", index=False)
    pd.DataFrame([(1, "19900101", "", 3571, 1, 11), (2, "19900101", "19900331", 2834, 1, 11), (2, "19900401", "", 6021, 1, 11),
                  (3, "19900101", "", 2911, 1, 11), (4, "19900101", "", 4911, 1, 11)],
                 columns=["permno", "namedt", "nameendt", "siccd", "exchcd", "shrcd"]).to_csv(dirpath / "names.csv", index=False)
    pd.DataFrame([(1, "1990-04-30", -0.5, 500), (2, "1990-06-29", -55.0, 574)], columns=["permno", "date", "dlret", "dlstcd"]).to_csv(
        dirpath / "delists.csv", index=False)
    pd.DataFrame([(1, "19900101", "19900430"), (2, "19900101", ""), (3, "19900301", ""), (4, "19900101", "")],
                 columns=["permno", "start", "ending"]).to_csv(dirpath / "sp500.csv", index=False)


def test_crsp_input_problems(tmp_path):
    assert len(crsp.input_problems(tmp_path / "none")) == 4
    _write_tiny(tmp_path)
    assert crsp.input_problems(tmp_path) == []
    (tmp_path / "sp500.csv").write_text("permno,start\n1,19900101\n")
    assert any("ending" in p for p in crsp.input_problems(tmp_path))


def test_crsp_delisting_return_and_invalid_codes(tmp_path):
    _write_tiny(tmp_path)
    data, b = crsp.build_bundle(tmp_path, start="1990-02-01", data_start="1990-01-01")
    c1 = data.closes["1"].dropna()
    assert c1.index[-1] == pd.Timestamp("1990-04-30")
    # 마지막 기록일 수익 = (1+0.01)(1-0.5)-1 → 직전 날 대비 0.505 배
    assert c1.iloc[-1] / c1.iloc[-2] == pytest.approx(1.01 * 0.5)
    # 무효 코드 dlret(-55)은 적용하지 않는다: permno 2 는 ret 0 이므로 지수가 1 로 평평
    assert data.closes["2"].dropna().iloc[-1] == pytest.approx(1.0)
    assert b["meta"]["delists"]["performance_delist_without_valid_dlret"] == 1
    assert b["meta"]["delist_returns_applied"] == 1
    # 특수 코드 ret(-99)은 그날 수익 0: 1/15(월)의 지수는 1/12(금)과 같다
    c3 = data.closes["3"].dropna()
    assert c3.loc["1990-01-15"] == pytest.approx(c3.loc["1990-01-12"])
    assert c3.loc["1990-01-16"] / c3.loc["1990-01-15"] == pytest.approx(1.002)
    assert b["meta"]["ret_invalid_or_missing"] >= 1


def test_crsp_market_cap_membership_sector_use_prior_close(tmp_path):
    _write_tiny(tmp_path)
    data, b = crsp.build_bundle(tmp_path, start="1990-02-01", data_start="1990-01-01")
    mar1 = pd.Timestamp("1990-03-01")
    key = "1990-03-01"
    # 시총 = |prc| × shrout × 1000, 전 거래일(2/28) 값
    assert b["caps"][key]["2"] == pytest.approx(10.0 * 500.0 * 1000.0)
    assert b["caps"][key]["4"] == pytest.approx(15.0 * 100.0 * 1000.0)
    # permno 3 은 3/1 편입 — 전 거래일(2/28)에는 아직 구성종목이 아니다. 4/2 에는 구성종목.
    assert "3" not in data.pool("sp500_pit", mar1) and "3" not in b["caps"][key]
    assert "3" in data.pool("sp500_pit", pd.Timestamp(1990, 4, 2))
    # permno 1 은 4/30 종료(포함): 5/1 의 전 거래일이 4/30 이라 아직 구성종목, 6/1 에는 아니다
    assert "1" in data.pool("sp500_pit", pd.Timestamp(1990, 4, 2)) and "1" in data.pool("sp500_pit", pd.Timestamp(1990, 5, 1)) and "1" not in data.pool("sp500_pit", pd.Timestamp(1990, 6, 1))
    # 시점 SIC: permno 2 는 4/1 부터 금융(6021). 3/1 은 헬스(2834)
    assert b["sector_dated"]["1990-03-01"]["2"] == "Hlth" and b["sector_dated"]["1990-05-01"]["2"] == "Money"
    assert b["sector_dated"]["1990-03-01"]["4"] == "Utils"
    # 상위 40 풀은 시총 내림차순
    top = data.pool("champion40", pd.Timestamp(1990, 4, 2))
    caps = b["caps"]["1990-04-02"]
    assert top == sorted(top, key=lambda t: (-caps[t], t))


def test_crsp_no_lookahead_in_caps_pools_sectors(tmp_path):
    a, bdir = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    bdir.mkdir()
    _write_tiny(a)
    _write_tiny(bdir, shift_after=pd.Timestamp("1990-03-01"))     # 3/1 부터의 가격·수익을 완전히 바꾼다
    da, ba = crsp.build_bundle(a, start="1990-02-01", data_start="1990-01-01")
    db, bb = crsp.build_bundle(bdir, start="1990-02-01", data_start="1990-01-01")
    assert ba["caps"]["1990-03-01"] == bb["caps"]["1990-03-01"]
    assert ba["sector_dated"]["1990-03-01"] == bb["sector_dated"]["1990-03-01"]
    assert da.pool("champion40", pd.Timestamp(1990, 3, 1)) == db.pool("champion40", pd.Timestamp(1990, 3, 1))
    assert ba["caps"]["1990-04-02"] != bb["caps"]["1990-04-02"]            # 3/1 이후 자료는 4/2 시총에는 반영된다
    pd.testing.assert_series_equal(da.closes["4"].loc[:"1990-02-28"], db.closes["4"].loc[:"1990-02-28"])


def test_industry_core_held_uses_only_prior_data():
    cl = crsp.load_core_longrun_lab()
    syn = cl.synthetic_data(n12=12, n49=16, start="1990-01-01", end="2000-12-31")
    ind = syn["ind12"].copy()
    ind.columns = list(crsp.FF12_NAMES)
    monthly = [d for d in pd.Series(ind.index, index=ind.index).groupby(ind.index.to_period("M")).min() if d >= pd.Timestamp("1992-01-01")]
    held = crsp.industry_core_held(monthly, ind, syn["mkt"], cl)
    d = pd.Timestamp("1996-06-03") if pd.Timestamp("1996-06-03") in ind.index else monthly[60]
    ind2 = ind.copy()
    ind2.loc[ind2.index >= d] = ind2.loc[ind2.index >= d] * -3.0 + 0.05
    mkt2 = syn["mkt"].copy()
    mkt2.loc[mkt2.index >= d] = -0.02
    held2 = crsp.industry_core_held(monthly, ind2, mkt2, cl)
    assert held[d.date().isoformat()] == held2[d.date().isoformat()]
    assert 0 < len(held[d.date().isoformat()]) <= 4 and set(held[d.date().isoformat()]) <= set(crsp.FF12_NAMES)


def test_crsp_synthetic_files_roundtrip(tmp_path):
    crsp.write_synthetic(tmp_path, start="1961-01-02", end="1966-12-30", per_industry=2)
    assert crsp.input_problems(tmp_path) == []
    data, b = crsp.build_bundle(tmp_path, start="1963-07-01")
    assert b["meta"]["n_permnos"] == 24 and len(b["caps"]) > 40
    assert all(isinstance(t, str) for t in data.closes.columns)


def test_ff12_sic_ranges_match_the_official_french_file_for_every_sic():
    """Ken French Siccodes12.txt(2026-10-11 에 받은 사본)와 SIC 0~9999 전부 대조 — 기억으로 쓴 범위의 오류를 막는다."""
    import re
    names = set(crsp.FF12_NAMES)
    off, cur = {}, None
    for line in (Path(__file__).parent / "fixtures" / "ff12_siccodes12.txt").read_text(encoding="latin-1").splitlines():
        m = re.match(r"\s*(\d+)\s+(\w+)\s", line)
        if m and m.group(2) in names:
            cur = m.group(2)
            continue
        m = re.match(r"\s*(\d{4})-(\d{4})", line)
        if m and cur:
            for s in range(int(m.group(1)), int(m.group(2)) + 1):
                off[s] = cur
    bad = [s for s in range(10000) if off.get(s, "Other") != crsp.ff12_from_sic(s)]
    assert bad == []
