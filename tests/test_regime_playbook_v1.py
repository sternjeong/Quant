"""regime-playbook-v1 — 국면은 과거만 본다, 플레이북 고르기, 계좌 비용·세금 근사, 스모크 전 경로."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("regime_playbook_v1", ROOT / "research" / "jobs" / "regime-playbook-v1" / "run.py")
rp = importlib.util.module_from_spec(spec)
sys.modules["regime_playbook_v1"] = rp
spec.loader.exec_module(rp)


def _mkt(n=1500, seed=3):
    idx = pd.bdate_range("1990-01-01", periods=n)
    return pd.Series(np.random.default_rng(seed).normal(0.0003, 0.01, n), index=idx)


def test_states_use_only_past():
    m = _mkt()
    base = rp.month_states(m)
    cut = m.index[900]
    changed = m.copy()
    changed.loc[cut:] = -0.05                         # 미래를 망가뜨려도
    after = rp.month_states(changed)
    last_closed = cut.to_period("M") - 1             # 그 전에 끝난 달의 국면은 그대로
    pd.testing.assert_series_equal(base[:last_closed], after[:last_closed])
    assert set(base.dropna().unique()) <= set(rp.STATES)


def test_applied_states_shift_one_month():
    s = pd.Series(["CRISIS"], index=pd.PeriodIndex(["2008-09"], freq="M"))
    assert rp.applied_states(s).index[0] == pd.Period("2008-10", "M")


def test_choose_playbook_picks_best_and_defaults_to_market():
    months = pd.period_range("1950-01", periods=60, freq="M")
    mret = pd.DataFrame({k: 0.01 for k in rp.MENU}, index=months)
    mret["DEF"] = 0.02
    st = pd.Series(["CALM_BULL"] * 50 + ["CRISIS"] * 10, index=months)
    book = rp.choose_playbook(mret, st)
    assert book["CALM_BULL"]["pick"] == "DEF"
    assert book["CRISIS"]["pick"] == "M" and book["CRISIS"]["months"] == 10   # 24달 미만 → 시장


def test_account_costs_and_tax():
    idx = pd.bdate_range("2000-01-03", "2001-12-31")
    menu = pd.DataFrame({k: 0.0 for k in rp.MENU}, index=idx)
    menu["M"] = 0.001
    hold = rp.run_account(menu, pd.Series("M", index=idx.to_period("M").unique()))
    gross = (1.001 ** len(idx))
    assert hold["switches"] == 0
    assert (1 + hold["cagr_after"]) ** 2 == pytest.approx(gross - rp.TAX * (gross - 1), rel=2e-3)  # 끝에 한 번 청산
    months = idx.to_period("M").unique()
    flip = pd.Series(["M" if i % 2 == 0 else "CASH" for i in range(len(months))], index=months)
    sw = rp.run_account(menu, flip)
    assert sw["switches"] == len(months) - 1
    assert sw["cagr_after"] < sw["cagr_pre"] < hold["cagr_pre"]


def test_smoke_end_to_end(tmp_path):
    assert rp.main(["--smoke", "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")]) == 0
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert res["verdict"] in {"GOAL_MET", "USEFUL", "FAIL"}
    assert set(res["local_verdicts"]) == set(rp.STATES)
    e = res["eras"]["confirmation"]
    assert e["year_oracle"]["cagr_pre"] >= e["honest"]["cagr_pre"]              # 사후 천장이 정직한 방식보다 낮을 수 없다
    assert "사후 천장" in (tmp_path / "o" / "REPORT.md").read_text(encoding="utf-8")
