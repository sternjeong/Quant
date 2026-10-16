"""검증 연구 mom-lowturn-v1 (2026-10-16 사전 등록): 같은 산업 모멘텀 신호를 '덜 사고팔면' 세후 수익이 늘어나나.

사용자 요청(2026-10-16: 수익 극대화). sector-concentrate-v1 에서 12 산업 상위 2개(12개월 수익 순위, RS12_k2)는 1927~2007 세전 15.3% 였지만
연 회전율 약 270% 때문에 한국 세금 근사 뒤 약 12.3% 로 줄었다(시장 그냥 보유는 세금 손실이 거의 없다).
가설: 같은 신호를 회전율을 낮춰(순위 완충·덜 잦은 리밸런싱·연말 손실 확정) 돌리면 세전 우위 대부분을 지키면서 세후로 이긴다.

규칙 전체는 SPEC.md(한국어)와 아래 상수에 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 다시 등록한다. 엔진 반영은 사용자 확인 뒤 별도 작업.
신호·M0 시뮬레이션·자료 정리는 sector-concentrate-v1/run.py(→ core-longrun-v1/lab.py)를 그대로 import 해서 쓴다.
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
from core import tax_fx as tx  # noqa: E402

_spec = importlib.util.spec_from_file_location("sector_concentrate_v1_run", PROJECT_ROOT / "research/jobs/sector-concentrate-v1/run.py")
sc = sys.modules.setdefault("sector_concentrate_v1_run", importlib.util.module_from_spec(_spec))
if not hasattr(sc, "simulate"):
    _spec.loader.exec_module(sc)
lab = sc.lab

JOB_ID = "mom-lowturn-v1"
RULES_VERSION = "mom-lowturn-v1/2026-10-16"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
K = 2                                   # 언제나 2개 산업, 동일가중
SIGNAL = "RS12"                         # 252행 수익 − 시장(순위는 252행 수익 순위와 같다)
BUFFERS = (None, 3, 4)                  # 완충: 보유 산업이 상위 K 안이면 유지
FREQS = ("monthly", "quarterly", "annual")
FREQ_MONTHS = {"monthly": tuple(range(1, 13)), "quarterly": (1, 4, 7, 10), "annual": (1,)}
HARVEST = (False, True)
COST_BPS = 10.0
WINDOWS = {"selection": ("1927-07-01", "1966-12-31"), "confirmation": ("1967-01-01", "2007-12-31"),
           "conf_1967_1986": ("1967-01-01", "1986-12-31"), "conf_1987_2007": ("1987-01-01", "2007-12-31"),
           "post2008": ("2008-01-01", None)}
POWER_YEARS, N_TRIALS = 41, 17
WORST_ROWS = 252
WORST_SLACK = 0.05                      # B: 최악 252행 수익 ≥ 시장 최악 − 5%p
M0_MARGIN = 0.005                       # 확인: 세후 ≥ M0 + 0.5%p
MKT_MARGIN = 0.010                      # 확인: 세후 ≥ 시장 + 1.0%p
TIE_TOL = 1e-9
EPS = 1e-12                             # 경계(= 문턱) 비교의 부동소수 오차 여유
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"

# 한국 세금 근사(sector-concentrate-v1 과 같음): 3,000만 원, 1달러 = 1,300원 고정, 22%·공제 250만 원·결손 이월 없음, 편도 10bp
TAX_INITIAL_KRW = 30_000_000
TAX_FX_CONST = 1300.0

# ETF 보조 시험(sector-concentrate-v1 과 같은 메뉴)
ETF_WINDOW = ("2000-01-01", "2024-09-30")
ETF_SPY_MARGIN = 0.005
SUPPORTING, NOT_SUPPORTING = "SUPPORTING", "NOT_SUPPORTING"


def cell_id(buffer: Optional[int], freq: str, harvest: bool) -> str:
    if buffer is None and freq == "monthly" and not harvest:
        return "M0"
    return f"B{buffer or 'none'}_{freq}_{'harvest' if harvest else 'noharvest'}"


def cell_spec(buffer: Optional[int], freq: str, harvest: bool) -> dict:
    """M0 = sector-concentrate RS12_k2 그대로(매 결정일 동일가중으로 다시 맞춤). 나머지 17칸은 이름이 바뀔 때만 동일가중으로 다시 맞춘다."""
    m0 = buffer is None and freq == "monthly" and not harvest
    return {"id": cell_id(buffer, freq, harvest), "buffer": buffer, "freq": freq, "harvest": harvest,
            "reset": "always" if m0 else "on_change"}


SPECS = tuple(cell_spec(b, f, h) for b in BUFFERS for f in FREQS for h in HARVEST)
CELLS = tuple(s["id"] for s in SPECS)
SPEC_BY_ID = {s["id"]: s for s in SPECS}


def moving_parts(spec: dict) -> int:
    return int(spec["buffer"] is not None) + int(spec["freq"] != "monthly") + int(spec["harvest"])


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


# =================================================================================================
# 달력·선택
# =================================================================================================

def decision_flags(index: pd.DatetimeIndex, freq: str) -> np.ndarray:
    """리밸런싱 결정일: 해당 달의 첫 거래일(첫 행 제외). monthly=매달, quarterly=1·4·7·10월, annual=1월."""
    f = lab.month_first_mask(index) & np.isin(index.month, FREQ_MONTHS[freq])
    f[0] = False
    return f


def december_last_flags(index: pd.DatetimeIndex) -> np.ndarray:
    """12월 마지막 거래일(다음 행이 다음 해인 12월 행). 자료 끝 행은 다음 거래일이 없어 제외."""
    f = np.zeros(len(index), dtype=bool)
    if len(index) > 1:
        f[:-1] = (index.month[:-1] == 12) & (index.year[1:] != index.year[:-1])
    return f


def ranking(score_row: np.ndarray) -> Optional[list[int]]:
    """유한한 점수의 내림차순 열 순서(동점은 열 순서, sector-concentrate select_top 과 같음). 유효 구성원이 2K 미만이면 None."""
    fin = np.isfinite(score_row)
    if fin.sum() < sc.MIN_VALID_FACTOR * K:
        return None
    order = np.argsort(-np.where(fin, score_row, -np.inf), kind="stable")
    return [int(j) for j in order[: int(fin.sum())]]


def choose(score_row: np.ndarray, held: list[int], buffer: Optional[int]) -> Optional[list[int]]:
    """보유 산업은 순위가 상위 buffer(없으면 K) 안이면 유지, 빈 자리는 보유하지 않은 가장 높은 순위로 채운다. 언제나 K 개."""
    order = ranking(score_row)
    if order is None:
        return None
    limit = buffer if buffer is not None else K
    rank = {j: r for r, j in enumerate(order)}          # 0 = 1위
    keep = [j for j in held if j in rank and rank[j] < limit]
    keep = sorted(keep, key=lambda j: rank[j])[:K]
    fill = [j for j in order if j not in keep][: K - len(keep)]
    return keep + fill


# =================================================================================================
# 경로 시뮬레이션 (결정일 d 종가에 체결, 수익은 d+1 부터; 그 사이 가격대로 표류)
# =================================================================================================

def run_path(R: np.ndarray, M: np.ndarray, C: np.ndarray, FX: np.ndarray, S: np.ndarray, index: pd.DatetimeIndex,
             cols: list[str], s: int, e: int, spec: dict, market_col: str, bps: float = COST_BPS) -> dict[str, Any]:
    """행 s..e 의 한 계좌. s ≥ 1 이면 s 종가에 현금으로 새로 연다(그 행이 결정일이 아니어도 첫 선택). s == 0 이면 sector-concentrate
    simulate 처럼 시장 100% 로 시작한다(비용 없음). 비용 = Σ|목표 − 표류 비중|(증권만) × 편도 bp. 현금은 수익 0.
    C·FX: 취득가 추적용 종가·환율(원화 취득가 = 종가 × 환율 × (1 + 수수료), tax_fx 와 같은 평균 단가). 손실 확정 판단에만 쓴다."""
    fee = bps / 10000.0
    dec = decision_flags(index, spec["freq"])
    dly = december_last_flags(index)
    m = R.shape[1]
    L = e - s + 1
    h = np.zeros(m)
    hm, hc = (1.0, 0.0) if s == 0 else (0.0, 1.0)
    pv = 1.0
    shares = np.zeros(m)
    basis = np.zeros(m)
    held: list[int] = []
    pending: dict[int, float] = {}
    out, turn = np.zeros(L), np.zeros(L)
    W = np.zeros((L, m + 1))
    last_row = np.r_[np.zeros(m), 1.0] if s == 0 else np.zeros(m + 1)
    toggle = False
    entry: dict[int, int] = {}
    spells: list[float] = []
    harvests: list[dict] = []
    trades = 0

    def set_held(new: list[int], i: int) -> None:
        nonlocal held
        for j in held:
            if j not in new:
                spells.append((index[i] - index[entry.pop(j)]).days)
        for j in new:
            if j not in held:
                entry[j] = i
        held = list(new)

    for i in range(s, e + 1):
        t = i - s
        if i > s:
            g = h * (1 + R[i])
            gm = hm * (1 + M[i])
            tot = g.sum() + gm + hc
            out[t] = tot - 1.0
            h, hm, hc = g / tot, gm / tot, hc / tot
            # 배당 재투자로 늘어난 주수(ETF: 조정가 수익 > 종가 변화)는 그날 종가로 산 것으로 취득가에 더한다
            vals = h * pv * tot
            grow = np.where(shares > 0, vals / C[i] - shares, 0.0)
            pos = grow > 1e-15
            if pos.any():
                basis[pos] += grow[pos] * C[i, pos] * FX[i] * (1 + fee)
                shares[pos] += grow[pos]

        target = None
        opening = i == s and s >= 1
        if opening or (i > s and dec[i]):
            picks = choose(S[i - 1], held, spec["buffer"])
            if picks is None:
                if spec["reset"] == "always" or hm < 1.0 - 1e-12 or opening:
                    target = (np.zeros(m), 1.0)
                set_held([], i)
            else:
                changed = set(picks) != set(held) or hm > 0
                if spec["reset"] == "always" or changed or opening:
                    tg = np.zeros(m)
                    tg[picks] = 1.0 / K
                    target = (tg, 0.0)
                elif pending:
                    target = (_restore(h, hc, pending), 0.0)
                set_held(picks, i)
            pending = {}
        elif pending and i > s:
            target = (_restore(h, hc, pending), hm)
            pending = {}

        def trade(tg: np.ndarray, tm: float, count_turn: bool) -> None:
            nonlocal h, hm, hc, toggle, last_row, trades
            tv = float(np.abs(tg - h).sum() + abs(tm - hm))
            out[t] = (1 + out[t]) * (1 - tv * bps / 10000.0) - 1
            if count_turn:
                turn[t] += tv / 2.0
            pv_after = pv * (1 + out[t])
            new_sh = tg * pv_after / np.where(C[i] > 0, C[i], np.nan)
            new_sh = np.nan_to_num(new_sh)
            up = new_sh > shares + 1e-15
            basis[up] += (new_sh[up] - shares[up]) * C[i, up] * FX[i] * (1 + fee)
            dn = (new_sh < shares - 1e-15) & (shares > 0)
            basis[dn] *= new_sh[dn] / shares[dn]
            shares[:] = new_sh
            basis[new_sh <= 0] = 0.0
            h, hm = tg.copy(), tm
            hc = max(0.0, 1.0 - h.sum() - hm)
            toggle = not toggle
            row = np.r_[h, hm]
            last_row = row * (1 - 1e-8) if toggle else row
            trades += 1

        if target is not None:
            trade(target[0], target[1], not opening)

        # 연말 손실 확정: 12월 마지막 거래일 종가에 평가손 산업을 팔고 다음 거래일 종가에 다시 산다
        if spec["harvest"] and dly[i] and i < e and held:
            losers = [j for j in held if shares[j] > 0 and C[i, j] * FX[i] * (1 - fee) < basis[j] / shares[j]]
            if losers:
                pending = {j: float(h[j]) for j in losers}
                tg = h.copy()
                tg[losers] = 0.0
                trade(tg, hm, True)
                harvests.append({"date": str(index[i].date()), "names": [cols[j] for j in losers]})
        pv *= 1 + out[t]
        W[t] = last_row

    for j in held:
        spells.append((index[e] - index[entry[j]]).days)
    idx = index[s: e + 1]
    return {"returns": pd.Series(out, index=idx), "turnover": pd.Series(turn, index=idx),
            "weights": pd.DataFrame(W, index=idx, columns=list(cols) + [market_col]),
            "avg_holding_years": float(np.mean(spells) / 365.25) if spells else float("nan"),
            "n_spells": len(spells), "harvests": harvests, "n_trades": trades,
            "final_picks": [cols[j] for j in held]}


def _restore(h: np.ndarray, hc: float, pending: dict[int, float]) -> np.ndarray:
    """손실 확정으로 판 산업을 그 현금으로 다시 산다(판 금액 비율대로)."""
    tg = h.copy()
    tot = sum(pending.values())
    for j, w in pending.items():
        tg[j] += hc * (w / tot if tot > 0 else 1.0 / len(pending))
    return tg


# =================================================================================================
# 지표
# =================================================================================================

def rows_of(index: pd.DatetimeIndex, a: str, b: Optional[str]) -> tuple[int, int]:
    s = int(index.searchsorted(pd.Timestamp(a), side="left"))
    e = (int(index.searchsorted(pd.Timestamp(b), side="right")) - 1) if b else len(index) - 1
    return s, e


def worst_rolling(values: pd.Series, n: int = WORST_ROWS, base: Optional[float] = None) -> Optional[float]:
    """연속 n 행 수익의 최솟값(시작 값 base 를 첫 행 앞에 둔다). 행이 모자라면 None."""
    v = values.to_numpy(dtype=float)
    if base is not None:
        v = np.r_[base, v]
    if len(v) <= n:
        return None
    return float((v[n:] / v[:-n] - 1).min())


def tax_config_french() -> tx.AccountConfig:
    return tx.AccountConfig(initial_krw=TAX_INITIAL_KRW, fee_rate=COST_BPS / 10000.0, fx_spread=0.0,
                            apply_tax=True, apply_dividend_tax=False)


def account_metrics(path_ret: pd.Series, turnover: pd.Series, sim: dict, initial: float, extra: dict) -> dict:
    vals = sim["values_krw"]
    pre_v = (1 + path_ret).cumprod()
    y = lab.years_of(path_ret)
    return {
        "first": str(vals.index[0].date()), "last": str(vals.index[-1].date()),
        "pre_tax_cagr": sc.cagr_of(path_ret),
        "after_tax_cagr": sc.liq_cagr(sim["final_after_liquidation_krw"], initial, vals.index[0], vals.index[-1]),
        "tax_paid_krw": sim["totals"]["capital_gains_tax_krw"],
        "liquidation_tax_krw": sim["unpaid_tax_if_sold_now_krw"],
        "turnover_per_year": float(turnover.iloc[1:].sum() / y) if y > 0 else float("nan"),
        "mdd_after_tax": sc.max_drawdown(vals, initial), "worst252_after_tax": worst_rolling(vals, WORST_ROWS, initial),
        "mdd_pre_tax": sc.max_drawdown(pre_v), "worst252_pre_tax": worst_rolling(pre_v, WORST_ROWS, 1.0),
        **extra}


def stability(c: dict, mk: dict) -> dict[str, Optional[bool]]:
    """A: 세후 원화 최대낙폭이 시장보다 나쁘지 않음. B: 세후 최악 252행 수익 ≥ 시장 최악 − 5%p."""
    a = c["mdd_after_tax"] >= mk["mdd_after_tax"] - EPS if _ok(c["mdd_after_tax"]) and _ok(mk["mdd_after_tax"]) else None
    w, wm = c.get("worst252_after_tax"), mk.get("worst252_after_tax")
    b = (w >= wm - WORST_SLACK - EPS) if _ok(w) and _ok(wm) else None
    return {"A_mdd": a, "B_worst252": b}


def _ok(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def select_cell(sel: dict[str, dict], mkt_sel: dict) -> tuple[Optional[str], list[str]]:
    """SELECTION 에서 A·B 를 모두 만족한 칸 중 세후 CAGR 최고(동점 → 움직이는 부분이 적은 칸 → 칸 순서). 없으면 None."""
    elig = [c for c in CELLS if c in sel and all(v is True for v in stability(sel[c], mkt_sel).values())
            and _ok(sel[c]["after_tax_cagr"])]
    if not elig:
        return None, []
    best = max(sel[c]["after_tax_cagr"] for c in elig)
    tied = [c for c in elig if sel[c]["after_tax_cagr"] >= best - TIE_TOL]
    tied.sort(key=lambda c: (moving_parts(SPEC_BY_ID[c]), CELLS.index(c)))
    return tied[0], elig


def confirmation_checks(c: dict, m0: dict, mk: dict, sub_c: list[dict], sub_m: list[dict]) -> dict[str, Optional[bool]]:
    at, at0, atm = c["after_tax_cagr"], m0["after_tax_cagr"], mk["after_tax_cagr"]
    st = stability(c, mk)
    subs = [(x["after_tax_cagr"] > y["after_tax_cagr"]) if _ok(x["after_tax_cagr"]) and _ok(y["after_tax_cagr"]) else None
            for x, y in zip(sub_c, sub_m)]
    return {"vs_M0": (at >= at0 + M0_MARGIN - EPS) if _ok(at) and _ok(at0) else None,
            "vs_market": (at >= atm + MKT_MARGIN - EPS) if _ok(at) and _ok(atm) else None,
            "A_mdd": st["A_mdd"], "B_worst252": st["B_worst252"],
            "subperiods_both": (all(v is True for v in subs)) if all(v is not None for v in subs) else None}


def active_ir(a: pd.Series, b: pd.Series) -> Optional[float]:
    """세후 원화 값의 일별 수익 차이로 본 연 정보비율(252 행)."""
    ra, rb = a.pct_change().dropna(), b.pct_change().dropna()
    d = (ra - rb.reindex(ra.index)).dropna()
    sd = float(d.std())
    if len(d) < 30 or not sd > 0:
        return None
    return float(d.mean() / sd * math.sqrt(252))


def final_verdict(chosen: Optional[str], checks: Optional[dict], noop: Optional[str], observed_ir: Optional[float],
                  power: dict) -> tuple[str, str]:
    """(판정, 사유). 고른 칸이 없거나 M0 이면 FAIL. 무효 실행 → NOT_EVALUABLE. 모든 확인 관문 → PASS. 그 밖 → classify_fail."""
    if chosen is None:
        return FAIL, "선택 구간에서 A·B 를 모두 만족한 칸이 없음"
    if chosen == "M0":
        return FAIL, "선택 구간 최고 칸이 기준선 M0 — 회전율을 낮춘 변형이 이기지 못함"
    if noop:
        return NOT_EVALUABLE, noop
    if checks and all(v is True for v in checks.values()):
        return PASS, "확인 구간 관문 모두 통과"
    bad = [k for k, v in (checks or {}).items() if v is not True]
    return rp.classify_fail(observed_ir, power), "미달 관문: " + ", ".join(bad)


def etf_verdict(chosen: Optional[dict], m0: dict, spy: dict) -> str:
    """SUPPORTING iff 고른 칸 세후(청산) ≥ SPY + 0.5%p 그리고 ≥ M0 세후."""
    if not chosen:
        return NOT_SUPPORTING
    try:
        ok = (chosen["after_tax_cagr"] >= spy["after_tax_cagr"] + ETF_SPY_MARGIN - EPS
              and chosen["after_tax_cagr"] >= m0["after_tax_cagr"] - EPS)
    except (TypeError, KeyError):
        ok = False
    return SUPPORTING if ok else NOT_SUPPORTING


# =================================================================================================
# 자료 준비
# =================================================================================================

def french_panel(data: dict) -> dict:
    rets = data["ind12"]
    mkt = data["mkt"].reindex(rets.index).fillna(0.0)
    R = rets.fillna(0.0).to_numpy()
    lev = (1 + pd.concat([rets.fillna(0.0), mkt.rename("MKT")], axis=1)).cumprod()
    return {"index": rets.index, "cols": list(rets.columns), "R": R, "M": mkt.to_numpy(),
            "C": lev[list(rets.columns)].to_numpy(), "FX": np.full(len(rets), TAX_FX_CONST),
            "S": sc.raw_signals(rets, mkt)[SIGNAL].to_numpy(), "market_col": "MKT",
            "close": lev, "adj": lev, "fx": pd.Series(TAX_FX_CONST, index=rets.index)}


def etf_panel(inp: dict) -> dict:
    prep = sc.etf_prepare(inp)
    rets = prep["rets"]
    idx = rets.index
    close = prep["close"].reindex(idx)
    fx = prep["fx"].reindex(idx).ffill().bfill()
    return {"index": idx, "cols": list(rets.columns), "R": rets.fillna(0.0).to_numpy(), "M": prep["mkt"].reindex(idx).fillna(0.0).to_numpy(),
            "C": close[list(rets.columns)].ffill().bfill().to_numpy(), "FX": fx.to_numpy(),
            "S": sc.raw_signals(rets, prep["mkt"])[SIGNAL].to_numpy(), "market_col": sc.ETF_MARKET,
            "close": prep["close"], "adj": prep["adj"], "fx": prep["fx"]}


def run_account(P: dict, spec: Optional[dict], a: str, b: Optional[str], cfg: tx.AccountConfig) -> dict:
    """spec None = 시장(MKT/SPY) 처음에 사서 끝까지 보유. 반환: 지표 + (확인용) 세후 원화 값·경로 수익."""
    s, e = rows_of(P["index"], a, b)
    idx = P["index"][s: e + 1]
    if spec is None:
        r = pd.Series(P["M"][s: e + 1], index=idx).copy()
        r.iloc[0] = -COST_BPS / 10000.0        # 새 계좌 첫 매수 비용
        turn = pd.Series(0.0, index=idx)
        w = tx.buy_and_hold_weights(idx, P["market_col"])
        extra = {"avg_holding_years": lab.years_of(r), "n_spells": 1, "n_harvests": 0, "n_trades": 1}
        path = {"returns": r}
    else:
        path = run_path(P["R"], P["M"], P["C"], P["FX"], P["S"], P["index"], P["cols"], s, e, spec, P["market_col"])
        r, turn, w = path["returns"], path["turnover"], path["weights"]
        extra = {"avg_holding_years": path["avg_holding_years"], "n_spells": path["n_spells"],
                 "n_harvests": len(path["harvests"]), "n_trades": path["n_trades"],
                 "final_picks": path["final_picks"], "harvest_sample": path["harvests"][-3:]}
    sim = tx.simulate(w, P["close"], P["adj"], P["fx"], cfg)
    met = account_metrics(r, turn, sim, cfg.initial_krw, extra)
    return {"metrics": met, "values": sim["values_krw"].astype("float64"), "returns": path["returns"]}


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


# =================================================================================================
# 계산 단계
# =================================================================================================

def cell_stage(P: dict, spec: Optional[dict]) -> dict:
    """한 칸(또는 시장)의 5개 창. 확인 구간만 세후 값·경로 수익을 남긴다(IR·무효 실행 가드용)."""
    cfg = tax_config_french()
    out: dict[str, Any] = {"windows": {}}
    for wname, (a, b) in WINDOWS.items():
        acc = run_account(P, spec, a, b, cfg)
        out["windows"][wname] = acc["metrics"]
        if wname == "confirmation":
            out["conf_values"] = acc["values"]
            out["conf_returns"] = acc["returns"]
    return out


def decide(cells: dict, mkt: dict, power: dict) -> dict:
    sel = {c: cells[c]["windows"]["selection"] for c in CELLS}
    chosen, elig = select_cell(sel, mkt["windows"]["selection"])
    res: dict[str, Any] = {"chosen": chosen, "eligible_in_selection": elig,
                           "selection_stability": {c: stability(sel[c], mkt["windows"]["selection"]) for c in CELLS}}
    checks = noop = ir = None
    if chosen is not None:
        cw, m0w, mw = cells[chosen]["windows"], cells["M0"]["windows"], mkt["windows"]
        checks = confirmation_checks(cw["confirmation"], m0w["confirmation"], mw["confirmation"],
                                     [cw["conf_1967_1986"], cw["conf_1987_2007"]],
                                     [mw["conf_1967_1986"], mw["conf_1987_2007"]])
        if chosen != "M0":
            a, b = cells[chosen]["conf_returns"], cells["M0"]["conf_returns"]
            noop = rp.noop_guard((a - b.reindex(a.index)).fillna(0.0).tolist())
            ir = active_ir(cells[chosen]["conf_values"], cells["M0"]["conf_values"])
    v, why = final_verdict(chosen, checks, noop, ir, power)
    res.update({"confirmation_checks": checks, "noop": noop, "observed_ir_after_tax_vs_M0": ir, "verdict": v, "reason": why})
    res["noop_vs_M0_confirmation"] = {
        c: rp.noop_guard((cells[c]["conf_returns"] - cells["M0"]["conf_returns"].reindex(cells[c]["conf_returns"].index)).fillna(0.0).tolist())
        for c in CELLS if c != "M0"}
    return res


def smoke_coverage(cells: dict, mkt: dict, dec: dict, etf: dict) -> dict:
    allw = [w for c in CELLS for w in cells[c]["windows"].values()]
    return {
        "eighteen_cells": len(cells) == 18 and len(CELLS) == 18,
        "all_windows": all(len(cells[c]["windows"]) == len(WINDOWS) for c in CELLS) and len(mkt["windows"]) == len(WINDOWS),
        "tax_engine": all(_ok(w["after_tax_cagr"]) for w in allw),
        "tax_paid_somewhere": any(w["tax_paid_krw"] > 0 for w in allw),
        "harvest_happened": any(w["n_harvests"] > 0 for c in CELLS if SPEC_BY_ID[c]["harvest"] for w in cells[c]["windows"].values()),
        "no_harvest_when_off": all(w["n_harvests"] == 0 for c in CELLS if not SPEC_BY_ID[c]["harvest"] for w in cells[c]["windows"].values()),
        "lower_turnover_exists": any(cells[c]["windows"]["selection"]["turnover_per_year"]
                                     < cells["M0"]["windows"]["selection"]["turnover_per_year"] for c in CELLS if c != "M0"),
        "verdict_label": dec["verdict"] in (PASS, FAIL, "FAIL_UNDERPOWERED", NOT_EVALUABLE),
        "etf_ran": all(k in etf["sims"] for k in ("M0", "SPY")) and etf["verdict"] in (SUPPORTING, NOT_SUPPORTING),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-steps-per-run", type=int, default=0, help="재개 확인용: 이번 실행에서 새로 할 단계 수 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    power = rp.power_report(POWER_YEARS, N_TRIALS)  # 결과를 보기 전에(구간·시도 수만)
    steps = {"new": 0}

    def log(s: str) -> None:
        print(s, flush=True)

    def check_time(margin: float = 90.0) -> None:
        if deadline is not None and time.time() > deadline - margin:
            raise _Stop()

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    def stage(name: str, fn, extra_fp: Optional[dict] = None):
        path = ck / f"{name}.pkl"
        f = {**fp, **(extra_fp or {})}
        got = _load_ckpt(path, f)
        if got is None:
            if a.max_steps_per_run and steps["new"] >= a.max_steps_per_run:
                raise _Stop()
            check_time()
            got = fn()
            _atomic_pickle(path, {"fingerprint": f, "payload": got})
            steps["new"] += 1
            log(f"단계 저장: {name}")
        return got

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        data = stage("french", lambda: _strip(lab.synthetic_data() if a.smoke else lab.load_real()))
        P = french_panel(data)
        cells = {c: stage(f"cell_{c}", lambda c=c: cell_stage(P, SPEC_BY_ID[c])) for c in CELLS}
        mkt = stage("cell_MKT", lambda: cell_stage(P, None))
        dec = decide(cells, mkt, power)

        einp = stage("etf_inputs", lambda: sc.synthetic_etf() if a.smoke else sc.load_etf_real())
        EP = etf_panel(einp)
        ecfg = tx.AccountConfig()
        wa, wb = ETF_WINDOW
        etf_cells = ["M0"] + ([dec["chosen"]] if dec["chosen"] and dec["chosen"] != "M0" else [])
        sims = {c: stage(f"etf_{c}", lambda c=c: run_account(EP, SPEC_BY_ID[c], wa, wb, ecfg)["metrics"]) for c in etf_cells}
        sims["SPY"] = stage("etf_SPY", lambda: run_account(EP, None, wa, wb, ecfg)["metrics"])
        etf = {"sims": sims, "chosen": dec["chosen"],
               "verdict": etf_verdict(sims.get(dec["chosen"]) if dec["chosen"] else None, sims["M0"], sims["SPY"]),
               "source": einp["source"], "missing": einp.get("missing", [])}
        result = build_result(cells, mkt, dec, etf, power, a.smoke, data["source"], str(P["index"][-1].date()))
        if a.smoke:
            cov = smoke_coverage(cells, mkt, dec, etf)
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
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(render(result), encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


def _strip(data: dict) -> dict:
    """49 산업은 쓰지 않는다(체크포인트 크기 절약)."""
    return {k: v for k, v in data.items() if k != "ind49"}


def _r(x, nd=5):
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return round(x, nd) if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    return x


def build_result(cells: dict, mkt: dict, dec: dict, etf: dict, power: dict, smoke: bool, source: str, data_end: str) -> dict:
    v = dec["verdict"]
    verdicts = {
        "overall": f"SMOKE_ONLY({v})" if smoke else v,
        "chosen_cell": dec["chosen"] or "없음",
        "reason": dec["reason"],
        "etf_support": f"SMOKE_ONLY({etf['verdict']})" if smoke else etf["verdict"],
    }
    if dec["chosen"]:
        cw = cells[dec["chosen"]]["windows"]["confirmation"]
        verdicts["confirmation_after_tax"] = (f"{dec['chosen']} {cw['after_tax_cagr'] * 100:.2f}% · M0 "
                                              f"{cells['M0']['windows']['confirmation']['after_tax_cagr'] * 100:.2f}% · 시장 "
                                              f"{mkt['windows']['confirmation']['after_tax_cagr'] * 100:.2f}%")
    table = {c: cells[c]["windows"] for c in CELLS}
    return _r({"judge_version": RULES_VERSION, "smoke": smoke, "source": source, "data_end": data_end,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "verdicts": verdicts, "power": power, "decision": dec,
               "rule": {"universe": "Ken French 12 industries daily value-weighted (weekday calendar)", "market": "Mkt-RF + RF",
                        "signal": f"{sc.W_RS}-row return − market (rank = {sc.W_RS}-row return rank)", "k": K,
                        "cells": {c: SPEC_BY_ID[c] for c in CELLS}, "n_trials": N_TRIALS,
                        "M0": "sector-concentrate-v1 RS12_k2: top-2 equal weight, reset every month",
                        "variants": "equal-weight reset only when a name changes; buffer keeps held names ranked within top K",
                        "harvest": "last trading day of December: sell held industries with unrealized KRW loss at close, buy back at next trading day's close (cash 0% for one day)",
                        "timing": "signal = close before decision day d; trade at close of d; each window is a fresh account",
                        "cost_bps_one_way": COST_BPS, "windows": WINDOWS},
               "thresholds": {"A": "after-tax KRW MDD >= market's", "B": f"worst {WORST_ROWS}-row after-tax return >= market's - {WORST_SLACK}",
                              "vs_M0_pp": M0_MARGIN, "vs_market_pp": MKT_MARGIN,
                              "subperiods": "after-tax CAGR > market in 1967-1986 and 1987-2007 (fresh accounts)",
                              "etf": {"vs_spy_pp": ETF_SPY_MARGIN, "and": ">= M0 after-tax", "window": ETF_WINDOW}},
               "tax_approx": (f"approximation: tax_fx.simulate on industry total-return index levels as prices, {TAX_INITIAL_KRW:,} KRW, "
                              f"fixed 1 USD = {TAX_FX_CONST:,.0f} KRW, 22% on realized gains above 2.5M KRW/yr, no loss carry-forward, "
                              "fee 10bp, no FX cost/dividend tax, liquidation-adjusted at window end"),
               "cells": table, "market": mkt["windows"], "etf": etf})


# =================================================================================================
# 보고서
# =================================================================================================

def _p(x, signed=False, nd=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _yn(v):
    return "—" if v is None else ("통과" if v else "미달")


def _name(c: str) -> str:
    if c == "M0":
        return "M0 기준(매달 동일가중)"
    s = SPEC_BY_ID[c]
    b = "완충 없음" if s["buffer"] is None else f"완충 {s['buffer']}"
    f = {"monthly": "매달", "quarterly": "분기", "annual": "매년 1월"}[s["freq"]]
    return f"{b}·{f}·{'손실 확정' if s['harvest'] else '확정 없음'}"


def _yr(x) -> str:
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.1f}년"


def _krw(x) -> str:
    return "—" if x is None else f"{x / 10000:,.0f}만"


def render(r: dict) -> str:
    v, d = r["verdicts"], r["decision"]
    smoke = r["smoke"]
    L = [f"# 저회전 모멘텀 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
         "sector-concentrate-v1 의 12 산업 상위 2개(12개월 수익 순위, 매달 동일가중)는 1927~2007 세전 연 15.3% 였지만 회전율이 연 약 270% 라 "
         "한국 세금 근사 뒤 약 12.3% 로 줄었다. 같은 신호를 **덜 사고팔면**(순위 완충, 덜 잦은 리밸런싱, 연말 손실 확정) 세전 우위를 대부분 "
         "지키면서 세후로 더 남는지 본다. 선택 구간(1927-07 ~ 1966)에서 칸 하나를 고르고, 확인 구간(1967 ~ 2007)에서 판정한다.", "",
         f"**판정: {v['overall']}** · 고른 칸: {v['chosen_cell']} · 사유: {v['reason']} · ETF 시대 보조 시험: {v['etf_support']}", "",
         rp.power_line(r["power"]), "",
         "## 판정 규칙 (결과를 보기 전에 고정)", "",
         "- 칸 18개 = 완충 {없음, 3, 4} × 리밸런싱 {매달, 분기(1·4·7·10월), 매년 1월} × 연말 손실 확정 {끔, 켬}. "
         "(완충 없음·매달·끔) 자리는 기준선 M0(sector-concentrate RS12_k2, 매달 동일가중으로 다시 맞춤). 나머지 17칸(시도 수 17)은 "
         "산업이 바뀔 때만 두 산업을 동일가중으로 다시 맞춘다.",
         "- 안정성(세후 원화 값 기준, 시장도 같은 세금 근사로 그냥 보유): A 최대 낙폭이 시장보다 나쁘지 않음 · "
         f"B 최악 연속 {WORST_ROWS}거래일 수익 ≥ 시장 최악 − {WORST_SLACK * 100:.0f}%p.",
         "- 선택(1927-07-01 ~ 1966-12-31): A·B 를 만족한 칸 중 세후 연수익(청산 반영) 최고. 동점이면 움직이는 부분이 적은 칸.",
         f"- 확인(1967-01-01 ~ 2007-12-31): 세후 ≥ M0 세후 + {M0_MARGIN * 100:.1f}%p · 세후 ≥ 시장 세후 + {MKT_MARGIN * 100:.1f}%p · A · B · "
         "1967~1986 과 1987~2007 각각 새 계좌로 세후 > 시장. 모두 만족하면 PASS_FORWARD_CANDIDATE(전진 원장 후보). "
         "탈락은 classify_fail(관측 IR = 확인 구간 세후 원화 일별 수익의 M0 대비 정보비율)로 FAIL / FAIL_UNDERPOWERED. "
         "고른 칸이 M0 와 매일 같으면 NOT_EVALUABLE. M0 가 뽑히면 FAIL.", "",
         "## 선택 구간 1927-07 ~ 1966 (모든 칸)", "",
         "| 칸 | 세전 | 세후 | 낸 세금(+청산 세금) | 연 회전율 | 평균 보유 | 손실 확정 횟수 | 세후 최대낙폭 | 세후 최악 252일 | A | B |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    mk = r["market"]

    def row(label, w, st=None):
        st = st or {}
        return (f"| {label} | {_p(w['pre_tax_cagr'])} | {_p(w['after_tax_cagr'])} | {_krw(w['tax_paid_krw'])}(+{_krw(w['liquidation_tax_krw'])}) | "
                f"{_p(w['turnover_per_year'], nd=0)} | {_yr(w['avg_holding_years'])} | {w.get('n_harvests', 0)} | {_p(w['mdd_after_tax'])} | "
                f"{_p(w['worst252_after_tax'])} | {_yn(st.get('A_mdd'))} | {_yn(st.get('B_worst252'))} |")

    for c in r["cells"]:
        w = r["cells"][c]["selection"]
        tag = " **←선택**" if c == d.get("chosen") else ""
        L.append(row(f"{c} ({_name(c)}){tag}", w, d["selection_stability"].get(c)))
    L.append(row("시장 그냥 보유", mk["selection"]))
    L += ["", "## 확인 구간 1967 ~ 2007 (모든 칸 보고, 판정은 고른 칸만)", "",
          "| 칸 | 세전 | 세후 | 낸 세금(+청산 세금) | 연 회전율 | 평균 보유 | 손실 확정 횟수 | 세후 최대낙폭 | 세후 최악 252일 | 1967~86 세후 | 1987~2007 세후 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in list(r["cells"]) + ["MKT"]:
        ws = r["cells"][c] if c != "MKT" else mk
        w = ws["confirmation"]
        L.append(f"| {c if c != 'MKT' else '시장 그냥 보유'} | {_p(w['pre_tax_cagr'])} | {_p(w['after_tax_cagr'])} | "
                 f"{_krw(w['tax_paid_krw'])}(+{_krw(w['liquidation_tax_krw'])}) | {_p(w['turnover_per_year'], nd=0)} | "
                 f"{_yr(w['avg_holding_years'])} | {w.get('n_harvests', 0)} | {_p(w['mdd_after_tax'])} | {_p(w['worst252_after_tax'])} | "
                 f"{_p(ws['conf_1967_1986']['after_tax_cagr'])} | {_p(ws['conf_1987_2007']['after_tax_cagr'])} |")
    ch = d.get("confirmation_checks")
    if ch:
        L += ["", f"고른 칸 {d['chosen']} 확인 관문: M0 + {M0_MARGIN * 100:.1f}%p {_yn(ch['vs_M0'])} · 시장 + {MKT_MARGIN * 100:.1f}%p "
              f"{_yn(ch['vs_market'])} · A {_yn(ch['A_mdd'])} · B {_yn(ch['B_worst252'])} · 두 하위 구간 {_yn(ch['subperiods_both'])}. "
              f"관측 IR(세후, M0 대비) {d['observed_ir_after_tax_vs_M0'] if d['observed_ir_after_tax_vs_M0'] is not None else '—'}."]
    L += ["", f"## 보고만: 2008 ~ {r['data_end'][:7]} (이미 여러 연구가 본 구간)", "",
          "| 칸 | 세전 | 세후 | 연 회전율 | 세후 최대낙폭 |", "|---|---|---|---|---|"]
    for c in list(r["cells"]) + ["MKT"]:
        w = (r["cells"][c] if c != "MKT" else mk)["post2008"]
        L.append(f"| {c if c != 'MKT' else '시장 그냥 보유'} | {_p(w['pre_tax_cagr'])} | {_p(w['after_tax_cagr'])} | "
                 f"{_p(w['turnover_per_year'], nd=0)} | {_p(w['mdd_after_tax'])} |")
    e = r["etf"]
    L += ["", "## ETF 시대 보조 시험 (세후 원화 실제 환율, SUPPORTING / NOT_SUPPORTING — PASS 아님)", "",
          "Select Sector SPDR(XLB XLE XLF XLI XLK XLP XLU XLV XLY, XLRE·XLC 는 상장 뒤 신호가 생기면), 시장 = SPY, 같은 규칙. "
          "카카오페이증권 기본값(`tax_fx.AccountConfig()` — 3,000만 원, 수수료 0.1%, 환전 우대 95%, 양도세 22%·공제 250만 원), "
          f"2000-01 ~ 2024-09, 끝에 청산. SUPPORTING = 고른 칸 세후 ≥ SPY + {ETF_SPY_MARGIN * 100:.1f}%p 그리고 ≥ M0 세후.", ""]
    if e.get("missing"):
        L += [f"받지 못한 가격: {', '.join(e['missing'])}", ""]
    L += ["| 칸 | 세전(달러 경로, 10bp) | 세후 원화(청산) | 낸 양도세 | 연 회전율 | 세후 최대낙폭 | 손실 확정 횟수 |", "|---|---|---|---|---|---|---|"]
    for c, w in e["sims"].items():
        L.append(f"| {c} | {_p(w['pre_tax_cagr'])} | {_p(w['after_tax_cagr'])} | {_krw(w['tax_paid_krw'])} | "
                 f"{_p(w['turnover_per_year'], nd=0)} | {_p(w['mdd_after_tax'])} | {w.get('n_harvests', 0)} |")
    L += ["", f"판정: **{v['etf_support']}**", "",
          "## 주의", "",
          "- **세금은 근사다.** 산업 총수익 지수를 가격으로 놓고 1달러 = 1,300원 고정, 연 250만 원 공제·22%·손실 이월 없음, 다음 해 5월 납부, "
          "편도 10bp, 환전 비용·배당 세금 없음, 창 끝에 전부 판다고 보고 미납 세금을 뺐다. 250만 원 공제는 1927 년에도 같은 명목 원화 금액이라 "
          "옛 구간일수록 실제와 다르다. 세무 조언이 아니다.",
          "- **연말 손실 확정**: 12월 마지막 거래일 종가에 평가손 산업을 팔고 다음 거래일 종가에 다시 산다(하루 현금, 수익 0). "
          "한국에는 해외주식에 대한 미국식 '워시세일(되사기 손실 불인정)' 규칙이 없다고 가정했다 — **확인 필요**. "
          "평가손 판단은 경로 계산 안의 평균 취득가 추적(수수료 포함)으로 하고, 실제 세금은 tax_fx 가 자기 취득가로 계산한다(둘은 거의 같다).",
          "- 산업 포트폴리오는 그대로 살 수 있는 상품이 아니다(1998 년 이전 섹터 ETF 없음). ETF 메뉴(미국 섹터 SPDR)는 일부 사후 지식이다.",
          "- 각 창은 새 계좌(창 첫날 종가에 현금으로 시작, 첫 선택)다. 손실 확정을 위해 판 날의 비중 조정은 경로의 표류 비중을 목표로 쓰므로 "
          "남은 산업도 아주 작게 사고팔 수 있다.",
          "- 2개 산업 집중은 한 산업의 붕괴에 그대로 노출된다.",
          "- PASS 는 '전진 원장에 올릴 후보'일 뿐 채택이 아니다. 엔진(챔피언 전략)은 바뀌지 않았다 — 반영은 사용자 확인 뒤 별도 작업.",
          "- 2024-10 이후 구간은 판정에 쓰지 않는다."]
    if smoke:
        L += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
