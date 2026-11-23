"""crash-fusion-v1 — 급락 예측 융합: 랜드마크 ⊕ 경로 모의(SIMMIX), 깊이 → 회복 두 단계(TWOPH).

python research/jobs/crash-fusion-v1/run.py --out OUT --checkpoint CK [--smoke]

규칙·판정은 SPEC.md(결과 보기 전 고정, 사전 등록 2026-11-23). 장부 H-029, parent crash-landmark-v1.

- 랜드마크 e ∈ (21, 63, 126) 마다 LM(LM_ANCHOR·LM_SCALED, crash-landmark-v1)과 같은 시점 상태에서 출발한 GARCH 경로 모의(SIM, crash-simpath-v1)를
  반반 섞은 SIMMIX, LM_ANCHOR 의 '남은 추가 하락'을 회복에 넣은 두 단계 회복 TWOPH 를 만든다.
- 판정 4개(SIMMIX 깊이·회복 = 해외 군집, TWOPH 회복 = 미국 사건·해외 군집), 새 족, 홈(Holm) 족 오류율 0.05. 비교 대상 = LM 단독(같은 쌍에서 다시 계산).
- 공용 lab(research/jobs/crash-cycle-lab/lab.py)과 기존 작업 파일은 고치지 않고 import 해서 쓴다. 계산은 수 분 이내라 체크포인트를 쓰지 않는다
  (--checkpoint 폴더만 만든다).
"""

from __future__ import annotations

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

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
STUDY = "crash-fusion-v1"
RULES_VERSION = "crash-fusion/v1"
JUDGE_VERSION = "crash-fusion-judge/v1"
KEYS = ("SIMMIX_M1_INTL", "SIMMIX_M2_INTL", "TWOPH_M2_US", "TWOPH_M2_INTL")   # 순서 고정(같은 p 의 순위 결정에도 씀)
K = 4
FAMILY_ALPHA = 0.05
PASS_LABEL = "BEATS_LANDMARK"
LABELS = ("BEATS_LANDMARK", "FAIL", "NOT_EVALUABLE")
VERDICT_SPEC = {"SIMMIX_M1_INTL": ("SIMMIX_M1", "INTL"), "SIMMIX_M2_INTL": ("SIMMIX_M2", "INTL"),
                "TWOPH_M2_US": ("TWOPH_M2", "US"), "TWOPH_M2_INTL": ("TWOPH_M2", "INTL")}
DESCRIPTIVE_US = ("SIMMIX_M1", "SIMMIX_M2")       # 미국 SIMMIX — 판정 아님(3.6 절)
W_MIX = 0.5
GRID_E = (21, 63, 126)                             # = lab.LANDMARKS (조견표)
GRID_D = (-0.05, -0.10, -0.15, -0.20, -0.25, -0.30, -0.40)
GRID_DD0 = -0.15
ROBUST_LANDMARKS = (63, 126)                       # 견고성(보고만)
JSON_MAX_BYTES = 230_000                           # results.json 크기 대비책 문턱(4.1)
MODEL_NAMES = {"SIMMIX_M1_INTL": "SIMMIX vs LM_ANCHOR (깊이, 해외 군집)",
               "SIMMIX_M2_INTL": "SIMMIX vs LM_SCALED (회복, 해외 군집)",
               "TWOPH_M2_US": "TWOPH vs LM_SCALED (회복, 미국 사건)",
               "TWOPH_M2_INTL": "TWOPH vs LM_SCALED (회복, 해외 군집)"}
QK = ("0.1", "0.25", "0.5", "0.75", "0.9")
EXPECTED = {
    "SIMMIX_M1_INTL": "FAIL 가능성이 높다(통과 약 12%). 두 깊이 예측이 같은 상태(지금 수준·지금까지 최저)에서 출발하고, 분위수 평균은 핀볼 손실을 크게 줄이지 않는다. 해외 지역 일별 이력이 짧아(1990~) 모의의 표류·변동성 추정이 거칠다.",
    "SIMMIX_M2_INTL": "FAIL 가능성이 높다(통과 약 15%). 모의 회복 확률은 지역 자기 표류에서 나와 사건 유사 표본(LM)과 오차가 덜 겹치면 섞기가 도울 수 있다. 그러나 발생일 모의의 해외 성적은 I1 양수·I2 음수로 엇갈렸다.",
    "TWOPH_M2_US": "FAIL 가능성이 높다(통과 약 8%). 같은 유사 사건의 정보를 다르게 나눌 뿐이고, 깊이가 확정된 사건만 쓰므로 LM_SCALED 보다 유사 사건이 조금 적다. 63·126 에서는 대부분의 유사 사건이 이미 바닥을 지나 LM_SCALED 와 거의 같아진다.",
    "TWOPH_M2_INTL": "FAIL 가능성이 높다(통과 약 7%). 미국 유사 사건의 '바닥까지 시간'과 '오르는 속도'를 USD 기준 해외 사건에 옮긴다. 해외 회복 속도가 미국과 다르면 두 단계 분해의 이득이 묻힌다.",
}
LIMITS = [
    "판정 사건의 결과는 모두 이미 알려져 있고 LM·SIM 의 미국 성적도 보았다. 진짜로 손대지 않은 자료는 앞으로 생길 급락뿐이다.",
    "해외 판정은 USD 기준 선진국 3지역(1991~)이고, 지역 일별 이력이 짧아 모의의 표류·변동성 추정이 거칠다(asof 1993-05 무렵 이전 쌍은 SIM 이 없어 빠짐).",
    "TWOPH 는 깊이가 확정된 유사 사건만 써서 LM_SCALED 보다 유사 사건이 조금 적다. 오르는 시간이 바닥 거리에 비례한다는 것은 근사다.",
    "SIMMIX 비중 0.5 는 고정값이다(최적 비중을 찾지 않았다). 모의는 표류 고정·대칭 GARCH·독립 재표집(crash-simpath-v1 의 한계 그대로).",
    "미국 C 와 해외 I2 는 같은 세계 급락(2008·2020·2022)을 겹쳐 담아 두 집단이 완전히 독립은 아니다. 급락 연구 전체(7연구 15개 + 이 연구 4개)를 묶은 다중 검정 보정은 하지 않았다.",
    "총수익·명목 기준, 최종 깊이는 3년에서 자른다(v1 과 같음).",
]
NOTES = [
    "비교 대상은 v1 기준선이 아니라 LM 이다. LM 대 v1 기준선은 다시 판정하지 않는다(설명용 표만).",
    "미국 SIMMIX 는 설명용이다: 공개된 랜드마크별 평균과 점수의 볼록성 때문에 합친 평균의 부호가 계산 전에 정해져 있다.",
    "사건이 독립이 아니다(1930년대·2000년대 겹침, 해외 동시 급락). 판정 단위는 미국 사건(랜드마크 평균)·해외 군집이다.",
]
SEEN = [
    "미국 사건 28개의 실제 결과(최종 깊이·회복)는 v1 부터 모두 보았다.",
    "미국 랜드마크 쌍의 LM 대 BASE: 랜드마크·층별 평균 점수와 보정표(crash-landmark-v1 REPORT), 사건·랜드마크별 점수(results.json episodes[].landmarks), 예측 전부(predictions.csv).",
    "미국 랜드마크 쌍의 SIM(그 시점 상태에서 출발) 대 같은 BASE: 랜드마크별 합친 평균·p(crash-simpath-v1 REPORT 견고성 절), 사건·랜드마크별 d(results.json), 예측 전부(predictions.csv). "
    "→ 두 비교의 BASE 가 같으므로 미국에서는 쌍마다 SIM 대 LM 점수 차를 공개 파일에서 바로 뺄 수 있다. 설계자는 계산하지 않았다. 그러나 설계자가 읽은 REPORT 의 랜드마크별 합친 평균만으로도 "
    "21·63 에서(평가 쌍 21개가 같음) SIM 이 LM 보다 회복은 평균 약 +0.015·+0.006, 깊이는 약 +0.003·+0.0003 잘 맞혔다는 것이 나온다(126 은 평가 쌍이 하나 달라 근사: 회복 약 +0.03, 깊이 약 −0.004). "
    "브라이어 점수와 핀볼 손실은 예측에 대해 볼록하므로 쌍마다 점수(SIMMIX) ≤ ½(점수(LM) + 점수(SIM)), 즉 SIMMIX 의 LM 대비 이득 ≥ ½ × (SIM 의 LM 대비 이득)이다. "
    "따라서 미국에서 SIMMIX 대 LM 의 합친 평균은 계산 전에 사실상 양수로 정해져 있다(회복 하한 약 +0.007, 깊이 하한 약 0). 미국 SIMMIX 를 판정하지 않고 설명용으로 내린 이유다.",
    "해외 군집: LM(미국 학습) 대 BASE 의 반쪽별 평균·p(깊이 I1 +0.0042·I2 +0.0005, p 0.035; 회복 I1 +0.0056·I2 +0.0118, p 0.17), 사건별 값(results.json — 랜드마크별 해외 값은 REPORT 에 없고 설계자는 파일에서 보지 않았다). "
    "해외 SIM 은 발생일에서만 계산되었다(대 BASE: 깊이 I1 +0.0065·I2 −0.0052, 회복 I1 +0.0562·I2 −0.0189). 해외 랜드마크의 SIM 은 어디서도 계산된 적이 없다 → 해외 SIMMIX 대 LM 은 공개 정보로 정해지지 않는다.",
    "TWOPH 는 어디서도 계산된 적이 없다. 그러나 그 재료(LM_ANCHOR 의 유사 사건·남은 추가 하락)와 비교 대상(LM_SCALED)의 성적은 보았다: LM_SCALED 는 21 에서 1년 회복을 덜 예측했고(47% vs 실제 67%) "
    "63 에서는 맞았다(66% vs 67%), 63 의 3년은 더 예측했다(88% vs 81%). 이 보정 양상을 아는 것이 '두 단계' 구조를 고르는 데 영향을 줄 수 있었다. 설계자는 TWOPH 가 이 양상을 어느 쪽으로 바꿀지 "
    "계산하지 않았고 알지 못한다. 두 단계 구조는 첫 도달 시간 논리에서 나왔고 자유 모수가 없다(X_FLOOR 는 v1 의 −5% 종료 문턱 그대로).",
    "변형 선택 자체가 결과를 보고 한 것이다(융합 연구의 본성): 일곱 중 성적이 가장 좋았던 둘(LM·SIM)을 골랐다. 공개 성적의 일부는 우연(승자의 저주)이라 기대보다 약하게 나올 수 있다. "
    "비교 대상이 LM 이므로 LM 선택의 영향은 양쪽에서 상쇄되지만, SIM 은 미국 랜드마크 성적을 보고 골랐다 → SIMMIX 를 해외에서만 판정한다.",
    "2024-10 이후 사건(미국 2025-04, 해외 2개)은 여러 연구가 이미 봤다 → 보고만.",
]
CAN_SAY = [
    "통과가 뜻하는 것: \"1991~2024-09 해외 3지역 군집(USD) / 1946~2024-09 미국 사건에서, 그 변형이 LM 단독보다 표본 밖 점수가 우연 이상으로, 두 반쪽(세 시대) 모두에서 같은 방향으로 나았다.\" "
    "설명 도구 후보·앞으로 생길 급락에서 기록해 볼 후보까지.",
    "말할 수 없는 것: LM(또는 융합)이 v1 기준선보다 낫다는 확인(본 자료 — 설명용 값만), 미국에서의 SIMMIX 이득(부호가 미리 정해짐), 수익·투입 시점, 앞으로의 급락에서의 성능, 엔진·주문 변경.",
    "FAIL: 효과 없음의 증명이 아니다(필요 효과 0.46~0.53 sd).",
    "진짜로 손대지 않은 자료는 앞으로 생길 급락뿐이다(판정 설계 규칙 3 의 '전진 원장' 정신). 이 연구는 그 자리를 대신하지 못한다.",
]
WHY_21 = [
    "LANDMARKS = (21, 63, 126) 는 공용 상수이고, '같은 (사건, 랜드마크) 쌍에서 LM 단독 대비'라는 질문은 crash-landmark-v1 의 사건 값(랜드마크 평균) 정의를 그대로 써야 성립한다.",
    "융합의 목적은 LM 이 쓰이는 모든 시점에서 예측을 낫게 하는 것이다. 발생 뒤 1개월도 사용자가 읽는 시점이다.",
    "21 에서 LM 의 이득이 없었다는 것(본 결과)을 이유로 빼면 결과를 보고 고르는 것이 된다.",
    "공개(선언된 한계): 미국에서는 21 에서 SIM 이 LM 보다 회복을 가장 크게 앞섰다(약 +0.015) — 21 을 남기는 것은 미국 SIMMIX 값에 유리하다. 이것도 미국 SIMMIX 를 판정하지 않는 이유 중 하나다. "
    "해외 판정과 TWOPH 에는 21 의 방향을 알려 주는 공개 정보가 없다.",
    "63·126 만으로 다시 계산한 값을 견고성 절에 보고한다(라벨 없음).",
]
# ------------------------------------------------------------------------------------------------------

SHORT = {"SIMMIX_M1_INTL": "SIMMIX 깊이(해외)", "SIMMIX_M2_INTL": "SIMMIX 회복(해외)",
         "TWOPH_M2_US": "TWOPH 회복(미국)", "TWOPH_M2_INTL": "TWOPH 회복(해외)"}
MODELS_ROW = ("BASE", "LM", "SIM", "SIMMIX", "TWOPH")
DESC_M1 = ("LM", "SIM", "SIMMIX", "LMB", "LM_POOL")
DESC_M2 = ("LM", "SIM", "SIMMIX", "TWOPH", "LMB", "LM_POOL")
QNAMES = (("SIMMIX_M1", "SIMMIX_M2", "TWOPH_M2", "SIM_M1", "SIM_M2", "LMB_M1", "LMB_M2", "LMPOOL_M1", "LMPOOL_M2")
          + tuple(f"B_{m}_M1" for m in DESC_M1) + tuple(f"B_{m}_M2" for m in DESC_M2))
EPISODE_FIELDS = ["d", "m", "s1_BASE", "s1_LM", "s1_SIM", "s1_SIMMIX", "s2_BASE", "s2_LM", "s2_SIM", "s2_SIMMIX", "s2_TWOPH"]
E_NAMES = {21: "약 1개월(21거래일)", 63: "약 3개월(63거래일)", 126: "약 6개월(126거래일)"}
_N = NormalDist()


def _load(name: str, rel: str):
    if name in sys.modules and getattr(sys.modules[name], "__file__", None):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def L():
    return _load("crash_cycle_lab", "research/jobs/crash-cycle-lab/lab.py")


def _fget(F: dict, h):
    """회복 확률 사전에서 h 를 int·str 키 모두로 읽는다."""
    h = int(h)
    return F[h] if h in F else F[str(h)]


# ================================================================ 섞기
def mix_q(qa, qb, w: float = W_MIX) -> Optional[dict]:
    """분위수 평균(Vincentization). 둘 중 하나라도 None 이면 None."""
    if qa is None or qb is None:
        return None
    return {k: float(w * float(qa[k]) + (1 - w) * float(qb[k])) for k in QK}


def mix_F(Fa, Fb, w: float = W_MIX) -> Optional[dict]:
    """확률 평균(선형 의견 풀). 하나라도 None 이면 None. 키 int(입력이 str 키여도 int h 로 읽는다)."""
    if Fa is None or Fb is None:
        return None
    return {int(h): float(w * _fget(Fa, h) + (1 - w) * _fget(Fb, h)) for h in L().HZ}


# ================================================================ TWOPH
def x_raw_of(st: dict) -> float:
    """st["x_raw"] 가 있으면 그것, 없으면 -log(1 + d) (조견표의 가상 상태)."""
    v = st.get("x_raw")
    return float(v) if v is not None else -math.log(1 + st["d"])


def twoph_analog(j: dict, e: int, D) -> Optional[tuple]:
    """유사 사건 j 하나의 (delta, y, x_tr, U, ev). alive_at(j, e) 가 아니거나 s > end1 이면 None."""
    lab = L()
    if not lab.alive_at(j, e):
        return None
    s = j["t0"] + e
    if s > j["end1"]:
        return None
    Lv = j["_Lv"]
    seg = Lv[s:j["end1"] + 1]
    k = int(np.argmin(seg))                      # 같은 값이면 첫 위치
    tau = s + k
    delta = k
    y = float(math.log(seg[k] / Lv[s]))
    x_tr = max(math.log(j["P"] / seg[k]), lab.X_FLOOR)
    D = pd.Timestamp(D)
    if j["rec_date"] is not None and j["rec_date"] <= D:
        U, ev = int(j["rec"] - tau), 1
    else:
        U, ev = int(lab.pos_le(j["_idx"], D) - tau), 0
    return (int(delta), y, float(x_tr), U, ev)


def twoph_from_arrays(delta, y, U, ev, x_tr, x_raw, hs=None) -> dict:
    """W = U/x_tr 의 KM 으로, 남은 회복 = 바닥까지 delta + 오르는 시간(바닥 거리 x_raw − y 에 비례)의 회복 확률."""
    lab = L()
    v1 = lab.v1()
    hs = lab.HZ if hs is None else hs
    delta = np.asarray(delta, dtype=float)
    y = np.asarray(y, dtype=float)
    W = np.asarray(U, dtype=float) / np.asarray(x_tr, dtype=float)
    tauW, SW = v1.wkm(W, np.asarray(ev, dtype=int))
    den = np.maximum(float(x_raw) - y, lab.X_FLOOR)
    out = {}
    for h in hs:
        g = []
        for k in range(len(delta)):
            u = h - delta[k]
            g.append(0.0 if u <= 0 else 1.0 - v1.surv_at(tauW, SW, u / den[k]))
        out[int(h)] = float(np.mean(g)) if g else float("nan")
    return out


def twoph_from_state(train_recs: list, st: dict, e: int) -> Optional[dict]:
    lab = L()
    D = st["asof"]
    A = [j for j in lab.m1_pool(train_recs, D) if lab.alive_at(j, e)]   # LM_ANCHOR 의 T1L 과 같은 유사 사건
    rows = [a for a in (twoph_analog(j, e, D) for j in A) if a is not None]
    n = len(rows)
    nev = int(sum(a[4] for a in rows))
    if n < lab.MIN_TRAIN or nev < lab.MIN_EVENTS_M2:
        return None
    m2 = twoph_from_arrays([a[0] for a in rows], [a[1] for a in rows], [a[3] for a in rows], [a[4] for a in rows],
                           [a[2] for a in rows], x_raw_of(st))
    return {"m2": m2, "n": n, "n_events": nev}


def twoph(train_recs: list, r: dict, e: int) -> Optional[dict]:
    lab = L()
    st = lab.landmark_state(r, e)
    if st is None:
        return None
    st["x_raw"] = math.log(r["P"] / r["_Lv"][st["tau"]])
    return twoph_from_state(train_recs, st, e)


# ================================================================ 쌍·사건
def pair_calc(us: list, all_recs: list, r: dict, e: int, n_paths: int) -> Optional[dict]:
    lab = L()
    st = lab.landmark_state(r, e)
    if st is None:
        return None
    st["x_raw"] = math.log(r["P"] / r["_Lv"][st["tau"]])
    B = lab.landmark_base(us, r, e)
    M = lab.landmark_lm(us, r, e)
    S = lab.simulate(r["_Lv"], r["market"], r["P"], st["tau"], st["m"], e, n_paths)
    smx = (mix_q(M["m1"], S["q"] if S else None), mix_F(M["m2"], S["F"] if S else None))
    T = twoph_from_state(us, st, e)
    lmb = (mix_q(M["m1"], B["m1_trunc"]), mix_F(M["m2"], B["m2"]))
    P = lab.landmark_lm(all_recs, r, e)
    pred = {"BASE": (B["m1_trunc"], B["m2"]), "LM": (M["m1"], M["m2"]),
            "SIM": (S["q"], S["F"]) if S else (None, None), "SIMMIX": smx,
            "TWOPH": (None, T["m2"] if T else None), "LMB": lmb, "LM_POOL": (P["m1"], P["m2"])}
    s1, s2 = {}, {}
    for name, (q, F) in pred.items():
        if r["depth_settled"] and q is not None:
            s1[name] = lab.score_m1(r["FD"], q)
        if r["R"] is not None and F is not None:
            s2[name] = lab.score_m2(r["R"] - e, F)

    def dif(sc, a, b):
        return float(sc[a] - sc[b]) if (a in sc and b in sc) else None

    q = {"SIMMIX_M1": dif(s1, "LM", "SIMMIX"), "SIMMIX_M2": dif(s2, "LM", "SIMMIX"), "TWOPH_M2": dif(s2, "LM", "TWOPH"),
         "SIM_M1": dif(s1, "LM", "SIM"), "SIM_M2": dif(s2, "LM", "SIM"), "LMB_M1": dif(s1, "LM", "LMB"), "LMB_M2": dif(s2, "LM", "LMB"),
         "LMPOOL_M1": dif(s1, "LM", "LM_POOL"), "LMPOOL_M2": dif(s2, "LM", "LM_POOL")}
    for m in DESC_M1:
        q[f"B_{m}_M1"] = dif(s1, "BASE", m)
    for m in DESC_M2:
        q[f"B_{m}_M2"] = dif(s2, "BASE", m)
    return {"e": int(e), "st": st, "B": B, "M": M, "S": S, "T": T, "pred": pred, "s1": s1, "s2": s2, "q": q}


def _val(pairs: dict, Q: str, landmarks=None) -> Optional[float]:
    vs = [p["q"][Q] for e, p in pairs.items() if (landmarks is None or e in landmarks) and p["q"][Q] is not None]
    return float(np.mean(vs)) if vs else None


def episode_calc(us: list, all_recs: list, r: dict, n_paths: int) -> dict:
    """사건 값 = 있는 랜드마크의 단순 평균(같은 사건의 랜드마크끼리는 독립이 아니다)."""
    lab = L()
    pairs = {}
    for e in lab.LANDMARKS:
        p = pair_calc(us, all_recs, r, e, n_paths)
        if p is not None:
            pairs[int(e)] = p
    return {"r": r, "pairs": pairs, "val": {Q: _val(pairs, Q) for Q in QNAMES}}


# ================================================================ 요약·판정
def summ(items: list, pop: str) -> dict:
    """items = [(사건, 값)]. 미국 = 층 A·B·C 사건 단위, 해외 = 층 I1·I2 군집 단위(라벨 없음)."""
    lab = L()
    if pop == "US":
        vals = {s: [float(v) for r, v in items if r["stratum"] == s and v is not None] for s in lab.US_STRATA}
        pooled = [v for s in lab.US_STRATA for v in vals[s]]
        n = {s: len(vals[s]) for s in lab.US_STRATA}
        n["pooled"] = len(pooled)
        mean = {s: lab.mean_or_none(vals[s]) for s in lab.US_STRATA}
        mean["pooled"] = lab.mean_or_none(pooled)
        return {"n": n, "mean": mean, "p": lab.signflip(pooled)}
    its = [(r["t0_date"], v, r["id"]) for r, v in items if r["stratum"] in lab.INTL_STRATA and v is not None]
    cl = lab.clusters(its)
    mean = {s: lab.mean_or_none([c["value"] for c in cl if c["stratum"] == s]) for s in lab.INTL_STRATA}
    mean["pooled"] = lab.mean_or_none([c["value"] for c in cl])
    return {"n_episodes": len(its), "n_clusters": len(cl), "mean": mean, "p_cluster": lab.signflip([c["value"] for c in cl])}


def st3(vals) -> dict:
    lab = L()
    a = [float(v) for v in vals if v is not None]
    return {"n": len(a), "mean": lab.mean_or_none(a), "p": lab.signflip(a)}


def holm_labels(dets: dict) -> dict:
    """홈 단계 하강(K = 4 고정). dets = {키: {"p", "allpos", "evaluable"[, "reason"]}}.
    평가 가능한 키를 (p, KEYS 순서)로 정렬, 순위 i 의 문턱 FAMILY_ALPHA/(K − i + 1), 처음 넘지 못한 순위에서 멈춤.
    방향 조건(allpos)은 기각 순서에 영향을 주지 않는다."""
    out = {}
    order = [k for k in KEYS if k in dets]
    ev = sorted([k for k in order if dets[k].get("evaluable") and dets[k].get("p") is not None],
                key=lambda k: (float(dets[k]["p"]), KEYS.index(k)))
    stopped = False
    for i, k in enumerate(ev, start=1):
        thr = FAMILY_ALPHA / (K - i + 1)
        rej = (not stopped) and float(dets[k]["p"]) < thr
        if not rej:
            stopped = True
        out[k] = {"holm_rank": i, "holm_threshold": thr, "holm_reject": bool(rej)}
    for k in order:
        d = dets[k]
        if k not in out:
            out[k] = {"holm_rank": None, "holm_threshold": None, "holm_reject": False,
                      "verdict": "NOT_EVALUABLE", "fail_kind": None, "reason": d.get("reason") or "평가 불가"}
            continue
        o = out[k]
        if o["holm_reject"] and d.get("allpos"):
            o.update(verdict=PASS_LABEL, fail_kind=None, reason="")
        elif d.get("allpos"):
            o.update(verdict="FAIL", fail_kind="FAIL_UNDERPOWERED", reason="홈 문턱 미달")
        else:
            o.update(verdict="FAIL", fail_kind="FAIL", reason="층 방향 불일치(평균 음수 층 있음)")
    return out


def _pairs_items(calcs: list, Q: str, pop: str, landmarks=None) -> list:
    lab = L()
    strata = lab.US_STRATA if pop == "US" else lab.INTL_STRATA
    out = []
    for c in calcs:
        if c["r"]["stratum"] not in strata:
            continue
        v = c["val"][Q] if landmarks is None else _val(c["pairs"], Q, landmarks)
        if v is not None:
            out.append((c["r"], v))
    return out


def per_landmark(calcs: list, Q: str, pop: str) -> dict:
    lab = L()
    strata = lab.US_STRATA if pop == "US" else lab.INTL_STRATA
    out = {}
    for e in lab.LANDMARKS:
        vals = [c["pairs"][e]["q"][Q] for c in calcs if c["r"]["stratum"] in strata and e in c["pairs"]
                and c["pairs"][e]["q"][Q] is not None]
        out[str(e)] = st3(vals)
    return out


def judge_all(calcs_us: list, calcs_intl: list) -> tuple:
    """4 판정. lab.judge_us / lab.intl_verdict 의 표본 조건·무효 가드·층별 평균·p 만 쓰고 그 verdict(0.05/15)는 버린다."""
    lab = L()
    dets, raws = {}, {}
    for key in KEYS:
        Q, pop = VERDICT_SPEC[key]
        if pop == "US":
            items = _pairs_items(calcs_us, Q, "US")
            dmap = {s: [v for r, v in items if r["stratum"] == s] for s in lab.US_STRATA}
            raw, cl = lab.judge_us(dmap, PASS_LABEL), None
            strata = lab.US_STRATA
        else:
            raw, cl = lab.intl_verdict([(c["r"], c["val"][Q]) for c in calcs_intl if c["val"][Q] is not None], PASS_LABEL)
            strata = lab.INTL_STRATA
        det = {"population": pop, "compare": MODEL_NAMES[key], "n": raw["n"], "mean": raw["mean"], "p": raw["p"],
               "p_method": raw["p_method"], "t": raw["t"], "p_t": raw["p_t"]}
        det["evaluable"] = raw["p"] is not None
        if not det["evaluable"]:
            det["reason"] = raw["reason"]
        det["allpos"] = bool(det["evaluable"] and all(raw["mean"][s] is not None and raw["mean"][s] > 0 for s in strata))
        if pop == "INTL":
            det["n_episodes"] = raw["n_episodes"]
            det["p_episode"] = raw["p_episode"]
            det["clusters"] = [{"first": lab.dstr(c["first"]), "stratum": c["stratum"], "members": list(c["members"]), "value": c["value"]}
                               for c in cl]
        dets[key] = det
        raws[key] = raw
    hl = holm_labels(dets)
    for key in KEYS:
        dets[key].update(hl[key])
        Q, pop = VERDICT_SPEC[key]
        dets[key]["per_landmark"] = per_landmark(calcs_us if pop == "US" else calcs_intl, Q, pop)
    verdicts = {k: dets[k]["verdict"] for k in KEYS}
    return verdicts, dets


def power_holm(n: int) -> dict:
    lab = L()
    if n < 2:
        return {"n": int(n), "needed_effect_sd": {"first": None, "last": None}, "min_p": None,
                "pass_prob_first": {f"{dl}": None for dl in (0.2, 0.3, 0.5, 0.8)}}
    cr = lab.v1()._cr()
    a1 = FAMILY_ALPHA / K
    z = _N.inv_cdf(1 - a1)
    return {"n": int(n),
            "needed_effect_sd": {"first": float(cr.t_crit(a1, n - 1) / math.sqrt(n)), "last": float(cr.t_crit(FAMILY_ALPHA, n - 1) / math.sqrt(n))},
            "min_p": 2.0 ** -n,
            "pass_prob_first": {f"{dl}": float(1 - _N.cdf(z - dl * math.sqrt(n))) for dl in (0.2, 0.3, 0.5, 0.8)}}


def interpretation_block(verdicts: dict) -> dict:
    ok = lambda k: verdicts[k] == PASS_LABEL  # noqa: E731
    a, b = ok("SIMMIX_M1_INTL"), ok("SIMMIX_M2_INTL")
    s = ("해외 깊이·회복 모두 통과" if a and b else "해외 깊이만 통과" if a else "해외 회복만 통과" if b else "통과 없음")
    s += ". 미국 값은 설명용(합친 평균 부호는 볼록성으로 미리 정해짐)."
    u, i = ok("TWOPH_M2_US"), ok("TWOPH_M2_INTL")
    t = ("미국·해외 모두 통과(두 집단에서 지지)" if u and i else "미국만 통과" if u else "해외만 통과" if i else "통과 없음")
    t += ". 미국 C 와 해외 I2 는 같은 세계 급락을 겹쳐 담아 두 집단이 완전히 독립은 아니다."
    return {"SIMMIX": s, "TWOPH": t}


LM_FALLBACK = "판정 통과 모델 없음 → 랜드마크 모델(LM) 표시. LM 도 crash-landmark-v1 판정은 통과하지 못했다(FAIL_UNDERPOWERED)"


def best_block(verdicts: dict, dets: dict) -> dict:
    """3.8 '가장 나은 모델' 규칙(결과 전 고정)."""
    ok = lambda k: verdicts[k] == PASS_LABEL  # noqa: E731
    depth = "SIMMIX" if ok("SIMMIX_M1_INTL") else "LM"
    sup = {"TWOPH": [k for k in ("TWOPH_M2_US", "TWOPH_M2_INTL") if ok(k)], "SIMMIX": [k for k in ("SIMMIX_M2_INTL",) if ok(k)]}
    cand = [(m, len(ks), min(float(dets[k]["p"]) for k in ks)) for m, ks in sup.items() if ks]
    rec = "LM"
    if cand:
        cand.sort(key=lambda c: (-c[1], c[2], 0 if c[0] == "TWOPH" else 1))
        rec = cand[0][0]
    txt = lambda m: "판정 통과 모델" if m != "LM" else LM_FALLBACK  # noqa: E731
    if depth == "LM" and rec == "LM":
        label = LM_FALLBACK
    else:
        label = f"깊이: {depth} — {txt(depth)} · 회복: {rec} — {txt(rec)}"
    return {"depth": depth, "recovery": rec, "label": label}


# ================================================================ 설명용·견고성·모델 표
def descriptive_block(cu: list, ci: list) -> dict:
    vs_base = {}
    for m in ("LM", "SIM", "SIMMIX", "TWOPH", "LMB", "LM_POOL"):
        vs_base[m] = {"m1": None if m == "TWOPH" else {"US": summ(_pairs_items(cu, f"B_{m}_M1", "US"), "US"),
                                                       "INTL": summ(_pairs_items(ci, f"B_{m}_M1", "INTL"), "INTL")},
                      "m2": {"US": summ(_pairs_items(cu, f"B_{m}_M2", "US"), "US"), "INTL": summ(_pairs_items(ci, f"B_{m}_M2", "INTL"), "INTL")}}
    simmix_us = {}
    for which, Q, QS in (("m1", "SIMMIX_M1", "SIM_M1"), ("m2", "SIMMIX_M2", "SIM_M2")):
        items = _pairs_items(cu, Q, "US")
        x = summ(items, "US")
        ids = {r["id"] for r, _v in items}
        sims = [c["val"][QS] for c in cu if c["r"]["id"] in ids and c["val"][QS] is not None]
        x["bound"] = None if not sims else 0.5 * float(np.mean(sims))
        simmix_us[which] = x
    both = lambda p1, p2: {"m1": {"US": summ(_pairs_items(cu, p1, "US"), "US"), "INTL": summ(_pairs_items(ci, p1, "INTL"), "INTL")},  # noqa: E731
                           "m2": {"US": summ(_pairs_items(cu, p2, "US"), "US"), "INTL": summ(_pairs_items(ci, p2, "INTL"), "INTL")}}
    pool = {"INTL": {"m1": summ(_pairs_items(ci, "LMPOOL_M1", "INTL"), "INTL"), "m2": summ(_pairs_items(ci, "LMPOOL_M2", "INTL"), "INTL")},
            "US_C": {w: st3([c["val"][Q] for c in cu if c["r"]["stratum"] == "C" and c["val"][Q] is not None])
                     for w, Q in (("m1", "LMPOOL_M1"), ("m2", "LMPOOL_M2"))},
            "n_identical_us": {w: int(sum(1 for r, v in _pairs_items(cu, Q, "US") if abs(v) <= 1e-12))
                               for w, Q in (("m1", "LMPOOL_M1"), ("m2", "LMPOOL_M2"))},
            "n_us": {w: len(_pairs_items(cu, Q, "US")) for w, Q in (("m1", "LMPOOL_M1"), ("m2", "LMPOOL_M2"))}}
    return {"vs_base": vs_base, "simmix_us": simmix_us, "sim_vs_lm": both("SIM_M1", "SIM_M2"), "lmb_vs_lm": both("LMB_M1", "LMB_M2"),
            "lm_pool_vs_lm": pool}


def robustness_block(cu: list, ci: list, dets: dict) -> dict:
    lab = L()
    v1 = lab.v1()
    only, per, pep = {}, {}, {}
    for key in KEYS:
        Q, pop = VERDICT_SPEC[key]
        cs = cu if pop == "US" else ci
        only[key] = summ(_pairs_items(cs, Q, pop, ROBUST_LANDMARKS), pop)
        per[key] = dets[key]["per_landmark"]
        if pop == "INTL":
            pep[key] = dets[key].get("p_episode")
    tw = [(c["r"]["t0"], c["r"]["rec"], c["val"]["TWOPH_M2"]) for c in cu
          if c["r"]["stratum"] in lab.US_STRATA and c["val"]["TWOPH_M2"] is not None]
    return {"only_63_126": only, "per_landmark": per, "p_episode_intl": pep, "cluster_us_twoph": v1.cluster_p(tw)}


def models_block(cu: list, ci: list) -> dict:
    lab = L()
    out: dict[str, Any] = {"m1": {}, "m2": {}, "calib": {}}
    for pop, cs, strata in (("US", cu, lab.US_STRATA), ("INTL", ci, lab.INTL_STRATA)):
        for e in lab.LANDMARKS:
            for s in tuple(strata) + ("all",):
                ps = [(c["r"], c["pairs"][e]) for c in cs if e in c["pairs"]
                      and (c["r"]["stratum"] == s or (s == "all" and c["r"]["stratum"] in strata))]
                p1 = [(r, p) for r, p in ps if all(m in p["s1"] for m in ("BASE", "LM", "SIM", "SIMMIX"))]
                cov = {}
                for m in ("LM", "SIM", "SIMMIX"):
                    hits = [p["pred"][m][0]["0.1"] <= r["FD"] <= p["pred"][m][0]["0.9"] for r, p in p1]
                    cov[m] = float(np.mean(hits)) if hits else None
                out["m1"][f"{pop}_{e}_{s}"] = {"n": len(p1), "score": {m: lab.mean_or_none([p["s1"][m] for _r, p in p1])
                                                                       for m in ("BASE", "LM", "SIM", "SIMMIX")}, "cov80": cov}
                p2 = [(r, p) for r, p in ps if all(m in p["s2"] for m in MODELS_ROW)]
                out["m2"][f"{pop}_{e}_{s}"] = {"n": len(p2), "score": {m: lab.mean_or_none([p["s2"][m] for _r, p in p2]) for m in MODELS_ROW}}
                if s == "all":
                    out["calib"][f"{pop}_{e}"] = {
                        str(h): dict({"n": len(p2)}, **{m: lab.mean_or_none([_fget(p["pred"][m][1], h) for _r, p in p2]) for m in MODELS_ROW},
                                     obs=(float(np.mean([r["R"] - e <= h for r, _p in p2])) if p2 else None))
                        for h in lab.HZ}
    return out


def brief(p: dict) -> dict:
    lab = L()
    pr = p["pred"]
    return {"e": p["e"], "asof": lab.dstr(p["st"]["asof"]), "d": p["st"]["d"], "m": p["st"]["m"],
            "BASE": {"m1": pr["BASE"][0], "m2": pr["BASE"][1]}, "LM": {"m1": pr["LM"][0], "m2": pr["LM"][1]},
            "SIM": {"m1": pr["SIM"][0], "m2": pr["SIM"][1]}, "SIMMIX": {"m1": pr["SIMMIX"][0], "m2": pr["SIMMIX"][1]},
            "TWOPH": {"m2": pr["TWOPH"][1]}}


def make_reader(us: list, all_recs: list, by_id: dict, n_paths: int):
    lab = L()

    def reader(ep: dict, d: int, mapping: str) -> dict:
        c = by_id.get(ep["id"])
        out: dict[str, Any] = {"landmarks": []}
        for e in lab.LANDMARKS:
            p = c["pairs"].get(e) if c is not None else pair_calc(us, all_recs, ep, e, n_paths)
            out["landmarks"].append(brief(p) if p is not None else {"e": int(e), "note": "이미 회복 또는 자료 끝"})
        if mapping == "inside":
            e_s = int(d - ep["t0"])
            p = pair_calc(us, all_recs, ep, e_s, n_paths)
            if p is not None:
                out["snapshot"] = brief(p)
        return out

    return reader


def _rng_of(vals) -> Optional[list]:
    a = [float(v) for v in vals if v is not None]
    return [min(a), max(a)] if a else None


def _best_preds(b: dict, best: dict) -> tuple:
    dm = b[best["depth"]]["m1"]
    rm = b[best["recovery"]]["m2"]
    return dm, rm


def active_sentence(b: dict, best: dict, e_now: int) -> str:
    dm, rm = _best_preds(b, best)
    lab = L()
    rec1 = _rng_of([None if b[m]["m2"] is None else _fget(b[m]["m2"], 252) for m in MODELS_ROW])
    dtxt = "—" if dm is None else f"{lab.pct(dm['0.5'], 0)}(10~90% {lab.pct(dm['0.1'], 0)}~{lab.pct(dm['0.9'], 0)})"
    rtxt = "—" if rm is None else lab.pct(_fget(rm, 252), 0, False)
    rr = "—" if rec1 is None else f"{rec1[0] * 100:.0f}~{rec1[1] * 100:.0f}%"
    return (f"발생 뒤 {e_now}거래일, 지금 {lab.pct(b['d'], 0)}: 최종 깊이 가운데 {dtxt}, 1년 안 전고점 회복 {rtxt}(모델 간 {rr}) "
            f"— 깊이 {best['depth']}, 회복 {best['recovery']} 기준.")


def current_block(ctx: dict, us: list, all_recs: list, n_paths: int, best: dict, smoke: bool) -> dict:
    lab = L()
    cur = lab.reading_now(ctx)
    last = ctx["last"]
    ep = lab.active_episode(ctx, last)
    cur["active"], cur["active_note"], cur["active_sentence"] = None, None, None
    if ep is None:
        cur["active_note"] = "진행 중 급락 사건 없음"
    else:
        e_now = int(last - ep["t0"])
        if e_now > lab.H:
            cur["active_note"] = "발생 뒤 3년이 넘어 랜드마크 읽기를 만들지 않음"
        else:
            p = pair_calc(us, all_recs, ep, e_now, n_paths)
            if p is None:
                cur["active_note"] = "오늘 랜드마크 읽기를 만들 수 없음(자료 부족)"
            else:
                cur["active"] = brief(p)
                cur["active_sentence"] = active_sentence(cur["active"], best, e_now)
    cur["spy_check"] = lab.spy_check(cur["state"], smoke)
    return cur


def reading_table(ctx: dict, us: list, cu: list, n_paths: int, best: dict) -> dict:
    """4.3-A 조견표(비전문가용, 설명용)."""
    lab = L()
    last = ctx["last"]
    D = pd.Timestamp(ctx["idx"][last])
    g = lab.garch_filter(lab.logret(ctx["Lv"])[1:last + 1])
    h0 = {}
    for e in GRID_E:
        hs = [c["pairs"][e]["S"]["vol_now"] ** 2 / 252 for c in cu if e in c["pairs"] and c["pairs"][e]["S"] is not None]
        h0[e] = float(np.median(hs)) if hs else float(g["v"])
    v = {e: math.sqrt(252 * h0[e]) * 100 for e in GRID_E}
    vol_note = (f"모의의 변동성은 과거 미국 급락의 같은 시점 중앙값(연율 21일째 {v[21]:.0f}% · 63일째 {v[63]:.0f}% · 126일째 {v[126]:.0f}%)에서 "
                "출발한다. 오늘의 변동성은 쓰지 않는다.")
    rows = []
    for e in GRID_E:
        for gi, d in enumerate(GRID_D):
            m = min(d, GRID_DD0)
            st = {"asof": D, "d": d, "m": m, "x": max(-math.log(1 + d), lab.X_FLOOR), "x_raw": -math.log(1 + d)}
            B = lab._base_from_state(us, st, GRID_DD0, e)
            M = lab._lm_from_state(us, st, e)
            T = twoph_from_state(us, st, e)
            rng = np.random.default_rng([lab.SEED, 0, int(last), int(e), gi])
            S = lab.simulate_from(math.log(1 + d), math.log(1 + m), g["mu"], g["omega"], h0[e], g["z"], lab.H - e, n_paths, rng)
            pred = {"BASE": {"m1": B["m1_trunc"], "m2": B["m2"]}, "LM": {"m1": M["m1"], "m2": M["m2"]},
                    "SIM": {"m1": S["q"], "m2": S["F"]}, "SIMMIX": {"m1": mix_q(M["m1"], S["q"]), "m2": mix_F(M["m2"], S["F"])},
                    "TWOPH": {"m1": None, "m2": None if T is None else T["m2"]}}
            dm, rm = pred[best["depth"]]["m1"], pred[best["recovery"]]["m2"]
            rows.append({"e": e, "d": d, "m": m,
                         "best_depth": None if dm is None else {k: dm[k] for k in ("0.1", "0.5", "0.9")},
                         "best_rec": None if rm is None else {str(h): _fget(rm, h) for h in (252, 504, 1260)},
                         "rec1_range": _rng_of([None if pred[k]["m2"] is None else _fget(pred[k]["m2"], 252) for k in MODELS_ROW]),
                         "depth50_range": _rng_of([None if pred[k]["m1"] is None else pred[k]["m1"]["0.5"] for k in ("BASE", "LM", "SIM", "SIMMIX")]),
                         "n_depth": M["n1"], "n_rec": M["n2"],
                         "base": [None if B["m1_trunc"] is None else B["m1_trunc"]["0.5"], None if B["m2"] is None else _fget(B["m2"], 252)]})
    return {"best": best, "vol_note": vol_note, "as_of": lab.dstr(D), "h0": {str(e): h0[e] for e in GRID_E}, "rows": rows}


# ================================================================ 재현 확인
def _cmp(ours: list, path: Path, model: str, us_only: bool) -> dict:
    lab = L()
    if not path.exists():
        return {"skipped": "파일 없음"}
    cols = ("d_q10", "d_q25", "d_q50", "d_q75", "d_q90", "r_252", "r_504", "r_756", "r_1260")
    ok = lambda r: r["model"] == model and r["landmark"] in lab.LANDMARKS and (not us_only or r["market"] == "US")  # noqa: E731
    pub = {(r["market"], r["episode_id"], r["landmark"]): r for r in lab.read_predictions(path) if ok(r)}
    n, nd, mx, miss = 0, 0, 0.0, 0
    for r in ours:
        if not ok(r):
            continue
        key = (r["market"], r["episode_id"], int(r["landmark"]))
        if key not in pub:
            miss += 1
            continue
        n += 1
        bad = False
        for c in cols:
            a, b = lab.fin(r.get(c)), pub[key].get(c)
            if a is None and b is None:
                continue
            if a is None or b is None:
                bad = True
                continue
            dv = abs(a - float(b))
            mx = max(mx, dv)
            bad = bad or dv > 1e-6
        nd += int(bad)
    return {"n_compared": n, "max_abs_diff": mx if n else None, "n_diff_gt_1e-6": nd, "n_not_in_published": miss}


def checks_block(rows: list, vs_base_lm: dict, smoke: bool) -> dict:
    if smoke:
        return {"skipped": "스모크"}
    res_dir = PROJECT_ROOT / "research" / "results"
    lm_p = res_dir / "crash-landmark-v1" / "predictions.csv"
    out = {"lm_check": _cmp(rows, lm_p, "LM", False), "base_check": _cmp(rows, lm_p, "BASE", False),
           "sim_check": _cmp(rows, res_dir / "crash-simpath-v1" / "predictions.csv", "SIM", True)}
    try:
        pub = json.loads((res_dir / "crash-landmark-v1" / "results.json").read_text(encoding="utf-8"))
        pc = {}
        for w, k in (("m1", "LM_M1"), ("m2", "LM_M2")):
            mine = vs_base_lm[w]["US"]
            pm, pp = pub["detail"][k]["mean"]["pooled"], pub["detail"][k]["p"]
            pc[k] = {"mine_mean": mine["mean"]["pooled"], "pub_mean": pm, "mine_p": mine["p"], "pub_p": pp,
                     "mine_n": mine["n"]["pooled"], "pub_n": pub["detail"][k]["n"]["pooled"]}
        out["published_check"] = pc
    except (OSError, ValueError, KeyError, TypeError):
        out["published_check"] = {"skipped": "파일 없음"}
    return out


# ================================================================ predictions.csv
def pred_rows_of(c: dict) -> list:
    lab = L()
    r = c["r"]
    us_j = r["market"] == "US" and r["stratum"] in lab.US_STRATA
    in_j = r["market"] != "US" and r["stratum"] in lab.INTL_STRATA
    rows = []
    for e, p in c["pairs"].items():
        B, M, S, T, st, q = p["B"], p["M"], p["S"], p["T"], p["st"], p["q"]
        j1 = jm2s = jt = 0
        if us_j:
            jt = int(q["TWOPH_M2"] is not None)
        if in_j:
            j1 = int(q["SIMMIX_M1"] is not None)
            jm2s = int(q["SIMMIX_M2"] is not None)
            jt = int(q["TWOPH_M2"] is not None)
        jbl2 = int(jm2s or jt)
        nb = lab.n_train_of(B["m1_trunc"], B["n1"], B["m2"], B["n2"])
        nl = lab.n_train_of(M["m1"], M["n1"], M["m2"], M["n2"])
        rows.append(lab.pred_row(STUDY, "BASE", r, e, st["asof"], nb, None, B["m1_trunc"], B["m2"], None, j1, jbl2))
        rows.append(lab.pred_row(STUDY, "LM", r, e, st["asof"], nl, None, M["m1"], M["m2"], None, j1, jbl2))
        if S is not None:
            rows.append(lab.pred_row(STUDY, "SIM", r, e, st["asof"], S["n_hist"], None, S["q"], S["F"]))
        sq, sF = p["pred"]["SIMMIX"]
        if sq is not None or sF is not None:
            rows.append(lab.pred_row(STUDY, "SIMMIX", r, e, st["asof"], nl, None, sq, sF, None, j1, jm2s))
        if T is not None:
            rows.append(lab.pred_row(STUDY, "TWOPH", r, e, st["asof"], T["n"], None, None, T["m2"], None, 0, jt))
    return rows


def _pred_bytes(rows: list) -> int:
    lab = L()
    lines = [",".join(lab.PRED_COLUMNS)] + [",".join(lab._cell(col, r.get(col)) for col in lab.PRED_COLUMNS) for r in rows]
    return len(("\n".join(lines) + "\n").encode("utf-8"))


# ================================================================ 평가
def evaluate(data: dict, intl: dict, smoke: bool) -> tuple:
    from core import research_power as rp

    lab = L()
    n_paths = lab.N_SIM_SMOKE if smoke else lab.N_SIM
    ctx = lab.us_context(data)
    us = ctx["recs"]
    idx = ctx["idx"]
    ictx = {k: lab.market_context(intl[k], k) for k in lab.INTL_REGIONS}
    intl_recs = [r for k in lab.INTL_REGIONS for r in ictx[k]["eps"]]
    all_recs = us + intl_recs

    cu = [episode_calc(us, all_recs, r, n_paths) for r in us]
    ci = [episode_calc(us, all_recs, r, n_paths) for r in intl_recs]
    by_id = {c["r"]["id"]: c for c in cu}

    rows: list = []
    for c in cu + ci:
        rows += pred_rows_of(c)

    verdicts, dets = judge_all(cu, ci)
    best = best_block(verdicts, dets)
    desc = descriptive_block(cu, ci)
    robust = robustness_block(cu, ci, dets)
    events = lab.events_rows(ctx, make_reader(us, all_recs, by_id, n_paths))
    current = current_block(ctx, us, all_recs, n_paths, best, smoke)
    table = reading_table(ctx, us, cu, n_paths, best)
    checks = checks_block(rows, desc["vs_base"]["LM"], smoke)
    notes = list(NOTES)

    summary = {}
    for k in KEYS:
        d = dets[k]
        if d["verdict"] == "NOT_EVALUABLE":
            summary[f"{k} {SHORT[k]}"] = f"NOT_EVALUABLE · n {d['n']['pooled']} · {d.get('reason', '')}"
        else:
            summary[f"{k} {SHORT[k]}"] = (f"{d['verdict']} · n {d['n']['pooled']} · 평균 d {d['mean']['pooled']:+.4f} · p {d['p']:.4f} · "
                                          f"홈 {d['holm_rank']}위 문턱 {d['holm_threshold']:.4f}")
    summary[f"지금(Ken French {current['as_of']})"] = lab.now_line(current)

    episodes = []
    for c in cu + ci:
        r = c["r"]
        lmv = {}
        for e, p in c["pairs"].items():
            lmv[str(e)] = [p["st"]["d"], p["st"]["m"]] + [p["s1"].get(m) for m in ("BASE", "LM", "SIM", "SIMMIX")] + \
                          [p["s2"].get(m) for m in MODELS_ROW]
        episodes.append({"id": r["id"], "t0": lab.dstr(r["t0_date"]), "era": r["stratum"], "dd0": r["dd0"], "FD": r["FD"], "R": r["R"],
                         "lm": lmv, "val": {Q: c["val"][Q] for Q in ("SIMMIX_M1", "SIMMIX_M2", "TWOPH_M2")}})

    res = {
        "study": STUDY, "lab_version": lab.LAB_VERSION, "rules": RULES_VERSION, "judge_version": JUDGE_VERSION, "smoke": bool(smoke),
        "data": {"source": data["source"], "first_date": str(idx[0].date()), "last_date": str(idx[-1].date()), "n_days": int(len(idx)),
                 "intl": {k: {"first_date": str(intl[k].index[0].date()), "last_date": str(intl[k].index[-1].date()),
                              "n_episodes": len(ictx[k]["eps"])} for k in lab.INTL_REGIONS}},
        "constants": dict(lab.lab_constants(), KEYS=list(KEYS), K=K, FAMILY_ALPHA=FAMILY_ALPHA, W_MIX=W_MIX, GRID_E=list(GRID_E),
                          GRID_D=list(GRID_D), GRID_DD0=GRID_DD0, ROBUST_LANDMARKS=list(ROBUST_LANDMARKS), n_paths=n_paths),
        "family": {"k": K, "alpha": FAMILY_ALPHA, "method": "holm", "alpha_expr": "Holm, 족 오류율 0.05, 문턱 0.05/4·0.05/3·0.05/2·0.05",
                   "keys": list(KEYS), "this_study": list(KEYS), "separate_from": "crash-cycle-lab 7연구 족(15개, 0.05/15)과 별개"},
        "power": rp.power_report(lab.YEARS_US, K), "power_intl": rp.power_report(lab.YEARS_INTL, K),
        "power_episode": {k: power_holm(dets[k]["n"]["pooled"]) for k in KEYS},
        "verdicts": verdicts, "summary": summary, "detail": dets,
        "interpretation": interpretation_block(verdicts), "best": best,
        "descriptive": desc, "robustness": robust, "models": models_block(cu, ci),
        "episode_fields": EPISODE_FIELDS, "episodes": episodes, "events": events, "current": current, "reading_table": table,
        "checks": checks, "seen": SEEN, "expected": EXPECTED, "notes": notes, "limits": LIMITS,
    }
    # 크기 대비책(결정적)
    size = lambda o: len(json.dumps(lab.v1()._clean(o), ensure_ascii=False, indent=1, default=str).encode("utf-8"))  # noqa: E731
    if size(res) > JSON_MAX_BYTES:
        for ep in res["episodes"]:
            if not ep["id"].startswith("US:"):
                ep["lm"] = None
        notes.append("results.json 크기 때문에 해외 사건의 랜드마크별 점수를 뺐다(predictions.csv 에 있음)")
        if size(res) > JSON_MAX_BYTES:
            for ep in res["episodes"]:
                ep["lm"] = None
            notes.append("results.json 크기 때문에 미국 사건의 랜드마크별 점수도 뺐다(predictions.csv 에 있음)")
    if _pred_bytes(rows) > lab.PRED_MAX_BYTES:
        rows = [r for r in rows if r["model"] != "SIM"]
        notes.append("predictions.csv 크기 때문에 SIM 줄을 뺐다(SIMMIX 줄은 남음)")
    return res, rows


# ================================================================ 보고서
def _strata(pop: str) -> tuple:
    lab = L()
    return lab.US_STRATA if pop == "US" else lab.INTL_STRATA


def _summ_txt(x: Optional[dict], pop: str) -> str:
    lab = L()
    if not x:
        return "—"
    if pop == "US":
        return " / ".join(lab.sgn(x["mean"][s]) for s in lab.US_STRATA) + f" / {lab.sgn(x['mean']['pooled'])} · p {lab.pval(x['p'])} (n {x['n']['pooled']})"
    return (" / ".join(lab.sgn(x["mean"][s]) for s in lab.INTL_STRATA) + f" · 군집 p {lab.pval(x['p_cluster'])} "
            f"(사건 {x['n_episodes']} · 군집 {x['n_clusters']})")


def _f100(v) -> str:
    lab = L()
    return "—" if lab.fin(v) is None else f"{v * 100:.2f}"


def _rt_line(lab, row: dict) -> str:
    bd, br = row.get("best_depth"), row.get("best_rec")
    dtxt = "—" if not bd else f"{lab.pct(bd['0.5'], 0)} ({lab.pct(bd['0.1'], 0)} ~ {lab.pct(bd['0.9'], 0)})"
    g = lambda h: "—" if not br or br.get(str(h)) is None else lab.pct(br[str(h)], 0, False)  # noqa: E731
    d50, r1 = row.get("depth50_range"), row.get("rec1_range")
    rng = (("—" if not d50 else f"{lab.pct(d50[1], 0)}~{lab.pct(d50[0], 0)}") + " · "
           + ("—" if not r1 else f"{r1[0] * 100:.0f}~{r1[1] * 100:.0f}%"))
    b = row.get("base") or [None, None]
    return (f"| {E_NAMES.get(int(row['e']), str(row['e']))} | {lab.pct(row['d'], 0)} ({lab.pct(row['m'], 0)}) | {dtxt} | {g(252)} | {g(504)} | {g(1260)} | "
            f"{rng} | {lab.pct(b[0], 0)} · {lab.pct(b[1], 0, False)} |")


EV_HEAD = ["| e | 기준일 | 지금 깊이 d | 지금까지 최저 m | BASE 깊이 | LM 깊이 | SIMMIX 깊이 | BASE 회복 | LM 회복 | SIMMIX 회복 | TWOPH 회복 |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]


def _ev_line(lab, b: dict, suffix: str = "") -> str:
    if "asof" not in b:
        return f"| {b['e']} | — | — | — | {b.get('note', '')} | | | | | | |"
    return (f"| {b['e']} | {b['asof']} | {lab.pct(b['d'])} | {lab.pct(b['m'])} | {lab.q3(b['BASE']['m1'])} | {lab.q3(b['LM']['m1'])} | "
            f"{lab.q3(b['SIMMIX']['m1'])} | {lab.r3(b['BASE']['m2'])} | {lab.r3(b['LM']['m2'])} | {lab.r3(b['SIMMIX']['m2'])} | "
            f"{lab.r3(b['TWOPH']['m2'])} |{suffix}")


def report(res: dict, smoke: bool) -> str:
    from core import research_power as rp

    lab = L()
    R = [f"# 급락 예측 융합 — 랜드마크 ⊕ 경로 모의 · 깊이 → 회복 두 단계 ({res['study']}{' · 스모크(가짜 자료)' if smoke else ''})", ""]
    if smoke:
        R += ["> 스모크 실행: 가짜 자료라 숫자·라벨에 뜻이 없다. 계산 경로 확인용이다.", ""]
    dt = res["data"]
    R += [f"자료: {dt['source']} · {dt['first_date']} ~ {dt['last_date']} ({dt['n_days']}일) · 해외 "
          + ", ".join(f"{lab.REGION_LABELS.get(k, k)} {v['first_date']}~{v['last_date']}(사건 {v['n_episodes']})" for k, v in dt["intl"].items())
          + f" · 규칙 {res['rules']} · 판정 {res['judge_version']} · 공용 {res['lab_version']} · 경로 {res['constants']['n_paths']}개", ""]
    # 2 한눈에
    R += ["## 한눈에", "", "| 키 | 비교 | 판정 집단 | 라벨 | n (층/합친) | 평균 d (층/합친) | p (한쪽 부호 뒤집기) | 홈 순위·문턱 |",
          "|---|---|---|---|---|---|---|---|"]
    for k in KEYS:
        d = res["detail"][k]
        st = _strata(d["population"])
        lab_txt = d["verdict"] + (" (FAIL_UNDERPOWERED)" if d.get("fail_kind") == "FAIL_UNDERPOWERED" else "")
        if d["verdict"] == "NOT_EVALUABLE":
            lab_txt += f" — {d.get('reason', '')}"
        pop = "미국 사건 A/B/C" if d["population"] == "US" else f"해외 군집 I1/I2 (사건 {d.get('n_episodes', '—')})"
        holm = "—" if d.get("holm_rank") is None else f"{d['holm_rank']}위 · {d['holm_threshold']:.4f}" + (" · 기각" if d.get("holm_reject") else "")
        R.append(f"| {k} | {MODEL_NAMES[k]} | {pop} | **{lab_txt}** | " + "/".join(str(d["n"][s]) for s in st) + f"/{d['n']['pooled']} | "
                 + " / ".join(lab.sgn(d["mean"][s]) for s in st) + f" / {lab.sgn(d['mean']['pooled'])} | {lab.pval(d.get('p'))} | {holm} |")
    R += ["", "평균 d = LM 점수 − 변형 점수(양수 = 변형이 더 잘 맞힘). 깊이 = 평균 핀볼 손실(전고점 대비 소수), 회복 = 1·2·3·5년 브라이어 평균(0~1).", "",
          "판정 기준: 이 연구의 판정 4개를 새 족으로 보고 홈(Holm) 단계 하강법으로 족 오류율 0.05 를 지킨다(p 가 작은 순서로 0.05/4, 0.05/3, 0.05/2, 0.05 와 "
          "비교하고 처음 넘지 못한 곳에서 멈춤). 급락 고도화 7연구의 15개 족(α = 0.05/15)과는 별개다. 비교 대상은 v1 기준선이 아니라 랜드마크 모델(LM: 깊이 LM_ANCHOR, "
          "회복 LM_SCALED)이고 같은 (사건, 랜드마크) 쌍에서 다시 계산한다. 미국은 사건 단위(랜드마크 평균)로 시대 A(1927-07~1966)·B(1967~2007)·C(2008-01~2024-09) "
          "평균이 모두 양수여야 하고, 해외는 동시 급락 군집 단위(평일 63일)로 I1(1991~2007)·I2(2008~2024-09) 평균이 모두 양수여야 한다. 표본 조건 미국 A ≥ 4·B ≥ 5·"
          "C ≥ 4·합친 ≥ 15, 해외 I1 ≥ 3·I2 ≥ 3·합친 ≥ 10 군집. 2024-10 이후 발생 사건은 보고만.", "",
          f"- 해석(SIMMIX): {res['interpretation']['SIMMIX']}", f"- 해석(TWOPH): {res['interpretation']['TWOPH']}", "",
          rp.power_line(res["power"]) + " (IR 기준은 일별 활성 수익용 근사이고 실제 기준은 아래 사건·군집 단위다.)", ""]
    for k in KEYS:
        pe = res["power_episode"][k]
        ne, pp = pe.get("needed_effect_sd") or {}, pe.get("pass_prob_first") or {}
        R.append(f"- 검정력 {k}: 합친 n={pe['n']} → 필요 효과 첫 문턱 {lab.num(ne.get('first'), 2)}sd · 마지막 문턱 {lab.num(ne.get('last'), 2)}sd, "
                 "첫 문턱 통과 확률 δ0.2/0.3/0.5/0.8 = " + "/".join("—" if pp.get(x) is None else f"{pp[x] * 100:.0f}%" for x in ("0.2", "0.3", "0.5", "0.8")))
    R += ["", "**이 연구는 랜드마크 모델이 v1 기준선보다 낫다는 것을 다시 판정하지 않는다**(모든 미국 사건과 해외 군집에서 이미 봄). 기준선 대비 값은 설명용이다.", "",
          "통과는 '설명 도구로 쓸 근거'까지만 뜻한다. **통과해도 엔진·아침 메시지·주문은 바뀌지 않는다**(사용자 확인 뒤 별도 작업).", ""]
    # 3
    R += ["## 이 연구가 묻는 것", "",
          "- 급락(1년 고점보다 15% 아래로 처음 내려간 날) 1·3·6개월째(21·63·126거래일)에 두 가지를 묻는다.",
          "- (1) 과거 사건에서 배운 예측(LM)과 그때까지의 일별 수익으로 만든 가상 경로(SIM)를 반반 섞으면(SIMMIX) LM 하나보다 나아지나.",
          "- (2) '얼마나 더 빠질지'(LM 깊이 모델의 남은 추가 하락)를 '언제 회복할지'에 넣어 남은 회복 시간을 '바닥까지 + 바닥에서 오르는 시간'으로 나누면(TWOPH) LM 하나보다 나아지나.", ""]
    # 4
    R += ["## 이미 본 것과 그 영향", "", "### 이미 본 것", ""] + [f"{i}. {s}" for i, s in enumerate(res["seen"], 1)]
    R += ["", "### 판정이 말할 수 있는 것과 없는 것", ""] + [f"- {s}" for s in CAN_SAY]
    R += ["", "### 랜드마크 21 — 남긴다 (사전 논리)", ""] + [f"{i}. {s}" for i, s in enumerate(WHY_21, 1)] + [""]
    # 5 지금 읽기
    cur = res["current"]
    R += ["## 지금 읽기 (설명용 — 추천 아님)", "", lab.READING_HEADER, ""] + lab.reading_state_lines(cur)
    if cur.get("active"):
        b = cur["active"]
        R += [f"진행 중 사건의 오늘 랜드마크 읽기(e = {b['e']}거래일, 기준일 {b['asof']}):", "",
              "| 모델 | 최종 깊이 10/50/90% | 회복 1/2/5년 |", "|---|---|---|"]
        for m in MODELS_ROW:
            R.append(f"| {m} | {lab.q3(b[m].get('m1'))} | {lab.r3(b[m].get('m2'))} |")
        R += ["", f"한 문장: {cur.get('active_sentence')}", ""]
    else:
        R += [f"오늘 랜드마크 읽기: {cur.get('active_note') or '—'}.", ""]
    rt = res["reading_table"]
    R += ["### 급락 N일째 조견표 (설명용)", "",
          "보는 법: 급락(1년 고점보다 15% 아래로 처음 내려간 날)이 시작되고 '며칠째'만큼 지났고 지금 전고점보다 '지금 깊이'만큼 아래일 때, 과거 급락에서 배운 모델이 말하는 "
          "최종 깊이(앞으로 3년 안 가장 낮은 지점)와 지금부터 전고점을 되찾을 확률이다. '10~90% 범위'는 과거 사건 열 개 중 여덟 개가 들어간 폭이고, '모델 간 차이'는 같은 "
          "자료로 만든 여러 모델이 얼마나 다르게 보는지다 — 폭이 넓을수록 불확실하다. 지금 깊이가 −15% 보다 얕은 줄은 −15% 까지 빠졌다가 반등한 경우다.", "",
          "| 급락 며칠째 | 지금 깊이 (지금까지 최저) | 최종 깊이 가운데 값 (10~90% 범위) | 1년 안 전고점 회복 | 2년 안 | 5년 안 | 모델 간 차이 (깊이 가운데 · 1년 회복) | v1 기준선 (깊이 가운데 · 1년 회복) |",
          "|---|---|---|---|---|---|---|---|"]
    R += [_rt_line(lab, row) for row in rt["rows"]]
    nlist = []
    for e in GRID_E:
        rr = [row for row in rt["rows"] if int(row["e"]) == e]
        if rr:
            nlist.append(f"{E_NAMES[e]} 깊이 {rr[0]['n_depth']}개 · 회복 {rr[0]['n_rec']}개")
    R += ["", f"표시 모델: {rt['best']['label']} (깊이 {rt['best']['depth']}, 회복 {rt['best']['recovery']}).", "", rt["vol_note"], "",
          f"학습 사건: {' / '.join(nlist)} (랜드마크마다 다름 — {rt.get('as_of')} 까지 확정된 미국 사건).", "",
          "추천이 아니다. 엔진·주문과 연결되지 않는다.", "", lab.spy_line(cur.get("spy_check") or {}), ""]
    # 6 7개 사건
    R += ["## 사용자가 든 7개 사건", ""] + lab.events_note_lines(res["events"])
    R += ["### 랜드마크 읽기 (그 시점까지 확정된 사건만으로 학습, 깊이 = 10/50/90%, 회복 = 1/2/5년)", ""]
    for ev in res["events"]:
        st = ev.get("study")
        if not st:
            continue
        R += [f"**{ev['label']}** — 발생일 {ev['episode_t0']}", ""] + EV_HEAD
        R += [_ev_line(lab, b) for b in st["landmarks"]]
        if st.get("snapshot"):
            R.append(_ev_line(lab, st["snapshot"], " ← 기준일 스냅숏(판정 아님)"))
        R.append("")
    # 7 SIMMIX
    mb = res["models"]
    R += ["## 융합 1 — LM ⊕ SIM (SIMMIX)", "", "판정은 해외 군집에서만 한다. 미국 값은 설명용이다.", "",
          "### 깊이: 평균 핀볼 손실(×100, 전고점 대비 %p, 낮을수록 잘 맞힘)과 실제가 10~90% 안에 든 비율(목표 80%)", "",
          "평가 = 깊이 확정이고 BASE·LM·SIM·SIMMIX 가 모두 있는 (사건, 랜드마크) 쌍.", "",
          "| 집단 | e | 층 | 평가 수 | BASE | LM | SIM | SIMMIX | 80% 포함 LM / SIM / SIMMIX |", "|---|---|---|---|---|---|---|---|---|"]
    for pop in ("US", "INTL"):
        for e in lab.LANDMARKS:
            for s in tuple(_strata(pop)) + ("all",):
                x = mb["m1"][f"{pop}_{e}_{s}"]
                sc, cv = x["score"], x["cov80"]
                R.append(f"| {'미국' if pop == 'US' else '해외'} | {e} | {'합' if s == 'all' else s} | {x['n']} | "
                         + " | ".join(_f100(sc[m]) for m in ("BASE", "LM", "SIM", "SIMMIX")) + " | "
                         + " / ".join(lab.pct(cv[m], 0, False) for m in ("LM", "SIM", "SIMMIX")) + " |")
    R += ["", "### 회복: 평균 브라이어 점수(0~1, 낮을수록 잘 맞힘)", "", "평가 = 자료 안에서 회복했고 BASE·LM·SIM·SIMMIX·TWOPH 가 모두 있는 쌍.", "",
          "| 집단 | e | 층 | 평가 수 | BASE | LM | SIM | SIMMIX |", "|---|---|---|---|---|---|---|---|"]
    for pop in ("US", "INTL"):
        for e in lab.LANDMARKS:
            for s in tuple(_strata(pop)) + ("all",):
                x = mb["m2"][f"{pop}_{e}_{s}"]
                R.append(f"| {'미국' if pop == 'US' else '해외'} | {e} | {'합' if s == 'all' else s} | {x['n']} | "
                         + " | ".join(lab.num(x["score"][m]) for m in ("BASE", "LM", "SIM", "SIMMIX")) + " |")
    R += ["", "### 보정: 평균 예측 회복 확률 vs 실제 비율 (판정 층 평가 쌍)", "",
          "| 집단 | e | 시점 | 쌍 | BASE | LM | SIM | SIMMIX | TWOPH | 실제 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for pop in ("US", "INTL"):
        for e in lab.LANDMARKS:
            for h in lab.HZ:
                c = mb["calib"][f"{pop}_{e}"][str(h)]
                R.append(f"| {'미국' if pop == 'US' else '해외'} | {e} | {h // 252}년 | {c['n']} | "
                         + " | ".join(lab.pct(c[m], 0, False) for m in ("BASE", "LM", "SIM", "SIMMIX")) + f" | **{lab.pct(c['TWOPH'], 0, False)}** | "
                         + f"{lab.pct(c['obs'], 0, False)} |")
    su = res["descriptive"]["simmix_us"]
    R += ["", "### 미국 SIMMIX vs LM (설명용, 판정 아님)", "", "| 항목 | A / B / C / 합친 · p | 볼록성 하한(½ × SIM 대 LM 평균) |", "|---|---|---|",
          f"| 깊이 | {_summ_txt(su['m1'], 'US')} | {lab.sgn(su['m1'].get('bound'))} |",
          f"| 회복 | {_summ_txt(su['m2'], 'US')} | {lab.sgn(su['m2'].get('bound'))} |", "",
          "합친 평균의 부호는 볼록성 때문에 계산 전에 정해져 있으므로 근거로 쓰지 않는다. 시대별 부호는 참고.", ""]
    # 8 TWOPH
    R += ["## 융합 2 — 깊이 → 회복 두 단계 (TWOPH)", "",
          "TWOPH 는 LM_SCALED 와 같은 생각(남은 회복 시간은 전고점까지 거리에 비례)을 쓰되, 랜드마크 뒤 더 빠진 유사 사건만 다르게 다룬다: 그 사건의 남은 회복 시간을 "
          "'바닥까지 걸린 시간' + '바닥에서 전고점까지 오른 시간'으로 나누고, 오른 시간은 바닥 거리로 나눠 척도를 맞춘다. 지금 사건에는 같은 유사 사건의 추가 하락을 "
          "지금 거리에 더한 바닥 거리를 쓴다. 모든 유사 사건이 랜드마크 뒤 더 빠지지 않았고 회복했으면 TWOPH = LM_SCALED 다. 유사 사건은 깊이가 확정된 것만(LM_ANCHOR 와 같음).", "",
          "평균 브라이어 점수(0~1, 낮을수록 잘 맞힘). 평가 쌍은 위 회복 표와 같다(다섯 모델이 모두 있는 쌍).", "",
          "| 집단 | e | 층 | 평가 수 | BASE | LM | TWOPH |", "|---|---|---|---|---|---|---|"]
    for pop in ("US", "INTL"):
        for e in lab.LANDMARKS:
            for s in tuple(_strata(pop)) + ("all",):
                x = mb["m2"][f"{pop}_{e}_{s}"]
                R.append(f"| {'미국' if pop == 'US' else '해외'} | {e} | {'합' if s == 'all' else s} | {x['n']} | "
                         + " | ".join(lab.num(x["score"][m]) for m in ("BASE", "LM")) + f" | **{lab.num(x['score']['TWOPH'])}** |")
    R += ["", "보정표의 TWOPH 열(굵게)은 위 '융합 1' 보정표에 있다.", ""]
    # 9 v1 기준선 대비
    vb = res["descriptive"]["vs_base"]
    R += ["## v1 기준선 대비 (설명용 — 이미 본 자료)", "", "d = BASE 점수 − 모델 점수(양수 = 모델이 더 잘 맞힘). 라벨을 붙이지 않는다.", "",
          "| 모델 | 깊이 미국 (A/B/C/합친 · p) | 깊이 해외 (I1/I2 · 군집 p) | 회복 미국 | 회복 해외 |", "|---|---|---|---|---|"]
    for m in ("LM", "SIM", "SIMMIX", "TWOPH", "LMB", "LM_POOL"):
        x = vb[m]
        m1 = x.get("m1") or {}
        R.append(f"| {m} | {_summ_txt(m1.get('US'), 'US')} | {_summ_txt(m1.get('INTL'), 'INTL')} | {_summ_txt(x['m2']['US'], 'US')} | {_summ_txt(x['m2']['INTL'], 'INTL')} |")
    R += ["", "LMB = LM 과 v1 기준선의 반반 평균(줄이기). LM_POOL = 미국 + 해외 사건으로 학습한 LM.", ""]
    # 10 견고성
    rb = res["robustness"]
    ds = res["descriptive"]
    R += ["## 견고성 (보고만)", "", "라벨을 붙이지 않는다. d = LM 점수 − 변형 점수.", "", "| 항목 | " + " | ".join(KEYS) + " |", "|---|---|---|---|---|"]
    R.append("| (a) 63·126 만 | " + " | ".join(_summ_txt(rb["only_63_126"][k], VERDICT_SPEC[k][1]) for k in KEYS) + " |")
    f3 = lambda x: f"{x['n']} · {lab.sgn(x['mean'])} · {lab.pval(x['p'])}"  # noqa: E731
    for e in lab.LANDMARKS:
        R.append(f"| (b) 랜드마크 {e} 만 (쌍 n · 평균 · p) | " + " | ".join(f3(rb["per_landmark"][k][str(e)]) for k in KEYS) + " |")
    R.append("| (c) 해외 사건 단위 p | " + " | ".join(lab.pval(rb["p_episode_intl"].get(k)) if k in rb["p_episode_intl"] else "—" for k in KEYS) + " |")
    R.append("| (d) 미국 겹침 군집 p | — | — | " + lab.pval(rb["cluster_us_twoph"]) + " | — |")
    R += ["", "| 항목 | 깊이 미국 | 깊이 해외 | 회복 미국 | 회복 해외 |", "|---|---|---|---|---|"]
    for name, key in (("(e) SIM 단독 vs LM", "sim_vs_lm"), ("(f) LMB vs LM", "lmb_vs_lm")):
        x = ds[key]
        R.append(f"| {name} | {_summ_txt(x['m1']['US'], 'US')} | {_summ_txt(x['m1']['INTL'], 'INTL')} | {_summ_txt(x['m2']['US'], 'US')} | {_summ_txt(x['m2']['INTL'], 'INTL')} |")
    pl = ds["lm_pool_vs_lm"]
    R += ["", f"(g) LM_POOL vs LM — 해외: 깊이 {_summ_txt(pl['INTL']['m1'], 'INTL')}, 회복 {_summ_txt(pl['INTL']['m2'], 'INTL')}; "
          f"미국 C: 깊이 {f3(pl['US_C']['m1'])}, 회복 {f3(pl['US_C']['m2'])}; 미국 판정 층에서 LM_POOL = LM(차이 0)인 사건 "
          f"깊이 {pl['n_identical_us']['m1']}/{pl['n_us']['m1']} · 회복 {pl['n_identical_us']['m2']}/{pl['n_us']['m2']}.", ""]
    # 11 재현 확인
    ck = res["checks"]
    R += ["## 재현 확인", ""]
    if "skipped" in ck:
        R += [f"- 건너뜀({ck['skipped']}).", ""]
    else:
        def cline(name, x, what):
            if "skipped" in x:
                return f"- {name}: 건너뜀({x['skipped']})"
            return (f"- {name}: {what} — 비교 줄 {x['n_compared']}, 최대 절대 차 {lab.num(x['max_abs_diff'], 6)}, 차이 > 1e-6 줄 {x['n_diff_gt_1e-6']}, "
                    f"공개 파일에 없는 줄 {x['n_not_in_published']}")
        R += [cline("lm_check", ck["lm_check"], "LM 줄 vs crash-landmark-v1 predictions.csv"),
              cline("base_check", ck["base_check"], "BASE 줄 vs crash-landmark-v1 predictions.csv"),
              cline("sim_check", ck["sim_check"], "미국 랜드마크 SIM 줄 vs crash-simpath-v1 predictions.csv")]
        pc = ck.get("published_check") or {}
        if "skipped" in pc:
            R.append(f"- published_check: 건너뜀({pc['skipped']})")
        else:
            for k, x in pc.items():
                R.append(f"- published_check {k}(LM vs BASE 미국 합친): 이 실행 평균 {lab.sgn(x['mine_mean'])} · p {lab.pval(x['mine_p'])} · n {x['mine_n']} / "
                         f"공개 평균 {lab.sgn(x['pub_mean'])} · p {lab.pval(x['pub_p'])} · n {x['pub_n']}")
        R += ["", "차이는 실패 조건이 아니다(Ken French 가 과거 값을 고치면 작은 차이가 날 수 있음 — 보고만).", ""]
    # 12 검정력과 한계
    R += ["## 검정력과 한계", "", "- **FAIL 은 효과 없음의 증명이 아니다.** 필요 효과가 0.46~0.53 sd 라 중간 크기 이하의 이득은 원리적으로 못 잡는다."]
    R += [f"- {n}" for n in res["notes"]] + [f"- {n}" for n in res["limits"]]
    # 13 사전 기대와 실제
    R += ["", "## 사전 기대와 실제", ""]
    for k in KEYS:
        d = res["detail"][k]
        R.append(f"- {k}: 기대 — {res['expected'][k]} / 실제 — {d['verdict']}" + (" (FAIL_UNDERPOWERED)" if d.get("fail_kind") == "FAIL_UNDERPOWERED" else ""))
    # 14 읽는 법
    R += ["", "## 읽는 법", "",
          "- 핀볼 손실: 최종 깊이 분위수 예측 5개(10·25·50·75·90%)가 실제 최종 깊이에서 빗나간 정도의 평균(전고점 대비 소수). 낮을수록 잘 맞힘.",
          "- 브라이어 점수: 1·2·3·5년 안 회복 확률 예측과 실제(0/1)의 제곱 오차 평균(0~1). 낮을수록 잘 맞힘.",
          "- 회복 확률은 언제나 예측 시점(asof)부터 h 거래일 안, 252거래일 = 1년.",
          "- **이 연구의 d 는 LM 점수 − 변형 점수다**(v1 기준선 대비 표만 BASE 점수 − 모델 점수).",
          "- SIMMIX = LM 과 SIM 의 반반 평균(깊이 = 분위수 평균, 회복 = 확률 평균).",
          "- TWOPH = 바닥까지 + 바닥에서 오르는 시간(바닥 거리에 비례)으로 나눈 회복 확률.",
          "- 랜드마크 e = 발생 뒤 거래일(21 ≈ 1개월, 63 ≈ 3개월, 126 ≈ 6개월), 사건 값 = 있는 랜드마크 d 의 단순 평균.",
          "- 숫자는 과거 사건 분포다. 성과를 약속하지 않는다."]
    return "\n".join(R) + "\n"


# ================================================================ 실행
def run(smoke: bool) -> tuple:
    lab = L()
    data = lab.load_us(smoke)
    intl = lab.load_intl(smoke, required=True)
    return evaluate(data, intl, smoke)


def main(argv=None) -> int:
    return L().run_main(argv, run, report)


if __name__ == "__main__":
    raise SystemExit(main())
