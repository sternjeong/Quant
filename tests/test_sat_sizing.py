"""sat-sizing-v1 (새틀라이트 3종목 사이징) 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

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
    spec = importlib.util.spec_from_file_location("sat_sizing_v1", ROOT / "research/jobs/sat-sizing-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()
cs = mod.cs


def _frames(n=6, days=900, seed=1, end=None):
    end = end or pd.Timestamp("2015-12-31")
    idx = pd.bdate_range(end=end, periods=days)
    rng = np.random.default_rng(seed)
    out = {}
    for i in range(n):
        vol = 0.005 + 0.01 * i
        c = 50 * np.exp(np.cumsum(rng.normal(0.0004, vol, len(idx))))
        out[f"S{i:02d}"] = pd.DataFrame({"Close": c}, index=idx)
    return out


# ---- 계약·상수 -------------------------------------------------------------------------------------------

def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "sat-sizing-v1" in valid, invalid.get("sat-sizing-v1")
    job = json.loads((ROOT / "research/jobs/sat-sizing-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 9 and job["resumable"] is True and job["max_memory_mb"] <= 2500
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert (ROOT / "research/jobs/sat-sizing-v1/SPEC.md").exists()


def test_pre_registered_constants():
    assert mod.CAP == 0.40 and mod.VOL_LB == {"Z1": 20, "Z2": 63}
    assert (mod.KELLY_LOOKBACK_YEARS, mod.KELLY_SAMPLE_SIZE, mod.KELLY_MIN_TRADES, mod.KELLY_SAFETY) == (5, 120, 20, 0.5)
    assert mod.JUDGED == ("Z1", "Z2", "Z3") and mod.N_TRIALS == 3 and mod.POWER_YEARS == 14.7
    assert mod.N_BOOT == 1000 and mod.BLOCK_DAYS == 126 and mod.BOOT_SEED == 20261020
    assert mod.CI_LOW_FLOOR == -0.005 and mod.MDD_TOL == 0.02 and mod.SAT_WEIGHT == 0.15
    assert mod.DECISION_END == "2024-09-30" and mod.HALF_SPLIT == "2017-05-31"


# ---- 변동성 역가중 ----------------------------------------------------------------------------------------

def test_z1_equals_live_inverse_vol_weights():
    fr = _frames()
    picks = ["S00", "S02", "S04"]
    d = pd.Timestamp("2015-07-01")
    w, fb = mod.inverse_vol_sleeve(fr, picks, d, 20)
    live = cs._inverse_vol_weights({t: fr[t][fr[t].index < d] for t in picks}, picks, cs.SATELLITE_SIZING_VOL_LOOKBACK_DAYS)
    assert not fb and w == live and w["S00"] > w["S04"]


def test_inverse_vol_uses_only_past_prices():
    fr = _frames()
    picks = ["S01", "S03", "S05"]
    d = pd.Timestamp("2015-07-01")
    w1, _ = mod.inverse_vol_sleeve(fr, picks, d, 63)
    fr2 = {t: df.copy() for t, df in fr.items()}
    for df in fr2.values():
        df.loc[df.index >= d, "Close"] *= np.linspace(1, 5, int((df.index >= d).sum()))
    w2, _ = mod.inverse_vol_sleeve(fr2, picks, d, 63)
    assert w1 == w2


def test_cap_applied_and_sum_to_one():
    fr = _frames()
    picks = ["S00", "S04", "S05"]       # S00 은 변동성이 아주 낮아 상한에 걸린다
    w, _ = mod.inverse_vol_sleeve(fr, picks, pd.Timestamp("2015-07-01"), 20)
    assert abs(sum(w.values()) - 1.0) < 1e-3
    # 라이브 함수는 상한을 한 번 자르고 다시 정규화 — 상한에 걸린 종목은 여전히 가장 큰 비중이지만 자르기 전보다 작다
    hist = {t: fr[t][fr[t].index < pd.Timestamp("2015-07-01")] for t in picks}
    uncapped = cs._inverse_vol_weights(hist, picks, 20, 1.0)
    assert uncapped["S00"] > mod.CAP and w["S00"] < uncapped["S00"]
    # 상한 이하로 이미 고른 경우엔 그대로
    idx = pd.bdate_range(end="2015-06-30", periods=200)
    rng = np.random.default_rng(4)
    close = {t: pd.DataFrame({"Close": 50 * np.exp(np.cumsum(rng.normal(0, v, len(idx))))}, index=idx)
             for t, v in (("P", 0.020), ("Q", 0.022), ("R", 0.024))}
    w2, _ = mod.inverse_vol_sleeve(close, ["P", "Q", "R"], pd.Timestamp("2015-07-01"), 63)
    un2 = cs._inverse_vol_weights(close, ["P", "Q", "R"], 63, 1.0)
    assert max(un2.values()) <= mod.CAP and w2 == un2


def test_inverse_vol_fallback_equal():
    fr = _frames()
    assert mod.inverse_vol_sleeve(fr, ["S00"], pd.Timestamp("2015-07-01"), 20) == ({"S00": 1.0}, True)
    w, fb = mod.inverse_vol_sleeve(fr, ["X1", "X2", "S00"], pd.Timestamp("2015-07-01"), 20)
    assert fb and w == {"X1": 1 / 3, "X2": 1 / 3, "S00": 1 / 3}


# ---- Kelly --------------------------------------------------------------------------------------------

def _trend_closes(n=8, seed=2, end="2015-12-31", years=7):
    idx = pd.bdate_range(end=end, periods=252 * years)
    rng = np.random.default_rng(seed)
    return {f"K{i:02d}": pd.Series(50 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, len(idx)))), index=idx) for i in range(n)}


def test_kelly_matches_live_function(monkeypatch):
    today = pd.Timestamp.today().normalize()
    closes = _trend_closes(n=10, end=today - pd.Timedelta(days=1))
    universe = ["SPY", "XLK"] + sorted(closes)
    monkeypatch.setattr(cs, "get_universe", lambda: pd.DataFrame({"Symbol": universe}))
    monkeypatch.setattr(cs, "get_multiple_price_history",
                        lambda tick, start, interval="1d": {t: pd.DataFrame({"Close": closes[t][closes[t].index >= pd.Timestamp(start)]})
                                                            for t in tick if t in closes})
    live = cs.compute_satellite_kelly_exposure()
    pit = mod.kelly_exposure_pit(closes, mod.kelly_sample(universe), today)
    assert live["trade_count"] == pit["trade_count"] >= 20
    assert live["recommended_fraction"] == pytest.approx(pit["recommended_fraction"])
    assert live["full_kelly"] == pytest.approx(pit["full_kelly"])


def test_kelly_pit_ignores_future():
    closes = _trend_closes()
    d = pd.Timestamp("2013-01-02")
    a = mod.kelly_exposure_pit(closes, sorted(closes), d)
    fut = {t: s.where(s.index < d, s * 3.0) for t, s in closes.items()}
    b = mod.kelly_exposure_pit(fut, sorted(closes), d)
    assert a == b and a["applied"]


def test_kelly_fallback_under_min_trades():
    closes = _trend_closes(n=1, years=2)
    r = mod.kelly_exposure_pit(closes, sorted(closes), pd.Timestamp("2015-12-31"))
    assert r["trade_count"] < 20 and not r["applied"] and r["recommended_fraction"] == 1.0
    assert mod.kelly_exposure_pit({}, [], pd.Timestamp("2015-12-31"))["recommended_fraction"] == 1.0


def test_kelly_sample_excludes_core_and_caps_120():
    members = [f"A{i:03d}" for i in range(200)] + ["SPY", "XLK", "TLT"]
    s = mod.kelly_sample(members)
    assert len(s) == 120 and s == sorted(s) and not ({"SPY", "XLK", "TLT"} & set(s))


def test_kelly_sleeve_sums_to_one():
    w = mod.kelly_sleeve(["A", "B", "C"], 0.3)
    assert sum(w.values()) == pytest.approx(1.0) and w["BIL"] == pytest.approx(0.7) and w["A"] == pytest.approx(0.1)
    assert mod.kelly_sleeve(["A", "B", "C"], 1.0) == {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}


def test_build_logs_weights_sum_to_sleeve():
    fr = _frames()
    sched = [("2015-01-02", ["S00", "S02", "S04"]), ("2015-07-01", ["S01", "S03", "S05"])]
    kelly = {"2015-01-02": {"recommended_fraction": 0.4, "applied": True, "trade_count": 50},
             "2015-07-01": {"recommended_fraction": 1.0, "applied": False, "trade_count": 3}}
    logs, diag = mod.build_logs(sched, fr, kelly)
    for v in mod.VARIANTS:
        for r in logs[v]:
            assert sum(r["weights"].values()) == pytest.approx(1.0, abs=1e-3)
    assert diag["Z3"][1]["fallback"] and not diag["Z3"][0]["fallback"]
    s = mod.diag_summary(diag, pd.Timestamp("2016-01-01"))
    assert s["Z0"]["mean_spread"] == 0 and s["Z1"]["mean_spread"] > 0 and s["Z3"]["n_fallback"] == 1


# ---- Z0 = satellite-value-v1 챔피언 ---------------------------------------------------------------------

def test_z0_equals_satellite_value_champion():
    from core import satellite_lab as sl

    pp, poolp = sl.synthetic_providers(n_tickers=30, start="2008-01-01", end="2013-12-31", seed=3)
    pool = mod.SV._pool_wrapper(poolp, date.fromisoformat(mod.START))
    data = sl.build_data({"champion40"}, start="2009-12-01", end="2013-12-31", pool_provider=pool, price_provider=pp)
    sched = mod._schedule(data)
    spec, signal, params = mod.SV._incumbent()
    ref_log = mod.SV.schedule_to_log(sl.run_variant(spec, params, signal, data)["schedule"])
    logs, _ = mod.build_logs(sched, {}, {})
    assert logs["Z0"] == ref_log
    core = pd.DataFrame(0.0, index=data.trading_days, columns=["C1"])
    a = mod.SV.build_weights(core, {"A": ref_log, "A2": ref_log})["A"]
    b = mod.tx.champion_weights(core, logs["Z0"], mod.SAT_WEIGHT)
    pd.testing.assert_frame_equal(a, b)


# ---- 판정 ----------------------------------------------------------------------------------------------

def test_pass_rule_edges():
    ok = dict(diff=0.001, h1=0.001, h2=0.001, sharpe_v=0.81, sharpe_0=0.80, mdd_v=-0.20, mdd_0=-0.19, ci_low=-0.004)
    assert mod.decide(**ok) == mod.PASS
    assert mod.decide(**{**ok, "diff": 0.0}) == mod.FAIL
    assert mod.decide(**{**ok, "h1": 0.0}) == mod.FAIL
    assert mod.decide(**{**ok, "h2": -0.001}) == mod.FAIL
    assert mod.decide(**{**ok, "sharpe_v": 0.80}) == mod.FAIL
    assert mod.decide(**{**ok, "mdd_v": -0.2101}) == mod.FAIL
    assert mod.decide(**{**ok, "mdd_v": -0.2099}) == mod.PASS
    assert mod.decide(**{**ok, "ci_low": -0.005}) == mod.FAIL
    assert mod.decide(**{**ok, "ci_low": float("nan")}) == mod.NOT_EVALUABLE
    assert mod.decide(**ok, noop="same") == mod.NOT_EVALUABLE
    pw = mod.rp.power_report(14.7, 3)
    assert mod.decide(**{**ok, "diff": -0.01}, observed_ir=0.1, power=pw) in ("FAIL", "FAIL_UNDERPOWERED")


def test_bootstrap_deterministic():
    rng = np.random.default_rng(0)
    a, b = rng.normal(0.0004, 0.01, 800), rng.normal(0.0003, 0.01, 800)
    x, y = mod.block_bootstrap_diff(a, b, 252.0), mod.block_bootstrap_diff(a, b, 252.0)
    assert len(x) == 1000 and np.array_equal(x, y)


def test_smoke_resume(tmp_path):
    out, ck = tmp_path / "o", tmp_path / "c"
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck), "--max-steps-per-run", "2"]) == 3
    assert not (out / "results.json").exists()
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck)]) == 0
    r = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert set(r["verdicts"]) == set(mod.JUDGED) and all(v.startswith("SMOKE_ONLY(") for v in r["verdicts"].values())
    assert all(r["smoke_coverage"].values())
    assert (out / "results.json").stat().st_size < 200_000
    assert "power" in r and "스모크" in (out / "REPORT.md").read_text(encoding="utf-8")
