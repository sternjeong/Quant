"""검증 연구 drawdown-cheap-v1 (사전 등록 2026-10-12, 트랙 B): SPY 대비 수익을 가장 적게 내주고 낙폭을 줄이는 방법이 있는가.

규칙 전문은 SPEC.md. 결과를 보기 전에 고정했고, 바꾸려면 새 id 로 새로 등록한다. 요약:
 후보 7개(모두 SPY 그냥 보유와 비교): B1_100/B1_200(SPY 가 SMA 위일 때만 SPY, 아니면 BIL; 월초 전일 종가 신호),
 B2_10/B2_12(변동성 목표 = min(1, 목표/63일 연율 변동성), 나머지 BIL, 월초 재설정), B3_85/B3_70(SPY/ERC 코어 85/15·70/30, 매년 첫 거래일 재조정),
 B4(SPY 80 + TLT 10 + GLD 10, 매년 재조정).
 PASS_FORWARD_CANDIDATE(B1/B2) 또는 PASS_ETF_ONLY(B3/B4) 는 모두 만족: (i) ETF 시대 판정 구간 세후 연수익 ≥ SPY − 1.0%p
 (ii) 두 절반 각각 ≥ SPY − 1.5%p (iii) 원화 MDD ≤ SPY 의 70% (iv) B1/B2 는 1927~2007 세전 장기: CAGR ≥ 시장 − 1.0%p 이고 MDD ≤ 시장의 70%.
 PASS 는 전진 원장에 올릴 후보까지만이며 채택이 아니다.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

RULES_VERSION = "drawdown-cheap/v1"
JUDGE_VERSION = "drawdown-cheap-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
SPY, BIL, TLT, GLD = "SPY", "BIL", "TLT", "GLD"
N_TRIALS = 7
CAPITAL = 30_000_000
CAPITAL_REPORT = 100_000_000
WINDOWS = {
    "judged": ("2010-01-04", "2024-09-30"),
    "h1": ("2010-01-04", "2017-05-31"),
    "h2": ("2017-06-01", "2024-09-30"),
    "crisis": ("2008-01-02", "2009-12-31"),   # 보고만
    "post": ("2024-10-01", None),             # 보고만
}
LONG_START, LONG_END = "1927-07-01", "2007-12-31"
LONG_REPORT_START = "2008-01-01"
MAX_GIVEUP_JUDGED = 0.010     # (i) SPY 보다 최대 1.0%p 덜
MAX_GIVEUP_HALF = 0.015       # (ii) 각 절반 1.5%p
MDD_RATIO_MAX = 0.70          # (iii)(iv) |MDD| ≤ 기준의 70%
LONG_MAX_GIVEUP = 0.010
SMA_100, SMA_200 = 100, 200
VOL_WINDOW = 63
VOL_TARGETS = {"B2_10": 0.10, "B2_12": 0.12}
BLEND_SHARE = {"B3_85": 0.85, "B3_70": 0.70}
B4_WEIGHTS = {SPY: 0.80, TLT: 0.10, GLD: 0.10}
CANDIDATES = ["B1_100", "B1_200", "B2_10", "B2_12", "B3_85", "B3_70", "B4"]
LONG_APPLICABLE = {"B1_100", "B1_200", "B2_10", "B2_12"}
LABELS = {
    "SPY": "SPY 그냥 보유", "B1_100": "B1 SPY 100일선 위만 보유(아래면 BIL)", "B1_200": "B1 SPY 200일선 위만 보유(아래면 BIL)",
    "B2_10": "B2 변동성 목표 10%", "B2_12": "B2 변동성 목표 12%",
    "B3_85": "B3 SPY 85% + ERC 코어 15%(매년 재조정)", "B3_70": "B3 SPY 70% + ERC 코어 30%(매년 재조정)",
    "B4": "B4 SPY 80% + TLT 10% + GLD 10%(매년 재조정)",
}
LONG_COST_BPS = 10.0          # 장기 자료 편도 비용(core-longrun-v1 과 같음)
REBAL_FLIP = 1e-7             # 연 재조정일을 '목표가 바뀐 날'로 만들기 위한 아주 작은 비중 흔들림(tax_fx 는 목표 변화일에만 매매)


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def _load_lab():
    spec = importlib.util.spec_from_file_location("core_longrun_lab", PROJECT_ROOT / "research" / "jobs" / "core-longrun-v1" / "lab.py")
    mod = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(spec))
    if not hasattr(mod, "Rule"):
        spec.loader.exec_module(mod)
    return mod


lab = _load_lab()


# =================================================================================================
# 신호·비중 (순수 함수 — 전일 종가까지의 정보만 쓴다)
# =================================================================================================

def month_first_flags(index: pd.DatetimeIndex) -> pd.Series:
    """각 달의 첫 거래일 True."""
    per = pd.Series(index.to_period("M"), index=index)
    return per != per.shift(1)


def year_first_flags(index: pd.DatetimeIndex) -> pd.Series:
    yr = pd.Series(index.year, index=index)
    return yr != yr.shift(1)


def _monthly_hold(raw_prior: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """raw_prior(전일 종가 기준으로 계산한 값, 이미 shift(1))를 월 첫 거래일에만 받아 다음 달 첫날까지 유지. 값이 없으면 1.0(보유)."""
    flag = month_first_flags(index)
    return raw_prior.where(flag).ffill().fillna(1.0)


def trend_exposure(close: pd.Series, window: int) -> pd.Series:
    """B1: 전일 종가 > 전일까지 window 일 단순이동평균 이면 1.0, 아니면 0.0 (월 첫 거래일에 갱신, 이동평균 없으면 1.0)."""
    sma = close.rolling(window).mean()
    raw = pd.Series(np.where(sma.isna(), 1.0, (close > sma).astype(float)), index=close.index)
    return _monthly_hold(raw.shift(1), close.index)


def vol_target_exposure(ret: pd.Series, target: float, window: int = VOL_WINDOW) -> pd.Series:
    """B2: min(1, 목표 / 전일까지 window 일 일별 수익의 연율 변동성). 월 첫 거래일에 갱신, 변동성 없거나 0 이면 1.0."""
    vol = ret.rolling(window).std(ddof=1) * math.sqrt(252)
    raw = (target / vol).clip(upper=1.0)
    raw = raw.where(vol.notna() & (vol > 0), 1.0)
    return _monthly_hold(raw.shift(1), ret.index)


def force_rebalance(weights: pd.DataFrame, flags: pd.Series) -> pd.DataFrame:
    """tx.simulate 는 목표 비중이 바뀐 날에만 매매한다. flags 날(연 재조정일)마다 행 전체를 (1 − 1e-7 × 홀짝)로 번갈아 곱해
    그날을 '목표 변경일'로 만든다(비중 오차 1e-7 — 무시 가능). 합이 1 을 넘지 않는다."""
    k = flags.astype(int).cumsum()
    factor = 1.0 - REBAL_FLIP * (k % 2)
    return weights.mul(factor, axis=0)


def two_asset_weights(exposure: pd.Series, risky: str = SPY, safe: str = BIL) -> pd.DataFrame:
    return pd.DataFrame({risky: exposure, safe: 1.0 - exposure})


def blend_weights(spy_ret: pd.Series, core_ret: pd.Series, core_w: pd.DataFrame, share: float) -> pd.DataFrame:
    """B3: SPY share + 코어 (1 − share). 슬리브 비중은 매년 첫 거래일에만 share 로 되돌리고 그 사이는 표류한다.
    코어의 내부 비중(월별 변경)이 바뀌는 날에는 SPY 도 '표류한 현재 비중'으로 맞춰(=SPY 를 사고팔지 않음) 슬리브 비율이 연 1회만 재조정되게 한다.
    표류는 세전 근사 수익으로 추적하므로 실제 계좌와 아주 조금 어긋날 수 있다."""
    idx = core_w.index
    cols = list(dict.fromkeys([SPY] + list(core_w.columns)))
    cw = core_w.reindex(columns=cols).fillna(0.0)
    sr = spy_ret.reindex(idx).fillna(0.0).to_numpy()
    cr = core_ret.reindex(idx).fillna(0.0).to_numpy()
    yfirst = year_first_flags(idx).to_numpy()
    core_arr = cw.to_numpy()
    changed = np.zeros(len(idx), dtype=bool)
    changed[1:] = np.abs(np.diff(core_arr, axis=0)).sum(axis=1) > 1e-12
    out = np.zeros_like(core_arr)
    spy_col = cols.index(SPY)
    a = share
    cur = None
    for i in range(len(idx)):
        if i > 0:  # 그날 수익으로 표류
            g_s, g_c = a * (1 + sr[i]), (1 - a) * (1 + cr[i])
            a = g_s / (g_s + g_c) if g_s + g_c > 0 else a
        if yfirst[i]:
            a = share
        if cur is None or yfirst[i] or changed[i]:
            row = (1 - a) * core_arr[i]
            row[spy_col] += a
            cur = row
        out[i] = cur
    w = pd.DataFrame(out, index=idx, columns=cols)
    return force_rebalance(w, pd.Series(yfirst, index=idx))


def static_weights(index: pd.DatetimeIndex, target: dict[str, float]) -> pd.DataFrame:
    w = pd.DataFrame({t: float(x) for t, x in target.items()}, index=index)
    return force_rebalance(w, year_first_flags(index))


def build_all_weights(close: pd.DataFrame, adj: pd.DataFrame, core_w: pd.DataFrame, core_ret: pd.Series) -> dict[str, pd.DataFrame]:
    """전체 기간 목표 비중(후보 7개 + SPY 그냥 보유). 구간별 시뮬레이션은 이를 잘라 쓴다(첫날은 그 구간 시작 비중 그대로 매수)."""
    idx = close.index
    spy_ret = adj[SPY].pct_change(fill_method=None).fillna(0.0)
    w: dict[str, pd.DataFrame] = {"SPY": pd.DataFrame({SPY: 1.0}, index=idx)}
    for name, win in (("B1_100", SMA_100), ("B1_200", SMA_200)):
        w[name] = two_asset_weights(trend_exposure(close[SPY], win))
    for name, tgt in VOL_TARGETS.items():
        w[name] = two_asset_weights(vol_target_exposure(spy_ret, tgt))
    for name, share in BLEND_SHARE.items():
        w[name] = blend_weights(spy_ret, core_ret, core_w.reindex(idx).fillna(0.0), share)
    w["B4"] = static_weights(idx, B4_WEIGHTS)
    return w


# =================================================================================================
# 장기(Ken French) 세전 — B1/B2 만
# =================================================================================================

def long_run_returns(mkt: pd.Series, rf: pd.Series, exposure: pd.Series, bps: float = LONG_COST_BPS) -> pd.Series:
    """전일 종가에 정한 시장 비중 e(t−1) 로 당일 수익: e·시장 + (1−e)·RF − 비용(|Δe| × 2 × bps, 매매가 일어난 다음 날 수익에서 차감)."""
    e = exposure.shift(1).fillna(1.0)
    gross = e * mkt + (1 - e) * rf.reindex(mkt.index).fillna(0.0)
    turnover = 2.0 * e.diff().abs().fillna(0.0)
    return gross - turnover * bps / 1e4


def long_run_exposures(mkt: pd.Series) -> dict[str, pd.Series]:
    level = (1 + mkt).cumprod()
    ret = mkt
    out = {"B1_100": trend_exposure(level, SMA_100), "B1_200": trend_exposure(level, SMA_200)}
    for name, tgt in VOL_TARGETS.items():
        out[name] = vol_target_exposure(ret, tgt)
    return out


def long_run_table(mkt: pd.Series, rf: pd.Series) -> dict[str, Any]:
    exps = long_run_exposures(mkt)
    out: dict[str, Any] = {}
    base = lab.window(mkt, LONG_START, LONG_END)
    base_full = mkt
    out["MARKET"] = {"cagr": lab.cagr(base), "mdd": lab.mdd(base), "cagr_2008_plus": lab.cagr(lab.window(mkt, LONG_REPORT_START)),
                     "mdd_2008_plus": lab.mdd(lab.window(mkt, LONG_REPORT_START)), "years": lab.years_of(base)}
    for name, e in exps.items():
        r_full = long_run_returns(mkt, rf, e)
        r = lab.window(r_full, LONG_START, LONG_END)
        ew = lab.window(e, LONG_START, LONG_END)
        out[name] = {"cagr": lab.cagr(r), "mdd": lab.mdd(r), "years": lab.years_of(r),
                     "cagr_2008_plus": lab.cagr(lab.window(r_full, LONG_REPORT_START)), "mdd_2008_plus": lab.mdd(lab.window(r_full, LONG_REPORT_START)),
                     "switches_per_year": float((ew.diff().abs() > 1e-9).sum() / max(lab.years_of(r), 1e-9)),
                     "mean_exposure": float(ew.mean()),
                     "active_ir": _ir((r - base).to_numpy()),
                     "noop": rp.noop_guard((r - base).to_numpy())}
    return out


def _ir(active: np.ndarray) -> Optional[float]:
    a = np.asarray(active, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 3 or a.std(ddof=1) <= 0:
        return None
    return float(a.mean() / a.std(ddof=1) * math.sqrt(252))


# =================================================================================================
# 판정 (사전 등록 — 순수 함수)
# =================================================================================================

def _ge(x: Optional[float], y: Optional[float]) -> bool:
    return x is not None and y is not None and math.isfinite(x) and math.isfinite(y) and x >= y - 1e-12


def mdd_ratio_ok(mdd: Optional[float], base_mdd: Optional[float]) -> bool:
    """|MDD| ≤ 기준 |MDD| × 70% (MDD 는 음수 또는 0)."""
    if mdd is None or base_mdd is None or not (math.isfinite(mdd) and math.isfinite(base_mdd)):
        return False
    return abs(mdd) <= MDD_RATIO_MAX * abs(base_mdd) + 1e-12


def judge_candidate(name: str, etf: dict, long: Optional[dict], noop_reason: Optional[str], etf_ir: Optional[float], power_etf: dict) -> dict:
    """etf: {cagr, spy_cagr, h1, spy_h1, h2, spy_h2, mdd, spy_mdd}  long: {cagr, mkt_cagr, mdd, mkt_mdd} 또는 None(해당 없음).
    반환: {verdict, checks, long_run: 'APPLIED'|'NOT_APPLICABLE'}"""
    if noop_reason:
        return {"verdict": "NOT_EVALUABLE", "checks": {}, "long_run": "NOT_APPLICABLE" if name not in LONG_APPLICABLE else "APPLIED", "note": noop_reason}
    checks = {
        "i_judged_return_within_1.0pp": _ge(etf.get("cagr"), None if etf.get("spy_cagr") is None else etf["spy_cagr"] - MAX_GIVEUP_JUDGED),
        "ii_h1_within_1.5pp": _ge(etf.get("h1"), None if etf.get("spy_h1") is None else etf["spy_h1"] - MAX_GIVEUP_HALF),
        "ii_h2_within_1.5pp": _ge(etf.get("h2"), None if etf.get("spy_h2") is None else etf["spy_h2"] - MAX_GIVEUP_HALF),
        "iii_krw_mdd_le_70pct_of_spy": mdd_ratio_ok(etf.get("mdd"), etf.get("spy_mdd")),
    }
    applicable = name in LONG_APPLICABLE
    if applicable:
        if long is None:
            return {"verdict": "NOT_EVALUABLE", "checks": checks, "long_run": "APPLIED", "note": "장기 자료 없음"}
        checks["iv_long_cagr_within_1.0pp"] = _ge(long.get("cagr"), None if long.get("mkt_cagr") is None else long["mkt_cagr"] - LONG_MAX_GIVEUP)
        checks["iv_long_mdd_le_70pct"] = mdd_ratio_ok(long.get("mdd"), long.get("mkt_mdd"))
    if all(checks.values()):
        return {"verdict": "PASS_FORWARD_CANDIDATE" if applicable else "PASS_ETF_ONLY", "checks": checks,
                "long_run": "APPLIED" if applicable else "NOT_APPLICABLE"}
    return {"verdict": rp.classify_fail(etf_ir, power_etf), "checks": checks, "long_run": "APPLIED" if applicable else "NOT_APPLICABLE"}


def efficiency(giveup: Optional[float], removed: Optional[float]) -> dict:
    """giveup = 내준 연수익(소수, 기준 − 후보), removed = 줄인 낙폭(소수, |기준 MDD| − |후보 MDD|). pp 단위로 돌려준다."""
    if giveup is None or removed is None or not (math.isfinite(giveup) and math.isfinite(removed)):
        return {"giveup_pp": None, "removed_pp": None, "pp_per_pp": None}
    gp, rpp = giveup * 100, removed * 100
    return {"giveup_pp": gp, "removed_pp": rpp, "pp_per_pp": (gp / rpp) if rpp > 1e-9 else None}


# =================================================================================================
# 시뮬레이션 (tx.simulate)
# =================================================================================================

def slice_weights(w: pd.DataFrame, start: str, end: Optional[str]) -> pd.DataFrame:
    return w.loc[pd.Timestamp(start): (pd.Timestamp(end) if end else None)]


def run_sim(weights: pd.DataFrame, close, adj, fx, capital: float) -> dict[str, Any]:
    cfg = tx.AccountConfig(initial_krw=capital)
    s = tx.simulate(weights, close, adj, fx, cfg)
    days = weights.index
    years = max((days[-1] - days[0]).days / 365.25, 1e-9)
    vals = s["values_krw"]
    change = weights.diff().abs().sum(axis=1) > 1e-9
    change.iloc[0] = True
    notional = s["totals"]["fees_krw"] / cfg.fee_rate
    tot = s["totals"]
    return {
        "values": vals, "years": years, "capital": capital,
        "cagr_after": float((s["final_after_liquidation_krw"] / capital) ** (1 / years) - 1) if s["final_after_liquidation_krw"] > 0 else float("nan"),
        "cagr_after_mtm": s["cagr_after"], "cagr_pre": s["cagr_pre"], "mdd_after": s["mdd_after"], "mdd_pre": s["mdd_pre"],
        "final_krw": s["final_krw"], "final_liq_krw": s["final_after_liquidation_krw"],
        "tax_paid_krw": tot["capital_gains_tax_krw"], "dividend_tax_krw": tot["dividend_tax_krw"], "fees_krw": tot["fees_krw"], "fx_cost_krw": tot["fx_cost_krw"],
        "unpaid_tax_krw": s["unpaid_tax_if_sold_now_krw"],
        "turnover_per_year": float(notional / 2 / max(float(vals.mean()), 1.0) / years),
        "trades_per_year": float(change.sum() / years),
        "start": str(days[0].date()), "end": str(days[-1].date()),
    }


def calendar_year_mdd(values: pd.Series, year: int) -> Optional[float]:
    v = values[values.index.year == year]
    if len(v) < 2:
        return None
    return float((v / v.cummax() - 1).min())


def _row_fmt_pct(x: Optional[float], signed: bool = False, nd: int = 1) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


# =================================================================================================
# 체크포인트
# =================================================================================================

def _atomic_pickle(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_ckpt(path: Path, fingerprint: dict):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)  # 이 스크립트가 쓴 파일만 읽는다
    except Exception:  # noqa: BLE001
        return None
    return obj["payload"] if obj.get("fingerprint") == fingerprint else None


# =================================================================================================
# 입력
# =================================================================================================

def _tickers() -> list[str]:
    from core import champion_strategy as cs

    return list(dict.fromkeys(list(cs.CORE_UNIVERSE) + [SPY, BIL, TLT, GLD]))


def _smoke_etf():
    tick = _tickers()
    idx = pd.bdate_range("2005-01-03", "2025-03-31")
    rng = np.random.default_rng(31)
    drift = np.full(len(idx), 0.0005)
    for a, b, d in (("2008-01-01", "2009-03-01", -0.0018), ("2020-02-20", "2020-03-23", -0.012), ("2022-01-03", "2022-10-14", -0.0008)):
        drift[(idx >= a) & (idx <= b)] = d
    mkt = rng.normal(0, 0.009, len(idx))
    close = pd.DataFrame({t: 50 * np.exp(np.cumsum(drift * (0.5 if t in (TLT, GLD) else 1.0) + mkt * (0.6 if t == TLT else 1.0)
                                                    + rng.normal(0.0001, 0.007, len(idx)))) for t in tick}, index=idx)
    close[BIL] = 90 + np.arange(len(idx)) * 0.002
    fx = pd.Series(1100.0 * np.exp(np.cumsum(rng.normal(0, 0.003, len(idx)))), index=idx)
    return close, close.copy(), fx


def _real_etf():
    from core.market_data import get_multiple_price_history

    tick = _tickers()
    h = get_multiple_price_history(tick, start="2005-06-01", end=None, interval="1d")
    close = pd.DataFrame({t: h[t]["Close"] for t in tick if t in h and not h[t].empty}).sort_index()
    adj = pd.DataFrame({t: h[t]["Adj Close"] for t in tick if t in h and not h[t].empty}).sort_index()
    for need in (SPY, BIL, TLT, GLD):
        if need not in close.columns:
            raise RuntimeError(f"{need} 가격을 받지 못함")
    days = close[SPY].dropna().index
    return close.reindex(days).ffill(), adj.reindex(days).ffill(), tx.usdkrw_series()


def _core(close: pd.DataFrame, adj: pd.DataFrame):
    from core import champion_strategy as cs
    from core import core_lab as cl

    core_cols = [t for t in cs.CORE_UNIVERSE if t in adj.columns]
    extra = adj[[SPY, BIL]]
    core_w = cl.build_weights(adj[core_cols], extra, cl.CoreConfig(cash="bil", weighting="erc"))
    core_ret = cl.portfolio_returns(adj[core_cols], extra, core_w.reindex(adj.index).fillna(0.0))
    return core_w, core_ret


def _french(smoke: bool):
    if smoke:
        d = lab.synthetic_data()
        return d["rf"], d["mkt"]
    from core import french_factors as ff

    ff3 = ff.load("ff3_daily")
    if ff3 is None:
        raise RuntimeError("Ken French 일별 FF3 자료를 받지 못함")
    rf = lab.to_weekdays(ff3["RF"].astype(float))
    mkt = lab.to_weekdays((ff3["Mkt-RF"] + ff3["RF"]).astype(float))
    idx = rf.index.intersection(mkt.index)
    return rf.reindex(idx), mkt.reindex(idx)


# =================================================================================================
# 분석·보고
# =================================================================================================

SIM_NAMES = ["SPY"] + CANDIDATES


def analyze(sims: dict[str, dict[str, dict]], long: dict, smoke: bool) -> tuple[dict, str]:
    j = {n: sims[n]["judged"] for n in SIM_NAMES}
    spy = j["SPY"]
    yrs_etf = spy["years"]
    long_years = long["MARKET"]["years"]
    power_etf = rp.power_report(yrs_etf, N_TRIALS)
    power_long = rp.power_report(long_years, N_TRIALS)
    verdicts, detail, eff_etf, eff_long = {}, {}, {}, {}
    for n in CANDIDATES:
        p = j[n]
        active = (p["values"].pct_change().fillna(0.0) - spy["values"].pct_change().fillna(0.0)).to_numpy()
        noop = rp.noop_guard(active)
        ir = _ir(active)
        etf = {"cagr": p["cagr_after"], "spy_cagr": spy["cagr_after"],
               "h1": sims[n]["h1"]["cagr_after"], "spy_h1": sims["SPY"]["h1"]["cagr_after"],
               "h2": sims[n]["h2"]["cagr_after"], "spy_h2": sims["SPY"]["h2"]["cagr_after"],
               "mdd": p["mdd_after"], "spy_mdd": spy["mdd_after"]}
        lg = None
        if n in LONG_APPLICABLE:
            lg = {"cagr": long[n]["cagr"], "mkt_cagr": long["MARKET"]["cagr"], "mdd": long[n]["mdd"], "mkt_mdd": long["MARKET"]["mdd"]}
        res = judge_candidate(n, etf, lg, noop, ir, power_etf)
        res.update({"etf": etf, "long": lg, "observed_ir_etf": ir})
        if n in LONG_APPLICABLE:
            res["observed_ir_long"] = long[n]["active_ir"]
            res["long_fail_kind"] = rp.classify_fail(long[n]["active_ir"], power_long)
        verdicts[n] = res["verdict"]
        detail[n] = res
        eff_etf[n] = efficiency(spy["cagr_after"] - p["cagr_after"], abs(spy["mdd_after"]) - abs(p["mdd_after"]))
        if n in LONG_APPLICABLE:
            eff_long[n] = efficiency(long["MARKET"]["cagr"] - long[n]["cagr"], abs(long["MARKET"]["mdd"]) - abs(long[n]["mdd"]))
        else:
            eff_long[n] = {"giveup_pp": None, "removed_pp": None, "pp_per_pp": None, "note": "NOT_APPLICABLE"}

    stats = {}
    for n in SIM_NAMES:
        s = sims[n]
        vals = s["judged"]["values"]
        stats[n] = {
            "label": LABELS[n],
            "after_tax_judged": s["judged"]["cagr_after"], "after_tax_mtm_judged": s["judged"]["cagr_after_mtm"], "pre_tax_judged": s["judged"]["cagr_pre"],
            "mdd_krw_judged": s["judged"]["mdd_after"], "mdd_pre_judged": s["judged"]["mdd_pre"],
            "mdd_2008_2009": s["crisis"]["mdd_after"], "mdd_2020": calendar_year_mdd(vals, 2020), "mdd_2022": calendar_year_mdd(vals, 2022),
            "turnover_per_year": s["judged"]["turnover_per_year"], "trades_per_year": s["judged"]["trades_per_year"],
            "tax_paid_krw": s["judged"]["tax_paid_krw"], "dividend_tax_krw": s["judged"]["dividend_tax_krw"], "fees_krw": s["judged"]["fees_krw"],
            "unpaid_tax_if_sold_krw": s["judged"]["unpaid_tax_krw"],
            "h1_after_tax": s["h1"]["cagr_after"], "h2_after_tax": s["h2"]["cagr_after"],
            "after_tax_2008_2009_report": s["crisis"]["cagr_after"], "after_tax_post_2024_10_report": s["post"]["cagr_after"],
            "after_tax_judged_100m_report": s["judged_100m"]["cagr_after"], "mdd_krw_judged_100m_report": s["judged_100m"]["mdd_after"],
        }
    result = {
        "judge_version": JUDGE_VERSION, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdicts": verdicts, "details": detail, "stats": stats, "long_run": long,
        "efficiency_etf": eff_etf, "efficiency_long": eff_long,
        "power": {"etf_era": power_etf, "long_run": power_long},
        "windows": WINDOWS, "long_window": [LONG_START, LONG_END],
    }
    return result, _report(result)


def _eff_cell(e: dict) -> str:
    if e.get("note"):
        return "해당 없음"
    if e["giveup_pp"] is None:
        return "—"
    if e["removed_pp"] is not None and e["removed_pp"] <= 1e-9:
        return f"낙폭 줄지 않음(수익 {e['giveup_pp']:.1f}%p 내줌)"
    if e["giveup_pp"] <= 0:
        return f"수익도 늘고 낙폭도 줄음(낙폭 {e['removed_pp']:.1f}%p 감소)"
    return f"{e['pp_per_pp']:.2f}%p/%p (수익 {e['giveup_pp']:.1f}%p 내주고 낙폭 {e['removed_pp']:.1f}%p 감소)"


def _report(r: dict) -> str:
    pc, st, v = _row_fmt_pct, r["stats"], r["verdicts"]
    L = [f"# 낙폭을 싸게 줄이는 방법 — drawdown-cheap-v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
         "트랙 B: SPY 그냥 보유 대비 최대낙폭을 줄이되 수익은 최소로 내주는 방법이 있는가. 후보 7개를 사전 등록 기준으로 판정했다. "
         "PASS 는 전진 원장에 올릴 후보라는 뜻이며 채택이 아니다.", "",
         rp.power_line(r["power"]["etf_era"]).replace("검정력(사전 계산)", "검정력(ETF 시대)"),
         rp.power_line(r["power"]["long_run"]).replace("검정력(사전 계산)", "검정력(장기 1927~2007)"), "",
         "## 판정", "", "| 후보 | 판정 | (i) 판정 구간 수익 | (ii) 전반 | (ii) 후반 | (iii) 원화 MDD | (iv) 장기 수익 | (iv) 장기 MDD |", "|---|---|---|---|---|---|---|---|"]
    ok = lambda x: "충족" if x else "미달"  # noqa: E731
    for n in CANDIDATES:
        c = r["details"][n].get("checks", {})
        L.append(f"| {LABELS[n]} | **{v[n]}** | {ok(c.get('i_judged_return_within_1.0pp'))} | {ok(c.get('ii_h1_within_1.5pp'))} | {ok(c.get('ii_h2_within_1.5pp'))} | "
                 f"{ok(c.get('iii_krw_mdd_le_70pct_of_spy'))} | {ok(c.get('iv_long_cagr_within_1.0pp')) if n in LONG_APPLICABLE else '해당 없음(NOT_APPLICABLE)'} | "
                 f"{ok(c.get('iv_long_mdd_le_70pct')) if n in LONG_APPLICABLE else '해당 없음(NOT_APPLICABLE)'} |")
    L += ["", f"판정 구간: ETF 시대 {WINDOWS['judged'][0]} ~ {WINDOWS['judged'][1]}(전반 {WINDOWS['h1'][0]}~{WINDOWS['h1'][1]}, 후반 {WINDOWS['h2'][0]}~{WINDOWS['h2'][1]}), "
          f"장기 {LONG_START} ~ {LONG_END}(세전, 프렌치 시장 = Mkt-RF+RF). 2008~2009 위기와 2024-10 이후는 보고만.", "",
          "## ETF 시대 — 세후·원화 (3,000만 원 시작, 카카오페이 가정: 수수료 0.1%, 환전 우대 95%, 양도세 22%·공제 250만 원, 배당 원천 15%)", "",
          "세후 연수익 = 마지막에 전부 팔았을 때 남는 금액 기준(미실현 양도세 차감). 전반·후반은 각 구간을 새 계좌로 따로 굴린 값.", "",
          "| | 세후 연수익 | 세전(원화) | 원화 MDD | 전반 세후 | 후반 세후 | 양도세 합(만 원) | 배당 원천세(만 원) | 연 회전율 | 연 매매일수 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for n in SIM_NAMES:
        s = st[n]
        L.append(f"| {s['label']} | {pc(s['after_tax_judged'])} | {pc(s['pre_tax_judged'])} | {pc(s['mdd_krw_judged'])} | {pc(s['h1_after_tax'])} | {pc(s['h2_after_tax'])} | "
                 f"{s['tax_paid_krw'] / 1e4:,.0f} | {s['dividend_tax_krw'] / 1e4:,.0f} | {s['turnover_per_year'] * 100:.0f}% | {s['trades_per_year']:.1f} |")
    L += ["", "연 회전율 = 편도 환산 거래대금 ÷ 평균 평가액 ÷ 연수(초기 매수·배당 재투자 포함). 세전(원화) = 비용·세금 없는 같은 비중의 원화 환산 수익.", "",
          "## 구간별 원화 MDD (보고만 — 판정 아님)", "", "| | 2008~2009 위기(새 계좌, 2008-01 시작) | 2020 | 2022 | 2024-10 이후 세후 연수익 | 2008~2009 세후 연수익 |", "|---|---|---|---|---|---|"]
    for n in SIM_NAMES:
        s = st[n]
        L.append(f"| {s['label']} | {pc(s['mdd_2008_2009'])} | {pc(s['mdd_2020'])} | {pc(s['mdd_2022'])} | {pc(s['after_tax_post_2024_10_report'])} | {pc(s['after_tax_2008_2009_report'])} |")
    L += ["", "2020·2022 는 판정 구간 계좌의 그 달력 연도 안 최대낙폭(그 해 안의 고점 기준). 2024-10 이후와 2008~2009 는 새 계좌로 따로 굴린 값.", "",
          "## 1억 원 시작 (보고만)", "", "| | 세후 연수익 | 원화 MDD |", "|---|---|---|"]
    for n in SIM_NAMES:
        s = st[n]
        L.append(f"| {s['label']} | {pc(s['after_tax_judged_100m_report'])} | {pc(s['mdd_krw_judged_100m_report'])} |")
    lg = r["long_run"]
    L += ["", f"## 장기 1927~2007 (세전, 프렌치 시장 대비; B3·B4 는 해당 없음 NOT_APPLICABLE)", "",
          "| | CAGR | MDD | 시장 대비 수익 | 평균 시장 비중 | 연 전환 횟수 | 2008~ CAGR(보고) | 2008~ MDD(보고) |", "|---|---|---|---|---|---|---|---|",
          f"| 시장(Mkt-RF+RF) 그냥 보유 | {pc(lg['MARKET']['cagr'])} | {pc(lg['MARKET']['mdd'])} | — | 100% | 0 | {pc(lg['MARKET']['cagr_2008_plus'])} | {pc(lg['MARKET']['mdd_2008_plus'])} |"]
    for n in CANDIDATES:
        if n in lg:
            x = lg[n]
            L.append(f"| {LABELS[n]} | {pc(x['cagr'])} | {pc(x['mdd'])} | {pc(x['cagr'] - lg['MARKET']['cagr'], True)} | {x['mean_exposure'] * 100:.0f}% | "
                     f"{x['switches_per_year']:.1f} | {pc(x['cagr_2008_plus'])} | {pc(x['mdd_2008_plus'])} |")
        else:
            L.append(f"| {LABELS[n]} | 해당 없음 | 해당 없음 | — | — | — | — | — |")
    L += ["", "## 효율표 — 낙폭 1%p 를 줄이려고 내준 연수익(%p)", "", "값이 작을수록 싸게 줄인 것. 수익은 SPY(또는 시장) − 후보 연수익, 낙폭은 |SPY MDD| − |후보 MDD|.", "",
          "| 후보 | ETF 시대(세후·원화) | 장기 1927~2007(세전) |", "|---|---|---|"]
    for n in CANDIDATES:
        L.append(f"| {LABELS[n]} | {_eff_cell(r['efficiency_etf'][n])} | {_eff_cell(r['efficiency_long'][n])} |")
    kinds = ", ".join(f"{n}={v[n]}" for n in CANDIDATES)
    L += ["", "## 사용자가 가져갈 것", "",
          f"판정: {kinds}. 표의 효율 열이 이 연구의 핵심이다 — 낙폭 방어에 수익을 얼마나 내주는지, 그리고 그 값이 SPY 그냥 보유와 비교해 허용 범위(수익 −1.0%p 이내, 낙폭 30% 이상 감소) 안인지를 본다. "
          "결과가 FAIL 이면 '싸게 줄이는 방법을 이 표본에서 찾지 못했다'이지, 방어가 무의미하다는 뜻이 아니다(FAIL_UNDERPOWERED 는 판별 불가에 가깝다).", "",
          "주의할 점(표본의 한계):",
          "- ETF 시대는 미국 주식 중심의 단일 경로(2010~2024)이며 큰 하락은 2020년과 2022년 정도뿐이다. 2008~2009 위기는 판정에 쓰지 않고 보고만 한다.",
          "- 추세 필터(B1)는 횡보장에서 잦은 신호 반전(whipsaw)으로 매번 비용과 양도세를 낸다. 장기 표의 연 전환 횟수와 ETF 시대의 양도세를 같이 본다.",
          "- 변동성 목표(B2)는 폭락이 변동성 상승보다 먼저 올 때(2020-02 같은 급락) 방어가 늦다.",
          "- B3·B4 는 장기 자료로 검증할 수 없어 PASS 여도 PASS_ETF_ONLY 로 약한 근거다(후보는 되지만 전진 원장에서 더 봐야 한다).",
          "- 후보 7개를 한꺼번에 본 것이므로 하나만 좋아 보여도 다중 비교를 감안한다(시도 7개로 검정력 계산). 세후 수익은 양도세 이연 효과가 큰 SPY 그냥 보유에 유리하다.",
          "- 통과해도 전진 원장에 올릴 후보이며, 엔진·챔피언 전략에는 사용자 확인 뒤 별도 작업으로만 반영한다."]
    return "\n".join(L) + "\n"


# =================================================================================================
# 실행
# =================================================================================================

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

    old_handler = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        inputs = _load_ckpt(ck / "inputs.pkl", fp)
        if inputs is None:
            close, adj, fx = _smoke_etf() if a.smoke else _real_etf()
            core_w, core_ret = _core(close, adj)
            weights = build_all_weights(close, adj, core_w, core_ret)
            rf, mkt = _french(a.smoke)
            inputs = {"close": close, "adj": adj, "fx": fx, "weights": weights, "rf": rf, "mkt": mkt}
            _atomic_pickle(ck / "inputs.pkl", {"fingerprint": fp, "payload": inputs})
            log("입력 체크포인트 저장")
        close, adj, fx, weights = inputs["close"], inputs["adj"], inputs["fx"], inputs["weights"]
        jobs = [(n, "judged", "judged", CAPITAL) for n in SIM_NAMES]
        jobs += [(n, w, w, CAPITAL) for w in ("h1", "h2", "crisis", "post") for n in SIM_NAMES]
        jobs += [(n, "judged_100m", "judged", CAPITAL_REPORT) for n in SIM_NAMES]
        sims: dict[str, dict[str, dict]] = {}
        new = 0
        for name, key, win, cap in jobs:
            path = ck / f"sim_{name}_{key}.pkl"
            got = _load_ckpt(path, fp)
            if got is None:
                if a.max_sims_per_run and new >= a.max_sims_per_run:
                    raise _Stop()
                check_time()
                log(f"시뮬레이션 {name} {key}")
                s, e = WINDOWS[win]
                got = run_sim(slice_weights(weights[name], s, e), close, adj, fx, cap)
                _atomic_pickle(path, {"fingerprint": fp, "payload": got})
                new += 1
            sims.setdefault(name, {})[key] = got
        long = long_run_table(inputs["mkt"], inputs["rf"])
        result, report = analyze(sims, long, a.smoke)
    except _Stop:
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old_handler is not None:
            _signal.signal(_signal.SIGTERM, old_handler)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
