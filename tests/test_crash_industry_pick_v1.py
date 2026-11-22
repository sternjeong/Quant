"""crash-industry-pick-v1 — 산업 고르기는 과거만 본다, 보유 수익 구간, 판정, 스모크 전 경로."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("crash_industry_pick_v1", ROOT / "research" / "jobs" / "crash-industry-pick-v1" / "run.py")
ci = importlib.util.module_from_spec(spec)
sys.modules["crash_industry_pick_v1"] = ci
spec.loader.exec_module(ci)


def _data(n=800, seed=2):
    idx = pd.bdate_range("1990-01-01", periods=n)
    r = np.random.default_rng(seed)
    mkt = pd.Series(r.normal(0.0003, 0.01, n), index=idx)
    ind = pd.DataFrame({f"I{j}": 0.0002 + (0.5 + 0.1 * j) * mkt.to_numpy() + r.normal(0, 0.006, n) for j in range(12)}, index=idx)
    return mkt, ind


def test_rank_uses_only_past_and_orders_beta():
    mkt, ind = _data()
    i = 500
    base = ci.rank_at(ind, mkt, i)
    ind2 = ind.copy()
    ind2.iloc[i + 1:] = 0.5                                   # 미래를 바꿔도
    assert ci.rank_at(ind2, mkt, i) == base                   # 고른 산업은 그대로
    assert set(base["P3_HIGH_BETA"]) == {"I9", "I10", "I11"} and set(base["P4_LOW_BETA"]) == {"I0", "I1", "I2"}


def test_hold_return_window_starts_two_days_after_signal():
    idx = pd.bdate_range("2000-01-03", periods=10)
    rets = pd.DataFrame({"A": [0.0, 0.0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}, index=idx)
    assert ci.hold_return(rets, ["A"], 0, 3) == pytest.approx(0.1)   # i=0 → 수익 구간 2,3,4
    assert ci.hold_return(rets, ["A"], 1, 3) == pytest.approx(0.0)
    assert ci.hold_return(rets, ["A"], 8, 3) is None


def test_smoke_end_to_end(tmp_path):
    assert ci.main(["--smoke", "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")]) == 0
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert set(res["verdicts"]) == set(ci.PICKS)
    assert all(v in {"PICK_HELPS", "FAIL", "NOT_EVALUABLE"} for v in res["verdicts"].values())
    assert res["episodes"] and all(len(e["picks"]["P1_MOST_FALLEN"]) == ci.TOP_N for e in res["episodes"])
