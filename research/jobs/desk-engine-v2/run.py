"""desk-engine-v2 — 판단 엔진 2판: 전문가 6명 + 증거 가중 + 구간 보정(V2) 대 1판 앙상블(ENS1), 시장·업종·종목 세 층.

python research/jobs/desk-engine-v2/run.py --out OUT --checkpoint CK [--smoke]

규칙·판정은 SPEC.md 와 research/jobs/desk-engine-lab-v2/SPEC.md(결과 보기 전 고정, 사전 등록 2026-11-24). 장부 H-031.
자료·점 집합·시대·판정 대상 기간은 desk-engine-v1 과 같다(1판 run.py 의 자료 읽기를 그대로 쓴다). 체크포인트는 쓰지 않는다.
산출: results.json, REPORT.md, model.json, library_{market,industry,stock}.csv.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
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
STUDY = "desk-engine-v2"
RULES_VERSION = "desk-engine/v2"
DATA_END = "2026-11-20"
JUDGED_END = "2024-09-30"
LAYERS = ("market", "industry", "stock")
FAMILY = (("MKT_Q63", "market", "63:q"), ("MKT_DD63", "market", "63:dd15"), ("IND_Q63", "industry", "63:q"),
          ("IND_DD63", "industry", "63:dd15"), ("IND_BEAT63", "industry", "63:beat"), ("STK_Q63", "stock", "63:q"),
          ("STK_DD63", "stock", "63:dd15"), ("STK_BEAT63", "stock", "63:beat"))
ALPHA = 0.05 / len(FAMILY)
LABELS = ("BEATS_V1", "FAIL", "NOT_EVALUABLE")
LIMITS = [
    "2판의 설계는 1판 결과(같은 자료)를 보고 정했다. 판정 기간의 통과는 그만큼 덜 믿을 만하다 — 2024-10 이후 보고값과 판단판의 실전 기록이 깨끗한 확인이다.",
    "종목 층은 Yahoo 수정 종가라 상장폐지 종목이 빠져 있다(생존 편향). 하락 위험이 실제보다 낮게 잡힌다.",
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


def L2():
    return _load("desk_engine_lab_v2", "research/jobs/desk-engine-lab-v2/lab.py")


def R1():
    """1판 run.py — 자료 읽기·시대·표기 도우미를 그대로 쓴다."""
    return _load("desk_engine_v1", "research/jobs/desk-engine-v1/run.py")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 자료(점 집합은 1판과 같다)
def _points(frames: dict, origins, with_market: bool, borrow: Optional[dict] = None) -> dict:
    lab = L2()
    return lab.attach(lab.V.build_points(frames, origins, with_market=with_market), frames, with_market, borrow)


def _layered_frame(lp: pd.Series, mlp: pd.Series, ms: pd.DataFrame, keep) -> pd.DataFrame:
    f = L2().asset_frame2(lp, mlp)
    f[["mdd", "mvolr", "m21", "m252"]] = ms
    return f.loc[f.index.intersection(keep)]


def industry_points(fr: dict) -> Optional[dict]:
    if fr["ind"] is None or fr["ind"].shape[1] == 0:
        return None
    ms = L2().market_state2(fr["mlp"])
    origins = fr["mlp"].index[252::L2().V.STEP]
    frames = {str(col).strip(): _layered_frame(np.log1p(fr["ind"][col]).cumsum(), fr["mlp"], ms, origins) for col in fr["ind"].columns}
    return _points(frames, origins, True)


def market_points(fr: dict, borrow: Optional[dict]) -> dict:
    return _points({"MKT": L2().asset_frame2(fr["mlp"])}, fr["mlp"].index[252::L2().V.STEP], False, borrow)


def stock_points(smoke: bool) -> tuple:
    """(점 표 또는 None, 자료 정보). 1판 stock_points 와 같은 자료·같은 편입 규칙."""
    lab, r1 = L2(), R1()
    if smoke:
        m, assets = lab.V.synthetic_panel(n_assets=14, n_days=6400, seed=11)
        ms = lab.market_state2(m)
        origins = m.index[252::lab.V.STEP]
        frames = {k: _layered_frame(lp, m, ms, origins) for k, lp in assets.items()}
        return _points(frames, origins, True), {"source": "synthetic (smoke)", "tickers": len(frames)}
    from core import market_data as md
    from core import point_in_time_universe as pit

    spy = r1._adj(md._load_store(md._store_path("SPY", "1d")))
    if spy is None or spy.dropna().empty:
        return None, {"reason": "SPY 가격 파일 없음"}
    spy = spy.dropna()
    spy = spy[spy.index <= DATA_END]
    cal = spy.index[spy.index >= "1995-01-01"]
    if len(cal) < 2000:
        return None, {"reason": "SPY 이력이 짧음"}
    mlp = np.log(spy.reindex(cal))
    origins = cal[252::lab.V.STEP]
    origins = origins[origins >= r1.STOCK_START]
    table = pit.load_historical_constituents_table()
    pos = np.searchsorted(table["date"].to_numpy(), origins.to_numpy(), side="right") - 1
    members = [set(table["tickers_list"].iloc[max(p, 0)]) for p in pos]
    tickers = sorted(set().union(*members)) if members else []
    ms = lab.market_state2(mlp)
    frames, missing = {}, 0
    for i, t in enumerate(tickers):
        s = r1._adj(md._load_store(md._store_path(t, "1d")))
        if s is None or s.dropna().empty:
            missing += 1
            continue
        memb = origins[[t in mset for mset in members]]
        if not len(memb):
            continue
        frames[t] = _layered_frame(np.log(s.reindex(cal).ffill(limit=r1.STOCK_FFILL)), mlp, ms, memb)
        if i % 300 == 0:
            log(f"종목 자료 {i}/{len(tickers)}")
    info = {"source": "Yahoo 수정 종가(VM 가격 저장소) + S&P500 그 시점 편입", "tickers_in_universe": len(tickers),
            "tickers_with_prices": len(frames), "tickers_missing": missing, "calendar": [str(cal[0].date()), str(cal[-1].date())]}
    if len(frames) < r1.MIN_STOCK_TICKERS:
        info["reason"] = f"가격 파일이 {len(frames)}개뿐(최소 {r1.MIN_STOCK_TICKERS})"
        return None, info
    return _points(frames, origins, True), info


# ---------------------------------------------------------------- 계산
def holdout_cells(P: dict, out: dict) -> dict:
    """2024-10 이후 기준일 예측(보고만): V2 의 기량(대 CLIM·대 ENS1)."""
    lab = L2()
    res = {}
    late = P["date"] > np.datetime64(JUDGED_END)
    for hi, h in enumerate(lab.HORIZONS):
        for k, kind in enumerate(lab.KINDS):
            Lm = lab.cell_loss(out, hi, k)
            ok = late & np.isfinite(Lm).all(axis=1)
            if ok.any():
                m = Lm[ok].mean(axis=0)
                res[f"{h}:{kind}"] = {"n_points": int(ok.sum()), "skill_vs_clim": lab.V._skill(m[0], m[lab.I_V2]),
                                      "skill_vs_v1": lab.V._skill(m[lab.I_ENS1], m[lab.I_V2])}
    return res


def run_layer(name: str, P: Optional[dict]) -> Optional[dict]:
    lab = L2()
    if P is None or len(P["date"]) == 0:
        return None
    t0 = time.time()
    out = lab.walk2(P, progress=lambda i, n: log(f"{name} 걸어 나가기 {i}/{n}"))
    cells = lab.score_layer2(P, out, R1().ERAS[name], JUDGED_END, ALPHA)
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
                  "skill_vs_clim": c["vs_clim"]["skill"], "grade_vs_clim": c["vs_clim"]["grade"],
                  "v1_skill_vs_clim": c["v1_vs_clim"]["skill"], "v1_grade_vs_clim": c["v1_vs_clim"]["grade"]}
    return v


def model_of(layers: dict, data_info: dict, smoke: bool) -> dict:
    lab = L2()
    m = {"study": STUDY, "lab_version": lab.LAB_VERSION, "data_end": DATA_END, "smoke": smoke, "horizons": list(lab.HORIZONS),
         "taus": list(lab.TAUS), "events": list(lab.EVENTS), "experts": list(lab.EXPERTS2), "kinds": list(lab.KINDS),
         "alpha_family": ALPHA, "layers": {}}
    for name, r in layers.items():
        if r is None:
            continue
        P, out = r["P"], r["out"]
        m["layers"][name] = {
            "feats": list(P["feats"]), "hx": list(P["hx"]), "sixth": P["sixth"], "library": f"library_{name}.csv",
            "borrow_library": "library_industry.csv" if P.get("borrow") is not None else None,
            "weights1": np.round(out["weights1"], 6).tolist(), "weights2": np.round(out["weights2"], 6).tolist(),
            "shifts": np.round(out["shifts"], 6).tolist(), "xs_grid": lab.xs_grid(P), "last_origin": str(P["date"][-1]),
            "cells": {k: {"grade": c["vs_clim"]["grade"], "skill": c["vs_clim"]["skill"], "p": c["vs_clim"]["p"],
                          "evaluable": c["vs_clim"]["evaluable"], "grade_vs_v1": c["vs_v1"]["grade"], "skill_vs_v1": c["vs_v1"]["skill"],
                          "v1_grade": c["v1_vs_clim"]["grade"], "coverage80": (c.get("coverage80") or {}).get("V2")}
                      for k, c in r["cells"].items()}}
    m["data"] = data_info
    return m


def now_reading(layers: dict, fr: dict) -> Optional[dict]:
    """시장의 마지막 날 읽기(보고용). 저장하는 모형과 같은 경로(export_library2 → forecast_live2)로 계산한다."""
    lab = L2()
    r = layers.get("market")
    st = None if r is None else lab.latest_state2(fr["mlp"])
    if st is None:
        return None
    lib = lab.library_from_frame2(lab.export_library2(r["P"]))
    ind = layers.get("industry")
    blib = None if ind is None or r["P"].get("borrow") is None else lab.library_from_frame2(lab.export_library2(ind["P"]))
    f = lab.forecast_live2(lib, r["out"]["weights2"], r["out"]["shifts"], st, r["P"]["sixth"], None, blib, r["out"]["weights1"])
    num = lambda a: [None if not np.isfinite(v) else float(v) for v in a]  # noqa: E731
    rows = [{"h": h, "q_v2": [float(math.expm1(v)) for v in f["q"]["V2"][hi]], "q_v1": [float(math.expm1(v)) for v in f["q"]["ENS1"][hi]],
             "q_clim": [float(math.expm1(v)) for v in f["q"]["CLIM"][hi]], "p_v2": num(f["p"]["V2"][hi]), "p_v1": num(f["p"]["ENS1"][hi]),
             "p_clim": num(f["p"]["CLIM"][hi]), "n": f["n"][hi]} for hi, h in enumerate(lab.HORIZONS)]
    return {"date": str(st["date"].date()), "dd": float(math.expm1(st["x"][0])), "rows": rows}


def run(smoke: bool) -> tuple:
    lab, r1 = L2(), R1()
    fr = r1.load_french(smoke)
    log(f"French 자료 {fr['mlp'].index[0].date()} ~ {fr['mlp'].index[-1].date()}")
    ind = industry_points(fr)
    layers: dict = {"market": run_layer("market", market_points(fr, ind)), "industry": run_layer("industry", ind)}
    sp, sinfo = stock_points(smoke)
    layers["stock"] = run_layer("stock", sp)
    data_info = {"french": {"source": fr["source"], "first": str(fr["mlp"].index[0].date()), "last": str(fr["mlp"].index[-1].date()),
                            "industries": 0 if fr["ind"] is None else int(fr["ind"].shape[1])}, "stock": sinfo}
    verdicts = verdicts_of(layers)
    summary = {k: (f"{v['label']} · 등급 {v['grade']}" + ("" if v["label"] == "NOT_EVALUABLE" else f" · 1판 대비 기량 {v['skill']:+.3f} · p {v['p']:.4f}"))
               for k, v in verdicts.items()}
    res = {"study": STUDY, "rules_version": RULES_VERSION, "lab_version": lab.LAB_VERSION, "smoke": smoke, "data_end": DATA_END,
           "judged_end": JUDGED_END, "family": {"keys": [k for k, _, _ in FAMILY], "alpha": ALPHA, "alpha_expr": "0.05/8"},
           "verdicts": verdicts, "summary": summary, "data": data_info, "limits": LIMITS,
           "layers": {n: None if r is None else {"n_points": int(len(r["P"]["date"])), "n_assets": len(r["P"]["names"]), "sixth": r["P"]["sixth"],
                                                 "first_origin": str(r["P"]["date"][0]), "last_origin": str(r["P"]["date"][-1]),
                                                 "weights2": np.round(r["out"]["weights2"], 4).tolist(),
                                                 "shifts": np.round(r["out"]["shifts"], 4).tolist(),
                                                 "realized_dates": r["out"]["realized_dates"].astype(int).tolist(),
                                                 "cells": r["cells"], "holdout": r["holdout"]} for n, r in layers.items()},
           "now": now_reading(layers, fr)}
    return res, layers, model_of(layers, data_info, smoke)


# ---------------------------------------------------------------- 보고서
def report(res: dict) -> str:
    lab, r1 = L2(), R1()
    _f, _pct, KN, LN = r1._f, r1._pct, r1.KIND_NAMES, r1.LAYER_NAMES
    out = [f"# {STUDY} — 판단 엔진 2판: 전문가 6명·증거 가중·구간 보정 대 1판 앙상블", ""]
    if res["smoke"]:
        out += ["**스모크(가짜 자료) 실행 — 숫자에 뜻이 없다.**", ""]
    out += ["## 한눈에", "",
            "- 무엇을 했나: 1판과 같은 자료·같은 점에서, 전문가 둘(변동성 회귀 HAR, 여섯째 = 업종·종목은 자산 간 순위 XRANK / 시장은 업종 서고 빌리기 BORROW)을 더하고,",
            "  가중을 '가장 나은 전문가보다 얼마나 뚜렷이 나쁜가(t 값)'로 바꾸고, 수익 범위를 과거 적중률에 맞춰 이동했다(V2).",
            "- 비교 대상: 1판 앙상블(ENS1 — 같은 걸어 나가기 안에서 1판 규칙 그대로 다시 계산).",
            f"- 판정 8개(유의수준 0.05/8 = {ALPHA:.5f}). 등급(강함·보통·약함·없음)은 판정과 별도로 모든 칸에 매긴다.", "",
            "## 판정 (V2 대 1판)", "", "| 열쇠 | 층 | 칸 | 판정 | 1판 대비 기량 | p | 시대별 | 과거 평균 대비 기량: 2판 (등급) | 1판 (등급) |", "|---|---|---|---|---|---|---|---|---|"]
    for k, v in res["verdicts"].items():
        h, kind = v["cell"].split(":")
        eras = " · ".join(f"{n} {_f(s)}" for n, s in (v.get("eras") or {}).items()) or "—"
        out.append(f"| {k} | {LN[v['layer']]} | {h}일 {KN[kind]} | {v['label']} | {_f(v.get('skill'))} | {_f(v.get('p'), '{:.4f}')} | {eras} | "
                   f"{_f(v.get('skill_vs_clim'))} ({v.get('grade_vs_clim', '—')}) | {_f(v.get('v1_skill_vs_clim'))} ({v.get('v1_grade_vs_clim', '—')}) |")
    out += ["", "기량 = 1 − 손실(2판)/손실(비교 대상). 양수면 2판이 더 잘 맞혔다.", ""]
    for name in LAYERS:
        r = res["layers"].get(name)
        out += [f"## {LN[name]} 층", ""]
        if r is None:
            out += [f"평가 불가 — {(res['data'].get('stock') or {}).get('reason', '자료 없음') if name == 'stock' else '자료 없음'}", ""]
            continue
        six = r["sixth"]
        out += [f"점 {r['n_points']:,}개 · 자산 {r['n_assets']}개 · 기준일 {r['first_origin']} ~ {r['last_origin']} · 여섯째 전문가 {six}", "",
                f"| 기간 | 종류 | 2판 등급(대 평균) | 기량 | 1판 등급 | 1판 기량 | 2판 대 1판 (p, 등급) | 보정 전 대 1판 | VOL | HAR | {six} | 80% 구간 적중 1판 → 2판 | 2024-10~ 대 1판(보고) |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for key, c in r["cells"].items():
            h, kind = key.split(":")
            es, cv, ho = c.get("expert_skill") or {}, c.get("coverage80") or {}, (r["holdout"] or {}).get(key) or {}
            cov = "—" if not cv else f"{_f(cv.get('ENS1'), '{:.1%}')} → {_f(cv.get('V2'), '{:.1%}')}"
            out.append(f"| {h}일 | {KN[kind]} | {c['vs_clim']['grade']} | {_f(c['vs_clim']['skill'])} | {c['v1_vs_clim']['grade']} | {_f(c['v1_vs_clim']['skill'])} | "
                       f"{_f(c['vs_v1']['skill'])} ({_f(c['vs_v1']['p'], '{:.3f}')}, {c['vs_v1']['grade']}) | {_f(c['ens2_vs_v1']['skill'])} | {_f(es.get('VOL'))} | "
                       f"{_f(es.get('HAR'))} | {_f(es.get('SIXTH'))} | {cov} | {_f(ho.get('skill_vs_v1'))} (n {ho.get('n_points', 0)}) |")
        out += ["", "마지막 증거 가중(전문가 순서 CLIM · VOL · ANALOG · TILT · HAR · " + six + "):", "",
                "| 기간 | " + " | ".join(KN[k] for k in lab.KINDS) + " |", "|---|" + "---|" * len(lab.KINDS)]
        for hi, h in enumerate(lab.HORIZONS):
            out.append(f"| {h}일 | " + " | ".join(" / ".join(f"{w:.2f}" for w in r["weights2"][hi][k]) for k in range(len(lab.KINDS))) + " |")
        out += ["", "구간 보정 이동(변동성 단위, 분위수 10·25·50·75·90%): " +
                " · ".join(f"{h}일 [" + ", ".join(f"{s:+.2f}" for s in r["shifts"][hi]) + "]" for hi, h in enumerate(lab.HORIZONS)), ""]
    now = res.get("now")
    if now:
        out += ["## 시장의 지금 읽기 (설명용, 추천 아님)", "", f"기준일 {now['date']} · 1년 고점 대비 {_pct(now['dd'])}", "",
                "| 기간 | 2판 10% | 25% | 중앙 | 75% | 90% | 1판 10%~90% | 15% 이상 빠질 확률(2판/1판/평균) |", "|---|---|---|---|---|---|---|---|"]
        for row in now["rows"]:
            out.append(f"| {row['h']}일 | " + " | ".join(_pct(v) for v in row["q_v2"]) + f" | {_pct(row['q_v1'][0])} ~ {_pct(row['q_v1'][4])} | "
                       f"{_f(row['p_v2'][1], '{:.0%}')} / {_f(row['p_v1'][1], '{:.0%}')} / {_f(row['p_clim'][1], '{:.0%}')} |")
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
    lab = L2()
    for name in LAYERS:
        r = layers.get(name)
        df = pd.DataFrame(columns=["dd"]) if r is None else lab.export_library2(r["P"])
        df.to_csv(out / f"library_{name}.csv", index=False)
    (out / "model.json").write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
