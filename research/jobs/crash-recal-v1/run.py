"""crash-recal-v1 — 기준선 자기 보정(과거 표본 밖 오차로 치우침 고치기). 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/crash-recal-v1/run.py --out OUT --checkpoint CK [--smoke]

- 모든 사건(미국·해외)의 표본 밖 BASE(미국만 학습한 v1 기준선)와 그때까지 확정된 실제 결과로
  모델 2 = 회복 확률의 로짓 치우침 c_h(1차원 뉴턴, 사전분포 sd 1), 모델 1 = 깊이 분위수의 치우침 δ_q(분위수, 사전 10건으로 줄임)를 배워 다음 예측을 고친다.
- 처방이 v1 의 보정 실패를 보고 골라졌으므로 **미국 사건으로 판정하지 않는다**: 처음 보는 해외 급락(1991~2024-09)을 동시 급락 군집 단위로 판정.
- 판정 2개(RECAL_M1·RECAL_M2), 족 15개 공통 α = 0.05/15. 해외 자료를 못 받으면 예외(실행기 재시도). 계산은 수십 초라 체크포인트를 쓰지 않는다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STUDY = "crash-recal-v1"
RULES_VERSION = "crash-recal/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
NOW_DD0 = -0.15
MODEL_NAMES = {"RECAL_M1": "RECAL vs BASE(미국만 학습) (깊이, 해외 군집)", "RECAL_M2": "RECAL vs BASE(미국만 학습) (회복, 해외 군집)"}
EXPECTED = {
    "RECAL_M1": "FAIL 가능성이 높다(통과 약 8%). v1 기준선의 깊이 구간 포함률은 이미 목표(80%)에 가깝다(77%).",
    "RECAL_M2": "불확실~FAIL(통과 약 12%). 초기 보정 집합은 미국 오차가 대부분이라 회복 확률을 올리는 쪽으로 고치는데, USD 기준 해외 회복이 느리면 오히려 나빠진다.",
}
NOTES = [
    "이 처방은 v1 의 보정 실패(평가 사건 1년 회복 예측 37% vs 실제 59%)를 보고 골랐다 → 미국 사건으로 판정하지 않는다. 방향을 미리 정하지 않는 자기 보정이다.",
    "상수(최소 쌍 10, 로짓 사전분포 sd 1, 분위수 보정 사전 10건)는 '사건 10개면 보정 크기의 절반을 믿는다'는 선험 규칙이다.",
    "판정 단위는 동시 급락 군집(평일 63일 간격, 군집 값 = 구성 평균, 층 = 첫 사건 날짜). 2024-10 이후 사건은 군집에 넣지 않는다.",
]
LIMITS = [
    "보정 집합은 미국 사건이 대부분이라 미국 오차를 해외로 옮긴다.",
    "군집 수가 적다(예상 약 13개, 필요 효과 약 0.9 sd).",
    "분위수 보정은 덧셈 이동이라 분포 모양은 못 고친다.",
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
def outcome_known(k: dict, D, h: int) -> Optional[int]:
    """D 날짜에 알 수 있는 1[R_k ≤ h]: 회복이 D 까지 확정이면 그 값, 아니고 D 까지 h 일 넘게 미회복이면 0, 그 밖 모름(None)."""
    lab = L()
    D = pd.Timestamp(D)
    if k["rec_date"] is not None and k["rec_date"] <= D:
        return int(k["R"] <= h)
    if lab.pos_le(k["_idx"], D) - k["t0"] >= h:
        return 0
    return None


def recal_at(allr: list, bases: dict, D, F_i: Optional[dict], Q_i: Optional[dict], dd0: float) -> dict:
    """D 날짜까지 확정된 쌍으로 보정한 RECAL 예측(11.5 절 2·3단계)."""
    lab = L()
    D = pd.Timestamp(D)
    out: dict[str, Any] = {"m1": None, "m2": None, "c": None, "delta": None, "n_pairs_m2": None, "n_pairs_m1": None}
    if F_i is not None:
        pairs = {}
        for h in lab.HZ:
            pr = []
            for k in allr:
                Fk = bases[k["id"]]["m2"]
                if k["t0_date"] < D and Fk is not None:
                    o = outcome_known(k, D, h)
                    if o is not None:
                        pr.append((Fk[h], o))
            pairs[h] = pr
        rm2 = lab.recal_m2(F_i, pairs)
        out.update(m2=rm2["F"], c=rm2["c"], n_pairs_m2=rm2["n"])
    if Q_i is not None:
        K1 = [k for k in allr if k["t0_date"] < D and bases[k["id"]]["m1"] is not None and k["depth_settled"] and k["end1_date"] <= D]
        rm1 = lab.recal_m1(Q_i, [k["FD"] for k in K1], {f"{q:g}": [bases[k["id"]]["m1"][f"{q:g}"] for k in K1] for q in lab.Q}, dd0)
        out.update(m1=rm1["q"], delta=rm1["delta"], n_pairs_m1=rm1["n"])
    return out


def episode_calc(allr: list, bases: dict, r: dict) -> dict:
    lab = L()
    b = bases[r["id"]]
    rc = recal_at(allr, bases, r["t0_date"], b["m2"], b["m1"], r["dd0"])
    s1, s2 = {}, {}
    for name, q, F in (("BASE", b["m1"], b["m2"]), ("RECAL", rc["m1"], rc["m2"])):
        if r["depth_settled"] and q is not None:
            s1[name] = lab.score_m1(r["FD"], q)
        if r["R"] is not None and F is not None:
            s2[name] = lab.score_m2(r["R"], F)
    return {"r": r, "base": b, "recal": rc, "s1": s1, "s2": s2,
            "d1": s1["BASE"] - s1["RECAL"] if len(s1) == 2 else None, "d2": s2["BASE"] - s2["RECAL"] if len(s2) == 2 else None}


def make_reader(by_id: dict):
    def reader(ep: dict, d: int, mapping: str) -> dict:
        c = by_id[ep["id"]]
        return {"base_m1": c["base"]["m1"], "base_m2": c["base"]["m2"], "recal_m1": c["recal"]["m1"], "recal_m2": c["recal"]["m2"],
                "c": c["recal"]["c"], "delta": c["recal"]["delta"]}

    return reader


def current_block(ctx: dict, us: list, allr: list, bases: dict, smoke: bool) -> dict:
    lab = L()
    cur = lab.reading_now(ctx)
    last = ctx["last"]
    D = pd.Timestamp(ctx["idx"][last])
    ep = lab.active_episode(ctx, last)
    if ep is not None:
        e_now, dd0 = int(last - ep["t0"]), ep["dd0"]
        cur["basis"] = f"진행 중 사건({lab.dstr(ep['t0_date'])}) — 발생일 깊이로 변환, 학습·보정은 {lab.dstr(D)} 까지, 회복은 경과 {e_now}일 조건부"
    else:
        e_now, dd0 = 0, NOW_DD0
        cur["basis"] = f"만약 오늘({lab.dstr(D)})이 미국 급락 발생일이라면(발생일 깊이 −15%)"
    T1 = lab.m1_pool(us, D)
    rows, times, events = lab.m2_pool(us, D)
    Q, F = lab.base_m1(T1, dd0), lab.base_m2(rows, times, events, e_now)
    rc = recal_at(allr, bases, D, F, Q, dd0)
    cur["base_now"], cur["recal_now"] = {"m1": Q, "m2": F, "n1": len(T1), "n2": len(rows)}, rc
    cur["spy_check"] = lab.spy_check(cur["state"], smoke)
    return cur


# ---------------------------------------------------------------- 평가
def evaluate(data: dict, smoke: bool) -> tuple:
    from core import research_power as rp

    lab = L()
    ctx = lab.us_context(data)
    us = ctx["recs"]
    idx = ctx["idx"]
    intl = data["intl"]
    intl_ctx = {k: lab.market_context(Lr, k) for k, Lr in intl.items()}
    intl_recs = [r for k in lab.INTL_REGIONS if k in intl_ctx for r in intl_ctx[k]["eps"]]
    allr = us + intl_recs
    bases = {k["id"]: lab.base0(us, k) for k in allr}

    icalcs = [episode_calc(allr, bases, r) for r in intl_recs]
    ucalcs = [episode_calc(allr, bases, r) for r in us]
    j1, cl1 = lab.intl_verdict([(c["r"], c["d1"]) for c in icalcs])
    j2, cl2 = lab.intl_verdict([(c["r"], c["d2"]) for c in icalcs])
    verdicts = {"RECAL_M1": j1["verdict"], "RECAL_M2": j2["verdict"]}

    rows: list = []
    for c in icalcs + ucalcs:
        r = c["r"]
        jd = r["market"] != "US" and r["stratum"] in lab.INTL_STRATA
        jf1, jf2 = int(jd and c["d1"] is not None), int(jd and c["d2"] is not None)
        b, rc = c["base"], c["recal"]
        rows.append(lab.pred_row(STUDY, "BASE", r, 0, r["t0_date"], b["n_train"], None, b["m1"], b["m2"], None, jf1, jf2))
        if rc["m1"] is not None or rc["m2"] is not None:
            rows.append(lab.pred_row(STUDY, "RECAL", r, 0, r["t0_date"], b["n_train"], None, rc["m1"], rc["m2"], None, jf1, jf2))

    def st3(vals):
        return {"n": len(vals), "mean": lab.mean_or_none(vals), "p": lab.signflip(vals)}

    jud = [c for c in icalcs if c["r"]["stratum"] in lab.INTL_STRATA]
    size_table = [{"id": c["r"]["id"], "t0": lab.dstr(c["r"]["t0_date"]), "era": c["r"]["stratum"],
                   "c": c["recal"]["c"], "delta": c["recal"]["delta"], "n_pairs_m1": c["recal"]["n_pairs_m1"],
                   "n_pairs_m2": c["recal"]["n_pairs_m2"], "d1": c["d1"], "d2": c["d2"]} for c in jud]
    e2 = [c for c in jud if c["d2"] is not None]
    calib = {str(h): {"BASE": lab.mean_or_none([c["base"]["m2"][h] for c in e2]), "RECAL": lab.mean_or_none([c["recal"]["m2"][h] for c in e2]),
                      "obs": float(np.mean([c["r"]["R"] <= h for c in e2])) if e2 else None, "n": len(e2)} for h in lab.HZ}
    e1 = [c for c in jud if c["d1"] is not None]
    cov = {m: (float(np.mean([c[k]["m1"]["0.1"] <= c["r"]["FD"] <= c[k]["m1"]["0.9"] for c in e1])) if e1 else None)
           for m, k in (("BASE", "base"), ("RECAL", "recal"))}
    us_j = [c for c in ucalcs if c["r"]["stratum"] in lab.US_STRATA]
    cl_rep = {"m1": [{"first": lab.dstr(c["first"]), "stratum": c["stratum"], "members": c["members"], "value": c["value"]} for c in cl1],
              "m2": [{"first": lab.dstr(c["first"]), "stratum": c["stratum"], "members": c["members"], "value": c["value"]} for c in cl2]}
    robust = {"us_report": {"m1": st3([c["d1"] for c in us_j if c["d1"] is not None]), "m2": st3([c["d2"] for c in us_j if c["d2"] is not None])},
              "episode_level": {"RECAL_M1": {"n": j1["n_episodes"], "p": j1["p_episode"]}, "RECAL_M2": {"n": j2["n_episodes"], "p": j2["p_episode"]}},
              "by_region": {k: {"m1": st3([c["d1"] for c in jud if c["r"]["market"] == k and c["d1"] is not None]),
                                "m2": st3([c["d2"] for c in jud if c["r"]["market"] == k and c["d2"] is not None])} for k in intl_ctx},
              "n_excluded_holdout": sum(1 for c in icalcs if c["r"]["stratum"] == "IX"),
              "n_unrecovered": sum(1 for c in jud if c["r"]["R"] is None)}

    by_id = {c["r"]["id"]: c for c in ucalcs}
    events = lab.events_rows(ctx, make_reader(by_id))
    current = current_block(ctx, us, allr, bases, smoke)
    summary = {"RECAL_M1 자기 보정 깊이": lab.summary_entry(j1), "RECAL_M2 자기 보정 회복": lab.summary_entry(j2),
               f"지금(Ken French {current['as_of']})": lab.now_line(current)}
    episodes = [{"id": c["r"]["id"], "t0": lab.dstr(c["r"]["t0_date"]), "era": c["r"]["stratum"], "dd0": c["r"]["dd0"], "FD": c["r"]["FD"],
                 "R": c["r"]["R"], "s1": c["s1"], "s2": c["s2"], "d1": c["d1"], "d2": c["d2"]} for c in icalcs + ucalcs]
    base_preds = {lab.dstr(c["r"]["t0_date"]): (c["base"]["m1"], c["base"]["m2"]) for c in ucalcs}
    res = {
        "study": STUDY, "lab_version": lab.LAB_VERSION, "rules": RULES_VERSION, "judge_version": lab.JUDGE_VERSION, "smoke": bool(smoke),
        "data": {"source": data["source"], "first_date": str(idx[0].date()), "last_date": str(idx[-1].date()), "n_days": int(len(idx)),
                 "intl": {k: {"source": "synthetic (smoke)" if smoke else f"Ken French {k}_3_Factors_Daily (USD, Mkt-RF + RF)",
                              "first_date": str(v.index[0].date()), "last_date": str(v.index[-1].date()), "n_episodes": len(intl_ctx[k]["eps"])}
                          for k, v in intl.items()},
                 "network_extras": {"spy": bool(current["spy_check"].get("available"))}},
        "constants": dict(lab.lab_constants(), NOW_DD0=NOW_DD0),
        "family": lab.family_block(STUDY),
        "power": rp.power_report(lab.YEARS_INTL, lab.K_FAMILY),
        "power_episode": {"RECAL_M1": lab.power_episode(j1["n"]["pooled"]), "RECAL_M2": lab.power_episode(j2["n"]["pooled"])},
        "verdicts": verdicts, "summary": summary, "detail": {"RECAL_M1": j1, "RECAL_M2": j2},
        "models": {"size_table": size_table, "calib": calib, "coverage80": cov, "clusters": cl_rep},
        "episodes": episodes, "events": events, "current": current, "robustness": robust,
        "v1_check": lab.v1_check(us, base_preds, smoke), "expected": EXPECTED, "notes": NOTES,
    }
    return res, rows


# ---------------------------------------------------------------- 보고서
def report(res: dict, smoke: bool) -> str:
    lab = L()
    R = lab.report_head(res, "기준선 자기 보정 — 과거 예측 오차로 치우침을 고치면", smoke, MODEL_NAMES, intl=True)
    R += ["n 은 군집 수다. 평균 d 는 군집 값의 평균. **미국 사건은 판정에 쓰지 않는다**(처방이 v1 의 보정 실패를 보고 골라졌기 때문).", ""]
    R += ["## 이 연구가 묻는 것", "",
          "- v1 기준선(과거 사건 분포)은 그때그때 예측을 내고, 시간이 지나면 실제 결과가 확정된다. 그 '과거 예측 오차'로 기준선의 치우침을 배워 다음 예측을 고치면(RECAL),",
          "  처음 보는 해외 급락에서 고치지 않은 기준선(BASE)보다 잘 맞히나.",
          "- 회복 확률: 확률을 로짓으로 바꾼 뒤 일정한 c_h 를 더한다(c_h 는 그때까지 확정된 쌍으로, 0 쪽으로 당기는 사전분포 sd 1). 1·2·3·5년 확률은 줄지 않게 정리.",
          "- 깊이: 실제 최종 깊이 − 예측 분위수의 같은 분위수를 n/(n + 10) 만큼 더한다(쌍 10개 미만이면 고치지 않음). 발생일 깊이보다 얕게는 고치지 않는다.", ""]
    cur = res["current"]
    b, rc = cur.get("base_now") or {}, cur.get("recal_now") or {}
    R += ["## 지금 읽기 (설명용 — 추천 아님)", "", lab.READING_HEADER, ""] + lab.reading_state_lines(cur)
    c = rc.get("c") or {}
    R += [f"기준: {cur.get('basis')}. **미국에서는 동기가 된 표본 안이라 참고만.**", "",
          "| 모델 | 최종 깊이 10/50/90% | 회복 1/2/5년 |", "|---|---|---|",
          f"| BASE | {lab.q3(b.get('m1'))} | {lab.r3(b.get('m2'))} |", f"| RECAL | {lab.q3(rc.get('m1'))} | {lab.r3(rc.get('m2'))} |", "",
          "지금 보정 크기: 로짓 c " + " · ".join(f"{h // 252}년 {lab.sgn(c.get(h, c.get(str(h))), 2)}" for h in lab.HZ)
          + f" · 깊이 δ(50%) {lab.pct((rc.get('delta') or {}).get('0.5'))} (쌍: 깊이 {rc.get('n_pairs_m1', '—')})", "",
          lab.spy_line(cur.get("spy_check") or {}), ""]
    R += ["## 사용자가 든 7개 사건", "", "미국 사건의 BASE vs RECAL(보고만 — v1 결과를 보고 고른 처방이라 미국 값은 판정에 쓰지 않음).", ""]
    R += lab.events_note_lines(res["events"])
    R += ["| 사건 | 발생일 | BASE 깊이 10/50/90% | RECAL 깊이 10/50/90% | BASE 회복 1/2/5년 | RECAL 회복 1/2/5년 | c(1년) | δ(50%) |", "|---|---|---|---|---|---|---|---|"]
    for e in res["events"]:
        st = e.get("study")
        if not st:
            R.append(f"| {e['label']} | — | | | | | | |")
            continue
        cc = st.get("c") or {}
        R.append(f"| {e['label']} | {e['episode_t0']} | {lab.q3(st['base_m1'])} | {lab.q3(st['recal_m1'])} | {lab.r3(st['base_m2'])} | {lab.r3(st['recal_m2'])} | "
                 f"{lab.sgn(cc.get('252', cc.get(252)), 2)} | {lab.pct((st.get('delta') or {}).get('0.5'))} |")
    R.append("")
    mb = res["models"]
    R += ["## 해외 판정 사건 — 보정 크기 (그 발생일까지 확정된 쌍으로)", "",
          "| 사건 | 층 | 쌍 수(깊이/회복 1년) | c 1년 / 2년 / 3년 / 5년 | δ 10% / 50% / 90% | d 모델 1 | d 모델 2 |", "|---|---|---|---|---|---|---|"]
    for s in sorted(mb["size_table"], key=lambda z: z["t0"]):
        cc, dl = s["c"] or {}, s["delta"] or {}
        npm2 = s["n_pairs_m2"] or {}
        R.append(f"| {s['id']} | {s['era']} | {s['n_pairs_m1'] if s['n_pairs_m1'] is not None else '—'}/{npm2.get('252', npm2.get(252, '—'))} | "
                 + " / ".join(lab.sgn(cc.get(str(h), cc.get(h)), 2) for h in lab.HZ) + " | "
                 + " / ".join(lab.pct(dl.get(k)) for k in ("0.1", "0.5", "0.9")) + f" | {lab.sgn(s['d1'])} | {lab.sgn(s['d2'])} |")
    R += ["", "### 보정표: 해외 판정 사건의 평균 예측 회복 확률 (전·후) vs 실제", "", "| 시점 | 사건 | BASE(전) | RECAL(후) | 실제 |", "|---|---|---|---|---|"]
    for h in lab.HZ:
        x = mb["calib"][str(h)]
        R.append(f"| {h // 252}년 | {x['n']} | {lab.pct(x['BASE'], 0, False)} | {lab.pct(x['RECAL'], 0, False)} | {lab.pct(x['obs'], 0, False)} |")
    cv = mb["coverage80"]
    R += ["", f"깊이 10~90% 구간 포함률(목표 80%): BASE {lab.pct(cv['BASE'], 0, False)} · RECAL {lab.pct(cv['RECAL'], 0, False)}.", ""]
    for mdl, title in (("m1", "모델 1(깊이)"), ("m2", "모델 2(회복)")):
        R += [f"### 군집 — {title}", "", "| 번호 | 첫 발생일 | 층 | 구성 사건 | 군집 값(평균 d) |", "|---|---|---|---|---|"]
        for n, x in enumerate(mb["clusters"][mdl], 1):
            R.append(f"| {n} | {x['first']} | {x['stratum']} | {', '.join(x['members'])} | {lab.sgn(x['value'])} |")
        if not mb["clusters"][mdl]:
            R.append("| — | 군집 없음 | | | |")
        R.append("")
    rb = res["robustness"]
    f3 = lambda x: f"{x['n']} · {lab.sgn(x['mean'])} · {lab.pval(x['p'])}"  # noqa: E731
    R += ["## 견고성 (보고만)", "", "| 항목 | 모델 1 (n · 평균 d · p) | 모델 2 (n · 평균 d · p) |", "|---|---|---|",
          f"| 사건 단위(군집 아님) | {rb['episode_level']['RECAL_M1']['n']} · — · {lab.pval(rb['episode_level']['RECAL_M1']['p'])} | "
          f"{rb['episode_level']['RECAL_M2']['n']} · — · {lab.pval(rb['episode_level']['RECAL_M2']['p'])} |"]
    for k, x in rb["by_region"].items():
        R.append(f"| {lab.REGION_LABELS.get(k, k)} | {f3(x['m1'])} | {f3(x['m2'])} |")
    R += [f"| 미국 A·B·C(판정 아님 — 처방의 동기가 된 표본) | {f3(rb['us_report']['m1'])} | {f3(rb['us_report']['m2'])} |", "",
          f"2024-10 이후 해외 사건(보고만): {rb['n_excluded_holdout']}개. 판정 층 해외 사건 중 자료 안 미회복(모델 2 에서 빠짐): {rb['n_unrecovered']}개.", ""]
    vc = res["v1_check"]
    R += ["v1 기준선 재현 확인(미국 발생일 BASE vs v1 결과 파일): "
          + (vc["skipped"] if "skipped" in vc else f"사건 {vc['n']} · 최대 차이 깊이 {lab.num(vc['max_abs_diff_m1'], 6)} · 회복 {lab.num(vc['max_abs_diff_m2'], 6)}"), ""]
    R += lab.report_tail(res, LIMITS, ["- c_h > 0 이면 과거 기준선이 회복 확률을 낮게 잡았다는 뜻(올려 고침), < 0 이면 반대.",
                                      "- δ_q > 0 이면 실제 최종 깊이가 예측보다 얕았다는 뜻(분위수를 위로 고침)."])
    return "\n".join(R) + "\n"


# ---------------------------------------------------------------- 실행
def run(smoke: bool) -> tuple:
    lab = L()
    data = lab.load_us(smoke)
    data["intl"] = lab.load_intl(smoke, required=True)
    return evaluate(data, smoke)


def main(argv=None) -> int:
    return L().run_main(argv, run, report)


if __name__ == "__main__":
    raise SystemExit(main())
