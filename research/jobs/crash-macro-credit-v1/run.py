"""crash-macro-credit-v1 — 금리·신용 여건(H-022)으로 가른 '긴 약세장 확률'. 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/crash-macro-credit-v1/run.py --out OUT --checkpoint CK [--smoke]

- 특징(발생일 m−1 달): RATECHG_M = 12·(RF[m−1] − RF[m−13])(French 월별 RF), TERM = AAA[m−1]/100 − 12·RF[m−1], DEF = (BAA − AAA)[m−1]/100(무디스 스냅숏).
- 능형 로지스틱(λ = 4) '긴 약세장 확률' → 과거 사건 두 갈래 재가중(MACRO) vs v1 기준선(모델 1 깊이·모델 2 회복).
- 모델 3: 발생일에 한 번 즉시 투입 비율 a = 1 − p 를 정한 분할(SPLIT_P) vs 같은 시점 기준 확률로 정한 고정 분할(SPLIT_P0, a0 = 1 − π), 3년 로그 계좌 차이.
- 판정 3개(MAC_M1·MAC_M2·MAC_M3), 족 15개 공통 α = 0.05/15, 미국 A·B·C 사건 단위. 계산은 수십 초라 체크포인트를 쓰지 않는다.
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

STUDY = "crash-macro-credit-v1"
RULES_VERSION = "crash-macro-credit/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
FEATS = ("RATECHG_M", "TERM", "DEF")
FEAT_LABELS = {"RATECHG_M": "단기금리 1년 변화(월별 RF, 연율)", "TERM": "장단기차(AAA − 1개월 국채, 연율)", "DEF": "신용 스프레드(BAA − AAA)"}
SINGLE_CODES = {"RATECHG_M": "MACRO_RATECHG", "TERM": "MACRO_TERM", "DEF": "MACRO_DEF"}
M3_H = 756
NOW_DD0 = -0.15
MODEL_NAMES = {"MAC_M1": "MACRO vs BASE (깊이, 발생일)", "MAC_M2": "MACRO vs BASE (회복, 발생일)",
               "MAC_M3": "SPLIT_P vs SPLIT_P0 (3년 로그 계좌 차이 D3)"}
EXPECTED = {
    "MAC_M1": "FAIL 가능성이 높다(통과 약 10%). 신용·금리 수준은 시대마다 크게 달라(1930년대 높은 DEF, 1950~60년대 낮음) 사건 20개 남짓으로는 갈래를 잘 못 가를 것.",
    "MAC_M2": "FAIL 가능성이 높다(통과 약 12%). 긴 약세장(1929·1937·1973·2000·2008)의 공통 거시 신호가 일정하지 않다.",
    "MAC_M3": "FAIL 가능성이 높다(통과 약 8%). 분류 실력이 약하면 SPLIT_P 는 고정 분할과 비슷해지고 차이는 잡음.",
}
NOTES = [
    "시대 C 사건(2008~2022)은 crash-cycle-model-v1 보고서에서 이미 보았다. 금리·신용 특징 값 자체는 이 저장소 급락 연구에서 처음 쓴다.",
    "분류기 미적합 사건(라벨 있는 학습 6개 미만·한 갈래뿐·미수렴)은 세 판정 모두에서 빠진다(n_unfit). 기준선과 같은 값을 0 차이로 넣지 않는다.",
]
LIMITS = [
    "월별 자료라 발생일 직전 몇 주의 급변을 못 본다.",
    "무디스 Baa 는 투자 등급 — 하이일드 스프레드가 아니다(하이일드는 FRED 에서 최근 3년만 제공).",
    "TERM 의 장기 금리는 국채가 아니라 Aaa 회사채.",
    "사건 20개 남짓에 특징 3개 — 능형으로 줄여도 잡음이 크다.",
    "모델 3 은 고정 분할 대비만 판정(한 번에 넣기 대비는 보고만).",
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


# ---------------------------------------------------------------- 계산
def feature_map(us: list, rf_m: pd.Series, moodys: pd.DataFrame) -> tuple:
    lab = L()
    feats = {r["id"]: lab.macro_features(r["t0_date"], rf_m, moodys) for r in us}
    xmap = {k: [v[f] for f in FEATS] for k, v in feats.items()}
    return feats, xmap


def kernel_pred(us: list, r: dict, feats: dict) -> dict:
    """KERNEL_RATECHG_M(보고만): v1 커널 가중 + v1 BASE 절차에 RATECHG_M 을 넣은 것."""
    lab = L()
    v1 = lab.v1()
    D = r["t0_date"]
    T1 = lab.m1_pool(us, D)
    out = {"m1": None, "m2": None}
    if len(T1) >= lab.MIN_TRAIN:
        y = np.array([j["y"] for j in T1], dtype=float)
        w = v1.kernel_weights([feats[j["id"]]["RATECHG_M"] for j in T1], feats[r["id"]]["RATECHG_M"])
        out["m1"] = v1._fd_quants(y, np.ones(len(y)) if w is None else w, r["dd0"])
    rows, times, events = lab.m2_pool(us, D)
    if len(rows) >= lab.MIN_TRAIN and int(np.sum(events)) >= lab.MIN_EVENTS_M2:
        w = v1.kernel_weights([feats[j["id"]]["RATECHG_M"] for j in rows], feats[r["id"]]["RATECHG_M"])
        tau, S = v1.wkm(times, events, w)
        out["m2"] = v1._cond_F(tau, S, 0)
    return out


def m3_calc(ctx: dict, r: dict, ts: dict) -> Optional[dict]:
    """발생일 다음 날부터 756일. SPLIT_P(a = 1 − p) vs SPLIT_P0(a0 = 1 − π), 보고용 LUMP·HALF6 대비."""
    lab = L()
    v1 = lab.v1()
    if ts["unfit"] or r["t0"] + 1 + M3_H > ctx["last"]:
        return None
    Lv, rfv, e = ctx["Lv"], ctx["rfv"], r["t0"] + 1
    a, a0 = 1 - ts["p_lb"], 1 - ts["pi"]
    W = {"SPLIT_P": v1.schedule_path(Lv, rfv, e, M3_H, lab.split_tranches(a)),
         "SPLIT_P0": v1.schedule_path(Lv, rfv, e, M3_H, lab.split_tranches(a0)),
         "HALF6": v1.schedule_path(Lv, rfv, e, M3_H, v1.SCHEDULES["HALF6"]),
         "LUMP": v1.schedule_path(Lv, rfv, e, M3_H, v1.SCHEDULES["LUMP"])}
    lw = float(W["LUMP"].min() - 1)
    out = {"a": a, "a0": a0, "D3": float(math.log(W["SPLIT_P"][M3_H]) - math.log(W["SPLIT_P0"][M3_H])), "vs_lump": {}}
    for k in ("SPLIT_P", "SPLIT_P0", "HALF6"):
        out["vs_lump"][k] = {"D": float(math.log(W[k][M3_H]) - math.log(W["LUMP"][M3_H])), "G": float((W[k].min() - 1) - lw)}
    return out


def episode_scores(r: dict, ts: dict, extra: dict) -> dict:
    """사건 r 의 BASE·MACRO 등 점수와 쌍 차이(미적합이면 MACRO 쌍 없음)."""
    lab = L()
    b = ts["base"]
    s1, s2 = {}, {}
    preds = {"BASE": (b["m1"], b["m2"])}
    if not ts["unfit"]:
        preds["MACRO"] = (ts["m1"], ts["m2"])
    preds.update(extra)
    for name, (q, F) in preds.items():
        if r["depth_settled"] and q is not None:
            s1[name] = lab.score_m1(r["FD"], q)
        if r["R"] is not None and F is not None:
            s2[name] = lab.score_m2(r["R"], F)
    d1 = s1["BASE"] - s1["MACRO"] if ("BASE" in s1 and "MACRO" in s1) else None
    d2 = s2["BASE"] - s2["MACRO"] if ("BASE" in s2 and "MACRO" in s2) else None
    return {"s1": s1, "s2": s2, "d1": d1, "d2": d2}


def make_reader(per: dict):
    lab = L()

    def reader(ep: dict, d: int, mapping: str) -> dict:
        x = per[ep["id"]]
        ts = x["ts"]
        return {"features": x["feat"], "p_lb": ts["p_lb"], "pi": ts["pi"], "unfit": ts["unfit"],
                "base_m1": ts["base"]["m1"], "base_m2": ts["base"]["m2"], "m1": ts["m1"], "m2": ts["m2"],
                "a_now": None if ts["unfit"] else 1 - ts["p_lb"], "a0": None if ts["unfit"] else 1 - ts["pi"],
                "note": "발생일 값(그 사건 발생일 종가까지의 정보)" if mapping != "trigger" else ""}

    return reader


def current_block(ctx: dict, us: list, xmap: dict, rf_m, moodys, smoke: bool) -> dict:
    lab = L()
    cur = lab.reading_now(ctx)
    last = ctx["last"]
    D = pd.Timestamp(ctx["idx"][last])
    ep = lab.active_episode(ctx, last)
    if ep is not None:
        x_now, dd0, e_days = xmap[ep["id"]], ep["dd0"], int(last - ep["t0"])
        cur["basis"] = f"진행 중 사건({lab.dstr(ep['t0_date'])}) 발생일의 특징·깊이, 학습은 {lab.dstr(D)} 까지, 회복은 경과 {e_days}일 조건부"
        cur["features_now"] = dict(zip(FEATS, x_now))
    else:
        f = lab.macro_features(D, rf_m, moodys)
        x_now, dd0, e_days = [f[k] for k in FEATS], NOW_DD0, 0
        cur["basis"] = f"만약 오늘({lab.dstr(D)})이 발생일이라면(발생일 깊이 −15%, 특징은 {pd.Period(D, 'M') - 1} 달 값)"
        cur["features_now"] = f
    tn = lab.two_state_now(us, D, xmap, x_now, dd0, e_days)
    tn["a_now"] = None if tn["p_lb"] is None else 1 - tn["p_lb"]
    cur["macro_now"] = tn
    cur["spy_check"] = lab.spy_check(cur["state"], smoke)
    return cur


# ---------------------------------------------------------------- 평가
def evaluate(data: dict, smoke: bool) -> tuple:
    from core import research_power as rp

    lab = L()
    v1 = lab.v1()
    rf_m, moodys = data["rf_m"], data["moodys"]
    ctx = lab.us_context(data)
    us = ctx["recs"]
    idx, last = ctx["idx"], ctx["last"]
    D_last = pd.Timestamp(idx[last])
    feats, xmap = feature_map(us, rf_m, moodys)

    per: dict[str, Any] = {}
    for r in us:
        ts = lab.two_state_episode(us, r, xmap)
        singles = {f: lab.two_state_episode(us, r, xmap, cols=[i]) for i, f in enumerate(FEATS)}
        kern = kernel_pred(us, r, feats)
        extra = {"KERNEL_RATECHG_M": (kern["m1"], kern["m2"])}
        for f, s in singles.items():
            if not s["unfit"]:
                extra[SINGLE_CODES[f]] = (s["m1"], s["m2"])
        sc = episode_scores(r, ts, extra)
        per[r["id"]] = {"r": r, "feat": feats[r["id"]], "ts": ts, "singles": singles, "kern": kern, "sc": sc, "m3": m3_calc(ctx, r, ts)}

    judged = [x for x in per.values() if x["r"]["stratum"] in lab.US_STRATA]
    dm1 = {s: [x["sc"]["d1"] for x in judged if x["r"]["stratum"] == s and x["sc"]["d1"] is not None] for s in lab.US_STRATA}
    dm2 = {s: [x["sc"]["d2"] for x in judged if x["r"]["stratum"] == s and x["sc"]["d2"] is not None] for s in lab.US_STRATA}
    dm3 = {s: [x["m3"]["D3"] for x in judged if x["r"]["stratum"] == s and x["m3"] is not None] for s in lab.US_STRATA}
    j1, j2 = lab.judge_us(dm1), lab.judge_us(dm2)
    j3 = lab.judge_us(dm3, "BEATS_FIXED_SPLIT")
    n_unfit = sum(1 for x in judged if x["ts"]["unfit"])
    for j in (j1, j2, j3):
        j["n_unfit"] = n_unfit
    verdicts = {"MAC_M1": j1["verdict"], "MAC_M2": j2["verdict"], "MAC_M3": j3["verdict"]}

    rows: list = []
    for x in per.values():
        r, ts, sc = x["r"], x["ts"], x["sc"]
        jj = r["stratum"] in lab.US_STRATA
        j1f, j2f = int(jj and sc["d1"] is not None), int(jj and sc["d2"] is not None)
        b = ts["base"]
        rows.append(lab.pred_row(STUDY, "BASE", r, 0, r["t0_date"], b["n_train"], None, b["m1"], b["m2"], None, j1f, j2f))
        if not ts["unfit"]:
            rows.append(lab.pred_row(STUDY, "MACRO", r, 0, r["t0_date"], lab.n_train_of(ts["m1"], ts["n1"], ts["m2"], ts["n2"]),
                                     ts["p_lb"], ts["m1"], ts["m2"], None, j1f, j2f))
            rows.append(lab.pred_row(STUDY, "SPLIT_P", r, 0, r["t0_date"], ts["n_cls"], ts["p_lb"], None, None, 1 - ts["p_lb"]))
            rows.append(lab.pred_row(STUDY, "SPLIT_P0", r, 0, r["t0_date"], ts["n_cls"], ts["p_lb"], None, None, 1 - ts["pi"]))
        for f, s in x["singles"].items():
            if not s["unfit"]:
                rows.append(lab.pred_row(STUDY, SINGLE_CODES[f], r, 0, r["t0_date"], lab.n_train_of(s["m1"], s["n1"], s["m2"], s["n2"]),
                                         s["p_lb"], s["m1"], s["m2"]))
        k = x["kern"]
        if k["m1"] is not None or k["m2"] is not None:
            rows.append(lab.pred_row(STUDY, "KERNEL_RATECHG_M", r, 0, r["t0_date"], b["n_train"], None, k["m1"], k["m2"]))

    # 보고만
    def pair_stats(code: str, which: str) -> dict:
        key = "s1" if which == "m1" else "s2"
        vals = [x["sc"][key]["BASE"] - x["sc"][key][code] for x in judged if "BASE" in x["sc"][key] and code in x["sc"][key]]
        return {"n": len(vals), "mean": lab.mean_or_none(vals), "p": lab.signflip(vals)}

    singles_rep = {SINGLE_CODES[f]: {"m1": pair_stats(SINGLE_CODES[f], "m1"), "m2": pair_stats(SINGLE_CODES[f], "m2")} for f in FEATS}
    kern_rep = {"m1": pair_stats("KERNEL_RATECHG_M", "m1"), "m2": pair_stats("KERNEL_RATECHG_M", "m2")}
    skill = lab.classification_skill([(lab.lb_label(x["r"], D_last), x["ts"]["p_lb"], x["ts"]["pi"]) for x in judged if not x["ts"]["unfit"]])
    C_last, y_last = lab.cls_set(us, D_last)
    fit_last = lab.fit_ridge_logit(np.array([xmap[j["id"]] for j in C_last], dtype=float).reshape(len(C_last), len(FEATS)), y_last)
    fits = [x["ts"]["fit"] for x in judged if not x["ts"]["unfit"]]
    slopes = {"last_fit": {f: (float(fit_last["beta"][i]) if fit_last["keep"][i] else None) for i, f in enumerate(FEATS)},
              "last_fit_n": len(C_last), "last_fit_ok": lab.fit_ok(fit_last),
              "share_positive": {f: (float(np.mean([ft["beta"][i] > 0 for ft in fits])) if fits else None) for i, f in enumerate(FEATS)},
              "n_fits": len(fits)}
    m3_by = {}
    for s in ("A", "B", "C", "all"):
        xs = [x for x in judged if x["m3"] is not None and (s == "all" or x["r"]["stratum"] == s)]
        D3 = [x["m3"]["D3"] for x in xs]
        m3_by[s] = {"n": len(xs), "D3_mean": lab.mean_or_none(D3), "regret_share": float(np.mean([d < 0 for d in D3])) if D3 else None,
                    "a_mean": lab.mean_or_none([x["m3"]["a"] for x in xs]), "a0_mean": lab.mean_or_none([x["m3"]["a0"] for x in xs]),
                    "vs_lump": {k: {"D_mean": lab.mean_or_none([x["m3"]["vs_lump"][k]["D"] for x in xs]),
                                    "G_mean": lab.mean_or_none([x["m3"]["vs_lump"][k]["G"] for x in xs]),
                                    "regret_share": float(np.mean([x["m3"]["vs_lump"][k]["D"] < 0 for x in xs])) if xs else None}
                                for k in ("SPLIT_P", "SPLIT_P0", "HALF6")}}
    m_by = {}
    for s in ("A", "B", "C", "all"):
        xs = [x for x in judged if s == "all" or x["r"]["stratum"] == s]
        e1 = [x for x in xs if x["sc"]["d1"] is not None]
        e2 = [x for x in xs if x["sc"]["d2"] is not None]
        m_by[s] = {"n1": len(e1), "n2": len(e2), "n_unfit": sum(1 for x in xs if x["ts"]["unfit"]),
                   "m1": {m: lab.mean_or_none([x["sc"]["s1"].get(m) for x in e1]) for m in ("BASE", "MACRO")},
                   "m2": {m: lab.mean_or_none([x["sc"]["s2"].get(m) for x in e2]) for m in ("BASE", "MACRO")}}
    e2 = [x for x in judged if x["sc"]["d2"] is not None]
    calib = {str(h): {"BASE": lab.mean_or_none([x["ts"]["base"]["m2"][h] for x in e2]), "MACRO": lab.mean_or_none([x["ts"]["m2"][h] for x in e2]),
                      "obs": float(np.mean([x["r"]["R"] <= h for x in e2])) if e2 else None, "n": len(e2)} for h in lab.HZ}

    ab = lambda dm: [v for s in ("A", "B") for v in dm[s]]  # noqa: E731
    robust = {"ab_only": {k: {"n": len(ab(dm)), "mean": lab.mean_or_none(ab(dm)), "p": lab.signflip(ab(dm))}
                          for k, dm in (("MAC_M1", dm1), ("MAC_M2", dm2), ("MAC_M3", dm3))},
              "cluster_us": {"MAC_M1": v1.cluster_p([(x["r"]["t0"], x["r"]["end1"], x["sc"]["d1"]) for x in judged if x["sc"]["d1"] is not None]),
                             "MAC_M2": v1.cluster_p([(x["r"]["t0"], x["r"]["rec"], x["sc"]["d2"]) for x in judged if x["sc"]["d2"] is not None]),
                             "MAC_M3": v1.cluster_p([(x["r"]["t0"], x["r"]["t0"] + 1 + M3_H, x["m3"]["D3"]) for x in judged if x["m3"] is not None])},
              "singles": singles_rep, "kernel_ratechg_m": kern_rep}

    events = lab.events_rows(ctx, make_reader(per))
    current = current_block(ctx, us, xmap, rf_m, moodys, smoke)
    summary = {"MAC_M1 금리·신용 깊이": lab.summary_entry(j1), "MAC_M2 금리·신용 회복": lab.summary_entry(j2),
               "MAC_M3 확률 분할 대 고정 분할": lab.summary_entry(j3), f"지금(Ken French {current['as_of']})": lab.now_line(current)}
    episodes = []
    for x in per.values():
        r, ts = x["r"], x["ts"]
        episodes.append({"id": r["id"], "t0": lab.dstr(r["t0_date"]), "era": r["stratum"], "dd0": r["dd0"], "FD": r["FD"], "R": r["R"],
                         "features": x["feat"], "p_lb": ts["p_lb"], "pi": ts["pi"], "unfit": ts["unfit"], "n_cls": ts["n_cls"],
                         "s1": x["sc"]["s1"], "s2": x["sc"]["s2"], "d1": x["sc"]["d1"], "d2": x["sc"]["d2"],
                         "D3": None if x["m3"] is None else x["m3"]["D3"], "a": None if x["m3"] is None else x["m3"]["a"]})
    base_preds = {lab.dstr(x["r"]["t0_date"]): (x["ts"]["base"]["m1"], x["ts"]["base"]["m2"]) for x in per.values()}
    res = {
        "study": STUDY, "lab_version": lab.LAB_VERSION, "rules": RULES_VERSION, "judge_version": lab.JUDGE_VERSION, "smoke": bool(smoke),
        "data": {"source": data["source"], "first_date": str(idx[0].date()), "last_date": str(idx[-1].date()), "n_days": int(len(idx)),
                 "rf_monthly": {"source": "synthetic (smoke)" if smoke else "Ken French ff3_monthly RF", "first": str(rf_m.index[0]), "last": str(rf_m.index[-1])},
                 "moodys": {"source": "synthetic (smoke)" if smoke else "research/jobs/crash-cycle-lab/data/moodys_monthly.csv (FRED AAA·BAA 스냅숏)",
                            "first": str(moodys.index[0]), "last": str(moodys.index[-1])},
                 "network_extras": {"spy": bool(current["spy_check"].get("available"))}},
        "constants": dict(lab.lab_constants(), FEATS=list(FEATS), M3_H=M3_H, NOW_DD0=NOW_DD0),
        "family": lab.family_block(STUDY),
        "power": rp.power_report(lab.YEARS_US, lab.K_FAMILY),
        "power_episode": {"MAC_M1": lab.power_episode(j1["n"]["pooled"]), "MAC_M2": lab.power_episode(j2["n"]["pooled"]),
                          "MAC_M3": lab.power_episode(j3["n"]["pooled"])},
        "verdicts": verdicts, "summary": summary,
        "detail": {"MAC_M1": j1, "MAC_M2": j2, "MAC_M3": j3},
        "models": {"by_stratum": m_by, "calib": calib, "skill": skill, "slopes": slopes, "model3": m3_by},
        "episodes": episodes, "events": events, "current": current, "robustness": robust,
        "v1_check": lab.v1_check(us, base_preds, smoke), "expected": EXPECTED, "notes": NOTES,
    }
    return res, rows


# ---------------------------------------------------------------- 보고서
def _fv(lab, v, nd=4) -> str:
    return "자료 없음" if lab.fin(v) is None else f"{v:+.{nd}f}"


def report(res: dict, smoke: bool) -> str:
    lab = L()
    R = lab.report_head(res, "금리·신용 여건(H-022) — 긴 약세장 확률로 깊이·회복·분할 비율", smoke, MODEL_NAMES)
    R += ["MAC_M3 의 평균 d 는 D3(SPLIT_P − SPLIT_P0, 3년 로그 %)이다. 분류기 미적합으로 판정에서 빠진 A·B·C 사건: "
          f"{res['detail']['MAC_M1']['n_unfit']}개.", ""]
    R += ["## 이 연구가 묻는 것", "",
          "- 급락 발생일 직전 달의 금리·신용 여건 세 가지 — 단기금리 1년 변화(RATECHG_M), 장단기차(TERM = Aaa 회사채 − 1개월 국채), "
          "신용 스프레드(DEF = Baa − Aaa) — 로 '252거래일 안에 전고점을 회복하지 못하는 긴 약세장' 확률 p 를 세운다(능형 로지스틱, 부호는 정하지 않음).",
          "- 그 확률로 과거 사건을 '긴 약세장'과 '빠른 반등' 두 갈래로 다시 가중하면(MACRO) v1 기준선보다 최종 깊이·회복을 잘 맞히나.",
          "- 그 확률로 발생일에 한 번 '바로 넣을 비율' a = 1 − p 를 정하고 나머지를 6개월 매달 나누면(SPLIT_P), 같은 날 기준 확률 π 로 정한 고정 분할(SPLIT_P0)보다 "
          "3년 뒤 더 많이 남나. 발생일 뒤 시장 정보는 보지 않는다(신호 기다리기가 아님).", ""]
    cur = res["current"]
    mn = cur.get("macro_now") or {}
    R += ["## 지금 읽기 (설명용 — 추천 아님)", "", lab.READING_HEADER, ""] + lab.reading_state_lines(cur)
    fnow = cur.get("features_now") or {}
    R += [f"기준: {cur.get('basis')}.", "",
          "특징 값: " + " · ".join(f"{k} {_fv(lab, fnow.get(k))}" for k in FEATS) + " (연율 소수, '자료 없음' = 그 달 값이 아직 없음)", ""]
    if mn.get("unfit"):
        R += [f"MACRO 읽기: {mn['unfit']}.", ""]
    else:
        R += [f"긴 약세장 확률 p = {lab.pct(mn.get('p_lb'), 0, False)} (기준 확률 π = {lab.pct(mn.get('pi'), 0, False)}, 라벨 있는 학습 사건 {mn.get('n_cls')}개) · "
              f"설명용 즉시 투입 비율 a = 1 − p = {lab.pct(mn.get('a_now'), 0, False)}", "",
              "| 모델 | 최종 깊이 10/50/90% | 회복 1/2/5년 |", "|---|---|---|",
              f"| BASE | {lab.q3(mn.get('base_m1'))} | {lab.r3(mn.get('base_m2'))} |",
              f"| MACRO | {lab.q3(mn.get('m1'))} | {lab.r3(mn.get('m2'))} |", ""]
    R += [lab.spy_line(cur.get("spy_check") or {}), ""]
    R += ["## 사용자가 든 7개 사건", ""] + lab.events_note_lines(res["events"])
    R += ["### 발생일 읽기 (그 사건 발생일까지의 정보만)", "",
          "| 사건 | 발생일 | RATECHG_M | TERM | DEF | p_lb (π) | BASE 깊이 10/50/90% | MACRO 깊이 10/50/90% | BASE 회복 1/2/5년 | MACRO 회복 1/2/5년 | a_now (a0) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in res["events"]:
        st = e.get("study")
        if not st:
            R.append(f"| {e['label']} | — | | | | | | | | | |")
            continue
        f = st["features"]
        pl = "미적합" if st["unfit"] else f"{lab.pct(st['p_lb'], 0, False)} ({lab.pct(st['pi'], 0, False)})"
        R.append(f"| {e['label']} | {e['episode_t0']} | {_fv(lab, f['RATECHG_M'])} | {_fv(lab, f['TERM'])} | {_fv(lab, f['DEF'])} | {pl} | "
                 f"{lab.q3(st['base_m1'])} | {lab.q3(st['m1'])} | {lab.r3(st['base_m2'])} | {lab.r3(st['m2'])} | "
                 f"{lab.pct(st['a_now'], 0, False)} ({lab.pct(st['a0'], 0, False)}) |")
    R.append("")
    mb = res["models"]
    f100 = lambda v: "—" if lab.fin(v) is None else f"{v * 100:.2f}"  # noqa: E731
    R += ["## 모델 1·2 — 층별 평균 점수", "", "핀볼 = 전고점 대비 %p(낮을수록 잘 맞힘), 브라이어 = 0~1(낮을수록 잘 맞힘). 평가 = 쌍이 있는 판정 층 사건.", "",
          "| 층 | 모델 1 평가 | 핀볼 BASE | 핀볼 MACRO | 모델 2 평가 | 브라이어 BASE | 브라이어 MACRO | 미적합 |", "|---|---|---|---|---|---|---|---|"]
    for s in ("A", "B", "C", "all"):
        x = mb["by_stratum"][s]
        R.append(f"| {s if s != 'all' else 'A+B+C'} | {x['n1']} | {f100(x['m1']['BASE'])} | {f100(x['m1']['MACRO'])} | {x['n2']} | "
                 f"{lab.num(x['m2']['BASE'])} | {lab.num(x['m2']['MACRO'])} | {x['n_unfit']} |")
    R += ["", "### 보정: 평균 예측 회복 확률 vs 실제 비율", "", "| 시점 | 사건 | BASE | MACRO | 실제 |", "|---|---|---|---|---|"]
    for h in lab.HZ:
        c = mb["calib"][str(h)]
        R.append(f"| {h // 252}년 | {c['n']} | {lab.pct(c['BASE'], 0, False)} | {lab.pct(c['MACRO'], 0, False)} | {lab.pct(c['obs'], 0, False)} |")
    sk, sl = mb["skill"], mb["slopes"]
    R += ["", "### 분류 실력과 기울기 (보고만)", "",
          f"- 판정 층 사건 {sk['n']}개의 실제 '긴 약세장' 라벨에 대한 브라이어: p_lb {lab.num(sk['brier_p'])} vs 기준 확률 π {lab.num(sk['brier_pi'])} (낮을수록 잘 가름).",
          f"- 마지막 날 적합(라벨 있는 사건 {sl['last_fit_n']}개, 적합 {'가능' if sl['last_fit_ok'] else '불가'})의 표준화 기울기: "
          + " · ".join(f"{f} {lab.sgn(sl['last_fit'][f], 3)}" for f in FEATS) + " (양수 = 값이 클수록 긴 약세장 쪽).",
          f"- 판정 사건 예측 때 적합 {sl['n_fits']}개에서 기울기가 양수였던 비율: " + " · ".join(f"{f} {lab.pct(sl['share_positive'][f], 0, False)}" for f in FEATS), ""]
    R += ["## 모델 3 — 확률로 정한 분할 비율", "",
          "- 발생일 다음 거래일에 a 를 바로 넣고 나머지 (1 − a) 를 21·42·…·126거래일 뒤 6번 같은 몫으로 넣는다(a = 0.5 면 v1 의 HALF6). 기다리는 돈은 그날 RF.",
          "- D3 = ln(SPLIT_P 계좌 3년 뒤) − ln(SPLIT_P0 계좌 3년 뒤). LUMP(다음 날 한 번에)·HALF6 대비는 보고만. G = 최악 순간(원금 대비) 개선.", "",
          "| 층 | 끝난 사건 | 평균 D3 | 후회 비율(D3<0) | 평균 a / a0 | 대 LUMP D: SPLIT_P / SPLIT_P0 / HALF6 | 대 LUMP G: SPLIT_P / SPLIT_P0 / HALF6 |", "|---|---|---|---|---|---|---|"]
    for s in ("A", "B", "C", "all"):
        x = mb["model3"][s]
        vl = x["vs_lump"]
        R.append(f"| {s if s != 'all' else 'A+B+C'} | {x['n']} | {lab.pct(x['D3_mean'], 2)} | {lab.pct(x['regret_share'], 0, False)} | "
                 f"{lab.pct(x['a_mean'], 0, False)} / {lab.pct(x['a0_mean'], 0, False)} | "
                 + " / ".join(lab.pct(vl[k]["D_mean"]) for k in ("SPLIT_P", "SPLIT_P0", "HALF6")) + " | "
                 + " / ".join(lab.pct(vl[k]["G_mean"]) for k in ("SPLIT_P", "SPLIT_P0", "HALF6")) + " |")
    rb = res["robustness"]
    f3 = lambda x: f"{x['n']} · {lab.sgn(x['mean'])} · {lab.pval(x['p'])}"  # noqa: E731
    R += ["", "## 견고성 (보고만)", "", "라벨을 붙이지 않는다. 값은 n · 평균 d · 한쪽 부호 뒤집기 p.", "",
          "| 항목 | 모델 1 | 모델 2 | 모델 3 |", "|---|---|---|---|",
          f"| A+B 만(v1 방식) | {f3(rb['ab_only']['MAC_M1'])} | {f3(rb['ab_only']['MAC_M2'])} | {f3(rb['ab_only']['MAC_M3'])} |",
          f"| 미국 겹침 군집 p | {lab.pval(rb['cluster_us']['MAC_M1'])} | {lab.pval(rb['cluster_us']['MAC_M2'])} | {lab.pval(rb['cluster_us']['MAC_M3'])} |"]
    for code, x in rb["singles"].items():
        R.append(f"| 특징 하나 {code} | {f3(x['m1'])} | {f3(x['m2'])} | — |")
    R.append(f"| KERNEL_RATECHG_M (v1 커널 + 월별 금리 변화) | {f3(rb['kernel_ratechg_m']['m1'])} | {f3(rb['kernel_ratechg_m']['m2'])} | — |")
    vc = res["v1_check"]
    R += ["", "v1 기준선 재현 확인(미국 발생일 BASE vs v1 결과 파일): "
          + (vc["skipped"] if "skipped" in vc else f"사건 {vc['n']} · 최대 차이 깊이 {lab.num(vc['max_abs_diff_m1'], 6)} · 회복 {lab.num(vc['max_abs_diff_m2'], 6)}"), ""]
    R += lab.report_tail(res, LIMITS, ["- p_lb = 긴 약세장(252거래일 안 회복 못 함) 확률, π = 그날 라벨을 아는 과거 사건의 긴 약세장 비율. 기울기가 0 이면 p = π 라 MACRO = BASE.",
                                      "- 특징은 모두 발생일이 속한 달의 전달 값(무디스 월평균은 다음 달 초 공표)."])
    return "\n".join(R) + "\n"


# ---------------------------------------------------------------- 실행
def run(smoke: bool) -> tuple:
    lab = L()
    data = lab.load_us(smoke)
    data["rf_m"] = lab.load_rf_monthly(smoke)
    data["moodys"] = lab.load_moodys(smoke)
    return evaluate(data, smoke)


def main(argv=None) -> int:
    return L().run_main(argv, run, report)


if __name__ == "__main__":
    raise SystemExit(main())
