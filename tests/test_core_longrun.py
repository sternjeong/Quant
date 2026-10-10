"""core-longrun-v1 · synthesis-rnd-v2 규칙 기계 장치(사전 등록 규칙이 의도대로 계산되는지)."""

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _lab():
    if "core_longrun_lab" in sys.modules and hasattr(sys.modules["core_longrun_lab"], "Rule"):
        return sys.modules["core_longrun_lab"]
    spec = importlib.util.spec_from_file_location("core_longrun_lab", ROOT / "research/jobs/core-longrun-v1/lab.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["core_longrun_lab"] = mod
    spec.loader.exec_module(mod)
    return mod


lab = _lab()
SMALL = lab.Rule(lookback=40, sma_window=30, erc_window=70)


def _toy(n=400, k=6, seed=1):
    idx = pd.bdate_range("2001-01-01", periods=n)
    rng = np.random.default_rng(seed)
    rets = pd.DataFrame(rng.normal(0.0005, 0.01, (n, k)) + np.linspace(-0.001, 0.001, k), index=idx,
                        columns=[f"I{j}" for j in range(k)])
    mkt = pd.Series(rng.normal(0.0003, 0.01, n), index=idx)
    return rets, mkt, pd.Series(0.0001, index=idx)


def test_signals_use_only_data_up_to_previous_close():
    rets, mkt, _ = _toy()
    w = lab.target_weights(rets, mkt, SMALL)
    firsts = np.flatnonzero(lab.month_first_mask(rets.index))
    d = firsts[firsts > 200][0]
    r2, m2 = rets.copy(), mkt.copy()
    r2.iloc[d:] = -r2.iloc[d:] * 5 + 0.03 * np.arange(r2.shape[1])  # 순위를 뒤집을 만큼 d 이후를 바꿈
    m2.iloc[d:] = -0.05
    w2 = lab.target_weights(r2, m2, SMALL)
    pd.testing.assert_frame_equal(w.iloc[: d + 1], w2.iloc[: d + 1])
    assert not w.iloc[d:].equals(w2.iloc[d:])
    # 체결은 다음 날: d 의 실제 보유는 지난달 목표
    ex = w.shift(1).fillna(0.0)
    assert (ex.iloc[d] == w.iloc[d - 1]).all()


def test_selection_top4_positive_and_market_filter():
    idx = pd.bdate_range("2001-01-01", periods=120)
    rets = pd.DataFrame({"A": 0.002, "B": 0.0015, "C": 0.001, "D": 0.0005, "E": 0.0001, "F": -0.001}, index=idx)
    up = pd.Series(0.001, index=idx)
    w = lab.target_weights(rets, up, SMALL)
    last = w.iloc[-1]
    assert list(last[last > 0].index) == ["A", "B", "C", "D"] and math.isclose(last.sum(), 1.0)
    # 음의 모멘텀은 빈 슬롯(RF)
    rets2 = rets.copy()
    rets2[["C", "D", "E"]] = -0.001
    last2 = lab.target_weights(rets2, up, SMALL).iloc[-1]
    assert set(last2[last2 > 0].index) == {"A", "B"} and math.isclose(last2.sum(), 0.5)
    # 시장이 200일선(여기선 30일) 아래면 × 0.5
    down = pd.Series(-0.001, index=idx)
    assert math.isclose(lab.target_weights(rets, down, SMALL).iloc[-1].sum(), 0.5)


def test_erc_weights_sum_to_one_and_equalize_risk():
    rets, mkt, _ = _toy(n=300, k=4)
    rets["I0"] *= 3
    er = lab.erc_weights(rets.tail(126))
    w = np.array([er[c] for c in rets.columns])
    assert math.isclose(w.sum(), 1.0, abs_tol=1e-9) and (w > 0).all()
    cov = rets.tail(126).cov().to_numpy()
    rc = w * (cov @ w)
    assert rc.max() / rc.min() < 1.01
    assert er["I0"] < er["I1"]
    # core_lab._erc(가격 창)와 같은 답
    from core import core_lab as cl

    prices = (1 + rets.tail(126)).cumprod()
    prices = pd.concat([pd.DataFrame([[1.0] * 4], columns=rets.columns, index=[rets.index[-127]]), prices])
    ref = cl._erc(prices)
    assert all(math.isclose(ref[c], er[c], abs_tol=1e-9) for c in rets.columns)


def test_erc_strategy_weights_scale_with_picks():
    rets, mkt, _ = _toy()
    mkt[:] = 0.002  # 필터 꺼짐
    w = lab.target_weights(rets, mkt, lab.Rule(lookback=40, sma_window=30, erc_window=70, weighting="erc"))
    eq = lab.target_weights(rets, mkt, SMALL)
    rows = w.iloc[150:]
    assert np.allclose(rows.sum(axis=1), eq.iloc[150:].sum(axis=1))
    assert ((rows > 0) == (eq.iloc[150:] > 0)).all().all()
    assert not np.allclose(rows.to_numpy(), eq.iloc[150:].to_numpy())


def test_strategy_returns_cash_and_costs():
    idx = pd.bdate_range("2001-01-01", periods=4)
    rets = pd.DataFrame({"A": [0.0, 0.01, 0.01, 0.01]}, index=idx)
    rf = pd.Series(0.001, index=idx)
    w = pd.DataFrame({"A": [0.5, 0.5, 0.0, 0.0]}, index=idx)
    r = lab.strategy_returns(rets, rf, w, bps=10)
    assert math.isclose(r.iloc[0], 0.001)
    assert math.isclose(r.iloc[1], 0.5 * 0.01 + 0.5 * 0.001 - 0.5 * 0.001)
    assert math.isclose(r.iloc[3], 0.001 - 0.5 * 0.001)


def test_episode_detection_from_market_only():
    path = [100, 130, 110, 90, 100, 120, 125, 105, 110, 80]
    lvl = pd.Series(path, index=pd.bdate_range("2001-01-01", periods=len(path)), dtype=float)
    eps = lab.market_episodes(lvl)
    assert len(eps) == 2
    assert eps[0]["peak"] == lvl.index[1] and eps[0]["trough"] == lvl.index[3] and not eps[0]["ongoing"]
    assert math.isclose(eps[0]["depth"], 90 / 130 - 1)
    assert eps[1]["peak"] == lvl.index[6] and eps[1]["trough"] == lvl.index[9] and eps[1]["ongoing"]
    assert lab.market_episodes(pd.Series([100, 90, 95, 85.0], index=lvl.index[:4])) == []  # −15% 는 국면 아님
    strat = pd.Series(0.0, index=lvl.index)
    rows = lab.episode_rows(strat, lvl.pct_change().fillna(0.0), eps)
    assert all(r["defended"] and r["strategy_dd"] == 0.0 for r in rows)


def test_memmel_sanity():
    rng = np.random.default_rng(0)
    a = rng.normal(0.01, 0.04, 1000)
    z0 = lab.memmel_test(a, a)
    assert z0["z"] == 0.0 and math.isclose(z0["p_one_sided"], 0.5)
    b = a * 0.5 + rng.normal(0.0, 0.03, 1000) - 0.005
    hi = lab.memmel_test(a, b)
    lo = lab.memmel_test(b, a)
    assert hi["p_one_sided"] < 0.05 and lo["p_one_sided"] > 0.95 and math.isclose(hi["z"], -lo["z"])
    # 손 계산: V = (2 − 2ρ + ½(SR1² + SR2² − 2·SR1·SR2·ρ²)) / T
    s1, s2, rho = hi["sr1"], hi["sr2"], hi["rho"]
    v = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / 1000
    assert math.isclose(hi["z"], (s1 - s2) / math.sqrt(v))


def test_blend_annual_rebalance():
    idx = pd.bdate_range("2001-12-27", "2002-01-04")
    a = pd.Series(0.10, index=idx)
    b = pd.Series(0.0, index=idx)
    r = lab.blend_returns(a, b, 0.5, bps=0)
    assert math.isclose(r.iloc[0], 0.05)
    assert r.iloc[1] > 0.05  # 흘러가며 a 비중이 커짐
    first_2002 = list(idx.year).index(2002)
    assert math.isclose(r.iloc[first_2002 + 1], 0.05)  # 그해 첫 거래일 종가에 50/50 으로 돌아옴
    assert np.allclose(lab.blend_returns(a, b, 1.0, bps=10), a)


def test_core_verdict_mapping():
    T, F = True, False
    v = lambda h1, h2, h3, h4: lab.core_verdict({"H1_low_beta": h1, "H2_positive_alpha": h2, "H3_crisis_defense": h3, "H4_alpha_stability": h4})
    assert v(T, T, T, T) == "CORE_IDENTITY_CONFIRMED"
    assert v(T, F, T, T) == "PARTIAL" and v(T, F, T, F) == "PARTIAL" and v(T, T, T, F) == "PARTIAL"
    assert v(F, T, T, T) == "NOT_CONFIRMED" and v(T, T, None, T) == "NOT_CONFIRMED"


def test_clean_industry_and_french_datasets():
    from core import french_factors as ff

    assert {"ind12_daily", "ind49_daily", "ff3_daily"} <= set(ff.DATASETS)
    text = ("header\n\n  Average Value Weighted Returns -- Daily\n,Agric,Soda\n19260701,   0.56, -99.99\n19260702,   0.29,   1.00\n"
            "\n  Average Equal Weighted Returns -- Daily\n,Agric,Soda\n19260701,   9.00,   9.00\n")
    df = ff.parse_french_csv(text)
    assert len(df) == 2 and math.isclose(df.iloc[0, 0], 0.0056) and math.isnan(df.iloc[0, 1])
    raw = pd.DataFrame({"X": [np.nan, 0.01, np.nan, 0.02]})
    assert lab.clean_industry(raw)["X"].tolist()[1:] == [0.01, 0.0, 0.02] and math.isnan(lab.clean_industry(raw)["X"][0])


@pytest.mark.parametrize("job_id", ["core-longrun-v1", "synthesis-rnd-v2"])
def test_job_definitions_valid(job_id):
    from core import research_jobs as rj

    data = json.loads((ROOT / "research/jobs" / job_id / "job.json").read_text(encoding="utf-8"))
    job, err = rj.validate_job(data, job_id, ROOT)
    assert job is not None, err


@pytest.mark.parametrize("job_id,keys", [
    ("core-longrun-v1", {"H1_low_beta", "H2_positive_alpha", "H3_crisis_defense", "H4_alpha_stability", "core_identity"}),
    ("synthesis-rnd-v2", {"a_sharpe_memmel", "b_return_per_mdd", "c_mdd_5pp", "d_subperiod_sharpe", "blend_50_50"}),
])
def test_smoke_runs_offline(tmp_path, job_id, keys):
    p = subprocess.run([sys.executable, str(ROOT / "research/jobs" / job_id / "run.py"), "--smoke",
                        "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-1500:]
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert res["smoke"] and keys <= set(res["verdicts"]) and res["power"]["n_trials"] == 1
    assert "검정력(사전 계산)" in (tmp_path / "o" / "REPORT.md").read_text(encoding="utf-8")
