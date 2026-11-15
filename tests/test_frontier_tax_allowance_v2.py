"""frontier-tax-allowance-v2 — 원가 올리기는 세전 수익을 바꾸지 않지만 세후 청산액은 바꾼다(판정 불가 검사가 이것을 봐야 한다)."""

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("frontier_tax_allowance_v2", ROOT / "research/jobs/frontier-tax-allowance-v2/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stepup_keeps_pretax_twr_but_moves_after_tax_terminal():
    m = _load()
    rng = np.random.default_rng(1)
    fm = 1 + rng.normal(0.008, 0.04, (40, 60))
    fl = 1 + 2 * (fm - 1) - 0.002
    cal = np.arange(60) % 12
    lump, monthly = m.SCENARIOS[m.JUDGE_SCENARIO]
    mkt = m.simulate(fm, fl, "MKT", cal, lump, monthly, want_twr=True)
    h0 = m.simulate(fm, fl, "H0_MKT_STEPUP", cal, lump, monthly, want_twr=True)
    assert np.allclose(h0["twr"], mkt["twr"])  # v1 이 NOT_EVALUABLE 을 낸 이유
    assert np.median(h0["harvested"]) > 0
    blk = m.era_block({"MKT": mkt, **{a: m.simulate(fm, fl, a, cal, lump, monthly) for a in m.ARMS}})
    assert blk["H0_MKT_STEPUP"]["terminal_diff_maxabs_krw"] > m.EVAL_TOL_KRW
