"""crash-cycle-lab — 급락 예측 고도화 7연구 공용 코드 (작업 아님, job.json 없음 — sat-selection-lab 선례).

규칙·정의는 research/jobs/crash-cycle-lab/SPEC.md (결과 보기 전 고정, 사전 등록 2026-11-23).
연구 run.py 는 이 파일을 importlib 로 읽는다(모듈 이름 "crash_cycle_lab"). v1(crash-cycle-model-v1/run.py)의 함수는
고치지 않고 import 해 그대로 쓴다.

미래 정보 규칙(모든 연구 공통):
- 예측 시점 asof = 발생일 t0(랜드마크 0) 또는 t0 + e 의 종가. 그날 종가까지의 정보만 쓴다.
- 월별 자료는 날짜 t 가 속한 달 m 의 m−1 달 값까지만.
- 다른 사건을 학습에 쓰려면 필요한 값이 asof 날짜까지 확정되어 있어야 한다(깊이 = end1_date ≤ asof, 회복 = rec_date ≤ asof 이면
  사건, 아니면 asof 에서 중도절단). 시장이 달라도 날짜로 맞춘다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import warnings
from pathlib import Path
from statistics import NormalDist
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load(name: str, rel: str):
    if name in sys.modules and getattr(sys.modules[name], "__file__", None):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def v1():
    """crash-cycle-model-v1 의 run.py (고치지 않는다)."""
    return _load("crash_cycle_model_v1_run", "research/jobs/crash-cycle-model-v1/run.py")


def lab0():
    """research/jobs/core-longrun-v1/lab.py."""
    return v1()._lab()


_V1 = v1()

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
LAB_VERSION = "crash-cycle-lab/v1"
JUDGE_VERSION = "crash-adv-judge/v1"
SEED = 20261124
FAMILY = (("LM_M1", "crash-landmark-v1"), ("LM_M2", "crash-landmark-v1"),
          ("SIM_M1", "crash-simpath-v1"), ("SIM_M2", "crash-simpath-v1"),
          ("MAC_M1", "crash-macro-credit-v1"), ("MAC_M2", "crash-macro-credit-v1"), ("MAC_M3", "crash-macro-credit-v1"),
          ("INT_M1", "crash-internals-v1"), ("INT_M2", "crash-internals-v1"),
          ("POOL_M1", "crash-intl-pool-v1"), ("POOL_M2", "crash-intl-pool-v1"),
          ("XFER_M1", "crash-industry-transfer-v1"), ("XFER_M2", "crash-industry-transfer-v1"),
          ("RECAL_M1", "crash-recal-v1"), ("RECAL_M2", "crash-recal-v1"))
K_FAMILY = 15
ALPHA = 0.05 / K_FAMILY                      # 0.0033333…
LABELS = ("BEATS_BASELINE", "BEATS_FIXED_SPLIT", "FAIL", "NOT_EVALUABLE")
HOLDOUT_START = "2024-10-01"                 # 이 날 이후 발생 사건은 보고만(층 X / IX)
INTL_SPLIT = "2008-01-01"                    # 해외 반쪽 I1 < 이 날 ≤ I2
US_STRATA = ("A", "B", "C")
INTL_STRATA = ("I1", "I2")
MIN_N_US = {"A": 4, "B": 5, "C": 4, "pooled": 15}
MIN_N_INTL = {"I1": 3, "I2": 3, "pooled": 10}
CLUSTER_GAP = 63                             # 해외 군집: 앞 사건 발생일과 평일 63일 넘게 떨어지면 새 군집
LANDMARKS = (21, 63, 126)                    # 발생 뒤 1·3·6개월(평일)
LB_H = 252                                   # '긴 약세장' = 발생 뒤 252거래일 안에 전고점 회복 못 함
RIDGE_LAMBDA = 4.0                           # 표준화 기울기에 N(0, 0.5²) 사전분포와 같은 벌점(½·λ·β²)
P_CLIP = (0.05, 0.95)
MIN_CLS_TRAIN = 6                            # 분류기 학습 최소 사건 수(라벨 있는 것), 두 갈래 각각 1개 이상
X_FLOOR = -math.log(1 + _V1.END_TH)          # 0.0512933 — v1 의 사건 종료 문턱(−5%)을 그대로 쓴 '남은 거리' 하한
GARCH_A, GARCH_B = 0.08, 0.90                # 미국 일별 주식 GARCH(1,1) 문헌 전형값, 지속성 0.98
N_SIM, N_SIM_SMOKE = 4000, 400
H_SIM = 1260                                 # 모의 길이(5년)
SIM_MIN_HIST = 756                           # 모의에 필요한 최소 과거 일수
RECAL_MIN, RECAL_TAU, RECAL_PRIOR_N, RECAL_CLIP = 10, 1.0, 10, 0.01
INTL_REGIONS = ("Europe", "Japan", "Asia_Pacific_ex_Japan")
REGION_LABELS = {"Europe": "유럽", "Japan": "일본", "Asia_Pacific_ex_Japan": "아시아태평양(일본 제외)"}
MARKET_CODE = {"US": 0, "Europe": 1, "Japan": 2, "Asia_Pacific_ex_Japan": 3}
YEARS_US, YEARS_INTL = 97.25, 33.25          # power_report 용 판정 구간 길이(1927-07~2024-09, 1991-07~2024-09)
MOODYS_CSV = PROJECT_ROOT / "research" / "jobs" / "crash-cycle-lab" / "data" / "moodys_monthly.csv"
READING_HEADER = ("아래는 과거 사건 분포를 지금에 대어 본 설명이다. 매수·매도 추천이 아니며 엔진·주문에 연결되지 않는다. "
                  "판정을 통과하지 못한 모델의 값은 참고만 하고 기준선을 먼저 본다.")
PRED_COLUMNS = ("study", "model", "market", "episode_id", "t0", "era", "landmark", "asof", "n_train", "p_lb",
                "d_q10", "d_q25", "d_q50", "d_q75", "d_q90", "r_252", "r_504", "r_756", "r_1260", "a_now",
                "y_FD", "y_depth_settled", "y_R_asof", "y_recovered", "judged_m1", "judged_m2")
# ------------------------------------------------------------------------------------------------------

# v1 에서 그대로 쓰는 상수(다시 정의하지 않고 이름만 붙임)
Q, HZ, H = _V1.Q, _V1.HZ, _V1.H
MIN_TRAIN, MIN_EVENTS_M2 = _V1.MIN_TRAIN, _V1.MIN_EVENTS_M2
CRASH_TH, END_TH = _V1.CRASH_TH, _V1.END_TH
EVENTS = _V1.EVENTS

PRED_INT = ("landmark", "n_train", "y_depth_settled", "y_R_asof", "y_recovered", "judged_m1", "judged_m2")
PRED_STR = ("study", "model", "market", "episode_id", "t0", "era", "asof")
PRED_FLOAT = tuple(c for c in PRED_COLUMNS if c not in PRED_INT and c not in PRED_STR)
PRED_MAX_BYTES = 250_000
STRATUM_NAMES = {"pre": "1927-07 이전(판정 밖)", "A": "A 1927-07~1966", "B": "B 1967~2007", "C": "C 2008~2024-09",
                 "X": "X 2024-10~ (보고만)", "I1": "I1 1991~2007", "I2": "I2 2008~2024-09", "IX": "IX 2024-10~ (보고만)"}
_N = NormalDist()


# ================================================================ 작은 도구
def fin(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def mean_or_none(xs) -> Optional[float]:
    a = [float(v) for v in xs if fin(v) is not None]
    return float(np.mean(a)) if a else None


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def dstr(ts) -> Optional[str]:
    return None if ts is None else str(pd.Timestamp(ts).date())


# ================================================================ 자료
def v1_series(d: dict, smoke: bool) -> dict:
    """v1.load(smoke) 의 본문을 '자료 받기 다음부터' 그대로 옮긴 것."""
    mkt = d["mkt"].astype(float).dropna()
    L = (1 + mkt).cumprod()
    rf = d["rf"].reindex(L.index).fillna(0.0)
    i12 = d["ind12"].reindex(L.index)
    if "Money" in i12.columns:
        fin_col = "Money"
    elif smoke:
        fin_col = str(i12.columns[10])
    else:
        raise RuntimeError("12 산업 자료에 Money 열이 없음(자료 형식 변경)")
    F = (1 + i12[fin_col].fillna(0.0)).cumprod()
    F49, cols49 = None, []
    i49 = d.get("ind49")
    if i49 is not None:
        cols49 = [c for c in _V1.FIN49 if c in i49.columns]
        if cols49:
            r = i49.reindex(L.index)[cols49].mean(axis=1, skipna=True)
            started = r.notna().cummax()
            F49 = (1 + r.fillna(0.0)).cumprod().where(started)
    return {"L": L, "rf": rf, "F": F, "F49": F49, "fin_column": fin_col, "fin49_columns": cols49,
            "source": d.get("source", "synthetic (smoke)" if smoke else "Ken French")}


def load_us(smoke: bool) -> dict:
    d = lab0().synthetic_data() if smoke else lab0().load_real()
    out = v1_series(d, smoke)
    out.update(ind12=d["ind12"], ind49=d.get("ind49"), news=_V1.load_news())
    return out


def synthetic_intl() -> dict:
    """스모크용 해외 3지역 가짜 지수(네트워크 없음)."""
    out = {}
    slow = (("1992-06-01", "1992-10-30"), ("1994-02-01", "1994-06-30"), ("1997-08-01", "1998-01-31"), ("1998-07-15", "1998-10-05"),
            ("2008-06-01", "2009-03-09"), ("2010-04-20", "2010-07-01"), ("2011-07-20", "2011-10-01"), ("2015-07-20", "2016-02-11"),
            ("2018-09-20", "2018-12-24"), ("2020-02-20", "2020-03-23"), ("2022-01-03", "2022-10-12"))
    for k, key in enumerate(INTL_REGIONS):
        rng = np.random.default_rng(SEED + 101 + k)
        idx = pd.bdate_range("1990-07-02", "2026-08-31")
        drift = np.full(len(idx), 0.0006)
        for a, b in slow:
            drift[(idx >= a) & (idx <= b)] = -0.004
        drift[(idx >= "2000-03-01") & (idx <= "2003-03-31")] = -0.0015
        noise = rng.normal(0, 0.011, len(idx))
        out[key] = pd.Series(np.cumprod(1 + drift + noise), index=idx)
    return out


def load_intl(smoke: bool, required: bool, reasons: Optional[dict] = None) -> dict:
    """{region: L_r}. 한 지역이라도 못 받으면 required=True → RuntimeError, False → 그 지역을 빼고 reasons 에 사유."""
    if smoke:
        return synthetic_intl()
    from core import french_factors as ff

    out = {}
    for key in INTL_REGIONS:
        k = f"intl_{key}_3"
        ff.DATASETS.setdefault(k, f"{key}_3_Factors_Daily_CSV.zip")
        df = ff.load(k)
        if df is None:
            if required:
                raise RuntimeError(f"Ken French {key} 자료를 받지 못함")
            if reasons is not None:
                reasons[key] = f"Ken French {key} 자료를 받지 못함"
            continue
        mkt = (df["Mkt-RF"] + df["RF"]).dropna()
        mkt = lab0().to_weekdays(mkt)
        out[key] = (1 + mkt).cumprod()
    return out


def synthetic_rf_monthly() -> pd.Series:
    idx = pd.period_range("1926-07", "2026-09", freq="M")
    k = np.arange(len(idx))
    return pd.Series(0.003 + 0.002 * np.sin(2 * np.pi * k / 120), index=idx)


def synthetic_moodys() -> pd.DataFrame:
    idx = pd.period_range("1919-01", "2026-10", freq="M")
    k = np.arange(len(idx))
    aaa = 4.5 + 1.5 * np.sin(2 * np.pi * k / 240)
    baa = aaa + 1.0 + 0.4 * np.sin(2 * np.pi * k / 90)
    return pd.DataFrame({"AAA": aaa, "BAA": baa}, index=idx)


def load_rf_monthly(smoke: bool) -> pd.Series:
    """월별 RF(소수/월), PeriodIndex('M')."""
    if smoke:
        return synthetic_rf_monthly()
    from core import french_factors as ff

    df = ff.load("ff3_monthly")
    if df is None or "RF" not in df.columns:
        raise RuntimeError("Ken French 월별 FF3(RF) 자료를 받지 못함")
    s = df["RF"].astype(float).dropna()
    s.index = pd.DatetimeIndex(s.index).to_period("M")
    return s[~s.index.duplicated(keep="last")].sort_index()


def load_moodys(smoke: bool) -> pd.DataFrame:
    """무디스 AAA·BAA 월별 수익률(%), PeriodIndex('M'). 실제 = 저장소 스냅숏(네트워크 안 씀)."""
    if smoke:
        return synthetic_moodys()
    try:
        df = pd.read_csv(MOODYS_CSV)
    except OSError as exc:
        raise RuntimeError(f"무디스 스냅숏 없음: {MOODYS_CSV.name}") from exc
    if list(df.columns) != ["month", "AAA", "BAA"]:
        raise RuntimeError("무디스 스냅숏 열이 month,AAA,BAA 가 아님")
    return pd.DataFrame({"AAA": df["AAA"].astype(float).to_numpy(), "BAA": df["BAA"].astype(float).to_numpy()},
                        index=pd.PeriodIndex(df["month"], freq="M")).sort_index()


# ================================================================ 사건·층
def stratum_us(date) -> str:
    d = pd.Timestamp(date)
    if d < pd.Timestamp("1927-07-01"):
        return "pre"
    if d <= pd.Timestamp("1966-12-31"):
        return "A"
    if d <= pd.Timestamp("2007-12-31"):
        return "B"
    if d < pd.Timestamp(HOLDOUT_START):
        return "C"
    return "X"


def stratum_intl(date) -> str:
    d = pd.Timestamp(date)
    if d < pd.Timestamp(INTL_SPLIT):
        return "I1"
    if d < pd.Timestamp(HOLDOUT_START):
        return "I2"
    return "IX"


def annotate(eps: list, market: str, idx: pd.DatetimeIndex, Lv: np.ndarray) -> list:
    """v1.build_episodes 의 사건 dict 에 키를 더한다(제자리, v1 키는 건드리지 않음)."""
    strat = stratum_intl if market in INTL_REGIONS else stratum_us
    for r in eps:
        t0d = pd.Timestamp(idx[r["t0"]])
        r["market"] = market
        r["id"] = f"{market}:{t0d.date()}"
        r["stratum"] = strat(t0d)
        r["t0_date"] = t0d
        r["end1_date"] = pd.Timestamp(idx[r["end1"]]) if r["depth_settled"] else None
        r["rec_date"] = pd.Timestamp(idx[r["rec"]]) if r["rec"] is not None else None
        r["_idx"], r["_Lv"], r["_last"] = idx, Lv, len(Lv) - 1
    return eps


def us_context(data: dict) -> dict:
    ctx = _V1.build_context(data["L"], data["rf"], data["F"], data["F49"], data.get("news"))
    annotate(ctx["eps"], "US", ctx["idx"], ctx["Lv"])
    ctx["recs"] = ctx["eps"]
    ctx["market"] = "US"
    return ctx


def market_context(L: pd.Series, market: str) -> dict:
    eps, _f = _V1.build_episodes(L)
    annotate(eps, market, L.index, L.to_numpy(dtype=float))
    return {"idx": L.index, "Lv": L.to_numpy(dtype=float), "eps": eps, "last": len(L) - 1, "market": market}


def pos_le(idx: pd.DatetimeIndex, date) -> int:
    return int(idx.searchsorted(pd.Timestamp(date), side="right")) - 1


# ================================================================ 학습 집합(날짜 기준)
def m1_pool(recs, D) -> list:
    D = pd.Timestamp(D)
    return [r for r in recs if r["depth_settled"] and r["end1_date"] <= D]


def m2_pool(recs, D) -> tuple:
    D = pd.Timestamp(D)
    rows = [r for r in recs if r["t0_date"] < D]
    done = [r["rec_date"] is not None and r["rec_date"] <= D for r in rows]
    times = np.array([r["R"] if ok else pos_le(r["_idx"], D) - r["t0"] for r, ok in zip(rows, done)], dtype=float)
    events = np.array([1 if ok else 0 for ok in done], dtype=int)
    return rows, times, events


def base_m1(pool, dd0) -> Optional[dict]:
    if len(pool) < MIN_TRAIN:
        return None
    y = np.array([r["y"] for r in pool], dtype=float)
    return _V1._fd_quants(y, np.ones(len(y)), dd0)


def base_m2(rows, times, events, e_days: int = 0) -> Optional[dict]:
    if len(rows) < MIN_TRAIN or int(np.sum(events)) < MIN_EVENTS_M2:
        return None
    tau, S = _V1.wkm(times, events)
    return _V1._cond_F(tau, S, e_days)


def n_train_of(m1, n1, m2, n2) -> Optional[int]:
    """predictions.csv 의 n_train: 모델 1 학습 수, 모델 1 예측이 없으면 모델 2 학습 수, 둘 다 없으면 빈칸."""
    if m1 is not None:
        return int(n1)
    if m2 is not None:
        return int(n2)
    return None


def base0(train_recs, r) -> dict:
    """랜드마크 0 공통 BASE(v1 발생일 기준선, 학습 = train_recs 중 r 의 발생일까지 확정된 것). 모든 작업에서 같은 값."""
    D = r["t0_date"]
    T1 = m1_pool(train_recs, D)
    rows, times, events = m2_pool(train_recs, D)
    m1, m2 = base_m1(T1, r["dd0"]), base_m2(rows, times, events, 0)
    return {"m1": m1, "m2": m2, "n1": len(T1), "n2": len(rows), "n_train": n_train_of(m1, len(T1), m2, len(rows))}


# ================================================================ 경로 상태·랜드마크
def alive_at(r, e) -> bool:
    return r["rec"] is None or r["rec"] > r["t0"] + e


def landmark_state(r, e) -> Optional[dict]:
    t0 = r["t0"]
    tau = t0 + e
    if tau > r["_last"] or not alive_at(r, e):
        return None
    Lv, P = r["_Lv"], r["P"]
    return {"tau": tau, "asof": pd.Timestamp(r["_idx"][tau]), "d": float(Lv[tau] / P - 1),
            "m": float(Lv[t0:tau + 1].min() / P - 1), "x": max(math.log(P / Lv[tau]), X_FLOOR)}


def yrem(r, e) -> float:
    Lv, s = r["_Lv"], r["t0"] + e
    return float(math.log(Lv[s:r["end1"] + 1].min() / Lv[s]))


def scaled_km(T, ev, x_train, x_now, hs=HZ) -> dict:
    V = np.asarray(T, dtype=float) / np.asarray(x_train, dtype=float)
    tau, S = _V1.wkm(V, ev)
    return {h: float(1 - _V1.surv_at(tau, S, h / x_now)) for h in hs}


def _base_from_state(train_recs, st: dict, dd0: float, e: int) -> dict:
    D = st["asof"]
    T1 = m1_pool(train_recs, D)
    m1v = base_m1(T1, dd0)
    trunc = None if m1v is None else {k: min(st["m"], v) for k, v in m1v.items()}
    rows, times, events = m2_pool(train_recs, D)
    return {"m1_v1": m1v, "m1_trunc": trunc, "m2": base_m2(rows, times, events, e), "n1": len(T1), "n2": len(rows),
            "_T1": T1, "_m2rows": (rows, times, events)}


def landmark_base(train_recs, r, e) -> Optional[dict]:
    """v1 진행 중 읽기(학습은 asof 기준): m1_v1(발생일 깊이로 변환), m1_trunc(지금까지 최저로 자름), m2(생존 조건 KM)."""
    st = landmark_state(r, e)
    if st is None:
        return None
    return _base_from_state(train_recs, st, r["dd0"], e)


def _lm_from_state(train_recs, st: dict, e: int) -> dict:
    D = st["asof"]
    T1L = [j for j in m1_pool(train_recs, D) if alive_at(j, e)]
    m1 = None
    if len(T1L) >= MIN_TRAIN:
        yr = np.array([yrem(j, e) for j in T1L], dtype=float)
        ones = np.ones(len(yr))
        m1 = {f"{q:g}": float(min(st["m"], (1 + st["d"]) * math.exp(_V1.wquantile(yr, ones, q)) - 1)) for q in Q}
    T, ev, xs = [], [], []
    for j in train_recs:
        s = j["t0"] + e
        if s > j["_last"] or not pd.Timestamp(j["_idx"][s]) < D or not alive_at(j, e):
            continue
        if j["rec_date"] is not None and j["rec_date"] <= D:
            T.append(j["R"] - e)
            ev.append(1)
        else:
            T.append(pos_le(j["_idx"], D) - s)
            ev.append(0)
        xs.append(max(math.log(j["P"] / j["_Lv"][s]), X_FLOOR))
    m2 = None
    if len(T) >= MIN_TRAIN and sum(ev) >= MIN_EVENTS_M2:
        m2 = scaled_km(T, ev, xs, st["x"])
    return {"m1": m1, "m2": m2, "n1": len(T1L), "n2": len(T)}


def landmark_lm(train_recs, r, e) -> Optional[dict]:
    """LM_ANCHOR(남은 추가 하락으로 다시 닻) · LM_SCALED(남은 로그 거리로 시간 척도를 늘인 KM)."""
    st = landmark_state(r, e)
    if st is None:
        return None
    return _lm_from_state(train_recs, st, e)


def m1_already(T1, m) -> Optional[dict]:
    deep = [j["FD"] for j in T1 if j["FD"] <= m]
    if len(deep) < 3:
        return None
    ones = np.ones(len(deep))
    return {f"{q:g}": float(_V1.wquantile(deep, ones, q)) for q in Q}


def m2_deep(train_recs, D, m, e) -> Optional[dict]:
    rows, times, events = m2_pool(train_recs, D)
    keep = []
    for j, t_, ev in zip(rows, times, events):
        if j["depth_settled"] and j["end1_date"] <= D:
            mj = j["FD"]
        else:
            p = pos_le(j["_idx"], D)
            mj = float(j["_Lv"][j["t0"]:p + 1].min() / j["P"] - 1)
        if mj <= m:
            keep.append((t_, ev))
    if len(keep) < MIN_TRAIN or sum(ev for _t, ev in keep) < MIN_EVENTS_M2:
        return None
    tau, S = _V1.wkm([t for t, _e in keep], [ev for _t, ev in keep])
    return _V1._cond_F(tau, S, e)


# ================================================================ 두 갈래 분류기
def lb_label(r, D) -> Optional[int]:
    D = pd.Timestamp(D)
    if r["rec_date"] is not None and r["rec_date"] <= D:
        return int(r["R"] > LB_H)
    if pos_le(r["_idx"], D) - r["t0"] >= LB_H:
        return 1
    return None


def fit_ridge_logit(X, y, lam: float = RIDGE_LAMBDA) -> dict:
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X[:, None]
    y = np.asarray(y, dtype=float)
    n, k = X.shape
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        mu = np.nanmean(X, axis=0) if n else np.full(k, np.nan)
        sd = np.nanstd(X, axis=0) if n else np.full(k, np.nan)
    keep = np.isfinite(sd) & (sd > 1e-12)
    Z = np.zeros((n, k))
    if n:
        with np.errstate(all="ignore"):
            Zr = (X - mu) / np.where(keep, sd, 1.0)
        Zr = np.where(np.isfinite(Zr), Zr, 0.0)
        Z[:, keep] = Zr[:, keep]
    n_pos = int(np.sum(y)) if n else 0
    out = {"mu": mu, "sd": sd, "keep": keep, "b0": 0.0, "beta": np.zeros(k), "n": n, "n_pos": n_pos, "converged": False}
    if n == 0 or n_pos == 0 or n_pos == n:
        return out
    A = np.hstack([np.ones((n, 1)), Z])
    beta = np.zeros(k + 1)
    beta[0] = logit(float(np.mean(y)))
    pen = np.r_[0.0, np.ones(k)] * lam
    free = np.r_[True, keep]
    converged = False
    for _ in range(100):
        eta_ = A @ beta
        p = 1.0 / (1.0 + np.exp(-eta_))
        W = p * (1 - p)
        g = A.T @ (y - p) - pen * beta
        Hm = (A * W[:, None]).T @ A + np.diag(pen)
        g, Hm = g[free], Hm[np.ix_(free, free)]
        try:
            step = np.linalg.solve(Hm, g)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(Hm) @ g
        full = np.zeros(k + 1)
        full[free] = step
        beta = beta + full
        if np.max(np.abs(full)) < 1e-10:
            converged = True
            break
    beta[1:][~keep] = 0.0
    out.update(b0=float(beta[0]), beta=beta[1:].astype(float), converged=bool(converged and np.all(np.isfinite(beta))))
    return out


def fit_ok(fit: dict) -> bool:
    return fit["n"] >= MIN_CLS_TRAIN and 1 <= fit["n_pos"] <= fit["n"] - 1 and fit["converged"]


def eta(fit: dict, x) -> float:
    x = np.atleast_1d(np.asarray(x, dtype=float))
    with np.errstate(all="ignore"):
        z = (x - fit["mu"]) / np.where(fit["keep"], fit["sd"], 1.0)
    z = np.where(np.isfinite(z) & fit["keep"], z, 0.0)
    return float(np.sum(np.where(fit["keep"], fit["beta"], 0.0) * z))


def p_center(fit: dict, x_new, pool_x, pool_lab) -> Optional[tuple]:
    labs = [(x, int(l)) for x, l in zip(pool_x, pool_lab) if l is not None]
    if not labs:
        return None
    ys = [l for _x, l in labs]
    if min(ys) == max(ys):
        return None
    pi = float(np.mean(ys))
    if not np.any(np.where(fit["keep"], fit["beta"], 0.0) != 0.0):
        return pi, pi                    # 기울기가 모두 0 → p = π 정확히(가중치 모두 1, 기준선과 같은 예측)
    ebar = float(np.mean([eta(fit, x) for x, _l in labs]))
    p = sigmoid(logit(pi) + eta(fit, x_new) - ebar)
    return float(min(max(p, P_CLIP[0]), P_CLIP[1])), pi


def two_state_w(labels, p, pi) -> np.ndarray:
    return np.array([1.0 if l is None else (p / pi if l == 1 else (1 - p) / (1 - pi)) for l in labels], dtype=float)


def rw_m1(pool, dd0, w) -> dict:
    y = np.array([r["y"] for r in pool], dtype=float)
    return _V1._fd_quants(y, np.asarray(w, dtype=float), dd0)


def rw_m2(times, events, w, e_days: int = 0) -> Optional[dict]:
    tau, S = _V1.wkm(times, events, w)
    return _V1._cond_F(tau, S, e_days)


def two_state_predict(us_recs, D, xmap: dict, x_i, fit: dict, dd0: float, e_days: int = 0) -> dict:
    """4.8 절 2·3단계: 기준선(BASE)과 두 갈래 재가중(모델) 예측. xmap = {사건 id: 특징}.
    p_center 가 None 이면 unfit=True(그 사건은 판정에서 빠짐)."""
    out: dict[str, Any] = {"base_m1": None, "base_m2": None, "m1": None, "m2": None, "n1": 0, "n2": 0, "unfit": False}
    T1 = m1_pool(us_recs, D)
    out["n1"] = len(T1)
    out["base_m1"] = base_m1(T1, dd0)
    if out["base_m1"] is not None:
        labs = [lb_label(j, D) for j in T1]
        pc = p_center(fit, x_i, [xmap[j["id"]] for j in T1], labs)
        if pc is None:
            out["unfit"] = True
        else:
            out["m1"] = rw_m1(T1, dd0, two_state_w(labs, pc[0], pc[1]))
    rows, times, events = m2_pool(us_recs, D)
    out["n2"] = len(rows)
    out["base_m2"] = base_m2(rows, times, events, e_days)
    if len(rows) >= MIN_TRAIN and int(np.sum(events)) >= MIN_EVENTS_M2:
        labs = [lb_label(j, D) for j in rows]
        pc = p_center(fit, x_i, [xmap[j["id"]] for j in rows], labs)
        if pc is None:
            out["unfit"] = True
        else:
            out["m2"] = rw_m2(times, events, two_state_w(labs, pc[0], pc[1]), e_days)
    return out


def cls_set(recs, D) -> tuple:
    """D 날짜에 라벨을 알 수 있는 발생 사건: (사건 목록, 라벨 목록)."""
    D = pd.Timestamp(D)
    C, y = [], []
    for j in recs:
        if j["t0_date"] < D:
            lbl = lb_label(j, D)
            if lbl is not None:
                C.append(j)
                y.append(lbl)
    return C, y


def _sel(cols):
    if cols is None:
        return lambda v: np.atleast_1d(np.asarray(v, dtype=float))
    return lambda v: np.atleast_1d(np.asarray(v, dtype=float))[list(cols)]


def two_state_episode(us_recs, r, xmap: dict, cls_recs=None, cls_xmap=None, plb_recs=None, plb_xmap=None, cols=None) -> dict:
    """연구 3·4·6 의 사건 하나(발생일 예측, 4.8 절 1~4단계).
    분류기 학습 집합 = cls_recs(기본 us_recs) 중 t0 < D 이고 라벨을 아는 것. p_lb 기준 집합 = plb_recs(기본 = 분류기 학습 집합).
    cols = 쓸 특징 위치(None = 전부). 반환에 base(공통 BASE)·모델 예측·p_lb·π·적합·미적합 사유."""
    sel = _sel(cols)
    cls_recs = us_recs if cls_recs is None else cls_recs
    cls_xmap = xmap if cls_xmap is None else cls_xmap
    D = r["t0_date"]
    x_i = sel(xmap[r["id"]])
    k = len(x_i)
    C, yC = cls_set(cls_recs, D)
    XC = np.array([sel(cls_xmap[j["id"]]) for j in C], dtype=float).reshape(len(C), k)
    fit = fit_ridge_logit(XC, yC)
    out: dict[str, Any] = {"base": base0(us_recs, r), "n_cls": len(C), "n_cls_pos": int(sum(yC)), "fit": fit, "unfit": None,
                           "p_lb": None, "pi": None, "m1": None, "m2": None, "n1": None, "n2": None}
    if not fit_ok(fit):
        out["unfit"] = "분류기 미적합(학습 6개 미만·한 갈래뿐·미수렴)"
        return out
    smap = {kk: sel(v) for kk, v in xmap.items()}
    tp = two_state_predict(us_recs, D, smap, x_i, fit, r["dd0"], 0)
    if plb_recs is None:
        pc = p_center(fit, x_i, list(XC), yC)
    else:
        P, yP = cls_set(plb_recs, D)
        pc = p_center(fit, x_i, [sel((plb_xmap or xmap)[j["id"]]) for j in P], yP)
    if tp["unfit"] or pc is None:
        out["unfit"] = "재가중 불가(학습 사건 라벨이 한 갈래뿐)"
        return out
    out.update(m1=tp["m1"], m2=tp["m2"], n1=tp["n1"], n2=tp["n2"], p_lb=pc[0], pi=pc[1])
    return out


def two_state_now(us_recs, D, xmap: dict, x_now, dd0: float, e_days: int = 0, cls_recs=None, cls_xmap=None,
                  plb_recs=None, plb_xmap=None) -> dict:
    """'지금 읽기'(설명용): D(마지막 날)까지 라벨을 아는 사건으로 학습한 두 갈래 예측과 같은 날 기준선."""
    cls_recs = us_recs if cls_recs is None else cls_recs
    cls_xmap = xmap if cls_xmap is None else cls_xmap
    x_now = np.atleast_1d(np.asarray(x_now, dtype=float))
    C, yC = cls_set(cls_recs, D)
    XC = np.array([np.asarray(cls_xmap[j["id"]], dtype=float) for j in C], dtype=float).reshape(len(C), len(x_now))
    fit = fit_ridge_logit(XC, yC)
    T1 = m1_pool(us_recs, D)
    rows, times, events = m2_pool(us_recs, D)
    out: dict[str, Any] = {"base_m1": base_m1(T1, dd0), "base_m2": base_m2(rows, times, events, e_days), "n1": len(T1), "n2": len(rows),
                           "n_cls": len(C), "m1": None, "m2": None, "p_lb": None, "pi": None, "unfit": None,
                           "beta": [float(b) for b in fit["beta"]], "keep": [bool(b) for b in fit["keep"]]}
    if not fit_ok(fit):
        out["unfit"] = "분류기 미적합"
        return out
    tp = two_state_predict(us_recs, D, xmap, x_now, fit, dd0, e_days)
    if plb_recs is None:
        pc = p_center(fit, x_now, list(XC), yC)
    else:
        P, yP = cls_set(plb_recs, D)
        pc = p_center(fit, x_now, [np.asarray((plb_xmap or xmap)[j["id"]], dtype=float) for j in P], yP)
    if pc is None:
        out["unfit"] = "재가중 불가"
        return out
    out.update(m1=tp["m1"], m2=tp["m2"], p_lb=pc[0], pi=pc[1])
    return out


def classification_skill(items: list) -> dict:
    """items = [(실제 라벨, p_lb, π)]. 브라이어 (LB − p)² 평균 vs (LB − π)² 평균(보고만)."""
    its = [(float(l), float(p), float(q)) for l, p, q in items if l is not None and p is not None and q is not None]
    if not its:
        return {"n": 0, "brier_p": None, "brier_pi": None}
    return {"n": len(its), "brier_p": float(np.mean([(l - p) ** 2 for l, p, _q in its])),
            "brier_pi": float(np.mean([(l - q) ** 2 for l, _p, q in its]))}


# ================================================================ 특징 (모두 t 종가까지)
def logret(Lv) -> np.ndarray:
    Lv = np.asarray(Lv, dtype=float)
    r = np.full(len(Lv), np.nan)
    with np.errstate(all="ignore"):
        r[1:] = np.log(Lv[1:] / Lv[:-1])
    return r


def volratio(r, t) -> float:
    if t < 252:
        return float("nan")
    a = np.asarray(r[t - 20:t + 1], dtype=float)
    b = np.asarray(r[t - 251:t + 1], dtype=float)
    den = math.sqrt(float(np.mean(b ** 2)))
    if not math.isfinite(den) or den == 0:
        return float("nan")
    return float(math.sqrt(float(np.mean(a ** 2))) / den)


def industry_tr(ind: pd.DataFrame) -> pd.DataFrame:
    started = ind.notna().cummax()
    return (1 + ind.fillna(0.0)).cumprod().where(started)


def dd252_matrix(tr: pd.DataFrame) -> np.ndarray:
    return (tr / tr.rolling(252, min_periods=252).max() - 1).to_numpy(dtype=float)


def breadth(ddm, t) -> float:
    row = np.asarray(ddm[t], dtype=float)
    ok = np.isfinite(row)
    if ok.sum() < 10:
        return float("nan")
    return float(np.mean(row[ok] <= -0.15))


def corr12(R12, t) -> float:
    if t < 62:
        return float("nan")
    W = np.asarray(R12[t - 62:t + 1], dtype=float)
    if not np.all(np.isfinite(W)):
        return float("nan")
    if np.any(W.std(axis=0) <= 1e-15):
        return float("nan")
    C = np.corrcoef(W, rowvar=False)
    k = C.shape[0]
    return float((C.sum() - np.trace(C)) / (k * (k - 1)))


def macro_features(date, rf_m: pd.Series, moodys: pd.DataFrame) -> dict:
    m = pd.Period(pd.Timestamp(date), freq="M")
    k1, k13 = m - 1, m - 13

    def g(s, k):
        try:
            v = float(s.loc[k])
        except KeyError:
            return float("nan")
        return v if math.isfinite(v) else float("nan")

    rf1, rf13 = g(rf_m, k1), g(rf_m, k13)
    aaa, baa = g(moodys["AAA"], k1), g(moodys["BAA"], k1)
    return {"RATECHG_M": 12 * (rf1 - rf13), "TERM": aaa / 100 - 12 * rf1, "DEF": (baa - aaa) / 100}


# ================================================================ 점수
def score_m1(FD, q: dict) -> float:
    return _V1.m1_score(FD, q)


def score_m2(R_asof, F: dict) -> float:
    return _V1.brier(R_asof, F)


def score_row(row: dict) -> tuple:
    s1 = s2 = None
    qs = [row.get(c) for c in ("d_q10", "d_q25", "d_q50", "d_q75", "d_q90")]
    if row.get("y_depth_settled") == 1 and row.get("y_FD") is not None and all(v is not None for v in qs):
        s1 = score_m1(row["y_FD"], {f"{q:g}": v for q, v in zip(Q, qs)})
    rs = [row.get(f"r_{h}") for h in HZ]
    if row.get("y_recovered") == 1 and row.get("y_R_asof") is not None and all(v is not None for v in rs):
        s2 = score_m2(row["y_R_asof"], dict(zip(HZ, rs)))
    return s1, s2


# ================================================================ 판정·검정력
def _judge(dmap: dict, strata, mins: dict, pass_label: str) -> dict:
    from core import research_power as rp

    vals = {s: [float(v) for v in dmap.get(s, []) if fin(v) is not None] for s in strata}
    pooled = [v for s in strata for v in vals[s]]
    n = {s: len(vals[s]) for s in strata}
    n["pooled"] = len(pooled)
    mean = {s: (float(np.mean(vals[s])) if vals[s] else None) for s in strata}
    mean["pooled"] = float(np.mean(pooled)) if pooled else None
    out = {"verdict": "NOT_EVALUABLE", "fail_kind": None, "reason": "", "n": n, "mean": mean,
           "p": None, "p_method": None, "t": None, "p_t": None}
    if any(n[s] < mins[s] for s in strata) or n["pooled"] < mins["pooled"]:
        out["reason"] = "표본 부족"
        return out
    guard = rp.noop_guard(pooled)
    if guard is not None:
        out["reason"] = guard
        return out
    sp = _V1.signflip_p(pooled)
    out.update(p=sp["p"], p_method=sp["method"], t=sp["t"], p_t=sp["p_t"])
    allpos = all(mean[s] > 0 for s in strata)
    if allpos and sp["p"] < ALPHA:
        out.update(verdict=pass_label, reason="")
    else:
        out.update(verdict="FAIL", fail_kind="FAIL_UNDERPOWERED" if allpos else "FAIL",
                   reason="합친 p ≥ α" if allpos else "층 방향 불일치(평균 음수 층 있음)")
    return out


def judge_us(dmap: dict, pass_label: str = "BEATS_BASELINE") -> dict:
    return _judge(dmap, US_STRATA, MIN_N_US, pass_label)


def clusters(items: list) -> list:
    """items = [(t0_date, value, episode_id)] — 해외 판정 층(I1·I2) 사건만."""
    its = sorted([(pd.Timestamp(d), float(v), i) for d, v, i in items if fin(v) is not None], key=lambda x: x[0])
    out, prev = [], None
    for d, v, i in its:
        if prev is None or np.busday_count(np.datetime64(prev.date(), "D"), np.datetime64(d.date(), "D")) > CLUSTER_GAP:
            out.append({"first": d, "stratum": stratum_intl(d), "members": [], "_vals": []})
        out[-1]["members"].append(i)
        out[-1]["_vals"].append(v)
        prev = d
    for c in out:
        c["value"] = float(np.mean(c.pop("_vals")))
    return out


def judge_intl(cmap: dict, pass_label: str = "BEATS_BASELINE") -> dict:
    return _judge(cmap, INTL_STRATA, MIN_N_INTL, pass_label)


def power_episode(n: int) -> dict:
    if n < 2:
        return {"n": n, "needed_effect_sd": None, "min_p": (2.0 ** -n if n >= 1 else None), "pass_prob": {}}
    z = _N.inv_cdf(1 - ALPHA)
    return {"n": n, "needed_effect_sd": float(_V1._cr().t_crit(ALPHA, n - 1) / math.sqrt(n)), "min_p": 2.0 ** -n,
            "pass_prob": {f"{dl}": float(1 - _N.cdf(z - dl * math.sqrt(n))) for dl in (0.3, 0.5, 0.8)}}


def signflip(vals) -> Optional[float]:
    """견고성(보고만)용: 부호 뒤집기 p(값 없으면 None)."""
    a = [float(v) for v in vals if fin(v) is not None]
    return _V1.signflip_p(a)["p"] if a else None


# ================================================================ GARCH 경로 모의
def garch_filter(r_hist) -> dict:
    r = np.asarray(r_hist, dtype=float)
    mu = float(r.mean())
    v = float(r.var())
    omega = (1 - GARCH_A - GARCH_B) * v
    z = np.empty(len(r))
    h = v
    for s in range(len(r)):
        e_ = r[s] - mu
        z[s] = e_ / math.sqrt(h)
        h = omega + GARCH_A * e_ * e_ + GARCH_B * h
    return {"mu": mu, "v": v, "omega": omega, "z": z, "h_next": h}


def simulate_from(ell0, m0_log, mu, omega, h0, Z, cap, n_paths, rng, a: float = GARCH_A, b: float = GARCH_B) -> dict:
    """6.6 절 5~7단계. (a, b) = (0, 0)·omega = h0 = v 이면 변동성 상수(SIM_IID)."""
    Z = np.asarray(Z, dtype=float)
    ell = np.full(n_paths, float(ell0))
    run_min = np.full(n_paths, float(m0_log))
    hit = np.full(n_paths, np.inf)
    hc = np.full(n_paths, float(h0))
    active = np.ones(n_paths, dtype=bool)
    for k in range(1, H_SIM + 1):
        zk = Z[rng.integers(0, len(Z), n_paths)]
        eps_ = np.sqrt(hc) * zk
        ell = ell + mu + eps_
        hc = omega + a * eps_ ** 2 + b * hc
        if k <= cap:
            run_min = np.where(active, np.minimum(run_min, ell), run_min)
        new = (hit == np.inf) & (ell >= 0)
        hit[new] = k
        active = active & (hit == np.inf) & (k < cap)
    ones = np.ones(n_paths)
    fd = np.exp(run_min) - 1
    return {"q": {f"{q:g}": float(_V1.wquantile(fd, ones, q)) for q in Q},
            "F": {h: float(np.mean(hit <= h)) for h in HZ}}


def simulate(Lv, market, P, tau, m_so_far, e, n_paths, iid: bool = False) -> Optional[dict]:
    """6.6 절. tau 종가까지의 일별 로그수익만 쓴다. iid=True → SIM_IID(거르기 없이 hc ≡ v, Z = (r − mu)/√v)."""
    if tau < SIM_MIN_HIST:
        return None
    r = logret(Lv)
    hist = r[1:tau + 1]
    g = garch_filter(hist)
    rng = np.random.default_rng([SEED, MARKET_CODE.get(market, 9), int(tau)])
    ell0, m0 = math.log(Lv[tau] / P), math.log(1 + m_so_far)
    if iid:
        Zi = (hist - g["mu"]) / math.sqrt(g["v"])
        out = simulate_from(ell0, m0, g["mu"], g["v"], g["v"], Zi, H - e, n_paths, rng, a=0.0, b=0.0)
    else:
        out = simulate_from(ell0, m0, g["mu"], g["omega"], g["h_next"], g["z"], H - e, n_paths, rng)
    out.update(vol_now=float(math.sqrt(252 * (g["v"] if iid else g["h_next"]))), vol_lr=float(math.sqrt(252 * g["v"])), n_hist=int(tau))
    return out


# ================================================================ 자기 보정(연구 7)
def recal_shift(F_list, o_list, tau: float = RECAL_TAU) -> float:
    ell = np.array([logit(min(max(float(f), RECAL_CLIP), 1 - RECAL_CLIP)) for f in F_list], dtype=float)
    o = np.asarray(o_list, dtype=float)
    c = 0.0
    for _ in range(50):
        s = 1.0 / (1.0 + np.exp(-(ell + c)))
        d1 = -float(np.sum(o - s)) + c / tau ** 2
        d2 = float(np.sum(s * (1 - s))) + 1 / tau ** 2
        step = d1 / d2
        c -= step
        if abs(step) < 1e-12:
            break
    return float(c)


def recal_m2(F_i: dict, pairs_by_h: dict) -> dict:
    """pairs_by_h = {h: [(F_k[h], o_k(h))]}. 쌍 수 < RECAL_MIN 이면 c_h = 0. 그다음 h 오름차순 누적 최댓값."""
    c, n, F = {}, {}, {}
    run = -np.inf
    for h in HZ:
        pr = pairs_by_h.get(h, [])
        n[h] = len(pr)
        c[h] = recal_shift([f for f, _o in pr], [o for _f, o in pr]) if len(pr) >= RECAL_MIN else 0.0
        v = sigmoid(logit(min(max(float(F_i[h]), 0.01), 0.99)) + c[h])
        run = max(run, v)
        F[h] = float(run)
    return {"F": F, "c": c, "n": n}


def recal_m1(Q_i: dict, fd_list, q_lists: dict, dd0) -> dict:
    n = len(fd_list)
    delta = {}
    for q in Q:
        k = f"{q:g}"
        if n >= RECAL_MIN:
            s = np.array([fd - qq for fd, qq in zip(fd_list, q_lists[k])], dtype=float)
            delta[k] = float(n / (n + RECAL_PRIOR_N) * _V1.wquantile(s, np.ones(n), q))
        else:
            delta[k] = 0.0
    vals = sorted(Q_i[f"{q:g}"] + delta[f"{q:g}"] for q in Q)
    return {"q": {f"{q:g}": float(min(v, dd0)) for q, v in zip(Q, vals)}, "delta": delta, "n": n}


def split_tranches(a: float) -> list:
    return [(0, float(a))] + [(21 * k, (1 - float(a)) / 6) for k in range(1, 7)]


# ================================================================ predictions.csv
def pred_row(study: str, model: str, r: dict, e: int, asof, n_train=None, p_lb=None, m1: Optional[dict] = None,
             m2: Optional[dict] = None, a_now=None, judged_m1: int = 0, judged_m2: int = 0) -> dict:
    """사건 r·랜드마크 e 의 예측 한 줄(실제 결과 포함)."""
    row = {"study": study, "model": model, "market": r["market"], "episode_id": r["id"], "t0": dstr(r["t0_date"]),
           "era": r["stratum"], "landmark": int(e), "asof": dstr(asof), "n_train": n_train, "p_lb": p_lb, "a_now": a_now,
           "y_FD": r["FD"] if r["depth_settled"] else None, "y_depth_settled": int(bool(r["depth_settled"])),
           "y_R_asof": (r["R"] - e) if r["R"] is not None else None, "y_recovered": int(r["R"] is not None),
           "judged_m1": int(judged_m1), "judged_m2": int(judged_m2)}
    for q, c in zip(Q, ("d_q10", "d_q25", "d_q50", "d_q75", "d_q90")):
        row[c] = None if m1 is None else m1.get(f"{q:g}")
    for h in HZ:
        row[f"r_{h}"] = None if m2 is None else (m2.get(h) if h in m2 else m2.get(str(h)))
    return row


def _cell(col: str, v) -> str:
    if v is None:
        return ""
    if col in PRED_INT:
        return str(int(v))
    if col in PRED_FLOAT:
        f = fin(v)
        return "" if f is None else f"{f:.6f}"
    return str(v)


def write_predictions(rows: list, path) -> None:
    path = Path(path)
    key = lambda r: (str(r["market"]), str(r["t0"]), int(r["landmark"]), str(r["model"]))  # noqa: E731
    lines = [",".join(PRED_COLUMNS)]
    for r in sorted(rows, key=key):
        lines.append(",".join(_cell(c, r.get(c)) for c in PRED_COLUMNS))
    data = ("\n".join(lines) + "\n").encode("utf-8")
    if len(data) > PRED_MAX_BYTES:
        raise RuntimeError(f"predictions.csv 가 {len(data)} 바이트로 상한 {PRED_MAX_BYTES} 을 넘음")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def read_predictions(path) -> list:
    text = Path(path).read_text(encoding="utf-8")
    lines = text.rstrip("\n").split("\n")
    head = lines[0].split(",")
    out = []
    for ln in lines[1:]:
        cells = ln.split(",")
        row = {}
        for c, v in zip(head, cells):
            if v == "":
                row[c] = None
            elif c in PRED_INT:
                row[c] = int(v)
            elif c in PRED_FLOAT:
                row[c] = float(v)
            else:
                row[c] = v
        out.append(row)
    return out


# ================================================================ 보고 도구
def active_episode(ctx: dict, pos: int) -> Optional[dict]:
    """pos 종가 기준 진행 중(전고점 미회복) 사건 중 가장 최근 것 — v1.reading_at 과 같은 규칙."""
    Lv = ctx["Lv"]
    act = [j for j in ctx["eps"] if j["t0"] <= pos and float(np.max(Lv[j["t0"]:pos + 1])) < j["P"]]
    return max(act, key=lambda j: j["t0"]) if act else None


def events_rows(ctx: dict, reader: Callable) -> list:
    """v1.EVENTS 7개마다 대응(v1 과 같은 규칙)·연구별 읽기(reader(ep, d, mapping))·실제."""
    idx, Lv, eps, last = ctx["idx"], ctx["Lv"], ctx["eps"], ctx["last"]
    out = []
    for key, label, date in EVENTS:
        d = int(idx.searchsorted(pd.Timestamp(date)))
        row: dict[str, Any] = {"key": key, "label": label, "date": date, "pos_date": None, "mapping": "none", "episode_id": None,
                               "episode_t0": None, "lag_days": None, "note": "", "study": None, "realized": None}
        if d > last:
            row["note"] = "자료 범위 밖(기준일이 자료 마지막 날 뒤)"
            out.append(row)
            continue
        row["pos_date"] = str(idx[d].date())
        mp = _V1.map_event(eps, Lv, d)
        j = mp["ep"]
        row.update(mapping=mp["mapping"], lag_days=mp["lag_days"])
        if j is None:
            w = ctx["dd252"][d:min(d + 252, last) + 1]
            w = w[np.isfinite(w)]
            row["note"] = (f"−15% 정의로는 사건이 아님 — 기준일부터 1년 안 252일 고점 대비 최저 "
                           f"{'—' if not len(w) else f'{w.min() * 100:.1f}%'}")
            out.append(row)
            continue
        t0s = str(idx[j["t0"]].date())
        row.update(episode_id=j["id"], episode_t0=t0s, era=j["stratum"], dd0=j["dd0"])
        if mp["mapping"] == "trigger":
            row["note"] = f"기준일이 발생일이다(전고점 {idx[j['tP']].date()}, 발생일 깊이 {j['dd0'] * 100:.1f}%)."
        elif mp["mapping"] == "inside":
            near = [r["date"] for r in j["retriggers"] if abs(r["_pos"] - d) <= _V1.RETRIGGER_NEAR]
            row["note"] = (f"**이 정의로는 독립 사건이 아니다 — {t0s} 에 시작된 사건 안({d - j['t0']} 거래일째, "
                           f"그날 전고점 대비 {(Lv[d] / j['P'] - 1) * 100:.1f}%)**"
                           + (f". 같은 고점을 공유해 병합된 재발생일: {', '.join(near)}" if near else ""))
        else:
            row["note"] = f"기준일 뒤 {mp['lag_days']} 거래일({t0s})에 발생일이 왔다."
        row["study"] = reader(j, d, mp["mapping"])
        R = j["R"]
        row["realized"] = {"FD": j["FD"], "rec_date": dstr(j["rec_date"]), "R_years": None if R is None else R / 252.0}
        out.append(row)
    return out


def reading_now(ctx: dict) -> dict:
    """v1 '지금 읽기'의 상태·사건 정보·기준선만 추린 것(pos = 마지막 날)."""
    r = _V1.reading_at(ctx, ctx["last"], bootstrap=False)
    out = {k: r.get(k) for k in ("as_of", "state", "hypothetical", "dd252", "distance_to_trigger", "episode", "others")}
    m1 = r.get("m1") or {}
    out["m1_base"] = (m1.get("pred") or {}).get("BASE")
    out["m1_n_train"] = m1.get("n_train")
    m2 = r.get("m2") or {}
    out["m2_base"] = (m2.get("pred") or {}).get("BASE")
    out["m2_n_train"] = m2.get("n_train")
    return out


def now_line(cur: dict) -> str:
    if cur["state"] == "in_episode":
        return f"급락 사건 진행 중 — {cur['episode']['t0']}부터, 전고점 대비 {cur['episode']['dd_now'] * 100:.1f}%"
    return f"급락 사건 아님 — 252일 고점 대비 {cur['dd252'] * 100:.1f}%" if cur.get("dd252") is not None else "급락 사건 아님"


def summary_line(verdicts: dict, keys, pass_label: str) -> str:
    vs = [verdicts[k] for k in keys]
    return f"{pass_label} {vs.count(pass_label)}/{len(keys)} · FAIL {vs.count('FAIL')} · NOT_EVALUABLE {vs.count('NOT_EVALUABLE')}"


def summary_entry(j: dict) -> str:
    if j["verdict"] == "NOT_EVALUABLE":
        return f"NOT_EVALUABLE · n {j['n']['pooled']} · {j['reason']}"
    return f"{j['verdict']} · n {j['n']['pooled']} · 평균 d {j['mean']['pooled']:+.4f} · p {j['p']:.4f}"


def family_block(study: str) -> dict:
    return {"k": K_FAMILY, "alpha": ALPHA, "alpha_expr": "0.05/15", "keys": [k for k, _s in FAMILY], "this_study": [k for k, s in FAMILY if s == study]}


def lab_constants() -> dict:
    return {"LAB_VERSION": LAB_VERSION, "SEED": SEED, "K_FAMILY": K_FAMILY, "ALPHA": ALPHA, "HOLDOUT_START": HOLDOUT_START,
            "INTL_SPLIT": INTL_SPLIT, "MIN_N_US": MIN_N_US, "MIN_N_INTL": MIN_N_INTL, "CLUSTER_GAP": CLUSTER_GAP,
            "LANDMARKS": list(LANDMARKS), "LB_H": LB_H, "RIDGE_LAMBDA": RIDGE_LAMBDA, "P_CLIP": list(P_CLIP),
            "MIN_CLS_TRAIN": MIN_CLS_TRAIN, "X_FLOOR": X_FLOOR, "GARCH_A": GARCH_A, "GARCH_B": GARCH_B, "N_SIM": N_SIM,
            "N_SIM_SMOKE": N_SIM_SMOKE, "H_SIM": H_SIM, "SIM_MIN_HIST": SIM_MIN_HIST, "RECAL_MIN": RECAL_MIN,
            "RECAL_TAU": RECAL_TAU, "RECAL_PRIOR_N": RECAL_PRIOR_N, "RECAL_CLIP": RECAL_CLIP, "Q": list(Q), "HZ": list(HZ),
            "H": H, "MIN_TRAIN": MIN_TRAIN, "MIN_EVENTS_M2": MIN_EVENTS_M2, "CRASH_TH": CRASH_TH, "END_TH": END_TH}


def v1_check(us_recs: list, base_preds: dict, smoke: bool) -> dict:
    """미국 BASE 랜드마크 0 예측을 v1 결과 파일의 episodes[].m1/m2.pred.BASE 와 비교(보고만).
    base_preds = {t0 문자열: (m1 dict | None, m2 dict | None)}."""
    if smoke:
        return {"skipped": "스모크"}
    path = PROJECT_ROOT / "research" / "results" / "crash-cycle-model-v1" / "results.json"
    try:
        v1r = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"skipped": "v1 결과 파일 없음"}
    d1, d2, n = [], [], 0
    for ep in v1r.get("episodes", []):
        mine = base_preds.get(ep.get("t0"))
        if mine is None:
            continue
        n += 1
        m1v = ((ep.get("m1") or {}).get("pred") or {}).get("BASE")
        m2v = ((ep.get("m2") or {}).get("pred") or {}).get("BASE")
        if m1v and mine[0]:
            d1 += [abs(float(m1v[k]) - mine[0][k]) for k in m1v if k in mine[0]]
        if m2v and mine[1]:
            d2 += [abs(float(m2v[str(h)]) - mine[1][h]) for h in HZ if str(h) in m2v]
    return {"n": n, "max_abs_diff_m1": max(d1) if d1 else None, "max_abs_diff_m2": max(d2) if d2 else None}


def spy_check(state: str, smoke: bool) -> dict:
    return {"available": False, "reason": "스모크"} if smoke else _V1.extra_spy(state)


# ---------------------------------------------------------------- 보고서 공통 조각
def pct(x, nd: int = 1, sign: bool = True) -> str:
    v = fin(x)
    if v is None:
        return "—"
    return f"{v * 100:+.{nd}f}%" if sign else f"{v * 100:.{nd}f}%"


def num(x, nd: int = 4) -> str:
    v = fin(x)
    return "—" if v is None else f"{v:.{nd}f}"


def sgn(x, nd: int = 4) -> str:
    v = fin(x)
    return "—" if v is None else f"{v:+.{nd}f}"


def pval(x) -> str:
    v = fin(x)
    return "—" if v is None else (f"{v:.4f}" if v >= 1e-4 else f"{v:.1e}")


def q3(m1: Optional[dict]) -> str:
    return "—" if not m1 else "/".join(pct(m1.get(k), 0) for k in ("0.1", "0.5", "0.9"))


def r3(m2: Optional[dict]) -> str:
    if not m2:
        return "—"
    g = lambda h: m2.get(h, m2.get(str(h)))  # noqa: E731
    return "/".join(pct(g(h), 0, False) for h in (252, 504, 1260))


def verdict_table(res: dict, model_names: dict, intl: bool = False) -> list:
    st = INTL_STRATA if intl else US_STRATA
    head = "/".join(st)
    L = [f"| 키 | 비교 | 라벨 | n ({head}/합친) | 평균 d ({head}/합친) | p (한쪽 부호 뒤집기) |", "|---|---|---|---|---|---|"]
    for k in res["family"]["this_study"]:
        d = res["detail"][k]
        lab = d["verdict"] + (" (FAIL_UNDERPOWERED)" if d.get("fail_kind") == "FAIL_UNDERPOWERED" else "")
        reason = f" — {d['reason']}" if d["verdict"] == "NOT_EVALUABLE" and d.get("reason") else ""
        fmt = (lambda v: pct(v, 2)) if k.endswith("M3") else (lambda v: sgn(v, 4))
        L.append(f"| {k} | {model_names.get(k, '')} | **{lab}**{reason} | "
                 + "/".join(str(d["n"][s]) for s in st) + f"/{d['n']['pooled']} | "
                 + " / ".join(fmt(d["mean"][s]) for s in st) + f" / {fmt(d['mean']['pooled'])} | {pval(d.get('p'))} |")
    return L


def criteria_paragraph(intl: bool) -> str:
    if intl:
        return (f"판정 기준: 급락 고도화 7연구의 판정 15개를 한 족으로 보고 본페로니 α = 0.05/15 = {ALPHA:.6f}(한쪽). "
                "해외 3지역(유럽·일본·아시아태평양 일본 제외) 사건을 동시 급락 군집(앞 사건과 평일 63일 이내면 같은 군집) 단위로 묶어, "
                "I1(1991~2007)·I2(2008~2024-09) 군집 값을 합친 부호 뒤집기 p < α 이고 I1·I2 평균이 모두 양수여야 통과. "
                "표본 조건 I1 ≥ 3·I2 ≥ 3·합친 ≥ 10 군집. 2024-10 이후 발생 사건은 보고만.")
    return (f"판정 기준: 급락 고도화 7연구의 판정 15개를 한 족으로 보고 본페로니 α = 0.05/15 = {ALPHA:.6f}(한쪽). "
            "미국 사건 시대 A(1927-07~1966)·B(1967~2007)·C(2008-01~2024-09)를 합친 사건 단위 부호 뒤집기 p < α 이고 "
            "A·B·C 각각의 평균도 양수여야 통과. 표본 조건 A ≥ 4·B ≥ 5·C ≥ 4·합친 ≥ 15. 2024-10 이후 발생 사건은 보고만. "
            "**v1(crash-cycle-model-v1)은 A·B 만 판정하고 C 는 보고만 했다 — 이번에는 검정력 때문에 C 를 판정에 넣었고, "
            "C 의 사건들은 이미 v1 보고서에서 본 것이다.**")


def power_lines(res: dict) -> list:
    from core import research_power as rp

    L = [rp.power_line(res["power"]) + " (IR 기준은 일별 활성 수익용 근사이고 이 연구의 실제 기준은 아래 사건 단위다.)", ""]
    parts = []
    for k, pe in res["power_episode"].items():
        pp = pe.get("pass_prob") or {}
        parts.append(f"{k} 합친 n={pe['n']} → 필요 효과 {num(pe.get('needed_effect_sd'), 2)}sd, "
                     f"최소 p {pval(2.0 ** -pe['n']) if pe['n'] else '—'}, "
                     f"통과 확률 δ0.3/0.5/0.8 = " + "/".join(f"{pp[x] * 100:.0f}%" if x in pp else "—" for x in ("0.3", "0.5", "0.8")))
    L += ["사건 단위 검정력: " + " · ".join(parts), ""]
    return L


def report_head(res: dict, title: str, smoke: bool, model_names: dict, intl: bool = False) -> list:
    L = [f"# {title} ({res['study']}{' · 스모크(가짜 자료)' if smoke else ''})", ""]
    if smoke:
        L += ["> 스모크 실행: 가짜 시장 자료라 숫자·라벨에 뜻이 없다. 계산 경로 확인용이다.", ""]
    dt = res["data"]
    L += [f"자료: {dt['source']} · {dt['first_date']} ~ {dt['last_date']} ({dt['n_days']}일) · 규칙 {res['rules']} · "
          f"판정 {res['judge_version']} · 공용 {res['lab_version']}", ""]
    L += ["## 한눈에", ""] + verdict_table(res, model_names, intl)
    L += ["", "평균 d = 기준선 점수 − 모델 점수(양수 = 모델이 더 잘 맞힘). 모델 1 = 평균 핀볼 손실(전고점 대비 소수), "
          "모델 2 = 1·2·3·5년 브라이어 점수 평균(0~1).", "", criteria_paragraph(intl), ""]
    L += power_lines(res)
    L += ["통과는 '설명 도구로 쓸 근거'까지만 뜻한다. **통과해도 엔진·아침 메시지·주문은 바뀌지 않는다**(사용자 확인 뒤 별도 작업).", ""]
    return L


def reading_state_lines(cur: dict) -> list:
    ep = cur.get("episode") or {}
    L = []
    if cur["state"] == "in_episode":
        L += [f"상태: **급락 사건 진행 중** ({cur['as_of']} 기준) — 발생일 {ep.get('t0')}, 전고점 {ep.get('peak_date')}, "
              f"발생일 깊이 {pct(ep.get('dd0'))}, 오늘 전고점 대비 {pct(ep.get('dd_now'))}, 지금까지 최저 {pct(ep.get('min_so_far'))}, "
              f"발생 뒤 {ep.get('e_days')} 거래일.", ""]
    else:
        L += [f"상태: **급락 사건 아님** ({cur['as_of']} 기준) — 252일 고점 대비 {pct(cur.get('dd252'))}, "
              f"−15% 발생까지 더 빠져야 하는 폭 {pct(cur.get('distance_to_trigger'))}.", ""]
    L += ["'지금'은 Ken French 자료 마지막 날 기준이라 오늘과 1~2개월 차이가 날 수 있다.", ""]
    L += [f"v1 기준선(BASE, 같은 날 기준): 최종 깊이 10/50/90% {q3(cur.get('m1_base'))} (학습 {cur.get('m1_n_train', '—')}개) · "
          f"회복 1/2/5년 {r3(cur.get('m2_base'))} (학습 {cur.get('m2_n_train', '—')}개)", ""]
    return L


def spy_line(sc: dict) -> str:
    if sc.get("available"):
        s = f"SPY 확인({sc['date']}): 252일 고점 대비 {pct(sc['dd252'])}."
        if sc.get("lag_warning"):
            s += " Ken French 자료가 늦어 아직 사건으로 잡히지 않았을 수 있다."
        return s
    return f"SPY 확인: 자료 없음({sc.get('reason', '—')})."


def events_note_lines(events: list) -> list:
    mapname = {"trigger": "발생일", "inside": "사건 안", "trigger_after": "뒤에 발생", "none": "사건 아님"}
    L = ["| 사건 | 기준일 | 대응 | 발생일 | 층 | 발생일 깊이 | 실제 최종 깊이 | 실제 회복일 | 실제 회복 기간 |", "|---|---|---|---|---|---|---|---|---|"]
    for e in events:
        r = e.get("realized") or {}
        ry = fin(r.get("R_years"))
        L.append(f"| {e['label']} | {e['pos_date'] or e['date']} | {mapname[e['mapping']]} | {e['episode_t0'] or '—'} | {e.get('era') or '—'} | "
                 f"{pct(e.get('dd0'))} | {pct(r.get('FD'))} | {r.get('rec_date') or ('미회복' if r else '—')} | "
                 f"{'—' if ry is None else f'{ry:.1f}년'} |")
    L.append("")
    for e in events:
        L.append(f"- **{e['label']}** ({e['date']}): {e['note']}")
    L.append("")
    return L


def report_tail(res: dict, limits: list, reading_help: list) -> list:
    L = ["## 검정력과 한계", "", "- **FAIL 은 효과 없음의 증명이 아니다.** 사건 수가 적어 중간 크기 이하의 효과는 원리적으로 못 잡는다."]
    L += [f"- {n}" for n in res["notes"]] + [f"- {n}" for n in limits]
    L += ["", "## 사전 기대와 실제", ""]
    for k, v in res["expected"].items():
        L.append(f"- {k}: 기대 — {v} / 실제 — {res['detail'][k]['verdict']}"
                 + (f" ({res['detail'][k]['fail_kind']})" if res["detail"][k].get("fail_kind") == "FAIL_UNDERPOWERED" else ""))
    L += ["", "## 읽는 법", "",
          "- 핀볼 손실: 최종 깊이 분위수 예측 5개(10·25·50·75·90%)가 실제 최종 깊이에서 빗나간 정도의 평균(전고점 대비 소수). 낮을수록 잘 맞힘.",
          "- 브라이어 점수: 1·2·3·5년 안 회복 확률 예측과 실제(0/1)의 제곱 오차 평균(0~1). 낮을수록 잘 맞힘.",
          "- 회복 확률은 언제나 **예측 시점(asof)부터** h 거래일 안. 252거래일 = 1년.",
          "- d = 기준선 점수 − 모델 점수. 양수면 모델이 더 잘 맞혔다. 판정은 '한눈에'의 검정으로만 한다."]
    L += reading_help
    L += ["- 숫자는 과거 사건 분포다. 성과를 약속하지 않는다."]
    return L


def write_outputs(out_dir, res: dict, report_md: str, rows: list) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "results.json.tmp"
    tmp.write_text(json.dumps(_V1._clean(res), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(out / "results.json")
    (out / "REPORT.md").write_text(report_md, encoding="utf-8")
    write_predictions(rows, out / "predictions.csv")


def run_main(argv, run_fn: Callable, report_fn: Callable) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    Path(a.checkpoint).mkdir(parents=True, exist_ok=True)
    res, rows = run_fn(a.smoke)
    res = _V1._clean(res)
    write_outputs(out, res, report_fn(res, a.smoke), rows)
    print(json.dumps(res["verdicts"], ensure_ascii=False), flush=True)
    return 0
