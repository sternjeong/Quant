"""combo-regime-switch-v1 — 신호는 과거만 본다, 교체 비용, 사후 천장 ≥ 신호, 스모크 전 경로."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("combo_regime_switch_v1", ROOT / "research" / "jobs" / "combo-regime-switch-v1" / "run.py")
cs = importlib.util.module_from_spec(spec)
sys.modules["combo_regime_switch_v1"] = cs
spec.loader.exec_module(cs)


def _data(n=1600, seed=5):
    idx = pd.bdate_range("1995-01-02", periods=n)
    r = np.random.default_rng(seed)
    mkt = pd.Series(r.normal(0.0003, 0.01, n), index=idx)
    ind = pd.DataFrame(r.normal(0.0003, 0.012, (n, 12)), index=idx)
    x2 = pd.Series(r.normal(0.0004, 0.009, n), index=idx)
    return mkt, ind, x2


def test_signals_use_only_past():
    mkt, ind, x2 = _data()
    base = cs.month_signals(mkt, ind, x2)
    cut = mkt.index[1000]
    m2, i2, x22 = mkt.copy(), ind.copy(), x2.copy()
    m2.loc[cut:], i2.loc[cut:], x22.loc[cut:] = -0.03, 0.05, 0.04
    after = cs.month_signals(m2, i2, x22)
    closed = cut.to_period("M") - 1
    pd.testing.assert_frame_equal(base.loc[:closed], after.loc[:closed])


def test_switch_costs_only_on_change():
    idx = pd.bdate_range("2000-01-03", "2000-06-30")
    mkt, x2 = pd.Series(0.0, index=idx), pd.Series(0.0, index=idx)
    months = idx.to_period("M").unique()
    on = pd.Series([False, True, True, False, np.nan, True], index=months, dtype=object)
    r, sw = cs.switch_returns(x2, mkt, on)
    assert sw.sum() == 3                                  # 2월 켜짐·4월 꺼짐·6월 켜짐 (NaN 은 시장)
    assert r.sum() == -3 * 2 * cs.COST_ONE_WAY


def test_smoke_end_to_end(tmp_path):
    assert cs.main(["--smoke", "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")]) == 0
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert set(res["verdicts"]) == set(cs.SIGNALS)
    for e in ("A", "B", "C"):
        orc = res["signals"]["ORACLE"]["eras"][e]["cagr"]
        assert all(orc >= res["signals"][s]["eras"][e]["cagr"] - 0.02 for s in cs.SIGNALS)   # 천장(연 단위)은 신호보다 크게 낮을 수 없다
