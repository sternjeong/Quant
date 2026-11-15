"""sat-industry-horizon-v1 — 신호는 d 전날까지, 수익은 d 다음날부터, 판정은 확인 A·B 둘 다 본다."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("sat_industry_horizon_v1", ROOT / "research/jobs/sat-industry-horizon-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_picks_use_past_only_and_forward_starts_next_day():
    m = _load()
    idx = pd.bdate_range("2000-01-03", periods=700)
    ind = pd.DataFrame(0.0, index=idx, columns=[f"I{j}" for j in range(8)])
    ind["I3"] = 0.002                      # 과거 내내 가장 강함
    mkt = pd.Series(0.0, index=idx)
    d = int(np.flatnonzero(m.LAB.month_first_mask(idx) & (np.arange(len(idx)) > 300))[0])
    ind.iloc[d:, 5] = 0.05                 # 형성일 d 부터만 강한 산업 — 고르면 미래를 본 것
    t = m.build_tables(ind, mkt)["1m"]
    row = t.loc[idx[d]]
    assert row["picks_RS12_k1"] == "I3" and row["picks_M6_k1"] == "I3"
    assert abs(row["RS12_k1"] - (np.expm1(21 * np.log1p(0.002)) - m.COST_RT)) < 1e-9


def test_target_requires_both_confirm_periods():
    m = _load()
    dates = pd.date_range("1927-07-01", "2024-01-01", freq="MS")
    rng = np.random.default_rng(0)
    t = pd.DataFrame(index=dates)
    t["end"] = dates + pd.Timedelta(days=360)
    for k in m.KS:
        t[f"rand_hit7_k{k}"] = 0.2
        t[f"rand_mean_k{k}"] = 0.0
    for c in m.CELLS:
        t[c] = rng.normal(0.0, 0.05, len(dates))
        t[f"picks_{c}"] = "Chips"
    strong = rng.normal(0.15, 0.04, len(dates))
    t["RS12_k1"] = np.where(dates < "2008-01-01", strong, rng.normal(0.02, 0.05, len(dates)))  # B 에서 약함
    out = m.judge_horizon("12m", t, m.rp.power_report(57.0, 4))
    assert out["chosen"] == "RS12_k1"
    assert out["confirm_A"]["a"] and not out["confirm_B"]["a"]
    assert out["verdict"] != "TARGET_MET"
    t["RS12_k1"] = strong
    assert m.judge_horizon("12m", t, m.rp.power_report(57.0, 4))["verdict"] == "TARGET_MET"


def test_job_json_is_valid():
    from core import research_jobs as rj

    job, why = rj.validate_job(json.loads((ROOT / "research/jobs/sat-industry-horizon-v1/job.json").read_text()), "sat-industry-horizon-v1")
    assert job is not None, why
