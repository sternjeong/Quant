"""판단 엔진 공용 코드 2판 (desk-engine-lab-v2) — 1판(desk-engine-lab/lab.py) 위에 전문가 둘·증거 가중·구간 보정을 더한다.

규칙은 SPEC.md 에 고정되어 있다(결과를 보기 전에 고정 — 바꾸려면 새 id). 1판 파일은 고치지 않고 그대로 불러 쓴다:
  1) asset_frame2 / attach : 1판 특징 위에 변동성 회귀 입력(HX)·앞으로의 실현 변동성(RV)·같은 날 자산 간 순위(XR)
  2) forecast_block2       : 1판 전문가 4명 + HAR(변동성 회귀) + 여섯째(업종·종목 = XRANK 순위 회귀, 시장 = BORROW 업종 서고 빌리기)
  3) Evidence              : 증거 가중 — 가장 나은 전문가보다 얼마나 뚜렷이(t 값) 나쁜가로 가중
  4) Calib                 : 구간 보정 — 실현된 과거 예측의 분위수별 어긋남만큼 이동
  5) walk2                 : 걸어 나가기. 같은 점·같은 서고에서 1판 ENS(ENS1)를 그대로 다시 계산해 비교 대상으로 둔다
  6) compare / score_layer2, export·forecast_live2
numpy·pandas 만 쓴다. 주문·엔진과 연결되어 있지 않다.
"""

from __future__ import annotations

import heapq
import importlib.util
import math
import sys
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

LAB_VERSION = "desk-engine-lab/v2"
HX_OWN = ("h21", "h63", "h252", "hew")       # ln 21·63·252일 변동성, ln EWMA 변동성(일 단위)
HX_MKT = ("m21", "m252")                     # 시장의 ln 21·252일 변동성(업종·종목 층에만)
XS = ("mom", "rev", "dd", "trend", "volr", "h252")   # 같은 날 자산 간 순위를 매기는 값
EXPERTS2 = ("CLIM", "VOL", "ANALOG", "TILT", "HAR", "SIXTH")
SIXTH = ("XRANK", "BORROW")                  # 여섯째 전문가: 업종·종목 층 / 시장 층
MODELS = EXPERTS2 + ("ENS1", "ENS2", "V2")   # ENS1 = 1판 앙상블(비교 대상), ENS2 = 증거 가중, V2 = ENS2 + 구간 보정(최종)
HAR_RIDGE = 1e-6                             # 변동성 회귀의 아주 작은 벌점(겹치는 입력 안정화)
HAR_CLIP = 3.0                               # 회귀 축척은 1판 축척의 1/3~3배 안
RV_FLOOR = 1e-6
XR_RIDGE = 0.02                              # 순위 회귀 벌점(×n, 표준화한 입력)
XR_CLIP = 0.5                                # 순위 전문가의 이동 한도(변동성 단위)
LAMBDA = 1.0                                 # 증거 가중: w ∝ exp(−λ·t), t 는 겹침만큼 줄인다(×√(21/h))
MIN_DATES = 12                               # 실현된 기준일이 이만큼 쌓이기 전에는 같은 가중
T_MAX = 50.0
CAL_MIN_DATES = 36                           # 구간 보정을 시작하는 실현 기준일 수
CAL_N0 = 20.0                                # 보정 이동의 줄임: 겹치지 않는 기간 수 m 에 대해 m/(m+20)
GRID = 101                                   # 실시간 순위 환산용 분위 격자
_HERE = Path(__file__).resolve().parent


def v1():
    """1판 lab 모듈(고치지 않는다)."""
    name = "desk_engine_lab"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _HERE.parent / "desk-engine-lab" / "lab.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


V = v1()
HORIZONS, TAUS, EVENTS, KINDS, H = V.HORIZONS, V.TAUS, V.EVENTS, V.KINDS, V.H
_TAU = np.array(TAUS)
K1, K2, M = len(V.EXPERTS), len(EXPERTS2), len(MODELS)
I_ENS1, I_ENS2, I_V2 = K2, K2 + 1, K2 + 2


# ---------------------------------------------------------------- 1) 특징
def asset_frame2(lp: pd.Series, mlp: Optional[pd.Series] = None) -> pd.DataFrame:
    """1판 asset_frame + 변동성 회귀 입력(그날 종가까지)과 앞으로 h일 실현 변동성(그 뒤 자료)."""
    f = V.asset_frame(lp, mlp)
    r = lp.astype(float).diff()
    with np.errstate(divide="ignore", invalid="ignore"):
        f["h21"] = np.log(r.rolling(21, min_periods=15).std())
        f["h63"] = np.log(r.rolling(63, min_periods=45).std())
        f["h252"] = np.log(r.rolling(252, min_periods=200).std())
        f["hew"] = 0.5 * np.log(r.pow(2).ewm(alpha=1 - V.EWMA_LAMBDA, adjust=False, min_periods=60).mean())
    r2 = r.pow(2)
    for h in HORIZONS:
        f[f"rv{h}"] = np.sqrt(r2.rolling(h, min_periods=h).sum()).shift(-h)
    return f


def market_state2(mlp: pd.Series) -> pd.DataFrame:
    f = asset_frame2(mlp)
    return f[["dd", "volr", "h21", "h252"]].rename(columns={"dd": "mdd", "volr": "mvolr", "h21": "m21", "h252": "m252"})


def hx_names(with_market: bool) -> tuple:
    return HX_OWN + (HX_MKT if with_market else ())


def xs_ranks(dates: np.ndarray, raw: np.ndarray) -> np.ndarray:
    """같은 날 자산들 사이의 순위 (순위 − 0.5)/개수. 값이 없으면 0.5."""
    df = pd.DataFrame(raw)
    g = df.groupby(np.asarray(dates).astype("datetime64[ns]"))
    out = ((g.rank(method="average") - 0.5) / g.transform("count")).to_numpy(dtype=float)
    return np.where(np.isfinite(out), out, 0.5)


def attach(P: dict, frames: dict, with_market: bool, borrow: Optional[dict] = None) -> dict:
    """1판 점 표 P(build_points 결과)에 2판 열을 붙인다. frames 는 asset_frame2 결과(+시장 상태 열). 점 집합은 1판 그대로다."""
    hx = hx_names(with_market)
    n = len(P["date"])
    HXa, RV, raw = np.full((n, len(hx)), np.nan), np.full((n, H), np.nan), np.full((n, len(XS)), np.nan)
    for k, name in enumerate(P["names"]):
        idx = np.where(P["asset"] == k)[0]
        if not len(idx):
            continue
        g = frames[name].reindex(pd.DatetimeIndex(P["date"][idx].astype("datetime64[ns]")))
        HXa[idx] = g[list(hx)].to_numpy(dtype=float)
        RV[idx] = g[[f"rv{h}" for h in HORIZONS]].to_numpy(dtype=float)
        raw[idx] = g[list(XS)].to_numpy(dtype=float)
    P2 = dict(P)
    P2.update(hx=hx, HX=HXa, RV=RV, XRAW=raw, XR=xs_ranks(P["date"], raw) if n else np.zeros((0, len(XS))),
              sixth="XRANK" if with_market else "BORROW", borrow=borrow)
    return P2


# ---------------------------------------------------------------- 2) 전문가
def lib_index(P: dict, a: int, D) -> Optional[np.ndarray]:
    """1판 library_at 과 같은 점 고르기(색인만)."""
    cand = np.where(P["END"][:a, 0] <= D)[0]
    if len(cand) < V.MIN_LIB:
        return None
    if len(cand) > V.CAP:
        cand = np.sort(cand[np.argpartition(P["prio"][cand], V.CAP - 1)[:V.CAP]])
    return cand


def library2(P: dict, cand: np.ndarray, D) -> dict:
    seen = P["END"][cand] <= D
    return {"X": P["X"][cand], "S": P["S"][cand], "RET": np.where(seen, P["RET"][cand], np.nan),
            "MN": np.where(seen, P["MN"][cand], np.nan), "EX": np.where(seen, P["EX"][cand], np.nan),
            "HX": P["HX"][cand], "RV": np.where(seen, P["RV"][cand], np.nan), "XR": P["XR"][cand]}


def scaled(raw: np.ndarray, rmn: np.ndarray, ex: np.ndarray, sl: np.ndarray, sq: np.ndarray) -> tuple:
    """결과를 서고 축척 sl 로 나눈 분포 × 질의 축척 sq (1판 VOL 과 같은 계산). q[Q,5], p[Q,3]."""
    zr, zm = raw / sl, rmn / sl
    q = V._uq(np.sort(zr), _TAU)[None, :] * sq[:, None]
    p = np.full((len(sq), len(EVENTS)), np.nan)
    p[:, 0] = float((zr > 0).mean())
    p[:, 1] = V._u_le(np.sort(zm), V.DD_LOG / sq)
    if np.isfinite(ex).all():
        p[:, 2] = float((ex > 0).mean())
    return q, p


def har_scales(HXl: np.ndarray, rv: np.ndarray, HXq: np.ndarray, sl: np.ndarray, sq: np.ndarray) -> Optional[tuple]:
    """ln(앞으로 h일 실현 변동성) ~ 1 + HX 회귀로 서고·질의의 축척. 입력이 없는 점은 1판 축척. 회귀할 점이 모자라면 None."""
    ok = np.isfinite(HXl).all(axis=1) & np.isfinite(rv)
    n = int(ok.sum())
    if n < V.MIN_LIB:
        return None
    A = np.column_stack([np.ones(n), HXl[ok]])
    y = np.log(np.maximum(rv[ok], RV_FLOOR))
    beta = np.linalg.solve(A.T @ A + HAR_RIDGE * n * np.eye(A.shape[1]), A.T @ y)

    def fit(HXx: np.ndarray, base: np.ndarray) -> np.ndarray:
        good = np.isfinite(HXx).all(axis=1)
        pred = np.exp(np.column_stack([np.ones(len(HXx)), np.where(good[:, None], HXx, 0.0)]) @ beta)
        return np.where(good, np.clip(pred, base / HAR_CLIP, base * HAR_CLIP), base)

    return fit(HXl, sl), fit(HXq, sq)


def _phi(XR: np.ndarray) -> np.ndarray:
    """순위(0~1) → 표준화한 1차·2차 항."""
    c = XR - 0.5
    return np.column_stack([c * math.sqrt(12.0), (c * c - 1.0 / 12.0) * math.sqrt(180.0)])


def rank_shift(Fl: np.ndarray, y: np.ndarray, Fq: np.ndarray) -> np.ndarray:
    mu, ym = Fl.mean(0), y.mean()
    Xc = Fl - mu
    beta = np.linalg.solve(Xc.T @ Xc + XR_RIDGE * len(y) * np.eye(Xc.shape[1]), Xc.T @ (y - ym))
    return np.clip((Fq - mu) @ beta, -XR_CLIP, XR_CLIP)


def forecast_block2(lib: dict, Xq: np.ndarray, Sq: np.ndarray, HXq: np.ndarray, XRq: np.ndarray, sixth: str,
                    blib: Optional[dict] = None) -> tuple:
    """FQ[Q, 전문가 6, 기간, 분위수], FP[Q, 전문가 6, 기간, 사건]. 앞 넷은 1판 forecast_block 그대로."""
    Q = len(Xq)
    FQ = np.full((Q, K2, H, len(TAUS)), np.nan)
    FP = np.full((Q, K2, H, len(EVENTS)), np.nan)
    FQ1, FP1, info = V.forecast_block(lib, Xq, Sq)
    FQ[:, :K1], FP[:, :K1] = FQ1, FP1
    if not Q or len(lib["X"]) < V.MIN_LIB:
        return FQ, FP, info
    Fl, Fq = (_phi(lib["XR"]), _phi(XRq)) if sixth == "XRANK" else (None, None)
    for hi in range(H):
        mh = np.isfinite(lib["RET"][:, hi]) & np.isfinite(lib["MN"][:, hi])
        if int(mh.sum()) < V.MIN_LIB:
            continue
        raw, rmn, sl, ex = lib["RET"][mh, hi], lib["MN"][mh, hi], lib["S"][mh, hi], lib["EX"][mh, hi]
        sq = Sq[:, hi]
        # HAR — 변동성을 회귀로 예측해 축척(못 하면 VOL 과 같다)
        hs = har_scales(lib["HX"][mh], lib["RV"][mh, hi], HXq, sl, sq)
        if hs is None:
            FQ[:, 4, hi], FP[:, 4, hi] = FQ[:, 1, hi], FP[:, 1, hi]
        else:
            FQ[:, 4, hi], FP[:, 4, hi] = scaled(raw, rmn, ex, hs[0], hs[1])
        # 여섯째 — 기본은 VOL 과 같고, 층에 따라 덮어쓴다
        FQ[:, 5, hi], FP[:, 5, hi] = FQ[:, 1, hi], FP[:, 1, hi]
        if sixth == "XRANK":
            zr = raw / sl
            zr_s = np.sort(zr)
            d = rank_shift(Fl[mh], zr, Fq)
            FQ[:, 5, hi] = (V._uq(zr_s, _TAU)[None, :] + d[:, None]) * sq[:, None]
            FP[:, 5, hi, 0] = 1.0 - V._u_le(zr_s, -d)
            if np.isfinite(ex).all():
                zx = ex / sl
                FP[:, 5, hi, 2] = 1.0 - V._u_le(np.sort(zx), -rank_shift(Fl[mh], zx, Fq))
        elif blib is not None:
            mb = np.isfinite(blib["RET"][:, hi]) & np.isfinite(blib["MN"][:, hi])
            if int(mb.sum()) >= V.MIN_LIB:
                qb, pb = scaled(blib["RET"][mb, hi], blib["MN"][mb, hi], np.full(int(mb.sum()), np.nan), blib["S"][mb, hi], sq)
                FQ[:, 5, hi], FP[:, 5, hi, :2] = qb, pb[:, :2]
    return FQ, FP, info


# ---------------------------------------------------------------- 3) 증거 가중
class Evidence:
    """기준일 평균 손실의 누계(기간 × 종류 × 전문가)와 곱 누계 → 가장 나은 전문가 대비 t 값으로 가중."""

    def __init__(self, k: int = K2):
        self.k = k
        self.n = np.zeros((H, len(KINDS)))
        self.s = np.zeros((H, len(KINDS), k))
        self.c = np.zeros((H, len(KINDS), k, k))

    def add(self, hi: int, kind: int, rows: np.ndarray) -> None:
        """rows[점, 전문가] — 한 기준일의 점별 손실. 모든 전문가 값이 있는 점의 평균을 한 번 더한다."""
        ok = np.isfinite(rows).all(axis=1)
        if not ok.any():
            return
        m = rows[ok].mean(axis=0)
        self.n[hi, kind] += 1
        self.s[hi, kind] += m
        self.c[hi, kind] += np.outer(m, m)

    def weight(self, hi: int, kind: int) -> np.ndarray:
        n = self.n[hi, kind]
        if n < MIN_DATES:
            return np.full(self.k, 1.0 / self.k)
        mean = self.s[hi, kind] / n
        b = int(np.argmin(mean))
        C = self.c[hi, kind]
        diff = mean - mean[b]
        var = (np.diag(C) + C[b, b] - 2.0 * C[:, b]) / n - diff ** 2
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(var > 1e-24, math.sqrt(n) * diff / np.sqrt(np.maximum(var, 1e-24)), np.where(diff > 1e-15, T_MAX, 0.0))
        w = np.exp(-LAMBDA * math.sqrt(V.STEP / HORIZONS[hi]) * np.clip(t, 0.0, T_MAX))
        return w / w.sum()

    def weights(self) -> np.ndarray:
        return np.array([[self.weight(hi, k) for k in range(len(KINDS))] for hi in range(H)])


# ---------------------------------------------------------------- 4) 구간 보정
class Calib:
    """분위수별 이동: 실현된 모든 과거 예측에서 (실제 − 예측 분위수)/축척 의 τ 분위수 × 줄임 m/(m+CAL_N0).

    줄이지 않은 이동을 더하면 과거 '실제 ≤ 분위수' 빈도가 τ 가 된다. m = 실현 기준일 수 × 21/h (겹치지 않는 기간 수)."""

    def __init__(self):
        self.blocks: list = [[] for _ in range(H)]
        self._shift = np.zeros((H, len(TAUS)))
        self._dirty = [False] * H

    def add(self, hi: int, y: np.ndarray, q: np.ndarray, s: np.ndarray) -> None:
        u = (y[:, None] - q) / s[:, None]
        u = u[np.isfinite(u).all(axis=1)]
        if len(u):
            self.blocks[hi].append(u)
            self._dirty[hi] = True

    def shifts(self) -> np.ndarray:
        for hi in range(H):
            if not self._dirty[hi]:
                continue
            self._dirty[hi] = False
            nd = len(self.blocks[hi])
            if nd < CAL_MIN_DATES:
                continue
            self.blocks[hi] = [np.concatenate(self.blocks[hi])] + [np.zeros((0, len(TAUS)))] * (nd - 1)   # 한 덩어리로(기준일 수는 유지)
            U = self.blocks[hi][0]
            m = nd * V.STEP / HORIZONS[hi]
            k = np.clip(np.ceil(_TAU * len(U)).astype(int) - 1, 0, len(U) - 1)
            self._shift[hi] = [np.partition(U[:, j], k[j])[k[j]] * m / (m + CAL_N0) for j in range(len(TAUS))]
        return self._shift.copy()


def apply_shift(q: np.ndarray, S: np.ndarray, shift: np.ndarray) -> np.ndarray:
    """q[Q, 기간, 분위수] + S[Q, 기간]·shift[기간, 분위수], 분위수 순서 유지."""
    return np.sort(q + S[:, :, None] * shift[None, :, :], axis=-1)


# ---------------------------------------------------------------- 5) 걸어 나가기
def walk2(P: dict, progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """모든 기준일에서 그날까지 실현된 자료만으로 전문가 6명·ENS1·ENS2·V2 예측. ENS1 은 1판 walk 의 ENS 와 같다."""
    n = len(P["date"])
    out = {"FQ": np.full((n, M, H, len(TAUS)), np.nan, np.float32), "FP": np.full((n, M, H, len(EVENTS)), np.nan, np.float32),
           "LQ": np.full((n, M, H), np.nan), "LB": np.full((n, M, H, len(EVENTS)), np.nan)}
    run1, ev, cal = V.Running(), Evidence(), Calib()
    pending: list = [[] for _ in range(H)]
    truth = V.event_truth(P["RET"], P["MN"], P["EX"])
    B = P.get("borrow")

    def settle(hi: int, pa: int, pb: int, rows: Optional[np.ndarray] = None) -> None:
        sel = slice(None) if rows is None else rows
        lq, lb = out["LQ"][pa:pb, :, hi][sel], out["LB"][pa:pb, :, hi, :][sel]
        run1.add(hi, lq[:, :K1], lb[:, :K1, :])
        ev.add(hi, 0, lq[:, :K2])
        for k in range(len(EVENTS)):
            ev.add(hi, 1 + k, lb[:, :K2, k])
        cal.add(hi, P["RET"][pa:pb, hi][sel], out["FQ"][pa:pb, I_ENS2, hi][sel].astype(float), P["S"][pa:pb, hi][sel])

    udates, starts = np.unique(P["date"], return_index=True)
    stops = np.append(starts[1:], n)
    for i, (D, a, b) in enumerate(zip(udates, starts, stops)):
        for hi in range(H):
            while pending[hi] and pending[hi][0][0] <= D:
                _, pa, pb = heapq.heappop(pending[hi])
                settle(hi, pa, pb)
        cand = lib_index(P, a, D)
        if cand is not None:
            blib = None if B is None else V.library_at(B, int(np.searchsorted(B["date"], D, side="left")), D)
            FQ, FP, _ = forecast_block2(library2(P, cand, D), P["X"][a:b], P["S"][a:b], P["HX"][a:b], P["XR"][a:b], P["sixth"], blib)
            q1, p1 = V.combine(FQ[:, :K1], FP[:, :K1], run1.weights())
            q2, p2 = V.combine(FQ, FP, ev.weights())
            q3 = apply_shift(q2, P["S"][a:b], cal.shifts())
            out["FQ"][a:b, :K2], out["FP"][a:b, :K2] = FQ, FP
            out["FQ"][a:b, I_ENS1], out["FQ"][a:b, I_ENS2], out["FQ"][a:b, I_V2] = q1, q2, q3
            out["FP"][a:b, I_ENS1], out["FP"][a:b, I_ENS2], out["FP"][a:b, I_V2] = p1, p2, p2
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
    out.update(weights1=run1.weights(), weights2=ev.weights(), shifts=cal.shifts(), realized=run1.cnt.copy(), realized_dates=ev.n.copy())
    return out


# ---------------------------------------------------------------- 6) 점수
def cell_loss(out: dict, hi: int, kind: int) -> np.ndarray:
    """[점, 모형 9] 손실."""
    return out["LQ"][:, :, hi] if kind == 0 else out["LB"][:, :, hi, kind - 1]


def compare(P: dict, L: np.ndarray, model: int, base: int, hi: int, eras: list, judged_end: str, alpha_family: float,
            min_blocks: int = 5) -> dict:
    """모형 대 기준의 성적: 기준일 평균 → 달력 구획(1년, 12개월 기간은 2년) → 한쪽 부호 뒤집기. 등급 규칙은 1판과 같다."""
    ok = np.isfinite(L).all(axis=1) & (P["END"][:, hi] <= np.datetime64(judged_end))
    df = pd.DataFrame({"m": L[ok, model], "b": L[ok, base], "date": P["date"][ok]})
    by = df.groupby("date").mean()
    block_years = 2 if HORIZONS[hi] >= 252 else 1
    years = pd.DatetimeIndex(by.index).year.to_numpy()

    def part(sel: np.ndarray) -> dict:
        sub = by[sel]
        if sub.empty:
            return {"n_origins": 0, "n_blocks": 0, "skill": None, "p": None}
        blocks = sub.groupby((years[sel] // block_years) * block_years).mean()
        return {"n_origins": int(len(sub)), "n_blocks": int(len(blocks)), "skill": V._skill(sub["b"].mean(), sub["m"].mean()),
                "p": V.signflip_p((blocks["b"] - blocks["m"]).to_numpy())}

    res = {"n_points": int(ok.sum()), "eras": {}}
    judged = np.zeros(len(by), bool)
    for name, start, end in eras:
        sel = np.asarray((by.index >= np.datetime64(start)) & (by.index <= np.datetime64(end)))
        res["eras"][name] = part(sel)
        judged |= sel
    res.update(part(judged))
    res["evaluable"] = bool(res["n_blocks"] >= 2 * min_blocks and all(res["eras"][nm]["n_blocks"] >= min_blocks for nm, _, _ in eras))
    res["grade"] = V.grade(res["skill"], res["p"], [res["eras"][nm]["skill"] for nm, _, _ in eras], alpha_family) if res["evaluable"] else "없음"
    return res


def score_layer2(P: dict, out: dict, eras: list, judged_end: str, alpha_family: float) -> dict:
    """칸(기간 × 종류)마다: V2 대 CLIM(표시 등급)·V2 대 ENS1(판정)·ENS1 대 CLIM(1판 재현)·ENS2 대 ENS1(보정 전), 전문가 기량, 구간 적중."""
    cells = {}
    first = np.datetime64(eras[0][1])
    last = np.datetime64(eras[-1][2])
    for hi, h in enumerate(HORIZONS):
        for k, kind in enumerate(KINDS):
            L = cell_loss(out, hi, k)
            if not np.isfinite(L[:, I_V2]).any():
                continue
            args = (hi, eras, judged_end, alpha_family)
            c = {"vs_clim": compare(P, L, I_V2, 0, *args), "vs_v1": compare(P, L, I_V2, I_ENS1, *args),
                 "v1_vs_clim": compare(P, L, I_ENS1, 0, *args), "ens2_vs_v1": compare(P, L, I_ENS2, I_ENS1, *args)}
            ok = np.isfinite(L).all(axis=1) & (P["END"][:, hi] <= np.datetime64(judged_end)) & (P["date"] >= first) & (P["date"] <= last)
            by = pd.DataFrame(L[ok]).groupby(P["date"][ok]).mean().mean() if ok.any() else None
            c["expert_skill"] = {} if by is None else {MODELS[e]: V._skill(by[0], by[e]) for e in range(1, M)}
            if k == 0 and ok.any():
                y = P["RET"][ok, hi]
                c["coverage80"] = {MODELS[e]: float(((y >= out["FQ"][ok, e, hi, 0]) & (y <= out["FQ"][ok, e, hi, 4])).mean())
                                   for e in (I_ENS1, I_ENS2, I_V2)}
            cells[f"{h}:{kind}"] = c
    return cells


# ---------------------------------------------------------------- 7) 모형 저장·실시간 예측
def export_library2(P: dict) -> pd.DataFrame:
    """자료 끝 시점의 서고(1판 export_library 와 같은 점) + 2판 열."""
    cand = np.where(np.isfinite(P["RET"][:, 0]) & np.isfinite(P["MN"][:, 0]))[0]
    if len(cand) > V.CAP:
        cand = np.sort(cand[np.argpartition(P["prio"][cand], V.CAP - 1)[:V.CAP]])
    df = pd.DataFrame(P["X"][cand], columns=list(P["feats"]))
    for hi, h in enumerate(HORIZONS):
        df[f"s{h}"], df[f"ret{h}"], df[f"mn{h}"], df[f"ex{h}"] = P["S"][cand, hi], P["RET"][cand, hi], P["MN"][cand, hi], P["EX"][cand, hi]
        df[f"rv{h}"] = P["RV"][cand, hi]
    for j, c in enumerate(P["hx"]):
        df[f"hx_{c}"] = P["HX"][cand, j]
    for j, c in enumerate(XS):
        df[f"xr_{c}"] = P["XR"][cand, j]
    return df.round(6)


def library_from_frame2(df: pd.DataFrame) -> dict:
    hx = [c for c in df.columns if c.startswith("hx_")]
    xr = [f"xr_{c}" for c in XS]
    fixed = set(V.LIB_COLS_FIXED) | {f"rv{h}" for h in HORIZONS} | set(hx) | set(xr)
    feats = [c for c in df.columns if c not in fixed]
    g = lambda c: np.stack([df[f"{c}{h}"].to_numpy(dtype=float) for h in HORIZONS], axis=1)  # noqa: E731
    return {"feats": tuple(feats), "hx": tuple(c[3:] for c in hx), "X": df[feats].to_numpy(dtype=float), "S": g("s"), "RET": g("ret"),
            "MN": g("mn"), "EX": g("ex"), "RV": g("rv"), "HX": df[hx].to_numpy(dtype=float), "XR": df[xr].to_numpy(dtype=float)}


def xs_grid(P: dict) -> Optional[list]:
    """마지막 기준일의 자산 간 분포(분위 격자). 실시간에서 값 → 순위 환산에 쓴다. 자산이 20개 미만이면 None."""
    if P["sixth"] != "XRANK" or not len(P["date"]):
        return None
    raw = P["XRAW"][P["date"] == P["date"][-1]]
    if len(raw) < 20:
        return None
    return [np.nanquantile(raw[:, j], np.linspace(0, 1, GRID)).tolist() for j in range(len(XS))]


def forecast_live2(lib: dict, weights2: np.ndarray, shifts: np.ndarray, state: dict, sixth: str, grid: Optional[list] = None,
                   blib: Optional[dict] = None, weights1: Optional[np.ndarray] = None) -> dict:
    """자산 하나의 지금 예측. state = latest_state2 결과. 결과: 전문가·ENS2·V2(주면 ENS1 도)의 분위수(로그 수익)와 확률."""
    x, s, hx = (np.asarray(state[k], float)[None, :] for k in ("x", "s", "hx"))
    if sixth == "XRANK" and grid is not None:
        xr = np.array([[np.interp(v, grid[j], np.linspace(0, 1, GRID)) if np.isfinite(v) else 0.5 for j, v in enumerate(state["xs"])]])
    else:
        xr = np.full((1, len(XS)), 0.5)
    FQ, FP, info = forecast_block2(lib, x, s, hx, xr, sixth, blib)
    q2, p2 = V.combine(FQ, FP, np.asarray(weights2, float))
    names = [sixth if e == "SIXTH" else e for e in EXPERTS2]
    out = {"q": {e: FQ[0, i] for i, e in enumerate(names)} | {"ENS2": q2[0], "V2": apply_shift(q2, s, np.asarray(shifts, float))[0]},
           "p": {e: FP[0, i] for i, e in enumerate(names)} | {"ENS2": p2[0], "V2": p2[0]}, "n": info["n"]}
    if weights1 is not None:
        q1, p1 = V.combine(FQ[:, :K1], FP[:, :K1], np.asarray(weights1, float))
        out["q"]["ENS1"], out["p"]["ENS1"] = q1[0], p1[0]
    return out


def latest_state2(lp: pd.Series, mlp: Optional[pd.Series] = None) -> Optional[dict]:
    """가격 이력의 마지막 날 상태(1판 x·s + 변동성 회귀 입력 hx + 순위 매길 값 xs). 이력이 모자라면 None."""
    st = V.latest_state(lp, mlp)
    if st is None:
        return None
    row = asset_frame2(lp).iloc[-1]
    hx = [float(row[c]) for c in HX_OWN]
    if mlp is not None:
        ms = market_state2(mlp).reindex(lp.index).ffill().iloc[-1]
        hx += [float(ms["m21"]), float(ms["m252"])]
    st.update(hx=hx, xs=[float(row[c]) for c in XS])
    return st
