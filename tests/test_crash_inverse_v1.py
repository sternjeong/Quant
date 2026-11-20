"""crash-inverse-v1 — 신호 다음 거래일 진입(미래 비의존), 겹치지 않는 사건, 인버스 수익식, t 꼬리확률."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location(
    "crash_inverse_v1", Path(__file__).resolve().parents[1] / "research" / "jobs" / "crash-inverse-v1" / "run.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

IDX = pd.bdate_range("2000-01-03", periods=40)


def test_entry_is_two_days_after_signal_and_extends():
    sig = pd.Series(False, index=IDX)
    sig.iloc[[3, 5]] = True
    on = mod.active_mask(sig, 5)
    assert not on.iloc[:5].any() and on.iloc[5:12].all() and not on.iloc[12:].any()  # 3→5..9, 5→7..11


def test_events_do_not_overlap():
    sig = pd.Series(False, index=IDX)
    sig.iloc[[3, 5, 11, 12]] = True
    assert mod.events(sig, 5) == [3, 11]  # 3 의 보유가 9 에서 끝나 5 는 겹치고 11 은 새 사건


def test_inverse_return_formula_and_signals():
    mkt = pd.Series([0.0] * 300 + [-0.04], index=pd.bdate_range("2000-01-03", periods=301))
    rf = pd.Series(0.0001, index=mkt.index)
    inv = mod.inverse_returns(mkt, rf)
    assert inv.iloc[-1] == pytest.approx(0.04 + 0.0002 - mod.INV_FEE / 252)
    assert mod.signals(mkt)["D1"].iloc[-1] and not mod.signals(mkt)["D1"].iloc[-2]


def test_t_sf_matches_known_values():
    assert mod.t_sf(2.0, 20) == pytest.approx(0.0296, abs=2e-4)
    assert mod.t_sf(3.0, 5) == pytest.approx(0.0150, abs=2e-4)
    assert mod.t_sf(-1.0, 10) == pytest.approx(1 - 0.1704, abs=2e-4)


def test_smoke_run_writes_outputs(tmp_path):
    assert mod.main(["--smoke", "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")]) == 0
    assert (tmp_path / "o" / "REPORT.md").is_file() and (tmp_path / "o" / "results.json").is_file()
