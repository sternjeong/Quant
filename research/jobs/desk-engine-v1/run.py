"""desk-engine-v1 — 판단 엔진 1판: 온라인 앙상블 분포 예측(ENS) 대 과거 평균 분포(CLIM), 시장·업종·종목 세 층.

python research/jobs/desk-engine-v1/run.py --out OUT --checkpoint CK [--smoke]

규칙·판정은 SPEC.md 와 research/jobs/desk-engine-lab/SPEC.md(결과 보기 전 고정, 사전 등록 2026-11-23). 장부 H-030.
계산은 공용 lab(desk-engine-lab/lab.py)이 한다. 체크포인트는 쓰지 않는다(--checkpoint 폴더만 만든다).
산출: results.json, REPORT.md, model.json, library_{market,industry,stock}.csv (실시간 판단판이 읽는 모형).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
STUDY = "desk-engine-v1"
RULES_VERSION = "desk-engine/v1"
DATA_END = "2026-11-20"
JUDGED_END = "2024-09-30"
LAYERS = ("market", "industry", "stock")
LAYER_NAMES = {"market": "시장", "industry": "업종(49 산업)", "stock": "종목(S&P500 편입)"}
ERAS = {
    "market": [("A", "1937-01-01", "1966-12-31"), ("B", "1967-01-01", "2007-12-31"), ("C", "2008-01-01", "2024-09-30")],
    "industry": [("A", "1937-01-01", "1966-12-31"), ("B", "1967-01-01", "2007-12-31"), ("C", "2008-01-01", "2024-09-30")],
    "stock": [("S1", "2001-01-01", "2012-12-31"), ("S2", "2013-01-01", "2024-09-30")],
}
FAMILY = (("MKT_Q63", "market", "63:q"), ("MKT_DD63", "market", "63:dd15"), ("IND_Q63", "industry", "63:q"),
          ("IND_DD63", "industry", "63:dd15"), ("STK_Q63", "stock", "63:q"), ("STK_DD63", "stock", "63:dd15"))
ALPHA = 0.05 / len(FAMILY)
LABELS = ("BEATS_CLIM", "FAIL", "NOT_EVALUABLE")
STOCK_START = "1996-01-02"
STOCK_FFILL = 5
MIN_STOCK_TICKERS = 300
KIND_NAMES = {"q": "수익 분포", "up": "오를 확률", "dd15": "15% 이상 빠질 확률", "beat": "시장을 이길 확률"}
LIMITS = [
    "종목 층은 Yahoo 수정 종가라 상장폐지 종목이 빠져 있다(생존 편향). 하락 위험이 실제보다 낮게 잡힌다.",
    "겹치는 기간의 예측은 독립이 아니다. 달력 구획 검정은 이를 줄일 뿐 없애지 못한다.",
    "CLIM(과거 평균)은 자산별 변동성 차이를 무시하는 낮은 기준선이다. ENS 대 VOL 등급이 상태 정보의 추가 이득이다.",
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


def L():
    return _load("desk_engine_lab", "research/jobs/desk-engine-lab/lab.py")


def crash_lab():
    return _load("crash_cycle_lab", "research/jobs/crash-cycle-lab/lab.py")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 자료
def load_french(smoke: bool) -> dict:
    us = crash_lab().load_us(smoke)
    mkt = us["L"].astype(float)
    mkt = mkt[mkt.index <= DATA_END]
    ind = us.get("ind49")
    if ind is not None:
        ind = ind.reindex(mkt.index).astype(float)
        ind = ind.where(ind > -0.99)
        if smoke:
            ind = ind.iloc[:, :6]
    return {"mlp": np.log(mkt), "ind": ind, "source": us.get("source")}


def market_points(fr: dict) -> dict:
    lab = L()
    f = lab.asset_frame(fr["mlp"])
    return lab.build_points({"MKT": f}, fr["mlp"].index[252::lab.STEP], with_market=False)


def industry_points(fr: dict) -> Optional[dict]:
    lab = L()
    if fr["ind"] is None or fr["ind"].shape[1] == 0:
        return None
    ms = lab.market_state(fr["mlp"])
    origins = fr["mlp"].index[252::lab.STEP]
    frames = {}
    for col in fr["ind"].columns:
        lp = np.log1p(fr["ind"][col]).cumsum()
        f = lab.asset_frame(lp, fr["mlp"])
        f[["mdd", "mvolr"]] = ms
        frames[str(col).strip()] = f.loc[f.index.intersection(origins)]
    return lab.build_points(frames, origins, with_market=True)


def _adj(df: pd.DataFrame) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    s = df["Adj Close"] if "Adj Close" in df.columns else df.get("Close")
    if s is None:
        return None
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    s = s.astype(float)
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.where(s > 0)


def stock_points(smoke: bool) -> tuple:
    """(점 표 또는 None, 자료 정보)."""
    lab = L()
    if smoke:
        m, assets = lab.synthetic_panel(n_assets=14, n_days=6400, seed=11)
        ms = lab.market_state(m)
        origins = m.index[252::lab.STEP]
        frames = {}
        for k, lp in assets.items():
            f = lab.asset_frame(lp, m)
            f[["mdd", "mvolr"]] = ms
            frames[k] = f.loc[f.index.intersection(origins)]
        return lab.build_points(frames, origins, with_market=True), {"source": "synthetic (smoke)", "tickers": len(frames)}
    from core import market_data as md
    from core import point_in_time_universe as pit

    spy = _adj(md._load_store(md._store_path("SPY", "1d")))
    if spy is None or spy.dropna().empty:
        return None, {"reason": "SPY 가격 파일 없음"}
    spy = spy.dropna()
    spy = spy[spy.index <= DATA_END]
    cal = spy.index[spy.index >= "1995-01-01"]
    if len(cal) < 2000:
        return None, {"reason": "SPY 이력이 짧음"}
    mlp = np.log(spy.reindex(cal))
    origins = cal[252::lab.STEP]
    origins = origins[origins >= STOCK_START]
    table = pit.load_historical_constituents_table()
    tdates = table["date"].to_numpy()
    pos = np.searchsorted(tdates, origins.to_numpy(), side="right") - 1
    members = [set(table["tickers_list"].iloc[max(p, 0)]) for p in pos]
    tickers = sorted(set().union(*members)) if members else []
    ms = lab.market_state(mlp)
    frames, missing, jumps = {}, 0, 0
    for i, t in enumerate(tickers):
        s = _adj(md._load_store(md._store_path(t, "1d")))
        if s is None or s.dropna().empty:
            missing += 1
            continue
        lp = np.log(s.reindex(cal).ffill(limit=STOCK_FFILL))
        jumps += int((lp.diff().abs() > 0.7).sum())
        memb = origins[[t in mset for mset in members]]
        if not len(memb):
            continue
        f = lab.asset_frame(lp, mlp)
        f[["mdd", "mvolr"]] = ms
        frames[t] = f.loc[f.index.intersection(memb)]
        if i % 300 == 0:
            log(f"종목 자료 {i}/{len(tickers)}")
    info = {"source": "Yahoo 수정 종가(VM 가격 저장소) + S&P500 그 시점 편입", "tickers_in_universe": len(tickers),
            "tickers_with_prices": len(frames), "tickers_missing": missing, "daily_jumps_over_70pct": jumps,
            "calendar": [str(cal[0].date()), str(cal[-1].date())]}
    if len(frames) < MIN_STOCK_TICKERS:
        info["reason"] = f"가격 파일이 {len(frames)}개뿐(최소 {MIN_STOCK_TICKERS})"
        return None, info
    return lab.build_points(frames, origins, with_market=True), info


# ---------------------------------------------------------------- 계산
def run_layer(name: str, P: Optional[dict]) -> Optional[dict]:
    lab = L()
    if P is None or len(P["date"]) == 0:
        return None
    t0 = time.time()
    out = lab.walk(P, progress=lambda i, n: log(f"{name} 걸어 나가기 {i}/{n}"))
    cells = lab.score_layer(P, out, ERAS[name], JUDGED_END, ALPHA)
    hold = holdout_cells(P, out)
    log(f"{name} 완료: 점 {len(P['date'])}개, {time.time() - t0:.0f}초")
    return {"P": P, "out": out, "cells": cells, "holdout": hold}


def holdout_cells(P: dict, out: dict) -> dict:
    """2024-10 이후 기준일 예측(보고만): 칸별 평균 손실과 기량."""
    lab = L()
    res = {}
    late = P["date"] > np.datetime64(JUDGED_END)
    for hi, h in enumerate(lab.HORIZONS):
        for k, kind in enumerate(lab.KINDS):
            Lm = out["LQ"][:, :, hi] if k == 0 else out["LB"][:, :, hi, k - 1]
            ok = late & np.isfinite(Lm).all(axis=1)
            if not ok.any():
                continue
            m = Lm[ok].mean(axis=0)
            res[f"{h}:{kind}"] = {"n_points": int(ok.sum()), "skill": lab._skill(m[0], m[-1]), "skill_vs_vol": lab._skill(m[1], m[-1])}
    return res


def verdicts_of(layers: dict) -> dict:
    v = {}
    for key, layer, cell in FAMILY:
        c = (layers.get(layer) or {}).get("cells", {}).get(cell)
        if c is None or not c.get("evaluable"):
            v[key] = {"label": "NOT_EVALUABLE", "layer": layer, "cell": cell, "grade": "없음"}
            continue
        eras_ok = all(e["skill"] is not None and e["skill"] > 0 for e in c["eras"].values())
        ok = c["p"] is not None and c["p"] < ALPHA and eras_ok
        v[key] = {"label": "BEATS_CLIM" if ok else "FAIL", "layer": layer, "cell": cell, "skill": c["skill"], "p": c["p"],
                  "eras": {n: e["skill"] for n, e in c["eras"].items()}, "grade": c["grade"],
                  "skill_vs_vol": c["skill_vs_vol"], "p_vs_vol": c["p_vs_vol"], "grade_vs_vol": c["grade_vs_vol"]}
    return v


def model_of(layers: dict, data_info: dict, smoke: bool) -> dict:
    lab = L()
    m = {"study": STUDY, "lab_version": lab.LAB_VERSION, "data_end": DATA_END, "smoke": smoke, "horizons": list(lab.HORIZONS),
         "taus": list(lab.TAUS), "events": list(lab.EVENTS), "experts": list(lab.EXPERTS), "kinds": list(lab.KINDS),
         "alpha_family": ALPHA, "layers": {}}
    for name, r in layers.items():
        if r is None:
            continue
        m["layers"][name] = {
            "feats": list(r["P"]["feats"]), "library": f"library_{name}.csv", "weights": np.round(r["out"]["weights"], 6).tolist(),
            "last_origin": str(r["P"]["date"][-1]),
            "cells": {k: {"grade": c["grade"], "grade_vs_vol": c["grade_vs_vol"], "skill": c["skill"], "p": c["p"],
                          "skill_vs_vol": c["skill_vs_vol"], "evaluable": c["evaluable"], "coverage80": c.get("coverage80")}
                      for k, c in r["cells"].items()}}
    m["data"] = data_info
    return m


def now_reading(layers: dict, fr: dict) -> Optional[dict]:
    """시장의 마지막 날 읽기(보고용). 모형 저장 파일과 같은 경로(export_library → forecast_live)로 계산한다."""
    lab = L()
    r = layers.get("market")
    if r is None:
        return None
    st = lab.latest_state(fr["mlp"])
    if st is None:
        return None
    lib = lab.library_from_frame(lab.export_library(r["P"]))
    f = lab.forecast_live(lib, r["out"]["weights"], st["x"], st["s"])
    rows = []
    for hi, h in enumerate(lab.HORIZONS):
        rows.append({"h": h, "q_ens": [float(math.expm1(v)) for v in f["q"]["ENS"][hi]], "q_clim": [float(math.expm1(v)) for v in f["q"]["CLIM"][hi]],
                     "p_ens": [None if not np.isfinite(v) else float(v) for v in f["p"]["ENS"][hi]],
                     "p_clim": [None if not np.isfinite(v) else float(v) for v in f["p"]["CLIM"][hi]], "n": f["n"][hi]})
    return {"date": str(st["date"].date()), "dd": float(math.expm1(st["x"][0])), "rows": rows}


def run(smoke: bool) -> tuple:
    lab = L()
    fr = load_french(smoke)
    log(f"French 자료 {fr['mlp'].index[0].date()} ~ {fr['mlp'].index[-1].date()}")
    layers: dict = {"market": run_layer("market", market_points(fr)), "industry": run_layer("industry", industry_points(fr))}
    sp, sinfo = stock_points(smoke)
    layers["stock"] = run_layer("stock", sp)
    data_info = {"french": {"source": fr["source"], "first": str(fr["mlp"].index[0].date()), "last": str(fr["mlp"].index[-1].date()),
                            "industries": 0 if fr["ind"] is None else int(fr["ind"].shape[1])}, "stock": sinfo}
    verdicts = verdicts_of(layers)
    summary = {k: (f"{v['label']} · 등급 {v['grade']}" + ("" if v["label"] == "NOT_EVALUABLE" else f" · 기량 {v['skill']:+.3f} · p {v['p']:.4f}"))
               for k, v in verdicts.items()}
    res = {"study": STUDY, "rules_version": RULES_VERSION, "lab_version": lab.LAB_VERSION, "smoke": smoke, "data_end": DATA_END,
           "judged_end": JUDGED_END, "family": {"keys": [k for k, _, _ in FAMILY], "alpha": ALPHA, "alpha_expr": "0.05/6"},
           "verdicts": verdicts, "summary": summary, "data": data_info, "limits": LIMITS,
           "layers": {n: None if r is None else {"n_points": int(len(r["P"]["date"])), "n_assets": len(r["P"]["names"]),
                                                 "first_origin": str(r["P"]["date"][0]), "last_origin": str(r["P"]["date"][-1]),
                                                 "weights": np.round(r["out"]["weights"], 4).tolist(),
                                                 "realized": r["out"]["realized"].astype(int).tolist(),
                                                 "cells": r["cells"], "holdout": r["holdout"]} for n, r in layers.items()},
           "now": now_reading(layers, fr)}
    return res, layers, model_of(layers, data_info, smoke)


# ---------------------------------------------------------------- 보고서
def _f(x: Any, fmt: str = "{:+.3f}") -> str:
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else fmt.format(x)


def _pct(x: Any) -> str:
    return _f(x, "{:+.1%}")


def report(res: dict) -> str:
    lab = L()
    out = [f"# {STUDY} — 판단 엔진 1판: 앙상블 분포 예측 대 과거 평균 분포", ""]
    if res["smoke"]:
        out += ["**스모크(가짜 자료) 실행 — 숫자에 뜻이 없다.**", ""]
    out += ["## 한눈에", "",
            "- 무엇을 했나: 시장·업종·종목마다 1·3·6·12개월 뒤 수익 분포와 사건 확률을 예측하고, 실현된 결과와 맞춰 봤다.",
            "- 비교 대상: 과거 평균 분포(CLIM). 엔진(ENS)은 전문가 4명(과거 평균·변동성 축척·닮은 과거 상태·상태 기울기)을 과거 성적으로 가중한다.",
            f"- 판정 6개(유의수준 0.05/6 = {ALPHA:.4f}). 등급은 판정과 별도로 모든 칸에 매긴다(강함·보통·약함·없음).", "",
            "## 판정", "", "| 열쇠 | 층 | 칸 | 판정 | 등급 | 기량(ENS 대 CLIM) | p | 시대별 기량 | ENS 대 VOL 기량 (p) |", "|---|---|---|---|---|---|---|---|---|"]
    for k, v in res["verdicts"].items():
        h, kind = v["cell"].split(":")
        eras = " · ".join(f"{n} {_f(s)}" for n, s in (v.get("eras") or {}).items()) or "—"
        out.append(f"| {k} | {LAYER_NAMES[v['layer']]} | {h}일 {KIND_NAMES[kind]} | {v['label']} | {v['grade']} | {_f(v.get('skill'))} | "
                   f"{_f(v.get('p'), '{:.4f}')} | {eras} | {_f(v.get('skill_vs_vol'))} ({_f(v.get('p_vs_vol'), '{:.3f}')}) |")
    out += ["", "기량 = 1 − 손실(ENS)/손실(CLIM). 양수면 엔진이 과거 평균보다 잘 맞혔다. 'ENS 대 VOL'은 변동성 위에 상태 정보가 더한 몫이다.", ""]
    for name in LAYERS:
        r = res["layers"].get(name)
        out += [f"## {LAYER_NAMES[name]} 층", ""]
        if r is None:
            out += [f"평가 불가 — {(res['data'].get('stock') or {}).get('reason', '자료 없음') if name == 'stock' else '자료 없음'}", ""]
            continue
        out += [f"점 {r['n_points']:,}개 · 자산 {r['n_assets']}개 · 기준일 {r['first_origin']} ~ {r['last_origin']}", "",
                "| 기간 | 종류 | 등급 | 기량 | p | 구획 | VOL | ANALOG | TILT | ENS 대 VOL (p, 등급) | 80% 구간 적중 | 2024-10~ 기량(보고) |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for key, c in r["cells"].items():
            h, kind = key.split(":")
            es = c.get("expert_skill") or {}
            ho = (r["holdout"] or {}).get(key) or {}
            out.append(f"| {h}일 | {KIND_NAMES[kind]} | {c['grade']} | {_f(c['skill'])} | {_f(c['p'], '{:.4f}')} | {c['n_blocks']} | {_f(es.get('VOL'))} | "
                       f"{_f(es.get('ANALOG'))} | {_f(es.get('TILT'))} | {_f(c['skill_vs_vol'])} ({_f(c['p_vs_vol'], '{:.3f}')}, {c['grade_vs_vol']}) | "
                       f"{_f(c.get('coverage80'), '{:.1%}')} | {_f(ho.get('skill'))} (n {ho.get('n_points', 0)}) |")
        out += ["", "마지막 가중(전문가 순서 " + " · ".join(lab.EXPERTS) + "):", "", "| 기간 | " + " | ".join(KIND_NAMES[k] for k in lab.KINDS) + " |",
                "|---|" + "---|" * len(lab.KINDS)]
        for hi, h in enumerate(lab.HORIZONS):
            out.append(f"| {h}일 | " + " | ".join(" / ".join(f"{w:.2f}" for w in r["weights"][hi][k]) for k in range(len(lab.KINDS))) + " |")
        out.append("")
    now = res.get("now")
    if now:
        out += ["## 시장의 지금 읽기 (설명용, 추천 아님)", "", f"기준일 {now['date']} · 1년 고점 대비 {_pct(now['dd'])}", "",
                "| 기간 | 엔진 10% | 25% | 중앙 | 75% | 90% | 과거 평균 중앙 | 오를 확률(엔진/평균) | 15% 이상 빠질 확률(엔진/평균) |", "|---|---|---|---|---|---|---|---|---|"]
        for row in now["rows"]:
            q, c, p, pc = row["q_ens"], row["q_clim"], row["p_ens"], row["p_clim"]
            out.append(f"| {row['h']}일 | " + " | ".join(_pct(v) for v in q) + f" | {_pct(c[2])} | {_f(p[0], '{:.0%}')} / {_f(pc[0], '{:.0%}')} | "
                       f"{_f(p[1], '{:.0%}')} / {_f(pc[1], '{:.0%}')} |")
        out.append("")
    out += ["## 한계", ""] + [f"- {x}" for x in res["limits"]] + ["", "## 자료", "", "```", json.dumps(res["data"], ensure_ascii=False, indent=1), "```", ""]
    return "\n".join(out)


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else round(float(o), 6)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


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
    res, model = _clean(res), _clean(model)
    lab = L()
    for name in LAYERS:
        r = layers.get(name)
        df = pd.DataFrame(columns=["dd"]) if r is None else lab.export_library(r["P"])
        df.to_csv(out / f"library_{name}.csv", index=False)
    (out / "model.json").write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
