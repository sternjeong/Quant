"""mom-proxy-v1 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

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
    spec = importlib.util.spec_from_file_location("mom_proxy_v1", ROOT / "research/jobs/mom-proxy-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "mom-proxy-v1" in valid, invalid.get("mom-proxy-v1")
    job = json.loads((ROOT / "research/jobs/mom-proxy-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 16 and job["resumable"] is True and job["max_memory_mb"] <= 2000
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert (ROOT / "research/jobs/mom-proxy-v1/SPEC.md").exists()


def test_pre_registered_constants():
    from core import french_factors as ff

    assert ff.DATASETS[mod.DATASET_6] == "6_Portfolios_ME_Prior_12_2_Daily_CSV.zip" == mod.FILE_6
    assert ff.DATASETS[mod.DATASET_25] == "25_Portfolios_ME_Prior_12_2_Daily_CSV.zip" == mod.FILE_25
    assert mod.COL_BIG_HI == "BIG HiPRIOR" and mod.JUDGED_SLEEVE == "BIGHI"
    assert mod.W_CELLS == (0.15, 0.30, 0.50, 0.70, 1.00) and mod.CELLS == ("w15", "w30", "w50", "w70", "w100")
    assert (mod.DRAG, mod.DRAG_SENS, mod.COST_BPS, mod.N_TRIALS) == (0.01, (0.0, 0.02), 10.0, 5)
    assert mod.WINDOWS == {"sel": ("1927-07-01", "1966-12-31"), "conf": ("1967-01-01", "2007-12-31"), "post": ("2008-01-01", None)}
    assert mod.CONF_SUBS == (("1967-01-01", "1986-12-31"), ("1987-01-01", "2007-12-31"))
    assert (mod.ROLL_DAYS, mod.WORST12_SLACK, mod.CAGR_MARGIN, mod.ALPHA_T_MIN, mod.POWER_YEARS) == (252, 0.05, 0.01, 2.0, 41.0)
    assert mod.CAL_WINDOWS == {"full": ("2010-01-01", "2024-09-30"), "h1": ("2010-01-01", "2017-05-31"), "h2": ("2017-06-01", "2024-09-30")}


# ---------------------------------------------------------------- 끌림·재조정

def test_drag_application():
    idx = pd.bdate_range("2000-01-03", periods=252)
    r = pd.Series(0.0, index=idx)
    d = mod.apply_drag(r, 0.01)
    assert (1 + d).prod() == pytest.approx((1 - 0.01 / 252) ** 252)
    assert (1 + d).prod() - 1 == pytest.approx(-0.01, abs=1e-4)
    r2 = pd.Series(0.01, index=idx[:3])
    assert mod.apply_drag(r2, 0.0).tolist() == pytest.approx(r2.tolist())
    assert mod.apply_drag(r2, 0.02).iloc[0] == pytest.approx(1.01 * (1 - 0.02 / 252) - 1)


def test_annual_rebalance_only_on_first_trading_day_of_year():
    idx = pd.bdate_range("2000-12-27", "2001-01-05")
    sleeve = pd.Series(0.10, index=idx)
    mkt = pd.Series(0.0, index=idx)
    out = mod.blend(sleeve, mkt, 0.5, bps=0.0)
    # 2000 년 안: 표류(슬리브 비중이 커지며 포트폴리오 수익이 커짐)
    va, vb = 0.5, 0.5
    exp = []
    for i, d in enumerate(idx):
        prev = va + vb
        va *= 1.10
        tot = va + vb
        if i > 0 and d.year != idx[i - 1].year:
            va, vb = 0.5 * tot, 0.5 * tot
        exp.append(tot / prev - 1)
    assert out.tolist() == pytest.approx(exp)
    first_2001 = list(idx.year).index(2001)
    # 재조정 다음 날 수익은 정확히 0.5 × 10%
    assert out.iloc[first_2001 + 1] == pytest.approx(0.05)
    assert out.iloc[first_2001 - 1] > 0.05
    # 비용: 재조정 날만 회전율 × 10bp
    with_cost = mod.blend(sleeve, mkt, 0.5, bps=10.0)
    diff = (out - with_cost).abs()
    assert diff.iloc[first_2001] > 0 and diff.drop(idx[first_2001]).max() == pytest.approx(0.0)


def test_w100_is_pure_sleeve():
    idx = pd.bdate_range("2000-06-01", "2002-03-01")
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(0.0005, 0.01, len(idx)), index=idx)
    m = pd.Series(rng.normal(0.0003, 0.01, len(idx)), index=idx)
    assert mod.blend(s, m, 1.0).tolist() == pytest.approx(s.tolist())


# ---------------------------------------------------------------- 안정성 지표

def test_stability_metrics_hand_built():
    idx = pd.bdate_range("2000-01-03", periods=4)
    r = pd.Series([0.10, -0.50, 0.20, 0.0], index=idx)
    # 값 1 → 1.1 → 0.55 → 0.66 → 0.66, 고점 1.1 → 0.55 = −50%
    assert mod.max_drawdown(r) == pytest.approx(-0.5)
    # 시작 전 값 1 을 고점으로 친다
    assert mod.max_drawdown(pd.Series([-0.2, 0.1], index=idx[:2])) == pytest.approx(-0.2)
    assert mod.worst_rolling(r, 2) == pytest.approx(min(0.55 / 1.0, 0.66 / 1.1, 0.66 / 0.55) - 1)
    assert mod.worst_rolling(r, 5) is None
    long = pd.Series(0.001, index=pd.bdate_range("2000-01-03", periods=300))
    assert mod.worst_rolling(long) == pytest.approx(1.001 ** 252 - 1)


def test_stable_edges():
    mk = {"mdd": -0.30, "worst12": -0.20}
    assert mod.stable({"mdd": -0.30, "worst12": -0.25}, mk) == (True, True)      # 같음 = 나쁘지 않음, 정확히 −5%p
    assert mod.stable({"mdd": -0.3001, "worst12": -0.2501}, mk) == (False, False)
    assert mod.stable({"mdd": -0.30 - 1e-12, "worst12": -0.25 - 1e-12}, mk) == (True, True)   # 부동소수 잡음은 허용
    assert mod.stable({"mdd": float("nan"), "worst12": None}, mk) == (False, False)


# ---------------------------------------------------------------- 고르기

def _m(cagr, mdd=-0.2, w12=-0.1):
    return {"cagr": cagr, "mdd": mdd, "worst12": w12}


def test_select_highest_cagr_among_stable():
    mk = {"mdd": -0.3, "worst12": -0.2}
    sel = {"w15": _m(0.08), "w30": _m(0.09), "w50": _m(0.12, mdd=-0.35), "w70": _m(0.11, w12=-0.26), "w100": _m(0.10)}
    assert mod.select_cell(sel, mk) == "w100"


def test_select_ties_go_to_lower_w():
    mk = {"mdd": -0.3, "worst12": -0.2}
    sel = {"w15": _m(0.08), "w30": _m(0.10), "w50": _m(0.10), "w100": _m(0.10 - 1e-12)}
    assert mod.select_cell(sel, mk) == "w30"


def test_select_none_eligible():
    mk = {"mdd": -0.1, "worst12": -0.05}
    assert mod.select_cell({c: _m(0.2, mdd=-0.5) for c in mod.CELLS}, mk) is None


def test_selection_uses_only_selection_window():
    """확인·2008 구간 자료를 바꿔도 고른 칸은 같다(선택 구간 자료만 본다)."""
    fr = mod.synthetic_french()
    power = {"mde_ir": 0.44}
    base = mod.frontier(fr["BIGHI"], fr["mkt"], fr["rf"], mod.DRAG, power)
    s2 = fr["BIGHI"].copy()
    late = s2.index >= pd.Timestamp("1967-01-01")
    s2[late] = s2[late] - 0.002          # 확인 이후 슬리브를 크게 망가뜨림
    alt = mod.frontier(s2, fr["mkt"], fr["rf"], mod.DRAG, power)
    assert base["chosen"] == alt["chosen"] and base["chosen"] is not None
    for c in mod.CELLS:
        assert base["metrics"][c]["sel"]["cagr"] == pytest.approx(alt["metrics"][c]["sel"]["cagr"])
    assert alt["metrics"][base["chosen"]]["conf"]["cagr"] < base["metrics"][base["chosen"]]["conf"]["cagr"]
    assert alt["verdict"] != mod.PASS


# ---------------------------------------------------------------- 통과 규칙

def _checks(**over):
    c = {"cagr_ge_mkt_plus_1pp": True, "A_mdd": True, "B_worst12": True, "beat_1967_1986": True, "beat_1987_2007": True, "alpha_t_ge_2": True}
    c.update(over)
    return c


def test_conf_checks_edges():
    mk = {"cagr": 0.08, "mdd": -0.4, "worst12": -0.3}
    subs = [{"cagr": 0.05, "market_cagr": 0.04}, {"cagr": 0.10, "market_cagr": 0.09}]
    ok = mod.conf_checks({"cagr": 0.09, "mdd": -0.4, "worst12": -0.35}, mk, subs, {"alpha_t_nw6": 2.0})
    assert all(v is True for v in ok.values())
    near = mod.conf_checks({"cagr": 0.0899, "mdd": -0.4, "worst12": -0.35}, mk, subs, {"alpha_t_nw6": 1.999})
    assert near["cagr_ge_mkt_plus_1pp"] is False and near["alpha_t_ge_2"] is False
    tie = mod.conf_checks({"cagr": 0.09, "mdd": -0.4, "worst12": -0.3}, mk,
                          [{"cagr": 0.04, "market_cagr": 0.04}, subs[1]], {"alpha_t_nw6": 3})
    assert tie["beat_1967_1986"] is False     # 같으면 이긴 것이 아니다(> 시장)
    miss = mod.conf_checks({"cagr": 0.09, "mdd": -0.4, "worst12": -0.3}, mk, subs, {"alpha_t_nw6": float("nan")})
    assert miss["alpha_t_ge_2"] is None


def test_decide_rules():
    power = {"mde_ir": 0.44}
    assert mod.decide(_checks(), None, 0.5, power) == (mod.PASS, [])
    assert mod.decide(_checks(), "noop", 0.5, power)[0] == mod.NOT_EVALUABLE
    assert mod.decide(_checks(alpha_t_ge_2=None), None, 0.5, power)[0] == mod.NOT_EVALUABLE
    v, miss = mod.decide(_checks(beat_1987_2007=False), None, 0.30, power)
    assert v == "FAIL_UNDERPOWERED" and miss == ["beat_1987_2007"]
    assert mod.decide(_checks(A_mdd=False), None, 0.60, power)[0] == mod.FAIL
    assert mod.decide(_checks(A_mdd=False), None, -0.1, power)[0] == mod.FAIL


def test_noop_cell_not_evaluable():
    fr = mod.synthetic_french()
    out = mod.frontier(fr["mkt"], fr["mkt"], fr["rf"], 0.0, {"mde_ir": 0.44})
    # 슬리브 = 시장, 끌림 0 → 모든 칸이 시장과 같다(연 재조정 비용도 0) → 고른 칸은 NOT_EVALUABLE
    assert out["chosen"] == "w15" and out["verdict"] == mod.NOT_EVALUABLE


# ---------------------------------------------------------------- PART 1 날짜 맞춤

def test_align_to_calendar_preserves_cumulative_and_merges_missing_days():
    sat_idx = pd.DatetimeIndex(["2010-01-04", "2010-01-05", "2010-01-06", "2010-01-07", "2010-01-08"])
    r = pd.Series([0.01, 0.02, -0.01, 0.03, 0.00], index=sat_idx)
    cal = pd.DatetimeIndex(["2009-12-31", "2010-01-04", "2010-01-06", "2010-01-07", "2010-01-08", "2010-01-11"])
    out = mod.align_to_calendar(r, cal)
    assert list(out.index) == list(pd.DatetimeIndex(["2010-01-04", "2010-01-06", "2010-01-07", "2010-01-08"]))
    assert out.iloc[0] == pytest.approx(0.01)
    assert out.iloc[1] == pytest.approx(1.02 * 0.99 - 1)            # 01-05(달력에 없음)은 01-06 에 복리
    assert (1 + out).prod() == pytest.approx((1 + r).prod())


def test_part1_pairs_on_same_dates():
    idx = pd.bdate_range("2010-01-04", "2024-10-31")
    rng = np.random.default_rng(1)
    common = rng.normal(0.0004, 0.01, len(idx))
    fr = {k: pd.Series(common + rng.normal(0, 0.002, len(idx)), index=idx) for k in ("mkt", "BIGHI", "ME5P5")}
    fr["rf"] = pd.Series(0.0, index=idx)
    # 새틀라이트 달력에서 French 날 하나를 빼고, French 에 없는 날 하나를 더한다
    sat_idx = idx.delete(100).union(pd.DatetimeIndex(["2012-07-07"]))
    sat = pd.Series(fr["BIGHI"].reindex(sat_idx).fillna(0.0).to_numpy(), index=sat_idx)
    p1 = mod.part1_stage(fr, {"gross": sat, "net": sat - 0.0001})
    al = p1["alignment"]
    assert al["sat_days_not_in_french"] == 1 and al["french_days_not_in_sat"] == 1
    st = p1["compare"]["full"]["gross_vs_BIGHI"]
    assert st["corr_daily"] > 0.9 and abs(st["cagr_diff"]) < 0.02
    assert p1["yearly"][0]["year"] == 2010 and p1["yearly"][-1]["year"] == 2024
    assert set(p1["compare"]) == {"full", "h1", "h2"}
    assert p1["compare"]["h1"]["gross_vs_BIGHI"]["end"] <= "2017-05-31" < p1["compare"]["h2"]["gross_vs_BIGHI"]["start"]
    assert p1["compare"]["full"]["gross_vs_BIGHI"]["end"] <= "2024-09-30"


def test_pair_stats_identical_series():
    idx = pd.bdate_range("2010-01-04", periods=400)
    a = pd.Series(np.random.default_rng(2).normal(0, 0.01, 400), index=idx)
    s = mod.pair_stats(a, a)
    assert s["cagr_diff"] == pytest.approx(0.0) and s["tracking_error"] == pytest.approx(0.0) and s["corr_daily"] == pytest.approx(1.0)


# ---------------------------------------------------------------- 자료 정리

def test_synthetic_french_weekday_calendar_and_gap_fill():
    fr = mod.synthetic_french()
    assert (fr["mkt"].index.dayofweek < 5).all()
    assert fr["weekend_rows_raw"] > 0 and fr["gaps_filled_zero"]["BIGHI"] == 1
    assert not fr["BIGHI"].loc["1927-07-01":].isna().any()


def test_smoke_resume_3_then_0(tmp_path):
    out, ck = tmp_path / "out", tmp_path / "ck"
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck), "--max-steps-per-run", "1"]) == 3
    assert not (out / "results.json").exists()
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck)]) == 0
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert all(res["smoke_coverage"].values())
    assert set(res["verdicts"]) == {"chosen_cell", "verdict"} and all(v.startswith("SMOKE_ONLY(") for v in res["verdicts"].values())
    assert (out / "results.json").stat().st_size < 200_000
    assert res["power"]["years"] == 41.0 and res["power"]["n_trials"] == 5
    assert "검정력" in (out / "REPORT.md").read_text(encoding="utf-8")
    assert math.isfinite(res["judged"]["metrics"]["w15"]["conf"]["cagr"])
