"""factor-combo-v1 규칙 기계 장치(결합·레버리지가 사전 등록대로 계산되는지 — 미래 정보 차단, 비중 되돌림, 노출 상한)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    name = "factor_combo_run"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "research/jobs/factor-combo-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fc = _mod()


def _series(n=900, seed=2):
    idx = pd.bdate_range("2001-01-01", periods=n)
    rng = np.random.default_rng(seed)
    a = pd.Series(rng.normal(0.0004, 0.01, n), index=idx)
    b = pd.Series(rng.normal(0.0003, 0.02, n), index=idx)
    return a, b, pd.Series(0.0001, index=idx)


def test_fixed_combo_rebalances_monthly_to_targets():
    a, b, rf = _series()
    combo = fc.Combo("T", "t", {"A": 0.6, "B": 0.4})
    r, w = fc.combine({"A": a, "B": b}, combo, rf, bps=0.0)
    firsts = np.flatnonzero(fc.lab.month_first_mask(a.index))
    d = firsts[5]
    assert np.allclose(w.iloc[d].to_numpy(), [0.6, 0.4])
    # 되돌림 다음 날 수익 = 목표 비중 × 소매 수익
    assert abs(r.iloc[d + 1] - (0.6 * a.iloc[d + 1] + 0.4 * b.iloc[d + 1])) < 1e-12
    # 비용은 되돌림 날에만
    r10, _ = fc.combine({"A": a, "B": b}, combo, rf, bps=10.0)
    diff = (r - r10).abs()
    assert (diff[~fc.lab.month_first_mask(a.index)] < 1e-15).all() and diff.iloc[firsts[5]] > 0


def test_erc_combo_equal_until_active_then_risk_balanced():
    a, b, rf = _series()
    combo = fc.Combo("E", "e", {"A": 0, "B": 0}, "erc")
    _, w = fc.combine({"A": a, "B": b}, combo, rf, bps=0.0)
    firsts = np.flatnonzero(fc.lab.month_first_mask(a.index))
    assert np.allclose(w.iloc[firsts[1]].to_numpy(), [0.5, 0.5])          # 126행 활동 전
    late = w.iloc[firsts[-1]].to_numpy()
    assert late[0] > 0.6 and abs(late.sum() - 1) < 1e-9                      # 변동성 낮은 A 가 더 큼


def test_lever_exposure_capped_and_uses_only_past():
    a, b, rf = _series()
    core = a * 0.3                                                            # 변동성 낮은 코어 → 상한 2배
    r, e = fc.lever_returns(core, b, rf, bps=0.0)
    assert e.max() <= fc.LEV_CAP + 1e-12 and e.iloc[-1] == fc.LEV_CAP
    i = len(r) - 1
    expect = rf.iloc[i] + 2.0 * (core.iloc[i] - rf.iloc[i]) - 1.0 * fc.LEV_SPREAD / 252
    assert abs(r.iloc[i] - expect) < 1e-12
    firsts = np.flatnonzero(fc.lab.month_first_mask(a.index))
    d = firsts[-3]
    b2 = b.copy()
    b2.iloc[d:] *= 10                                                         # d 이후 시장을 바꿔도 d 까지 노출은 그대로
    _, e2 = fc.lever_returns(core, b2, rf, bps=0.0)
    pd.testing.assert_series_equal(e.iloc[: d + 1], e2.iloc[: d + 1])


def test_judge_checks_and_noop():
    a, b, rf = _series(n=300)
    idx = pd.bdate_range("1927-07-01", periods=300)
    s = lambda x: pd.Series(x.to_numpy(), index=idx)  # noqa: E731
    rf = s(rf)
    jd = fc.judge(s(a), s(a), s(a), s(b), s(b), rf)
    assert jd["noop"] and not jd["checks"]["a_cagr_vs_market"]


def test_job_definition_valid():
    from core import research_jobs as rj

    data = json.loads((ROOT / "research/jobs/factor-combo-v1/job.json").read_text(encoding="utf-8"))
    job, err = rj.validate_job(data, "factor-combo-v1", ROOT)
    assert job is not None, err


def test_smoke_runs_offline(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "research/jobs/factor-combo-v1/run.py"), "--smoke",
                        "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-1500:]
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert res["smoke"] and res["power"]["n_trials"] == 4
    assert {"X1_core_mkt_leg", "X2_core_sector", "X3_sleeve_erc", "X4_core_levered", "overall"} <= set(res["verdicts"])
    assert "검정력(사전 계산)" in (tmp_path / "o" / "REPORT.md").read_text(encoding="utf-8")
