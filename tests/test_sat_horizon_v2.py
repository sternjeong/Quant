"""sat-horizon-v2 — 판정 구간만 쓰고(본 구간 제외), 자료 부족이면 NOT_EVALUABLE, 기준을 넘으면 CONFIRMED."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("sat_horizon_v2", ROOT / "research/jobs/sat-horizon-v2/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _table(m, e5, coverage=0.8):
    dates = pd.date_range("1997-01-01", "2024-01-01", freq="MS")
    t = pd.DataFrame(index=dates)
    t["end"] = dates + pd.Timedelta(days=365)
    t["coverage"] = coverage
    t["E5"] = e5(dates)
    t["rand_hit7"] = 0.3
    t["rand_mean"] = 0.0
    return t


def test_only_judge_window_counts_and_confirmed_path():
    m = _load()
    rng = np.random.default_rng(1)
    # 판정 구간(1997~2001-01)은 강하고, 그 뒤는 나쁘게 — 판정이 뒤 구간을 보지 않아야 CONFIRMED
    t = _table(m, lambda d: np.where(d <= "2001-01-31", rng.normal(0.25, 0.05, len(d)), -0.5))
    out = m.judge(t, m.rp.power_report(5.0, 1))
    assert out["n_months"] == 49 and out["verdict"] == "CONFIRMED", out


def test_low_coverage_is_not_evaluable():
    m = _load()
    t = _table(m, lambda d: np.full(len(d), 0.3), coverage=0.4)
    assert m.judge(t, m.rp.power_report(5.0, 1))["verdict"] == "NOT_EVALUABLE"


def test_survivorship_stress_blocks_marginal_result():
    m = _load()
    rng = np.random.default_rng(2)
    t = _table(m, lambda d: rng.normal(0.08, 0.02, len(d)))  # +8%p 평균: (a) 통과, (b) 8−3=5 < 7 미달
    out = m.judge(t, m.rp.power_report(5.0, 1))
    assert out["checks"]["a_mean_ge_target"] and not out["checks"]["b_survivorship_stress"] and out["verdict"] != "CONFIRMED"


def test_job_json_is_valid():
    from core import research_jobs as rj

    job, why = rj.validate_job(json.loads((ROOT / "research/jobs/sat-horizon-v2/job.json").read_text()), "sat-horizon-v2")
    assert job is not None, why
