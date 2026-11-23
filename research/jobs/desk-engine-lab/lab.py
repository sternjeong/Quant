"""판단 엔진 공용 코드 (desk-engine-lab) — 자산 하나의 '앞으로 h 거래일' 수익 분포와 사건 확률을 내는 예측 엔진.

규칙은 SPEC.md 에 고정되어 있다(결과를 보기 전에 고정 — 바꾸려면 새 id). 이 파일은 계산만 한다:
  1) asset_frame      : 총수익 가격 → 상태 특징·변동성 축척·앞으로의 결과
  2) build_points     : (자산, 기준일) 점 표
  3) forecast_block   : 서고(과거 점)로 전문가 4명(CLIM·VOL·ANALOG·TILT)의 예측
  4) walk             : 걸어 나가기(기준일까지 실현된 결과만 사용) + 온라인 가중 앙상블(ENS)
  5) score / grade    : 손실·기량·부호 뒤집기 검정·근거 등급
  6) export_model / forecast_live : 실시간 판단판이 쓰는 모형 저장·읽기
numpy·pandas 만 쓴다. 주문·엔진과 연결되어 있지 않다.
"""

from __future__ import annotations

import heapq
import math
from typing import Callable, Optional

import numpy as np
import pandas as pd

LAB_VERSION = "desk-engine-lab/v1"
SEED = 20261123
HORIZONS = (21, 63, 126, 252)                # 1·3·6·12개월(거래일)
TAUS = (0.1, 0.25, 0.5, 0.75, 0.9)
EVENTS = ("up", "dd15", "beat")              # 수익 > 0 / 기간 중 저점이 기준일보다 15% 이상 아래 / 시장보다 높은 수익
STEP = 21                                    # 기준일 간격(거래일)
EWMA_LAMBDA = 0.94
EWMA_W = {21: 0.7, 63: 0.5, 126: 0.35, 252: 0.25}   # 변동성 예측에서 최근(EWMA) 분산의 비중, 나머지는 252일 분산
DD_LOG = math.log(0.85)
OWN = ("dd", "mom", "trend", "volr", "rev")  # 자기 특징
MKT = ("mdd", "mvolr")                       # 시장 상태(업종·종목 층에만)
CAP = 12000                                  # 서고에서 쓰는 점 수 상한(고정 난수 우선순위로 고름)
MIN_LIB = 250                                # 예측에 필요한 최소 서고 점 수(기간별)
B0, B_GROW, B_STEPS, ESS_MIN = 0.15, 1.25, 8, 60.0   # 유사 사례 띠폭: 유효 표본이 60 이 될 때까지 1.25 배씩 넓힘
RIDGE = 0.1
TILT_CLIP = 0.5                              # 기울기 전문가의 이동 한도(변동성 단위)
KAPPA = 50.0                                 # 앙상블 가중: 손실이 기준선의 1% 만큼 나쁘면 가중 e^-0.5 배
WARM_POINTS = 200                            # 실현된 예측이 이만큼 쌓이기 전에는 같은 가중
EXPERTS = ("CLIM", "VOL", "ANALOG", "TILT")
ALL = EXPERTS + ("ENS",)
KINDS = ("q",) + EVENTS                      # 가중을 따로 두는 점수 종류(분위수 / 사건 셋)
GRADES = ("강함", "보통", "약함", "없음")
MC_DRAWS = 20000
EXACT_MAX = 16
H = len(HORIZONS)
_TAU = np.array(TAUS)


# ---------------------------------------------------------------- 1) 특징·결과
def asset_frame(lp: pd.Series, mlp: Optional[pd.Series] = None) -> pd.DataFrame:
    """로그 총수익 가격(날짜 색인) → 날짜별 특징·축척·앞으로의 결과. 특징은 그날 종가까지, 결과는 그 뒤 자료다."""
    s = lp.astype(float)
    r = s.diff()
    ew = r.pow(2).ewm(alpha=1 - EWMA_LAMBDA, adjust=False, min_periods=60).mean()
    v252 = r.rolling(252, min_periods=200).std()
    v21 = r.rolling(21, min_periods=15).std()
    f = pd.DataFrame(index=s.index)
    f["dd"] = s - s.rolling(252, min_periods=200).max()
    f["mom"] = (s.shift(21) - s.shift(252)) / (v252 * math.sqrt(231))
    f["trend"] = s - np.log(np.exp(s - s.max()).rolling(200, min_periods=160).mean()) - s.max()
    with np.errstate(divide="ignore", invalid="ignore"):
        f["volr"] = np.log(v21 / v252)
    f["rev"] = (s - s.shift(21)) / (v252 * math.sqrt(21))
    rev = s.iloc[::-1]
    dates = pd.Series(s.index, index=s.index)
    m = None if mlp is None else mlp.reindex(s.index).astype(float)
    for h in HORIZONS:
        var = EWMA_W[h] * ew + (1 - EWMA_W[h]) * v252 ** 2
        f[f"s{h}"] = np.sqrt(var.where(var > 1e-10)) * math.sqrt(h)
        f[f"ret{h}"] = s.shift(-h) - s
        f[f"mn{h}"] = rev.rolling(h, min_periods=h).min().iloc[::-1].shift(-1) - s
        f[f"ex{h}"] = np.nan if m is None else f[f"ret{h}"] - (m.shift(-h) - m)
        f[f"end{h}"] = dates.shift(-h)
    return f


def market_state(mlp: pd.Series) -> pd.DataFrame:
    f = asset_frame(mlp)
    return f[["dd", "volr"]].rename(columns={"dd": "mdd", "volr": "mvolr"})


def feature_names(with_market: bool) -> tuple:
    return OWN + (MKT if with_market else ())


# ---------------------------------------------------------------- 2) 점 표
def build_points(frames: dict, origins: pd.DatetimeIndex, with_market: bool,
                 member: Optional[Callable[[str, pd.Timestamp], bool]] = None, seed: int = SEED) -> dict:
    """{자산: asset_frame(+시장 상태)} → (자산, 기준일) 점 표. 특징·축척이 모두 유한한 점만. 날짜순(같은 날은 자산 이름순)."""
    feats = feature_names(with_market)
    names = sorted(frames)
    parts = []
    for k, name in enumerate(names):
        f = frames[name]
        g = f.loc[f.index.intersection(origins)]
        if member is not None and len(g):
            g = g[[bool(member(name, d)) for d in g.index]]
        cols = list(feats) + [f"s{h}" for h in HORIZONS]
        g = g[np.isfinite(g[cols].to_numpy(dtype=float)).all(axis=1)]
        if len(g):
            parts.append(g.assign(_asset=k))
    if not parts:
        return empty_points(feats, names)
    t = pd.concat(parts)
    t = t.assign(_date=t.index).sort_values(["_date", "_asset"], kind="stable")
    P = {"feats": feats, "names": names,
         "asset": t["_asset"].to_numpy(dtype=np.int32),
         "date": t["_date"].to_numpy(dtype="datetime64[D]"),
         "X": t[list(feats)].to_numpy(dtype=float),
         "S": t[[f"s{h}" for h in HORIZONS]].to_numpy(dtype=float),
         "RET": t[[f"ret{h}" for h in HORIZONS]].to_numpy(dtype=float),
         "MN": t[[f"mn{h}" for h in HORIZONS]].to_numpy(dtype=float),
         "EX": t[[f"ex{h}" for h in HORIZONS]].to_numpy(dtype=float),
         "END": np.stack([t[f"end{h}"].to_numpy(dtype="datetime64[D]") for h in HORIZONS], axis=1)}
    P["prio"] = np.random.default_rng(seed).random(len(P["date"]))
    return P


def empty_points(feats: tuple, names: list) -> dict:
    z = np.zeros((0, H))
    return {"feats": feats, "names": names, "asset": np.zeros(0, np.int32), "date": np.zeros(0, "datetime64[D]"),
            "X": np.zeros((0, len(feats))), "S": z, "RET": z.copy(), "MN": z.copy(), "EX": z.copy(),
            "END": np.zeros((0, H), "datetime64[D]"), "prio": np.zeros(0)}


# ---------------------------------------------------------------- 3) 전문가 예측
def _ecdf_u(sorted_cols: list, X: np.ndarray) -> np.ndarray:
    n = len(sorted_cols[0])
    return np.stack([np.searchsorted(c, X[:, j], side="right") / n for j, c in enumerate(sorted_cols)], axis=1)


def kernel_weights(Uq: np.ndarray, Ul: np.ndarray) -> tuple:
    """가우스 핵 가중(Q×N)과 질의별 띠폭. 유효 표본 수가 ESS_MIN 이 될 때까지 띠폭을 넓힌다."""
    Uq32, Ul32 = Uq.astype(np.float32), Ul.astype(np.float32)
    d2 = (Uq32 ** 2).sum(1)[:, None] + (Ul32 ** 2).sum(1)[None, :] - 2.0 * (Uq32 @ Ul32.T)
    np.maximum(d2, 0.0, out=d2)
    Q = len(Uq)
    W = np.empty_like(d2)
    b = np.full(Q, B0)
    todo = np.arange(Q)
    for step in range(B_STEPS + 1):
        w = np.exp(-d2[todo] / (2.0 * (b[todo, None] ** 2)).astype(np.float32))
        W[todo] = w
        s1 = w.sum(1, dtype=np.float64)
        ess = s1 ** 2 / np.maximum((w.astype(np.float64) ** 2).sum(1), 1e-300)
        todo = todo[ess < ESS_MIN]
        if not len(todo) or step == B_STEPS:
            break
        b[todo] *= B_GROW
    return W, b


def _uq(sorted_vals: np.ndarray, taus: np.ndarray) -> np.ndarray:
    """같은 가중 표본의 분위수(경험 분포의 왼쪽 역함수)."""
    n = len(sorted_vals)
    return sorted_vals[np.clip(np.ceil(taus * n).astype(int) - 1, 0, n - 1)]


def _u_le(sorted_vals: np.ndarray, thr) -> np.ndarray:
    return np.searchsorted(sorted_vals, thr, side="right") / len(sorted_vals)


def _wcdf(W: np.ndarray, order: np.ndarray) -> np.ndarray:
    C = np.cumsum(W[:, order], axis=1, dtype=np.float64)
    return C / np.maximum(C[:, -1:], 1e-300)


def _wq(C: np.ndarray, sorted_vals: np.ndarray) -> np.ndarray:
    return np.stack([sorted_vals[(C >= t - 1e-12).argmax(axis=1)] for t in TAUS], axis=1)


def _w_le(C: np.ndarray, sorted_vals: np.ndarray, thr) -> np.ndarray:
    pos = np.searchsorted(sorted_vals, thr, side="right")
    pos = np.broadcast_to(pos, (C.shape[0],))
    return np.where(pos > 0, C[np.arange(C.shape[0]), np.maximum(pos - 1, 0)], 0.0)


def _ridge_shift(Ul: np.ndarray, y: np.ndarray, Uq: np.ndarray) -> np.ndarray:
    mu, ym = Ul.mean(0), y.mean()
    Xc = Ul - mu
    beta = np.linalg.solve(Xc.T @ Xc + RIDGE * len(y) * np.eye(Xc.shape[1]), Xc.T @ (y - ym))
    return np.clip((Uq - mu) @ beta, -TILT_CLIP, TILT_CLIP)


def forecast_block(lib: dict, Xq: np.ndarray, Sq: np.ndarray) -> tuple:
    """서고(X,S,RET,MN,EX — 쓰면 안 되는 결과는 NaN)로 질의 Q개의 전문가 예측.

    FQ[Q, 전문가 4, 기간, 분위수 5] = 로그 수익 분위수, FP[Q, 전문가 4, 기간, 사건 3] = 확률. 서고가 모자란 기간은 NaN."""
    Q = len(Xq)
    FQ = np.full((Q, len(EXPERTS), H, len(TAUS)), np.nan)
    FP = np.full((Q, len(EXPERTS), H, len(EVENTS)), np.nan)
    info = {"n": [0] * H, "band": None}
    if len(lib["X"]) < MIN_LIB or not Q:
        return FQ, FP, info
    cols = [np.sort(lib["X"][:, j]) for j in range(lib["X"].shape[1])]
    Ul, Uq = _ecdf_u(cols, lib["X"]), _ecdf_u(cols, Xq)
    W, band = kernel_weights(Uq, Ul)
    info["band"] = band
    for hi in range(H):
        mh = np.isfinite(lib["RET"][:, hi]) & np.isfinite(lib["MN"][:, hi])
        n = int(mh.sum())
        info["n"][hi] = n
        if n < MIN_LIB:
            continue
        raw, rmn, sc, ex = lib["RET"][mh, hi], lib["MN"][mh, hi], lib["S"][mh, hi], lib["EX"][mh, hi]
        zr, zm, zx = raw / sc, rmn / sc, ex / sc
        has_ex = bool(np.isfinite(zx).all())
        sq = Sq[:, hi]
        Wh, Uh = W[:, mh], Ul[mh]
        o_r, o_m = np.argsort(zr, kind="stable"), np.argsort(zm, kind="stable")
        zr_s, zm_s = zr[o_r], zm[o_m]
        # CLIM — 과거 평균 분포(변동성 무시)
        FQ[:, 0, hi] = _uq(np.sort(raw), _TAU)[None, :]
        FP[:, 0, hi, 0] = float((raw > 0).mean())
        FP[:, 0, hi, 1] = float((rmn <= DD_LOG).mean())
        # VOL — 지금 변동성으로 축척
        qz = _uq(zr_s, _TAU)
        FQ[:, 1, hi] = qz[None, :] * sq[:, None]
        FP[:, 1, hi, 0] = float((zr > 0).mean())
        FP[:, 1, hi, 1] = _u_le(zm_s, DD_LOG / sq)
        # ANALOG — 지금과 닮은 과거 상태
        C = _wcdf(Wh, o_r)
        FQ[:, 2, hi] = _wq(C, zr_s) * sq[:, None]
        FP[:, 2, hi, 0] = 1.0 - _w_le(C, zr_s, 0.0)
        FP[:, 2, hi, 1] = _w_le(_wcdf(Wh, o_m), zm_s, DD_LOG / sq)
        # TILT — 상태에 따른 위치 이동(능형 회귀)
        d = _ridge_shift(Uh, zr, Uq)
        FQ[:, 3, hi] = (qz[None, :] + d[:, None]) * sq[:, None]
        FP[:, 3, hi, 0] = 1.0 - _u_le(zr_s, -d)
        FP[:, 3, hi, 1] = FP[:, 1, hi, 1]
        if has_ex:
            o_x = np.argsort(zx, kind="stable")
            zx_s = zx[o_x]
            FP[:, 0, hi, 2] = float((ex > 0).mean())
            FP[:, 1, hi, 2] = float((zx > 0).mean())
            FP[:, 2, hi, 2] = 1.0 - _w_le(_wcdf(Wh, o_x), zx_s, 0.0)
            FP[:, 3, hi, 2] = 1.0 - _u_le(zx_s, -_ridge_shift(Uh, zx, Uq))
    return FQ, FP, info


def pinball(y: np.ndarray, q: np.ndarray) -> np.ndarray:
    """y[...], q[..., 분위수 5] → 분위수 평균 핀볼 손실."""
    e = y[..., None] - q
    return np.maximum(_TAU * e, (_TAU - 1) * e).mean(axis=-1)


def event_truth(ret: np.ndarray, mn: np.ndarray, ex: np.ndarray) -> np.ndarray:
    """[..., 사건 3] 0/1(모르면 NaN)."""
    out = np.stack([np.where(np.isfinite(ret), ret > 0, np.nan), np.where(np.isfinite(mn), mn <= DD_LOG, np.nan),
                    np.where(np.isfinite(ex), ex > 0, np.nan)], axis=-1)
    return out.astype(float)


def ens_weights(mean_loss: Optional[np.ndarray], n: int) -> np.ndarray:
    """전문가 평균 손실 → 가중. 실현 예측이 WARM_POINTS 미만이거나 손실을 모르면 같은 가중."""
    k = len(EXPERTS)
    if mean_loss is None or n < WARM_POINTS or not np.isfinite(mean_loss).all() or mean_loss[0] <= 0:
        return np.full(k, 1.0 / k)
    w = np.exp(-KAPPA * (mean_loss - mean_loss.min()) / mean_loss[0])
    return w / w.sum()


def combine(FQ: np.ndarray, FP: np.ndarray, Wt: np.ndarray) -> tuple:
    """Wt[기간, 종류 4, 전문가 4] 로 앙상블. 분위수는 분위수별 가중 평균, 확률은 가중 평균."""
    q = np.einsum("qehn,he->qhn", np.nan_to_num(FQ), Wt[:, 0, :])
    q[np.isnan(FQ).any(axis=1)] = np.nan
    p = np.einsum("qehk,hke->qhk", np.nan_to_num(FP), Wt[:, 1:, :])
    p[np.isnan(FP).any(axis=1)] = np.nan
    return q, p


# ---------------------------------------------------------------- 4) 걸어 나가기
class Running:
    """실현된 예측의 손실 누계(기간 × 종류 × 전문가)."""

    def __init__(self):
        self.sum = np.zeros((H, len(KINDS), len(EXPERTS)))
        self.cnt = np.zeros((H, len(KINDS)))

    def add(self, hi: int, lq: np.ndarray, lb: np.ndarray) -> None:
        """lq[점, 전문가], lb[점, 전문가, 사건]."""
        ok = np.isfinite(lq).all(axis=1)
        self.sum[hi, 0] += lq[ok].sum(axis=0)
        self.cnt[hi, 0] += ok.sum()
        for k in range(len(EVENTS)):
            ok = np.isfinite(lb[:, :, k]).all(axis=1)
            self.sum[hi, 1 + k] += lb[ok][:, :, k].sum(axis=0)
            self.cnt[hi, 1 + k] += ok.sum()

    def weights(self) -> np.ndarray:
        Wt = np.empty((H, len(KINDS), len(EXPERTS)))
        for hi in range(H):
            for k in range(len(KINDS)):
                n = int(self.cnt[hi, k])
                Wt[hi, k] = ens_weights(self.sum[hi, k] / n if n else None, n)
        return Wt


def library_at(P: dict, a: int, D) -> Optional[dict]:
    """기준일 D 에 쓸 수 있는 서고: 앞선 점 중 1개월 결과가 D 까지 실현된 것(최대 CAP), 실현 안 된 기간 결과는 NaN."""
    cand = np.where(P["END"][:a, 0] <= D)[0]
    if len(cand) < MIN_LIB:
        return None
    if len(cand) > CAP:
        cand = np.sort(cand[np.argpartition(P["prio"][cand], CAP - 1)[:CAP]])
    seen = P["END"][cand] <= D
    return {"X": P["X"][cand], "S": P["S"][cand], "RET": np.where(seen, P["RET"][cand], np.nan),
            "MN": np.where(seen, P["MN"][cand], np.nan), "EX": np.where(seen, P["EX"][cand], np.nan)}


def walk(P: dict, progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """모든 기준일에서 그날까지 실현된 자료만으로 예측. 결과: 점별 예측·손실, 마지막 가중."""
    n, E = len(P["date"]), len(ALL)
    out = {"FQ": np.full((n, E, H, len(TAUS)), np.nan, np.float32), "FP": np.full((n, E, H, len(EVENTS)), np.nan, np.float32),
           "LQ": np.full((n, E, H), np.nan), "LB": np.full((n, E, H, len(EVENTS)), np.nan)}
    run = Running()
    pending: list = [[] for _ in range(H)]
    truth = event_truth(P["RET"], P["MN"], P["EX"])                       # [점, 기간, 사건]
    udates, starts = np.unique(P["date"], return_index=True)
    stops = np.append(starts[1:], n)
    for i, (D, a, b) in enumerate(zip(udates, starts, stops)):
        for hi in range(H):
            while pending[hi] and pending[hi][0][0] <= D:
                _, pa, pb = heapq.heappop(pending[hi])
                run.add(hi, out["LQ"][pa:pb, :len(EXPERTS), hi], out["LB"][pa:pb, :len(EXPERTS), hi, :])
        lib = library_at(P, a, D)
        if lib is not None:
            FQ, FP, _ = forecast_block(lib, P["X"][a:b], P["S"][a:b])
            q, p = combine(FQ, FP, run.weights())
            out["FQ"][a:b, :len(EXPERTS)], out["FQ"][a:b, -1] = FQ, q
            out["FP"][a:b, :len(EXPERTS)], out["FP"][a:b, -1] = FP, p
            y = P["RET"][a:b]
            for e in range(E):
                out["LQ"][a:b, e] = pinball(y, out["FQ"][a:b, e].astype(float))
                out["LB"][a:b, e] = (out["FP"][a:b, e].astype(float) - truth[a:b]) ** 2
            for hi in range(H):
                ends = P["END"][a:b, hi]
                ends = ends[~np.isnat(ends)]
                if len(ends):
                    heapq.heappush(pending[hi], (ends.max(), int(a), int(b)))
        if progress and (i % 50 == 0 or i == len(udates) - 1):
            progress(i + 1, len(udates))
    # 마지막 가중: 자료 끝까지 실현된 것을 모두 반영
    for hi in range(H):
        for _, pa, pb in pending[hi]:
            done = ~np.isnat(P["END"][pa:pb, hi])
            run.add(hi, out["LQ"][pa:pb, :len(EXPERTS), hi][done], out["LB"][pa:pb, :len(EXPERTS), hi, :][done])
    out["weights"] = run.weights()
    out["realized"] = run.cnt.copy()
    return out


# ---------------------------------------------------------------- 5) 점수·판정
def signflip_p(d: np.ndarray, seed: int = SEED) -> Optional[float]:
    """구획 평균 차이 d 의 평균이 0 보다 큰가(한쪽). 구획 16개 이하는 전수, 넘으면 난수 20,000회."""
    d = np.asarray(d, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 2:
        return None
    obs = d.mean()
    if n <= EXACT_MAX:
        signs = ((np.arange(2 ** n)[:, None] >> np.arange(n)) & 1) * 2.0 - 1.0
        stat = (signs * d).mean(axis=1)
        return float((stat >= obs - 1e-15).mean())
    rng = np.random.default_rng(seed)
    hit = 0
    for _ in range(MC_DRAWS // 2000):
        signs = rng.integers(0, 2, size=(2000, n)) * 2.0 - 1.0
        hit += int(((signs * d).mean(axis=1) >= obs - 1e-15).sum())
    return float((1 + hit) / (1 + MC_DRAWS))


def grade(skill: Optional[float], p: Optional[float], era_skills: list, alpha_family: float) -> str:
    """근거 등급(SPEC 고정): 강함 = p < 족 유의수준 & 모든 시대 양수 / 보통 = p < 0.05 & 모든 시대 양수 / 약함 = 전체 기량 양수 / 없음."""
    if skill is None or not skill > 0:
        return "없음"
    eras_ok = bool(era_skills) and all(s is not None and s > 0 for s in era_skills)
    if p is not None and eras_ok and p < alpha_family:
        return "강함"
    if p is not None and eras_ok and p < 0.05:
        return "보통"
    return "약함"


def _skill(base: float, model: float) -> Optional[float]:
    return None if not (np.isfinite(base) and np.isfinite(model) and base > 0) else float(1.0 - model / base)


def score_cell(P: dict, out: dict, hi: int, kind: int, eras: list, judged_end: str, alpha_family: float,
               min_blocks: int = 5) -> dict:
    """한 칸(기간 × 종류)의 성적. 기준일별 평균 손실 → 달력 구획(1년, 12개월 기간은 2년) → ENS vs CLIM 부호 뒤집기."""
    L = out["LQ"][:, :, hi] if kind == 0 else out["LB"][:, :, hi, kind - 1]         # [점, 전문가 5]
    ok = np.isfinite(L).all(axis=1) & (P["END"][:, hi] <= np.datetime64(judged_end))
    df = pd.DataFrame(L[ok], columns=list(ALL))
    df["date"] = P["date"][ok]
    by = df.groupby("date").mean()
    block_years = 2 if HORIZONS[hi] >= 252 else 1
    years = pd.DatetimeIndex(by.index).year
    res = {"n_points": int(ok.sum()), "n_origins": int(len(by)), "eras": {}}

    def part(sub: pd.DataFrame, yrs: np.ndarray) -> dict:
        if sub.empty:
            return {"n_origins": 0, "n_blocks": 0, "skill": None, "p": None, "skill_vs_vol": None, "p_vs_vol": None, "expert_skill": {}}
        blocks = sub.groupby((yrs // block_years) * block_years).mean()
        m = sub.mean()
        return {"n_origins": int(len(sub)), "n_blocks": int(len(blocks)),
                "skill": _skill(m["CLIM"], m["ENS"]), "p": signflip_p((blocks["CLIM"] - blocks["ENS"]).to_numpy()),
                "skill_vs_vol": _skill(m["VOL"], m["ENS"]), "p_vs_vol": signflip_p((blocks["VOL"] - blocks["ENS"]).to_numpy()),
                "expert_skill": {e: _skill(m["CLIM"], m[e]) for e in ALL[1:]},
                "mean_loss": {e: float(m[e]) for e in ALL}}

    judged = np.zeros(len(by), bool)
    for name, start, end in eras:
        sel = (by.index >= np.datetime64(start)) & (by.index <= np.datetime64(end))
        res["eras"][name] = part(by[sel], years[sel].to_numpy())
        judged |= sel
    res.update(part(by[judged], years[judged].to_numpy()))
    era_sk = [res["eras"][n]["skill"] for n, _, _ in eras]
    res["evaluable"] = bool(res["n_blocks"] >= 2 * min_blocks and all(res["eras"][n]["n_blocks"] >= min_blocks for n, _, _ in eras))
    res["grade"] = grade(res["skill"], res["p"], era_sk, alpha_family) if res["evaluable"] else "없음"
    res["grade_vs_vol"] = grade(res["skill_vs_vol"], res["p_vs_vol"], [res["eras"][n]["skill_vs_vol"] for n, _, _ in eras],
                                alpha_family) if res["evaluable"] else "없음"
    if kind == 0:
        q = out["FQ"][:, -1, hi].astype(float)
        y = P["RET"][:, hi]
        sel = ok & (P["date"] >= np.datetime64(eras[0][1]))
        res["coverage80"] = float(((y[sel] >= q[sel, 0]) & (y[sel] <= q[sel, 4])).mean()) if sel.any() else None
    return res


def score_layer(P: dict, out: dict, eras: list, judged_end: str, alpha_family: float) -> dict:
    cells = {}
    for hi, h in enumerate(HORIZONS):
        for k, name in enumerate(KINDS):
            if k and not np.isfinite(out["LB"][:, -1, hi, k - 1]).any():
                continue
            cells[f"{h}:{name}"] = score_cell(P, out, hi, k, eras, judged_end, alpha_family)
    return cells


# ---------------------------------------------------------------- 6) 모형 저장·실시간 예측
LIB_COLS_FIXED = tuple(f"{c}{h}" for h in HORIZONS for c in ("s", "ret", "mn", "ex"))


def export_library(P: dict) -> pd.DataFrame:
    """자료 끝 시점의 서고(1개월 결과가 있는 점 중 우선순위 낮은 순 CAP 개)."""
    cand = np.where(np.isfinite(P["RET"][:, 0]) & np.isfinite(P["MN"][:, 0]))[0]
    if len(cand) > CAP:
        cand = np.sort(cand[np.argpartition(P["prio"][cand], CAP - 1)[:CAP]])
    df = pd.DataFrame(P["X"][cand], columns=list(P["feats"]))
    for hi, h in enumerate(HORIZONS):
        df[f"s{h}"], df[f"ret{h}"], df[f"mn{h}"], df[f"ex{h}"] = P["S"][cand, hi], P["RET"][cand, hi], P["MN"][cand, hi], P["EX"][cand, hi]
    return df.round(6)


def library_from_frame(df: pd.DataFrame) -> dict:
    feats = [c for c in df.columns if c not in LIB_COLS_FIXED]
    g = lambda c: np.stack([df[f"{c}{h}"].to_numpy(dtype=float) for h in HORIZONS], axis=1)  # noqa: E731
    return {"feats": tuple(feats), "X": df[feats].to_numpy(dtype=float), "S": g("s"), "RET": g("ret"), "MN": g("mn"), "EX": g("ex")}


def forecast_live(lib: dict, weights: np.ndarray, x: np.ndarray, s: np.ndarray) -> dict:
    """자산 하나의 지금 예측. x = 특징(서고와 같은 순서), s = 기간별 축척. 결과는 전문가·앙상블의 분위수(로그 수익)와 확률."""
    FQ, FP, info = forecast_block(lib, np.asarray(x, float)[None, :], np.asarray(s, float)[None, :])
    q, p = combine(FQ, FP, np.asarray(weights, float))
    return {"q": {e: FQ[0, i] for i, e in enumerate(EXPERTS)} | {"ENS": q[0]},
            "p": {e: FP[0, i] for i, e in enumerate(EXPERTS)} | {"ENS": p[0]},
            "n": info["n"], "band": None if info["band"] is None else float(info["band"][0])}


def latest_state(lp: pd.Series, mlp: Optional[pd.Series] = None) -> Optional[dict]:
    """가격 이력의 마지막 날 특징·축척(예측 입력). 이력이 모자라면 None."""
    f = asset_frame(lp)
    row = f.iloc[-1]
    x = [float(row[c]) for c in OWN]
    if mlp is not None:
        ms = market_state(mlp).reindex(lp.index).ffill().iloc[-1]
        x += [float(ms["mdd"]), float(ms["mvolr"])]
    s = [float(row[f"s{h}"]) for h in HORIZONS]
    if not (np.isfinite(x).all() and np.isfinite(s).all()):
        return None
    return {"date": pd.Timestamp(f.index[-1]), "x": x, "s": s}


# ---------------------------------------------------------------- 가짜 자료(스모크·테스트)
def synthetic_panel(n_assets: int = 12, n_days: int = 2600, seed: int = 7, start: str = "2000-01-03") -> tuple:
    """변동성이 뭉치는 가짜 시장과 자산들(로그 가격). 자산마다 변동성 수준이 달라 VOL 전문가가 이길 수 있는 자료."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n_days)

    def path(level: float, beta: float, mret: Optional[np.ndarray]) -> np.ndarray:
        v, out = level ** 2, np.empty(n_days)
        for t in range(n_days):
            e = rng.standard_normal() * math.sqrt(v)
            out[t] = 0.0002 + e + (0.0 if mret is None else beta * mret[t])
            v = 0.05 * level ** 2 + 0.10 * e * e + 0.85 * v
        return out

    mret = path(0.010, 0.0, None)
    m = pd.Series(np.cumsum(mret), index=idx)
    assets = {f"A{k:02d}": pd.Series(np.cumsum(path(0.006 + 0.002 * k, 0.6 + 0.05 * k, mret)), index=idx) for k in range(n_assets)}
    return m, assets
