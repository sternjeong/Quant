"""momentum-decay-regime-v1 — 구조 변수는 과거만 본다, 기울기 검정 방향, 스모크 전 경로."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("momentum_decay_regime_v1", ROOT / "research" / "jobs" / "momentum-decay-regime-v1" / "run.py")
md = importlib.util.module_from_spec(spec)
sys.modules["momentum_decay_regime_v1"] = md
spec.loader.exec_module(md)


def _data(n=1200, seed=4):
    idx = pd.bdate_range("1995-01-02", periods=n)
    r = np.random.default_rng(seed)
    mkt = pd.Series(r.normal(0.0003, 0.01, n), index=idx)
    ind = pd.DataFrame({f"I{j}": mkt.to_numpy() * (0.6 + 0.08 * j) + r.normal(0, 0.007, n) for j in range(12)}, index=idx)
    return mkt, ind


def test_variables_use_only_past():
    mkt, ind = _data()
    base = md.month_variables(mkt, ind)
    cut = mkt.index[900]
    m2, i2 = mkt.copy(), ind.copy()
    m2.loc[cut:], i2.loc[cut:] = 0.03, -0.02
    after = md.month_variables(m2, i2)
    closed = cut.to_period("M") - 1
    pd.testing.assert_frame_equal(base.loc[:closed], after.loc[:closed])
    assert base["C1_CORR"].dropna().between(-1, 1).all()


def test_slope_test_detects_negative_relation():
    r = np.random.default_rng(1)
    x = pd.Series(r.normal(0, 1, 400))
    y = -0.01 * x + pd.Series(r.normal(0, 0.005, 400))
    s = md.slope_test(y, x)
    assert s["b"] < 0 and s["p"] < 0.001
    assert md.slope_test(-y, x)["p"] > 0.99


def test_smoke_end_to_end(tmp_path):
    assert md.main(["--smoke", "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")]) == 0
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert set(res["verdicts"]) == set(md.VARIABLES)
    assert all(v in {"EXPLAINS_AND_SWITCHES", "EXPLAINS_ONLY", "FAIL"} for v in res["verdicts"].values())
