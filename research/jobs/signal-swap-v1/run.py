"""검증 signal-swap-v1 (2026-10-16 사전 등록): 코어·새틀라이트의 순위 신호를 바꾸면 세후 원화로 나아지나.

계기(사용자, 2026-10-16): leader-catch-v1(1927~2007 산업)에서 6개월 모멘텀과 12개월 상대강도는 견고했고 12-1개월 모멘텀은
그렇지 않았다. 라이브 코어는 252일 모멘텀 순위(> 0 자격), 새틀라이트는 추세 활성 종목을 252일 모멘텀으로 줄 세운다.

규칙 전체는 SPEC.md(한국어)에 고정. 판정을 바꾸려면 새 id. 엔진(core/*.py)은 바꾸지 않는다 — 변형은 이 파일 안에서 구현하고
라이브 함수와 같음을 테스트로 확인한다(K12 = champion_strategy._build_core_weights, S12 = S-SEED-000).
spy-champion-v1(슬리브 규약)·satellite-value-v1(입력·부트스트랩)·core-longrun-v1(장기 복제)을 import 해서 쓴다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import signal as _signal
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402


def _load(name: str, rel: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SC = _load("spy_champion_v1_for_signal_swap", "research/jobs/spy-champion-v1/run.py")
SV = SC.SV
LAB = _load("core_longrun_lab", "research/jobs/core-longrun-v1/lab.py")

JOB_ID = "signal-swap-v1"
RULES_VERSION = "signal-swap-v1/2026-10-16"
START = "2010-01-01"
SAT_WEIGHT = 0.15
CASH_ETF = "BIL"
MARKET = "SPY"
CORE_WARMUP_DAYS = 400   # champion_strategy.BACKTEST_WARMUP_DAYS 와 같음

WINDOWS = SC.WINDOWS      # judged 2010-01-04~2024-09-30, h1 ~2017-05-31, h2 2017-06-01~, post 2024-10-01~(보고만)
JUDGED_WINDOWS = ("judged", "h1", "h2")

# 코어 신호 변형: (순위·자격 기간(거래일 행), 자격 기준) — zero: 수익 > 0, spy: 수익 > 같은 기간 SPY 수익
CORE_VARIANTS = {"K12": (252, "zero"), "K6": (126, "zero"), "KRS": (252, "spy")}
# 새틀라이트 신호 변형: S-SEED-000 의 mom_window(추세 활성 판정·풀·보유는 그대로)
SAT_VARIANTS = {"S12": 252, "S6": 126}

# 칸: 맥락 A = 코어(변형) 85% + 새틀라이트(변형) 15%(라이브 방식), 맥락 B = SPY 85% + 새틀라이트 15%(1월만 슬리브 리셋)
CELLS = {"A_K12_S12": ("A", "K12", "S12"), "A_K6_S12": ("A", "K6", "S12"), "A_KRS_S12": ("A", "KRS", "S12"),
         "A_K12_S6": ("A", "K12", "S6"), "A_K6_S6": ("A", "K6", "S6"), "A_KRS_S6": ("A", "KRS", "S6"),
         "B_S12": ("B", None, "S12"), "B_S6": ("B", None, "S6")}
BASELINES = {"A": "A_K12_S12", "B": "B_S12"}
CANDIDATES = ("A_K6_S12", "A_KRS_S12", "A_K12_S6", "A_K6_S6", "A_KRS_S6", "B_S6")
N_TRIALS = 6
NAMES = {"A_K12_S12": "현 챔피언(K12·S12, 기준)", "A_K6_S12": "코어 6개월(K6)·새틀 12개월", "A_KRS_S12": "코어 상대강도(KRS)·새틀 12개월",
         "A_K12_S6": "코어 12개월·새틀 6개월(S6)", "A_K6_S6": "코어 6개월·새틀 6개월", "A_KRS_S6": "코어 상대강도·새틀 6개월",
         "B_S12": "SPY 85% + 새틀 12개월(기준)", "B_S6": "SPY 85% + 새틀 6개월"}
SETUPS = {"base_30m": {}, "base_100m": {"initial_krw": 100_000_000}}
DECISION_SETUP = "base_30m"

# 판정(사전 등록)
MDD_TOLERANCE = 0.02
CI_LOW_FLOOR = -0.005
N_BOOT = 1000
BLOCK_DAYS = 126
BOOT_SEED = 20261022
CI_PCT = (5.0, 95.0)
POWER_YEARS = 14.7
LONGRUN_T_MIN = 2.0
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


# =================================================================================================
# 신호 변형(순수 함수)
# =================================================================================================

def _first_of_month(index: pd.DatetimeIndex) -> np.ndarray:
    per = index.to_period("M")
    m = np.ones(len(index), dtype=bool)
    m[1:] = per[1:] != per[:-1]
    return m


def core_variant_weights(closes: pd.DataFrame, market_close: pd.Series, variant: str,
                         cash_ticker: Optional[str] = CASH_ETF) -> pd.DataFrame:
    """champion_strategy._build_core_weights(균등, 시장 필터, BIL 남는 몫)과 같은 규칙에서 순위 신호만 바꾼다.
    월 첫 거래일 d 에 d 전 거래일 종가(가격)로: lb 행 수익률 순위 상위 4, 자격 = 수익률 > 0(zero) 또는 > SPY 같은 기간 수익률(spy).
    SPY 수익률이 없으면(워밍업) spy 자격은 아무도 통과하지 못한다(전액 BIL)."""
    from core.champion_strategy import CORE_TOP_N, MARKET_FILTER_EXPOSURE_CUT, MARKET_FILTER_SMA_WINDOW

    lb, rule = CORE_VARIANTS[variant]
    cols = list(closes.columns)
    assets = [c for c in cols if c != cash_ticker]
    mom = closes[assets].pct_change(lb, fill_method=None)
    mkt_mom = market_close.pct_change(lb, fill_method=None)
    sma = market_close.rolling(MARKET_FILTER_SMA_WINDOW, min_periods=MARKET_FILTER_SMA_WINDOW).mean()
    firsts = _first_of_month(closes.index)
    out = np.zeros((len(closes.index), len(cols)))
    last = np.zeros(len(cols))
    for i in range(1, len(closes.index)):
        if firsts[i]:
            sd = closes.index[i - 1]
            m = mom.loc[sd]
            if rule == "zero":
                hurdle = 0.0
            else:
                h = mkt_mom.get(sd)
                hurdle = float(h) if h is not None and pd.notna(h) else math.inf
            elig = m[m > hurdle].sort_values(ascending=False)
            picks = list(elig.index[:CORE_TOP_N])
            row = np.array([1.0 / CORE_TOP_N if c in picks else 0.0 for c in cols])
            if sd in sma.index and pd.notna(sma.loc[sd]) and market_close.loc[sd] < sma.loc[sd]:
                row = row * MARKET_FILTER_EXPOSURE_CUT
            if cash_ticker is not None and cash_ticker in cols and pd.notna(closes.at[sd, cash_ticker]):
                row[cols.index(cash_ticker)] = max(0.0, 1.0 - float(row.sum()))
            last = row
        out[i] = last
    return pd.DataFrame(out, index=closes.index, columns=cols)


def sat_params(variant: str) -> dict:
    return {"mom_window": SAT_VARIANTS[variant]}


def sat_schedule(data, variant: str) -> list:
    """S-SEED-000 스펙·신호 그대로(champion40 풀), mom_window 만 변형값으로."""
    from core import satellite_lab as sl

    spec, signal, params = SV._incumbent()
    sp = json.loads(json.dumps(spec))
    sp["pool"] = {"type": "champion40"}
    p = dict(params)
    p.update(sat_params(variant))
    return SV.schedule_to_log(sl.run_variant(sp, p, signal, data)["schedule"])


def longrun_weights(rets: pd.DataFrame, mkt: pd.Series, variant: str) -> pd.DataFrame:
    """core-longrun-v1 lab.target_weights(동일가중 상위 4·200행 시장 필터·빈 몫 RF)와 같은 규칙에서 신호만 바꾼다.
    K6 = 126행 모멘텀(순위·자격 > 0), KRS = 252행 순위, 자격 = 시장(Mkt-RF+RF) 252행 수익보다 큼."""
    lb, rule = CORE_VARIANTS[variant]
    idx = rets.index
    mom = np.expm1(np.log1p(rets).rolling(lb, min_periods=lb).sum()).to_numpy()
    m_full = mkt.reindex(idx).fillna(0.0)
    mmom = np.expm1(np.log1p(m_full).rolling(lb, min_periods=lb).sum()).to_numpy()
    level = (1 + m_full).cumprod()
    sma = level.rolling(LAB.SMA_WINDOW, min_periods=LAB.SMA_WINDOW).mean().to_numpy()
    level = level.to_numpy()
    cols = list(rets.columns)
    firsts = LAB.month_first_mask(idx)
    out = np.zeros((len(idx), len(cols)))
    last = np.zeros(len(cols))
    for i in range(1, len(idx)):
        if firsts[i]:
            sd = i - 1
            m = mom[sd]
            hurdle = 0.0 if rule == "zero" else (mmom[sd] if np.isfinite(mmom[sd]) else math.inf)
            elig = [j for j in range(len(cols)) if np.isfinite(m[j]) and m[j] > hurdle]
            picks = sorted(elig, key=lambda j: (-m[j], cols[j]))[: LAB.TOP_N]
            row = np.zeros(len(cols))
            row[picks] = 1.0 / LAB.TOP_N
            if np.isfinite(sma[sd]) and level[sd] < sma[sd]:
                row = row * LAB.FILTER_CUT
            last = row
        out[i] = last
    return pd.DataFrame(out, index=idx, columns=cols)


def longrun_table(data: dict) -> dict:
    """FF12 산업(1927-07 ~ 2007-12, 편도 10bp)에서 세 코어 신호의 연수익·CAPM 알파."""
    rf, mkt, ind = data["rf"], data["mkt"], data["ind12"]
    out = {}
    for v in CORE_VARIANTS:
        w = longrun_weights(ind, mkt, v)
        s = LAB.strategy_returns(ind, rf, w, LAB.COST_BPS)
        sw = LAB.window(s, LAB.MAIN_START, LAB.MAIN_END)
        cp = LAB.capm(sw, mkt, rf)
        out[v] = {"cagr": LAB.cagr(sw), "mdd": LAB.mdd(sw), "alpha_annual": cp["alpha_annual"], "alpha_t_nw6": cp["alpha_t_nw6"],
                  "beta_daily": cp["beta_daily"], "sharpe_monthly": LAB.sharpe_monthly(sw, rf),
                  "avg_exposure": float(LAB.window(w.sum(axis=1), LAB.MAIN_START, LAB.MAIN_END).mean())}
    mw = LAB.window(mkt, LAB.MAIN_START, LAB.MAIN_END)
    out["market"] = {"cagr": LAB.cagr(mw), "mdd": LAB.mdd(mw)}
    out["source"] = data.get("source")
    return out


# =================================================================================================
# 판정(순수 함수)
# =================================================================================================

def _finite(*vals) -> bool:
    return all(v is not None and isinstance(v, (int, float)) and math.isfinite(float(v)) for v in vals)


def decide(d_judged, d_h1, d_h2, mdd_cand, mdd_base, ci_low, longrun: Optional[dict] = None,
           noop: Optional[str] = None) -> tuple[str, list]:
    """기준 칸 대비. longrun: 코어 신호를 바꾼 후보만 {"cagr", "cagr_k12", "alpha_t"}(없으면 장기 관문 없음)."""
    if noop:
        return NOT_EVALUABLE, ["noop"]
    if not _finite(d_judged, d_h1, d_h2, mdd_cand, mdd_base, ci_low):
        return NOT_EVALUABLE, ["non_finite"]
    if longrun is not None and not _finite(longrun.get("cagr"), longrun.get("cagr_k12"), longrun.get("alpha_t")):
        return NOT_EVALUABLE, ["longrun_non_finite"]
    miss = []
    if not d_judged > 0:
        miss.append("a_judged_diff_gt_0")
    if not (d_h1 > 0 and d_h2 > 0):
        miss.append("b_both_halves_gt_0")
    if not mdd_cand >= mdd_base - MDD_TOLERANCE:
        miss.append("c_mdd_not_worse_than_2pp")
    if not ci_low > CI_LOW_FLOOR:
        miss.append("d_boot_ci90_low_gt_minus_0.5pp")
    if longrun is not None:
        if not longrun["cagr"] >= longrun["cagr_k12"]:
            miss.append("e_longrun_cagr_ge_k12")
        if not longrun["alpha_t"] >= LONGRUN_T_MIN:
            miss.append("f_longrun_alpha_t_ge_2")
    return (PASS if not miss else FAIL), miss


def bootstrap_diff(ra: np.ndarray, rb: np.ndarray, ppy: float) -> np.ndarray:
    return SV.block_bootstrap_diff(ra, rb, ppy, n_boot=N_BOOT, block=BLOCK_DAYS, seed=BOOT_SEED)


def _pair(a: dict, b: dict, initial: float) -> dict:
    va, vb = a["values"], b["values"]
    ra, rb = SV.window_returns(va, initial, va.index[-1]), SV.window_returns(vb, initial, vb.index[-1])
    years = (va.index[-1] - va.index[0]).days / 365.25
    ppy = len(ra) / years
    d = (ra - rb).to_numpy()
    sd = float(np.std(d, ddof=1)) if len(d) > 1 else float("nan")
    ir = float(np.mean(d) / sd * math.sqrt(ppy)) if sd and math.isfinite(sd) and sd > 0 else float("nan")
    boot = bootstrap_diff(ra.to_numpy(), rb.to_numpy(), ppy)
    lo, hi = np.percentile(boot, CI_PCT)
    return {"daily_diff_ir": ir, "noop_reason": rp.noop_guard(d), "boot_ci90_low": float(lo), "boot_ci90_high": float(hi),
            "boot_median": float(np.median(boot)), "boot_share_positive": float(np.mean(boot > 0))}


# =================================================================================================
# 입력
# =================================================================================================

def _real_inputs(log) -> dict:
    from core import champion_strategy as cs
    from core import satellite_lab as sl
    from core.market_data import get_multiple_price_history

    log("코어 가격(신호 = 가격 Close)")
    tickers = list(cs.CORE_UNIVERSE) + [CASH_ETF]
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=CORE_WARMUP_DAYS)).date().isoformat()
    hist = get_multiple_price_history(tickers + [MARKET], start=fetch_start, end=None, interval="1d")
    closes_all = cs._closes_from_histories(hist, tickers + [MARKET])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    mkt = closes_all[MARKET]
    core_w = {}
    for v in CORE_VARIANTS:
        w = core_variant_weights(closes, mkt, v, CASH_ETF if CASH_ETF in closes.columns else None)
        core_w[v] = w.loc[w.index >= pd.Timestamp(START)]
    live = cs.run_core_backtest(START)["weights"]
    diff = float((core_w["K12"].reindex_like(live).fillna(0.0) - live).abs().to_numpy().max())
    if diff > 1e-9:
        raise RuntimeError(f"K12 가 라이브 코어 비중과 다름(최대 차이 {diff})")
    log("새틀라이트 풀·가격")
    pool = SV._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", pool_provider=pool, log=log)
    logs = {s: sat_schedule(data, s) for s in SAT_VARIANTS}
    picks = sorted({t for lg in logs.values() for r in lg for t in r["weights"]})
    others = sorted((set(closes.columns) | {MARKET}) - set(picks))
    h2 = get_multiple_price_history(others, start="2009-06-01", end=None, interval="1d")
    frames = {t: h2.get(t) for t in others}
    frames.update({t: data.ohlcv.get(t) for t in picks})
    close, adj = SV._panel(frames)
    return {"core_w": core_w, "logs": logs, "close": close, "adj": adj, "fx": tx.usdkrw_series(),
            "meta": {"k12_vs_live_max_abs_diff": diff, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
                     "judge_version": sl.JUDGE_VERSION, "pool_cache_tag": sl.POOL_CACHE_TAG,
                     "core_universe": list(closes.columns)}}


SMOKE_CORE = {"XLK": (0.0006, 0.012), "XLE": (0.0001, 0.018), "TLT": (0.0002, 0.009), "GLD": (0.0003, 0.010),
              "EFA": (0.0002, 0.012), "HYG": (0.0002, 0.005)}


def _smoke_core(days: pd.DatetimeIndex, spy_close: pd.Series, seed: int = 11) -> tuple[dict, pd.DataFrame]:
    """합성 코어 가격(체제가 1년마다 바뀌어 6·12개월 신호가 갈리게). 실데이터가 아니다."""
    rng = np.random.default_rng(seed)
    blocks = np.arange(len(days)) // 250
    frames = {}
    for t, (mu, sd) in SMOKE_CORE.items():
        regime = rng.normal(0, 0.0012, blocks.max() + 1)[blocks]
        c = 50 * np.exp(np.cumsum(mu + regime + rng.normal(0, sd, len(days))))
        frames[t] = pd.DataFrame({"Close": c, "Adj Close": c * np.exp(np.linspace(0, 0.2, len(days)))}, index=days)
    b = 80 * np.exp(np.cumsum(np.full(len(days), 0.00004)))
    frames[CASH_ETF] = pd.DataFrame({"Close": b, "Adj Close": b}, index=days)
    closes = pd.DataFrame({t: f["Close"] for t, f in frames.items()})
    return frames, closes


def _smoke_inputs(log) -> dict:
    """합성 데이터(네트워크 없음). 실데이터가 아니다."""
    from core import champion_strategy as cs
    from core import satellite_lab as sl

    end = "2026-06-30"
    pp, poolp = sl.synthetic_providers(n_tickers=50, start="2008-01-01", end=end, seed=7)
    pool = SV._pool_wrapper(poolp, date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", end=end, pool_provider=pool, price_provider=pp)
    logs = {s: sat_schedule(data, s) for s in SAT_VARIANTS}
    spy = pp("SPY", "2008-01-01", end)
    days = spy.index
    core_frames, closes = _smoke_core(days, spy["Close"])
    mkt = spy["Close"]
    core_w = {}
    for v in CORE_VARIANTS:
        w = core_variant_weights(closes, mkt, v)
        core_w[v] = w.loc[w.index >= pd.Timestamp(START)]
    live = cs._build_core_weights(closes, mkt, cash_ticker=CASH_ETF)
    diff = float((core_w["K12"] - live.loc[core_w["K12"].index]).abs().to_numpy().max())
    frames = {t: data.ohlcv[t] for lg in logs.values() for r in lg for t in r["weights"]}
    frames.update(core_frames)
    frames["SPY"] = spy
    close, adj = SV._panel(frames)
    rng = np.random.default_rng(5)
    fx = pd.Series(1100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(days)))), index=days)
    return {"core_w": core_w, "logs": logs, "close": close, "adj": adj, "fx": fx,
            "meta": {"k12_vs_live_max_abs_diff": diff, "synthetic": True}}


# =================================================================================================
# 비중·시뮬레이션
# =================================================================================================

def build_all_weights(inputs: dict) -> tuple[dict, dict]:
    base = tx.champion_weights(inputs["core_w"]["K12"], inputs["logs"]["S12"], SAT_WEIGHT)
    idx = base.index
    wins = SC.window_bounds(idx)
    inner = {s: SC.inner_frame_from_log(idx, inputs["logs"][s]) for s in SAT_VARIANTS}
    full = {}
    for c, (ctx, k, s) in CELLS.items():
        if ctx == "A":
            full[c] = tx.champion_weights(inputs["core_w"][k], inputs["logs"][s], SAT_WEIGHT).reindex(idx).fillna(0.0)
    W = {}
    for win, (t0, t1) in wins.items():
        sub = idx[(idx >= t0) & (idx <= t1)]
        for c, (ctx, k, s) in CELLS.items():
            if ctx == "A":
                W[(c, win)] = full[c].loc[sub]
            else:
                W[(c, win)] = SC.candidate_weights("P1", sub, inputs["core_w"]["K12"], inner[s], inputs["adj"])[0]
    for key in list(W):
        w = W[key]
        W[key] = w.loc[:, w.abs().sum() > 0]
    return W, wins


def sim_jobs(wins: dict) -> list:
    jobs = [(c, win, DECISION_SETUP) for win in wins for c in CELLS]
    if "judged" in wins:
        jobs += [(c, "judged", "base_100m") for c in CELLS]
    return jobs


# =================================================================================================
# 분석·보고
# =================================================================================================

def analyze(sims: dict, inputs: dict, wins: dict, lr: dict, smoke: bool) -> dict:
    initial = tx.AccountConfig(**SETUPS[DECISION_SETUP]).initial_krw
    metrics = {}
    for (c, win, setup), s in sims.items():
        metrics.setdefault(setup, {}).setdefault(c, {})[win] = {k: v for k, v in s.items() if k != "values"}
    m = metrics[DECISION_SETUP]
    power = rp.power_report(POWER_YEARS, N_TRIALS)
    verdicts, details = {}, {}
    for c in CANDIDATES:
        ctx, k, _ = CELLS[c]
        b = BASELINES[ctx]
        d = {w: m[c][w]["cagr_after_liq"] - m[b][w]["cagr_after_liq"] for w in JUDGED_WINDOWS}
        pr = _pair(sims[(c, "judged", DECISION_SETUP)], sims[(b, "judged", DECISION_SETUP)], initial)
        lrg = None
        if k is not None and k != "K12":
            lrg = {"cagr": lr[k]["cagr"], "cagr_k12": lr["K12"]["cagr"], "alpha_t": lr[k]["alpha_t_nw6"]}
        v, miss = decide(d["judged"], d["h1"], d["h2"], m[c]["judged"]["mdd_after"], m[b]["judged"]["mdd_after"],
                         pr["boot_ci90_low"], lrg, pr["noop_reason"])
        verdicts[c] = f"SMOKE_ONLY({v})" if smoke else v
        details[c] = {"baseline": b, "verdict_raw": v, "failed_conditions": miss, "diff": d, "pair": pr, "longrun_gate": lrg,
                      "mdd_diff": m[c]["judged"]["mdd_after"] - m[b]["judged"]["mdd_after"],
                      "power_class": rp.classify_fail(pr["daily_diff_ir"], power) if v == FAIL else None}
    post = {c: m[c]["post"]["cagr_after_liq"] for c in CELLS if "post" in m[c]}
    used = sorted({t for lg in inputs["logs"].values() for r in lg for t in r["weights"]}
                  | {t for w in inputs["core_w"].values() for t in w.columns} | {MARKET})
    missing = sorted(t for t in used if t not in inputs["close"].columns or inputs["close"][t].dropna().empty)
    same = {}
    for s in SAT_VARIANTS:
        same[s] = [{"date": r["date"], "picks": sorted(r["weights"])} for r in inputs["logs"][s]]
    overlap = [len(set(a["picks"]) & set(b["picks"])) / max(len(a["picks"]), 1) for a, b in zip(same["S12"], same["S6"])]
    core_diff = {k: float((inputs["core_w"][k].reindex_like(inputs["core_w"]["K12"]).fillna(0.0) - inputs["core_w"]["K12"])
                          .abs().sum(axis=1).gt(1e-9).mean()) for k in CORE_VARIANTS}
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windows": {k: [str(a.date()), str(b.date())] for k, (a, b) in wins.items()},
        "rules": {"core_variants": {k: {"lookback_rows": lb, "eligibility": e} for k, (lb, e) in CORE_VARIANTS.items()},
                  "sat_variants": {k: {"mom_window": v} for k, v in SAT_VARIANTS.items()},
                  "cells": {c: list(v) for c, v in CELLS.items()}, "baselines": BASELINES, "candidates": list(CANDIDATES),
                  "n_trials": N_TRIALS, "mdd_tolerance": MDD_TOLERANCE, "ci_low_floor": CI_LOW_FLOOR, "n_boot": N_BOOT,
                  "block_days": BLOCK_DAYS, "boot_seed": BOOT_SEED, "longrun_t_min": LONGRUN_T_MIN,
                  "metric": "세후 원화, 끝날 청산 시 낼 세금 반영 연복리(3,000만 원)", "post_2024_10": "report only"},
        "names": NAMES, "metrics": metrics, "details": details, "post_2024_10": post, "longrun": lr,
        "power": power, "power_line": rp.power_line(power), "verdicts": verdicts,
        "inputs_meta": inputs.get("meta", {}), "missing_prices": missing,
        "satellite_schedules": same, "sat_pick_overlap_mean": float(np.mean(overlap)) if overlap else None,
        "core_days_differ_from_k12": core_diff,
    }
    return result


def _pct(x) -> str:
    return f"{x:.2%}" if isinstance(x, (int, float)) and math.isfinite(x) else "—"


def _pp(x) -> str:
    return f"{x * 100:+.2f}%p" if isinstance(x, (int, float)) and math.isfinite(x) else "—"


def _num(x, nd=2) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) and math.isfinite(x) else "—"


def report(r: dict) -> str:
    m = r["metrics"][DECISION_SETUP]
    w = r["windows"]
    L = [f"# 순위 신호 바꾸기(6개월·상대강도) — 세후 원화 판정{' (스모크 — 합성 데이터)' if r['smoke'] else ''}", "",
         f"판정 구간 {w['judged'][0]} ~ {w['judged'][1]} · 앞 절반 ~ {w['h1'][1]} · 뒤 절반 {w['h2'][0]} ~ "
         "(구간마다 새 계좌, 초기 3,000만 원, 카카오페이증권 가정, 세후 = 끝날 다 팔면 낼 세금까지 뺀 원화 연복리). "
         "2024-10 이후는 보고만.", "",
         "## 판정(같은 맥락의 기준 칸 대비)", "",
         "| 후보 | 판정 | 기준 대비(판정 구간) | 앞 절반 | 뒤 절반 | MDD 차이 | 부트스트랩 90% | 장기(1927~2007) 관문 | 미충족 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for c in CANDIDATES:
        d = r["details"][c]
        g = d["longrun_gate"]
        gl = "해당 없음(코어 그대로)" if g is None else f"연 {_pct(g['cagr'])} vs K12 {_pct(g['cagr_k12'])}, 알파 t {_num(g['alpha_t'])}"
        L.append(f"| {c} {NAMES[c]} | **{r['verdicts'][c]}** | {_pp(d['diff']['judged'])} | {_pp(d['diff']['h1'])} | {_pp(d['diff']['h2'])} | "
                 f"{_pp(d['mdd_diff'])} | {_pp(d['pair']['boot_ci90_low'])} ~ {_pp(d['pair']['boot_ci90_high'])} | {gl} | "
                 f"{', '.join(d['failed_conditions']) or '없음'}" + (f" ({d['power_class']})" if d["power_class"] else "") + " |")
    L += ["", "통과(PASS_FORWARD_CANDIDATE) = 모두 만족: (a) 판정 구간 세후 차이 > 0 (b) 두 절반 모두 > 0 (c) 원화 MDD 가 기준보다 2%p 넘게 "
          "나쁘지 않음 (d) 126일 블록 부트스트랩 1,000회(시드 20261022) 연수익 차이 90% 하한 > −0.5%p (e·f) 코어 신호를 바꾼 후보만: "
          "FF12 산업 장기 복제(1927-07~2007-12)에서 연수익 ≥ K12 복제, CAPM 알파 t ≥ 2.0. 시도 수 6.", "",
          f"- {r['power_line']}",
          "- 무효 실행 가드: " + ", ".join(f"{c} {r['details'][c]['pair']['noop_reason'] or '통과'}" for c in CANDIDATES),
          "", "## 모든 칸(3,000만 원)", "",
          "| 칸 | 세후(판정) | 세전 | 원화 MDD | 앞 절반 | 뒤 절반 | 2024-10~(보고) | 양도세(백만) | 수수료(백만) | 회전율/년 | 1억 원 세후 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    m1 = r["metrics"].get("base_100m", {})
    for c in CELLS:
        j = m[c]["judged"]
        L.append(f"| {c} {NAMES[c]} | {_pct(j['cagr_after_liq'])} | {_pct(j['cagr_pre'])} | {_pct(j['mdd_after'])} | "
                 f"{_pct(m[c]['h1']['cagr_after_liq'])} | {_pct(m[c]['h2']['cagr_after_liq'])} | {_pct(r['post_2024_10'].get(c))} | "
                 f"{j['totals']['capital_gains_tax_krw'] / 1e6:.1f} | {j['totals']['fees_krw'] / 1e6:.1f} | {_num(j['turnover'])} | "
                 f"{_pct(m1.get(c, {}).get('judged', {}).get('cagr_after_liq'))} |")
    lr = r["longrun"]
    L += ["", "## 장기 복제(FF 12 산업, 1927-07 ~ 2007-12, 편도 10bp, 세전)", "",
          "| 신호 | 연수익 | 최대낙폭 | 연 알파 | 알파 t(NW6) | 베타 | 평균 주식 비중 |", "|---|---|---|---|---|---|---|"]
    for k in CORE_VARIANTS:
        x = lr[k]
        L.append(f"| {k} | {_pct(x['cagr'])} | {_pct(x['mdd'])} | {_pp(x['alpha_annual'])} | {_num(x['alpha_t_nw6'])} | "
                 f"{_num(x['beta_daily'])} | {_pct(x['avg_exposure'])} |")
    L.append(f"| 시장 | {_pct(lr['market']['cagr'])} | {_pct(lr['market']['mdd'])} | | | | |")
    ov = r.get("sat_pick_overlap_mean")
    L += ["", f"새틀라이트 S12·S6 같은 선정일 종목 겹침 평균: {_pct(ov)}. 코어 변형이 K12 와 비중이 다른 날 비율: "
          + ", ".join(f"{k} {_pct(v)}" for k, v in r["core_days_differ_from_k12"].items()) + ".", "",
          "## 규약", "",
          "- K12 = 라이브 코어(가격 기준 252거래일 수익 순위 상위 4, 수익 > 0 만 자격, SPY 200일선 아래면 ×0.5, 남는 몫 BIL, 월 첫 거래일). "
          "K6 = 126거래일 수익으로 순위·자격(> 0). KRS = 252거래일 순위, 자격은 같은 기간 SPY 수익보다 높은 자산만(빈 슬롯 BIL).",
          "- 'SPY 대비 수익'으로 줄 세우는 것은 같은 날 모든 자산에서 같은 값을 빼는 것이라 순위가 원래 수익 순위와 같다. "
          "그래서 KRS 는 자격 기준만 다르다(> 0 대신 > SPY).",
          "- S12 = S-SEED-000(champion40 풀, 돈치안 20일 추세 활성, 252일 모멘텀 상위 3, 균등, 1·7월). S6 = 같은 규칙에서 순위만 126일 모멘텀.",
          "- 맥락 A = 코어 85% + 새틀라이트 15%(코어 신호가 바뀌는 날마다 전체를 85/15 — 라이브 방식). "
          "맥락 B = SPY 85% + 새틀라이트 15%(spy-champion-v1 P1: 1월 첫 거래일만 슬리브 리셋).",
          f"- 가격 없는 보유 종목: {', '.join(r['missing_prices']) or '없음'}. K12 와 라이브 코어 비중 최대 차이: "
          f"{r['inputs_meta'].get('k12_vs_live_max_abs_diff')}.", "",
          "## 한계(꼭 읽기)", "",
          "- 앞선 코어 변형 연구(core-rnd-v1/v2 의 C03 여러 기간 모멘텀 혼합 등)는 통과하지 못했다. 이번 변형도 같은 계열이다.",
          "- 2010~2024 ETF·새틀라이트 자료는 이미 여러 연구가 본 자료다. PASS 는 '전진 원장에 올릴 후보'까지만 뜻한다.",
          "- 새틀라이트 생존편향: 상장폐지 종목이 가격 소스에 없어 후보에서 빠진다. 새틀라이트 변형 비교에도 이 편향이 남는다.",
          "- 장기 복제는 주식 산업 12개로 ETF 16개(채권·금·해외 포함)와 다르다 — 메커니즘만 본다. 세전·비용 단순화.",
          "- 일봉 종가 체결, 금융소득 종합과세 미반영. 과거 결과이며 앞으로의 수익을 뜻하지 않는다. 엔진은 바뀌지 않았다 — 반영은 사용자 확인 뒤 별도 작업."]
    return "\n".join(L) + "\n"


def smoke_coverage(r: dict) -> dict:
    m = r["metrics"][DECISION_SETUP]
    lr = r["longrun"]
    return {
        "all_candidates_judged": len(r["verdicts"]) == len(CANDIDATES),
        "k12_equals_live": (r["inputs_meta"].get("k12_vs_live_max_abs_diff") or 0.0) <= 1e-12,
        "core_variants_differ": all(r["core_days_differ_from_k12"][k] > 0 for k in ("K6", "KRS")),
        "sat_variants_differ": r["sat_pick_overlap_mean"] is not None and r["sat_pick_overlap_mean"] < 1.0,
        "tax_engine": any(m[c]["judged"]["totals"]["capital_gains_tax_krw"] > 0 for c in CELLS),
        "longrun_path": all(_finite(lr[k]["cagr"], lr[k]["alpha_t_nw6"]) for k in CORE_VARIANTS),
        "longrun_gate_applied": all((r["details"][c]["longrun_gate"] is not None) == (CELLS[c][1] in ("K6", "KRS")) for c in CANDIDATES),
        "halves_and_post": all(w in r["windows"] for w in ("judged", "h1", "h2", "post")),
    }


# =================================================================================================
# 실행
# =================================================================================================

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-sims-per-run", type=int, default=0, help="재개 확인용: 이번 실행에서 새로 할 시뮬레이션 수 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None

    def log(s: str) -> None:
        print(s, flush=True)

    def check_time(margin: float = 90.0) -> None:
        if deadline is not None and time.time() > deadline - margin:
            raise _Stop()

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        lr = SV._load_ckpt(ck / "longrun.pkl", fp)
        if lr is None:
            check_time()
            log("장기 복제(FF12, 1927~2007)")
            lr = longrun_table(LAB.synthetic_data() if a.smoke else LAB.load_real())
            SV._atomic_pickle(ck / "longrun.pkl", {"fingerprint": fp, "payload": lr})
        inputs = SV._load_ckpt(ck / "inputs.pkl", fp)
        if inputs is None:
            check_time()
            inputs = _smoke_inputs(log) if a.smoke else _real_inputs(log)
            SV._atomic_pickle(ck / "inputs.pkl", {"fingerprint": fp, "payload": inputs})
            log("입력 체크포인트 저장")
        W, wins = build_all_weights(inputs)
        sims, new = {}, 0
        for key in sim_jobs(wins):
            c, win, setup = key
            path = ck / f"sim_{c}_{win}_{setup}.pkl"
            got = SV._load_ckpt(path, fp)
            if got is None:
                if a.max_sims_per_run and new >= a.max_sims_per_run:
                    raise _Stop()
                check_time()
                cfg = tx.AccountConfig(**SETUPS[setup])
                w = W[(c, win)]
                s = tx.simulate(w, inputs["close"], inputs["adj"], inputs["fx"], cfg)
                got = SC._summ(s, w, inputs["adj"], cfg.initial_krw)
                SV._atomic_pickle(path, {"fingerprint": fp, "payload": got})
                new += 1
                log(f"시뮬레이션 {key} 세후(청산) {got['cagr_after_liq']:.4f}")
            sims[key] = got
        result = analyze(sims, inputs, wins, lr, a.smoke)
        if a.smoke:
            cov = smoke_coverage(result)
            result["smoke_coverage"] = cov
            bad = [k for k, v in cov.items() if not v]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
        rep = report(result)
    except _Stop:
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(rep, encoding="utf-8")
    log(json.dumps({"verdicts": result["verdicts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
