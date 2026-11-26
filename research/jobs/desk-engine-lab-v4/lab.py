"""판단 엔진 공용 코드 4판 (desk-engine-lab-v4) — 3판(desk-engine-lab-v3/lab.py) 위에 세 가지를 바꾼다.

규칙은 SPEC.md 에 고정되어 있다(결과를 보기 전에 고정 — 바꾸려면 새 id). 1판·2판·3판 파일은 고치지 않고 그대로 불러 쓴다:
  1) dd_logit / ddlogit_block : 낙폭 확률 전문가 DDLOGIT — HAR 확률을 출발점으로 상태에 따라 고치는 벌점 로지스틱 회귀
  2) stack_quantile / stack_event / stack_weights : 쌓기 — 실현된 과거에서 **섞은 결과의 손실**이 가장 작아지게 전문가를 하나씩 더해 가중을 정한다
  3) walk4 : 3판 걸어 나가기(walk3, 값 그대로) 뒤에 4판을 얹는다. STK4(쌓기) → CAL4(범위 보정) → V4(둘을 다시 쌓기)
  4) score_layer4, forecast_live4 — 4판은 재무 자료 없이 예측한다(FUND 를 쓰지 않는다)
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

LAB_VERSION = "desk-engine-lab/v4"
DL_RIDGE = 0.05          # DDLOGIT 벌점: 출발점(HAR 확률)의 정보량 Σp(1−p) 의 5%
DL_CLIP = 1.5            # DDLOGIT 이 HAR 확률의 로짓을 고칠 수 있는 한도
DL_MIN_EVENTS = 20       # 서고에 사건·비사건이 각각 이만큼 있어야 회귀한다
DL_ITERS = 8             # 뉴턴 반복 횟수(고정)
DL_EPS = 1e-4            # 확률을 로짓으로 바꿀 때의 안쪽 한도
STACK_PICKS = 10         # 쌓기에서 더하는 횟수(가중은 1/10 단위 이하)
_HERE = Path(__file__).resolve().parent


def v3():
    """3판 lab 모듈(고치지 않는다)."""
    name = "desk_engine_lab_v3"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _HERE.parent / "desk-engine-lab-v3" / "lab.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L3 = v3()
L2, V = L3.L2, L3.V
HORIZONS, TAUS, EVENTS, KINDS, H = V.HORIZONS, V.TAUS, V.EVENTS, V.KINDS, V.H
_TAU = np.array(TAUS)
POOL4 = ("CLIM", "VOL", "HAR", "ANALOG_H", "TILT_H", "SIXTH_H", "DDLOGIT")   # 4판 쌓기에 들어가는 전문가(FUND 는 뺀다)
MODELS = L3.MODELS + ("DDLOGIT", "STK4", "CAL4", "V4")                      # 앞 16개는 3판 그대로
M3, M, KP4 = L3.M, len(MODELS), len(POOL4)
I_DDL, I_STK4, I_CAL4, I_V4 = range(M3, M3 + 4)
I_HAR, I_ENS1, I_V3 = L3.I_HAR, L3.I_ENS1, L3.I_V3
POOL4_IDX = np.array([MODELS.index(e) for e in POOL4])
I_DD = 1 + EVENTS.index("dd15")                                              # 종류 번호(0 = 분위수)


# ---------------------------------------------------------------- 1) 낙폭 확률 전문가
def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, DL_EPS, 1.0 - DL_EPS)
    return np.log(p / (1.0 - p))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))


def dd_logit(Ul: np.ndarray, yl: np.ndarray, pl: np.ndarray, Uq: np.ndarray, pq: np.ndarray) -> Optional[np.ndarray]:
    """로짓(p) = 로짓(HAR 확률) + a + c·표준화한 로짓 + Σ b·(상태 순위 − 0.5)√12 — a 를 뺀 계수에 벌점. 질의의 확률 [Q].

    Ul·Uq 는 상태의 서고 내 순위(0~1), yl 은 서고의 사건(0/1), pl·pq 는 HAR 확률. 사건이 모자라거나 계산이 깨지면 None(→ HAR 그대로)."""
    n1 = float(yl.sum())
    if n1 < DL_MIN_EVENTS or len(yl) - n1 < DL_MIN_EVENTS:
        return None
    gl, gq = _logit(pl), _logit(pq)
    mu, sd = float(gl.mean()), float(gl.std())
    z = (lambda g: (g - mu) / sd) if sd > 1e-9 else (lambda g: np.zeros(len(g)))
    Al = np.column_stack([np.ones(len(gl)), z(gl), (Ul - 0.5) * math.sqrt(12.0)])
    Aq = np.column_stack([np.ones(len(gq)), z(gq), (Uq - 0.5) * math.sqrt(12.0)])
    p0 = _sigmoid(gl)
    pen = DL_RIDGE * float((p0 * (1.0 - p0)).sum()) * np.eye(Al.shape[1])
    pen[0, 0] = 0.0
    beta = np.zeros(Al.shape[1])
    for _ in range(DL_ITERS):
        p = _sigmoid(gl + Al @ beta)
        w = p * (1.0 - p)
        try:
            beta = beta + np.linalg.solve((Al * w[:, None]).T @ Al + pen + 1e-9 * np.eye(len(beta)), Al.T @ (yl - p) - pen @ beta)
        except np.linalg.LinAlgError:
            return None
        if not np.isfinite(beta).all():
            return None
    return _sigmoid(gq + np.clip(Aq @ beta, -DL_CLIP, DL_CLIP))


def ddlogit_block(lib: dict, Xq: np.ndarray, Sq: np.ndarray, HXq: np.ndarray) -> np.ndarray:
    """질의의 DDLOGIT 낙폭 확률 [Q, 기간]. 회귀하지 못한 기간은 NaN(호출한 쪽이 HAR 확률을 그대로 둔다)."""
    out = np.full((len(Xq), H), np.nan)
    if not len(Xq) or len(lib["X"]) < V.MIN_LIB:
        return out
    Sl3, Sq3 = L3.har_base(lib, HXq, Sq)
    cols = [np.sort(lib["X"][:, j]) for j in range(lib["X"].shape[1])]
    Ul, Uq = V._ecdf_u(cols, lib["X"]), V._ecdf_u(cols, Xq)
    for hi in range(H):
        mh = np.isfinite(lib["RET"][:, hi]) & np.isfinite(lib["MN"][:, hi])
        if int(mh.sum()) < V.MIN_LIB:
            continue
        mn, sl = lib["MN"][mh, hi], Sl3[mh, hi]
        zm = np.sort(mn / sl)
        p = dd_logit(Ul[mh], (mn <= V.DD_LOG).astype(float), V._u_le(zm, V.DD_LOG / sl), Uq, V._u_le(zm, V.DD_LOG / Sq3[:, hi]))
        if p is not None:
            out[:, hi] = p
    return out


# ---------------------------------------------------------------- 2) 쌓기
def _picked(counts_at_best: Optional[np.ndarray], k: int) -> np.ndarray:
    return np.full(k, 1.0 / k) if counts_at_best is None else counts_at_best / counts_at_best.sum()


def stack_quantile(F: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """F[점, 전문가, 분위수], y[점], w[점](합 1). 전문가를 하나씩(같은 전문가를 다시 골라도 된다) STACK_PICKS 번 더하면서
    섞은 분위수의 가중 평균 핀볼 손실이 가장 작았던 시점의 구성 → 가중[전문가]. 첫 번째는 가장 나은 한 명이다."""
    n, k, _ = F.shape
    S, counts, best, best_counts = np.zeros((n, F.shape[2])), np.zeros(k), np.inf, None
    for m in range(STACK_PICKS):
        e = y[:, None, None] - (S[:, None, :] + F) / (m + 1)
        loss = w @ np.maximum(_TAU * e, (_TAU - 1) * e).mean(axis=-1)
        j = int(np.argmin(loss))
        counts[j] += 1
        S += F[:, j]
        if loss[j] < best:
            best, best_counts = float(loss[j]), counts.copy()
    return _picked(best_counts, k)


def stack_event(Pm: np.ndarray, t: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Pm[점, 전문가] 확률, t[점] 0/1, w[점](합 1). 같은 쌓기를 가중 평균 브라이어 손실로(2차식이라 합계만으로 계산)."""
    k = Pm.shape[1]
    A, b = (Pm * w[:, None]).T @ Pm, Pm.T @ (w * t)
    counts, best, best_counts = np.zeros(k), np.inf, None
    for m in range(STACK_PICKS):
        loss = (counts @ A @ counts + 2.0 * (A @ counts) + np.diag(A)) / (m + 1) ** 2 - 2.0 * (b @ counts + b) / (m + 1)
        j = int(np.argmin(loss))
        counts[j] += 1
        if loss[j] < best:
            best, best_counts = float(loss[j]), counts.copy()
    return _picked(best_counts, k)


def date_weights(ok: np.ndarray, block: np.ndarray) -> tuple:
    """쓸 수 있는 점(ok)에 기준일마다 같은 무게(기준일 안에서는 점마다 같게). (가중[점] 합 1, 쓸 수 있는 기준일 수)."""
    cnt = np.bincount(block[ok], minlength=int(block.max()) + 1 if len(block) else 0)
    nd = int((cnt > 0).sum())
    w = np.zeros(len(ok))
    if nd:
        w[ok] = 1.0 / (cnt[block[ok]] * nd)
    return w, nd


class History:
    """기간마다 실현이 끝난 점의 번호와 그 점이 속한 기준일 묶음 번호."""

    def __init__(self):
        self.idx = [np.zeros(0, np.int64) for _ in range(H)]
        self.block = [np.zeros(0, np.int64) for _ in range(H)]
        self.nb = [0] * H
        self.version = [0] * H

    def add(self, hi: int, idx: np.ndarray) -> None:
        if len(idx):
            self.idx[hi] = np.concatenate([self.idx[hi], idx])
            self.block[hi] = np.concatenate([self.block[hi], np.full(len(idx), self.nb[hi], np.int64)])
            self.nb[hi] += 1
            self.version[hi] += 1


def stack_weights_h(FQ: np.ndarray, FP: np.ndarray, y: np.ndarray, truth: np.ndarray, hist: History, hi: int, models: np.ndarray) -> np.ndarray:
    """한 기간의 쌓기 가중 [종류 4, 전문가]. 실현 기준일이 MIN_DATES 미만인 종류는 같은 가중."""
    k = len(models)
    Wt = np.full((len(KINDS), k), 1.0 / k)
    idx, block = hist.idx[hi], hist.block[hi]
    if not len(idx):
        return Wt
    F = FQ[idx[:, None], models[None, :], hi].astype(float)
    yy = y[idx, hi]
    w, nd = date_weights(np.isfinite(F).all(axis=(1, 2)) & np.isfinite(yy), block)
    if nd >= L2.MIN_DATES:
        ok = w > 0
        Wt[0] = stack_quantile(F[ok], yy[ok], w[ok])
    Pm = FP[idx[:, None], models[None, :], hi].astype(float)
    for e in range(len(EVENTS)):
        t = truth[idx, hi, e]
        w, nd = date_weights(np.isfinite(Pm[:, :, e]).all(axis=1) & np.isfinite(t), block)
        if nd >= L2.MIN_DATES:
            ok = w > 0
            Wt[1 + e] = stack_event(Pm[ok][:, :, e], t[ok], w[ok])
    return Wt


def blend_weights_h(FQ: np.ndarray, y: np.ndarray, hist: History, hi: int) -> np.ndarray:
    """보정 전(STK4)·후(CAL4) 분위수를 같은 쌓기로 섞는 가중 [2]. 보정이 시작된 뒤 실현된 기준일이 MIN_DATES 미만이면 반반."""
    idx = hist.idx[hi]
    if not len(idx):
        return np.array([0.5, 0.5])
    F = FQ[idx[:, None], np.array([I_STK4, I_CAL4])[None, :], hi].astype(float)
    yy = y[idx, hi]
    w, nd = date_weights(np.isfinite(F).all(axis=(1, 2)) & np.isfinite(yy), hist.block[hi])
    if nd < L2.MIN_DATES:
        return np.array([0.5, 0.5])
    ok = w > 0
    return stack_quantile(F[ok], yy[ok], w[ok])


def assemble4(FQp: np.ndarray, FPp: np.ndarray, S3q: np.ndarray, weights4: np.ndarray, shifts4: np.ndarray, blend4: np.ndarray,
              active: np.ndarray) -> tuple:
    """쌓기에 들어가는 전문가 예측 FQp[Q, 7, 기간, 분위수]·FPp[Q, 7, 기간, 사건] → (STK4 분위수, STK4 확률, CAL4 분위수, V4 분위수).

    weights4[기간, 종류, 전문가 7], shifts4[기간, 분위수], blend4[기간, 2] = (STK4, CAL4) 가중, active[기간] = 보정이 시작됐나. V4 확률은 STK4 확률이다."""
    q, p = V.combine(FQp, FPp, weights4)
    qc = L2.apply_shift(q, S3q, np.where(active[:, None], shifts4, 0.0))
    qv = np.where(active[None, :, None], blend4[None, :, 0, None] * q + blend4[None, :, 1, None] * qc, q)
    return q, p, qc, qv


# ---------------------------------------------------------------- 3) 걸어 나가기
def walk4(P: dict, progress: Optional[Callable[[int, int], None]] = None, out3: Optional[dict] = None) -> dict:
    """3판 걸어 나가기(walk3 — 앞 16개 모형은 값 그대로) 뒤에, 같은 기준일 순서로 DDLOGIT·STK4·CAL4·V4 를 그날까지 실현된 자료만으로 계산한다."""
    o3 = L3.walk3(P, progress) if out3 is None else out3
    n = len(P["date"])
    out = {"FQ": np.full((n, M, H, len(TAUS)), np.nan, np.float32), "FP": np.full((n, M, H, len(EVENTS)), np.nan, np.float32),
           "LQ": np.full((n, M, H), np.nan), "LB": np.full((n, M, H, len(EVENTS)), np.nan), "S3": o3["S3"], "CA4": np.zeros((n, H), bool)}
    for k in ("FQ", "FP", "LQ", "LB"):
        out[k][:, :M3] = o3[k]
    FQ, FP, S3 = out["FQ"], out["FP"], out["S3"]
    FQ[:, I_DDL], FP[:, I_DDL] = FQ[:, I_HAR], FP[:, I_HAR]            # 기본은 HAR 과 같고, 낙폭 확률만 회귀가 되면 덮어쓴다
    truth = V.event_truth(P["RET"], P["MN"], P["EX"])
    hist, histb, cal4 = History(), History(), L3.Calib3()
    pending: list = [[] for _ in range(H)]
    wcache = [(-1, np.full((len(KINDS), KP4), 1.0 / KP4)) for _ in range(H)]
    bcache = [(-1, np.array([0.5, 0.5])) for _ in range(H)]

    def settle(hi: int, pa: int, pb: int, rows: Optional[np.ndarray] = None) -> None:
        idx = np.arange(pa, pb) if rows is None else np.arange(pa, pb)[rows]
        hist.add(hi, idx)
        cal4.add(hi, P["RET"][idx, hi], FQ[idx, I_STK4, hi].astype(float), S3[idx, hi])
        if out["CA4"][pa, hi]:
            histb.add(hi, idx)

    def weights() -> np.ndarray:
        for hi in range(H):
            if wcache[hi][0] != hist.version[hi]:
                wcache[hi] = (hist.version[hi], stack_weights_h(FQ, FP, P["RET"], truth, hist, hi, POOL4_IDX))
        return np.array([w for _, w in wcache])

    def blend() -> np.ndarray:
        for hi in range(H):
            if bcache[hi][0] != histb.version[hi]:
                bcache[hi] = (histb.version[hi], blend_weights_h(FQ, P["RET"], histb, hi))
        return np.array([w for _, w in bcache])

    udates, starts = np.unique(P["date"], return_index=True)
    stops = np.append(starts[1:], n)
    for i, (D, a, b) in enumerate(zip(udates, starts, stops)):
        for hi in range(H):
            while pending[hi] and pending[hi][0][0] <= D:
                _, pa, pb = heapq.heappop(pending[hi])
                settle(hi, pa, pb)
        cand = L2.lib_index(P, a, D)
        if cand is not None:
            dd = ddlogit_block(L3.library3(P, cand, D), P["X"][a:b], P["S"][a:b], P["HX"][a:b])
            FP[a:b, I_DDL, :, I_DD - 1] = np.where(np.isfinite(dd), dd, FP[a:b, I_HAR, :, I_DD - 1])
            act = cal4.active()
            q, p, qc, qv = assemble4(FQ[a:b, POOL4_IDX].astype(float), FP[a:b, POOL4_IDX].astype(float), S3[a:b], weights(), cal4.shifts(),
                                     blend(), act)
            out["CA4"][a:b] = act[None, :]
            for idx, qq in ((I_STK4, q), (I_CAL4, qc), (I_V4, qv)):
                FQ[a:b, idx], FP[a:b, idx] = qq, p
            y = P["RET"][a:b]
            for e in range(M3, M):
                out["LQ"][a:b, e] = V.pinball(y, FQ[a:b, e].astype(float))
                out["LB"][a:b, e] = (FP[a:b, e].astype(float) - truth[a:b]) ** 2
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
    out.update(weights1=o3["weights1"], weights4=weights(), shifts4=cal4.shifts(), blend4=blend(), cal_active4=cal4.active(),
               realized_dates=np.array(hist.nb), blend_dates=np.array(histb.nb), weights3=o3["weights3"], shifts3=o3["shifts3"],
               blend=o3["blend"], cal_active=o3["cal_active"], weights2=o3["weights2"], shifts2=o3["shifts2"])
    return out


# ---------------------------------------------------------------- 4) 점수
COMPARES = (("vs_clim", I_V4, 0), ("vs_v1", I_V4, I_ENS1), ("vs_v3", I_V4, I_V3), ("v3_vs_v1", I_V3, I_ENS1), ("v1_vs_clim", I_ENS1, 0),
            ("stk4_vs_v1", I_STK4, I_ENS1), ("vs_har", I_V4, I_HAR), ("ddl_vs_har", I_DDL, I_HAR))
COVERAGE = (I_ENS1, I_V3, I_STK4, I_CAL4, I_V4)


def score_layer4(P: dict, out: dict, eras: list, judged_end: str, alpha_family: float) -> dict:
    """칸(기간 × 종류)마다: V4 대 CLIM(표시 등급)·V4 대 ENS1(판정)·V4 대 V3·V3 대 ENS1(3판 재현)·ENS1 대 CLIM·STK4 대 ENS1(보정 전)·
    V4 대 HAR·DDLOGIT 대 HAR, 모형별 기량, 구간 적중."""
    cells = {}
    first, last = np.datetime64(eras[0][1]), np.datetime64(eras[-1][2])
    for hi, h in enumerate(HORIZONS):
        for k, kind in enumerate(KINDS):
            L = L2.cell_loss(out, hi, k)
            if not np.isfinite(L[:, I_V4]).any():
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


# ---------------------------------------------------------------- 5) 모형 저장·실시간 예측
def export_library4(P: dict) -> pd.DataFrame:
    """자료 끝 시점의 서고. 4판은 재무를 쓰지 않으므로 2판 서고 열 그대로다."""
    return L2.export_library2(P)


def library_from_frame4(df: pd.DataFrame) -> dict:
    lib = L2.library_from_frame2(df[[c for c in df.columns if not c.startswith("fr_")]])
    lib["FR"] = np.full((len(df), len(L3.FX)), np.nan)
    return lib


def forecast_live4(lib: dict, layer: dict, state: dict, blib: Optional[dict] = None) -> dict:
    """자산 하나의 지금 예측. layer = model.json 의 층(가중·이동·격자), state = L2.latest_state2 결과. 재무 자료는 필요 없다.

    결과: 전문가·ENS1·STK4·CAL4·V4 의 분위수(로그 수익)와 확률, 4판이 쓴 가중."""
    x, s, hx = (np.asarray(state[k], float)[None, :] for k in ("x", "s", "hx"))
    sixth = layer["sixth"]
    xr = L3._to_rank(state["xs"], layer.get("xs_grid"), 0.5) if sixth == "XRANK" else np.full((1, len(L2.XS)), 0.5)
    FQ3, FP3, S3q, info = L3.forecast_block3(lib, x, s, hx, xr, np.full((1, len(L3.FX)), np.nan), sixth, blib)
    FQ = np.concatenate([FQ3, FQ3[:, [I_HAR]]], axis=1)
    FP = np.concatenate([FP3, FP3[:, [I_HAR]]], axis=1)
    dd = ddlogit_block(lib, x, s, hx)
    FP[:, -1, :, I_DD - 1] = np.where(np.isfinite(dd), dd, FP[:, -1, :, I_DD - 1])
    names = [sixth if e == "SIXTH" else f"{sixth}_H" if e == "SIXTH_H" else e for e in L3.EXPERTS3] + ["DDLOGIT"]
    pool = [names.index(f"{sixth}_H" if e == "SIXTH_H" else e) for e in POOL4]
    a = lambda k: np.asarray(layer[k], float)  # noqa: E731
    q, p, qc, qv = assemble4(FQ[:, pool], FP[:, pool], S3q, a("weights4"), a("shifts4"), a("blend4"), np.asarray(layer["cal_active4"], bool))
    q1, p1 = V.combine(FQ[:, :L3.K1], FP[:, :L3.K1], a("weights1"))
    return {"q": {e: FQ[0, i] for i, e in enumerate(names)} | {"ENS1": q1[0], "STK4": q[0], "CAL4": qc[0], "V4": qv[0]},
            "p": {e: FP[0, i] for i, e in enumerate(names)} | {"ENS1": p1[0], "STK4": p[0], "CAL4": p[0], "V4": p[0]},
            "n": info["n"], "weights": a("weights4")}
