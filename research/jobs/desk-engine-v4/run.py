"""desk-engine-v4 — 판단 엔진 4판: 쌓기(섞은 결과의 손실로 가중)·낙폭 확률 전문가 DDLOGIT·보정 전후 쌓기(V4) 대 1판 앙상블(ENS1), 시장·업종·종목 세 층.

python research/jobs/desk-engine-v4/run.py --out OUT --checkpoint CK [--smoke]

규칙·판정은 SPEC.md 와 research/jobs/desk-engine-lab-v4/SPEC.md(결과 보기 전 고정, 사전 등록 2026-11-26). 장부 H-037.
자료·점 집합·시대·판정 대상 기간은 desk-engine-v1·v2·v3 과 같다(3판 run.py 의 점 만들기를 그대로 쓴다 — 3판 V3 을 같은 실행 안에서 그대로
다시 계산하려고 종목 층의 재무도 3판과 같이 붙인다. 4판 자신은 재무를 쓰지 않는다). 체크포인트는 쓰지 않는다.
산출: results.json, REPORT.md, model.json, library_{market,industry,stock}.csv.
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
STUDY = "desk-engine-v4"
RULES_VERSION = "desk-engine/v4"
DATA_END = "2026-11-20"
JUDGED_END = "2024-09-30"
LAYERS = ("market", "industry", "stock")
FAMILY = (("MKT_Q63", "market", "63:q"), ("MKT_DD63", "market", "63:dd15"), ("IND_Q63", "industry", "63:q"),
          ("IND_DD63", "industry", "63:dd15"), ("IND_BEAT63", "industry", "63:beat"), ("STK_Q63", "stock", "63:q"),
          ("STK_DD63", "stock", "63:dd15"), ("STK_BEAT63", "stock", "63:beat"))
ALPHA = 0.05 / len(FAMILY)
LABELS = ("BEATS_V1", "FAIL", "NOT_EVALUABLE")
SWITCH_MIN_PASS, SWITCH_WORST = 3, -0.005     # 판단판 교체를 '제안'할 기준(3판과 같다, 자동 반영 아님)
PREFER_WORST_VS_V3 = -0.005                   # 3판보다 4판을 권할 기준: 통과 수가 3판 이상, 3판 대비 기량 평균 > 0, 가장 나쁜 열쇠가 이 값 이상
LIMITS = [
    "4판의 설계는 1판·2판·3판 결과(같은 자료)를 보고 정했다. 같은 자료를 네 번째 쓴다. 판정 기간의 통과는 그만큼 덜 믿을 만하다 — 2024-10 이후 보고값과 판단판의 실전 기록이 깨끗한 확인이다.",
    "쌓기는 실현된 과거 손실을 직접 줄이는 가중을 고른다. 전문가 7명·가중 1/10 단위라 자유도는 작지만, 과거에 맞춘 만큼 표본 안 성적은 좋게 나온다. 판정은 표본 밖(걸어 나가기) 예측으로만 한다.",
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


def L4():
    return _load("desk_engine_lab_v4", "research/jobs/desk-engine-lab-v4/lab.py")


def R3():
    """3판 run.py — 점 만들기(1판·2판과 같은 점 + 종목 층 재무)를 그대로 쓴다."""
    return _load("desk_engine_v3", "research/jobs/desk-engine-v3/run.py")


def R1():
    return R3().R1()


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 계산
def holdout_cells(P: dict, out: dict) -> dict:
    """2024-10 이후 기준일 예측(보고만): V4 의 기량(대 CLIM·대 ENS1·대 V3)."""
    lab = L4()
    res = {}
    late = P["date"] > np.datetime64(JUDGED_END)
    for hi, h in enumerate(lab.HORIZONS):
        for k, kind in enumerate(lab.KINDS):
            Lm = lab.L2.cell_loss(out, hi, k)
            ok = late & np.isfinite(Lm).all(axis=1)
            if ok.any():
                m = Lm[ok].mean(axis=0)
                res[f"{h}:{kind}"] = {"n_points": int(ok.sum()), "skill_vs_clim": lab.V._skill(m[0], m[lab.I_V4]),
                                      "skill_vs_v1": lab.V._skill(m[lab.I_ENS1], m[lab.I_V4]), "skill_vs_v3": lab.V._skill(m[lab.I_V3], m[lab.I_V4])}
    return res


BULKY = ("FQ", "FP", "LQ", "LB", "S3", "CA4")  # 점 수만큼 큰 배열(채점 뒤에는 버린다)


def _layer_key(name: str, P: dict, smoke: bool) -> str:
    """층 체크포인트가 지금 점 집합·규칙과 같은 계산의 것인지 가리는 지문."""
    h = hashlib.sha1()
    h.update(f"{STUDY}|{RULES_VERSION}|{L4().LAB_VERSION}|{name}|{int(smoke)}|{len(P['date'])}|{len(P['names'])}".encode())
    h.update(np.ascontiguousarray(P["date"]).view(np.uint8).tobytes())
    h.update(np.ascontiguousarray(P["asset"]).astype(np.int64).tobytes())
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


def run_layer(name: str, P: Optional[dict], ckpt: Optional[Path] = None, smoke: bool = False) -> Optional[dict]:
    """한 층을 걸어 나가 채점한다. ckpt 가 있으면 끝난 층의 채점 결과를 저장해 두고, 다시 실행되면 그 층은 건너뛴다
    (층끼리는 서로의 출력을 쓰지 않으므로 이어서 계산해도 결과가 같다)."""
    lab = L4()
    if P is None or len(P["date"]) == 0:
        return None
    path = None if ckpt is None else Path(ckpt) / f"layer_{name}.pkl"
    key = _layer_key(name, P, smoke)
    saved = _load_layer(path, key)
    if saved is not None:
        log(f"{name} 체크포인트에서 이어받음")
        return {"P": P, **saved}
    t0 = time.time()
    o3 = lab.L3.walk3(P, progress=lambda i, n: log(f"{name} 3판 걸어 나가기 {i}/{n}"))
    out = lab.walk4(P, progress=lambda i, n: log(f"{name} 4판 걸어 나가기 {i}/{n}"), out3=o3)
    del o3
    cells = lab.score_layer4(P, out, R1().ERAS[name], JUDGED_END, ALPHA)
    holdout = holdout_cells(P, out)
    # 점마다의 예측·손실 배열은 채점이 끝나면 쓰지 않는다 — 다음 층과 함께 들고 있으면 메모리만 차지한다
    layer = {"out": {k: v for k, v in out.items() if k not in BULKY}, "cells": cells, "holdout": holdout}
    del out
    gc.collect()
    if path is not None:
        _save_layer(path, key, layer)
    log(f"{name} 완료: 점 {len(P['date'])}개, {time.time() - t0:.0f}초")
    return {"P": P, **layer}


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
                  "skill_vs_clim": c["vs_clim"]["skill"], "grade_vs_clim": c["vs_clim"]["grade"],
                  "v1_skill_vs_clim": c["v1_vs_clim"]["skill"], "v1_grade_vs_clim": c["v1_vs_clim"]["grade"]}
    return v


def switch_advice(verdicts: dict) -> dict:
    """판단판을 4판으로 바꾸기를 제안할 만한가, 3판보다 4판을 권할 만한가(미리 고정한 기준, 자동 반영 아님 — 사용자 확인이 필요하다)."""
    judged = [v for v in verdicts.values() if v["label"] != "NOT_EVALUABLE"]
    n_pass = sum(v["label"] == "BEATS_V1" for v in judged)
    n_pass3 = sum(v.get("v3_label") == "BEATS_V1" for v in judged)
    worst = min((v["skill"] for v in judged if v.get("skill") is not None), default=None)
    vs3 = [v["skill_vs_v3"] for v in judged if v.get("skill_vs_v3") is not None]
    ok = bool(n_pass >= SWITCH_MIN_PASS and worst is not None and worst >= SWITCH_WORST)
    prefer = bool(ok and vs3 and n_pass >= n_pass3 and float(np.mean(vs3)) > 0 and min(vs3) >= PREFER_WORST_VS_V3)
    return {"propose_switch": ok, "prefer_v4_over_v3": prefer, "n_pass": int(n_pass), "n_pass_v3": int(n_pass3), "n_judged": len(judged),
            "worst_skill_vs_v1": worst, "mean_skill_vs_v3": float(np.mean(vs3)) if vs3 else None, "worst_skill_vs_v3": min(vs3) if vs3 else None,
            "rule": f"BEATS_V1 {SWITCH_MIN_PASS}개 이상이고 1판 대비 기량이 {SWITCH_WORST} 아래인 열쇠가 없음",
            "rule_prefer": f"위 기준을 채우고, 통과 수가 3판(같은 실행에서 다시 계산) 이상, 3판 대비 기량 평균 > 0, 3판 대비 기량이 {PREFER_WORST_VS_V3} 아래인 열쇠가 없음"}


def layer_model(P: dict, out: dict) -> dict:
    """실시간 예측(lab.forecast_live4)이 읽는 층 설정."""
    lab = L4()
    r = lambda a: np.round(a, 6).tolist()  # noqa: E731
    return {"feats": list(P["feats"]), "hx": list(P["hx"]), "sixth": P["sixth"], "weights1": r(out["weights1"]), "weights4": r(out["weights4"]),
            "shifts4": r(out["shifts4"]), "blend4": r(out["blend4"]), "cal_active4": [bool(x) for x in out["cal_active4"]],
            "xs_grid": lab.L2.xs_grid(P), "last_origin": str(P["date"][-1])}


def model_of(layers: dict, data_info: dict, smoke: bool) -> dict:
    lab = L4()
    m = {"study": STUDY, "lab_version": lab.LAB_VERSION, "data_end": DATA_END, "smoke": smoke, "horizons": list(lab.HORIZONS),
         "taus": list(lab.TAUS), "events": list(lab.EVENTS), "pool": list(lab.POOL4), "kinds": list(lab.KINDS), "alpha_family": ALPHA, "layers": {}}
    for name, r in layers.items():
        if r is None:
            continue
        lm = layer_model(r["P"], r["out"])
        lm.update(library=f"library_{name}.csv", borrow_library="library_industry.csv" if r["P"].get("borrow") is not None else None,
                  cells={k: {"grade": c["vs_clim"]["grade"], "skill": c["vs_clim"]["skill"], "p": c["vs_clim"]["p"],
                             "evaluable": c["vs_clim"]["evaluable"], "grade_vs_v1": c["vs_v1"]["grade"], "skill_vs_v1": c["vs_v1"]["skill"],
                             "grade_vs_v3": c["vs_v3"]["grade"], "skill_vs_v3": c["vs_v3"]["skill"], "v1_grade": c["v1_vs_clim"]["grade"],
                             "coverage80": (c.get("coverage80") or {}).get("V4")} for k, c in r["cells"].items()})
        m["layers"][name] = lm
    m["data"] = data_info
    return m


def now_reading(layers: dict, fr: dict) -> Optional[dict]:
    """시장의 마지막 날 읽기(보고용). 저장하는 모형과 같은 경로(export_library4 → forecast_live4)로 계산한다."""
    lab = L4()
    r = layers.get("market")
    st = None if r is None else lab.L2.latest_state2(fr["mlp"])
    if st is None:
        return None
    lib = lab.library_from_frame4(lab.export_library4(r["P"]))
    ind = layers.get("industry")
    blib = None if ind is None or r["P"].get("borrow") is None else lab.library_from_frame4(lab.export_library4(ind["P"]))
    f = lab.forecast_live4(lib, layer_model(r["P"], r["out"]), st, blib)
    num = lambda a: [None if not np.isfinite(v) else float(v) for v in a]  # noqa: E731
    ex = lambda a: [None if not np.isfinite(v) else float(math.expm1(v)) for v in a]  # noqa: E731
    rows = [{"h": h, "q_v4": ex(f["q"]["V4"][hi]), "q_v1": ex(f["q"]["ENS1"][hi]), "q_clim": ex(f["q"]["CLIM"][hi]),
             "p_v4": num(f["p"]["V4"][hi]), "p_har": num(f["p"]["HAR"][hi]), "p_ddl": num(f["p"]["DDLOGIT"][hi]), "p_v1": num(f["p"]["ENS1"][hi]),
             "p_clim": num(f["p"]["CLIM"][hi]), "n": f["n"][hi]} for hi, h in enumerate(lab.HORIZONS)]
    return {"date": str(st["date"].date()), "dd": float(math.expm1(st["x"][0])), "rows": rows}


def run(smoke: bool, ckpt: Optional[Path] = None) -> tuple:
    lab = L4()
    fr, points, data_info = R3().build_layers(smoke)
    layers = {name: run_layer(name, points[name], ckpt, smoke) for name in LAYERS}
    verdicts = verdicts_of(layers)
    summary = {k: (f"{v['label']} · 등급 {v['grade']}" + ("" if v["label"] == "NOT_EVALUABLE" else
                                                         f" · 1판 대비 기량 {v['skill']:+.3f} · p {v['p']:.4f} · 3판 대비 {v['skill_vs_v3']:+.3f}"))
               for k, v in verdicts.items()}
    res = {"study": STUDY, "rules_version": RULES_VERSION, "lab_version": lab.LAB_VERSION, "smoke": smoke, "data_end": DATA_END,
           "judged_end": JUDGED_END, "family": {"keys": [k for k, _, _ in FAMILY], "alpha": ALPHA, "alpha_expr": "0.05/8"},
           "verdicts": verdicts, "switch_advice": switch_advice(verdicts), "summary": summary, "data": data_info, "limits": LIMITS,
           "layers": {n: None if r is None else {"n_points": int(len(r["P"]["date"])), "n_assets": len(r["P"]["names"]), "sixth": r["P"]["sixth"],
                                                 "first_origin": str(r["P"]["date"][0]), "last_origin": str(r["P"]["date"][-1]),
                                                 "weights4": np.round(r["out"]["weights4"], 4).tolist(),
                                                 "shifts4": np.round(r["out"]["shifts4"], 4).tolist(),
                                                 "blend4": np.round(r["out"]["blend4"], 4).tolist(),
                                                 "realized_dates": r["out"]["realized_dates"].astype(int).tolist(),
                                                 "blend_dates": r["out"]["blend_dates"].astype(int).tolist(),
                                                 "cells": r["cells"], "holdout": r["holdout"]} for n, r in layers.items()},
           "now": now_reading(layers, fr)}
    return res, layers, model_of(layers, data_info, smoke)


# ---------------------------------------------------------------- 보고서
def report(res: dict) -> str:
    lab, r1 = L4(), R1()
    _f, _pct, KN, LN = r1._f, r1._pct, r1.KIND_NAMES, r1.LAYER_NAMES
    adv = res["switch_advice"]
    yn = lambda b: "제안함" if b else "제안하지 않음"  # noqa: E731
    out = [f"# {STUDY} — 판단 엔진 4판: 쌓기·낙폭 확률 전문가·보정 전후 쌓기 대 1판 앙상블", ""]
    if res["smoke"]:
        out += ["**스모크(가짜 자료) 실행 — 숫자에 뜻이 없다.**", ""]
    out += ["## 한눈에", "",
            "- 무엇을 했나: 1판·2판·3판과 같은 자료·같은 점에서, (1) 전문가 가중을 '섞은 결과의 실현 손실이 가장 작아지게 하나씩 더하는' 쌓기로 정하고,",
            "  (2) 낙폭 확률 전문가 DDLOGIT(HAR 확률을 출발점으로 상태에 따라 고치는 벌점 로지스틱 회귀)을 더하고, (3) 범위 보정 전·후도 같은 쌓기로 섞었다(V4).",
            "  재무 순위 전문가(FUND)는 뺐다 — 4판은 가격 자료만으로 예측한다.",
            "- 비교 대상: 1판 앙상블(ENS1, 판정)과 3판 최종(V3, 보고) — 둘 다 같은 걸어 나가기 안에서 원래 규칙 그대로 다시 계산.",
            f"- 판정 8개(유의수준 0.05/8 = {ALPHA:.5f}). 등급(강함·보통·약함·없음)은 판정과 별도로 모든 칸에 매긴다.",
            f"- 판단판 교체 제안 기준(미리 고정, 자동 반영 아님): {adv['rule']} → **{yn(adv['propose_switch'])}** "
            f"(통과 {adv['n_pass']}/{adv['n_judged']}, 가장 나쁜 열쇠 {_f(adv['worst_skill_vs_v1'])}).",
            f"- 3판보다 4판을 권하는 기준(미리 고정): {adv['rule_prefer']} → **{'4판을 권함' if adv['prefer_v4_over_v3'] else '4판을 권하지 않음'}** "
            f"(3판 통과 {adv['n_pass_v3']}/{adv['n_judged']}, 3판 대비 기량 평균 {_f(adv['mean_skill_vs_v3'])}, 가장 나쁜 열쇠 {_f(adv['worst_skill_vs_v3'])}).", "",
            "## 판정 (V4 대 1판)", "",
            "| 열쇠 | 층 | 칸 | 판정 | 1판 대비 기량 | p | 시대별 | 3판 대비 기량 (p, 등급) | 3판의 판정 · 1판 대비 (p) | HAR 단독 대비 (p) | 과거 평균 대비: 4판 (등급) | 1판 (등급) |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in res["verdicts"].items():
        h, kind = v["cell"].split(":")
        eras = " · ".join(f"{n} {_f(s)}" for n, s in (v.get("eras") or {}).items()) or "—"
        out.append(f"| {k} | {LN[v['layer']]} | {h}일 {KN[kind]} | {v['label']} | {_f(v.get('skill'))} | {_f(v.get('p'), '{:.4f}')} | {eras} | "
                   f"{_f(v.get('skill_vs_v3'))} ({_f(v.get('p_vs_v3'), '{:.3f}')}, {v.get('grade_vs_v3', '—')}) | "
                   f"{v.get('v3_label', '—')} · {_f(v.get('v3_skill_vs_v1'))} ({_f(v.get('v3_p_vs_v1'), '{:.4f}')}) | "
                   f"{_f(v.get('skill_vs_har'))} ({_f(v.get('p_vs_har'), '{:.3f}')}) | "
                   f"{_f(v.get('skill_vs_clim'))} ({v.get('grade_vs_clim', '—')}) | {_f(v.get('v1_skill_vs_clim'))} ({v.get('v1_grade_vs_clim', '—')}) |")
    out += ["", "기량 = 1 − 손실(4판)/손실(비교 대상). 양수면 4판이 더 잘 맞혔다.", ""]
    for name in LAYERS:
        r = res["layers"].get(name)
        out += [f"## {LN[name]} 층", ""]
        if r is None:
            out += [f"평가 불가 — {(res['data'].get('stock') or {}).get('reason', '자료 없음') if name == 'stock' else '자료 없음'}", ""]
            continue
        six = r["sixth"]
        out += [f"점 {r['n_points']:,}개 · 자산 {r['n_assets']}개 · 기준일 {r['first_origin']} ~ {r['last_origin']} · 여섯째 전문가 {six}_H", "",
                f"| 기간 | 종류 | 4판 등급(대 평균) | 기량 | 4판 대 1판 (p, 등급) | 4판 대 3판 (p, 등급) | 4판 대 HAR (p) | 보정 전 대 1판 | DDLOGIT 대 HAR (p) | "
                f"VOL | HAR | ANALOG_H | TILT_H | {six}_H | DDLOGIT | 3판 | 80% 구간 적중 1판 → 3판 → 보정 전 → 4판 | 2024-10~ 대 1판 / 대 3판(보고) |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for key, c in r["cells"].items():
            h, kind = key.split(":")
            es, cv, ho = c.get("expert_skill") or {}, c.get("coverage80") or {}, (r["holdout"] or {}).get(key) or {}
            cov = "—" if not cv else " → ".join(_f(cv.get(e), "{:.1%}") for e in ("ENS1", "V3", "STK4", "V4"))
            cmp = lambda d, g=True: f"{_f(d['skill'])} ({_f(d['p'], '{:.3f}')}" + (f", {d['grade']})" if g else ")")  # noqa: E731
            out.append(f"| {h}일 | {KN[kind]} | {c['vs_clim']['grade']} | {_f(c['vs_clim']['skill'])} | {cmp(c['vs_v1'])} | {cmp(c['vs_v3'])} | "
                       f"{cmp(c['vs_har'], False)} | {_f(c['stk4_vs_v1']['skill'])} | {cmp(c['ddl_vs_har'], False) if kind == 'dd15' else '—'} | " +
                       " | ".join(_f(es.get(e)) for e in ("VOL", "HAR", "ANALOG_H", "TILT_H", "SIXTH_H", "DDLOGIT", "V3")) +
                       f" | {cov} | {_f(ho.get('skill_vs_v1'))} / {_f(ho.get('skill_vs_v3'))} (n {ho.get('n_points', 0)}) |")
        out += ["", "마지막 쌓기 가중(전문가 순서 " + " · ".join(six + "_H" if e == "SIXTH_H" else e for e in lab.POOL4) + "):", "",
                "| 기간 | " + " | ".join(KN[k] for k in lab.KINDS) + " |", "|---|" + "---|" * len(lab.KINDS)]
        for hi, h in enumerate(lab.HORIZONS):
            out.append(f"| {h}일 | " + " | ".join(" / ".join(f"{w:.2f}" for w in r["weights4"][hi][k]) for k in range(len(lab.KINDS))) + " |")
        out += ["", "범위 보정 이동(변동성 단위, 분위수 10·25·50·75·90%)과 섞는 가중(보정 전 / 보정 후): " +
                " · ".join(f"{h}일 [" + ", ".join(f"{s:+.2f}" for s in r["shifts4"][hi]) + f"] {r['blend4'][hi][0]:.2f}/{r['blend4'][hi][1]:.2f}"
                           for hi, h in enumerate(lab.HORIZONS)), ""]
    now = res.get("now")
    if now:
        out += ["## 시장의 지금 읽기 (설명용, 추천 아님)", "", f"기준일 {now['date']} · 1년 고점 대비 {_pct(now['dd'])}", "",
                "| 기간 | 4판 10% | 25% | 중앙 | 75% | 90% | 1판 10%~90% | 15% 이상 빠질 확률(4판/DDLOGIT/HAR/1판/평균) |", "|---|---|---|---|---|---|---|---|"]
        for row in now["rows"]:
            out.append(f"| {row['h']}일 | " + " | ".join(_pct(v) for v in row["q_v4"]) + f" | {_pct(row['q_v1'][0])} ~ {_pct(row['q_v1'][4])} | " +
                       " / ".join(_f(row[k][1], "{:.0%}") for k in ("p_v4", "p_ddl", "p_har", "p_v1", "p_clim")) + " |")
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
    lab = L4()
    for name in LAYERS:
        r = layers.get(name)
        df = pd.DataFrame(columns=["dd"]) if r is None else lab.export_library4(r["P"])
        df.to_csv(out / f"library_{name}.csv", index=False)
    (out / "model.json").write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
