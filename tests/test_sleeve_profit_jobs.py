"""sleeve-mechanism-v1·profit-tilt-v1 의 핵심 계산(미리 보기 없음, 레버리지 식, 자료 연결)."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load(job: str):
    spec = importlib.util.spec_from_file_location(job.replace("-", "_"), ROOT / "research/jobs" / job / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vm_leverage_uses_only_past_data():
    sm = _load("sleeve-mechanism-v1")
    idx = pd.bdate_range("2000-01-03", periods=900)
    r = pd.Series(np.random.default_rng(1).normal(0, 0.01, len(idx)), index=idx)
    base = sm.vm_leverage(r)
    bumped = r.copy()
    bumped.iloc[600:] *= 5  # 미래 변동성 급등
    lev = sm.vm_leverage(bumped)
    assert np.allclose(base[:601], lev[:601])
    assert lev[700] < base[700]
    assert base.max() <= sm.L_CAP and base.min() > 0


def test_lev_leg_matches_synthetic_2x_and_rf():
    sm = _load("sleeve-mechanism-v1")
    idx = pd.bdate_range("2000-01-03", periods=5)
    m = pd.Series([0.0, 0.01, -0.02, 0.005, 0.0], index=idx)
    rf = pd.Series(0.0001, index=idx)
    two = sm.lev_leg(m, rf, np.full(5, 2.0)).to_numpy()
    exp = (2 * m - (rf + sm.FIN / 252) - sm.FEE_Y / 252).to_numpy()
    assert np.allclose(two[1:], exp[1:])
    zero = sm.lev_leg(m, rf, np.zeros(5)).to_numpy()
    assert np.allclose(zero[2:], rf.to_numpy()[2:])


def test_profit_tilt_windows_halves_do_not_overlap():
    pt = _load("profit-tilt-v1")
    days = pd.bdate_range("1963-07-01", "2026-08-31")
    sets = pt.window_sets(days, 10, smoke=True)
    assert max(e for _, e in sets["first"]) <= pd.Timestamp(pt.H1_END)
    assert min(s for s, _ in sets["second"]) >= pd.Timestamp(pt.H2_START)
    assert max(e for _, e in sets["second"]) <= pd.Timestamp(pt.H2_END)


def test_profit_tilt_datasets_registered():
    from core import french_factors as ff
    pt = _load("profit-tilt-v1")
    for ds, _col in pt.SRC.values():
        assert ds in ff.DATASETS
