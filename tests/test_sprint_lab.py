"""2주 스프린트(core/sprint_lab.py)·매매 실행 R&D(core/execution_lab.py) — 과적합 측정, 코어 매도 규칙, 실행 규칙, 작업 정의."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core import execution_lab as xl
from core import sprint_lab as sp

ROOT = Path(__file__).resolve().parent.parent


def test_pbo_high_for_pure_noise_low_for_real_edge():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.01, (800, 40))
    assert sp.cscv_pbo(noise)["pbo"] > 0.3
    edge = noise.copy()
    edge[:, 0] += 0.004  # 한 설정만 진짜로 낫다
    assert sp.cscv_pbo(edge)["pbo"] < 0.05


def test_finalize_returns_family_keeps_current_when_noise():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2012-01-02", periods=1500)
    names = ["inc"] + [f"c{i}" for i in range(30)]
    mat = rng.normal(0.0003, 0.01, (len(idx), len(names)))
    res = sp.finalize_returns_family(names, mat, idx, idx[-1] - pd.DateOffset(years=2), "inc")
    assert res["verdict"] == "KEEP_CURRENT" and res["n_configs"] == 31 and len(res["top10"]) == 10
    json.dumps(res, default=str)


def test_finalize_returns_family_can_pick_a_real_winner():
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2010-01-04", periods=2600)
    names = ["inc"] + [f"c{i}" for i in range(20)]
    mat = rng.normal(0.0002, 0.01, (len(idx), len(names)))
    mat[:, 5] = mat[:, 0] + 0.0015 + rng.normal(0, 0.002, len(idx))  # 현 규칙 + 꾸준한 초과
    res = sp.finalize_returns_family(names, mat, idx, idx[-1] - pd.DateOffset(years=2), "inc")
    assert res["winner"] == "c4" or res["winner"] == names[5]
    assert res["verdict"] == "CANDIDATE", res["reasons"]


def test_core_exit_trailing_stop_moves_to_cash():
    idx = pd.bdate_range("2021-01-04", periods=40)
    closes = pd.DataFrame({"A": np.r_[np.linspace(100, 110, 10), np.linspace(110, 90, 30)], "B": 100.0}, index=idx)
    w = pd.DataFrame({"A": 0.5, "B": 0.3, "BIL": 0.2}, index=idx)
    spy = pd.Series(100.0, index=idx)
    out = sp.apply_core_exits(w, closes, spy, {"kind": "trail", "p": 0.10, "freq": "daily"})
    assert out["A"].iloc[-1] == 0.0 and out["BIL"].iloc[-1] == pytest.approx(0.7)
    first_zero = out.index[out["A"] == 0.0][0]
    prev = closes["A"].shift(1).loc[first_zero]
    assert prev <= 110 * 0.9 + 1e-9  # 전날 종가로 판단(미래 정보 없음)
    assert (out.sum(axis=1).round(9) == 1.0).all()
    assert sp.apply_core_exits(w, closes, spy, {"kind": "none"}).equals(w)


def test_core_exit_rules_and_configs_are_unique():
    names = [n for n, _ in sp.core_exit_rules()]
    assert len(names) == len(set(names)) and names[0] == "none"
    cfgs = [n for n, _ in sp.core_configs()]
    assert len(cfgs) == len(set(cfgs)) and sp.CORE_INCUMBENT in cfgs
    sats = [sp.satellite_config_name(c) for c in sp.satellite_configs()]
    assert len(sats) == len(set(sats)) and sp.SATELLITE_INCUMBENT in sats and len(sats) > 900


def _ohlc():
    idx = pd.bdate_range("2022-01-03", periods=40)
    c = np.full(40, 100.0)
    df = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Adj Close": c}, index=idx)
    df.loc[idx[2], "Low"] = 97.5  # 2일째 저가 −2.5%
    return df


def test_execute_param_limit_fill_and_fallback():
    df = _ohlc()
    f = xl.adjusted(df).to_numpy()
    assert sp.execute_param(df, 0, "buy", {"kind": "limit", "pct": 0.02, "days": 5}, f) == pytest.approx(98.0)
    assert sp.execute_param(df, 0, "buy", {"kind": "limit", "pct": 0.05, "days": 3}, f) == pytest.approx(100.0)  # 안 채워짐 → 3일째 종가
    assert sp.execute_param(df, 0, "sell", {"kind": "base"}, f) == pytest.approx(100.0)
    assert sp.execute_param(df, 30, "buy", {"kind": "next_open"}, f) is None  # 뒤 데이터 부족
    names = [n for n, _ in sp.execution_rules()]
    assert names[0] == "base" and len(names) == len(set(names))


def test_execution_lab_trades_and_take_profit():
    idx = pd.bdate_range("2021-01-04", periods=6)
    w = pd.DataFrame({"A": [0, .5, .5, .5, 0, 0], "BIL": [0, .5, .5, .5, 1, 1]}, index=idx, dtype=float)
    tr = xl.core_trades(w, 0.85)
    assert [(t["ticker"], t["side"]) for t in tr] == [("A", "buy"), ("A", "sell")]
    sat = xl.satellite_trades([("2021-01-04", ["X", "Y"]), ("2021-07-01", ["Y", "Z"])], 0.15)
    assert {(t["ticker"], t["side"]) for t in sat} == {("X", "buy"), ("Y", "buy"), ("Z", "buy"), ("X", "sell")}
    px = pd.DataFrame({"Close": [100, 125, 90, 80.0]}, index=pd.bdate_range("2021-01-04", periods=4))
    assert xl.take_profit_improvement(px, px.index[0], px.index[-1], 0.20) == pytest.approx(1.25 / 0.80 - 1)


@pytest.mark.parametrize("job_id", ["exec-rnd-v1", "sprint-2w", "tech-rnd-v1", "info-rnd-v1"])
def test_job_definitions_valid(job_id):
    from core import research_jobs as rj

    data = json.loads((ROOT / "research/jobs" / job_id / "job.json").read_text(encoding="utf-8"))
    job, err = rj.validate_job(data, job_id, ROOT)
    assert job is not None, err


def test_exec_rnd_smoke(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "research/jobs/exec-rnd-v1/run.py"), "--smoke",
                        "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-1500:]
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert res["smoke"] and len(res["verdicts"]) == 26


@pytest.mark.parametrize("job_id,expect", [("info-rnd-v1", {"A_crash_filters", "B_crypto"}), ("tech-rnd-v1", {"standalone", "synergy"})])
def test_research_job_smokes(tmp_path, job_id, expect):
    p = subprocess.run([sys.executable, str(ROOT / "research/jobs" / job_id / "run.py"), "--smoke",
                        "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-1500:]
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert res["smoke"] and set(res["verdicts"]) == expect


def test_technical_rules_have_no_lookahead():
    from core import technical_lab as tl

    idx = pd.bdate_range("2019-01-01", periods=400)
    rng = np.random.default_rng(3)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, len(idx))))
    df = pd.DataFrame({"Open": c * 0.999, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6 * (1 + rng.random(len(idx)))}, index=idx)
    cut = 300
    for name, kind, p in tl.rule_grid():
        full = tl.rule_position(df, kind, p)
        head = tl.rule_position(df.iloc[:cut], kind, p)
        assert np.allclose(full.iloc[:cut].to_numpy(), head.to_numpy(), equal_nan=True), name  # 뒤 데이터가 앞 포지션을 바꾸지 않는다
