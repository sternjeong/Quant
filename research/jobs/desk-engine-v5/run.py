"""desk-engine-v5 — 판단 엔진 5판: 변동성 예측 고도화(HAR-X) 대 1판 앙상블. 섞기는 3판 그대로, 범위 보정은 시장 층만.

사전 등록(SPEC.md, research/jobs/desk-engine-lab-v5/SPEC.md): 판정 규칙·상수는 결과를 보기 전에 고정했다. 바꾸려면 새 id.
자료·점 집합·판정 열쇠 8개·유의수준은 1~4판과 같다. 1판 앙상블과 3판 최종은 같은 실행 안에서 원래 규칙 그대로 다시 계산한다.
끝난 층은 체크포인트에 저장하고 다시 실행되면 건너뛴다(층끼리는 서로의 출력을 쓰지 않는다).
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import math
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
STUDY = "desk-engine-v5"
RULES_VERSION = "desk-engine/v5"
DATA_END = "2026-11-20"
JUDGED_END = "2024-09-30"
LAYERS = ("market", "industry", "stock")
FAMILY = (("MKT_Q63", "market", "63:q"), ("MKT_DD63", "market", "63:dd15"), ("IND_Q63", "industry", "63:q"),
          ("IND_DD63", "industry", "63:dd15"), ("IND_BEAT63", "industry", "63:beat"), ("STK_Q63", "stock", "63:q"),
          ("STK_DD63", "stock", "63:dd15"), ("STK_BEAT63", "stock", "63:beat"))
ALPHA = 0.05 / len(FAMILY)
LABELS = ("BEATS_V1", "FAIL", "NOT_EVALUABLE")
SWITCH_MIN_PASS, SWITCH_WORST = 3, -0.005     # 판단판 교체를 '제안'할 기준(3·4판과 같다, 자동 반영 아님)
PREFER_WORST_VS_V3 = -0.005                   # 3판보다 5판을 권할 기준: 통과 수가 3판 이상, 3판 대비 기량 평균 > 0, 가장 나쁜 열쇠가 이 값 이상
LIMITS = [
    "5판의 설계는 1~4판 결과(같은 자료)를 보고 정했다. 같은 자료를 다섯 번째 쓴다. 판정 기간의 통과는 그만큼 덜 믿을 만하다 — 2024-10 이후 보고값과 판단판의 실전 기록이 깨끗한 확인이다.",
    "범위 보정을 시장 층에만 쓰는 규칙은 3·4판 결과를 보고 정했다. 그 몫의 이득은 표본 안 선택이다(보정 전·후를 모두 보고한다).",
    "종목 층은 Yahoo 수정 종가라 상장폐지 종목이 빠져 있다(생존 편향). 하락 위험이 실제보다 낮게 잡힌다. 종목 가격 저장소는 실행 사이에 채워질 수 있어 앞선 실행과 점 수가 다를 수 있다(비교 대상은 같은 실행 안에서 다시 계산한다).",
    "겹치는 기간의 예측은 독립이 아니다. 달력 구획 검정은 이를 줄일 뿐 없애지 못한다.",
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


def L5():
    return _load("desk_engine_lab_v5", "research/jobs/desk-engine-lab-v5/lab.py")


def R3():
    """3판 run.py — 점 만들기(1판·2판과 같은 점 + 종목 층 재무)를 그대로 쓴다."""
    return _load("desk_engine_v3", "research/jobs/desk-engine-v3/run.py")


def R1():
    return R3().R1()


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 계산
def build_points(smoke: bool) -> tuple:
    """(시장 자료, {층: (3판 점 표, 5판 점 표) 또는 None}, 자료 정보). 점 집합은 1~4판과 같고 5판 열만 더한다."""
    lab = L5()
    with lab.extended_frames():
        fr, points, data_info = R3().build_layers(smoke)
    ind, mkt, stock = points["industry"], points["market"], points["stock"]
    ind5 = None if ind is None else lab.extend_points(ind, lab.CALIBRATE["industry"])
    pairs = {"market": None if mkt is None else (mkt, lab.extend_points(mkt, lab.CALIBRATE["market"], ind5)),
             "industry": None if ind is None else (ind, ind5),
             "stock": None if stock is None else (stock, lab.extend_points(stock, lab.CALIBRATE["stock"]))}
    return fr, pairs, data_info


def holdout_cells(P: dict, out: dict) -> dict:
    """2024-10 이후 기준일 예측(보고만): V5 의 기량(대 CLIM·대 ENS1·대 V3)."""
    lab = L5()
    res = {}
    late = P["date"] > np.datetime64(JUDGED_END)
    for hi, h in enumerate(lab.HORIZONS):
        for k, kind in enumerate(lab.KINDS):
            Lm = lab.L2.cell_loss(out, hi, k)
            ok = late & np.isfinite(Lm).all(axis=1)
            if ok.any():
                m = Lm[ok].mean(axis=0)
                res[f"{h}:{kind}"] = {"n_points": int(ok.sum()), "skill_vs_clim": lab.V._skill(m[0], m[lab.I_V5]),
                                      "skill_vs_v1": lab.V._skill(m[lab.I_ENS1], m[lab.I_V5]), "skill_vs_v3": lab.V._skill(m[lab.I_V3], m[lab.I_V5])}
    return res


BULKY = ("FQ", "FP", "LQ", "LB", "S_HAR", "S_HARX")  # 점 수만큼 큰 배열(채점 뒤에는 버린다)


def _layer_key(name: str, P5: dict, smoke: bool) -> str:
    """층 체크포인트가 지금 점 집합·규칙과 같은 계산의 것인지 가리는 지문."""
    h = hashlib.sha1()
    h.update(f"{STUDY}|{RULES_VERSION}|{L5().LAB_VERSION}|{name}|{int(smoke)}|{len(P5['date'])}|{len(P5['names'])}".encode())
    h.update(np.ascontiguousarray(P5["date"]).view(np.uint8).tobytes())
    h.update(np.ascontiguousarray(P5["asset"]).astype(np.int64).tobytes())
    h.update(np.ascontiguousarray(np.nan_to_num(P5["HX"], nan=-99.0)).tobytes())
    return h.hexdigest()


def _load_layer(path: Optional[Path], key: str) -> Optional[dict]:
    if path is None or not path.exists():
        return None
    try:
        with path.open("rb") as f:
            saved = pickle.load(f)
    except Exception:  # noqa: BLE001 — 깨진 체크포인트는 버리고 다시 계산
        return None
    return saved["layer"] if isinstance(saved, dict) and saved.get("key") == key else None


def _save_layer(path: Path, key: str, layer: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as f:
        pickle.dump({"key": key, "layer": layer}, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def run_layer(name: str, pair: Optional[tuple], ckpt: Optional[Path] = None, smoke: bool = False) -> Optional[dict]:
    """한 층을 걸어 나가 채점한다. ckpt 가 있으면 끝난 층의 채점 결과를 저장해 두고, 다시 실행되면 그 층은 건너뛴다."""
    lab = L5()
    if pair is None or len(pair[0]["date"]) == 0:
        return None
    P, P5 = pair
    path = None if ckpt is None else Path(ckpt) / f"layer_{name}.pkl"
    key = _layer_key(name, P5, smoke)
    saved = _load_layer(path, key)
    if saved is not None:
        log(f"{name} 체크포인트에서 이어받음")
        return {"P": P5, **saved}
    t0 = time.time()
    out = lab.walk5(P, P5, progress=lambda tag, i, n: log(f"{name} {tag} 걸어 나가기 {i}/{n}"))
    eras = R1().ERAS[name]
    layer = {"cells": lab.score_layer5(P5, out, eras, JUDGED_END, ALPHA), "scales": lab.scale_cells(P5, out, eras, JUDGED_END, ALPHA),
             "holdout": holdout_cells(P5, out)}
    layer["out"] = {k: v for k, v in out.items() if k not in BULKY}
    del out
    gc.collect()
    if path is not None:
        _save_layer(path, key, layer)
    log(f"{name} 완료: 점 {len(P5['date'])}개, {time.time() - t0:.0f}초")
    return {"P": P5, **layer}


def _passes(d: dict) -> bool:
    """판정 규칙: 한쪽 p < ALPHA 이고 모든 시대의 기량 > 0."""
    return bool(d["p"] is not None and d["p"] < ALPHA and all(e["skill"] is not None and e["skill"] > 0 for e in d["eras"].values()))


def verdicts_of(layers: dict) -> dict:
    v = {}
    for key, layer, cell in FAMILY:
        c = (layers.get(layer) or {}).get("cells", {}).get(cell)
        if c is None or not c["vs_v1"]["evaluable"]:
            v[key] = {"label": "NOT_EVALUABLE", "layer": layer, "cell": cell, "grade": "없음"}
            continue
        d = c["vs_v1"]
        v[key] = {"label": "BEATS_V1" if _passes(d) else "FAIL", "layer": layer, "cell": cell, "skill": d["skill"], "p": d["p"],
                  "eras": {n: e["skill"] for n, e in d["eras"].items()}, "grade": d["grade"],
                  "skill_vs_v3": c["vs_v3"]["skill"], "p_vs_v3": c["vs_v3"]["p"], "grade_vs_v3": c["vs_v3"]["grade"],
                  "v3_label": "BEATS_V1" if _passes(c["v3_vs_v1"]) else "FAIL", "v3_skill_vs_v1": c["v3_vs_v1"]["skill"], "v3_p_vs_v1": c["v3_vs_v1"]["p"],
                  "skill_vs_har": c["vs_har"]["skill"], "p_vs_har": c["vs_har"]["p"],
                  "harx_vs_har": c["harx_vs_har"]["skill"], "p_harx_vs_har": c["harx_vs_har"]["p"],
                  "skill_vs_clim": c["vs_clim"]["skill"], "grade_vs_clim": c["vs_clim"]["grade"],
                  "v1_skill_vs_clim": c["v1_vs_clim"]["skill"], "v1_grade_vs_clim": c["v1_vs_clim"]["grade"]}
    return v


def switch_advice(verdicts: dict) -> dict:
    """판단판을 5판으로 바꾸기를 제안할 만한가, 3판보다 5판을 권할 만한가(미리 고정한 기준, 자동 반영 아님 — 사용자 확인이 필요하다)."""
    judged = [v for v in verdicts.values() if v["label"] != "NOT_EVALUABLE"]
    n_pass = sum(v["label"] == "BEATS_V1" for v in judged)
    n_pass3 = sum(v.get("v3_label") == "BEATS_V1" for v in judged)
    worst = min((v["skill"] for v in judged if v.get("skill") is not None), default=None)
    vs3 = [v["skill_vs_v3"] for v in judged if v.get("skill_vs_v3") is not None]
    ok = bool(n_pass >= SWITCH_MIN_PASS and worst is not None and worst >= SWITCH_WORST)
    prefer = bool(ok and vs3 and n_pass >= n_pass3 and float(np.mean(vs3)) > 0 and min(vs3) >= PREFER_WORST_VS_V3)
    return {"propose_switch": ok, "prefer_v5_over_v3": prefer, "n_pass": int(n_pass), "n_pass_v3": int(n_pass3), "n_judged": len(judged),
            "worst_skill_vs_v1": worst, "mean_skill_vs_v3": float(np.mean(vs3)) if vs3 else None, "worst_skill_vs_v3": min(vs3) if vs3 else None,
            "rule": f"BEATS_V1 {SWITCH_MIN_PASS}개 이상이고 1판 대비 기량이 {SWITCH_WORST} 아래인 열쇠가 없음",
            "rule_prefer": f"위 기준을 채우고, 통과 수가 3판(같은 실행에서 다시 계산) 이상, 3판 대비 기량 평균 > 0, 3판 대비 기량이 {PREFER_WORST_VS_V3} 아래인 열쇠가 없음"}


def layer_model(P5: dict, out: dict) -> dict:
    """실시간 예측(lab.forecast_live5)이 읽는 층 설정."""
    lab = L5()
    r = lambda a: np.round(a, 6).tolist()  # noqa: E731
    return {"feats": list(P5["feats"]), "hx": list(P5["hx"]), "sixth": P5["sixth"], "calibrate": bool(out["calibrate"]),
            "weights1": r(out["weights1"]), "weights2": r(out["weights2"]), "shifts2": r(out["shifts2"]), "weights3": r(out["weights3"]),
            "shifts3": r(out["shifts3"]), "blend": r(out["blend"]), "cal_active": [bool(x) for x in out["cal_active"]],
            "xs_grid": lab.L2.xs_grid(P5), "fx_grid": None, "last_origin": str(P5["date"][-1])}


def model_of(layers: dict, data_info: dict, smoke: bool) -> dict:
    lab = L5()
    m = {"study": STUDY, "lab_version": lab.LAB_VERSION, "data_end": DATA_END, "smoke": smoke, "horizons": list(lab.HORIZONS),
         "taus": list(lab.TAUS), "events": list(lab.EVENTS), "pool": list(lab.L3.POOL), "kinds": list(lab.KINDS), "alpha_family": ALPHA, "layers": {}}
    for name, r in layers.items():
        if r is None:
            continue
        lm = layer_model(r["P"], r["out"])
        lm.update(library=f"library_{name}.csv", borrow_library="library_industry.csv" if r["P"].get("borrow") is not None else None,
                  cells={k: {"grade": c["vs_clim"]["grade"], "skill": c["vs_clim"]["skill"], "p": c["vs_clim"]["p"],
                             "evaluable": c["vs_clim"]["evaluable"], "grade_vs_v1": c["vs_v1"]["grade"], "skill_vs_v1": c["vs_v1"]["skill"],
                             "grade_vs_v3": c["vs_v3"]["grade"], "skill_vs_v3": c["vs_v3"]["skill"], "v1_grade": c["v1_vs_clim"]["grade"],
                             "coverage80": (c.get("coverage80") or {}).get("V5")} for k, c in r["cells"].items()})
        m["layers"][name] = lm
    m["data"] = data_info
    return m


def now_reading(layers: dict, fr: dict) -> Optional[dict]:
    """시장의 마지막 날 읽기(보고용). 저장하는 모형과 같은 경로(export_library5 → forecast_live5)로 계산한다."""
    lab = L5()
    r = layers.get("market")
    st = None if r is None else lab.latest_state5(fr["mlp"])
    if st is None:
        return None
    lib = lab.library_from_frame5(lab.export_library5(r["P"]))
    ind = layers.get("industry")
    blib = None if ind is None or r["P"].get("borrow") is None else lab.library_from_frame5(lab.export_library5(ind["P"]))
    f = lab.forecast_live5(lib, layer_model(r["P"], r["out"]), st, blib)
    num = lambda a: [None if not np.isfinite(v) else float(v) for v in a]  # noqa: E731
    ex = lambda a: [None if not np.isfinite(v) else float(math.expm1(v)) for v in a]  # noqa: E731
    rows = [{"h": h, "q_v5": ex(f["q"]["V5"][hi]), "q_v1": ex(f["q"]["ENS1"][hi]), "q_clim": ex(f["q"]["CLIM"][hi]),
             "p_v5": num(f["p"]["V5"][hi]), "p_harx": num(f["p"]["HARX"][hi]), "p_v1": num(f["p"]["ENS1"][hi]),
             "p_clim": num(f["p"]["CLIM"][hi]), "n": f["n"][hi]} for hi, h in enumerate(lab.HORIZONS)]
    return {"date": str(st["date"].date()), "dd": float(math.expm1(st["x"][0])), "rows": rows}


def run(smoke: bool, ckpt: Optional[Path] = None) -> tuple:
    lab = L5()
    fr, pairs, data_info = build_points(smoke)
    layers = {name: run_layer(name, pairs[name], ckpt, smoke) for name in LAYERS}
    verdicts = verdicts_of(layers)
    summary = {k: (f"{v['label']} · 등급 {v['grade']}" + ("" if v["label"] == "NOT_EVALUABLE" else
                                                         f" · 1판 대비 기량 {v['skill']:+.3f} · p {v['p']:.4f} · 3판 대비 {v['skill_vs_v3']:+.3f}"))
               for k, v in verdicts.items()}
    res = {"study": STUDY, "rules_version": RULES_VERSION, "lab_version": lab.LAB_VERSION, "smoke": smoke, "data_end": DATA_END,
           "judged_end": JUDGED_END, "family": {"keys": [k for k, _, _ in FAMILY], "alpha": ALPHA, "alpha_expr": "0.05/8"},
           "verdicts": verdicts, "switch_advice": switch_advice(verdicts), "summary": summary, "data": data_info, "limits": LIMITS,
           "layers": {n: None if r is None else {"n_points": int(len(r["P"]["date"])), "n_assets": len(r["P"]["names"]), "sixth": r["P"]["sixth"],
                                                 "calibrate": bool(r["out"]["calibrate"]), "hx": list(r["P"]["hx"]),
                                                 "first_origin": str(r["P"]["date"][0]), "last_origin": str(r["P"]["date"][-1]),
                                                 "weights3": np.round(r["out"]["weights3"], 4).tolist(),
                                                 "shifts3": np.round(r["out"]["shifts3"], 4).tolist(),
                                                 "blend": np.round(r["out"]["blend"], 4).tolist(),
                                                 "realized_dates": r["out"]["realized_dates"].astype(int).tolist(),
                                                 "cells": r["cells"], "scales": r["scales"], "holdout": r["holdout"]} for n, r in layers.items()},
           "now": now_reading(layers, fr)}
    return res, layers, model_of(layers, data_info, smoke)


# ---------------------------------------------------------------- 보고서
def report(res: dict) -> str:
    lab, r1 = L5(), R1()
    _f, _pct, KN, LN = r1._f, r1._pct, r1.KIND_NAMES, r1.LAYER_NAMES
    adv = res["switch_advice"]
    yn = lambda b: "제안함" if b else "제안하지 않음"  # noqa: E731
    cmp = lambda d, g=True: f"{_f(d['skill'])} ({_f(d['p'], '{:.3f}')}" + (f", {d['grade']})" if g else ")")  # noqa: E731
    out = [f"# {STUDY} — 판단 엔진 5판: 변동성 예측 고도화(HAR-X) 대 1판 앙상블", ""]
    if res["smoke"]:
        out += ["**스모크(가짜 자료) 실행 — 숫자에 뜻이 없다.**", ""]
    out += ["## 한눈에", "",
            "- 무엇을 했나: 1~4판과 같은 자료·같은 점에서, 변동성 회귀(HAR)의 입력에 1주 변동성·하락 변동성·최근 수익(지렛대 효과)과 그 음수 부분·낙폭을 더했다(HAR-X).",
            "  전문가·가중·보정 계산은 3판 코드 그대로다. 최종 V5 는 시장 층만 범위 보정을 섞고 업종·종목 층은 보정 전 앙상블이다. 재무 순위는 쓰지 않는다.",
            "- 비교 대상: 1판 앙상블(ENS1, 판정)과 3판 최종(V3, 보고) — 둘 다 같은 실행 안에서 원래 규칙 그대로 다시 계산.",
            f"- 판정 8개(유의수준 0.05/8 = {ALPHA:.5f}). 등급(강함·보통·약함·없음)은 판정과 별도로 모든 칸에 매긴다.",
            f"- 판단판 교체 제안 기준(미리 고정, 자동 반영 아님): {adv['rule']} → **{yn(adv['propose_switch'])}** "
            f"(통과 {adv['n_pass']}/{adv['n_judged']}, 가장 나쁜 열쇠 {_f(adv['worst_skill_vs_v1'])}).",
            f"- 3판보다 5판을 권하는 기준(미리 고정): {adv['rule_prefer']} → **{'5판을 권함' if adv['prefer_v5_over_v3'] else '5판을 권하지 않음'}** "
            f"(3판 통과 {adv['n_pass_v3']}/{adv['n_judged']}, 3판 대비 기량 평균 {_f(adv['mean_skill_vs_v3'])}, 가장 나쁜 열쇠 {_f(adv['worst_skill_vs_v3'])}).", "",
            "## 판정 (V5 대 1판)", "",
            "| 열쇠 | 층 | 칸 | 판정 | 1판 대비 기량 | p | 시대별 | 3판 대비 기량 (p, 등급) | 3판의 판정 · 1판 대비 (p) | HARX 대 HAR (p) | V5 대 HAR (p) | 과거 평균 대비: 5판 (등급) | 1판 (등급) |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in res["verdicts"].items():
        h, kind = v["cell"].split(":")
        eras = " · ".join(f"{n} {_f(s)}" for n, s in (v.get("eras") or {}).items()) or "—"
        out.append(f"| {k} | {LN[v['layer']]} | {h}일 {KN[kind]} | {v['label']} | {_f(v.get('skill'))} | {_f(v.get('p'), '{:.4f}')} | {eras} | "
                   f"{_f(v.get('skill_vs_v3'))} ({_f(v.get('p_vs_v3'), '{:.3f}')}, {v.get('grade_vs_v3', '—')}) | "
                   f"{v.get('v3_label', '—')} · {_f(v.get('v3_skill_vs_v1'))} ({_f(v.get('v3_p_vs_v1'), '{:.4f}')}) | "
                   f"{_f(v.get('harx_vs_har'))} ({_f(v.get('p_harx_vs_har'), '{:.3f}')}) | {_f(v.get('skill_vs_har'))} ({_f(v.get('p_vs_har'), '{:.3f}')}) | "
                   f"{_f(v.get('skill_vs_clim'))} ({v.get('grade_vs_clim', '—')}) | {_f(v.get('v1_skill_vs_clim'))} ({v.get('v1_grade_vs_clim', '—')}) |")
    out += ["", "기량 = 1 − 손실(5판)/손실(비교 대상). 양수면 5판이 더 잘 맞혔다. HARX 대 HAR 은 변동성 예측만 바꾼 전문가 한 명끼리의 비교다.", ""]
    for name in LAYERS:
        r = res["layers"].get(name)
        out += [f"## {LN[name]} 층", ""]
        if r is None:
            out += [f"평가 불가 — {(res['data'].get('stock') or {}).get('reason', '자료 없음') if name == 'stock' else '자료 없음'}", ""]
            continue
        out += [f"점 {r['n_points']:,}개 · 자산 {r['n_assets']}개 · 기준일 {r['first_origin']} ~ {r['last_origin']} · 범위 보정 {'씀' if r['calibrate'] else '안 씀'} · "
                f"회귀 입력 {', '.join(r['hx'])}", "",
                "| 기간 | 종류 | 5판 등급(대 평균) | 기량 | 5판 대 1판 (p, 등급) | 5판 대 3판 (p, 등급) | HARX 대 HAR (p) | 3판 틀+HARX 대 3판 (p) | 보정 전 대 1판 (p) | "
                "HAR | HARX | 3판 | 보정 전 | 80% 구간 적중 1판 → 3판 → 보정 전 → 5판 | 2024-10~ 대 1판 / 대 3판(보고) |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for key, c in r["cells"].items():
            h, kind = key.split(":")
            es, cv, ho = c.get("expert_skill") or {}, c.get("coverage80") or {}, (r["holdout"] or {}).get(key) or {}
            cov = "—" if not cv else " → ".join(_f(cv.get(e), "{:.1%}") for e in ("ENS1", "V3", "ENS5", "V5"))
            out.append(f"| {h}일 | {KN[kind]} | {c['vs_clim']['grade']} | {_f(c['vs_clim']['skill'])} | {cmp(c['vs_v1'])} | {cmp(c['vs_v3'])} | "
                       f"{cmp(c['harx_vs_har'], False)} | {cmp(c['v3x_vs_v3'], False)} | {cmp(c['ens5_vs_v1'], False)} | " +
                       " | ".join(_f(es.get(e)) for e in ("HAR", "HARX", "V3", "ENS5")) +
                       f" | {cov} | {_f(ho.get('skill_vs_v1'))} / {_f(ho.get('skill_vs_v3'))} (n {ho.get('n_points', 0)}) |")
        out += ["", "변동성 예측 자체의 오차(보고) — 기량은 1 − 오차(앞)/오차(뒤), 양수면 앞이 더 정확:", "",
                "| 기간 | 로그 오차²: HARX 대 HAR (p) | HAR 대 1판 축척 (p) | QLIKE: HARX 대 HAR (p) | HAR 대 1판 축척 (p) |", "|---|---|---|---|---|"]
        for h in lab.HORIZONS:
            s = r["scales"][str(h)]
            out.append(f"| {h}일 | {cmp(s['log2']['harx_vs_har'], False)} | {cmp(s['log2']['har_vs_v1'], False)} | "
                       f"{cmp(s['qlike']['harx_vs_har'], False)} | {cmp(s['qlike']['har_vs_v1'], False)} |")
        out += ["", "범위 보정 이동(변동성 단위, 분위수 10·25·50·75·90%)과 섞는 가중(보정 전 / 보정 후" + ("" if r["calibrate"] else ", 이 층은 쓰지 않음") + "): " +
                " · ".join(f"{h}일 [" + ", ".join(f"{s:+.2f}" for s in r["shifts3"][hi]) + f"] {r['blend'][hi][0]:.2f}/{r['blend'][hi][1]:.2f}"
                           for hi, h in enumerate(lab.HORIZONS)), ""]
    now = res.get("now")
    if now:
        out += ["## 시장의 지금 읽기 (설명용, 추천 아님)", "", f"기준일 {now['date']} · 1년 고점 대비 {_pct(now['dd'])}", "",
                "| 기간 | 5판 10% | 25% | 중앙 | 75% | 90% | 1판 10%~90% | 15% 이상 빠질 확률(5판/HARX/1판/평균) |", "|---|---|---|---|---|---|---|---|"]
        for row in now["rows"]:
            out.append(f"| {row['h']}일 | " + " | ".join(_pct(v) for v in row["q_v5"]) + f" | {_pct(row['q_v1'][0])} ~ {_pct(row['q_v1'][4])} | " +
                       " / ".join(_f(row[k][1], "{:.0%}") for k in ("p_v5", "p_harx", "p_v1", "p_clim")) + " |")
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
    res, layers, model = run(a.smoke, Path(a.checkpoint))
    clean = R1()._clean
    res, model = clean(res), clean(model)
    lab = L5()
    for name in LAYERS:
        r = layers.get(name)
        df = pd.DataFrame(columns=["dd"]) if r is None else lab.export_library5(r["P"])
        df.to_csv(out / f"library_{name}.csv", index=False)
    (out / "model.json").write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
