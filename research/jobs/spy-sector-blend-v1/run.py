"""검증 연구 spy-sector-blend-v1 (2026-10-17 사전 등록): SPY 를 바탕으로 두고 모멘텀·변동성 맞춤 섹터 소매를 섞으면 나은가.

사용자 방향(2026-10-17): 산업 모멘텀 + 변동성 맞춤(I2/VT20/none)은 1967~2007 에서 가장 강한 장기 결과(연 16.0% 대 시장 10.8%,
최대낙폭 −38.6% 대 −49.2%)였지만 2008 이후에는 뒤처졌다(8.7% 대 11.5%). 최근에는 SPY 가 강했다. 둘을 섞으면 어떤가.

PART L (장기·세전·판정): 시장(Mkt-RF+RF) × (1−w) + FF12 소매 I2/VT20/none × w, w ∈ {15,30,50,70,100}%, 매년 1월 첫 거래일에 목표 비중으로 재조정
(재조정 회전율 × 편도 10bp, 소매 자신의 비용 위에 추가). 시도 5. 선택 1927-07-01~1966-12-31, 확인 1967-01-01~2007-12-31, 2008~ 은 보고만.
PART E (ETF 시대·한국 세후·판정): SPY × (1−w) + SC2VT20 소매 × w(core/forward_tournament_v3.py 정의 그대로, 남는 몫 BIL), 1월에만 소매 크기를 목표로 되돌림.
판정 구간 2000-01-03~2024-09-30, 절반 경계 2012-06-30. PART L 에서 고른 w 만 PART E 판정.

규칙 전체는 SPEC.md(한국어)와 아래 상수에 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 다시 등록한다. 엔진은 바뀌지 않는다.
소매·통계는 mom-volscale-v1/run.py, 세금 계좌는 core/tax_fx.py, SC2VT20 정의는 core/forward_tournament_v3.py 를 그대로 가져다 쓴다.
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

from core import forward_tournament_v3 as ft3  # noqa: E402
from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mv = _load("_ssb_mom_volscale_v1", "research/jobs/mom-volscale-v1/run.py")
sc = _load("_ssb_sector_concentrate_v1", "research/jobs/sector-concentrate-v1/run.py")
lab = mv.lab

JOB_ID = "spy-sector-blend-v1"
RULES_VERSION = "spy-sector-blend-v1/2026-10-17"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
WS = (0.15, 0.30, 0.50, 0.70, 1.00)
N_TRIALS = 5
POWER_YEARS_L = 41
POWER_YEARS_E = 24.7
COST_BPS = 10.0                      # 재조정 회전율에 붙는 편도 bp(소매 자신의 비용 위에 추가)
EPS = 1e-12                          # 포함 비교(≥)의 부동소수 오차 허용

SELECTION = ("1927-07-01", "1966-12-31")
CONFIRMATION = ("1967-01-01", "2007-12-31")
CONF_HALVES = {"h1": ("1967-01-01", "1986-12-31"), "h2": ("1987-01-01", "2007-12-31")}
RECENT = ("2008-01-01", None)
L_WINDOWS = {"selection": SELECTION, "confirmation": CONFIRMATION, "h1": CONF_HALVES["h1"], "h2": CONF_HALVES["h2"],
             "recent": RECENT}

L_CAGR_MARGIN = 0.010                # 확인: 연수익 ≥ 시장 + 1.0%p
ROLL_SLACK = 0.05                    # B: 최악 252행 ≥ 시장 최악 − 5%p
ALPHA_T_MIN = 2.0

E_AFTER_TAX_MARGIN = 0.005           # 세후 연수익 ≥ SPY + 0.5%p
E_MDD_TOL = 0.03                     # 원화 MDD 가 SPY 보다 3%p 넘게 나쁘지 않음
E_BOOT_FLOOR = -0.005                # 부트스트랩 90% 하한 > −0.5%p
N_BOOT, BLOCK_DAYS, BOOT_SEED = 1000, 126, 20261030
E_START, E_END, E_SPLIT = "2000-01-03", "2024-09-30", "2012-06-30"
E_POST_START = "2024-10-01"
TAX_INITIAL_KRW, TAX_INITIAL_KRW_BIG = 30_000_000, 100_000_000

ETF_MENU = list(ft3.SECTORS)         # 9 개 원본 + XLRE·XLC(252행 생기면 신호에 들어감)
SPY, BIL = ft3.SPY, ft3.BIL
ETF_TICKERS = ETF_MENU + [SPY, BIL]
ETF_DATA_START = "1998-12-01"
FILL_LIMIT = 3                       # 상장 뒤 드문 결측일만 최대 3일 앞 값으로 채움(상장 전 결측은 그대로)

PASS_L, PASS_E = "PASS_LONGRUN", "PASS_ETF"
FAIL, NOT_EVALUABLE, NOT_JUDGED = "FAIL", "NOT_EVALUABLE", "NOT_JUDGED"
BOTH_PASS, LONGRUN_ONLY, ETF_ONLY, NEITHER = "BOTH_PASS", "LONGRUN_ONLY", "ETF_ONLY", "NEITHER"


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def wname(w: float) -> str:
    return f"w{int(round(w * 100))}"


def etf_windows(smoke: bool) -> dict[str, tuple[str, Optional[str]]]:
    """PART E 계산 창. 스모크는 같은 구조의 짧은 창(합성 자료 확인용)."""
    if smoke:
        return {"judged": ("2013-01-01", "2017-12-29"), "h1": ("2013-01-01", "2015-06-30"), "h2": ("2015-07-01", "2017-12-29"),
                "post": ("2018-01-01", "2018-12-31")}
    return {"judged": (E_START, E_END), "h1": (E_START, E_SPLIT), "h2": ("2012-07-02", E_END), "post": (E_POST_START, None)}


# =================================================================================================
# PART L — 자료·소매·섞기
# =================================================================================================

def load_real() -> dict[str, Any]:
    """Ken French 일별 FF3·12 산업(대형 고모멘텀 BH 는 쓰지 않으므로 받지 않는다)."""
    from core import french_factors as ff

    ff3, i12 = ff.load("ff3_daily"), ff.load("ind12_daily")
    if ff3 is None or i12 is None:
        raise RuntimeError("Ken French 일별 FF3 / 12 산업 자료를 받지 못함")
    out = lab._normalize(ff3["RF"], ff3["Mkt-RF"] + ff3["RF"], i12, None)
    out["source"] = "Ken French data library (daily, weekday calendar; 12 industries VW)"
    return out


def synthetic_long(seed: int = 7) -> dict[str, Any]:
    d = lab.synthetic_data(seed=seed)
    return {"rf": d["rf"], "mkt": d["mkt"], "ind12": d["ind12"], "source": "synthetic (smoke)"}


def long_sleeve(data: dict) -> dict[str, Any]:
    """mom-volscale-v1 의 I2/VT20/none 칸 그대로(상위 2, 252행 모멘텀, 직전 126행 자기 변동성, 상한 1.0, 나머지 RF, 월 1회, 10bp)."""
    panel, rf = data["ind12"], data["rf"]
    sched = mv.pick_schedule(panel, "I2")
    raw = mv.raw_sleeve(panel, rf, sched, 2)
    exp = mv.exposure_schedule(raw, np.zeros(len(panel), dtype=bool), sched, "VT20", "none")
    return mv.simulate(panel, rf, sched, exp, 2)


def blend(r_sleeve: pd.Series, r_mkt: pd.Series, w: float, bps: float = COST_BPS) -> tuple[pd.Series, pd.Series]:
    """시장 (1−w) + 소매 w 로 시작해 매년 1월 첫 거래일 종가에 목표 비중으로 되돌린다. 재조정 비용 = 회전율 × 편도 bp.
    반환: 일별 수익, 재조정 회전율(Σ|Δ비중|, 계좌 대비). lab.blend_returns 와 같은 산식."""
    idx = r_sleeve.index
    a = r_sleeve.to_numpy(dtype=float)
    b = r_mkt.reindex(idx).fillna(0.0).to_numpy(dtype=float)
    years = idx.year
    va, vb = w, 1.0 - w
    out, turn = np.zeros(len(idx)), np.zeros(len(idx))
    for i in range(len(idx)):
        prev = va + vb
        va *= 1 + a[i]
        vb *= 1 + b[i]
        tot = va + vb
        if i > 0 and years[i] != years[i - 1]:
            t = (abs(va - w * tot) + abs(vb - (1 - w) * tot)) / tot
            tot *= 1 - t * bps / 10000.0
            va, vb = w * tot, (1 - w) * tot
            turn[i] = t
        out[i] = tot / prev - 1
    return pd.Series(out, index=idx), pd.Series(turn, index=idx)


def _ok(x) -> bool:
    return isinstance(x, (int, float)) and x is not None and math.isfinite(x)


def window(s: pd.Series, a: str, b: Optional[str]) -> pd.Series:
    return s.loc[pd.Timestamp(a): (pd.Timestamp(b) if b else None)]


def per_year(s: pd.Series) -> float:
    y = lab.years_of(s)
    return y if y > 0 else float("nan")


def long_stage(data: dict) -> dict[str, Any]:
    rf, mkt = data["rf"], data["mkt"]
    sim = long_sleeve(data)
    a0 = SELECTION[0]
    rs, rm = sim["returns"].loc[pd.Timestamp(a0):], mkt.loc[pd.Timestamp(a0):]
    out: dict[str, Any] = {"market": {k: mv.market_stats(mkt, rf, a, b) for k, (a, b) in L_WINDOWS.items()}, "cells": {},
                           "sleeve": {}, "data_end": str(rf.index[-1].date())}
    for k, (a, b) in L_WINDOWS.items():
        s = mv.stats(sim, mkt, rf, a, b, with_capm=False)
        out["sleeve"][k] = {"cagr": s["cagr"], "mdd": s["mdd"], "avg_exposure": s["avg_exposure"],
                            "turnover_per_year": s["turnover_per_year"]}
    yearly = {}
    for w in WS:
        r, turn = blend(rs, rm, w)
        cell = {"windows": {}, "rebalance_turnover_per_year": {}}
        for k, (a, b) in L_WINDOWS.items():
            cell["windows"][k] = mv.stats({"returns": r}, mkt, rf, a, b)
            sw = window(turn, a, b)
            cell["rebalance_turnover_per_year"][k] = float(sw.sum() / per_year(sw)) if len(sw) > 1 else float("nan")
        cell["noop_vs_market"] = rp.noop_guard((window(r, *CONFIRMATION) - window(mkt, *CONFIRMATION)).tolist())
        out["cells"][wname(w)] = cell
        y = window(r, "2008-01-01", None)
        yearly[wname(w)] = {str(k): round(float(v), 4) for k, v in ((1 + y).groupby(y.index.year).prod() - 1).items()}
    ym = window(mkt, "2008-01-01", None)
    yearly["market"] = {str(k): round(float(v), 4) for k, v in ((1 + ym).groupby(ym.index.year).prod() - 1).items()}
    out["yearly_2008"] = yearly
    return out


# =================================================================================================
# 판정 (결과를 보기 전에 고정)
# =================================================================================================

def stability(st: dict, mk: dict) -> dict[str, Optional[bool]]:
    """A: MDD 가 시장보다 나쁘지 않음. B: 최악 252행 수익 ≥ 시장 최악 − 5%p."""
    return {"A_mdd": (st["mdd"] >= mk["mdd"] - EPS) if _ok(st.get("mdd")) and _ok(mk.get("mdd")) else None,
            "B_worst252": (st["worst_252"] >= mk["worst_252"] - ROLL_SLACK - EPS)
            if _ok(st.get("worst_252")) and _ok(mk.get("worst_252")) else None}


def select_w(sel_stats: dict[str, dict], sel_market: dict, ws=WS) -> Optional[str]:
    """SELECTION 에서 A·B 를 만족하는 칸 중 CAGR 최고, 동점이면 더 작은 w. 없으면 None. 확인·2008~ 값은 보지 않는다."""
    elig = [wname(w) for w in ws if all(v is True for v in stability(sel_stats[wname(w)], sel_market).values())
            and _ok(sel_stats[wname(w)]["cagr"])]
    if not elig:
        return None
    best = max(sel_stats[c]["cagr"] for c in elig)
    return sorted([c for c in elig if sel_stats[c]["cagr"] == best], key=lambda c: int(c[1:]))[0]


def confirmation_checks(conf: dict, conf_mkt: dict, halves: list[dict]) -> dict[str, Optional[bool]]:
    ch = {"cagr_margin": (conf["cagr"] >= conf_mkt["cagr"] + L_CAGR_MARGIN - EPS) if _ok(conf["cagr"]) and _ok(conf_mkt["cagr"]) else None}
    ch.update(stability(conf, conf_mkt))
    ch["both_halves"] = all(h["cagr"] > h["market_cagr"] for h in halves) if halves and all(
        _ok(h["cagr"]) and _ok(h["market_cagr"]) for h in halves) else None
    ch["alpha_t"] = (conf["alpha_t_nw6"] >= ALPHA_T_MIN - EPS) if _ok(conf.get("alpha_t_nw6")) else None
    return ch


def verdict_long(chosen: Optional[str], checks: Optional[dict], noop: Optional[str], observed_ir, power: dict) -> str:
    if chosen is None:
        return FAIL
    if noop:
        return NOT_EVALUABLE
    if checks and all(v is True for v in checks.values()):
        return PASS_L
    return rp.classify_fail(observed_ir, power)


def etf_checks(cand: dict, spy: dict, cand_halves: list[float], spy_halves: list[float], boot_low: Optional[float]) -> dict[str, Optional[bool]]:
    ch: dict[str, Optional[bool]] = {}
    ch["after_tax_margin"] = (cand["cagr_after_liq"] >= spy["cagr_after_liq"] + E_AFTER_TAX_MARGIN - EPS) \
        if _ok(cand.get("cagr_after_liq")) and _ok(spy.get("cagr_after_liq")) else None
    ch["both_halves"] = all(c > s for c, s in zip(cand_halves, spy_halves)) if cand_halves and len(cand_halves) == len(spy_halves) \
        and all(_ok(x) for x in cand_halves + spy_halves) else None
    ch["mdd_within_3pp"] = (cand["mdd"] - spy["mdd"] >= -E_MDD_TOL - EPS) if _ok(cand.get("mdd")) and _ok(spy.get("mdd")) else None
    ch["boot_low"] = (boot_low > E_BOOT_FLOOR) if _ok(boot_low) else None
    return ch


def verdict_etf(chosen: Optional[str], checks: Optional[dict], noop: Optional[str], observed_ir, power: dict) -> str:
    if chosen is None:
        return NOT_JUDGED
    if noop:
        return NOT_EVALUABLE
    if checks and all(v is True for v in checks.values()):
        return PASS_E
    return rp.classify_fail(observed_ir, power)


def overall_verdict(verdict_l: str, verdict_e: str) -> str:
    l, e = verdict_l == PASS_L, verdict_e == PASS_E
    return BOTH_PASS if l and e else LONGRUN_ONLY if l else ETF_ONLY if e else NEITHER


def block_bootstrap_diff(ra: np.ndarray, rb: np.ndarray, ppy: float, *, n_boot: int = N_BOOT, block: int = BLOCK_DAYS,
                         seed: int = BOOT_SEED) -> np.ndarray:
    """짝지은 일별 수익을 순환 이동 블록으로 재표집해 '연수익(A) − 연수익(B)' 분포(결정론, 시드 고정)."""
    ra, rb = np.asarray(ra, dtype=float), np.asarray(rb, dtype=float)
    n = len(ra)
    if n == 0 or len(rb) != n:
        raise ValueError("두 수익 계열의 길이가 같고 0 보다 커야 합니다")
    block = max(1, min(int(block), n))
    n_blocks = -(-n // block)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(n_boot, -1)[:, :n]

    def ann(r):
        return np.exp(np.log1p(r).sum(axis=-1) * (ppy / r.shape[-1])) - 1.0
    return ann(ra[idx]) - ann(rb[idx])


# =================================================================================================
# PART E — SC2VT20 소매(core/forward_tournament_v3.py 정의) + SPY, 한국 세후
# =================================================================================================

def synthetic_etf(seed: int = 5) -> dict:
    d = sc.synthetic_etf(seed)
    adj, close = d["adj"].copy(), d["close"].copy()
    idx = adj.index
    bil = 90 * (1 + pd.Series(0.00008, index=idx)).cumprod()
    start = idx[idx >= "2007-05-30"][0]
    adj["BIL"] = bil.where(idx >= start)
    close["BIL"] = (bil * 0.998).where(idx >= start)
    return {"close": close[ETF_TICKERS], "adj": adj[ETF_TICKERS], "fx": d["fx"], "source": "synthetic ETF (smoke)", "missing": []}


def load_etf_real() -> dict:
    from core.market_data import get_multiple_price_history

    h = get_multiple_price_history(ETF_TICKERS, start=ETF_DATA_START, end=None, interval="1d") or {}
    close, adj = {}, {}
    for t in ETF_TICKERS:
        df = h.get(t)
        if df is None or df.empty:
            continue
        for store, col in ((close, "Close"), (adj, "Adj Close" if "Adj Close" in df and df["Adj Close"].notna().any() else "Close")):
            s = df[col].dropna()
            s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
            store[t] = s[~s.index.duplicated(keep="last")]
    need = [SPY] + ETF_MENU[:9]
    if any(t not in adj for t in need):
        raise RuntimeError(f"필수 ETF 가격을 받지 못함: {[t for t in need if t not in adj]}")
    days = adj[SPY].index
    close, adj = pd.DataFrame(close).reindex(days), pd.DataFrame(adj).reindex(days)
    fx = tx.usdkrw_series()
    if fx.index.min() > pd.Timestamp("2000-01-31"):
        raise RuntimeError("원/달러 환율이 2000-01 이전부터 없음(FRED DEXKOUS 필요)")
    cols = [t for t in ETF_TICKERS if t in adj.columns]
    return {"close": close[cols], "adj": adj[cols], "fx": fx, "source": "yfinance (Close / Adj Close), USDKRW via tax_fx.usdkrw_series",
            "missing": sorted(set(ETF_TICKERS) - set(cols))}


def etf_prepare(inp: dict) -> dict:
    """신호용 가격은 상장 전 결측을 그대로 두고(후보 아님), 드문 결측만 3일까지 앞 값으로 채운다. 세금 계좌용은 앞쪽도 채운다(보유 전 비중 0)."""
    cols = [t for t in ETF_TICKERS if t in inp["adj"].columns]
    adj = inp["adj"][cols].ffill(limit=FILL_LIMIT)
    close = inp["close"][cols].ffill(limit=FILL_LIMIT)
    for t in ETF_TICKERS:
        if t not in adj.columns:
            adj[t] = np.nan
            close[t] = np.nan
    adj, close = adj[ETF_TICKERS], close[ETF_TICKERS]
    total = adj[[t for t in ETF_MENU + [SPY]]]
    return {"adj": adj, "close": close, "total": total, "rets": adj.pct_change(fill_method=None).fillna(0.0),
            "tax_adj": adj.bfill(), "tax_close": close.bfill(), "fx": inp["fx"]}


def sleeve_decisions(prep: dict) -> list[dict]:
    """월 첫 거래일마다 SC2VT20 의 결정 — ft3.sc2_target(상위 2·SPY 대체)과 ft3.vol_exposure(직전 126개 맞추지 않은 SC2 수익).
    맞추지 않은 SC2 수익은 ft3.sc2_unscaled_returns 로 전체 가격에서 한 번에 만든다(각 시점은 자기 앞 자료만 쓰므로 결정일마다 다시 만든 것과 같다)."""
    total = prep["total"]
    idx = total.index
    per = idx.to_period("M")
    unscaled = ft3.sc2_unscaled_returns(total)
    uidx, uvals = unscaled.index, unscaled.to_numpy()
    bil_ok = prep["adj"][BIL].notna().to_numpy()
    out = []
    for i in range(1, len(idx)):
        if per[i] == per[i - 1]:
            continue
        sc2 = ft3.sc2_target(total.iloc[: i + 1])
        n = int(uidx.searchsorted(idx[i]))          # idx[i] 보다 앞 날짜의 수익만(결정일 전 거래일까지)
        win = uvals[max(0, n - ft3.VT_WINDOW): n].tolist()
        expo, vol = ft3.vol_exposure(win)
        out.append({"i": i, "date": str(idx[i].date()), "weights": {k: float(v) for k, v in sc2["weights"].items()},
                    "picks": list(sc2["picks"]), "exposure": float(expo), "vol": None if vol is None else float(vol),
                    "n_window": len(win), "bil": bool(bil_ok[i])})
    return out


def build_etf_weights(prep: dict, decisions: list[dict], w: float, start: str, end: Optional[str]) -> tuple[pd.DataFrame, dict]:
    """tax_fx 용 목표 비중. 매월 첫 거래일에 소매 크기 안에서 SC2VT20 목표로 다시 맞추고, 1월(과 시작일)에만 SPY/소매를 (1−w)/w 로 되돌린다.
    그 사이 SPY 몫과 소매 몫은 (배당 포함) 가격대로 표류. 남는 몫은 BIL(상장 전이면 이자 없는 달러 현금). 매월 같은 선택도 다시 맞추도록 번갈아
    전체를 1e-8 줄여 '바뀐 날'로 표시한다(현금 1e-8, spy-champion-v1 과 같은 방법)."""
    adj_idx = prep["adj"].index
    rows = np.flatnonzero((adj_idx >= pd.Timestamp(start)) & ((adj_idx <= pd.Timestamp(end)) if end else True))
    s0, e0 = int(rows[0]), int(rows[-1])
    cols = ETF_TICKERS
    col = {t: j for j, t in enumerate(cols)}
    R = prep["rets"][cols].to_numpy()
    dec = {d["i"]: d for d in decisions}
    if s0 not in dec:
        raise ValueError(f"시작일 {adj_idx[s0].date()} 이 월 첫 거래일(결정일)이 아님")
    n = len(cols)
    spy_v, sl_v, sl_cash = np.zeros(n), np.zeros(n), 0.0
    W = np.zeros((e0 - s0 + 1, n))
    row, toggle, sleeve_turn = np.zeros(n), False, 0.0
    for i in range(s0, e0 + 1):
        if i > s0:
            g = 1.0 + R[i]
            tot = float((spy_v * g).sum() + (sl_v * g).sum() + sl_cash)
            spy_v, sl_v, sl_cash = spy_v * g / tot, sl_v * g / tot, sl_cash / tot
        if i in dec:
            d = dec[i]
            reset = (i == s0) or adj_idx[i].month == 1
            if reset:
                cap = w
                spy_v = np.zeros(n)
                spy_v[col[SPY]] = 1.0 - w
            else:
                cap = float(sl_v.sum() + sl_cash)
            new, new_cash = np.zeros(n), 0.0
            for t, v in d["weights"].items():
                new[col[t]] += cap * d["exposure"] * v
            rest = cap * (1.0 - d["exposure"])
            if rest > 0:
                if d["bil"]:
                    new[col[BIL]] += rest
                else:
                    new_cash = rest
            if i > s0:
                sleeve_turn += float(np.abs(new - sl_v).sum())
            sl_v, sl_cash = new, new_cash
            toggle = not toggle
            row = (spy_v + sl_v) * ((1 - 1e-8) if toggle else 1.0)
        W[i - s0] = row
    idx = adj_idx[s0: e0 + 1]
    years = (idx[-1] - idx[0]).days / 365.25
    return pd.DataFrame(W, index=idx, columns=cols), {"sleeve_turnover_per_year": sleeve_turn / years if years > 0 else float("nan"),
                                                       "years": years}


def etf_sim(prep: dict, weights: pd.DataFrame, initial: float) -> dict:
    cfg = tx.AccountConfig(initial_krw=initial)
    s = tx.simulate(weights, prep["tax_close"], prep["tax_adj"], prep["fx"], cfg)
    m = sc.etf_after_tax(s, initial)
    m["unpaid_tax_if_sold_now_krw"] = s["unpaid_tax_if_sold_now_krw"]
    m["fx_cost_krw"] = s["totals"]["fx_cost_krw"]
    m["final_after_liquidation_krw"] = s["final_after_liquidation_krw"]
    m["daily_returns"] = s["values_krw"].pct_change().dropna().to_numpy(dtype=float)
    return m


def etf_cell(prep: dict, decisions: list[dict], w: float, win: tuple[str, Optional[str]], initial: float) -> dict:
    a, b = win
    if w == 0:
        idx = prep["adj"].loc[pd.Timestamp(a): (pd.Timestamp(b) if b else None)].index
        wts, meta = tx.buy_and_hold_weights(idx, SPY), {"sleeve_turnover_per_year": 0.0}
    else:
        wts, meta = build_etf_weights(prep, decisions, w, a, b)
    out = etf_sim(prep, wts, initial)
    out["sleeve_turnover_per_year"] = meta["sleeve_turnover_per_year"]
    out["first"], out["last"] = str(wts.index[0].date()), str(wts.index[-1].date())
    return out


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
# 종합 판정
# =================================================================================================

def judge_long(L: dict, power: dict) -> dict[str, Any]:
    cells, mk = L["cells"], L["market"]
    sel = {c: cells[c]["windows"]["selection"] for c in cells}
    chosen = select_w(sel, mk["selection"])
    checks, halves, noop, ir = None, [], None, None
    if chosen is not None:
        conf = cells[chosen]["windows"]["confirmation"]
        for k in ("h1", "h2"):
            halves.append({"start": CONF_HALVES[k][0], "end": CONF_HALVES[k][1],
                           "cagr": cells[chosen]["windows"][k]["cagr"], "market_cagr": mk[k]["cagr"]})
        checks = confirmation_checks(conf, mk["confirmation"], halves)
        noop = cells[chosen]["noop_vs_market"]
        ir = conf.get("appraisal_ir")
    eligible = [c for c in cells if all(v is True for v in stability(sel[c], mk["selection"]).values())]
    return {"chosen": chosen, "eligible_on_selection": eligible, "checks": checks, "halves": halves, "noop": noop,
            "observed_ir": ir, "verdict": verdict_long(chosen, checks, noop, ir, power)}


def judge_etf(chosen: Optional[str], sims: dict, power: dict) -> dict[str, Any]:
    if chosen is None:
        return {"chosen": None, "verdict": NOT_JUDGED, "checks": None}
    c, s = sims[f"{chosen}|judged"], sims["w0|judged"]
    ra, rb = c["daily_returns"], s["daily_returns"]
    n = min(len(ra), len(rb))
    ra, rb = ra[-n:], rb[-n:]
    years = (pd.Timestamp(c["last"]) - pd.Timestamp(c["first"])).days / 365.25
    ppy = n / years
    boot = block_bootstrap_diff(ra, rb, ppy)
    lo, hi = np.percentile(boot, (5.0, 95.0))
    d = ra - rb
    sd = float(np.std(d, ddof=1)) if n > 1 else float("nan")
    ir = float(np.mean(d) / sd * math.sqrt(ppy)) if sd and math.isfinite(sd) and sd > 0 else float("nan")
    noop = rp.noop_guard(d.tolist())
    halves_c = [sims[f"{chosen}|h1"]["cagr_after_liq"], sims[f"{chosen}|h2"]["cagr_after_liq"]]
    halves_s = [sims["w0|h1"]["cagr_after_liq"], sims["w0|h2"]["cagr_after_liq"]]
    checks = etf_checks(c, s, halves_c, halves_s, float(lo))
    return {"chosen": chosen, "checks": checks, "halves_cand": halves_c, "halves_spy": halves_s,
            "boot": {"ci90_low": float(lo), "ci90_high": float(hi), "median": float(np.median(boot)),
                     "share_positive": float(np.mean(boot > 0)), "n_boot": N_BOOT, "block_days": BLOCK_DAYS, "seed": BOOT_SEED},
            "observed_ir": ir, "noop": noop, "verdict": verdict_etf(chosen, checks, noop, ir, power)}


def smoke_coverage(L: dict, jl: dict, sims: dict, decisions: list[dict], je: dict, cells_e: list[str]) -> dict[str, bool]:
    return {
        "five_blends": len(L["cells"]) == len(WS),
        "windows": all(set(c["windows"]) == set(L_WINDOWS) for c in L["cells"].values()),
        "long_verdict": jl["verdict"] in (PASS_L, FAIL, "FAIL_UNDERPOWERED", NOT_EVALUABLE),
        "sc2vt_scales": any(d["exposure"] < 0.999 for d in decisions),
        "sc2vt_picks": any(len(d["picks"]) == 2 for d in decisions),
        "etf_all_sims": all(f"{c}|{k}" in sims for c in cells_e for k in ("judged", "h1", "h2", "post", "judged100m")),
        "tax_paid_somewhere": any(s["tax_paid_krw"] > 0 for s in sims.values()),
        "bootstrap": je["verdict"] == NOT_JUDGED or (je["boot"]["ci90_low"] <= je["boot"]["ci90_high"]),
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
    power_l = rp.power_report(POWER_YEARS_L, N_TRIALS)       # 결과를 보기 전에(구간·시도 수만)
    power_e = rp.power_report(POWER_YEARS_E, 1)
    steps = {"new": 0}
    wins = etf_windows(a.smoke)

    def log(s: str) -> None:
        print(s, flush=True)

    def check_time(margin: float = 90.0) -> None:
        if deadline is not None and time.time() > deadline - margin:
            raise _Stop()

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    def stage(name: str, fn):
        path = ck / f"{name}.pkl"
        got = _load_ckpt(path, fp)
        if got is None:
            if a.max_steps_per_run and steps["new"] >= a.max_steps_per_run:
                raise _Stop()
            check_time()
            got = fn()
            _atomic_pickle(path, {"fingerprint": fp, "payload": got})
            steps["new"] += 1
            log(f"단계 저장: {name}")
        return got

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        data = stage("french", lambda: synthetic_long() if a.smoke else load_real())
        L = stage("long", lambda: long_stage(data))
        jl = judge_long(L, power_l)
        einp = stage("etf_inputs", lambda: synthetic_etf() if a.smoke else load_etf_real())
        prep = etf_prepare(einp)
        decisions = stage("etf_decisions", lambda: sleeve_decisions(prep))
        sims: dict[str, dict] = {}
        cells_e = ["w0"] + [wname(w) for w in WS]
        for c in cells_e:
            w = 0.0 if c == "w0" else int(c[1:]) / 100
            for k in ("judged", "h1", "h2", "post"):
                sims[f"{c}|{k}"] = stage(f"etf_{c}_{k}", lambda w=w, k=k: etf_cell(prep, decisions, w, wins[k], TAX_INITIAL_KRW))
            sims[f"{c}|judged100m"] = stage(f"etf_{c}_judged100m",
                                            lambda w=w: etf_cell(prep, decisions, w, wins["judged"], TAX_INITIAL_KRW_BIG))
        je = judge_etf(jl["chosen"], sims, power_e)
        result = build_result(L, jl, sims, decisions, je, power_l, power_e, a.smoke, data["source"], einp, wins)
        if a.smoke:
            cov = smoke_coverage(L, jl, sims, decisions, je, cells_e)
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


def _r(x, nd=4):
    if isinstance(x, float):
        return round(x, nd) if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    return x


def build_result(L, jl, sims, decisions, je, power_l, power_e, smoke: bool, source: str, einp: dict, wins: dict) -> dict:
    vl, ve = jl["verdict"], je["verdict"]
    overall = overall_verdict(vl, ve)
    if smoke:
        vl, ve, overall = f"SMOKE_ONLY({vl})", f"SMOKE_ONLY({ve})", f"SMOKE_ONLY({overall})"
    verdicts = {"overall": overall, "part_L": vl, "part_E": ve, "chosen_w": jl["chosen"] or "NO_ELIGIBLE_CELL"}
    if jl["checks"]:
        verdicts["L_checks"] = ", ".join(f"{k}={'Y' if v else ('N' if v is False else '-')}" for k, v in jl["checks"].items())
    if je.get("checks"):
        verdicts["E_checks"] = ", ".join(f"{k}={'Y' if v else ('N' if v is False else '-')}" for k, v in je["checks"].items())
    esims = {k: {kk: vv for kk, vv in v.items() if kk != "daily_returns"} for k, v in sims.items()}
    recent = [{k: d[k] for k in ("date", "picks", "exposure", "vol")} for d in decisions[-3:]]
    return _r({"judge_version": RULES_VERSION, "smoke": smoke, "source": source,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "verdicts": verdicts, "power": {"part_L": power_l, "part_E": power_e},
               "rule": {"part_L": {"market": "Mkt-RF+RF", "sleeve": "mom-volscale-v1 I2/VT20/none (FF12 top-2 by 252-row return, vol target 20% on the sleeve's own prior 126 rows, cap 1.0, rest RF, monthly, 10bp)",
                                   "w": [int(w * 100) for w in WS], "rebalance": "first trading day of each January to target, one-way 10bp on turnover",
                                   "windows": L_WINDOWS, "n_trials": N_TRIALS},
                        "part_E": {"sleeve": "SC2VT20 as core/forward_tournament_v3.py (Select Sector SPDRs, top-2 by 252-day total return from prior close, equal weight, monthly, vol 20% on backfilled unscaled-SC2 prior 126 days, remainder BIL; USD cash before BIL exists)",
                                   "reset": "January only", "account": "tax_fx.AccountConfig defaults (Kakao), 30M KRW judged / 100M reported",
                                   "windows": wins, "bootstrap": [N_BOOT, BLOCK_DAYS, BOOT_SEED]}},
               "thresholds": {"L": {"cagr_margin": L_CAGR_MARGIN, "A": "mdd >= market mdd", "B_slack_252row": ROLL_SLACK, "alpha_t_min": ALPHA_T_MIN},
                              "E": {"after_tax_margin": E_AFTER_TAX_MARGIN, "mdd_tol": E_MDD_TOL, "boot_floor": E_BOOT_FLOOR}},
               "part_L": {"selection": {k: jl[k] for k in ("chosen", "eligible_on_selection", "checks", "halves", "noop", "observed_ir", "verdict")},
                          "market": L["market"], "sleeve_alone": L["sleeve"], "cells": L["cells"], "yearly_2008": L["yearly_2008"],
                          "data_end": L["data_end"]},
               "part_E": {"judge": je, "sims": esims, "recent_sleeve_decisions": recent, "source": einp["source"],
                          "missing": einp.get("missing", [])}})


# =================================================================================================
# 보고서
# =================================================================================================

def _p(x, signed=False, nd=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _f(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{nd}f}"


def _yn(v):
    return "—" if v is None else ("통과" if v else "미달")


def _wl(c: str) -> str:
    return f"시장 {100 - int(c[1:])}% + 소매 {int(c[1:])}%" if c != "w0" else "SPY 100%"


WIN_NAMES = {"selection": "선택 1927-07 ~ 1966", "confirmation": "확인 1967 ~ 2007", "h1": "확인 전반 1967 ~ 1986",
             "h2": "확인 후반 1987 ~ 2007", "recent": "2008 ~ (보고만)"}


def render(r: dict) -> str:
    v, pl, pe = r["verdicts"], r["part_L"], r["part_E"]
    smoke = r["smoke"]
    sel = pl["selection"]
    L = [f"# SPY + 섹터 모멘텀·변동성 맞춤 소매 섞기 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
         "산업 모멘텀에 변동성 맞춤(상위 2, 목표 변동성 20%, 나머지 현금)을 건 소매는 1967~2007 에서 가장 강했지만 2008 이후 뒤처졌다. "
         "시장(SPY)을 바탕으로 두고 이 소매를 w 만큼 섞으면(15·30·50·70·100%) 장기 우위가 남고 2008 이후 약점이 줄어드는지 본다.", "",
         f"**종합: {v['overall']}** · 장기(PART L) **{v['part_L']}** · ETF 세후(PART E) **{v['part_E']}** · 장기에서 고른 w: `{v['chosen_w']}`", "",
         "PASS 는 '전진 원장 v4 에 올릴 후보'일 뿐 채택이 아니다. 엔진(챔피언 전략)은 바뀌지 않았다.", "",
         "검정력(사전 계산) — " + rp.power_line(r["power"]["part_L"]) + " (PART L, 확인 41년·시도 5)", "",
         "검정력(사전 계산) — " + rp.power_line(r["power"]["part_E"]) + " (PART E, 24.7년·시도 1)", "",
         "## 판정 규칙 (결과를 보기 전에 고정)", "",
         "- PART L: 시장 × (1−w) + 산업 소매 × w, 매년 1월 재조정(편도 10bp 추가). 선택 구간에서 A(최대낙폭이 시장보다 나쁘지 않음)·"
         "B(최악 252거래일 ≥ 시장 최악 − 5%p)를 만족하는 w 중 연수익 최고(동점이면 작은 w). 확인 구간에서 연수익 ≥ 시장 + 1.0%p, A, B, "
         "1967~86·1987~2007 둘 다 시장보다 높음, CAPM 알파 NW(6) t ≥ 2.0 이면 PASS_LONGRUN.",
         "- PART E: 고른 w 의 SPY × (1−w) + SC2VT20 × w(1월에만 소매 크기 되돌림), 한국 세후(카카오 기본값, 3,000만 원). 2000-01-03 ~ 2024-09-30, "
         "절반 경계 2012-06-30. 세후 연수익 ≥ SPY + 0.5%p, 두 절반 모두 SPY 보다 높음, 원화 MDD 가 SPY 보다 3%p 넘게 나쁘지 않음, "
         "126거래일 블록 부트스트랩(1,000회, 시드 20261030) 90% 하한 > −0.5%p 이면 PASS_ETF.",
         "- 종합: BOTH_PASS / LONGRUN_ONLY / ETF_ONLY / NEITHER. 탈락은 classify_fail 로 FAIL / FAIL_UNDERPOWERED, 매일 같으면 NOT_EVALUABLE.", ""]
    # ---- PART L
    L += ["## PART L — 장기(세전)", ""]
    if sel["chosen"]:
        cs, mk = pl["cells"][sel["chosen"]]["windows"], pl["market"]
        ch = sel["checks"] or {}
        L += [f"선택 구간에서 A·B 를 만족한 w {len(sel['eligible_on_selection'])}개 중 `{sel['chosen']}` 가 골라졌다 → **{sel['verdict']}**.", "",
              "| 관문 (확인 구간) | 값 | 기준 | 결과 |", "|---|---|---|---|",
              f"| 연수익 | {_p(cs['confirmation']['cagr'])} | 시장 {_p(mk['confirmation']['cagr'])} + 1.0%p | {_yn(ch.get('cagr_margin'))} |",
              f"| A 최대 낙폭 | {_p(cs['confirmation']['mdd'])} | 시장 {_p(mk['confirmation']['mdd'])} | {_yn(ch.get('A_mdd'))} |",
              f"| B 최악 252일 | {_p(cs['confirmation']['worst_252'])} | 시장 {_p(mk['confirmation']['worst_252'])} − 5%p | {_yn(ch.get('B_worst252'))} |",
              "| 두 하위 구간 | " + " · ".join(f"{h['start'][:4]}~{h['end'][:4]} {_p(h['cagr'])}/{_p(h['market_cagr'])}" for h in sel["halves"])
              + f" | 둘 다 시장보다 높음 | {_yn(ch.get('both_halves'))} |",
              f"| CAPM 알파 t | {_f(cs['confirmation'].get('alpha_t_nw6'))} (알파 {_p(cs['confirmation'].get('alpha_annual'), True)}) | ≥ 2.0 | {_yn(ch.get('alpha_t'))} |", ""]
        if sel.get("noop"):
            L += [f"무효 실행 가드: {sel['noop']}", ""]
    else:
        L += ["선택 구간에서 A·B 를 모두 만족한 w 가 없다 → PART L FAIL(고른 w 없음), PART E 는 판정하지 않는다(보고만).", ""]
    for k, name in WIN_NAMES.items():
        L += [f"### {name}", "", "| 구성 | 연수익 | 최대낙폭 | 최악 252일 | 샤프 | 알파 / t | 소매 회전율(연) | 재조정 회전율(연) |", "|---|---|---|---|---|---|---|---|"]
        m = pl["market"][k]
        L.append(f"| 시장 100% (w=0) | {_p(m['cagr'])} | {_p(m['mdd'])} | {_p(m['worst_252'])} | {_f(m.get('sharpe'))} | — | 0% | 0% |")
        for c, x in pl["cells"].items():
            s = x["windows"][k]
            L.append(f"| {_wl(c)} | {_p(s['cagr'])} | {_p(s['mdd'])} | {_p(s['worst_252'])} | {_f(s.get('sharpe'))} | "
                     f"{_p(s.get('alpha_annual'), True)} / {_f(s.get('alpha_t_nw6'))} | "
                     f"{_p(pl['sleeve_alone'][k]['turnover_per_year'] * int(c[1:]) / 100, nd=0)} | "
                     f"{_p(x['rebalance_turnover_per_year'][k], nd=0)} |")
        L.append("")
    # ---- 2008+ 약점
    rc = {c: x["windows"]["recent"]["cagr"] for c, x in pl["cells"].items()}
    mc = pl["market"]["recent"]["cagr"]
    L += ["### 2008 이후 약점이 섞으면 어떻게 달라지나 (보고만)", "",
          "| 구성 | 2008~ 연수익 | 시장 대비 | w=100% 대비 | 시장과 w=100% 사이 격차 중 메운 몫 |", "|---|---|---|---|---|"]
    full = rc.get("w100")
    for c, cg in rc.items():
        gap = (mc - full) if _ok(mc) and _ok(full) else None
        closed = ((cg - full) / gap) if gap and gap > 0 and _ok(cg) and _ok(full) else None
        L.append(f"| {_wl(c)} | {_p(cg)} | {_p(cg - mc if _ok(cg) and _ok(mc) else None, True)}p | "
                 f"{_p(cg - full if _ok(cg) and _ok(full) else None, True)}p | {_p(closed, nd=0)} |")
    L += ["", "2008 이후 달력 연도별 수익:", "", "| 연도 | 시장 | " + " | ".join(f"w={c[1:]}%" for c in pl["cells"]) + " |", "|---|---|" + "---|" * len(pl["cells"])]
    for y in sorted(pl["yearly_2008"].get("market", {}), key=int):
        L.append(f"| {y} | {_p(pl['yearly_2008']['market'][y])} | " + " | ".join(_p(pl["yearly_2008"][c].get(y)) for c in pl["cells"]) + " |")
    # ---- PART E
    je = pe["judge"]
    L += ["", "## PART E — ETF 시대(한국 세후 원화)", "",
          "Select Sector SPDR(XLB XLE XLF XLI XLK XLP XLU XLV XLY, XLRE·XLC 는 252행이 쌓이면 추가) 중 직전 종가까지 252거래일 총수익 상위 2 균등·월 1회, "
          "소매 자신의 직전 126일(과거 가격으로 다시 만든 맞추지 않은 SC2) 변동성으로 목표 20%, 남는 몫은 BIL(상장 전 2007-05 이전은 이자 없는 달러 현금). "
          "SPY 와 소매는 1월에만 목표 크기로 되돌린다. 정의는 core/forward_tournament_v3.py SC2VT20 그대로.", ""]
    if pe.get("missing"):
        L += [f"받지 못한 가격: {', '.join(pe['missing'])}", ""]
    if je.get("chosen"):
        ch, bt = je["checks"] or {}, je["boot"]
        c, s = pe["sims"][f"{je['chosen']}|judged"], pe["sims"]["w0|judged"]
        L += [f"PART L 에서 고른 `{je['chosen']}` 를 판정한다 → **{je['verdict']}**.", "",
              "| 관문 | 값 | 기준 | 결과 |", "|---|---|---|---|",
              f"| 세후 연수익(청산 후) | {_p(c['cagr_after_liq'])} | SPY {_p(s['cagr_after_liq'])} + 0.5%p | {_yn(ch.get('after_tax_margin'))} |",
              f"| 전반 2000~2012-06 / 후반 2012-07~2024-09 | {_p(je['halves_cand'][0])} · {_p(je['halves_cand'][1])} | SPY {_p(je['halves_spy'][0])} · {_p(je['halves_spy'][1])} 보다 둘 다 높음 | {_yn(ch.get('both_halves'))} |",
              f"| 원화 MDD | {_p(c['mdd'])} | SPY {_p(s['mdd'])} (3%p 넘게 나쁘지 않음) | {_yn(ch.get('mdd_within_3pp'))} |",
              f"| 부트스트랩 90% 구간 | {_p(bt['ci90_low'], True, 2)}p ~ {_p(bt['ci90_high'], True, 2)}p | 하한 > −0.5%p | {_yn(ch.get('boot_low'))} |", ""]
        if je.get("noop"):
            L += [f"무효 실행 가드: {je['noop']}", ""]
    else:
        L += ["고른 w 가 없어 PART E 는 판정하지 않았다(아래 표는 보고만).", ""]
    L += ["### 모든 w (판정 대상 아님, 맥락)", "",
          "| 구성 | 세후 연수익 | 세전 | 원화 MDD | 낸 양도세 | 수수료 | 전반 | 후반 | 2024-10~ (보고만) | 1억 원 세후 | 소매 회전율(연) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in ["w0"] + [wname(w) for w in WS]:
        j, h1, h2 = pe["sims"][f"{c}|judged"], pe["sims"][f"{c}|h1"], pe["sims"][f"{c}|h2"]
        po, big = pe["sims"][f"{c}|post"], pe["sims"][f"{c}|judged100m"]
        star = " ◀ 고른 w" if c == je.get("chosen") else ""
        L.append(f"| {_wl(c)}{star} | {_p(j['cagr_after_liq'])} | {_p(j['cagr_pre'])} | {_p(j['mdd'])} | {j['tax_paid_krw'] / 10000:,.0f}만 원 | "
                 f"{j['fees_krw'] / 10000:,.0f}만 원 | {_p(h1['cagr_after_liq'])} | {_p(h2['cagr_after_liq'])} | {_p(po['cagr_after_liq'])} | "
                 f"{_p(big['cagr_after_liq'])} | {_p(j['sleeve_turnover_per_year'], nd=0)} |")
    L += ["", "세금: 청산 후 연수익 = 끝에 전부 판다고 보고 미납 양도세를 뺀 값. 절반(전반·후반)은 각각 3,000만 원으로 새로 시작해 끝에 청산하는 별도 계좌다. "
          "소매 회전율 = 소매 쪽 목표 변경의 Σ|Δ비중|(계좌 대비) 연평균.", ""]
    L += ["## 주의", "",
          "- 섹터 ETF 메뉴(미국 섹터 SPDR)는 미국 시장이 지난 25년 강했다는 사후 지식이 일부 섞인 선택이다. XLRE·XLC 는 신호가 생긴 뒤에만 들어간다.",
          "- French 산업 포트폴리오는 그대로 살 수 있는 상품이 아니다(PART L 은 세전·세금 없음). 판정 가능한 실제 상품 근거는 PART E 뿐이다.",
          "- 2008 이후와 2024-10 이후는 이미 여러 연구가 본 구간이라 보고만 한다.",
          "- BIL 상장(2007-05) 이전에는 소매의 남는 몫을 이자 없는 달러 현금으로 두었다 — 소매에 불리하게 근사한 것이다.",
          "- PASS 는 '전진 원장 v4 후보'까지만 뜻한다. 엔진은 바뀌지 않았다. 투자 조언이 아니다."]
    if smoke:
        L += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
