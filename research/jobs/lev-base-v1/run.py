"""검증 연구 lev-base-v1 (사전 등록 2026-10-16): SPY 바탕 + 작은 2배 레버리지 다리(추세 필터는 그 다리에만).

사용자(2026-10-16): "수익 먼저, 안정성은 어느 정도". lev-trend-v1 의 2배 + 추세 필터는 SPY 보다 수익은 높았지만
MDD −40% 와 잦은 전환에 따른 양도세가 컸다. 가설: SPY 를 바탕으로 두고 작은 2배 다리(L = 10/15/25%)만 얹으며,
200일선 필터(완충 ±2%, 월초)를 그 다리에만 걸면 낙폭은 조금만 늘고 회전율은 낮게 수익을 올릴 수 있다.

규칙 전문은 SPEC.md(한국어). 결과를 보기 전에 고정했고 바꾸려면 새 id 로 다시 등록한다. 요약:
 - 포트폴리오: SPY (1 − L) + 합성 2배 일일 리셋 SPY 상품 L. 상품 일 수익 = 2 × SPY 총수익 − (BIL + 연 1%)/252 − 연 0.9%/252
   (lev-trend-v1 과 같은 관례). 장기(프렌치)에서는 BIL 대신 RF.
 - 필터(F, 2배 다리에만): 매달 첫 거래일에 전일 종가 기준으로 평가. 상태 기계: 전일 종가 > 1.02 × 전일 SMA200 이면 켜짐,
   < 0.98 × SMA200 이면 꺼짐, 그 사이면 이전 상태 유지. 처음(평가 전)은 꺼짐. 켜짐이면 다리는 2배 상품, 꺼짐이면 BIL(장기: RF).
   SPY 부분은 필터하지 않는다. 슬리브 목표 비중 재조정은 매년 1월 첫 거래일(과 구간 첫날)만. 그 밖에는 필터 전환일에
   다리의 '표류한 크기 그대로' 2배 상품 ↔ BIL 만 바꾼다.
 - 판정 셀: L10F, L15F, L25F (시도 3). 참고: L25(필터 없음), SPY 그냥 보유, 각 판정 셀 + 새틀라이트 15%(SPY 15%p 감소).
 - PASS_FORWARD_CANDIDATE ⇔ (a)~(h) 모두. PASS 는 전진 원장 후보일 뿐 채택이 아니다(엔진 변경 없음).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import pickle
import signal as _signal
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "lev-base-v1"
RULES_VERSION = "lev-base-v1/2026-10-16"
JUDGE_VERSION = "lev-base-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
SPY, BIL, X2, SSO = "SPY", "BIL", "SPY2X", "SSO"
LEV_MULT = 2.0
FIN_SPREAD = 0.010            # 차입 가산 연 1% (BIL/RF 위)
FEE = 0.009                   # 상품 보수 연 0.9%
SMA_WIN = 200
BAND_ON, BAND_OFF = 1.02, 0.98
SAT_WEIGHT = 0.15
CELLS = {"L10F": (0.10, True), "L15F": (0.15, True), "L25F": (0.25, True)}
REFS = {"L25": (0.25, False)}
JUDGED = tuple(CELLS)
N_TRIALS = 3
CAPITAL = 30_000_000
CAPITAL_REPORT = 100_000_000
WINDOWS = {"judged": ("2010-01-04", "2024-09-30"), "h1": ("2010-01-04", "2017-05-31"),
           "h2": ("2017-06-01", "2024-09-30"), "post": ("2024-10-01", None)}
LONG_START, LONG_END = "1927-07-01", "2007-12-31"
SUB_PERIODS = {"1927-46": ("1927-07-01", "1946-12-31"), "1947-66": ("1947-01-01", "1966-12-31"),
               "1967-86": ("1967-01-01", "1986-12-31"), "1987-07": ("1987-01-01", "2007-12-31")}
LONG_COST_BPS = 10.0
LONG_WORST_YEARS = (1929, 1930, 1931, 1932, 1973, 1974, 2000, 2001, 2002)
ETF_STRESS_YEARS = (2020, 2022)
# 판정 문턱
A_LONG_EDGE = 0.010           # (a) 장기 CAGR ≥ 시장 + 1.0%p
C_ROLL12_TOL = 0.05           # (c) 최악 12개월 ≥ 시장 최악 − 5%p
D_SUB_MIN = 3                 # (d) 4 구간 중 3 이상에서 시장 초과
E_ETF_EDGE = 0.005            # (e) 세후 ≥ SPY + 0.5%p
G_MDD_TOL = 0.03              # (g) 원화 MDD 가 SPY 보다 3%p 넘게 나쁘지 않음
H_CI_FLOOR = -0.005           # (h) 부트스트랩 90% 하한 > −0.5%p
N_BOOT, BLOCK_DAYS, BOOT_SEED, CI_PCT = 1000, 126, 20261024, (5.0, 95.0)
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"
LABELS = {"L10F": "SPY 90% + 2배 10%(필터)", "L15F": "SPY 85% + 2배 15%(필터)", "L25F": "SPY 75% + 2배 25%(필터)",
          "L25": "SPY 75% + 2배 25%(필터 없음, 참고)", "SPY": "SPY 그냥 보유(기준)"}


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def _load_mod(name: str, rel: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SC = _load_mod("spy_champion_v1_for_lev_base", "research/jobs/spy-champion-v1/run.py")   # 슬리브 비중·새틀라이트 일정
SV = SC.SV                                                                                  # 부트스트랩·체크포인트
lab = _load_mod("core_longrun_lab", "research/jobs/core-longrun-v1/lab.py")                 # 프렌치 자료·지표


# =================================================================================================
# 순수 함수: 합성 상품·필터·슬리브
# =================================================================================================

def synthetic_2x_returns(r: pd.Series, r_fin: pd.Series) -> pd.Series:
    """2배 일일 리셋 상품의 일 수익 = 2 × r − (r_fin + 연 1%/252) − 연 0.9%/252. r_fin = BIL 일 수익(장기는 RF)."""
    rf = r_fin.reindex(r.index).fillna(0.0)
    return LEV_MULT * r - (LEV_MULT - 1.0) * (rf + FIN_SPREAD / 252) - FEE / 252


def month_first_flags(index: pd.DatetimeIndex) -> np.ndarray:
    per = index.to_period("M")
    out = np.ones(len(index), dtype=bool)
    out[1:] = per[1:] != per[:-1]
    return out


def january_first_flags(index: pd.DatetimeIndex) -> np.ndarray:
    yr = index.year
    out = np.zeros(len(index), dtype=bool)
    out[1:] = (yr[1:] != yr[:-1]) & (index.month[1:] == 1)
    if len(index) and index[0].month == 1:
        out[0] = True
    return out


def buffered_state(close: pd.Series, window: int = SMA_WIN) -> pd.Series:
    """2배 다리 상태(True=켜짐). 매달 첫 거래일에 '전일' 종가·'전일' SMA 로만 평가하고 그날 종가에 매매.
    켜기: 전일 종가 > 1.02 × SMA, 끄기: < 0.98 × SMA, 그 사이: 유지. 평가 전(SMA 없음) 처음 상태는 꺼짐."""
    sma = close.rolling(window, min_periods=window).mean()
    c_prev, s_prev = close.shift(1).to_numpy(), sma.shift(1).to_numpy()
    flags = month_first_flags(close.index)
    st, out = False, np.zeros(len(close), dtype=bool)
    for i in range(len(close)):
        if flags[i] and np.isfinite(s_prev[i]) and np.isfinite(c_prev[i]):
            if c_prev[i] > BAND_ON * s_prev[i]:
                st = True
            elif c_prev[i] < BAND_OFF * s_prev[i]:
                st = False
        out[i] = st
    return pd.Series(out, index=close.index)


def lev_inner(state: pd.Series, filtered: bool) -> pd.DataFrame:
    """2배 다리 슬리브 안 비중: 켜짐 → 2배 상품 1.0, 꺼짐 → BIL 1.0. 필터 없음이면 항상 2배."""
    on = state.astype(float) if filtered else pd.Series(1.0, index=state.index)
    return pd.DataFrame({X2: on, BIL: 1.0 - on}, index=state.index)


def portfolio_weights(index: pd.DatetimeIndex, adj: pd.DataFrame, L: float, filtered: bool, state: pd.Series,
                      sat_inner: Optional[pd.DataFrame] = None) -> tuple[pd.DataFrame, dict]:
    """SPY 슬리브(1 − L [− 15%]) + 2배 다리 L (+ 새틀라이트 15%). 1월 첫 거래일·첫날만 목표로 재조정,
    필터 전환일·새틀라이트 선정일엔 그 슬리브만 표류 크기 그대로 안을 바꾼다(spy-champion-v1 의 sleeve_weights)."""
    spy_w = 1.0 - L - (SAT_WEIGHT if sat_inner is not None else 0.0)
    sleeves = [("spy", spy_w, pd.DataFrame({SPY: 1.0}, index=index)),
               ("lev", L, lev_inner(state.reindex(index).fillna(False).astype(bool), filtered))]
    if sat_inner is not None:
        si = sat_inner.reindex(index).fillna(0.0)
        si.attrs["marks"] = sat_inner.attrs.get("marks")
        sleeves.append(("sat", SAT_WEIGHT, si))
    w, info = SC.sleeve_weights(index, adj, sleeves, SC.january_resets(index))
    return w.loc[:, w.abs().sum() > 0], info


# =================================================================================================
# 장기(프렌치) 세전 시뮬레이션
# =================================================================================================

def long_run_path(mkt: pd.Series, rf: pd.Series, L: float, filtered: bool, start: str = LONG_START,
                  end: Optional[str] = LONG_END, bps: float = LONG_COST_BPS) -> dict:
    """구간 첫날 목표대로 보유하고 시작(초기 매수 비용 없음, 시장도 같음). 그날 수익 뒤 종가에 매매:
    1월 첫 거래일 → 목표 (1−L, L) 재조정, 필터 전환일 → 다리만 2배 ↔ RF. 비용 = Σ|매매액| × bps(매도·매수 각 편도)."""
    level = (1 + mkt).cumprod()
    state_full = buffered_state(level) if filtered else pd.Series(True, index=mkt.index)
    x2_full = synthetic_2x_returns(mkt, rf)
    m = lab.window(mkt, start, end)
    idx = m.index
    r_m, r_x, r_f = m.to_numpy(), x2_full.reindex(idx).to_numpy(), rf.reindex(idx).fillna(0.0).to_numpy()
    st = state_full.reindex(idx).to_numpy(dtype=bool)
    jan = january_first_flags(idx)
    pos = np.array([1 - L, L if st[0] else 0.0, 0.0 if st[0] else L])
    rets = np.zeros(len(idx))
    w_x2 = np.zeros(len(idx))
    costs = 0.0
    switches = 0
    for i in range(1, len(idx)):
        prev = pos.sum()
        pos = pos * np.array([1 + r_m[i], 1 + r_x[i], 1 + r_f[i]])
        w_x2[i] = pos[1] / pos.sum() if pos.sum() > 0 else 0.0
        V = pos.sum()
        target = None
        if st[i] != st[i - 1]:
            switches += 1
        if jan[i]:
            target = np.array([(1 - L) * V, L * V if st[i] else 0.0, 0.0 if st[i] else L * V])
        elif st[i] != st[i - 1]:
            lev = pos[1] + pos[2]
            target = np.array([pos[0], lev if st[i] else 0.0, 0.0 if st[i] else lev])
        if target is not None:
            c = float(np.abs(target - pos).sum()) * bps / 1e4
            costs += c
            pos = target * ((V - c) / V) if V > 0 else target
        rets[i] = pos.sum() / prev - 1 if prev > 0 else 0.0
    r = pd.Series(rets, index=idx)
    years = lab.years_of(r)
    drag = float(np.mean(w_x2[1:] * ((LEV_MULT - 1) * (r_f[1:] + FIN_SPREAD / 252) + FEE / 252)) * 252) if len(idx) > 1 else 0.0
    return {"returns": r, "switches_per_year": switches / max(years, 1e-9), "time_on": float(st.mean()),
            "cost_total": costs, "financing_fee_drag_annual": drag}


def worst_rolling_12m(r: pd.Series) -> float:
    """월 수익을 복리로 묶은 뒤 연속 12개월 수익의 최솟값."""
    mo = lab.monthly(r)
    roll = (1 + mo).rolling(12).apply(np.prod, raw=True) - 1
    return float(roll.min()) if roll.notna().any() else float("nan")


def calendar_returns(r: pd.Series, years) -> dict:
    out = {}
    for y in years:
        s = r[r.index.year == y]
        out[str(y)] = float((1 + s).prod() - 1) if len(s) else None
    return out


def long_metrics(r: pd.Series) -> dict:
    return {"cagr": lab.cagr(r), "mdd": lab.mdd(r), "worst_12m": worst_rolling_12m(r), "years": lab.years_of(r),
            "sub": {k: lab.cagr(lab.window(r, a, b)) for k, (a, b) in SUB_PERIODS.items()},
            "calendar": calendar_returns(r, LONG_WORST_YEARS)}


def long_run_table(mkt: pd.Series, rf: pd.Series) -> dict:
    base = lab.window(mkt, LONG_START, LONG_END)
    out: dict[str, Any] = {"MARKET": long_metrics(base)}
    for name, (L, f) in {**CELLS, **REFS}.items():
        p = long_run_path(mkt, rf, L, f)
        r = p["returns"]
        met = long_metrics(r)
        active = (r - base.reindex(r.index)).to_numpy()
        met.update({k: v for k, v in p.items() if k != "returns"})
        met["active_ir"] = _ir(active)
        met["noop"] = rp.noop_guard(active)
        met["sub_beats"] = int(sum(met["sub"][k] > out["MARKET"]["sub"][k] for k in SUB_PERIODS))
        out[name] = met
    return out


def _ir(active) -> Optional[float]:
    a = np.asarray(active, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 3 or a.std(ddof=1) <= 0:
        return None
    return float(a.mean() / a.std(ddof=1) * math.sqrt(252))


# =================================================================================================
# 판정 (사전 등록 — 순수 함수)
# =================================================================================================

def _fin(*xs) -> bool:
    return all(x is not None and math.isfinite(float(x)) for x in xs)


def judge(long: dict, etf: dict, noop: Optional[str] = None) -> tuple[str, dict]:
    """long: {cagr, mkt_cagr, mdd, mkt_mdd, worst12, mkt_worst12, sub_beats}
    etf: {cagr, spy_cagr, h1, spy_h1, h2, spy_h2, mdd, spy_mdd, ci_low}. 반환 (PASS|FAIL|NOT_EVALUABLE, 조건별 bool)."""
    if noop:
        return NOT_EVALUABLE, {}
    need = [long.get(k) for k in ("cagr", "mkt_cagr", "mdd", "mkt_mdd", "worst12", "mkt_worst12", "sub_beats")]
    need += [etf.get(k) for k in ("cagr", "spy_cagr", "h1", "spy_h1", "h2", "spy_h2", "mdd", "spy_mdd", "ci_low")]
    if not _fin(*need):
        return NOT_EVALUABLE, {}
    c = {
        "a_long_cagr_ge_mkt_plus_1pp": long["cagr"] >= long["mkt_cagr"] + A_LONG_EDGE - 1e-12,
        "b_long_mdd_not_worse": long["mdd"] >= long["mkt_mdd"] - 1e-12,
        "c_long_worst12m_ge_mkt_minus_5pp": long["worst12"] >= long["mkt_worst12"] - C_ROLL12_TOL - 1e-12,
        "d_long_beats_mkt_in_3of4_subperiods": int(long["sub_beats"]) >= D_SUB_MIN,
        "e_etf_after_tax_ge_spy_plus_0.5pp": etf["cagr"] >= etf["spy_cagr"] + E_ETF_EDGE - 1e-12,
        "f_etf_both_halves_gt_spy": etf["h1"] > etf["spy_h1"] and etf["h2"] > etf["spy_h2"],
        "g_etf_krw_mdd_within_3pp_of_spy": etf["mdd"] >= etf["spy_mdd"] - G_MDD_TOL - 1e-12,
        "h_boot_ci90_low_gt_minus_0.5pp": etf["ci_low"] > H_CI_FLOOR,
    }
    return (PASS if all(c.values()) else FAIL), c


# =================================================================================================
# ETF 시대 시뮬레이션
# =================================================================================================

def _summ(s: dict, w: pd.DataFrame, adj: pd.DataFrame, initial: float, state: Optional[pd.Series]) -> dict:
    v = s["values_krw"]
    t0, t1 = v.index[0], v.index[-1]
    yrs = max((t1 - t0).days / 365.25, 1e-9)
    out = {"cagr_after_liq": SC.liq_cagr(s["final_after_liquidation_krw"], initial, t0, t1),
           "cagr_after": s["cagr_after"], "cagr_pre": s["cagr_pre"], "mdd_after": s["mdd_after"],
           "final_after_liquidation_krw": s["final_after_liquidation_krw"], "totals": s["totals"],
           "unpaid_tax_if_sold_now_krw": s["unpaid_tax_if_sold_now_krw"],
           "turnover": SC.annual_turnover(w, adj),
           "calendar_mdd": {str(y): SC.calendar_mdd(v, y) for y in ETF_STRESS_YEARS},
           "calendar_return": {str(y): _cal_ret(v, y) for y in ETF_STRESS_YEARS},
           "start": str(t0.date()), "end": str(t1.date()), "values": v}
    if X2 in w.columns:
        rb = adj[BIL].reindex(w.index).pct_change(fill_method=None).fillna(0.0)
        out["financing_fee_drag_annual_approx"] = float((w[X2] * ((LEV_MULT - 1) * (rb + FIN_SPREAD / 252) + FEE / 252)).mean() * 252)
    if state is not None:
        stw = state.reindex(w.index).fillna(False).astype(int)
        out["switches_per_year"] = float((stw.diff().abs() > 0).sum() / yrs)
        out["time_on"] = float(stw.mean())
    return out


def _cal_ret(v: pd.Series, y: int) -> Optional[float]:
    cur = v[v.index.year == y]
    prev = v[v.index.year < y]
    if cur.empty or prev.empty:
        return None
    return float(cur.iloc[-1] / prev.iloc[-1] - 1)


def pair_stats(a: dict, b: dict, initial: float) -> dict:
    va, vb = a["values"], b["values"]
    ra, rb = SV.window_returns(va, initial, va.index[-1]), SV.window_returns(vb, initial, vb.index[-1])
    years = (va.index[-1] - va.index[0]).days / 365.25
    ppy = len(ra) / years
    d = (ra - rb).to_numpy()
    sd = float(np.std(d, ddof=1)) if len(d) > 1 else float("nan")
    ir = float(np.mean(d) / sd * math.sqrt(ppy)) if sd and math.isfinite(sd) and sd > 0 else float("nan")
    boot = SV.block_bootstrap_diff(ra.to_numpy(), rb.to_numpy(), ppy, n_boot=N_BOOT, block=BLOCK_DAYS, seed=BOOT_SEED)
    lo, hi = np.percentile(boot, CI_PCT)
    return {"daily_diff_ir": ir, "noop_reason": rp.noop_guard(d), "boot_ci90_low": float(lo), "boot_ci90_high": float(hi),
            "boot_share_positive": float(np.mean(boot > 0))}


def sso_tracking(adj: pd.DataFrame) -> dict:
    """합성 2배 vs 실제 SSO(2006+) 일 수익 비교 — 보고만."""
    if SSO not in adj.columns or X2 not in adj.columns:
        return {"available": False}
    df = adj[[X2, SSO]].pct_change(fill_method=None).dropna()
    df = df[df.index >= pd.Timestamp("2006-07-01")]
    if len(df) < 60:
        return {"available": False}
    yrs = (df.index[-1] - df.index[0]).days / 365.25
    ann = lambda s: float((1 + s).prod() ** (1 / yrs) - 1)  # noqa: E731
    d = df[X2] - df[SSO]
    return {"available": True, "start": str(df.index[0].date()), "end": str(df.index[-1].date()),
            "synthetic_cagr": ann(df[X2]), "sso_cagr": ann(df[SSO]),
            "tracking_error_annual": float(d.std(ddof=1) * math.sqrt(252)), "corr": float(df.corr().iloc[0, 1])}


# =================================================================================================
# 입력
# =================================================================================================

def _assemble(base: pd.DataFrame, base_adj: pd.DataFrame, sat_close: pd.DataFrame, sat_adj: pd.DataFrame,
              fx: pd.Series, log: list, meta: dict) -> dict:
    """base: SPY·BIL(·SSO) 일별 종가/조정가(2005~). 합성 2배는 조정가 기준(배당 포함) — 종가=조정가(분배 없음)."""
    days = base[SPY].dropna().index
    base, base_adj = base.reindex(days).ffill(), base_adj.reindex(days).ffill()
    r = base_adj[SPY].pct_change(fill_method=None).fillna(0.0)
    rb = base_adj[BIL].pct_change(fill_method=None).fillna(0.0)
    lvl = 100 * (1 + synthetic_2x_returns(r, rb)).cumprod()
    close, adj = base.copy(), base_adj.copy()
    close[X2], adj[X2] = lvl, lvl
    extra = [t for t in sat_close.columns if t not in close.columns]
    close = close.join(sat_close[extra].reindex(days).ffill())
    adj = adj.join(sat_adj[extra].reindex(days).ffill())
    return {"close": close, "adj": adj, "fx": fx, "log": log, "state": buffered_state(base[SPY]), "meta": meta}


def _smoke_inputs(log) -> dict:
    """합성 데이터(네트워크 없음). 실데이터가 아니다."""
    s = SV._smoke_inputs(log)
    idx = pd.bdate_range("2005-01-03", "2026-06-30")
    rng = np.random.default_rng(24)
    drift = np.full(len(idx), 0.0005)
    for a, b, d in (("2008-01-01", "2009-03-01", -0.0025), ("2011-05-01", "2011-10-01", -0.002), ("2015-08-01", "2016-02-10", -0.0015),
                    ("2018-10-01", "2018-12-24", -0.003), ("2020-02-20", "2020-03-23", -0.012), ("2022-01-03", "2022-10-14", -0.0015)):
        drift[(idx >= a) & (idx <= b)] = d
    spy = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.01, len(idx))))
    bil = 90 + np.arange(len(idx)) * 0.002
    base = pd.DataFrame({SPY: spy, BIL: bil}, index=idx)
    adj = base.copy()
    adj[SPY] = spy * np.exp(np.linspace(0, 0.3, len(idx)))
    r = adj[SPY].pct_change().fillna(0.0)
    sso = 50 * (1 + 2 * r - 0.0001 + rng.normal(0, 0.0005, len(idx))).cumprod()
    base[SSO], adj[SSO] = sso, sso
    fx = s["fx"].reindex(idx).ffill().bfill()
    return _assemble(base, adj, s["close"], s["adj"], fx, s["logs"]["A"], {**s["meta"], "synthetic": True})


def _real_inputs(log) -> dict:
    from core import champion_strategy as cs
    from core import satellite_lab as sl
    from core.market_data import get_multiple_price_history

    h = get_multiple_price_history([SPY, BIL, SSO], start="2005-01-01", end=None, interval="1d")
    base = pd.DataFrame({t: h[t]["Close"] for t in (SPY, BIL, SSO) if t in h and not h[t].empty}).sort_index()
    badj = pd.DataFrame({t: h[t]["Adj Close"] for t in (SPY, BIL, SSO) if t in h and not h[t].empty}).sort_index()
    for need in (SPY, BIL):
        if need not in base.columns:
            raise RuntimeError(f"{need} 가격을 받지 못함")
    log("새틀라이트(S-SEED-000) 일정")
    pool = SV._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(SC.START))
    data = sl.build_data({"champion40"}, start="2009-12-01", pool_provider=pool, log=log)
    spec, signal, params = SV._incumbent()
    sp = json.loads(json.dumps(spec))
    sp["pool"] = {"type": "champion40"}
    sat_log = SV.schedule_to_log(sl.run_variant(sp, params, signal, data)["schedule"])
    picks = sorted({t for r in sat_log for t in r["weights"]})
    sc, sa = SV._panel({t: data.ohlcv.get(t) for t in picks})
    meta = {"live_satellite_weight": cs.SATELLITE_WEIGHT, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
            "pool_cache_tag": sl.POOL_CACHE_TAG}
    return _assemble(base, badj, sc, sa, tx.usdkrw_series(), sat_log, meta)


def _french(smoke: bool):
    if smoke:
        d = lab.synthetic_data()
        rf, mkt = d["rf"], d["mkt"]
    else:
        from core import french_factors as ff

        ff3 = ff.load("ff3_daily")
        if ff3 is None:
            raise RuntimeError("Ken French 일별 FF3 자료를 받지 못함")
        rf, mkt = ff3["RF"].astype(float), (ff3["Mkt-RF"] + ff3["RF"]).astype(float)
    rf, mkt = lab.to_weekdays(rf), lab.to_weekdays(mkt)
    idx = rf.index.intersection(mkt.index)
    return rf.reindex(idx).fillna(0.0), mkt.reindex(idx)


# =================================================================================================
# 작업 목록·분석·보고
# =================================================================================================

def window_index(index: pd.DatetimeIndex, win: str) -> pd.DatetimeIndex:
    a, b = WINDOWS[win]
    return index[(index >= pd.Timestamp(a)) & ((index <= pd.Timestamp(b)) if b else True)]


def build_weights(inputs: dict, name: str, win: str) -> tuple[pd.DataFrame, dict]:
    sub = window_index(inputs["close"].index, win)
    if name == "SPY":
        return tx.buy_and_hold_weights(sub), {}
    sat = name.endswith("+SAT")
    L, f = {**CELLS, **REFS}[name.replace("+SAT", "")]
    si = SC.inner_frame_from_log(sub, inputs["log"]) if sat else None
    return portfolio_weights(sub, inputs["adj"], L, f, inputs["state"], si)


def sim_jobs() -> list:
    names = list(CELLS) + list(REFS) + ["SPY"]
    jobs = [(n, w, CAPITAL) for w in WINDOWS for n in names]
    jobs += [(n, "judged", CAPITAL_REPORT) for n in names]
    jobs += [(f"{n}+SAT", "judged", CAPITAL) for n in CELLS]
    return jobs


def analyze(sims: dict, long: dict, inputs: dict, smoke: bool) -> tuple[dict, str]:
    def g(n, w="judged", cap=CAPITAL):
        return sims[(n, w, cap)]

    spy = g("SPY")
    power_etf = rp.power_report((spy["values"].index[-1] - spy["values"].index[0]).days / 365.25, N_TRIALS)
    power_long = rp.power_report(long["MARKET"]["years"], N_TRIALS)
    verdicts, details = {}, {}
    for n in JUDGED:
        pr = pair_stats(g(n), spy, CAPITAL)
        lg = long[n]
        lj = {"cagr": lg["cagr"], "mkt_cagr": long["MARKET"]["cagr"], "mdd": lg["mdd"], "mkt_mdd": long["MARKET"]["mdd"],
              "worst12": lg["worst_12m"], "mkt_worst12": long["MARKET"]["worst_12m"], "sub_beats": lg["sub_beats"]}
        ej = {"cagr": g(n)["cagr_after_liq"], "spy_cagr": spy["cagr_after_liq"], "h1": g(n, "h1")["cagr_after_liq"],
              "spy_h1": g("SPY", "h1")["cagr_after_liq"], "h2": g(n, "h2")["cagr_after_liq"], "spy_h2": g("SPY", "h2")["cagr_after_liq"],
              "mdd": g(n)["mdd_after"], "spy_mdd": spy["mdd_after"], "ci_low": pr["boot_ci90_low"]}
        noop = pr["noop_reason"] or lg["noop"]
        v, checks = judge(lj, ej, noop)
        fail_kind = None
        if v == FAIL:
            etf_fail = not all(checks[k] for k in checks if k[0] in "efgh")
            fail_kind = rp.classify_fail(pr["daily_diff_ir"], power_etf) if etf_fail else rp.classify_fail(lg["active_ir"], power_long)
            v = fail_kind
        verdicts[n] = v
        details[n] = {"checks": checks, "long": lj, "etf": ej, "pair_vs_spy": pr, "observed_ir_long": lg["active_ir"],
                      "fail_kind": fail_kind, "noop": noop}
    strip = lambda s: {k: v for k, v in s.items() if k != "values"}  # noqa: E731
    etf_stats = {f"{n}|{w}|{cap // 1_000_000}M": strip(s) for (n, w, cap), s in sims.items()}
    sat_table = {}
    for n in CELLS:
        s = g(f"{n}+SAT")
        sat_table[n] = {"after_tax_liq": s["cagr_after_liq"], "mdd_krw": s["mdd_after"],
                        "diff_vs_spy": s["cagr_after_liq"] - spy["cagr_after_liq"],
                        "diff_vs_cell": s["cagr_after_liq"] - g(n)["cagr_after_liq"],
                        "tax_paid_krw": s["totals"]["capital_gains_tax_krw"]}
    result = {"job_id": JOB_ID, "judge_version": JUDGE_VERSION, "rules_version": RULES_VERSION, "smoke": smoke,
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "details": details, "etf_stats": etf_stats, "long_run": long,
              "satellite_secondary": sat_table, "sso_tracking": sso_tracking(inputs["adj"]),
              "power": {"etf_era": power_etf, "long_run": power_long},
              "windows": WINDOWS, "long_window": [LONG_START, LONG_END], "sub_periods": SUB_PERIODS,
              "rules": {"lev_mult": LEV_MULT, "fin_spread": FIN_SPREAD, "fee": FEE, "band": [BAND_OFF, BAND_ON], "sma": SMA_WIN,
                        "long_cost_bps": LONG_COST_BPS, "n_boot": N_BOOT, "block_days": BLOCK_DAYS, "boot_seed": BOOT_SEED},
              "meta": inputs.get("meta", {})}
    return result, report(result)


def _p(x, signed=False, nd=1) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def report(r: dict) -> str:
    ok = lambda x: "충족" if x else "미달"  # noqa: E731
    es, lg, v = r["etf_stats"], r["long_run"], r["verdicts"]
    L = [f"# SPY 바탕 + 작은 2배 다리 — {JOB_ID} ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
         "질문: SPY 를 바탕에 두고 2배 일일 리셋 상품을 10·15·25% 만 얹되, 200일선 필터(±2% 완충, 월초)를 그 다리에만 걸면 "
         "낙폭을 크게 늘리지 않고 수익을 올릴 수 있나. PASS 는 전진 원장에 올릴 후보라는 뜻이며 채택이 아니다(엔진 변경 없음).", "",
         rp.power_line(r["power"]["long_run"]).replace("검정력(사전 계산)", "검정력(장기 1927~2007)"),
         rp.power_line(r["power"]["etf_era"]).replace("검정력(사전 계산)", "검정력(ETF 시대)"), "",
         "## 판정", "", "| 셀 | 판정 | (a) 장기 수익 | (b) 장기 MDD | (c) 최악 12개월 | (d) 4구간 중 3 | (e) 세후 +0.5%p | (f) 두 절반 | (g) 원화 MDD | (h) 부트스트랩 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for n in JUDGED:
        c = r["details"][n]["checks"]
        keys = list(c) or [None] * 8
        L.append(f"| {LABELS[n]} | **{v[n]}** | " + " | ".join(ok(c.get(k)) if k else "—" for k in keys) + " |")
    L += ["", "## 장기 1927-07 ~ 2007 (세전, 프렌치 시장 = Mkt-RF+RF, 편도 10bp)", "",
          "| | CAGR | MDD | 최악 12개월 | 1927-46 | 1947-66 | 1967-86 | 1987-07 | 연 전환 | 켜짐 비율 | 차입·보수 부담(연) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in ["MARKET", *JUDGED, *REFS]:
        x = lg[n]
        lab_n = "시장 그냥 보유" if n == "MARKET" else LABELS[n]
        L.append(f"| {lab_n} | {_p(x['cagr'])} | {_p(x['mdd'])} | {_p(x['worst_12m'])} | " + " | ".join(_p(x["sub"][k]) for k in SUB_PERIODS)
                 + f" | {x.get('switches_per_year', 0):.2f} | {_p(x.get('time_on', 1.0), nd=0)} | {_p(x.get('financing_fee_drag_annual'), nd=2)} |")
    L += ["", "### 장기 나쁜 해(달력 연 수익, 보고만)", "", "| | " + " | ".join(str(y) for y in LONG_WORST_YEARS) + " |", "|---" * (len(LONG_WORST_YEARS) + 1) + "|"]
    for n in ["MARKET", *JUDGED, *REFS]:
        L.append(f"| {'시장' if n == 'MARKET' else n} | " + " | ".join(_p(lg[n]["calendar"][str(y)]) for y in LONG_WORST_YEARS) + " |")
    L += ["", "## ETF 시대 — 세후·원화 (3,000만 원, 카카오페이 기본값; 세후 = 마지막에 전부 판 뒤 금액 기준)", "",
          "| | 판정 구간 세후 | 세전(원화) | 원화 MDD | 전반 | 후반 | 2024-10~ (보고만) | 양도세 합(만 원) | 연 회전율 | 연 전환 | 켜짐 비율 | 차입·보수 부담(근사) | 2020 수익/MDD | 2022 수익/MDD |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in [*JUDGED, *REFS, "SPY"]:
        j, h1, h2, po = (es[f"{n}|{w}|30M"] for w in ("judged", "h1", "h2", "post"))
        cal = " | ".join(f"{_p(j['calendar_return'][str(y)])} / {_p(j['calendar_mdd'][str(y)])}" for y in ETF_STRESS_YEARS)
        L.append(f"| {LABELS[n]} | {_p(j['cagr_after_liq'])} | {_p(j['cagr_pre'])} | {_p(j['mdd_after'])} | {_p(h1['cagr_after_liq'])} | {_p(h2['cagr_after_liq'])} | "
                 f"{_p(po['cagr_after_liq'])} | {j['totals']['capital_gains_tax_krw'] / 1e4:,.0f} | {_p(j['turnover'], nd=0)} | {j.get('switches_per_year', 0):.2f} | "
                 f"{_p(j.get('time_on'), nd=0)} | {_p(j.get('financing_fee_drag_annual_approx'), nd=2)} | {cal} |")
    L += ["", "| 판정 셀 vs SPY | 일별 차이 IR | 부트스트랩 90% 구간(연수익 차) | 차이 > 0 비율 |", "|---|---|---|---|"]
    for n in JUDGED:
        pr = r["details"][n]["pair_vs_spy"]
        L.append(f"| {n} | {pr['daily_diff_ir']:.2f} | {_p(pr['boot_ci90_low'], True, 2)} ~ {_p(pr['boot_ci90_high'], True, 2)} | {pr['boot_share_positive']:.0%} |")
    L += ["", "### 1억 원 시작 (보고만)", "", "| | 세후 | 원화 MDD | 양도세 합(만 원) |", "|---|---|---|---|"]
    for n in [*JUDGED, *REFS, "SPY"]:
        j = es[f"{n}|judged|100M"]
        L.append(f"| {LABELS[n]} | {_p(j['cagr_after_liq'])} | {_p(j['mdd_after'])} | {j['totals']['capital_gains_tax_krw'] / 1e4:,.0f} |")
    L += ["", "### 새틀라이트 15% 를 함께 둔 경우 (보조 표, 판정 아님 — SPY 를 15%p 줄이고 라이브 S-SEED-000)", "",
          "| | 세후 | 원화 MDD | SPY 대비 | 같은 셀(새틀라이트 없음) 대비 | 양도세 합(만 원) |", "|---|---|---|---|---|---|"]
    for n in JUDGED:
        s = r["satellite_secondary"][n]
        L.append(f"| {n} + 새틀라이트 15% | {_p(s['after_tax_liq'])} | {_p(s['mdd_krw'])} | {_p(s['diff_vs_spy'], True)} | {_p(s['diff_vs_cell'], True)} | {s['tax_paid_krw'] / 1e4:,.0f} |")
    t = r["sso_tracking"]
    L += ["", "### 합성 2배 vs 실제 SSO (보고만)", ""]
    if t.get("available"):
        L.append(f"{t['start']} ~ {t['end']}: 합성 연 {_p(t['synthetic_cagr'])}, SSO 연 {_p(t['sso_cagr'])}, 일별 차이 연 추적오차 {_p(t['tracking_error_annual'])}, 상관 {t['corr']:.3f}.")
    else:
        L.append("SSO 자료 없음.")
    L += ["", "## 읽는 법과 주의", "",
          "- 2배 상품은 매일 2배를 다시 맞추는 일일 리셋이다. 오르내림이 심한 횡보장에서는 변동성 감쇠로 기초 지수 2배보다 덜 번다. 장기 표는 이 효과를 그대로 포함한다.",
          "- 차입(BIL·RF + 연 1%)·보수(연 0.9%)는 가정이다. 실제 상품의 스왑 비용·추적오차는 다르다(SSO 비교 표 참고). 1927~2007 에는 이런 상품이 없었다 — 장기 결과는 '그런 상품이 있었다면'의 근사다.",
          "- 장기 필터 신호는 프렌치 시장 총수익 지수로 만든 200일선(가격 지수 아님)이다.",
          "- ETF 시대(2010~2024)는 이미 여러 연구가 본 자료다. 2024-10 이후는 보고만 한다. 세금은 추정(카카오페이 기본값, 양도세 22%·공제 250만 원)이다.",
          "- PASS 는 전진 원장에 올릴 후보라는 뜻이다. 엔진·챔피언은 바뀌지 않으며 반영은 사용자 확인 뒤 별도 작업이다. FAIL_UNDERPOWERED 는 '효과 없음'이 아니라 판별 불가에 가깝다.",
          "- 투자 권유가 아니다. 과거 결과는 앞으로의 수익을 보장하지 않는다."]
    return "\n".join(L) + "\n"


def smoke_coverage(r: dict) -> dict:
    lg, es = r["long_run"], r["etf_stats"]
    return {"long_filter_switches": all(lg[n]["switches_per_year"] > 0 for n in JUDGED),
            "etf_filter_switches": all(es[f"{n}|judged|30M"].get("switches_per_year", 0) > 0 for n in JUDGED),
            "etf_tax_paid": any(es[f"{n}|judged|30M"]["totals"]["capital_gains_tax_krw"] > 0 for n in JUDGED),
            "verdicts_present": all(n in r["verdicts"] for n in JUDGED),
            "sso_tracking": bool(r["sso_tracking"].get("available"))}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-sims-per-run", type=int, default=0, help="재개 확인용: 이번 실행에서 새로 할 시뮬레이션 수 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None

    def log(s: str) -> None:
        print(s, flush=True)

    def check_time(margin: float = 90.0) -> None:
        if deadline is not None and time.time() > deadline - margin:
            raise _Stop()

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        inputs = SV._load_ckpt(ck / "inputs.pkl", fp)
        if inputs is None:
            check_time()
            inputs = _smoke_inputs(log) if a.smoke else _real_inputs(log)
            rf, mkt = _french(a.smoke)
            inputs.update({"rf": rf, "mkt": mkt})
            SV._atomic_pickle(ck / "inputs.pkl", {"fingerprint": fp, "payload": inputs})
            log("입력 체크포인트 저장")
        long = SV._load_ckpt(ck / "long.pkl", fp)
        if long is None:
            check_time()
            long = long_run_table(inputs["mkt"], inputs["rf"])
            SV._atomic_pickle(ck / "long.pkl", {"fingerprint": fp, "payload": long})
            log("장기 표 저장")
        sims, new = {}, 0
        for key in sim_jobs():
            name, win, cap = key
            path = ck / f"sim_{name.replace('+', '_')}_{win}_{cap // 1_000_000}M.pkl"
            got = SV._load_ckpt(path, fp)
            if got is None:
                if a.max_sims_per_run and new >= a.max_sims_per_run:
                    raise _Stop()
                check_time()
                w, _info = build_weights(inputs, name, win)
                s = tx.simulate(w, inputs["close"], inputs["adj"], inputs["fx"], tx.AccountConfig(initial_krw=cap))
                st = inputs["state"] if name != "SPY" and not name.startswith("L25+") and name != "L25" else None
                got = _summ(s, w, inputs["adj"], cap, st)
                SV._atomic_pickle(path, {"fingerprint": fp, "payload": got})
                new += 1
                log(f"시뮬레이션 {key} 세후(청산) {got['cagr_after_liq']:.4f}")
            sims[key] = got
        result, rep = analyze(sims, long, inputs, a.smoke)
        if a.smoke:
            cov = smoke_coverage(result)
            result["smoke_coverage"] = cov
            bad = [k for k, ok in cov.items() if not ok]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
    except _Stop:
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(rep, encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
