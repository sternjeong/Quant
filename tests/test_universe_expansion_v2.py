import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from core import core_lab as cl
from core import research_power as rp
from core.champion_strategy import CORE_UNIVERSE, MARKET_FILTER_TICKER

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("universe_expansion_v2", ROOT / "research/jobs/core-universe-expansion-v2/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dominant_prices(winner="LQD"):
    """추가 ETF 하나가 강하게 오르고 나머지는 거의 제자리인 합성 가격."""
    mod = _load()
    tickers = list(dict.fromkeys([*CORE_UNIVERSE, MARKET_FILTER_TICKER, cl.CASH_ETF, *cl.CREDIT_PAIR, *mod.ASSETS]))
    ix = pd.bdate_range("2006-01-02", "2018-12-31")
    rng = np.random.default_rng(7)
    px = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(0.0001, 0.008, len(ix)))) for t in tickers}, index=ix)
    px[winner] = 50 * np.exp(np.cumsum(rng.normal(0.0015, 0.005, len(ix))))
    px[MARKET_FILTER_TICKER] = 50 * np.exp(np.cumsum(np.full(len(ix), 0.0003)))  # 시장 필터는 늘 200일선 위
    px[cl.CASH_ETF] = 90.0
    return mod, px, px * 1.0001


def test_added_etf_is_rankable_and_selected_when_dominant():
    mod, px, adj = _dominant_prices("LQD")
    w = mod.weights_for(px, ("LQD",))
    sel = mod.selection_diagnostics(w, ("LQD",), "2008-01-01")["LQD"]
    assert sel["rebalance_months"] > 100
    assert sel["selected_fraction"] > 0.8
    base = mod.run_one(px, adj, ())
    cand = mod.run_one(px, adj, ("LQD",))
    active = (cand - base).loc["2008-01-01":]
    assert rp.noop_guard(list(active)) is None
    assert (active.abs() > 1e-12).sum() > 1000
    assert active.sum() > 0


def test_v1_style_plumbing_is_a_noop_and_guard_catches_it():
    """v1 버그 재현: 추가 ETF 를 extra 에만 넣으면 순위 후보가 아니어서 기준선과 같다."""
    mod, px, adj = _dominant_prices("LQD")
    core = [t for t in CORE_UNIVERSE if t in px]
    extras = [MARKET_FILTER_TICKER, cl.CASH_ETF, *cl.CREDIT_PAIR, "LQD"]
    cfg = cl.with_changes(cl.CoreConfig(), extra_assets=("LQD",))
    v1 = cl.run(px[core], px[extras], cfg, mod.START, total=(adj[core], adj[extras]))
    base = mod.run_one(px, adj, ())
    assert rp.noop_guard(list((v1 - base).loc[base.index])) is not None


def test_decide_noop_is_not_evaluable_not_fail():
    mod = _load()
    power = rp.power_report(16.7, 6)
    zero = pd.Series(0.0, index=pd.bdate_range("2010-01-01", periods=300))
    failing = {"verdict": "FAIL", "reasons": ["G1"], "gates": {"G1_improves_corrected": {"active_sharpe_annual": 0.0}}}
    for smoke in (False, True):
        d = mod.decide(zero, failing, False, power, smoke)
        assert d["verdict"] == "NOT_EVALUABLE_NOOP"
        assert d["fail_kind"] is None


def test_decide_fail_kind_and_pass():
    mod = _load()
    power = rp.power_report(16.7, 6)
    act = pd.Series(np.linspace(-1e-3, 1e-3, 300))
    weak = {"verdict": "FAIL", "reasons": ["G1"], "gates": {"G1_improves_corrected": {"active_sharpe_annual": 0.2}}}
    d = mod.decide(act, weak, True, power, False)
    assert d["verdict"] == "FAIL" and d["fail_kind"] == "FAIL_UNDERPOWERED"
    neg = {"verdict": "FAIL", "reasons": ["G1"], "gates": {"G1_improves_corrected": {"active_sharpe_annual": -0.3}}}
    assert mod.decide(act, neg, True, power, False)["fail_kind"] == "FAIL"
    ok = {"verdict": "PASS", "reasons": [], "gates": {"G1_improves_corrected": {"active_sharpe_annual": 1.5}}}
    assert mod.decide(act, ok, True, power, False) == {"verdict": "PASS_REVIEW_ONLY", "fail_kind": None, "reasons": []}
    assert mod.decide(act, ok, False, power, False)["verdict"] == "FAIL"  # 비용 스트레스 미충족


def test_smoke_writes_outputs_with_power_and_selection(tmp_path):
    mod = _load()
    assert mod.main(["--smoke", "--out", str(tmp_path / "out"), "--checkpoint", str(tmp_path / "ckpt")]) == 0
    d = json.loads((tmp_path / "out/results.json").read_text())
    assert len(d["candidates"]) == 6
    assert set(d["verdicts"].values()) == {"SMOKE_ONLY"}
    assert d["power"]["n_trials"] == 6 and d["power"]["mde_ir"] > 0
    for row in d["candidates"].values():
        assert row["active_nonzero_days"] > 0
        assert set(row["selection"]) == set(row["assets"])
        assert all(s["selected_months"] > 0 for s in row["selection"].values())
    report = (tmp_path / "out/REPORT.md").read_text()
    assert "검정력(사전 계산)" in report and "전진 원장" in report
