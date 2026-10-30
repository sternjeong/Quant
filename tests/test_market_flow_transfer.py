"""research/jobs/market-flow-transfer-v1 — 판정 로직과 실행 계약을 합성 자료로 검증한다(네트워크 없음)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "research/jobs/market-flow-transfer-v1"

_spec = importlib.util.spec_from_file_location("mft_run", JOB / "run.py")
mft = importlib.util.module_from_spec(_spec)
sys.modules["mft_run"] = mft
_spec.loader.exec_module(mft)


def _world(effect: float, seed: int = 3, start="1950-01-02", end="2007-12-31") -> pd.DataFrame:
    """BusEq 가 21행 하위 10%로 빠진 뒤 21행 동안 TARGET 만 `effect` 만큼 더 오르게 심는다. 1967 전·후 모두 에피소드가 충분하다."""
    idx = pd.bdate_range(start, end)
    n = len(idx)
    rng = np.random.default_rng(seed)
    src_r = rng.normal(0.0003, 0.012, n)
    tgt_r = rng.normal(0.0003, 0.008, n)
    oth_r = rng.normal(0.0003, 0.008, n)
    mkt_r = rng.normal(0.0003, 0.008, n)
    s = pd.Series(100 * np.cumprod(1 + src_r), index=idx)
    ret21 = s / s.shift(21) - 1
    thr = ret21.expanding(min_periods=mft.MIN_HISTORY // 2).quantile(mft.QUANTILE)
    trig = ((ret21 <= thr) & thr.notna()).to_numpy()
    last = -10**9
    for i in np.flatnonzero(trig):
        if i - last >= 21 and i + 21 < n:
            tgt_r[i + 1:i + 22] += effect / 21
            last = i
    return pd.DataFrame({"BusEq": s.to_numpy(), "TARGET": 100 * np.cumprod(1 + tgt_r), "OTHER": 100 * np.cumprod(1 + oth_r),
                         "MKT": 100 * np.cumprod(1 + mkt_r)}, index=idx)


def test_planted_effect_passes_and_null_does_not():
    planted = mft.run_primary(_world(effect=0.02), "BusEq")
    assert planted["targets"]["TARGET"]["verdict"] == mft.PASS and planted["verdict"] == mft.PASS
    assert planted["targets"]["OTHER"]["verdict"] == mft.FAIL
    for seed in range(4):
        null = mft.run_primary(_world(effect=0.0, seed=seed), "BusEq")
        assert null["verdict"] != mft.PASS and null["passed"] == []


def test_effect_below_economic_floor_fails_even_if_significant():
    res = mft.run_primary(_world(effect=0.0015), "BusEq")  # 21행당 0.15%p < 0.30%p
    t = res["targets"]["TARGET"]
    assert t["checks"]["b"] is False and t["verdict"] == mft.FAIL


def test_not_evaluable_when_source_never_triggers_enough():
    short = _world(effect=0.0, start="2006-01-02", end="2007-12-31")  # 504행 이력 뒤 에피소드 5건 미만
    assert mft.run_primary(short, "BusEq")["verdict"] == mft.NOT_EVALUABLE


def test_target_verdict_requires_both_halves():
    idx = pd.to_datetime(["1950-03-01", "1952-03-01"] * 6 + ["1970-03-01", "1972-03-01"] * 6)
    pos_after = pd.Series([-1.0] * 12 + [3.0] * 12, index=idx)  # 1967 전 평균 음수
    row = pd.Series({"episodes": 24, "mean_excess": pos_after.mean(), "t_stat": 3.0, "p_value": 0.001, "hit_rate": 60.0})
    v = mft.target_verdict(row, pos_after)
    assert v["checks"] == {"a": True, "b": True, "c": False} and v["verdict"] == mft.FAIL
    both = pd.Series([2.0] * 12 + [3.0] * 12, index=idx)
    row2 = pd.Series({"episodes": 24, "mean_excess": both.mean(), "t_stat": 3.0, "p_value": 0.001, "hit_rate": 60.0})
    assert mft.target_verdict(row2, both)["verdict"] == mft.PASS


def test_mde_shrinks_with_more_episodes_and_is_none_when_too_few():
    assert mft.mde_mean_excess(3.0, 400) < mft.mde_mean_excess(3.0, 50)
    assert mft.mde_mean_excess(3.0, 3) is None and mft.mde_mean_excess(0.0, 100) is None


def test_preregistered_constants_are_frozen():
    # 결과를 보기 전에 고정한 값. 바꾸려면 새 id 로 새로 등록해야 하므로 이 테스트가 깨지면 의도적으로 바꾼 것이다.
    assert (mft.TRIGGER_WINDOW, mft.HORIZON, mft.QUANTILE, mft.MIN_HISTORY) == (21, 21, 0.10, 504)
    assert mft.N_TESTS == 12 and mft.ECON_FLOOR == 0.30 and mft.MIN_HALF_EPISODES == 10
    assert abs(mft.ALPHA - 0.05 / 12) < 1e-12 and mft.SPLIT == pd.Timestamp("1967-01-01")
    assert (mft.DATA_START, mft.DATA_END) == ("1926-07-01", "2007-12-31")


def test_job_json_matches_contract():
    job = json.loads((JOB / "job.json").read_text(encoding="utf-8"))
    assert job["id"] == JOB.name == "market-flow-transfer-v1"
    assert (ROOT / job["entrypoint"]).exists() and job["outputs"] == ["results.json", "REPORT.md"]
    assert 60 <= job["timeout_seconds"] <= 10800 and job["resumable"] is True and "--out" not in job["args"]
    from core import research_jobs

    definition, reason = research_jobs.validate_job(job, JOB.name)
    assert definition is not None, reason


def test_smoke_run_writes_outputs_and_exits_zero(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(JOB / "run.py"), "--smoke", "--out", str(tmp_path / "out"), "--checkpoint", str(tmp_path / "ck")],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-800:]
    res = json.loads((tmp_path / "out/results.json").read_text(encoding="utf-8"))
    assert res["verdicts"]["overall"].startswith("SMOKE_ONLY(") and all(res["smoke_coverage"].values())
    assert "DEFENSIVE" in res["verdicts"] and len(res["primary"]["targets"]) == 12
    assert (tmp_path / "out/REPORT.md").read_text(encoding="utf-8").startswith("# 시장 자금 이동 v1")
    # 체크포인트가 있으면 자료 단계를 다시 계산하지 않고 같은 결과를 낸다(재개 가능).
    again = subprocess.run(
        [sys.executable, str(JOB / "run.py"), "--smoke", "--out", str(tmp_path / "out2"), "--checkpoint", str(tmp_path / "ck")],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert again.returncode == 0
    assert json.loads((tmp_path / "out2/results.json").read_text(encoding="utf-8"))["verdicts"] == {
        k: v for k, v in res["verdicts"].items()}
