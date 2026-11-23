"""crash-landmark-v1 — 급락 진행 중 예측 갱신(발생 뒤 21·63·126거래일). 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/crash-landmark-v1/run.py --out OUT --checkpoint CK [--smoke]

- 랜드마크 e ∈ (21, 63, 126) 에서 그때까지의 경로(지금 깊이 d · 지금까지 최저 m)로 예측을 다시 세운다.
- 모델 1 LM_ANCHOR: '지금 수준에서 남은 추가 하락' 분포로 다시 닻을 내린 최종 깊이 분위수 vs BASE_TRUNC(v1 진행 중 읽기를 m 으로 자름).
- 모델 2 LM_SCALED: 남은 회복 시간을 '남은 로그 거리'로 늘인 KM vs BASE(v1 생존 조건 KM).
- 판정 2개(LM_M1·LM_M2), 족 15개 공통 α = 0.05/15, 미국 A·B·C 사건 단위(랜드마크는 사건 안에서 평균).
- 해외 3지역 재현(미국 학습)은 보고만. 계산은 수십 초라 체크포인트를 쓰지 않는다(--checkpoint 폴더만 만든다).
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STUDY = "crash-landmark-v1"
RULES_VERSION = "crash-landmark/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
GRID_D = (-0.05, -0.10, -0.15, -0.20, -0.25, -0.30, -0.40)   # 조견표(설명용) 지금 깊이
GRID_DD0 = -0.15
MODEL_NAMES = {"LM_M1": "LM_ANCHOR vs BASE_TRUNC (깊이, 랜드마크)", "LM_M2": "LM_SCALED vs BASE 생존 조건 KM (회복, 랜드마크)"}
EXPECTED = {
    "LM_M1": "BEATS_BASELINE 가능성이 높다(약 55%). 발생 뒤 1~3개월에 이미 반등한 사건(1957·1962·1987·1998·2010·2016·2018·2020 유형)에서 깊은 꼬리 예측을 크게 줄인다. 계속 빠지는 사건에서는 두 예측이 비슷할 것.",
    "LM_M2": "BEATS_BASELINE 가능성이 가장 높다(약 65%). 회복은 남은 거리가 정한다(v1 깊이 구간별 KM). 생존 조건 KM 은 지금 깊이를 모른다.",
}
NOTES = [
    "미국 사건 결과(최종 깊이·회복)는 모두 알려져 있고 시대 C 사건은 crash-cycle-model-v1 보고서에서 이미 보았다. 해외 3지역 재현은 보고만.",
    "사건이 독립이 아니다(1930년대·2000년대 겹침). 판정은 사건 단위, 군집 단위 p 는 견고성 절에 보고만.",
]
LIMITS = [
    "랜드마크 예측은 '발생일 뒤'에만 쓸 수 있다. 발생일 예측(v1 의 벽)은 그대로다.",
    "거리 비례 변환은 근사다(작은 거리에서는 시간이 거리의 제곱에 가깝다 — X_FLOOR 로 일부만 막는다).",
    "126일 랜드마크는 시대 A 에서 학습 사건이 적다.",
    "총수익·명목 기준, 최종 깊이는 3년에서 자른다(v1 과 같음).",
]
# ------------------------------------------------------------------------------------------------------


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


# ---------------------------------------------------------------- 사건 하나의 계산
def episode_calc(train_recs: list, r: dict) -> dict:
    """사건 r(미국 또는 해외)의 랜드마크 0 BASE 와 21·63·126 의 BASE·BASE_V1·LM 예측·점수."""
    lab = L()
    b0 = lab.base0(train_recs, r)
    out: dict[str, Any] = {"r": r, "base0": b0, "lm": {}}
    for e in lab.LANDMARKS:
        st = lab.landmark_state(r, e)
        if st is None:
            continue
        B = lab.landmark_base(train_recs, r, e)
        M = lab.landmark_lm(train_recs, r, e)
        x: dict[str, Any] = {"st": st, "B": B, "M": M, "s1": {}, "s2": {}, "d1": None, "d2": None}
        x["already"] = lab.m1_already(B["_T1"], st["m"])
        x["deep"] = lab.m2_deep(train_recs, st["asof"], st["m"], e)
        if r["depth_settled"]:
            for name, q in (("BASE_V1", B["m1_v1"]), ("BASE_TRUNC", B["m1_trunc"]), ("LM_ANCHOR", M["m1"]), ("M1_ALREADY", x["already"])):
                if q is not None:
                    x["s1"][name] = lab.score_m1(r["FD"], q)
            if "BASE_TRUNC" in x["s1"] and "LM_ANCHOR" in x["s1"]:
                x["d1"] = x["s1"]["BASE_TRUNC"] - x["s1"]["LM_ANCHOR"]
        if r["R"] is not None:
            for name, F in (("BASE", B["m2"]), ("LM_SCALED", M["m2"]), ("M2_DEEP", x["deep"])):
                if F is not None:
                    x["s2"][name] = lab.score_m2(r["R"] - e, F)
            if "BASE" in x["s2"] and "LM_SCALED" in x["s2"]:
                x["d2"] = x["s2"]["BASE"] - x["s2"]["LM_SCALED"]
        out["lm"][e] = x
    d1 = [x["d1"] for x in out["lm"].values() if x["d1"] is not None]
    d2 = [x["d2"] for x in out["lm"].values() if x["d2"] is not None]
    out["d1"] = float(np.mean(d1)) if d1 else None
    out["d2"] = float(np.mean(d2)) if d2 else None
    return out


def pred_rows(calc: dict, judged_strata) -> list:
    lab = L()
    r = calc["r"]
    b0 = calc["base0"]
    rows = [lab.pred_row(STUDY, "BASE", r, 0, r["t0_date"], b0["n_train"], None, b0["m1"], b0["m2"])]
    judged = r["stratum"] in judged_strata
    for e, x in calc["lm"].items():
        B, M, st = x["B"], x["M"], x["st"]
        j1 = int(judged and x["d1"] is not None)
        j2 = int(judged and x["d2"] is not None)
        nb = lab.n_train_of(B["m1_trunc"], B["n1"], B["m2"], B["n2"])
        rows.append(lab.pred_row(STUDY, "BASE", r, e, st["asof"], nb, None, B["m1_trunc"], B["m2"], None, j1, j2))
        rows.append(lab.pred_row(STUDY, "BASE_V1", r, e, st["asof"], lab.n_train_of(B["m1_v1"], B["n1"], B["m2"], B["n2"]),
                                 None, B["m1_v1"], B["m2"]))
        rows.append(lab.pred_row(STUDY, "LM", r, e, st["asof"], lab.n_train_of(M["m1"], M["n1"], M["m2"], M["n2"]),
                                 None, M["m1"], M["m2"], None, j1, j2))
    return rows


# ---------------------------------------------------------------- 보고용 블록
def model_blocks(calcs: list) -> dict:
    lab = L()
    out: dict[str, Any] = {"m1": {}, "m2": {}, "calib": {}}
    for e in lab.LANDMARKS:
        for s in ("A", "B", "C", "all"):
            xs = [c["lm"][e] for c in calcs if e in c["lm"] and (c["r"]["stratum"] == s or (s == "all" and c["r"]["stratum"] in lab.US_STRATA))]
            x1 = [x for x in xs if x["d1"] is not None]
            cov = {}
            for name, key in (("BASE_V1", "m1_v1"), ("BASE_TRUNC", "m1_trunc")):
                hits = [x["B"][key]["0.1"] <= x["_FD"] <= x["B"][key]["0.9"] for x in x1]
                cov[name] = float(np.mean(hits)) if hits else None
            hits = [x["M"]["m1"]["0.1"] <= x["_FD"] <= x["M"]["m1"]["0.9"] for x in x1]
            cov["LM_ANCHOR"] = float(np.mean(hits)) if hits else None
            out["m1"][f"{e}_{s}"] = {"n": len(x1), "score": {m: lab.mean_or_none([x["s1"].get(m) for x in x1])
                                                             for m in ("BASE_V1", "BASE_TRUNC", "LM_ANCHOR", "M1_ALREADY")},
                                     "n_already": sum(1 for x in x1 if "M1_ALREADY" in x["s1"]), "coverage80": cov}
            x2 = [x for x in xs if x["d2"] is not None]
            out["m2"][f"{e}_{s}"] = {"n": len(x2), "score": {m: lab.mean_or_none([x["s2"].get(m) for x in x2])
                                                             for m in ("BASE", "LM_SCALED", "M2_DEEP")},
                                     "n_deep": sum(1 for x in x2 if "M2_DEEP" in x["s2"])}
        x2 = [c["lm"][e] for c in calcs if e in c["lm"] and c["r"]["stratum"] in lab.US_STRATA and c["lm"][e]["d2"] is not None]
        out["calib"][str(e)] = {str(h): {"BASE": lab.mean_or_none([x["B"]["m2"][h] for x in x2]),
                                         "LM_SCALED": lab.mean_or_none([x["M"]["m2"][h] for x in x2]),
                                         "obs": float(np.mean([x["_R"] - e <= h for x in x2])) if x2 else None, "n": len(x2)}
                                for h in lab.HZ}
    return out


def _brief(B: Optional[dict], M: Optional[dict], st: dict, e: int) -> dict:
    return {"e": e, "asof": L().dstr(st["asof"]), "d": st["d"], "m": st["m"],
            "base_m1": None if B is None else B["m1_trunc"], "base_v1_m1": None if B is None else B["m1_v1"],
            "base_m2": None if B is None else B["m2"], "lm_m1": None if M is None else M["m1"], "lm_m2": None if M is None else M["m2"]}


def make_reader(us_recs: list):
    lab = L()

    def reader(ep: dict, d: int, mapping: str) -> dict:
        out: dict[str, Any] = {"landmarks": []}
        for e in lab.LANDMARKS:
            st = lab.landmark_state(ep, e)
            if st is None:
                out["landmarks"].append({"e": e, "note": "이미 회복 또는 자료 끝"})
                continue
            out["landmarks"].append(_brief(lab.landmark_base(us_recs, ep, e), lab.landmark_lm(us_recs, ep, e), st, e))
        if mapping == "inside":
            e = int(d - ep["t0"])
            st = lab.landmark_state(ep, e)
            if st is not None:
                out["snapshot"] = _brief(lab.landmark_base(us_recs, ep, e), lab.landmark_lm(us_recs, ep, e), st, e)
        return out

    return reader


def current_block(ctx: dict, us_recs: list, smoke: bool) -> dict:
    lab = L()
    cur = lab.reading_now(ctx)
    last = ctx["last"]
    D = pd.Timestamp(ctx["idx"][last])
    ep = lab.active_episode(ctx, last)
    if ep is not None:
        e_now = int(last - ep["t0"])
        st = lab.landmark_state(ep, e_now)
        cur["landmark_now"] = None if st is None else _brief(lab.landmark_base(us_recs, ep, e_now), lab.landmark_lm(us_recs, ep, e_now), st, e_now)
    else:
        grid = []
        for e in lab.LANDMARKS:
            for dv in GRID_D:
                m = min(dv, GRID_DD0)
                st = {"asof": D, "d": dv, "m": m, "x": max(math.log(1 / (1 + dv)), lab.X_FLOOR)}
                B = lab._base_from_state(us_recs, st, GRID_DD0, e)
                M = lab._lm_from_state(us_recs, st, e)
                grid.append(_brief(B, M, st, e))
        cur["grid"] = grid
    cur["spy_check"] = lab.spy_check(cur["state"], smoke)
    return cur


# ---------------------------------------------------------------- 평가
def evaluate(data: dict, smoke: bool) -> tuple:
    from core import research_power as rp

    lab = L()
    v1 = lab.v1()
    ctx = lab.us_context(data)
    us = ctx["recs"]
    reasons: dict = {}
    intl = lab.load_intl(smoke, required=False, reasons=reasons)
    intl_ctx = {k: lab.market_context(Lr, k) for k, Lr in intl.items()}

    calcs = [episode_calc(us, r) for r in us]
    for c in calcs:
        for x in c["lm"].values():
            x["_FD"], x["_R"] = c["r"]["FD"], c["r"]["R"]
    icalcs = {k: [episode_calc(us, r) for r in mc["eps"]] for k, mc in intl_ctx.items()}

    rows: list = []
    for c in calcs:
        rows += pred_rows(c, lab.US_STRATA)
    for k, cs in icalcs.items():
        for c in cs:
            rows += pred_rows(c, ())

    dm1 = {s: [c["d1"] for c in calcs if c["r"]["stratum"] == s and c["d1"] is not None] for s in lab.US_STRATA}
    dm2 = {s: [c["d2"] for c in calcs if c["r"]["stratum"] == s and c["d2"] is not None] for s in lab.US_STRATA}
    j1, j2 = lab.judge_us(dm1), lab.judge_us(dm2)
    verdicts = {"LM_M1": j1["verdict"], "LM_M2": j2["verdict"]}

    judged = [c for c in calcs if c["r"]["stratum"] in lab.US_STRATA]
    # 견고성(보고만, judge_* 를 부르지 않는다)
    ab1 = [c["d1"] for c in judged if c["r"]["stratum"] in ("A", "B") and c["d1"] is not None]
    ab2 = [c["d2"] for c in judged if c["r"]["stratum"] in ("A", "B") and c["d2"] is not None]
    cl1 = v1.cluster_p([(c["r"]["t0"], c["r"]["end1"], c["d1"]) for c in judged if c["d1"] is not None])
    cl2 = v1.cluster_p([(c["r"]["t0"], c["r"]["rec"], c["d2"]) for c in judged if c["d2"] is not None])
    per_lm = {}
    for e in lab.LANDMARKS:
        a = [c["lm"][e]["d1"] for c in judged if e in c["lm"] and c["lm"][e]["d1"] is not None]
        b = [c["lm"][e]["d2"] for c in judged if e in c["lm"] and c["lm"][e]["d2"] is not None]
        per_lm[str(e)] = {"m1": {"n": len(a), "mean": lab.mean_or_none(a), "p": lab.signflip(a)},
                          "m2": {"n": len(b), "mean": lab.mean_or_none(b), "p": lab.signflip(b)}}
    intl_rep = {}
    for which in ("d1", "d2"):
        its = [(c["r"]["t0_date"], c[which], c["r"]["id"]) for cs in icalcs.values() for c in cs
               if c[which] is not None and c["r"]["stratum"] in lab.INTL_STRATA]
        cl = lab.clusters(its)
        intl_rep[which] = {"n_episodes": len(its), "n_clusters": len(cl),
                           "mean": {s: lab.mean_or_none([c["value"] for c in cl if c["stratum"] == s]) for s in lab.INTL_STRATA},
                           "p_cluster": lab.signflip([c["value"] for c in cl])}
    vs_already = []
    vs_deep = []
    for c in judged:
        for x in c["lm"].values():
            if "M1_ALREADY" in x["s1"] and "LM_ANCHOR" in x["s1"]:
                vs_already.append(x["s1"]["M1_ALREADY"] - x["s1"]["LM_ANCHOR"])
            if "M2_DEEP" in x["s2"] and "LM_SCALED" in x["s2"]:
                vs_deep.append(x["s2"]["M2_DEEP"] - x["s2"]["LM_SCALED"])
    robust = {"ab_only": {"LM_M1": {"n": len(ab1), "mean": lab.mean_or_none(ab1), "p": lab.signflip(ab1)},
                          "LM_M2": {"n": len(ab2), "mean": lab.mean_or_none(ab2), "p": lab.signflip(ab2)}},
              "cluster_us": {"LM_M1": cl1, "LM_M2": cl2}, "per_landmark": per_lm, "intl": intl_rep,
              "vs_already": {"n": len(vs_already), "mean": lab.mean_or_none(vs_already), "p": lab.signflip(vs_already)},
              "vs_deep": {"n": len(vs_deep), "mean": lab.mean_or_none(vs_deep), "p": lab.signflip(vs_deep)}}

    events = lab.events_rows(ctx, make_reader(us))
    current = current_block(ctx, us, smoke)
    now = lab.now_line(current)
    summary = {"LM_M1 랜드마크 깊이": lab.summary_entry(j1), "LM_M2 랜드마크 회복": lab.summary_entry(j2),
               f"지금(Ken French {current['as_of']})": now}
    idx = ctx["idx"]
    episodes = []
    for c in calcs + [c for cs in icalcs.values() for c in cs]:
        r = c["r"]
        episodes.append({"id": r["id"], "t0": lab.dstr(r["t0_date"]), "era": r["stratum"], "dd0": r["dd0"], "FD": r["FD"], "R": r["R"],
                         "d1": c["d1"], "d2": c["d2"],
                         "landmarks": {str(e): {"d": x["st"]["d"], "m": x["st"]["m"], "s1": x["s1"], "s2": x["s2"],
                                                "d1": x["d1"], "d2": x["d2"]} for e, x in c["lm"].items()}})
    base_preds = {lab.dstr(c["r"]["t0_date"]): (c["base0"]["m1"], c["base0"]["m2"]) for c in calcs}
    res = {
        "study": STUDY, "lab_version": lab.LAB_VERSION, "rules": RULES_VERSION, "judge_version": lab.JUDGE_VERSION, "smoke": bool(smoke),
        "data": {"source": data["source"], "first_date": str(idx[0].date()), "last_date": str(idx[-1].date()), "n_days": int(len(idx)),
                 "intl": {k: {"first_date": str(v.index[0].date()), "last_date": str(v.index[-1].date()), "n_episodes": len(intl_ctx[k]["eps"])}
                          for k, v in intl.items()},
                 "intl_missing": reasons, "network_extras": {"spy": bool(current["spy_check"].get("available"))}},
        "constants": dict(lab.lab_constants(), GRID_D=list(GRID_D), GRID_DD0=GRID_DD0),
        "family": lab.family_block(STUDY),
        "power": rp.power_report(lab.YEARS_US, lab.K_FAMILY),
        "power_episode": {"LM_M1": lab.power_episode(j1["n"]["pooled"]), "LM_M2": lab.power_episode(j2["n"]["pooled"])},
        "verdicts": verdicts, "summary": summary,
        "detail": {"LM_M1": j1, "LM_M2": j2},
        "models": model_blocks(calcs), "episodes": episodes, "events": events, "current": current, "robustness": robust,
        "v1_check": lab.v1_check(us, base_preds, smoke), "expected": EXPECTED, "notes": NOTES,
    }
    return res, rows


# ---------------------------------------------------------------- 보고서
def _lm_line(lab, b: dict) -> str:
    return (f"| {b['e']} | {b['asof']} | {lab.pct(b['d'])} | {lab.pct(b['m'])} | {lab.q3(b['base_m1'])} | {lab.q3(b['lm_m1'])} | "
            f"{lab.r3(b['base_m2'])} | {lab.r3(b['lm_m2'])} |")


LM_HEAD = ["| e(거래일) | 기준일 | 지금 깊이 d | 지금까지 최저 m | BASE_TRUNC 깊이 10/50/90% | LM_ANCHOR 깊이 10/50/90% | BASE 회복 1/2/5년 | LM_SCALED 회복 1/2/5년 |",
           "|---|---|---|---|---|---|---|---|"]


def report(res: dict, smoke: bool) -> str:
    lab = L()
    Lr = lab.report_head(res, "급락 진행 중 예측 갱신 — 발생 뒤 21·63·126거래일", smoke, MODEL_NAMES)
    Lr += ["## 이 연구가 묻는 것", "",
           "- 급락 발생일(총수익 지수가 1년 고점보다 15% 아래로 처음 내려간 날)에는 최종 깊이를 모른다. 그러나 1·3·6개월(21·63·126거래일) 뒤에는 "
           "'지금 깊이'와 '지금까지 최저'가 드러난다.",
           "- 질문: 그때까지의 경로로 예측을 다시 세우면(LM), v1 의 진행 중 읽기(발생일 분포를 지금까지 최저로 자른 깊이, 생존 조건 KM 회복)보다 "
           "최종 깊이와 남은 회복 기간을 더 잘 맞히나.",
           "- LM_ANCHOR = 과거 사건이 같은 랜드마크에서 '그 뒤 더 빠진 폭'의 분포를 지금 수준에 붙인 것. LM_SCALED = 과거 사건의 남은 회복 시간을 "
           "'전고점까지 남은 로그 거리'로 나눠 척도를 맞춘 KM.", ""]
    cur = res["current"]
    Lr += ["## 지금 읽기 (설명용 — 추천 아님)", "", lab.READING_HEADER, ""] + lab.reading_state_lines(cur)
    if cur.get("landmark_now"):
        Lr += ["진행 중 사건의 오늘 랜드마크 읽기(e = 오늘 − 발생일):", ""] + LM_HEAD + [_lm_line(lab, cur["landmark_now"]), ""]
    elif cur.get("landmark_now") is None and cur["state"] == "in_episode":
        Lr += ["진행 중 사건이지만 오늘 랜드마크 읽기를 만들 수 없다(자료 부족).", ""]
    if cur.get("grid"):
        Lr += ["**조견표(설명용)** — 만약 급락(발생일 깊이 −15%)이 났고 e 거래일 뒤 지금 깊이가 d 라면(지금까지 최저 m = min(d, −15%)). "
               f"학습은 {cur['as_of']} 까지 확정된 사건. 표시용이고 판정과 무관하다.", ""] + LM_HEAD
        Lr += [_lm_line(lab, b) for b in cur["grid"]] + [""]
    Lr += [lab.spy_line(cur.get("spy_check") or {}), ""]
    # 7개 사건
    Lr += ["## 사용자가 든 7개 사건", ""] + lab.events_note_lines(res["events"])
    Lr += ["### 랜드마크 읽기 (그 시점까지 확정된 사건만으로 학습)", ""]
    for e in res["events"]:
        st = e.get("study")
        if not st:
            continue
        Lr += [f"**{e['label']}** — 발생일 {e['episode_t0']}", ""] + LM_HEAD
        for b in st["landmarks"]:
            Lr.append(_lm_line(lab, b) if "asof" in b else f"| {b['e']} | — | — | — | {b['note']} | | | |")
        if st.get("snapshot"):
            Lr.append(_lm_line(lab, st["snapshot"]) + " ← 기준일 스냅숏(판정 아님)")
        Lr.append("")
    # 모델 1·2
    mb = res["models"]
    Lr += ["## 모델 1 — 랜드마크 깊이", "", "평균 핀볼 손실(전고점 대비 %p, 낮을수록 잘 맞힘)과 실제가 10~90% 구간에 든 비율(목표 80%). 평가 = 깊이 확정이고 BASE_TRUNC·LM_ANCHOR 둘 다 있는 (사건, 랜드마크).", "",
           "| e | 층 | 평가 수 | BASE_V1 | BASE_TRUNC | LM_ANCHOR | M1_ALREADY (수) | 80% 포함 BASE_V1 / BASE_TRUNC / LM |", "|---|---|---|---|---|---|---|---|"]
    f100 = lambda v: "—" if lab.fin(v) is None else f"{v * 100:.2f}"  # noqa: E731
    for e in lab.LANDMARKS:
        for s in ("A", "B", "C", "all"):
            x = mb["m1"][f"{e}_{s}"]
            sc, cv = x["score"], x["coverage80"]
            Lr.append(f"| {e} | {s if s != 'all' else 'A+B+C'} | {x['n']} | {f100(sc['BASE_V1'])} | {f100(sc['BASE_TRUNC'])} | {f100(sc['LM_ANCHOR'])} | "
                      f"{f100(sc['M1_ALREADY'])} ({x['n_already']}) | {lab.pct(cv['BASE_V1'], 0, False)} / {lab.pct(cv['BASE_TRUNC'], 0, False)} / {lab.pct(cv['LM_ANCHOR'], 0, False)} |")
    Lr += ["", "## 모델 2 — 랜드마크 회복", "", "평균 브라이어 점수(0~1, 낮을수록 잘 맞힘). 평가 = 자료 안에서 회복했고 BASE·LM_SCALED 둘 다 있는 (사건, 랜드마크).", "",
           "| e | 층 | 평가 수 | BASE | LM_SCALED | M2_DEEP (수) |", "|---|---|---|---|---|---|"]
    for e in lab.LANDMARKS:
        for s in ("A", "B", "C", "all"):
            x = mb["m2"][f"{e}_{s}"]
            Lr.append(f"| {e} | {s if s != 'all' else 'A+B+C'} | {x['n']} | {lab.num(x['score']['BASE'])} | {lab.num(x['score']['LM_SCALED'])} | "
                      f"{lab.num(x['score']['M2_DEEP'])} ({x['n_deep']}) |")
    Lr += ["", "### 보정: 평균 예측 회복 확률 vs 실제 비율 (A+B+C 평가 쌍)", "", "| e | 시점 | 쌍 | BASE 평균 | LM_SCALED 평균 | 실제 |", "|---|---|---|---|---|---|"]
    for e in lab.LANDMARKS:
        for h in lab.HZ:
            c = mb["calib"][str(e)][str(h)]
            Lr.append(f"| {e} | {h // 252}년 | {c['n']} | {lab.pct(c['BASE'], 0, False)} | {lab.pct(c['LM_SCALED'], 0, False)} | {lab.pct(c['obs'], 0, False)} |")
    # 견고성
    rb = res["robustness"]
    Lr += ["", "## 견고성 (보고만)", "", "라벨을 붙이지 않는다. 값은 평균 d 와 한쪽 부호 뒤집기 p.", "",
           "| 항목 | LM_M1 (n · 평균 d · p) | LM_M2 (n · 평균 d · p) |", "|---|---|---|"]
    f3 = lambda x: f"{x['n']} · {lab.sgn(x['mean'])} · {lab.pval(x['p'])}"  # noqa: E731
    Lr.append(f"| (a) A+B 만(v1 방식) | {f3(rb['ab_only']['LM_M1'])} | {f3(rb['ab_only']['LM_M2'])} |")
    Lr.append(f"| (b) 미국 겹침 군집 p | {lab.pval(rb['cluster_us']['LM_M1'])} | {lab.pval(rb['cluster_us']['LM_M2'])} |")
    for e in lab.LANDMARKS:
        x = rb["per_landmark"][str(e)]
        Lr.append(f"| (c) 랜드마크 {e} 만 (A+B+C 쌍) | {f3(x['m1'])} | {f3(x['m2'])} |")
    it = rb["intl"]
    Lr.append(f"| (d) 해외 3지역 재현(미국 학습, 군집) | 사건 {it['d1']['n_episodes']} · 군집 {it['d1']['n_clusters']} · I1 {lab.sgn(it['d1']['mean']['I1'])} / "
              f"I2 {lab.sgn(it['d1']['mean']['I2'])} · p {lab.pval(it['d1']['p_cluster'])} | 사건 {it['d2']['n_episodes']} · 군집 {it['d2']['n_clusters']} · "
              f"I1 {lab.sgn(it['d2']['mean']['I1'])} / I2 {lab.sgn(it['d2']['mean']['I2'])} · p {lab.pval(it['d2']['p_cluster'])} |")
    Lr.append(f"| (e) 설명값 대비(M1_ALREADY − LM_ANCHOR / M2_DEEP − LM_SCALED, 쌍 단위) | {f3(rb['vs_already'])} | {f3(rb['vs_deep'])} |")
    miss = res["data"].get("intl_missing") or {}
    if miss:
        Lr += ["", "해외 자료 없음: " + ", ".join(f"{k}({v})" for k, v in miss.items())]
    vc = res["v1_check"]
    Lr += ["", "v1 기준선 재현 확인(미국 랜드마크 0 BASE vs v1 결과 파일): "
           + (vc["skipped"] if "skipped" in vc else f"사건 {vc['n']} · 최대 차이 깊이 {lab.num(vc['max_abs_diff_m1'], 6)} · 회복 {lab.num(vc['max_abs_diff_m2'], 6)}"), ""]
    Lr += lab.report_tail(res, LIMITS, ["- 랜드마크 e = 발생일 뒤 거래일(21 ≈ 1개월, 63 ≈ 3개월, 126 ≈ 6개월). 사건 값 = 있는 랜드마크 d 의 단순 평균.",
                                        "- BASE_TRUNC 는 자르기 이득을 기준선에 미리 준 것이라 판정은 '다시 닻 내리기 + 생존 선택'의 효과만 본다. BASE_V1 은 자르지 않은 v1 그대로(보고만)."])
    return "\n".join(Lr) + "\n"


# ---------------------------------------------------------------- 실행
def run(smoke: bool) -> tuple:
    return evaluate(L().load_us(smoke), smoke)


def main(argv=None) -> int:
    return L().run_main(argv, run, report)


if __name__ == "__main__":
    raise SystemExit(main())
