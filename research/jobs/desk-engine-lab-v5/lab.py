"""판단 엔진 공용 코드 5판 (desk-engine-lab-v5) — 변동성 예측을 고도화한다(HAR-X). 섞기 방식은 3판 그대로.

규칙은 SPEC.md 에 고정되어 있다(결과를 보기 전에 고정 — 바꾸려면 새 id). 1판·2판·3판 파일은 고치지 않고 그대로 불러 쓴다:
  1) extended_frames / extend_points : 2판 변동성 회귀 입력(HX) 뒤에 다섯 열을 더한다 — 1주 변동성, 하락 변동성, 최근 수익(지렛대 효과)과 그 음수 부분, 낙폭
  2) walk5                           : 3판 walk3 를 두 번 돈다 — 원래 점(3판 재현)과 입력을 늘린 점. 전문가·가중·보정 계산은 3판 코드 그대로다
  3) merge                           : 두 걸음의 결과에서 비교에 쓰는 모형 8개를 모은다. V5 = 시장 층은 보정을 섞은 것, 업종·종목 층은 보정 전
  4) score_layer5 / scale_cells      : 예측 손실 비교(판정)와 변동성 예측 자체의 오차 비교(보고)
  5) export·latest_state5·forecast_live5
numpy·pandas 만 쓴다. 주문·엔진과 연결되어 있지 않다.
"""

from __future__ import annotations

import contextlib
import importlib.util
import math
import sys
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

LAB_VERSION = "desk-engine-lab/v5"
EXTRA = ("x5", "xneg")                                 # 가격에서 새로 재는 값: ln 5일 변동성, ln 21일 하락 변동성(일 단위)
HX_ADD = ("d5", "dneg", "lev", "levneg", "ddp")        # 변동성 회귀에 더하는 입력
D_CLIP = 2.0                                           # d5·dneg 는 ln 21일 변동성과의 차이, ±2 안
LEV_CLIP = 4.0                                         # 최근 21일 수익(1년 변동성 단위) ±4 안
DD_CLIP = 1.5                                          # 1년 고점 대비 로그 낙폭 −1.5 ~ 0
DNEG_FILL = -0.5 * math.log(2.0)                       # 하락 변동성을 모를 때: 오르내림이 대칭일 때의 값
VAR_FLOOR = 1e-12
CALIBRATE = {"market": True, "industry": False, "stock": False}   # 범위 보정을 쓰는 층(3·4판에서 같은 방향이던 것을 규칙으로 고정)
MODELS5 = ("CLIM", "ENS1", "HAR", "V3", "HARX", "ENS5", "V3X", "V5")
SCALES = ("V1", "HAR", "HARX")                         # 변동성 예측 비교(보고): 1판 축척, 3판 회귀, 5판 회귀
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
M5 = len(MODELS5)
I_CLIM, I_ENS1, I_HAR, I_V3, I_HARX, I_ENS5, I_V3X, I_V5 = range(M5)
# (5판 모형, 어느 걸음, 3판 모형 색인) — V5 는 merge 에서 층 규칙으로 고른다
_SOURCES = ((I_CLIM, 0, 0), (I_ENS1, 0, L3.I_ENS1), (I_HAR, 0, L3.I_HAR), (I_V3, 0, L3.I_V3),
            (I_HARX, 1, L3.I_HAR), (I_ENS5, 1, L3.I_ENS3), (I_V3X, 1, L3.I_V3))


# ---------------------------------------------------------------- 1) 입력
def extra_frame(lp: pd.Series) -> pd.DataFrame:
    """로그 가격 → 날짜별 ln 5일 변동성·ln 21일 하락 변동성(그날 종가까지)."""
    r = lp.astype(float).diff()
    f = pd.DataFrame(index=lp.index)
    f["x5"] = 0.5 * np.log(np.maximum(r.pow(2).rolling(5, min_periods=4).mean(), VAR_FLOOR))
    f["xneg"] = 0.5 * np.log(np.maximum(r.clip(upper=0.0).pow(2).rolling(21, min_periods=15).mean(), VAR_FLOOR))
    return f


@contextlib.contextmanager
def extended_frames():
    """이 안에서 만든 점 표에는 XE(점별 x5·xneg)가 붙는다. 2판의 점 만들기 코드를 그대로 쓰기 위해 asset_frame2·attach 를 잠시 감싼다
    (점 집합과 2판 열은 바뀌지 않는다 — 열만 더한다)."""
    frame0, attach0 = L2.asset_frame2, L2.attach

    def frame(lp, mlp=None):
        f = frame0(lp, mlp)
        f[list(EXTRA)] = extra_frame(lp)
        return f

    def attach(P, frames, with_market, borrow=None):
        P2 = attach0(P, frames, with_market, borrow)
        XE = np.full((len(P["date"]), len(EXTRA)), np.nan)
        for k, name in enumerate(P["names"]):
            idx = np.where(P["asset"] == k)[0]
            if len(idx):
                XE[idx] = frames[name].reindex(pd.DatetimeIndex(P["date"][idx].astype("datetime64[ns]")))[list(EXTRA)].to_numpy(dtype=float)
        P2["XE"] = XE
        return P2

    L2.asset_frame2, L2.attach = frame, attach
    try:
        yield
    finally:
        L2.asset_frame2, L2.attach = frame0, attach0


def hx_extend(HX: np.ndarray, hx: tuple, XE: np.ndarray, XRAW: np.ndarray) -> np.ndarray:
    """2판 회귀 입력 뒤에 HX_ADD 다섯 열. 새 값을 모르면 중립값으로 채운다 — 회귀를 쓸 수 있는 점은 3판과 같다."""
    h21 = HX[:, list(hx).index("h21")]
    fin = lambda a, fill: np.where(np.isfinite(a), a, fill)  # noqa: E731
    d5 = fin(np.clip(XE[:, 0] - h21, -D_CLIP, D_CLIP), 0.0)
    dneg = fin(np.clip(XE[:, 1] - h21, -D_CLIP, D_CLIP), DNEG_FILL)
    lev = fin(np.clip(XRAW[:, L2.XS.index("rev")], -LEV_CLIP, LEV_CLIP), 0.0)
    ddp = fin(np.clip(XRAW[:, L2.XS.index("dd")], -DD_CLIP, 0.0), 0.0)
    return np.column_stack([HX, d5, dneg, lev, np.minimum(lev, 0.0), ddp])


def extend_points(P: dict, calibrate: bool, borrow5: Optional[dict] = None) -> dict:
    """3판 점 표 → 5판 점 표. 회귀 입력을 늘리고 재무 순위는 모두 '모름'으로 둔다(5판은 가격 자료만으로 예측한다)."""
    P5 = dict(P)
    P5.update(HX=hx_extend(P["HX"], P["hx"], P["XE"], P["XRAW"]), hx=tuple(P["hx"]) + HX_ADD, FR=np.full_like(P["FR"], np.nan),
              FXRAW=np.full_like(P["FXRAW"], np.nan), borrow=borrow5 if P.get("borrow") is not None else None, calibrate=bool(calibrate))
    return P5


# ---------------------------------------------------------------- 2) 걸어 나가기
def merge(P5: dict, o3: dict, o5: dict) -> dict:
    """두 걸음(3판 재현 o3, 입력을 늘린 o5)에서 비교 모형 8개를 모은다. ENS1 은 두 걸음에서 같아야 한다(회귀 입력을 쓰지 않는다)."""
    for key in ("FQ", "FP"):
        if not np.allclose(o3[key][:, L3.I_ENS1], o5[key][:, L3.I_ENS1], equal_nan=True):
            raise RuntimeError("1판 앙상블이 두 걸음에서 다르다 — 점 표가 어긋났다")
    n = len(P5["date"])
    out = {"FQ": np.full((n, M5, H, len(TAUS)), np.nan, np.float32), "FP": np.full((n, M5, H, len(EVENTS)), np.nan, np.float32),
           "LQ": np.full((n, M5, H), np.nan), "LB": np.full((n, M5, H, len(EVENTS)), np.nan)}
    src = (o3, o5)
    for m, which, j in _SOURCES + ((I_V5, 1, L3.I_V3 if P5["calibrate"] else L3.I_ENS3),):
        for key in out:
            out[key][:, m] = src[which][key][:, j]
    out.update(S_HAR=o3["S3"], S_HARX=o5["S3"], calibrate=P5["calibrate"],
               **{k: o5[k] for k in ("weights1", "weights2", "shifts2", "weights3", "shifts3", "blend", "cal_active", "realized_dates", "blend_dates")})
    return out


def walk5(P: dict, P5: dict, progress: Optional[Callable[[str, int, int], None]] = None) -> dict:
    """3판 걸어 나가기를 원래 점과 5판 점에서 한 번씩. 앞을 보지 않는 성질은 walk3 그대로다."""
    step = lambda tag: None if progress is None else (lambda i, n: progress(tag, i, n))  # noqa: E731
    keep = ("FQ", "FP", "LQ", "LB", "S3")
    o3 = {k: v for k, v in L3.walk3(P, step("3판")).items() if k in keep}
    return merge(P5, o3, L3.walk3(P5, step("5판")))


# ---------------------------------------------------------------- 3) 점수
COMPARES = (("vs_clim", I_V5, I_CLIM), ("vs_v1", I_V5, I_ENS1), ("vs_v3", I_V5, I_V3), ("v3_vs_v1", I_V3, I_ENS1), ("v1_vs_clim", I_ENS1, I_CLIM),
            ("vs_har", I_V5, I_HAR), ("harx_vs_har", I_HARX, I_HAR), ("v3x_vs_v3", I_V3X, I_V3), ("ens5_vs_v1", I_ENS5, I_ENS1),
            ("v3x_vs_v1", I_V3X, I_ENS1))
COVERAGE = (I_ENS1, I_V3, I_ENS5, I_V5)


def score_layer5(P: dict, out: dict, eras: list, judged_end: str, alpha_family: float) -> dict:
    """칸(기간 × 종류)마다: V5 대 CLIM(표시 등급)·V5 대 ENS1(판정)·V5 대 V3·V3 대 ENS1(3판 재현)·V5 대 HAR·HARX 대 HAR(변동성 예측만 바꾼 효과)·
    V3X 대 V3(3판 틀에 새 변동성 예측만 넣은 효과)·보정 전 ENS5 대 ENS1, 모형별 기량, 구간 적중."""
    cells = {}
    first, last = np.datetime64(eras[0][1]), np.datetime64(eras[-1][2])
    for hi, h in enumerate(HORIZONS):
        for k, kind in enumerate(KINDS):
            L = L2.cell_loss(out, hi, k)
            if not np.isfinite(L[:, I_V5]).any():
                continue
            c = {name: L2.compare(P, L, m, b, hi, eras, judged_end, alpha_family) for name, m, b in COMPARES}
            ok = np.isfinite(L).all(axis=1) & (P["END"][:, hi] <= np.datetime64(judged_end)) & (P["date"] >= first) & (P["date"] <= last)
            by = pd.DataFrame(L[ok]).groupby(P["date"][ok]).mean().mean() if ok.any() else None
            c["expert_skill"] = {} if by is None else {MODELS5[e]: V._skill(by[0], by[e]) for e in range(1, M5)}
            if k == 0 and ok.any():
                y = P["RET"][ok, hi]
                c["coverage80"] = {MODELS5[e]: float(((y >= out["FQ"][ok, e, hi, 0]) & (y <= out["FQ"][ok, e, hi, 4])).mean()) for e in COVERAGE}
            cells[f"{h}:{kind}"] = c
    return cells


def scale_cells(P: dict, out: dict, eras: list, judged_end: str, alpha_family: float) -> dict:
    """변동성 예측 자체의 오차(보고): 기간마다 (ln 실현 변동성 − ln 예측 축척)² 과 QLIKE 를 1판 축척·HAR·HARX 로 비교."""
    res = {}
    for hi, h in enumerate(HORIZONS):
        rv = np.maximum(P["RV"][:, hi], L2.RV_FLOOR)
        S = np.column_stack([P["S"][:, hi], out["S_HAR"][:, hi], out["S_HARX"][:, hi]])
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = (rv[:, None] / S) ** 2
            losses = {"log2": np.log(rv)[:, None] - np.log(S), "qlike": ratio - np.log(ratio) - 1.0}
        losses["log2"] = losses["log2"] ** 2
        res[str(h)] = {name: {"harx_vs_har": L2.compare(P, L, 2, 1, hi, eras, judged_end, alpha_family),
                              "har_vs_v1": L2.compare(P, L, 1, 0, hi, eras, judged_end, alpha_family)} for name, L in losses.items()}
    return res


# ---------------------------------------------------------------- 4) 모형 저장·실시간 예측
def export_library5(P5: dict) -> pd.DataFrame:
    """자료 끝 시점의 서고(앞선 판과 같은 점). 회귀 입력 열(hx_*)이 5판 것이다."""
    return L2.export_library2(P5)


def library_from_frame5(df: pd.DataFrame) -> dict:
    lib = L2.library_from_frame2(df)
    lib["FR"] = np.full((len(df), len(L3.FX)), np.nan)
    return lib


def latest_state5(lp: pd.Series, mlp: Optional[pd.Series] = None) -> Optional[dict]:
    """가격 이력의 마지막 날 상태(2판 상태 + 5판 회귀 입력). 이력이 모자라면 None."""
    st = L2.latest_state2(lp, mlp)
    if st is None:
        return None
    hx = L2.hx_names(mlp is not None)
    xe = extra_frame(lp).iloc[[-1]].to_numpy(dtype=float)
    st["hx"] = hx_extend(np.asarray(st["hx"], float)[None, :], hx, xe, np.asarray(st["xs"], float)[None, :])[0].tolist()
    return st


def forecast_live5(lib: dict, layer: dict, state: dict, blib: Optional[dict] = None) -> dict:
    """자산 하나의 지금 예측. layer = model.json 의 층, state = latest_state5 결과. 3판 실시간 경로를 그대로 쓰고 V5 만 층 규칙으로 고른다."""
    f = L3.forecast_live3(lib, layer, state, blib)
    pick = "V3" if layer["calibrate"] else "ENS3"
    return {"q": {"CLIM": f["q"]["CLIM"], "ENS1": f["q"]["ENS1"], "HARX": f["q"]["HAR"], "ENS5": f["q"]["ENS3"], "V5": f["q"][pick]},
            "p": {"CLIM": f["p"]["CLIM"], "ENS1": f["p"]["ENS1"], "HARX": f["p"]["HAR"], "ENS5": f["p"]["ENS3"], "V5": f["p"][pick]},
            "n": f["n"], "weights": f["weights"]}
