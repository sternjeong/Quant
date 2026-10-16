"""검증 sat-frontier-v1 (2026-10-16 사전 등록): SPY + 새틀라이트, 안정성 한도 안에서 수익이 가장 큰 새틀라이트 비중은.

사용자 요청(2026-10-16): 수익 우선, 안정성은 어느 정도. spy-champion-v1 에서 SPY + 새틀라이트가 세후로 챔피언·SPY 를 이겼고
새틀라이트 비중이 클수록 수익이 올랐지만 생존편향도 커진다. 엇갈린 하위 슬리브(sat-stagger-v1)·순위 버퍼 K6(sat-buffer-v1)는
적은 비용으로 분산을 줄였다. 고정한 안정성 한도 안에서 앞 절반(선택)만 보고 비중을 고르고 뒤 절반(확인)에서 확인한다.

규칙 전체는 SPEC.md(한국어)에 고정. 판정 기준을 바꾸려면 새 id 로 다시 등록한다. 엔진 반영은 사용자 확인 뒤 별도 작업이다.
spy-champion-v1(슬리브·1월 리셋), sat-buffer-v1(순위 버퍼), satellite-value-v1(통계·체크포인트·패널)의 함수를 import 해서 쓴다.
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

JOB_ID = "sat-frontier-v1"
RULES_VERSION = "sat-frontier-v1/2026-10-16"
START = "2010-01-01"

# 구간(각 구간은 새 계좌) — 시작·끝은 그 날 이후 첫 / 그 날 이전 마지막 거래일
WINDOWS = {"sel": ("2010-01-04", "2017-05-31"), "conf": ("2017-06-01", "2024-09-30"), "post": ("2024-10-01", None)}

W_SATS = (0.15, 0.20, 0.30, 0.40, 0.50)
STABILIZERS = ("none", "ST")
ST_SLEEVES = (("S17", (1, 7)), ("S39", (3, 9)), ("S511", (5, 11)))
BUFFER_K = 6
CELLS = tuple(f"{st}_{int(round(w * 100))}" for w in W_SATS for st in STABILIZERS)


def cell_params(cell: str) -> tuple[str, float]:
    st, w = cell.rsplit("_", 1)
    return st, int(w) / 100.0


NAMES = {c: f"SPY {100 - int(c.rsplit('_', 1)[1])}% + 새틀라이트 {c.rsplit('_', 1)[1]}% "
            + ("(현행 단일 슬리브 1·7월)" if c.startswith("none") else "(하위 슬리브 3개 1·7/3·9/5·11월 + 순위 버퍼 K6)")
         for c in CELLS}
NAMES["SPY"] = "SPY 그냥 보유(기준)"
SETUPS = {"base_30m": {}, "base_100m": {"initial_krw": 100_000_000}}
DECISION_SETUP = "base_30m"

# 판정(사전 등록)
ROLL_12M_DAYS = 252             # 롤링 12개월 = 252 거래일
WORST12_TOL = 0.05              # B: 최악 12개월 ≥ SPY 최악 − 5%p
CI_LOW_FLOOR = -0.005           # 90% 하한 > −0.5%p
N_BOOT = 1000
BLOCK_DAYS = 126
BOOT_SEED = 20261023
CI_PCT = (5.0, 95.0)
HAIRCUTS = (0.01, 0.02, 0.03)   # 새틀라이트 일별 수익에서 연 d (하루 d/252)
ROBUST_D = 0.02
TIE_EPS = 1e-9
POWER_YEARS = 7.3
N_TRIALS = 10
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"
NO_ELIGIBLE = "NO_ELIGIBLE_CELL"
ROBUST, NOT_ROBUST, NA = "ROBUST_TO_HAIRCUT", "NOT_ROBUST_TO_HAIRCUT", "NOT_APPLICABLE"


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SC = _load("spy_champion_v1_for_frontier", "research/jobs/spy-champion-v1/run.py")
BUF = _load("sat_buffer_v1_for_frontier", "research/jobs/sat-buffer-v1/run.py")
SV = SC.SV


# =================================================================================================
# 일정·비중 (순수 함수 — tests/test_sat_frontier.py)
# =================================================================================================

def st_dates(trading_days: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """START 이후 홀수 달(1·3·5·7·9·11) 첫 거래일(전날이 있는 날만) — 하위 슬리브 재선정일."""
    from core import satellite_lab as sl

    return [d for d in sl.rebalance_dates(trading_days, 1)
            if d >= pd.Timestamp(START) and d.month % 2 == 1 and sl._prev_day(trading_days, d) is not None]


def st_schedules(dates: list, pool_scores: dict, score_extra) -> dict:
    """{하위 슬리브: [{date, picks, kept}]} — 각자 자기 달에만 S-SEED-000 + 순위 버퍼 K6(sat-buffer-v1 규칙 그대로)."""
    return BUF.build_schedules(dates, pool_scores, score_extra, variants={n: (BUFFER_K, m) for n, m in ST_SLEEVES})


def rows_to_log(rows: list[dict]) -> list[dict]:
    return [{"date": str(pd.Timestamp(r["date"]).date()), "weights": ({t: 1.0 / len(r["picks"]) for t in r["picks"]}
                                                                       if r["picks"] else {})} for r in rows]


def cell_weights(cell: str, index: pd.DatetimeIndex, logs: dict, adj: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """SPY w_spy + 새틀라이트 w_sat(none: 단일 슬리브 / ST: 하위 슬리브 3개 w_sat/3 씩), 1월 첫 거래일에만 슬리브 리셋."""
    st, w_sat = cell_params(cell)
    sleeves = [("spy", 1.0 - w_sat, pd.DataFrame({"SPY": 1.0}, index=index))]
    parts = [("sat", logs["none"])] if st == "none" else [(n, logs[n]) for n, _ in ST_SLEEVES]
    for n, lg in parts:
        f = SC.inner_frame_from_log(index, lg)
        sleeves.append((n, w_sat / len(parts), f))
    return SC.sleeve_weights(index, adj, sleeves)


def haircut_prices(close: pd.DataFrame, adj: pd.DataFrame, d: float, keep: tuple = ("SPY",)
                   ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """새틀라이트 종목(keep 밖 모든 열)의 가격에 거래일마다 (1 − d/252) 를 곱해 누적. 종가·조정가 모두 같은 배수 →
    일별 수익이 (1+r)(1−d/252)−1, 배당 복원은 같은 비율로 줄어든다."""
    k = np.arange(len(adj.index), dtype=float)
    fac = pd.Series((1.0 - d / 252.0) ** k, index=adj.index)
    cols_a = [c for c in adj.columns if c not in keep]
    cols_c = [c for c in close.columns if c not in keep]
    a, c = adj.copy(), close.copy()
    a[cols_a] = a[cols_a].mul(fac, axis=0)
    c[cols_c] = c[cols_c].mul(fac.reindex(c.index).ffill().bfill(), axis=0)
    return c, a


def window_bounds(index: pd.DatetimeIndex) -> dict:
    out = {}
    for k, (a, b) in WINDOWS.items():
        sub = index[(index >= pd.Timestamp(a)) & ((index <= pd.Timestamp(b)) if b else True)]
        if len(sub) >= 2:
            out[k] = (sub[0], sub[-1])
    return out


# =================================================================================================
# 판정 (순수 함수)
# =================================================================================================

def worst_rolling(values: pd.Series, window: int = ROLL_12M_DAYS) -> float:
    r = (values / values.shift(window) - 1.0).dropna()
    return float(r.min()) if len(r) else float("nan")


def mdd(values: pd.Series) -> float:
    return float((values / values.cummax() - 1).min())


def stable(m: dict, spy: dict) -> tuple[bool, bool]:
    """(A, B): A = 원화 MDD 가 SPY 보다 나쁘지 않음, B = 최악 12개월 ≥ SPY 최악 − 5%p."""
    a = math.isfinite(m["mdd"]) and math.isfinite(spy["mdd"]) and m["mdd"] >= spy["mdd"]
    b = math.isfinite(m["worst12"]) and math.isfinite(spy["worst12"]) and m["worst12"] >= spy["worst12"] - WORST12_TOL
    return bool(a), bool(b)


def select_cell(sel_metrics: dict, spy_sel: dict) -> Optional[str]:
    """선택 구간 지표만 받는다: {셀: {ann, mdd, worst12}}. A·B 를 만족하는 셀 중 세후 연수익 최대
    (동률 → 낮은 w_sat, 그다음 none). 없으면 None."""
    ok = [c for c, m in sel_metrics.items() if all(stable(m, spy_sel)) and math.isfinite(m["ann"])]
    if not ok:
        return None
    best = max(sel_metrics[c]["ann"] for c in ok)
    tied = [c for c in ok if sel_metrics[c]["ann"] >= best - TIE_EPS]
    return min(tied, key=lambda c: (cell_params(c)[1], STABILIZERS.index(cell_params(c)[0])))


def decide(diff, a_ok, b_ok, ci_low, *, noop: Optional[str] = None, observed_ir=None, power=None) -> tuple[str, list]:
    if noop:
        return NOT_EVALUABLE, ["noop"]
    if any(v is None or not math.isfinite(float(v)) for v in (diff, ci_low)):
        return NOT_EVALUABLE, ["non_finite"]
    miss = []
    if not diff > 0:
        miss.append("conf_after_tax_gt_spy")
    if not a_ok:
        miss.append("A_mdd_not_worse_than_spy")
    if not b_ok:
        miss.append("B_worst12m_ge_spy_minus_5pp")
    if not ci_low > CI_LOW_FLOOR:
        miss.append("boot_ci90_low_gt_minus_0.5pp")
    if not miss:
        return PASS, []
    return (rp.classify_fail(observed_ir, power) if power else FAIL), miss


def haircut_flag(diff_at_2: Optional[float]) -> str:
    if diff_at_2 is None or not math.isfinite(float(diff_at_2)):
        return NA
    return ROBUST if diff_at_2 > 0 else NOT_ROBUST


# =================================================================================================
# 입력
# =================================================================================================

def score_inputs(data, dates: list) -> tuple[dict, callable]:
    """sat-buffer-v1.score_inputs 와 같은 식(S-SEED-000 순서·창)을 주어진 날짜에서."""
    from core import satellite_lab as sl

    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    signal = sl.load_signal(code)
    params = dict(spec["signal"]["params_grid"][0])
    pool_scores, cutoffs = {}, {}
    for d in dates:
        cutoff = sl._prev_day(data.trading_days, d)
        members = data.pool(spec["pool"]["type"], d)
        prices = sl._signal_prices(data, members, cutoff, d)
        eligible = {t for t in prices if t in data.closes.columns and pd.notna(data.closes.at[d, t])}
        scores = sl._call_signal(signal, spec, data, {t: prices[t] for t in eligible}, cutoff, params)
        pool_scores[d] = {t: float(v) for t, v in (scores or {}).items()
                          if t in eligible and v is not None and math.isfinite(float(v))}
        cutoffs[d] = cutoff
    cache: dict = {}

    def score_extra(d, t):
        key = (pd.Timestamp(d), t)
        if key not in cache:
            d_ = pd.Timestamp(d)
            prices = sl._signal_prices(data, [t], cutoffs[d_], d_)
            ok = t in prices and t in data.closes.columns and pd.notna(data.closes.at[d_, t])
            v = (sl._call_signal(signal, spec, data, {t: prices[t]}, cutoffs[d_], params) or {}).get(t) if ok else None
            cache[key] = float(v) if v is not None and math.isfinite(float(v)) else None
        return cache[key]

    return pool_scores, score_extra


def _prepare(data, spy_frame: pd.DataFrame, fx: pd.Series, meta: dict) -> dict:
    from core import satellite_lab as sl

    spec, signal, params = SV._incumbent()
    sp = json.loads(json.dumps(spec))
    sp["pool"] = {"type": "champion40"}
    none_log = SV.schedule_to_log(sl.run_variant(sp, params, signal, data)["schedule"])
    dates = st_dates(data.trading_days)
    pool_scores, score_extra = score_inputs(data, dates)
    scheds = st_schedules(dates, pool_scores, score_extra)
    logs = {"none": none_log, **{n: rows_to_log(rows) for n, rows in scheds.items()}}
    names = sorted({t for lg in logs.values() for r in lg for t in r["weights"]})
    frames = {t: data.ohlcv.get(t) for t in names}
    frames["SPY"] = spy_frame
    close, adj = SV._panel(frames)
    sched_out = {n: [{"date": str(pd.Timestamp(r["date"]).date()), "picks": r["picks"], "kept": r["kept"]} for r in rows]
                 for n, rows in scheds.items()}
    return {"logs": logs, "schedules": sched_out, "close": close, "adj": adj, "fx": fx, "meta": meta}


def _real_prep(log) -> dict:
    from core import champion_strategy as cs
    from core import satellite_lab as sl
    from core.market_data import get_multiple_price_history

    pool = SV._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", pool_provider=pool, log=log)
    hist = get_multiple_price_history(["SPY"], start="2009-06-01", end=None, interval="1d")
    meta = {"live_satellite_weight": cs.SATELLITE_WEIGHT, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
            "judge_version": sl.JUDGE_VERSION, "pool_cache_tag": sl.POOL_CACHE_TAG}
    return _prepare(data, hist.get("SPY"), tx.usdkrw_series(), meta)


def _smoke_prep(log) -> dict:
    """합성 데이터(네트워크 없음). 실데이터가 아니다."""
    from core import satellite_lab as sl

    end = "2026-06-30"
    pp, poolp = sl.synthetic_providers(n_tickers=50, start="2008-01-01", end=end, seed=11)
    base_pool = SV._pool_wrapper(poolp, date.fromisoformat(START))
    names = sorted(f"T{i:02d}" for i in range(50))

    def pool(pt, d):   # 풀이 반기마다 조금씩 바뀌게(풀 밖 보유 종목 버퍼 규칙도 지나가게)
        m = base_pool(pt, d)
        if not m:
            return m
        k = (d.year * 2 + (d.month >= 7)) % 10
        return names[k:k + 40]
    data = sl.build_data({"champion40"}, start="2009-12-01", end=end, pool_provider=pool, price_provider=pp)
    full = pd.bdate_range("2008-01-01", end)
    rng = np.random.default_rng(5)
    c = 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, len(full))))
    spy = pd.DataFrame({"Close": c, "Adj Close": c * np.exp(np.linspace(0, 0.3, len(full)))}, index=full)
    fx = pd.Series(1100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(full)))), index=full)
    return _prepare(data, spy, fx, {"synthetic": True})


def sim_index(prep: dict) -> pd.DatetimeIndex:
    a = prep["adj"]["SPY"].dropna()
    return a.index[a.index >= pd.Timestamp(START)]


def sim_jobs(wins: dict) -> list[tuple]:
    """(포트폴리오, 구간, 설정, 헤어컷 d)."""
    ports = CELLS + ("SPY",)
    jobs = [(p, w, DECISION_SETUP, 0.0) for w in wins for p in ports]
    if "conf" in wins:
        jobs += [(p, "conf", "base_100m", 0.0) for p in ports]
        jobs += [(c, "conf", DECISION_SETUP, d) for d in HAIRCUTS for c in CELLS]
    return jobs


def summarize(s: dict, w: pd.DataFrame, adj: pd.DataFrame, initial: float) -> dict:
    v = s["values_krw"]
    t0, t1 = v.index[0], v.index[-1]
    return {"ann": SC.liq_cagr(s["final_after_liquidation_krw"], initial, t0, t1), "cagr_pre": s["cagr_pre"],
            "mdd": mdd(v), "worst12": worst_rolling(v), "tax_krw": s["totals"]["capital_gains_tax_krw"],
            "fees_krw": s["totals"]["fees_krw"], "unpaid_tax_if_sold_krw": s["unpaid_tax_if_sold_now_krw"],
            "turnover": SC.annual_turnover(w, adj), "start": str(t0.date()), "end": str(t1.date()), "values": v}


# =================================================================================================
# 분석·보고
# =================================================================================================

def pair(a: dict, b: dict, initial: float) -> dict:
    va, vb = a["values"], b["values"]
    ra, rb = SV.window_returns(va, initial, va.index[-1]), SV.window_returns(vb, initial, vb.index[-1])
    years = (va.index[-1] - va.index[0]).days / 365.25
    ppy = len(ra) / years
    d = (ra - rb).to_numpy()
    sd = float(np.std(d, ddof=1)) if len(d) > 1 else float("nan")
    ir = float(np.mean(d) / sd * math.sqrt(ppy)) if sd and math.isfinite(sd) and sd > 0 else float("nan")
    boot = SV.block_bootstrap_diff(ra.to_numpy(), rb.to_numpy(), ppy, n_boot=N_BOOT, block=BLOCK_DAYS, seed=BOOT_SEED)
    lo, hi = np.percentile(boot, CI_PCT)
    return {"daily_diff_ir": ir, "noop_reason": rp.noop_guard(d), "boot_ci90_low": float(lo), "boot_ci90_high": float(hi),
            "boot_share_positive": float(np.mean(boot > 0))}


def analyze(sims: dict, info: dict, prep: dict, wins: dict, smoke: bool) -> tuple[dict, str]:
    initial = tx.AccountConfig(**SETUPS[DECISION_SETUP]).initial_krw
    power = rp.power_report(POWER_YEARS, N_TRIALS)
    strip = lambda s: {k: v for k, v in s.items() if k != "values"}  # noqa: E731
    metrics = {}
    for (p, win, setup, d), s in sims.items():
        key = setup if d == 0 else f"{setup}_haircut_{int(round(d * 100))}"
        metrics.setdefault(key, {}).setdefault(p, {})[win] = strip(s)
    m = metrics[DECISION_SETUP]
    stab = {w: {c: dict(zip(("A", "B"), stable(m[c][w], m["SPY"][w]))) for c in CELLS} for w in ("sel", "conf")}
    chosen = select_cell({c: m[c]["sel"] for c in CELLS}, m["SPY"]["sel"])
    haircut = {c: {"0": m[c]["conf"]["ann"] - m["SPY"]["conf"]["ann"]} for c in CELLS}
    for d in HAIRCUTS:
        hm = metrics[f"{DECISION_SETUP}_haircut_{int(round(d * 100))}"]
        for c in CELLS:
            haircut[c][str(int(round(d * 100)))] = hm[c]["conf"]["ann"] - m["SPY"]["conf"]["ann"]
    detail = {"chosen": chosen}
    if chosen is None:
        verdict, flag = NO_ELIGIBLE, NA
    else:
        pc = pair(sims[(chosen, "conf", DECISION_SETUP, 0.0)], sims[("SPY", "conf", DECISION_SETUP, 0.0)], initial)
        diff = haircut[chosen]["0"]
        verdict, miss = decide(diff, stab["conf"][chosen]["A"], stab["conf"][chosen]["B"], pc["boot_ci90_low"],
                               noop=pc["noop_reason"], observed_ir=pc["daily_diff_ir"], power=power)
        hv = haircut[chosen]
        ds = [0.0] + [d * 100 for d in HAIRCUTS]
        be = rp_break_even(ds, [hv["0"]] + [hv[str(int(round(d * 100)))] for d in HAIRCUTS])
        flag = haircut_flag(hv["2"])
        detail.update({"conf_diff_vs_spy": diff, "vs_spy_conf": pc, "failed_conditions": miss,
                       "break_even_haircut_pct_per_year": be, "haircut_diffs": hv})
    verdicts = {"chosen_cell": chosen or NO_ELIGIBLE, "verdict": verdict, "haircut": flag}
    if smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    sleeve_info = {f"{p}|{w}": {"reset_days": len(i["reset_days"]), "sleeve_trades": i["sleeve_trades"]}
                   for (p, w), i in info.items()}
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windows": {k: [str(a.date()), str(b.date())] for k, (a, b) in wins.items()},
        "rules": {"cells": list(CELLS), "w_sats": list(W_SATS), "st_sleeves": {n: list(mo) for n, mo in ST_SLEEVES},
                  "buffer_k": BUFFER_K, "roll_12m_days": ROLL_12M_DAYS, "worst12_tol": WORST12_TOL,
                  "ci_low_floor": CI_LOW_FLOOR, "n_boot": N_BOOT, "block_days": BLOCK_DAYS, "boot_seed": BOOT_SEED,
                  "haircuts": list(HAIRCUTS), "robust_d": ROBUST_D, "power_years": POWER_YEARS, "n_trials": N_TRIALS,
                  "metric": "세후 원화, 끝날 청산 시 낼 세금 반영 연복리", "post_2024_10": "report only"},
        "names": NAMES, "verdicts": verdicts, "detail": detail, "stability": stab, "haircut_diff_vs_spy_conf": haircut,
        "metrics": metrics, "power": power, "power_line": rp.power_line(power), "sleeve_info": sleeve_info,
        "schedules": prep.get("schedules", {}), "inputs_meta": prep.get("meta", {}),
    }
    return result, report(result)


def rp_break_even(ds: list, diffs: list) -> Optional[float]:
    """diff(d)=0 이 되는 d(연 %) 선형 보간. 격자(0~3%) 안에서 부호가 안 바뀌면 None."""
    pts = sorted(zip(ds, diffs))
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        if v0 == 0:
            return float(d0)
        if (v0 > 0) != (v1 > 0) and v1 != v0:
            return float(d0 + (0 - v0) * (d1 - d0) / (v1 - v0))
    return None


_pct, _pp, _won = BUF._pct, BUF._pp, BUF._won


def report(r: dict) -> str:
    sm = " (스모크 — 합성 데이터, 실측 아님)" if r["smoke"] else ""
    m = r["metrics"][DECISION_SETUP]
    w = r["windows"]
    v = r["verdicts"]
    det = r["detail"]
    L = [f"# SPY + 새틀라이트 비중 고르기(안정성 한도 안에서 수익 최대){sm}", "",
         f"선택 구간 {w['sel'][0]} ~ {w['sel'][1]}(여기서만 고름) · 확인 구간 {w['conf'][0]} ~ {w['conf'][1]}(구간마다 새 계좌, "
         "초기 3,000만 원, 카카오페이증권 가정, 세후 = 끝날 다 팔면 낼 세금까지 뺀 원화 연복리).", "",
         "## 판정", "",
         f"- 고른 칸: **{v['chosen_cell']}** {NAMES.get(det.get('chosen') or '', '')}",
         f"- 확인 구간 판정: **{v['verdict']}**",
         f"- 생존편향 스트레스(연 2% 깎아도 SPY 를 이기나): **{v['haircut']}**"]
    if det.get("chosen"):
        pc = det["vs_spy_conf"]
        be = det["break_even_haircut_pct_per_year"]
        L += [f"- 확인 구간 SPY 대비 세후 연수익 차이 {_pp(det['conf_diff_vs_spy'])}, 부트스트랩 90% {_pp(pc['boot_ci90_low'])} ~ "
              f"{_pp(pc['boot_ci90_high'])}, 미충족: {', '.join(det['failed_conditions']) or '없음'}",
              "- 손익분기 헤어컷 d*: " + (f"연 {be:.2f}%" if be is not None else "0~3% 격자 밖(부호가 안 바뀜)")]
    L += ["", "고르는 규칙(선택 구간만): (A) 원화 MDD 가 SPY 그냥 보유보다 나쁘지 않음, (B) 최악 롤링 12개월(252거래일) 수익 ≥ SPY 최악 − 5%p 를 "
          "모두 만족하는 칸 중 세후 연수익이 가장 큰 칸(동률이면 낮은 비중, 그다음 '현행'). 없으면 NO_ELIGIBLE_CELL.",
          "통과(PASS_FORWARD_CANDIDATE) = 확인 구간에서 세후 연수익이 SPY 보다 높고(차이 > 0), A·B 유지, 126일 블록 부트스트랩 1,000회"
          f"(시드 {BOOT_SEED}) 차이 90% 하한 > −0.5%p.", f"- {r['power_line']}", "",
          "## 모든 칸(3,000만 원)", "",
          "| 칸 | 선택: 세후 | MDD | 최악 12개월 | A/B | 확인: 세후 | MDD | 최악 12개월 | A/B | 2024-10~(보고) | 양도세 선택/확인(만 원) | 회전율/년(확인) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    st = r["stability"]
    for p in CELLS + ("SPY",):
        s, c = m[p]["sel"], m[p]["conf"]
        ab = lambda win: "—" if p == "SPY" else ("✓" if st[win][p]["A"] else "✗") + "/" + ("✓" if st[win][p]["B"] else "✗")  # noqa: E731
        L.append(f"| {p} | {_pct(s['ann'], nd=2)} | {_pct(s['mdd'])} | {_pct(s['worst12'])} | {ab('sel')} | {_pct(c['ann'], nd=2)} | "
                 f"{_pct(c['mdd'])} | {_pct(c['worst12'])} | {ab('conf')} | {_pct(m[p].get('post', {}).get('ann'), nd=2)} | "
                 f"{s['tax_krw'] / 1e4:,.0f} / {c['tax_krw'] / 1e4:,.0f} | {c['turnover']:.2f} |")
    L += ["", "## 생존편향 스트레스(확인 구간, 새틀라이트 일별 수익에서 연 d% 차감, SPY 대비 세후 연수익 차이)", "",
          "| 칸 | d=0 | 1% | 2% | 3% |", "|---|---|---|---|---|"]
    for c in CELLS:
        h = r["haircut_diff_vs_spy_conf"][c]
        L.append(f"| {c} | {_pp(h['0'])} | {_pp(h['1'])} | {_pp(h['2'])} | {_pp(h['3'])} |")
    m1 = r["metrics"].get("base_100m", {})
    if m1:
        L += ["", "## 초기 1억 원(확인 구간, 보고만)", "",
              ", ".join(f"{p} {_pct(m1[p]['conf']['ann'], nd=2)}" for p in CELLS + ("SPY",) if p in m1) + "."]
    L += ["", "## 규약", "",
          "- SPY 는 처음 사서 1월 첫 거래일 슬리브 리셋 때만 판다. 슬리브 비중은 매년 1월 첫 거래일에만 목표로 되돌리고 그 사이 표류(spy-champion-v1 과 같음).",
          "- none = 현행 S-SEED-000(그 시점 champion40 풀, 돈치안 20일 추세 활성, 252일 모멘텀 상위 3, 균등, 1·7월 재선정) 한 슬리브.",
          "- ST = 하위 슬리브 3개(1·7월, 3·9월, 5·11월, 각 w_sat/3). 각자 자기 달에 S-SEED-000 + 순위 버퍼 K6(보유 종목이 추세 활성이고 상위 6 안이면 유지). "
          "한 하위 슬리브가 재선정하는 날은 그 슬리브 안만 다시 나눈다. 시작 구간 첫 몇 달(3·9월, 5·11월 슬리브의 첫 재선정 전)은 그 몫이 현금이다.",
          "- 헤어컷은 새틀라이트 종목 가격에 거래일마다 (1 − d/252) 를 곱해 넣는다(종가·조정가 같은 배수, 세금 계산에도 반영).",
          "- 2024-10 이후는 판정에 쓰지 않는다(보고만).", "",
          "## 한계(꼭 읽기)", "",
          "- 생존편향: 상장폐지 종목이 가격 소스에 없어 후보에서 빠진다. 새틀라이트를 실제보다 좋게 보이게 하며, 새틀라이트 비중이 클수록 편향이 결과에 더 크게 실린다. "
          "w_sat 30% 이상을 채택하기 전에 CRSP(상장폐지 포함) 자료로 다시 검증할 것을 권한다. 헤어컷은 상수 근사일 뿐 실제 편향 크기를 재지 않는다.",
          "- 이미 본 데이터: 2010~2024 는 spy-champion-v1·sleeve-weight-v1·sat-stagger-v1·sat-buffer-v1 등이 이미 본 기간이다. 앞/뒤 절반 나누기도 완전한 표본 외 검증은 아니다.",
          "- PASS 는 '전진 원장에 올릴 후보'까지만 뜻한다. 엔진(챔피언)은 바뀌지 않았다. 반영은 사용자 확인 뒤 별도 작업이다.",
          "- 일봉 종가 체결, 금융소득 종합과세 미반영. 과거 결과이며 앞으로의 수익을 뜻하지 않는다.", ""]
    return "\n".join(L)


def smoke_coverage(r: dict, prep: dict) -> dict:
    sch = prep["schedules"]
    return {"all_cells": all(c in r["metrics"][DECISION_SETUP] for c in CELLS),
            "st_calendars": all(pd.Timestamp(x["date"]).month in mo for n, mo in ST_SLEEVES for x in sch[n]) and all(sch[n] for n, _ in ST_SLEEVES),
            "buffer_kept_some": any(x["kept"] for n, _ in ST_SLEEVES for x in sch[n]),
            "haircut_lowers": all(r["haircut_diff_vs_spy_conf"][c]["3"] < r["haircut_diff_vs_spy_conf"][c]["0"] for c in CELLS),
            "tax_engine": any(r["metrics"][DECISION_SETUP][c]["conf"]["tax_krw"] > 0 for c in CELLS),
            "windows": all(k in r["windows"] for k in ("sel", "conf", "post"))}


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
        prep = SV._load_ckpt(ck / "prep.pkl", fp)
        if prep is None:
            step()
            prep = _smoke_prep(log) if a.smoke else _real_prep(log)
            SV._atomic_pickle(ck / "prep.pkl", {"fingerprint": fp, "payload": prep})
            log("입력 체크포인트 저장")
        idx = sim_index(prep)
        wins = window_bounds(idx)
        W, info, panels = {}, {}, {}
        sims = {}
        for key in sim_jobs(wins):
            pname, win, setup, d = key
            path = ck / f"sim_{pname}_{win}_{setup}_{int(round(d * 100))}.pkl"
            got = SV._load_ckpt(path, fp)
            if (pname, win) not in W:
                t0, t1 = wins[win]
                sub = idx[(idx >= t0) & (idx <= t1)]
                if pname == "SPY":
                    W[(pname, win)] = tx.buy_and_hold_weights(sub)
                else:
                    wt, info[(pname, win)] = cell_weights(pname, sub, prep["logs"], prep["adj"])
                    W[(pname, win)] = wt.loc[:, wt.abs().sum() > 0]
            if got is None:
                step()
                if d not in panels:
                    panels[d] = (prep["close"], prep["adj"]) if d == 0 else haircut_prices(prep["close"], prep["adj"], d)
                close, adj = panels[d]
                cfg = tx.AccountConfig(**SETUPS[setup])
                w = W[(pname, win)]
                s = tx.simulate(w, close, adj, prep["fx"], cfg)
                got = summarize(s, w, adj, cfg.initial_krw)
                SV._atomic_pickle(path, {"fingerprint": fp, "payload": got})
                log(f"시뮬레이션 {key} 세후(청산) {got['ann']:.4f}")
            sims[key] = got
        result, rep = analyze(sims, info, prep, wins, a.smoke)
        if a.smoke:
            cov = smoke_coverage(result, prep)
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
    (out / "REPORT.md").write_text(rep, encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
