"""crash-industry-transfer-v1 — 업종 급락에서 배운 '긴 약세장' 판별식을 시장에 옮기기. 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/crash-industry-transfer-v1/run.py --out OUT --checkpoint CK [--smoke]

- 49 산업 각각의 총수익 지수에서 v1 과 같은 정의(252일 고점 −15%)로 업종 급락 수천 건을 만들고, 발생일 특징 4개(DD0·SPEED·VOLRATIO·RUNUP)로
  '긴 약세장(252거래일 안 회복 못 함)' 능형 로지스틱 기울기를 배운다(업종 표준화).
- 시장 사건에는 그 기울기만 옮기고, 기준 확률·중심은 시장 사건 풀에서 잡아 과거 시장 사건을 두 갈래로 재가중(XFER) vs v1 기준선.
- 판정 2개(XFER_M1·XFER_M2), 족 15개 공통 α = 0.05/15, 미국 A·B·C 사건 단위. 49 산업 자료가 없으면 예외. 계산은 1분 안팎이라 체크포인트를 쓰지 않는다.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STUDY = "crash-industry-transfer-v1"
RULES_VERSION = "crash-industry-transfer/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
FEATS = ("DD0", "SPEED", "VOLRATIO", "RUNUP")
NOW_DD0 = -0.15
SLOPE_DATES = ("1946-01-01", "1967-01-01", "2008-01-01")   # 보고용 적합 시점(+ 마지막 날)
MIN_IND_DAYS = 300                                        # 사건을 만들 수 있는 최소 업종 이력(252일 고점 + 여유)
MODEL_NAMES = {"XFER_M1": "XFER vs BASE (깊이, 발생일)", "XFER_M2": "XFER vs BASE (회복, 발생일)"}
EXPECTED = {
    "XFER_M1": "FAIL 가능성이 높다(통과 약 8%). 업종 급락은 시장보다 변동성이 크고 고유 충격이 많아 관계가 옮겨지지 않을 수 있다.",
    "XFER_M2": "FAIL 가능성이 높다(통과 약 8%). 업종 급락은 시장보다 변동성이 크고 고유 충격이 많아 관계가 옮겨지지 않을 수 있다.",
}
NOTES = [
    "시대 C 사건(2008~2022)은 crash-cycle-model-v1 보고서에서 이미 보았다. 업종 급락은 이 질문에 처음 쓴다.",
    "기울기는 업종 사건으로만 배우고 시장 사건은 중심·기준 확률에만 쓴다. p_lb 도 시장 라벨 집합 기준(업종 기준 확률이 아님).",
    "분류기 미적합 사건은 두 판정 모두에서 빠진다(n_unfit). 기준선과 같은 값을 0 차이로 넣지 않는다.",
]
LIMITS = [
    "업종은 시장과 변동성·고유 위험이 다르다.",
    "업종 급락은 시장 급락 때 몰려 있다(실질 표본은 사건 수보다 작다).",
    "산업 구성이 시대마다 다르다(늦게 생긴 산업은 그때부터 사건을 만든다).",
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
def ep_features(Lv: np.ndarray, t0: int, tP: int, dd0: float, r: np.ndarray) -> list:
    """[DD0, SPEED, VOLRATIO, RUNUP] — 모두 t0 종가까지."""
    lab = L()
    runup = float(math.log(Lv[tP] / Lv[tP - 504])) if tP >= 504 else float("nan")
    return [float(dd0), float(math.log(max(t0 - tP, 1))), lab.volratio(r, t0), runup]


def industry_events(ind49: pd.DataFrame) -> tuple:
    """업종 사건 목록과 특징: 열마다 첫 유효일부터 (1 + r).cumprod(), v1 정의로 사건."""
    lab = L()
    recs, xmap, per_col = [], {}, {}
    for k in ind49.columns:
        s = ind49[k]
        fv = s.first_valid_index()
        if fv is None:
            continue
        s = s.loc[fv:].fillna(0.0)
        if len(s) < MIN_IND_DAYS:
            continue
        I = (1 + s).cumprod()
        mc = lab.market_context(I, f"IND:{k}")
        r = lab.logret(mc["Lv"])
        for e in mc["eps"]:
            xmap[e["id"]] = ep_features(mc["Lv"], e["t0"], e["tP"], e["dd0"], r)
        recs += mc["eps"]
        per_col[str(k)] = len(mc["eps"])
    return recs, xmap, per_col


def market_features(ctx: dict) -> dict:
    lab = L()
    r = lab.logret(ctx["Lv"])
    return {e["id"]: [float(e["dd0"]), float(e["feat"]["SPEED"]), lab.volratio(r, e["t0"]), float(e["feat"]["RUNUP"])] for e in ctx["recs"]}


def episode_scores(r: dict, ts: dict) -> dict:
    lab = L()
    b = ts["base"]
    s1, s2 = {}, {}
    preds = {"BASE": (b["m1"], b["m2"])}
    if not ts["unfit"]:
        preds["XFER"] = (ts["m1"], ts["m2"])
    for name, (q, F) in preds.items():
        if r["depth_settled"] and q is not None:
            s1[name] = lab.score_m1(r["FD"], q)
        if r["R"] is not None and F is not None:
            s2[name] = lab.score_m2(r["R"], F)
    return {"s1": s1, "s2": s2, "d1": s1["BASE"] - s1["XFER"] if len(s1) == 2 else None, "d2": s2["BASE"] - s2["XFER"] if len(s2) == 2 else None}


def fit_at(ind_recs: list, ind_xmap: dict, D) -> dict:
    lab = L()
    C, y = lab.cls_set(ind_recs, D)
    fit = lab.fit_ridge_logit(np.array([ind_xmap[j["id"]] for j in C], dtype=float).reshape(len(C), len(FEATS)), y)
    return {"date": lab.dstr(D), "n": len(C), "n_pos": int(sum(y)), "ok": lab.fit_ok(fit),
            "beta": {f: (float(fit["beta"][i]) if fit["keep"][i] else None) for i, f in enumerate(FEATS)}}


def make_reader(per: dict):
    def reader(ep: dict, d: int, mapping: str) -> dict:
        x = per[ep["id"]]
        ts = x["ts"]
        return {"features": dict(zip(FEATS, x["x"])), "p_lb": ts["p_lb"], "pi": ts["pi"], "unfit": ts["unfit"],
                "base_m1": ts["base"]["m1"], "base_m2": ts["base"]["m2"], "m1": ts["m1"], "m2": ts["m2"]}

    return reader


def current_block(ctx: dict, us: list, xmap: dict, ind_recs: list, ind_xmap: dict, smoke: bool) -> dict:
    lab = L()
    v1 = lab.v1()
    cur = lab.reading_now(ctx)
    last, Lv = ctx["last"], ctx["Lv"]
    D = pd.Timestamp(ctx["idx"][last])
    ep = lab.active_episode(ctx, last)
    if ep is not None:
        x_now, dd0, e_days = xmap[ep["id"]], ep["dd0"], int(last - ep["t0"])
        cur["basis"] = f"진행 중 사건({lab.dstr(ep['t0_date'])}) 발생일의 특징·깊이, 학습은 {lab.dstr(D)} 까지, 회복은 경과 {e_days}일 조건부"
    else:
        lo = last - v1.HIGH_WIN + 1
        tP = lo + int(np.argmax(Lv[lo:last + 1]))
        x_now = ep_features(Lv, last, tP, NOW_DD0, lab.logret(Lv))
        dd0, e_days = NOW_DD0, 0
        cur["basis"] = f"만약 오늘({lab.dstr(D)})이 발생일이라면(발생일 깊이 −15%, 속도·변동성 비·직전 상승은 오늘 값)"
    cur["features_now"] = dict(zip(FEATS, x_now))
    cur["xfer_now"] = lab.two_state_now(us, D, xmap, x_now, dd0, e_days, cls_recs=ind_recs, cls_xmap=ind_xmap, plb_recs=us, plb_xmap=xmap)
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
    xmap = market_features(ctx)
    ind_recs, ind_xmap, per_col = industry_events(data["ind49"])

    per: dict[str, Any] = {}
    for r in us:
        ts = lab.two_state_episode(us, r, xmap, cls_recs=ind_recs, cls_xmap=ind_xmap, plb_recs=us, plb_xmap=xmap)
        per[r["id"]] = {"r": r, "x": xmap[r["id"]], "ts": ts, "sc": episode_scores(r, ts)}

    judged = [x for x in per.values() if x["r"]["stratum"] in lab.US_STRATA]
    dm1 = {s: [x["sc"]["d1"] for x in judged if x["r"]["stratum"] == s and x["sc"]["d1"] is not None] for s in lab.US_STRATA}
    dm2 = {s: [x["sc"]["d2"] for x in judged if x["r"]["stratum"] == s and x["sc"]["d2"] is not None] for s in lab.US_STRATA}
    j1, j2 = lab.judge_us(dm1), lab.judge_us(dm2)
    j1["n_unfit"] = j2["n_unfit"] = sum(1 for x in judged if x["ts"]["unfit"])
    verdicts = {"XFER_M1": j1["verdict"], "XFER_M2": j2["verdict"]}

    rows: list = []
    for x in per.values():
        r, ts, sc = x["r"], x["ts"], x["sc"]
        jj = r["stratum"] in lab.US_STRATA
        j1f, j2f = int(jj and sc["d1"] is not None), int(jj and sc["d2"] is not None)
        b = ts["base"]
        rows.append(lab.pred_row(STUDY, "BASE", r, 0, r["t0_date"], b["n_train"], None, b["m1"], b["m2"], None, j1f, j2f))
        if not ts["unfit"]:
            rows.append(lab.pred_row(STUDY, "XFER", r, 0, r["t0_date"], lab.n_train_of(ts["m1"], ts["n1"], ts["m2"], ts["n2"]),
                                     ts["p_lb"], ts["m1"], ts["m2"], None, j1f, j2f))

    ind_lab = [lab.lb_label(j, D_last) for j in ind_recs]
    mkt_lab = [lab.lb_label(j, D_last) for j in us]
    il = [v for v in ind_lab if v is not None]
    ml = [v for v in mkt_lab if v is not None]
    sample = {"n_industry_events": len(ind_recs), "n_industry_labeled": len(il), "industry_lb_rate": float(np.mean(il)) if il else None,
              "n_market_labeled": len(ml), "market_lb_rate": float(np.mean(ml)) if ml else None, "n_columns_used": len(per_col),
              "first_industry_event": lab.dstr(min((j["t0_date"] for j in ind_recs), default=None)),
              "slopes": [fit_at(ind_recs, ind_xmap, pd.Timestamp(d)) for d in SLOPE_DATES] + [fit_at(ind_recs, ind_xmap, D_last)],
              "n_cls_at_first_judged": next((x["ts"]["n_cls"] for x in sorted(judged, key=lambda z: z["r"]["t0"]) if x["sc"]["d1"] is not None), None)}
    skill = lab.classification_skill([(lab.lb_label(x["r"], D_last), x["ts"]["p_lb"], x["ts"]["pi"]) for x in judged if not x["ts"]["unfit"]])
    m_by = {}
    for s in ("A", "B", "C", "all"):
        xs = [x for x in judged if s == "all" or x["r"]["stratum"] == s]
        e1 = [x for x in xs if x["sc"]["d1"] is not None]
        e2 = [x for x in xs if x["sc"]["d2"] is not None]
        m_by[s] = {"n1": len(e1), "n2": len(e2), "n_unfit": sum(1 for x in xs if x["ts"]["unfit"]),
                   "m1": {m: lab.mean_or_none([x["sc"]["s1"].get(m) for x in e1]) for m in ("BASE", "XFER")},
                   "m2": {m: lab.mean_or_none([x["sc"]["s2"].get(m) for x in e2]) for m in ("BASE", "XFER")}}
    e2 = [x for x in judged if x["sc"]["d2"] is not None]
    calib = {str(h): {"BASE": lab.mean_or_none([x["ts"]["base"]["m2"][h] for x in e2]), "XFER": lab.mean_or_none([x["ts"]["m2"][h] for x in e2]),
                      "obs": float(np.mean([x["r"]["R"] <= h for x in e2])) if e2 else None, "n": len(e2)} for h in lab.HZ}
    ab = lambda dm: [v for s in ("A", "B") for v in dm[s]]  # noqa: E731
    robust = {"ab_only": {k: {"n": len(ab(dm)), "mean": lab.mean_or_none(ab(dm)), "p": lab.signflip(ab(dm))} for k, dm in (("XFER_M1", dm1), ("XFER_M2", dm2))},
              "cluster_us": {"XFER_M1": v1.cluster_p([(x["r"]["t0"], x["r"]["end1"], x["sc"]["d1"]) for x in judged if x["sc"]["d1"] is not None]),
                             "XFER_M2": v1.cluster_p([(x["r"]["t0"], x["r"]["rec"], x["sc"]["d2"]) for x in judged if x["sc"]["d2"] is not None])}}

    events = lab.events_rows(ctx, make_reader(per))
    current = current_block(ctx, us, xmap, ind_recs, ind_xmap, smoke)
    summary = {"XFER_M1 업종 이전 깊이": lab.summary_entry(j1), "XFER_M2 업종 이전 회복": lab.summary_entry(j2),
               f"지금(Ken French {current['as_of']})": lab.now_line(current)}
    episodes = [{"id": x["r"]["id"], "t0": lab.dstr(x["r"]["t0_date"]), "era": x["r"]["stratum"], "dd0": x["r"]["dd0"], "FD": x["r"]["FD"],
                 "R": x["r"]["R"], "features": dict(zip(FEATS, x["x"])), "p_lb": x["ts"]["p_lb"], "pi": x["ts"]["pi"], "unfit": x["ts"]["unfit"],
                 "n_cls": x["ts"]["n_cls"], "s1": x["sc"]["s1"], "s2": x["sc"]["s2"], "d1": x["sc"]["d1"], "d2": x["sc"]["d2"]} for x in per.values()]
    base_preds = {lab.dstr(x["r"]["t0_date"]): (x["ts"]["base"]["m1"], x["ts"]["base"]["m2"]) for x in per.values()}
    res = {
        "study": STUDY, "lab_version": lab.LAB_VERSION, "rules": RULES_VERSION, "judge_version": lab.JUDGE_VERSION, "smoke": bool(smoke),
        "data": {"source": data["source"], "first_date": str(idx[0].date()), "last_date": str(idx[-1].date()), "n_days": int(len(idx)),
                 "ind49_columns": int(data["ind49"].shape[1]), "industry_events_per_column": per_col,
                 "network_extras": {"spy": bool(current["spy_check"].get("available"))}},
        "constants": dict(lab.lab_constants(), FEATS=list(FEATS), NOW_DD0=NOW_DD0, SLOPE_DATES=list(SLOPE_DATES), MIN_IND_DAYS=MIN_IND_DAYS),
        "family": lab.family_block(STUDY),
        "power": rp.power_report(lab.YEARS_US, lab.K_FAMILY),
        "power_episode": {"XFER_M1": lab.power_episode(j1["n"]["pooled"]), "XFER_M2": lab.power_episode(j2["n"]["pooled"])},
        "verdicts": verdicts, "summary": summary, "detail": {"XFER_M1": j1, "XFER_M2": j2},
        "models": {"by_stratum": m_by, "calib": calib, "skill": skill, "industry_sample": sample},
        "episodes": episodes, "events": events, "current": current, "robustness": robust,
        "v1_check": lab.v1_check(us, base_preds, smoke), "expected": EXPECTED, "notes": NOTES,
    }
    return res, rows


# ---------------------------------------------------------------- 보고서
def _fv(lab, v, nd=3) -> str:
    return "—" if lab.fin(v) is None else f"{v:+.{nd}f}"


def report(res: dict, smoke: bool) -> str:
    lab = L()
    R = lab.report_head(res, "업종 급락에서 배우기 — 업종 판별식을 시장 급락에 옮기면", smoke, MODEL_NAMES)
    R += [f"분류기 미적합으로 판정에서 빠진 A·B·C 사건: {res['detail']['XFER_M1']['n_unfit']}개.", ""]
    R += ["## 이 연구가 묻는 것", "",
          "- 시장 급락은 약 28개뿐이라 '어떤 급락이 길게 끄나'의 관계를 시장 사건만으로는 추정하기 어렵다. 49 산업 각각에서 같은 정의(업종 총수익이 1년 고점보다 15% 아래)로 "
          "업종 급락을 모으면 훨씬 많다.",
          "- 업종 급락에서 발생일 특징 4개 — 발생일 깊이(DD0), 고점에서 발생일까지 속도(SPEED, 거래일 로그), 1개월/1년 변동성 비(VOLRATIO), 직전 2년 상승(RUNUP) — 와 "
          "'252거래일 안에 회복 못 함'의 관계(기울기)를 배운다.",
          "- 그 기울기만 시장에 옮기고(기준 확률은 시장 것), 과거 시장 사건을 두 갈래로 다시 가중하면(XFER) v1 기준선보다 최종 깊이·회복을 잘 맞히나.", ""]
    cur = res["current"]
    mn = cur.get("xfer_now") or {}
    fnow = cur.get("features_now") or {}
    R += ["## 지금 읽기 (설명용 — 추천 아님)", "", lab.READING_HEADER, ""] + lab.reading_state_lines(cur)
    R += [f"기준: {cur.get('basis')}.", "", "특징 값: " + " · ".join(f"{k} {_fv(lab, fnow.get(k))}" for k in FEATS), ""]
    if mn.get("unfit"):
        R += [f"XFER 읽기: {mn['unfit']}.", ""]
    else:
        R += [f"긴 약세장 확률 p = {lab.pct(mn.get('p_lb'), 0, False)} (시장 기준 확률 π = {lab.pct(mn.get('pi'), 0, False)}, 기울기는 업종 사건 {mn.get('n_cls')}개로 학습)", "",
              "| 모델 | 최종 깊이 10/50/90% | 회복 1/2/5년 |", "|---|---|---|",
              f"| BASE | {lab.q3(mn.get('base_m1'))} | {lab.r3(mn.get('base_m2'))} |", f"| XFER | {lab.q3(mn.get('m1'))} | {lab.r3(mn.get('m2'))} |", ""]
    R += [lab.spy_line(cur.get("spy_check") or {}), ""]
    R += ["## 사용자가 든 7개 사건", ""] + lab.events_note_lines(res["events"])
    R += ["### 발생일 읽기 (그 사건 발생일 종가까지의 정보만)", "",
          "| 사건 | 발생일 | DD0 | SPEED | VOLRATIO | RUNUP | p_lb (π) | BASE 깊이 10/50/90% | XFER 깊이 10/50/90% | BASE 회복 1/2/5년 | XFER 회복 1/2/5년 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in res["events"]:
        st = e.get("study")
        if not st:
            R.append(f"| {e['label']} | — | | | | | | | | | |")
            continue
        f = st["features"]
        pl = "미적합" if st["unfit"] else f"{lab.pct(st['p_lb'], 0, False)} ({lab.pct(st['pi'], 0, False)})"
        R.append(f"| {e['label']} | {e['episode_t0']} | " + " | ".join(_fv(lab, f[k]) for k in FEATS) + f" | {pl} | "
                 f"{lab.q3(st['base_m1'])} | {lab.q3(st['m1'])} | {lab.r3(st['base_m2'])} | {lab.r3(st['m2'])} |")
    R.append("")
    mb = res["models"]
    smp = mb["industry_sample"]
    R += ["## 업종 표본", "",
          f"- 업종 사건 {smp['n_industry_events']}개(산업 {smp['n_columns_used']}개, 첫 사건 {smp['first_industry_event']}), 마지막 날 라벨 있음 {smp['n_industry_labeled']}개, "
          f"긴 약세장 비율 {lab.pct(smp['industry_lb_rate'], 0, False)} vs 시장 사건 {smp['n_market_labeled']}개 중 {lab.pct(smp['market_lb_rate'], 0, False)}.",
          f"- 첫 판정 시장 사건 때 분류기 학습 업종 사건 수: {smp['n_cls_at_first_judged'] if smp['n_cls_at_first_judged'] is not None else '—'}.", "",
          "### 적합 기울기 (업종 사건, 표준화; 양수 = 값이 클수록 긴 약세장 쪽)", "",
          "| 적합 시점 | 라벨 있는 업종 사건 | 긴 약세장 | 적합 | " + " | ".join(FEATS) + " |", "|---|---|---|---|" + "---|" * len(FEATS)]
    for s in smp["slopes"]:
        R.append(f"| {s['date']} | {s['n']} | {s['n_pos']} | {'가능' if s['ok'] else '불가'} | " + " | ".join(lab.sgn(s["beta"][f], 3) for f in FEATS) + " |")
    f100 = lambda v: "—" if lab.fin(v) is None else f"{v * 100:.2f}"  # noqa: E731
    R += ["", "## 모델 1·2 — 층별 평균 점수", "", "핀볼 = 전고점 대비 %p, 브라이어 = 0~1(둘 다 낮을수록 잘 맞힘). 평가 = 쌍이 있는 판정 층 사건.", "",
          "| 층 | 모델 1 평가 | 핀볼 BASE | 핀볼 XFER | 모델 2 평가 | 브라이어 BASE | 브라이어 XFER | 미적합 |", "|---|---|---|---|---|---|---|---|"]
    for s in ("A", "B", "C", "all"):
        x = mb["by_stratum"][s]
        R.append(f"| {s if s != 'all' else 'A+B+C'} | {x['n1']} | {f100(x['m1']['BASE'])} | {f100(x['m1']['XFER'])} | {x['n2']} | "
                 f"{lab.num(x['m2']['BASE'])} | {lab.num(x['m2']['XFER'])} | {x['n_unfit']} |")
    R += ["", "### 보정: 평균 예측 회복 확률 vs 실제 비율", "", "| 시점 | 사건 | BASE | XFER | 실제 |", "|---|---|---|---|---|"]
    for h in lab.HZ:
        c = mb["calib"][str(h)]
        R.append(f"| {h // 252}년 | {c['n']} | {lab.pct(c['BASE'], 0, False)} | {lab.pct(c['XFER'], 0, False)} | {lab.pct(c['obs'], 0, False)} |")
    sk = mb["skill"]
    rb = res["robustness"]
    f3 = lambda x: f"{x['n']} · {lab.sgn(x['mean'])} · {lab.pval(x['p'])}"  # noqa: E731
    R += ["", f"분류 실력(보고만): 판정 층 시장 사건 {sk['n']}개의 실제 라벨에 대한 브라이어 p_lb {lab.num(sk['brier_p'])} vs 시장 기준 확률 π {lab.num(sk['brier_pi'])}.", "",
          "## 견고성 (보고만)", "", "라벨을 붙이지 않는다. 값은 n · 평균 d · 한쪽 부호 뒤집기 p.", "", "| 항목 | 모델 1 | 모델 2 |", "|---|---|---|",
          f"| A+B 만(v1 방식) | {f3(rb['ab_only']['XFER_M1'])} | {f3(rb['ab_only']['XFER_M2'])} |",
          f"| 미국 겹침 군집 p | {lab.pval(rb['cluster_us']['XFER_M1'])} | {lab.pval(rb['cluster_us']['XFER_M2'])} |", ""]
    vc = res["v1_check"]
    R += ["v1 기준선 재현 확인(미국 발생일 BASE vs v1 결과 파일): "
          + (vc["skipped"] if "skipped" in vc else f"사건 {vc['n']} · 최대 차이 깊이 {lab.num(vc['max_abs_diff_m1'], 6)} · 회복 {lab.num(vc['max_abs_diff_m2'], 6)}"), ""]
    R += lab.report_tail(res, LIMITS, ["- p_lb = 긴 약세장 확률(기울기 = 업종, 기준 확률·중심 = 그날 라벨을 아는 시장 사건). 기울기가 0 이면 p = π 라 XFER = BASE.",
                                      "- DD0 = 발생일 전고점 대비(소수), SPEED = ln(고점→발생일 거래일), VOLRATIO = 21일/252일 변동성 배수, RUNUP = 직전 2년 로그 상승."])
    return "\n".join(R) + "\n"


# ---------------------------------------------------------------- 실행
def run(smoke: bool) -> tuple:
    return evaluate(L().load_us(smoke), smoke)


def main(argv=None) -> int:
    return L().run_main(argv, run, report)


if __name__ == "__main__":
    raise SystemExit(main())
