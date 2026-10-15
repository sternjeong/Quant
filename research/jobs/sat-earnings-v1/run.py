"""검증 sat-earnings-v1 (2026-10-15 사전 등록): 새틀라이트 '실적 발표 직전 매수 피하기'.

사용자 요청(2026-10-15): 새틀라이트는 3종목뿐이라 사자마자 실적 발표 갭이 반기를 좌우할 수 있다.
가설: 재선정일에 고른 종목의 실적 발표가 임박했으면 바로 사지 않는다(E1 미루기 / E2 다음 순위로 바꾸기).

규칙 전체는 SPEC.md(한국어)에 고정되어 있다. 판정 기준을 바꾸려면 새 id 로 다시 등록한다.
엔진(챔피언) 반영은 사용자 확인 뒤 별도 작업이다.
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "sat-earnings-v1"
RULES_VERSION = "sat-earnings-v1/2026-10-15"
START = "2010-01-01"
SAT_WEIGHT = 0.15
TOP_N = 3
DECISION_END = "2024-09-30"
HALF_SPLIT = "2017-05-31"
N_BOOT = 1000
BLOCK_DAYS = 126
BOOT_SEED = 20261021
CI_PCT = (5.0, 95.0)
CI_LOW_FLOOR = -0.005
MDD_TOL = 0.02
POWER_YEARS = 14.7
N_TRIALS = 2
CADENCE_DAYS = 91          # 분기 간격 근사(달력일)
IMMINENT_TD = 7            # d 다음 거래일(d+1)부터 7거래일 안
DELAY_TD_AFTER = 2         # E1: 예상일 뒤 두 번째 거래일 종가에 매수
TREND_LOOKAHEAD_TD = 12    # E1 매수일 추세 활성 여부를 미리 계산해 둘 거래일 수
ACC_TOL_TD = 3             # 진단: 예상일 정확도 ±3거래일
GAP_BAD = -0.05            # 진단: 3일 반응 −5% 보다 나쁨
EVENT_DAYS = 3
SAT_CASH = "BIL#SAT"       # E1 미루는 동안 그 자리 돈(가격은 BIL). 코어의 BIL 과 섞이지 않게 따로 둔 열
BIL = "BIL"
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"

VARIANTS = ("E0", "E1", "E2")
JUDGED = ("E1", "E2")
NAMES = {"E0": "현행 S-SEED-000(실적 일정 무시)",
         "E1": "임박 종목은 그 자리를 BIL 로 두고 예상일 뒤 2번째 거래일 종가에 매수",
         "E2": "임박 종목 대신 임박하지 않은 다음 순위 추세 활성 후보"}
SETUPS = {"base_30m": {}, "base_100m": {"initial_krw": 100_000_000}}


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def _load_mod(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass 가 모듈을 찾을 수 있게
    spec.loader.exec_module(mod)
    return mod


SV = _load_mod("satellite_value_v1_for_earnings", "research/jobs/satellite-value-v1/run.py")
SB = _load_mod("sat_buffer_v1_for_earnings", "research/jobs/sat-buffer-v1/run.py")
EL = _load_mod("sat_exit_ladder_v1_for_earnings", "research/jobs/sat-exit-ladder-v1/run.py")


# =================================================================================================
# 시점 기준 예상 실적일 (순수 함수 — tests/test_sat_earnings.py)
# =================================================================================================

def _ts(x) -> pd.Timestamp:
    return pd.Timestamp(x).normalize()


def expected_date(filings: list, d) -> Optional[pd.Timestamp]:
    """d 보다 엄격히 앞선 마지막 8-K 2.02 제출일 + 91일, d 보다 앞이면 d 이상이 될 때까지 91일씩 더한다. 이력 없으면 None."""
    d = _ts(d)
    past = [_ts(f) for f in filings if _ts(f) < d]
    if not past:
        return None
    e = max(past) + timedelta(days=CADENCE_DAYS)
    while e < d:
        e += timedelta(days=CADENCE_DAYS)
    return e


def window_end(trading_days: pd.DatetimeIndex, d) -> pd.Timestamp:
    """d 다음 7번째 거래일(달력이 모자라면 d + 7 영업일 근사)."""
    i = int(trading_days.searchsorted(_ts(d), side="right"))
    j = i + IMMINENT_TD - 1
    return trading_days[j] if j < len(trading_days) else _ts(d) + pd.offsets.BDay(IMMINENT_TD)


def is_imminent(filings: list, d, trading_days: pd.DatetimeIndex) -> tuple[bool, Optional[pd.Timestamp]]:
    """(임박, 예상일). 임박 = d < 예상일 ≤ d 다음 7번째 거래일(d+1 포함). 이력 없으면 임박 아님."""
    e = expected_date(filings, d)
    if e is None:
        return False, None
    return bool(_ts(d) < e <= window_end(trading_days, d)), e


def delay_buy_day(trading_days: pd.DatetimeIndex, exp: pd.Timestamp) -> pd.Timestamp:
    """E1 매수일 = 예상일 뒤(엄격히 이후) 두 번째 거래일."""
    j = int(trading_days.searchsorted(_ts(exp), side="right")) + DELAY_TD_AFTER - 1
    return trading_days[j] if j < len(trading_days) else _ts(exp) + pd.offsets.BDay(DELAY_TD_AFTER)


def select_e2(order: list[str], imminent: Callable[[str], bool], top_n: int = TOP_N) -> tuple[list[str], list[tuple]]:
    """E2: 상위 top_n 중 임박 종목을 (top_n 다음부터) 임박하지 않은 다음 순위 후보로 바꾼다. 없으면 원래 종목 유지.
    반환 (종목, [(원래, 대체 또는 None)])."""
    base = order[:top_n]
    used = set(base)
    out, swaps = [], []
    for t in base:
        if not imminent(t):
            out.append(t)
            continue
        rep = next((c for c in order[top_n:] if c not in used and not imminent(c)), None)
        if rep is None:
            out.append(t)
            swaps.append((t, None))
        else:
            used.add(rep)
            out.append(rep)
            swaps.append((t, rep))
    return out, swaps


def build_schedules(dates: list, pool_scores: dict, filings: dict, trading_days: pd.DatetimeIndex) -> dict:
    """{E0/E1/E2: [{date, picks, delayed{t: 매수일}, swaps}]} + 재선정별 임박 기록."""
    out = {v: [] for v in VARIANTS}
    imm_log = []
    for d in dates:
        d = _ts(d)
        order = SB.ranked(pool_scores[d])
        cache: dict = {}

        def imm(t):
            if t not in cache:
                cache[t] = is_imminent(filings.get(t, []), d, trading_days)
            return cache[t][0]
        e0 = order[:TOP_N]
        out["E0"].append({"date": d, "picks": list(e0), "delayed": {}, "swaps": []})
        delayed = {t: delay_buy_day(trading_days, cache[t][1]) for t in e0 if imm(t)}
        out["E1"].append({"date": d, "picks": list(e0), "delayed": delayed, "swaps": []})
        e2, swaps = select_e2(order, imm)
        out["E2"].append({"date": d, "picks": e2, "delayed": {}, "swaps": swaps})
        imm_log.append({"date": str(d.date()), "picks": list(e0), "imminent": [t for t in e0 if imm(t)],
                        "no_history": [t for t in e0 if not any(_ts(f) < d for f in filings.get(t, []))],
                        "expected": {t: (None if cache[t][1] is None else str(cache[t][1].date())) for t in e0}})
    return {"schedules": out, "imminent_log": imm_log}


# =================================================================================================
# 목표 비중
# =================================================================================================

def _log_rows(rows: list[dict]) -> list[dict]:
    """champion_weights 용 기록. E1 은 미룬 자리를 SAT_CASH 로, 매수일마다 기록을 하나 더 둔다."""
    lg = []
    for j, r in enumerate(rows):
        p = r["picks"]
        if not p:
            lg.append({"date": str(r["date"].date()), "weights": {}})
            continue
        per = 1.0 / len(p)
        nxt = rows[j + 1]["date"] if j + 1 < len(rows) else None
        w0: dict = {}
        for t in p:
            k = SAT_CASH if t in r["delayed"] else t
            w0[k] = w0.get(k, 0.0) + per
        lg.append({"date": str(r["date"].date()), "weights": w0})
        held = dict(w0)
        for b in sorted(set(r["delayed"].values())):
            if nxt is not None and b >= nxt:
                continue  # 다음 재선정 전에 사지 못한 자리는 없앤다(91일 규칙상 생기지 않음)
            for t, bt in r["delayed"].items():
                if bt == b:
                    held[SAT_CASH] -= per
                    held[t] = held.get(t, 0.0) + per
            held = {k: v for k, v in held.items() if v > 1e-12}
            lg.append({"date": str(b.date()), "weights": dict(held)})
    return lg


def variant_weights(core_w: pd.DataFrame, rows: list[dict], adj: pd.DataFrame, sw: float = SAT_WEIGHT) -> pd.DataFrame:
    """E0·E2 = tx.champion_weights 그대로(satellite-value-v1 과 같음). E1 은 매수일에만 그날까지 표류한 비중에서
    SAT_CASH 몫을 그 종목으로 옮긴다(다른 종목·코어는 매매하지 않음). 코어 변경일·재선정일은 기본 목표."""
    lg = _log_rows(rows)
    base = tx.champion_weights(core_w, lg, sw)
    buy_days = {b for r in rows for b in r["delayed"].values()}
    if not buy_days:
        return base
    idx = base.index
    cols = list(base.columns)
    ci = {c: i for i, c in enumerate(cols)}
    B = base.to_numpy()
    core_chg = core_w.reindex(idx).fillna(0.0).diff().abs().sum(axis=1).to_numpy() > 1e-12
    resel = {_ts(r["date"]) for r in rows}
    base_chg = np.r_[True, np.abs(np.diff(B, axis=0)).sum(axis=1) > 1e-12]
    pending = {}  # 매수일 -> [종목]
    for j, r in enumerate(rows):
        nxt = _ts(rows[j + 1]["date"]) if j + 1 < len(rows) else None
        for t, b in r["delayed"].items():
            if nxt is None or _ts(b) < nxt:
                pending.setdefault(_ts(b), []).append(t)
    a = adj.reindex(index=idx, columns=cols).ffill()
    tr = a.pct_change(fill_method=None).fillna(0.0).to_numpy()
    out = np.zeros_like(B)
    drift = None
    row = None
    cash_slots = 0
    for i, d in enumerate(idx):
        if drift is not None:
            g = drift * (1 + tr[i])
            port = g.sum() + (1 - drift.sum())
            drift = g / port if port > 0 else drift
        full = row is None or core_chg[i] or d in resel
        if d in resel:
            r = next(x for x in rows if _ts(x["date"]) == d)
            cash_slots = len(r["delayed"])
        swap = pending.get(d, []) if cash_slots else []
        if full or (base_chg[i] and not swap):
            row = B[i].copy()
            if swap:
                cash_slots -= len(swap)
        elif swap:
            row = drift.copy()
            amt = row[ci[SAT_CASH]] * (len(swap) / cash_slots) if cash_slots else 0.0
            row[ci[SAT_CASH]] -= amt
            for t in swap:
                row[ci[t]] += amt / len(swap)
            cash_slots -= len(swap)
        out[i] = row
        if full or swap or base_chg[i] or drift is None:
            drift = row.copy()
    return pd.DataFrame(out, index=idx, columns=cols)


# =================================================================================================
# 판정 (순수 함수)
# =================================================================================================

def decide(diff: float, h1: float, h2: float, sharpe_v: float, sharpe_0: float, mdd_v: float, mdd_0: float,
           ci_low: float, *, noop: Optional[str] = None, observed_ir: Optional[float] = None,
           power: Optional[dict] = None) -> str:
    """사전 등록 판정(챔피언 수준, 세후 원화). 차이는 소수(0.01 = 1%p), MDD 는 음수."""
    if noop:
        return NOT_EVALUABLE
    vals = (diff, h1, h2, sharpe_v, sharpe_0, mdd_v, mdd_0, ci_low)
    if any(v is None or not math.isfinite(float(v)) for v in vals):
        return NOT_EVALUABLE
    if diff > 0 and h1 > 0 and h2 > 0 and sharpe_v > sharpe_0 and mdd_v >= mdd_0 - MDD_TOL and ci_low > CI_LOW_FLOOR:
        return PASS
    return rp.classify_fail(observed_ir, power) if power else FAIL


def block_bootstrap_diff(ra, rb, ppy):
    return SV.block_bootstrap_diff(ra, rb, ppy, n_boot=N_BOOT, block=BLOCK_DAYS, seed=BOOT_SEED)


def pair_stats(va: pd.Series, vb: pd.Series, initial: float, *, with_boot: bool = True) -> dict:
    segs = SB.segments(va.index)
    out = {f"{k}_diff": SV.seg_ann(va, initial, t0, t1) - SV.seg_ann(vb, initial, t0, t1) for k, (t0, t1) in segs.items()}
    dec_end = segs["judged"][1]
    ra, rb = SV.window_returns(va, initial, dec_end), SV.window_returns(vb, initial, dec_end)
    years = (dec_end - va.index[0]).days / 365.25
    ppy = len(ra) / years if years > 0 else 252.0
    d = (ra - rb).to_numpy()
    sd = float(np.std(d, ddof=1)) if len(d) > 1 else float("nan")
    out["daily_diff_ir"] = float(np.mean(d) / sd * math.sqrt(ppy)) if sd and math.isfinite(sd) and sd > 0 else float("nan")
    out["noop_reason"] = rp.noop_guard(d)
    if with_boot and len(d) > 2:
        boot = block_bootstrap_diff(ra.to_numpy(), rb.to_numpy(), ppy)
        lo, hi = np.percentile(boot, CI_PCT)
        out.update({"boot_ci90_low": float(lo), "boot_ci90_high": float(hi), "boot_share_positive": float(np.mean(boot > 0))})
    return out


# =================================================================================================
# 진단 (보고만)
# =================================================================================================

def _tpos(days: pd.DatetimeIndex, x) -> int:
    return int(days.searchsorted(_ts(x), side="left"))


def accuracy_diag(dates: list, pool_scores: dict, filings: dict, days: pd.DatetimeIndex, top_k: int = 10) -> dict:
    """재선정일마다 상위 top_k 추세 활성 후보: 예상일 vs 실제 다음 8-K 2.02(≥ d) 의 거래일 차이."""
    errs, no_hist, no_next = [], 0, 0
    for d in dates:
        d = _ts(d)
        for t in SB.ranked(pool_scores[d])[:top_k]:
            fl = sorted(_ts(f) for f in filings.get(t, []))
            e = expected_date(fl, d)
            if e is None:
                no_hist += 1
                continue
            nxt = next((f for f in fl if f >= d), None)
            if nxt is None:
                no_next += 1
                continue
            errs.append(_tpos(days, nxt) - _tpos(days, e))
    a = np.array(errs, dtype=float)
    return {"n": int(len(a)), "share_within_3td": float(np.mean(np.abs(a) <= ACC_TOL_TD)) if len(a) else None,
            "median_err_td": float(np.median(a)) if len(a) else None,
            "mean_abs_err_td": float(np.mean(np.abs(a))) if len(a) else None, "n_no_history": no_hist, "n_no_next": no_next}


def coverage_by_year(dates: list, pools: dict, filings: dict) -> dict:
    """해마다: 그해 재선정 풀 종목 중 그해 8-K 2.02 제출이 하나라도 있는 비율."""
    by: dict = {}
    for d in dates:
        by.setdefault(_ts(d).year, set()).update(pools.get(_ts(d), []))
    out = {}
    for y, names in sorted(by.items()):
        has = sum(1 for t in names if any(_ts(f).year == y for f in filings.get(t, [])))
        out[str(y)] = {"n": len(names), "with_filing": has, "share": has / len(names) if names else None}
    return out


def event_study(rows: list[dict], filings: dict, adj: pd.DataFrame, days: pd.DatetimeIndex, end) -> dict:
    """E0 보유 구간 안의 실적 3일 반응(제출일 전 종가 → 제출일 포함 3번째 거래일 종가) vs 같은 종목 비실적 3일 창."""
    end = _ts(end)
    earn, other = [], []
    for j, r in enumerate(rows):
        d0 = _ts(r["date"])
        if d0 > end:
            break
        d1 = min(_ts(rows[j + 1]["date"]) if j + 1 < len(rows) else end, end)
        p0, p1 = _tpos(days, d0), _tpos(days, d1)
        for t in r["picks"]:
            if t not in adj.columns:
                continue
            px = adj[t].reindex(days).ffill().to_numpy()
            fl = [_ts(f) for f in filings.get(t, []) if d0 < _ts(f) <= d1]
            ev_pos = [_tpos(days, f) for f in fl]
            for q in ev_pos:
                if q - 1 >= p0 and q + EVENT_DAYS - 1 < min(p1 + 1, len(px)):
                    a, b = px[q - 1], px[q + EVENT_DAYS - 1]
                    if np.isfinite(a) and np.isfinite(b) and a > 0:
                        earn.append(b / a - 1)
            q = p0 + 1
            while q + EVENT_DAYS - 1 <= p1 and q + EVENT_DAYS - 1 < len(px):
                if all(abs(q - e) > 5 and abs(q + EVENT_DAYS - 1 - e) > 5 for e in ev_pos):
                    a, b = px[q - 1], px[q + EVENT_DAYS - 1]
                    if np.isfinite(a) and np.isfinite(b) and a > 0:
                        other.append(b / a - 1)
                q += EVENT_DAYS

    def s(x):
        x = np.array(x, dtype=float)
        return {"n": int(len(x)), "mean": float(np.mean(x)) if len(x) else None,
                "share_worse_than_-5pct": float(np.mean(x < GAP_BAD)) if len(x) else None,
                "p10": float(np.percentile(x, 10)) if len(x) else None}
    return {"earnings": s(earn), "non_earnings": s(other)}


def schedule_diag(sched: dict, imm_log: list, trend_after: dict, end) -> dict:
    end = _ts(end)
    rows = [x for x in imm_log if _ts(x["date"]) <= end]
    per = [len(x["imminent"]) for x in rows]
    e1 = [r for r in sched["E1"] if _ts(r["date"]) <= end]
    n_del, n_not_active, n_unknown = 0, 0, 0
    for r in e1:
        for t, b in r["delayed"].items():
            n_del += 1
            v = trend_after.get((str(_ts(r["date"]).date()), t), {}).get(str(_ts(b).date()))
            if v is None:
                n_unknown += 1
            elif not v:
                n_not_active += 1
    e2 = [r for r in sched["E2"] if _ts(r["date"]) <= end]
    return {"n_reselections": len(rows), "imminent_per_reselection": per, "n_imminent": int(sum(per)),
            "n_no_history_picks": int(sum(len(x["no_history"]) for x in rows)),
            "e1_delayed": n_del, "e1_buy_not_trend_active": n_not_active, "e1_buy_trend_unknown": n_unknown,
            "e2_replaced": int(sum(1 for r in e2 for _, rep in r["swaps"] if rep is not None)),
            "e2_kept_no_alternative": int(sum(1 for r in e2 for _, rep in r["swaps"] if rep is None))}


# =================================================================================================
# 입력
# =================================================================================================

def score_inputs(data) -> dict:
    """S-SEED-000 과 같은 순서·창: 1·7월 재선정일의 추세 활성 후보 점수, 풀 구성, 상위 3 의 이후 거래일 추세 활성 여부."""
    from core import satellite_lab as sl

    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    signal = sl.load_signal(code)
    params = dict(spec["signal"]["params_grid"][0])
    days = data.trading_days

    def score_at(members, d):
        cutoff = sl._prev_day(days, d)
        if cutoff is None:
            return {}
        prices = sl._signal_prices(data, members, cutoff, d)
        eligible = {t for t in prices if t in data.closes.columns and pd.notna(data.closes.at[d, t])}
        sc = sl._call_signal(signal, spec, data, {t: prices[t] for t in eligible}, cutoff, params) or {}
        return {t: float(v) for t, v in sc.items() if t in eligible and v is not None and math.isfinite(float(v))}

    dates, pool_scores, pools, trend_after = [], {}, {}, {}
    for d in sl.rebalance_dates(days, spec["portfolio"]["hold_months"]):
        if sl._prev_day(days, d) is None:
            continue
        members = data.pool(spec["pool"]["type"], d)
        pool_scores[d] = score_at(members, d)
        pools[d] = list(members)
        dates.append(d)
        i = int(days.searchsorted(d))
        for t in SB.ranked(pool_scores[d])[:TOP_N]:
            trend_after[(str(d.date()), t)] = {str(x.date()): bool(score_at([t], x))
                                              for x in days[i + 1:i + 1 + TREND_LOOKAHEAD_TD]}
    return {"dates": dates, "pool_scores": pool_scores, "pools": pools, "trend_after": trend_after}


def _stage1_real(log) -> dict:
    from core import champion_strategy as cs
    from core import satellite_lab as sl
    from core.market_data import get_multiple_price_history

    log("코어 백테스트(일별 목표 비중)")
    core_w = cs.run_core_backtest(START)["weights"]
    pool = SV._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", pool_provider=pool, log=log)
    sc = score_inputs(data)
    universe = sorted({t for m in sc["pools"].values() for t in m})
    others = sorted(set(core_w.columns) | {BIL})
    hist = get_multiple_price_history(others, start="2009-06-01", end=None, interval="1d")
    frames = {t: hist.get(t) for t in others}
    frames.update({t: data.ohlcv.get(t) for t in universe if t not in frames})
    close, adj = SV._panel(frames)
    meta = {"live_satellite_weight": cs.SATELLITE_WEIGHT, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
            "judge_version": sl.JUDGE_VERSION, "pool_cache_tag": sl.POOL_CACHE_TAG, "core_universe": list(core_w.columns)}
    return {**sc, "universe": universe, "trading_days": data.trading_days, "core_w": core_w, "close": close, "adj": adj,
            "fx": tx.usdkrw_series(), "meta": meta}


def _stage1_smoke(log) -> dict:
    """합성 데이터(네트워크 없음). 실데이터가 아니다."""
    from core import satellite_lab as sl

    end = "2026-06-30"
    pp, poolp = sl.synthetic_providers(n_tickers=50, start="2008-01-01", end=end, seed=11)
    pool = SV._pool_wrapper(poolp, date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", end=end, pool_provider=pool, price_provider=pp)
    sc = score_inputs(data)
    universe = sorted({t for m in sc["pools"].values() for t in m})
    full = pd.bdate_range("2008-01-01", end)
    rng = np.random.default_rng(5)
    idx = data.trading_days[data.trading_days >= pd.Timestamp(START)]
    frames = {}
    for t in ("C1", "C2"):
        c = 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, len(full))))
        frames[t] = pd.DataFrame({"Close": c, "Adj Close": c * np.exp(np.linspace(0, 0.3, len(full)))}, index=full)
    b = 91.5 + np.zeros(len(full))
    frames[BIL] = pd.DataFrame({"Close": b, "Adj Close": b * np.exp(np.linspace(0, 0.18, len(full)))}, index=full)
    frames.update({t: data.ohlcv.get(t) for t in universe})
    close, adj = SV._panel(frames)
    core_w = pd.DataFrame(0.0, index=idx, columns=["C1", "C2"])
    core_w.loc[core_w.index.month % 2 == 0, "C1"] = 1.0
    core_w.loc[core_w.index.month % 2 == 1, "C2"] = 1.0
    fx = pd.Series(1100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(full)))), index=full)
    return {**sc, "universe": universe, "trading_days": data.trading_days, "core_w": core_w, "close": close, "adj": adj,
            "fx": fx, "meta": {"synthetic": True}}


def synthetic_filings(universe: list[str]) -> dict:
    """스모크용 합성 8-K 2.02 날짜(분기 ± 흔들림, 일부는 이력 없음·2012년부터). 실데이터가 아니다."""
    rng = np.random.default_rng(17)
    out = {}
    for i, t in enumerate(sorted(universe)):
        if i % 10 == 9:
            out[t] = []
            continue
        d = pd.Timestamp("2008-01-15") + timedelta(days=(i * 13) % 91)
        start = pd.Timestamp("2012-01-01") if i % 7 == 3 else pd.Timestamp("2008-01-01")
        fl = []
        while d < pd.Timestamp("2026-07-01"):
            if d >= start:
                fl.append(str((d + timedelta(days=int(rng.integers(-6, 7)))).date()))
            d += timedelta(days=91)
        out[t] = fl
    return out


def fetch_filings(universe: list[str], deadline: Optional[float], log) -> tuple[dict, dict]:
    """SEC submissions 의 8-K Item 2.02 제출일(core.fundamentals_pit.Store — 기존 캐시 사용, 예의 있는 속도 제한).
    시간이 모자라면 (부분, {"complete": False}) — 받은 것은 캐시에 남아 다음 회차에 이어 받는다."""
    from core import fundamentals_pit as fp

    store = fp.Store(fetch=True)
    st = store.prefetch(universe, deadline=deadline, log=log)
    if not st["complete"]:
        return {}, st
    out, missing = {}, 0
    for t in universe:
        rec = store.ensure(t) or {}
        if rec.get("missing") or rec.get("submissions_error"):
            missing += 1
        out[t] = list(rec.get("earnings_dates") or [])
    st["n_missing_or_error"] = missing
    return out, st


def stage2(s1: dict, filings: dict) -> dict:
    built = build_schedules(s1["dates"], s1["pool_scores"], filings, s1["trading_days"])
    adj, close = s1["adj"].copy(), s1["close"].copy()
    if any(r["delayed"] for r in built["schedules"]["E1"]):
        adj[SAT_CASH], close[SAT_CASH] = adj[BIL], close[BIL]
    return {**built, "adj": adj, "close": close}


# =================================================================================================
# 분석·보고
# =================================================================================================

def _mdd(v: pd.Series) -> float:
    return float((v / v.cummax() - 1).min())


def sim_summary(s: dict, w: pd.DataFrame, adj: pd.DataFrame, initial: float, with_pre: bool) -> dict:
    vals = s["values_krw"]
    segs = SB.segments(vals.index)
    dec_end = segs["judged"][1]
    out = {"values": vals, "initial": initial, "cagr_judged": SV.seg_ann(vals, initial, None, dec_end),
           "mdd_judged": _mdd(vals.loc[:dec_end]), "cagr_post": SV.seg_ann(vals, initial, *segs["post"]) if "post" in segs else None,
           "final_judged_krw": float(vals.loc[dec_end]), "totals": s["totals"],
           "turnover_annual_judged": SB.annual_turnover(w, adj, dec_end)}
    if with_pre:
        r = EL.pretax_returns(w.loc[:dec_end], adj)
        bil_r = adj[BIL].pct_change(fill_method=None) if BIL in adj.columns else pd.Series(0.0, index=r.index)
        out["sharpe_pretax_excess"] = EL.sharpe_excess(r, bil_r)
    return out


def analyze(s1: dict, s2: dict, sims: dict, fetch_meta: dict, filings: dict, smoke: bool) -> tuple[dict, str]:
    power = rp.power_report(POWER_YEARS, N_TRIALS)
    dec_end = pd.Timestamp(DECISION_END)
    sd = schedule_diag(s2["schedules"], s2["imminent_log"], s1["trend_after"], dec_end)
    pairs, verdicts, raw = {}, {}, {}
    for setup in SETUPS:
        for name in JUDGED:
            pairs.setdefault(setup, {})[name] = pair_stats(sims[(name, setup)]["values"], sims[("E0", setup)]["values"],
                                                           sims[(name, setup)]["initial"], with_boot=setup == "base_30m")
    for name in JUDGED:
        c = pairs["base_30m"][name]
        sv, s0 = sims[(name, "base_30m")], sims[("E0", "base_30m")]
        noop = c["noop_reason"] or ("임박 사례 없음" if sd["n_imminent"] == 0 else None)
        v = decide(c["judged_diff"], c["h1_diff"], c["h2_diff"], sv["sharpe_pretax_excess"], s0["sharpe_pretax_excess"],
                   sv["mdd_judged"], s0["mdd_judged"], c.get("boot_ci90_low", float("nan")), noop=noop,
                   observed_ir=c["daily_diff_ir"], power=power)
        raw[name] = v
        verdicts[name] = f"SMOKE_ONLY({v})" if smoke else v
    metrics = {f"{n}|{st}": {k: v for k, v in s.items() if k not in ("values", "initial")} for (n, st), s in sims.items()}
    days = s1["trading_days"]
    v0 = sims[("E0", "base_30m")]["values"]
    segs = {k: [None if a is None else str(a.date()), str(b.date())] for k, (a, b) in SB.segments(v0.index).items()}
    sched_out = {n: [{"date": str(r["date"].date()), "picks": r["picks"],
                      "delayed": {t: str(b.date()) for t, b in r["delayed"].items()}, "swaps": r["swaps"]}
                     for r in s2["schedules"][n]] for n in VARIANTS}
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": str(v0.index[0].date()), "segments": segs, "verdicts": verdicts, "verdicts_raw": raw,
        "pairs": pairs, "metrics": metrics, "schedule_diag": sd, "schedules": sched_out,
        "imminent_log": s2["imminent_log"],
        "diag_accuracy": accuracy_diag(s1["dates"], s1["pool_scores"], filings, days),
        "diag_event_study": event_study(s2["schedules"]["E0"], filings, s2["adj"], days, dec_end),
        "coverage_by_year": coverage_by_year(s1["dates"], s1["pools"], filings),
        "filings_fetch": {k: v for k, v in fetch_meta.items() if k in ("done", "left", "complete", "n_missing_or_error")},
        "power": power, "power_line": rp.power_line(power), "variants": NAMES, "inputs_meta": s1.get("meta", {}),
        "rules": {"top_n": TOP_N, "sat_weight": SAT_WEIGHT, "n_boot": N_BOOT, "block_days": BLOCK_DAYS, "boot_seed": BOOT_SEED,
                  "ci_low_floor": CI_LOW_FLOOR, "mdd_tol": MDD_TOL, "decision_end": DECISION_END, "half_split": HALF_SPLIT,
                  "power_years": POWER_YEARS, "n_trials": N_TRIALS, "cadence_days": CADENCE_DAYS,
                  "imminent_trading_days": IMMINENT_TD, "delay_td_after": DELAY_TD_AFTER},
    }
    return result, report(result)


def _pct(x, nd=1) -> str:
    return "—" if x is None or not isinstance(x, (int, float)) or not math.isfinite(x) else f"{x * 100:.{nd}f}%"


def _pp(x) -> str:
    return "—" if x is None or not isinstance(x, (int, float)) or not math.isfinite(x) else f"{x * 100:+.2f}%p"


def _f(x, nd=2) -> str:
    return "—" if x is None or not isinstance(x, (int, float)) or not math.isfinite(x) else f"{x:.{nd}f}"


def report(r: dict) -> str:
    sm = " (스모크 — 합성 데이터, 실측 아님)" if r["smoke"] else ""
    sg, m, sd = r["segments"], r["metrics"], r["schedule_diag"]
    p30, p100 = r["pairs"]["base_30m"], r["pairs"]["base_100m"]
    L = [f"# 새틀라이트 '실적 발표 직전 매수 피하기'{sm}", "",
         "재선정일에 고른 종목의 다음 실적 발표 예상일(그 전 마지막 8-K Item 2.02 제출일 + 91일씩)이 다음 7거래일 안이면 '임박'으로 본다.",
         "E1 은 그 자리를 BIL 로 두었다가 예상일 뒤 2번째 거래일 종가에 사고, E2 는 임박하지 않은 다음 순위 추세 활성 후보로 바꾼다. "
         "기준선 E0 = 지금 규칙(S-SEED-000).", "",
         f"## 판정(챔피언 = 코어 85% + 새틀라이트 15%, 세후 원화 3,000만 원, {r['start']} ~ {sg['judged'][1]})", "",
         "| 변형 | 판정 | 세후 연수익 차이 | 앞/뒤 절반 | 세전 샤프(본/E0) | 부트스트랩 90% | 원화 MDD(본/E0) | 2024-10~ 차이(보고) | 1억 원 차이 |",
         "|---|---|---|---|---|---|---|---|---|"]
    e0 = m["E0|base_30m"]
    for n in JUDGED:
        c, mv = p30[n], m[f"{n}|base_30m"]
        L.append(f"| {n} {NAMES[n]} | **{r['verdicts'][n]}** | {_pp(c['judged_diff'])} | {_pp(c['h1_diff'])} / {_pp(c['h2_diff'])} | "
                 f"{_f(mv.get('sharpe_pretax_excess'))} / {_f(e0.get('sharpe_pretax_excess'))} | "
                 f"{_pp(c.get('boot_ci90_low'))} ~ {_pp(c.get('boot_ci90_high'))} | {_pct(mv['mdd_judged'])} / {_pct(e0['mdd_judged'])} | "
                 f"{_pp(c.get('post_diff'))} | {_pp(p100[n].get('judged_diff'))} |")
    L += ["", f"통과 조건(모두, E0 대비): 세후 연수익 차이 > 0, 앞 절반(~{sg['h1'][1]})·뒤 절반 모두 > 0, 세전 샤프(BIL 초과) 더 높음, "
          f"원화 MDD 가 {MDD_TOL:.0%}p 넘게 나빠지지 않음, 126일 블록 부트스트랩 1,000회(시드 {BOOT_SEED}) 90% 하한 > −0.5%p. "
          "임박 사례가 하나도 없으면 NOT_EVALUABLE.", f"- {r['power_line']}"]
    for n in JUDGED:
        if p30[n].get("noop_reason"):
            L.append(f"- {n}: 무효 실행 가드 — {p30[n]['noop_reason']}")
    L += ["", "## 세후 수익·세금(3,000만 원, 판정 구간)", "", "| 변형 | 세후 연수익 | 원화 MDD | 연 회전율 | 양도세(전체) |", "|---|---|---|---|---|"]
    for n in VARIANTS:
        mv = m[f"{n}|base_30m"]
        tax = (mv.get("totals") or {}).get("capital_gains_tax_krw")
        L.append(f"| {n} | {_pct(mv['cagr_judged'], 2)} | {_pct(mv['mdd_judged'])} | {_pct(mv['turnover_annual_judged'], 0)} | "
                 f"{'—' if tax is None else f'{tax / 10_000:,.0f}만 원'} |")
    acc, ev, cov = r["diag_accuracy"], r["diag_event_study"], r["coverage_by_year"]
    L += ["", "## 진단(보고만, 판정에 안 씀)", "",
          f"- 재선정 {sd['n_reselections']}회, 고른 종목 중 임박 {sd['n_imminent']}건(재선정별 {sd['imminent_per_reselection']}), "
          f"8-K 2.02 이력이 없어 '임박 아님'으로 본 종목 {sd['n_no_history_picks']}건.",
          f"- E1 미룬 매수 {sd['e1_delayed']}건 중 매수일에 추세 활성이 아니었는데도 산 경우 {sd['e1_buy_not_trend_active']}건"
          f"(확인 불가 {sd['e1_buy_trend_unknown']}건). E2 대체 {sd['e2_replaced']}건, 대체 후보가 없어 원래 종목 유지 {sd['e2_kept_no_alternative']}건.",
          f"- 예상일 정확도(상위 10 후보, 실제 다음 8-K 2.02 와 ±3거래일 안): {_pct(acc['share_within_3td'])} "
          f"(n={acc['n']}, 중앙 오차 {_f(acc['median_err_td'], 1)}거래일, 평균 절대 오차 {_f(acc['mean_abs_err_td'], 1)}거래일).",
          f"- 새틀라이트 보유 중 실적 3일 반응: 평균 {_pct(ev['earnings']['mean'], 2)}, −5%보다 나쁜 비율 "
          f"{_pct(ev['earnings']['share_worse_than_-5pct'])} (n={ev['earnings']['n']}) — 같은 종목 비실적 3일 창: 평균 "
          f"{_pct(ev['non_earnings']['mean'], 2)}, −5%보다 나쁜 비율 {_pct(ev['non_earnings']['share_worse_than_-5pct'])} (n={ev['non_earnings']['n']}).",
          "", "| 연도 | 풀 종목 | 8-K 2.02 있음 | 비율 |", "|---|---|---|---|"]
    for y, c in cov.items():
        L.append(f"| {y} | {c['n']} | {c['with_filing']} | {_pct(c['share'], 0)} |")
    L += ["", "## 이것이 증명하는 것과 증명하지 못하는 것", "",
          "- 8-K 제출일은 실제 발표 시각과 다르다(장 전·장 후 발표, 다음 날 제출 등). 하루 정도 어긋날 수 있다.",
          "- 예상일은 '마지막 제출 + 91일' 분기 근사다. 회계연도 말 분기(10-K 시기)는 더 늦게 발표하는 회사가 많아 어긋난다(정확도 진단 참조).",
          "- 2012년 무렵 이전은 8-K 2.02 기록이 얇을 수 있다(연도별 비율 참조). 이력 없는 종목은 '임박 아님'으로 처리했다.",
          "- 생존편향: 상장폐지 종목은 가격 소스에 없어 후보에서 빠진다.",
          "- 이미 본 데이터: 2010~2024 는 다른 새틀라이트 연구들이 여러 번 본 기간이다. PASS 도 '전진 원장에 올릴 후보'일 뿐 채택이 아니다. 2024-10 이후는 보고만 한다.",
          "- 세금은 한국 해외주식 양도소득세와 카카오페이증권 기본 가정(`core/tax_fx.py`). 실제 계좌와 다를 수 있다.",
          "- 엔진(챔피언)은 바뀌지 않았다. 반영은 사용자 확인 뒤 별도 작업이다.", ""]
    return "\n".join(L)


def smoke_coverage(r: dict) -> dict:
    sd = r["schedule_diag"]
    return {"imminent": sd["n_imminent"] > 0, "no_history": sd["n_no_history_picks"] > 0, "e1_delayed": sd["e1_delayed"] > 0,
            "e2_replaced": sd["e2_replaced"] > 0, "verdicts": len(r["verdicts"]) == len(JUDGED),
            "tax_engine": "capital_gains_tax_krw" in r["metrics"]["E0|base_30m"]["totals"],
            "event_study": r["diag_event_study"]["earnings"]["n"] > 0, "accuracy": r["diag_accuracy"]["n"] > 0}


# =================================================================================================
# 실행
# =================================================================================================

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-steps-per-run", type=int, default=0, help="재개 확인용: 이번 실행의 새 계산 단위 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    steps = {"n": 0}

    def log(s: str) -> None:
        print(s, flush=True)

    def step() -> None:
        if deadline is not None and time.time() > deadline - 90:
            raise _Stop()
        if a.max_steps_per_run and steps["n"] >= a.max_steps_per_run:
            raise _Stop()
        steps["n"] += 1

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        s1 = SV._load_ckpt(ck / "stage1.pkl", fp)
        if s1 is None:
            step()
            s1 = _stage1_smoke(log) if a.smoke else _stage1_real(log)
            SV._atomic_pickle(ck / "stage1.pkl", {"fingerprint": fp, "payload": s1})
            log("입력 체크포인트 저장")
        got = SV._load_ckpt(ck / "filings.pkl", fp)
        if got is None:
            step()
            if a.smoke:
                got = {"filings": synthetic_filings(s1["universe"]), "meta": {"complete": True, "synthetic": True}}
            else:
                fl, st = fetch_filings(s1["universe"], (deadline - 300) if deadline else None, log)
                if not st["complete"]:
                    log(f"SEC 제출일 수집 미완료(남은 {st['left']}) — 다음 회차에 이어서")
                    raise _Stop()
                got = {"filings": fl, "meta": st}
            SV._atomic_pickle(ck / "filings.pkl", {"fingerprint": fp, "payload": got})
            log("8-K 2.02 제출일 체크포인트 저장")
        filings = got["filings"]
        s2 = stage2(s1, filings)
        sims = {}
        for name in VARIANTS:
            for setup in SETUPS:
                path = ck / f"sim_{name}_{setup}.pkl"
                res = SV._load_ckpt(path, fp)
                if res is None:
                    step()
                    w = variant_weights(s1["core_w"], s2["schedules"][name], s2["adj"])
                    w = w.loc[:, w.abs().sum() > 0]
                    cfg = tx.AccountConfig(**SETUPS[setup])
                    s = tx.simulate(w, s2["close"], s2["adj"], s1["fx"], cfg)
                    res = sim_summary(s, w, s2["adj"], cfg.initial_krw, with_pre=setup == "base_30m")
                    SV._atomic_pickle(path, {"fingerprint": fp, "payload": res})
                    log(f"시뮬레이션 {name} {setup} 판정 구간 세후 {res['cagr_judged']:.4f}")
                sims[(name, setup)] = res
        result, rep = analyze(s1, s2, sims, got["meta"], filings, a.smoke)
        if a.smoke:
            cov = smoke_coverage(result)
            result["smoke_coverage"] = cov
            missing = [k for k, v in cov.items() if not v]
            if missing:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {missing}")
    except _Stop:
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(rep, encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
