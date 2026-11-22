"""regime-playbook-v2 — 두 달 확인 규칙, 2배 자리 바꾸기, 과세 이연 계좌 세금, 스모크 전 경로."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("regime_playbook_v2", ROOT / "research" / "jobs" / "regime-playbook-v2" / "run.py")
p2 = importlib.util.module_from_spec(spec)
sys.modules["regime_playbook_v2"] = p2
spec.loader.exec_module(p2)


def test_hysteresis_needs_two_months():
    idx = pd.period_range("2000-01", periods=8, freq="M")
    s = pd.Series([np.nan, "CALM_BULL", "CRISIS", "CALM_BULL", "CRISIS", "CRISIS", "CRISIS", "CALM_BULL"], index=idx, dtype=object)
    h = p2.hysteresis(s)
    assert list(h.iloc[1:]) == ["CALM_BULL", "CALM_BULL", "CALM_BULL", "CALM_BULL", "CRISIS", "CRISIS", "CRISIS"]
    assert pd.isna(h.iloc[0])


def test_picks_nolev_replaces_only_l2():
    assert p2.picks_for(True) == {"CALM_BULL": "SV", "NERVOUS_BULL": "M", "QUIET_BEAR": "M", "CRISIS": "LV"}
    assert p2.picks_for(False) == p2.PICKS_V1


def test_deferred_account_taxes_only_at_end():
    idx = pd.bdate_range("2000-01-03", "2001-12-31")
    menu = pd.DataFrame({k: 0.0 for k in p2._v1().MENU}, index=idx)
    menu["M"], menu["CASH"] = 0.001, 0.001
    months = idx.to_period("M").unique()
    flip = pd.Series(["M" if i % 2 == 0 else "CASH" for i in range(len(months))], index=months)
    d, t = p2.account(menu, flip, "deferred"), p2.account(menu, flip, "taxable")
    gross = float((1 + d["daily"]).prod())
    assert (1 + d["cagr_after"]) ** ((idx[-1] - idx[0]).days / 365.25) == pytest.approx(gross - p2.TAX_DEFERRED_END * (gross - 1), rel=1e-9)
    assert d["cagr_after"] > t["cagr_after"]                       # 교체가 잦을수록 과세 이연이 유리


def test_smoke_end_to_end(tmp_path):
    assert p2.main(["--smoke", "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")]) == 0
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert set(res["verdicts"]) == set(p2.VARIANTS)
    v = res["variants"]
    assert v["P_HYST"]["eras"]["B"]["switches"] < res["reference_v1"]["B"]["switches"]   # 두 달 확인은 교체를 줄인다
