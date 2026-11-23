"""crash-internals-v1 — 시장 내부 상태(산업 폭·산업 간 상관·변동성 비)로 가른 '긴 약세장 확률'. 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/crash-internals-v1/run.py --out OUT --checkpoint CK [--smoke]

- 특징(발생일 종가까지): BREADTH = 49 산업 중 자기 252일 고점 대비 −15% 이하 비율, CORR12 = 12 산업 63일 일별 수익 평균 상관,
  VOLRATIO = 시장 21일/252일 실현 변동성 비.
- 능형 로지스틱(λ = 4) '긴 약세장 확률' → 과거 사건 두 갈래 재가중(INTERNAL) vs v1 기준선(모델 1 깊이·모델 2 회복).
- 판정 2개(INT_M1·INT_M2), 족 15개 공통 α = 0.05/15, 미국 A·B·C 사건 단위. 49 산업 자료가 없으면 예외. 계산은 수십 초라 체크포인트를 쓰지 않는다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STUDY = "crash-internals-v1"
RULES_VERSION = "crash-internals/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
FEATS = ("BREADTH", "CORR12", "VOLRATIO")
SINGLE_CODES = {"BREADTH": "INTERNAL_BREADTH", "CORR12": "INTERNAL_CORR", "VOLRATIO": "INTERNAL_VOLRATIO"}
NOW_DD0 = -0.15
MODEL_NAMES = {"INT_M1": "INTERNAL vs BASE (깊이, 발생일)", "INT_M2": "INTERNAL vs BASE (회복, 발생일)"}
EXPECTED = {
    "INT_M1": "FAIL 가능성이 높다(통과 약 8%). 발생일 가격 정보는 v1 에서 모두 약했다.",
    "INT_M2": "FAIL 가능성이 높다(통과 약 8%). 변동성 급등형(1987·2020)은 빠른 반등이었지만 2008 처럼 변동성 급등이 뒤에 오는 사건이 섞여 있다.",
}
NOTES = [
    "시대 C 사건(2008~2022)은 crash-cycle-model-v1 보고서에서 이미 보았다. 특징 3개는 v1 에 없던 정보다(BREADTH 의 −15% 는 사건 정의의 문턱을 그대로 씀).",
    "분류기 미적합 사건(라벨 있는 학습 6개 미만·한 갈래뿐·미수렴)은 두 판정 모두에서 빠진다(n_unfit). 기준선과 같은 값을 0 차이로 넣지 않는다.",
]
LIMITS = [
    "49 산업 구성은 시대에 따라 다르다(늦게 생긴 산업). 252일 이력이 있는 산업이 10개 미만이면 BREADTH 는 결측(표준화 뒤 0).",
    "상관은 63일 창 하나.",
    "사건 20개 남짓에 특징 3개 — 능형으로 줄여도 잡음이 크다.",
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


# ---------------------------------------------------------------- 특징
def feature_arrays(ctx: dict, ind12: pd.DataFrame, ind49: pd.DataFrame) -> dict:
    """날짜 축(ctx idx)에 맞춘 특징 계산용 배열. 각 위치 t 의 값은 t 종가까지의 자료만 쓴다."""
    lab = L()
    idx = ctx["idx"]
    return {"ddm": lab.dd252_matrix(lab.industry_tr(ind49.reindex(idx))), "R12": ind12.reindex(idx).to_numpy(dtype=float),
            "r": lab.logret(ctx["Lv"])}


def features_at(arr: dict, t: int) -> dict:
    lab = L()
    return {"BREADTH": lab.breadth(arr["ddm"], t), "CORR12": lab.corr12(arr["R12"], t), "VOLRATIO": lab.volratio(arr["r"], t)}


def episode_scores(r: dict, ts: dict, extra: dict) -> dict:
    lab = L()
    b = ts["base"]
    s1, s2 = {}, {}
    preds = {"BASE": (b["m1"], b["m2"])}
    if not ts["unfit"]:
        preds["INTERNAL"] = (ts["m1"], ts["m2"])
    preds.update(extra)
    for name, (q, F) in preds.items():
        if r["depth_settled"] and q is not None:
            s1[name] = lab.score_m1(r["FD"], q)
        if r["R"] is not None and F is not None:
            s2[name] = lab.score_m2(r["R"], F)
    return {"s1": s1, "s2": s2, "d1": s1["BASE"] - s1["INTERNAL"] if ("BASE" in s1 and "INTERNAL" in s1) else None,
            "d2": s2["BASE"] - s2["INTERNAL"] if ("BASE" in s2 and "INTERNAL" in s2) else None}


def make_reader(per: dict):
    def reader(ep: dict, d: int, mapping: str) -> dict:
        x = per[ep["id"]]
        ts = x["ts"]
        return {"features": x["feat"], "p_lb": ts["p_lb"], "pi": ts["pi"], "unfit": ts["unfit"], "base_m1": ts["base"]["m1"],
                "base_m2": ts["base"]["m2"], "m1": ts["m1"], "m2": ts["m2"]}

    return reader


def current_block(ctx: dict, us: list, xmap: dict, arr: dict, smoke: bool) -> dict:
    lab = L()
    cur = lab.reading_now(ctx)
    last = ctx["last"]
    D = pd.Timestamp(ctx["idx"][last])
    ep = lab.active_episode(ctx, last)
    if ep is not None:
        x_now, dd0, e_days = xmap[ep["id"]], ep["dd0"], int(last - ep["t0"])
        cur["basis"] = f"진행 중 사건({lab.dstr(ep['t0_date'])}) 발생일의 특징·깊이, 학습은 {lab.dstr(D)} 까지, 회복은 경과 {e_days}일 조건부"
        cur["features_now"] = dict(zip(FEATS, x_now))
        cur["features_today"] = features_at(arr, last)
    else:
        f = features_at(arr, last)
        x_now, dd0, e_days = [f[k] for k in FEATS], NOW_DD0, 0
        cur["basis"] = f"만약 오늘({lab.dstr(D)})이 발생일이라면(발생일 깊이 −15%, 특징은 오늘 값)"
        cur["features_now"] = f
    cur["internal_now"] = lab.two_state_now(us, D, xmap, x_now, dd0, e_days)
    cur["spy_check"] = lab.spy_check(cur["state"], smoke)
    return cur


# ---------------------------------------------------------------- 평가
def evaluate(data: dict, smoke: bool) -> tuple:
    from core import research_power as rp

    lab = L()
    v1 = lab.v1()
    if data.get("ind49") is None:
        raise RuntimeError("49 산업 자료를 받지 못함")
    ctx = lab.us_context(data)
    us = ctx["recs"]
    idx, last = ctx["idx"], ctx["last"]
    D_last = pd.Timestamp(idx[last])
    arr = feature_arrays(ctx, data["ind12"], data["ind49"])
    feats = {r["id"]: features_at(arr, r["t0"]) for r in us}
    xmap = {k: [v[f] for f in FEATS] for k, v in feats.items()}

    per: dict[str, Any] = {}
    for r in us:
        ts = lab.two_state_episode(us, r, xmap)
        singles = {f: lab.two_state_episode(us, r, xmap, cols=[i]) for i, f in enumerate(FEATS)}
        extra = {SINGLE_CODES[f]: (s["m1"], s["m2"]) for f, s in singles.items() if not s["unfit"]}
        per[r["id"]] = {"r": r, "feat": feats[r["id"]], "ts": ts, "singles": singles, "sc": episode_scores(r, ts, extra)}

    judged = [x for x in per.values() if x["r"]["stratum"] in lab.US_STRATA]
    dm1 = {s: [x["sc"]["d1"] for x in judged if x["r"]["stratum"] == s and x["sc"]["d1"] is not None] for s in lab.US_STRATA}
    dm2 = {s: [x["sc"]["d2"] for x in judged if x["r"]["stratum"] == s and x["sc"]["d2"] is not None] for s in lab.US_STRATA}
    j1, j2 = lab.judge_us(dm1), lab.judge_us(dm2)
    n_unfit = sum(1 for x in judged if x["ts"]["unfit"])
    j1["n_unfit"] = j2["n_unfit"] = n_unfit
    verdicts = {"INT_M1": j1["verdict"], "INT_M2": j2["verdict"]}

    rows: list = []
    for x in per.values():
        r, ts, sc = x["r"], x["ts"], x["sc"]
        jj = r["stratum"] in lab.US_STRATA
        j1f, j2f = int(jj and sc["d1"] is not None), int(jj and sc["d2"] is not None)
        b = ts["base"]
        rows.append(lab.pred_row(STUDY, "BASE", r, 0, r["t0_date"], b["n_train"], None, b["m1"], b["m2"], None, j1f, j2f))
        if not ts["unfit"]:
            rows.append(lab.pred_row(STUDY, "INTERNAL", r, 0, r["t0_date"], lab.n_train_of(ts["m1"], ts["n1"], ts["m2"], ts["n2"]),
                                     ts["p_lb"], ts["m1"], ts["m2"], None, j1f, j2f))
        for f, s in x["singles"].items():
            if not s["unfit"]:
                rows.append(lab.pred_row(STUDY, SINGLE_CODES[f], r, 0, r["t0_date"], lab.n_train_of(s["m1"], s["n1"], s["m2"], s["n2"]),
                                         s["p_lb"], s["m1"], s["m2"]))

    def pair_stats(code: str, key: str) -> dict:
        vals = [x["sc"][key]["BASE"] - x["sc"][key][code] for x in judged if "BASE" in x["sc"][key] and code in x["sc"][key]]
        return {"n": len(vals), "mean": lab.mean_or_none(vals), "p": lab.signflip(vals)}

    singles_rep = {SINGLE_CODES[f]: {"m1": pair_stats(SINGLE_CODES[f], "s1"), "m2": pair_stats(SINGLE_CODES[f], "s2")} for f in FEATS}
    skill = lab.classification_skill([(lab.lb_label(x["r"], D_last), x["ts"]["p_lb"], x["ts"]["pi"]) for x in judged if not x["ts"]["unfit"]])
    C_last, y_last = lab.cls_set(us, D_last)
    fit_last = lab.fit_ridge_logit(np.array([xmap[j["id"]] for j in C_last], dtype=float).reshape(len(C_last), len(FEATS)), y_last)
    fits = [x["ts"]["fit"] for x in judged if not x["ts"]["unfit"]]
    slopes = {"last_fit": {f: (float(fit_last["beta"][i]) if fit_last["keep"][i] else None) for i, f in enumerate(FEATS)},
              "last_fit_n": len(C_last), "last_fit_ok": lab.fit_ok(fit_last),
              "share_positive": {f: (float(np.mean([ft["beta"][i] > 0 for ft in fits])) if fits else None) for i, f in enumerate(FEATS)},
              "n_fits": len(fits)}
    m_by = {}
    for s in ("A", "B", "C", "all"):
        xs = [x for x in judged if s == "all" or x["r"]["stratum"] == s]
        e1 = [x for x in xs if x["sc"]["d1"] is not None]
        e2 = [x for x in xs if x["sc"]["d2"] is not None]
        m_by[s] = {"n1": len(e1), "n2": len(e2), "n_unfit": sum(1 for x in xs if x["ts"]["unfit"]),
                   "m1": {m: lab.mean_or_none([x["sc"]["s1"].get(m) for x in e1]) for m in ("BASE", "INTERNAL")},
                   "m2": {m: lab.mean_or_none([x["sc"]["s2"].get(m) for x in e2]) for m in ("BASE", "INTERNAL")}}
    e2 = [x for x in judged if x["sc"]["d2"] is not None]
    calib = {str(h): {"BASE": lab.mean_or_none([x["ts"]["base"]["m2"][h] for x in e2]), "INTERNAL": lab.mean_or_none([x["ts"]["m2"][h] for x in e2]),
                      "obs": float(np.mean([x["r"]["R"] <= h for x in e2])) if e2 else None, "n": len(e2)} for h in lab.HZ}
    ab = lambda dm: [v for s in ("A", "B") for v in dm[s]]  # noqa: E731
    robust = {"ab_only": {k: {"n": len(ab(dm)), "mean": lab.mean_or_none(ab(dm)), "p": lab.signflip(ab(dm))} for k, dm in (("INT_M1", dm1), ("INT_M2", dm2))},
              "cluster_us": {"INT_M1": v1.cluster_p([(x["r"]["t0"], x["r"]["end1"], x["sc"]["d1"]) for x in judged if x["sc"]["d1"] is not None]),
                             "INT_M2": v1.cluster_p([(x["r"]["t0"], x["r"]["rec"], x["sc"]["d2"]) for x in judged if x["sc"]["d2"] is not None])},
              "singles": singles_rep,
              "n_feature_missing": {f: sum(1 for x in judged if lab.fin(x["feat"][f]) is None) for f in FEATS}}

    events = lab.events_rows(ctx, make_reader(per))
    current = current_block(ctx, us, xmap, arr, smoke)
    summary = {"INT_M1 시장 내부 깊이": lab.summary_entry(j1), "INT_M2 시장 내부 회복": lab.summary_entry(j2),
               f"지금(Ken French {current['as_of']})": lab.now_line(current)}
    episodes = [{"id": x["r"]["id"], "t0": lab.dstr(x["r"]["t0_date"]), "era": x["r"]["stratum"], "dd0": x["r"]["dd0"], "FD": x["r"]["FD"],
                 "R": x["r"]["R"], "features": x["feat"], "p_lb": x["ts"]["p_lb"], "pi": x["ts"]["pi"], "unfit": x["ts"]["unfit"],
                 "n_cls": x["ts"]["n_cls"], "s1": x["sc"]["s1"], "s2": x["sc"]["s2"], "d1": x["sc"]["d1"], "d2": x["sc"]["d2"]} for x in per.values()]
    base_preds = {lab.dstr(x["r"]["t0_date"]): (x["ts"]["base"]["m1"], x["ts"]["base"]["m2"]) for x in per.values()}
    res = {
        "study": STUDY, "lab_version": lab.LAB_VERSION, "rules": RULES_VERSION, "judge_version": lab.JUDGE_VERSION, "smoke": bool(smoke),
        "data": {"source": data["source"], "first_date": str(idx[0].date()), "last_date": str(idx[-1].date()), "n_days": int(len(idx)),
                 "ind12_columns": int(data["ind12"].shape[1]), "ind49_columns": int(data["ind49"].shape[1]),
                 "network_extras": {"spy": bool(current["spy_check"].get("available"))}},
        "constants": dict(lab.lab_constants(), FEATS=list(FEATS), NOW_DD0=NOW_DD0),
        "family": lab.family_block(STUDY),
        "power": rp.power_report(lab.YEARS_US, lab.K_FAMILY),
        "power_episode": {"INT_M1": lab.power_episode(j1["n"]["pooled"]), "INT_M2": lab.power_episode(j2["n"]["pooled"])},
        "verdicts": verdicts, "summary": summary, "detail": {"INT_M1": j1, "INT_M2": j2},
        "models": {"by_stratum": m_by, "calib": calib, "skill": skill, "slopes": slopes},
        "episodes": episodes, "events": events, "current": current, "robustness": robust,
        "v1_check": lab.v1_check(us, base_preds, smoke), "expected": EXPECTED, "notes": NOTES,
    }
    return res, rows


# ---------------------------------------------------------------- 보고서
def _fv(lab, v, nd=3) -> str:
    return "—" if lab.fin(v) is None else f"{v:.{nd}f}"


def report(res: dict, smoke: bool) -> str:
    lab = L()
    R = lab.report_head(res, "시장 내부 상태 — 산업 폭·산업 간 상관·변동성 비로 가른 긴 약세장 확률", smoke, MODEL_NAMES)
    R += [f"분류기 미적합으로 판정에서 빠진 A·B·C 사건: {res['detail']['INT_M1']['n_unfit']}개.", ""]
    R += ["## 이 연구가 묻는 것", "",
          "- 급락 발생일의 시장 내부 상태 세 가지 — 49 산업 중 자기 1년 고점보다 15% 이상 빠진 산업 비율(BREADTH, 하락의 폭), 12 산업 간 63일 평균 상관(CORR12, "
          "모두 같이 움직이는 정도), 시장의 최근 1개월 대 1년 변동성 비(VOLRATIO, 갑작스러운 충격인지) — 로 '252거래일 안에 전고점을 회복하지 못하는 긴 약세장' 확률을 세운다.",
          "- 그 확률로 과거 사건을 '긴 약세장'과 '빠른 반등' 두 갈래로 다시 가중하면(INTERNAL) v1 기준선보다 최종 깊이·회복을 잘 맞히나.", ""]
    cur = res["current"]
    mn = cur.get("internal_now") or {}
    fnow = cur.get("features_now") or {}
    R += ["## 지금 읽기 (설명용 — 추천 아님)", "", lab.READING_HEADER, ""] + lab.reading_state_lines(cur)
    R += [f"기준: {cur.get('basis')}.", "", "특징 값: " + " · ".join(f"{k} {_fv(lab, fnow.get(k))}" for k in FEATS)
          + " (BREADTH = 비율 0~1, CORR12 = 상관 −1~1, VOLRATIO = 배수)", ""]
    if cur.get("features_today"):
        R += ["오늘 값: " + " · ".join(f"{k} {_fv(lab, cur['features_today'].get(k))}" for k in FEATS), ""]
    if mn.get("unfit"):
        R += [f"INTERNAL 읽기: {mn['unfit']}.", ""]
    else:
        R += [f"긴 약세장 확률 p = {lab.pct(mn.get('p_lb'), 0, False)} (기준 확률 π = {lab.pct(mn.get('pi'), 0, False)}, 라벨 있는 학습 사건 {mn.get('n_cls')}개)", "",
              "| 모델 | 최종 깊이 10/50/90% | 회복 1/2/5년 |", "|---|---|---|",
              f"| BASE | {lab.q3(mn.get('base_m1'))} | {lab.r3(mn.get('base_m2'))} |", f"| INTERNAL | {lab.q3(mn.get('m1'))} | {lab.r3(mn.get('m2'))} |", ""]
    R += [lab.spy_line(cur.get("spy_check") or {}), ""]
    R += ["## 사용자가 든 7개 사건", ""] + lab.events_note_lines(res["events"])
    R += ["### 발생일 읽기 (그 사건 발생일 종가까지의 정보만)", "",
          "| 사건 | 발생일 | BREADTH | CORR12 | VOLRATIO | p_lb (π) | BASE 깊이 10/50/90% | INTERNAL 깊이 10/50/90% | BASE 회복 1/2/5년 | INTERNAL 회복 1/2/5년 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for e in res["events"]:
        st = e.get("study")
        if not st:
            R.append(f"| {e['label']} | — | | | | | | | | |")
            continue
        f = st["features"]
        pl = "미적합" if st["unfit"] else f"{lab.pct(st['p_lb'], 0, False)} ({lab.pct(st['pi'], 0, False)})"
        R.append(f"| {e['label']} | {e['episode_t0']} | {_fv(lab, f['BREADTH'])} | {_fv(lab, f['CORR12'])} | {_fv(lab, f['VOLRATIO'])} | {pl} | "
                 f"{lab.q3(st['base_m1'])} | {lab.q3(st['m1'])} | {lab.r3(st['base_m2'])} | {lab.r3(st['m2'])} |")
    R.append("")
    mb = res["models"]
    f100 = lambda v: "—" if lab.fin(v) is None else f"{v * 100:.2f}"  # noqa: E731
    R += ["## 모델 1·2 — 층별 평균 점수", "", "핀볼 = 전고점 대비 %p, 브라이어 = 0~1(둘 다 낮을수록 잘 맞힘). 평가 = 쌍이 있는 판정 층 사건.", "",
          "| 층 | 모델 1 평가 | 핀볼 BASE | 핀볼 INTERNAL | 모델 2 평가 | 브라이어 BASE | 브라이어 INTERNAL | 미적합 |", "|---|---|---|---|---|---|---|---|"]
    for s in ("A", "B", "C", "all"):
        x = mb["by_stratum"][s]
        R.append(f"| {s if s != 'all' else 'A+B+C'} | {x['n1']} | {f100(x['m1']['BASE'])} | {f100(x['m1']['INTERNAL'])} | {x['n2']} | "
                 f"{lab.num(x['m2']['BASE'])} | {lab.num(x['m2']['INTERNAL'])} | {x['n_unfit']} |")
    R += ["", "### 보정: 평균 예측 회복 확률 vs 실제 비율", "", "| 시점 | 사건 | BASE | INTERNAL | 실제 |", "|---|---|---|---|---|"]
    for h in lab.HZ:
        c = mb["calib"][str(h)]
        R.append(f"| {h // 252}년 | {c['n']} | {lab.pct(c['BASE'], 0, False)} | {lab.pct(c['INTERNAL'], 0, False)} | {lab.pct(c['obs'], 0, False)} |")
    sk, sl = mb["skill"], mb["slopes"]
    R += ["", "### 분류 실력과 기울기 (보고만)", "",
          f"- 판정 층 사건 {sk['n']}개의 실제 '긴 약세장' 라벨에 대한 브라이어: p_lb {lab.num(sk['brier_p'])} vs 기준 확률 π {lab.num(sk['brier_pi'])} (낮을수록 잘 가름).",
          f"- 마지막 날 적합(라벨 있는 사건 {sl['last_fit_n']}개, 적합 {'가능' if sl['last_fit_ok'] else '불가'})의 표준화 기울기: "
          + " · ".join(f"{f} {lab.sgn(sl['last_fit'][f], 3)}" for f in FEATS) + " (양수 = 값이 클수록 긴 약세장 쪽).",
          f"- 판정 사건 예측 때 적합 {sl['n_fits']}개에서 기울기가 양수였던 비율: " + " · ".join(f"{f} {lab.pct(sl['share_positive'][f], 0, False)}" for f in FEATS), ""]
    rb = res["robustness"]
    f3 = lambda x: f"{x['n']} · {lab.sgn(x['mean'])} · {lab.pval(x['p'])}"  # noqa: E731
    R += ["## 견고성 (보고만)", "", "라벨을 붙이지 않는다. 값은 n · 평균 d · 한쪽 부호 뒤집기 p.", "", "| 항목 | 모델 1 | 모델 2 |", "|---|---|---|",
          f"| A+B 만(v1 방식) | {f3(rb['ab_only']['INT_M1'])} | {f3(rb['ab_only']['INT_M2'])} |",
          f"| 미국 겹침 군집 p | {lab.pval(rb['cluster_us']['INT_M1'])} | {lab.pval(rb['cluster_us']['INT_M2'])} |"]
    for code, x in rb["singles"].items():
        R.append(f"| 특징 하나 {code} | {f3(x['m1'])} | {f3(x['m2'])} |")
    R += ["", "판정 층 사건 중 특징 결측(표준화 뒤 평균 대치): " + " · ".join(f"{f} {n}개" for f, n in rb["n_feature_missing"].items()), ""]
    vc = res["v1_check"]
    R += ["v1 기준선 재현 확인(미국 발생일 BASE vs v1 결과 파일): "
          + (vc["skipped"] if "skipped" in vc else f"사건 {vc['n']} · 최대 차이 깊이 {lab.num(vc['max_abs_diff_m1'], 6)} · 회복 {lab.num(vc['max_abs_diff_m2'], 6)}"), ""]
    R += lab.report_tail(res, LIMITS, ["- p_lb = 긴 약세장(252거래일 안 회복 못 함) 확률, π = 그날 라벨을 아는 과거 사건의 긴 약세장 비율. 기울기가 0 이면 p = π 라 INTERNAL = BASE.",
                                      "- 특징은 모두 발생일 종가까지의 자료로 계산한다."])
    return "\n".join(R) + "\n"


# ---------------------------------------------------------------- 실행
def run(smoke: bool) -> tuple:
    return evaluate(L().load_us(smoke), smoke)


def main(argv=None) -> int:
    return L().run_main(argv, run, report)


if __name__ == "__main__":
    raise SystemExit(main())
