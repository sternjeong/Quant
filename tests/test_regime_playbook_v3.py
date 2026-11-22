"""regime-playbook-v3 — 같은 노출 대조군 비중, 고정 비중 되돌림, 판정 분기, 스모크 전 경로."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("regime_playbook_v3", ROOT / "research" / "jobs" / "regime-playbook-v3" / "run.py")
p3 = importlib.util.module_from_spec(spec)
sys.modules["regime_playbook_v3"] = p3
spec.loader.exec_module(p3)


def test_static_weights_cover_beta_ranges():
    assert p3.static_weights(1.3) == pytest.approx({"M": 0.7, "L2": 0.3})
    assert p3.static_weights(0.6) == pytest.approx({"M": 0.6, "CASH": 0.4})
    assert p3.static_weights(2.4) == {"L2": 1.0}


def test_static_returns_constant_menu_has_no_cost():
    idx = pd.bdate_range("2000-01-03", "2000-12-29")
    menu = pd.DataFrame({k: 0.001 for k in p3._v1().MENU}, index=idx)
    r = p3.static_returns(menu, {"M": 0.5, "L2": 0.5})
    assert r.to_numpy() == pytest.approx(0.001)                     # 두 다리 수익이 같으면 표류도 비용도 없다


def _era(vm, vs, mdd=-0.4, mdd_mkt=-0.4, p=0.001):
    return {"excess_vs_mkt": vm, "excess_vs_static": vs, "mdd": mdd, "mdd_mkt": mdd_mkt, "monthly_excess_mean": 0.01, "p": p}


def test_judge_branches():
    assert p3.judge({"B": _era(0.03, 0.01), "C": _era(0.02, 0.0)}) == "TIMING_HELPS"
    assert p3.judge({"B": _era(0.03, -0.01), "C": _era(0.02, 0.01)}) == "BETA_ONLY"
    assert p3.judge({"B": _era(0.03, 0.01), "C": _era(0.02, 0.01, mdd=-0.6)}) == "FAIL"
    assert p3.judge({"B": _era(0.03, 0.01, p=0.2), "C": _era(0.02, 0.01)}) == "FAIL"


def test_smoke_end_to_end(tmp_path):
    assert p3.main(["--smoke", "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")]) == 0
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert set(res["verdicts"]) == set(p3.VARIANTS)
    assert all(x["picks"]["CRISIS"] in {"CASH", "M"} for x in res["variants"].values())
