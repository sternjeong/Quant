"""lev-weight-frontier-v1 — 비중을 바꿔 부른 뒤 공유 모듈 상수가 되돌려지고, 비중이 노출에 반영되는지."""

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("lev_weight_frontier_v1", ROOT / "research/jobs/lev-weight-frontier-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sim_weight_restores_shared_target_and_scales_exposure():
    m = _load()
    rng = np.random.default_rng(0)
    fm = 1 + rng.normal(0.008, 0.04, (50, 36))
    fl = 1 + 2 * (fm - 1) - 0.002
    cal = np.arange(36) % 12
    lo, hi = m.sim_weight(fm, fl, cal, 0.10), m.sim_weight(fm, fl, cal, 0.40)
    assert m.FL.TARGET_W == 0.20
    assert np.median(hi["exposure"]) > np.median(lo["exposure"])
