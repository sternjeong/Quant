"""mom-lowturn-v1 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("mom_lowturn_v1", ROOT / "research/jobs/mom-lowturn-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()
sc = mod.sc


def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "mom-lowturn-v1" in valid, invalid.get("mom-lowturn-v1")
    job = json.loads((ROOT / "research/jobs/mom-lowturn-v1/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 18 and job["resumable"] is True and job["max_memory_mb"] <= 2000
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert (ROOT / "research/jobs/mom-lowturn-v1/SPEC.md").exists()


def test_pre_registered_constants():
    assert len(mod.CELLS) == 18 and mod.CELLS[0] == "M0" and len(set(mod.CELLS)) == 18
    assert mod.N_TRIALS == 17 and mod.POWER_YEARS == 41 and mod.K == 2 and mod.SIGNAL == "RS12"
    assert mod.BUFFERS == (None, 3, 4) and mod.FREQS == ("monthly", "quarterly", "annual") and mod.HARVEST == (False, True)
    assert mod.WINDOWS["selection"] == ("1927-07-01", "1966-12-31")
    assert mod.WINDOWS["confirmation"] == ("1967-01-01", "2007-12-31")
    assert (mod.M0_MARGIN, mod.MKT_MARGIN, mod.WORST_SLACK, mod.WORST_ROWS) == (0.005, 0.010, 0.05, 252)
    assert (mod.TAX_INITIAL_KRW, mod.TAX_FX_CONST, mod.COST_BPS) == (30_000_000, 1300.0, 10.0)
    assert mod.ETF_WINDOW == ("2000-01-01", "2024-09-30") and mod.ETF_SPY_MARGIN == 0.005
    m0 = mod.SPEC_BY_ID["M0"]
    assert m0["buffer"] is None and m0["freq"] == "monthly" and not m0["harvest"] and m0["reset"] == "always"
    assert all(mod.SPEC_BY_ID[c]["reset"] == "on_change" for c in mod.CELLS if c != "M0")


# --- 완충 ---------------------------------------------------------------------------------------

def test_buffer_keep_and_replace():
    s = np.array([10.0, 9.0, 8.0, 7.0, 6.0, 5.0])       # 순위: 0,1,2,3,4,5
    assert sorted(mod.choose(s, [], None)) == [0, 1]
    assert sorted(mod.choose(s, [2, 3], None)) == [0, 1]       # 완충 없음 → 언제나 상위 2
    assert sorted(mod.choose(s, [2, 3], 3)) == [0, 2]          # 3위 유지, 4위 교체 → 빈 자리는 1위
    assert sorted(mod.choose(s, [2, 3], 4)) == [2, 3]          # 3·4위 모두 상위 4 안 → 그대로
    assert sorted(mod.choose(s, [4, 1], 4)) == [0, 1]          # 5위는 밖 → 보유하지 않은 최고 순위(1위)로
    assert sorted(mod.choose(s, [5, 4], 3)) == [0, 1]
    s2 = s.copy()
    s2[2] = np.nan                                             # 보유 산업 점수 없음 → 교체
    assert sorted(mod.choose(s2, [2, 0], 4)) == [0, 1]
    few = np.array([1.0, 2.0, 3.0, np.nan, np.nan, np.nan])     # 유효 3 < 2K → 시장
    assert mod.choose(few, [0, 1], 3) is None


# --- 달력 ---------------------------------------------------------------------------------------

def test_rebalance_calendars():
    idx = pd.bdate_range("2001-01-01", "2002-12-31")
    firsts = idx[mod.lab.month_first_mask(idx)]
    m = idx[mod.decision_flags(idx, "monthly")]
    q = idx[mod.decision_flags(idx, "quarterly")]
    a = idx[mod.decision_flags(idx, "annual")]
    assert list(m) == list(firsts[1:])                         # 첫 행 제외
    assert sorted(set(q.month)) == [1, 4, 7, 10] and len(q) == 7
    assert list(a) == [pd.Timestamp("2002-01-01")]
    dl = idx[mod.december_last_flags(idx)]
    assert list(dl) == [pd.Timestamp("2001-12-31")]            # 2002-12-31 은 다음 거래일이 없어 제외


# --- 연말 손실 확정 ---------------------------------------------------------------------------------

def _harvest_panel(loss: bool):
    idx = pd.bdate_range("2000-10-02", "2001-02-27")
    n, m = len(idx), 4
    R = np.zeros((n, m))
    R[:, 0] = -0.003 if loss else 0.003
    R[:, 1] = 0.002
    R[:, 2:] = 0.0005
    S = np.tile(np.array([4.0, 3.0, 2.0, 1.0]), (n, 1))       # 언제나 0·1 선택
    C = np.cumprod(1 + R, axis=0)
    return idx, R, S, C


def _run(idx, R, S, C, spec, s=1):
    cols = [f"I{j}" for j in range(R.shape[1])]
    return mod.run_path(R, np.zeros(len(idx)), C, np.full(len(idx), 1300.0), S, idx, cols, s, len(idx) - 1, spec, "MKT")


def test_harvest_only_losers_at_year_end_with_next_day_rebuy():
    idx, R, S, C = _harvest_panel(loss=True)
    spec = mod.SPEC_BY_ID["Bnone_quarterly_harvest"]
    p = _run(idx, R, S, C, spec)
    assert [h["date"] for h in p["harvests"]] == ["2000-12-29"] and p["harvests"][0]["names"] == ["I0"]
    W = p["weights"]
    dec_last = pd.Timestamp("2000-12-29")
    jan = idx[idx.get_loc(dec_last) + 1]                                                # 다음 거래일(이 달력에선 2001-01-01)
    assert W.loc[dec_last, "I0"] == 0 and W.loc[dec_last, "I1"] > 0.45
    assert W.loc[jan, "I0"] > 0.4 and abs(W.loc[jan].sum() - 1) < 1e-6                  # 다음 거래일 종가에 다시 삼
    assert (W.loc[: idx[idx.get_loc(dec_last) - 1], "I0"] > 0).all()            # 그 전에는 팔지 않음
    # 판 다음 거래일 I0 수익은 계좌에 들어오지 않는다(현금)
    R2 = R.copy()
    R2[idx.get_loc(jan), 0] = 0.5
    p2 = _run(idx, R2, S, np.cumprod(1 + R2, axis=0), spec)
    assert abs(p2["returns"][jan] - p["returns"][jan]) < 1e-12
    # 실제 세금 엔진에서 2000 년 실현 손실이 생긴다
    from core import tax_fx as tx
    lev = pd.DataFrame(np.c_[C, np.ones(len(idx))], index=idx, columns=["I0", "I1", "I2", "I3", "MKT"])
    sim = tx.simulate(W, lev, lev, pd.Series(1300.0, index=idx), mod.tax_config_french())
    y2000 = [y for y in sim["years"] if y["year"] == 2000][0]
    assert y2000["realized_gain_krw"] < 0


def test_no_harvest_without_loss_or_when_off():
    idx, R, S, C = _harvest_panel(loss=False)
    assert _run(idx, R, S, C, mod.SPEC_BY_ID["Bnone_quarterly_harvest"])["harvests"] == []
    idx, R, S, C = _harvest_panel(loss=True)
    p = _run(idx, R, S, C, mod.SPEC_BY_ID["Bnone_quarterly_noharvest"])
    assert p["harvests"] == [] and (p["weights"]["I0"].iloc[1:] > 0).all()


def test_reset_only_on_name_change_lowers_turnover():
    idx, R, S, C = _harvest_panel(loss=False)
    m0 = _run(idx, R, S, C, mod.SPEC_BY_ID["M0"])
    low = _run(idx, R, S, C, mod.SPEC_BY_ID["Bnone_monthly_harvest"])        # 이름이 같으면 다시 맞추지 않음
    assert low["n_trades"] == 1 and m0["n_trades"] > 3
    assert low["turnover"].sum() == 0 and m0["turnover"].sum() > 0


# --- M0 = sector-concentrate RS12_k2 -------------------------------------------------------------

def test_m0_equals_sector_concentrate_rs12_k2():
    idx = pd.bdate_range("2000-01-03", periods=900)
    rng = np.random.default_rng(3)
    rets = pd.DataFrame(rng.normal(0.0003, 0.012, (900, 6)), index=idx, columns=[f"I{j}" for j in range(6)])
    mkt = rets.mean(axis=1)
    sched = sc.pick_schedule(rets, mkt, "RS12", 2)
    ref = sc.simulate(rets, mkt, sched, 2)
    refw = sc.target_weight_frame(rets, sched, 2, "MKT")
    P = mod.french_panel({"ind12": rets, "mkt": mkt})
    p = mod.run_path(P["R"], P["M"], P["C"], P["FX"], P["S"], P["index"], P["cols"], 0, len(idx) - 1, mod.SPEC_BY_ID["M0"], "MKT")
    np.testing.assert_allclose(p["returns"].to_numpy(), ref["returns"].to_numpy(), rtol=0, atol=1e-14)
    np.testing.assert_allclose(p["turnover"].to_numpy(), ref["turnover"].to_numpy(), rtol=0, atol=1e-14)
    np.testing.assert_allclose(p["weights"].to_numpy(), refw.to_numpy(), rtol=0, atol=1e-14)


# --- 선택·판정 ---------------------------------------------------------------------------------------

def _m(at, mdd=-0.5, w=-0.3):
    return {"after_tax_cagr": at, "mdd_after_tax": mdd, "worst252_after_tax": w}


def test_selection_rule():
    mk = _m(0.05, -0.6, -0.4)
    sel = {c: _m(0.08) for c in mod.CELLS}
    sel["B4_annual_harvest"] = _m(0.12, -0.7)                  # 최고지만 A 미달 → 제외
    sel["B3_quarterly_noharvest"] = _m(0.10)
    sel["B3_quarterly_harvest"] = _m(0.10)                     # 동점 → 움직이는 부분이 적은 쪽(harvest 없음)
    sel["B4_monthly_noharvest"] = _m(0.11, -0.5, -0.46)        # B 미달(−0.46 < −0.45)
    chosen, elig = mod.select_cell(sel, mk)
    assert chosen == "B3_quarterly_noharvest"
    assert "B4_annual_harvest" not in elig and "B4_monthly_noharvest" not in elig
    sel["B4_monthly_noharvest"] = _m(0.11, -0.5, -0.45)        # 경계(= 시장 − 5%p) 는 통과
    assert mod.select_cell(sel, mk)[0] == "B4_monthly_noharvest"
    bad = {c: _m(0.2, -0.9) for c in mod.CELLS}
    assert mod.select_cell(bad, mk) == (None, [])
    tie = {c: _m(0.08) for c in mod.CELLS}                     # 모두 같으면 M0(움직이는 부분 0)
    assert mod.select_cell(tie, mk)[0] == "M0"


def test_pass_rule_edges():
    power = mod.rp.power_report(41, 17)
    mk, m0 = _m(0.08, -0.6, -0.4), _m(0.085)
    c = _m(0.09)                                               # = M0 + 0.5%p, = 시장 + 1.0%p (경계 통과)
    sub_c, sub_m = [_m(0.07), _m(0.10)], [_m(0.06), _m(0.09)]
    ch = mod.confirmation_checks(c, m0, mk, sub_c, sub_m)
    assert all(ch.values())
    assert mod.final_verdict("B3_quarterly_noharvest", ch, None, 0.3, power)[0] == mod.PASS
    ch2 = mod.confirmation_checks(_m(0.0899), m0, mk, sub_c, sub_m)
    assert ch2["vs_M0"] is False and ch2["vs_market"] is False
    eq = mod.confirmation_checks(c, m0, mk, [_m(0.06), _m(0.10)], sub_m)   # 하위 구간은 엄격히 >
    assert eq["subperiods_both"] is False
    assert mod.final_verdict("B3_quarterly_noharvest", eq, None, 0.1, power)[0] == "FAIL_UNDERPOWERED"
    assert mod.final_verdict("B3_quarterly_noharvest", eq, None, 0.9, power)[0] == mod.FAIL
    assert mod.final_verdict("B3_quarterly_noharvest", ch, "same", 0.3, power)[0] == mod.NOT_EVALUABLE
    assert mod.final_verdict(None, None, None, None, power)[0] == mod.FAIL
    assert mod.final_verdict("M0", ch, None, None, power)[0] == mod.FAIL
    worse_mdd = mod.confirmation_checks(_m(0.09, -0.61), m0, mk, sub_c, sub_m)
    assert worse_mdd["A_mdd"] is False


def test_etf_verdict_edges():
    spy, m0 = {"after_tax_cagr": 0.07}, {"after_tax_cagr": 0.08}
    assert mod.etf_verdict({"after_tax_cagr": 0.08}, m0, spy) == mod.SUPPORTING
    assert mod.etf_verdict({"after_tax_cagr": 0.0749}, {"after_tax_cagr": 0.06}, spy) == mod.NOT_SUPPORTING
    assert mod.etf_verdict({"after_tax_cagr": 0.079}, m0, spy) == mod.NOT_SUPPORTING
    assert mod.etf_verdict(None, m0, spy) == mod.NOT_SUPPORTING


def test_worst_rolling_and_rows():
    v = pd.Series([1.0, 0.5, 0.6, 0.9], index=pd.bdate_range("2001-01-01", periods=4))
    assert abs(mod.worst_rolling(v, 2, 1.0) - (-0.5)) < 1e-12      # [1, 1, .5, .6, .9] → 2행 수익 최솟값 .5/1 − 1
    assert mod.worst_rolling(v, 5, 1.0) is None
    s, e = mod.rows_of(v.index, "2001-01-02", "2001-01-03")
    assert (s, e) == (1, 2)
