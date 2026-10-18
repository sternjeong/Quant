"""검증 연구 contrib-reval-longrun-v1 (사전 등록 2026-10-17): 목돈 + 월 적립으로 굴릴 때, 장기(1927~) 여러 시작일에서
근사 한국 세금 뒤에도 시장을 이기나.

사용자 목표(2026-10-17): 처음 목돈 + 매달 적립으로 엔진을 끝없이 굴리고, 장기적으로 세후 SPY(여기서는 시장)를 이긴다.
지금까지 장기 연구는 한 시작일·목돈 한 번으로 쟀다. 서로 독립인 수십 년을 여러 번 주는 자료는 장기 프렌치 자료뿐이라,
이 작업이 재평가의 주 근거다. 시작일(매달) × 10·20년 구간에서 전략과 시장을 같은 적립금으로 굴린다.

규칙 전문은 SPEC.md(한국어)와 아래 상수에 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 다시 등록한다. 엔진 반영은 사용자 확인 뒤 별도 작업.

세전 수익은 원래 연구의 함수를 그대로 써서 한 번 만든다:
  CORE   — core-longrun-v1 lab.target_weights + lab.strategy_returns (FF12 상위 4, 252행 모멘텀 > 0, 200행 필터 × 0.5)
  I2     — mom-volscale-v1 I2/none/none (FF12 252행 수익 상위 2, 100%, 매달)
  I2VT20 — mom-volscale-v1 I2/VT20/none
  BIG    — mom-proxy-v1 apply_drag(BIG HiPRIOR, 연 1%)
  LEG    — lev-base-v1 합성 2배(synthetic_2x_returns) + 완충 필터(buffered_state), 꺼지면 RF
적립 시뮬레이션은 core/rolling_eval.index_sim(적립 정책 underweight_first) — 단일 소매 전략은 소매 하나를 자산으로,
혼합(MB30·MB50·BH50·L15F)은 [시장, 소매] 두 자산을 고정 목표로 두고 매년 1월 첫 거래일에 재조정한다.
근사 세금은 core/rolling_eval.approx_tax_sim 과 같은 설정(1,300원 고정, 공제 250만 원, 22%, 이월 없음)을 산업 단위 보유표에 적용한다(SPEC.md).
"""

from __future__ import annotations

import argparse
import importlib.util
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

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import rolling_eval as re_  # noqa: E402
from core import tax_fx as tx  # noqa: E402


def _load_mod(name: str, rel: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lab = _load_mod("core_longrun_lab", "research/jobs/core-longrun-v1/lab.py")
MV = _load_mod("mom_volscale_v1_for_contrib", "research/jobs/mom-volscale-v1/run.py")
MP = _load_mod("mom_proxy_v1_for_contrib", "research/jobs/mom-proxy-v1/run.py")
LB = _load_mod("lev_base_v1_for_contrib", "research/jobs/lev-base-v1/run.py")

JOB_ID = "contrib-reval-longrun-v1"
RULES_VERSION = "contrib-reval-longrun-v1/2026-10-17"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
BENCH = "MKT"
STRATEGIES = ("CORE", "I2", "I2VT20", "MB30", "MB50", "BH50", "L15F")
ALL_NAMES = (BENCH,) + STRATEGIES
N_TRIALS = 7
LABELS = {"MKT": "시장 그냥 보유(기준)", "CORE": "현 코어 복제(상위 4 + 200일 필터)", "I2": "산업 상위 2(100%)",
          "I2VT20": "산업 상위 2 + 변동성 20% 맞춤", "MB30": "시장 70 + I2VT20 30", "MB50": "시장 50 + I2VT20 50",
          "BH50": "시장 50 + 대형 모멘텀 승자 50", "L15F": "시장 85 + 합성 2배 15(완충 필터)"}
# 소매 수준 구성(세전·적립): {자산: 목표 비중}, 혼합은 매년 1월 첫 거래일 재조정
COMPOSITION = {"MKT": {"MKT": 1.0}, "CORE": {"CORE": 1.0}, "I2": {"I2": 1.0}, "I2VT20": {"I2VT20": 1.0},
               "MB30": {"MKT": 0.70, "I2VT20": 0.30}, "MB50": {"MKT": 0.50, "I2VT20": 0.50},
               "BH50": {"MKT": 0.50, "BIG": 0.50}, "L15F": {"MKT": 0.85, "LEG": 0.15}}
BH_DRAG = 0.01
COST_BPS = 10.0
POLICY = "underweight_first"

HORIZONS = (10, 20)
SEL_FIRST_START, SEL_END_CUTOFF = "1927-07-01", "1966-12-31"
CONF_FIRST_START, CONF_END_CUTOFF = "1967-01-01", "2007-12-31"
POST_FIRST_END = "2008-01-01"
RECENT_START = "2000-01-01"           # 2008+ 끝 구간 중 2000 년 이후 시작(보고만)
JUDGED_SETS = ("selection", "confirmation")
WINDOW_SETS = ("selection", "confirmation", "post2008")

SCENARIOS = {"A": 0.0, "B": 0.015, "C": 0.05}         # 월 적립 / 처음 금액
TAX_INITIAL_KRW = {"A": 10_000_000, "B": 10_000_000, "C": 3_000_000}
PRIMARY = "B"
TAX_FX = re_.APPROX_FX                 # 1,300 원/달러 고정
TAX_START_MONTHS = (1, 4, 7, 10)       # 세금은 1·4·7·10월 시작 구간만(매달 시작의 1/3, 1927-07 기준 3개월마다). 세전은 매달 전부.

WIN_SHARE_MIN = 0.70
MEDIAN_IRR_MIN = 0.005
P10_IRR_MIN = -0.015
MDD_TOL = 0.05
POWER_YEARS = 41.0

PASS, FAIL, NOT_EVALUABLE = "CONTRIB_BEATS_MARKET", "FAIL", "NOT_EVALUABLE"
SMOKE_STEP_MONTHS = 72                 # 스모크만: 6년마다 시작(전체는 매달)
STOP_MARGIN_S = 120.0
SAVE_EVERY_S = 60.0


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 저장된다."""


# =================================================================================================
# 자료
# =================================================================================================

def load_real() -> dict[str, Any]:
    """Ken French 일별 FF3·12 산업·6 규모×과거수익(BIG HiPRIOR). mom-volscale-v1 prepare 로 평일 달력 정리."""
    from core import french_factors as ff

    ff3, i12, p6 = ff.load("ff3_daily"), ff.load("ind12_daily"), ff.load("mom6_daily")
    if ff3 is None or i12 is None or p6 is None or MV.BH_COLUMN not in p6:
        raise RuntimeError("Ken French 일별 FF3 / 12 산업 / 6 규모×과거수익 자료를 받지 못함")
    out = MV.prepare(ff3["RF"], ff3["Mkt-RF"] + ff3["RF"], i12, p6[MV.BH_COLUMN])
    out["source"] = "Ken French data library (daily, weekday calendar; FF3, 12 industries VW, 6 ME×Prior BIG HiPRIOR VW)"
    return out


def synthetic_data(seed: int = 7) -> dict[str, Any]:
    """스모크(네트워크 없음): mom-volscale-v1 의 가짜 자료(1926-07~2026-08, 1952 이전 토요일 행 포함)."""
    return MV.synthetic_data(seed=seed)


# =================================================================================================
# 소매 수익(원래 연구 함수 그대로) + 세금용 보유표
# =================================================================================================

def leg_returns(mkt: pd.Series, rf: pd.Series, bps: float = COST_BPS) -> tuple[pd.Series, pd.Series, pd.Series]:
    """lev-base-v1 의 2배 다리만: 행 i 수익 = 상태[i−1] 이면 합성 2배, 아니면 RF. 상태가 바뀐 날(그날 종가 매매)엔
    다리 크기 × 2(판 것 + 산 것) × bps 를 뗀다. 반환 (다리 수익, 합성 2배 수익, 상태)."""
    state = LB.buffered_state((1 + mkt).cumprod())
    x2 = LB.synthetic_2x_returns(mkt, rf)
    st = state.to_numpy(dtype=bool)
    xv, fv = x2.to_numpy(), rf.reindex(mkt.index).fillna(0.0).to_numpy()
    out = np.zeros(len(st))
    for i in range(1, len(st)):
        r = xv[i] if st[i - 1] else fv[i]
        if st[i] != st[i - 1]:
            r = (1 + r) * (1 - 2 * bps / 1e4) - 1
        out[i] = r
    return pd.Series(out, index=mkt.index), x2, state


def i2_parts(data: dict) -> dict[str, Any]:
    ind, rf, mkt = data["ind12"], data["rf"], data["mkt"]
    sched = MV.pick_schedule(ind, "I2")
    raw = MV.raw_sleeve(ind, rf, sched, 2)
    below = MV.market_below_sma(mkt, ind.index)
    out = {"sched": sched}
    for v in ("none", "VT20"):
        exp = MV.exposure_schedule(raw, below, sched, v, "none")
        out[v] = {"exp": exp, "returns": MV.simulate(ind, rf, sched, exp, 2)["returns"]}
    return out


def build_sleeves(data: dict) -> dict[str, Any]:
    """전 기간 일별 소매 수익(세전, 원래 연구의 비용 포함) + 세금용 산업 단위 보유표의 재료."""
    ind, rf, mkt = data["ind12"], data["rf"], data["mkt"]
    core_w = lab.target_weights(ind, mkt, lab.Rule())
    core = lab.strategy_returns(ind, rf, core_w)
    i2 = i2_parts(data)
    big = MP.apply_drag(data["bh"].fillna(0.0), BH_DRAG)
    leg, x2, state = leg_returns(mkt, rf)
    sleeve_r = pd.DataFrame({"MKT": mkt, "CORE": core, "I2": i2["none"]["returns"], "I2VT20": i2["VT20"]["returns"],
                             "BIG": big, "LEG": leg}).fillna(0.0)
    under = pd.concat([ind.fillna(0.0), pd.DataFrame({"MKT": mkt, "RF": rf, "BIG": big, "X2": x2}).fillna(0.0)], axis=1)
    return {"sleeve_r": sleeve_r, "under_r": under, "core_w": core_w, "i2": i2, "state": state}


def toggle_rows(W: np.ndarray, rows) -> np.ndarray:
    """정해진 행에서 다시 맞추게(목표가 같아도) 번갈아 전체를 1e-8 만큼 줄인다(현금 1e-8, spy-champion-v1 과 같은 방법)."""
    W = W.copy()
    flip = False
    rows = sorted(int(r) for r in rows)
    bounds = rows + [len(W)]
    for a, b in zip(bounds[:-1], bounds[1:]):
        flip = not flip
        if flip:
            W[a:b] *= (1 - 1e-8)
    return W


def jan_rows(index: pd.DatetimeIndex) -> np.ndarray:
    return np.flatnonzero(LB.january_first_flags(index))


def sleeve_weight_frames(index: pd.DatetimeIndex) -> dict[str, Any]:
    """소매 수준 목표: 단일 소매 = dict(첫날 사고 적립금으로만 맞춤), 혼합 = 1월 첫 거래일마다 다시 맞추는 표."""
    out: dict[str, Any] = {}
    jr = jan_rows(index)
    for name, comp in COMPOSITION.items():
        if len(comp) == 1:
            out[name] = dict(comp)
            continue
        cols = list(comp)
        W = np.tile(np.array([comp[c] for c in cols]), (len(index), 1))
        out[name] = pd.DataFrame(toggle_rows(W, jr), index=index, columns=cols)
    return out


def tax_frames(sl: dict, ind_cols: list) -> dict[str, pd.DataFrame]:
    """세금 근사용 산업 단위 목표 비중(같은 날짜, 열 = 12 산업 + MKT, RF, BIG, X2). 목표가 바뀌는(또는 표시된) 날만 그날 종가에
    전체를 목표로 맞추고 그 사이는 표류한다(tax_fx.simulate 규칙). SPEC.md '세금 근사' 참고:
      CORE  — lab.target_weights 행(매달 다시 맞춤), 나머지 RF
      I2 / I2VT20 — 매달 선택 2개에 노출/2 씩, 나머지 RF
      MB30 / MB50 — 매달 전체를 (1−w) 시장 + w × I2VT20 목표로(원래는 1월에만 혼합 재조정 — 세금은 조금 더 많이 잡힌다)
      BH50 — 시장 50 / BIG 50, 1월 첫 거래일 재조정(원래와 같다)
      L15F — 시장 85 + 15 × (켜짐 X2 / 꺼짐 RF), 1월 첫 거래일·필터 전환일에 전체를 맞춘다(원래는 전환일엔 다리만)"""
    index = sl["under_r"].index
    cols = list(sl["under_r"].columns)
    ci = {c: j for j, c in enumerate(cols)}
    n, m = len(index), len(cols)
    dec_rows = MV.decision_rows(index)
    jr = jan_rows(index)

    def blank_rf() -> np.ndarray:
        W = np.zeros((n, m))
        W[:, ci["RF"]] = 1.0
        return W

    out: dict[str, pd.DataFrame] = {}
    W = np.zeros((n, m))
    W[:, ci["MKT"]] = 1.0
    out["MKT"] = W
    cw = sl["core_w"].reindex(index=index, columns=ind_cols).fillna(0.0).to_numpy()
    W = np.zeros((n, m))
    W[:, [ci[c] for c in ind_cols]] = cw
    W[:, ci["RF"]] = 1.0 - cw.sum(axis=1)
    out["CORE"] = toggle_rows(W, dec_rows)
    i2rows = {}
    for key, name in (("none", "I2"), ("VT20", "I2VT20")):
        W = blank_rf()
        sched, exp = sl["i2"]["sched"], sl["i2"][key]["exp"]
        ds = sorted(sched)
        for d, e in zip(ds, ds[1:] + [n]):
            row = np.zeros(m)
            picks, x = sched[d], exp.get(d, 0.0)
            if picks is not None and x > 0:
                for j in picks:
                    row[ci[ind_cols[j]]] = x / 2
            row[ci["RF"]] = 1.0 - row.sum()
            W[d:e] = row
        i2rows[name] = W
        out[name] = toggle_rows(W, ds)
    for name, w in (("MB30", 0.30), ("MB50", 0.50)):
        W = w * i2rows["I2VT20"]
        W[:, ci["MKT"]] += 1.0 - w
        out[name] = toggle_rows(W, sorted(set(sl["i2"]["sched"]) | set(jr)))
    W = np.zeros((n, m))
    W[:, ci["MKT"]], W[:, ci["BIG"]] = 0.5, 0.5
    out["BH50"] = toggle_rows(W, jr)
    st = sl["state"].reindex(index).fillna(False).to_numpy(dtype=bool)
    W = np.zeros((n, m))
    W[:, ci["MKT"]] = 0.85
    W[:, ci["X2"]] = 0.15 * st
    W[:, ci["RF"]] = 0.15 * (~st)
    out["L15F"] = toggle_rows(W, jr)
    return {k: pd.DataFrame(v, index=index, columns=cols) for k, v in out.items()}


def prepare(data: dict) -> dict[str, Any]:
    sl = build_sleeves(data)
    idx = sl["sleeve_r"].index
    sl["sleeve_w"] = sleeve_weight_frames(idx)
    sl["tax_w"] = tax_frames(sl, list(data["ind12"].columns))
    return sl


# =================================================================================================
# 구간
# =================================================================================================

def window_sets(days: pd.DatetimeIndex, step_months: int = 1) -> dict[str, dict[int, list]]:
    """{집합: {연수: [(시작, 끝)]}}. 매달 첫 거래일 시작(1927-07~). selection = 끝 ≤ 1966-12-31, confirmation = 시작 ≥ 1967-01
    이고 끝 ≤ 2007-12-31, post2008 = 끝 ≥ 2008-01-01(보고만). 1967 을 걸치는 구간(시작 ≤ 1966, 끝 ≥ 1967)은 어디에도 넣지 않는다."""
    out: dict[str, dict[int, list]] = {s: {} for s in WINDOW_SETS}
    for h in HORIZONS:
        allw = re_.rolling_windows(days, h, step=step_months, first_start=SEL_FIRST_START)
        out["selection"][h] = [(s, e) for s, e in allw if e <= pd.Timestamp(SEL_END_CUTOFF)]
        out["confirmation"][h] = [(s, e) for s, e in allw
                                  if s >= pd.Timestamp(CONF_FIRST_START) and e <= pd.Timestamp(CONF_END_CUTOFF)]
        out["post2008"][h] = [(s, e) for s, e in allw if e >= pd.Timestamp(POST_FIRST_END)]
    return out


def tax_sampled(start: pd.Timestamp) -> bool:
    return pd.Timestamp(start).month in TAX_START_MONTHS


# =================================================================================================
# 구간 계산
# =================================================================================================

def flows_for(days: pd.DatetimeIndex, ratio: float, terminal: float) -> list:
    cday = tx.contribution_days(days)
    cf = [(days[0], -1.0)] + ([(d, -float(ratio)) for d in days[cday]] if ratio > 0 else [])
    return cf + [(days[-1], float(terminal))]


def pre_window(sl: dict, name: str, s, e, ratio: float) -> dict[str, float]:
    """세전 + 적립(index_sim, 처음 금액 1, 적립 = ratio, 편도 10bp — 첫 매수·적립 매수·혼합 재조정)."""
    w = sl["sleeve_w"][name]
    cols = list(COMPOSITION[name])
    r = sl["sleeve_r"].loc[s:e, cols]
    ww = w.loc[s:e] if isinstance(w, pd.DataFrame) else w
    o = re_.index_sim(r, ww, ratio, policy=POLICY, initial=1.0, cost_bps=COST_BPS)
    return {"terminal": o["terminal"], "irr": o["irr"], "mdd_tw": o["mdd_tw"], "mdd_mw": o["mdd_mw"],
            "contributed": o["total_contributed"]}


def tax_arm(r: pd.DataFrame, w: pd.DataFrame, ratio: float, initial_krw: float) -> dict[str, float]:
    """rolling_eval.approx_tax_sim 의 'tax' 쪽과 똑같은 설정·계산(세금 없는 쪽은 index_sim 으로 따로 — 시간 절반)."""
    lev = (1 + r.fillna(0.0).astype(float)).cumprod()
    fx = pd.Series(float(TAX_FX), index=lev.index)
    ww = w.reindex(index=lev.index, columns=lev.columns).fillna(0.0)
    cfg = tx.AccountConfig(initial_krw=float(initial_krw), fee_rate=COST_BPS / 10000.0, fx_spread=0.0,
                           apply_tax=True, apply_dividend_tax=False,
                           monthly_contribution_krw=float(ratio) * float(initial_krw), contribution_policy=POLICY)
    sim = tx.simulate(ww, lev, lev, fx, cfg)
    return {"terminal_after_liquidation_krw": sim["terminal_after_liquidation_krw"],
            "irr_after_liquidation": sim["irr_after_liquidation"],
            "capital_gains_tax_krw": sim["totals"]["capital_gains_tax_krw"],
            "unpaid_tax_if_sold_now_krw": sim["unpaid_tax_if_sold_now_krw"]}


def tax_window(sl: dict, name: str, s, e, ratio: float, initial_krw: float, pre: dict) -> dict[str, float]:
    """근사 세금: 산업 단위 보유표로 세금 있는 계좌(tax_fx) / 없는 계좌(index_sim, 같은 10bp) 최종 금액 비율 = 세금 계수.
    세후 최종 = 세전(소매 수준, 원래 연구 수익) × 세금 계수. 세후 IRR = 같은 적립 흐름에 세후 최종으로 XIRR."""
    w = sl["tax_w"][name].loc[s:e]
    w = w.loc[:, w.abs().sum() > 0]
    r = sl["under_r"].loc[s:e, list(w.columns)]
    t = tax_arm(r, w, ratio, initial_krw)
    nt = re_.index_sim(r, w, ratio, policy=POLICY, initial=1.0, cost_bps=COST_BPS)
    t_ratio = t["terminal_after_liquidation_krw"] / float(initial_krw)
    factor = t_ratio / nt["terminal"] if nt["terminal"] > 0 else float("nan")
    term = pre["terminal"] * factor
    return {"terminal": term, "irr": tx.xirr(flows_for(r.index, ratio, term)), "factor": factor,
            "frame_pre_irr": nt["irr"], "frame_tax_irr": t["irr_after_liquidation"],
            "tax_paid_ratio": (t["capital_gains_tax_krw"] + t["unpaid_tax_if_sold_now_krw"]) / float(initial_krw)}


def _key(h: int, s, e) -> str:
    return f"{h}|{pd.Timestamp(s).date()}|{pd.Timestamp(e).date()}"


# =================================================================================================
# 체크포인트
# =================================================================================================

def _atomic_pickle(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_ckpt(path: Path, fp: dict):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
        return obj["payload"] if obj.get("fingerprint") == fp else None
    except Exception:  # noqa: BLE001 — 깨진 체크포인트는 다시 계산
        return None


def run_unit(sl: dict, name: str, scen: str, wset: dict[int, list], path: Path, fp: dict,
             check, timing: dict) -> dict:
    """한 단위(전략 × 시나리오 × 구간 집합): 구간마다 세전(전부) + 근사 세금(1·4·7·10월 시작만). 중간 저장(원자적)."""
    got = _load_ckpt(path, fp) or {"rows": {}, "complete": False}
    if got.get("complete"):
        return got
    rows = got["rows"]
    ratio, init = SCENARIOS[scen], TAX_INITIAL_KRW[scen]
    last_save = time.monotonic()
    try:
        for h, wins in wset.items():
            for s, e in wins:
                k = _key(h, s, e)
                if k in rows:
                    continue
                check()
                t0 = time.perf_counter()
                pre = pre_window(sl, name, s, e, ratio)
                timing["pre_n"] += 1
                timing["pre_s"] += time.perf_counter() - t0
                row = {"h": h, "start": str(pd.Timestamp(s).date()), "end": str(pd.Timestamp(e).date()), "pre": pre, "tax": None}
                if tax_sampled(s):
                    t0 = time.perf_counter()
                    row["tax"] = tax_window(sl, name, s, e, ratio, init, pre)
                    timing["tax_n"] += 1
                    timing["tax_s"] += time.perf_counter() - t0
                    timing["tax_years"] += (pd.Timestamp(e) - pd.Timestamp(s)).days / 365.25
                rows[k] = row
                if time.monotonic() - last_save > SAVE_EVERY_S:
                    _atomic_pickle(path, {"fingerprint": fp, "payload": {"rows": rows, "complete": False}})
                    last_save = time.monotonic()
    except _Stop:
        _atomic_pickle(path, {"fingerprint": fp, "payload": {"rows": rows, "complete": False}})
        raise
    out = {"rows": rows, "complete": True}
    _atomic_pickle(path, {"fingerprint": fp, "payload": out})
    return out


# =================================================================================================
# 통계·판정 (사전 등록)
# =================================================================================================

def pair_rows(strat: dict, bench: dict, h: int, after_tax: bool, start_from: Optional[str] = None) -> list[dict]:
    """rolling_eval.summarize 형식의 행. after_tax 면 세금 표본(1·4·7·10월 시작)만 — 세후 IRR·최종, 낙폭은 세전 시간가중."""
    out = []
    for k, sr in strat["rows"].items():
        if sr["h"] != h or k not in bench["rows"]:
            continue
        if start_from and pd.Timestamp(sr["start"]) < pd.Timestamp(start_from):
            continue
        br = bench["rows"][k]
        if after_tax:
            if sr["tax"] is None or br["tax"] is None:
                continue
            s_v, b_v = sr["tax"], br["tax"]
        else:
            s_v, b_v = sr["pre"], br["pre"]
        out.append({"start": sr["start"], "end": sr["end"],
                    "years": (pd.Timestamp(sr["end"]) - pd.Timestamp(sr["start"])).days / 365.25,
                    "strategy": {"irr": s_v["irr"], "mdd_tw": sr["pre"]["mdd_tw"]},
                    "benchmark": {"irr": b_v["irr"], "mdd_tw": br["pre"]["mdd_tw"]},
                    "diff_irr": s_v["irr"] - b_v["irr"],
                    "terminal_ratio": s_v["terminal"] / b_v["terminal"] if b_v["terminal"] > 0 else float("nan"),
                    "win": bool(s_v["terminal"] > b_v["terminal"]),
                    "drag_s": (sr["pre"]["irr"] - sr["tax"]["irr"]) if after_tax else None,
                    "drag_b": (br["pre"]["irr"] - br["tax"]["irr"]) if after_tax else None,
                    "frame_gap": (sr["tax"]["frame_pre_irr"] - sr["pre"]["irr"]) if after_tax else None})
    out.sort(key=lambda r: r["start"])
    return out


def compact(rows: list[dict], h: int) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    s = re_.summarize(rows, horizon_years=h)
    out = {"n": s["n_windows"], "share_win": s["share_terminal_win"], "median_diff_irr": s["median_diff_irr"],
           "mean_diff_irr": s["mean_diff_irr"], "p10_diff_irr": s["p10_diff_irr"], "p90_diff_irr": s["p90_diff_irr"],
           "median_terminal_ratio": s["median_terminal_ratio"], "min_terminal_ratio": s["min_terminal_ratio"],
           "median_irr": s["median_strategy_irr"], "median_bench_irr": s["median_benchmark_irr"],
           "median_mdd_tw": s["median_strategy_mdd_tw"], "median_bench_mdd_tw": s["median_benchmark_mdd_tw"],
           "worst": {"start": s["worst_window"]["start"], "diff_irr": s["worst_window"]["diff_irr"]},
           "eff_windows": s["effective_independent_windows"]}
    if rows[0].get("drag_s") is not None:
        out["median_tax_drag"] = float(np.nanmedian([r["drag_s"] for r in rows]))
        out["median_bench_tax_drag"] = float(np.nanmedian([r["drag_b"] for r in rows]))
        out["median_frame_gap"] = float(np.nanmedian([r["frame_gap"] for r in rows]))
    return out


def _fin(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def cell_checks(st: dict) -> dict[str, Optional[bool]]:
    """한 칸(집합 × 연수, 세후): 네 조건."""
    if not st or st.get("n", 0) == 0:
        return {"win_share": None, "median_irr": None, "p10_irr": None, "mdd": None}
    return {"win_share": st["share_win"] >= WIN_SHARE_MIN if _fin(st["share_win"]) else None,
            "median_irr": st["median_diff_irr"] >= MEDIAN_IRR_MIN if _fin(st["median_diff_irr"]) else None,
            "p10_irr": st["p10_diff_irr"] >= P10_IRR_MIN if _fin(st["p10_diff_irr"]) else None,
            "mdd": (st["median_mdd_tw"] >= st["median_bench_mdd_tw"] - MDD_TOL)
            if _fin(st["median_mdd_tw"]) and _fin(st["median_bench_mdd_tw"]) else None}


def rule_outcome(after: dict[str, dict[int, dict]]) -> dict[str, Any]:
    """사전 등록 규칙: selection·confirmation 두 집합 × 10·20년 네 칸 모두에서 네 조건 모두. 하나라도 평가 불가면 None."""
    checks = {f"{ws}_{h}y": cell_checks(after.get(ws, {}).get(h)) for ws in JUDGED_SETS for h in HORIZONS}
    flat = [v for c in checks.values() for v in c.values()]
    passed = None if any(v is None for v in flat) else all(flat)
    return {"passed": passed, "checks": checks}


def verdict_for(outcome: dict, noop: Optional[str], observed_ir: Optional[float], power: dict) -> str:
    if noop or outcome["passed"] is None:
        return NOT_EVALUABLE
    if outcome["passed"]:
        return PASS
    return rp.classify_fail(observed_ir, power)


def continuous_returns(sl: dict, name: str, a: str, b: Optional[str]) -> pd.Series:
    """한 구간을 새 계좌로 굴린 일별 세전 수익(적립 없음, index_sim — 혼합은 1월 재조정)."""
    w = sl["sleeve_w"][name]
    cols = list(COMPOSITION[name])
    r = sl["sleeve_r"].loc[pd.Timestamp(a): (pd.Timestamp(b) if b else None), cols]
    ww = w.loc[r.index[0]: r.index[-1]] if isinstance(w, pd.DataFrame) else w
    v = re_.index_sim(r, ww, 0.0, policy=POLICY, initial=1.0, cost_bps=COST_BPS)["values"]
    return v.pct_change().fillna(0.0)


def observed_ir(sl: dict, name: str) -> tuple[Optional[float], Optional[str]]:
    """사전 등록: 확인 구간(1967-01-01~2007-12-31) 하나의 연속 세전 계좌로 낸 일별 활성 수익(전략 − 시장)의 연 IR, noop 가드."""
    s = continuous_returns(sl, name, CONF_FIRST_START, CONF_END_CUTOFF)
    m = continuous_returns(sl, BENCH, CONF_FIRST_START, CONF_END_CUTOFF)
    act = (s - m.reindex(s.index)).iloc[1:].to_numpy()
    noop = rp.noop_guard(act.tolist())
    sd = float(np.std(act, ddof=1)) if len(act) > 2 else 0.0
    ir = float(np.mean(act) / sd * math.sqrt(252)) if sd > 0 else None
    return ir, noop


def aggregate(units: dict, sl: dict, power: dict) -> dict[str, Any]:
    """통계표(전략 × 시나리오 × 집합 × 연수, 세전 전부 / 세후 표본) + 규칙 결과 + 판정."""
    stats: dict[str, Any] = {}
    rules: dict[str, dict] = {}
    for name in ALL_NAMES:
        stats[name] = {}
        for scen in SCENARIOS:
            st: dict[str, Any] = {"pre": {}, "after": {}}
            for ws in WINDOW_SETS + ("post2008_start2000",):
                src = "post2008" if ws == "post2008_start2000" else ws
                frm = RECENT_START if ws == "post2008_start2000" else None
                u, b = units[(name, scen, src)], units[(BENCH, scen, src)]
                st["pre"][ws] = {str(h): compact(pair_rows(u, b, h, False, frm), h) for h in HORIZONS}
                st["after"][ws] = {str(h): compact(pair_rows(u, b, h, True, frm), h) for h in HORIZONS}
            stats[name][scen] = st
            if name != BENCH:
                after = {ws: {h: st["after"][ws][str(h)] for h in HORIZONS} for ws in JUDGED_SETS}
                rules.setdefault(name, {})[scen] = rule_outcome(after)
    irs = {n: observed_ir(sl, n) for n in STRATEGIES}
    verdicts = {n: verdict_for(rules[n][PRIMARY], irs[n][1], irs[n][0], power) for n in STRATEGIES}
    changed = {}
    for n in STRATEGIES:
        a, b_, c = (rules[n][s]["passed"] for s in ("A", "B", "C"))
        changed[n] = {"A_no_contrib": a, "B_primary": b_, "C_small_initial": c,
                      "contributions_changed_conclusion": (None if a is None or b_ is None else a != b_)}
    return {"stats": stats, "rules": rules, "verdicts": verdicts, "changed": changed,
            "observed_ir": {n: irs[n][0] for n in STRATEGIES}, "noop": {n: irs[n][1] for n in STRATEGIES}}


# =================================================================================================
# 결과·보고
# =================================================================================================

def _r(x, nd=4):
    if isinstance(x, float):
        return round(x, nd) if math.isfinite(x) else None
    if isinstance(x, dict):
        return {str(k): _r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    if isinstance(x, (np.floating,)):
        return _r(float(x), nd)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def build_result(agg: dict, ws_counts: dict, power: dict, timing: dict, smoke: bool, source: str) -> dict:
    verdicts = dict(agg["verdicts"])
    n_pass = sum(v == PASS for v in verdicts.values())
    verdicts["overall"] = f"{n_pass}/{len(STRATEGIES)} {PASS}"
    if smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    return _r({
        "judge_version": RULES_VERSION, "smoke": smoke, "source": source,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdicts": verdicts, "power": power,
        "rule": {"benchmark": "MKT = French Mkt-RF + RF, buy and hold",
                 "strategies": {n: LABELS[n] for n in STRATEGIES}, "composition": COMPOSITION, "n_trials": N_TRIALS,
                 "contributions": {"policy": POLICY, "ratio_per_month": SCENARIOS, "tax_initial_krw": TAX_INITIAL_KRW,
                                   "primary": PRIMARY, "engine": "core.rolling_eval.index_sim (initial 1, cost 10bp one-way)"},
                 "tax": {"label": re_.APPROX_LABEL, "applied_to": "industry-level holdings frames (SPEC.md)",
                         "after_tax_terminal": "pre-tax sleeve-level terminal × (tax_fx tax terminal / index_sim no-tax terminal) of the frame",
                         "subsample": f"tax only on windows starting in months {TAX_START_MONTHS} (every 3rd monthly start); pre-tax on all"},
                 "windows": {"horizons": HORIZONS, "selection": f"start >= {SEL_FIRST_START}, end <= {SEL_END_CUTOFF}",
                             "confirmation": f"start >= {CONF_FIRST_START}, end <= {CONF_END_CUTOFF}",
                             "post2008": f"end >= {POST_FIRST_END} (report only)",
                             "post2008_start2000": f"post2008 with start >= {RECENT_START} (report only)",
                             "excluded": "windows starting before 1967 and ending after 1966 (bridge)", "counts": ws_counts},
                 "pass_if": {"all_cells": [f"{ws}_{h}y" for ws in JUDGED_SETS for h in HORIZONS],
                             "share_terminal_win_min": WIN_SHARE_MIN, "median_irr_diff_min": MEDIAN_IRR_MIN,
                             "p10_irr_diff_min": P10_IRR_MIN, "median_mdd_tw_tolerance": MDD_TOL,
                             "scenario": PRIMARY, "after": "approximate Korean tax"},
                 "observed_ir": "annualized IR of daily (strategy − market) pre-tax, one continuous account 1967-01..2007-12"},
        "rules_by_scenario": agg["rules"], "contributions_changed": agg["changed"],
        "observed_ir": agg["observed_ir"], "noop": agg["noop"],
        "stats": agg["stats"], "timing": timing,
    })


def _p(x, nd=1, signed=False) -> str:
    if x is None or not _fin(x):
        return "-"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _pp(x, nd=2) -> str:
    return "-" if x is None or not _fin(x) else f"{x * 100:+.{nd}f}%p"


def _yn(v) -> str:
    return "-" if v is None else ("예" if v else "아니오")


def _cell_table(r: dict, scen: str, kind: str, sets, title: str) -> list[str]:
    L = [f"### {title}", "", "| 전략 | 구간 | 칸 | 구간 수 | 시장보다 많이 남은 비율 | IRR 차이 중앙값 | IRR 차이 하위 10% | 전략 시간가중 MDD 중앙값 | 시장 MDD 중앙값 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for n in STRATEGIES:
        for ws in sets:
            for h in HORIZONS:
                s = r["stats"][n][scen][kind][ws][str(h)]
                if not s or not s.get("n"):
                    L.append(f"| {n} | {ws} | {h}년 | 0 | - | - | - | - | - |")
                    continue
                L.append(f"| {n} | {ws} | {h}년 | {s['n']} | {_p(s['share_win'], 0)} | {_pp(s['median_diff_irr'])} | "
                         f"{_pp(s['p10_diff_irr'])} | {_p(s['median_mdd_tw'], 0)} | {_p(s['median_bench_mdd_tw'], 0)} |")
    return L + [""]


def render(r: dict) -> str:
    v = r["verdicts"]
    L = [f"# 목돈 + 월 적립 장기 재평가 (contrib-reval-longrun-v1)", "",
         f"판정 버전 `{r['judge_version']}` · 자료: {r['source']} · 생성 {r['generated_at']}" + (" · **스모크(가짜 자료)**" if r["smoke"] else ""), "",
         "## 한 줄 결론", "",
         f"- 사전 등록 판정(시나리오 B = 처음 1,000만 원 + 매달 15만 원, 근사 세후): **{v.get('overall')}**.",
         "- PASS(CONTRIB_BEATS_MARKET)는 '전진 원장에 올릴 후보'까지만 뜻한다. 엔진(챔피언·코어)은 바뀌지 않았다.", "",
         "## 왜 장기 자료가 주 근거인가", "",
         "목돈 + 적립의 결과는 '언제 시작했나'에 크게 좌우된다. 10·20년 구간을 서로 겹치지 않게 여러 번 볼 수 있는 자료는 1926년부터의 "
         "Ken French 일별 자료뿐이다(최근 ETF 자료로는 20년 구간이 사실상 한두 번). 그래서 매달 시작하는 10·20년 구간을 "
         "1927~1966(선택)·1967~2007(확인) 두 묶음에서 각각 보고, 둘 다에서 같은 결론이 나와야 통과로 한다. 2008년 이후에 끝나는 구간은 "
         "이미 많은 연구가 본 기간이라 보고만 한다.", "",
         "## 판정 (시나리오 B, 근사 세후)", "",
         "| 전략 | 설명 | 판정 | 선택 10년 | 선택 20년 | 확인 10년 | 확인 20년 | 확인 구간 관측 IR |", "|---|---|---|---|---|---|---|---|"]
    for n in STRATEGIES:
        ch = r["rules_by_scenario"][n][PRIMARY]["checks"]

        def cc(key):
            c = ch[key]
            if any(x is None for x in c.values()):
                return "평가 불가"
            bad = [k for k, x in c.items() if not x]
            return "통과" if not bad else "탈락(" + ",".join(bad) + ")"
        ir = r["observed_ir"].get(n)
        L.append(f"| {n} | {LABELS[n]} | **{v.get(n)}** | {cc('selection_10y')} | {cc('selection_20y')} | "
                 f"{cc('confirmation_10y')} | {cc('confirmation_20y')} | {'-' if ir is None else f'{ir:.2f}'} |")
    L += ["", f"조건(칸마다 모두): 시장보다 많이 남은 구간 ≥ {WIN_SHARE_MIN:.0%} · IRR 차이 중앙값 ≥ {MEDIAN_IRR_MIN * 100:+.1f}%p · "
          f"IRR 차이 하위 10% ≥ {P10_IRR_MIN * 100:+.1f}%p · 시간가중 MDD 중앙값이 시장보다 {MDD_TOL * 100:.0f}%p 넘게 나쁘지 않음. "
          "칸 = 선택·확인 × 10·20년 네 개. 하나라도 빠지면 FAIL(관측 IR 이 최소 검출 효과보다 작으면 FAIL_UNDERPOWERED).", "",
          rp.power_line(r["power"]), "",
          "세후 통계는 1·4·7·10월에 시작하는 구간(매달 시작의 1/3)만으로 냈다(계산 시간 때문에 결과를 보기 전에 정함). 세전 통계는 매달 시작 전부.", ""]
    L += _cell_table(r, PRIMARY, "after", JUDGED_SETS, "시나리오 B — 근사 세후 (판정에 쓰는 숫자)")
    L += _cell_table(r, PRIMARY, "pre", JUDGED_SETS, "시나리오 B — 세전 (매달 시작 전부, 보고)")
    L += ["## 적립이 결론을 바꿨나 (같은 규칙, 근사 세후)", "",
          "| 전략 | A: 목돈만 1,000만 원 | B: 1,000만 + 월 15만 (판정) | C: 300만 + 월 15만 | A와 B 결론이 다른가 |", "|---|---|---|---|---|"]
    for n in STRATEGIES:
        c = r["contributions_changed"][n]
        L.append(f"| {n} | {_yn(c['A_no_contrib'])} | {_yn(c['B_primary'])} | {_yn(c['C_small_initial'])} | "
                 f"{_yn(c['contributions_changed_conclusion'])} |")
    L += ["", "(예 = 네 칸 모두 네 조건 통과)", ""]
    L += _cell_table(r, "A", "after", JUDGED_SETS, "시나리오 A — 목돈만, 근사 세후 (보고)")
    L += _cell_table(r, "C", "after", JUDGED_SETS, "시나리오 C — 300만 원 + 월 15만 원, 근사 세후 (보고)")
    L += ["## 2008년 이후에 끝나는 구간 (보고만)", ""]
    L += _cell_table(r, PRIMARY, "after", ("post2008",), "시나리오 B — 2008+ 끝, 근사 세후")
    L += _cell_table(r, PRIMARY, "pre", ("post2008", "post2008_start2000"), "시나리오 B — 2008+ 끝(및 2000년 이후 시작), 세전")
    L += _cell_table(r, PRIMARY, "after", ("post2008_start2000",), "시나리오 B — 2000년 이후 시작, 근사 세후")
    L += ["## 세금 끌림 (근사, 시나리오 B, IRR 중앙값 = 세전 − 세후)", "",
          "| 전략 | 구간 | 칸 | 전략 세금 끌림 | 시장 세금 끌림 | 보유표 세전 − 소매 세전 IRR 중앙값 |", "|---|---|---|---|---|---|"]
    for n in STRATEGIES:
        for ws in WINDOW_SETS:
            for h in HORIZONS:
                s = r["stats"][n][PRIMARY]["after"][ws][str(h)]
                if s and s.get("n"):
                    L.append(f"| {n} | {ws} | {h}년 | {_pp(s.get('median_tax_drag'))} | {_pp(s.get('median_bench_tax_drag'))} | "
                             f"{_pp(s.get('median_frame_gap'))} |")
    eff = r["stats"][STRATEGIES[0]][PRIMARY]["pre"]
    L += ["", "## 겹침", "",
          "구간이 서로 크게 겹친다. 겹치지 않는 구간 수(전체 기간 ÷ 구간 길이): " + ", ".join(
              f"{ws} {h}년 ≈ {eff[ws][str(h)].get('eff_windows', 0) or 0:.1f}개" for ws in WINDOW_SETS for h in HORIZONS
              if eff[ws][str(h)].get("n")) + ". '70% 구간에서 이김'은 수백 번의 독립 시행이 아니라 몇 번의 독립 시행에 가깝다.", "",
          "## 주의", "",
          "- 지수는 투자할 수 없는 대상이다(산업 포트폴리오·BIG HiPRIOR·합성 2배는 실제 ETF 가 아니며, 1990년대 전에는 이런 상품이 없었다). 비용은 편도 10bp·BIG 연 1%·2배 차입/보수 가정뿐이다.",
          "- 세금은 **근사**다: 지수 수준을 가격으로, 1달러 = 1,300원 고정, 공제 250만 원(명목 원화), 22%, 이월결손금 없음, 배당세·환전비용 없음. "
          "1930년대에 오늘의 명목 250만 원 공제를 그대로 쓰는 것은 매우 거칠다(처음 금액이 같은 원화라 금액 규모 대비 공제는 시대와 무관하게 같지만, 실제 세법은 그때 없었다).",
          "- 세후 최종 = 원래 연구의 세전 결과 × (산업 단위 보유표로 굴린 세금 있음/없음 비율). 보유표는 혼합 전략을 매달(MB) 또는 필터 전환일(L15F)에 전체 재조정해 세금을 조금 더 잡는다(SPEC.md).",
          "- 구간이 겹쳐 통계적 독립 표본이 적다(위 '겹침').",
          "- 모멘텀은 1993년(Jegadeesh·Titman) 이후 널리 알려져, 확인 구간(1967~2007)의 뒷부분부터 효과가 줄었을 수 있다.",
          "- PASS 는 전진 원장 후보일 뿐 채택이 아니다. 엔진은 바뀌지 않았다.", ""]
    t = r.get("timing") or {}
    if t.get("tax_n"):
        L += [f"계산 시간(이번 실행 기준): 세전 구간 {t['pre_n']}개 평균 {t['pre_s'] / max(t['pre_n'], 1):.3f}초, "
              f"세금 구간 {t['tax_n']}개 평균 {t['tax_s'] / t['tax_n']:.2f}초.", ""]
    return "\n".join(L)


def smoke_coverage(r: dict, units: dict) -> dict[str, bool]:
    st = r["stats"]
    return {
        "all_units_complete": all(u["complete"] for u in units.values()),
        "every_judged_cell_has_after_tax": all(st[n][s]["after"][ws][str(h)].get("n", 0) > 0
                                               for n in STRATEGIES for s in SCENARIOS for ws in JUDGED_SETS for h in HORIZONS),
        "post2008_present": all(st[n][PRIMARY]["pre"]["post2008"][str(h)].get("n", 0) > 0 for n in STRATEGIES for h in HORIZONS),
        "tax_paid_somewhere": any((row["tax"] or {}).get("tax_paid_ratio", 0) > 0 for u in units.values() for row in u["rows"].values()),
        "contributions_differ": any(row["pre"]["contributed"] > 1.0 for (n, s, _), u in units.items() if s == "B" for row in u["rows"].values()),
        "verdicts_cover_all": set(STRATEGIES) <= set(r["verdicts"]),
        "results_small": len(json.dumps(r, ensure_ascii=False, default=str)) < 200_000,
    }


# =================================================================================================
# 실행
# =================================================================================================

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-units-per-run", type=int, default=0, help="재개 확인용: 이번 실행에서 새로 끝낼 단위 수 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    power = rp.power_report(POWER_YEARS, N_TRIALS)  # 결과를 보기 전에(구간·시도 수만)
    timing = {"pre_n": 0, "pre_s": 0.0, "tax_n": 0, "tax_s": 0.0, "tax_years": 0.0}
    t_start = time.time()

    def log(s: str) -> None:
        print(s, flush=True)

    def check() -> None:
        if deadline is not None and time.time() > deadline - STOP_MARGIN_S:
            raise _Stop()

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        dpath = ck / "french.pkl"
        data = _load_ckpt(dpath, fp)
        if data is None:
            check()
            data = synthetic_data() if a.smoke else load_real()
            _atomic_pickle(dpath, {"fingerprint": fp, "payload": data})
            log("자료 저장")
        sl = prepare(data)
        sets = window_sets(sl["sleeve_r"].index, SMOKE_STEP_MONTHS if a.smoke else 1)
        counts = {ws: {str(h): {"all": len(sets[ws][h]), "tax": sum(tax_sampled(s) for s, _ in sets[ws][h])} for h in HORIZONS}
                  for ws in WINDOW_SETS}
        log(f"구간 수: {json.dumps(counts)}")
        units: dict[tuple, dict] = {}
        new_units = 0
        for name in ALL_NAMES:
            for scen in SCENARIOS:
                for ws in WINDOW_SETS:
                    path = ck / f"unit_{name}_{scen}_{ws}.pkl"
                    prev = _load_ckpt(path, fp)
                    if not (prev and prev.get("complete")):
                        if a.max_units_per_run and new_units >= a.max_units_per_run:
                            raise _Stop()
                        new_units += 1
                    units[(name, scen, ws)] = run_unit(sl, name, scen, sets[ws], path, fp, check, timing)
                    if not (prev and prev.get("complete")):
                        log(f"단위 완료: {name} {scen} {ws} (누적 {time.time() - t_start:.0f}초)")
        agg = aggregate(units, sl, power)
        result = build_result(agg, counts, power, timing, a.smoke, data["source"])
        if a.smoke:
            cov = smoke_coverage(result, units)
            result["smoke_coverage"] = cov
            bad = [k for k, v in cov.items() if not v]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
    except _Stop:
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    (out / "results.json").write_text(text, encoding="utf-8")
    (out / "REPORT.md").write_text(render(result), encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    log(f"results.json {len(text) / 1024:.0f}KB, 소요 {time.time() - t_start:.0f}초, 시간: {json.dumps(_r(timing))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
