"""검증 연구 mom-volscale-v1 (2026-10-16 사전 등록): 모멘텀 노출을 최근 변동성으로 줄이면 '수익 대 낙폭' 경계가 나아지나.

사용자 방향(2026-10-16): 수익 극대화. sector-concentrate-v1 에서 산업 집중 모멘텀은 1927~2007 연 ~15%(시장 9.9%)였지만
낙폭이 ~−80% 였고, 현 코어(상위 4 + 200일 필터)는 12.9%·−42% 였다. 문헌(Barroso & Santa-Clara 2015; Daniel & Moskowitz 2016)은
모멘텀 노출을 최근 변동성으로 나누면 모멘텀 붕괴를 피하고 위험 대비 수익이 오른다고 한다. 아무도 보지 않은 긴 자료에서
수익-낙폭 경계를 그리고, 변동성 맞춤이 그 경계를 개선하는지 본다.

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

_spec = importlib.util.spec_from_file_location("core_longrun_lab", PROJECT_ROOT / "research/jobs/core-longrun-v1/lab.py")
lab = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(_spec))
if not hasattr(lab, "Rule"):
    _spec.loader.exec_module(lab)

JOB_ID = "mom-volscale-v1"
RULES_VERSION = "mom-volscale-v1/2026-10-16"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
SELECTION = ("1927-07-01", "1966-12-31")
CONFIRMATION = ("1967-01-01", "2007-12-31")
RECENT = ("2008-01-01", None)
WINDOWS = {"selection": SELECTION, "confirmation": CONFIRMATION, "recent": RECENT}
CONF_HALVES = (("1967-01-01", "1986-12-31"), ("1987-01-01", "2007-12-31"))
CRASHES = {"1932-33": ("1932-06-01", "1933-12-31"), "2009": ("2009-03-01", "2009-12-31")}

LOOKBACK = 252                 # 산업 모멘텀(252행 총수익)
VOL_WINDOW = 126               # 실현 변동성(직전 126행, 소매 자신의 비조정 일별 수익)
TRADING_DAYS = 252
SMA_WINDOW = 200
FILTER_CUT = 0.5
EXPOSURE_CAP = 1.0             # 레버리지 없음
COST_BPS = 10.0                # 편도, 위험자산 비중 변화 전체
BH_DRAG = 0.01                 # BIG HiPRIOR 연 1.0% 비용 차감(mom-proxy-v1 과 같은 가정)

SLEEVES = ("I1", "I2", "I4", "BH")
SLEEVE_K = {"I1": 1, "I2": 2, "I4": 4}
SCALINGS = ("none", "VT12", "VT15", "VT20")
VT_TARGET = {"VT12": 0.12, "VT15": 0.15, "VT20": 0.20}
FILTERS = ("none", "F")
CELLS = tuple(f"{s}/{v}/{f}" for s in SLEEVES for v in SCALINGS for f in FILTERS)
N_TRIALS = 32
POWER_YEARS = 41

CAGR_MARGIN = 0.015
ROLL_SLACK = 0.05              # B: 최악 252행 수익 ≥ 시장 최악 − 5%p
ALPHA_T_MIN = 2.0
VOLSCALE_MIN_SLEEVES = 3
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"
HELPS, NOT_SHOWN = "VOLSCALE_HELPS", "VOLSCALE_NOT_SHOWN"

BH_DATASET = ("me_prior6_daily", "6_Portfolios_ME_Prior_12_2_Daily_CSV.zip")
BH_COLUMN = "BIG HiPRIOR"


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def parse_cell(cell: str) -> tuple[str, str, str]:
    s, v, f = cell.split("/")
    return s, v, f


# =================================================================================================
# 자료
# =================================================================================================

def load_real() -> dict[str, Any]:
    """Ken French 일별 FF3·12 산업·6 규모×과거수익 포트폴리오(BIG HiPRIOR, 시가총액 가중 첫 표)."""
    from core import french_factors as ff

    ff.DATASETS.setdefault(*BH_DATASET)   # core 모듈은 바꾸지 않고 이 실행에서만 등록
    ff3, i12, p6 = ff.load("ff3_daily"), ff.load("ind12_daily"), ff.load(BH_DATASET[0])
    if ff3 is None or i12 is None or p6 is None or BH_COLUMN not in p6:
        raise RuntimeError("Ken French 일별 FF3 / 12 산업 / 6 규모×과거수익 자료를 받지 못함")
    out = prepare(ff3["RF"], ff3["Mkt-RF"] + ff3["RF"], i12, p6[BH_COLUMN])
    out["source"] = "Ken French data library (daily, weekday calendar; 12 industries VW; 6 ME×Prior(12-2) VW BIG HiPRIOR)"
    return out


def prepare(rf: pd.Series, mkt: pd.Series, i12: pd.DataFrame, bh: pd.Series) -> dict[str, Any]:
    idx = rf.index.intersection(i12.index).sort_values()
    out = lab._normalize(rf, mkt, i12, None)
    b = lab.to_weekdays(bh.reindex(idx).astype(float).to_frame("BH"))
    out["bh"] = lab.clean_industry(b).reindex(out["rf"].index)["BH"]
    return out


def synthetic_data(seed: int = 7) -> dict[str, Any]:
    """스모크용(네트워크 없음): core-longrun 의 가짜 산업 자료 + 시장에 붙은 가짜 BIG HiPRIOR(1926-11 부터)."""
    d = lab.synthetic_data(seed=seed)
    idx = d["rf"].index
    rng = np.random.default_rng(seed + 11)
    bh = d["mkt"] * 1.1 + rng.normal(0.0001, 0.006, len(idx))
    crash = (idx >= "2009-03-01") & (idx <= "2009-05-31")
    bh[crash] = bh[crash] - 0.006            # 모멘텀 붕괴 흉내
    bh = pd.Series(np.where(idx < pd.Timestamp("1926-11-03"), np.nan, bh), index=idx)
    return {"rf": d["rf"], "mkt": d["mkt"], "ind12": d["ind12"], "bh": bh, "source": "synthetic (smoke)"}


def sleeve_panel(data: dict, sleeve: str) -> pd.DataFrame:
    if sleeve == "BH":
        return (data["bh"] - BH_DRAG / TRADING_DAYS).to_frame("BH")
    return data["ind12"]


# =================================================================================================
# 신호·노출 (결정일 d 의 값은 행 d−1 까지의 자료만)
# =================================================================================================

def decision_rows(index: pd.DatetimeIndex) -> np.ndarray:
    pos = np.flatnonzero(lab.month_first_mask(index))
    return pos[pos >= 1]


def select_top(mom_row: np.ndarray, k: int) -> Optional[list[int]]:
    """유한한 252행 수익 상위 k(동점은 열 순서). 유한한 구성원이 k 미만이면 None(→ RF)."""
    fin = np.isfinite(mom_row)
    if fin.sum() < k:
        return None
    order = np.argsort(-np.where(fin, mom_row, -np.inf), kind="stable")[:k]
    return [int(j) for j in order]


def pick_schedule(panel: pd.DataFrame, sleeve: str) -> dict[int, Optional[list[int]]]:
    """{결정 행 d: 선택 열 또는 None}. 산업: 행 d−1 까지의 252행 총수익 상위 k. BH: 행 d−1 수익이 있으면 [0]."""
    rows = decision_rows(panel.index)
    if sleeve == "BH":
        v = panel["BH"].to_numpy()
        return {int(d): ([0] if np.isfinite(v[d - 1]) else None) for d in rows}
    mom = np.expm1(np.log1p(panel).rolling(LOOKBACK, min_periods=LOOKBACK).sum()).to_numpy()
    return {int(d): select_top(mom[d - 1], SLEEVE_K[sleeve]) for d in rows}


def realized_vol(raw: np.ndarray, d: int, window: int = VOL_WINDOW) -> float:
    """행 d−window .. d−1 (결정일 앞 window 행)의 연율 표준편차. 유한한 값이 window 개가 안 되면 NaN."""
    if d < window:
        return float("nan")
    w = raw[d - window: d]
    if not np.isfinite(w).all():
        return float("nan")
    return float(np.std(w, ddof=1) * math.sqrt(TRADING_DAYS))


def vt_exposure(vol: float, target: Optional[float]) -> float:
    """none(target None) → 1.0. VT → min(target / vol, 1.0). vol 이 없으면(이력 126행 미만) 1.0, vol 0 이면 1.0."""
    if target is None or not math.isfinite(vol) or vol <= 0:
        return 1.0
    return float(min(target / vol, EXPOSURE_CAP))


def market_below_sma(mkt: pd.Series, index: pd.DatetimeIndex) -> np.ndarray:
    """행 i: 시장 지수(누적)가 행 i 의 200행 SMA 아래인가(SMA 가 없으면 False). 결정일 d 에는 행 d−1 값을 쓴다."""
    level = (1 + mkt.reindex(index).fillna(0.0)).cumprod()
    sma = level.rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean()
    return (level < sma).to_numpy() & sma.notna().to_numpy()


def exposure_schedule(raw: np.ndarray, below: np.ndarray, schedule: dict, scaling: str, filt: str) -> dict[int, float]:
    target = VT_TARGET.get(scaling)
    out = {}
    for d, picks in schedule.items():
        if picks is None:
            out[d] = 0.0
            continue
        e = vt_exposure(realized_vol(raw, d), target)
        if filt == "F" and below[d - 1]:
            e *= FILTER_CUT
        out[d] = e
    return out


# =================================================================================================
# 포트폴리오: 결정일 d 종가에 체결(수익은 d+1 부터), 다음 결정일까지 가격대로 표류, 남는 몫은 RF
# =================================================================================================

def simulate(panel: pd.DataFrame, rf: pd.Series, schedule: dict, exposure: dict, k: int, bps: float = COST_BPS) -> dict[str, Any]:
    """비용 = Σ|목표 − 표류 위험자산 비중| × 편도 bp (RF 쪽은 세지 않는다). 반환: 일별 수익·회전율(Σ|Δw|)·위험 비중."""
    R = panel.fillna(0.0).to_numpy()
    F = rf.reindex(panel.index).fillna(0.0).to_numpy()
    n, m = R.shape
    h, c = np.zeros(m), 1.0
    out, turn, risky = np.zeros(n), np.zeros(n), np.zeros(n)
    for i in range(n):
        if i > 0:
            g = h * (1 + R[i])
            gc = c * (1 + F[i])
            tot = g.sum() + gc
            out[i] = tot - 1.0
            h, c = g / tot, gc / tot
        if i in schedule:
            picks = schedule[i]
            tgt = np.zeros(m)
            e = exposure.get(i, 0.0)
            if picks is not None and e > 0:
                tgt[picks] = e / k
            tv = float(np.abs(tgt - h).sum())
            if i > 0:
                out[i] = (1 + out[i]) * (1 - tv * bps / 10000.0) - 1
            turn[i] = tv
            h, c = tgt, 1.0 - tgt.sum()
        risky[i] = h.sum()
    idx = panel.index
    return {"returns": pd.Series(out, index=idx), "turnover": pd.Series(turn, index=idx), "risky": pd.Series(risky, index=idx)}


def raw_sleeve(panel: pd.DataFrame, rf: pd.Series, schedule: dict, k: int) -> np.ndarray:
    """소매 자신의 비조정(노출 1.0, 필터·비용 없음) 일별 수익. 아직 보유가 없는 행(선택 전)은 NaN."""
    exp = {d: 1.0 for d in schedule}
    sim = simulate(panel, rf, schedule, exp, k, bps=0.0)
    r = sim["returns"].to_numpy().copy()
    first = next((d for d in sorted(schedule) if schedule[d] is not None), None)
    if first is None:
        return np.full(len(r), np.nan)
    r[: first + 1] = np.nan
    return r


# =================================================================================================
# 지표
# =================================================================================================

def window(s: pd.Series, a: str, b: Optional[str]) -> pd.Series:
    return s.loc[pd.Timestamp(a): (pd.Timestamp(b) if b else None)]


def max_drawdown(r: pd.Series) -> float:
    """시작 값 1 을 첫 고점으로 포함한 최대 낙폭(음수)."""
    v = np.r_[1.0, (1 + r).cumprod().to_numpy(dtype=float)]
    return float((v / np.maximum.accumulate(v) - 1).min())


def worst_rolling(r: pd.Series, rows: int = TRADING_DAYS) -> Optional[float]:
    """연속 rows 행 수익의 최솟값(시작 값 1 포함). 행이 모자라면 None."""
    v = np.r_[1.0, (1 + r).cumprod().to_numpy(dtype=float)]
    if len(v) <= rows:
        return None
    return float((v[rows:] / v[:-rows] - 1).min())


def cagr_of(r: pd.Series) -> float:
    return lab.cagr(r) if len(r) > 1 else float("nan")


def calmar(cagr: float, mdd: float) -> float:
    if not (math.isfinite(cagr) and math.isfinite(mdd)):
        return float("nan")
    return float(cagr / abs(mdd)) if mdd < 0 else float("inf")


def stats(sim: dict, mkt: pd.Series, rf: pd.Series, a: str, b: Optional[str], with_capm: bool = True) -> dict[str, Any]:
    s = window(sim["returns"], a, b)
    st = {"cagr": cagr_of(s), "mdd": max_drawdown(s), "worst_252": worst_rolling(s),
          "sharpe": lab.sharpe_monthly(s, rf)}
    st["calmar"] = calmar(st["cagr"], st["mdd"])
    if "risky" in sim:
        y = lab.years_of(s)
        st["avg_exposure"] = float(window(sim["risky"], a, b).mean())
        st["turnover_per_year"] = float(window(sim["turnover"], a, b).sum() / y) if y > 0 else float("nan")
    if with_capm:
        cp = lab.capm(s, mkt, rf)
        st["alpha_annual"], st["alpha_t_nw6"], st["appraisal_ir"], st["beta_daily"] = (
            cp["alpha_annual"], cp["alpha_t_nw6"], cp["appraisal_ir"], cp["beta_daily"])
    return st


def market_stats(mkt: pd.Series, rf: pd.Series, a: str, b: Optional[str]) -> dict[str, Any]:
    st = stats({"returns": mkt}, mkt, rf, a, b, with_capm=False)
    st["avg_exposure"], st["turnover_per_year"] = 1.0, 0.0
    return st


def _ok(x) -> bool:
    return isinstance(x, (int, float)) and x is not None and math.isfinite(x)


def stability(st: dict, mk: dict) -> dict[str, Optional[bool]]:
    """A: MDD ≥ 시장 MDD. B: 최악 252행 ≥ 시장 최악 − 5%p."""
    return {"A_mdd": (st["mdd"] >= mk["mdd"]) if _ok(st["mdd"]) and _ok(mk["mdd"]) else None,
            "B_worst252": (st["worst_252"] >= mk["worst_252"] - ROLL_SLACK)
            if _ok(st.get("worst_252")) and _ok(mk.get("worst_252")) else None}


def tie_key(cell: str) -> tuple:
    """동점 정리: 덜 복잡한 쪽 먼저 — 조정 없음 → VT(12, 15, 20 순), 필터 없음 → F, 그다음 소매 순서."""
    s, v, f = parse_cell(cell)
    return (v != "none", f != "none", SCALINGS.index(v), FILTERS.index(f), SLEEVES.index(s))


def select_cell(sel_stats: dict[str, dict], sel_market: dict, cells=CELLS) -> Optional[str]:
    """SELECTION 에서 A·B 를 만족하는 칸 중 CAGR 최고. 없으면 None."""
    elig = [c for c in cells if all(v is True for v in stability(sel_stats[c], sel_market).values())
            and _ok(sel_stats[c]["cagr"])]
    if not elig:
        return None
    best = max(sel_stats[c]["cagr"] for c in elig)
    return sorted([c for c in elig if sel_stats[c]["cagr"] == best], key=tie_key)[0]


def confirmation_checks(conf: dict, conf_mkt: dict, halves: list[dict]) -> dict[str, Optional[bool]]:
    ch = {"cagr_margin": (conf["cagr"] >= conf_mkt["cagr"] + CAGR_MARGIN) if _ok(conf["cagr"]) and _ok(conf_mkt["cagr"]) else None}
    ch.update(stability(conf, conf_mkt))
    ch["both_halves"] = all(h["cagr"] > h["market_cagr"] for h in halves) if halves and all(
        _ok(h["cagr"]) and _ok(h["market_cagr"]) for h in halves) else None
    ch["alpha_t"] = (conf["alpha_t_nw6"] >= ALPHA_T_MIN) if _ok(conf.get("alpha_t_nw6")) else None
    return ch


def primary_verdict(chosen: Optional[str], checks: Optional[dict], noop: Optional[str], observed_ir, power: dict) -> str:
    if chosen is None:
        return FAIL
    if noop:
        return NOT_EVALUABLE
    if checks and all(v is True for v in checks.values()):
        return PASS
    return rp.classify_fail(observed_ir, power)


def sleeve_best_filter(sleeve: str, sel_stats: dict, sel_market: dict) -> str:
    """소매의 최선 칸(같은 선택 규칙을 소매 안에서; A·B 통과 칸이 없으면 CAGR 최고)의 필터 설정."""
    cells = [c for c in CELLS if parse_cell(c)[0] == sleeve]
    c = select_cell(sel_stats, sel_market, cells)
    if c is None:
        c = sorted(cells, key=lambda x: (-(sel_stats[x]["cagr"] if _ok(sel_stats[x]["cagr"]) else -1e9), tie_key(x)))[0]
    return parse_cell(c)[2]


def volscale_check(sel_stats: dict, conf_stats: dict, sel_market: dict) -> dict[str, Any]:
    """소매마다: 최선 칸의 필터 f 고정, 그 f 의 VT 3칸 중 SELECTION CAGR/|MDD| 최고(동점 VT12→VT20)를 고르고,
    CONFIRMATION CAGR/|MDD| 가 같은 소매·f·조정 없음보다 **높으면** 개선. 4개 중 3개 이상 → VOLSCALE_HELPS."""
    rows = {}
    for s in SLEEVES:
        f = sleeve_best_filter(s, sel_stats, sel_market)
        vts = [f"{s}/{v}/{f}" for v in SCALINGS if v != "none"]
        best = sorted(vts, key=lambda c: (-(sel_stats[c]["calmar"] if _ok(sel_stats[c]["calmar"]) else -1e9), tie_key(c)))[0]
        base = f"{s}/none/{f}"
        cv, cb = conf_stats[best]["calmar"], conf_stats[base]["calmar"]
        rows[s] = {"filter": f, "vt_cell": best, "base_cell": base, "conf_calmar_vt": cv, "conf_calmar_base": cb,
                   "improves": bool(_ok(cv) and _ok(cb) and cv > cb)}
    n = sum(r["improves"] for r in rows.values())
    return {"verdict": HELPS if n >= VOLSCALE_MIN_SLEEVES else NOT_SHOWN, "n_improved": n, "sleeves": rows}


def frontier(stats_by_cell: dict[str, dict]) -> list[str]:
    """CAGR 와 MDD 둘 다에서 지배되지 않는 칸(다른 칸이 둘 다 같거나 낫고 하나는 엄격히 나으면 지배됨)."""
    ok = {c: s for c, s in stats_by_cell.items() if _ok(s["cagr"]) and _ok(s["mdd"])}
    out = []
    for c, s in ok.items():
        dom = any(o["cagr"] >= s["cagr"] and o["mdd"] >= s["mdd"] and (o["cagr"] > s["cagr"] or o["mdd"] > s["mdd"])
                  for c2, o in ok.items() if c2 != c)
        if not dom:
            out.append(c)
    return sorted(out, key=lambda c: -ok[c]["cagr"])


def crash_rows(sim_ret: pd.Series, mkt: pd.Series) -> dict[str, Any]:
    out = {}
    for name, (a, b) in CRASHES.items():
        s, m = window(sim_ret, a, b), window(mkt, a, b)
        if len(s) < 2:
            out[name] = None
            continue
        out[name] = {"ret": float((1 + s).prod() - 1), "mdd": max_drawdown(s), "market_ret": float((1 + m).prod() - 1),
                     "market_mdd": max_drawdown(m)}
    return out


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

ALL_WINDOWS = dict(WINDOWS, **{f"conf_{a[:4]}_{b[:4]}": (a, b) for a, b in CONF_HALVES})


def sleeve_stage(data: dict, sleeve: str) -> dict[str, Any]:
    """한 소매의 8칸: 창별 지표·붕괴 구간·noop(시장 대비, VT 는 같은 필터의 조정 없음 대비)."""
    rf, mkt = data["rf"], data["mkt"]
    panel = sleeve_panel(data, sleeve)
    k = SLEEVE_K.get(sleeve, 1)
    sched = pick_schedule(panel, sleeve)
    raw = raw_sleeve(panel, rf, sched, k)
    below = market_below_sma(mkt, panel.index)
    sims, out = {}, {}
    for v in SCALINGS:
        for f in FILTERS:
            cell = f"{sleeve}/{v}/{f}"
            exp = exposure_schedule(raw, below, sched, v, f)
            sim = simulate(panel, rf, sched, exp, k)
            sims[cell] = sim["returns"]
            out[cell] = {"windows": {w: stats(sim, mkt, rf, a, b) for w, (a, b) in ALL_WINDOWS.items()},
                         "crashes": crash_rows(sim["returns"], mkt),
                         "noop_vs_market": rp.noop_guard((window(sim["returns"], *CONFIRMATION)
                                                          - window(mkt, *CONFIRMATION)).tolist())}
    for v in SCALINGS[1:]:
        for f in FILTERS:
            c, base = f"{sleeve}/{v}/{f}", f"{sleeve}/none/{f}"
            out[c]["noop_vs_unscaled"] = rp.noop_guard((window(sims[c], *CONFIRMATION) - window(sims[base], *CONFIRMATION)).tolist())
    yearly = {c: {str(y): round(float(x), 4) for y, x in
                  ((1 + window(r, SELECTION[0], None)).groupby(window(r, SELECTION[0], None).index.year).prod() - 1).items()}
              for c, r in sims.items()}
    return {"cells": out, "yearly": yearly,
            "recent_picks": [{"date": str(panel.index[d].date()),
                              "picks": None if sched[d] is None else [panel.columns[j] for j in sched[d]]}
                             for d in sorted(sched)[-3:]]}


def reference_stage(data: dict) -> dict[str, Any]:
    """보고만: 시장, 그리고 core-longrun-v1 의 현 코어 복제(252행 모멘텀 > 0 상위 4, 200일 필터 ×0.5, 상수 비중)."""
    rf, mkt = data["rf"], data["mkt"]
    w = lab.target_weights(data["ind12"], mkt, lab.Rule())
    core = lab.strategy_returns(data["ind12"], rf, w)
    ex = w.shift(1).fillna(0.0)
    tv = ex.diff().abs().sum(axis=1)
    sim = {"returns": core, "turnover": tv, "risky": ex.sum(axis=1)}
    m_years = {str(y): round(float(x), 4) for y, x in
               ((1 + window(mkt, SELECTION[0], None)).groupby(window(mkt, SELECTION[0], None).index.year).prod() - 1).items()}
    return {"market": {w_: market_stats(mkt, rf, a, b) for w_, (a, b) in ALL_WINDOWS.items()},
            "market_crashes": crash_rows(mkt, mkt),
            "core": {"windows": {w_: stats(sim, mkt, rf, a, b) for w_, (a, b) in ALL_WINDOWS.items()},
                     "crashes": crash_rows(core, mkt)},
            "market_yearly": m_years, "data_end": str(data["rf"].index[-1].date())}


def judge(cells: dict, ref: dict, power: dict) -> dict[str, Any]:
    sel = {c: cells[c]["windows"]["selection"] for c in CELLS}
    conf = {c: cells[c]["windows"]["confirmation"] for c in CELLS}
    sm, cm = ref["market"]["selection"], ref["market"]["confirmation"]
    chosen = select_cell(sel, sm)
    checks, halves, noop, ir = None, [], None, None
    if chosen is not None:
        for a, b in CONF_HALVES:
            key = f"conf_{a[:4]}_{b[:4]}"
            halves.append({"start": a, "end": b, "cagr": cells[chosen]["windows"][key]["cagr"],
                           "market_cagr": ref["market"][key]["cagr"]})
        checks = confirmation_checks(conf[chosen], cm, halves)
        noop = cells[chosen]["noop_vs_market"]
        ir = conf[chosen].get("appraisal_ir")
    primary = primary_verdict(chosen, checks, noop, ir, power)
    vs = volscale_check(sel, conf, sm)
    eligible = [c for c in CELLS if all(v is True for v in stability(sel[c], sm).values())]
    return {"chosen": chosen, "eligible_on_selection": eligible, "confirmation_checks": checks, "halves": halves,
            "noop": noop, "observed_ir": ir, "primary": primary, "volscale": vs,
            "frontiers": {w: frontier({c: cells[c]["windows"][w] for c in CELLS}) for w in WINDOWS}}


def smoke_coverage(cells: dict, ref: dict, j: dict) -> dict[str, bool]:
    sel = [cells[c]["windows"]["selection"] for c in CELLS]
    return {
        "all_cells": len(cells) == N_TRIALS,
        "exposure_capped": all(s["avg_exposure"] <= EXPOSURE_CAP + 1e-9 for s in sel),
        "vt_scales_down": any(cells[c]["windows"]["selection"]["avg_exposure"] < 0.99 for c in CELLS if "/VT" in c),
        "filter_bites": any(cells[f"{s}/none/F"]["windows"]["selection"]["avg_exposure"]
                            < cells[f"{s}/none/none"]["windows"]["selection"]["avg_exposure"] - 1e-6 for s in SLEEVES),
        "crashes": all(cells[c]["crashes"]["2009"] is not None for c in CELLS),
        "core_reference": _ok(ref["core"]["windows"]["confirmation"]["cagr"]),
        "volscale_logic": j["volscale"]["verdict"] in (HELPS, NOT_SHOWN),
        "frontier": all(len(v) >= 1 for v in j["frontiers"].values()),
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
        data = stage("french", lambda: synthetic_data() if a.smoke else load_real())
        ref = stage("reference", lambda: reference_stage(data))
        sl = {s: stage(f"sleeve_{s}", lambda s=s: sleeve_stage(data, s)) for s in SLEEVES}
        cells = {c: v for s in SLEEVES for c, v in sl[s]["cells"].items()}
        j = judge(cells, ref, power)
        result = build_result(cells, sl, ref, j, power, a.smoke, data["source"])
        if a.smoke:
            cov = smoke_coverage(cells, ref, j)
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
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    return x


def build_result(cells, sl, ref, j, power, smoke: bool, source: str) -> dict:
    prim, vs = j["primary"], j["volscale"]["verdict"]
    if smoke:
        prim, vs = f"SMOKE_ONLY({prim})", f"SMOKE_ONLY({vs})"
    verdicts = {"primary": prim, "chosen_cell": j["chosen"] or "NO_ELIGIBLE_CELL", "volscale": vs,
                "volscale_sleeves_improved": f"{j['volscale']['n_improved']}/{len(SLEEVES)}"}
    if j["chosen"] and j["confirmation_checks"]:
        verdicts["confirmation_checks"] = ", ".join(f"{k}={'Y' if v else ('N' if v is False else '-')}"
                                                    for k, v in j["confirmation_checks"].items())
    chosen_yearly = sl[parse_cell(j["chosen"])[0]]["yearly"][j["chosen"]] if j["chosen"] else None
    return _r({"judge_version": RULES_VERSION, "smoke": smoke, "source": source,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "verdicts": verdicts, "power": power,
               "rule": {"sleeves": {"I1/I2/I4": "FF12 industries VW, top k by 252-row total return at row d-1, equal weight, monthly, drift between",
                                    "BH": f"French 6 ME×Prior(12-2) daily VW '{BH_COLUMN}', minus {BH_DRAG:.1%}/yr drag"},
                        "scaling": {"none": 1.0, **{k: f"min({v}/vol126, {EXPOSURE_CAP})" for k, v in VT_TARGET.items()},
                                    "vol": f"annualized std of the sleeve's own unscaled daily returns, rows d-{VOL_WINDOW}..d-1; "
                                           "if fewer than 126 rows of sleeve history: exposure 1.0"},
                        "filter": f"F: market level < {SMA_WINDOW}-row SMA at row d-1 → exposure × {FILTER_CUT}",
                        "rest": "RF", "cost_bps_one_way": COST_BPS, "turnover": "sum |Δ risky weights| (RF leg not counted)",
                        "windows": {**WINDOWS, "confirmation_halves": CONF_HALVES, "crashes": CRASHES}, "n_trials": N_TRIALS},
               "thresholds": {"cagr_margin": CAGR_MARGIN, "A": "mdd >= market mdd", "B_slack_252row": ROLL_SLACK,
                              "alpha_t_min": ALPHA_T_MIN, "volscale_min_sleeves": VOLSCALE_MIN_SLEEVES},
               "selection": {k: j[k] for k in ("chosen", "eligible_on_selection", "confirmation_checks", "halves", "noop", "observed_ir")},
               "volscale": j["volscale"], "frontiers": j["frontiers"],
               "cells": cells, "reference": {k: ref[k] for k in ("market", "market_crashes", "core")},
               "yearly": {"market": ref["market_yearly"], "chosen": chosen_yearly},
               "recent_picks": {s: sl[s]["recent_picks"] for s in SLEEVES if s != "BH"}, "data_end": ref["data_end"]})


# =================================================================================================
# 보고서
# =================================================================================================

def _p(x, signed=False, nd=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _f(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{nd}f}"


def _yn(v):
    return "—" if v is None else ("통과" if v else "미달")


SLEEVE_NAMES = {"I1": "산업 상위 1", "I2": "산업 상위 2", "I4": "산업 상위 4", "BH": "대형 고모멘텀(BH)"}
WINDOW_NAMES = {"selection": "선택 구간 1927-07 ~ 1966", "confirmation": "확인 구간 1967 ~ 2007", "recent": "2008 ~ (보고만)"}


def _row(name: str, s: dict) -> str:
    return (f"| {name} | {_p(s['cagr'])} | {_p(s['mdd'])} | {_p(s.get('worst_252'))} | {_f(s.get('sharpe'))} | "
            f"{_f(s.get('calmar'))} | {_p(s.get('avg_exposure'), nd=0)} | {_p(s.get('turnover_per_year'), nd=0)} |")


def render(r: dict) -> str:
    v, sel = r["verdicts"], r["selection"]
    smoke = r["smoke"]
    L = [f"# 모멘텀 변동성 맞춤 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
         "산업 집중 모멘텀은 수익이 컸지만 낙폭이 −80% 안팎이었다. 모멘텀 노출을 **최근 6개월 변동성으로 줄이면**(목표 변동성 12·15·20%, "
         "레버리지 없음, 나머지는 단기 국채 RF) 수익-낙폭 경계가 나아지는지, 아무 연구도 보지 않은 1927~2007 자료로 본다. "
         "자료: Ken French 일별 12 산업과 대형 고모멘텀 포트폴리오(상장폐지 포함이라 생존편향 없음). 세전.", "",
         f"**주 판정: {v['primary']}** (선택된 칸 `{v['chosen_cell']}`) · **변동성 맞춤: {v['volscale']}** (개선 소매 {v['volscale_sleeves_improved']})", "",
         rp.power_line(r["power"]), "",
         "## 판정 규칙 (결과를 보기 전에 고정)", "",
         "- 칸 = 소매 4(산업 상위 1·2·4, BH) × 조정 4(없음, VT12, VT15, VT20) × 필터 2(없음, F) = 32칸(시도 32). 편도 10bp.",
         f"- **선택(1927-07 ~ 1966)**: A(최대 낙폭이 시장보다 나쁘지 않음)·B(최악 252거래일 수익 ≥ 시장 최악 − {ROLL_SLACK * 100:.0f}%p)를 "
         "만족하는 칸 중 연수익(CAGR) 최고. 동점이면 덜 복잡한 쪽(조정 없음 → VT, 필터 없음 → F).",
         f"- **확인(1967 ~ 2007)**: 선택된 칸이 연수익 ≥ 시장 + {CAGR_MARGIN * 100:.1f}%p, A, B, 1967~86·1987~2007 둘 다 시장보다 높은 연수익, "
         f"CAPM 알파 NW(6) t ≥ {ALPHA_T_MIN} 를 모두 만족하면 PASS_FORWARD_CANDIDATE. 아니면 classify_fail(FAIL / FAIL_UNDERPOWERED).",
         f"- **VOLSCALE_HELPS**: 소매마다 최선 칸의 필터 설정을 고정하고 그 VT 3칸 중 선택 구간 연수익/|최대낙폭| 최고를 고른 뒤, "
         f"확인 구간에서 같은 소매·필터의 조정 없음보다 연수익/|최대낙폭| 이 높으면 개선. 4개 중 {VOLSCALE_MIN_SLEEVES}개 이상이면 HELPS.", ""]
    L += ["## 선택과 확인", ""]
    if sel["chosen"]:
        cs = r["cells"][sel["chosen"]]["windows"]
        mk = r["reference"]["market"]
        ch = sel["confirmation_checks"] or {}
        L += [f"선택 구간에서 A·B 를 만족한 칸 {len(sel['eligible_on_selection'])}개 중 `{sel['chosen']}` 가 골라졌다.", "",
              "| 관문 (확인 구간) | 값 | 기준 | 결과 |", "|---|---|---|---|",
              f"| 연수익 | {_p(cs['confirmation']['cagr'])} | 시장 {_p(mk['confirmation']['cagr'])} + 1.5%p | {_yn(ch.get('cagr_margin'))} |",
              f"| A 최대 낙폭 | {_p(cs['confirmation']['mdd'])} | 시장 {_p(mk['confirmation']['mdd'])} | {_yn(ch.get('A_mdd'))} |",
              f"| B 최악 252일 | {_p(cs['confirmation']['worst_252'])} | 시장 {_p(mk['confirmation']['worst_252'])} − 5%p | {_yn(ch.get('B_worst252'))} |",
              "| 두 하위 구간 | " + " · ".join(f"{h['start'][:4]}~{h['end'][:4]} {_p(h['cagr'])}/{_p(h['market_cagr'])}" for h in sel["halves"])
              + f" | 둘 다 시장보다 높음 | {_yn(ch.get('both_halves'))} |",
              f"| CAPM 알파 t | {_f(cs['confirmation'].get('alpha_t_nw6'))} (알파 {_p(cs['confirmation'].get('alpha_annual'), True)}) | ≥ {ALPHA_T_MIN} | {_yn(ch.get('alpha_t'))} |", ""]
        if sel.get("noop"):
            L += [f"무효 실행 가드: {sel['noop']}", ""]
    else:
        L += ["선택 구간에서 A·B 를 모두 만족한 칸이 없다 → 주 판정 FAIL(선택할 칸 없음).", ""]
    vs = r["volscale"]
    L += ["## 변동성 맞춤이 도움이 되었나 (확인 구간 연수익/|최대낙폭|)", "",
          "| 소매 | 필터 | 고른 VT 칸 | VT | 조정 없음 | 개선 |", "|---|---|---|---|---|---|"]
    for s, x in vs["sleeves"].items():
        L.append(f"| {SLEEVE_NAMES[s]} | {x['filter']} | `{x['vt_cell']}` | {_f(x['conf_calmar_vt'])} | {_f(x['conf_calmar_base'])} | "
                 f"{'예' if x['improves'] else '아니오'} |")
    for w, (a, b) in WINDOWS.items():
        L += ["", f"## 경계표 — {WINDOW_NAMES[w]}", "",
              f"효율 경계(연수익·최대낙폭 둘 다에서 다른 칸에 지배되지 않음): {', '.join(f'`{c}`' for c in r['frontiers'][w]) or '—'}", "",
              "| 칸 | 연수익 | 최대낙폭 | 최악 252일 | 샤프 | 연수익÷낙폭 | 평균 노출 | 연 회전율 |", "|---|---|---|---|---|---|---|---|",
              _row("시장", r["reference"]["market"][w]), _row("참고: 현 코어 복제(보고만)", r["reference"]["core"]["windows"][w])]
        for c in r["cells"]:
            mark = " ★" if c in r["frontiers"][w] else ""
            L.append(_row(f"`{c}`{mark}", r["cells"][c]["windows"][w]))
    L += ["", "## 모멘텀 붕괴 구간 (구간 수익 / 구간 안 최대낙폭)", "",
          "| 칸 | " + " | ".join(f"{n} ({a}~{b})" for n, (a, b) in CRASHES.items()) + " |", "|---|" + "---|" * len(CRASHES)]

    def cr(x):
        return "—" if not x else f"{_p(x['ret'], True)} / {_p(x['mdd'])}"
    L.append("| 시장 | " + " | ".join(cr(r["reference"]["market_crashes"].get(n)) for n in CRASHES) + " |")
    L.append("| 현 코어 복제 | " + " | ".join(cr(r["reference"]["core"]["crashes"].get(n)) for n in CRASHES) + " |")
    for c, x in r["cells"].items():
        L.append(f"| `{c}` | " + " | ".join(cr(x["crashes"].get(n)) for n in CRASHES) + " |")
    noop_cells = [c for c, x in r["cells"].items() if x.get("noop_vs_unscaled")]
    if noop_cells:
        L += ["", f"조정 없음과 확인 구간에서 매일 같은 VT 칸(변동성이 늘 목표 아래 — 사실상 조정이 걸리지 않음): {', '.join(noop_cells)}"]
    L += ["", "## 주의", "",
          "- 세전 수익이다. 한국 양도세·환전 비용은 반영하지 않았다.",
          "- 산업 포트폴리오와 French 대형 고모멘텀 포트폴리오는 그대로 살 수 있는 상품이 아니다(BH 는 연 1.0% 비용 차감으로 근사).",
          "- PASS 는 '전진 원장에 올릴 후보'일 뿐 채택이 아니다. 엔진(챔피언 전략)은 바뀌지 않았다 — 반영은 사용자 확인 뒤 별도 작업.",
          "- 2008 이후 구간은 이미 여러 연구가 본 구간이라 보고만 한다.",
          "- 산업 소매는 1927-07 첫 선택 뒤 126거래일 이력이 쌓일 때까지(약 1927 하반기) 변동성 조정 없이(노출 1.0) 돈다.",
          "- '현 코어 복제'는 core-longrun-v1 규칙(모멘텀 > 0 조건 포함, 상수 비중)이라 I4/none/F 와 조금 다르다. 비교 참고용이다.",
          "- 평일 달력: 1952년 이전 토요일 수익은 다음 평일에 복리로 합쳤다(core-longrun-v1 과 같음)."]
    if smoke:
        L += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
