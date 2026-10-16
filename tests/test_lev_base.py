import importlib.util
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core import research_jobs as rj

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("lev_base_v1", ROOT / "research/jobs/lev-base-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = _load()


# --- 합성 2배 수익 ---------------------------------------------------------------------------------

def test_synthetic_2x_return_math():
    idx = pd.bdate_range("2020-01-01", periods=3)
    r = pd.Series([0.0, 0.01, -0.02], index=idx)
    fin = pd.Series([0.0001, 0.0002, 0.0], index=idx)
    got = m.synthetic_2x_returns(r, fin)
    exp = 2 * r - (fin + 0.01 / 252) - 0.009 / 252
    assert np.allclose(got.to_numpy(), exp.to_numpy())
    assert got.iloc[1] == pytest.approx(0.02 - 0.0002 - 0.01 / 252 - 0.009 / 252)


# --- 완충 필터 상태 기계 ---------------------------------------------------------------------------

def test_buffered_state_band_no_flip():
    idx = pd.bdate_range("2021-01-04", periods=120)
    c = pd.Series(100.0, index=idx)
    # 1.01 배(띠 안)는 꺼짐 상태를 켜지 못한다
    c.iloc[10:] = 101.0
    st = m.buffered_state(c, window=5)
    assert not st.any()
    # 1.03 배로 뛰면 다음 월초에 켜짐
    c2 = c.copy()
    c2.iloc[30:] = 103.0  # SMA 는 곧 103 으로 따라오므로 짧은 창에서는 그다음 월초 평가 때 띠 안
    st2 = m.buffered_state(c2, window=200)
    assert not st2.any()  # SMA200 없으면 평가 안 함 → 꺼짐 유지


def test_buffered_state_hysteresis():
    idx = pd.bdate_range("2021-01-04", "2021-08-31")
    flags = m.month_first_flags(idx)
    firsts = idx[flags]
    c = pd.Series(100.0, index=idx)
    sma_win = 3

    def set_prior(day, val):
        # 월 첫날 전 3 거래일을 val 로 → 전일 종가 = SMA = val … 대신 전일만 바꿔 비율을 만든다
        i = idx.get_loc(day)
        c.iloc[i - 1] = val

    # 기본 100. 전일 종가 x, SMA ≈ (100+100+x)/3
    set_prior(firsts[1], 104.0)    # 104 / 101.33 = 1.026 > 1.02 → 켜짐
    set_prior(firsts[2], 100.9)    # 100.9/100.3 ≈ 1.006 띠 안 → 유지(켜짐)
    set_prior(firsts[3], 99.0)     # 99/99.67 ≈ 0.993 띠 안 → 유지(켜짐)
    set_prior(firsts[4], 97.0)     # 97/99 = 0.980 → 경계: 0.98 미만 아님(97/99=0.9798 <0.98) → 꺼짐
    set_prior(firsts[5], 101.0)    # 101/100.33 ≈ 1.007 띠 안 → 유지(꺼짐)
    st = m.buffered_state(c, window=sma_win)
    s = st.loc[firsts]
    assert list(s.to_numpy()) == [False, True, True, True, False, False, False, False][:len(s)]
    # 월 첫날 사이에는 바뀌지 않는다
    for i in range(1, len(idx)):
        if not flags[i]:
            assert st.iloc[i] == st.iloc[i - 1]


def test_state_uses_prior_close_only():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2015-01-01", periods=900)
    c = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, 900))), index=idx)
    base = m.buffered_state(c)
    d = idx[600]
    c2 = c.copy()
    c2.iloc[600:] = c2.iloc[600:] * 0.3   # 그날 종가부터 폭락시켜도 그날까지 상태 불변
    assert (m.buffered_state(c2).loc[:d] == base.loc[:d]).all()


# --- 필터는 2배 다리에만, 1월 재조정 ------------------------------------------------------------------

def _panel(n=600, seed=4):
    idx = pd.bdate_range("2019-01-01", periods=n)
    rng = np.random.default_rng(seed)
    spy = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    adj = pd.DataFrame({m.SPY: spy, m.BIL: 90 + np.arange(n) * 0.002}, index=idx)
    r = adj[m.SPY].pct_change().fillna(0.0)
    adj[m.X2] = 100 * (1 + m.synthetic_2x_returns(r, adj[m.BIL].pct_change().fillna(0.0))).cumprod()
    return idx, adj


def test_filter_only_on_lev_leg_and_january_reset():
    idx, adj = _panel()
    state = pd.Series(False, index=idx)
    state.loc["2019-06-03":"2019-12-31"] = True
    state.loc["2020-04-01":] = True
    w, info = m.portfolio_weights(idx, adj, 0.25, True, state)
    # SPY 슬리브는 꺼짐에도 그대로 남는다 / 다리는 꺼짐이면 BIL, 켜짐이면 2배
    off_day, on_day = pd.Timestamp("2019-03-01"), pd.Timestamp("2019-08-01")
    assert w.loc[off_day, m.SPY] == pytest.approx(0.75, abs=1e-6)
    assert w.loc[off_day].get(m.X2, 0.0) == pytest.approx(0.0)
    assert w.loc[off_day, m.BIL] == pytest.approx(0.25, abs=1e-6)
    assert w.loc[on_day, m.X2] > 0.2 and w.loc[on_day, m.BIL] == pytest.approx(0.0, abs=1e-9)
    # 1월 첫 거래일에 목표 비중으로 재조정(그날 상태 꺼짐 → BIL 25%)
    jan = pd.Timestamp("2020-01-01")  # bdate_range 의 1월 첫 거래일
    assert w.loc[jan, m.SPY] == pytest.approx(0.75, abs=1e-6) and w.loc[jan, m.BIL] == pytest.approx(0.25, abs=1e-6)
    assert "2020-01-01" in info["reset_days"]
    # 전환일(2019-06-03)에는 SPY 를 매매하지 않는다(표류값 유지) — 직전 목표와 달라도 실제 보유 비중과 같음
    sw = pd.Timestamp("2019-06-03")
    lev = w.loc[sw, m.X2]
    assert w.loc[sw, m.BIL] == pytest.approx(0.0, abs=1e-12)
    assert abs(w.loc[sw, m.SPY] + lev - 1.0) < 1e-6
    # 1월·전환일 외에는 목표가 바뀌지 않는다
    chg = w.diff().abs().sum(axis=1) > 1e-9
    allowed = {pd.Timestamp("2019-06-03"), pd.Timestamp("2020-01-01"), pd.Timestamp("2020-04-01"), idx[0]}
    allowed |= {d for d in idx if str(d.date()) in info["reset_days"]}
    state_chg = set(idx[np.r_[False, state.to_numpy()[1:] != state.to_numpy()[:-1]]])
    assert set(idx[chg.to_numpy()]) <= allowed | state_chg


def test_unfiltered_never_holds_bil():
    idx, adj = _panel()
    w, _ = m.portfolio_weights(idx, adj, 0.25, False, pd.Series(False, index=idx))
    assert m.BIL not in w.columns or (w[m.BIL] == 0).all()


def test_long_run_path_filter_and_costs():
    idx = pd.bdate_range("1926-07-01", "1930-12-31")
    rng = np.random.default_rng(2)
    mkt = pd.Series(rng.normal(0.0003, 0.01, len(idx)), index=idx)
    mkt.loc["1929-10-01":"1930-12-31"] = -0.003
    rf = pd.Series(0.0001, index=idx)
    p = m.long_run_path(mkt, rf, 0.25, True, start="1927-07-01", end="1930-12-31")
    unf = m.long_run_path(mkt, rf, 0.25, False, start="1927-07-01", end="1930-12-31")
    assert p["switches_per_year"] > 0 and p["time_on"] < 1.0
    assert unf["switches_per_year"] == 0 and unf["time_on"] == 1.0
    # 폭락기에 필터가 다리를 RF 로 빼면 필터 없는 쪽보다 1930 손실이 작다
    r1930 = lambda r: float((1 + r[r.index.year == 1930]).prod() - 1)  # noqa: E731
    assert r1930(p["returns"]) > r1930(unf["returns"])
    # 비용 0 이면 수익이 같거나 크다
    p0 = m.long_run_path(mkt, rf, 0.25, True, start="1927-07-01", end="1930-12-31", bps=0.0)
    assert (1 + p0["returns"]).prod() >= (1 + p["returns"]).prod()


# --- 판정 경계 ------------------------------------------------------------------------------------

def _ok_inputs():
    long = {"cagr": 0.110, "mkt_cagr": 0.100, "mdd": -0.80, "mkt_mdd": -0.80, "worst12": -0.70, "mkt_worst12": -0.65, "sub_beats": 3}
    etf = {"cagr": 0.125, "spy_cagr": 0.120, "h1": 0.10, "spy_h1": 0.099, "h2": 0.15, "spy_h2": 0.149,
           "mdd": -0.33, "spy_mdd": -0.30, "ci_low": -0.0049}
    return long, etf


def test_judge_pass_at_edges():
    long, etf = _ok_inputs()
    v, c = m.judge(long, etf)
    assert v == m.PASS and all(c.values())


@pytest.mark.parametrize("key,where,val", [
    ("cagr", "long", 0.1099), ("mdd", "long", -0.8001), ("worst12", "long", -0.7001), ("sub_beats", "long", 2),
    ("cagr", "etf", 0.1249), ("h1", "etf", 0.099), ("h2", "etf", 0.149), ("mdd", "etf", -0.3301), ("ci_low", "etf", -0.005)])
def test_judge_fail_just_beyond_edge(key, where, val):
    long, etf = _ok_inputs()
    (long if where == "long" else etf)[key] = val
    v, _ = m.judge(long, etf)
    assert v == m.FAIL


def test_judge_noop_and_nan():
    long, etf = _ok_inputs()
    assert m.judge(long, etf, "noop")[0] == m.NOT_EVALUABLE
    etf["ci_low"] = float("nan")
    assert m.judge(long, etf)[0] == m.NOT_EVALUABLE


# --- 작업 계약 -------------------------------------------------------------------------------------

def test_job_contract_and_fixed_constants():
    cfg = rj.Config.for_root(ROOT)
    valid, invalid = rj.load_job_definitions(cfg)
    assert "lev-base-v1" not in invalid, invalid.get("lev-base-v1")
    job = valid["lev-base-v1"]
    assert job.priority == 15 and job.resumable is True and job.max_memory_mb <= 2000
    assert job.summary_from == "verdicts" and list(job.outputs) == ["results.json", "REPORT.md"]
    assert (ROOT / "research/jobs/lev-base-v1/SPEC.md").is_file()
    assert m.JUDGED == ("L10F", "L15F", "L25F") and m.N_TRIALS == 3
    assert (m.FIN_SPREAD, m.FEE, m.BAND_ON, m.BAND_OFF, m.SMA_WIN) == (0.010, 0.009, 1.02, 0.98, 200)
    assert (m.N_BOOT, m.BLOCK_DAYS, m.BOOT_SEED) == (1000, 126, 20261024)
    assert m.WINDOWS["judged"] == ("2010-01-04", "2024-09-30") and m.WINDOWS["h1"][1] == "2017-05-31"
    assert (m.LONG_START, m.LONG_END, m.LONG_COST_BPS) == ("1927-07-01", "2007-12-31", 10.0)


def test_smoke_resume_3_then_0():
    with tempfile.TemporaryDirectory() as td:
        out, ck = Path(td) / "out", Path(td) / "ck"
        args = ["--smoke", "--out", str(out), "--checkpoint", str(ck)]
        assert m.main(args + ["--max-sims-per-run", "4"]) == 3
        assert not (out / "results.json").exists()
        assert m.main(args) == 0
        res = json.loads((out / "results.json").read_text(encoding="utf-8"))
        assert set(res["verdicts"]) == {"L10F", "L15F", "L25F"}
        assert all(res["smoke_coverage"].values())
        assert "power" in res and "etf_era" in res["power"] and "long_run" in res["power"]
        assert (out / "results.json").stat().st_size < 200_000
        assert (out / "REPORT.md").read_text(encoding="utf-8").startswith("# SPY 바탕")
