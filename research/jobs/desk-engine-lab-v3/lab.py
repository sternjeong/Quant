"""판단 엔진 공용 코드 3판 (desk-engine-lab-v3) — 2판(desk-engine-lab-v2/lab.py) 위에 네 가지를 바꾼다.

규칙은 SPEC.md 에 고정되어 있다(결과를 보기 전에 고정 — 바꾸려면 새 id). 1판·2판 파일은 고치지 않고 그대로 불러 쓴다:
  1) forecast_block3 : 변동성 회귀(HAR) 축척을 바탕으로 닮은 상태·기울기·여섯째 전문가를 다시 계산(ANALOG_H·TILT_H·SIXTH_H) + 재무 순위 전문가(FUND)
  2) dedupe          : 같은 값을 내는 전문가들은 한 표를 나눠 갖는다
  3) Calib3          : 핀볼 손실을 줄이는 이동(축척 가중 분위수). 보정한 것(CAL3)과 안 한 것(ENS3)을 증거 가중으로 섞는다 → V3
  4) walk3           : 걸어 나가기. 같은 점·같은 서고에서 1판 ENS(ENS1)와 2판 최종(V2)을 그대로 다시 계산해 비교 대상으로 둔다
  5) score_layer3, export·forecast_live3
numpy·pandas 만 쓴다. 주문·엔진과 연결되어 있지 않다.
"""

from __future__ import annotations

import heapq
import importlib.util
import sys
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

LAB_VERSION = "desk-engine-lab/v3"
FX = ("gp_assets", "rev_yoy", "rev_acc", "ni_yoy")   # 매출총이익/자산, 분기 매출 전년비, 그 변화(가속), 분기 순이익 전년비
EXPERTS3 = ("CLIM", "VOL", "ANALOG", "TILT", "HAR", "SIXTH", "ANALOG_H", "TILT_H", "SIXTH_H", "FUND")
POOL = ("CLIM", "VOL", "HAR", "ANALOG_H", "TILT_H", "SIXTH_H", "FUND")       # 3판 앙상블에 들어가는 전문가
POOL_IDX = [EXPERTS3.index(e) for e in POOL]
MODELS = EXPERTS3 + ("ENS1", "ENS2", "V2", "ENS3", "CAL3", "V3")
SAME_TOL = 1e-12                                     # 이 안쪽으로 같으면 같은 값을 내는 전문가로 본다
_HERE = Path(__file__).resolve().parent


def v2():
    """2판 lab 모듈(고치지 않는다)."""
    name = "desk_engine_lab_v2"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _HERE.parent / "desk-engine-lab-v2" / "lab.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L2 = v2()
V = L2.V
HORIZONS, TAUS, EVENTS, KINDS, H = V.HORIZONS, V.TAUS, V.EVENTS, V.KINDS, V.H
_TAU = np.array(TAUS)
K1, K2, K3, KP, M = len(V.EXPERTS), len(L2.EXPERTS2), len(EXPERTS3), len(POOL), len(MODELS)
I_HAR = EXPERTS3.index("HAR")
I_AH, I_TH, I_SH, I_FUND = (EXPERTS3.index(e) for e in ("ANALOG_H", "TILT_H", "SIXTH_H", "FUND"))
I_ENS1, I_ENS2, I_V2, I_ENS3, I_CAL3, I_V3 = range(K3, K3 + 6)


# ---------------------------------------------------------------- 1) 입력
def xs_ranks_nan(dates: np.ndarray, raw: np.ndarray) -> np.ndarray:
    """같은 날 값이 있는 자산들 사이의 순위 (순위 − 0.5)/개수. 값이 없으면 NaN 그대로."""
    if not len(raw):
        return np.zeros(raw.shape)
    g = pd.DataFrame(raw).groupby(np.asarray(dates).astype("datetime64[ns]"))
    return ((g.rank(method="average") - 0.5) / g.transform("count")).to_numpy(dtype=float)


def attach3(P2: dict, fx_raw: Optional[np.ndarray] = None) -> dict:
    """2판 점 표(L2.attach 결과)에 재무 값(FXRAW)과 그 순위(FR)를 붙인다. 재무가 없으면 모두 NaN. 점 집합은 그대로다."""
    n = len(P2["date"])
    raw = np.full((n, len(FX)), np.nan) if fx_raw is None else np.where(np.isfinite(fx_raw), fx_raw, np.nan).astype(float)
    P3 = dict(P2)
    P3.update(FXRAW=raw, FR=xs_ranks_nan(P2["date"], raw))
    return P3


def library3(P: dict, cand: np.ndarray, D) -> dict:
    lib = L2.library2(P, cand, D)
    lib["FR"] = P["FR"][cand]
    return lib


def phi_nan(FR: np.ndarray) -> np.ndarray:
    """순위(0~1, 모르면 NaN) → 표준화한 1차·2차 항. 모르는 값의 항은 0(평균)."""
    known = np.isfinite(FR)
    F = L2._phi(np.where(known, FR, 0.5))
    F[np.tile(~known, 2)] = 0.0
    return F


# ---------------------------------------------------------------- 2) 전문가
def har_base(lib: dict, HXq: np.ndarray, Sq: np.ndarray) -> tuple:
    """기간마다 변동성 회귀 축척(서고 [N,기간], 질의 [Q,기간]). 회귀를 못 하는 기간은 1판 축척."""
    Sl, Sq3 = lib["S"].copy(), Sq.copy()
    for hi in range(H):
        mh = np.isfinite(lib["RET"][:, hi]) & np.isfinite(lib["MN"][:, hi])
        if int(mh.sum()) < V.MIN_LIB:
            continue
        hs = L2.har_scales(lib["HX"][mh], lib["RV"][mh, hi], HXq, lib["S"][mh, hi], Sq[:, hi])
        if hs is not None:
            Sl[mh, hi], Sq3[:, hi] = hs
    return Sl, Sq3


def shifted(zr: np.ndarray, zx: Optional[np.ndarray], rows: np.ndarray, Fl: np.ndarray, Fq: np.ndarray, qmask: np.ndarray,
            sq: np.ndarray) -> tuple:
    """z 분포(서고 전체)를 능형 회귀(서고의 rows 점, 입력 Fl)가 말하는 만큼 이동. qmask 가 아닌 질의는 이동 0.

    결과: 분위수 q[Q,5], 오를 확률 [Q], 시장 초과 확률 [Q](zx 가 없으면 None)."""
    zr_s = np.sort(zr)
    d = np.where(qmask, L2.rank_shift(Fl, zr[rows], Fq), 0.0)
    q = (V._uq(zr_s, _TAU)[None, :] + d[:, None]) * sq[:, None]
    up = 1.0 - V._u_le(zr_s, -d)
    beat = None if zx is None else 1.0 - V._u_le(np.sort(zx), -np.where(qmask, L2.rank_shift(Fl, zx[rows], Fq), 0.0))
    return q, up, beat


def forecast_block3(lib: dict, Xq: np.ndarray, Sq: np.ndarray, HXq: np.ndarray, XRq: np.ndarray, FRq: np.ndarray, sixth: str,
                    blib: Optional[dict] = None) -> tuple:
    """FQ[Q, 전문가 10, 기간, 분위수], FP[Q, 전문가 10, 기간, 사건], 3판 바탕 축척 S3q[Q, 기간].

    앞 여섯은 2판 forecast_block2 그대로. ANALOG_H·TILT_H 는 1판 forecast_block 을 변동성 회귀 축척으로 다시 돌린 것."""
    Q = len(Xq)
    FQ = np.full((Q, K3, H, len(TAUS)), np.nan)
    FP = np.full((Q, K3, H, len(EVENTS)), np.nan)
    FQ[:, :K2], FP[:, :K2], info = L2.forecast_block2(lib, Xq, Sq, HXq, XRq, sixth, blib)
    if not Q or len(lib["X"]) < V.MIN_LIB:
        return FQ, FP, Sq.copy(), info
    Sl3, Sq3 = har_base(lib, HXq, Sq)
    FQh, FPh, _ = V.forecast_block(dict(lib, S=Sl3), Xq, Sq3)
    FQ[:, I_AH], FP[:, I_AH], FQ[:, I_TH], FP[:, I_TH] = FQh[:, 2], FPh[:, 2], FQh[:, 3], FPh[:, 3]
    all_q = np.ones(Q, bool)
    Fl, Fq = (L2._phi(lib["XR"]), L2._phi(XRq)) if sixth == "XRANK" else (None, None)
    Gl, Gq = phi_nan(lib["FR"]), phi_nan(FRq)
    kl, kq = np.isfinite(lib["FR"]).any(axis=1), np.isfinite(FRq).any(axis=1)
    for hi in range(H):
        mh = np.isfinite(lib["RET"][:, hi]) & np.isfinite(lib["MN"][:, hi])
        if int(mh.sum()) < V.MIN_LIB:
            continue
        sl, sq, ex = Sl3[mh, hi], Sq3[:, hi], lib["EX"][mh, hi]
        zr = lib["RET"][mh, hi] / sl
        zx = ex / sl if np.isfinite(ex).all() else None
        # 기본은 HAR 과 같고(같은 값이면 한 표로 센다), 쓸 수 있는 정보가 있으면 덮어쓴다
        for e in (I_SH, I_FUND):
            FQ[:, e, hi], FP[:, e, hi] = FQ[:, I_HAR, hi], FP[:, I_HAR, hi]
        if sixth == "XRANK":
            q, up, beat = shifted(zr, zx, np.ones(len(zr), bool), Fl[mh], Fq, all_q, sq)
            FQ[:, I_SH, hi], FP[:, I_SH, hi, 0] = q, up
            if beat is not None:
                FP[:, I_SH, hi, 2] = beat
        elif blib is not None:
            mb = np.isfinite(blib["RET"][:, hi]) & np.isfinite(blib["MN"][:, hi])
            if int(mb.sum()) >= V.MIN_LIB:
                sb = blib["S"][mb, hi]
                hb = L2.har_scales(blib["HX"][mb], blib["RV"][mb, hi], blib["HX"][mb][:1], sb, sb[:1])
                qb, pb = L2.scaled(blib["RET"][mb, hi], blib["MN"][mb, hi], np.full(int(mb.sum()), np.nan), sb if hb is None else hb[0], sq)
                FQ[:, I_SH, hi], FP[:, I_SH, hi, :2] = qb, pb[:, :2]
        # FUND — 재무 순위를 아는 서고 점으로만 회귀, 재무를 모르는 질의는 이동 0(= HAR)
        rows = kl[mh]
        if int(rows.sum()) >= V.MIN_LIB and kq.any():
            q, up, beat = shifted(zr, zx, rows, Gl[mh][rows], Gq, kq, sq)
            FQ[:, I_FUND, hi], FP[:, I_FUND, hi, 0] = q, up
            if beat is not None:
                FP[:, I_FUND, hi, 2] = beat
    return FQ, FP, Sq3, info


# ---------------------------------------------------------------- 3) 한 표 나누기·보정·조립
def dedupe(w: np.ndarray, F: np.ndarray) -> np.ndarray:
    """w[전문가], F[질의, 전문가, ...]. 이 묶음의 모든 질의에서 값이 같은 전문가들은 가중을 사람 수로 나눈다(한 표)."""
    k = len(w)
    gid = list(range(k))
    for i in range(1, k):
        for j in range(i):
            if gid[j] == j and np.allclose(F[:, i], F[:, j], rtol=0.0, atol=SAME_TOL, equal_nan=True):
                gid[i] = j
                break
    out = w / np.bincount(gid, minlength=k)[gid]
    return out / out.sum()


def pool_weights(base: np.ndarray, FQp: np.ndarray, FPp: np.ndarray) -> np.ndarray:
    """base[기간, 종류, 전문가] 증거 가중 → 이 묶음에서 같은 값끼리 한 표로 고친 가중."""
    Wt = np.empty_like(base)
    for hi in range(H):
        Wt[hi, 0] = dedupe(base[hi, 0], FQp[:, :, hi])
        for k in range(len(EVENTS)):
            Wt[hi, 1 + k] = dedupe(base[hi, 1 + k], FPp[:, :, hi, k])
    return Wt


class Calib3:
    """분위수별 이동: 실현된 과거 ENS3 예측의 u = (실제 − 예측 분위수)/축척 에서 **축척 가중 τ 분위수** × 줄임 m/(m+CAL_N0).

    줄이지 않은 이동은 과거 핀볼 손실 Σ ρ_τ(실제 − 분위수 − 축척·c) 를 가장 작게 하는 c 다(2판은 적중 빈도를 맞추는 무가중 분위수였다)."""

    def __init__(self):
        self.U: list = [[] for _ in range(H)]
        self.W: list = [[] for _ in range(H)]
        self.nd = np.zeros(H, int)
        self._shift = np.zeros((H, len(TAUS)))
        self._dirty = [False] * H

    def add(self, hi: int, y: np.ndarray, q: np.ndarray, s: np.ndarray) -> None:
        u = (y[:, None] - q) / s[:, None]
        ok = np.isfinite(u).all(axis=1) & (s > 0)
        if ok.any():
            self.U[hi].append(u[ok])
            self.W[hi].append(s[ok])
            self.nd[hi] += 1
            self._dirty[hi] = True

    def active(self) -> np.ndarray:
        return self.nd >= L2.CAL_MIN_DATES

    def shifts(self) -> np.ndarray:
        for hi in range(H):
            if not self._dirty[hi] or self.nd[hi] < L2.CAL_MIN_DATES:
                continue
            self._dirty[hi] = False
            self.U[hi], self.W[hi] = [np.concatenate(self.U[hi])], [np.concatenate(self.W[hi])]
            U, w = self.U[hi][0], self.W[hi][0]
            m = self.nd[hi] * V.STEP / HORIZONS[hi]
            for j, tau in enumerate(TAUS):
                o = np.argsort(U[:, j], kind="stable")
                c = np.cumsum(w[o])
                self._shift[hi, j] = U[o[min(int(np.searchsorted(c, tau * c[-1] - 1e-12 * c[-1], side="left")), len(o) - 1)], j] * m / (m + L2.CAL_N0)
        return self._shift.copy()


def assemble3(FQ: np.ndarray, FP: np.ndarray, S3q: np.ndarray, base3: np.ndarray, shifts3: np.ndarray, blend: np.ndarray,
              active: np.ndarray) -> tuple:
    """전문가 예측 → (ENS3 분위수, ENS3 확률, CAL3 분위수, V3 분위수). V3 확률은 ENS3 확률이다.

    base3[기간, 종류, 전문가 7], shifts3[기간, 분위수], blend[기간, 2] = (ENS3, CAL3) 가중, active[기간] = 보정이 시작됐나."""
    FQp, FPp = FQ[:, POOL_IDX], FP[:, POOL_IDX]
    q, p = V.combine(FQp, FPp, pool_weights(base3, FQp, FPp))
    qc = L2.apply_shift(q, S3q, np.where(active[:, None], shifts3, 0.0))
    qv = np.where(active[None, :, None], blend[None, :, 0, None] * q + blend[None, :, 1, None] * qc, q)
    return q, p, qc, qv


# ---------------------------------------------------------------- 4) 걸어 나가기
def walk3(P: dict, progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """모든 기준일에서 그날까지 실현된 자료만으로 전문가 10명·ENS1·ENS2·V2·ENS3·CAL3·V3 예측. ENS1·ENS2·V2 는 2판 walk2 와 같다."""
    n = len(P["date"])
    out = {"FQ": np.full((n, M, H, len(TAUS)), np.nan, np.float32), "FP": np.full((n, M, H, len(EVENTS)), np.nan, np.float32),
           "LQ": np.full((n, M, H), np.nan), "LB": np.full((n, M, H, len(EVENTS)), np.nan),
           "S3": np.full((n, H), np.nan), "CA": np.zeros((n, H), bool)}
    run1, ev2, cal2 = V.Running(), L2.Evidence(), L2.Calib()
    ev3, cal3, evb = L2.Evidence(KP), Calib3(), L2.Evidence(2)
    pending: list = [[] for _ in range(H)]
    truth = V.event_truth(P["RET"], P["MN"], P["EX"])
    B = P.get("borrow")

    def settle(hi: int, pa: int, pb: int, rows: Optional[np.ndarray] = None) -> None:
        sel = slice(None) if rows is None else rows
        lq, lb = out["LQ"][pa:pb, :, hi][sel], out["LB"][pa:pb, :, hi, :][sel]
        y = P["RET"][pa:pb, hi][sel]
        run1.add(hi, lq[:, :K1], lb[:, :K1, :])
        ev2.add(hi, 0, lq[:, :K2])
        ev3.add(hi, 0, lq[:, POOL_IDX])
        for k in range(len(EVENTS)):
            ev2.add(hi, 1 + k, lb[:, :K2, k])
            ev3.add(hi, 1 + k, lb[:, POOL_IDX, k])
        cal2.add(hi, y, out["FQ"][pa:pb, I_ENS2, hi][sel].astype(float), P["S"][pa:pb, hi][sel])
        cal3.add(hi, y, out["FQ"][pa:pb, I_ENS3, hi][sel].astype(float), out["S3"][pa:pb, hi][sel])
        if out["CA"][pa, hi]:
            evb.add(hi, 0, lq[:, [I_ENS3, I_CAL3]])

    def blend() -> np.ndarray:
        return np.array([evb.weight(hi, 0) for hi in range(H)])

    udates, starts = np.unique(P["date"], return_index=True)
    stops = np.append(starts[1:], n)
    for i, (D, a, b) in enumerate(zip(udates, starts, stops)):
        for hi in range(H):
            while pending[hi] and pending[hi][0][0] <= D:
                _, pa, pb = heapq.heappop(pending[hi])
                settle(hi, pa, pb)
        cand = L2.lib_index(P, a, D)
        if cand is not None:
            cb = None if B is None else L2.lib_index(B, int(np.searchsorted(B["date"], D, side="left")), D)
            blib = None if cb is None else L2.library2(B, cb, D)
            FQ, FP, S3q, _ = forecast_block3(library3(P, cand, D), P["X"][a:b], P["S"][a:b], P["HX"][a:b], P["XR"][a:b], P["FR"][a:b],
                                             P["sixth"], blib)
            q1, p1 = V.combine(FQ[:, :K1], FP[:, :K1], run1.weights())
            q2, p2 = V.combine(FQ[:, :K2], FP[:, :K2], ev2.weights())
            act = cal3.active()
            q3, p3, qc, qv = assemble3(FQ, FP, S3q, ev3.weights(), cal3.shifts(), blend(), act)
            out["S3"][a:b], out["CA"][a:b] = S3q, act[None, :]
            out["FQ"][a:b, :K3], out["FP"][a:b, :K3] = FQ, FP
            for idx, q, p in ((I_ENS1, q1, p1), (I_ENS2, q2, p2), (I_V2, L2.apply_shift(q2, P["S"][a:b], cal2.shifts()), p2),
                              (I_ENS3, q3, p3), (I_CAL3, qc, p3), (I_V3, qv, p3)):
                out["FQ"][a:b, idx], out["FP"][a:b, idx] = q, p
            y = P["RET"][a:b]
            for e in range(M):
                out["LQ"][a:b, e] = V.pinball(y, out["FQ"][a:b, e].astype(float))
                out["LB"][a:b, e] = (out["FP"][a:b, e].astype(float) - truth[a:b]) ** 2
            for hi in range(H):
                ends = P["END"][a:b, hi]
                ends = ends[~np.isnat(ends)]
                if len(ends):
                    heapq.heappush(pending[hi], (ends.max(), int(a), int(b)))
        if progress and (i % 50 == 0 or i == len(udates) - 1):
            progress(i + 1, len(udates))
    for hi in range(H):
        for _, pa, pb in sorted(pending[hi]):
            settle(hi, pa, pb, ~np.isnat(P["END"][pa:pb, hi]))
    out.update(weights1=run1.weights(), weights2=ev2.weights(), shifts2=cal2.shifts(), weights3=ev3.weights(), shifts3=cal3.shifts(),
               blend=blend(), cal_active=cal3.active(), realized_dates=ev3.n.copy(), blend_dates=evb.n[:, 0].copy())
    return out


# ---------------------------------------------------------------- 5) 점수
COMPARES = (("vs_clim", I_V3, 0), ("vs_v1", I_V3, I_ENS1), ("vs_v2", I_V3, I_V2), ("v2_vs_v1", I_V2, I_ENS1),
            ("v1_vs_clim", I_ENS1, 0), ("ens3_vs_v1", I_ENS3, I_ENS1), ("vs_har", I_V3, I_HAR))
COVERAGE = (I_ENS1, I_V2, I_ENS3, I_CAL3, I_V3)


def score_layer3(P: dict, out: dict, eras: list, judged_end: str, alpha_family: float) -> dict:
    """칸(기간 × 종류)마다: V3 대 CLIM(표시 등급)·V3 대 ENS1(판정)·V3 대 V2·V2 대 ENS1(2판 재현)·ENS1 대 CLIM·ENS3 대 ENS1(보정 전)·
    V3 대 HAR(가장 나았던 전문가), 모형별 기량, 구간 적중."""
    cells = {}
    first, last = np.datetime64(eras[0][1]), np.datetime64(eras[-1][2])
    for hi, h in enumerate(HORIZONS):
        for k, kind in enumerate(KINDS):
            L = L2.cell_loss(out, hi, k)
            if not np.isfinite(L[:, I_V3]).any():
                continue
            c = {name: L2.compare(P, L, m, b, hi, eras, judged_end, alpha_family) for name, m, b in COMPARES}
            ok = np.isfinite(L).all(axis=1) & (P["END"][:, hi] <= np.datetime64(judged_end)) & (P["date"] >= first) & (P["date"] <= last)
            by = pd.DataFrame(L[ok]).groupby(P["date"][ok]).mean().mean() if ok.any() else None
            c["expert_skill"] = {} if by is None else {MODELS[e]: V._skill(by[0], by[e]) for e in range(1, M)}
            if k == 0 and ok.any():
                y = P["RET"][ok, hi]
                c["coverage80"] = {MODELS[e]: float(((y >= out["FQ"][ok, e, hi, 0]) & (y <= out["FQ"][ok, e, hi, 4])).mean()) for e in COVERAGE}
            cells[f"{h}:{kind}"] = c
    return cells


# ---------------------------------------------------------------- 6) 모형 저장·실시간 예측
def export_library3(P: dict) -> pd.DataFrame:
    """자료 끝 시점의 서고(2판 export_library2 와 같은 점) + 재무 순위 열."""
    df = L2.export_library2(P)
    cand = np.where(np.isfinite(P["RET"][:, 0]) & np.isfinite(P["MN"][:, 0]))[0]
    if len(cand) > V.CAP:
        cand = np.sort(cand[np.argpartition(P["prio"][cand], V.CAP - 1)[:V.CAP]])
    for j, c in enumerate(FX):
        df[f"fr_{c}"] = np.round(P["FR"][cand, j], 6)
    return df


def library_from_frame3(df: pd.DataFrame) -> dict:
    fr = [f"fr_{c}" for c in FX]
    lib = L2.library_from_frame2(df.drop(columns=fr))
    lib["FR"] = df[fr].to_numpy(dtype=float)
    return lib


def fx_grid(P: dict) -> Optional[list]:
    """마지막 기준일의 자산 간 재무 값 분포(분위 격자, 값이 20개 미만인 항목은 None). 재무가 하나도 없으면 None."""
    if not len(P["date"]):
        return None
    raw = P["FXRAW"][P["date"] == P["date"][-1]]
    grid = [np.nanquantile(raw[:, j], np.linspace(0, 1, L2.GRID)).tolist() if int(np.isfinite(raw[:, j]).sum()) >= 20 else None
            for j in range(len(FX))]
    return grid if any(g is not None for g in grid) else None


def _to_rank(values, grid: Optional[list], fill: float) -> np.ndarray:
    u = np.linspace(0, 1, L2.GRID)
    return np.array([[np.interp(v, grid[j], u) if grid is not None and grid[j] is not None and np.isfinite(v) else fill
                      for j, v in enumerate(values)]])


def forecast_live3(lib: dict, layer: dict, state: dict, blib: Optional[dict] = None) -> dict:
    """자산 하나의 지금 예측. layer = model.json 의 층(가중·이동·격자), state = L2.latest_state2 결과(+ 있으면 재무 값 'fx').

    결과: 전문가·ENS1·V2·ENS3·CAL3·V3 의 분위수(로그 수익)와 확률, 3판이 실제로 쓴 가중."""
    x, s, hx = (np.asarray(state[k], float)[None, :] for k in ("x", "s", "hx"))
    sixth = layer["sixth"]
    xr = _to_rank(state["xs"], layer.get("xs_grid"), 0.5) if sixth == "XRANK" else np.full((1, len(L2.XS)), 0.5)
    fr = _to_rank(state.get("fx") or [np.nan] * len(FX), layer.get("fx_grid"), np.nan)
    FQ, FP, S3q, info = forecast_block3(lib, x, s, hx, xr, fr, sixth, blib)
    a = lambda k: np.asarray(layer[k], float)  # noqa: E731
    act = np.asarray(layer["cal_active"], bool)
    q3, p3, qc, qv = assemble3(FQ, FP, S3q, a("weights3"), a("shifts3"), a("blend"), act)
    q1, p1 = V.combine(FQ[:, :K1], FP[:, :K1], a("weights1"))
    q2, p2 = V.combine(FQ[:, :K2], FP[:, :K2], a("weights2"))
    names = [sixth if e == "SIXTH" else f"{sixth}_H" if e == "SIXTH_H" else e for e in EXPERTS3]
    return {"q": {e: FQ[0, i] for i, e in enumerate(names)} | {"ENS1": q1[0], "V2": L2.apply_shift(q2, s, a("shifts2"))[0], "ENS3": q3[0],
                                                                "CAL3": qc[0], "V3": qv[0]},
            "p": {e: FP[0, i] for i, e in enumerate(names)} | {"ENS1": p1[0], "V2": p2[0], "ENS3": p3[0], "CAL3": p3[0], "V3": p3[0]},
            "n": info["n"], "weights": pool_weights(a("weights3"), FQ[:, POOL_IDX], FP[:, POOL_IDX])}
