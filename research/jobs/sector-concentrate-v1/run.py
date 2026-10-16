"""검증 연구 sector-concentrate-v1 (2026-10-16 사전 등록): 산업 주도 신호로 '수익 우선' 집중 투자를 하면 시장을 이기나.

사용자 요청(2026-10-16): 수익이 먼저, 안정성은 어느 정도. leader-catch-v1 은 산업 수준 주도 신호(6개월 모멘텀 F2,
12개월 시장 대비 상대강도 F5)가 아무도 보지 않은 1927~2007 자료에서 견고하다고 했고, 종목 단위 이전은 실패했다.
산업·섹터 포트폴리오에는 상장폐지 생존편향이 없다. 여기서는 주식 100%·집중(상위 1~2개)·시장 필터 없음으로 쓴다.

규칙 전체는 SPEC.md(한국어)와 아래 상수에 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 다시 등록한다. 엔진 반영은 사용자 확인 뒤 별도 작업.
자료 정리(평일 달력·결측)와 CAPM(NW6)은 core-longrun-v1/lab.py 를 그대로 import 해서 쓴다.
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

_spec = importlib.util.spec_from_file_location("core_longrun_lab", PROJECT_ROOT / "research/jobs/core-longrun-v1/lab.py")
lab = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(_spec))
if not hasattr(lab, "Rule"):
    _spec.loader.exec_module(lab)

JOB_ID = "sector-concentrate-v1"
RULES_VERSION = "sector-concentrate-v1/2026-10-16"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
MAIN_START, MAIN_END = "1927-07-01", "2007-12-31"
COMPARE_START = "2008-01-01"
SUBPERIODS = (("1927-07-01", "1946-12-31"), ("1947-01-01", "1966-12-31"),
              ("1967-01-01", "1986-12-31"), ("1987-01-01", "2007-12-31"))
W_M6, W_RS = 126, 252
SIGNALS = ("M6", "RS12", "C")
KS = (1, 2)
CELLS = tuple(f"{s}_k{k}" for s in SIGNALS for k in KS)
N_TRIALS = 6
POWER_YEARS = 80.5
COST_BPS = 10.0
MIN_VALID_FACTOR = 2           # 신호가 유한한 구성원이 2k 미만인 달은 시장(전액 투자) 보유
CAGR_MARGIN = 0.015            # (a) 시장 + 1.5%p
WORST12_SLACK = 0.05           # (c) 최악 12개월 ≥ 시장 최악 − 5%p
SUB_MIN_BEAT = 3               # (d) 4개 하위 구간 중 3개 이상
ALPHA_T_MIN = 2.0              # (e)
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"

# 한국 세금 근사(보고만): 3,000만 원 계좌, 1달러 = 1,300원 고정, 22%·공제 250만 원·결손 이월 없음, 수수료 = 편도 10bp
TAX_INITIAL_KRW = 30_000_000
TAX_FX_CONST = 1300.0

# ETF 보조 시험
ETF_SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC"]
ETF_MARKET = "SPY"
ETF_DATA_START = "1998-12-01"
ETF_WINDOWS = {"judged": ("2000-01-01", "2024-09-30"), "post": ("2024-10-01", None)}
ETF_SPY_MARGIN = 0.005
SUPPORTING, NOT_SUPPORTING = "SUPPORTING", "NOT_SUPPORTING"


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


# =================================================================================================
# 신호·선택 (모두 결정일 d 전 거래일 종가까지의 자료만)
# =================================================================================================

def raw_signals(rets: pd.DataFrame, mkt: pd.Series) -> dict[str, pd.DataFrame]:
    """행 i 의 값 = 행 i 까지(포함)의 자료. 결정일 d 에는 행 d−1 의 값을 쓴다."""
    lr = np.log1p(rets)
    mlr = np.log1p(mkt.reindex(rets.index).fillna(0.0))
    m6 = np.expm1(lr.rolling(W_M6, min_periods=W_M6).sum())
    mk12 = np.expm1(mlr.rolling(W_RS, min_periods=W_RS).sum())
    rs12 = np.expm1(lr.rolling(W_RS, min_periods=W_RS).sum()).sub(mk12, axis=0)
    both = m6.notna() & rs12.notna()
    # 순위는 두 신호가 모두 있는 구성원 사이에서
    r1b = m6.where(both).rank(axis=1, pct=True)
    r2b = rs12.where(both).rank(axis=1, pct=True)
    c = (r1b + r2b) / 2.0
    return {"M6": m6, "RS12": rs12, "C": c}


def decision_rows(index: pd.DatetimeIndex) -> np.ndarray:
    """매월 첫 거래일의 행 위치(첫 행 제외 — 그 앞 종가가 없다)."""
    pos = np.flatnonzero(lab.month_first_mask(index))
    return pos[pos >= 1]


def select_top(scores_row: np.ndarray, k: int) -> Optional[list[int]]:
    """유한한 점수 상위 k 개(동점은 열 순서). 유효 구성원이 2k 미만이면 None(→ 시장 보유)."""
    fin = np.isfinite(scores_row)
    if fin.sum() < MIN_VALID_FACTOR * k:
        return None
    order = np.argsort(-np.where(fin, scores_row, -np.inf), kind="stable")[:k]
    return [int(j) for j in order]


def pick_schedule(rets: pd.DataFrame, mkt: pd.Series, signal: str, k: int) -> list[tuple[int, Optional[list[int]]]]:
    """[(결정 행 d, 선택 열 목록 또는 None)] — 점수는 행 d−1 값."""
    sc = raw_signals(rets, mkt)[signal].to_numpy()
    return [(int(d), select_top(sc[d - 1], k)) for d in decision_rows(rets.index)]


# =================================================================================================
# 포트폴리오 (월 1회 동일가중으로 다시 맞추고 그 사이는 가격대로 표류, 언제나 100% 투자)
# =================================================================================================

def simulate(rets: pd.DataFrame, mkt: pd.Series, schedule: list, k: int, bps: float = COST_BPS) -> dict[str, Any]:
    """결정일 d 종가에 체결(수익은 d+1 부터). 첫 유효 선택 전과 선택이 None 인 달은 시장(Mkt) 100%.
    비용 = Σ|목표 − 표류 비중| × 편도 bp (시장 ↔ 산업 전환도 1.0 의 양쪽으로 센다). 반환: 일별 수익·편도 회전율(일별)·보유 기록."""
    R = rets.fillna(0.0).to_numpy()
    M = mkt.reindex(rets.index).fillna(0.0).to_numpy()
    n, m = R.shape
    h = np.zeros(m)          # 산업 비중
    hm = 1.0                 # 시장 비중(대체 보유)
    sched = dict(schedule)
    out = np.zeros(n)
    turn = np.zeros(n)
    invested = np.zeros(n)
    holds: list[dict] = []
    for i in range(n):
        if i > 0:
            g = h * (1 + R[i])
            gm = hm * (1 + M[i])
            tot = g.sum() + gm
            out[i] = tot - 1.0      # 합 = 1 이므로 그대로 수익
            h, hm = g / tot, gm / tot
        if i in sched:
            picks = sched[i]
            tgt = np.zeros(m)
            tm = 1.0
            if picks is not None:
                tgt[picks] = 1.0 / k
                tm = 0.0
            tv = float(np.abs(tgt - h).sum() + abs(tm - hm))
            if i > 0:
                out[i] = (1 + out[i]) * (1 - tv * bps / 10000.0) - 1
            turn[i] = tv / 2.0
            h, hm = tgt, tm
            holds.append({"row": i, "picks": picks})
        invested[i] = h.sum() + hm
    idx = rets.index
    return {"returns": pd.Series(out, index=idx), "turnover": pd.Series(turn, index=idx),
            "invested": pd.Series(invested, index=idx), "holds": holds}


def target_weight_frame(rets: pd.DataFrame, schedule: list, k: int, market_col: str) -> pd.DataFrame:
    """tax_fx.simulate 용 목표 비중(결정일부터 다음 결정일 전까지 같은 행). 선택이 같은 달도 다시 맞추도록
    번갈아 전체를 1e-8 만큼 줄여 '바뀐 날'로 표시한다(현금 1e-8 — 결과에 영향 없음, spy-champion-v1 과 같은 방법)."""
    cols = list(rets.columns) + [market_col]
    W = np.zeros((len(rets), len(cols)))
    W[:, -1] = 1.0
    ds = [d for d, _ in schedule] + [len(rets)]
    toggle = False
    for (d, picks), e in zip(schedule, ds[1:]):
        row = np.zeros(len(cols))
        if picks is None:
            row[-1] = 1.0
        else:
            row[picks] = 1.0 / k
        toggle = not toggle
        if toggle:
            row = row * (1 - 1e-8)
        W[d:e] = row
    return pd.DataFrame(W, index=rets.index, columns=cols)


# =================================================================================================
# 지표
# =================================================================================================

def window(s: pd.Series, a: str, b: Optional[str]) -> pd.Series:
    return s.loc[pd.Timestamp(a): (pd.Timestamp(b) if b else None)]


def values_from_returns(r: pd.Series) -> pd.Series:
    return (1 + r).cumprod()


def max_drawdown(values: pd.Series, base: float = 1.0) -> float:
    """시작 값(base)을 첫 고점으로 포함한 최대 낙폭(음수)."""
    v = np.r_[base, values.to_numpy(dtype=float)]
    return float((v / np.maximum.accumulate(v) - 1).min())


def worst_rolling_12m(values: pd.Series, base: float = 1.0) -> Optional[float]:
    """월말 값 기준 연속 12개월 수익의 최솟값(시작 값 base 를 첫 월말 앞에 둔다). 12개월이 안 되면 None."""
    me = values.groupby(values.index.to_period("M")).last().to_numpy(dtype=float)
    v = np.r_[base, me]
    if len(v) < 13:
        return None
    return float((v[12:] / v[:-12] - 1).min())


def longest_underwater(values: pd.Series, base: float = 1.0) -> dict[str, Any]:
    """고점 → 그 고점 회복까지 가장 긴 달력 일수. 끝까지 회복 못 하면 ongoing."""
    idx = values.index
    v = values.to_numpy(dtype=float)
    peak, peak_d = base, idx[0]
    best = {"days": 0, "peak": None, "recovered": None, "ongoing": False}
    under = False
    for d, x in zip(idx, v):
        if x >= peak:
            if under:
                days = (d - peak_d).days
                if days > best["days"]:
                    best = {"days": days, "peak": str(peak_d.date()), "recovered": str(d.date()), "ongoing": False}
            peak, peak_d, under = x, d, False
        else:
            under = True
    if under:
        days = (idx[-1] - peak_d).days
        if days > best["days"]:
            best = {"days": days, "peak": str(peak_d.date()), "recovered": None, "ongoing": True}
    best["years"] = round(best["days"] / 365.25, 1)
    return best


def cagr_of(r: pd.Series) -> float:
    return lab.cagr(r) if len(r) > 1 else float("nan")


def annual_turnover(turn: pd.Series) -> float:
    y = lab.years_of(turn)
    return float(turn.sum() / y) if y > 0 else float("nan")


def subperiod_rows(s: pd.Series, mkt: pd.Series) -> list[dict]:
    rows = []
    for a, b in SUBPERIODS:
        cs, cm = cagr_of(window(s, a, b)), cagr_of(window(mkt, a, b))
        rows.append({"start": a, "end": b, "cagr": cs, "market_cagr": cm, "beat": bool(cs > cm)})
    return rows


def evaluate(strat: dict, mkt: pd.Series, rf: pd.Series, a: str, b: Optional[str], subperiods: bool = True) -> dict[str, Any]:
    s, m = window(strat["returns"], a, b), window(mkt, a, b)
    vs, vm = values_from_returns(s), values_from_returns(m)
    cp = lab.capm(s, mkt, rf)
    subs = subperiod_rows(strat["returns"], mkt) if subperiods else []
    st = {"cagr": cagr_of(s), "mdd": max_drawdown(vs), "worst_12m": worst_rolling_12m(vs),
          "sharpe_monthly": lab.sharpe_monthly(s, rf), "underwater": longest_underwater(vs),
          "turnover_per_year": annual_turnover(window(strat["turnover"], a, b)),
          "min_invested": float(window(strat["invested"], a, b).min())}
    mk = {"cagr": cagr_of(m), "mdd": max_drawdown(vm), "worst_12m": worst_rolling_12m(vm),
          "sharpe_monthly": lab.sharpe_monthly(m, rf), "underwater": longest_underwater(vm)}
    checks = criteria(st, mk, subs, cp) if subperiods else criteria(st, mk, None, cp)
    return {"window": [a, b], "strategy": st, "market": mk, "capm": cp, "subperiods": subs, "checks": checks,
            "noop": rp.noop_guard((s - m).tolist())}


def criteria(st: dict, mk: dict, subs: Optional[list], cp: dict) -> dict[str, Optional[bool]]:
    """사전 등록 관문 (a)~(e). 값이 없으면 None."""
    def ok(x):
        return x is not None and isinstance(x, (int, float)) and math.isfinite(x)
    w_s, w_m = st.get("worst_12m"), mk.get("worst_12m")
    return {
        "a_cagr": (st["cagr"] >= mk["cagr"] + CAGR_MARGIN) if ok(st["cagr"]) and ok(mk["cagr"]) else None,
        "A_mdd": (st["mdd"] >= mk["mdd"]) if ok(st["mdd"]) and ok(mk["mdd"]) else None,
        "B_worst12": (w_s >= w_m - WORST12_SLACK) if ok(w_s) and ok(w_m) else None,
        "d_subperiods": (sum(x["beat"] for x in subs) >= SUB_MIN_BEAT) if subs else None,
        "e_alpha_t": (cp["alpha_t_nw6"] >= ALPHA_T_MIN) if ok(cp.get("alpha_t_nw6")) else None,
    }


def cell_verdict(checks: dict, noop: Optional[str], observed_ir: Optional[float], power: dict) -> str:
    """모든 관문 통과 → PASS_FORWARD_CANDIDATE. 무효 실행 → NOT_EVALUABLE. 그 밖 → classify_fail(FAIL / FAIL_UNDERPOWERED)."""
    if noop:
        return NOT_EVALUABLE
    if all(v is True for v in checks.values()):
        return PASS
    return rp.classify_fail(observed_ir, power)


def overall(verdicts: dict) -> str:
    n = sum(v == PASS for v in verdicts.values())
    return f"{PASS} ({n}/{len(verdicts)})" if n else "NO_PASS"


# =================================================================================================
# 한국 세금 근사 (보고만)
# =================================================================================================

def tax_inputs(rets: pd.DataFrame, mkt: pd.Series, a: str, b: Optional[str]) -> dict:
    """산업·시장 누적 지수를 가격(종가 = 조정가, 배당 없음 — 총수익 지수)으로 쓴다."""
    px = pd.concat([rets.fillna(0.0), mkt.rename("MKT").fillna(0.0)], axis=1)
    lev = (1 + px).cumprod()
    lev = lev.loc[pd.Timestamp(a): (pd.Timestamp(b) if b else None)]
    return {"close": lev, "adj": lev, "fx": pd.Series(TAX_FX_CONST, index=lev.index)}


def tax_drag(weights: pd.DataFrame, inp: dict, a: str, b: Optional[str]) -> dict:
    w = weights.loc[pd.Timestamp(a): (pd.Timestamp(b) if b else None)]
    res = {}
    for key, apply in (("no_tax", False), ("tax", True)):
        cfg = tx.AccountConfig(initial_krw=TAX_INITIAL_KRW, fee_rate=COST_BPS / 10000.0, fx_spread=0.0,
                               apply_tax=apply, apply_dividend_tax=False)
        s = tx.simulate(w, inp["close"], inp["adj"], inp["fx"], cfg)
        res[key] = liq_cagr(s["final_after_liquidation_krw"], TAX_INITIAL_KRW, w.index[0], w.index[-1])
        if apply:
            res["capital_gains_tax_krw"] = s["totals"]["capital_gains_tax_krw"]
            res["unpaid_tax_if_sold_now_krw"] = s["unpaid_tax_if_sold_now_krw"]
    res["drag_pp"] = res["no_tax"] - res["tax"]
    return res


def liq_cagr(final: float, initial: float, t0: pd.Timestamp, t1: pd.Timestamp) -> float:
    y = (t1 - t0).days / 365.25
    return float((final / initial) ** (1 / y) - 1) if y > 0 and final > 0 else float("nan")


# =================================================================================================
# ETF 보조 시험 (세후 원화, 카카오 기본값, 3,000만 원)
# =================================================================================================

def etf_after_tax(sim: dict, initial: float) -> dict:
    v = sim["values_krw"]
    return {"cagr_after_liq": liq_cagr(sim["final_after_liquidation_krw"], initial, v.index[0], v.index[-1]),
            "cagr_after": sim["cagr_after"], "cagr_pre": sim["cagr_pre"],
            "mdd": max_drawdown(v, initial), "worst_12m": worst_rolling_12m(v, initial),
            "tax_paid_krw": sim["totals"]["capital_gains_tax_krw"], "fees_krw": sim["totals"]["fees_krw"],
            "first": str(v.index[0].date()), "last": str(v.index[-1].date())}


def etf_verdict(c: dict, spy: dict) -> str:
    """SUPPORTING iff 세후(청산) CAGR ≥ SPY + 0.5%p AND 최대낙폭이 SPY 보다 나쁘지 않음 AND 최악 12개월 ≥ SPY 최악 − 5%p."""
    try:
        ok = (c["cagr_after_liq"] >= spy["cagr_after_liq"] + ETF_SPY_MARGIN and c["mdd"] >= spy["mdd"]
              and c["worst_12m"] is not None and spy["worst_12m"] is not None
              and c["worst_12m"] >= spy["worst_12m"] - WORST12_SLACK)
    except (TypeError, KeyError):
        ok = False
    return SUPPORTING if ok else NOT_SUPPORTING


def load_etf_real() -> dict:
    from core.market_data import get_multiple_price_history

    tick = ETF_SECTORS + [ETF_MARKET]
    h = get_multiple_price_history(tick, start=ETF_DATA_START, end=None, interval="1d") or {}
    close, adj = {}, {}
    for t in tick:
        df = h.get(t)
        if df is None or df.empty:
            continue
        for store, col in ((close, "Close"), (adj, "Adj Close" if "Adj Close" in df and df["Adj Close"].notna().any() else "Close")):
            s = df[col].dropna()
            s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
            store[t] = s[~s.index.duplicated(keep="last")]
    if ETF_MARKET not in adj:
        raise RuntimeError("SPY 가격을 받지 못함")
    days = adj[ETF_MARKET].index
    close, adj = pd.DataFrame(close).reindex(days), pd.DataFrame(adj).reindex(days)
    fx = tx.usdkrw_series()
    if fx.index.min() > pd.Timestamp("2000-01-31"):
        raise RuntimeError("원/달러 환율이 2000-01 이전부터 없음(FRED DEXKOUS 필요)")
    return {"close": close, "adj": adj, "fx": fx, "source": "yfinance (Close / Adj Close), USDKRW via tax_fx.usdkrw_series",
            "missing": sorted(set(tick) - set(adj.columns))}


def synthetic_etf(seed: int = 5) -> dict:
    idx = pd.bdate_range(ETF_DATA_START, "2026-06-30")
    n = len(idx)
    rng = np.random.default_rng(seed)
    mk = rng.normal(0.0003, 0.011, n)
    k = len(ETF_SECTORS)
    blocks = np.arange(n) // 250
    trend = rng.normal(0, 0.0006, (blocks.max() + 1, k))[blocks]
    ret = mk[:, None] * np.linspace(0.6, 1.4, k) + trend + rng.normal(0, 0.006, (n, k))
    r = pd.DataFrame(np.c_[ret, mk], index=idx, columns=ETF_SECTORS + [ETF_MARKET])
    adj = 50 * (1 + r).cumprod()
    q = pd.Series(idx.to_period("Q"), index=idx)
    step = (q != q.shift(1)).cumsum().to_numpy()
    close = adj.mul(0.996 ** (-step) * 0.996 ** step.max(), axis=0)   # 분기마다 0.4% 배당(종가/조정가 비율 계단)
    adj.loc[idx < "2015-10-08", "XLRE"] = np.nan
    close.loc[idx < "2015-10-08", "XLRE"] = np.nan
    adj.loc[idx < "2018-06-19", "XLC"] = np.nan
    close.loc[idx < "2018-06-19", "XLC"] = np.nan
    fx = pd.Series(1100 + np.cumsum(rng.normal(0, 3, n)), index=idx).clip(lower=800)
    return {"close": close, "adj": adj, "fx": fx, "source": "synthetic ETF (smoke)", "missing": []}


def etf_prepare(inp: dict) -> dict:
    adj = inp["adj"]
    rets = adj.pct_change(fill_method=None).iloc[1:]
    sectors = [t for t in ETF_SECTORS if t in rets.columns]
    sec = lab.clean_industry(rets[sectors])
    return {"rets": sec, "mkt": rets[ETF_MARKET].fillna(0.0),
            "close": inp["close"].bfill(), "adj": inp["adj"].bfill(), "fx": inp["fx"]}


def etf_weights(prep: dict, signal: str, k: int, a: str, b: Optional[str]) -> pd.DataFrame:
    sched = pick_schedule(prep["rets"], prep["mkt"], signal, k)
    w = target_weight_frame(prep["rets"], sched, k, ETF_MARKET)
    w = w.loc[pd.Timestamp(a): (pd.Timestamp(b) if b else None)]
    return w


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


def _load_ckpt(path: Path, fp: dict):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
        return obj["payload"] if obj.get("fingerprint") == fp else None
    except Exception:  # noqa: BLE001 — 깨진 체크포인트는 다시 계산
        return None


# =================================================================================================
# 계산 단계
# =================================================================================================

def industry_stage(data: dict, power: dict) -> dict:
    rf, mkt = data["rf"], data["mkt"]
    out: dict[str, Any] = {"cells": {}, "ind49": {}, "compare_2008": {}, "yearly": {}, "data_end": str(data["ind12"].index[-1].date())}
    for name, panel in (("ind12", data["ind12"]), ("ind49", data.get("ind49"))):
        if panel is None:
            continue
        for sig in SIGNALS:
            for k in KS:
                cell = f"{sig}_k{k}"
                sched = pick_schedule(panel, mkt, sig, k)
                st = simulate(panel, mkt, sched, k)
                ev = evaluate(st, mkt, rf, MAIN_START, MAIN_END)
                ev["verdict"] = cell_verdict(ev["checks"], ev["noop"], ev["capm"]["appraisal_ir"], power)
                if name == "ind12":
                    out["cells"][cell] = ev
                    out["compare_2008"][cell] = evaluate(st, mkt, rf, COMPARE_START, None, subperiods=False)
                    yt = lab.yearly_table(window(st["returns"], MAIN_START, None), window(mkt, MAIN_START, None))
                    out["yearly"][cell] = {str(y["year"]): round(y["strategy"], 4) for y in yt}
                    out["yearly"]["MKT"] = {str(y["year"]): round(y["market"], 4) for y in yt}
                    out.setdefault("_sched", {})[cell] = sched
                    out.setdefault("recent_picks", {})[cell] = [
                        {"date": str(panel.index[h["row"]].date()),
                         "picks": None if h["picks"] is None else [panel.columns[j] for j in h["picks"]]}
                        for h in st["holds"][-6:]]
                else:
                    out["ind49"][cell] = ev
    return out


def smoke_coverage(res: dict) -> dict:
    cells = res["industry"]["cells"]
    return {
        "six_cells": len(cells) == len(CELLS),
        "ind49": len(res["industry"]["ind49"]) == len(CELLS),
        "always_invested": all(abs(c["strategy"]["min_invested"] - 1.0) < 1e-9 for c in cells.values()),
        "tax_engine": all(math.isfinite(v["drag_pp"]) for v in res["tax_drag"].values() if v),
        "tax_paid_somewhere": any((v or {}).get("capital_gains_tax_krw", 0) > 0 for v in res["tax_drag"].values()),
        "etf_judged": all(f"{c}|judged" in res["etf"]["sims"] for c in CELLS),
        "etf_post": all(f"{c}|post" in res["etf"]["sims"] for c in CELLS),
        "etf_verdicts": set(res["etf"]["verdicts"].values()) <= {SUPPORTING, NOT_SUPPORTING},
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-steps-per-run", type=int, default=0, help="재개 확인용: 이번 실행에서 새로 할 단계 수 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    power = rp.power_report(POWER_YEARS, N_TRIALS)  # 결과를 보기 전에(구간·시도 수만)
    steps = {"new": 0}

    def log(s: str) -> None:
        print(s, flush=True)

    def check_time(margin: float = 90.0) -> None:
        if deadline is not None and time.time() > deadline - margin:
            raise _Stop()

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    def stage(name: str, fn):
        path = ck / f"{name}.pkl"
        got = _load_ckpt(path, fp)
        if got is None:
            if a.max_steps_per_run and steps["new"] >= a.max_steps_per_run:
                raise _Stop()
            check_time()
            got = fn()
            _atomic_pickle(path, {"fingerprint": fp, "payload": got})
            steps["new"] += 1
            log(f"단계 저장: {name}")
        return got

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        data = stage("french", lambda: lab.synthetic_data() if a.smoke else lab.load_real())
        ind = stage("industry", lambda: industry_stage(data, power))
        drags = {}
        tin = tax_inputs(data["ind12"], data["mkt"], MAIN_START, MAIN_END)
        for cell in CELLS:
            k = int(cell[-1])
            w = target_weight_frame(data["ind12"], ind["_sched"][cell], k, "MKT")
            drags[cell] = stage(f"tax_{cell}", lambda w=w: tax_drag(w, tin, MAIN_START, MAIN_END))
        wm = pd.DataFrame(0.0, index=data["ind12"].index, columns=list(data["ind12"].columns) + ["MKT"])
        wm["MKT"] = 1.0
        drags["MKT"] = stage("tax_MKT", lambda: tax_drag(wm, tin, MAIN_START, MAIN_END))

        einp = stage("etf_inputs", lambda: synthetic_etf() if a.smoke else load_etf_real())
        prep = etf_prepare(einp)
        cfg = tx.AccountConfig()
        sims = {}
        for win, (wa, wb) in ETF_WINDOWS.items():
            for cell in CELLS + ("SPY",):
                def run(cell=cell, wa=wa, wb=wb):
                    if cell == "SPY":
                        idx = prep["adj"].loc[pd.Timestamp(wa): (pd.Timestamp(wb) if wb else None)].index
                        w = tx.buy_and_hold_weights(idx, ETF_MARKET)
                    else:
                        sig, k = cell.rsplit("_k", 1)
                        w = etf_weights(prep, sig, int(k), wa, wb)
                    s = tx.simulate(w, prep["close"], prep["adj"], prep["fx"], cfg)
                    return etf_after_tax(s, cfg.initial_krw)
                sims[f"{cell}|{win}"] = stage(f"etf_{cell}_{win}", run)
        etf_v = {c: etf_verdict(sims[f"{c}|judged"], sims["SPY|judged"]) for c in CELLS}
        res = {"industry": ind, "tax_drag": drags, "etf": {"sims": sims, "verdicts": etf_v,
                                                          "source": einp["source"], "missing": einp.get("missing", [])}}
        result = build_result(res, power, a.smoke, data["source"])
        if a.smoke:
            cov = smoke_coverage(res)
            result["smoke_coverage"] = cov
            bad = [k for k, v in cov.items() if not v]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
    except _Stop:
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(render(result), encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


def _r(x, nd=4):
    if isinstance(x, float):
        return round(x, nd) if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, list):
        return [_r(v, nd) for v in x]
    return x


def build_result(res: dict, power: dict, smoke: bool, source: str) -> dict:
    ind = res["industry"]
    cell_v = {c: ind["cells"][c]["verdict"] for c in CELLS}
    if smoke:
        cell_v = {c: f"SMOKE_ONLY({v})" for c, v in cell_v.items()}
    verdicts = dict(cell_v)
    verdicts["overall"] = overall({c: ind["cells"][c]["verdict"] for c in CELLS}) if not smoke else "SMOKE_ONLY"
    sup = [c for c, v in res["etf"]["verdicts"].items() if v == SUPPORTING]
    verdicts["etf_supporting"] = f"{len(sup)}/{len(CELLS)}" + (f" ({', '.join(sup)})" if sup else "")
    return _r({"judge_version": RULES_VERSION, "smoke": smoke, "source": source,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "verdicts": verdicts, "power": power,
               "rule": {"universe": "Ken French 12 industries daily value-weighted (weekday calendar)", "market": "Mkt-RF + RF",
                        "signals": {"M6": f"{W_M6}-row return", "RS12": f"{W_RS}-row return − market {W_RS}-row return",
                                    "C": "mean cross-sectional pct rank of M6 and RS12"},
                        "k": list(KS), "weighting": "equal, monthly rebalance, drift between, 100% invested (market if <2k valid)",
                        "timing": "signal = close before first trading day d; trade at close of d",
                        "cost_bps_one_way": COST_BPS, "judged": [MAIN_START, MAIN_END], "subperiods": SUBPERIODS,
                        "n_trials": N_TRIALS},
               "thresholds": {"cagr_margin": CAGR_MARGIN, "A": "mdd >= market mdd", "B_slack": WORST12_SLACK,
                              "sub_min_beat": SUB_MIN_BEAT, "alpha_t_min": ALPHA_T_MIN,
                              "etf": {"after_tax_margin_vs_spy": ETF_SPY_MARGIN, "judged": ETF_WINDOWS["judged"]}},
               "cells": ind["cells"], "ind49": ind["ind49"], "compare_2008": ind["compare_2008"],
               "yearly": ind["yearly"], "recent_picks": ind.get("recent_picks"), "data_end": ind["data_end"],
               "tax_drag_approx": {"method": f"approximation: tax_fx.simulate on industry total-return indices, {TAX_INITIAL_KRW:,} KRW, "
                                             f"fixed 1 USD = {TAX_FX_CONST:,.0f} KRW, 22% on realized gains above 2.5M KRW/yr, "
                                             "no loss carry-forward, fee 10bp, no FX cost/dividend tax, liquidation at end",
                                   "cells": res["tax_drag"]},
               "etf": res["etf"]})


# =================================================================================================
# 보고서
# =================================================================================================

def _p(x, signed=False, nd=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _yn(v):
    return "—" if v is None else ("통과" if v else "미달")


NAMES = {"M6": "6개월 모멘텀", "RS12": "12개월 상대강도", "C": "합성(M6·RS12 평균 순위)"}


def render(r: dict) -> str:
    v = r["verdicts"]
    smoke = r["smoke"]
    L = [f"# 섹터 집중 투자 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
         "산업 주도 신호(leader-catch-v1 에서 견고했던 6개월 모멘텀·12개월 상대강도)로 **상위 1~2개 산업에 주식 100% 집중**"
         "(현금·시장 필터 없음, 월 1회, 편도 10bp)하면, 아무 연구도 보지 않은 **1927-07 ~ 2007-12** 에서 시장을 이기면서 "
         "어느 정도 안정성도 지키는지 본다. 자료: Ken French 일별 12 산업(시가총액 가중, 상장폐지 포함이라 생존편향 없음).", "",
         f"**종합: {v['overall']}** · ETF 보조 시험 SUPPORTING {v['etf_supporting']}", "",
         rp.power_line(r["power"]), "",
         "## 판정 규칙 (결과를 보기 전에 고정)", "",
         f"칸(신호 3 × 상위 k 2 = 6칸, 시도 수 6)마다 다음을 **모두** 만족하면 PASS_FORWARD_CANDIDATE(전진 원장 후보):",
         f"(a) 연수익 ≥ 시장 + {CAGR_MARGIN * 100:.1f}%p · (A) 최대 낙폭이 시장보다 나쁘지 않음 · "
         f"(B) 최악 12개월 수익 ≥ 시장 최악 − {WORST12_SLACK * 100:.0f}%p · (d) 4개 하위 구간 중 {SUB_MIN_BEAT}개 이상 시장보다 높은 연수익 · "
         f"(e) CAPM 연 알파 NW(6, 월별) t ≥ {ALPHA_T_MIN}. 탈락은 classify_fail 로 FAIL / FAIL_UNDERPOWERED 구분.", "",
         "## 판정 (12 산업, 1927-07 ~ 2007-12, 세전)", "",
         "| 칸 | 연수익 (시장) | 최대낙폭 (시장) | 최악 12개월 (시장) | 하위 구간 이김 | 알파 / t | a | A | B | d | e | 판정 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        x = r["cells"][c]
        s, m, ch, cp = x["strategy"], x["market"], x["checks"], x["capm"]
        sig, k = c.rsplit("_k", 1)
        L.append(f"| {NAMES[sig]} 상위 {k} | {_p(s['cagr'])} ({_p(m['cagr'])}) | {_p(s['mdd'])} ({_p(m['mdd'])}) | "
                 f"{_p(s['worst_12m'])} ({_p(m['worst_12m'])}) | {sum(y['beat'] for y in x['subperiods'])}/4 | "
                 f"{_p(cp['alpha_annual'], True)} / {cp['alpha_t_nw6']:.2f} | {_yn(ch['a_cagr'])} | {_yn(ch['A_mdd'])} | "
                 f"{_yn(ch['B_worst12'])} | {_yn(ch['d_subperiods'])} | {_yn(ch['e_alpha_t'])} | **{v[c]}** |")
    L += ["", "## 하위 구간 연수익 (전략 / 시장)", "", "| 칸 | " + " | ".join(f"{a[:4]}~{b[:4]}" for a, b in SUBPERIODS) + " |",
          "|---|" + "---|" * len(SUBPERIODS)]
    for c in CELLS:
        L.append(f"| {c} | " + " | ".join(f"{_p(y['cagr'])} / {_p(y['market_cagr'])}" for y in r["cells"][c]["subperiods"]) + " |")
    L += ["", "## 견딜 수 있나: 회전율·가장 긴 물속 기간·세금 근사 (보고만)", "",
          "| 칸 | 연 회전율(편도) | 가장 긴 물속 기간 | 세전 연수익(10bp, 청산) | 한국 세금 뒤(근사) | 세금 손실 |", "|---|---|---|---|---|---|"]
    td = r["tax_drag_approx"]["cells"]
    for c in CELLS + ("MKT",):
        x = r["cells"].get(c)
        uw = (x["strategy"] if x else r["cells"][CELLS[0]]["market"])["underwater"]
        tv = _p(x["strategy"]["turnover_per_year"], nd=0) if x else "0%"
        d = td.get(c) or {}
        L.append(f"| {c if x else '시장 그냥 보유'} | {tv} | {uw['years']}년 ({uw['peak']}→{uw['recovered'] or '미회복'}) | "
                 f"{_p(d.get('no_tax'))} | {_p(d.get('tax'))} | {_p(d.get('drag_pp'))}p |")
    L += ["", "세금 근사 방법(**근사일 뿐**): 산업 총수익 지수를 가격으로 놓고 `core/tax_fx.simulate` 로 3,000만 원 계좌를 굴린다. "
          "환율은 1달러 = 1,300원 고정, 실현 이익에서 연 250만 원 공제 후 22%, 손실 이월 없음, 다음 해 5월 납부, 수수료 편도 10bp, "
          "환전 비용·배당 세금 없음, 끝에 전부 판다고 보고 미납 세금을 뺀 연수익. 공제 250만 원은 1927 년에도 같은 원화 금액이라 "
          "계좌가 커질수록 의미가 없어진다 — 실제 세금 손실은 이와 다르다.", "",
          "## 보고만: 49 산업 판(같은 규칙)", "", "| 칸 | 연수익 (시장) | 최대낙폭 | 최악 12개월 | 알파 t | 관문 a/A/B/d/e | 판정이었다면 |", "|---|---|---|---|---|---|---|"]
    for c, x in r["ind49"].items():
        ch = x["checks"]
        L.append(f"| {c} | {_p(x['strategy']['cagr'])} ({_p(x['market']['cagr'])}) | {_p(x['strategy']['mdd'])} | "
                 f"{_p(x['strategy']['worst_12m'])} | {x['capm']['alpha_t_nw6']:.2f} | "
                 + "/".join(_yn(ch[kk]) for kk in ("a_cagr", "A_mdd", "B_worst12", "d_subperiods", "e_alpha_t")) + f" | {x['verdict']} |")
    L += ["", f"## 보고만: 2008 ~ {r['data_end'][:7]} (이미 여러 연구가 본 구간, 12 산업)", "",
          "| 칸 | 연수익 (시장) | 최대낙폭 (시장) | 최악 12개월 (시장) | 알파 / t |", "|---|---|---|---|---|"]
    for c, x in r["compare_2008"].items():
        s, m = x["strategy"], x["market"]
        L.append(f"| {c} | {_p(s['cagr'])} ({_p(m['cagr'])}) | {_p(s['mdd'])} ({_p(m['mdd'])}) | {_p(s['worst_12m'])} ({_p(m['worst_12m'])}) | "
                 f"{_p(x['capm']['alpha_annual'], True)} / {x['capm']['alpha_t_nw6']:.2f} |")
    e = r["etf"]
    L += ["", "## ETF 시대 보조 시험 (세후 원화, 판정은 SUPPORTING / NOT_SUPPORTING — PASS 아님)", "",
          "Select Sector SPDR 9개(XLB XLE XLF XLI XLK XLP XLU XLV XLY) + XLRE·XLC 는 상장 뒤 신호가 생기면 추가. 다른 ETF 는 넣지 않는다. "
          "시장 = SPY. 같은 신호·상위 k·월 1회. 카카오페이증권 기본값(수수료 0.1%, 환전 우대 95%, 3,000만 원, 양도세 22%·공제 250만 원), "
          f"끝에 청산한 세후 연수익. SUPPORTING = 세후 ≥ SPY + {ETF_SPY_MARGIN * 100:.1f}%p 그리고 (A)·(B)가 SPY 대비 성립. 판정 구간 2000-01 ~ 2024-09.", ""]
    if e.get("missing"):
        L += [f"받지 못한 가격: {', '.join(e['missing'])}", ""]
    L += ["| 칸 | 세후 연수익 (청산) | 세전 | 최대낙폭 | 최악 12개월 | 낸 양도세 | 2024-10~ 세후(보고만) | 판정 |", "|---|---|---|---|---|---|---|---|"]
    for c in CELLS + ("SPY",):
        j, po = e["sims"][f"{c}|judged"], e["sims"].get(f"{c}|post") or {}
        L.append(f"| {c} | {_p(j['cagr_after_liq'])} | {_p(j['cagr_pre'])} | {_p(j['mdd'])} | {_p(j['worst_12m'])} | "
                 f"{j['tax_paid_krw'] / 10000:,.0f}만 원 | {_p(po.get('cagr_after_liq'))} | {e['verdicts'].get(c, '기준')} |")
    L += ["", "## 연도별 (세전, 12 산업)", "", "| 연도 | 시장 | " + " | ".join(CELLS) + " |", "|---|---|" + "---|" * len(CELLS)]
    years = sorted(r["yearly"].get("MKT", {}), key=int)
    for y in years:
        tag = " (비교)" if int(y) >= 2008 else ""
        L.append(f"| {y}{tag} | {_p(r['yearly']['MKT'][y])} | " + " | ".join(_p(r["yearly"][c].get(y)) for c in CELLS) + " |")
    L += ["", "## 주의", "",
          "- 산업 포트폴리오는 장기적으로 그대로 살 수 있는 상품이 아니다(1927~1998 에는 섹터 ETF 가 없었고, 실제 체결·비용·세금은 더 크다).",
          "- ETF 메뉴(미국 섹터 SPDR)는 미국 시장이 지난 25년간 강했다는 사후 지식이 일부 섞인 선택이다.",
          "- 상위 1~2개 산업 집중은 한 산업의 붕괴(1930년대 공공요금, 2000년 기술, 2008년 금융 같은)에 그대로 노출된다.",
          "- PASS 는 '전진 원장에 올릴 후보'일 뿐 채택이 아니다. 엔진(챔피언 전략)은 바뀌지 않았다 — 반영은 사용자 확인 뒤 별도 작업.",
          "- 2024-10 이후 구간은 이미 많은 연구가 본 구간이라 보고만 한다.",
          "- 평일 달력: 1952년 이전 토요일 수익은 다음 평일에 복리로 합쳤다(core-longrun-v1 과 같음)."]
    if r.get("smoke"):
        L += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
