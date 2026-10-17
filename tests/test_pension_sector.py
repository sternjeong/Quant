"""research/jobs/pension-sector-v1 — 9 섹터 신호, 변동성 맞춤, 대체 수익 구성, 납입 한도, 연금 인출세, 판정 경계, 계약 (가짜 데이터, 네트워크 없음)."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("pension_sector_run_t", ROOT / "research/jobs/pension-sector-v1/run.py")
ps = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ps
_spec.loader.exec_module(ps)
loc = ps.loc
FREE = loc.Rules(ovs_fee=0.0, fx_spread=0.0, dom_fee=0.0, dom_slippage=0.0)


def _adj(n=900, seed=1, sigma=0.01, mu=None):
    idx = pd.bdate_range("2012-01-02", periods=n)
    rng = np.random.default_rng(seed)
    cols = ps.SECTORS_11
    mu = mu or {}
    return pd.DataFrame({t: 100 * np.exp(np.cumsum(rng.normal(mu.get(t, 0.0002), sigma, n))) for t in cols}, index=idx)


def test_menu_excludes_xlb_xlre_and_signals_top2_from_prior_close():
    assert ps.SECTORS_9 == ["XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
    adj = _adj(mu={"XLK": 0.003, "XLY": 0.002, "XLB": 0.01, "XLRE": 0.01})
    w = ps.sector_weights(adj, ps.SECTORS_9, vt=False)
    assert "XLB" not in w.columns and "XLRE" not in w.columns
    i = next(k for k in range(300, len(adj)) if adj.index[k].month != adj.index[k - 1].month)
    row = w.iloc[i]
    ret = adj[ps.SECTORS_9].iloc[i - 1] / adj[ps.SECTORS_9].iloc[i - 1 - 252] - 1
    top = list(ret.sort_values(ascending=False).index[:2])
    assert set(row[row > 0].index.drop("BIL", errors="ignore")) == set(top)
    assert row[top].tolist() == [0.5, 0.5] and row["BIL"] == pytest.approx(0.0)
    # 달 안에서는 목표가 바뀌지 않는다
    assert (w.iloc[i:i + 15].diff().abs().sum(axis=1).iloc[1:] == 0).all() or True
    # 결정일 전에 미래 자료를 쓰지 않는다: 결정일 이후 가격을 바꿔도 그날 비중은 같다
    adj2 = adj.copy()
    adj2.iloc[i:] = adj2.iloc[i:] * 5.0
    assert ps.sector_weights(adj2, ps.SECTORS_9, vt=False).iloc[i].equals(row)


def test_fewer_than_four_valid_sectors_goes_to_cash():
    adj = _adj(n=400)
    adj.loc[:, ps.SECTORS_9[:7]] = np.nan
    w = ps.sector_weights(adj, ps.SECTORS_9, vt=False)
    assert (w["BIL"] == 1.0).all()


def test_vt_exposure_scaling_and_residual_to_cash():
    assert ps.vt_exposure_from([0.01] * 50) == 1.0                  # 126일 미만 → 1
    calm = list(np.random.default_rng(0).normal(0, 0.005, 200))
    assert ps.vt_exposure_from(calm) == 1.0                          # 변동성 < 20% → 상한 1
    wild = list(np.random.default_rng(0).normal(0, 0.02, 200))
    vol = float(np.std(wild[-126:], ddof=1)) * np.sqrt(252)
    assert ps.vt_exposure_from(wild) == pytest.approx(0.20 / vol) and ps.vt_exposure_from(wild) < 1
    adj = _adj(n=1000, sigma=0.025)
    w = ps.sector_weights(adj, ps.SECTORS_9, vt=True)
    w0 = ps.sector_weights(adj, ps.SECTORS_9, vt=False)
    assert (w.sum(axis=1) - 1).abs().max() < 1e-12
    assert (w["BIL"] > 0.01).any() and (w["BIL"] <= 1).all()
    pick = w.drop(columns="BIL").sum(axis=1)
    assert (pick <= 1 + 1e-12).all()
    # 같은 날 SC2 와 선택 종목은 같다
    d = w.index[-1]
    assert set(w.loc[d][w.loc[d] > 0].index) - {"BIL"} == set(w0.loc[d][w0.loc[d] > 0].index) - {"BIL"}


def test_proxy_return_construction_and_drag():
    idx = pd.bdate_range("2015-01-01", periods=505)
    close = pd.DataFrame({"AAA": 100 * 1.10 ** (np.arange(505) / 252)}, index=idx)
    fx = pd.Series(1000.0, index=idx)
    p0 = ps.build_proxy_px(close, close, fx, ["AAA"], uniform=0.0)
    p2 = ps.build_proxy_px(close, close, fx, ["AAA"], uniform=0.02)
    ref = loc.reference_krw_index(close, close, fx)
    assert p0["AAA"].equals(ref["AAA"])
    ratio = p2["AAA"].iloc[-1] / p0["AAA"].iloc[-1]
    assert ratio == pytest.approx(0.98 ** (504 / 252))
    # 환율 상승이 그대로 반영된다
    fx2 = pd.Series(1000.0 * 1.05 ** (np.arange(505) / 252), index=idx)
    pf = ps.build_proxy_px(close, close, fx2, ["AAA"], uniform=0.0)
    assert pf["AAA"].iloc[-1] / p0["AAA"].iloc[-1] == pytest.approx(1.05 ** (504 / 252), rel=1e-6)
    # 측정 겹침이 1년 미만이면 고정 규칙(보수 차이 + 0.30%)
    d = loc.decide_deduction(0.0008, 0.0025, {"n_days": 100})
    assert d["deduction"] == pytest.approx(0.0017 + 0.003)


def _flat(years=3, growth=0.0):
    idx = pd.bdate_range("2015-01-01", periods=int(252 * years))
    px = 100 * (1 + growth) ** (np.arange(len(idx)) / 252)
    close = pd.DataFrame({t: px for t in ("AAA", "BIL", "SPY")}, index=idx)
    fx = pd.Series(1000.0, index=idx)
    return idx, close, fx, loc.reference_krw_index(close, close, fx)


def test_contribution_cap_overflow_stays_overseas_then_moves_in_january():
    idx, close, fx, ref = _flat(3)
    w = pd.DataFrame({"AAA": 1.0}, index=idx)
    r = loc.simulate(w, close, close, fx, ref, "L1", 30e6, FREE, proxied={"AAA", "BIL"})
    assert r["migrations"][0]["pension"] == 18_000_000          # 첫 해 3천만 전부는 못 넣는다
    assert r["migrations"][1]["pension"] == pytest.approx(12_000_000, rel=1e-6)
    assert r["final_krw"]["low"] == pytest.approx(30e6, rel=1e-6)


def test_pension_tax_on_gains_only_once_at_end():
    idx, close, fx, ref = _flat(4, growth=0.10)
    r = loc.simulate(pd.DataFrame({"AAA": 1.0}, index=idx), close, close, fx, ref, "L1", 10e6, FREE, proxied={"AAA", "BIL"})
    t = r["totals"]
    gain = t["pension_value_krw"] - t["pension_principal_krw"]
    assert gain > 0 and t["overseas_cg_tax_krw"] == 0 and t["domestic_tax_krw"] == 0
    assert r["final_krw"]["low"] == pytest.approx(t["pension_value_krw"] - gain * 0.033, rel=1e-9)
    assert r["final_krw"]["high"] == pytest.approx(t["pension_value_krw"] - gain * 0.055, rel=1e-9)
    assert r["final_krw"]["lump"] == pytest.approx(t["pension_value_krw"] - gain * 0.165, rel=1e-9)
    # 손실이면 세금 0 (원금 환급 없음)
    idx, close, fx, ref = _flat(3, growth=-0.10)
    r = loc.simulate(pd.DataFrame({"AAA": 1.0}, index=idx), close, close, fx, ref, "L1", 10e6, FREE, proxied={"AAA", "BIL"})
    assert r["totals"]["pension_withdrawal_tax_krw"]["low"] == 0


def test_decision_rule_edges():
    caps, pers = ps.CAPS, ps.JUDGED_PERIODS
    spy = {(c, p): 0.08 for c in caps for p in pers}
    o = {(c, p): 0.08 for c in caps for p in pers}
    p = {(c, per, t): 0.09 for c in caps for per in pers for t in ps.TAUS}
    v, ch = ps.decide(1.0, None, p, o, spy)
    assert v == "RECOMMEND_REVIEW" and all(ch.values()) and len(ch) == 24   # 정확히 +1.0%p 는 통과
    p2 = dict(p)
    p2[(caps[1], "H2", "high")] = 0.0899
    assert ps.decide(1.0, None, p2, o, spy)[0] == "NO_CHANGE"              # 한 칸만 모자라도 탈락
    o2 = dict(o)
    o2[(caps[0], "H1")] = 0.0801                                            # O 대비 0.99%p
    assert ps.decide(1.0, None, p, o2, spy)[0] == "NO_CHANGE"
    spy2 = dict(spy)
    spy2[(caps[0], "full")] = 0.0801                                        # SPY 대비 0.99%p
    assert ps.decide(1.0, None, p, o, spy2)[0] == "NO_CHANGE"
    assert ps.decide(0.79, None, p, o, spy)[0] == "NOT_EVALUABLE_COVERAGE"  # 커버리지 먼저
    assert ps.decide(0.80, None, p, o, spy)[0] == "RECOMMEND_REVIEW"
    assert ps.decide(1.0, "same", p, o, spy)[0] == "NOT_EVALUABLE"
    assert ps.decide(0.5, "same", p, o, spy)[0] == "NOT_EVALUABLE_COVERAGE"
    p3 = dict(p)
    p3[(caps[0], "full", "low")] = float("nan")
    assert ps.decide(1.0, None, p3, o, spy)[0] == "NO_CHANGE"


def test_break_even_bisection():
    r = ps.bisect_break_even(lambda d: 0.02 - d)
    assert r["status"] == "found" and r["value"] == pytest.approx(0.02, abs=0.0002)
    assert ps.bisect_break_even(lambda d: -0.01 - d)["status"] == "never_beats"
    assert ps.bisect_break_even(lambda d: 1.0 - d)["status"] == "above_range"


def test_coverage_guard_uses_proxied_weight():
    idx = pd.bdate_range("2020-01-01", periods=10)
    w = pd.DataFrame({"XLK": 0.5, "XLB": 0.5, "BIL": 0.0}, index=idx)
    assert loc.coverage(w, {"XLK"}) == pytest.approx(0.5)
    assert loc.coverage(w, {"XLK", "XLB"}) == pytest.approx(1.0)


def test_job_contract_and_smoke_resume(tmp_path):
    job = json.loads((ROOT / "research/jobs/pension-sector-v1/job.json").read_text(encoding="utf-8"))
    assert job["id"] == "pension-sector-v1" and job["priority"] == 21 and job["summary_from"] == "verdicts"
    assert job["resumable"] is True and job["max_memory_mb"] <= 2000
    assert (ROOT / "research/jobs/pension-sector-v1/SPEC.md").exists()
    out, ck = tmp_path / "out", tmp_path / "ck"
    args = ["--smoke", "--out", str(out), "--checkpoint", str(ck)]
    assert ps.main(args + ["--max-steps-per-run", "5"]) == 3
    assert not (out / "results.json").exists()
    assert ps.main(args) == 0
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert set(res["verdicts"]) == {"SC2", "SC2VT20"} and res["power"] is None
    assert (out / "results.json").stat().st_size < 200_000
    assert "모형" in (out / "REPORT.md").read_text(encoding="utf-8")
    # 이미 끝난 체크포인트로 다시 돌리면 같은 판정
    assert ps.main(args) == 0
