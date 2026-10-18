"""research/jobs/contrib-reval-champion-v1 — 사전 등록 규칙·출처 연구와 같은 목표 비중(합성 자료)."""

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load():
    name = "contrib_reval_champion_v1"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "research/jobs/contrib-reval-champion-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "contrib-reval-champion-v1" in valid, invalid.get("contrib-reval-champion-v1")
    job = json.loads((ROOT / "research/jobs/contrib-reval-champion-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 22 and job["resumable"] is True and job["max_memory_mb"] <= 2500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"


def test_pre_registered_constants_and_scenarios():
    assert mod.N_TRIALS == len(mod.JUDGED) == 8 and "D1" not in mod.JUDGED and "SPY" not in mod.STRATEGIES
    assert (mod.MIN_SHARE_WIN, mod.MIN_MEDIAN_DIFF, mod.MIN_P10_DIFF, mod.MDD_TW_TOL) == (0.70, 0.005, -0.015, 0.05)
    assert mod.PRIMARY_SCENARIO == "B" and mod.PRIMARY_HORIZON == 5 and mod.DECISION_END == "2024-09-30"
    b, a, c, b10 = (mod.scenario_config(k) for k in ("B", "A", "C", "B10"))
    assert (b.initial_krw, b.monthly_contribution_krw) == (10_000_000, 150_000)
    assert (a.initial_krw, a.monthly_contribution_krw) == (10_000_000, 0.0)
    assert (c.initial_krw, c.monthly_contribution_krw) == (3_000_000, 150_000)
    assert (b10.initial_krw, b10.monthly_contribution_krw) == (100_000_000, 1_500_000)
    from core import tax_fx as tx
    d = tx.AccountConfig()
    assert all(x.contribution_policy == "underweight_first" and x.fee_rate == d.fee_rate and x.fx_spread == d.fx_spread
               for x in (a, b, c, b10))


def test_windows_judged_end_before_cutoff():
    cal = pd.bdate_range("2010-01-04", "2026-06-30")
    w = mod.split_windows(cal, 5, 1, "2010-01-01")
    assert w["judged"] and w["post"]
    assert all(e <= pd.Timestamp("2024-09-30") for _, e in w["judged"])
    assert all(e > pd.Timestamp("2024-09-30") for _, e in w["post"])
    assert w["judged"][0][0] == pd.Timestamp("2010-01-04")
    starts = [s for s, _ in w["judged"]]
    assert all((b.year * 12 + b.month) - (a.year * 12 + a.month) == 1 for a, b in zip(starts, starts[1:]))
    assert len(w["judged"]) == 117   # 2010-01 ~ 2019-09
    w14 = mod.split_windows(cal, 5, 1, "2014-01-02")
    assert w14["judged"][0][0] >= pd.Timestamp("2014-01-01")


def _s(**kw):
    base = {"n_windows": 100, "share_terminal_win": 0.70, "median_diff_irr": 0.005, "p10_diff_irr": -0.015,
            "median_strategy_mdd_tw": -0.30, "median_benchmark_mdd_tw": -0.25}
    base.update(kw)
    return base


@pytest.mark.parametrize("kw,expect", [
    ({}, "CONTRIB_BEATS_SPY"),
    ({"share_terminal_win": 0.69}, "FAIL_UNDERPOWERED"),
    ({"median_diff_irr": 0.0049}, "FAIL_UNDERPOWERED"),
    ({"p10_diff_irr": -0.0151}, "FAIL_UNDERPOWERED"),
    ({"median_strategy_mdd_tw": -0.3001}, "FAIL_UNDERPOWERED"),
    ({"median_diff_irr": -0.01, "share_terminal_win": 0.2}, "FAIL"),
])
def test_verdict_edges(kw, expect):
    from core import research_power as rp
    power = rp.power_report(14.7, 8)
    assert mod.decide(_s(**kw), power)[0] == expect
    assert mod.decide(_s(**kw))[0] == ("CONTRIB_BEATS_SPY" if expect == "CONTRIB_BEATS_SPY" else "FAIL")


def test_not_evaluable():
    assert mod.decide(_s(), noop="x")[0] == "NOT_EVALUABLE"
    assert mod.decide({"n_windows": 0})[0] == "NOT_EVALUABLE"
    assert mod.decide(_s(p10_diff_irr=float("nan")))[0] == "NOT_EVALUABLE"


@pytest.fixture(scope="module")
def smoke_base():
    return mod._smoke_base(lambda s: None)


def test_frames_equal_source_jobs(smoke_base, monkeypatch):
    sc = mod.SC
    # 합성 달력에는 2010-01-01(평일)이 있어 CHAMP 축이 그날 시작한다. 실자료에서는 첫 거래일 = 2010-01-04 = 출처의 판정 구간 시작.
    # 같은 시작일로 맞춰 비교한다(출처 함수의 구간 시작만 바꿈).
    monkeypatch.setitem(sc.WINDOWS, "judged", (str(smoke_base["frames"]["CHAMP"].index[0].date()), sc.WINDOWS["judged"][1]))
    src = sc._smoke_inputs(lambda s: None)
    champ = sc.champion_weights(src["core_w"], src["log"])
    W = smoke_base["frames"]
    pd.testing.assert_frame_equal(W["CHAMP"], champ, check_freq=False)
    ref, _ = sc.build_all_weights(src)
    for p in ("P1", "P3", "P4"):
        r = ref[(p, "judged")]
        mine = W[p].reindex(r.index)[r.columns]
        pd.testing.assert_frame_equal(mine, r, check_freq=False, atol=1e-12)


def test_champ_k6_and_p1st_subsleeve_a_match_sat_buffer(smoke_base):
    data, _ = mod._smoke_data()
    buf = mod.BUF
    d6, ps6, ex6 = buf.score_inputs(data)
    k6 = buf.build_schedules(d6, ps6, ex6, {"K6_H6": buf.VARIANT_RULES["K6_H6"]})["K6_H6"]
    sch = smoke_base["schedules"]
    ref = [(str(pd.Timestamp(r["date"]).date()), r["picks"]) for r in k6 if pd.Timestamp(r["date"]) >= pd.Timestamp("2010-01-01")]
    assert [(r["date"], r["picks"]) for r in sch["K6_H6"] if r["date"] >= "2010-01-01"] == ref
    # 1·7월 하위 슬리브(ST_A)는 같은 K6 규칙 → sat-buffer K6_H6 와 같은 일정
    assert [(r["date"], r["picks"]) for r in sch["ST_A"]] == ref
    assert all(pd.Timestamp(r["date"]).month in (1, 3, 9) for r in sch["ST_B"])
    assert sch["ST_C"][0]["date"] == sch["ST_A"][0]["date"]      # 셋 다 첫 달에 처음 고른다
    w = smoke_base["frames"]["P1ST"]
    assert abs(w.loc[w.index[0], "SPY"] - 0.85) < 1e-9


def test_compact_and_report_helpers():
    from core import rolling_eval as re_
    rows = [{"start": "2010-01-04", "end": "2015-01-02", "years": 5.0, "diff_irr": 0.01, "terminal_ratio": 1.05, "win": True,
             "diff_terminal_krw": 1e5,
             "strategy": {"irr": 0.1, "mdd_tw": -0.2, "mdd_mw": -0.15, "capital_gains_tax_krw": 1e5,
                          "unpaid_tax_if_sold_now_krw": 0.0, "total_contributed_krw": 1.8e7, "terminal_krw": 3e7},
             "benchmark": {"irr": 0.09, "mdd_tw": -0.2, "mdd_mw": -0.15, "capital_gains_tax_krw": 0.0,
                           "unpaid_tax_if_sold_now_krw": 0.0, "total_contributed_krw": 1.8e7, "terminal_krw": 2.9e7}}]
    c = mod.compact(re_.summarize(rows, 5), rows)
    assert c["n_windows"] == 1 and c["median_strategy_cgt_krw"] == 1e5 and "worst_window" in c
    assert mod._rnd({"a": float("nan"), "b": 1234.56, "c": 0.12345678}) == {"a": None, "b": 1235, "c": 0.123457}
