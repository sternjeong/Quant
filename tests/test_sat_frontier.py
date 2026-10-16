"""sat-frontier-v1 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("sat_frontier_v1", ROOT / "research/jobs/sat-frontier-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()
SPY = {"ann": 0.10, "mdd": -0.20, "worst12": -0.15}


def test_job_contract():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "sat-frontier-v1" in valid, invalid.get("sat-frontier-v1")
    job = json.loads((ROOT / "research/jobs/sat-frontier-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 14 and job["resumable"] is True and job["max_memory_mb"] <= 2500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"


def test_constants():
    assert len(mod.CELLS) == 10 and mod.N_TRIALS == 10 and mod.POWER_YEARS == 7.3
    assert mod.W_SATS == (0.15, 0.20, 0.30, 0.40, 0.50) and mod.BOOT_SEED == 20261023
    assert mod.WINDOWS["sel"] == ("2010-01-04", "2017-05-31") and mod.WINDOWS["conf"] == ("2017-06-01", "2024-09-30")
    assert mod.cell_params("ST_30") == ("ST", 0.30)


def _m(ann, mdd=-0.10, w12=-0.10):
    return {"ann": ann, "mdd": mdd, "worst12": w12}


def test_selection_uses_only_selection_metrics_and_limits():
    sel = {"none_15": _m(0.11), "ST_15": _m(0.12), "none_50": _m(0.30, mdd=-0.25), "ST_50": _m(0.20, w12=-0.21)}
    # none_50 fails A, ST_50 fails B(-0.21 < -0.15-0.05) → ST_15
    assert mod.select_cell(sel, SPY) == "ST_15"
    # B edge: exactly SPY worst − 5pp is allowed
    sel["ST_50"] = _m(0.20, w12=-0.20)
    assert mod.select_cell(sel, SPY) == "ST_50"
    assert mod.select_cell({"none_15": _m(0.2, mdd=-0.3)}, SPY) is None
    import inspect
    assert list(inspect.signature(mod.select_cell).parameters) == ["sel_metrics", "spy_sel"]


def test_tie_breaking():
    sel = {"ST_20": _m(0.12), "none_20": _m(0.12), "ST_15": _m(0.12)}
    assert mod.select_cell(sel, SPY) == "ST_15"
    sel = {"ST_20": _m(0.12), "none_20": _m(0.12)}
    assert mod.select_cell(sel, SPY) == "none_20"


def test_stability_edges():
    assert mod.stable(_m(0, mdd=-0.20, w12=-0.20), SPY) == (True, True)
    assert mod.stable(_m(0, mdd=-0.2001, w12=-0.2001), SPY) == (False, False)


def test_pass_rule_edges():
    assert mod.decide(0.001, True, True, -0.004)[0] == mod.PASS
    assert mod.decide(0.0, True, True, -0.004)[0] == mod.FAIL
    assert mod.decide(0.01, True, True, -0.005)[0] == mod.FAIL
    assert mod.decide(0.01, False, True, 0.0)[1] == ["A_mdd_not_worse_than_spy"]
    assert mod.decide(0.01, True, False, 0.0)[1] == ["B_worst12m_ge_spy_minus_5pp"]
    assert mod.decide(0.01, True, True, 0.0, noop="x")[0] == mod.NOT_EVALUABLE
    assert mod.decide(float("nan"), True, True, 0.0)[0] == mod.NOT_EVALUABLE
    assert mod.haircut_flag(0.0001) == mod.ROBUST and mod.haircut_flag(0.0) == mod.NOT_ROBUST
    assert mod.haircut_flag(None) == mod.NA


def test_break_even():
    assert abs(mod.rp_break_even([0, 1, 2, 3], [0.02, 0.01, 0.0, -0.01]) - 2.0) < 1e-12
    assert abs(mod.rp_break_even([0, 1, 2, 3], [0.015, 0.005, -0.005, -0.015]) - 1.5) < 1e-12
    assert mod.rp_break_even([0, 1, 2, 3], [0.04, 0.03, 0.02, 0.01]) is None


def test_worst_12m_metric():
    idx = pd.bdate_range("2020-01-01", periods=600)
    v = pd.Series(np.linspace(100, 200, 600), index=idx)
    v.iloc[300:] *= 0.7
    r = (v / v.shift(252) - 1).dropna()
    assert mod.worst_rolling(v) == float(r.min())
    assert math.isnan(mod.worst_rolling(v.iloc[:100]))
    assert abs(mod.mdd(pd.Series([1.0, 2.0, 1.0, 3.0])) + 0.5) < 1e-12


def test_haircut_math():
    idx = pd.bdate_range("2020-01-01", periods=300)
    adj = pd.DataFrame({"SPY": np.linspace(100, 110, 300), "AAA": np.full(300, 50.0)}, index=idx)
    close = adj.copy()
    c, a = mod.haircut_prices(close, adj, 0.0252)
    r = a["AAA"].pct_change().dropna()
    assert np.allclose(r, -0.0001)
    assert a["SPY"].equals(adj["SPY"]) and c["SPY"].equals(close["SPY"])
    assert np.allclose(c["AAA"] / a["AAA"], 1.0)
    assert abs(a["AAA"].iloc[252] / a["AAA"].iloc[0] - (1 - 0.0001) ** 252) < 1e-12


def _scores(dates, ranking_by_date):
    return {d: {t: float(len(r) - i) for i, t in enumerate(r)} for d, r in zip(dates, ranking_by_date)}


def test_st_sub_sleeve_calendars_and_buffer():
    dates = [pd.Timestamp(f"2010-{m:02d}-01") for m in (1, 3, 5, 7, 9, 11)] + [pd.Timestamp("2011-01-03")]
    base = list("ABCDEFGHIJ")
    rankings = [base] * len(dates)
    # 2010-07: A,B,C 가 4~6위로 내려감(버퍼 K6 안 → 1·7월 슬리브는 유지)
    rankings[3] = list("DEFABCGHIJ")
    # 2011-01: C 가 7위로(버퍼 밖 → 교체), A,B 는 상위 6 안
    rankings[6] = list("DEFABGCHIJ")
    sch = mod.st_schedules(dates, _scores(dates, rankings), lambda d, t: None)
    months = {n: [r["date"].month for r in sch[n]] for n, _ in mod.ST_SLEEVES}
    assert months == {"S17": [1, 7, 1], "S39": [3, 9], "S511": [5, 11]}
    s17 = sch["S17"]
    assert s17[0]["picks"] == ["A", "B", "C"]
    assert sorted(s17[1]["picks"]) == ["A", "B", "C"] and sorted(s17[1]["kept"]) == ["A", "B", "C"]
    assert sorted(s17[2]["kept"]) == ["A", "B"] and "C" not in s17[2]["picks"] and "D" in s17[2]["picks"]
    # 9월 슬리브(3월 A,B,C 보유)도 같은 규칙
    assert sorted(sch["S39"][1]["picks"]) == ["A", "B", "C"]


def _synthetic(n=800, seed=3):
    idx = pd.bdate_range("2010-01-04", periods=n)
    rng = np.random.default_rng(seed)
    cols = ["SPY", "AAA", "BBB", "CCC", "DDD"]
    adj = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, (n, len(cols))), axis=0)), index=idx, columns=cols)
    jul = idx[(idx.month == 7)][0]
    jan = idx[(idx.month == 1) & (idx.year == 2011)][0]
    log = [{"date": str(idx[0].date()), "weights": {"AAA": 1 / 3, "BBB": 1 / 3, "CCC": 1 / 3}},
           {"date": str(jul.date()), "weights": {"BBB": 1 / 3, "CCC": 1 / 3, "DDD": 1 / 3}},
           {"date": str(jan.date()), "weights": {"AAA": 0.5, "DDD": 0.5}}]
    return idx, adj, log


def test_none_15_equals_spy_champion_p1():
    idx, adj, log = _synthetic()
    w, _ = mod.cell_weights("none_15", idx, {"none": log}, adj)
    sat_inner = mod.SC.inner_frame_from_log(idx, log)
    p1, _ = mod.SC.candidate_weights("P1", idx, pd.DataFrame(index=idx), sat_inner, adj)
    pd.testing.assert_frame_equal(w, p1)


def test_st_cell_splits_into_thirds_and_resets_in_january():
    idx, adj, log = _synthetic()
    logs = {"S17": log, "S39": [{"date": str(idx[40].date()), "weights": {"AAA": 1.0}}],
            "S511": [{"date": str(idx[80].date()), "weights": {"BBB": 0.5, "CCC": 0.5}}]}
    w, info = mod.cell_weights("ST_30", idx, logs, adj)
    assert abs(w.iloc[0].sum() - (0.70 + 0.10)) < 1e-9          # 다른 두 하위 슬리브는 첫 재선정 전 현금
    jan = idx[(idx.month == 1) & (idx.year == 2011)][0]
    row = w.loc[jan]
    assert abs(row["SPY"] - 0.70) < 1e-6 and abs(row.sum() - 1.0) < 1e-6
    assert set(info["sleeve_trades"]) == {"spy", "S17", "S39", "S511"}
