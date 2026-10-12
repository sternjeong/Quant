import importlib.util
import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from core import research_jobs as rj
from core import research_power as rp
from core import tax_fx as tx

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("drawdown_cheap_v1", ROOT / "research/jobs/drawdown-cheap-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = _load()


def _series(n=600, seed=3, start="2019-01-01"):
    idx = pd.bdate_range(start, periods=n)
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n))), index=idx)


# --- 신호: 룩어헤드 없음 ------------------------------------------------------------------------------------

def test_trend_exposure_uses_only_prior_close():
    c = _series()
    base = m.trend_exposure(c, 100)
    # 어느 날의 종가를 바꿔도 그날과 그 이전의 노출은 변하지 않는다(그날 종가는 다음 날부터 영향)
    d = c.index[300]
    c2 = c.copy()
    c2.iloc[300] *= 0.2
    alt = m.trend_exposure(c2, 100)
    assert (base.loc[:d] == alt.loc[:d]).all()
    # 미래 가격 전체를 바꿔도 과거 노출 동일
    c3 = c.copy()
    c3.iloc[301:] = 1.0
    assert (m.trend_exposure(c3, 100).loc[:d] == base.loc[:d]).all()


def test_trend_exposure_hand_built():
    idx = pd.bdate_range("2020-01-01", periods=70)
    # 처음 30 거래일 상승(종가 > SMA), 이후 하락
    vals = np.concatenate([np.linspace(100, 130, 35), np.linspace(130, 60, 35)])
    c = pd.Series(vals, index=idx)
    e = m.trend_exposure(c, 10)
    flag = m.month_first_flags(idx)
    # 월 첫 거래일이 아닌 날은 직전 월 첫날 값을 유지
    for i in range(1, len(idx)):
        if not flag.iloc[i]:
            assert e.iloc[i] == e.iloc[i - 1]
    # 상승 구간의 월 첫날(2020-02-03): 전일 종가 > SMA → 1.0 ; 하락이 충분히 진행된 3월 첫날 → 0.0
    assert e.loc["2020-02-03"] == 1.0
    assert e.loc["2020-03-02"] == 0.0
    # 이동평균을 못 구하는 초반은 보유(1.0)
    assert (e.iloc[:5] == 1.0).all()


def test_trend_signal_is_strict_greater_and_prior_day():
    idx = pd.bdate_range("2021-01-27", periods=6)  # 1/27 수, 1/28 목, 1/29 금, 2/1 월(월 첫 거래일) ...
    c = pd.Series([10, 10, 10, 10, 20, 20.0], index=idx)
    e = m.trend_exposure(c, 3)
    # 2/1 신호는 1/29 종가(10) vs SMA(10,10,10)=10 → 같으면 보유 아님(엄격히 큰 경우만)
    assert e.loc["2021-02-01"] == 0.0
    assert e.loc["2021-02-02"] == 0.0  # 2/1 종가 급등은 다음 월초까지 영향 없음(월별 갱신)


def test_vol_target_math_and_cap():
    idx = pd.bdate_range("2020-01-01", periods=200)
    sign = np.where(np.arange(200) % 2 == 0, 1.0, -1.0)
    r = pd.Series(0.01 * sign, index=idx)       # 일별 ±1% → 표준편차 ≈ 0.01 → 연율 ≈ 15.9%
    vol = r.iloc[100:163].std(ddof=1) * math.sqrt(252)
    e = m.vol_target_exposure(r, 0.10, 63)
    flag = m.month_first_flags(idx)
    d = idx[flag.to_numpy() & (np.arange(200) >= 100)][0]
    i = idx.get_loc(d)
    expect_vol = r.iloc[i - 63:i].std(ddof=1) * math.sqrt(252)   # 전일까지 63개
    assert abs(e.loc[d] - min(1.0, 0.10 / expect_vol)) < 1e-12
    assert 0 < e.loc[d] < 1.0 and vol > 0.10
    # 목표가 변동성보다 크면 노출은 1 로 자름
    assert (m.vol_target_exposure(r, 0.50, 63).iloc[70:] == 1.0).all()
    # 변동성 0 이면 1.0, 기록 부족한 초반도 1.0
    flat = pd.Series(0.0, index=idx)
    assert (m.vol_target_exposure(flat, 0.10).iloc[:] == 1.0).all()
    assert (e.iloc[:60] == 1.0).all()


def test_vol_target_no_lookahead():
    idx = pd.bdate_range("2020-01-01", periods=200)
    rng = np.random.default_rng(5)
    r = pd.Series(rng.normal(0, 0.01, 200), index=idx)
    base = m.vol_target_exposure(r, 0.10)
    r2 = r.copy()
    r2.iloc[120] = 0.5   # 120 번째 날의 큰 수익은 120 번째 날 노출까지 영향 없음
    alt = m.vol_target_exposure(r2, 0.10)
    assert (base.iloc[:121] == alt.iloc[:121]).all()


# --- 비중: 연 재조정 ------------------------------------------------------------------------------------------

def test_static_weights_trade_only_on_year_first_days():
    idx = pd.bdate_range("2019-01-01", "2022-12-31")
    w = m.static_weights(idx, m.B4_WEIGHTS)
    change = w.diff().abs().sum(axis=1) > 1e-9
    assert set(idx[change]) == set(idx[m.year_first_flags(idx)].tolist()[1:])  # 첫 해 첫날은 tx.simulate 가 항상 매수
    assert (w.sum(axis=1) <= 1.0 + 1e-12).all()
    assert abs(w.iloc[10]["SPY"] - 0.8) < 1e-6


def test_blend_resets_sleeve_ratio_only_on_year_first_day():
    idx = pd.bdate_range("2019-01-01", "2021-12-31")
    n = len(idx)
    spy_ret = pd.Series(0.001, index=idx)      # SPY 는 계속 오른다
    core_ret = pd.Series(0.0, index=idx)
    # 코어는 매달 첫날 비중이 BIL<->TLT 로 바뀐다
    core_w = pd.DataFrame(0.0, index=idx, columns=["TLT", "BIL"])
    mon = m.month_first_flags(idx)
    flip = mon.cumsum() % 2
    core_w["TLT"] = flip.astype(float)
    core_w["BIL"] = 1.0 - flip
    w = m.blend_weights(spy_ret, core_ret, core_w, 0.85)
    assert abs(w.iloc[0]["SPY"] - 0.85) < 1e-6
    yfirst = m.year_first_flags(idx)
    # 연 첫날: 85% 로 되돌아간다. 그 사이 코어가 바뀌는 날의 SPY 는 표류한 비중(> 85%)이고 연 중에는 다시 85% 로 돌아가지 않는다
    spy_w = w["SPY"].round(4)
    for d in idx[yfirst][1:]:
        assert abs(w.loc[d, "SPY"] - 0.85) < 1e-5
    mid = w.loc["2019-07-01":"2019-12-31", "SPY"]
    assert (mid > 0.85).all() and mid.is_monotonic_increasing
    assert spy_w.loc["2019-12-30"] > spy_w.loc["2019-02-01"]
    assert (w.sum(axis=1) <= 1.0 + 1e-12).all() and n == len(w)


# --- 판정 규칙 ----------------------------------------------------------------------------------------------

POWER = rp.power_report(14.7, 7)


def _etf(**kw):
    base = dict(cagr=0.141, spy_cagr=0.151, h1=0.085, spy_h1=0.100, h2=0.19, spy_h2=0.20, mdd=-0.20, spy_mdd=-0.30)
    base.update(kw)
    return base


def _long(**kw):
    base = dict(cagr=0.100, mkt_cagr=0.105, mdd=-0.50, mkt_mdd=-0.80)
    base.update(kw)
    return base


def test_pass_rule_boundaries():
    j = m.judge_candidate
    assert j("B1_200", _etf(), _long(), None, 0.1, POWER)["verdict"] == "PASS_FORWARD_CANDIDATE"
    # (i) 정확히 −1.0%p 는 통과, 조금 넘으면 FAIL
    assert j("B1_200", _etf(cagr=0.141), _long(), None, 0.1, POWER)["checks"]["i_judged_return_within_1.0pp"]
    assert j("B1_200", _etf(cagr=0.1409), _long(), None, 0.1, POWER)["verdict"].startswith("FAIL")
    # (ii) 각 절반 −1.5%p
    assert j("B1_200", _etf(h1=0.085), _long(), None, 0.1, POWER)["verdict"] == "PASS_FORWARD_CANDIDATE"
    assert j("B1_200", _etf(h1=0.0849), _long(), None, 0.1, POWER)["verdict"].startswith("FAIL")
    assert j("B1_200", _etf(h2=0.1849), _long(), None, 0.1, POWER)["verdict"].startswith("FAIL")
    # (iii) MDD 크기 ≤ SPY 의 70%
    assert j("B1_200", _etf(mdd=-0.21), _long(), None, 0.1, POWER)["verdict"] == "PASS_FORWARD_CANDIDATE"
    assert j("B1_200", _etf(mdd=-0.2101), _long(), None, 0.1, POWER)["verdict"].startswith("FAIL")
    # (iv) 장기: CAGR −1.0%p, MDD 70%
    assert j("B1_200", _etf(), _long(cagr=0.095), None, 0.1, POWER)["verdict"] == "PASS_FORWARD_CANDIDATE"
    assert j("B1_200", _etf(), _long(cagr=0.0949), None, 0.1, POWER)["verdict"].startswith("FAIL")
    assert j("B2_10", _etf(), _long(mdd=-0.56), None, 0.1, POWER)["verdict"] == "PASS_FORWARD_CANDIDATE"
    assert j("B2_10", _etf(), _long(mdd=-0.5601), None, 0.1, POWER)["verdict"].startswith("FAIL")
    # NaN 은 통과 못 함
    assert j("B1_100", _etf(cagr=float("nan")), _long(), None, 0.1, POWER)["verdict"].startswith("FAIL")


def test_long_run_not_applicable_for_blends_and_static():
    j = m.judge_candidate
    for name in ("B3_85", "B3_70", "B4"):
        r = j(name, _etf(), None, None, 0.1, POWER)
        assert r["verdict"] == "PASS_ETF_ONLY" and r["long_run"] == "NOT_APPLICABLE"
        assert "iv_long_cagr_within_1.0pp" not in r["checks"]
        assert j(name, _etf(mdd=-0.25), None, None, 0.1, POWER)["verdict"].startswith("FAIL")
    # 장기 자료가 없는 B1/B2 는 PASS 가 될 수 없다
    assert j("B1_200", _etf(), None, None, 0.1, POWER)["verdict"] == "NOT_EVALUABLE"


def test_fail_kind_and_noop():
    j = m.judge_candidate
    bad = _etf(mdd=-0.29)
    assert j("B4", bad, None, None, -0.2, POWER)["verdict"] == "FAIL"              # 관측 IR ≤ 0
    assert j("B4", bad, None, None, 0.1, POWER)["verdict"] == "FAIL_UNDERPOWERED"  # 0 < IR < MDE
    assert j("B4", bad, None, None, POWER["mde_ir"] + 0.1, POWER)["verdict"] == "FAIL"
    assert j("B4", _etf(), None, "같음", 0.1, POWER)["verdict"] == "NOT_EVALUABLE"
    assert rp.noop_guard(np.zeros(100)) is not None


def test_efficiency():
    e = m.efficiency(0.02, 0.10)
    assert abs(e["pp_per_pp"] - 0.2) < 1e-9 and abs(e["giveup_pp"] - 2.0) < 1e-9
    assert m.efficiency(0.02, 0.0)["pp_per_pp"] is None
    assert m.efficiency(None, 0.1)["pp_per_pp"] is None


# --- 장기 경로 -------------------------------------------------------------------------------------------------

def test_long_run_returns_cost_and_lag():
    idx = pd.bdate_range("2000-01-03", periods=10)
    mkt = pd.Series(0.01, index=idx)
    rf = pd.Series(0.001, index=idx)
    e = pd.Series([1, 1, 1, 0, 0, 0, 1, 1, 1, 1.0], index=idx)
    r = m.long_run_returns(mkt, rf, e, bps=10.0)
    assert abs(r.iloc[3] - 0.01) < 1e-12            # e(t-1)=1 → 당일 시장 수익
    assert abs(r.iloc[4] - (0.001 - 2 * 10 / 1e4)) < 1e-12  # 전환 다음 날: RF 수익 − 비용
    assert abs(r.iloc[5] - 0.001) < 1e-12
    full = m.long_run_returns(mkt, rf, pd.Series(1.0, index=idx))
    assert (full == 0.01).all()


def test_long_run_table_runs_on_synthetic():
    d = m.lab.synthetic_data(end="1960-12-31")
    t = m.long_run_table(d["mkt"], d["rf"])
    assert set(m.LONG_APPLICABLE) <= set(t)
    assert all(math.isfinite(t[k]["cagr"]) for k in t)


# --- 세금 엔진 = tax_fx ------------------------------------------------------------------------------------------

def test_sim_equals_tax_fx_on_spy_buy_and_hold():
    close = pd.DataFrame({"SPY": _series(400, 8), "BIL": 90 + np.arange(400) * 0.01}, index=_series(400, 8).index)
    fx = pd.Series(1200 + np.arange(400) * 0.1, index=close.index)
    w = pd.DataFrame({"SPY": 1.0}, index=close.index)
    ours = m.run_sim(w, close, close.copy(), fx, 30_000_000)
    ref = tx.simulate(w, close, close.copy(), fx, tx.AccountConfig(initial_krw=30_000_000))
    assert abs(ours["final_liq_krw"] - ref["final_after_liquidation_krw"]) < 1e-6
    assert abs(ours["mdd_after"] - ref["mdd_after"]) < 1e-12
    pd.testing.assert_series_equal(ours["values"], ref["values_krw"])
    years = (close.index[-1] - close.index[0]).days / 365.25
    assert abs(ours["cagr_after"] - ((ref["final_after_liquidation_krw"] / 30_000_000) ** (1 / years) - 1)) < 1e-12


def test_forced_rebalance_trades_in_tax_engine():
    idx = pd.bdate_range("2019-01-01", "2021-12-31")
    rng = np.random.default_rng(1)
    close = pd.DataFrame({"SPY": 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.01, len(idx)))),
                          "TLT": 100 * np.exp(np.cumsum(rng.normal(0.0001, 0.006, len(idx))))}, index=idx)
    fx = pd.Series(1100.0, index=idx)
    res = m.run_sim(m.static_weights(idx, {"SPY": 0.5, "TLT": 0.5}), close, close.copy(), fx, 30_000_000)
    assert res["trades_per_year"] >= 1.0 and res["fees_krw"] > 0


# --- 작업 계약 ---------------------------------------------------------------------------------------------------

def test_job_contract_valid_and_fixed_constants():
    cfg = rj.Config.for_root(ROOT)
    valid, invalid = rj.load_job_definitions(cfg)
    assert "drawdown-cheap-v1" not in invalid, invalid.get("drawdown-cheap-v1")
    job = valid["drawdown-cheap-v1"]
    assert job.priority == 21 and job.resumable is True and job.max_memory_mb <= 2000
    assert job.summary_from == "verdicts" and list(job.outputs) == ["results.json", "REPORT.md"]
    assert (ROOT / "research/jobs/drawdown-cheap-v1/SPEC.md").is_file()
    assert m.CANDIDATES == ["B1_100", "B1_200", "B2_10", "B2_12", "B3_85", "B3_70", "B4"] and m.N_TRIALS == 7
    assert (m.MAX_GIVEUP_JUDGED, m.MAX_GIVEUP_HALF, m.MDD_RATIO_MAX) == (0.010, 0.015, 0.70)
    assert m.WINDOWS["judged"] == ("2010-01-04", "2024-09-30") and (m.LONG_START, m.LONG_END) == ("1927-07-01", "2007-12-31")


def test_smoke_resume_3_then_0():
    with tempfile.TemporaryDirectory() as td:
        out, ck = Path(td) / "out", Path(td) / "ck"
        args = ["--smoke", "--out", str(out), "--checkpoint", str(ck)]
        assert m.main(args + ["--max-sims-per-run", "5"]) == 3
        assert not (out / "results.json").exists()
        assert m.main(args) == 0
        assert (out / "results.json").is_file() and (out / "REPORT.md").is_file()
