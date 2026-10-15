"""sat-stop-v1 (새틀라이트 손절 방식 × 손절 뒤 행동) 사전 등록 규칙 테스트 — 합성 경로만, 네트워크 없음."""

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("sat_stop_v1", ROOT / "research/jobs/sat-stop-v1/run.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


mod = _load()


def _path(vals, K=None):
    v = np.asarray(vals, dtype=float)
    K = K or len(v)
    C = np.full((1, K), v[-1])
    C[0, :len(v)] = v
    return C, np.array([len(v)])


def _nobrk(K):
    return np.zeros((1, K), dtype=bool)


def _exec_days(out):
    p = out.pos[0]
    return [k for k in range(1, len(p)) if p[k] != p[k - 1]]


# ---- 계약·상수 -------------------------------------------------------------------------------------------

def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "sat-stop-v1" in valid, invalid.get("sat-stop-v1")
    job = json.loads((ROOT / "research/jobs/sat-stop-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 8 and job["resumable"] is True and job["max_memory_mb"] <= 2500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert (ROOT / "research/jobs/sat-stop-v1/SPEC.md").exists()


def test_pre_registered_constants():
    assert mod.FIXED_PCT == (0.10, 0.15, 0.20, 0.25) and mod.K_W == (2.0, 3.0, 4.0)
    assert mod.N_TRIALS == 42 and len(mod.JUDGED) == 12
    assert mod.MAX_REENTRY == 2 and mod.WHIPSAW_DAYS == 20
    assert mod.N_BOOT == 1000 and mod.BLOCK_DAYS == 126 and mod.BOOT_SEED == 20261019
    assert mod.CI_LOW_FLOOR == -0.005 and mod.MDD_TOL_CHAMP == 0.02 and mod.COST == 0.0008
    assert mod.SEL_ENTRY == ("2010-01-01", "2016-07-31") and mod.CONF_ENTRY == ("2017-07-01", "2024-01-31")
    assert mod.CONF_DAILY == ("2017-07-01", "2024-09-30")


# ---- 손절 유형 -------------------------------------------------------------------------------------------

def test_t1_hard_stop_from_entry_executes_next_close():
    C, L = _path([100, 98, 95, 90, 89, 92, 95, 97, 99, 100])
    out = mod.run_stops(C, L, _nobrk(10), 0.10, "T1", "A1")
    assert [s[1] for s in out.stops] == [3]          # 90 ≤ 100×0.9 (신호 k=3)
    assert _exec_days(out) == [4]                    # 체결 k+1
    assert out.pos[0, :4].all() and not out.pos[0, 4:].any()


def test_t2_k_times_w():
    C, L = _path([100, 95, 92, 91, 88, 90, 90, 90])
    w = np.array([0.05])
    out = mod.run_stops(C, L, _nobrk(8), mod.width_for("T2", 2.0, w), "T2", "A1")   # 선 = 90
    assert [s[1] for s in out.stops] == [4]
    out3 = mod.run_stops(C, L, _nobrk(8), mod.width_for("T2", 3.0, w), "T2", "A1")  # 선 = 85
    assert out3.stops == []


def test_t3_trailing_from_highest_close_ratchets():
    C, L = _path([100, 110, 130, 125, 118, 116, 117, 120, 120, 120])
    out = mod.run_stops(C, L, _nobrk(10), 0.10, "T3", "A1")      # 최고 130 → 선 117
    assert [(s[1], round(s[2], 6)) for s in out.stops] == [(5, 117.0)]
    # 진입가 기준(T1)이면 같은 경로에서 발동 없음
    assert mod.run_stops(C, L, _nobrk(10), 0.10, "T1", "A1").stops == []


def test_t4_trailing_k_w():
    C, L = _path([100, 120, 110, 107, 105, 103, 103, 103])
    out = mod.run_stops(C, L, _nobrk(8), mod.width_for("T4", 3.0, np.array([0.05])), "T4", "A1")   # 120×0.85 = 102
    assert out.stops == []
    out = mod.run_stops(C, L, _nobrk(8), mod.width_for("T4", 2.0, np.array([0.05])), "T4", "A1")   # 108
    assert [s[1] for s in out.stops] == [3]


def test_no_execution_on_rebalance_day():
    C, L = _path([100, 99, 98, 99, 85, 86])            # L=6: 신호 k=4 → 체결 5 = 리밸런싱일 → 무시
    out = mod.run_stops(C, L, _nobrk(6), 0.10, "T1", "A1")
    assert out.stops == [] and out.pos[0].all()


# ---- A2 재진입 -------------------------------------------------------------------------------------------

def _brk(C):
    return mod.breakout_flags(C[0])[None, :]


def test_a2_reenters_only_after_fresh_breakout_and_resets_stop():
    pre = list(np.linspace(80, 99, 20))                  # 앞 20일(돌파 계산용)
    path = [100, 95, 89, 88, 90, 92, 101, 102, 100, 99, 95, 93, 92, 92, 92]
    full = np.array(pre + path, dtype=float)
    brk_full = mod.breakout_flags(full)
    C, L = _path(path)
    BRK = brk_full[20:][None, :]
    out = mod.run_stops(C, L, BRK, 0.10, "T1", "A2")
    # 손절 신호 k=2(89 ≤ 90) → 체결 3; 돌파: 101 > 직전 20일 최고(100) → k=6 신호, 7 체결
    assert out.stops[0][1] == 2
    assert out.reentries == [(0, 6)]
    assert not BRK[0, 4] and not BRK[0, 5]               # 회복만으로는 재진입 없음
    assert out.pos[0, 7] and not out.pos[0, 6]
    # 새 진입가 102 → 선 91.8: 92 는 그대로, 91.8 이하에서만 다시 손절
    assert len(out.stops) == 1


def test_a2_max_two_reentries():
    K = 40
    C = np.full((1, K), 100.0)
    # 손절 → 돌파 재진입 → 손절 → 재진입 → 손절 → (세 번째 돌파는 막힘)
    seq = [100, 85, 85, 120, 120, 100, 100, 130, 130, 110, 110, 140, 140, 140]
    C[0, :len(seq)] = seq
    C[0, len(seq):] = 140
    L = np.array([K])
    BRK = np.zeros((1, K), dtype=bool)
    for k in (3, 7, 11):
        BRK[0, k] = True
    out = mod.run_stops(C, L, BRK, 0.10, "T1", "A2")
    assert [k for _, k in out.reentries] == [3, 7]
    assert out.blocked.sum() >= 1
    assert len(out.stops) == 3


def test_a1_never_reenters():
    C, L = _path([100, 85, 85, 120, 120, 120])
    BRK = np.zeros((1, 6), dtype=bool)
    BRK[0, 3] = True
    out = mod.run_stops(C, L, BRK, 0.10, "T1", "A1")
    assert out.reentries == [] and not out.pos[0, 2:].any()


def test_path_values_match_ladder_full_sale():
    rng = np.random.default_rng(3)
    n, K = 50, 60
    C = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, (n, K)), axis=1))
    C[:, 0] = 100
    L = rng.integers(10, K + 1, n)
    B = np.cumprod(np.full((n, K), 1.0001), axis=1)
    out = mod.run_stops(C, L, np.zeros((n, K), dtype=bool), 0.15, "T3", "A1")
    mine = mod.path_log_values(C, L, B, out.pos)
    lad = mod.LD.run_engine(C, L, 0.15, 0, 1, "E3", None, None, mode="entry")
    btoe = np.array([[B[e, L[e] - 1] / B[e, k] if k < L[e] else 1.0 for k in range(K)] for e in range(n)])
    theirs = mod.LD.event_log_values(C, L, lad.sold, btoe)
    assert np.allclose(mine, theirs, atol=1e-12)
    v0 = mod.path_log_values(C, L, B, np.ones((n, K), dtype=bool))
    assert np.allclose(v0, np.log(C[np.arange(n), L - 1] / 100) + 2 * math.log(1 - mod.COST))


def test_no_lookahead_future_changes_do_not_alter_past_actions():
    rng = np.random.default_rng(7)
    C = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, (20, 80)), axis=1))
    L = np.full(20, 80)
    BRK = rng.random((20, 80)) < 0.1
    for st in mod.STOP_TYPES:
        a = mod.run_stops(C, L, BRK, 0.1, st, "A2")
        C2, B2 = C.copy(), BRK.copy()
        C2[:, 50:] *= 0.3
        B2[:, 50:] = ~B2[:, 50:]
        b = mod.run_stops(C2, L, B2, 0.1, st, "A2")
        assert np.array_equal(a.pos[:, :51], b.pos[:, :51])


def test_trend_and_momentum_use_data_up_to_t():
    rng = np.random.default_rng(1)
    px = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 600)))
    ta, mom = mod.trend_active_series(px), mod.momentum_series(px)
    px2 = px.copy()
    px2[400:] *= 2
    assert np.array_equal(ta[:400], mod.trend_active_series(px2)[:400])
    assert np.allclose(mom[:400], mod.momentum_series(px2)[:400], equal_nan=True)
    assert mom[300] == pytest.approx(px[300] / px[48] - 1)


# ---- A3 교체 ---------------------------------------------------------------------------------------------

def _universe(series: dict, n):
    tick = sorted(series)
    PX = np.array([series[t] for t in tick], dtype=float)
    U = mod.Universe(tick, PX, np.isfinite(PX), np.vstack([mod.trend_active_series(r) for r in PX]),
                     np.vstack([mod.momentum_series(r, 5) for r in PX]), np.linspace(100, 101, n))
    return U


def test_a3_picks_best_ranked_non_held_trend_active_from_frozen_pool():
    n = 80
    base = np.linspace(50, 100, n)                      # 꾸준히 오름 → 추세 활성
    s = {"A": base.copy(), "B": base * 1.0, "C": base.copy(), "D": base.copy(), "E": base.copy(), "OUT": base.copy()}
    s["A"][60:] = s["A"][59] * 0.8                     # A: k=?에서 손절
    s["B"] = 50 * np.exp(np.linspace(0, 0.9, n))       # B 보유 중(모멘텀 최고지만 제외)
    s["C"] = 50 * np.exp(np.linspace(0, 0.6, n))       # C: 보유 아님, 모멘텀 2위 → 교체
    s["D"] = 50 * np.exp(np.linspace(0, 0.3, n))
    s["OUT"] = 50 * np.exp(np.linspace(0, 2.0, n))     # 풀 밖 — 고르면 안 됨
    s["E"][:] = np.linspace(100, 60, n)                # 하락 → 추세 비활성
    U = _universe(s, n)
    i0 = 50
    po = mod.run_replace_period(U, i0, 25, ["A", "B", "D"], ["A", "B", "C", "D", "E"], [0.05] * 3, "T1", 0.10, 0.05)
    assert po.replacements and po.replacements[0][1] == "A" and po.replacements[0][2] == "C"
    k = po.replacements[0][3]
    assert i0 + k == 60                                # 신호일 = 첫 하락 종가
    assert po.segs[0][1] == (k + 1, "C")               # 다음 날 종가에 교체


def test_a3_ranking_uses_only_data_up_to_stop_day_and_falls_back_to_bil():
    n = 80
    s = {"A": np.linspace(50, 100, n), "C": 50 * np.exp(np.linspace(0, 0.6, n)), "D": 50 * np.exp(np.linspace(0, 0.3, n))}
    s["A"][60:] = s["A"][59] * 0.8
    U = _universe(s, n)
    r1 = mod.rank_replacement(U, ["A", "C", "D"], {"A"}, 60)
    s2 = {k: v.copy() for k, v in s.items()}
    s2["D"][61:] *= 5                                   # 미래에 D 가 폭등해도 순위 불변
    U2 = _universe(s2, n)
    assert r1 == mod.rank_replacement(U2, ["A", "C", "D"], {"A"}, 60) == "C"
    po = mod.run_replace_period(U, 50, 25, ["A"], ["A"], [0.05], "T1", 0.10, 0.05)
    assert po.replacements[0][2] is None and po.segs[0][1][1] is None


def test_slot_weights_v0_and_bil_match_ladder():
    idx = pd.bdate_range("2020-01-01", "2020-12-31")
    core = pd.DataFrame(0.0, index=idx, columns=["C1", "C2"])
    core.loc[idx.month % 2 == 0, "C1"] = 1.0
    core.loc[idx.month % 2 == 1, "C2"] = 1.0
    rng = np.random.default_rng(1)
    adj = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))) for t in ["C1", "C2", "A", "B", "D", "E", "BIL"]},
                       index=idx)
    sched = [(idx[0], ["A", "B", "D"]), (idx[idx.month == 7][0], ["A", "B"])]
    pd.testing.assert_frame_equal(mod.build_slot_weights(core, sched, {}, 0.15, adj),
                                  mod.LD.build_target_weights(core, sched, {}, 0.15, adj), check_dtype=False)
    d = idx[idx.month == 1][10]
    mine = mod.build_slot_weights(core, sched, {(0, 0): [(d, None)]}, 0.15, adj)
    theirs = mod.LD.build_target_weights(core, sched, {(0, "A"): [(d, 1.0)]}, 0.15, adj)
    pd.testing.assert_frame_equal(mine[sorted(mine.columns)], theirs[sorted(theirs.columns)], check_dtype=False, atol=1e-12)
    # 교체: 같은 날 A 의 표류 가치가 E 로 그대로 옮겨진다
    rep = mod.build_slot_weights(core, sched, {(0, 0): [(d, "E")]}, 0.15, adj)
    assert rep.loc[d, "E"] == pytest.approx(theirs.loc[d, "BIL"], rel=1e-12) and rep.loc[d, "A"] == 0


# ---- 맞추기·판정 -----------------------------------------------------------------------------------------

def test_fit_uses_grid_means_and_ties_first():
    grid = {(st, a, x): 0.0 for st in mod.STOP_TYPES for a in mod.ACTIONS for x in mod.WIDTHS[st]}
    grid[("T1", "A2", 0.20)] = 0.01
    fit = mod.fit_widths(grid)
    assert fit["T1_A2"]["x"] == 0.20 and fit["T1_A1"]["x"] == 0.10 and fit["T4_A3"]["x"] == 2.0
    assert len(fit) == 12


def test_fitting_uses_selection_only():
    """main 의 격자는 선정 사건·선정 기간만 eval 에 넘긴다."""
    import inspect
    src = inspect.getsource(mod.main)
    assert 'eval_event_cell(se, sel_idx' in src and 'periods_of(prep, se, "sel")' in src
    assert "eval_replace(U, sel_periods" in src


def test_primary_verdict_edges():
    d = mod.decide_primary
    ok = dict(diff_conf=0.001, sharpe_v=1.1, sharpe_0=1.0, mdd_v=-0.22, mdd_0=-0.20, ci_low=-0.0049)
    assert d(**ok) == mod.PASS
    assert d(**{**ok, "diff_conf": 0.0}) == mod.FAIL
    assert d(**{**ok, "sharpe_v": 1.0}) == mod.FAIL
    assert d(**{**ok, "mdd_v": -0.2201}) == mod.FAIL
    assert d(**{**ok, "ci_low": -0.005}) == mod.FAIL
    assert d(**ok, noop="same") == mod.NOT_EVALUABLE
    from core import research_power as rp
    assert d(**{**ok, "diff_conf": -0.01}, observed_ir=0.1, power=rp.power_report(7.0, 42)) == "FAIL_UNDERPOWERED"


def test_bootstrap_deterministic_with_new_seed():
    rng = np.random.default_rng(0)
    a, b = rng.normal(0.0005, 0.01, 600), rng.normal(0.0003, 0.01, 600)
    x, y = mod.block_bootstrap_diff(a, b, 252), mod.block_bootstrap_diff(a, b, 252)
    assert len(x) == 1000 and np.array_equal(x, y)
    z = mod.SV.block_bootstrap_diff(a, b, 252, n_boot=1000, block=126, seed=20261015)
    assert not np.array_equal(x, z)
