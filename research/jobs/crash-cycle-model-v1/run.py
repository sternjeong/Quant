"""crash-cycle-model-v1 — 급락장 3모델: 하락 깊이 · 전고점 회복 기간 · 투입 일정. 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/crash-cycle-model-v1/run.py --out OUT --checkpoint CK [--smoke]

- 사건(발생일) = 총수익 지수가 252거래일 고점 대비 −15% 이하가 된 첫날(crash-rebound-signal-v1 의 state_frame·episodes 재사용),
  같은 고점을 공유하는 사건은 병합. 회복 목표 = 그 사건의 전고점 P(발생일까지 252일 최고 종가).
- 모델 1(깊이): 과거 '추가 하락' 분포(기준선) vs 특징 1개 가우스 커널 가중 — 핀볼 손실.
- 모델 2(회복): 카플란-마이어(기준선) vs 베란 가중 KM — 1·2·3·5년 브라이어 점수.
- 모델 3(투입 일정): 다음 날 한 번에(LUMP) vs 달력 고정 DCA6·DCA12·HALF6 — 3년 수익 차이 D, 최악 순간 개선 G.
- 판정 14개, α = 0.05/14, 시대 A+B 합친 부호 뒤집기 검정 유의 + A·B 각각 방향 일치. 2008~(C)는 보고만.
계산은 수십 초라 체크포인트를 쓰지 않는다(계약상 --checkpoint 폴더만 만든다).

미래 정보 규칙:
- 발생일·P·dd0·특징 = t0 종가까지의 정보. 예측은 t0 종가 기준, 투입(모델 3)은 t0+1 종가부터.
- rec·end1·y·FD·trough = 사후. 다른 사건을 예측할 때 학습 자료로 쓰려면 그 예측 시점에 이미 확정되어 있어야 한다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STUDY = "crash-cycle-model-v1"
RULES_VERSION = "crash-cycle/v1"
JUDGE_VERSION = "crash-cycle-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
CRASH_TH, END_TH = -0.15, -0.05
HIGH_WIN = 252
DEPTH_CAP = 756
Q = (0.10, 0.25, 0.50, 0.75, 0.90)
HZ = (252, 504, 756, 1260)
H = 756
H_REPORT = 252
SCHEDULES = {
    "LUMP": [(0, 1.0)],
    "DCA6": [(21 * k, 1 / 6) for k in range(6)],
    "DCA12": [(21 * k, 1 / 12) for k in range(12)],
    "HALF6": [(0, 0.5)] + [(21 * k, 1 / 12) for k in range(1, 7)],
}
MENU = ("DCA6", "DCA12", "HALF6")
FEATURES = ("SPEED", "RUNUP", "FINREL", "RATECHG")
REPORT_FEATURES = ("FINREL49", "NEWS_EPU", "NEWS_GPR")
ALL_FEATURES = FEATURES + REPORT_FEATURES
ALPHA = 0.05 / 14
K_TESTS = 14
MIN_TRAIN = 6
MIN_EVENTS_M2 = 3
MIN_N_A, MIN_N_B, MIN_N_POOLED = 4, 5, 10
SEED = 20261123
SIGNFLIP_EXACT_MAX_N = 16
SIGNFLIP_MC_DRAWS = 200_000
SIGNFLIP_MC_BLOCK = 20_000
G_MIN, D_MARGIN = 0.05, 0.03
TAX = 0.154
TOL = 1e-12
BOOT_B = 1000
ERA_A_YEARS = 39.5
ROBUST_TH = (-0.20, -0.30)
NEWS_LAG = 1
NEWS_WIN = 120
FIN49 = ("Banks", "Insur", "RlEst", "Fin")
RETRIGGER_NEAR = 63          # 7개 사건 문구에 '기준일 근처' 재발생일로 함께 적는 거리(거래일, 보고용 표시 규칙)
DEPTH_BINS = (("FD>-0.25", -0.25, None), ("-0.40<FD<=-0.25", -0.40, -0.25), ("FD<=-0.40", None, -0.40))
ERAS = {"A": ("1927-07-01", "1966-12-31"), "B": ("1967-01-01", "2007-12-31"), "C": ("2008-01-01", None)}
JUDGED = ("A", "B")
EVENTS = (
    ("1987_black_monday", "1987 블랙먼데이", "1987-10-19"),
    ("1998_russia", "1998 러시아 금융위기(LTCM)", "1998-08-17"),
    ("2000_dotcom", "2000 닷컴 버블 붕괴", "2000-03-10"),
    ("2001_911", "2001 9/11 테러", "2001-09-17"),
    ("2008_gfc", "2008 글로벌 금융위기(리먼)", "2008-09-15"),
    ("2020_covid", "2020 코로나19", "2020-02-19"),
    ("2022_inflation", "2022 인플레이션·금리 인상", "2022-01-03"),
)
VERDICT_KEYS = tuple([f"M1_{f}" for f in FEATURES] + [f"M2_{f}" for f in FEATURES]
                     + [f"M3_{s}_{k}" for s in MENU for k in ("RETURN", "INSURANCE")])
LABELS = ("BEATS_BASELINE", "BEATS_LUMP", "CHEAP_INSURANCE", "FAIL", "NOT_EVALUABLE")
NEWS_CSV = PROJECT_ROOT / "research" / "jobs" / "news-core-combo-v1" / "data" / "news_indices_monthly.csv"
FEATURE_LABELS = {"SPEED": "하락 속도(고점→발생일 거래일 로그)", "RUNUP": "직전 2년 상승(로그)",
                  "FINREL": "금융 업종 상대 하락(로그)", "RATECHG": "단기금리 1년 변화(연율)",
                  "FINREL49": "49 산업 금융 상대 하락(보고)", "NEWS_EPU": "뉴스 정책 불확실성(보고)",
                  "NEWS_GPR": "지정학 위험(보고)"}
SCHED_LABELS = {"LUMP": "다음 날 한 번에", "DCA6": "6개월 매달 1/6", "DCA12": "12개월 매달 1/12", "HALF6": "절반 바로 + 절반 6개월"}
ERA_NAMES = {"A": "A 1927~1966 (판정)", "B": "B 1967~2007 (판정)", "C": "C 2008~ (보고만)", "all": "전체"}
_N = NormalDist()


def _load(name: str, rel: str):
    if name in sys.modules and getattr(sys.modules[name], "__file__", None):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cr():
    return _load("crash_rebound_signal_v1_run", "research/jobs/crash-rebound-signal-v1/run.py")


def _lab():
    return _load("core_longrun_lab", "research/jobs/core-longrun-v1/lab.py")


# ---------------------------------------------------------------- 작은 도구
def _fin(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _mean(xs) -> Optional[float]:
    a = [float(v) for v in xs if _fin(v) is not None]
    return float(np.mean(a)) if a else None


def _median(xs) -> Optional[float]:
    a = [float(v) for v in xs if _fin(v) is not None]
    return float(np.median(a)) if a else None


def era_of(date) -> str:
    d = pd.Timestamp(date)
    for k, (a, b) in ERAS.items():
        if d >= pd.Timestamp(a) and (b is None or d <= pd.Timestamp(b)):
            return k
    return "pre"


# ---------------------------------------------------------------- 사건
def recovery_pos(Lv: np.ndarray, t0: int, P: float) -> Optional[int]:
    """t0 뒤 처음으로 Lv ≥ P 가 되는 위치. 자료 끝까지 없으면 None(오른쪽 중도절단)."""
    hit = np.flatnonzero(Lv[t0 + 1:] >= P)
    return int(t0 + 1 + hit[0]) if len(hit) else None


def build_episodes(L: pd.Series, crash_th: float = CRASH_TH, end_th: float = END_TH) -> tuple[list[dict], pd.DataFrame]:
    """부모 사건 목록(병합 뒤)과 state_frame. 사건 i 의 t0·tP·P·dd0·병합 여부는 t0 종가까지의 정보로만 정해진다."""
    cr = _cr()
    frame = cr.state_frame(L, crash_th=crash_th, end_th=end_th)
    assert len(frame) == len(L)
    Lv = L.to_numpy(dtype=float)
    dd = frame["dd"].to_numpy(dtype=float)
    idx = L.index
    last = len(Lv) - 1
    eps: list[dict] = []
    for a, b, open_ in cr.episodes(frame):
        t0 = int(a)
        lo = t0 - (HIGH_WIN - 1)
        tP = lo + int(np.argmax(Lv[lo:t0 + 1]))
        if eps and eps[-1]["tP"] == tP:
            eps[-1]["retriggers"].append({"date": str(idx[t0].date()), "dd252": float(dd[t0]), "_pos": t0})
            continue
        P = float(Lv[tP])
        rec = recovery_pos(Lv, t0, P)
        end1 = min(rec, t0 + DEPTH_CAP) if rec is not None else t0 + DEPTH_CAP
        settled = end1 <= last
        ep = {"t0": t0, "tP": tP, "P": P, "dd0": float(Lv[t0] / P - 1), "house_end": int(b), "house_open": bool(open_),
              "retriggers": [], "rec": rec, "R": None if rec is None else int(rec - t0), "end1": int(end1),
              "depth_settled": bool(settled), "y": None, "FD": None, "trough": None, "era": era_of(idx[t0])}
        if settled:
            seg = Lv[t0:end1 + 1]
            ep["y"] = float(math.log(seg.min() / Lv[t0]))
            ep["FD"] = float((1 + ep["dd0"]) * math.exp(ep["y"]) - 1)
            ep["trough"] = int(t0 + int(np.argmin(seg)))
        eps.append(ep)
    return eps, frame


# ---------------------------------------------------------------- 특징 (모두 t 종가까지)
def features_at(Lv: np.ndarray, Fv: np.ndarray, rfv: np.ndarray, t: int, tP: int, F49v: Optional[np.ndarray] = None) -> dict:
    """판정 특징 4개(+49 산업 금융). 계산 불가면 NaN. t 이후 값은 읽지 않는다."""
    nan = float("nan")
    out = {"SPEED": float(math.log(max(t - tP, 1)))}
    out["RUNUP"] = float(math.log(Lv[tP] / Lv[tP - 504])) if tP >= 504 else nan

    def rel(G):
        if G is None:
            return nan
        g1, g0 = G[t], G[tP]
        if not (np.isfinite(g1) and np.isfinite(g0)) or g1 <= 0 or g0 <= 0:
            return nan
        return float(math.log(g1 / g0) - math.log(Lv[t] / Lv[tP]))

    out["FINREL"] = rel(Fv)
    if t >= 272:
        rfa = lambda u: 252.0 * float(np.mean(rfv[u - 20:u + 1]))  # noqa: E731
        out["RATECHG"] = rfa(t) - rfa(t - 252)
    else:
        out["RATECHG"] = nan
    out["FINREL49"] = rel(F49v)
    return out


def load_news(path: Path = NEWS_CSV) -> Optional[pd.DataFrame]:
    """월별 gpr_hist·epu_news (PeriodIndex). 없으면 None(뉴스 특징 NaN, 실패 아님)."""
    try:
        df = pd.read_csv(path)
        out = pd.DataFrame({"gpr": df["gpr_hist"].astype(float).to_numpy(), "epu": df["epu_news"].astype(float).to_numpy()},
                           index=pd.PeriodIndex(df["month"], freq="M"))
        return out.sort_index()
    except (OSError, KeyError, ValueError):
        return None


def news_features(news: Optional[pd.DataFrame], date) -> dict:
    """NEWS_EPU·NEWS_GPR = ln(x(m−1) / mean(x(m−120 … m−1))), m = date 의 달(공표 지연 1개월). 120개월이 다 있어야 계산."""
    nan = float("nan")
    if news is None or len(news) == 0:
        return {"NEWS_EPU": nan, "NEWS_GPR": nan}
    m = pd.Timestamp(date).to_period("M")
    months = pd.period_range(m - NEWS_WIN, m - NEWS_LAG, freq="M")
    out = {}
    for key, col in (("NEWS_EPU", "epu"), ("NEWS_GPR", "gpr")):
        vals = news[col].reindex(months).to_numpy(dtype=float)
        if len(vals) != NEWS_WIN or not np.all(np.isfinite(vals)) or vals[-1] <= 0 or vals.mean() <= 0:
            out[key] = nan
        else:
            out[key] = float(math.log(vals[-1] / vals.mean()))
    return out


# ---------------------------------------------------------------- 분위수·커널·생존
def wquantile(y, w, q: float) -> float:
    y, w = np.asarray(y, dtype=float), np.asarray(w, dtype=float)
    keep = w > 0
    y, w = y[keep], w[keep]
    order = np.argsort(y, kind="mergesort")
    y, w = y[order], w[order] / w.sum()
    c = np.cumsum(w) - w / 2
    if q <= c[0]:
        return float(y[0])
    if q >= c[-1]:
        return float(y[-1])
    k = int(np.searchsorted(c, q, side="right"))
    return float(y[k - 1] + (q - c[k - 1]) / (c[k] - c[k - 1]) * (y[k] - y[k - 1]))


def pinball(y: float, yhat: float, q: float) -> float:
    return float((y - yhat) * (q - (1.0 if y < yhat else 0.0)))


def kernel_weights(x_train, x_new) -> Optional[np.ndarray]:
    """가우스 커널 유사도 가중(실버먼 대역폭, 그 학습 집합으로 표준화). 계산 불가면 None(= 기준선과 같은 예측)."""
    x = np.asarray(x_train, dtype=float)
    ok = np.isfinite(x)
    m = int(ok.sum())
    if x_new is None or not np.isfinite(float(x_new)) or m < MIN_TRAIN:
        return None
    mu, sd = float(x[ok].mean()), float(x[ok].std(ddof=0))
    if sd <= 1e-12:
        return None
    z, zs = (x[ok] - mu) / sd, (float(x_new) - mu) / sd
    h = 1.06 * m ** (-1 / 5)
    ell = -0.5 * ((z - zs) / h) ** 2
    w_ok = np.exp(ell - ell.max())
    w = np.empty(len(x))
    w[ok] = w_ok
    w[~ok] = w_ok.mean()
    return w


def n_eff(w) -> Optional[float]:
    if w is None:
        return None
    w = np.asarray(w, dtype=float)
    return float(w.sum() ** 2 / (w ** 2).sum())


def wkm(times, events, w=None) -> tuple[np.ndarray, np.ndarray]:
    """가중 카플란-마이어(w 가 모두 같으면 보통 KM, 아니면 베란 추정). 같은 시각 중도절단은 위험 집합에 남긴다."""
    times, events = np.asarray(times, dtype=float), np.asarray(events, dtype=int)
    w = np.ones(len(times)) if w is None else np.asarray(w, dtype=float)
    keep = w > 0
    tau = np.unique(times[keep & (events == 1)])
    S, out = 1.0, []
    for t in tau:
        n = w[keep & (times >= t)].sum()
        d = w[keep & (times == t) & (events == 1)].sum()
        S = S * (1 - d / n) if n > 0 else S
        out.append(S)
    return tau, np.asarray(out, dtype=float)


def surv_at(tau, S, h: float) -> float:
    k = np.flatnonzero(np.asarray(tau) <= h)
    return float(S[k[-1]]) if len(k) else 1.0


def km_median(tau, S) -> Optional[int]:
    k = np.flatnonzero(np.asarray(S) <= 0.5)
    return int(tau[k[0]]) if len(k) else None


def brier(R: int, F: dict) -> float:
    """1·2·3·5년 브라이어 점수 평균. F = {h: 회복 확률}."""
    return float(np.mean([((1.0 if R <= h else 0.0) - F[h]) ** 2 for h in HZ]))


# ---------------------------------------------------------------- 모델 1·2 예측(확장 창)
def m1_train(eps: list[dict], pos: int) -> list[dict]:
    """pos 종가까지 깊이가 확정된 사건(end1 ≤ pos, 같은 날 확정 허용)."""
    return [j for j in eps if j["depth_settled"] and j["end1"] <= pos]


def _fd_quants(y: np.ndarray, w: np.ndarray, dd0: float) -> dict:
    return {f"{q:g}": float((1 + dd0) * math.exp(wquantile(y, w, q)) - 1) for q in Q}


def m1_predict(train: list[dict], feat_new: dict, dd0: float, feats=FEATURES) -> Optional[dict]:
    """과거 추가 하락 y 의 (가중) 분위수를 이번 발생일 깊이 dd0 에서 출발시킨 최종 깊이 FD 분위수."""
    if len(train) < MIN_TRAIN:
        return None
    y = np.array([j["y"] for j in train], dtype=float)
    base = _fd_quants(y, np.ones(len(y)), dd0)
    out = {"n_train": len(train), "pred": {"BASE": base}, "n_eff": {}}
    for f in feats:
        w = kernel_weights([j["feat"][f] for j in train], feat_new.get(f, float("nan")))
        out["pred"][f] = dict(base) if w is None else _fd_quants(y, w, dd0)
        out["n_eff"][f] = n_eff(w)
    return out


def m1_score(FD: float, pred: dict) -> float:
    return float(np.mean([pinball(FD, pred[f"{q:g}"], q) for q in Q]))


def m2_train(eps: list[dict], pos: int) -> tuple[list[dict], np.ndarray, np.ndarray]:
    """t0_j < pos 인 사건. pos 까지 회복했으면 (R, 1), 아니면 (pos − t0, 0)."""
    rows = [j for j in eps if j["t0"] < pos]
    times = np.array([j["R"] if (j["rec"] is not None and j["rec"] <= pos) else pos - j["t0"] for j in rows], dtype=float)
    events = np.array([1 if (j["rec"] is not None and j["rec"] <= pos) else 0 for j in rows], dtype=int)
    return rows, times, events


def _cond_F(tau, S, e: int) -> Optional[dict]:
    s0 = surv_at(tau, S, e)
    if s0 <= 0:
        return None
    return {h: float(1 - surv_at(tau, S, e + h) / s0) for h in HZ}


def m2_predict(rows: list[dict], times, events, feat_new: dict, feats=FEATURES, e_days: int = 0) -> Optional[dict]:
    """회복 확률 F(h) = 1 − S(e+h)/S(e) (평가는 e = 0). 기준선 = KM, 특징 모델 = 베란 가중 KM."""
    if len(rows) < MIN_TRAIN or int(np.sum(events)) < MIN_EVENTS_M2:
        return None
    tau, S = wkm(times, events)
    out = {"n_train": len(rows), "n_events": int(np.sum(events)), "pred": {"BASE": _cond_F(tau, S, e_days)},
           "n_eff": {}, "median_days": km_median(tau, S)}
    for f in feats:
        w = kernel_weights([j["feat"][f] for j in rows], feat_new.get(f, float("nan")))
        if w is None:
            out["pred"][f] = None if out["pred"]["BASE"] is None else dict(out["pred"]["BASE"])
        else:
            t2, s2 = wkm(times, events, w)
            out["pred"][f] = _cond_F(t2, s2, e_days)
        out["n_eff"][f] = n_eff(w)
    return out


# ---------------------------------------------------------------- 모델 3 (달력 고정 일정)
def schedule_path(Lv: np.ndarray, rfv: np.ndarray, e: int, horizon: int, tranches, tax: float = 0.0, with_cash: bool = False):
    """원금 1 의 계좌 가치 경로(path[0] = 1.0). 기다리는 돈은 그날 RF, 마지막 회차는 남은 현금 전부."""
    cash, units = 1.0, 0.0
    path, cash_path = [], []
    offsets = {int(o): float(f) for o, f in tranches}
    last_off = max(offsets)
    for s in range(e, e + horizon + 1):
        if s > e:
            cash *= 1 + rfv[s] * (1 - tax)
        k = s - e
        if k in offsets:
            amt = cash if k == last_off else min(offsets[k], cash)
            units += amt / Lv[s]
            cash -= amt
        path.append(cash + units * Lv[s])
        cash_path.append(cash)
    if with_cash:
        return np.array(path), np.array(cash_path)
    return np.array(path)


def _mdd(path: np.ndarray) -> float:
    return float((path / np.maximum.accumulate(path) - 1).min())


def m3_outcomes(Lv: np.ndarray, rfv: np.ndarray, t0: int, last: int) -> Optional[dict]:
    """발생일 t0 다음 거래일 e 부터 756일. e + 756 > last 면 None(평가 제외)."""
    e = t0 + 1
    if e + H > last:
        return None
    lump = schedule_path(Lv, rfv, e, H, SCHEDULES["LUMP"])
    lump_t = schedule_path(Lv, rfv, e, H, SCHEDULES["LUMP"], tax=TAX)
    lump_minw = float(lump.min() - 1)
    out: dict[str, Any] = {"LUMP": {"minw": lump_minw, "mdd": _mdd(lump)}}
    for s in MENU:
        p = schedule_path(Lv, rfv, e, H, SCHEDULES[s])
        pt = schedule_path(Lv, rfv, e, H, SCHEDULES[s], tax=TAX)
        minw = float(p.min() - 1)
        out[s] = {"D756": float(math.log(p[H]) - math.log(lump[H])),
                  "D252": float(math.log(p[H_REPORT]) - math.log(lump[H_REPORT])),
                  "G": float(minw - lump_minw), "minw": minw, "mdd": _mdd(p),
                  "D_tax": float(math.log(pt[H]) - math.log(lump_t[H]))}
    s_star = e + int(np.argmin(Lv[e:e + H_REPORT + 1]))   # 사후 정보 — 도달 불가 상한
    po = schedule_path(Lv, rfv, e, H, [(s_star - e, 1.0)])
    out["oracle_D"] = float(math.log(po[H]) - math.log(lump[H]))
    return out


def m3_stats(rows: list[dict]) -> dict:
    out: dict[str, Any] = {}
    for s in MENU:
        D = [r["m3"][s]["D756"] for r in rows]
        out[s] = {"n": len(D), "D_mean": _mean(D), "D_median": _median(D),
                  "regret_share": float(np.mean([d < 0 for d in D])) if D else None,
                  "D_p10": float(np.percentile(D, 10)) if D else None,
                  "G_mean": _mean([r["m3"][s]["G"] for r in rows]),
                  "minw_mean": _mean([r["m3"][s]["minw"] for r in rows]),
                  "lump_minw_mean": _mean([r["m3"]["LUMP"]["minw"] for r in rows]),
                  "D252_mean": _mean([r["m3"][s]["D252"] for r in rows]),
                  "D_tax_mean": _mean([r["m3"][s]["D_tax"] for r in rows]),
                  "mdd_mean": _mean([r["m3"][s]["mdd"] for r in rows]),
                  "lump_mdd_mean": _mean([r["m3"]["LUMP"]["mdd"] for r in rows])}
    out["oracle_D_mean"] = _mean([r["m3"]["oracle_D"] for r in rows])
    return out


def m3_menu(eps: list[dict], pos: int) -> dict:
    """pos 종가까지 결과가 끝난(e + 756 ≤ pos) A·B·C 사건으로 일정별 통계, 시대별과 전체."""
    done = [j for j in eps if j["era"] != "pre" and j["m3"] is not None and j["t0"] + 1 + H <= pos]
    out = {era: m3_stats([j for j in done if j["era"] == era]) for era in ("A", "B", "C")}
    out["all"] = m3_stats(done)
    return out


# ---------------------------------------------------------------- 통계·판정
def signflip_p(x) -> dict:
    """한쪽 부호 뒤집기 검정(H1: 평균 > 0). n ≤ 16 정확, 그 위는 몬테카를로(검정마다 default_rng(SEED) 새로)."""
    a0 = np.asarray([float(v) for v in x if _fin(v) is not None], dtype=float)
    n = len(a0)
    out: dict[str, Any] = {"n": n, "mean": float(a0.mean()) if n else None, "p": None, "method": None, "t": None, "p_t": None}
    if n == 0:
        return out
    obs, a = float(a0.mean()), np.abs(a0)
    if n <= SIGNFLIP_EXACT_MAX_N:
        bits = (np.arange(2 ** n)[:, None] >> np.arange(n)) & 1
        stat = ((1 - 2 * bits) * a).mean(axis=1)
        out["p"], out["method"] = float(np.sum(stat >= obs - TOL) / 2 ** n), "exact"
    else:
        rng = np.random.default_rng(SEED)
        cnt = 0
        for _ in range(SIGNFLIP_MC_DRAWS // SIGNFLIP_MC_BLOCK):
            sg = rng.integers(0, 2, size=(SIGNFLIP_MC_BLOCK, n)) * 2 - 1
            cnt += int(np.sum((sg * a).mean(axis=1) >= obs - TOL))
        out["p"], out["method"] = float((1 + cnt) / (1 + SIGNFLIP_MC_DRAWS)), "mc"
    sd = float(a0.std(ddof=1)) if n >= 2 else 0.0
    if n >= 3 and sd > 0:
        t = obs / (sd / math.sqrt(n))
        out["t"], out["p_t"] = float(t), float(_cr().t_sf(t, n - 1))
    return out


def _sample_short(nA: int, nB: int) -> bool:
    return nA < MIN_N_A or nB < MIN_N_B or nA + nB < MIN_N_POOLED


def judge_scores(dA, dB, pass_label: str = "BEATS_BASELINE") -> dict:
    """모델 1·2(d = 기준선 점수 − 모델 점수). 합친 A+B 부호 뒤집기 p < α 이고 A·B 평균이 모두 양수면 통과."""
    from core import research_power as rp

    dA = [float(v) for v in dA if _fin(v) is not None]
    dB = [float(v) for v in dB if _fin(v) is not None]
    d = dA + dB
    if _sample_short(len(dA), len(dB)):
        return {"verdict": "NOT_EVALUABLE", "fail_kind": None, "reason": "표본 부족"}
    guard = rp.noop_guard(d)
    if guard is not None:
        return {"verdict": "NOT_EVALUABLE", "fail_kind": None, "reason": guard}
    mA, mB, m = float(np.mean(dA)), float(np.mean(dB)), float(np.mean(d))
    p = signflip_p(d)["p"]
    if mA > 0 and mB > 0 and p < ALPHA:
        return {"verdict": pass_label, "fail_kind": None, "reason": ""}
    kind = "FAIL_UNDERPOWERED" if (mA > 0 and mB > 0 and m > 0) else "FAIL"
    return {"verdict": "FAIL", "fail_kind": kind, "reason": "합친 p ≥ α 또는 시대 방향 불일치"}


def judge_return(DA, DB) -> dict:
    return judge_scores(DA, DB, pass_label="BEATS_LUMP")


def judge_insurance(DA, DB, GA, GB) -> dict:
    """보험: 최악 순간 개선 G > 5%p 와 손해 D > −3% 를 둘 다 요구(교집합-합집합, 판정 1개)."""
    DA, DB = [float(v) for v in DA], [float(v) for v in DB]
    GA, GB = [float(v) for v in GA], [float(v) for v in GB]
    if _sample_short(len(DA), len(DB)):
        return {"verdict": "NOT_EVALUABLE", "fail_kind": None, "reason": "표본 부족", "p_G": None, "p_D": None}
    gA, gB = [g - G_MIN for g in GA], [g - G_MIN for g in GB]
    cA, cB = [d + D_MARGIN for d in DA], [d + D_MARGIN for d in DB]
    pG, pD = signflip_p(gA + gB)["p"], signflip_p(cA + cB)["p"]
    means = [np.mean(gA), np.mean(gB), np.mean(cA), np.mean(cB)]
    ok = all(m > 0 for m in means) and pG < ALPHA and pD < ALPHA
    if ok:
        return {"verdict": "CHEAP_INSURANCE", "fail_kind": None, "reason": "", "p_G": pG, "p_D": pD}
    allpos = all(m > 0 for m in means) and np.mean(gA + gB) > 0 and np.mean(cA + cB) > 0
    return {"verdict": "FAIL", "fail_kind": "FAIL_UNDERPOWERED" if allpos else "FAIL",
            "reason": "보호 개선 또는 비용 조건 미충족", "p_G": pG, "p_D": pD}


def cluster_p(items: list[tuple[int, int, float]]) -> Optional[float]:
    """결과 구간이 겹치는 사건을 한 군집으로 묶고(구간 합집합) 군집 평균으로 부호 뒤집기 p."""
    items = sorted([it for it in items if _fin(it[2]) is not None])
    if not items:
        return None
    groups, cur, cur_end = [], [items[0][2]], items[0][1]
    for s, e, v in items[1:]:
        if s <= cur_end:
            cur.append(v)
            cur_end = max(cur_end, e)
        else:
            groups.append(float(np.mean(cur)))
            cur, cur_end = [v], e
    groups.append(float(np.mean(cur)))
    return signflip_p(groups)["p"]


# ---------------------------------------------------------------- 7개 사건 대응
def map_event(eps: list[dict], Lv: np.ndarray, d: int) -> dict:
    for j in eps:
        if j["t0"] == d:
            return {"mapping": "trigger", "ep": j, "lag_days": 0}
    inside = [j for j in eps if j["t0"] < d and float(np.max(Lv[j["t0"]:d + 1])) < j["P"]]
    if inside:
        j = max(inside, key=lambda e: e["t0"])
        return {"mapping": "inside", "ep": j, "lag_days": int(d - j["t0"])}
    after = [j for j in eps if d < j["t0"] <= d + 252]
    if after:
        j = min(after, key=lambda e: e["t0"])
        return {"mapping": "trigger_after", "ep": j, "lag_days": int(j["t0"] - d)}
    return {"mapping": "none", "ep": None, "lag_days": None}


# ---------------------------------------------------------------- 맥락(자료 + 사건 + 사건별 모델)
def build_context(L: pd.Series, rf: pd.Series, F: pd.Series, F49: Optional[pd.Series], news, crash_th: float = CRASH_TH) -> dict:
    Lv = L.to_numpy(dtype=float)
    idx = L.index
    rfv = rf.reindex(idx).fillna(0.0).to_numpy(dtype=float)
    Fv = F.reindex(idx).to_numpy(dtype=float)
    F49v = None if F49 is None else F49.reindex(idx).to_numpy(dtype=float)
    eps, frame = build_episodes(L, crash_th, END_TH)
    for j in eps:
        j["feat"] = features_at(Lv, Fv, rfv, j["t0"], j["tP"], F49v)
        j["feat"].update(news_features(news, idx[j["t0"]]))
    ctx = {"idx": idx, "Lv": Lv, "rfv": rfv, "Fv": Fv, "F49v": F49v, "news": news, "eps": eps,
           "dd252": frame["dd"].to_numpy(dtype=float), "last": len(Lv) - 1}
    fill_models(ctx)
    return ctx


def fill_models(ctx: dict) -> None:
    """사건마다 그 발생일 종가 시점 학습 집합으로 모델 1·2 예측, 모델 3 결과."""
    eps, Lv, rfv, last = ctx["eps"], ctx["Lv"], ctx["rfv"], ctx["last"]
    for j in eps:
        p1 = m1_predict(m1_train(eps, j["t0"]), j["feat"], j["dd0"], ALL_FEATURES)
        rows, times, events = m2_train(eps, j["t0"])
        p2 = m2_predict(rows, times, events, j["feat"], ALL_FEATURES)
        j["_p1"], j["_p2"] = p1, p2
        j["_s1"] = {m: m1_score(j["FD"], p1["pred"][m]) for m in ("BASE",) + ALL_FEATURES} if (p1 and j["depth_settled"]) else None
        ok2 = p2 is not None and j["rec"] is not None and all(p2["pred"][m] is not None for m in ("BASE",) + ALL_FEATURES)
        j["_s2"] = {m: brier(j["R"], p2["pred"][m]) for m in ("BASE",) + ALL_FEATURES} if ok2 else None
        j["m3"] = m3_outcomes(Lv, rfv, j["t0"], last)


def collect(ctx: dict, feats=FEATURES) -> dict:
    """판정·보고용 사건 단위 값: (구간 시작, 구간 끝, 값) 을 시대별로."""
    eps, last = ctx["eps"], ctx["last"]
    out: dict[str, Any] = {}
    for f in feats:
        out[f"M1_{f}"] = {e: [(j["t0"], j["end1"], j["_s1"]["BASE"] - j["_s1"][f]) for j in eps if j["era"] == e and j["_s1"]]
                          for e in ("A", "B", "C")}
        out[f"M2_{f}"] = {e: [(j["t0"], j["rec"], j["_s2"]["BASE"] - j["_s2"][f]) for j in eps if j["era"] == e and j["_s2"]]
                          for e in ("A", "B", "C")}
    for s in MENU:
        for kind, key in (("D", "D756"), ("G", "G")):
            out[f"M3_{s}_{kind}"] = {e: [(j["t0"], j["t0"] + 1 + H, j["m3"][s][key]) for j in eps if j["era"] == e and j["m3"]]
                                     for e in ("A", "B", "C")}
    return out


def _vals(items) -> list[float]:
    return [v for _a, _b, v in items]


def _era_block(c: dict) -> tuple[dict, dict]:
    n = {e: len(c[e]) for e in ("A", "B", "C")}
    n["pooled"] = n["A"] + n["B"]
    m = {e: _mean(_vals(c[e])) for e in ("A", "B", "C")}
    m["pooled"] = _mean(_vals(c["A"]) + _vals(c["B"]))
    return n, m


def verdict_block(col: dict) -> tuple[dict, dict, dict]:
    verdicts, detail, diag = {}, {}, {}
    for model in ("M1", "M2"):
        for f in FEATURES:
            key = f"{model}_{f}"
            c = col[key]
            j = judge_scores(_vals(c["A"]), _vals(c["B"]))
            n, m = _era_block(c)
            sp = signflip_p(_vals(c["A"]) + _vals(c["B"]))
            detail[key] = {"verdict": j["verdict"], "fail_kind": j["fail_kind"], "reason": j["reason"], "n": n, "mean": m,
                           "p_signflip": sp["p"], "p_method": sp["method"], "t": sp["t"], "p_t": sp["p_t"],
                           "p_signflip_era": {e: signflip_p(_vals(c[e]))["p"] for e in JUDGED},
                           "p_cluster": cluster_p(c["A"] + c["B"])}
            verdicts[key] = j["verdict"]
    for s in MENU:
        cD, cG = col[f"M3_{s}_D"], col[f"M3_{s}_G"]
        DA, DB, GA, GB = _vals(cD["A"]), _vals(cD["B"]), _vals(cG["A"]), _vals(cG["B"])
        jr = judge_return(DA, DB)
        n, m = _era_block(cD)
        sp = signflip_p(DA + DB)
        key = f"M3_{s}_RETURN"
        detail[key] = {"verdict": jr["verdict"], "fail_kind": jr["fail_kind"], "reason": jr["reason"], "n": n, "mean": m,
                       "p_signflip": sp["p"], "p_method": sp["method"], "t": sp["t"], "p_t": sp["p_t"],
                       "p_signflip_era": {e: signflip_p(_vals(cD[e]))["p"] for e in JUDGED},
                       "p_cluster": cluster_p(cD["A"] + cD["B"])}
        verdicts[key] = jr["verdict"]
        ji = judge_insurance(DA, DB, GA, GB)
        nG, mG = _era_block(cG)
        shift = lambda c, k: [(a, b, v + k) for a, b, v in c]  # noqa: E731
        gpool = shift(cG["A"] + cG["B"], -G_MIN)
        dpool = shift(cD["A"] + cD["B"], D_MARGIN)
        spG, spD = signflip_p(_vals(gpool)), signflip_p(_vals(dpool))
        pGc, pDc = cluster_p(gpool), cluster_p(dpool)
        mD = {e: (None if v is None else v + D_MARGIN) for e, v in m.items()}
        pera = {}
        for e in JUDGED:
            pg = signflip_p([v - G_MIN for v in _vals(cG[e])])["p"]
            pd_ = signflip_p([v + D_MARGIN for v in _vals(cD[e])])["p"]
            pera[e] = None if pg is None or pd_ is None else max(pg, pd_)
        key = f"M3_{s}_INSURANCE"
        detail[key] = {"verdict": ji["verdict"], "fail_kind": ji["fail_kind"], "reason": ji["reason"], "n": nG, "mean": mG,
                       "p_signflip": None if spG["p"] is None or spD["p"] is None else max(spG["p"], spD["p"]),
                       "p_method": spG["method"], "t": spG["t"], "p_t": spG["p_t"], "p_signflip_era": pera,
                       "p_cluster": None if pGc is None or pDc is None else max(pGc, pDc),
                       "insurance": {"G_mean": mG, "p_G": spG["p"], "D_plus_margin_mean": mD, "p_D": spD["p"]}}
        verdicts[key] = ji["verdict"]
        neg = signflip_p([-v for v in DA + DB])["p"]
        if neg is not None and neg < ALPHA:
            diag[s] = "LUMP_BETTER"
        elif jr["verdict"] == "BEATS_LUMP":
            diag[s] = "SCHEDULE_BETTER"
        else:
            diag[s] = "NO_CLEAR_DIFFERENCE"
    return verdicts, detail, diag


def robust_table(col: dict, keys) -> dict:
    """견고성(보고만): 라벨 없이 시대별 n·평균, 합친 A+B 부호 뒤집기 p."""
    out = {}
    for key in keys:
        c = col[key]
        n, m = _era_block(c)
        out[key] = {"n": n, "mean": m, "p_pooled": signflip_p(_vals(c["A"]) + _vals(c["B"]))["p"]}
    return out


# ---------------------------------------------------------------- 지금 읽기 (설명용 — 추천 아님)
def reading_at(ctx: dict, pos: int, bootstrap: bool = False) -> dict:
    """pos 종가까지의 정보로만 만든 읽기. pos 이후 자료는 읽지 않는다(사건 목록도 t0 ≤ pos 만, 사후 값은 pos 까지 확정된 것만)."""
    Lv, idx = ctx["Lv"], ctx["idx"]
    eps = [j for j in ctx["eps"] if j["t0"] <= pos]
    out: dict[str, Any] = {"as_of": str(idx[pos].date())}
    dd252 = float(Lv[pos] / Lv[pos - HIGH_WIN + 1:pos + 1].max() - 1) if pos >= HIGH_WIN - 1 else None
    out["dd252"] = dd252
    active = [j for j in eps if float(np.max(Lv[j["t0"]:pos + 1])) < j["P"]]
    tr1 = m1_train(eps, pos)
    rows, times, events = m2_train(eps, pos)
    if active:
        ep = max(active, key=lambda j: j["t0"])
        P = ep["P"]
        m = float(Lv[ep["t0"]:pos + 1].min() / P - 1)
        e_days = int(pos - ep["t0"])
        out.update(state="in_episode", hypothetical=False,
                   episode={"t0": str(idx[ep["t0"]].date()), "peak_date": str(idx[ep["tP"]].date()), "dd0": ep["dd0"],
                            "dd_now": float(Lv[pos] / P - 1), "min_so_far": m, "e_days": e_days,
                            "retriggers": [{"date": r["date"], "dd252": r["dd252"]} for r in ep["retriggers"] if r["_pos"] <= pos]},
                   others=[str(idx[j["t0"]].date()) for j in active if j is not ep])
        feat, dd0 = ep["feat"], ep["dd0"]
    else:
        lo = pos - HIGH_WIN + 1
        tP = lo + int(np.argmax(Lv[lo:pos + 1]))
        feat = features_at(Lv, ctx["Fv"], ctx["rfv"], pos, tP, ctx["F49v"])
        feat.update(news_features(ctx["news"], idx[pos]))
        dd0, e_days, m = CRASH_TH, 0, None
        out.update(state="not_in_episode", hypothetical=True,
                   distance_to_trigger=None if dd252 is None else float((1 + CRASH_TH) / (1 + dd252) - 1),
                   episode={"peak_date": str(idx[tP].date()), "dd0": dd0, "e_days": 0}, others=[])
    out["features"] = {f: _fin(feat.get(f)) for f in ALL_FEATURES}
    p1 = m1_predict(tr1, feat, dd0, FEATURES)
    out["m1"] = p1 if p1 else {"n_train": len(tr1), "reason": f"학습 사건 부족({len(tr1)})"}
    if m is not None:
        deep = [j["FD"] for j in tr1 if j["FD"] <= m]
        out["m1_already"] = ({"n": len(deep), "q": {f"{q:g}": wquantile(deep, np.ones(len(deep)), q) for q in Q}}
                             if len(deep) >= 3 else {"n": len(deep), "reason": "비교할 과거 사건 부족"})
    p2 = m2_predict(rows, times, events, feat, FEATURES, e_days)
    if p2 is None:
        out["m2"] = {"n_train": len(rows), "n_events": int(np.sum(events)), "e_days": e_days,
                     "reason": f"학습 사건 부족({len(rows)}, 회복 {int(np.sum(events))})"}
    else:
        p2["e_days"] = e_days
        if p2["pred"]["BASE"] is None:
            p2["reason"] = "과거에 이만큼 오래 회복 못 한 사건 없음"
        out["m2"] = p2
    if m is not None:
        low = []
        for j, t_, ev in zip(rows, times, events):
            mj = j["FD"] if (j["depth_settled"] and j["end1"] <= pos) else float(Lv[j["t0"]:pos + 1].min() / j["P"] - 1)
            if mj <= m:
                low.append((j, t_, ev))
        if len(low) >= MIN_TRAIN and sum(ev for _j, _t, ev in low) >= MIN_EVENTS_M2:
            tau, S = wkm([t_ for _j, t_, _e in low], [ev for _j, _t, ev in low])
            cf = _cond_F(tau, S, e_days)
            out["m2_deep"] = {"n": len(low), "n_events": int(sum(ev for _j, _t, ev in low)), "cond": cf,
                              "reason": None if cf is not None else "과거에 이만큼 오래 회복 못 한 사건 없음"}
        else:
            out["m2_deep"] = {"n": len(low), "reason": "비교할 과거 사건 부족"}
    out["m3"] = m3_menu(eps, pos)
    if bootstrap:
        out["bands"] = _bootstrap(eps, pos, tr1, rows, times, events, dd0, e_days)
    return out


def _bootstrap(eps, pos, tr1, rows, times, events, dd0, e_days) -> dict:
    rng = np.random.default_rng(SEED + 1)
    y = np.array([j["y"] for j in tr1], dtype=float)
    done = [j for j in eps if j["era"] != "pre" and j["m3"] is not None and j["t0"] + 1 + H <= pos]
    m1v, m2v = [], []
    m3v = {s: {"D": [], "G": []} for s in MENU}
    for _ in range(BOOT_B):
        if len(y) >= MIN_TRAIN:
            yb = y[rng.integers(0, len(y), len(y))]
            m1v.append([(1 + dd0) * math.exp(wquantile(yb, np.ones(len(yb)), q)) - 1 for q in (0.10, 0.50, 0.90)])
        if len(rows) >= MIN_TRAIN:
            k = rng.integers(0, len(rows), len(rows))
            if events[k].sum() >= MIN_EVENTS_M2:
                tau, S = wkm(times[k], events[k])
                cf = _cond_F(tau, S, e_days)
                m2v.append([cf[h] if cf else np.nan for h in HZ])
            else:
                m2v.append([np.nan] * len(HZ))
        if done:
            k = rng.integers(0, len(done), len(done))
            for s in MENU:
                m3v[s]["D"].append(float(np.mean([done[i]["m3"][s]["D756"] for i in k])))
                m3v[s]["G"].append(float(np.mean([done[i]["m3"][s]["G"] for i in k])))

    def band(a):
        a = np.asarray(a, dtype=float)
        a = a[np.isfinite(a)]
        return [float(np.percentile(a, 10)), float(np.percentile(a, 90))] if len(a) else None

    out: dict[str, Any] = {"B": BOOT_B, "m1_base_fd": {}, "m2_base_cond": {}, "m3": {}}
    if m1v:
        arr = np.array(m1v)
        out["m1_base_fd"] = {f"{q:g}": band(arr[:, i]) for i, q in enumerate((0.10, 0.50, 0.90))}
    if m2v:
        arr = np.array(m2v)
        out["m2_base_cond"] = {str(h): band(arr[:, i]) for i, h in enumerate(HZ)}
    for s in MENU:
        out["m3"][s] = {"D_mean": band(m3v[s]["D"]), "G_mean": band(m3v[s]["G"])}
    return out


# ---------------------------------------------------------------- 보고용 블록
def model1_block(ctx: dict) -> dict:
    eps, by = ctx["eps"], {}
    for era in ("A", "B", "C", "all"):
        es = [j for j in eps if (era == "all" or j["era"] == era)]
        ev = [j for j in es if j["_s1"] and j["era"] != "pre"]
        st = [j for j in es if j["depth_settled"]]
        cov = {}
        for mdl in ("BASE",) + FEATURES:
            hits = [j["_p1"]["pred"][mdl]["0.1"] <= j["FD"] <= j["_p1"]["pred"][mdl]["0.9"] for j in ev]
            cov[mdl] = float(np.mean(hits)) if hits else None
        by[era] = {"n_eval": len(ev), "score_mean": {mdl: _mean([j["_s1"][mdl] for j in ev]) for mdl in ("BASE",) + FEATURES},
                   "coverage80": cov, "FD_mean": _mean([j["FD"] for j in st]), "FD_median": _median([j["FD"] for j in st]),
                   "FD_min": min([j["FD"] for j in st]) if st else None, "y_mean": _mean([j["y"] for j in st]),
                   "y_median": _median([j["y"] for j in st]),
                   "days_to_trough_median": _median([j["trough"] - j["t0"] for j in st]), "n_settled": len(st)}
    return {"by_era": by}


def _km_summary(times, events) -> dict:
    if len(times) == 0:
        return {"F_at": {str(h): None for h in HZ}, "median_days": None, "n": 0, "n_events": 0}
    tau, S = wkm(times, events)
    return {"F_at": {str(h): float(1 - surv_at(tau, S, h)) for h in HZ}, "median_days": km_median(tau, S),
            "n": int(len(times)), "n_events": int(np.sum(events))}


def model2_block(ctx: dict) -> dict:
    eps, last, by = ctx["eps"], ctx["last"], {}
    for era in ("A", "B", "C", "all"):
        es = [j for j in eps if j["era"] != "pre" and (era == "all" or j["era"] == era)]
        ev = [j for j in es if j["_s2"]]
        cens = [j for j in es if j["_p2"] is not None and j["rec"] is None]
        calib = {}
        for h in HZ:
            calib[str(h)] = {"pred_mean": _mean([j["_p2"]["pred"]["BASE"][h] for j in ev]),
                             "obs_rate": float(np.mean([j["R"] <= h for j in ev])) if ev else None}
        by[era] = {"n_eval": len(ev), "n_censored_excluded": len(cens),
                   "score_mean": {mdl: _mean([j["_s2"][mdl] for j in ev]) for mdl in ("BASE",) + FEATURES}, "calib": calib}
    allx = [j for j in eps if j["era"] != "pre"]
    tt = lambda es: (np.array([j["R"] if j["rec"] is not None else last - j["t0"] for j in es], dtype=float),  # noqa: E731
                     np.array([1 if j["rec"] is not None else 0 for j in es], dtype=int))
    km_all = _km_summary(*tt(allx))
    bins = {}
    for name, lo, hi in DEPTH_BINS:
        es = [j for j in allx if j["FD"] is not None and (lo is None or j["FD"] > lo) and (hi is None or j["FD"] <= hi)]
        bins[name] = _km_summary(*tt(es))
    return {"by_era": by, "km_all": km_all, "km_by_depth": bins}


def power_episode(n: int) -> dict:
    if n < 2:
        return {"n_pooled": n, "needed_effect_t": None, "min_p_signflip": None if n < 1 else 2.0 ** -n, "power_at": {}}
    z = _N.inv_cdf(1 - ALPHA)
    return {"n_pooled": n, "needed_effect_t": float(_cr().t_crit(ALPHA, n - 1) / math.sqrt(n)), "min_p_signflip": 2.0 ** -n,
            "power_at": {f"{dl}": float(1 - _N.cdf(z - dl * math.sqrt(n))) for dl in (0.3, 0.5, 0.8)}}


def episode_row(ctx: dict, j: dict) -> dict:
    idx = ctx["idx"]
    dt = lambda p: None if p is None else str(idx[p].date())  # noqa: E731
    row = {"t0": dt(j["t0"]), "era": j["era"], "peak_date": dt(j["tP"]), "dd0": j["dd0"], "house_end": dt(j["house_end"]),
           "house_open": j["house_open"], "retriggers": [{"date": r["date"], "dd252": r["dd252"]} for r in j["retriggers"]],
           "rec_date": dt(j["rec"]), "recovered": j["rec"] is not None, "R_days": j["R"],
           "end1_date": dt(j["end1"]) if j["depth_settled"] else None, "depth_settled": j["depth_settled"], "y": j["y"],
           "FD": j["FD"], "trough_date": dt(j["trough"]), "features": {f: _fin(j["feat"][f]) for f in ALL_FEATURES},
           "m1": None, "m2": None, "m3": j["m3"]}
    if j["_s1"]:
        p = j["_p1"]
        row["m1"] = {"n_train": p["n_train"], "pred": {m: p["pred"][m] for m in ("BASE",) + FEATURES},
                     "n_eff": {f: p["n_eff"][f] for f in FEATURES}, "score": {m: j["_s1"][m] for m in ("BASE",) + FEATURES}}
    if j["_s2"]:
        p = j["_p2"]
        row["m2"] = {"n_train": p["n_train"], "n_events": p["n_events"],
                     "pred": {m: {str(h): v for h, v in p["pred"][m].items()} for m in ("BASE",) + FEATURES},
                     "n_eff": {f: p["n_eff"][f] for f in FEATURES}, "score": {m: j["_s2"][m] for m in ("BASE",) + FEATURES}}
    return row


def _trigger_reading(ctx: dict, j: dict) -> dict:
    p1, p2 = j["_p1"], j["_p2"]
    m1 = ({"n_train": p1["n_train"], "BASE": {k: p1["pred"]["BASE"][k] for k in ("0.1", "0.5", "0.9")},
           "median": {f: p1["pred"][f]["0.5"] for f in FEATURES}}
          if p1 else {"reason": f"학습 사건 부족({len(m1_train(ctx['eps'], j['t0']))})"})
    if p2 and p2["pred"]["BASE"] is not None:
        m2 = {"n_train": p2["n_train"], "BASE": {str(h): p2["pred"]["BASE"][h] for h in HZ},
              "F504": {f: (p2["pred"][f][504] if p2["pred"][f] else None) for f in FEATURES}}
    else:
        m2 = {"reason": f"학습 사건 부족({len(m2_train(ctx['eps'], j['t0'])[0])})"}
    menu = m3_menu(ctx["eps"], j["t0"])["all"]
    m3 = {"n": menu[MENU[0]]["n"], **{s: {"D_mean": menu[s]["D_mean"], "G_mean": menu[s]["G_mean"]} for s in MENU}}
    return {"m1": m1, "m2": m2, "m3_menu": m3}


def events_block(ctx: dict) -> list[dict]:
    idx, Lv, eps, last = ctx["idx"], ctx["Lv"], ctx["eps"], ctx["last"]
    out = []
    for key, label, date in EVENTS:
        d = int(idx.searchsorted(pd.Timestamp(date)))
        row: dict[str, Any] = {"key": key, "label": label, "date": date, "pos_date": None, "mapping": "none", "episode_t0": None,
                               "lag_days": None, "note": "", "trigger_reading": None, "realized": None, "snapshot": None}
        if d > last:
            row["note"] = "자료 범위 밖(기준일이 자료 마지막 날 뒤)"
            out.append(row)
            continue
        row["pos_date"] = str(idx[d].date())
        mp = map_event(eps, Lv, d)
        j = mp["ep"]
        row.update(mapping=mp["mapping"], lag_days=mp["lag_days"])
        if j is None:
            w = ctx["dd252"][d:min(d + 252, last) + 1]
            w = w[np.isfinite(w)]
            row["min_dd252_next_year"] = float(w.min()) if len(w) else None
            row["note"] = (f"−15% 정의로는 사건이 아님 — 기준일부터 1년 안 252일 고점 대비 최저 "
                           f"{'—' if not len(w) else f'{w.min() * 100:.1f}%'}")
            out.append(row)
            continue
        t0s = str(idx[j["t0"]].date())
        row["episode_t0"] = t0s
        row["peak_date"] = str(idx[j["tP"]].date())
        row["dd0"] = j["dd0"]
        row["features"] = {f: _fin(j["feat"][f]) for f in FEATURES + ("NEWS_EPU", "NEWS_GPR")}
        if mp["mapping"] == "trigger":
            row["note"] = f"기준일이 발생일이다(전고점 {idx[j['tP']].date()}, 발생일 깊이 {j['dd0'] * 100:.1f}%)."
        elif mp["mapping"] == "inside":
            near = [r["date"] for r in j["retriggers"] if abs(r["_pos"] - d) <= RETRIGGER_NEAR]
            row["note"] = (f"**이 정의로는 독립 사건이 아니다 — {t0s} 에 시작된 사건 안({d - j['t0']} 거래일째, "
                           f"그날 전고점 대비 {(Lv[d] / j['P'] - 1) * 100:.1f}%)**"
                           + (f". 같은 고점을 공유해 병합된 재발생일: {', '.join(near)}" if near else ""))
        else:
            row["note"] = f"기준일 뒤 {mp['lag_days']} 거래일({t0s})에 발생일이 왔다."
        row["trigger_reading"] = _trigger_reading(ctx, j)
        R = j["R"]
        row["realized"] = {"FD": j["FD"], "trough_date": None if j["trough"] is None else str(idx[j["trough"]].date()),
                           "rec_date": None if j["rec"] is None else str(idx[j["rec"]].date()),
                           "R_years": None if R is None else R / 252.0,
                           "m3": None if j["m3"] is None else {s: {"D756": j["m3"][s]["D756"], "G": j["m3"][s]["G"]} for s in MENU}}
        if mp["mapping"] in ("inside", "trigger_after"):
            row["snapshot"] = reading_at(ctx, d, bootstrap=False)
        out.append(row)
    return out


# ---------------------------------------------------------------- 선택 자료(보고만; 실패하면 '자료 없음')
def extra_price_index(ctx: dict) -> dict:
    try:
        from core.market_data import get_price_history

        s = _cr().price_close(get_price_history("^GSPC", start="1927-01-01", interval="1d"))
        s = s[s > 0]
        if len(s) < HIGH_WIN + 10:
            return {"available": False, "reason": "^GSPC 자료를 받지 못함"}
        eps, _f = build_episodes(s)
        Lp = s.to_numpy(dtype=float)
        rows = []
        tr_events = {e["key"]: e for e in ctx.get("_events", [])}
        for key, label, date in EVENTS:
            d = int(s.index.searchsorted(pd.Timestamp(date)))
            if d >= len(s):
                rows.append({"key": key, "label": label, "mapping": "none"})
                continue
            mp = map_event(eps, Lp, d)
            j = mp["ep"]
            r = {"key": key, "label": label, "mapping": mp["mapping"]}
            if j is not None:
                r.update(t0=str(s.index[j["t0"]].date()), peak_date=str(s.index[j["tP"]].date()),
                         rec_date=None if j["rec"] is None else str(s.index[j["rec"]].date()),
                         R_years=None if j["R"] is None else j["R"] / 252.0)
            tr = tr_events.get(key, {}).get("realized") or {}
            r["tr_R_years"] = tr.get("R_years")
            rows.append(r)
        return {"available": True, "first_date": str(s.index[0].date()), "last_date": str(s.index[-1].date()),
                "n_episodes": len(eps), "events": rows}
    except Exception as exc:  # noqa: BLE001 — 보고만, 실패해도 판정·종료 코드 불변
        return {"available": False, "reason": f"{type(exc).__name__}"}


def extra_real_cpi(ctx: dict) -> dict:
    try:
        from core.fred_data import get_series

        cpi = get_series("CPIAUCSL")
        if cpi is None or len(cpi) == 0:
            return {"available": False, "reason": "FRED CPIAUCSL 없음(키 없음 또는 호출 실패)"}
        cpi = cpi.astype(float).dropna()
        cpi.index = pd.DatetimeIndex(cpi.index).to_period("M")
        idx, Lv = ctx["idx"], ctx["Lv"]
        c = cpi.groupby(level=0).last().reindex(idx.to_period("M")).to_numpy(dtype=float)
        Lr = Lv / c
        rows = []
        for j in ctx["eps"]:
            if idx[j["tP"]] < pd.Timestamp("1947-01-01") or not np.isfinite(Lr[j["tP"]]):
                continue
            Pr = Lr[j["tP"]]
            hit = np.flatnonzero(np.nan_to_num(Lr[j["t0"] + 1:], nan=-np.inf) >= Pr)
            rr = None if not len(hit) else int(j["t0"] + 1 + hit[0])
            rows.append({"t0": str(idx[j["t0"]].date()), "era": j["era"],
                         "nominal_rec": None if j["rec"] is None else str(idx[j["rec"]].date()),
                         "nominal_R_years": None if j["R"] is None else j["R"] / 252.0,
                         "real_rec": None if rr is None else str(idx[rr].date()),
                         "real_R_years": None if rr is None else (rr - j["t0"]) / 252.0})
        return {"available": True, "episodes": rows}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}"}


def extra_spy(state: str) -> dict:
    try:
        from core.market_data import get_price_history

        s = _cr().price_close(get_price_history("SPY", start="1993-01-01", interval="1d"))
        if len(s) < HIGH_WIN:
            return {"available": False, "reason": "SPY 자료를 받지 못함"}
        dd = float(s.iloc[-1] / s.iloc[-HIGH_WIN:].max() - 1)
        return {"available": True, "date": str(s.index[-1].date()), "dd252": dd,
                "lag_warning": bool(state == "not_in_episode" and dd <= CRASH_TH)}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}"}


# ---------------------------------------------------------------- 자료
def load(smoke: bool) -> dict:
    lab = _lab()
    d = lab.synthetic_data() if smoke else lab.load_real()
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
        cols49 = [c for c in FIN49 if c in i49.columns]
        if cols49:
            r = i49.reindex(L.index)[cols49].mean(axis=1, skipna=True)
            started = r.notna().cummax()
            F49 = (1 + r.fillna(0.0)).cumprod().where(started)
    return {"L": L, "rf": rf, "F": F, "F49": F49, "fin_column": fin_col, "fin49_columns": cols49,
            "source": d.get("source", "synthetic (smoke)" if smoke else "Ken French")}


# ---------------------------------------------------------------- 평가
EXPECTED = {
    "M1": "4개 모두 FAIL 또는 NOT_EVALUABLE 예상(보통 크기 낙폭은 무기억에 가깝다 — Johansen·Sornette; 큰 사건은 시대당 2~3개). 그나마 가능성은 FINREL.",
    "M2": "FAIL 예상. 회복 기간은 사후 깊이에 대부분 달려 있고 발생일 특징의 추가 설명력은 작을 것.",
    "M3_return": "3개 모두 FAIL, 시대 B 에서 D 평균 음수 예상(crash-rebound-signal-v1·dca-dip-deploy-v1·Vanguard·AQR 'Hold the Dip'). 진단은 LUMP_BETTER 가능.",
    "M3_insurance": "불확실. HALF6·DCA6 은 통과 가능성이 있고 DCA12 는 비용 한도(3%)를 넘을 가능성이 있다.",
}
NOTES = [
    "사건 수가 적다(시대당 약 11~12, 병합 뒤 그보다 적을 수 있음; 모델 1·2 의 시대 A 평가는 약 5개). 중간 크기 이하 효과는 원리적으로 못 잡는다.",
    "사건이 독립이 아니다: 1930년대에 몰려 있고, 회복 구간·3년 투입 구간이 겹친다. 판정은 사건 단위, 군집 단위는 보고만 — 겹침 때문에 판정 p 는 실제보다 낙관적일 수 있다.",
    "미국 한 시장(가장 잘된 시장)의 생존 편향. 일본 1989 같은 사례가 표본에 없다.",
    "총수익·명목 기준. 가격 지수·실질 기준 회복은 훨씬 길 수 있다(선택 자료로만 보고).",
    "전고점 P 는 '발생일까지 1년 안 최고점'이다. 1930년대처럼 이전 고점을 회복하지 못한 채 새 사건이 생기면 그 사건의 P 는 사상 최고점보다 낮다.",
    "최종 깊이는 3년에서 자른다.",
    "정책 대응(금리 인하·양적 완화)은 발생일에 알 수 없어 특징이 아니라 시대 효과로 남는다. 2008 이후(C) 결과가 다를 수 있다.",
    "같은 급락 사건 날짜를 이 저장소에서 네 번째로 쓴다(crash-inverse·crash-rebound-signal·crash-industry-pick). 특징은 선행연구로만 골랐고 기존 결과를 보고 고르지 않았다.",
    "세금·비용: 모델 3 은 이자소득세 변형만 보고. 양도세·환전·수수료 미반영.",
    "판정 통과는 '설명 도구로 쓸 근거'까지만 뜻한다. 엔진·아침 메시지·주문 반영은 사용자 확인 뒤 별도 작업.",
]


def _summary_line(verdicts: dict, keys, pass_label: str, k: int) -> str:
    vs = [verdicts[x] for x in keys]
    return f"{pass_label} {vs.count(pass_label)}/{k} · FAIL {vs.count('FAIL')} · NOT_EVALUABLE {vs.count('NOT_EVALUABLE')}"


def evaluate(data: dict, smoke: bool, news=None) -> dict:
    from core import research_power as rp

    ctx = build_context(data["L"], data["rf"], data["F"], data["F49"], news)
    idx, last = ctx["idx"], ctx["last"]
    col = collect(ctx, ALL_FEATURES)
    verdicts, detail, diag = verdict_block(col)
    events = events_block(ctx)
    ctx["_events"] = events
    current = reading_at(ctx, last, bootstrap=True)
    current["spy_check"] = {"available": False, "reason": "스모크"} if smoke else extra_spy(current["state"])
    if current["state"] == "in_episode":
        now = f"급락 사건 진행 중 — {current['episode']['t0']}부터, 전고점 대비 {current['episode']['dd_now'] * 100:.1f}%"
    else:
        now = f"급락 사건 아님 — 252일 고점 대비 {current['dd252'] * 100:.1f}%" if current["dd252"] is not None else "급락 사건 아님"
    summary = {"모델1 하락 깊이": _summary_line(verdicts, [f"M1_{f}" for f in FEATURES], "BEATS_BASELINE", 4),
               "모델2 회복 기간": _summary_line(verdicts, [f"M2_{f}" for f in FEATURES], "BEATS_BASELINE", 4),
               "모델3 수익(대 한 번에)": _summary_line(verdicts, [f"M3_{s}_RETURN" for s in MENU], "BEATS_LUMP", 3),
               "모델3 보험": _summary_line(verdicts, [f"M3_{s}_INSURANCE" for s in MENU], "CHEAP_INSURANCE", 3),
               f"지금(Ken French {current['as_of']})": now}
    # 견고성(보고만, 라벨 없음)
    robust: dict[str, Any] = {}
    for th in ROBUST_TH:
        c2 = build_context(data["L"], data["rf"], data["F"], data["F49"], news, crash_th=th)
        col2 = collect(c2, FEATURES)
        keys = [f"M1_{f}" for f in FEATURES] + [f"M2_{f}" for f in FEATURES] + [f"M3_{s}_{k}" for s in MENU for k in ("D", "G")]
        robust[f"th_{th:.2f}"] = {"n_episodes": len(c2["eps"]), "table": robust_table(col2, keys)}
    if data["F49"] is not None:
        robust["finrel49"] = {"available": True, "table": robust_table(col, ["M1_FINREL49", "M2_FINREL49"])}
    else:
        robust["finrel49"] = {"available": False, "reason": "49 산업 금융 열 없음" + (" (스모크)" if smoke else "")}
    if news is not None:
        robust["news"] = {"available": True, "table": robust_table(col, [f"M{m}_{f}" for m in (1, 2) for f in ("NEWS_EPU", "NEWS_GPR")])}
    else:
        robust["news"] = {"available": False, "reason": "뉴스 CSV 없음"}
    robust["cluster"] = {k: detail[k]["p_cluster"] for k in VERDICT_KEYS}
    robust["tax"] = {s: {e: robust_mean(ctx, s, e) for e in ("A", "B", "C")} for s in MENU}
    if smoke:
        robust["price_index"] = {"available": False, "reason": "스모크"}
        robust["real_cpi"] = {"available": False, "reason": "스모크"}
    else:
        robust["price_index"] = extra_price_index(ctx)
        robust["real_cpi"] = extra_real_cpi(ctx)
    m1b, m2b = model1_block(ctx), model2_block(ctx)
    m3b = {"by_era": {e: m3_stats([j for j in ctx["eps"] if j["m3"] and (e == "all" and j["era"] != "pre" or j["era"] == e)])
                      for e in ("A", "B", "C", "all")}}
    n1 = detail["M1_SPEED"]["n"]["pooled"]
    n2 = detail["M2_SPEED"]["n"]["pooled"]
    n3 = detail[f"M3_{MENU[0]}_RETURN"]["n"]["pooled"]
    res = {
        "study": STUDY, "rules": RULES_VERSION, "judge_version": JUDGE_VERSION, "smoke": bool(smoke),
        "data": {"source": data["source"], "first_date": str(idx[0].date()), "last_date": str(idx[-1].date()),
                 "n_days": int(len(idx)), "fin_column": data["fin_column"], "fin49_columns": data["fin49_columns"],
                 "network_extras": {"gspc": bool(robust["price_index"].get("available")),
                                    "spy": bool(current["spy_check"].get("available")),
                                    "cpi": bool(robust["real_cpi"].get("available"))}},
        "constants": {"CRASH_TH": CRASH_TH, "END_TH": END_TH, "HIGH_WIN": HIGH_WIN, "DEPTH_CAP": DEPTH_CAP, "Q": list(Q),
                      "HZ": list(HZ), "H": H, "H_REPORT": H_REPORT, "SCHEDULES": {k: [list(t) for t in v] for k, v in SCHEDULES.items()},
                      "FEATURES": list(FEATURES), "MIN_TRAIN": MIN_TRAIN, "MIN_EVENTS_M2": MIN_EVENTS_M2, "MIN_N_A": MIN_N_A,
                      "MIN_N_B": MIN_N_B, "MIN_N_POOLED": MIN_N_POOLED, "ALPHA": ALPHA, "K": K_TESTS, "G_MIN": G_MIN,
                      "D_MARGIN": D_MARGIN, "TAX": TAX, "SEED": SEED, "SIGNFLIP_EXACT_MAX_N": SIGNFLIP_EXACT_MAX_N,
                      "SIGNFLIP_MC_DRAWS": SIGNFLIP_MC_DRAWS, "BOOT_B": BOOT_B, "EVENTS": [list(e) for e in EVENTS],
                      "ERAS": {k: list(v) for k, v in ERAS.items()}, "ROBUST_TH": list(ROBUST_TH)},
        "alpha": ALPHA, "k_tests": K_TESTS,
        "power": rp.power_report(ERA_A_YEARS, K_TESTS),
        "power_episode": {"M1": power_episode(n1), "M2": power_episode(n2), "M3": power_episode(n3)},
        "verdicts": verdicts, "summary": summary, "detail": detail, "diagnostics": diag,
        "episodes": [episode_row(ctx, j) for j in ctx["eps"]],
        "model1": m1b, "model2": m2b, "model3": m3b,
        "events": events, "current": current, "robustness": robust, "expected": EXPECTED, "notes": NOTES,
    }
    return res


def robust_mean(ctx: dict, s: str, era: str) -> Optional[float]:
    return _mean([j["m3"][s]["D_tax"] for j in ctx["eps"] if j["era"] == era and j["m3"]])


# ---------------------------------------------------------------- 보고서
def _pct(x, nd: int = 1, sign: bool = True) -> str:
    v = _fin(x)
    if v is None:
        return "—"
    return f"{v * 100:+.{nd}f}%" if sign else f"{v * 100:.{nd}f}%"


def _pp(x, nd: int = 1) -> str:
    v = _fin(x)
    return "—" if v is None else f"{v * 100:+.{nd}f}%p"


def _p(x) -> str:
    v = _fin(x)
    return "—" if v is None else (f"{v:.4f}" if v >= 1e-4 else f"{v:.1e}")


def _num(x, nd: int = 2) -> str:
    v = _fin(x)
    return "—" if v is None else f"{v:.{nd}f}"


def _yrs(days) -> str:
    v = _fin(days)
    return "—" if v is None else f"{v / 252:.1f}년"


def _reading_lines(r: dict, bands: Optional[dict] = None, heading: str = "###") -> list[str]:
    L: list[str] = []
    ep = r["episode"]
    if r["state"] == "in_episode":
        L += [f"{heading} 상태: 급락 사건 진행 중 ({r['as_of']} 기준)", "",
              "| 항목 | 값 |", "|---|---|",
              f"| 발생일 | {ep['t0']} |", f"| 전고점 날짜 | {ep['peak_date']} |",
              f"| 발생일 깊이(전고점 대비) | {_pct(ep['dd0'])} |", f"| 오늘 전고점 대비 | {_pct(ep['dd_now'])} |",
              f"| 지금까지 최저(전고점 대비) | {_pct(ep['min_so_far'])} |", f"| 발생일 뒤 경과 | {ep['e_days']} 거래일 ({ep['e_days'] / 252:.1f}년) |"]
        if ep.get("retriggers"):
            L.append(f"| 병합된 재발생일 | {', '.join(x['date'] for x in ep['retriggers'])} |")
        if r.get("others"):
            L.append(f"| 함께 미회복인 이전 사건 | {', '.join(r['others'])} |")
    else:
        L += [f"{heading} 상태: 급락 사건 아님 ({r['as_of']} 기준)", "",
              "| 항목 | 값 |", "|---|---|",
              f"| 252일 고점 대비 | {_pct(r['dd252'])} |",
              f"| −15% 발생까지 더 빠져야 하는 폭 | {_pct(r.get('distance_to_trigger'))} |",
              f"| 가상 전고점 날짜 | {ep['peak_date']} |", "",
              "아래 모델 표는 **만약 오늘이 발생일이라면**(발생일 깊이 −15% 로 고정, 특징은 오늘 값) 이라는 가상 읽기다."]
    L += ["", "특징 값(그날 종가까지): " + " · ".join(f"{f} {_num(r['features'].get(f), 3)}" for f in ALL_FEATURES), ""]
    m1 = r["m1"]
    if "pred" in m1:
        b1 = (bands or {}).get("m1_base_fd") or {}
        L += [f"**모델 1 — 최종 깊이 분포(전고점 대비, %)** · 학습 사건 {m1['n_train']}개", "",
              "| 분위수 | 기준선(BASE) | 80% 부트스트랩 범위 | " + " | ".join(FEATURES) + " |",
              "|---|---|---|" + "---|" * len(FEATURES)]
        for q in Q:
            k = f"{q:g}"
            bd = b1.get(k)
            L.append(f"| {int(q * 100)}% | {_pct(m1['pred']['BASE'][k])} | {'—' if not bd else _pct(bd[0]) + ' ~ ' + _pct(bd[1])} | "
                     + " | ".join(_pct(m1["pred"][f][k]) for f in FEATURES) + " |")
        L += ["", "특징 모델 유효 표본 수 n_eff: " + " · ".join(f"{f} {_num(m1['n_eff'].get(f), 1)}" for f in FEATURES)
              + " (— = 계산 불가로 기준선과 같음)", ""]
    else:
        L += [f"모델 1: {m1.get('reason')}", ""]
    if "m1_already" in r:
        a = r["m1_already"]
        if "q" in a:
            L += [f"이미 지금만큼 빠진 과거 사건 {a['n']}개의 최종 깊이: 10% {_pct(a['q']['0.1'])} · 50% {_pct(a['q']['0.5'])} · 90% {_pct(a['q']['0.9'])}", ""]
        else:
            L += [f"이미 지금만큼 빠진 과거 사건: {a['reason']}({a['n']}개)", ""]
    m2 = r["m2"]
    if m2.get("pred") and m2["pred"].get("BASE"):
        b2 = (bands or {}).get("m2_base_cond") or {}
        cond = "아직 회복 못 한 채 경과한 지금부터 " if m2.get("e_days") else ""
        L += [f"**모델 2 — {cond}전고점 회복 확률(%)** · 학습 사건 {m2['n_train']}개(회복 {m2['n_events']})", "",
              "| 모델 | 1년 안 | 2년 안 | 3년 안 | 5년 안 |", "|---|---|---|---|---|"]
        L.append("| 기준선(BASE) | " + " | ".join(_pct(m2["pred"]["BASE"][str(h)], 0, False) for h in HZ) + " |")
        if b2:
            L.append("| BASE 80% 범위 | " + " | ".join("—" if not b2.get(str(h)) else f"{b2[str(h)][0] * 100:.0f}~{b2[str(h)][1] * 100:.0f}%" for h in HZ) + " |")
        for f in FEATURES:
            pf = m2["pred"].get(f)
            L.append(f"| {f} | " + " | ".join("—" if not pf else _pct(pf[str(h)], 0, False) for h in HZ) + " |")
        L.append("")
    else:
        L += [f"모델 2: {m2.get('reason')}", ""]
    if "m2_deep" in r:
        d2 = r["m2_deep"]
        if d2.get("cond"):
            L += [f"설명용: 지금까지 최저보다 더 빠졌던 과거 사건 {d2['n']}개만의 같은 조건부 회복 확률 — "
                  + " · ".join(f"{h // 252}년 {_pct(d2['cond'][str(h)], 0, False)}" for h in HZ), ""]
        else:
            L += [f"설명용 '더 빠졌던 사건만' 회복 확률: {d2.get('reason')}({d2.get('n')}개)", ""]
    m3 = r["m3"]["all"]
    b3 = (bands or {}).get("m3") or {}
    L += [f"**모델 3 — 끝난 과거 사건 {m3[MENU[0]]['n']}개(A+B+C)의 일정 비교** (D = 3년 뒤 한 번에 넣기 대비 로그 차이, G = 최악 순간 개선)", "",
          "| 일정 | 평균 D | 후회 비율(D<0) | 평균 G | 최악 10% D | D 80% 범위 | G 80% 범위 |", "|---|---|---|---|---|---|---|"]
    for s in MENU:
        x = m3[s]
        bd = b3.get(s, {})
        rng_ = lambda v: "—" if not v else f"{_pct(v[0])} ~ {_pct(v[1])}"  # noqa: E731
        rngp = lambda v: "—" if not v else f"{_pp(v[0])} ~ {_pp(v[1])}"  # noqa: E731
        L.append(f"| {s} ({SCHED_LABELS[s]}) | {_pct(x['D_mean'])} | {_pct(x['regret_share'], 0, False)} | {_pp(x['G_mean'])} | "
                 f"{_pct(x['D_p10'])} | {rng_(bd.get('D_mean'))} | {rngp(bd.get('G_mean'))} |")
    L.append("")
    return L


def report(res: dict, smoke: bool) -> str:
    from core import research_power as rp

    V, Dt = res["verdicts"], res["detail"]
    L = [f"# 급락장 3모델 — 하락 깊이 · 전고점 회복 기간 · 투입 일정 ({STUDY}{' · 스모크(가짜 자료)' if smoke else ''})", ""]
    if smoke:
        L += ["> 스모크 실행: 가짜 시장 자료라 숫자·라벨에 뜻이 없다. 계산 경로 확인용이다.", ""]
    L += [f"자료: {res['data']['source']} · {res['data']['first_date']} ~ {res['data']['last_date']} ({res['data']['n_days']}일) · "
          f"규칙 {RULES_VERSION} · 판정 {JUDGE_VERSION}", ""]
    # 1. 한눈에
    L += ["## 한눈에", "", "| 모델 | 특징·일정 | 라벨 | 합친 n (A+B) | 평균 차이 (A / B / 합친) | p (부호 뒤집기) |", "|---|---|---|---|---|---|"]
    for key in VERDICT_KEYS:
        d = Dt[key]
        model, rest = key.split("_", 1)
        fmt = (lambda v: _pp(v, 2)) if model == "M1" else ((lambda v: _num(v, 4)) if model == "M2" else (lambda v: _pct(v)))
        if key.endswith("INSURANCE"):
            fmt = lambda v: _pp(v)  # noqa: E731
        lab = d["verdict"] + (f" ({d['fail_kind']})" if d["fail_kind"] == "FAIL_UNDERPOWERED" else "")
        reason = f" — {d['reason']}" if d["verdict"] == "NOT_EVALUABLE" else ""
        L.append(f"| {model} | {rest} | **{lab}**{reason} | {d['n']['pooled']} | {fmt(d['mean']['A'])} / {fmt(d['mean']['B'])} / "
                 f"{fmt(d['mean']['pooled'])} | {_p(d['p_signflip'])} |")
    pe = res["power_episode"]
    L += ["", "평균 차이 단위: 모델 1 = 평균 핀볼 손실 차이(기준선 − 특징 모델, %p; 양수면 특징 모델이 더 잘 맞힘), "
          "모델 2 = 브라이어 점수 차이(기준선 − 특징 모델), 모델 3 수익 = D(일정 − 한 번에, 3년 로그 %), 보험 = G(최악 순간 개선, %p; p 는 G·비용 두 검정 중 큰 값).", "",
          f"판정 기준: 판정 14개 전체에 본페로니 α = 0.05/14 = {ALPHA:.6f}. 시대 A(1927-07~1966)와 B(1967~2007)를 합친 사건 목록에서 "
          "한쪽 부호 뒤집기 검정 p < α 이고, A·B 각각의 평균도 같은 방향(양수)이어야 통과. 표본 조건 A ≥ 4·B ≥ 5·합친 ≥ 10. "
          "2008 이후(C)는 표에 나오지만 판정에 넣지 않는다.", "",
          rp.power_line(res["power"]) + " (위 IR 기준은 일별 활성 수익용 근사이고 이 연구의 실제 기준은 아래 사건 단위 표다.)", "",
          "사건 단위 검정력: " + " · ".join(
              f"{m} 합친 n={pe[m]['n_pooled']} → 필요 효과 {_num(pe[m]['needed_effect_t'])}sd, 최소 p {_p(2.0 ** -pe[m]['n_pooled'] if pe[m]['n_pooled'] else None)}, "
              f"통과 확률 δ0.3/0.5/0.8 = " + "/".join(f"{pe[m]['power_at'].get(k, 0) * 100:.0f}%" for k in ("0.3", "0.5", "0.8"))
              for m in ("M1", "M2", "M3")), "",
          "모델 3 진단(판정 아님): " + " · ".join(f"{s} {res['diagnostics'][s]}" for s in MENU), "",
          "통과해도 엔진·주문은 바뀌지 않는다(사용자 확인 뒤 별도 작업).", ""]
    # 2. 묻는 것
    L += ["## 이 연구가 묻는 것", "",
          "- **발생일**: 총수익(배당 포함) 지수가 1년(252거래일) 최고점보다 15% 아래로 처음 내려간 날. 같은 고점을 공유하는 재발생은 한 사건으로 합친다.",
          "- **전고점**: 발생일까지 1년 안의 최고점(그 사건의 회복 목표).",
          "- **최종 깊이**: 전고점 대비, 회복 전·발생일 뒤 3년 안의 최저점.",
          "- **회복 기간**: 발생일부터 전고점을 다시 넘은 날까지(거래일, 252거래일 = 1년).",
          "- **일정**: LUMP(다음 날 한 번에) · DCA6(6개월 매달 1/6) · DCA12(12개월 매달 1/12) · HALF6(절반 바로 + 절반 6개월). 기다리는 돈은 단기금리(RF)를 받는다.",
          "- 질문: (1) 발생일에 알 수 있는 특징 하나로 비슷한 과거 사건에 가중을 주면 최종 깊이·회복 확률을 가중치 없는 과거 분포보다 잘 맞히나, "
          "(2) 달력 고정 분할 투입이 한 번에 넣기보다 3년 뒤 더 많이 남기나, 또는 적은 비용으로 최악 순간을 덜 아프게 하나.",
          "- 총수익(배당 포함) 기준이라 뉴스의 S&P 500 가격 지수보다 회복이 빠르게 나온다.", ""]
    # 3. 지금 읽기
    cur = res["current"]
    L += ["## 지금 읽기 (설명용 — 추천 아님)", "",
          "아래는 과거 사건 분포를 지금에 대어 본 **설명**이다. 매수·매도 추천이 아니며 엔진·주문에 연결되지 않는다. "
          "판정을 통과하지 못한 특징 모델의 값은 참고만 하고 기준선(가중치 없는 과거 분포)을 먼저 본다.", ""]
    L += _reading_lines(cur, cur.get("bands"))
    sc = cur.get("spy_check") or {}
    if sc.get("available"):
        L.append(f"SPY 확인({sc['date']}): 252일 고점 대비 {_pct(sc['dd252'])}.")
        if sc.get("lag_warning"):
            L.append("Ken French 자료가 늦어 아직 사건으로 잡히지 않았을 수 있다. 위 '만약 오늘 발생일이라면' 표를 참고.")
    else:
        L.append(f"SPY 확인: 자료 없음({sc.get('reason', '—')}).")
    n_tr = cur["m1"].get("n_train", "—")
    L += ["", f"불확실성: 학습 사건은 모델 1 {n_tr}개, 모델 2 {cur['m2'].get('n_train', '—')}개다. 범위는 학습 사건을 복원 추출로 "
          f"{BOOT_B}번 다시 뽑은 10~90 백분위다. 표본이 30개 남짓이라 범위가 넓다.", ""]
    # 4. 7개 사건
    mapname = {"trigger": "발생일", "inside": "사건 안", "trigger_after": "뒤에 발생", "none": "사건 아님"}
    L += ["## 사용자가 든 7개 사건", "", "### 대응과 발생일 특징 (발생일 종가까지)", "",
          "| 사건 | 기준일 | 대응 | 발생일 | 전고점일 | 발생일 깊이 | SPEED | RUNUP | FINREL | RATECHG | NEWS_EPU | NEWS_GPR |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in res["events"]:
        f = e.get("features") or {}
        L.append(f"| {e['label']} | {e['pos_date'] or e['date']} | {mapname[e['mapping']]} | {e['episode_t0'] or '—'} | {e.get('peak_date') or '—'} | "
                 f"{_pct(e.get('dd0'))} | " + " | ".join(_num(f.get(k), 3) for k in FEATURES + ("NEWS_EPU", "NEWS_GPR")) + " |")
    L += ["", "### 발생일 읽기 (그 시점 학습 사건만 사용)", "",
          "| 사건 | 기준일 | 대응 | 발생일 | 모델 1 BASE 최종 깊이 10/50/90% | 모델 1 특징별 50% (SPEED/RUNUP/FINREL/RATECHG) | "
          "모델 2 BASE 회복 1/2/3/5년 | 모델 2 특징별 2년 | 모델 3 메뉴(과거 평균 D / G) |", "|---|---|---|---|---|---|---|---|---|"]
    for e in res["events"]:
        tr = e.get("trigger_reading") or {}
        m1, m2, m3 = tr.get("m1") or {}, tr.get("m2") or {}, tr.get("m3_menu") or {}
        c1 = "/".join(_pct(m1["BASE"][k], 0) for k in ("0.1", "0.5", "0.9")) if "BASE" in m1 else (m1.get("reason") or "—")
        c2 = "/".join(_pct(m1["median"][f], 0) for f in FEATURES) if "median" in m1 else "—"
        c3 = "/".join(_pct(m2["BASE"][str(h)], 0, False) for h in HZ) if "BASE" in m2 else (m2.get("reason") or "—")
        c4 = "/".join(_pct(m2["F504"][f], 0, False) for f in FEATURES) if "F504" in m2 else "—"
        c5 = (" · ".join(f"{s} {_pct(m3[s]['D_mean'])}/{_pp(m3[s]['G_mean'])}" for s in MENU) + f" (n={m3['n']})") if m3 else "—"
        L.append(f"| {e['label']} | {e['pos_date'] or e['date']} | {mapname[e['mapping']]} | {e['episode_t0'] or '—'} | {c1} | {c2} | {c3} | {c4} | {c5} |")
    L += ["", "### 실제 (사후)", "", "| 사건 | 발생일 | 최종 깊이 | 바닥일 | 회복일 | 회복 기간 | 실제 D (DCA6/DCA12/HALF6) | 실제 G (DCA6/DCA12/HALF6) |",
          "|---|---|---|---|---|---|---|---|"]
    for e in res["events"]:
        r = e.get("realized") or {}
        m3 = r.get("m3")
        L.append(f"| {e['label']} | {e['episode_t0'] or '—'} | {_pct(r.get('FD'))} | {r.get('trough_date') or '—'} | "
                 f"{r.get('rec_date') or ('미회복' if r else '—')} | {_num(r.get('R_years'), 1) + '년' if _fin(r.get('R_years')) is not None else '—'} | "
                 f"{'/'.join(_pct(m3[s]['D756']) for s in MENU) if m3 else '—'} | {'/'.join(_pp(m3[s]['G']) for s in MENU) if m3 else '—'} |")
    L.append("")
    for e in res["events"]:
        L.append(f"- **{e['label']}** ({e['date']}): {e['note']}")
    L.append("")
    for e in res["events"]:
        if e.get("snapshot"):
            L += [f"#### {e['label']} — 기준일 스냅숏 ({e['snapshot']['as_of']}, 그날까지의 정보만)", ""]
            L += _reading_lines(e["snapshot"], None, heading="#####")
    # 5. 모델 1
    m1b = res["model1"]["by_era"]
    L += ["## 모델 1 — 하락 깊이", "", "판정: " + " · ".join(f"{f} **{V['M1_' + f]}**" for f in FEATURES), "",
          "### 시대별 평균 핀볼 손실 (전고점 대비 %p, 낮을수록 잘 맞힘)", "",
          "| 시대 | 평가 사건 | BASE | " + " | ".join(FEATURES) + " |", "|---|---|---|" + "---|" * len(FEATURES)]
    for era in ("A", "B", "C", "all"):
        x = m1b[era]
        L.append(f"| {ERA_NAMES[era]} | {x['n_eval']} | " + " | ".join(_num(None if x['score_mean'][m] is None else x['score_mean'][m] * 100, 2)
                                                                       for m in ("BASE",) + FEATURES) + " |")
    L += ["", "### 보정: 실제 최종 깊이가 예측 10~90% 구간 안에 든 비율 (목표 80%)", "",
          "| 시대 | BASE | " + " | ".join(FEATURES) + " |", "|---|---|" + "---|" * len(FEATURES)]
    for era in ("A", "B", "C", "all"):
        x = m1b[era]
        L.append(f"| {ERA_NAMES[era]} | " + " | ".join(_pct(x['coverage80'][m], 0, False) for m in ("BASE",) + FEATURES) + " |")
    L += ["", "### 평균 하락률 (확정 사건, 전고점 대비)", "",
          "| 시대 | 확정 사건 | 최종 깊이 평균 | 중앙 | 최소 | 발생일 뒤 추가 하락 평균(로그) | 중앙 | 바닥까지 거래일 중앙(사후) |", "|---|---|---|---|---|---|---|---|"]
    for era in ("A", "B", "C", "all"):
        x = m1b[era]
        L.append(f"| {ERA_NAMES[era]} | {x['n_settled']} | {_pct(x['FD_mean'])} | {_pct(x['FD_median'])} | {_pct(x['FD_min'])} | "
                 f"{_pct(x['y_mean'])} | {_pct(x['y_median'])} | {_num(x['days_to_trough_median'], 0)} |")
    L += ["", "읽는 법: 핀볼 손실은 분위수 예측 다섯 개가 실제 최종 깊이에서 얼마나 빗나갔는지의 평균이다. "
          "특징 모델이 기준선보다 작으면 그 시대에서는 더 잘 맞혔다는 뜻이지만, 판정은 위 '한눈에'의 검정으로만 한다.", ""]
    # 6. 모델 2
    m2 = res["model2"]
    L += ["## 모델 2 — 전고점 회복 기간", "", "판정: " + " · ".join(f"{f} **{V['M2_' + f]}**" for f in FEATURES), "",
          "### 시대별 평균 브라이어 점수 (0~1, 낮을수록 잘 맞힘)", "",
          "| 시대 | 평가 사건 | 미회복 제외 | BASE | " + " | ".join(FEATURES) + " |", "|---|---|---|---|" + "---|" * len(FEATURES)]
    for era in ("A", "B", "C", "all"):
        x = m2["by_era"][era]
        L.append(f"| {ERA_NAMES[era]} | {x['n_eval']} | {x['n_censored_excluded']} | " + " | ".join(_num(x['score_mean'][m], 4) for m in ("BASE",) + FEATURES) + " |")
    ka = m2["km_all"]
    L += ["", f"### 전체 사건 KM (A+B+C, 사건 {ka['n']}개 · 회복 {ka['n_events']}개, 미회복은 마지막 날 기준 중도절단)", "",
          "| 1년 안 | 2년 안 | 3년 안 | 5년 안 | 중앙 회복 기간 |", "|---|---|---|---|---|",
          "| " + " | ".join(_pct(ka["F_at"][str(h)], 0, False) for h in HZ) + f" | {_yrs(ka['median_days'])} |", "",
          "### 사후 최종 깊이로 나눈 설명용 KM (예측 모델 아님 — 깊이는 사후에만 안다)", "",
          "| 최종 깊이 구간 | 사건 | 1년 안 | 2년 안 | 3년 안 | 5년 안 | 중앙 회복 기간 |", "|---|---|---|---|---|---|---|"]
    for name, x in m2["km_by_depth"].items():
        L.append(f"| {name} | {x['n']} | " + " | ".join(_pct(x["F_at"][str(h)], 0, False) for h in HZ) + f" | {_yrs(x['median_days'])} |")
    L += ["", "### 보정: 기준선 평균 예측 회복 확률 vs 실제 회복 비율 (평가 사건, 전체)", "", "| 시점 | 예측 평균 | 실제 |", "|---|---|---|"]
    for h in HZ:
        c = m2["by_era"]["all"]["calib"][str(h)]
        L.append(f"| {h // 252}년 | {_pct(c['pred_mean'], 0, False)} | {_pct(c['obs_rate'], 0, False)} |")
    L.append("")
    # 7. 모델 3
    m3 = res["model3"]["by_era"]
    L += ["## 모델 3 — 투입 일정", "",
          "- 발생일 이후 어떤 시장 정보도 보지 않는다 — 투입 날짜와 금액은 발생일에 달력으로 고정된다(신호 기다리기가 아님).",
          "- 바닥을 맞히려 하지 않는다 — 사후 최적(ORACLE)은 도달 불가능한 상한으로만 보고한다.",
          "- 메뉴는 결과 전에 3개로 고정했고, '수익이 더 높은가'와 '최악의 순간을 얼마나 덜 아프게 하는가(그 대가)'를 따로 판정한다.", "",
          "판정: " + " · ".join(f"{s} 수익 **{V[f'M3_{s}_RETURN']}** · 보험 **{V[f'M3_{s}_INSURANCE']}**" for s in MENU), "",
          "진단(판정 아님): " + " · ".join(f"{s} {res['diagnostics'][s]}" for s in MENU), ""]
    for era in ("A", "B", "C", "all"):
        x = m3[era]
        L += [f"### {ERA_NAMES[era]} — 끝난 사건 {x[MENU[0]]['n']}개", "",
              "| 일정 | 평균 D | 중앙 D | 후회 비율 | 평균 G | 최악 10% D | 세후 D | 252일 D | 평균 최악 순간(일정 / 한 번에) |", "|---|---|---|---|---|---|---|---|---|"]
        for s in MENU:
            y = x[s]
            L.append(f"| {s} | {_pct(y['D_mean'])} | {_pct(y['D_median'])} | {_pct(y['regret_share'], 0, False)} | {_pp(y['G_mean'])} | "
                     f"{_pct(y['D_p10'])} | {_pct(y['D_tax_mean'])} | {_pct(y['D252_mean'])} | {_pct(y['minw_mean'])} / {_pct(y['lump_minw_mean'])} |")
        L += [f"| ORACLE (사후에만 알 수 있는 상한 — 따라 할 수 없음) | {_pct(x['oracle_D_mean'])} | | | | | | | |", ""]
    # 8. 사건 목록
    L += ["## 사건 목록", "", "| 발생일 | 시대 | 전고점일 | 발생일 깊이 | 최종 깊이 | 바닥일 | 회복일 | 회복 기간 | 병합된 재발생일 |", "|---|---|---|---|---|---|---|---|---|"]
    for e in res["episodes"]:
        L.append(f"| {e['t0']} | {e['era'] if e['era'] != 'pre' else '시대 전'} | {e['peak_date']} | {_pct(e['dd0'])} | {_pct(e['FD'])} | "
                 f"{e['trough_date'] or '—'} | {e['rec_date'] or '미회복'} | {_yrs(e['R_days'])} | {', '.join(r['date'] for r in e['retriggers']) or '—'} |")
    L.append("")
    # 9. 견고성
    rb = res["robustness"]
    L += ["## 견고성 (보고만)", "", "라벨을 붙이지 않는다. 값은 평균(A / B / C)과 합친 A+B 부호 뒤집기 p.", ""]
    for th in ROBUST_TH:
        t = rb[f"th_{th:.2f}"]
        L += [f"### 문턱 {th * 100:.0f}% (부모 사건 {t['n_episodes']}개)", "", "| 항목 | n (A/B/C) | 평균 (A / B / C) | 합친 p |", "|---|---|---|---|"]
        for key, x in t["table"].items():
            fmt = (lambda v: _pp(v, 2)) if key.startswith("M1") else ((lambda v: _num(v, 4)) if key.startswith("M2") else (lambda v: _pct(v)))
            if key.endswith("_G"):
                fmt = lambda v: _pp(v)  # noqa: E731
            L.append(f"| {key} | {x['n']['A']}/{x['n']['B']}/{x['n']['C']} | {fmt(x['mean']['A'])} / {fmt(x['mean']['B'])} / {fmt(x['mean']['C'])} | {_p(x['p_pooled'])} |")
        L.append("")
    for name, title in (("finrel49", "49 산업 금융(FINREL49)"), ("news", "뉴스 특징(NEWS_EPU·NEWS_GPR)")):
        x = rb[name]
        L += [f"### {title}", ""]
        if not x.get("available"):
            L += [f"자료 없음({x.get('reason')}).", ""]
            continue
        L += ["| 항목 | n (A/B/C) | 평균 (A / B / C) | 합친 p |", "|---|---|---|---|"]
        for key, y in x["table"].items():
            fmt = (lambda v: _pp(v, 2)) if key.startswith("M1") else (lambda v: _num(v, 4))
            L.append(f"| {key} | {y['n']['A']}/{y['n']['B']}/{y['n']['C']} | {fmt(y['mean']['A'])} / {fmt(y['mean']['B'])} / {fmt(y['mean']['C'])} | {_p(y['p_pooled'])} |")
        L.append("")
    L += ["### 7개 사건의 뉴스 특징 값 (발생일 기준)", "", "| 사건 | NEWS_EPU | NEWS_GPR |", "|---|---|---|"]
    epmap = {e["t0"]: e for e in res["episodes"]}
    for e in res["events"]:
        f = (epmap.get(e["episode_t0"]) or {}).get("features") or {}
        L.append(f"| {e['label']} | {_num(f.get('NEWS_EPU'), 3)} | {_num(f.get('NEWS_GPR'), 3)} |")
    L += ["", "### 겹침 군집 (결과 구간이 겹치는 사건을 하나로 묶은 합친 A+B p)", "", "| 판정 키 | 사건 단위 p | 군집 단위 p |", "|---|---|---|"]
    for key in VERDICT_KEYS:
        L.append(f"| {key} | {_p(Dt[key]['p_signflip'])} | {_p(rb['cluster'][key])} |")
    L += ["", "### 세후(이자소득세 15.4%) 평균 D", "", "| 일정 | A | B | C |", "|---|---|---|---|"]
    for s in MENU:
        L.append(f"| {s} | " + " | ".join(_pct(rb["tax"][s][e]) for e in ("A", "B", "C")) + " |")
    L += ["", "### 가격 지수(^GSPC) 기준 회복", ""]
    pi = rb["price_index"]
    if pi.get("available"):
        L += ["뉴스에서 말하는 '전고점 회복'은 보통 가격 지수 기준이라 이 표의 숫자가 더 길다.", "",
              "| 사건 | 대응 | 가격 기준 발생일 | 전고점일 | 회복일 | 회복 기간(가격) | 회복 기간(총수익) |", "|---|---|---|---|---|---|---|"]
        for r in pi["events"]:
            L.append(f"| {r['label']} | {mapname.get(r['mapping'], r['mapping'])} | {r.get('t0', '—')} | {r.get('peak_date', '—')} | "
                     f"{r.get('rec_date') or ('미회복' if r.get('t0') else '—')} | {_num(r.get('R_years'), 1)}년 | {_num(r.get('tr_R_years'), 1)}년 |")
    else:
        L.append(f"자료 없음({pi.get('reason')}).")
    L += ["", "### 실질(CPI) 기준 회복 (전고점이 1947-01 이후인 사건)", ""]
    rc = rb["real_cpi"]
    if rc.get("available"):
        L += ["| 발생일 | 시대 | 명목 회복일 | 명목 회복 기간 | 실질 회복일 | 실질 회복 기간 |", "|---|---|---|---|---|---|"]
        for r in rc["episodes"]:
            L.append(f"| {r['t0']} | {r['era']} | {r['nominal_rec'] or '미회복'} | {_num(r['nominal_R_years'], 1)}년 | {r['real_rec'] or '미회복'} | {_num(r['real_R_years'], 1)}년 |")
    else:
        L.append(f"자료 없음({rc.get('reason')}).")
    L.append("")
    # 10. 검정력과 한계
    L += ["## 검정력과 한계", "", "- **FAIL 은 효과 없음의 증명이 아니다.** 사건 수가 적어 중간 크기 이하의 효과는 원리적으로 못 잡는다."]
    L += [f"- {n}" for n in res["notes"]]
    L += ["", "사전 기대(결과 전에 적어 둠)와 실제:", ""]
    actual = {"M1": res["summary"]["모델1 하락 깊이"], "M2": res["summary"]["모델2 회복 기간"],
              "M3_return": res["summary"]["모델3 수익(대 한 번에)"], "M3_insurance": res["summary"]["모델3 보험"]}
    for k, v in res["expected"].items():
        L.append(f"- {k}: 기대 — {v} / 실제 — {actual[k]}")
    # 11. 읽는 법
    L += ["", "## 읽는 법", "",
          "- 모델 1·2 의 d = 기준선 점수 − 특징 모델 점수. 양수면 특징 모델이 더 잘 맞혔다.",
          "- 모델 3 의 D = ln(일정 계좌 3년 뒤) − ln(한 번에 넣은 계좌 3년 뒤). 양수면 일정이 더 많이 남겼다. "
          "G = 일정의 최악 순간(원금 대비) − 한 번에의 최악 순간. 양수면 일정의 최악 순간이 덜 나빴다.",
          "- 모든 일정이 252거래일 안에 투입을 끝내므로 그 뒤로는 두 계좌가 같은 지수만 들고 같은 비율로 움직인다. 그래서 252일 D 와 3년 D 가 같게 나온다"
          "(3년 시계는 최악 순간 G 를 재는 데 쓰인다).",
          "- 거래일 ↔ 년: 252거래일 = 1년.",
          "- 숫자는 과거 미국 시장 31개 남짓 사건의 분포다. 성과를 약속하지 않는다."]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 실행
def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        v = float(o)
        return round(v, 6) if math.isfinite(v) else None
    return o


def run(smoke: bool) -> dict:
    data = load(smoke)
    return _clean(evaluate(data, smoke, load_news()))


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    Path(a.checkpoint).mkdir(parents=True, exist_ok=True)
    res = run(a.smoke)
    tmp = out / "results.json.tmp"
    tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(out / "results.json")
    (out / "REPORT.md").write_text(report(res, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
