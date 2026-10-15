"""sat-exit-ladder-v1 (새틀라이트 매도 사다리) 사전 등록 규칙 테스트 — 합성 경로만, 네트워크 없음."""

import importlib.util
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("sat_exit_ladder_v1", ROOT / "research/jobs/sat-exit-ladder-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # @dataclass 가 모듈을 찾을 수 있게
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _path(vals, K=None):
    v = np.asarray(vals, dtype=float)
    K = K or len(v)
    C = np.full((1, K), v[-1])
    C[0, :len(v)] = v
    return C, np.array([len(v)])


def _flags(K, true_at=()):
    f = np.zeros((1, K), dtype=bool)
    for k in true_at:
        f[0, k] = True
    return f


# ---- 계약·상수 -------------------------------------------------------------------------------------------

def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "sat-exit-ladder-v1" in valid, invalid.get("sat-exit-ladder-v1")
    job = json.loads((ROOT / "research/jobs/sat-exit-ladder-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 8 and job["resumable"] is True and job["max_memory_mb"] <= 2500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"


def test_pre_registered_constants():
    assert mod.K_STOP == (1.0, 1.5, 2.0, 3.0) and mod.K_TRAIL == (1.0, 1.5, 2.0, 3.0)
    assert mod.M_FRAC == (0.33, 0.5, 1.0) and mod.REM_RULES == ("R0", "R1", "R2", "R3")
    assert mod.N_GRID == 144 and len(set(mod.grid_combos())) == 144
    assert mod.N_TRIALS == {"user": 1, "grid": 144, "entry": 4}
    assert mod.N_BOOT == 1000 and mod.BLOCK_DAYS == 126 and mod.BOOT_SEED == 20261015
    assert mod.CI_LOW_FLOOR == -0.005 and mod.MDD_TOL_CHAMP == 0.02 and mod.COST == 0.0008
    assert mod.CELL_MIN_EVENTS == 60 and mod.CELL_MIN_GAIN == 0.01 and mod.SAT_WEIGHT == 0.15
    assert mod.CONF_DAILY == ("2017-07-01", "2024-09-30")
    assert set(mod.JUDGED) == {"V_U", "V_G", "V_C", "V_E1", "V_E2", "V_E3a", "V_E3b"}


# ---- 상태 기계 ------------------------------------------------------------------------------------------

def test_user_example_20_30_27_and_40pct_sale():
    # 20 에 사서 22.5 에 활성(+10%), 30 에서 선 27, 26.9 < 27 → 다음 날 원래 보유의 40% 매도
    vals = [20, 21, 22.5, 25, 30, 28, 27.5, 26.9, 26.5, 26, 25, 25, 25]
    C, L = _path(vals)
    K = C.shape[1]
    out = mod.run_engine(C, L, 0.10, 0.10, 0.40, "R0", _flags(K), _flags(K))
    assert out.line[0, 4] == pytest.approx(27.0)
    assert np.isnan(out.line[0, 1])                       # 활성 전에는 선 없음
    assert out.sold[0, 8] == pytest.approx(0.40)          # 신호 7일 → 체결 8일
    assert out.sold[0].sum() == pytest.approx(0.40)       # R0: 나머지 보유
    assert out.trail_hit[0] and not out.stop_hit[0]


def test_line_ratchets_up_to_29_7():
    vals = [20, 22.5, 30, 33, 30, 31, 29.6, 29, 29, 29, 29]
    C, L = _path(vals)
    K = C.shape[1]
    out = mod.run_engine(C, L, 0.10, 0.10, 0.40, "R0", _flags(K), _flags(K))
    assert out.line[0, 2] == pytest.approx(27.0)
    assert out.line[0, 3] == pytest.approx(29.7)
    assert out.line[0, 4] == pytest.approx(29.7) and out.line[0, 5] == pytest.approx(29.7)   # 내려가지 않음
    assert out.sold[0, 7] == pytest.approx(0.40) and out.sold[0, :7].sum() == 0


def test_stop_path_sells_all_next_day():
    vals = [20, 19, 18.5, 17.9, 17, 16, 15, 15, 15]
    C, L = _path(vals)
    K = C.shape[1]
    out = mod.run_engine(C, L, 0.10, 0.10, 0.40, "R1", _flags(K), _flags(K))
    assert out.stop_hit[0] and out.sold[0, 4] == 1.0 and out.sold[0].sum() == 1.0


def test_stop_off_after_activation():
    vals = [20, 22.5, 22.6, 17.0, 17, 17, 17, 17, 17, 17]
    C, L = _path(vals)
    K = C.shape[1]
    out = mod.run_engine(C, L, 0.10, 0.10, 0.5, "R0", _flags(K), _flags(K))
    assert not out.stop_hit[0] and out.trail_hit[0] and out.sold[0].sum() == pytest.approx(0.5)


def test_remainder_r1_and_r2_trigger_from_l2_execution_day():
    vals = [20, 22.5, 30, 26.9, 27, 27, 27, 27, 27, 27, 27, 27, 27]
    C, L = _path(vals)
    K = C.shape[1]
    # 신호 3일, L2 체결 4일. 3일의 플래그는 무시(나머지는 4일 종가부터), 6일 플래그 → 7일 매도
    for rule, kw in (("R1", "below"), ("R2", "div")):
        below = _flags(K, (3, 6)) if kw == "below" else _flags(K)
        div = _flags(K, (3, 6)) if kw == "div" else _flags(K)
        out = mod.run_engine(C, L, 0.10, 0.10, 0.40, rule, below, div)
        assert out.sold[0, 4] == pytest.approx(0.40)
        assert out.sold[0, 7] == pytest.approx(0.60) and out.sold[0].sum() == pytest.approx(1.0)
        assert out.rem_hit[0]


def test_remainder_r3_second_line_two_t():
    vals = [20, 22.5, 30, 26.9, 30, 35, 30, 27.9, 27, 27, 27, 27]
    C, L = _path(vals)
    K = C.shape[1]
    out = mod.run_engine(C, L, 0.10, 0.10, 0.40, "R3", _flags(K), _flags(K))
    # 4일부터 최고 35, 선 28; 30 은 위, 27.9 < 28 → 8일 매도
    assert out.sold[0, 4] == pytest.approx(0.40) and out.sold[0, 8] == pytest.approx(0.60)


def test_m_one_sells_everything_at_line():
    vals = [20, 22.5, 30, 26.9, 27, 27, 27, 27]
    C, L = _path(vals)
    K = C.shape[1]
    out = mod.run_engine(C, L, 0.10, 0.10, 1.0, "-", _flags(K, (5,)), _flags(K))
    assert out.sold[0, 4] == 1.0 and out.sold[0].sum() == 1.0 and not out.rem_hit[0]


def test_no_sale_executes_on_rebalance_day():
    vals = [20, 20, 20, 17.0, 17]          # 신호 3일 → 체결 4일 = 리밸런싱일(L−1) → 무시
    C, L = _path(vals)
    K = C.shape[1]
    out = mod.run_engine(C, L, 0.10, 0.10, 0.4, "R0", _flags(K), _flags(K))
    assert out.sold.sum() == 0 and out.first_exit[0] == -1


def test_no_lookahead_actions_depend_only_on_past():
    rng = np.random.default_rng(3)
    vals = 20 * np.exp(np.cumsum(rng.normal(0, 0.03, 120)))
    vals[0] = 20
    C, L = _path(vals)
    K = C.shape[1]
    base = mod.run_engine(C, L, 0.1, 0.1, 0.4, "R3", _flags(K), _flags(K))
    for cut in (10, 40, 80):
        C2 = C.copy()
        C2[0, cut + 1:] *= rng.uniform(0.5, 1.5, K - cut - 1)
        alt = mod.run_engine(C2, L, 0.1, 0.1, 0.4, "R3", _flags(K), _flags(K))
        # cut 일까지의 종가가 같으면 cut+1 일까지의 체결(= cut 일 신호)은 같다
        assert np.array_equal(base.sold[:, :cut + 2], alt.sold[:, :cut + 2])
    # 지표 플래그도 t 이후 자료를 보지 않는다
    long = 50 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, 400)))
    b0, d0 = mod.indicator_flags(long)
    for cut in (100, 250):
        l2 = long.copy()
        l2[cut + 1:] *= 1.7
        b1, d1 = mod.indicator_flags(l2)
        assert np.array_equal(b0[:cut + 1], b1[:cut + 1]) and np.array_equal(d0[:cut + 1], d1[:cut + 1])


def test_event_value_includes_bil_and_costs():
    vals = [100, 100, 100, 100, 110]
    C, L = _path(vals)
    sold = np.zeros_like(C)
    sold[0, 2] = 0.5
    bil = np.ones_like(C)
    bil[0, 2] = 1.01
    got = mod.event_log_values(C, L, sold, bil)[0]
    c = mod.COST
    expect = math.log((1 - c) * (0.5 * 1.0 * (1 - c) * 1.01 + 0.5 * 1.1 * (1 - c)))
    assert got == pytest.approx(expect)


# ---- V_E 가족 ------------------------------------------------------------------------------------------

def test_ve1_ema21_cross_triggers_next_close():
    up = list(np.linspace(50, 80, 60))
    entry = len(up) - 1
    tail = [80.5, 81, 81.5, 76, 75, 75, 75, 75, 75, 75]
    full = np.array(up + tail)
    below, div = mod.indicator_flags(full)
    seg = full[entry:]
    C, L = _path(seg)
    b = below[entry:][None, :]
    d = div[entry:][None, :]
    first = int(np.argmax(b[0, 1:])) + 1            # 진입 다음 날부터의 첫 '종가 < EMA21'
    assert seg[first] == 76
    out = mod.run_engine(C, L, 0, 0, 1, "E1", b, d, mode="entry")
    assert out.sold[0, first + 1] == 1.0 and out.sold[0].sum() == 1.0


def test_no_action_before_day_after_entry():
    vals = [100, 100, 100, 100, 100, 100]
    C, L = _path(vals)
    K = C.shape[1]
    out = mod.run_engine(C, L, 0, 0, 1, "E1", _flags(K, (0,)), _flags(K), mode="entry")
    assert out.sold.sum() == 0                          # 진입일 플래그는 무시
    out = mod.run_engine(C, L, 0, 0, 1, "E1", _flags(K, (0, 1)), _flags(K), mode="entry")
    assert out.sold[0, :2].sum() == 0 and out.sold[0, 2] == 1.0


def test_ve2_divergence_trigger():
    vals = [100] * 8
    C, L = _path(vals)
    K = C.shape[1]
    out = mod.run_engine(C, L, 0, 0, 1, "E2", _flags(K), _flags(K, (3,)), mode="entry")
    assert out.sold[0, 4] == 1.0


def test_ve3_trailing_from_entry_ratchets_both_variants():
    vals = [100, 110, 120, 97, 95, 95, 95, 95]
    C, L = _path(vals)
    K = C.shape[1]
    a = mod.run_engine(C, L, 0.20, 0, 1, "E3", _flags(K), _flags(K), mode="entry")
    assert a.line[0, 1] == pytest.approx(88) and a.line[0, 2] == pytest.approx(96)
    assert a.line[0, 3] == pytest.approx(96)            # 97 은 선 위
    assert a.sold[0, 5] == 1.0                           # 95 < 96 신호 4일 → 5일
    # 진입가도 최고점에 포함: 100 → 79 이면 바로 신호
    C2, L2 = _path([100, 79, 79, 79, 79])
    assert mod.run_engine(C2, L2, 0.20, 0, 1, "E3", _flags(5), _flags(5), mode="entry").sold[0, 2] == 1.0
    # V_E3b: 선 = 3w
    w = np.array([0.05])
    b = mod.run_engine(C, L, 3 * w, 0, 1, "E3", _flags(K), _flags(K), mode="entry")
    assert b.line[0, 2] == pytest.approx(120 * 0.85)
    assert b.sold[0, 4] == 1.0                           # 97 < 102 신호 3일 → 4일


# ---- 지표·분류 ------------------------------------------------------------------------------------------

def test_divergence_definition():
    n = 60
    close = np.full(n, 100.0)
    close[20] = 110.0                                   # t=50 의 [10, 40] 구간 최고
    close[50] = 111.0
    rsi = np.full(n, 50.0)
    hist = np.zeros(n)
    rsi[20], rsi[50] = 70.0, 66.0                        # 4 낮음 → RSI 조건 아님
    hist[20], hist[50] = 1.0, 1.0                        # 같음 → 히스토그램 조건 아님
    assert not mod.bearish_divergence(close, rsi, hist)[50]
    rsi[50] = 64.9
    assert mod.bearish_divergence(close, rsi, hist)[50]
    rsi[50] = 66.0
    hist[50] = 0.5
    assert mod.bearish_divergence(close, rsi, hist)[50]
    close[50] = 110.0                                   # 신고가 아님
    assert not mod.bearish_divergence(close, rsi, hist)[50]
    close[50] = 111.0
    close[45] = 120.0                                   # t−5 는 구간 밖 → 영향 없음
    assert mod.bearish_divergence(close, rsi, hist)[50]
    assert not mod.bearish_divergence(close, rsi, hist)[:40].any()


def test_sigma_tercile_and_sector():
    r = np.tile([0.01, -0.01], 40)
    s = pd.Series(100 * np.exp(np.r_[0, np.cumsum(r)]))
    assert mod.sigma_63(s) == pytest.approx(np.std(r[-63:], ddof=1))
    assert math.isnan(mod.sigma_63(s.iloc[:30]))
    b = mod.vol_buckets({f"t{i}": float(i) for i in range(1, 10)} | {"nan": float("nan")})
    assert [b[f"t{i}"] for i in range(1, 10)] == ["low"] * 3 + ["mid"] * 3 + ["high"] * 3 and b["nan"] == "mid"
    assert mod.sector_family("Utilities") == ("defensive", False)
    assert mod.sector_family("Communication Services") == ("growth", False)
    assert mod.sector_family("Energy") == ("cyclical", False)
    assert mod.sector_family(None) == ("cyclical", True)


def test_cell_fallback_rule():
    combos = mod.grid_combos()
    vg = combos.index((1.0, 1.0, 0.5, "R1"))
    alt = combos.index((2.0, 3.0, 0.5, "R1"))
    other_m = combos.index((3.0, 3.0, 0.33, "R1"))      # m 이 다르면 셀 후보 아님

    def run(n, gain):
        cells = [("low", "defensive")] * n + [("mid", "growth")] * 70
        logv = np.zeros((len(combos), len(cells)))
        logv[alt, :n] = gain
        logv[other_m, :] = 1.0
        return mod.fit_cells(logv, combos, cells, vg)

    assert run(59, 0.5)["low|defensive"]["deviates"] is False
    got = run(60, 0.011)["low|defensive"]
    assert got["deviates"] is True and (got["k_stop"], got["k_trail"]) == (2.0, 3.0)
    assert run(60, 0.009)["low|defensive"]["deviates"] is False
    assert run(60, 0.011)["mid|growth"]["k_stop"] == 1.0                     # 이득 없음 → V_G
    assert run(60, 0.011)["high|growth"]["n_sel_events"] == 0


# ---- 판정 ----------------------------------------------------------------------------------------------

def test_primary_verdict_edges():
    d = mod.decide_primary
    ok = dict(diff_conf=0.001, sharpe_v=1.1, sharpe_0=1.0, mdd_v=-0.22, mdd_0=-0.20, ci_low=-0.0049)
    assert d(**ok) == mod.PASS
    assert d(**{**ok, "diff_conf": 0.0}) == mod.FAIL
    assert d(**{**ok, "sharpe_v": 1.0}) == mod.FAIL
    assert d(**{**ok, "mdd_v": -0.2201}) == mod.FAIL
    assert d(**{**ok, "ci_low": -0.005}) == mod.FAIL
    assert d(**ok, require_sel=True, diff_sel=0.0) == mod.FAIL
    assert d(**ok, require_sel=True, diff_sel=0.0001) == mod.PASS
    assert d(**ok, noop="same") == mod.NOT_EVALUABLE
    assert d(**{**ok, "ci_low": float("nan")}) == mod.NOT_EVALUABLE
    from core import research_power as rp
    pw = rp.power_report(7.0, 144)
    assert d(**{**ok, "diff_conf": -0.01}, observed_ir=0.1, power=pw) == "FAIL_UNDERPOWERED"


def test_secondary_verdicts():
    assert mod.beats_spy(0.1501, -0.329, 0.14, -0.30)
    assert not mod.beats_spy(0.1499, -0.30, 0.14, -0.30)
    assert not mod.beats_spy(0.2, -0.3301, 0.14, -0.30)
    assert mod.beats_champion(0.11, -0.299, 0.10, -0.20)
    assert not mod.beats_champion(0.11, -0.3001, 0.10, -0.20)
    assert not mod.beats_champion(0.10, -0.10, 0.10, -0.20)


def test_bootstrap_deterministic():
    rng = np.random.default_rng(0)
    a, b = rng.normal(0.0005, 0.01, 600), rng.normal(0.0003, 0.01, 600)
    x, y = mod.block_bootstrap_diff(a, b, 252), mod.block_bootstrap_diff(a, b, 252)
    assert len(x) == 1000 and np.array_equal(x, y)


# ---- 챔피언 구성 ----------------------------------------------------------------------------------------

def _toy_core():
    idx = pd.bdate_range("2020-01-01", "2020-12-31")
    core = pd.DataFrame(0.0, index=idx, columns=["C1", "C2"])
    core.loc[idx.month % 2 == 0, "C1"] = 1.0
    core.loc[idx.month % 2 == 1, "C2"] = 1.0
    rng = np.random.default_rng(1)
    adj = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))) for t in ["C1", "C2", "A", "B", "D", "BIL"]},
                       index=idx)
    return idx, core, adj


def test_v0_equals_satellite_value_champion_construction():
    idx, core, adj = _toy_core()
    sched = [(idx[0], ["A", "B", "D"]), (idx[idx.month == 7][0], ["A", "B"])]
    mine = mod.build_target_weights(core, sched, {}, 0.15, adj)
    logs = mod.SV.schedule_to_log([(d.date().isoformat(), p) for d, p in sched])
    theirs = mod.SV.build_weights(core, {"A": logs, "A2": logs})["A"]
    pd.testing.assert_frame_equal(mine[sorted(mine.columns)], theirs[sorted(theirs.columns)], check_dtype=False)


def test_exit_day_keeps_other_drift_and_moves_sold_to_bil():
    idx, core, adj = _toy_core()
    sched = [(idx[0], ["A", "B", "D"]), (idx[idx.month == 7][0], ["A", "B"])]
    exit_day = idx[idx.month == 1][10]                   # 코어 변경 없는 날
    sales = {(0, "A"): [(exit_day, 0.4)]}
    w = mod.build_target_weights(core, sched, sales, 0.15, adj)
    i = w.index.get_loc(exit_day)
    prev, row = w.iloc[i - 1], w.iloc[i]
    assert row["BIL"] > 0 and prev["BIL"] == 0
    assert row.sum() == pytest.approx(prev.sum(), abs=1e-9)        # 현금 비중 그대로
    # 다른 종목은 표류 비중(전날 목표 × 가격 변화 비율) 그대로
    g = prev * (1 + adj.pct_change().iloc[1:i + 1].add(1).prod().sub(1).reindex(prev.index).fillna(0))
    port = g.sum() + (1 - prev.sum())
    assert row["B"] == pytest.approx(g["B"] / port, rel=1e-9)
    assert row["A"] == pytest.approx(g["A"] / port * 0.6, rel=1e-9)
    assert (w.iloc[i + 1] == row).all()                  # 다음 날은 매매 없음
    # 7월 리밸런싱일에는 BIL 0 으로 리셋
    assert w.loc[sched[1][0], "BIL"] == 0


def test_replicated_schedule_matches_s_seed_000():
    from core import satellite_lab as sl

    pp, poolp = sl.synthetic_providers(n_tickers=30, start="2008-01-01", end="2013-12-31", seed=4)
    pool = mod.SV._pool_wrapper(poolp, date.fromisoformat("2010-01-01"))
    data = sl.build_data({"champion40"}, start="2009-12-01", end="2013-12-31", pool_provider=pool, price_provider=pp)
    got = mod.replicate_schedule(data, {})
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    ref = sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), data)["schedule"]
    assert [(r["date"].date().isoformat(), r["picks"]) for r in got] == [(d, list(p)) for d, p in ref]
    assert got[0]["date"] == pd.Timestamp("2010-01-01")
    for r in got:
        assert set(r["picks"]) <= set(r["cands"])
        assert all(c[2] == "cyclical" and c[3] for c in r["cands"].values())
