"""crash-simpath-v1 — 급락 경로 모의(GARCH(1,1) + 과거 표준화 수익 재표집). 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/crash-simpath-v1/run.py --out OUT --checkpoint CK [--smoke]

- 발생일 깊이와 그날 변동성 상태에서 출발해 경로 4,000개(스모크 400개)를 5년(1,260거래일) 모의 → 최종 깊이 분위수(3년 안 최저)·1·2·3·5년 회복 확률.
- 사건 28개가 아니라 그때까지의 일별 자료(약 25,000일)로 배운다. 기준선 = v1 발생일 기준선.
- 판정 2개(SIM_M1·SIM_M2), 족 15개 공통 α = 0.05/15, 미국 A·B·C 사건 단위(발생일).
- 랜드마크·SIM_IID(변동성 상태 없음)·해외 재현은 보고만. 작업은 결정적(같은 seed). 계산은 수 분 이내라 체크포인트를 쓰지 않는다.
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

STUDY = "crash-simpath-v1"
RULES_VERSION = "crash-simpath/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
NOW_DD0 = -0.15
MODEL_NAMES = {"SIM_M1": "SIM vs BASE (깊이, 발생일)", "SIM_M2": "SIM vs BASE (회복, 발생일)"}
EXPECTED = {
    "SIM_M1": "FAIL 가능성이 높다(통과 약 15%). 변동성이 큰 발생일(1987·2020)에는 분포가 넓어지고, 조용히 미끄러지는 약세장(1973·2000·2008 초입)에서는 좁아져 깊은 꼬리를 놓칠 수 있다.",
    "SIM_M2": "불확실(통과 약 25%). 기준선 KM 은 발생일 깊이를 무시하지만 모의는 깊이·변동성에 따라 회복 확률이 달라진다. 무작위 보행은 급락 뒤 V자 반등(평균 회귀)을 못 담는다.",
}
NOTES = [
    "시대 C 사건(2008~2022)은 crash-cycle-model-v1 보고서에서 이미 보았다. GARCH 상수·경로 수·길이는 문헌 전형값과 계산 예산으로 정했다.",
    "평가 집합은 v1 기준선이 있는 사건이다(모의는 학습 사건이 필요 없지만 짝 비교라 기준선 조건을 따름).",
]
LIMITS = [
    "표류 고정·평균 회귀 없음·대칭 GARCH(하락 때 변동성이 더 오르는 비대칭 없음).",
    "잔차는 독립 재표집(달력 군집 없음).",
    "경로 하나의 시장만(정책·거시 없음).",
    "모의 오차: 경로 4,000개 — 분위수 표준오차는 핀볼 차이보다 작다(작업은 결정적: 같은 seed).",
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
def _scores(r: dict, e: int, preds: dict) -> tuple:
    lab = L()
    s1, s2 = {}, {}
    for name, (q, F) in preds.items():
        if r["depth_settled"] and q is not None:
            s1[name] = lab.score_m1(r["FD"], q)
        if r["R"] is not None and F is not None:
            s2[name] = lab.score_m2(r["R"] - e, F)
    return s1, s2


def episode_calc(us: list, r: dict, n_paths: int, landmarks: bool, iid: bool) -> dict:
    """사건 r 의 발생일 SIM(·SIM_IID) vs BASE, 랜드마크(보고) SIM vs 연구 1 BASE."""
    lab = L()
    Lv = r["_Lv"]
    b0 = lab.base0(us, r)
    sim = lab.simulate(Lv, r["market"], r["P"], r["t0"], r["dd0"], 0, n_paths)
    preds = {"BASE": (b0["m1"], b0["m2"])}
    if sim is not None:
        preds["SIM"] = (sim["q"], sim["F"])
    sim_iid = None
    if iid:
        sim_iid = lab.simulate(Lv, r["market"], r["P"], r["t0"], r["dd0"], 0, n_paths, iid=True)
        if sim_iid is not None:
            preds["SIM_IID"] = (sim_iid["q"], sim_iid["F"])
    s1, s2 = _scores(r, 0, preds)
    out: dict[str, Any] = {"r": r, "base0": b0, "sim": sim, "sim_iid": sim_iid, "s1": s1, "s2": s2,
                           "d1": s1["BASE"] - s1["SIM"] if ("BASE" in s1 and "SIM" in s1) else None,
                           "d2": s2["BASE"] - s2["SIM"] if ("BASE" in s2 and "SIM" in s2) else None, "lm": {}}
    if landmarks:
        for e in lab.LANDMARKS:
            st = lab.landmark_state(r, e)
            if st is None:
                continue
            B = lab.landmark_base(us, r, e)
            se = lab.simulate(Lv, r["market"], r["P"], r["t0"] + e, st["m"], e, n_paths)
            p = {"BASE": (B["m1_trunc"], B["m2"])}
            if se is not None:
                p["SIM"] = (se["q"], se["F"])
            a1, a2 = _scores(r, e, p)
            out["lm"][e] = {"st": st, "B": B, "sim": se,
                            "d1": a1["BASE"] - a1["SIM"] if ("BASE" in a1 and "SIM" in a1) else None,
                            "d2": a2["BASE"] - a2["SIM"] if ("BASE" in a2 and "SIM" in a2) else None}
    return out


def pred_rows(c: dict, judged: bool) -> list:
    lab = L()
    r, b0 = c["r"], c["base0"]
    j1, j2 = int(judged and c["d1"] is not None), int(judged and c["d2"] is not None)
    rows = [lab.pred_row(STUDY, "BASE", r, 0, r["t0_date"], b0["n_train"], None, b0["m1"], b0["m2"], None, j1, j2)]
    if c["sim"] is not None:
        rows.append(lab.pred_row(STUDY, "SIM", r, 0, r["t0_date"], c["sim"]["n_hist"], None, c["sim"]["q"], c["sim"]["F"], None, j1, j2))
    if c["sim_iid"] is not None:
        rows.append(lab.pred_row(STUDY, "SIM_IID", r, 0, r["t0_date"], c["sim_iid"]["n_hist"], None, c["sim_iid"]["q"], c["sim_iid"]["F"]))
    for e, x in c["lm"].items():
        B, st = x["B"], x["st"]
        rows.append(lab.pred_row(STUDY, "BASE", r, e, st["asof"], lab.n_train_of(B["m1_trunc"], B["n1"], B["m2"], B["n2"]), None, B["m1_trunc"], B["m2"]))
        if x["sim"] is not None:
            rows.append(lab.pred_row(STUDY, "SIM", r, e, st["asof"], x["sim"]["n_hist"], None, x["sim"]["q"], x["sim"]["F"]))
    return rows


def make_reader(us: list, by_id: dict, n_paths: int):
    lab = L()

    def reader(ep: dict, d: int, mapping: str) -> dict:
        c = by_id[ep["id"]]
        out = {"base_m1": c["base0"]["m1"], "base_m2": c["base0"]["m2"], "sim_m1": None if c["sim"] is None else c["sim"]["q"],
               "sim_m2": None if c["sim"] is None else c["sim"]["F"], "vol_now": None if c["sim"] is None else c["sim"]["vol_now"],
               "vol_lr": None if c["sim"] is None else c["sim"]["vol_lr"]}
        if mapping == "inside":
            e = int(d - ep["t0"])
            st = lab.landmark_state(ep, e)
            if st is not None:
                B = lab.landmark_base(us, ep, e)
                s = lab.simulate(ep["_Lv"], "US", ep["P"], d, st["m"], e, n_paths)
                out["snapshot"] = {"e": e, "asof": lab.dstr(st["asof"]), "d": st["d"], "m": st["m"], "base_m1": B["m1_trunc"], "base_m2": B["m2"],
                                   "sim_m1": None if s is None else s["q"], "sim_m2": None if s is None else s["F"],
                                   "vol_now": None if s is None else s["vol_now"]}
        return out

    return reader


def current_block(ctx: dict, us: list, n_paths: int, smoke: bool) -> dict:
    lab = L()
    cur = lab.reading_now(ctx)
    last, Lv = ctx["last"], ctx["Lv"]
    D = pd.Timestamp(ctx["idx"][last])
    ep = lab.active_episode(ctx, last)
    if ep is not None:
        e_now = int(last - ep["t0"])
        m = float(Lv[ep["t0"]:last + 1].min() / ep["P"] - 1)
        s = lab.simulate(Lv, "US", ep["P"], last, m, e_now, n_paths)
        st = lab.landmark_state(ep, e_now)
        B = None if st is None else lab.landmark_base(us, ep, e_now)
        cur["basis"] = f"진행 중 사건({lab.dstr(ep['t0_date'])}) 오늘 상태(발생 뒤 {e_now} 거래일, 지금까지 최저 {m * 100:.1f}%)에서 모의"
        cur["base_now"] = None if B is None else {"m1": B["m1_trunc"], "m2": B["m2"]}
    else:
        s = lab.simulate(Lv, "US", float(Lv[last]) / (1 + NOW_DD0), last, NOW_DD0, 0, n_paths)
        cur["basis"] = f"만약 오늘({lab.dstr(D)})이 발생일이라면(전고점 대비 −15% 로 고정, 변동성 상태는 오늘 값)"
        cur["base_now"] = {"m1": cur.get("m1_base"), "m2": cur.get("m2_base")}
    cur["sim_now"] = None if s is None else {"m1": s["q"], "m2": s["F"], "vol_now": s["vol_now"], "vol_lr": s["vol_lr"]}
    cur["spy_check"] = lab.spy_check(cur["state"], smoke)
    return cur


# ---------------------------------------------------------------- 평가
def evaluate(data: dict, smoke: bool) -> tuple:
    from core import research_power as rp

    lab = L()
    v1 = lab.v1()
    n_paths = lab.N_SIM_SMOKE if smoke else lab.N_SIM
    ctx = lab.us_context(data)
    us = ctx["recs"]
    idx = ctx["idx"]
    reasons: dict = {}
    intl = lab.load_intl(smoke, required=False, reasons=reasons)
    intl_ctx = {k: lab.market_context(Lr, k) for k, Lr in intl.items()}

    calcs = [episode_calc(us, r, n_paths, landmarks=True, iid=True) for r in us]
    icalcs = {k: [episode_calc(us, r, n_paths, landmarks=False, iid=False) for r in mc["eps"]] for k, mc in intl_ctx.items()}
    by_id = {c["r"]["id"]: c for c in calcs}

    rows: list = []
    for c in calcs:
        rows += pred_rows(c, c["r"]["stratum"] in lab.US_STRATA)
    for cs in icalcs.values():
        for c in cs:
            rows += pred_rows(c, False)

    judged = [c for c in calcs if c["r"]["stratum"] in lab.US_STRATA]
    dm1 = {s: [c["d1"] for c in judged if c["r"]["stratum"] == s and c["d1"] is not None] for s in lab.US_STRATA}
    dm2 = {s: [c["d2"] for c in judged if c["r"]["stratum"] == s and c["d2"] is not None] for s in lab.US_STRATA}
    j1, j2 = lab.judge_us(dm1), lab.judge_us(dm2)
    verdicts = {"SIM_M1": j1["verdict"], "SIM_M2": j2["verdict"]}

    # 보고만
    def st3(vals):
        return {"n": len(vals), "mean": lab.mean_or_none(vals), "p": lab.signflip(vals)}

    ab = lambda dm: [v for s in ("A", "B") for v in dm[s]]  # noqa: E731
    per_lm = {str(e): {"m1": st3([c["lm"][e]["d1"] for c in judged if e in c["lm"] and c["lm"][e]["d1"] is not None]),
                       "m2": st3([c["lm"][e]["d2"] for c in judged if e in c["lm"] and c["lm"][e]["d2"] is not None])} for e in lab.LANDMARKS}
    iid = {"m1": st3([c["s1"]["BASE"] - c["s1"]["SIM_IID"] for c in judged if "BASE" in c["s1"] and "SIM_IID" in c["s1"]]),
           "m2": st3([c["s2"]["BASE"] - c["s2"]["SIM_IID"] for c in judged if "BASE" in c["s2"] and "SIM_IID" in c["s2"]]),
           "garch_vs_iid_m1": st3([c["s1"]["SIM_IID"] - c["s1"]["SIM"] for c in judged if "SIM" in c["s1"] and "SIM_IID" in c["s1"]]),
           "garch_vs_iid_m2": st3([c["s2"]["SIM_IID"] - c["s2"]["SIM"] for c in judged if "SIM" in c["s2"] and "SIM_IID" in c["s2"]])}
    intl_rep = {}
    for which in ("d1", "d2"):
        its = [(c["r"]["t0_date"], c[which], c["r"]["id"]) for cs in icalcs.values() for c in cs
               if c[which] is not None and c["r"]["stratum"] in lab.INTL_STRATA]
        cl = lab.clusters(its)
        intl_rep[which] = {"n_episodes": len(its), "n_clusters": len(cl),
                           "mean": {s: lab.mean_or_none([c["value"] for c in cl if c["stratum"] == s]) for s in lab.INTL_STRATA},
                           "p_cluster": lab.signflip([c["value"] for c in cl])}
    robust = {"ab_only": {"SIM_M1": st3(ab(dm1)), "SIM_M2": st3(ab(dm2))},
              "cluster_us": {"SIM_M1": v1.cluster_p([(c["r"]["t0"], c["r"]["end1"], c["d1"]) for c in judged if c["d1"] is not None]),
                             "SIM_M2": v1.cluster_p([(c["r"]["t0"], c["r"]["rec"], c["d2"]) for c in judged if c["d2"] is not None])},
              "per_landmark": per_lm, "sim_iid": iid, "intl": intl_rep}
    m_by, cov, calib = {}, {}, {}
    for s in ("A", "B", "C", "all"):
        xs = [c for c in judged if s == "all" or c["r"]["stratum"] == s]
        e1 = [c for c in xs if c["d1"] is not None]
        e2 = [c for c in xs if c["d2"] is not None]
        m_by[s] = {"n1": len(e1), "n2": len(e2), "m1": {m: lab.mean_or_none([c["s1"].get(m) for c in e1]) for m in ("BASE", "SIM", "SIM_IID")},
                   "m2": {m: lab.mean_or_none([c["s2"].get(m) for c in e2]) for m in ("BASE", "SIM", "SIM_IID")}}
        hb = [c["base0"]["m1"]["0.1"] <= c["r"]["FD"] <= c["base0"]["m1"]["0.9"] for c in e1]
        hs = [c["sim"]["q"]["0.1"] <= c["r"]["FD"] <= c["sim"]["q"]["0.9"] for c in e1]
        cov[s] = {"BASE": float(np.mean(hb)) if hb else None, "SIM": float(np.mean(hs)) if hs else None}
    e2 = [c for c in judged if c["d2"] is not None]
    for h in lab.HZ:
        calib[str(h)] = {"BASE": lab.mean_or_none([c["base0"]["m2"][h] for c in e2]), "SIM": lab.mean_or_none([c["sim"]["F"][h] for c in e2]),
                         "obs": float(np.mean([c["r"]["R"] <= h for c in e2])) if e2 else None, "n": len(e2)}
    vol_table = [{"id": c["r"]["id"], "t0": lab.dstr(c["r"]["t0_date"]), "era": c["r"]["stratum"], "dd0": c["r"]["dd0"],
                  "vol_now": c["sim"]["vol_now"], "vol_lr": c["sim"]["vol_lr"], "d1": c["d1"], "d2": c["d2"]} for c in judged if c["sim"] is not None]

    events = lab.events_rows(ctx, make_reader(us, by_id, n_paths))
    current = current_block(ctx, us, n_paths, smoke)
    summary = {"SIM_M1 경로 모의 깊이": lab.summary_entry(j1), "SIM_M2 경로 모의 회복": lab.summary_entry(j2),
               f"지금(Ken French {current['as_of']})": lab.now_line(current)}
    episodes = []
    for c in calcs + [c for cs in icalcs.values() for c in cs]:
        r = c["r"]
        episodes.append({"id": r["id"], "t0": lab.dstr(r["t0_date"]), "era": r["stratum"], "dd0": r["dd0"], "FD": r["FD"], "R": r["R"],
                         "s1": c["s1"], "s2": c["s2"], "d1": c["d1"], "d2": c["d2"],
                         "vol_now": None if c["sim"] is None else c["sim"]["vol_now"],
                         "landmarks": {str(e): {"d1": x["d1"], "d2": x["d2"]} for e, x in c["lm"].items()}})
    base_preds = {lab.dstr(c["r"]["t0_date"]): (c["base0"]["m1"], c["base0"]["m2"]) for c in calcs}
    res = {
        "study": STUDY, "lab_version": lab.LAB_VERSION, "rules": RULES_VERSION, "judge_version": lab.JUDGE_VERSION, "smoke": bool(smoke),
        "data": {"source": data["source"], "first_date": str(idx[0].date()), "last_date": str(idx[-1].date()), "n_days": int(len(idx)),
                 "intl": {k: {"first_date": str(v.index[0].date()), "last_date": str(v.index[-1].date()), "n_episodes": len(intl_ctx[k]["eps"])}
                          for k, v in intl.items()},
                 "intl_missing": reasons, "network_extras": {"spy": bool(current["spy_check"].get("available"))}},
        "constants": dict(lab.lab_constants(), n_paths_used=n_paths, NOW_DD0=NOW_DD0),
        "family": lab.family_block(STUDY),
        "power": rp.power_report(lab.YEARS_US, lab.K_FAMILY),
        "power_episode": {"SIM_M1": lab.power_episode(j1["n"]["pooled"]), "SIM_M2": lab.power_episode(j2["n"]["pooled"])},
        "verdicts": verdicts, "summary": summary, "detail": {"SIM_M1": j1, "SIM_M2": j2},
        "models": {"by_stratum": m_by, "coverage80": cov, "calib": calib, "vol_table": vol_table},
        "episodes": episodes, "events": events, "current": current, "robustness": robust,
        "v1_check": lab.v1_check(us, base_preds, smoke), "expected": EXPECTED, "notes": NOTES,
    }
    return res, rows


# ---------------------------------------------------------------- 보고서
def report(res: dict, smoke: bool) -> str:
    lab = L()
    R = lab.report_head(res, "급락 경로 모의 — GARCH 변동성 상태 + 과거 일별 수익 재표집", smoke, MODEL_NAMES)
    R += [f"경로 수: {res['constants']['n_paths_used']}개 × {lab.H_SIM}거래일(5년). GARCH(1,1) α = {lab.GARCH_A}, β = {lab.GARCH_B}(지속성 0.98, 고정).", ""]
    R += ["## 이 연구가 묻는 것", "",
          "- v1 의 기준선은 과거 급락 사건 28개의 분포다. 이 연구는 사건 대신 **그때까지의 일별 수익 전체**로 배운다: 발생일의 깊이와 그날의 변동성 상태(GARCH)에서 "
          "출발해, 과거 일별 수익을 그날 변동성에 맞게 다시 뽑아 이어 붙인 가상 경로 수천 개를 만든다.",
          "- 질문: 그 가상 경로들의 최종 깊이 분포(3년 안 최저)와 1·2·3·5년 안 전고점 회복 비율이 v1 기준선보다 실제를 잘 맞히나.", ""]
    cur = res["current"]
    R += ["## 지금 읽기 (설명용 — 추천 아님)", "", lab.READING_HEADER, ""] + lab.reading_state_lines(cur)
    sn, bn = cur.get("sim_now"), cur.get("base_now") or {}
    R += [f"기준: {cur.get('basis')}.", ""]
    if sn:
        R += [f"오늘 연율 변동성(GARCH) {lab.pct(sn['vol_now'], 1, False)} vs 장기 평균 {lab.pct(sn['vol_lr'], 1, False)}.", "",
              "| 모델 | 최종 깊이 10/50/90% | 회복 1/2/5년 |", "|---|---|---|",
              f"| BASE | {lab.q3(bn.get('m1'))} | {lab.r3(bn.get('m2'))} |", f"| SIM | {lab.q3(sn['m1'])} | {lab.r3(sn['m2'])} |", ""]
    else:
        R += ["모의 불가(과거 일수 부족).", ""]
    R += [lab.spy_line(cur.get("spy_check") or {}), ""]
    R += ["## 사용자가 든 7개 사건", ""] + lab.events_note_lines(res["events"])
    R += ["### 발생일 읽기: SIM vs BASE (그 사건 발생일까지의 정보만)", "",
          "| 사건 | 발생일 | 발생일 변동성(연율, 오늘/장기) | BASE 깊이 10/50/90% | SIM 깊이 10/50/90% | BASE 회복 1/2/5년 | SIM 회복 1/2/5년 |", "|---|---|---|---|---|---|---|"]
    snaps = []
    for e in res["events"]:
        st = e.get("study")
        if not st:
            R.append(f"| {e['label']} | — | | | | | |")
            continue
        R.append(f"| {e['label']} | {e['episode_t0']} | {lab.pct(st['vol_now'], 0, False)}/{lab.pct(st['vol_lr'], 0, False)} | {lab.q3(st['base_m1'])} | "
                 f"{lab.q3(st['sim_m1'])} | {lab.r3(st['base_m2'])} | {lab.r3(st['sim_m2'])} |")
        if st.get("snapshot"):
            snaps.append((e, st["snapshot"]))
    R.append("")
    if snaps:
        R += ["### 사건 안 기준일 스냅숏 (그날 상태에서 모의, 판정 아님; BASE = 연구 1 진행 중 기준선)", "",
              "| 사건 | 기준일 | 발생 뒤 | 지금 깊이 | 지금까지 최저 | BASE 깊이 10/50/90% | SIM 깊이 10/50/90% | BASE 회복 1/2/5년 | SIM 회복 1/2/5년 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for e, s in snaps:
            R.append(f"| {e['label']} | {s['asof']} | {s['e']}일 | {lab.pct(s['d'])} | {lab.pct(s['m'])} | {lab.q3(s['base_m1'])} | {lab.q3(s['sim_m1'])} | "
                     f"{lab.r3(s['base_m2'])} | {lab.r3(s['sim_m2'])} |")
        R.append("")
    mb = res["models"]
    f100 = lambda v: "—" if lab.fin(v) is None else f"{v * 100:.2f}"  # noqa: E731
    R += ["## 모델 1·2 — 층별 평균 점수", "", "핀볼 = 전고점 대비 %p, 브라이어 = 0~1(둘 다 낮을수록 잘 맞힘). SIM_IID = 변동성 상태 없이(상수 분산) 같은 절차(보고만).", "",
          "| 층 | 모델 1 평가 | 핀볼 BASE / SIM / SIM_IID | 80% 포함 BASE / SIM | 모델 2 평가 | 브라이어 BASE / SIM / SIM_IID |", "|---|---|---|---|---|---|"]
    for s in ("A", "B", "C", "all"):
        x, cv = mb["by_stratum"][s], mb["coverage80"][s]
        R.append(f"| {s if s != 'all' else 'A+B+C'} | {x['n1']} | " + " / ".join(f100(x["m1"][m]) for m in ("BASE", "SIM", "SIM_IID"))
                 + f" | {lab.pct(cv['BASE'], 0, False)} / {lab.pct(cv['SIM'], 0, False)} | {x['n2']} | "
                 + " / ".join(lab.num(x["m2"][m]) for m in ("BASE", "SIM", "SIM_IID")) + " |")
    R += ["", "### 보정: 평균 예측 회복 확률 vs 실제 비율", "", "| 시점 | 사건 | BASE | SIM | 실제 |", "|---|---|---|---|---|"]
    for h in lab.HZ:
        c = mb["calib"][str(h)]
        R.append(f"| {h // 252}년 | {c['n']} | {lab.pct(c['BASE'], 0, False)} | {lab.pct(c['SIM'], 0, False)} | {lab.pct(c['obs'], 0, False)} |")
    R += ["", "### 발생일 변동성별 사건 (판정 층)", "", "| 발생일 | 층 | 발생일 깊이 | 변동성 오늘/장기(연율) | d 모델 1 | d 모델 2 |", "|---|---|---|---|---|---|"]
    for v in sorted(mb["vol_table"], key=lambda z: -(z["vol_now"] or 0)):
        R.append(f"| {v['t0']} | {v['era']} | {lab.pct(v['dd0'])} | {lab.pct(v['vol_now'], 0, False)}/{lab.pct(v['vol_lr'], 0, False)} | {lab.sgn(v['d1'])} | {lab.sgn(v['d2'])} |")
    rb = res["robustness"]
    f3 = lambda x: f"{x['n']} · {lab.sgn(x['mean'])} · {lab.pval(x['p'])}"  # noqa: E731
    R += ["", "## 견고성 (보고만)", "", "라벨을 붙이지 않는다. 값은 n · 평균 d · 한쪽 부호 뒤집기 p.", "", "| 항목 | 모델 1 | 모델 2 |", "|---|---|---|",
          f"| A+B 만(v1 방식) | {f3(rb['ab_only']['SIM_M1'])} | {f3(rb['ab_only']['SIM_M2'])} |",
          f"| 미국 겹침 군집 p | {lab.pval(rb['cluster_us']['SIM_M1'])} | {lab.pval(rb['cluster_us']['SIM_M2'])} |"]
    for e in lab.LANDMARKS:
        x = rb["per_landmark"][str(e)]
        R.append(f"| 랜드마크 {e}: SIM vs 연구 1 BASE | {f3(x['m1'])} | {f3(x['m2'])} |")
    R += [f"| SIM_IID vs BASE | {f3(rb['sim_iid']['m1'])} | {f3(rb['sim_iid']['m2'])} |",
          f"| SIM vs SIM_IID (변동성 상태의 몫) | {f3(rb['sim_iid']['garch_vs_iid_m1'])} | {f3(rb['sim_iid']['garch_vs_iid_m2'])} |"]
    it = rb["intl"]
    R.append(f"| 해외 3지역(자기 수익으로 SIM vs 미국 학습 BASE, 군집) | 사건 {it['d1']['n_episodes']} · 군집 {it['d1']['n_clusters']} · I1 {lab.sgn(it['d1']['mean']['I1'])} / "
             f"I2 {lab.sgn(it['d1']['mean']['I2'])} · p {lab.pval(it['d1']['p_cluster'])} | 사건 {it['d2']['n_episodes']} · 군집 {it['d2']['n_clusters']} · "
             f"I1 {lab.sgn(it['d2']['mean']['I1'])} / I2 {lab.sgn(it['d2']['mean']['I2'])} · p {lab.pval(it['d2']['p_cluster'])} |")
    miss = res["data"].get("intl_missing") or {}
    if miss:
        R += ["", "해외 자료 없음: " + ", ".join(f"{k}({v})" for k, v in miss.items())]
    vc = res["v1_check"]
    R += ["", "v1 기준선 재현 확인(미국 발생일 BASE vs v1 결과 파일): "
          + (vc["skipped"] if "skipped" in vc else f"사건 {vc['n']} · 최대 차이 깊이 {lab.num(vc['max_abs_diff_m1'], 6)} · 회복 {lab.num(vc['max_abs_diff_m2'], 6)}"), ""]
    R += lab.report_tail(res, LIMITS, ["- 모의 깊이 = 각 경로의 3년(756거래일) 안 회복 전 최저(v1 최종 깊이와 같은 정의), 회복 = 경로가 전고점에 처음 닿은 날.",
                                      "- 변동성(연율) = √(252 × 일별 분산). '오늘' = GARCH 가 거른 다음 날 분산, '장기' = 그때까지 전체 표본 분산."])
    return "\n".join(R) + "\n"


# ---------------------------------------------------------------- 실행
def run(smoke: bool) -> tuple:
    return evaluate(L().load_us(smoke), smoke)


def main(argv=None) -> int:
    return L().run_main(argv, run, report)


if __name__ == "__main__":
    raise SystemExit(main())
