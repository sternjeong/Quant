"""crash-intl-pool-v1 — 해외 급락 합치기(유럽·일본·아시아태평양). 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/crash-intl-pool-v1/run.py --out OUT --checkpoint CK [--smoke]

- POOL = 미국 + 해외 3지역 사건으로 학습한 v1 기준선 계산, BASE = 미국 사건만으로 학습한 같은 계산(날짜 기준 학습 집합).
- 판정: 처음 보는 해외 급락(1991~2024-09)을 동시 급락 군집(평일 63일 간격) 단위로, I1(~2007)·I2(2008~2024-09) 두 반쪽.
- 판정 2개(POOL_M1·POOL_M2), 족 15개 공통 α = 0.05/15. 해외 자료를 못 받으면 예외(실행기 재시도). 계산은 수십 초라 체크포인트를 쓰지 않는다.
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

STUDY = "crash-intl-pool-v1"
RULES_VERSION = "crash-intl-pool/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
NOW_DD0 = -0.15
MODEL_NAMES = {"POOL_M1": "POOL vs BASE(미국만 학습) (깊이, 해외 군집)", "POOL_M2": "POOL vs BASE(미국만 학습) (회복, 해외 군집)"}
EXPECTED = {
    "POOL_M1": "FAIL 가능성이 높다(통과 약 10%). 미국 학습 깊이 분포도 해외에 크게 어긋나지 않을 것.",
    "POOL_M2": "불확실(통과 약 18%). USD 기준 해외 회복은 미국보다 느린 경우가 많아, 해외 사건이 쌓인 2008 이후 예측에서 POOL 이 덜 낙관적이 되어 나을 수 있다. 군집 수가 적어 검정력이 낮다.",
}
NOTES = [
    "해외 사건은 이 저장소 급락 질문에 처음 쓴다(v1 결과를 본 영향이 없는 확인 시험). 방법에 모수가 없다(단순 합치기).",
    "판정 단위는 동시 급락 군집이다: 앞 사건 발생일과 평일 63일 이내면 같은 군집, 군집 값 = 구성 사건 d 의 평균, 군집 층 = 첫 사건 날짜. 2024-10 이후 사건은 군집에 넣지 않는다.",
    "예상 군집 수가 약 13개라 필요 효과가 약 0.9 sd 로 크다(검정력이 낮다는 것을 미리 밝힘).",
]
LIMITS = [
    "USD 수익(환율 포함). 선진국 지수만.",
    "지역끼리·미국과 강하게 겹친다(군집으로 일부만 처리).",
    "1990 이전 해외 사건 없음(해외 자료 1990-07 시작, 첫 발생 가능일 약 1991-07).",
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
def pool_pred(train: list, r: dict, D=None, dd0=None, e_days: int = 0) -> dict:
    """train 사건으로 학습한 v1 기준선 계산(날짜 D 기준, 기본 = r 의 발생일)."""
    lab = L()
    D = r["t0_date"] if D is None else D
    dd0 = r["dd0"] if dd0 is None else dd0
    T1 = lab.m1_pool(train, D)
    rows, times, events = lab.m2_pool(train, D)
    m1, m2 = lab.base_m1(T1, dd0), lab.base_m2(rows, times, events, e_days)
    return {"m1": m1, "m2": m2, "n1": len(T1), "n2": len(rows), "n_train": lab.n_train_of(m1, len(T1), m2, len(rows))}


def episode_calc(us: list, allr: list, r: dict) -> dict:
    lab = L()
    b, p = lab.base0(us, r), pool_pred(allr, r)
    s1, s2 = {}, {}
    for name, x in (("BASE", b), ("POOL", p)):
        if r["depth_settled"] and x["m1"] is not None:
            s1[name] = lab.score_m1(r["FD"], x["m1"])
        if r["R"] is not None and x["m2"] is not None:
            s2[name] = lab.score_m2(r["R"], x["m2"])
    return {"r": r, "base": b, "pool": p, "s1": s1, "s2": s2,
            "d1": s1["BASE"] - s1["POOL"] if len(s1) == 2 else None, "d2": s2["BASE"] - s2["POOL"] if len(s2) == 2 else None}


def make_reader(by_id: dict):
    def reader(ep: dict, d: int, mapping: str) -> dict:
        c = by_id[ep["id"]]
        return {"base_m1": c["base"]["m1"], "base_m2": c["base"]["m2"], "pool_m1": c["pool"]["m1"], "pool_m2": c["pool"]["m2"],
                "n_base": c["base"]["n_train"], "n_pool": c["pool"]["n_train"]}

    return reader


def current_block(ctx: dict, us: list, allr: list, smoke: bool) -> dict:
    lab = L()
    cur = lab.reading_now(ctx)
    last = ctx["last"]
    D = pd.Timestamp(ctx["idx"][last])
    ep = lab.active_episode(ctx, last)
    if ep is not None:
        e_now = int(last - ep["t0"])
        b, p = pool_pred(us, ep, D, ep["dd0"], e_now), pool_pred(allr, ep, D, ep["dd0"], e_now)
        cur["basis"] = f"진행 중 사건({lab.dstr(ep['t0_date'])}) — 발생일 깊이로 변환, 학습은 {lab.dstr(D)} 까지, 회복은 경과 {e_now}일 조건부"
    else:
        fake = {"t0_date": D, "dd0": NOW_DD0}
        b, p = pool_pred(us, fake, D, NOW_DD0, 0), pool_pred(allr, fake, D, NOW_DD0, 0)
        cur["basis"] = f"만약 오늘({lab.dstr(D)})이 미국 급락 발생일이라면(발생일 깊이 −15%)"
    cur["base_now"], cur["pool_now"] = b, p
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

    icalcs = [episode_calc(us, allr, r) for r in intl_recs]
    ucalcs = [episode_calc(us, allr, r) for r in us]
    j1, cl1 = lab.intl_verdict([(c["r"], c["d1"]) for c in icalcs])
    j2, cl2 = lab.intl_verdict([(c["r"], c["d2"]) for c in icalcs])
    verdicts = {"POOL_M1": j1["verdict"], "POOL_M2": j2["verdict"]}

    rows: list = []
    for c in icalcs + ucalcs:
        r = c["r"]
        jd = r["market"] != "US" and r["stratum"] in lab.INTL_STRATA
        jf1, jf2 = int(jd and c["d1"] is not None), int(jd and c["d2"] is not None)
        b, p = c["base"], c["pool"]
        rows.append(lab.pred_row(STUDY, "BASE", r, 0, r["t0_date"], b["n_train"], None, b["m1"], b["m2"], None, jf1, jf2))
        if p["m1"] is not None or p["m2"] is not None:
            rows.append(lab.pred_row(STUDY, "POOL", r, 0, r["t0_date"], p["n_train"], None, p["m1"], p["m2"], None, jf1, jf2))

    def st3(vals):
        return {"n": len(vals), "mean": lab.mean_or_none(vals), "p": lab.signflip(vals)}

    cl_id = {}
    for n, c in enumerate(cl1, 1):
        for m in c["members"]:
            cl_id.setdefault(m, {})["m1"] = n
    for n, c in enumerate(cl2, 1):
        for m in c["members"]:
            cl_id.setdefault(m, {})["m2"] = n
    judged_list = [{"region": c["r"]["market"], "id": c["r"]["id"], "t0": lab.dstr(c["r"]["t0_date"]), "era": c["r"]["stratum"],
                    "cluster_m1": cl_id.get(c["r"]["id"], {}).get("m1"), "cluster_m2": cl_id.get(c["r"]["id"], {}).get("m2"),
                    "dd0": c["r"]["dd0"], "FD": c["r"]["FD"], "R": c["r"]["R"], "d1": c["d1"], "d2": c["d2"]} for c in icalcs]
    by_region = {k: {"m1": st3([c["d1"] for c in icalcs if c["r"]["market"] == k and c["r"]["stratum"] in lab.INTL_STRATA and c["d1"] is not None]),
                     "m2": st3([c["d2"] for c in icalcs if c["r"]["market"] == k and c["r"]["stratum"] in lab.INTL_STRATA and c["d2"] is not None])}
                 for k in intl_ctx}
    jud = [c for c in icalcs if c["r"]["stratum"] in lab.INTL_STRATA]
    e2 = [c for c in jud if c["d2"] is not None]
    calib = {str(h): {"BASE": lab.mean_or_none([c["base"]["m2"][h] for c in e2]), "POOL": lab.mean_or_none([c["pool"]["m2"][h] for c in e2]),
                      "obs": float(np.mean([c["r"]["R"] <= h for c in e2])) if e2 else None, "n": len(e2)} for h in lab.HZ}
    us_j = [c for c in ucalcs if c["r"]["stratum"] in lab.US_STRATA]
    robust = {"us_report": {"m1": st3([c["d1"] for c in us_j if c["d1"] is not None]), "m2": st3([c["d2"] for c in us_j if c["d2"] is not None]),
                            "n_identical_pre1992": sum(1 for c in ucalcs if c["r"]["t0_date"] < pd.Timestamp("1992-01-01")
                                                       and c["base"]["m1"] == c["pool"]["m1"] and c["base"]["m2"] == c["pool"]["m2"])},
              "by_region": by_region,
              "episode_level": {"POOL_M1": {"n": j1["n_episodes"], "p": j1["p_episode"]}, "POOL_M2": {"n": j2["n_episodes"], "p": j2["p_episode"]}},
              "n_excluded_holdout": sum(1 for c in icalcs if c["r"]["stratum"] == "IX"),
              "n_unrecovered": sum(1 for c in jud if c["r"]["R"] is None),
              "n_same_as_base": {"m1": sum(1 for c in jud if c["d1"] is not None and c["pool"]["m1"] == c["base"]["m1"]),
                                 "m2": sum(1 for c in jud if c["d2"] is not None and c["pool"]["m2"] == c["base"]["m2"])}}
    clusters_rep = {"m1": [{"first": lab.dstr(c["first"]), "stratum": c["stratum"], "members": c["members"], "value": c["value"]} for c in cl1],
                    "m2": [{"first": lab.dstr(c["first"]), "stratum": c["stratum"], "members": c["members"], "value": c["value"]} for c in cl2]}

    by_id = {c["r"]["id"]: c for c in ucalcs}
    events = lab.events_rows(ctx, make_reader(by_id))
    current = current_block(ctx, us, allr, smoke)
    summary = {"POOL_M1 해외 합치기 깊이": lab.summary_entry(j1), "POOL_M2 해외 합치기 회복": lab.summary_entry(j2),
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
        "power_episode": {"POOL_M1": lab.power_episode(j1["n"]["pooled"]), "POOL_M2": lab.power_episode(j2["n"]["pooled"])},
        "verdicts": verdicts, "summary": summary, "detail": {"POOL_M1": j1, "POOL_M2": j2},
        "models": {"judged_episodes": judged_list, "clusters": clusters_rep, "calib": calib},
        "episodes": episodes, "events": events, "current": current, "robustness": robust,
        "v1_check": lab.v1_check(us, base_preds, smoke), "expected": EXPECTED, "notes": NOTES,
    }
    return res, rows


# ---------------------------------------------------------------- 보고서
def _years(days) -> str:
    return "미회복" if days is None else f"{days / 252:.1f}년"


def report(res: dict, smoke: bool) -> str:
    lab = L()
    R = lab.report_head(res, "해외 급락 합치기 — 유럽·일본·아시아태평양 사건을 학습에 더하면", smoke, MODEL_NAMES, intl=True)
    mb = res["models"]
    R += ["n 은 군집 수다(사건 수는 아래 목록). 평균 d 는 군집 값의 평균.", "",
          "### 해외 판정 사건 목록", "",
          "| 지역 | 발생일 | 층 | 군집(모델 1/2) | 발생일 깊이 | 최종 깊이 | 회복 기간 | d 모델 1 | d 모델 2 |", "|---|---|---|---|---|---|---|---|---|"]
    for e in sorted(mb["judged_episodes"], key=lambda z: z["t0"]):
        R.append(f"| {lab.REGION_LABELS.get(e['region'], e['region'])} | {e['t0']} | {e['era']} | {e['cluster_m1'] or '—'}/{e['cluster_m2'] or '—'} | "
                 f"{lab.pct(e['dd0'])} | {lab.pct(e['FD'])} | {_years(e['R'])} | {lab.sgn(e['d1'])} | {lab.sgn(e['d2'])} |")
    R += ["", "## 이 연구가 묻는 것", "",
          "- v1 기준선은 미국 급락 사건(약 28개)만으로 배운다. 같은 정의(USD 총수익 252일 고점 −15%)로 유럽·일본·아시아태평양(일본 제외) 급락을 학습에 합치면(POOL),",
          "  **처음 보는 해외 급락**의 최종 깊이와 회복 확률을 미국만 배운 기준선(BASE)보다 잘 맞히나. 학습은 언제나 그 발생일까지 확정된 사건만(시장이 달라도 날짜로 맞춤).", ""]
    cur = res["current"]
    b, p = cur.get("base_now") or {}, cur.get("pool_now") or {}
    R += ["## 지금 읽기 (설명용 — 추천 아님)", "", lab.READING_HEADER, ""] + lab.reading_state_lines(cur)
    R += [f"기준: {cur.get('basis')}. 판정은 해외 사건으로 하므로 미국 읽기는 참고만.", "",
          "| 모델 | 학습 사건 | 최종 깊이 10/50/90% | 회복 1/2/5년 |", "|---|---|---|---|",
          f"| BASE(미국만) | {b.get('n_train', '—')} | {lab.q3(b.get('m1'))} | {lab.r3(b.get('m2'))} |",
          f"| POOL(미국+해외) | {p.get('n_train', '—')} | {lab.q3(p.get('m1'))} | {lab.r3(p.get('m2'))} |", "",
          lab.spy_line(cur.get("spy_check") or {}), ""]
    R += ["## 사용자가 든 7개 사건", "", "미국 사건의 BASE vs POOL(보고만 — **판정은 해외 사건으로 한다**).", ""] + lab.events_note_lines(res["events"])
    R += ["| 사건 | 발생일 | BASE 깊이 10/50/90% | POOL 깊이 10/50/90% | BASE 회복 1/2/5년 | POOL 회복 1/2/5년 | 학습 사건 BASE/POOL |", "|---|---|---|---|---|---|---|"]
    for e in res["events"]:
        st = e.get("study")
        if not st:
            R.append(f"| {e['label']} | — | | | | | |")
            continue
        R.append(f"| {e['label']} | {e['episode_t0']} | {lab.q3(st['base_m1'])} | {lab.q3(st['pool_m1'])} | {lab.r3(st['base_m2'])} | {lab.r3(st['pool_m2'])} | "
                 f"{st['n_base'] if st['n_base'] is not None else '—'}/{st['n_pool'] if st['n_pool'] is not None else '—'} |")
    R.append("")
    rb = res["robustness"]
    f3 = lambda x: f"{x['n']} · {lab.sgn(x['mean'])} · {lab.pval(x['p'])}"  # noqa: E731
    R += ["## 지역별·군집별 (판정 층 사건, 보고만)", "", "| 지역 | 모델 1 (사건 n · 평균 d · p) | 모델 2 (사건 n · 평균 d · p) |", "|---|---|---|"]
    for k, x in rb["by_region"].items():
        R.append(f"| {lab.REGION_LABELS.get(k, k)} | {f3(x['m1'])} | {f3(x['m2'])} |")
    for mdl, title in (("m1", "모델 1(깊이)"), ("m2", "모델 2(회복)")):
        R += ["", f"### 군집 — {title}", "", "| 번호 | 첫 발생일 | 층 | 구성 사건 | 군집 값(평균 d) |", "|---|---|---|---|---|"]
        for n, c in enumerate(mb["clusters"][mdl], 1):
            R.append(f"| {n} | {c['first']} | {c['stratum']} | {', '.join(c['members'])} | {lab.sgn(c['value'])} |")
        if not mb["clusters"][mdl]:
            R.append("| — | 군집 없음 | | | |")
    R += ["", "### 보정: 해외 판정 사건의 평균 예측 회복 확률 vs 실제 비율 (자료 안 회복 사건만)", "", "| 시점 | 사건 | BASE | POOL | 실제 |", "|---|---|---|---|---|"]
    for h in lab.HZ:
        c = mb["calib"][str(h)]
        R.append(f"| {h // 252}년 | {c['n']} | {lab.pct(c['BASE'], 0, False)} | {lab.pct(c['POOL'], 0, False)} | {lab.pct(c['obs'], 0, False)} |")
    ur = rb["us_report"]
    R += ["", "## 견고성 (보고만)", "",
          f"- 사건 단위(군집 아님) 부호 뒤집기 p: 모델 1 {lab.pval(rb['episode_level']['POOL_M1']['p'])}(사건 {rb['episode_level']['POOL_M1']['n']}) · "
          f"모델 2 {lab.pval(rb['episode_level']['POOL_M2']['p'])}(사건 {rb['episode_level']['POOL_M2']['n']}).",
          f"- 미국 A·B·C 사건에서도 POOL vs BASE(1992 이전은 같은 값): 모델 1 {f3(ur['m1'])} · 모델 2 {f3(ur['m2'])}. "
          f"1992 이전 미국 사건 중 BASE 와 POOL 이 같은 사건 {ur['n_identical_pre1992']}개.",
          f"- 판정 층 해외 사건 중 POOL 이 BASE 와 같은 사건(그 발생일까지 확정된 해외 사건이 없어 학습 집합이 같음, 설계대로 d = 0 으로 들어감): "
          f"모델 1 {rb['n_same_as_base']['m1']}개 · 모델 2 {rb['n_same_as_base']['m2']}개.",
          f"- 2024-10 이후 해외 사건(보고만, 군집에서 제외): {rb['n_excluded_holdout']}개. 판정 층 해외 사건 중 자료 안 미회복(모델 2 에서 빠짐): {rb['n_unrecovered']}개.", ""]
    vc = res["v1_check"]
    R += ["v1 기준선 재현 확인(미국 발생일 BASE vs v1 결과 파일): "
          + (vc["skipped"] if "skipped" in vc else f"사건 {vc['n']} · 최대 차이 깊이 {lab.num(vc['max_abs_diff_m1'], 6)} · 회복 {lab.num(vc['max_abs_diff_m2'], 6)}"), ""]
    R += lab.report_tail(res, LIMITS, ["- 해외 지수는 Ken French 지역 파일의 USD 시장 총수익(Mkt-RF + RF). 사건 정의는 미국과 같다.",
                                      "- 군집 = 동시 급락 묶음. 같은 위기에 여러 지역이 함께 빠지면 한 표로 센다."])
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
