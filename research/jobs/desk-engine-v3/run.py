"""desk-engine-v3 — 판단 엔진 3판: 변동성 회귀 축척 바탕·한 표 나누기·보정 섞기·재무 순위(V3) 대 1판 앙상블(ENS1), 시장·업종·종목 세 층.

python research/jobs/desk-engine-v3/run.py --out OUT --checkpoint CK [--smoke]

규칙·판정은 SPEC.md 와 research/jobs/desk-engine-lab-v3/SPEC.md(결과 보기 전 고정, 사전 등록 2026-11-26). 장부 H-032.
자료·점 집합·시대·판정 대상 기간은 desk-engine-v1·v2 와 같다(2판 run.py 의 점 만들기를 그대로 쓴다). 종목 층에만 SEC 재무(디스크에 있는 것만,
네트워크 없음)를 붙인다. 체크포인트는 쓰지 않는다. 산출: results.json, REPORT.md, model.json, library_{market,industry,stock}.csv.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
STUDY = "desk-engine-v3"
RULES_VERSION = "desk-engine/v3"
DATA_END = "2026-11-20"
JUDGED_END = "2024-09-30"
LAYERS = ("market", "industry", "stock")
FAMILY = (("MKT_Q63", "market", "63:q"), ("MKT_DD63", "market", "63:dd15"), ("IND_Q63", "industry", "63:q"),
          ("IND_DD63", "industry", "63:dd15"), ("IND_BEAT63", "industry", "63:beat"), ("STK_Q63", "stock", "63:q"),
          ("STK_DD63", "stock", "63:dd15"), ("STK_BEAT63", "stock", "63:beat"))
ALPHA = 0.05 / len(FAMILY)
LABELS = ("BEATS_V1", "FAIL", "NOT_EVALUABLE")
SWITCH_MIN_PASS, SWITCH_WORST = 3, -0.005     # 판단판 교체를 '제안'할 기준(자동 반영 아님): 통과 3개 이상이고 1판 대비 기량이 −0.005 아래인 열쇠가 없음
FUND_LAG_DAYS = 1                             # 재무는 기준일 전날까지 공시된 것만
LIMITS = [
    "3판의 설계는 1판·2판 결과(같은 자료)를 보고 정했다. 같은 자료를 세 번째 쓴다. 판정 기간의 통과는 그만큼 덜 믿을 만하다 — 2024-10 이후 보고값과 판단판의 실전 기록이 깨끗한 확인이다.",
    "재무 자료(SEC XBRL)는 2009년 무렵부터 있고, 지금 상장된 회사만 있다(상장폐지·티커 변경 회사는 '모름'). 종목 층의 앞 시대(2001~2012)는 대부분 재무 없이 계산된다.",
    "종목 층은 Yahoo 수정 종가라 상장폐지 종목이 빠져 있다(생존 편향). 하락 위험이 실제보다 낮게 잡힌다. 종목 가격 저장소는 실행 사이에 채워질 수 있어 1판·2판 실행과 점 수가 다를 수 있다(비교 대상은 같은 실행 안에서 다시 계산한다).",
    "겹치는 기간의 예측은 독립이 아니다. 달력 구획 검정은 이를 줄일 뿐 없애지 못한다. 증거 가중의 t 값도 같은 이유로 과장된다.",
    "분포를 맞히는 것과 돈을 버는 것은 다르다. 이 연구는 수익률 개선을 주장하지 않는다.",
]


def _load(name: str, rel: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def L3():
    return _load("desk_engine_lab_v3", "research/jobs/desk-engine-lab-v3/lab.py")


def R2():
    """2판 run.py — 점 만들기(1판과 같은 점 + 2판 입력)를 그대로 쓴다."""
    return _load("desk_engine_v2", "research/jobs/desk-engine-v2/run.py")


def R1():
    return R2().R1()


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 재무(종목 층)
class DiskFundamentals:
    """core/fundamentals_pit 저장소에서 디스크에 있는 기록만 읽는다(받지 않음). view(티커, 날짜) = 그 날짜까지 공시된 지표."""

    def __init__(self):
        from core import fundamentals_pit as fp

        self.fp, self.store, self.first = fp, fp.Store(fetch=False), {}

    def __call__(self, name: str, asof) -> Optional[dict]:
        rec = self.store.ensure(name)
        if not rec or rec.get("missing"):
            return None
        if name not in self.first:
            self.first[name] = min((str(r[3])[:10] for rows in (rec.get("facts") or {}).values() for r in rows), default=None)
        if self.first[name] is None or asof.isoformat() < self.first[name]:
            return None
        return self.fp.view_from_record(rec, asof)


def synthetic_fundamentals() -> Callable:
    from core.fundamentals_pit import SyntheticStore

    store = SyntheticStore()
    return lambda name, asof: store.view(name, asof) if asof.year >= 2012 else None    # 앞쪽은 '모름' — 실제 자료처럼


def fund_values(v: Optional[dict]) -> list:
    """재무 view → FX 순서의 값(모르면 NaN)."""
    if not v:
        return [np.nan] * 4
    g = lambda k: float(v[k]) if v.get(k) is not None and math.isfinite(float(v[k])) else np.nan  # noqa: E731
    return [g("gp_assets"), g("rev_yoy"), g("rev_yoy") - g("rev_yoy_prev"), g("ni_yoy")]


def fund_raw(P: dict, view: Callable) -> tuple:
    """(점별 재무 값 [n, 4], 자료 정보). 점의 기준일 전날까지 공시된 것만 쓴다."""
    n = len(P["date"])
    raw = np.full((n, len(L3().FX)), np.nan)
    with_rec = 0
    for k, name in enumerate(P["names"]):
        idx = np.where(P["asset"] == k)[0]
        got = False
        for i in idx:
            v = view(name, pd.Timestamp(P["date"][i]).date() - timedelta(days=FUND_LAG_DAYS))
            if v:
                raw[i], got = fund_values(v), True
        with_rec += got
        if k % 100 == 0:
            log(f"재무 {k}/{len(P['names'])}")
    known = np.isfinite(raw).any(axis=1)
    years = pd.DatetimeIndex(P["date"]).year.to_numpy()
    by_year = {int(y): round(float(known[years == y].mean()), 3) for y in np.unique(years)}
    info = {"tickers_with_fundamentals": int(with_rec), "tickers": len(P["names"]), "points_known": int(known.sum()), "points": int(n),
            "known_share_by_year": by_year, "first_known": str(P["date"][known][0]) if known.any() else None,
            "known_share_by_item": {c: round(float(np.isfinite(raw[:, j]).mean()), 3) for j, c in enumerate(L3().FX)}}
    return raw, info


# ---------------------------------------------------------------- 계산
def build_layers(smoke: bool) -> tuple:
    """(시장 자료, {층: 점 표 또는 None}, 자료 정보). 점 집합은 1판·2판과 같다."""
    lab, r2 = L3(), R2()
    fr = R1().load_french(smoke)
    log(f"French 자료 {fr['mlp'].index[0].date()} ~ {fr['mlp'].index[-1].date()}")
    ind2 = r2.industry_points(fr)
    ind = None if ind2 is None else lab.attach3(ind2)
    mkt = lab.attach3(r2.market_points(fr, ind))
    sp2, sinfo = r2.stock_points(smoke)
    stock, finfo = None, None
    if sp2 is not None:
        raw, finfo = fund_raw(sp2, synthetic_fundamentals() if smoke else DiskFundamentals())
        stock = lab.attach3(sp2, raw)
        log(f"재무를 아는 점 {finfo['points_known']:,}/{finfo['points']:,}")
    data_info = {"french": {"source": fr["source"], "first": str(fr["mlp"].index[0].date()), "last": str(fr["mlp"].index[-1].date()),
                            "industries": 0 if fr["ind"] is None else int(fr["ind"].shape[1])}, "stock": sinfo, "fundamentals": finfo}
    return fr, {"market": mkt, "industry": ind, "stock": stock}, data_info


def holdout_cells(P: dict, out: dict) -> dict:
    """2024-10 이후 기준일 예측(보고만): V3 의 기량(대 CLIM·대 ENS1·대 V2)."""
    lab = L3()
    res = {}
    late = P["date"] > np.datetime64(JUDGED_END)
    for hi, h in enumerate(lab.HORIZONS):
        for k, kind in enumerate(lab.KINDS):
            Lm = lab.L2.cell_loss(out, hi, k)
            ok = late & np.isfinite(Lm).all(axis=1)
            if ok.any():
                m = Lm[ok].mean(axis=0)
                res[f"{h}:{kind}"] = {"n_points": int(ok.sum()), "skill_vs_clim": lab.V._skill(m[0], m[lab.I_V3]),
                                      "skill_vs_v1": lab.V._skill(m[lab.I_ENS1], m[lab.I_V3]), "skill_vs_v2": lab.V._skill(m[lab.I_V2], m[lab.I_V3])}
    return res


def run_layer(name: str, P: Optional[dict]) -> Optional[dict]:
    lab = L3()
    if P is None or len(P["date"]) == 0:
        return None
    t0 = time.time()
    out = lab.walk3(P, progress=lambda i, n: log(f"{name} 걸어 나가기 {i}/{n}"))
    cells = lab.score_layer3(P, out, R1().ERAS[name], JUDGED_END, ALPHA)
    log(f"{name} 완료: 점 {len(P['date'])}개, {time.time() - t0:.0f}초")
    return {"P": P, "out": out, "cells": cells, "holdout": holdout_cells(P, out)}


def verdicts_of(layers: dict) -> dict:
    v = {}
    for key, layer, cell in FAMILY:
        c = (layers.get(layer) or {}).get("cells", {}).get(cell)
        if c is None or not c["vs_v1"]["evaluable"]:
            v[key] = {"label": "NOT_EVALUABLE", "layer": layer, "cell": cell, "grade": "없음"}
            continue
        d = c["vs_v1"]
        eras_ok = all(e["skill"] is not None and e["skill"] > 0 for e in d["eras"].values())
        ok = d["p"] is not None and d["p"] < ALPHA and eras_ok
        v[key] = {"label": "BEATS_V1" if ok else "FAIL", "layer": layer, "cell": cell, "skill": d["skill"], "p": d["p"],
                  "eras": {n: e["skill"] for n, e in d["eras"].items()}, "grade": d["grade"],
                  "skill_vs_v2": c["vs_v2"]["skill"], "p_vs_v2": c["vs_v2"]["p"], "grade_vs_v2": c["vs_v2"]["grade"],
                  "v2_skill_vs_v1": c["v2_vs_v1"]["skill"], "v2_p_vs_v1": c["v2_vs_v1"]["p"],
                  "skill_vs_clim": c["vs_clim"]["skill"], "grade_vs_clim": c["vs_clim"]["grade"],
                  "v1_skill_vs_clim": c["v1_vs_clim"]["skill"], "v1_grade_vs_clim": c["v1_vs_clim"]["grade"]}
    return v


def switch_advice(verdicts: dict) -> dict:
    """판단판 교체를 제안할 만한가(미리 고정한 기준, 자동 반영 아님 — 사용자 확인이 필요하다)."""
    judged = [v for v in verdicts.values() if v["label"] != "NOT_EVALUABLE"]
    n_pass = sum(v["label"] == "BEATS_V1" for v in judged)
    worst = min((v["skill"] for v in judged if v.get("skill") is not None), default=None)
    ok = bool(n_pass >= SWITCH_MIN_PASS and worst is not None and worst >= SWITCH_WORST)
    return {"propose_switch": ok, "n_pass": int(n_pass), "n_judged": len(judged), "worst_skill_vs_v1": worst,
            "rule": f"BEATS_V1 {SWITCH_MIN_PASS}개 이상이고 1판 대비 기량이 {SWITCH_WORST} 아래인 열쇠가 없음"}


def layer_model(P: dict, out: dict) -> dict:
    """실시간 예측(lab.forecast_live3)이 읽는 층 설정."""
    lab = L3()
    r = lambda a: np.round(a, 6).tolist()  # noqa: E731
    return {"feats": list(P["feats"]), "hx": list(P["hx"]), "sixth": P["sixth"], "weights1": r(out["weights1"]), "weights2": r(out["weights2"]),
            "shifts2": r(out["shifts2"]), "weights3": r(out["weights3"]), "shifts3": r(out["shifts3"]), "blend": r(out["blend"]),
            "cal_active": [bool(x) for x in out["cal_active"]], "xs_grid": lab.L2.xs_grid(P), "fx_grid": lab.fx_grid(P),
            "last_origin": str(P["date"][-1])}


def model_of(layers: dict, data_info: dict, smoke: bool) -> dict:
    lab = L3()
    m = {"study": STUDY, "lab_version": lab.LAB_VERSION, "data_end": DATA_END, "smoke": smoke, "horizons": list(lab.HORIZONS),
         "taus": list(lab.TAUS), "events": list(lab.EVENTS), "experts": list(lab.EXPERTS3), "pool": list(lab.POOL), "fx": list(lab.FX),
         "kinds": list(lab.KINDS), "alpha_family": ALPHA, "layers": {}}
    for name, r in layers.items():
        if r is None:
            continue
        lm = layer_model(r["P"], r["out"])
        lm.update(library=f"library_{name}.csv", borrow_library="library_industry.csv" if r["P"].get("borrow") is not None else None,
                  cells={k: {"grade": c["vs_clim"]["grade"], "skill": c["vs_clim"]["skill"], "p": c["vs_clim"]["p"],
                             "evaluable": c["vs_clim"]["evaluable"], "grade_vs_v1": c["vs_v1"]["grade"], "skill_vs_v1": c["vs_v1"]["skill"],
                             "grade_vs_v2": c["vs_v2"]["grade"], "skill_vs_v2": c["vs_v2"]["skill"], "v1_grade": c["v1_vs_clim"]["grade"],
                             "coverage80": (c.get("coverage80") or {}).get("V3")} for k, c in r["cells"].items()})
        m["layers"][name] = lm
    m["data"] = data_info
    return m


def now_reading(layers: dict, fr: dict) -> Optional[dict]:
    """시장의 마지막 날 읽기(보고용). 저장하는 모형과 같은 경로(export_library3 → forecast_live3)로 계산한다."""
    lab = L3()
    r = layers.get("market")
    st = None if r is None else lab.L2.latest_state2(fr["mlp"])
    if st is None:
        return None
    lib = lab.library_from_frame3(lab.export_library3(r["P"]))
    ind = layers.get("industry")
    blib = None if ind is None or r["P"].get("borrow") is None else lab.library_from_frame3(lab.export_library3(ind["P"]))
    f = lab.forecast_live3(lib, layer_model(r["P"], r["out"]), st, blib)
    num = lambda a: [None if not np.isfinite(v) else float(v) for v in a]  # noqa: E731
    ex = lambda a: [None if not np.isfinite(v) else float(math.expm1(v)) for v in a]  # noqa: E731
    rows = [{"h": h, "q_v3": ex(f["q"]["V3"][hi]), "q_v2": ex(f["q"]["V2"][hi]), "q_v1": ex(f["q"]["ENS1"][hi]), "q_clim": ex(f["q"]["CLIM"][hi]),
             "p_v3": num(f["p"]["V3"][hi]), "p_v2": num(f["p"]["V2"][hi]), "p_v1": num(f["p"]["ENS1"][hi]), "p_clim": num(f["p"]["CLIM"][hi]),
             "n": f["n"][hi]} for hi, h in enumerate(lab.HORIZONS)]
    return {"date": str(st["date"].date()), "dd": float(math.expm1(st["x"][0])), "rows": rows}


def run(smoke: bool) -> tuple:
    lab = L3()
    fr, points, data_info = build_layers(smoke)
    layers = {name: run_layer(name, points[name]) for name in LAYERS}
    verdicts = verdicts_of(layers)
    summary = {k: (f"{v['label']} · 등급 {v['grade']}" + ("" if v["label"] == "NOT_EVALUABLE" else
                                                         f" · 1판 대비 기량 {v['skill']:+.3f} · p {v['p']:.4f} · 2판 대비 {v['skill_vs_v2']:+.3f}"))
               for k, v in verdicts.items()}
    res = {"study": STUDY, "rules_version": RULES_VERSION, "lab_version": lab.LAB_VERSION, "smoke": smoke, "data_end": DATA_END,
           "judged_end": JUDGED_END, "family": {"keys": [k for k, _, _ in FAMILY], "alpha": ALPHA, "alpha_expr": "0.05/8"},
           "verdicts": verdicts, "switch_advice": switch_advice(verdicts), "summary": summary, "data": data_info, "limits": LIMITS,
           "layers": {n: None if r is None else {"n_points": int(len(r["P"]["date"])), "n_assets": len(r["P"]["names"]), "sixth": r["P"]["sixth"],
                                                 "first_origin": str(r["P"]["date"][0]), "last_origin": str(r["P"]["date"][-1]),
                                                 "weights3": np.round(r["out"]["weights3"], 4).tolist(),
                                                 "shifts3": np.round(r["out"]["shifts3"], 4).tolist(),
                                                 "blend": np.round(r["out"]["blend"], 4).tolist(),
                                                 "realized_dates": r["out"]["realized_dates"].astype(int).tolist(),
                                                 "blend_dates": r["out"]["blend_dates"].astype(int).tolist(),
                                                 "cells": r["cells"], "holdout": r["holdout"]} for n, r in layers.items()},
           "now": now_reading(layers, fr)}
    return res, layers, model_of(layers, data_info, smoke)


# ---------------------------------------------------------------- 보고서
def report(res: dict) -> str:
    lab, r1 = L3(), R1()
    _f, _pct, KN, LN = r1._f, r1._pct, r1.KIND_NAMES, r1.LAYER_NAMES
    adv = res["switch_advice"]
    out = [f"# {STUDY} — 판단 엔진 3판: 변동성 회귀 축척 바탕·한 표 나누기·보정 섞기·재무 순위 대 1판 앙상블", ""]
    if res["smoke"]:
        out += ["**스모크(가짜 자료) 실행 — 숫자에 뜻이 없다.**", ""]
    out += ["## 한눈에", "",
            "- 무엇을 했나: 1판·2판과 같은 자료·같은 점에서, (1) 닮은 상태·기울기·여섯째 전문가를 변동성 회귀(HAR) 축척 위에서 다시 계산하고,",
            "  (2) 같은 값을 내는 전문가는 한 표로 세고, (3) 범위 보정을 핀볼 손실 기준으로 바꿔 보정한 것과 안 한 것을 증거 가중으로 섞고,",
            "  (4) 종목 층에 재무 순위 전문가(FUND — SEC 공시, 기준일 전날까지 나온 것만)를 더했다(V3).",
            "- 비교 대상: 1판 앙상블(ENS1, 판정)과 2판 최종(V2, 보고) — 둘 다 같은 걸어 나가기 안에서 원래 규칙 그대로 다시 계산.",
            f"- 판정 8개(유의수준 0.05/8 = {ALPHA:.5f}). 등급(강함·보통·약함·없음)은 판정과 별도로 모든 칸에 매긴다.",
            f"- 판단판 교체 제안 기준(미리 고정, 자동 반영 아님): {adv['rule']} → **{'제안함' if adv['propose_switch'] else '제안하지 않음'}** "
            f"(통과 {adv['n_pass']}/{adv['n_judged']}, 가장 나쁜 열쇠 {_f(adv['worst_skill_vs_v1'])}).", "",
            "## 판정 (V3 대 1판)", "",
            "| 열쇠 | 층 | 칸 | 판정 | 1판 대비 기량 | p | 시대별 | 2판 대비 기량 (p, 등급) | 2판의 1판 대비 (p) | 과거 평균 대비: 3판 (등급) | 1판 (등급) |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in res["verdicts"].items():
        h, kind = v["cell"].split(":")
        eras = " · ".join(f"{n} {_f(s)}" for n, s in (v.get("eras") or {}).items()) or "—"
        out.append(f"| {k} | {LN[v['layer']]} | {h}일 {KN[kind]} | {v['label']} | {_f(v.get('skill'))} | {_f(v.get('p'), '{:.4f}')} | {eras} | "
                   f"{_f(v.get('skill_vs_v2'))} ({_f(v.get('p_vs_v2'), '{:.3f}')}, {v.get('grade_vs_v2', '—')}) | "
                   f"{_f(v.get('v2_skill_vs_v1'))} ({_f(v.get('v2_p_vs_v1'), '{:.3f}')}) | "
                   f"{_f(v.get('skill_vs_clim'))} ({v.get('grade_vs_clim', '—')}) | {_f(v.get('v1_skill_vs_clim'))} ({v.get('v1_grade_vs_clim', '—')}) |")
    out += ["", "기량 = 1 − 손실(3판)/손실(비교 대상). 양수면 3판이 더 잘 맞혔다.", ""]
    for name in LAYERS:
        r = res["layers"].get(name)
        out += [f"## {LN[name]} 층", ""]
        if r is None:
            out += [f"평가 불가 — {(res['data'].get('stock') or {}).get('reason', '자료 없음') if name == 'stock' else '자료 없음'}", ""]
            continue
        six = r["sixth"]
        out += [f"점 {r['n_points']:,}개 · 자산 {r['n_assets']}개 · 기준일 {r['first_origin']} ~ {r['last_origin']} · 여섯째 전문가 {six}_H", "",
                f"| 기간 | 종류 | 3판 등급(대 평균) | 기량 | 3판 대 1판 (p, 등급) | 3판 대 2판 (p, 등급) | 3판 대 HAR (p) | 보정 전 대 1판 | "
                f"VOL | HAR | ANALOG_H | TILT_H | {six}_H | FUND | 80% 구간 적중 1판 → 2판 → 보정 전 → 3판 | 2024-10~ 대 1판 / 대 2판(보고) |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for key, c in r["cells"].items():
            h, kind = key.split(":")
            es, cv, ho = c.get("expert_skill") or {}, c.get("coverage80") or {}, (r["holdout"] or {}).get(key) or {}
            cov = "—" if not cv else " → ".join(_f(cv.get(e), "{:.1%}") for e in ("ENS1", "V2", "ENS3", "V3"))
            cmp = lambda d, g=True: f"{_f(d['skill'])} ({_f(d['p'], '{:.3f}')}" + (f", {d['grade']})" if g else ")")  # noqa: E731
            out.append(f"| {h}일 | {KN[kind]} | {c['vs_clim']['grade']} | {_f(c['vs_clim']['skill'])} | {cmp(c['vs_v1'])} | {cmp(c['vs_v2'])} | "
                       f"{cmp(c['vs_har'], False)} | {_f(c['ens3_vs_v1']['skill'])} | " +
                       " | ".join(_f(es.get(e)) for e in ("VOL", "HAR", "ANALOG_H", "TILT_H", "SIXTH_H", "FUND")) +
                       f" | {cov} | {_f(ho.get('skill_vs_v1'))} / {_f(ho.get('skill_vs_v2'))} (n {ho.get('n_points', 0)}) |")
        out += ["", "마지막 증거 가중 — 한 표 나누기 전(전문가 순서 " + " · ".join(six + "_H" if e == "SIXTH_H" else e for e in lab.POOL) + "):", "",
                "| 기간 | " + " | ".join(KN[k] for k in lab.KINDS) + " |", "|---|" + "---|" * len(lab.KINDS)]
        for hi, h in enumerate(lab.HORIZONS):
            out.append(f"| {h}일 | " + " | ".join(" / ".join(f"{w:.2f}" for w in r["weights3"][hi][k]) for k in range(len(lab.KINDS))) + " |")
        out += ["", "범위 보정 이동(변동성 단위, 분위수 10·25·50·75·90%)과 섞는 가중(보정 전 / 보정 후): " +
                " · ".join(f"{h}일 [" + ", ".join(f"{s:+.2f}" for s in r["shifts3"][hi]) + f"] {r['blend'][hi][0]:.2f}/{r['blend'][hi][1]:.2f}"
                           for hi, h in enumerate(lab.HORIZONS)), ""]
    fi = (res["data"] or {}).get("fundamentals")
    if fi:
        yrs = fi["known_share_by_year"]
        out += ["## 재무 자료가 닿은 범위 (종목 층)", "",
                f"재무 기록이 있는 종목 {fi['tickers_with_fundamentals']}/{fi['tickers']} · 재무를 하나라도 아는 점 {fi['points_known']:,}/{fi['points']:,} · 첫 점 {fi['first_known']}", "",
                "연도별 아는 점 비율: " + " · ".join(f"{y} {float(s):.0%}" for y, s in yrs.items()), ""]
    now = res.get("now")
    if now:
        out += ["## 시장의 지금 읽기 (설명용, 추천 아님)", "", f"기준일 {now['date']} · 1년 고점 대비 {_pct(now['dd'])}", "",
                "| 기간 | 3판 10% | 25% | 중앙 | 75% | 90% | 2판 10%~90% | 1판 10%~90% | 15% 이상 빠질 확률(3판/2판/1판/평균) |", "|---|---|---|---|---|---|---|---|---|"]
        for row in now["rows"]:
            out.append(f"| {row['h']}일 | " + " | ".join(_pct(v) for v in row["q_v3"]) + f" | {_pct(row['q_v2'][0])} ~ {_pct(row['q_v2'][4])} | "
                       f"{_pct(row['q_v1'][0])} ~ {_pct(row['q_v1'][4])} | " + " / ".join(_f(row[k][1], "{:.0%}") for k in ("p_v3", "p_v2", "p_v1", "p_clim")) + " |")
        out.append("")
    out += ["## 한계", ""] + [f"- {x}" for x in res["limits"]] + ["", "## 자료", "", "```", json.dumps(res["data"], ensure_ascii=False, indent=1), "```", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    Path(a.checkpoint).mkdir(parents=True, exist_ok=True)
    res, layers, model = run(a.smoke)
    clean = R1()._clean
    res, model = clean(res), clean(model)
    lab = L3()
    for name in LAYERS:
        r = layers.get(name)
        df = pd.DataFrame(columns=["dd"]) if r is None else lab.export_library3(r["P"])
        df.to_csv(out / f"library_{name}.csv", index=False)
    (out / "model.json").write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
