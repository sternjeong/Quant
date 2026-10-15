"""spy-champion-v1 (SPY 바탕 + 새틀라이트) 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

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
    spec = importlib.util.spec_from_file_location("spy_champion_v1", ROOT / "research/jobs/spy-champion-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "spy-champion-v1" in valid, invalid.get("spy-champion-v1")
    job = json.loads((ROOT / "research/jobs/spy-champion-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 5 and job["resumable"] is True and job["max_memory_mb"] <= 2500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"


def test_pre_registered_constants():
    assert mod.CANDIDATES == {"P1": (0.85, 0.15, 0.0), "P2": (0.80, 0.20, 0.0), "P3": (0.70, 0.30, 0.0),
                              "P4": (0.50, 0.30, 0.20), "P5": (0.40, 0.40, 0.20)}
    assert all(abs(sum(v) - 1) < 1e-12 for v in mod.CANDIDATES.values())
    assert mod.N_BOOT == 1000 and mod.BLOCK_DAYS == 126 and mod.BOOT_SEED == 20261016
    assert mod.MIN_DIFF_CHAMP == 0.010 and mod.CI_LOW_FLOOR == -0.005 and mod.SPY_MARGIN == 0.005
    assert mod.WINDOWS["judged"] == ("2010-01-04", "2024-09-30")
    assert mod.WINDOWS["h1"][1] == "2017-05-31" and mod.WINDOWS["h2"] == ("2017-06-01", "2024-09-30")
    assert mod.POWER_YEARS == 14.7 and mod.N_TRIALS == 5


def _prices(idx, rates):
    return pd.DataFrame({t: 100 * np.cumprod(np.full(len(idx), 1 + r)) for t, r in rates.items()}, index=idx)


def test_annual_only_rebalance_and_drift():
    idx = pd.bdate_range("2015-01-01", "2017-03-31")
    adj = _prices(idx, {"SPY": 0.001, "A": 0.0, "C": 0.0})
    sat = pd.DataFrame({"A": 1.0}, index=idx)
    core = pd.DataFrame({"C": 1.0}, index=idx)
    W, info = mod.sleeve_weights(idx, adj, [("spy", 0.5, pd.DataFrame({"SPY": 1.0}, index=idx)), ("sat", 0.3, sat),
                                            ("core", 0.2, core)])
    chg = W.diff().abs().sum(axis=1) > 1e-12
    trade_days = list(W.index[chg])
    assert all(d.month == 1 and d == W.index[(W.index.year == d.year) & (W.index.month == 1)][0] for d in trade_days)
    assert len(trade_days) == 2                     # 2016-01, 2017-01 (첫날 제외)
    assert W.iloc[0].to_dict() == pytest.approx({"SPY": 0.5, "A": 0.3, "C": 0.2}, rel=1e-7)
    jan16 = W.index[(W.index.year == 2016)][0]
    assert W.loc[jan16].to_dict() == pytest.approx({"SPY": 0.5, "A": 0.3, "C": 0.2}, rel=1e-7)
    assert info["drift_at_reset"][0] > 0.05           # SPY 가 오르며 표류했다가 1월에 되돌림


def test_satellite_reselection_stays_inside_sleeve():
    idx = pd.bdate_range("2015-01-01", "2015-12-31")
    adj = _prices(idx, {"SPY": 0.002, "A": 0.001, "B": 0.0, "D": 0.0})
    jul = idx[idx.month == 7][0]
    log = [{"date": str(idx[0].date()), "weights": {"A": 0.5, "B": 0.5}}, {"date": str(jul.date()), "weights": {"D": 1.0}}]
    inner = mod.inner_frame_from_log(idx, log)
    W, info = mod.sleeve_weights(idx, adj, [("spy", 0.85, pd.DataFrame({"SPY": 1.0}, index=idx)), ("sat", 0.15, inner)])
    before = W.loc[idx[idx < jul][-1]]
    # 7월 선정일 직전까지 실제 표류
    tr = adj.loc[:jul].pct_change().fillna(0.0)
    g = W.iloc[0] * (1 + tr).prod()
    g = g / g.sum()
    row = W.loc[jul]
    assert row["SPY"] == pytest.approx(g["SPY"], rel=1e-9)          # SPY 는 표류값 그대로(매매 없음)
    assert row["A"] == 0 and row["B"] == 0
    assert row["D"] == pytest.approx(g["A"] + g["B"], rel=1e-9)     # 새틀라이트 슬리브 크기만큼만 새 종목에
    assert row["SPY"] != pytest.approx(0.85, abs=1e-4)
    assert info["sleeve_trades"]["sat"] == 1 and info["sleeve_trades"]["spy"] == 0
    assert before["A"] == pytest.approx(0.075)


def test_reselection_with_same_picks_rebalances_inside_sleeve():
    idx = pd.bdate_range("2015-01-01", "2015-12-31")
    adj = _prices(idx, {"SPY": 0.0, "A": 0.002, "B": 0.0})
    jul = idx[idx.month == 7][0]
    log = [{"date": str(idx[0].date()), "weights": {"A": 0.5, "B": 0.5}}, {"date": str(jul.date()), "weights": {"A": 0.5, "B": 0.5}}]
    W, _ = mod.sleeve_weights(idx, adj, [("spy", 0.85, pd.DataFrame({"SPY": 1.0}, index=idx)),
                                         ("sat", 0.15, mod.inner_frame_from_log(idx, log))])
    assert W.loc[jul, "A"] == pytest.approx(W.loc[jul, "B"])


def _smoke_inputs():
    return mod._smoke_inputs(lambda s: None)


def test_champion_reference_equals_satellite_value_v1():
    inp = _smoke_inputs()
    sv = mod.SV._smoke_inputs(lambda s: None)
    a = mod.SV.build_weights(sv["core_w"], sv["logs"])["A"]
    W, _ = mod.build_all_weights(inp)
    ch = W[("CHAMP", "judged")]
    ref = a.loc[ch.index[0]:ch.index[-1]]
    ref = ref.loc[:, ref.abs().sum() > 0]
    pd.testing.assert_frame_equal(ch.sort_index(axis=1), ref.sort_index(axis=1))


@pytest.mark.parametrize("args,expect", [
    ((0.010, 0.001, 0.001, -0.2, -0.2, -0.0049), "PASS_FORWARD_CANDIDATE"),
    ((0.0099, 0.001, 0.001, -0.2, -0.2, 0.0), "FAIL"),
    ((0.02, 0.0, 0.01, -0.2, -0.3, 0.0), "FAIL"),
    ((0.02, 0.01, 0.01, -0.3001, -0.3, 0.0), "FAIL"),
    ((0.02, 0.01, 0.01, -0.3, -0.3, -0.005), "FAIL"),
    ((0.02, 0.01, float("nan"), -0.3, -0.3, 0.0), "NOT_EVALUABLE"),
])
def test_pass_rule_edges(args, expect):
    assert mod.decide(*args)[0] == expect


def test_noop_is_not_evaluable_and_beats_spy():
    assert mod.decide(0.05, 0.05, 0.05, -0.1, -0.2, 0.01, "same")[0] == "NOT_EVALUABLE"
    assert mod.beats_spy(0.005, 1e-9, 1e-9) is True
    assert mod.beats_spy(0.0049, 0.01, 0.01) is False
    assert mod.beats_spy(0.01, 0.0, 0.01) is False


def test_bootstrap_deterministic():
    rng = np.random.default_rng(1)
    a, b = rng.normal(0.0005, 0.01, 800), rng.normal(0.0003, 0.01, 800)
    x, y = mod.bootstrap_diff(a, b, 252), mod.bootstrap_diff(a, b, 252)
    assert len(x) == 1000 and np.array_equal(x, y)


def test_calendar_mdd_and_liq_cagr():
    idx = pd.to_datetime(["2019-12-31", "2020-01-02", "2020-03-01", "2020-12-31"])
    v = pd.Series([100, 110, 55, 120], index=idx)
    assert mod.calendar_mdd(v, 2020) == pytest.approx(-0.5)
    assert mod.calendar_mdd(v, 2021) is None
    assert mod.liq_cagr(200, 100, pd.Timestamp("2010-01-01"), pd.Timestamp("2012-01-01")) \
        == pytest.approx(math.sqrt(2) - 1, rel=5e-3)


def test_smoke_resume_3_then_0(tmp_path):
    out, ck = tmp_path / "o", tmp_path / "c"
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck), "--max-sims-per-run", "4"]) == 3
    assert not (out / "results.json").exists()
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck)]) == 0
    r = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert all(r["smoke_coverage"].values())
    assert set(r["verdicts"]) == set(mod.CANDIDATES)
    assert all(v.startswith("SMOKE_ONLY(") for v in r["verdicts"].values())
    assert (out / "results.json").stat().st_size < 200_000
    assert "생존편향" in (out / "REPORT.md").read_text(encoding="utf-8")
