"""검증 sat-exit-ladder-v1 (2026-10-15 사전 등록): 새틀라이트 매도 규칙 — 변동성·섹터별 손절/추적 익절 사다리.

사용자 요청(2026-10-15): 종목의 직전 변동성과 섹터 성격에 맞춘 손절 %·익절 %, 올라가기만 하는 추적 익절선
("$20 에 사서 $30 이 되면 n=10% 일 때 매도선 $27, $33 이 되면 선이 올라간다"), 선에 닿으면 m 만큼 팔고 나머지는
EMA·다이버전스 등 규칙으로. (1) 이 전략 vs SPY·현 챔피언, (2) 챔피언의 새틀라이트 매도 규칙으로 썼을 때 vs 현 챔피언.
같은 날 사용자 추가(결과 계산 전): 'V_E — 진입 다음 날부터 전체에 적용하는 규칙' 4종(가족 시도 수 4).

규칙 전체는 SPEC.md(한국어)에 고정되어 있다. 판정 기준을 바꾸려면 새 id 로 다시 등록한다.
진입은 S-SEED-000 그대로이고 매도만 바뀐다. 엔진(챔피언) 반영은 사용자 확인 뒤 별도 작업이다.
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
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "sat-exit-ladder-v1"
RULES_VERSION = "sat-exit-ladder-v1/2026-10-15b"   # b = 같은 날 결과 전 V_E 가족 추가
START = "2010-01-01"
SAT_WEIGHT = 0.15
COST = 8.0 / 10_000.0          # 편도 8bp(부분 매도 포함) — 사건 표본·세전 샤프용 USD 계산
BIL = "BIL"

# 구간(진입일 기준) — 2017-01 진입은 어느 쪽에도 넣지 않는다(선정·확인 사이 완충)
SEL_ENTRY = ("2010-01-01", "2016-07-31")
CONF_ENTRY = ("2017-07-01", "2024-01-31")
CONF_DAILY = ("2017-07-01", "2024-09-30")
POST_FROM = "2024-07-01"        # 2024-07 이후 진입은 보고만

# 분류
VOL_LOOKBACK = 63
W_HORIZON = 21                  # w = σ × sqrt(21)
DEFENSIVE = {"Consumer Staples", "Utilities", "Health Care", "Real Estate"}
CYCLICAL = {"Materials", "Energy", "Financials", "Industrials", "Consumer Discretionary"}
GROWTH = {"Information Technology", "Communication Services"}
VOL_BUCKETS = ("low", "mid", "high")
FAMILIES = ("defensive", "cyclical", "growth")
CELLS = tuple((v, f) for v in VOL_BUCKETS for f in FAMILIES)

# 격자
K_STOP = (1.0, 1.5, 2.0, 3.0)
K_TRAIL = (1.0, 1.5, 2.0, 3.0)
M_FRAC = (0.33, 0.5, 1.0)
REM_RULES = ("R0", "R1", "R2", "R3")
CELL_MIN_EVENTS = 60
CELL_MIN_GAIN = 0.01            # 셀 전용 폭은 평균 사건 로그수익이 1.0%p 이상 나을 때만

# 지표
EMA_SPAN = 21
RSI_N = 14
MACD = (12, 26, 9)
DIV_LO, DIV_HI = 40, 10         # [t−40, t−10]
RSI_GAP = 5.0

# 판정
N_BOOT = 1000
BLOCK_DAYS = 126
BOOT_SEED = 20261015
CI_PCT = (5.0, 95.0)
CI_LOW_FLOOR = -0.005
MDD_TOL_CHAMP = 0.02
SPY_MARGIN = 0.01
MDD_TOL_SPY = 0.03
MDD_TOL_SLEEVE_CHAMP = 0.10
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"

# 변형 — fitted: 격자 가족(시도 수 = 고유 조합 수), user: 사용자 예시(시도 1), entry: V_E 가족(시도 4)
JUDGED = ("V_U", "V_G", "V_C", "V_E1", "V_E2", "V_E3a", "V_E3b")
REPORT_ONLY = ("V_U_R0", "V_U_R2", "V_U_R3")
VARIANTS = ("V0",) + JUDGED + REPORT_ONLY
FAMILY_OF = {"V_U": "user", "V_G": "grid", "V_C": "grid", "V_E1": "entry", "V_E2": "entry",
             "V_E3a": "entry", "V_E3b": "entry"}
NAMES = {
    "V0": "현행(반기까지 보유, 중간 매도 없음)",
    "V_U": "사용자 예시: 손절 10%·추적 익절 10%·40% 매도·나머지 EMA21",
    "V_G": "격자 최적(전체 공통 σ 배수)",
    "V_C": "셀별(변동성×섹터) σ 배수 — 조건 미달 셀은 V_G",
    "V_E1": "진입 다음 날부터: 종가 < EMA21 이면 전량 매도",
    "V_E2": "진입 다음 날부터: 약세 다이버전스면 전량 매도",
    "V_E3a": "진입 다음 날부터: 진입 후 최고 종가 대비 20% 추적선",
    "V_E3b": "진입 다음 날부터: 진입 후 최고 종가 대비 3w(=2×1.5×w) 추적선",
    "V_U_R0": "사용자 예시 + 나머지 반기까지 보유(보고만)",
    "V_U_R2": "사용자 예시 + 나머지 다이버전스(보고만)",
    "V_U_R3": "사용자 예시 + 나머지 2배 추적선(보고만)",
}
LEVELS = ("champ", "sleeve")
WINDOWS = ("sel", "conf", "post")
SETUPS = {"base_30m": {}, "base_100m": {"initial_krw": 100_000_000}}


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def _sv():
    """satellite-value-v1 의 챔피언 구성·통계 함수를 그대로 쓴다(중복 구현하지 않음)."""
    spec = importlib.util.spec_from_file_location("satellite_value_v1_for_ladder",
                                                  PROJECT_ROOT / "research/jobs/satellite-value-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SV = _sv()


# =================================================================================================
# 분류·지표 (순수 함수)
# =================================================================================================

def sector_family(sector: Optional[str]) -> tuple[str, bool]:
    """(가족, 알 수 없음 여부). 모르는 섹터는 cyclical."""
    if sector in DEFENSIVE:
        return "defensive", False
    if sector in GROWTH:
        return "growth", False
    if sector in CYCLICAL:
        return "cyclical", False
    return "cyclical", True


def sigma_63(adj: pd.Series) -> float:
    """마지막 64개 값(= 63개 일별 로그수익)의 표준편차(ddof=1). 입력은 진입일 전날까지."""
    v = pd.to_numeric(adj, errors="coerce").dropna().to_numpy(dtype=float)
    if len(v) < VOL_LOOKBACK + 1 or np.any(v[-(VOL_LOOKBACK + 1):] <= 0):
        return float("nan")
    lr = np.diff(np.log(v[-(VOL_LOOKBACK + 1):]))
    return float(np.std(lr, ddof=1))


def vol_buckets(sigmas: dict) -> dict:
    """그날 추세 활성 후보 전체에서 σ 삼분위: σ ≤ 1/3 분위 → low, σ > 2/3 분위 → high, 나머지 mid. σ 없음 → mid."""
    vals = np.array([s for s in sigmas.values() if np.isfinite(s)], dtype=float)
    if len(vals) == 0:
        return {t: "mid" for t in sigmas}
    q1, q2 = np.quantile(vals, [1 / 3, 2 / 3])
    out = {}
    for t, s in sigmas.items():
        out[t] = "mid" if not np.isfinite(s) else ("low" if s <= q1 else ("high" if s > q2 else "mid"))
    return out


def ema(x: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


def rsi(x: np.ndarray, n: int = RSI_N) -> np.ndarray:
    s = pd.Series(x)
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn
    out = 100 - 100 / (1 + rs)
    out[(dn == 0) & (up > 0)] = 100.0
    return out.to_numpy()


def macd_hist(x: np.ndarray) -> np.ndarray:
    f, s, g = MACD
    m = ema(x, f) - ema(x, s)
    return m - ema(m, g)


def bearish_divergence(close: np.ndarray, rsi_v: np.ndarray, hist_v: np.ndarray) -> np.ndarray:
    """D[t] = close_t > max(close[t−40..t−10]) AND (RSI_t < RSI[j*] − 5 OR hist_t < hist[j*]),
    j* = 그 구간에서 최고 종가가 처음 나온 날. 값이 없으면 False. t 까지의 자료만 쓴다."""
    n = len(close)
    out = np.zeros(n, dtype=bool)
    w = DIV_LO - DIV_HI + 1
    if n <= DIV_LO:
        return out
    from numpy.lib.stride_tricks import sliding_window_view

    c = np.where(np.isfinite(close), close, -np.inf)
    win = sliding_window_view(c, w)           # win[i] = c[i .. i+w-1]
    t = np.arange(DIV_LO, n)
    rows = win[t - DIV_LO]                    # c[t−40 .. t−10]
    arg = rows.argmax(axis=1)
    j = t - DIV_LO + arg
    mx = rows[np.arange(len(t)), arg]
    with np.errstate(invalid="ignore"):
        higher = np.isfinite(close[t]) & np.isfinite(mx) & (close[t] > mx)
        r_div = np.isfinite(rsi_v[t]) & np.isfinite(rsi_v[j]) & (rsi_v[t] < rsi_v[j] - RSI_GAP)
        h_div = np.isfinite(hist_v[t]) & np.isfinite(hist_v[j]) & (hist_v[t] < hist_v[j])
    out[t] = higher & (r_div | h_div)
    return out


def indicator_flags(close: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(종가 < EMA21, 약세 다이버전스) — 둘 다 그날 종가까지의 자료만."""
    c = np.asarray(close, dtype=float)
    ok = np.isfinite(c)
    e = np.full(len(c), np.nan)
    r = np.full(len(c), np.nan)
    h = np.full(len(c), np.nan)
    if ok.any():
        first = int(np.argmax(ok))
        cc = pd.Series(c[first:]).ffill().to_numpy()
        e[first:] = ema(cc, EMA_SPAN)
        r[first:] = rsi(cc)
        h[first:] = macd_hist(cc)
    with np.errstate(invalid="ignore"):
        below = ok & np.isfinite(e) & (c < e)
    return below, bearish_divergence(c, r, h)


# =================================================================================================
# 매도 사다리 엔진 (사건 축으로 벡터화)
# =================================================================================================

@dataclass
class EngineOut:
    sold: np.ndarray        # 사건 × 일: 그날 종가에 판 '원래 보유 대비' 비율
    stop_hit: np.ndarray
    trail_hit: np.ndarray
    rem_hit: np.ndarray
    first_exit: np.ndarray  # 첫 매도 체결일(경로 위치), 없으면 −1
    line: np.ndarray        # 그날 종가 기준 추적선(활성일 때), 없으면 NaN


def run_engine(C: np.ndarray, L: np.ndarray, s, t, m, rule: str, below_ema: np.ndarray, div: np.ndarray,
               mode: str = "ladder") -> EngineOut:
    """C: 사건 × 경로일 조정 종가(0 = 진입일 종가, L−1 = 다음 리밸런싱일 종가, 이후는 패딩).
    신호는 k 일 종가로 판단하고 k+1 일 종가에 체결. 체결일이 L−1(리밸런싱일) 이상이면 무시(그날 어차피 정리).
    mode='ladder': rule ∈ R0..R3, s=손절 폭, t=추적 폭, m=추적선에서 팔 비율(원래 보유 대비).
    mode='entry' : rule ∈ E1(EMA21), E2(다이버전스), E3(진입 후 최고 종가 대비 s 추적선) — 전량 매도."""
    C = np.asarray(C, dtype=float)
    n, K = C.shape
    L = np.asarray(L, dtype=int)
    s = np.broadcast_to(np.asarray(s, dtype=float), (n,)).copy()
    t = np.broadcast_to(np.asarray(t, dtype=float), (n,)).copy()
    m = np.broadcast_to(np.asarray(m, dtype=float), (n,)).copy()
    P0 = C[:, 0]
    sold = np.zeros((n, K))
    line = np.full((n, K), np.nan)
    phase = np.zeros(n, dtype=int)          # 0 활성 전(전량), 1 추적 중(전량), 2 나머지 규칙, 3 끝
    peak = np.full(n, -np.inf)
    peak2 = np.full(n, -np.inf)
    p2start = np.full(n, K + 1)
    stop_hit = np.zeros(n, dtype=bool)
    trail_hit = np.zeros(n, dtype=bool)
    rem_hit = np.zeros(n, dtype=bool)
    first_exit = np.full(n, -1)
    if mode == "entry" and rule == "E3":
        peak = P0.copy()

    def _sell(mask, frac, k):
        idx = np.nonzero(mask)[0]
        if len(idx):
            sold[idx, k + 1] += frac[idx] if np.ndim(frac) else frac
            fe = first_exit[idx]
            first_exit[idx] = np.where(fe < 0, k + 1, fe)

    for k in range(1, K - 1):
        live = (k + 1) <= (L - 2)
        if not live.any():
            break
        c = C[:, k]
        if mode == "entry":
            p = live & (phase == 0)
            if rule == "E1":
                hit = p & below_ema[:, k]
            elif rule == "E2":
                hit = p & div[:, k]
            elif rule == "E3":
                peak = np.where(p, np.maximum(peak, c), peak)
                ln = peak * (1 - s)
                line[p, k] = ln[p]
                hit = p & (c < ln)
            else:
                raise ValueError(rule)
            _sell(hit, 1.0, k)
            rem_hit |= hit
            phase[hit] = 3
            continue
        # L1 손절 / L2 활성화
        p0 = live & (phase == 0)
        st = p0 & (c <= P0 * (1 - s))
        _sell(st, 1.0, k)
        stop_hit |= st
        phase[st] = 3
        act = p0 & ~st & (c >= P0 * (1 + t))
        phase[act] = 1
        peak[act] = c[act]
        # L2 추적선(선은 올라가기만)
        p1 = live & (phase == 1)
        peak = np.where(p1, np.maximum(peak, c), peak)
        ln = peak * (1 - t)
        line[p1, k] = ln[p1]
        tr = p1 & (c < ln)
        _sell(tr, m, k)
        trail_hit |= tr
        whole = tr & (m >= 1 - 1e-12)
        part = tr & ~whole
        phase[whole] = 3
        phase[part] = 2
        p2start[part] = k + 1               # 나머지 규칙은 L2 체결일 종가부터
        # L3 나머지 규칙
        p2 = live & (phase == 2) & (k >= p2start)
        if rule == "R1":
            hit = p2 & below_ema[:, k]
        elif rule == "R2":
            hit = p2 & div[:, k]
        elif rule == "R3":
            peak2 = np.where(p2, np.maximum(peak2, c), peak2)
            hit = p2 & (c < peak2 * (1 - 2 * t))
        elif rule in ("R0", None, "-"):
            hit = np.zeros(n, dtype=bool)
        else:
            raise ValueError(rule)
        _sell(hit, 1 - m, k)
        rem_hit |= hit
        phase[hit] = 3
    return EngineOut(sold, stop_hit, trail_hit, rem_hit, first_exit, line)


def event_log_values(C: np.ndarray, L: np.ndarray, sold: np.ndarray, bil_to_end: np.ndarray, cost: float = COST) -> np.ndarray:
    """사건별 순 로그수익: 진입 비용 + (판 몫 × 그날 가격 × 매도 비용 × 남은 기간 BIL) + (남은 몫 × 끝 가격 × 매도 비용)."""
    n = C.shape[0]
    P0 = C[:, 0]
    end = C[np.arange(n), L - 1]
    sold_val = (sold * (C / P0[:, None]) * bil_to_end).sum(axis=1) * (1 - cost)
    rest = (1 - sold.sum(axis=1)) * (end / P0) * (1 - cost)
    return np.log((1 - cost) * (sold_val + rest))


# =================================================================================================
# 사건 표본
# =================================================================================================

@dataclass
class Events:
    keys: list            # [(리밸런싱 번호, 종목)]
    C: np.ndarray
    L: np.ndarray
    below: np.ndarray
    div: np.ndarray
    bil_to_end: np.ndarray
    w: np.ndarray         # σ × sqrt(21)
    cell: list            # [(변동성, 가족)]
    window: np.ndarray    # 'sel' / 'conf' / 'post' / 'gap'
    picked: np.ndarray
    start_pos: np.ndarray  # 확장 달력 위치


def entry_window(d: pd.Timestamp) -> str:
    if pd.Timestamp(SEL_ENTRY[0]) <= d <= pd.Timestamp(SEL_ENTRY[1]):
        return "sel"
    if pd.Timestamp(CONF_ENTRY[0]) <= d <= pd.Timestamp(CONF_ENTRY[1]):
        return "conf"
    if d >= pd.Timestamp(POST_FROM):
        return "post"
    return "gap"


def build_events(prep: dict) -> Events:
    days = prep["ext_days"]
    P = prep["P_ext"]                      # DataFrame ext_days × 종목(조정 종가, 전방 채움)
    bil = prep["bil_ext"].to_numpy(dtype=float)
    sched = prep["schedule"]               # [{date, picks, cands: {t: (sigma, bucket, family, unknown)}}]
    flags = {t: indicator_flags(P[t].to_numpy(dtype=float)) for t in P.columns}
    last = len(days) - 1
    pos = {d: i for i, d in enumerate(days)}
    rows = []
    for j, r in enumerate(sched):
        d = pd.Timestamp(r["date"])
        i0 = pos[d]
        i1 = pos[pd.Timestamp(sched[j + 1]["date"])] if j + 1 < len(sched) else last
        for tkr, c in sorted(r["cands"].items()):
            rows.append((j, tkr, i0, i1, c, tkr in r["picks"], entry_window(d)))
    K = max((r_[3] - r_[2] + 1 for r_ in rows), default=2)
    n = len(rows)
    C = np.zeros((n, K))
    below = np.zeros((n, K), dtype=bool)
    div = np.zeros((n, K), dtype=bool)
    btoe = np.ones((n, K))
    L = np.zeros(n, dtype=int)
    w = np.zeros(n)
    cell, keys, win, picked, sp = [], [], [], [], []
    for e, (j, tkr, i0, i1, c, pk, wn) in enumerate(rows):
        ln = i1 - i0 + 1
        px = P[tkr].to_numpy(dtype=float)[i0:i1 + 1]
        C[e, :ln] = px
        C[e, ln:] = px[-1]
        b, dv = flags[tkr]
        below[e, :ln] = b[i0:i1 + 1]
        div[e, :ln] = dv[i0:i1 + 1]
        btoe[e, :ln] = bil[i1] / bil[i0:i1 + 1]
        L[e] = ln
        sigma, bucket, fam, _unk = c
        w[e] = sigma * math.sqrt(W_HORIZON) if np.isfinite(sigma) else np.nan
        cell.append((bucket, fam))
        keys.append((j, tkr))
        win.append(wn)
        picked.append(pk)
        sp.append(i0)
    # σ 가 없는 사건(드묾)은 그날 후보 중앙값 w 로 — 개수는 보고
    sp_arr = np.array(sp, dtype=int)
    n_missing = int(np.isnan(w).sum()) if n else 0
    for e in np.nonzero(np.isnan(w))[0] if n else []:
        same = w[(sp_arr == sp_arr[e]) & ~np.isnan(w)]
        w[e] = float(np.median(same)) if len(same) else float(np.nanmedian(w)) if np.isfinite(w).any() else 0.05
    ev = Events(keys, C, L, below, div, btoe, w, cell, np.array(win), np.array(picked, dtype=bool), sp_arr)
    ev.n_sigma_missing = n_missing
    return ev


# =================================================================================================
# 변형 정의
# =================================================================================================

def grid_combos() -> list[tuple]:
    """고유 조합. m=1.0 이면 나머지 규칙이 무의미하므로 R='-' 하나로 합친다."""
    out = []
    for ks in K_STOP:
        for kt in K_TRAIL:
            for m in M_FRAC:
                for r in (REM_RULES if m < 1.0 else ("-",)):
                    out.append((ks, kt, m, r))
    return out


N_GRID = len(grid_combos())
N_TRIALS = {"user": 1, "grid": N_GRID, "entry": 4}


def variant_engine(name: str, ev: Events, fit: Optional[dict], idx: Optional[np.ndarray] = None) -> EngineOut:
    """변형을 사건(부분집합 idx)에 적용."""
    idx = np.arange(len(ev.L)) if idx is None else idx
    C, L, b, dv, w = ev.C[idx], ev.L[idx], ev.below[idx], ev.div[idx], ev.w[idx]
    if name == "V0":
        n, K = C.shape
        z = np.zeros(n, dtype=bool)
        return EngineOut(np.zeros((n, K)), z, z.copy(), z.copy(), np.full(n, -1), np.full((n, K), np.nan))
    if name.startswith("V_U"):
        rule = {"V_U": "R1", "V_U_R0": "R0", "V_U_R2": "R2", "V_U_R3": "R3"}[name]
        return run_engine(C, L, 0.10, 0.10, 0.40, rule, b, dv)
    if name == "V_E1":
        return run_engine(C, L, 0, 0, 1, "E1", b, dv, mode="entry")
    if name == "V_E2":
        return run_engine(C, L, 0, 0, 1, "E2", b, dv, mode="entry")
    if name == "V_E3a":
        return run_engine(C, L, 0.20, 0, 1, "E3", b, dv, mode="entry")
    if name == "V_E3b":
        return run_engine(C, L, 2 * 1.5 * w, 0, 1, "E3", b, dv, mode="entry")
    if name == "V_G":
        ks, kt, m, r = fit["V_G"]
        return run_engine(C, L, ks * w, kt * w, m, r, b, dv)
    if name == "V_C":
        ks, kt, m, r = fit["V_G"]
        cells = [ev.cell[i] for i in idx]
        kss = np.array([fit["V_C"][f"{c[0]}|{c[1]}"]["k_stop"] for c in cells])
        kts = np.array([fit["V_C"][f"{c[0]}|{c[1]}"]["k_trail"] for c in cells])
        return run_engine(C, L, kss * w, kts * w, m, r, b, dv)
    raise ValueError(name)


def fit_cells(logv: np.ndarray, combos: list, cells: list, vg_index: int) -> dict:
    """V_C: V_G 의 m·R 고정, 셀마다 (k_stop, k_trail) 16개 중 최선. 셀 사건 ≥ 60 이고 V_G 폭보다 평균 ≥ 1.0%p 나을 때만 바꾼다.
    logv: 조합 × 선정 사건 순 로그수익, cells: 선정 사건별 셀."""
    ks_g, kt_g, m_g, r_g = combos[vg_index]
    cand = [i for i, c in enumerate(combos) if c[2] == m_g and c[3] == r_g]
    out = {}
    cells_arr = np.array([f"{a}|{b}" for a, b in cells]) if len(cells) else np.array([], dtype=str)
    for v, f in CELLS:
        key = f"{v}|{f}"
        mask = cells_arr == key
        n = int(mask.sum())
        base = float(logv[vg_index, mask].mean()) if n else float("nan")
        best_i, best = vg_index, base
        if n:
            for i in cand:
                val = float(logv[i, mask].mean())
                if val > best + 1e-15:
                    best_i, best = i, val
        deviate = bool(n >= CELL_MIN_EVENTS and best_i != vg_index and best - base >= CELL_MIN_GAIN)
        use = combos[best_i] if deviate else combos[vg_index]
        out[key] = {"n_sel_events": n, "k_stop": use[0], "k_trail": use[1], "deviates": deviate,
                    "vg_mean": base, "best_k_stop": combos[best_i][0], "best_k_trail": combos[best_i][1],
                    "best_mean": best, "gain_vs_vg": (best - base) if n else None}
    return out


# =================================================================================================
# 포트폴리오 목표 비중
# =================================================================================================

def sales_for_picks(ev: Events, eng: EngineOut, idx: np.ndarray, ext_days: pd.DatetimeIndex) -> dict:
    """{(리밸런싱 번호, 종목): [(체결일, 원래 대비 비율)]}"""
    out = {}
    for row, e in enumerate(idx):
        ks = np.nonzero(eng.sold[row] > 0)[0]
        if len(ks):
            out[ev.keys[e]] = [(ext_days[ev.start_pos[e] + k], float(eng.sold[row, k])) for k in ks]
    return out


def build_target_weights(core_w: pd.DataFrame, schedule: list, sales: dict, sw: float, adj: pd.DataFrame) -> pd.DataFrame:
    """코어 × (1 − sw) + 새틀라이트 × sw 의 일별 목표 비중.
    - 리밸런싱일·코어 신호 변경일: 기본 목표(종목 sw/n × 남은 비율, BIL = sw/n × 판 비율) — 매도가 없으면 tx.champion_weights 와 같다.
    - 매도만 있는 날: 그날까지 표류한 비중을 그대로 두고 판 몫만 BIL 로 옮긴다(다른 종목은 매매하지 않게).
    - 그 밖의 날: 전날 목표 그대로(tax_fx 는 목표가 바뀌는 날에만 매매)."""
    sched = sorted(((pd.Timestamp(d), list(p)) for d, p in schedule), key=lambda x: x[0])
    idx = core_w.index[core_w.index >= sched[0][0]]
    sat_cols = sorted({t for _, p in sched for t in p})
    cols = list(dict.fromkeys(list(core_w.columns) + sat_cols + ([BIL] if sales else [])))
    base = core_w.reindex(index=idx, columns=cols).fillna(0.0) * (1 - sw)
    starts = [d for d, _ in sched]
    sale_days: dict = {}
    for j, (d, picks) in enumerate(sched):
        span = (idx >= d) & ((idx < sched[j + 1][0]) if j + 1 < len(sched) else True)
        if not picks:
            continue
        per = sw / len(picks)
        for tkr in picks:
            rem = pd.Series(1.0, index=idx[span])
            for dd, fr in sales.get((j, tkr), []):
                rem.loc[rem.index >= dd] -= fr
                sale_days.setdefault(pd.Timestamp(dd), []).append((tkr, fr, j))
            rem = rem.clip(lower=0.0)
            base.loc[span, tkr] = base.loc[span, tkr] + per * rem.to_numpy()
            if sales:
                base.loc[span, BIL] = base.loc[span, BIL] + per * (1 - rem.to_numpy())
    if not sales:
        return base
    core_chg = core_w.reindex(idx).fillna(0.0).diff().abs().sum(axis=1) > 1e-12
    reset = set(idx[core_chg.to_numpy()]) | set(starts) | {idx[0]}
    a = adj.reindex(index=idx, columns=cols).ffill()
    tr = a.pct_change(fill_method=None).fillna(0.0).to_numpy()
    B = base.to_numpy()
    out = np.zeros_like(B)
    ci = {c: i for i, c in enumerate(cols)}
    remaining = {}  # (j, tkr) -> 남은 비율(원래 대비)
    drift = None
    row = None
    for i, d in enumerate(idx):
        if drift is not None:
            g = drift * (1 + tr[i])
            port = g.sum() + (1 - drift.sum())
            drift = g / port if port > 0 else drift
        todays = sale_days.get(d, [])
        for tkr, fr, j in todays:
            remaining.setdefault((j, tkr), 1.0)
        if d in reset or row is None:
            row = B[i].copy()
            for tkr, fr, j in todays:
                remaining[(j, tkr)] -= fr
        elif todays:
            row = drift.copy()
            for tkr, fr, j in todays:
                before = remaining[(j, tkr)]
                f = min(1.0, fr / before) if before > 1e-12 else 1.0
                amt = row[ci[tkr]] * f
                row[ci[tkr]] -= amt
                row[ci[BIL]] += amt
                remaining[(j, tkr)] = before - fr
        out[i] = row
        if d in reset or todays or drift is None:
            drift = row.copy()
    return pd.DataFrame(out, index=idx, columns=cols)


def pretax_returns(weights: pd.DataFrame, adj: pd.DataFrame, cost: float = COST) -> pd.Series:
    """세전 USD 일별 수익: tax_fx 세전 기준선과 같은 표류 + 목표가 바뀌는 날 회전율 × 8bp."""
    days = weights.index
    W = weights.to_numpy()
    a = adj.reindex(index=days, columns=weights.columns).ffill()
    tr = a.pct_change(fill_method=None).fillna(0.0).to_numpy()
    chg = np.r_[True, np.abs(np.diff(W, axis=0)).sum(axis=1) > 1e-9]
    drift = np.zeros(W.shape[1])
    v, vals = 1.0, []
    for i in range(len(days)):
        if i > 0:
            g = drift * (1 + tr[i])
            port = g.sum() + (1 - drift.sum())
            v *= port
            drift = g / port if port > 0 else drift
        if chg[i]:
            turnover = float(np.abs(W[i] - drift).sum())
            v *= 1 - cost * turnover
            drift = W[i].copy()
        vals.append(v)
    s = pd.Series(vals, index=days)
    return s.pct_change().iloc[1:]


# =================================================================================================
# 판정 (순수 함수)
# =================================================================================================

def decide_primary(diff_conf: float, sharpe_v: float, sharpe_0: float, mdd_v: float, mdd_0: float, ci_low: float,
                   *, diff_sel: Optional[float] = None, require_sel: bool = False, noop: Optional[str] = None,
                   observed_ir: Optional[float] = None, power: Optional[dict] = None) -> str:
    """사전 등록 판정. 차이는 소수(0.01 = 1%p). MDD 는 음수(−0.22)."""
    if noop:
        return NOT_EVALUABLE
    vals = [diff_conf, sharpe_v, sharpe_0, mdd_v, mdd_0, ci_low] + ([diff_sel] if require_sel else [])
    if any(v is None or not math.isfinite(float(v)) for v in vals):
        return NOT_EVALUABLE
    ok = (diff_conf > 0 and sharpe_v > sharpe_0 and mdd_v >= mdd_0 - MDD_TOL_CHAMP and ci_low > CI_LOW_FLOOR
          and (not require_sel or diff_sel > 0))
    if ok:
        return PASS
    return rp.classify_fail(observed_ir, power) if power else FAIL


def beats_spy(ann_v: float, mdd_v: float, ann_spy: float, mdd_spy: float) -> bool:
    return bool(ann_v >= ann_spy + SPY_MARGIN and mdd_v >= mdd_spy - MDD_TOL_SPY)


def beats_champion(ann_v: float, mdd_v: float, ann_ch: float, mdd_ch: float) -> bool:
    return bool(ann_v > ann_ch and mdd_v >= mdd_ch - MDD_TOL_SLEEVE_CHAMP)


def sharpe_excess(r: pd.Series, bil_r: pd.Series) -> float:
    x = (r - bil_r.reindex(r.index).fillna(0.0)).to_numpy()
    sd = float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
    return float(np.mean(x) / sd * math.sqrt(252)) if sd > 0 else float("nan")


def block_bootstrap_diff(ra, rb, ppy):
    return SV.block_bootstrap_diff(ra, rb, ppy, n_boot=N_BOOT, block=BLOCK_DAYS, seed=BOOT_SEED)


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
            obj = pickle.load(f)  # 이 스크립트가 쓴 파일만 읽는다
    except Exception:  # noqa: BLE001
        return None
    return obj["payload"] if obj.get("fingerprint") == fp else None


# =================================================================================================
# 입력
# =================================================================================================

def replicate_schedule(data, sectors: dict) -> list[dict]:
    """S-SEED-000 을 run_variant 와 같은 순서로 재현하면서 그날의 추세 활성 후보 전체(점수가 나온 종목)와 σ·셀을 남긴다."""
    from core import satellite_lab as sl

    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    signal = sl.load_signal(code)
    params = dict(spec["signal"]["params_grid"][0])
    out = []
    for d in sl.rebalance_dates(data.trading_days, spec["portfolio"]["hold_months"]):
        cutoff = sl._prev_day(data.trading_days, d)
        if cutoff is None:
            continue
        members = data.pool(spec["pool"]["type"], d)
        prices = sl._signal_prices(data, members, cutoff, d)
        eligible = {t for t in prices if t in data.closes.columns and pd.notna(data.closes.at[d, t])}
        scores = sl._call_signal(signal, spec, data, {t: prices[t] for t in eligible}, cutoff, params)
        picks = sl.pick_top(scores, spec["portfolio"]["top_k"], eligible)
        active = sorted(t for t, v in (scores or {}).items() if t in eligible and v is not None and math.isfinite(float(v)))
        sig = {}
        for t in active:
            df = data.ohlcv[t]
            col = "Adj Close" if "Adj Close" in df.columns and df["Adj Close"].notna().any() else "Close"
            sig[t] = sigma_63(df.loc[df.index <= cutoff, col])
        buckets = vol_buckets(sig)
        cands = {}
        for t in active:
            fam, unk = sector_family(sectors.get(t))
            cands[t] = (sig[t], buckets[t], fam, unk)
        out.append({"date": d, "picks": picks, "cands": cands})
    return out


def _prepare(data, sectors: dict, core_w: pd.DataFrame, frames: dict, spy_frame: pd.DataFrame,
             bil_frame: pd.DataFrame, fx: pd.Series, meta: dict) -> dict:
    schedule = replicate_schedule(data, sectors)
    cand = sorted({t for r in schedule for t in r["cands"]})
    end = data.trading_days[-1]
    spy_n = SV._norm(spy_frame)
    ext = spy_n.index.union(data.trading_days)
    ext = ext[ext <= end]
    adj_cols = {}
    for t in cand:
        df = SV._norm(data.ohlcv[t])
        col = "Adj Close" if "Adj Close" in df.columns and df["Adj Close"].notna().any() else "Close"
        adj_cols[t] = pd.to_numeric(df[col], errors="coerce")
    P_ext = pd.DataFrame(adj_cols).reindex(ext).ffill()
    bil_n = SV._norm(bil_frame)
    bil_col = "Adj Close" if "Adj Close" in bil_n.columns and bil_n["Adj Close"].notna().any() else "Close"
    bil_ext = pd.to_numeric(bil_n[bil_col], errors="coerce").reindex(ext).ffill().bfill()
    picks = sorted({t for r in schedule for t in r["picks"]})
    pf = {t: frames.get(t) for t in frames}
    pf.update({t: data.ohlcv.get(t) for t in picks})
    pf["SPY"] = spy_frame
    pf[BIL] = bil_frame
    close, adj = SV._panel(pf)
    unknown = sorted({t for r in schedule for t, c in r["cands"].items() if c[3]})
    return {"schedule": schedule, "ext_days": ext, "P_ext": P_ext, "bil_ext": bil_ext, "core_w": core_w,
            "close": close, "adj": adj, "fx": fx, "trading_days": data.trading_days,
            "meta": {**meta, "unknown_sector_tickers": unknown, "n_candidate_tickers": len(cand)}}


def _real_prep(log) -> dict:
    from core import champion_strategy as cs
    from core import hypothesis_engine as he
    from core import satellite_lab as sl
    from core import screener
    from core.market_data import get_multiple_price_history

    log("코어 백테스트(일별 목표 비중)")
    core_w = cs.run_core_backtest(START)["weights"]
    pool = SV._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", pool_provider=pool, log=log)
    others = sorted(set(core_w.columns) | {"SPY", BIL})
    hist = get_multiple_price_history(others, start="2007-06-01", end=None, interval="1d")
    frames = {t: hist.get(t) for t in others}
    uni = screener.get_universe(use_cache=True)
    sectors = {he.price_symbol(str(s)): str(sec) for s, sec in zip(uni["Symbol"], uni["Sector"])}
    fx = tx.usdkrw_series()
    meta = {"live_satellite_weight": cs.SATELLITE_WEIGHT, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
            "judge_version": sl.JUDGE_VERSION, "pool_cache_tag": sl.POOL_CACHE_TAG,
            "core_universe": list(core_w.columns), "sector_source": "core.screener.get_universe (현재 S&P500 분류, 시점 기준 아님)"}
    return _prepare(data, sectors, core_w, frames, frames["SPY"], frames[BIL], fx, meta)


def _smoke_prep(log) -> dict:
    """합성 데이터(네트워크 없음). 실데이터가 아니다."""
    from core import satellite_lab as sl

    end = "2026-06-30"
    pp, poolp = sl.synthetic_providers(n_tickers=50, start="2008-01-01", end=end, seed=11)
    pool = SV._pool_wrapper(poolp, date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", end=end, pool_provider=pool, price_provider=pp)
    full = pd.bdate_range("2008-01-01", end)
    rng = np.random.default_rng(5)
    idx = data.trading_days[data.trading_days >= pd.Timestamp(START)]
    frames = {}
    for t in ("C1", "C2"):
        c = 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, len(full))))
        frames[t] = pd.DataFrame({"Close": c, "Adj Close": c * np.exp(np.linspace(0, 0.3, len(full)))}, index=full)
    bil_close = np.full(len(full), 91.5)
    frames[BIL] = pd.DataFrame({"Close": bil_close, "Adj Close": bil_close * np.exp(np.linspace(0, 0.18, len(full)))}, index=full)
    core_w = pd.DataFrame(0.0, index=idx, columns=["C1", "C2"])
    core_w.loc[core_w.index.month % 2 == 0, "C1"] = 1.0
    core_w.loc[core_w.index.month % 2 == 1, "C2"] = 1.0
    core_w.loc[core_w.index.month == 3, "C2"] = 0.5
    secs = sorted(DEFENSIVE | CYCLICAL | GROWTH) + [None]
    sectors = {f"T{i:02d}": secs[i % len(secs)] for i in range(50)}
    sectors = {k: v for k, v in sectors.items() if v is not None}   # 일부는 모르는 섹터 → cyclical
    fx = pd.Series(1100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(full)))), index=full)
    spy = pp("SPY", "2008-01-01", end)
    return _prepare(data, sectors, core_w, frames, spy, frames[BIL], fx, {"synthetic": True})


# =================================================================================================
# 분석
# =================================================================================================

def window_bounds(index: pd.DatetimeIndex, schedule: list) -> dict:
    """일별 평가 구간(각각 새 계좌로 시작): sel = 첫 선정일 ~ 2017-01 리밸런싱일 전날, conf = 2017-07 리밸런싱일 ~ 2024-09-30,
    post = 2024-07 리밸런싱일 ~ 끝(보고만)."""
    dates = [pd.Timestamp(r["date"]) for r in schedule]

    def first_on_or_after(x):
        c = [d for d in dates if d >= pd.Timestamp(x)]
        return c[0] if c else None

    out = {}
    s0 = first_on_or_after(START)
    s1 = first_on_or_after("2017-01-01")
    if s0 is not None and s1 is not None:
        # 2017-01 리밸런싱일 전날까지(그날 새 종목 매수가 선정 구간에 섞이지 않게)
        out["sel"] = (s0, index[index < s1][-1])
    c0 = first_on_or_after(CONF_DAILY[0])
    if c0 is not None:
        c1 = index[index <= pd.Timestamp(CONF_DAILY[1])][-1]
        if c1 > c0:
            out["conf"] = (c0, c1)
    p0 = first_on_or_after(POST_FROM)
    if p0 is not None and index[-1] > p0:
        out["post"] = (p0, index[-1])
    return out


def _sim_summary(s: dict, w: pd.DataFrame, adj: pd.DataFrame, bil_r: pd.Series, initial: float) -> dict:
    r_pre = pretax_returns(w, adj)
    vals = s["values_krw"]
    years = (vals.index[-1] - vals.index[0]).days / 365.25
    return {"cagr_after": s["cagr_after"], "cagr_pre": s["cagr_pre"], "mdd_after": s["mdd_after"],
            "final_krw": s["final_krw"], "totals": s["totals"], "values": vals,
            "sharpe_pretax_excess": sharpe_excess(r_pre, bil_r), "years": years, "initial": initial}


def pair_stats(a: dict, b: dict, with_boot: bool = True) -> dict:
    va, vb, initial = a["values"], b["values"], a["initial"]
    t1 = va.index[-1]
    ra, rb = SV.window_returns(va, initial, t1), SV.window_returns(vb, initial, t1)
    years = (t1 - va.index[0]).days / 365.25
    ppy = len(ra) / years if years > 0 else 252.0
    d = (ra - rb).to_numpy()
    sd = float(np.std(d, ddof=1)) if len(d) > 1 else float("nan")
    out = {"diff": a["cagr_after"] - b["cagr_after"],
           "daily_diff_ir": float(np.mean(d) / sd * math.sqrt(ppy)) if sd and math.isfinite(sd) and sd > 0 else float("nan"),
           "noop_reason": rp.noop_guard(d), "years": years}
    mid = va.index[0] + (t1 - va.index[0]) / 2
    h1 = va.index[va.index <= mid][-1]
    out["h1_diff"] = SV.seg_ann(va, initial, None, h1) - SV.seg_ann(vb, initial, None, h1)
    out["h2_diff"] = SV.seg_ann(va, initial, h1, t1) - SV.seg_ann(vb, initial, h1, t1)
    if with_boot and len(d) > 2:
        boot = block_bootstrap_diff(ra.to_numpy(), rb.to_numpy(), ppy)
        lo, hi = np.percentile(boot, CI_PCT)
        out.update({"boot_ci90_low": float(lo), "boot_ci90_high": float(hi), "boot_share_positive": float(np.mean(boot > 0))})
    return out


def event_stats(name: str, ev: Events, eng: EngineOut, logv: np.ndarray, logv0: np.ndarray, idx: np.ndarray) -> dict:
    """한 무리 사건의 매도 통계."""
    n = len(idx)
    if n == 0:
        return {"n": 0}
    C = ev.C[idx]
    L = ev.L[idx]
    mfe = np.array([C[i, :L[i]].max() / C[i, 0] - 1 for i in range(n)])
    mae = np.array([C[i, :L[i]].min() / C[i, 0] - 1 for i in range(n)])
    exited = eng.first_exit >= 0
    return {"n": int(n), "stop_hit_rate": float(eng.stop_hit.mean()), "trail_hit_rate": float(eng.trail_hit.mean()),
            "rem_or_rule_hit_rate": float(eng.rem_hit.mean()), "any_exit_rate": float(exited.mean()),
            "mean_days_to_first_exit": float(eng.first_exit[exited].mean()) if exited.any() else None,
            "mean_log_ret": float(logv.mean()), "mean_log_ret_v0": float(logv0.mean()),
            "mean_foregone_vs_v0_exited": float((logv0[exited] - logv[exited]).mean()) if exited.any() else None,
            "mean_mfe": float(mfe.mean()), "mean_mae": float(mae.mean())}


def analyze(prep: dict, ev: Events, fit: dict, grid_logv: np.ndarray, sims: dict, smoke: bool) -> tuple[dict, str]:
    combos = grid_combos()
    sel_idx = np.nonzero(ev.window == "sel")[0]
    conf_idx = np.nonzero(ev.window == "conf")[0]
    # 셀별 표
    cell_rows = []
    engines = {v: variant_engine(v, ev, fit) for v in VARIANTS}
    logvs = {v: event_log_values(ev.C, ev.L, engines[v].sold, ev.bil_to_end) for v in VARIANTS}

    def sub(eng: EngineOut, ix):
        return EngineOut(eng.sold[ix], eng.stop_hit[ix], eng.trail_hit[ix], eng.rem_hit[ix], eng.first_exit[ix], eng.line[ix])

    cell_of = np.array([f"{a}|{b}" for a, b in ev.cell])
    for v, f in CELLS:
        key = f"{v}|{f}"
        sel_c = sel_idx[cell_of[sel_idx] == key]
        conf_c = conf_idx[cell_of[conf_idx] == key]
        med_w = float(np.median(ev.w[sel_c])) if len(sel_c) else (float(np.median(ev.w[conf_c])) if len(conf_c) else float("nan"))
        fc = fit["V_C"][key]
        row = {"cell": key, "n_sel": int(len(sel_c)), "n_conf": int(len(conf_c)), "median_w": med_w,
               "V_C": {**fc, "stop_pct": fc["k_stop"] * med_w, "trail_pct": fc["k_trail"] * med_w,
                       "m": fit["V_G"][2], "rule": fit["V_G"][3]},
               "V_G_pct": {"stop_pct": fit["V_G"][0] * med_w, "trail_pct": fit["V_G"][1] * med_w},
               "V_E3b_line_pct": 3.0 * med_w, "stats": {}}
        for name in VARIANTS:
            if name == "V0":
                continue
            row["stats"][name] = {
                "sel": event_stats(name, ev, sub(engines[name], sel_c), logvs[name][sel_c], logvs["V0"][sel_c], sel_c),
                "conf": event_stats(name, ev, sub(engines[name], conf_c), logvs[name][conf_c], logvs["V0"][conf_c], conf_c)}
        cell_rows.append(row)
    overall = {name: {w_: event_stats(name, ev, sub(engines[name], ix), logvs[name][ix], logvs["V0"][ix], ix)
                      for w_, ix in (("sel", sel_idx), ("conf", conf_idx))} for name in VARIANTS if name != "V0"}
    picked_overall = {name: {w_: event_stats(name, ev, sub(engines[name], ix), logvs[name][ix], logvs["V0"][ix], ix)
                             for w_, ix in (("sel", sel_idx[ev.picked[sel_idx]]), ("conf", conf_idx[ev.picked[conf_idx]]))}
                      for name in VARIANTS if name != "V0"}
    # 포트폴리오 판정
    powers = {fam: rp.power_report(sims[("champ", "V0", "conf", "base_30m")]["years"], n) for fam, n in N_TRIALS.items()}
    pairs, verdicts, raw = {}, {}, {}
    for name in VARIANTS[1:]:
        p = {}
        for win in WINDOWS:
            k0 = ("champ", "V0", win, "base_30m")
            kv = ("champ", name, win, "base_30m")
            if k0 in sims and kv in sims:
                p[win] = pair_stats(sims[kv], sims[k0], with_boot=(win == "conf"))
        if ("champ", name, "conf", "base_100m") in sims:
            p["conf_100m"] = pair_stats(sims[("champ", name, "conf", "base_100m")], sims[("champ", "V0", "conf", "base_100m")], with_boot=False)
        pairs[name] = p
        if name in JUDGED and "conf" in p:
            c = p["conf"]
            fam = FAMILY_OF[name]
            sv, s0 = sims[("champ", name, "conf", "base_30m")], sims[("champ", "V0", "conf", "base_30m")]
            v = decide_primary(c["diff"], sv["sharpe_pretax_excess"], s0["sharpe_pretax_excess"], sv["mdd_after"], s0["mdd_after"],
                               c.get("boot_ci90_low", float("nan")), diff_sel=p.get("sel", {}).get("diff"),
                               require_sel=fam in ("user", "entry"), noop=c["noop_reason"],
                               observed_ir=c["daily_diff_ir"], power=powers[fam])
            raw[name] = v
            verdicts[name] = f"SMOKE_ONLY({v})" if smoke else v
    secondary = {}
    for name in ("V0",) + JUDGED:
        k = ("sleeve", name, "conf", "base_30m")
        if k not in sims:
            continue
        s, spy, ch = sims[k], sims[("spy", "SPY", "conf", "base_30m")], sims[("champ", "V0", "conf", "base_30m")]
        bs = beats_spy(s["cagr_after"], s["mdd_after"], spy["cagr_after"], spy["mdd_after"])
        bc = beats_champion(s["cagr_after"], s["mdd_after"], ch["cagr_after"], ch["mdd_after"])
        secondary[name] = {"BEATS_SPY": bs, "BEATS_CHAMPION": bc,
                           "label": f"SPY:{'YES' if bs else 'NO'} / CHAMP:{'YES' if bc else 'NO'}"}
    metrics = {}
    for (lvl, name, win, setup), s in sims.items():
        metrics.setdefault(setup, {}).setdefault(win, {}).setdefault(lvl, {})[name] = {
            k: s[k] for k in ("cagr_after", "cagr_pre", "mdd_after", "final_krw", "sharpe_pretax_excess", "years", "totals")}
    wb = {k: [str(a.date()), str(b.date())] for k, (a, b) in prep["windows"].items()}
    top = np.argsort(-grid_logv.mean(axis=1))[:10]
    n_unknown = sum(1 for r in prep["schedule"] for c in r["cands"].values() if c[3])
    n_cands = sum(len(r["cands"]) for r in prep["schedule"])
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windows_daily": wb, "entry_windows": {"sel": list(SEL_ENTRY), "conf": list(CONF_ENTRY), "post_from": POST_FROM},
        "n_events": {"sel": int(len(sel_idx)), "conf": int(len(conf_idx)), "all": int(len(ev.L))},
        "unknown_sector_events": n_unknown, "candidate_events_total": n_cands,
        "sigma_missing_events": int(getattr(ev, "n_sigma_missing", 0)),
        "n_unique_grid_combos": N_GRID, "fit": {"V_G": list(fit["V_G"]), "V_G_mean_sel_log_ret": fit["V_G_mean"], "V_C": fit["V_C"]},
        "grid_top10": [{"combo": list(combos[i]), "mean_sel_log_ret": float(grid_logv[i].mean())} for i in top],
        "cells": cell_rows, "event_overall": overall, "event_picked": picked_overall,
        "metrics": metrics, "pairs": pairs, "power": powers,
        "power_lines": {k: rp.power_line(v) for k, v in powers.items()},
        "verdicts": verdicts, "verdicts_raw": raw, "secondary_verdicts": secondary,
        "variants": NAMES, "inputs_meta": prep.get("meta", {}),
        "rules": {"cost_bp_per_side": COST * 1e4, "n_boot": N_BOOT, "block_days": BLOCK_DAYS, "boot_seed": BOOT_SEED,
                  "ci_low_floor": CI_LOW_FLOOR, "mdd_tol_champion": MDD_TOL_CHAMP, "spy_margin": SPY_MARGIN,
                  "mdd_tol_spy": MDD_TOL_SPY, "mdd_tol_sleeve_vs_champion": MDD_TOL_SLEEVE_CHAMP,
                  "cell_min_events": CELL_MIN_EVENTS, "cell_min_gain": CELL_MIN_GAIN, "sat_weight": SAT_WEIGHT},
    }
    return result, report(result)


# =================================================================================================
# 보고서
# =================================================================================================

def _pct(x, signed=False, nd=1) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _pp(x) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x * 100:+.2f}%p"


def report(r: dict) -> str:
    vg = r["fit"]["V_G"]
    rule_ko = {"R0": "반기까지 보유", "R1": "EMA21 아래로 내려가면", "R2": "약세 다이버전스", "R3": "2배 폭 추적선", "-": "(전량 매도라 없음)"}
    L = [f"# 새틀라이트 매도 사다리 — 변동성·섹터별 손절/추적 익절{' (스모크 — 합성 데이터, 실측 아님)' if r['smoke'] else ''}", "",
         "진입은 지금과 똑같다(S-SEED-000: champion40 후보 중 추세 활성 + 12개월 모멘텀 상위 3, 1·7월). 바뀌는 것은 '언제 파는가'뿐이다.",
         "판 돈은 다음 리밸런싱까지 BIL(초단기 국채)에 둔다. 신호는 그날 종가로 보고 다음 날 종가에 판다. 매매 비용 편도 8bp.", "",
         "## 판정(주: 챔피언 = 코어 85% + 새틀라이트 15%, 세후 원화 3,000만 원, 확인 구간)", "",
         "| 변형 | 판정 | 세후 연수익 차이 | 앞/뒤 절반 | 부트스트랩 90% | 세전 샤프(본/현행) | 원화 MDD(본/현행) | 선정 구간 차이 |",
         "|---|---|---|---|---|---|---|---|"]
    m30 = r["metrics"].get("base_30m", {})
    conf = m30.get("conf", {})
    for name in JUDGED + REPORT_ONLY:
        p = r["pairs"].get(name, {})
        c = p.get("conf", {})
        cv = conf.get("champ", {}).get(name, {})
        c0 = conf.get("champ", {}).get("V0", {})
        L.append(f"| {name} {NAMES[name]} | **{r['verdicts'].get(name, '보고만')}** | {_pp(c.get('diff'))} | "
                 f"{_pp(c.get('h1_diff'))} / {_pp(c.get('h2_diff'))} | {_pp(c.get('boot_ci90_low'))} ~ {_pp(c.get('boot_ci90_high'))} | "
                 f"{cv.get('sharpe_pretax_excess', float('nan')):.2f} / {c0.get('sharpe_pretax_excess', float('nan')):.2f} | "
                 f"{_pct(cv.get('mdd_after'))} / {_pct(c0.get('mdd_after'))} | {_pp(p.get('sel', {}).get('diff'))} |")
    L += ["", "통과 조건(모두): 확인 구간 세후 연수익 차이 > 0, 세전 샤프(BIL 초과) 더 높음, 원화 MDD 가 2%p 넘게 나빠지지 않음, "
          "126일 블록 부트스트랩 1,000회 90% 구간 하한 > −0.5%p, 그리고 맞추지 않은 규칙(V_U·V_E)은 선정 구간 차이도 > 0.", ""]
    for fam, line in r["power_lines"].items():
        L.append(f"- { {'user': 'V_U(시도 1)', 'grid': 'V_G·V_C(격자 가족)', 'entry': 'V_E 가족(시도 4)'}[fam] } — {line}")
    for name in JUDGED:
        c = r["pairs"].get(name, {}).get("conf", {})
        if c.get("noop_reason"):
            L.append(f"- {name}: 무효 실행 가드 — {c['noop_reason']}")
    L += ["", f"## 답: 셀(변동성 × 섹터)별 매도 규칙", "",
          f"격자 최적(V_G, 선정 구간 사건 평균 순 로그수익 {_pct(r['fit']['V_G_mean_sel_log_ret'], True, 2)}): "
          f"손절 {vg[0]}×w, 추적 익절 {vg[1]}×w, 선에 닿으면 원래 보유의 {vg[2]:.0%} 매도, 나머지 규칙 {vg[3]}({rule_ko.get(vg[3], vg[3])}). "
          "w = 진입 전 63일 일별 변동성 × √21(한 달 변동 폭). 아래 %는 셀 중앙값 종목 기준이다.", "",
          "| 셀 | 사건(선정/확인) | 한 달 변동 w | 손절 % | 추적 익절 % | m | 나머지 | 셀 전용? | 손절 발동(선정/확인) | 추적 발동(선정/확인) | 최대 상승/하락 평균(확인) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in r["cells"]:
        vc = c["V_C"]
        s_sel = c["stats"]["V_C"]["sel"]
        s_conf = c["stats"]["V_C"]["conf"]
        L.append(f"| {c['cell']} | {c['n_sel']}/{c['n_conf']} | {_pct(c['median_w'])} | {_pct(vc['stop_pct'])} | {_pct(vc['trail_pct'])} | "
                 f"{vc['m']:.0%} | {vc['rule']} | {'예' if vc['deviates'] else '아니오(V_G)'} | "
                 f"{_pct(s_sel.get('stop_hit_rate'), nd=0)}/{_pct(s_conf.get('stop_hit_rate'), nd=0)} | "
                 f"{_pct(s_sel.get('trail_hit_rate'), nd=0)}/{_pct(s_conf.get('trail_hit_rate'), nd=0)} | "
                 f"{_pct(s_conf.get('mean_mfe'), True, 0)} / {_pct(s_conf.get('mean_mae'), True, 0)} |")
    L += ["", f"셀 전용 폭은 선정 사건 {CELL_MIN_EVENTS}개 이상이고 V_G 폭보다 평균이 {CELL_MIN_GAIN:.1%}p 이상 나을 때만 쓴다. "
          "사건 = 그 리밸런싱일의 추세 활성 후보 전부(실제 매수한 3개만이 아님)를 가상으로 사서 다음 리밸런싱까지 든 것.", "",
          "## V_E 가족(사용자 추가, 진입 다음 날부터 전체에 적용) — 셀별 발동률·보유 일수·현행 대비 놓친 수익(확인 구간)", "",
          "| 셀 | V_E1 EMA21 | V_E2 다이버전스 | V_E3a 20% 추적 | V_E3b 3w 추적 (중앙 %) |", "|---|---|---|---|---|"]

    def _e(s):
        return (f"{_pct(s.get('any_exit_rate'), nd=0)} · {s.get('mean_days_to_first_exit') or 0:.0f}일 · "
                f"{_pct(s.get('mean_foregone_vs_v0_exited'), True, 1)}") if s.get("n") else "—"
    for c in r["cells"]:
        st = c["stats"]
        L.append(f"| {c['cell']} | {_e(st['V_E1']['conf'])} | {_e(st['V_E2']['conf'])} | {_e(st['V_E3a']['conf'])} | "
                 f"{_e(st['V_E3b']['conf'])} ({_pct(c['V_E3b_line_pct'])}) |")
    L += ["", "칸 = 발동률 · 첫 매도까지 평균 거래일 · 매도한 사건의 '현행 보유 대비 놓친 로그수익'(+면 팔아서 손해).", "",
          "## 사건 전체 요약(가상 진입 포함, 순 로그수익 평균)", "",
          "| 변형 | 선정: 평균 / 현행 | 확인: 평균 / 현행 | 확인: 손절·추적·규칙 발동 | 실제 3종목만(확인) 평균 / 현행 |", "|---|---|---|---|---|"]
    for name in VARIANTS[1:]:
        o = r["event_overall"][name]
        pk = r["event_picked"][name]["conf"]
        L.append(f"| {name} | {_pct(o['sel'].get('mean_log_ret'), True, 2)} / {_pct(o['sel'].get('mean_log_ret_v0'), True, 2)} | "
                 f"{_pct(o['conf'].get('mean_log_ret'), True, 2)} / {_pct(o['conf'].get('mean_log_ret_v0'), True, 2)} | "
                 f"{_pct(o['conf'].get('stop_hit_rate'), nd=0)}·{_pct(o['conf'].get('trail_hit_rate'), nd=0)}·{_pct(o['conf'].get('rem_or_rule_hit_rate'), nd=0)} | "
                 f"{_pct(pk.get('mean_log_ret'), True, 2)} / {_pct(pk.get('mean_log_ret_v0'), True, 2)} |")
    L += ["", "## 보조 비교: 새틀라이트 3종목만 100%(확인 구간, 세후 원화 3,000만 원)", "",
          "3종목에 전부 넣는 것은 챔피언보다 훨씬 집중된 위험이다. 판정에 쓰지 않는 보조 결과다.", "",
          "| 변형 | 세후 연수익 | 원화 MDD | SPY 이김?(연 +1%p, MDD 3%p 이내) | 챔피언 이김?(연수익 >, MDD 10%p 이내) |", "|---|---|---|---|---|"]
    spy = conf.get("spy", {}).get("SPY", {})
    ch = conf.get("champ", {}).get("V0", {})
    for name, sv in r["secondary_verdicts"].items():
        s = conf.get("sleeve", {}).get(name, {})
        L.append(f"| {name} | {_pct(s.get('cagr_after'), nd=2)} | {_pct(s.get('mdd_after'))} | {'예' if sv['BEATS_SPY'] else '아니오'} | {'예' if sv['BEATS_CHAMPION'] else '아니오'} |")
    L.append(f"| (기준) SPY 그냥 보유 | {_pct(spy.get('cagr_after'), nd=2)} | {_pct(spy.get('mdd_after'))} | | |")
    L.append(f"| (기준) 현 챔피언 | {_pct(ch.get('cagr_after'), nd=2)} | {_pct(ch.get('mdd_after'))} | | |")
    L += ["", "## 구간별 세후 연수익(3,000만 원, 챔피언 수준)", "", "| 변형 | 선정 구간 | 확인 구간 | 2024-07~ (보고) | 확인 1억 원 |", "|---|---|---|---|---|"]
    m100 = r["metrics"].get("base_100m", {}).get("conf", {}).get("champ", {})
    for name in VARIANTS:
        row = [m30.get(w, {}).get("champ", {}).get(name, {}).get("cagr_after") for w in WINDOWS]
        L.append(f"| {name} | {_pct(row[0], nd=2)} | {_pct(row[1], nd=2)} | {_pct(row[2], nd=2)} | {_pct(m100.get(name, {}).get('cagr_after'), nd=2)} |")
    wd = r["windows_daily"]
    L += ["", f"구간: 선정 {wd.get('sel')} (진입 2010-01~2016-07), 확인 {wd.get('conf')} (진입 2017-07~2024-01, 2024-07 진입분의 9월 말까지 포함), "
          f"보고 {wd.get('post')}. 각 구간은 새 계좌(3,000만 원)로 시작한다. 2017-01 진입분은 선정·확인 사이 완충으로 어느 쪽에도 넣지 않았다.",
          f"격자 고유 조합 {r['n_unique_grid_combos']}개(m=100% 이면 나머지 규칙이 무의미해 합침). 섹터 모름 → 경기민감으로 분류한 후보 사건 "
          f"{r['unknown_sector_events']}/{r['candidate_events_total']}.", "",
          "## 이것이 증명하는 것과 증명하지 못하는 것", "",
          "- 미국 시장 한 경로(2010~2024)의 과거 결과다. 같은 일이 앞으로 반복된다는 보장은 없다.",
          "- 생존편향: 상장폐지 종목은 가격 소스에 없어 후보에서 빠진다(매도 규칙이 막아 줬을 급락 일부가 빠질 수 있다).",
          "- 섹터 분류는 지금의 S&P500 분류이고 그 시점 분류가 아니다.",
          "- 선정 구간은 규칙을 맞추는 데 썼다. 확인 구간(2017-07~2024-09)은 다른 연구들이 이미 본 기간이라 완전히 새로운 시험이 아니다. "
          "그래서 PASS 도 '전진 원장에 올릴 후보'일 뿐 채택이 아니다. 챔피언 반영은 사용자 확인 뒤 별도 작업이다.",
          "- 이전 연구(exec-rnd-v1 +20%/+40% 익절, sprint-2w 익절 30%, 새틀라이트 R&D 청산 규칙)에서는 고정 익절이 그냥 보유를 이기지 못했다.",
          "- 함께 볼 연구: sat-exit-accuracy-v1(매도 신호 4개 각각의 정확도 — 이 연구와 겹치지 않는 '한 번 매도' 질문).",
          "- V_E 가족(진입 다음 날부터 적용하는 4개 규칙)은 결과 계산 전에 사용자 요청으로 추가했다(시도 수 4, 별도 가족).", ""]
    return "\n".join(L)


def smoke_coverage(r: dict) -> dict:
    """스모크가 모든 사다리 상태·나머지 규칙·V_E 규칙·두 비교를 실제로 지났는지."""
    o = {k: v["sel"] for k, v in r["event_overall"].items()}
    o2 = {k: v["conf"] for k, v in r["event_overall"].items()}

    def hit(name, key):
        return bool((o[name].get(key) or 0) > 0 or (o2[name].get(key) or 0) > 0)
    return {"L1_stop": hit("V_U", "stop_hit_rate"), "L2_trail": hit("V_U", "trail_hit_rate"),
            "R1": hit("V_U", "rem_or_rule_hit_rate"), "R2": hit("V_U_R2", "rem_or_rule_hit_rate"),
            "R3": hit("V_U_R3", "rem_or_rule_hit_rate"), "E1": hit("V_E1", "rem_or_rule_hit_rate"),
            "E2": hit("V_E2", "rem_or_rule_hit_rate"), "E3a": hit("V_E3a", "rem_or_rule_hit_rate"),
            "E3b": hit("V_E3b", "rem_or_rule_hit_rate"),
            "champion_verdicts": len(r["verdicts"]) == len(JUDGED),
            "sleeve_verdicts": len(r["secondary_verdicts"]) == len(JUDGED) + 1,
            "tax_engine": bool(r["metrics"].get("base_30m", {}).get("conf", {}).get("champ", {}).get("V0", {}).get("totals"))}


# =================================================================================================
# 실행
# =================================================================================================

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
        prep = _load_ckpt(ck / "prep.pkl", fp)
        if prep is None:
            step()
            prep = _smoke_prep(log) if a.smoke else _real_prep(log)
            _atomic_pickle(ck / "prep.pkl", {"fingerprint": fp, "payload": prep})
            log("입력 체크포인트 저장")
        ev = build_events(prep)
        sel_idx = np.nonzero(ev.window == "sel")[0]
        log(f"사건: 선정 {len(sel_idx)} · 확인 {int((ev.window == 'conf').sum())} · 전체 {len(ev.L)}")
        # 격자(선정 사건만) — 묶음마다 체크포인트
        combos = grid_combos()
        batch = 24
        parts = []
        for b0 in range(0, len(combos), batch):
            path = ck / f"grid_{b0:04d}.pkl"
            got = _load_ckpt(path, fp)
            if got is None:
                step()
                rows = []
                for ks, kt, m, r in combos[b0:b0 + batch]:
                    eng = run_engine(ev.C[sel_idx], ev.L[sel_idx], ks * ev.w[sel_idx], kt * ev.w[sel_idx], m, r,
                                     ev.below[sel_idx], ev.div[sel_idx])
                    rows.append(event_log_values(ev.C[sel_idx], ev.L[sel_idx], eng.sold, ev.bil_to_end[sel_idx]))
                got = np.array(rows).reshape(len(rows), len(sel_idx))
                _atomic_pickle(path, {"fingerprint": fp, "payload": got})
                log(f"격자 {b0 + len(rows)}/{len(combos)}")
            parts.append(got)
        grid_logv = np.vstack(parts)
        means = grid_logv.mean(axis=1) if grid_logv.shape[1] else np.zeros(len(combos))
        vg_i = int(np.argmax(means))   # 동점이면 격자 순서상 앞
        fit = {"V_G": combos[vg_i], "V_G_mean": float(means[vg_i])}
        fit["V_C"] = fit_cells(grid_logv, combos, [ev.cell[i] for i in sel_idx], vg_i)
        log(f"V_G = {fit['V_G']}")
        # 포트폴리오 시뮬레이션
        sched = [(pd.Timestamp(r["date"]), r["picks"]) for r in prep["schedule"]]
        pick_idx = np.nonzero(ev.picked)[0]
        windows = window_bounds(prep["core_w"].index, prep["schedule"])
        prep["windows"] = windows
        bil_r = prep["adj"][BIL].pct_change(fill_method=None)
        zero_core = pd.DataFrame(0.0, index=prep["core_w"].index, columns=prep["core_w"].columns)
        weights = {}
        for name in VARIANTS:
            eng = variant_engine(name, ev, fit, pick_idx)
            sales = sales_for_picks(ev, eng, pick_idx, prep["ext_days"])
            weights[("champ", name)] = build_target_weights(prep["core_w"], sched, sales, SAT_WEIGHT, prep["adj"])
            weights[("sleeve", name)] = build_target_weights(zero_core, sched, sales, 1.0, prep["adj"])
        jobs = []
        for win in WINDOWS:
            if win not in windows:
                continue
            for lvl in LEVELS:
                for name in VARIANTS:
                    jobs.append((lvl, name, win, "base_30m"))
            jobs.append(("spy", "SPY", win, "base_30m"))
        if "conf" in windows:
            jobs += [("champ", name, "conf", "base_100m") for name in VARIANTS] + [("spy", "SPY", "conf", "base_100m")]
        sims = {}
        for key in jobs:
            lvl, name, win, setup = key
            path = ck / f"sim_{lvl}_{name}_{win}_{setup}.pkl"
            got = _load_ckpt(path, fp)
            if got is None:
                step()
                t0, t1 = windows[win]
                base_idx = weights[("champ", "V0")].index
                if lvl == "spy":
                    w = tx.buy_and_hold_weights(base_idx[(base_idx >= t0) & (base_idx <= t1)])
                else:
                    w = weights[(lvl, name)]
                    w = w.loc[(w.index >= t0) & (w.index <= t1)]
                    w = w.loc[:, w.abs().sum() > 0]
                cfg = tx.AccountConfig(**SETUPS[setup])
                s = tx.simulate(w, prep["close"], prep["adj"], prep["fx"], cfg)
                got = _sim_summary(s, w, prep["adj"], bil_r, cfg.initial_krw)
                _atomic_pickle(path, {"fingerprint": fp, "payload": got})
                log(f"시뮬레이션 {key} 세후 {got['cagr_after']:.4f}")
            sims[key] = got
        result, rep = analyze(prep, ev, fit, grid_logv, sims, a.smoke)
        if a.smoke:
            cov = smoke_coverage(result)
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
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(rep, encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
