"""판단판 — 시장·내 포트폴리오·보유·관심 종목의 '앞으로 1·3·6·12개월' 수익 분포와 사건 확률을 한 장으로 만든다.

매수·매도를 정해 주지 않는다. 사용자가 스스로 판단할 때 볼 숫자(분포, 오를 확률, 15% 이상 빠질 확률, 시장을 이길 확률)와
그 숫자가 과거에 얼마나 맞았는지(근거 등급)를 낸다. 예측은 검증 연구 desk-engine-v1 이 만든 모형
(data/research_results/desk-engine-v1/model.json + library_*.csv)을 research/jobs/desk-engine-lab/lab.py 로 읽어 계산한다.
주문·챔피언 전략·아침 메시지와 연결되어 있지 않다. 이 모듈은 받은 가격으로 계산만 한다(가격 받기·DB 읽기는 scripts/decision_desk.py).
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_ROOT / "data" / "research_results" / "desk-engine-v1"
OUT_DIR = PROJECT_ROOT / "data" / "decision_desk"
SNAPSHOT_NAME = "latest.json"
HISTORY_NAME = "history.jsonl"
MARKET_TICKER = "SPY"
MARKET_LIKE = frozenset({"SPY", "VOO", "IVV", "SPLG", "VTI", "ITOT"})
ETF_LIKE = frozenset({
    "QQQ", "QQQM", "DIA", "IWM", "IJH", "IJR", "MDY", "RSP", "VUG", "VTV", "SCHD", "VIG", "MTUM", "QUAL", "USMV", "SPLV",
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY", "SMH", "SOXX", "XBI", "IBB", "KRE", "XHB", "ITB",
    "VEA", "VWO", "EFA", "EEM", "VXUS", "ACWI", "EWJ", "EWY", "FXI", "INDA", "VNQ"})
PORTFOLIO_KEY = "내 포트폴리오"
MIN_PORTFOLIO_DAYS = 300
STALE_DAYS = 7
NOTE = "설명용 숫자입니다. 매수·매도 추천이 아니며 주문과 연결되어 있지 않습니다."
EVENT_LABELS = {"up": "오를 확률", "dd15": "15% 이상 빠질 확률", "beat": "시장(SPY)을 이길 확률"}
LAYER_LABELS = {"market": "시장 모형", "industry": "업종·분산 묶음 모형", "stock": "개별 종목 모형"}


def lab():
    """연구 공용 모듈을 불러온다(폴더 이름에 '-' 가 있어 import 문을 못 쓴다)."""
    name = "desk_engine_lab"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "research" / "jobs" / "desk-engine-lab" / "lab.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 모형
def load_model(model_dir: Path = MODEL_DIR) -> Optional[dict]:
    """모형(가중·등급)과 층별 서고. 파일이 없거나 깨졌으면 None."""
    try:
        model = json.loads((Path(model_dir) / "model.json").read_text(encoding="utf-8"))
        libs = {}
        for name, layer in model["layers"].items():
            df = pd.read_csv(Path(model_dir) / layer["library"])
            if len(df) >= lab().MIN_LIB:
                libs[name] = lab().library_from_frame(df)
    except (OSError, ValueError, KeyError):
        return None
    if not libs:
        return None
    model["libs"] = libs
    return model


def layer_for(ticker: str, model: dict) -> str:
    """어느 층의 모형으로 읽을지. 넓은 지수 ETF = 시장, 그 밖의 ETF·포트폴리오 = 업종(분산 묶음), 나머지 = 종목."""
    t = ticker.upper()
    want = "market" if t in MARKET_LIKE else "industry" if (t in ETF_LIKE or ticker == PORTFOLIO_KEY) else "stock"
    for cand in (want, "stock", "industry", "market"):
        if cand in model["libs"]:
            return cand
    return want


# ---------------------------------------------------------------- 한 자산
def describe(lp: pd.Series) -> dict:
    """지금 위치(사실만): 1년 고점 대비, 200일선 대비, 기간 수익, 연 변동성."""
    s = lp.dropna()
    last = float(s.iloc[-1])

    def back(n: int) -> Optional[float]:
        return None if len(s) <= n else float(math.expm1(last - float(s.iloc[-1 - n])))

    r = s.diff().dropna()
    return {"dd_252": float(math.expm1(last - float(s.iloc[-252:].max()))),
            "vs_200ma": None if len(s) < 200 else float(math.exp(last) / float(np.exp(s.iloc[-200:]).mean()) - 1),
            "ret": {str(n): back(n) for n in (21, 63, 126, 252)},
            "vol_ann": None if len(r) < 60 else float(r.iloc[-63:].std() * math.sqrt(252))}


def _num(v: Any) -> Optional[float]:
    v = float(v)
    return v if math.isfinite(v) else None


def sheet(model: dict, ticker: str, lp: pd.Series, mlp: Optional[pd.Series]) -> dict:
    """자산 하나의 판단표. lp·mlp = 로그 수정 종가(날짜 색인)."""
    m = lab()
    layer = layer_for(ticker, model)
    out: dict = {"ticker": ticker, "layer": layer, "foreign": ticker.upper().endswith((".KS", ".KQ", ".T", ".HK")), "flags": []}
    s = lp.dropna()
    if len(s) < 2:
        return out | {"error": "가격 이력 없음"}
    out["asof"] = str(pd.Timestamp(s.index[-1]).date())
    out["stats"] = describe(s)
    feats = model["layers"][layer]["feats"]
    st = m.latest_state(s, mlp if len(feats) > len(m.OWN) else None)
    if st is None:
        return out | {"error": "가격 이력이 1년 남짓보다 짧아 예측하지 않음"}
    f = m.forecast_live(model["libs"][layer], np.asarray(model["layers"][layer]["weights"], float), st["x"], st["s"])
    cells = model["layers"][layer]["cells"]
    rows = []
    for hi, h in enumerate(m.HORIZONS):
        if not np.isfinite(f["q"]["ENS"][hi]).all():
            continue
        row = {"h": h, "n": int(f["n"][hi]),
               "q": [float(math.expm1(v)) for v in f["q"]["ENS"][hi]], "q_base": [float(math.expm1(v)) for v in f["q"]["CLIM"][hi]],
               "p": {}, "p_base": {}, "grade": {"q": (cells.get(f"{h}:q") or {}).get("grade", "없음")}}
        for k, ev in enumerate(m.EVENTS):
            p = _num(f["p"]["ENS"][hi][k])
            if p is None or (ev == "beat" and (out["foreign"] or layer == "market")):
                continue
            row["p"][ev], row["p_base"][ev] = p, _num(f["p"]["CLIM"][hi][k])
            row["grade"][ev] = (cells.get(f"{h}:{ev}") or {}).get("grade", "없음")
        rows.append(row)
    out["horizons"] = rows
    out["flags"] = flags_of(out)
    return out


def flags_of(sh: dict) -> list:
    """눈에 띄는 사실(판단 아님)."""
    fl = []
    st = sh.get("stats") or {}
    if st.get("dd_252") is not None and st["dd_252"] <= -0.20:
        fl.append(f"1년 고점 대비 {st['dd_252']:+.0%}")
    if st.get("vs_200ma") is not None and st["vs_200ma"] < 0:
        fl.append("200일 평균 아래")
    r63 = next((r for r in sh.get("horizons", []) if r["h"] == 63), None)
    if r63 and r63["p"].get("dd15") is not None and r63["p_base"].get("dd15"):
        if r63["p"]["dd15"] >= 2 * r63["p_base"]["dd15"] and r63["p"]["dd15"] >= 0.10:
            fl.append("3개월 낙폭 위험이 과거 평균의 2배 이상")
    if sh.get("foreign"):
        fl.append("미국 대형주로 만든 모형을 적용(참고만)")
    return fl


# ---------------------------------------------------------------- 포트폴리오
def aggregate_holdings(holdings: list, closes: dict) -> list:
    """매입 기록을 티커별로 합친다: 수량, 평균 매입가, 평가액, 손익률, 비중."""
    by: dict = {}
    for h in holdings:
        t = str(h.get("ticker") or "").upper().strip()
        q = float(h.get("quantity") or 0)
        if not t or q <= 0:
            continue
        a = by.setdefault(t, {"ticker": t, "quantity": 0.0, "cost": 0.0})
        a["quantity"] += q
        a["cost"] += q * float(h.get("purchase_price") or 0)
    rows = []
    for t, a in by.items():
        price = closes.get(t)
        value = None if price is None else a["quantity"] * float(price)
        rows.append({"ticker": t, "quantity": a["quantity"], "avg_cost": a["cost"] / a["quantity"], "price": price, "value": value,
                     "pnl_pct": None if value is None or a["cost"] <= 0 else value / a["cost"] - 1})
    total = sum(r["value"] for r in rows if r["value"] is not None)
    for r in rows:
        r["weight"] = None if not total or r["value"] is None else r["value"] / total
    return sorted(rows, key=lambda r: -(r["value"] or 0))


def portfolio_series(positions: list, prices: dict) -> tuple:
    """지금 비중을 계속 유지했다고 놓은 포트폴리오의 로그 가격과 빠진 종목. 이력이 짧은 종목은 빼고 비중을 다시 맞춘다."""
    use, dropped = {}, []
    for p in positions:
        s = prices.get(p["ticker"])
        if p.get("weight") and s is not None and s.dropna().shape[0] >= MIN_PORTFOLIO_DAYS:
            use[p["ticker"]] = (float(p["weight"]), s.dropna())
        elif p.get("weight"):
            dropped.append(p["ticker"])
    if not use:
        return None, dropped
    rets = pd.concat({t: np.expm1(s.diff()) for t, (_, s) in use.items()}, axis=1).dropna()
    if len(rets) < MIN_PORTFOLIO_DAYS:
        return None, dropped
    w = np.array([use[t][0] for t in rets.columns])
    port = (rets.to_numpy() * (w / w.sum())).sum(axis=1)
    return pd.Series(np.log1p(port).cumsum(), index=rets.index), dropped


def build_snapshot(model: Optional[dict], prices: dict, closes: dict, holdings: list, watch: list, cash: float = 0.0,
                   crash_lines: Optional[list] = None, now: Optional[datetime] = None) -> dict:
    """판단판 한 장. prices = {티커: 로그 수정 종가}, closes = {티커: 마지막 종가}."""
    now = now or datetime.now(timezone.utc)
    snap: dict = {"generated_at": now.isoformat(timespec="seconds"), "note": NOTE, "crash": crash_lines or [], "market": None,
                  "portfolio": None, "positions": [], "watch": [], "model": None}
    if model is None:
        return snap | {"status": "no_model", "message": "예측 모형이 아직 없습니다(검증 연구 desk-engine-v1 결과 대기)."}
    mlp = prices.get(MARKET_TICKER)
    if mlp is None or mlp.dropna().empty:
        return snap | {"status": "no_market", "message": "시장(SPY) 가격을 읽지 못했습니다."}
    snap["model"] = {"study": model.get("study"), "data_end": model.get("data_end"), "lab_version": model.get("lab_version"),
                     "smoke": bool(model.get("smoke")),
                     "grades": {name: {k: c.get("grade") for k, c in layer["cells"].items()} for name, layer in model["layers"].items()}}
    snap["market"] = sheet(model, MARKET_TICKER, mlp, None)
    snap["asof"] = snap["market"].get("asof")
    positions = aggregate_holdings(holdings, closes)
    held = {p["ticker"] for p in positions}
    total = sum(p["value"] for p in positions if p["value"] is not None)
    for p in positions:
        s = prices.get(p["ticker"])
        sh = {"ticker": p["ticker"], "error": "가격을 읽지 못함", "flags": []} if s is None else sheet(model, p["ticker"], s, mlp)
        sh["position"] = p
        r63 = next((r for r in sh.get("horizons", []) if r["h"] == 63), None)
        if r63 and p["value"] is not None:
            sh["position"] = p | {"bad_case_63": p["value"] * r63["q"][0]}
        if p.get("weight") and p["weight"] >= 0.25:
            sh["flags"] = sh.get("flags", []) + [f"비중 {p['weight']:.0%}"]
        _stale(sh, snap["asof"])
        snap["positions"].append(sh)
    for t in watch:
        t = str(t).upper().strip()
        if not t or t in held or t == MARKET_TICKER:
            continue
        s = prices.get(t)
        sh = {"ticker": t, "error": "가격을 읽지 못함", "flags": []} if s is None else sheet(model, t, s, mlp)
        _stale(sh, snap["asof"])
        snap["watch"].append(sh)
    if positions and total:
        plp, dropped = portfolio_series(positions, prices)
        if plp is not None:
            ps = sheet(model, PORTFOLIO_KEY, plp, mlp)
            ps["value"], ps["cash"], ps["dropped"] = total, float(cash or 0), dropped
            r63 = next((r for r in ps.get("horizons", []) if r["h"] == 63), None)
            if r63:
                ps["bad_case_63"] = total * r63["q"][0]
            snap["portfolio"] = ps
        else:
            snap["portfolio"] = {"ticker": PORTFOLIO_KEY, "error": "보유 종목의 가격 이력이 짧아 포트폴리오 예측을 만들지 못함",
                                 "value": total, "cash": float(cash or 0), "dropped": dropped, "flags": []}
    return snap | {"status": "ok"}


def _stale(sh: dict, asof: Optional[str]) -> None:
    if asof and sh.get("asof") and (pd.Timestamp(asof) - pd.Timestamp(sh["asof"])).days > STALE_DAYS:
        sh["flags"] = sh.get("flags", []) + [f"가격이 {sh['asof']} 에서 멈춤"]


# ---------------------------------------------------------------- 저장
def history_rows(snap: dict) -> list:
    """나중에 실제 결과와 맞춰 볼 수 있게 남기는 예측 기록(자산·기준일마다 한 줄)."""
    rows = []
    for sh in [snap.get("market"), snap.get("portfolio")] + list(snap.get("positions", [])) + list(snap.get("watch", [])):
        if not sh or not sh.get("horizons"):
            continue
        rows.append({"asof": sh["asof"], "ticker": sh["ticker"], "layer": sh["layer"], "model": (snap.get("model") or {}).get("study"),
                     "horizons": [{"h": r["h"], "q": [round(v, 5) for v in r["q"]], "p": {k: round(v, 4) for k, v in r["p"].items()}}
                                  for r in sh["horizons"]]})
    return rows


def write_snapshot(snap: dict, out_dir: Path = OUT_DIR) -> int:
    """latest.json 을 바꿔 쓰고, 아직 없는 (기준일, 자산) 예측을 history.jsonl 에 덧붙인다. 덧붙인 줄 수를 돌려준다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / (SNAPSHOT_NAME + ".tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out_dir / SNAPSHOT_NAME)
    hist = out_dir / HISTORY_NAME
    seen = set()
    try:
        for line in hist.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                seen.add((r["asof"], r["ticker"]))
            except (ValueError, KeyError):
                continue
    except OSError:
        pass
    new = [r for r in history_rows(snap) if (r["asof"], r["ticker"]) not in seen]
    if new:
        with hist.open("a", encoding="utf-8") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    return len(new)


def read_history(out_dir: Path = OUT_DIR) -> list:
    rows = []
    try:
        lines = (Path(out_dir) / HISTORY_NAME).read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def score_history(rows: list, prices: dict) -> dict:
    """실전 기록 채점: 기간이 다 지난 예측을 실제 결과와 맞춘다(기간별 건수, 10~90% 범위 적중률, 사건 확률의 브라이어 점수와 실제 빈도).

    포트폴리오 전체 줄은 그때의 비중을 다시 만들 수 없어 채점하지 않는다. 겹치는 날짜의 예측은 독립이 아니라 건수만큼의 근거는 아니다."""
    m = lab()
    mlp = prices.get(MARKET_TICKER)
    acc: dict = {}
    pending = 0
    for row in rows:
        s = prices.get(row.get("ticker"))
        if s is None or row.get("ticker") == PORTFOLIO_KEY:
            continue
        s = s.dropna()
        pos = int(s.index.searchsorted(pd.Timestamp(row["asof"]), side="right")) - 1
        if pos < 0 or str(pd.Timestamp(s.index[pos]).date()) != row["asof"]:
            continue
        for r in row.get("horizons", []):
            h = int(r["h"])
            if pos + h >= len(s):
                pending += 1
                continue
            ret = float(s.iloc[pos + h] - s.iloc[pos])
            mn = float(s.iloc[pos + 1:pos + h + 1].min() - s.iloc[pos])
            truth = {"up": ret > 0, "dd15": mn <= m.DD_LOG}
            if mlp is not None and "beat" in r.get("p", {}):
                mm = mlp.dropna().reindex(s.index).ffill()
                if math.isfinite(mm.iloc[pos + h]) and math.isfinite(mm.iloc[pos]):
                    truth["beat"] = ret > float(mm.iloc[pos + h] - mm.iloc[pos])
            a = acc.setdefault(h, {"n": 0, "inside": 0, "events": {}})
            a["n"] += 1
            a["inside"] += int(r["q"][0] <= math.expm1(ret) <= r["q"][4])
            for ev, p in r.get("p", {}).items():
                if ev in truth:
                    e = a["events"].setdefault(ev, {"n": 0, "brier": 0.0, "hits": 0, "p_sum": 0.0})
                    e["n"] += 1
                    e["brier"] += (p - float(truth[ev])) ** 2
                    e["hits"] += int(truth[ev])
                    e["p_sum"] += p
    out = {"pending": pending, "horizons": []}
    for h in sorted(acc):
        a = acc[h]
        out["horizons"].append({"h": h, "n": a["n"], "coverage80": a["inside"] / a["n"],
                                "events": {ev: {"n": e["n"], "brier": e["brier"] / e["n"], "freq": e["hits"] / e["n"], "mean_p": e["p_sum"] / e["n"]}
                                           for ev, e in a["events"].items()}})
    return out


def read_snapshot(out_dir: Path = OUT_DIR) -> Optional[dict]:
    try:
        return json.loads((Path(out_dir) / SNAPSHOT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
