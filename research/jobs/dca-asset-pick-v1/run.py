"""검증 연구 dca-asset-pick-v1 (2026-10-22 사전 등록): 팔지 않고 매달 적립할 때, 새 돈을 '어디에' 넣어야 시장보다 많이 남나.

사용자 요청(2026-10-22): 웬만해서는 팔지 않고 월 10만 원 정도를 늘 추가로 넣을 때 어떤 종목을 선택해야 하는가 — 길게 보고 싸게 사서 누리자.
dca-dip-deploy-v1 은 '언제' 넣을지(기다림의 대가가 있다)를 보고, 이 연구는 늘 바로 넣되 '어디에' 넣을지를 본다(기다림 없음, 팔지 않아 세금 이연).

메뉴(긴 역사, Ken French 1927~): 미국 12 산업(시가총액 가중) + 시장 + 대형 가치주(25 규모×BM 의 BIG HiBM).
팔(매달 들어온 돈 전부를, 전날 종가까지의 자료로 고른 곳에 그날 종가로 산다):
  MKT      시장(기준)
  EW12     12 산업에 똑같이 나눔
  UW12     지금 보유 중 동일 비중보다 가장 모자란 산업(팔지 않는 리밸런싱)
  DD12     252일 고점 대비 가장 많이 빠진 산업('가장 싸진 것')
  REV36    지난 3년 수익이 가장 낮은 산업(장기 반전)
  MOM12    지난 12-1개월 수익이 가장 높은 산업(추세)
  MA200    200일 평균 대비 가장 아래에 있는 산업
  BV       대형 가치주 묶음(싼 주식)
판정·구간은 dca-dip-deploy-v1 과 같다(선택·확인 두 반쪽 × 10·20년, 시나리오 M 월 10만 원, 청산 세후).
보고만: 실제 Select Sector SPDR 9개 + SPY(2000~, 원화·실제 환율), 시나리오 H(이미 1,000만 원을 시장에 보유 + 월 10만 원 고르기).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import signal as _signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "research/jobs/dca-dip-deploy-v1"))

import lab as L  # noqa: E402

JOB_ID = "dca-asset-pick-v1"
RULES_VERSION = "dca-asset-pick-v1/2026-10-22"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
MONTHLY_KRW = 100_000
SCENARIOS = {"M": (0, MONTHLY_KRW), "H": (10_000_000, MONTHLY_KRW)}   # H 의 목돈은 모든 팔에서 첫날 시장에 산다
PRIMARY = "M"
HORIZONS = (10, 20)
JUDGED_SETS = ("selection", "confirmation")
BASE = "MKT"
ARMS = ("EW12", "UW12", "DD12", "REV36", "MOM12", "MA200", "BV")
N_TRIALS = len(ARMS)
LABELS = {"MKT": "시장(기준)", "EW12": "12 산업 똑같이", "UW12": "가장 모자란 산업(팔지 않는 리밸런싱)",
          "DD12": "1년 고점 대비 가장 많이 빠진 산업", "REV36": "3년 수익 가장 낮은 산업", "MOM12": "12-1개월 수익 가장 높은 산업",
          "MA200": "200일선 대비 가장 아래 산업", "BV": "대형 가치주"}
DD_ROWS, REV_ROWS, MOM_ROWS, MOM_SKIP, MA_ROWS = 252, 756, 252, 21, 200

WIN_SHARE_MIN = 0.65
MEDIAN_IRR_MIN = 0.003
P10_IRR_MIN = -0.015
MDD_TOL = 0.05
PASS, FAIL = "BEATS_MARKET", "FAIL"

ETF_FIRST_START = "2000-01-01"
ETF_JUDGED_END = "2024-09-30"
ETF_MENU9 = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
DEADLINE_MARGIN = 120.0
SIZE_LIMIT = 190_000


class _Stop(Exception):
    pass


# =================================================================================================
# 고르기 (행 t 의 선택은 행 t−1 종가까지의 자료)
# =================================================================================================

def score_tables(ind_px: pd.DataFrame) -> dict[str, np.ndarray]:
    """각 행의 '점수가 가장 큰 열'을 고른다(결측 = 후보 아님). 한 행 늦춰 전날 자료만 쓴다."""
    dd = ind_px / ind_px.rolling(DD_ROWS, min_periods=DD_ROWS).max() - 1.0
    rev = ind_px / ind_px.shift(REV_ROWS) - 1.0
    mom = ind_px.shift(MOM_SKIP) / ind_px.shift(MOM_ROWS) - 1.0
    ma = ind_px / ind_px.rolling(MA_ROWS, min_periods=MA_ROWS).mean() - 1.0
    raw = {"DD12": -dd, "REV36": -rev, "MOM12": mom, "MA200": -ma}
    return {k: v.shift(1).to_numpy(dtype=float) for k, v in raw.items()}


def pick(score_row: np.ndarray) -> int:
    if not np.isfinite(score_row).any():
        return -1
    return int(np.nanargmax(score_row))


def choose_assets(arm: str, rows: np.ndarray, scores: dict, n_ind: int, ind_px: np.ndarray, lump: int,
                  ind_offset: int, bv_col: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(사는 행, 자산 열, 금액 배수) — EW 는 한 적립을 n_ind 조각으로 나눈다. 고를 수 없으면 시장(열 0). 목돈은 시장."""
    k = len(rows)
    if arm == BASE:
        return rows, np.zeros(k, dtype=int), np.ones(k)
    if arm == "BV":
        a = np.full(k, bv_col)
        a[:lump] = 0
        return rows, a, np.ones(k)
    if arm == "EW12":
        rr = np.repeat(rows, n_ind)
        aa = np.tile(np.arange(n_ind) + ind_offset, k)
        mm = np.full(k * n_ind, 1.0 / n_ind)
        if lump:
            rr = np.concatenate([rows[:lump], rr[lump * n_ind:]])
            aa = np.concatenate([np.zeros(lump, dtype=int), aa[lump * n_ind:]])
            mm = np.concatenate([np.ones(lump), mm[lump * n_ind:]])
        return rr, aa, mm
    if arm == "UW12":
        return rows, None, np.ones(k)   # 경로 의존 — simulate 에서 처리
    a = np.array([pick(scores[arm][r]) for r in rows])
    a = np.where(a < 0, 0, a + ind_offset)
    a[:lump] = 0
    return rows, a, np.ones(k)


def uw_assets(px: np.ndarray, rows: np.ndarray, amounts: np.ndarray, lump: int, ind_offset: int, n_ind: int) -> np.ndarray:
    """매번 산업 보유 가치가 가장 작은 산업에 넣는다(동일 비중 목표). 시장 목돈은 비교에서 뺀다."""
    units = np.zeros(n_ind)
    out = np.zeros(len(rows), dtype=int)
    for i, (r, amt) in enumerate(zip(rows, amounts)):
        if i < lump:
            continue
        p = px[r, ind_offset:ind_offset + n_ind]
        val = np.where(np.isfinite(p), units * p, np.inf)
        j = int(np.argmin(val))
        out[i] = j + ind_offset
        units[j] += amt / p[j]
    return out


def hhi(px_end: np.ndarray, units: np.ndarray) -> float:
    v = np.nan_to_num(units * px_end)
    s = v.sum()
    return float(np.sum((v / s) ** 2)) if s > 0 else float("nan")


def run_window(px: np.ndarray, cg: np.ndarray, days, scores, s, e, scen, n_ind, ind_offset, bv_col) -> dict:
    init, monthly = SCENARIOS[scen]
    rows = L.contribution_rows(days, s, e)
    end_row = days.searchsorted(e, side="right") - 1
    start_row = rows[0]
    amounts = np.full(len(rows), float(monthly))
    lump = 0
    if init > 0:
        rows = np.concatenate([[rows[0]], rows])
        amounts = np.concatenate([[float(init)], amounts])
        lump = 1
    out = {}
    for arm in (BASE,) + ARMS:
        r_, a_, m_ = choose_assets(arm, rows, scores, n_ind, px, lump, ind_offset, bv_col)
        if arm == "EW12":
            am = np.concatenate([amounts[:lump], np.repeat(amounts[lump:], n_ind)]) * m_
        else:
            am = amounts * m_
        if a_ is None:
            a_ = uw_assets(px, rows, amounts, lump, ind_offset, n_ind)
        sim = L.simulate_buy_only(px, cg, r_, am, r_.copy(), a_, end_row, start_row)
        irr = L.xirr_monthly(amounts, rows, end_row, sim["terminal"], days)
        u = np.zeros(px.shape[1])
        np.add.at(u, a_, am * (1 - L.FEE - L.FX_SPREAD) / L.FX / px[r_, a_])
        out[arm] = {"irr": irr, "terminal": sim["terminal"], "mdd": sim["mdd"], "hhi": hhi(px[end_row], u),
                    "top_share": float(np.nanmax(np.nan_to_num(u * px[end_row])) / max(np.nansum(np.nan_to_num(u * px[end_row])), 1e-12))}
    return out


def pair_rows(res: list, arm: str) -> list[dict]:
    return [{"start": str(s.date()), "end": str(e.date()), "strategy_irr": r[arm]["irr"], "base_irr": r[BASE]["irr"],
             "strategy_terminal": r[arm]["terminal"], "base_terminal": r[BASE]["terminal"],
             "strategy_mdd": r[arm]["mdd"], "base_mdd": r[BASE]["mdd"]} for (s, e), r in res]


def checks_for(s: dict) -> Optional[dict]:
    if not s.get("n_windows"):
        return None
    gap = (s["median_strategy_mdd"] - s["median_base_mdd"]) if "median_strategy_mdd" in s else None
    return {"win_share": s["share_win"] >= WIN_SHARE_MIN, "median_irr": s["median_diff_irr"] >= MEDIAN_IRR_MIN,
            "p10_irr": s["p10_diff_irr"] >= P10_IRR_MIN, "mdd": (gap >= -MDD_TOL) if gap is not None else None}


# =================================================================================================
# ETF 시대 (보고만): SPY + Select Sector SPDR 9 개, 원화·실제 환율
# =================================================================================================

def etf_part(smoke: bool) -> dict:
    ssb = L._load_mod("_dca_ssb", "research/jobs/spy-sector-blend-v1/run.py")
    inp = ssb.synthetic_etf() if smoke else ssb.load_etf_real()
    cols = ["SPY"] + [t for t in ETF_MENU9 if t in inp["adj"].columns]
    adj = inp["adj"][cols].dropna(subset=["SPY"]).ffill(limit=3)
    days = adj.index
    fx = inp["fx"].reindex(days).ffill().bfill().to_numpy()
    bil = inp["adj"]["BIL"].reindex(days).ffill()
    cg = np.cumprod(1 + bil.pct_change().fillna(0.0).to_numpy() * (1 - L.INTEREST_TAX))
    px = adj.to_numpy(dtype=float)
    n_ind = len(cols) - 1
    scores = score_tables(adj[cols[1:]])
    first = "2012-01-01" if smoke else ETF_FIRST_START
    judged_end = "2016-06-30" if smoke else ETF_JUDGED_END
    out = {}
    for hz in ((2,) if smoke else (10,)):
        wins = [w for w in L.re_.rolling_windows(days, hz, step="A" if smoke else "M", first_start=first) if w[1] <= pd.Timestamp(judged_end)]
        res = []
        for s, e in wins:
            rows = L.contribution_rows(days, s, e)
            end_row = days.searchsorted(e, side="right") - 1
            amounts = np.full(len(rows), float(MONTHLY_KRW))
            r_all = {}
            for arm in (BASE,) + tuple(a for a in ARMS if a != "BV"):
                r_, a_, m_ = choose_assets(arm, rows, scores, n_ind, px, 0, 1, -1)
                am = (np.repeat(amounts, n_ind) if arm == "EW12" else amounts) * m_
                if a_ is None:
                    a_ = uw_assets(px, rows, amounts, 0, 1, n_ind)
                ok = np.isfinite(px[r_, a_])
                a_ = np.where(ok, a_, 0)
                usd = am / (fx[r_] * (1 + L.FX_SPREAD))
                units = usd * (1 - L.FEE) / px[r_, a_]
                eq = float(np.sum(units * px[end_row, a_]) * fx[end_row] * (1 - L.FX_SPREAD))
                term = L.liquidation_value(eq, float(am.sum()))
                r_all[arm] = {"irr": L.xirr_monthly(amounts, rows, end_row, term, days), "terminal": term, "mdd": None}
            res.append(((s, e), r_all))
        out[f"{hz}y"] = {arm: L.summarize_pairs(pair_rows(res, arm)) for arm in ARMS if arm != "BV"}
    out["menu"] = cols
    return out


# =================================================================================================
# 실행
# =================================================================================================

def _atomic_pickle(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_ckpt(path: Path, fp):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
        return obj["payload"] if obj.get("fingerprint") == fp else None
    except Exception:  # noqa: BLE001
        return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    dl_epoch = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    t0 = time.time()

    def log(s):
        print(s, flush=True)

    def check_time():
        if dl_epoch is not None and time.time() > dl_epoch - DEADLINE_MARGIN:
            raise _Stop()

    def stage(name, fn):
        path = ck / f"{name}.pkl"
        got = _load_ckpt(path, fp)
        if got is None:
            check_time()
            got = fn()
            _atomic_pickle(path, {"fingerprint": fp, "payload": got})
            log(f"단계 저장: {name} ({time.time() - t0:.0f}초)")
        return got

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        data = stage("inputs", lambda: L.load_long_synthetic() if a.smoke else L.load_long_real())
        days = data["mkt"].dropna().index
        ind = data["ind12"].reindex(days)
        n_ind = ind.shape[1]
        ind_px = ind.apply(L.level)
        mkt_px = L.level(data["mkt"].reindex(days))
        bv_px = L.level(data["bv"].reindex(days))
        panel = pd.concat([mkt_px.rename("MKT"), ind_px, bv_px.rename("BV")], axis=1)
        px = panel.to_numpy(dtype=float)
        bv_col = px.shape[1] - 1
        cg = np.cumprod(1 + data["rf"].reindex(days).fillna(0.0).to_numpy() * (1 - L.INTEREST_TAX))
        scores = score_tables(ind_px)
        cells: dict[str, dict] = {}
        for hz in HORIZONS:
            sets = L.window_sets(days, hz, a.smoke)
            for scen in SCENARIOS:
                def compute(sets=sets, scen=scen):
                    res = {}
                    for sn, wins in sets.items():
                        rr = []
                        for s, e in wins:
                            rr.append(((s, e), run_window(px, cg, days, scores, s, e, scen, n_ind, 1, bv_col)))
                            check_time()
                        res[sn] = {arm: L.summarize_pairs(pair_rows(rr, arm)) for arm in ARMS}
                        for arm in (BASE,) + ARMS:
                            res[sn].setdefault(arm, {})
                            if rr:
                                res[sn][arm]["median_top_share"] = float(np.nanmedian([r[1][arm]["top_share"] for r in rr]))
                        res[sn]["_base"] = {"median_irr": float(np.nanmedian([r[1][BASE]["irr"] for r in rr])) if rr else None,
                                            "median_mdd": float(np.nanmedian([r[1][BASE]["mdd"] for r in rr])) if rr else None}
                    return res
                cells[f"{scen}|{hz}y"] = stage(f"cell_{scen}_{hz}y", compute)
        etf = stage("etf", lambda: etf_part(a.smoke))
        last_picks = {arm: list(panel.columns)[1 + pick(scores[arm][-1])] if pick(scores[arm][-1]) >= 0 else None
                      for arm in ("DD12", "REV36", "MOM12", "MA200")}
        result = build_result(cells, etf, last_picks, str(days[-1].date()), a.smoke, data.get("source"), list(ind.columns))
        if a.smoke:
            cov = {"all_cells": len(cells) == len(SCENARIOS) * len(HORIZONS),
                   "judged_sets_nonempty": all(cells[f"{PRIMARY}|{h}y"][s][ARMS[0]].get("n_windows", 0) > 0
                                               for h in HORIZONS for s in JUDGED_SETS),
                   "arms_differ": len({round(cells[f"{PRIMARY}|10y"]["selection"][k].get("median_diff_irr", 0), 8) for k in ARMS}) > 2,
                   "concentration": cells[f"{PRIMARY}|10y"]["selection"]["MOM12"]["median_top_share"]
                   > cells[f"{PRIMARY}|10y"]["selection"]["EW12"]["median_top_share"],
                   "etf_part": bool(etf.get("2y"))}
            result["smoke_coverage"] = cov
            bad = [k for k, v in cov.items() if not v]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
    except _Stop:
        log(f"시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서 ({time.time() - t0:.0f}초)")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    report = render(result)
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text.encode("utf-8")) > SIZE_LIMIT:
        result.pop("etf_sectors", None)
        result["note_size"] = "크기 상한 때문에 ETF 부분을 뺐다(REPORT.md 에는 있다)"
        text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    (out / "results.json").write_text(text, encoding="utf-8")
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    log(f"완료 ({time.time() - t0:.0f}초)")
    return 0


# =================================================================================================
# 결과·보고서
# =================================================================================================

def _r(x, nd=4):
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return round(x, nd) if math.isfinite(x) else None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    return x


def build_result(cells, etf, last_picks, last_day, smoke, source, ind_cols) -> dict:
    verdicts: dict[str, Any] = {}
    checks: dict[str, dict] = {}
    for arm in ARMS:
        ch = {f"{s}|{h}y": checks_for(cells[f"{PRIMARY}|{h}y"][s][arm]) for h in HORIZONS for s in JUDGED_SETS}
        checks[arm] = ch
        ok = all(c is not None and all(v is True for v in c.values()) for c in ch.values())
        verdicts[arm] = f"SMOKE_ONLY({PASS if ok else FAIL})" if smoke else (PASS if ok else FAIL)
    verdicts["passed"] = f"{sum(v == PASS for k, v in verdicts.items() if k in ARMS)}/{N_TRIALS}"
    verdicts["scenario"] = f"M: {MONTHLY_KRW:,} KRW/month, never sell, after liquidation tax, 1927-2007 halves, 10y+20y, vs market"
    return _r({"judge_version": RULES_VERSION, "smoke": smoke, "source": source,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "verdicts": verdicts, "checks": checks, "cells": cells, "etf_sectors": etf,
               "last_day": last_day, "last_picks": last_picks, "industries": ind_cols,
               "rule": {"monthly_krw": MONTHLY_KRW, "scenarios": {k: {"initial_krw": v[0], "monthly_krw": v[1]} for k, v in SCENARIOS.items()},
                        "horizons": list(HORIZONS), "thresholds": {"win_share_min": WIN_SHARE_MIN, "median_irr_min": MEDIAN_IRR_MIN,
                                                                   "p10_irr_min": P10_IRR_MIN, "mdd_tol": MDD_TOL},
                        "lookbacks": {"dd": DD_ROWS, "rev": REV_ROWS, "mom": [MOM_ROWS, MOM_SKIP], "ma": MA_ROWS},
                        "account": "buy-only, fee 0.1% + FX 0.05%, liquidation CGT 22% over 2.5M KRW, FX fixed 1300 (long history)",
                        "labels": LABELS}})


def _p(x, signed=False, nd=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _yn(v):
    return "—" if v is None else ("통과" if v else "미달")


def render(r: dict) -> str:
    v = r["verdicts"]
    smoke = r["smoke"]
    out = [f"# 팔지 않는 적립 — 새 돈을 어디에 넣을까 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
           f"매달 {MONTHLY_KRW // 10000}만 원을 늘 바로 넣고 절대 팔지 않을 때, 그 돈을 시장 전체 대신 '빠진 산업'·'추세 산업'·'싼 주식' 등에 넣으면 "
           "세후로 더 많이 남는지 1927~2024 미국 자료로 본다.", "",
           f"**판정(대 시장, 두 반쪽 × 10·20년 모두): 통과 {v['passed']}** — " + " · ".join(f"{LABELS[a]} **{v[a]}**" for a in ARMS), "",
           "통과는 엔진 반영이 아니다. 엔진은 바뀌지 않았다.", "",
           "## 규칙 (결과를 보기 전에 고정)", "",
           "- 매달 첫 거래일 10만 원, 전날 종가까지의 자료로 고른 곳을 그날 종가에 산다. 절대 팔지 않는다. 구간 끝에 모두 판다고 보고 양도세 22%(250만 원 공제).",
           "- 구간: 매달 시작하는 10년·20년. 선택 반쪽(끝 ≤ 1966)·확인 반쪽(1967~2007). 2008 이후 끝나는 구간은 보고만.",
           f"- 통과(BEATS_MARKET): 두 반쪽 × 두 길이 모두 ① 시장보다 많이 남은 구간 ≥ {WIN_SHARE_MIN:.0%} ② 세후 IRR 차이 중앙값 ≥ +{MEDIAN_IRR_MIN * 100:.1f}%p "
           f"③ 10분위 ≥ {P10_IRR_MIN * 100:.1f}%p ④ 계좌 최대낙폭 중앙값이 {MDD_TOL * 100:.0f}%p 넘게 나쁘지 않음.", ""]
    for h in HORIZONS:
        for sn in ("selection", "confirmation", "post2008"):
            cell = r["cells"][f"M|{h}y"][sn]
            out += [f"## {h}년 구간 — {sn}{' (보고만)' if sn == 'post2008' else ''}", "",
                    f"시장 세후 IRR 중앙값 {_p(cell['_base']['median_irr'], nd=2)}, 계좌 최대낙폭 중앙값 {_p(cell['_base']['median_mdd'])}", "",
                    "| 넣을 곳 | 구간 | 이긴 비율 | IRR 차이 중앙값 / 10분위 | 남은 돈 비율 중앙값 | 최대낙폭 중앙값 (시장) | 가장 큰 종목 비중 중앙값 | ①②③④ |",
                    "|---|---|---|---|---|---|---|---|"]
            for arm in ARMS:
                s = cell[arm]
                if not s.get("n_windows"):
                    continue
                ch = r["checks"][arm].get(f"{sn}|{h}y")
                chs = "".join(_yn(x)[0] for x in ch.values()) if ch else "—"
                out.append(f"| {LABELS[arm]} | {s['n_windows']} | {_p(s['share_win'], nd=0)} | {_p(s['median_diff_irr'], True, 2)}p / "
                           f"{_p(s['p10_diff_irr'], True, 2)}p | {s['median_terminal_ratio']:.3f} | {_p(s.get('median_strategy_mdd'))} "
                           f"({_p(s.get('median_base_mdd'))}) | {_p(s.get('median_top_share'), nd=0)} | {chs} |")
            out.append("")
    out += ["## 보고 — 이미 1,000만 원을 시장에 보유 + 월 10만 원 고르기(시나리오 H)", "",
            "| 넣을 곳 | 길이 | 반쪽 | 이긴 비율 | IRR 차이 중앙값 |", "|---|---|---|---|---|"]
    for h in HORIZONS:
        for sn in JUDGED_SETS:
            for arm in ARMS:
                s = r["cells"][f"H|{h}y"][sn][arm]
                if s.get("n_windows"):
                    out.append(f"| {LABELS[arm]} | {h}년 | {sn} | {_p(s['share_win'], nd=0)} | {_p(s['median_diff_irr'], True, 2)}p |")
    etf = r.get("etf_sectors") or {}
    for hk, tbl in etf.items():
        if hk == "menu" or not isinstance(tbl, dict):
            continue
        out += ["", f"## 보고 — 실제 섹터 ETF 9 개 대 SPY, 원화·실제 환율, 2000 년부터 매달 시작하는 {hk} 구간(끝 ≤ 2024-09)", "",
                "| 넣을 곳 | 구간 | 이긴 비율 | IRR 차이 중앙값 / 10분위 |", "|---|---|---|---|"]
        for arm, s in tbl.items():
            if s.get("n_windows"):
                out.append(f"| {LABELS[arm].replace('12 산업', '9 섹터').replace('산업', '섹터')} | {s['n_windows']} | {_p(s['share_win'], nd=0)} | "
                           f"{_p(s['median_diff_irr'], True, 2)}p / {_p(s['p10_diff_irr'], True, 2)}p |")
    out += ["", f"## 지금 고른다면 ({r['last_day']}, 자료 마지막 날 · 12 산업 기준)", "",
            ", ".join(f"{LABELS[k]} → {v_ or '—'}" for k, v_ in r["last_picks"].items()), "",
            "## 주의", "",
            "- 구간이 크게 겹친다. 두 반쪽에서 독립적인 20년은 반쪽마다 2개 남짓이다.",
            "- 한 곳에만 계속 넣는 규칙은 계좌가 한 산업에 몰릴 수 있다('가장 큰 종목 비중' 열). 같은 수익이면 몰린 쪽이 더 위험하다.",
            "- 12 산업·대형 가치주는 Ken French 학술 포트폴리오다. 실제 ETF 와 비용·구성이 다르다. 배당 원천징수는 넣지 않았다.",
            "- 대형 가치주 효과는 2007 년 이후 약해졌다고 알려져 있다 — 2008+ 보고 칸을 함께 볼 것.",
            "- 세금은 근사이며 신고용이 아니다. 투자 조언이 아니다."]
    if smoke:
        out += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
