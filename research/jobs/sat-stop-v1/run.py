"""검증 sat-stop-v1 (2026-10-15 사전 등록): 새틀라이트 손절 — 손절 방식 × 손절 뒤 행동.

사용자 요청(2026-10-15): sat-exit-ladder-v1 에서 모든 손절·익절 규칙이 '그냥 보유'에 졌고, 주된 이유는 손절 뒤 돈이 다음
리밸런싱까지 BIL 에 묶이고 손절한 종목이 자주 회복했기 때문이었다. 그래서 '손절을 어떻게 걸어야 하나'를 따로 본다.
새 축: 손절 방식 4종(진입가 기준 고정 %·σ 배수, 최고 종가 기준 추적 고정 %·σ 배수) × 손절 뒤 행동 3종
(A1 현금, A2 같은 종목 새 돌파 때 재진입, A3 같은 풀의 다음 순위 추세 활성 종목으로 교체).

규칙 전체는 SPEC.md(한국어)에 고정되어 있다. 판정 기준을 바꾸려면 새 id 로 다시 등록한다.
진입은 S-SEED-000 그대로다. 사건 표본·σ·w·변동성 삼분위·섹터 가족·S-SEED-000 재현·챔피언 세후 계산은
sat-exit-ladder-v1(과 그 안의 satellite-value-v1)을 그대로 가져다 쓴다. 엔진 반영은 사용자 확인 뒤 별도 작업이다.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import math
import os
import signal as _signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402


def _ladder():
    """sat-exit-ladder-v1 모듈(사건 표본·분류·챔피언 구성·판정 도구)을 그대로 쓴다."""
    name = "sat_exit_ladder_v1_for_stop"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "research/jobs/sat-exit-ladder-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


LD = _ladder()
SV = LD.SV

JOB_ID = "sat-stop-v1"
RULES_VERSION = "sat-stop-v1/2026-10-15a"
START = LD.START
SAT_WEIGHT = LD.SAT_WEIGHT
COST = LD.COST                       # 편도 8bp
BIL = LD.BIL
SEL_ENTRY, CONF_ENTRY, CONF_DAILY, POST_FROM = LD.SEL_ENTRY, LD.CONF_ENTRY, LD.CONF_DAILY, LD.POST_FROM
W_HORIZON = LD.W_HORIZON
CELLS = LD.CELLS

# 격자(사전 등록)
FIXED_PCT = (0.10, 0.15, 0.20, 0.25)
K_W = (2.0, 3.0, 4.0)
STOP_TYPES = ("T1", "T2", "T3", "T4")
WIDTHS = {"T1": FIXED_PCT, "T2": K_W, "T3": FIXED_PCT, "T4": K_W}
TRAILING = {"T1": False, "T2": False, "T3": True, "T4": True}
SIGMA_SCALED = {"T1": False, "T2": True, "T3": False, "T4": True}
ACTIONS = ("A1", "A2", "A3")
MAX_REENTRY = 2
DONCHIAN = 20
TREND_STOP = 0.15                    # S-SEED-000 추세 상태 기계의 이탈 폭
MOM_DAYS = 252
WHIPSAW_DAYS = 20
N_TRIALS = sum(len(v) for v in WIDTHS.values()) * len(ACTIONS)      # 42

# 판정
N_BOOT = 1000
BLOCK_DAYS = 126
BOOT_SEED = 20261019
CI_PCT = (5.0, 95.0)
CI_LOW_FLOOR = LD.CI_LOW_FLOOR       # −0.5%p
MDD_TOL_CHAMP = LD.MDD_TOL_CHAMP     # 2%p
PASS, FAIL, NOT_EVALUABLE = LD.PASS, LD.FAIL, LD.NOT_EVALUABLE

JUDGED = tuple(f"{t}_{a}" for t in STOP_TYPES for a in ACTIONS)
VARIANTS = ("V0",) + JUDGED
TYPE_KO = {"T1": "진입가 대비 고정 % 손절", "T2": "진입가 대비 k·w 손절", "T3": "최고 종가 대비 고정 % 추적 손절",
           "T4": "최고 종가 대비 k·w 추적 손절"}
ACTION_KO = {"A1": "손절 뒤 현금(BIL)", "A2": "새 돌파 때 같은 종목 재진입(최대 2회)", "A3": "풀의 다음 순위 종목으로 교체"}
LEVELS = ("champ", "sleeve")
WINDOWS = ("sel", "conf", "post")
SETUPS = LD.SETUPS
RESULTS_MAX_BYTES = 200_000


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


# =================================================================================================
# 지표(순수 함수, 그날 종가까지의 자료만)
# =================================================================================================

def breakout_flags(px: np.ndarray, window: int = DONCHIAN) -> np.ndarray:
    """B[t] = 종가_t > 직전 window 개 종가의 최고(t−window..t−1). 값이 모자라면 False."""
    s = pd.Series(np.asarray(px, dtype=float))
    prior = s.shift(1).rolling(window, min_periods=window).max()
    with np.errstate(invalid="ignore"):
        return (s > prior).fillna(False).to_numpy(dtype=bool)


def trend_active_series(px: np.ndarray, window: int = DONCHIAN, stop: float = TREND_STOP) -> np.ndarray:
    """S-SEED-000 의 추세 상태(돈치안 돌파로 켜짐, 켜진 뒤 최고 종가 대비 stop 하락으로 꺼짐)를 날마다 — t 까지의 자료만."""
    v = np.asarray(px, dtype=float)
    brk = breakout_flags(v, window)
    out = np.zeros(len(v), dtype=bool)
    on, peak = False, None
    for i in range(len(v)):
        c = v[i]
        if not np.isfinite(c):
            out[i] = on
            continue
        if on:
            peak = max(peak, c)
            if c <= peak * (1 - stop):
                on, peak = False, None
        elif brk[i]:
            on, peak = True, c
        out[i] = on
    return out


def momentum_series(px: np.ndarray, days: int = MOM_DAYS) -> np.ndarray:
    v = np.asarray(px, dtype=float)
    out = np.full(len(v), np.nan)
    if len(v) > days:
        with np.errstate(invalid="ignore", divide="ignore"):
            out[days:] = v[days:] / v[:-days] - 1.0
    return out


# =================================================================================================
# 손절 엔진 A1/A2 (사건 축으로 벡터화)
# =================================================================================================

@dataclass
class StopOut:
    pos: np.ndarray                        # 사건 × 일: 그날 종가 매매 뒤 주식 보유 여부
    stops: list = field(default_factory=list)      # (사건, 신호일 k, 선)
    reentries: list = field(default_factory=list)  # (사건, 신호일 k)
    blocked: np.ndarray = None             # 재진입 한도 때문에 막힌 돌파 수


def run_stops(C: np.ndarray, L: np.ndarray, BRK: np.ndarray, width, stype: str, action: str,
              max_re: int = MAX_REENTRY) -> StopOut:
    """C: 사건 × 경로일 조정 종가(0 = 진입일 종가, L−1 = 다음 리밸런싱일). 신호는 k 일 종가, 체결은 k+1 일 종가.
    체결일이 L−1(리밸런싱일) 이상이 될 신호는 내지 않는다. stype: T1/T2 진입가 기준, T3/T4 최고 종가 기준(폭은 이미 % 로 받음).
    action A1: 손절 뒤 끝까지 현금. A2: 손절 체결일 다음 날부터 새 돌파(BRK) 신호 → 다음 날 종가에 재진입, 최대 max_re 번,
    손절선은 새 진입가(최고 종가도 새로)에서 다시 시작."""
    if action not in ("A1", "A2"):
        raise ValueError(action)
    C = np.asarray(C, dtype=float)
    n, K = C.shape
    L = np.asarray(L, dtype=int)
    width = np.broadcast_to(np.asarray(width, dtype=float), (n,)).copy()
    trailing = TRAILING[stype]
    pos = np.zeros((n, K), dtype=bool)
    holding = np.ones(n, dtype=bool)
    entry = C[:, 0].copy()
    peak = C[:, 0].copy()
    pend_sell = np.zeros(n, dtype=bool)
    pend_buy = np.zeros(n, dtype=bool)
    n_re = np.zeros(n, dtype=int)
    exit_day = np.full(n, K + 10)
    blocked = np.zeros(n, dtype=int)
    out = StopOut(pos=pos, blocked=blocked)
    pos[:, 0] = True
    for k in range(1, K):
        act = k <= (L - 2)
        xs = pend_sell & act
        holding[xs] = False
        exit_day[xs] = k
        xb = pend_buy & act
        holding[xb] = True
        entry[xb] = C[xb, k]
        peak[xb] = C[xb, k]
        n_re[xb] += 1
        pend_sell[:] = False
        pend_buy[:] = False
        pos[:, k] = holding
        live = (k + 1) <= (L - 2)
        if not live.any():
            pos[:, k:] = holding[:, None]
            break
        c = C[:, k]
        h = live & holding
        peak = np.where(h, np.maximum(peak, c), peak)
        level = (peak if trailing else entry) * (1 - width)
        with np.errstate(invalid="ignore"):
            sig = h & (c <= level)
        for e in np.nonzero(sig)[0]:
            out.stops.append((int(e), k, float(level[e])))
        pend_sell |= sig
        if action == "A2":
            cand = live & ~holding & (k > exit_day) & BRK[:, k]
            ok = cand & (n_re < max_re)
            blocked += (cand & ~ok).astype(int)
            for e in np.nonzero(ok)[0]:
                out.reentries.append((int(e), k))
            pend_buy |= ok
    return out


def path_log_values(C: np.ndarray, L: np.ndarray, B: np.ndarray, pos: np.ndarray, cost: float = COST) -> np.ndarray:
    """사건별 순 로그수익: 보유일은 종목, 아니면 BIL 총수익. 진입·매도·재진입·리밸런싱일 정리마다 편도 비용(BIL 매매는 무비용)."""
    C = np.asarray(C, dtype=float)
    n, K = C.shape
    L = np.asarray(L, dtype=int)
    ar = np.arange(K)
    with np.errstate(invalid="ignore", divide="ignore"):
        g = np.where(pos[:, :-1], C[:, 1:] / C[:, :-1], B[:, 1:] / B[:, :-1])
    valid = ar[None, 1:] <= (L - 1)[:, None]
    lg = np.where(valid, np.log(np.where(valid, g, 1.0)), 0.0).sum(axis=1)
    ch = (pos[:, 1:] != pos[:, :-1]) & (ar[None, 1:] <= (L - 2)[:, None])
    final = pos[np.arange(n), np.maximum(L - 2, 0)]
    trades = 1 + ch.sum(axis=1) + final.astype(int)
    return lg + trades * math.log(1 - cost)


# =================================================================================================
# 사건 표본(사다리 연구 그대로 + 돌파·BIL 경로·손절 뒤 20일)
# =================================================================================================

@dataclass
class StopEvents:
    base: object            # LD.Events
    B: np.ndarray           # 사건 × 일 BIL 조정 가격(패딩 = 마지막)
    BRK: np.ndarray         # 사건 × 일 돈치안 20 돌파
    TAIL: np.ndarray        # 사건 × (K + 20) 조정 종가(리밸런싱일 뒤 20일까지, 없으면 NaN) — 휩쏘 진단용


def build_stop_events(prep: dict) -> StopEvents:
    ev = LD.build_events(prep)
    P = prep["P_ext"]
    bil = prep["bil_ext"].to_numpy(dtype=float)
    n, K = ev.C.shape
    B = np.ones((n, K))
    BRK = np.zeros((n, K), dtype=bool)
    TAIL = np.full((n, K + WHIPSAW_DAYS), np.nan)
    brk_cache: dict = {}
    last = len(P.index) - 1
    for e, (j, tkr) in enumerate(ev.keys):
        i0, ln = int(ev.start_pos[e]), int(ev.L[e])
        i1 = i0 + ln - 1
        B[e, :ln] = bil[i0:i1 + 1]
        B[e, ln:] = bil[i1]
        if tkr not in brk_cache:
            brk_cache[tkr] = breakout_flags(P[tkr].to_numpy(dtype=float))
        BRK[e, :ln] = brk_cache[tkr][i0:i1 + 1]
        px = P[tkr].to_numpy(dtype=float)
        hi = min(last, i1 + WHIPSAW_DAYS)
        TAIL[e, :hi - i0 + 1] = px[i0:hi + 1]
    return StopEvents(ev, B, BRK, TAIL)


def width_for(stype: str, x: float, w) -> np.ndarray:
    return np.asarray(w, dtype=float) * x if SIGMA_SCALED[stype] else np.full(np.shape(w), float(x))


# =================================================================================================
# A3 교체 엔진(실제 상위 3 일정, 보유 기간별)
# =================================================================================================

@dataclass
class Universe:
    tickers: list
    PX: np.ndarray          # 종목 × 확장 달력 조정 종가(전방 채움)
    OBS: np.ndarray         # 그날 실제 종가가 있었나
    TA: np.ndarray          # 추세 활성(그날까지 자료)
    MOM: np.ndarray         # 252일 모멘텀(그날까지 자료)
    bil: np.ndarray

    def __post_init__(self):
        self.ix = {t: i for i, t in enumerate(self.tickers)}


def build_universe(prep: dict) -> Universe:
    P = prep["P_ext"]
    tick = list(P.columns)
    PX = P.to_numpy(dtype=float).T.copy()
    raw = prep.get("obs_ext")
    OBS = raw.reindex(columns=tick).fillna(False).to_numpy(dtype=bool).T if raw is not None else np.isfinite(PX)
    TA = np.vstack([trend_active_series(r) for r in PX]) if len(tick) else np.zeros((0, PX.shape[1]), dtype=bool)
    MOM = np.vstack([momentum_series(r) for r in PX]) if len(tick) else np.zeros((0, PX.shape[1]))
    return Universe(tick, PX, OBS, TA, MOM, prep["bil_ext"].to_numpy(dtype=float))


def rank_replacement(U: Universe, pool: list, held: set, i_sig: int) -> Optional[str]:
    """그 보유 기간 풀(리밸런싱일에 고정) 중 신호일 i_sig 종가 기준 추세 활성 + 252일 모멘텀 최고(동점은 티커순), 보유 중 제외.
    i_sig 까지의 자료만 쓴다. 없으면 None(→ BIL)."""
    rows = []
    for t in pool:
        if t in held or t not in U.ix:
            continue
        r = U.ix[t]
        if not (U.OBS[r, i_sig] and U.TA[r, i_sig]):
            continue
        m = U.MOM[r, i_sig]
        if np.isfinite(m):
            rows.append((-float(m), t))
    rows.sort()
    return rows[0][1] if rows else None


def sigma_w_at(U: Universe, tkr: str, i_last: int) -> float:
    s = LD.sigma_63(pd.Series(U.PX[U.ix[tkr], :i_last + 1]))
    return s * math.sqrt(W_HORIZON) if np.isfinite(s) else float("nan")


@dataclass
class PeriodOut:
    segs: list               # 슬롯별 [(k, 자산 또는 None=BIL)] — 첫 항목은 (0, 원래 종목)
    replacements: list       # (슬롯, 손절 종목, 교체 종목 또는 None, 신호일 k)
    stops: list              # (슬롯, 종목, 신호일 k, 선)


def run_replace_period(U: Universe, i0: int, L: int, picks: list, pool: list, w_picks: list, stype: str, x: float,
                       fallback_w: float) -> PeriodOut:
    """한 보유 기간(확장 달력 i0 = 리밸런싱일, 길이 L)에서 슬롯마다 손절 → 교체(A3). 교체 종목도 같은 손절을 새로 받는다.
    손절·교체 순위 판단은 신호일 k 종가까지, 체결은 k+1 종가(매도와 매수 같은 종가)."""
    ns = len(picks)
    asset = list(picks)
    entry = [U.PX[U.ix[t], i0] for t in picks]
    peak = list(entry)
    width = [float(x * w) if SIGMA_SCALED[stype] else float(x) for w in w_picks]
    pending: dict = {}
    segs = [[(0, t)] for t in picks]
    reps, stops = [], []
    for k in range(1, L):
        i = i0 + k
        if pending and k <= L - 2:
            for sl, new in pending.items():
                asset[sl] = new
                segs[sl].append((k, new))
                if new is not None:
                    px = U.PX[U.ix[new], i]
                    entry[sl], peak[sl] = px, px
                    wn = sigma_w_at(U, new, i - 1) if SIGMA_SCALED[stype] else 1.0
                    wn = wn if np.isfinite(wn) else fallback_w
                    width[sl] = float(x * wn) if SIGMA_SCALED[stype] else float(x)
        pending = {}
        if k + 1 > L - 2:
            continue
        held = {a for a in asset if a is not None}
        for sl in range(ns):
            t = asset[sl]
            if t is None:
                continue
            c = U.PX[U.ix[t], i]
            peak[sl] = max(peak[sl], c)
            level = (peak[sl] if TRAILING[stype] else entry[sl]) * (1 - width[sl])
            if c <= level:
                stops.append((sl, t, k, float(level)))
                new = rank_replacement(U, pool, held | {t}, i)
                if new is not None:
                    held.add(new)
                pending[sl] = new
                reps.append((sl, t, new, k))
    return PeriodOut(segs, reps, stops)


def segs_log_value(U: Universe, i0: int, L: int, segs: list, cost: float = COST) -> float:
    """슬롯 하나의 순 로그수익(종목↔종목 교체는 매도+매수 2회, BIL 쪽 매매는 무비용)."""
    lg, trades = 0.0, 0
    bounds = [s[0] for s in segs] + [L - 1]
    for (k0, a), k1 in zip(segs, bounds[1:]):
        series = U.bil if a is None else U.PX[U.ix[a]]
        lg += math.log(series[i0 + k1] / series[i0 + k0])
        if a is not None:
            trades += 2
    return lg + trades * math.log(1 - cost)


# =================================================================================================
# 슬롯 단위 목표 비중(코어 85% + 새틀라이트 15%)
# =================================================================================================

def build_slot_weights(core_w: pd.DataFrame, schedule: list, switches: dict, sw: float, adj: pd.DataFrame) -> pd.DataFrame:
    """switches = {(리밸런싱 번호, 슬롯 번호): [(체결일, 새 자산 또는 None=BIL)]}. 슬롯 = 그 기간 picks 의 순서.
    - 리밸런싱일·코어 신호 변경일: 기본 목표(슬롯마다 sw/n 을 그날 그 슬롯의 자산에) — 바뀜이 없으면 tx.champion_weights 와 같다.
    - 교체만 있는 날: 그날까지 표류한 비중을 두고 그 슬롯의 표류 가치만 옛 자산 → 새 자산으로 옮긴다.
    - 그 밖의 날: 전날 목표 그대로."""
    sched = sorted(((pd.Timestamp(d), list(p)) for d, p in schedule), key=lambda x: x[0])
    idx = core_w.index[core_w.index >= sched[0][0]]
    any_bil = any(a is None for v in switches.values() for _, a in v)
    sat_cols = sorted({t for _, p in sched for t in p} | {a for v in switches.values() for _, a in v if a is not None})
    cols = list(dict.fromkeys(list(core_w.columns) + sat_cols + ([BIL] if any_bil else [])))
    ci = {c: i for i, c in enumerate(cols)}
    base = core_w.reindex(index=idx, columns=cols).fillna(0.0).to_numpy() * (1 - sw)
    # 날마다 슬롯의 자산
    slot_asset = {}      # 날 위치 → [(슬롯 키, 자산 열 번호, 슬롯 비중)]
    trade_days: dict = {}
    for j, (d, picks) in enumerate(sched):
        if not picks:
            continue
        lo = idx.searchsorted(d)
        hi = idx.searchsorted(sched[j + 1][0]) if j + 1 < len(sched) else len(idx)
        per = sw / len(picks)
        for s, tkr in enumerate(picks):
            path = [(lo, tkr)]
            for dd, a in sorted(switches.get((j, s), []), key=lambda x: x[0]):
                p = int(idx.searchsorted(pd.Timestamp(dd)))
                if p < hi:
                    path.append((p, a))
                    trade_days.setdefault(p, []).append((j, s))
            bounds = [p for p, _ in path] + [hi]
            for (p0, a), p1 in zip(path, bounds[1:]):
                col = ci[BIL if a is None else a]
                base[p0:p1, col] += per
                for q in range(p0, p1):
                    slot_asset.setdefault(q, []).append(((j, s), col, per))
    if not trade_days:
        return pd.DataFrame(base, index=idx, columns=cols)
    core_chg = core_w.reindex(idx).fillna(0.0).diff().abs().sum(axis=1).to_numpy() > 1e-12
    starts = {int(idx.searchsorted(d)) for d, _ in sched}
    a = adj.reindex(index=idx, columns=cols).ffill()
    tr = a.pct_change(fill_method=None).fillna(0.0).to_numpy()
    out = np.zeros_like(base)
    drift, sval = None, {}
    row = None
    for i in range(len(idx)):
        cur = {key: col for key, col, _ in slot_asset.get(i, [])}
        prev_cur = {key: col for key, col, _ in slot_asset.get(i - 1, [])} if i else {}
        if drift is not None:
            g = drift * (1 + tr[i])
            port = g.sum() + (1 - drift.sum())
            port = port if port > 0 else 1.0
            drift = g / port
            sval = {key: v * (1 + tr[i][prev_cur[key]]) / port for key, v in sval.items() if key in prev_cur}
        reset = row is None or i in starts or core_chg[i]
        if reset:
            row = base[i].copy()
            sval = {key: per for key, _, per in slot_asset.get(i, [])}
        elif i in trade_days:
            row = drift.copy()
            for key in trade_days[i]:
                old, new = prev_cur.get(key), cur.get(key)
                if old is None or new is None or old == new:
                    continue
                amt = sval.get(key, 0.0)
                row[old] -= amt
                row[new] += amt
        out[i] = row
        if reset or i in trade_days or drift is None:
            drift = row.copy()
    return pd.DataFrame(out, index=idx, columns=cols)


# =================================================================================================
# 판정
# =================================================================================================

def decide_primary(diff_conf, sharpe_v, sharpe_0, mdd_v, mdd_0, ci_low, *, noop=None, observed_ir=None, power=None) -> str:
    """사전 등록: (a) 세후 연수익 차이 > 0, (b) 세전 샤프 더 높음, (c) 원화 MDD 2%p 넘게 나빠지지 않음, (d) 부트스트랩 90% 하한 > −0.5%p."""
    return LD.decide_primary(diff_conf, sharpe_v, sharpe_0, mdd_v, mdd_0, ci_low, noop=noop,
                             observed_ir=observed_ir, power=power)


def block_bootstrap_diff(ra, rb, ppy):
    return SV.block_bootstrap_diff(ra, rb, ppy, n_boot=N_BOOT, block=BLOCK_DAYS, seed=BOOT_SEED)


def pair_stats(a: dict, b: dict, with_boot: bool = True) -> dict:
    out = LD.pair_stats(a, b, with_boot=False)
    if with_boot:
        va, vb, initial = a["values"], b["values"], a["initial"]
        t1 = va.index[-1]
        ra, rb = SV.window_returns(va, initial, t1), SV.window_returns(vb, initial, t1)
        years = (t1 - va.index[0]).days / 365.25
        ppy = len(ra) / years if years > 0 else 252.0
        if len(ra) > 2:
            boot = block_bootstrap_diff(ra.to_numpy(), rb.to_numpy(), ppy)
            lo, hi = np.percentile(boot, CI_PCT)
            out.update({"boot_ci90_low": float(lo), "boot_ci90_high": float(hi), "boot_share_positive": float(np.mean(boot > 0))})
    return out


# =================================================================================================
# 입력(사다리 연구의 준비 + 풀 전체 가격)
# =================================================================================================

def _prepare_stop(data, sectors, core_w, frames, spy_frame, bil_frame, fx, meta):
    prep = _ORIG_PREPARE(data, sectors, core_w, frames, spy_frame, bil_frame, fx, meta)
    pools = []
    for r in prep["schedule"]:
        d = pd.Timestamp(r["date"])
        mem = [t for t in data.pool("champion40", d) if t in data.closes.columns and pd.notna(data.closes.at[d, t])
               and t in data.ohlcv]
        pools.append(sorted(set(mem)))
    allt = sorted(set(prep["P_ext"].columns) | {t for p in pools for t in p})
    ext = prep["ext_days"]
    adj_cols, obs = {}, {}
    for t in allt:
        df = SV._norm(data.ohlcv[t])
        col = "Adj Close" if "Adj Close" in df.columns and df["Adj Close"].notna().any() else "Close"
        s = pd.to_numeric(df[col], errors="coerce")
        adj_cols[t] = s
        obs[t] = s.reindex(ext).notna()
    prep["P_ext"] = pd.DataFrame(adj_cols).reindex(ext).ffill()
    prep["obs_ext"] = pd.DataFrame(obs)
    pf = {t: frames.get(t) for t in frames}
    pf.update({t: data.ohlcv.get(t) for t in allt})
    pf["SPY"] = spy_frame
    pf[BIL] = bil_frame
    prep["close"], prep["adj"] = SV._panel(pf)
    prep["pools"] = pools
    prep["meta"] = {**prep["meta"], "n_pool_tickers": len(allt)}
    return prep


_ORIG_PREPARE = LD._prepare


@contextlib.contextmanager
def _patched_prepare():
    LD._prepare = _prepare_stop
    try:
        yield
    finally:
        LD._prepare = _ORIG_PREPARE


def _real_prep(log) -> dict:
    with _patched_prepare():
        return LD._real_prep(log)


def _smoke_prep(log) -> dict:
    with _patched_prepare():
        return LD._smoke_prep(log)


# =================================================================================================
# 맞추기(선정 구간만)
# =================================================================================================

def eval_event_cell(se: StopEvents, idx: np.ndarray, stype: str, x: float, action: str) -> tuple[np.ndarray, StopOut]:
    ev = se.base
    wd = width_for(stype, x, ev.w[idx])
    out = run_stops(ev.C[idx], ev.L[idx], se.BRK[idx], wd, stype, action)
    return path_log_values(ev.C[idx], ev.L[idx], se.B[idx], out.pos), out


def periods_of(prep: dict, se: StopEvents, window: Optional[str]) -> list:
    """실제 상위 3 보유 기간: [(j, i0, L, picks, pool, w_picks, fallback_w)]."""
    ev = se.base
    key_ix = {k: e for e, k in enumerate(ev.keys)}
    out = []
    for j, r in enumerate(prep["schedule"]):
        picks = list(r["picks"])
        if not picks:
            continue
        es = [key_ix[(j, t)] for t in picks]
        if window is not None and ev.window[es[0]] != window:
            continue
        ws = [float(ev.w[e]) for e in es]
        same = ev.w[ev.start_pos == ev.start_pos[es[0]]]
        out.append((j, int(ev.start_pos[es[0]]), int(ev.L[es[0]]), picks, prep["pools"][j], ws, float(np.median(same))))
    return out


def eval_replace(U: Universe, periods: list, stype: str, x: float) -> tuple[list, list]:
    """(슬롯별 순 로그수익 목록, 기간별 PeriodOut)."""
    vals, outs = [], []
    for j, i0, L, picks, pool, ws, fw in periods:
        po = run_replace_period(U, i0, L, picks, pool, ws, stype, x, fw)
        outs.append(po)
        vals += [segs_log_value(U, i0, L, s) for s in po.segs]
    return vals, outs


def fit_widths(grid: dict) -> dict:
    """(유형, 행동)마다 선정 구간 평균 순 로그수익 최대 폭. 동점은 격자 순서상 앞."""
    fit = {}
    for st in STOP_TYPES:
        for a in ACTIONS:
            best_x, best = None, -np.inf
            for x in WIDTHS[st]:
                m = grid[(st, a, x)]
                if m > best + 1e-15:
                    best_x, best = x, m
            fit[f"{st}_{a}"] = {"x": best_x, "mean_sel": best}
    return fit


# =================================================================================================
# 진단
# =================================================================================================

def stop_diagnostics(se: StopEvents, idx: np.ndarray, out: StopOut, logv: np.ndarray, logv0: np.ndarray) -> dict:
    """손절 발동률·휩쏘율(체결 뒤 20거래일 안에 종가가 선 위로)·피한 손실/놓친 수익(현행 보유 대비)."""
    n = len(idx)
    if n == 0:
        return {"n": 0}
    first = {}
    for e, k, lv in out.stops:
        first.setdefault(e, (k, lv))
    whip = []
    for e, (k, lv) in first.items():
        seg = se.TAIL[idx[e], k + 2:k + 2 + WHIPSAW_DAYS]
        seg = seg[np.isfinite(seg)]
        whip.append(bool(len(seg) and (seg > lv).any()))
    hit = np.array(sorted(first), dtype=int)
    d = (logv - logv0)[hit] if len(hit) else np.array([])
    return {"n": int(n), "stop_hit_rate": len(first) / n, "whipsaw_rate": float(np.mean(whip)) if whip else None,
            "n_stopped": len(first),
            "share_helped": float(np.mean(d > 0)) if len(d) else None,
            "mean_loss_avoided": float(d[d > 0].mean()) if (d > 0).any() else None,
            "mean_gain_missed": float(-d[d < 0].mean()) if (d < 0).any() else None,
            "mean_diff_stopped": float(d.mean()) if len(d) else None,
            "mean_log_ret": float(logv.mean()), "mean_log_ret_v0": float(logv0.mean())}


def reentry_success(se: StopEvents, idx: np.ndarray, out: StopOut, cost: float = COST) -> dict:
    """재진입 성공 = 재진입 체결 종가 → 그 구간 끝(다음 손절 체결 또는 리밸런싱일) 종목 순수익이 같은 기간 BIL 보다 높음."""
    ev = se.base
    res = []
    for e, k in out.reentries:
        g = idx[e]
        L = int(ev.L[g])
        k0 = k + 1
        pos = out.pos[e]
        k1 = k0 + 1
        while k1 < L - 1 and pos[k1]:
            k1 += 1
        k1 = min(k1, L - 1)
        r_s = math.log(ev.C[g, k1] / ev.C[g, k0]) + 2 * math.log(1 - cost)
        r_b = math.log(se.B[g, k1] / se.B[g, k0])
        res.append(r_s > r_b)
    return {"n_reentries": len(res), "success_rate": float(np.mean(res)) if res else None,
            "n_blocked_by_limit": int(out.blocked.sum())}


def replacement_diag(U: Universe, periods: list, outs: list) -> dict:
    """교체 종목 vs 손절 종목: 체결일 → 기간 끝 그냥 보유 로그수익 차이."""
    diffs, n_bil = [], 0
    for (j, i0, L, *_), po in zip(periods, outs):
        for sl, old, new, k in po.replacements:
            if k + 1 > L - 2:
                continue
            if new is None:
                n_bil += 1
                continue
            a, b = i0 + k + 1, i0 + L - 1
            r_new = math.log(U.PX[U.ix[new], b] / U.PX[U.ix[new], a])
            r_old = math.log(U.PX[U.ix[old], b] / U.PX[U.ix[old], a])
            diffs.append(r_new - r_old)
    d = np.array(diffs)
    return {"n_replaced": len(d), "n_to_bil": n_bil, "mean_fwd_diff": float(d.mean()) if len(d) else None,
            "share_replacement_better": float(np.mean(d > 0)) if len(d) else None}


# =================================================================================================
# 분석·보고
# =================================================================================================

def _pp(x):
    return LD._pp(x)


def _pct(x, signed=False, nd=1):
    return LD._pct(x, signed, nd)


def analyze(prep: dict, se: StopEvents, U: Universe, fit: dict, grid: dict, sims: dict, smoke: bool) -> dict:
    ev = se.base
    sel_idx = np.nonzero(ev.window == "sel")[0]
    conf_idx = np.nonzero(ev.window == "conf")[0]
    cell_of = np.array([f"{a}|{b}" for a, b in ev.cell])
    v0 = path_log_values(ev.C, ev.L, se.B, np.ones_like(ev.C, dtype=bool))
    # 사건 진단(A1/A2: 후보 전체, 확인 구간 위주)
    per_type, per_cell = {}, {}
    for st in STOP_TYPES:
        row = {}
        for a in ("A1", "A2"):
            x = fit[f"{st}_{a}"]["x"]
            for wn, ix in (("sel", sel_idx), ("conf", conf_idx)):
                lv, out = eval_event_cell(se, ix, st, x, a)
                dg = stop_diagnostics(se, ix, out, lv, v0[ix])
                if a == "A2":
                    dg.update(reentry_success(se, ix, out))
                row[f"{a}_{wn}"] = dg
                if a == "A1" and wn == "conf":
                    for v, f in CELLS:
                        key = f"{v}|{f}"
                        m = cell_of[ix] == key
                        sub = StopOut(pos=out.pos[m], blocked=out.blocked[m])
                        remap = {old: new for new, old in enumerate(np.nonzero(m)[0])}
                        sub.stops = [(remap[e], k, lv_) for e, k, lv_ in out.stops if e in remap]
                        per_cell.setdefault(key, {})[st] = {
                            k_: v_ for k_, v_ in stop_diagnostics(se, ix[m], sub, lv[m], v0[ix][m]).items()
                            if k_ in ("n", "stop_hit_rate", "whipsaw_rate", "share_helped", "mean_loss_avoided", "mean_gain_missed")}
                if a == "A2" and wn == "conf":
                    for v, f in CELLS:
                        key = f"{v}|{f}"
                        m = cell_of[ix] == key
                        sub = StopOut(pos=out.pos[m], blocked=out.blocked[m])
                        remap = {old: new for new, old in enumerate(np.nonzero(m)[0])}
                        sub.reentries = [(remap[e], k) for e, k in out.reentries if e in remap]
                        per_cell.setdefault(key, {}).setdefault(st, {})["A2_reentry_success"] = reentry_success(se, ix[m], sub)["success_rate"]
        for wn in ("sel", "conf"):
            per = periods_of(prep, se, wn)
            vals, outs = eval_replace(U, per, st, fit[f"{st}_A3"]["x"])
            base_vals = [segs_log_value(U, i0, L, [(0, t)]) for _, i0, L, picks, *_ in per for t in picks]
            row[f"A3_{wn}"] = {**replacement_diag(U, per, outs), "n_slots": len(vals),
                               "mean_log_ret": float(np.mean(vals)) if vals else None,
                               "mean_log_ret_v0": float(np.mean(base_vals)) if base_vals else None,
                               "stop_hit_rate": (sum(len({s for s, *_ in po.stops}) for po in outs) / len(vals)) if vals else None}
        per_type[st] = row
    # 고른 폭을 평범한 %로
    med_w_all = float(np.median(ev.w[sel_idx])) if len(sel_idx) else float("nan")
    med_w_bucket = {b: float(np.median(ev.w[sel_idx][np.array([ev.cell[i][0] == b for i in sel_idx])]))
                    if any(ev.cell[i][0] == b for i in sel_idx) else None for b in LD.VOL_BUCKETS}
    widths_pct = {}
    for name, fv in fit.items():
        st = name.split("_")[0]
        x = fv["x"]
        widths_pct[name] = {"x": x, "median_ticker_pct": x * med_w_all if SIGMA_SCALED[st] else x,
                            "by_vol_bucket_pct": {b: (x * m if SIGMA_SCALED[st] else x) if m is not None else None
                                                  for b, m in med_w_bucket.items()}}
    # 포트폴리오 판정
    powers = rp.power_report(sims[("champ", "V0", "conf", "base_30m")]["years"], N_TRIALS)
    pairs, verdicts, raw = {}, {}, {}
    for name in JUDGED:
        p = {}
        for win in WINDOWS:
            k0, kv = ("champ", "V0", win, "base_30m"), ("champ", name, win, "base_30m")
            if k0 in sims and kv in sims:
                p[win] = pair_stats(sims[kv], sims[k0], with_boot=(win == "conf"))
        if ("champ", name, "conf", "base_100m") in sims:
            p["conf_100m"] = pair_stats(sims[("champ", name, "conf", "base_100m")], sims[("champ", "V0", "conf", "base_100m")],
                                        with_boot=False)
        pairs[name] = p
        if "conf" in p:
            c = p["conf"]
            sv, s0 = sims[("champ", name, "conf", "base_30m")], sims[("champ", "V0", "conf", "base_30m")]
            v = decide_primary(c["diff"], sv["sharpe_pretax_excess"], s0["sharpe_pretax_excess"], sv["mdd_after"], s0["mdd_after"],
                               c.get("boot_ci90_low", float("nan")), noop=c["noop_reason"], observed_ir=c["daily_diff_ir"],
                               power=powers)
            raw[name] = v
            verdicts[name] = f"SMOKE_ONLY({v})" if smoke else v
    secondary = {}
    for name in VARIANTS:
        k = ("sleeve", name, "conf", "base_30m")
        if k not in sims:
            continue
        s, spy, ch = sims[k], sims[("spy", "SPY", "conf", "base_30m")], sims[("champ", "V0", "conf", "base_30m")]
        bs = LD.beats_spy(s["cagr_after"], s["mdd_after"], spy["cagr_after"], spy["mdd_after"])
        bc = LD.beats_champion(s["cagr_after"], s["mdd_after"], ch["cagr_after"], ch["mdd_after"])
        secondary[name] = {"BEATS_SPY": bs, "BEATS_CHAMPION": bc, "label": f"SPY:{'YES' if bs else 'NO'} / CHAMP:{'YES' if bc else 'NO'}"}
    metrics = {}
    for (lvl, name, win, setup), s in sims.items():
        metrics.setdefault(setup, {}).setdefault(win, {}).setdefault(lvl, {})[name] = {
            k: (round(s[k], 6) if isinstance(s[k], float) else s[k]) for k in
            ("cagr_after", "cagr_pre", "mdd_after", "final_krw", "sharpe_pretax_excess", "years")}
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windows_daily": {k: [str(a.date()), str(b.date())] for k, (a, b) in prep["windows"].items()},
        "entry_windows": {"sel": list(SEL_ENTRY), "conf": list(CONF_ENTRY), "post_from": POST_FROM},
        "n_events": {"sel": int(len(sel_idx)), "conf": int(len(conf_idx)), "all": int(len(ev.L))},
        "n_trials": N_TRIALS,
        "grid_sel_mean_log_ret": {f"{st}_{a}_{x}": v for (st, a, x), v in grid.items()},
        "fit": fit, "widths_pct": widths_pct, "median_w_sel": med_w_all, "median_w_by_bucket": med_w_bucket,
        "diagnostics_by_type": per_type, "diagnostics_by_cell_conf": per_cell,
        "metrics": metrics, "pairs": pairs, "power": powers, "power_line": rp.power_line(powers),
        "verdicts": verdicts, "verdicts_raw": raw, "secondary_verdicts": secondary,
        "variants": {"V0": "현행(반기까지 보유)", **{f"{t}_{a}": f"{TYPE_KO[t]} + {ACTION_KO[a]}" for t in STOP_TYPES for a in ACTIONS}},
        "inputs_meta": prep.get("meta", {}),
        "rules": {"cost_bp_per_side": COST * 1e4, "n_boot": N_BOOT, "block_days": BLOCK_DAYS, "boot_seed": BOOT_SEED,
                  "ci_low_floor": CI_LOW_FLOOR, "mdd_tol_champion": MDD_TOL_CHAMP, "max_reentry": MAX_REENTRY,
                  "whipsaw_days": WHIPSAW_DAYS, "fixed_pct": list(FIXED_PCT), "k_w": list(K_W), "sat_weight": SAT_WEIGHT},
    }
    return result


def practical_answer(r: dict) -> list[str]:
    """'그래서 손절은 어떻게?' — 데이터가 말하는 것과 말하지 못하는 것(채택 주장 없음)."""
    L = ["## 그래서 손절은 어떻게?", ""]
    raw = r["verdicts_raw"]
    passed = [k for k, v in raw.items() if v == PASS]
    pairs = r["pairs"]
    diffs = {k: pairs[k].get("conf", {}).get("diff") for k in JUDGED}
    finite = {k: v for k, v in diffs.items() if v is not None and math.isfinite(v)}
    if passed:
        L.append(f"- 사전 등록 관문을 모두 넘은 조합: {', '.join(passed)}. 이것은 '전진 원장에 올릴 후보'일 뿐 채택이 아니다(확인 구간은 이미 본 기간).")
    else:
        L.append("- 확인 구간에서 사전 등록 관문을 모두 넘은 손절 조합은 없다. 이 기간·이 진입 규칙에서는 '손절을 건다'가 '반기까지 들고 간다'보다 낫다는 근거가 없다.")
    if finite:
        best = max(finite, key=finite.get)
        L.append(f"- 세후 연수익 차이가 가장 나은 조합은 {best}({_pp(finite[best])}) — 판정은 위 표 그대로다.")
    acts = {}
    for a in ACTIONS:
        v = [finite[f"{t}_{a}"] for t in STOP_TYPES if f"{t}_{a}" in finite]
        acts[a] = float(np.mean(v)) if v else None
    L.append("- 손절 뒤 행동별 평균 세후 차이(4개 유형 평균): " + ", ".join(f"{a} {ACTION_KO[a]} {_pp(acts[a])}" for a in ACTIONS) + ".")
    whips = [r["diagnostics_by_type"][t]["A1_conf"].get("whipsaw_rate") for t in STOP_TYPES]
    whips = [w for w in whips if w is not None]
    if whips:
        L.append(f"- 손절한 종목이 20거래일 안에 손절선 위로 되돌아온 비율(휩쏘, 확인 구간 A1): {min(whips):.0%}~{max(whips):.0%}. "
                 "이 비율이 높을수록 '손절 = 바닥에서 팔기'가 잦았다는 뜻이다.")
    L += ["- 데이터가 말하지 못하는 것: 상장폐지된 종목이 빠져 있어(생존편향) 손절이 가장 도움이 됐을 폭락 사례가 표본에 없다. "
          "따라서 '손절이 필요 없다'를 증명하지 않는다 — 회사가 망가지는 꼬리 위험에 대한 보험으로서의 손절은 이 표본으로 평가할 수 없다.",
          "- 고른 폭(아래 표의 %)은 선정 구간 평균을 최대로 한 값이고, 42개 칸 중 최선이라 운이 섞여 있다.", ""]
    return L


def report(r: dict) -> str:
    sm = " (스모크 — 합성 데이터, 실측 아님)" if r["smoke"] else ""
    m30 = r["metrics"].get("base_30m", {})
    conf = m30.get("conf", {})
    c0 = conf.get("champ", {}).get("V0", {})
    L = [f"# 새틀라이트 손절 — 손절 방식 × 손절 뒤 행동{sm}", "",
         "진입은 지금과 똑같다(S-SEED-000). 바뀌는 것은 손절 방식(4종)과 손절 뒤 돈을 어디에 두는지(3종)다. 신호는 그날 종가, 체결은 다음 날 종가, 편도 8bp.",
         "폭은 (유형, 행동)마다 선정 구간(진입 2010-01~2016-07) 사건 평균 순 로그수익이 가장 큰 값을 골랐다. 판정은 확인 구간(진입 2017-07~2024-01, 일별 2024-09-30까지).", "",
         "## 판정(챔피언 = 코어 85% + 새틀라이트 15%, 세후 원화 3,000만 원, 확인 구간)", "",
         "| 변형 | 폭 | 판정 | 세후 연수익 차이 | 부트스트랩 90% | 세전 샤프(본/현행) | 원화 MDD(본/현행) | 1억 원 차이 |",
         "|---|---|---|---|---|---|---|---|"]
    for name in JUDGED:
        st = name.split("_")[0]
        p = r["pairs"].get(name, {})
        c = p.get("conf", {})
        cv = conf.get("champ", {}).get(name, {})
        wp = r["widths_pct"][name]
        wtxt = (f"{wp['x']:g}·w(≈{_pct(wp['median_ticker_pct'])})" if SIGMA_SCALED[st] else _pct(wp["x"], nd=0))
        L.append(f"| {name} {TYPE_KO[st]} + {ACTION_KO[name.split('_')[1]]} | {wtxt} | **{r['verdicts'].get(name, '—')}** | {_pp(c.get('diff'))} | "
                 f"{_pp(c.get('boot_ci90_low'))} ~ {_pp(c.get('boot_ci90_high'))} | "
                 f"{cv.get('sharpe_pretax_excess', float('nan')):.2f} / {c0.get('sharpe_pretax_excess', float('nan')):.2f} | "
                 f"{_pct(cv.get('mdd_after'))} / {_pct(c0.get('mdd_after'))} | {_pp(p.get('conf_100m', {}).get('diff'))} |")
    L += ["", "통과 조건(모두): 세후 연수익 차이 > 0, 세전 샤프(BIL 초과) 더 높음, 원화 MDD 가 2%p 넘게 나빠지지 않음, "
          f"126일 블록 부트스트랩 1,000회(시드 {BOOT_SEED}) 90% 하한 > −0.5%p.", "", f"- {r['power_line']}"]
    for name in JUDGED:
        c = r["pairs"].get(name, {}).get("conf", {})
        if c.get("noop_reason"):
            L.append(f"- {name}: 무효 실행 가드 — {c['noop_reason']}")
    L += [""] + practical_answer(r)
    L += ["## 유형별 진단(사건 = 리밸런싱일의 추세 활성 후보 전부, 고른 폭)", "",
          "| 유형 | 행동 | 구간 | 발동률 | 휩쏘율 | 손절이 도움된 비율 | 평균 피한 손실 / 놓친 수익 | 사건 평균 / 현행 | 재진입 성공(A2) | 교체 vs 손절 종목(A3) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for st in STOP_TYPES:
        d = r["diagnostics_by_type"][st]
        for a in ("A1", "A2"):
            for wn in ("sel", "conf"):
                x = d[f"{a}_{wn}"]
                if not x.get("n"):
                    continue
                re = f"{_pct(x.get('success_rate'), nd=0)} ({x.get('n_reentries', 0)}건, 한도로 막힘 {x.get('n_blocked_by_limit', 0)})" if a == "A2" else ""
                L.append(f"| {st} | {a} | {wn} | {_pct(x.get('stop_hit_rate'), nd=0)} | {_pct(x.get('whipsaw_rate'), nd=0)} | "
                         f"{_pct(x.get('share_helped'), nd=0)} | {_pct(x.get('mean_loss_avoided'), True)} / {_pct(x.get('mean_gain_missed'), True)} | "
                         f"{_pct(x.get('mean_log_ret'), True, 2)} / {_pct(x.get('mean_log_ret_v0'), True, 2)} | {re} | |")
        for wn in ("sel", "conf"):
            x = d[f"A3_{wn}"]
            L.append(f"| {st} | A3 | {wn} | {_pct(x.get('stop_hit_rate'), nd=0)} | | | | "
                     f"{_pct(x.get('mean_log_ret'), True, 2)} / {_pct(x.get('mean_log_ret_v0'), True, 2)} (실제 3종목) | | "
                     f"교체 {x.get('n_replaced', 0)}건·BIL {x.get('n_to_bil', 0)}건, 기간 끝까지 차이 {_pct(x.get('mean_fwd_diff'), True)}, "
                     f"교체가 나은 비율 {_pct(x.get('share_replacement_better'), nd=0)} |")
    L += ["", "휩쏘 = 손절 체결 뒤 20거래일 안에 종가가 손절선 위로 돌아옴. 피한 손실/놓친 수익 = 손절된 사건의 '현행 보유 대비' 로그수익 차이(+ 평균 / − 평균).", "",
          "## 셀(변동성 × 섹터)별 — 확인 구간, A1(현금) 고른 폭", "",
          "| 셀 | " + " | ".join(f"{t} 발동·휩쏘·도움" for t in STOP_TYPES) + " | A2 재진입 성공(T1/T2/T3/T4) |", "|---|---|---|---|---|---|"]
    for key, row in r["diagnostics_by_cell_conf"].items():
        cells = []
        for t in STOP_TYPES:
            x = row.get(t, {})
            cells.append(f"{_pct(x.get('stop_hit_rate'), nd=0)}·{_pct(x.get('whipsaw_rate'), nd=0)}·{_pct(x.get('share_helped'), nd=0)} (n={x.get('n', 0)})")
        re = "/".join(_pct(row.get(t, {}).get("A2_reentry_success"), nd=0) for t in STOP_TYPES)
        L.append(f"| {key} | " + " | ".join(cells) + f" | {re} |")
    L += ["", "## 고른 폭을 평범한 %로(선정 구간 중앙값 종목, 변동성 삼분위별)", "",
          f"선정 구간 중앙값 종목의 한 달 변동 w = {_pct(r['median_w_sel'])}.", "", "| 변형 | 폭 | 중앙값 종목 | low / mid / high |", "|---|---|---|---|"]
    for name, wp in r["widths_pct"].items():
        b = wp["by_vol_bucket_pct"]
        L.append(f"| {name} | {wp['x']:g} | {_pct(wp['median_ticker_pct'])} | {_pct(b.get('low'))} / {_pct(b.get('mid'))} / {_pct(b.get('high'))} |")
    spy = conf.get("spy", {}).get("SPY", {})
    L += ["", "## 보조 비교: 새틀라이트 3종목만 100%(확인 구간, 세후 원화 3,000만 원, 판정 아님)", "",
          "| 변형 | 세후 연수익 | 원화 MDD | SPY 이김?(연 +1%p, MDD 3%p 이내) | 챔피언 이김?(연수익 >, MDD 10%p 이내) |", "|---|---|---|---|---|"]
    for name, sv in r["secondary_verdicts"].items():
        s = conf.get("sleeve", {}).get(name, {})
        L.append(f"| {name} | {_pct(s.get('cagr_after'), nd=2)} | {_pct(s.get('mdd_after'))} | {'예' if sv['BEATS_SPY'] else '아니오'} | {'예' if sv['BEATS_CHAMPION'] else '아니오'} |")
    L.append(f"| (기준) SPY | {_pct(spy.get('cagr_after'), nd=2)} | {_pct(spy.get('mdd_after'))} | | |")
    L.append(f"| (기준) 현 챔피언 | {_pct(c0.get('cagr_after'), nd=2)} | {_pct(c0.get('mdd_after'))} | | |")
    L += ["", "## 구간별 세후 연수익(챔피언 수준, 3,000만 원)", "", "| 변형 | 선정 구간(맞춘 구간) | 확인 구간 | 2024-07~ (보고) |", "|---|---|---|---|"]
    for name in VARIANTS:
        row = [m30.get(w, {}).get("champ", {}).get(name, {}).get("cagr_after") for w in WINDOWS]
        L.append(f"| {name} | {_pct(row[0], nd=2)} | {_pct(row[1], nd=2)} | {_pct(row[2], nd=2)} |")
    L += ["", "## 주의", "",
          "- **생존편향(손절에 불리한 쪽)**: 상장폐지·파산 종목은 가격 소스에 없어 후보에서 빠진다. 손절이 가장 크게 도왔을 붕괴 사례가 빠졌으므로 "
          "이 결과는 손절의 가치를 **과소평가**하는 쪽으로 기울어 있다.",
          "- 섹터 분류는 지금의 S&P500 분류다(시점 기준 아님).",
          "- 확인 구간(2017-07~2024-09)은 다른 연구들이 이미 본 기간이다. PASS 도 '전진 원장에 올릴 후보'일 뿐 채택이 아니다. 챔피언 반영은 사용자 확인 뒤 별도 작업이다.",
          f"- 시도 수 {r['n_trials']}(유형별 폭 14개 × 행동 3개)로 검정력을 계산했다.",
          "- A2·A3 의 추세 판정·돌파·모멘텀은 조정 종가로 계산한다(S-SEED-000 선정은 원 종가). 배당 차이만큼 미세하게 다를 수 있다.",
          "- 함께 볼 연구: sat-exit-ladder-v1(손절·추적 익절 사다리 — 모두 FAIL, 손절 뒤 BIL 대기가 주된 비용), "
          "sat-exit-accuracy-v1(매도 신호별 정확도).", ""]
    return "\n".join(L)


def smoke_coverage(r: dict, extra: dict) -> dict:
    d = r["diagnostics_by_type"]

    def any_hit(st, key):
        return any((d[st][f"{key}_{w}"].get("stop_hit_rate") or 0) > 0 for w in ("sel", "conf"))
    cov = {f"{st}_{a}_stop": any_hit(st, a) for st in STOP_TYPES for a in ACTIONS}
    cov.update({"A2_reentry": any((d[st][f"A2_{w}"].get("n_reentries") or 0) > 0 for st in STOP_TYPES for w in ("sel", "conf")),
                "A2_limit": extra.get("blocked", 0) > 0,
                "A3_replace": any((d[st][f"A3_{w}"].get("n_replaced") or 0) > 0 for st in STOP_TYPES for w in ("sel", "conf")),
                "champion_verdicts": len(r["verdicts"]) == len(JUDGED),
                "sleeve_verdicts": len(r["secondary_verdicts"]) == len(VARIANTS),
                "tax_engine": bool(r["metrics"].get("base_30m", {}).get("conf", {}).get("champ", {}).get("V0", {}).get("final_krw"))})
    return cov


# =================================================================================================
# 실행
# =================================================================================================

def variant_switches(name: str, prep: dict, se: StopEvents, U: Universe, fit: dict) -> dict:
    """{(j, 슬롯): [(체결일, 자산 또는 None)]} — 실제 상위 3 에 변형을 적용."""
    ext = prep["ext_days"]
    if name == "V0":
        return {}
    st, a = name.split("_")
    x = fit[name]["x"]
    ev = se.base
    out: dict = {}
    if a in ("A1", "A2"):
        idx = np.nonzero(ev.picked)[0]
        _, so = eval_event_cell(se, idx, st, x, a)
        for row, e in enumerate(idx):
            j, tkr = ev.keys[e]
            s = prep["schedule"][j]["picks"].index(tkr)
            p = so.pos[row]
            L = int(ev.L[e])
            for k in range(1, L - 1):
                if p[k] != p[k - 1]:
                    out.setdefault((j, s), []).append((ext[ev.start_pos[e] + k], tkr if p[k] else None))
        return out
    for j, i0, L, picks, pool, ws, fw in periods_of(prep, se, None):
        po = run_replace_period(U, i0, L, picks, pool, ws, st, x, fw)
        for s, sg in enumerate(po.segs):
            for k, asset in sg[1:]:
                out.setdefault((j, s), []).append((ext[i0 + k], asset))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-steps-per-run", type=int, default=0, help="재개 확인용: 이번 실행의 새 계산 단위 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    steps = {"n": 0}

    def log(s: str) -> None:
        print(s, flush=True)

    def step() -> None:
        if deadline is not None and time.time() > deadline - 90:
            raise _Stop()
        if a.max_steps_per_run and steps["n"] >= a.max_steps_per_run:
            raise _Stop()
        steps["n"] += 1

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        prep = LD._load_ckpt(ck / "prep.pkl", fp)
        if prep is None:
            step()
            prep = _smoke_prep(log) if a.smoke else _real_prep(log)
            LD._atomic_pickle(ck / "prep.pkl", {"fingerprint": fp, "payload": prep})
            log("입력 체크포인트 저장")
        se = build_stop_events(prep)
        U = build_universe(prep)
        ev = se.base
        sel_idx = np.nonzero(ev.window == "sel")[0]
        log(f"사건: 선정 {len(sel_idx)} · 확인 {int((ev.window == 'conf').sum())} · 전체 {len(ev.L)} · 풀 종목 {len(U.tickers)}")
        # 격자(선정 구간만): 유형마다 체크포인트
        grid: dict = {}
        blocked_total = 0
        sel_periods = periods_of(prep, se, "sel")
        for st in STOP_TYPES:
            path = ck / f"grid_{st}.pkl"
            got = LD._load_ckpt(path, fp)
            if got is None:
                step()
                got = {}
                for x in WIDTHS[st]:
                    for act in ("A1", "A2"):
                        lv, so = eval_event_cell(se, sel_idx, st, x, act)
                        got[(st, act, x)] = float(lv.mean()) if len(lv) else float("nan")
                        if act == "A2":
                            got[("blocked", st, x)] = int(so.blocked.sum())
                    vals, _ = eval_replace(U, sel_periods, st, x)
                    got[(st, "A3", x)] = float(np.mean(vals)) if vals else float("nan")
                LD._atomic_pickle(path, {"fingerprint": fp, "payload": got})
                log(f"격자 {st} 끝")
            for k_, v_ in got.items():
                if k_[0] == "blocked":
                    blocked_total += v_
                else:
                    grid[k_] = v_
        fit = fit_widths(grid)
        log("고른 폭: " + ", ".join(f"{k}={v['x']}" for k, v in fit.items()))
        # 포트폴리오
        sched = [(pd.Timestamp(r["date"]), r["picks"]) for r in prep["schedule"]]
        windows = LD.window_bounds(prep["core_w"].index, prep["schedule"])
        prep["windows"] = windows
        bil_r = prep["adj"][BIL].pct_change(fill_method=None)
        zero_core = pd.DataFrame(0.0, index=prep["core_w"].index, columns=prep["core_w"].columns)
        switches = {name: variant_switches(name, prep, se, U, fit) for name in VARIANTS}
        jobs = []
        for win in WINDOWS:
            if win not in windows:
                continue
            for lvl in LEVELS:
                jobs += [(lvl, name, win, "base_30m") for name in VARIANTS]
            jobs.append(("spy", "SPY", win, "base_30m"))
        if "conf" in windows:
            jobs += [("champ", name, "conf", "base_100m") for name in VARIANTS]
        sims: dict = {}
        wcache: dict = {}
        for key in jobs:
            lvl, name, win, setup = key
            path = ck / f"sim_{lvl}_{name}_{win}_{setup}.pkl"
            got = LD._load_ckpt(path, fp)
            if got is None:
                step()
                t0, t1 = windows[win]
                if lvl == "spy":
                    bidx = prep["core_w"].index
                    bidx = bidx[bidx >= sched[0][0]]
                    w = tx.buy_and_hold_weights(bidx[(bidx >= t0) & (bidx <= t1)])
                else:
                    if (lvl, name) not in wcache:
                        wcache[(lvl, name)] = build_slot_weights(prep["core_w"] if lvl == "champ" else zero_core, sched,
                                                                 switches[name], SAT_WEIGHT if lvl == "champ" else 1.0, prep["adj"])
                    w = wcache[(lvl, name)]
                    w = w.loc[(w.index >= t0) & (w.index <= t1)]
                    w = w.loc[:, w.abs().sum() > 0]
                cfg = tx.AccountConfig(**SETUPS[setup])
                s = tx.simulate(w, prep["close"], prep["adj"], prep["fx"], cfg)
                got = LD._sim_summary(s, w, prep["adj"], bil_r, cfg.initial_krw)
                LD._atomic_pickle(path, {"fingerprint": fp, "payload": got})
                log(f"시뮬레이션 {key} 세후 {got['cagr_after']:.4f}")
            sims[key] = got
        result = analyze(prep, se, U, fit, grid, sims, a.smoke)
        rep = report(result)
        if a.smoke:
            cov = smoke_coverage(result, {"blocked": blocked_total})
            result["smoke_coverage"] = cov
            missing = [k for k, v in cov.items() if not v]
            if missing:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {missing}")
    except _Stop:
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
    if len(text.encode("utf-8")) > RESULTS_MAX_BYTES:
        text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    (out / "results.json").write_text(text, encoding="utf-8")
    (out / "REPORT.md").write_text(rep, encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
