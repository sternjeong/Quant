"""research/jobs/account-location-v1 — 계좌 위치 시뮬레이터의 세금·한도 기계(가짜 데이터, 네트워크 없음)."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.research_power import noop_guard

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("account_location_engine_t", ROOT / "research/jobs/account-location-v1/location.py")
loc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = loc
_spec.loader.exec_module(loc)

FREE = loc.Rules(ovs_fee=0.0, fx_spread=0.0, dom_fee=0.0, dom_slippage=0.0)


def _data(years=4, growth=0.0, tickers=("AAA",)):
    idx = pd.bdate_range("2015-01-01", periods=int(252 * years))
    px = 100 * (1 + growth) ** (np.arange(len(idx)) / 252)
    close = pd.DataFrame({t: px for t in list(tickers) + ["BIL", "SPY"]}, index=idx)
    fx = pd.Series(1000.0, index=idx)
    ref = loc.reference_krw_index(close, close, fx)
    return idx, close, fx, ref


def _w(idx, row):
    return pd.DataFrame({t: x for t, x in row.items()}, index=idx)


def test_isa_tax_free_band_then_9_9pct():
    assert loc.isa_settlement_tax(1_500_000) == 0
    assert loc.isa_settlement_tax(2_000_000) == 0
    assert loc.isa_settlement_tax(5_000_000) == pytest.approx(3_000_000 * 0.099)
    assert loc.isa_settlement_tax(-1_000_000) == 0


def test_pension_withdrawal_tax_only_on_gain():
    assert loc.pension_withdrawal_tax(30e6, 20e6, 0.055) == pytest.approx(10e6 * 0.055)
    assert loc.pension_withdrawal_tax(15e6, 20e6, 0.055) == 0


def test_pension_cap_first_year_and_overflow_stays_overseas():
    idx, close, fx, ref = _data(years=3)
    w = _w(idx, {"AAA": 1.0})
    r = loc.simulate(w, close, close, fx, ref, "L1", 100e6, FREE, proxied={"AAA", "BIL"})
    pens = [c for c in r["contributions"] if c["kind"] == "pension"]
    by_year = {}
    for c in pens:
        by_year[c["date"][:4]] = by_year.get(c["date"][:4], 0) + c["krw"]
    assert all(v <= 18_000_000 for v in by_year.values())
    assert by_year["2015"] == 18_000_000 and by_year["2016"] == 18_000_000
    # 넘친 돈은 해외 계좌에서 계속 굴러간다: 평탄한 가격·비용 0 이면 최종 = 원금
    assert r["final_krw"]["low"] == pytest.approx(100e6, rel=1e-6)
    assert r["totals"]["pension_principal_krw"] == pytest.approx(sum(by_year.values()), abs=5)


def test_small_pot_moves_fully_in_second_year():
    idx, close, fx, ref = _data(years=3)
    r = loc.simulate(_w(idx, {"AAA": 1.0}), close, close, fx, ref, "L1", 30e6, FREE, proxied={"AAA", "BIL"})
    assert r["migrations"][0]["pension"] == 18_000_000
    assert r["migrations"][1]["pension"] == pytest.approx(12_000_000, rel=1e-6)
    assert len(r["migrations"]) == 2


def test_pension_tax_applied_once_at_end_not_during():
    idx, close, fx, ref = _data(years=4, growth=0.10)
    r = loc.simulate(_w(idx, {"AAA": 1.0}), close, close, fx, ref, "L1", 10e6, FREE, proxied={"AAA", "BIL"})
    t = r["totals"]
    assert t["domestic_tax_krw"] == 0 and t["overseas_cg_tax_krw"] == 0
    gain = t["pension_value_krw"] - t["pension_principal_krw"]
    assert gain > 0
    assert r["final_krw"]["low"] - r["final_krw"]["high"] == pytest.approx(gain * (0.055 - 0.033), rel=1e-9)
    assert r["final_krw"]["low"] == pytest.approx(t["pension_value_krw"] - gain * 0.033, rel=1e-9)


def test_isa_rolls_into_pension_after_three_years_with_tax():
    idx, close, fx, ref = _data(years=4, growth=0.10)
    r = loc.simulate(_w(idx, {"AAA": 1.0}), close, close, fx, ref, "L2", 10e6, FREE, proxied={"AAA", "BIL"})
    assert len(r["isa_rollovers"]) == 1
    roll = r["isa_rollovers"][0]
    assert pd.Timestamp(roll["date"]) >= idx[0] + pd.DateOffset(years=3)
    pre_tax = 10e6 * 1.10 ** ((idx.get_loc(pd.Timestamp(roll["date"]))) / 252)
    assert roll["krw"] == pytest.approx(pre_tax - loc.isa_settlement_tax(pre_tax - 10e6), rel=1e-6)
    assert r["totals"]["pension_principal_krw"] == pytest.approx(roll["krw"], abs=1)
    assert not [c for c in r["contributions"] if c["kind"] == "pension" and c["source"] == "overseas"]


def test_household_targets_fill_domestic_first_and_overflow():
    ovs, dom = loc.household_targets({"A": 0.5, "B": 0.5}, {"A"}, 60.0, {"pension": 40.0})
    assert dom["pension"] == {"A": pytest.approx(40.0)}
    assert ovs == {"A": pytest.approx(10.0), "B": pytest.approx(50.0)}
    ovs, dom = loc.household_targets({"A": 0.5, "B": 0.5}, {"A"}, 30.0, {"pension": 70.0})
    assert dom["pension"]["A"] == pytest.approx(50.0) and dom["pension"]["BIL"] == pytest.approx(20.0)
    assert ovs == {"B": pytest.approx(30.0)}


def test_reserve_keeps_non_proxied_share_overseas():
    idx, close, fx, ref = _data(years=3, tickers=("AAA", "BBB"))
    w = _w(idx, {"AAA": 0.5, "BBB": 0.5})
    r = loc.simulate(w, close, close, fx, ref[["AAA", "BIL"]], "L3", 30e6, FREE, proxied={"AAA", "BIL"}, reserve_share=0.5)
    assert r["migrations"][0]["taxable"] == pytest.approx(15e6)
    assert len(r["migrations"]) == 1  # 유보 몫(50%)만 남아 더 옮길 것이 없다


def test_domestic_taxable_taxes_each_gain_without_loss_offset():
    a = loc.Domestic("taxable", FREE)
    a.deposit(2000.0, pd.Timestamp("2020-01-02"))
    a.buy("A", 1000.0, 1.0)
    a.buy("B", 1000.0, 1.0)
    a.sell("A", 1000.0, 1.5)
    a.sell("B", 1000.0, 0.5)
    assert a.tax_krw == pytest.approx(500 * 0.154)
    assert a.cash == pytest.approx(1500 - 500 * 0.154 + 500)


def test_overseas_deduction_and_noop_guard():
    idx, close, fx, ref = _data(years=3, growth=0.2)
    w = _w(idx, {"AAA": 1.0})
    r0 = loc.simulate(w, close, close, fx, ref, "L0", 30e6, FREE, proxied={"AAA", "BIL"})
    r0b = loc.simulate(w, close, close, fx, ref, "L0", 30e6, FREE, proxied={"AAA", "BIL"})
    r1 = loc.simulate(w, close, close, fx, ref, "L1", 30e6, FREE, proxied={"AAA", "BIL"})
    same = (r0b["values_krw"].pct_change() - r0["values_krw"].pct_change()).fillna(0.0).to_numpy()
    assert noop_guard(same) is not None
    assert loc.overseas_cg_tax(2_000_000) == 0 and loc.overseas_cg_tax(3_500_000) == pytest.approx(220_000)
    # 해외 계좌만이면 이전할 때 실현한 차익에 양도세, 연금은 끝까지 비과세
    assert r1["totals"]["domestic_tax_krw"] == 0


def test_decide_deduction_rule():
    d = loc.decide_deduction(0.0008, 0.0025, {"measured_drag": 0.01})
    assert d["deduction"] == pytest.approx(0.01) and d["source"] == "measured"
    d = loc.decide_deduction(0.0008, 0.0025, {"measured_drag": -0.02})  # 더 잘한 몫은 인정 안 함
    assert d["deduction"] == pytest.approx(0.0017)
    d = loc.decide_deduction(0.0008, 0.0025, {"n_days": 10})
    assert d["deduction"] == pytest.approx(0.0017 + 0.003) and d["source"] == "fixed"
    d = loc.decide_deduction(0.0049, 0.0030, {"measured_drag": 0.10})
    assert d["deduction"] == pytest.approx(-0.0019 + 0.03)
