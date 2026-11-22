"""regime-playbook-v4 — 평균 메뉴 비중, 분해 판정, ETF 메뉴 이어 붙이기, 스모크 전 경로(네트워크 없음)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("regime_playbook_v4", ROOT / "research" / "jobs" / "regime-playbook-v4" / "run.py")
p4 = importlib.util.module_from_spec(spec)
sys.modules["regime_playbook_v4"] = p4
spec.loader.exec_module(p4)


def test_menu_weights_sum_to_one_and_use_frozen_picks():
    w = p4.menu_weights(p4._v1().load_smoke())
    assert sum(w.values()) == pytest.approx(1.0) and set(w) <= {"SV", "L2", "CASH"}


def test_judge_a_requires_sets_and_pooled_significance():
    def s(b, diffs):
        return {"beyond_menu": b, "monthly_diff": {str(p): d for p, d in zip(pd.period_range("2000-01", periods=len(diffs), freq="M"), diffs)}}
    rng = np.random.default_rng(0)
    good = {k: s(0.01, list(0.01 + rng.normal(0, 0.005, 200))) for k in ["US_B", "US_C", *p4.REGION_SETS]}
    assert p4.judge_a(good)[0] == "TIMING_BEYOND_MENU"
    bad = dict(good, US_B=s(-0.01, [0.0] * 200), US_C=s(-0.01, [0.0] * 200))
    assert p4.judge_a(bad)[0] == "MENU_ONLY"


def test_etf_menu_splices_synthetic_before_listing():
    prices, rf = p4.synthetic_etf()
    menu = p4.etf_menu(prices, rf)
    assert menu.index[0] < pd.Timestamp(p4.SSO_START) and not menu[["L2", "CASH", "SV"]].isna().any().any()
    early = menu.loc[: "2005-12-30"]
    np.testing.assert_allclose(early["L2"], 2 * (early["M"] - early["CASH"]) + early["CASH"] - p4.L2_FEE / 252, atol=1e-12)


def test_smoke_end_to_end(tmp_path):
    assert p4.main(["--smoke", "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")]) == 0
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert res["verdicts"]["A_decomposition"] in {"TIMING_BEYOND_MENU", "MENU_ONLY"}
    assert res["verdicts"]["B_etf"] in {"ETF_HOLDS", "FAIL"} and len(res["decomposition"]) == 5
