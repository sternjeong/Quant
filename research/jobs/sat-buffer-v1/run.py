"""검증 sat-buffer-v1 (2026-10-15 사전 등록): 새틀라이트 '이긴 종목 계속 들고 가기(순위 버퍼)'.

사용자 요청(2026-10-15): 중간 매도 규칙은 모두 '재선정까지 그냥 보유'에 졌고, 반기 재선정 때마다 3종목 대부분이 바뀌며
과세 이익이 실현된다. 재선정일에 보유 종목이 아직 상위권(상위 K)이면 계속 들고 가서 회전율과 양도소득세를 줄이면 나아지는가.

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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "sat-buffer-v1"
RULES_VERSION = "sat-buffer-v1/2026-10-15"
START = "2010-01-01"
SAT_WEIGHT = 0.15
TOP_N = 3
DECISION_END = "2024-09-30"       # 판정 구간 끝(포함). 이후는 보고만
HALF_SPLIT = "2017-05-31"         # 앞 절반 = 시작 ~ 이 날 이전 마지막 거래일, 뒤 절반 = 그 날 ~ 판정 끝
N_BOOT = 1000
BLOCK_DAYS = 126
BOOT_SEED = 20261017
CI_PCT = (5.0, 95.0)
CI_LOW_FLOOR = -0.005
MDD_TOL = 0.02
POWER_YEARS = 14.7
N_TRIALS = 4
RESET_EPS = 1e-7                  # 재선정일마다 목표를 아주 조금 바꿔 tax_fx 가 그날 균등가중으로 다시 맞추게 함(SPEC)
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"

# 변형: (K, 재선정 달). K=None 은 B0(그냥 상위 3)
VARIANT_RULES = {"B0": (None, (1, 7)), "K6_H6": (6, (1, 7)), "K10_H6": (10, (1, 7)),
                 "K6_H12": (6, (1,)), "K10_H12": (10, (1,))}
JUDGED = ("K6_H6", "K10_H6", "K6_H12", "K10_H12")
VARIANTS = ("B0",) + JUDGED
NAMES = {"B0": "현행 S-SEED-000(1·7월 상위 3 전부 교체)",
         "K6_H6": "1·7월, 보유 종목이 추세 활성·상위 6 안이면 유지",
         "K10_H6": "1·7월, 보유 종목이 추세 활성·상위 10 안이면 유지",
         "K6_H12": "1월만, 보유 종목이 추세 활성·상위 6 안이면 유지",
         "K10_H12": "1월만, 보유 종목이 추세 활성·상위 10 안이면 유지"}
LEVELS = ("champ", "sleeve")
SETUPS = {"base_30m": {}, "base_100m": {"initial_krw": 100_000_000}}


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def _sv():
    """satellite-value-v1 의 통계·체크포인트·패널 함수를 그대로 쓴다(중복 구현하지 않음)."""
    spec = importlib.util.spec_from_file_location("satellite_value_v1_for_buffer",
                                                  PROJECT_ROOT / "research/jobs/satellite-value-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SV = _sv()


# =================================================================================================
# 선정 규칙 (순수 함수 — tests/test_sat_buffer.py)
# =================================================================================================

def _key(t: str, s: float) -> tuple:
    return (-float(s), t)          # 점수 내림차순, 동점은 티커순(sl.pick_top 과 같음)


def ranked(pool_scores: dict) -> list[str]:
    return [t for t, s in sorted(((t, float(s)) for t, s in pool_scores.items() if s is not None and math.isfinite(float(s))),
                                 key=lambda kv: _key(*kv))]


def held_rank(t: str, score: float, pool_scores: dict) -> int:
    """보유 종목 t 의 순위 = 1 + (그날 풀의 추세 활성 후보 중 t 보다 앞서는 종목 수). t 가 풀 밖이어도 같은 식."""
    k = _key(t, score)
    return 1 + sum(1 for c, s in pool_scores.items()
                   if c != t and s is not None and math.isfinite(float(s)) and _key(c, s) < k)


def select_with_buffer(held: list[str], pool_scores: dict, held_scores: dict, K: Optional[int],
                       top_n: int = TOP_N) -> tuple[list[str], list[str]]:
    """(새 보유, 유지한 종목). held_scores[t] = 보유 종목의 그날 점수(추세 활성·가격 있음일 때만, 아니면 없음/None).
    K=None 이면 B0: 버퍼 없이 상위 top_n."""
    order = ranked(pool_scores)
    if K is None:
        return order[:top_n], []
    kept = []
    for t in held:
        s = held_scores.get(t)
        if s is None or not math.isfinite(float(s)):
            continue
        if held_rank(t, float(s), pool_scores) <= K:
            kept.append(t)
    kept = sorted(kept, key=lambda t: _key(t, held_scores[t]))[:top_n]
    picks = list(kept)
    for t in order:
        if len(picks) >= top_n:
            break
        if t not in picks:
            picks.append(t)
    return picks, kept


def build_schedules(dates: list, pool_scores_by_date: dict, score_extra: Callable[[pd.Timestamp, str], Optional[float]],
                    variants: dict = VARIANT_RULES) -> dict:
    """{변형: [{date, picks, kept}]} — 변형의 재선정 달에만 기록. score_extra(d, t) = 풀 밖 보유 종목 점수(자기 가격)."""
    out = {}
    for name, (K, months) in variants.items():
        held: list[str] = []
        rows = []
        for d in dates:
            d = pd.Timestamp(d)
            if d.month not in months:
                continue
            ps = pool_scores_by_date[d]
            hs = {}
            for t in held:
                hs[t] = ps[t] if t in ps else score_extra(d, t)
            picks, kept = select_with_buffer(held, ps, hs, K)
            rows.append({"date": d, "picks": picks, "kept": kept})
            held = picks
        out[name] = rows
    return out


def schedule_log(rows: list[dict]) -> list[dict]:
    """champion_weights 용 기록. 재선정마다 균등가중으로 다시 맞추도록 홀짝 번째 기록에 RESET_EPS 만큼 차이를 둔다."""
    out = []
    for j, r in enumerate(rows):
        p = r["picks"]
        f = 1.0 - RESET_EPS * (j % 2)
        out.append({"date": str(pd.Timestamp(r["date"]).date()), "weights": ({t: f / len(p) for t in p} if p else {})})
    return out


def schedule_stats(rows: list[dict], end: pd.Timestamp) -> dict:
    """재선정당 유지·교체 수, 평균 보유 기간(연속 보유 구간, 판정 끝에서 자름)."""
    end = pd.Timestamp(end)
    rows = [r for r in rows if pd.Timestamp(r["date"]) <= end]
    kept_n, new_n, spans = [], [], []
    open_ = {}
    prev: list[str] = []
    for r in rows:
        d = pd.Timestamp(r["date"])
        cur = r["picks"]
        stay = [t for t in cur if t in prev]
        kept_n.append(len(stay))
        new_n.append(len([t for t in cur if t not in prev]))
        for t in prev:
            if t not in cur:
                spans.append((d - open_.pop(t)).days)
        for t in cur:
            open_.setdefault(t, d)
        prev = cur
    spans_all = spans + [(end - d0).days for d0 in open_.values()]
    return {"n_reselections": len(rows), "mean_kept_per_reselection": float(np.mean(kept_n[1:])) if len(kept_n) > 1 else None,
            "kept_per_reselection": kept_n, "mean_new_per_reselection": float(np.mean(new_n[1:])) if len(new_n) > 1 else None,
            "mean_holding_days": float(np.mean(spans_all)) if spans_all else None,
            "mean_holding_days_closed": float(np.mean(spans)) if spans else None, "n_holding_spells": len(spans_all)}


# =================================================================================================
# 판정 (순수 함수)
# =================================================================================================

def decide(diff: float, h1: float, h2: float, mdd_v: float, mdd_0: float, ci_low: float, *, noop: Optional[str] = None,
           observed_ir: Optional[float] = None, power: Optional[dict] = None) -> str:
    """사전 등록 판정(챔피언 수준, 세후 원화). 차이는 소수(0.01 = 1%p), MDD 는 음수."""
    if noop:
        return NOT_EVALUABLE
    vals = (diff, h1, h2, mdd_v, mdd_0, ci_low)
    if any(v is None or not math.isfinite(float(v)) for v in vals):
        return NOT_EVALUABLE
    if diff > 0 and h1 > 0 and h2 > 0 and mdd_v >= mdd_0 - MDD_TOL and ci_low > CI_LOW_FLOOR:
        return PASS
    return rp.classify_fail(observed_ir, power) if power else FAIL


def block_bootstrap_diff(ra, rb, ppy):
    return SV.block_bootstrap_diff(ra, rb, ppy, n_boot=N_BOOT, block=BLOCK_DAYS, seed=BOOT_SEED)


def segments(index: pd.DatetimeIndex) -> dict:
    dec = index[index <= pd.Timestamp(DECISION_END)]
    dec_end = dec[-1]
    h1_end = index[index <= pd.Timestamp(HALF_SPLIT)][-1]
    out = {"judged": (None, dec_end), "h1": (None, h1_end), "h2": (h1_end, dec_end)}
    if index[-1] > dec_end:
        out["post"] = (dec_end, index[-1])
    return out


def pair_stats(va: pd.Series, vb: pd.Series, initial: float, *, with_boot: bool = True) -> dict:
    segs = segments(va.index)
    out = {f"{k}_diff": SV.seg_ann(va, initial, t0, t1) - SV.seg_ann(vb, initial, t0, t1) for k, (t0, t1) in segs.items()}
    dec_end = segs["judged"][1]
    ra, rb = SV.window_returns(va, initial, dec_end), SV.window_returns(vb, initial, dec_end)
    years = (dec_end - va.index[0]).days / 365.25
    ppy = len(ra) / years if years > 0 else 252.0
    d = (ra - rb).to_numpy()
    sd = float(np.std(d, ddof=1)) if len(d) > 1 else float("nan")
    out["daily_diff_ir"] = float(np.mean(d) / sd * math.sqrt(ppy)) if sd and math.isfinite(sd) and sd > 0 else float("nan")
    out["noop_reason"] = rp.noop_guard(d)
    out["judged_years"] = years
    if with_boot and len(d) > 2:
        boot = block_bootstrap_diff(ra.to_numpy(), rb.to_numpy(), ppy)
        lo, hi = np.percentile(boot, CI_PCT)
        out.update({"boot_ci90_low": float(lo), "boot_ci90_high": float(hi), "boot_share_positive": float(np.mean(boot > 0))})
    return out


def annual_turnover(weights: pd.DataFrame, adj: pd.DataFrame, t1: pd.Timestamp) -> float:
    """한쪽 회전율(매수+매도 합 ÷ 2)의 연평균 — tax_fx 처럼 목표가 바뀌는 날에만 매매, 그 사이 표류."""
    w = weights.loc[:t1]
    W = w.to_numpy()
    a = adj.reindex(index=w.index, columns=w.columns).ffill()
    tr = a.pct_change(fill_method=None).fillna(0.0).to_numpy()
    chg = np.r_[True, np.abs(np.diff(W, axis=0)).sum(axis=1) > 1e-9]
    drift = np.zeros(W.shape[1])
    total = 0.0
    for i in range(len(W)):
        if i > 0:
            g = drift * (1 + tr[i])
            port = g.sum() + (1 - drift.sum())
            drift = g / port if port > 0 else drift
        if chg[i]:
            if i > 0:
                total += float(np.abs(W[i] - drift).sum()) / 2
            drift = W[i].copy()
    years = (w.index[-1] - w.index[0]).days / 365.25
    return total / years if years > 0 else float("nan")


# =================================================================================================
# 입력
# =================================================================================================

def score_inputs(data) -> tuple[list, dict, Callable]:
    """S-SEED-000 과 같은 순서·창으로 매 1·7월 재선정일의 풀 점수(추세 활성 후보)와 풀 밖 종목 점수 함수."""
    from core import satellite_lab as sl

    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    signal = sl.load_signal(code)
    params = dict(spec["signal"]["params_grid"][0])
    dates, pool_scores = [], {}
    cutoffs = {}
    for d in sl.rebalance_dates(data.trading_days, spec["portfolio"]["hold_months"]):
        cutoff = sl._prev_day(data.trading_days, d)
        if cutoff is None:
            continue
        members = data.pool(spec["pool"]["type"], d)
        prices = sl._signal_prices(data, members, cutoff, d)
        eligible = {t for t in prices if t in data.closes.columns and pd.notna(data.closes.at[d, t])}
        scores = sl._call_signal(signal, spec, data, {t: prices[t] for t in eligible}, cutoff, params)
        pool_scores[d] = {t: float(v) for t, v in (scores or {}).items()
                          if t in eligible and v is not None and math.isfinite(float(v))}
        dates.append(d)
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

    return dates, pool_scores, score_extra


def _prepare(data, core_w: pd.DataFrame, frames: dict, fx: pd.Series, meta: dict) -> dict:
    dates, pool_scores, score_extra = score_inputs(data)
    scheds = build_schedules(dates, pool_scores, score_extra)
    picks = sorted({t for rows in scheds.values() for r in rows for t in r["picks"]})
    pf = dict(frames)
    pf.update({t: data.ohlcv.get(t) for t in picks})
    close, adj = SV._panel(pf)
    return {"schedules": scheds, "core_w": core_w, "close": close, "adj": adj, "fx": fx,
            "pool_sizes": {str(d.date()): len(pool_scores[d]) for d in dates}, "meta": meta}


def _real_prep(log) -> dict:
    from core import champion_strategy as cs
    from core import satellite_lab as sl
    from core.market_data import get_multiple_price_history

    log("코어 백테스트(일별 목표 비중)")
    core_w = cs.run_core_backtest(START)["weights"]
    pool = SV._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", pool_provider=pool, log=log)
    others = sorted(set(core_w.columns))
    hist = get_multiple_price_history(others, start="2009-06-01", end=None, interval="1d")
    frames = {t: hist.get(t) for t in others}
    fx = tx.usdkrw_series()
    meta = {"live_satellite_weight": cs.SATELLITE_WEIGHT, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
            "judge_version": sl.JUDGE_VERSION, "pool_cache_tag": sl.POOL_CACHE_TAG, "core_universe": list(core_w.columns)}
    return _prepare(data, core_w, frames, fx, meta)


def _smoke_prep(log) -> dict:
    """합성 데이터(네트워크 없음). 실데이터가 아니다."""
    from core import satellite_lab as sl

    end = "2026-06-30"
    pp, poolp = sl.synthetic_providers(n_tickers=50, start="2008-01-01", end=end, seed=11)
    base_pool = SV._pool_wrapper(poolp, date.fromisoformat(START))
    names = sorted(f"T{i:02d}" for i in range(50))

    def pool(pt, d):   # 풀이 해마다 조금씩 바뀌게(풀 밖 보유 종목 규칙도 지나가게)
        m = base_pool(pt, d)
        if not m:
            return m
        k = (d.year * 2 + (d.month >= 7)) % 10
        return names[k:k + 40]
    data = sl.build_data({"champion40"}, start="2009-12-01", end=end, pool_provider=pool, price_provider=pp)
    full = pd.bdate_range("2008-01-01", end)
    rng = np.random.default_rng(5)
    idx = data.trading_days[data.trading_days >= pd.Timestamp(START)]
    frames = {}
    for t in ("C1", "C2"):
        c = 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, len(full))))
        frames[t] = pd.DataFrame({"Close": c, "Adj Close": c * np.exp(np.linspace(0, 0.3, len(full)))}, index=full)
    core_w = pd.DataFrame(0.0, index=idx, columns=["C1", "C2"])
    core_w.loc[core_w.index.month % 2 == 0, "C1"] = 1.0
    core_w.loc[core_w.index.month % 2 == 1, "C2"] = 1.0
    core_w.loc[core_w.index.month == 3, "C2"] = 0.5
    fx = pd.Series(1100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(full)))), index=full)
    return _prepare(data, core_w, frames, fx, {"synthetic": True})


# =================================================================================================
# 분석·보고
# =================================================================================================

def _mdd(v: pd.Series) -> float:
    return float((v / v.cummax() - 1).min())


def sim_summary(s: dict, w: pd.DataFrame, adj: pd.DataFrame, initial: float) -> dict:
    vals = s["values_krw"]
    segs = segments(vals.index)
    dec_end = segs["judged"][1]
    years = {y["year"]: y for y in s["years"]}
    tax_judged = sum(y.get("tax_krw", 0.0) for yr, y in years.items() if yr <= dec_end.year - 1)
    return {"values": vals, "initial": initial, "cagr_judged": SV.seg_ann(vals, initial, None, dec_end),
            "mdd_judged": _mdd(vals.loc[:dec_end]), "cagr_post": SV.seg_ann(vals, initial, *segs["post"]) if "post" in segs else None,
            "final_judged_krw": float(vals.loc[dec_end]), "totals": s["totals"],
            "cg_tax_judged_years_krw": tax_judged,
            "turnover_annual_judged": annual_turnover(w, adj, dec_end)}


def analyze(prep: dict, sims: dict, smoke: bool) -> tuple[dict, str]:
    power = rp.power_report(POWER_YEARS, N_TRIALS)
    dec_end = pd.Timestamp(DECISION_END)
    pairs, verdicts, raw = {}, {}, {}
    for lvl in LEVELS:
        for setup in SETUPS:
            k0 = (lvl, "B0", setup)
            if k0 not in sims:
                continue
            for name in JUDGED:
                kv = (lvl, name, setup)
                if kv in sims:
                    boot = (lvl == "champ" and setup == "base_30m")
                    pairs.setdefault(setup, {}).setdefault(lvl, {})[name] = pair_stats(
                        sims[kv]["values"], sims[k0]["values"], sims[kv]["initial"], with_boot=boot)
    main = pairs["base_30m"]["champ"]
    for name in JUDGED:
        c = main[name]
        sv, s0 = sims[("champ", name, "base_30m")], sims[("champ", "B0", "base_30m")]
        v = decide(c["judged_diff"], c["h1_diff"], c["h2_diff"], sv["mdd_judged"], s0["mdd_judged"],
                   c.get("boot_ci90_low", float("nan")), noop=c["noop_reason"], observed_ir=c["daily_diff_ir"], power=power)
        raw[name] = v
        verdicts[name] = f"SMOKE_ONLY({v})" if smoke else v
    metrics = {}
    for (lvl, name, setup), s in sims.items():
        metrics.setdefault(setup, {}).setdefault(lvl, {})[name] = {k: v for k, v in s.items() if k not in ("values", "initial")}
    sched_stats = {n: schedule_stats(prep["schedules"][n], dec_end) for n in VARIANTS}
    sched_out = {n: [{"date": str(pd.Timestamp(r["date"]).date()), "picks": r["picks"], "kept": r["kept"]}
                     for r in prep["schedules"][n]] for n in VARIANTS}
    v0 = sims[("champ", "B0", "base_30m")]["values"]
    segs = {k: [None if a is None else str(a.date()), str(b.date())] for k, (a, b) in segments(v0.index).items()}
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": str(v0.index[0].date()), "segments": segs,
        "verdicts": verdicts, "verdicts_raw": raw, "pairs": pairs, "metrics": metrics,
        "schedule_stats": sched_stats, "schedules": sched_out, "pool_sizes": prep.get("pool_sizes", {}),
        "power": power, "power_line": rp.power_line(power), "variants": NAMES, "inputs_meta": prep.get("meta", {}),
        "rules": {"top_n": TOP_N, "sat_weight": SAT_WEIGHT, "n_boot": N_BOOT, "block_days": BLOCK_DAYS, "boot_seed": BOOT_SEED,
                  "ci_low_floor": CI_LOW_FLOOR, "mdd_tol": MDD_TOL, "decision_end": DECISION_END, "half_split": HALF_SPLIT,
                  "power_years": POWER_YEARS, "n_trials": N_TRIALS, "reset_eps": RESET_EPS},
    }
    return result, report(result)


def _pct(x, signed=False, nd=1) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _pp(x) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x * 100:+.2f}%p"


def _won(x) -> str:
    return "—" if x is None or not math.isfinite(float(x)) else f"{x / 10_000:,.0f}만 원"


def report(r: dict) -> str:
    sm = " (스모크 — 합성 데이터, 실측 아님)" if r["smoke"] else ""
    m30 = r["metrics"]["base_30m"]
    c30 = m30["champ"]
    p30 = r["pairs"]["base_30m"]["champ"]
    sg = r["segments"]
    L = [f"# 새틀라이트 '이긴 종목 계속 들고 가기'(순위 버퍼){sm}", "",
         "재선정일에 지금 들고 있는 종목이 아직 추세 활성이고 12개월 모멘텀 순위가 상위 K 안이면 팔지 않고 계속 든다. "
         "빈자리만 순위가 가장 높은 새 종목으로 채운다(항상 3종목, 재선정일마다 3종목 균등가중으로 다시 맞춤 — 차이만 매매).",
         "기준선 B0 = 지금 규칙(S-SEED-000: 1·7월마다 상위 3으로 전부 교체).", "",
         f"## 판정(주: 챔피언 = 코어 85% + 새틀라이트 15%, 세후 원화 3,000만 원, 판정 구간 {r['start']} ~ {sg['judged'][1]})", "",
         "| 변형 | 판정 | 세후 연수익 차이 | 앞/뒤 절반 | 부트스트랩 90% | 원화 MDD(본/B0) | 2024-10~ 차이(보고) | 1억 원 차이 |",
         "|---|---|---|---|---|---|---|---|"]
    p100 = r["pairs"].get("base_100m", {}).get("champ", {})
    for n in JUDGED:
        c = p30[n]
        L.append(f"| {n} {NAMES[n]} | **{r['verdicts'][n]}** | {_pp(c['judged_diff'])} | {_pp(c['h1_diff'])} / {_pp(c['h2_diff'])} | "
                 f"{_pp(c.get('boot_ci90_low'))} ~ {_pp(c.get('boot_ci90_high'))} | {_pct(c30[n]['mdd_judged'])} / {_pct(c30['B0']['mdd_judged'])} | "
                 f"{_pp(c.get('post_diff'))} | {_pp(p100.get(n, {}).get('judged_diff'))} |")
    L += ["", f"통과 조건(모두, 챔피언 수준): 판정 구간 세후 연수익 차이 > 0, 앞 절반(~{sg['h1'][1]})·뒤 절반 모두 > 0, "
          f"원화 MDD 가 B0 보다 {MDD_TOL:.0%}p 넘게 나빠지지 않음, 126일 블록 부트스트랩 1,000회(시드 {BOOT_SEED}) 90% 하한 > −0.5%p.",
          f"- {r['power_line']}"]
    for n in JUDGED:
        if p30[n].get("noop_reason"):
            L.append(f"- {n}: 무효 실행 가드 — {p30[n]['noop_reason']}")
    L += ["", "## 세금·회전율·보유 기간(챔피언 수준 3,000만 원, 판정 구간)", "",
          "| 변형 | 세후 연수익 | 양도세(판정 구간 해) | 양도세(전체) | 연 회전율(한쪽) | 평균 보유 일수 | 재선정당 유지 종목 수 |",
          "|---|---|---|---|---|---|---|"]
    for n in VARIANTS:
        m = c30[n]
        st = r["schedule_stats"][n]
        L.append(f"| {n} | {_pct(m['cagr_judged'], nd=2)} | {_won(m['cg_tax_judged_years_krw'])} | {_won(m['totals']['capital_gains_tax_krw'])} | "
                 f"{_pct(m['turnover_annual_judged'], nd=0)} | {st['mean_holding_days'] or 0:.0f}일 | "
                 f"{st['mean_kept_per_reselection'] if st['mean_kept_per_reselection'] is not None else float('nan'):.2f} |")
    L += ["", "B0 의 '유지 종목 수'는 규칙 없이 우연히 다시 뽑힌 수다. 양도세(판정 구간 해) = 판정 끝 해 전년도까지 확정된 세금.", "",
          "## 보조: 새틀라이트 3종목만 100%(세후 원화 3,000만 원, 판정 구간)", "",
          "| 변형 | 세후 연수익 | 원화 MDD | B0 대비 | 앞/뒤 절반 | 연 회전율 | 양도세(전체) |", "|---|---|---|---|---|---|---|"]
    s30 = m30.get("sleeve", {})
    ps = r["pairs"]["base_30m"].get("sleeve", {})
    for n in VARIANTS:
        m = s30.get(n, {})
        p = ps.get(n, {})
        L.append(f"| {n} | {_pct(m.get('cagr_judged'), nd=2)} | {_pct(m.get('mdd_judged'))} | {_pp(p.get('judged_diff'))} | "
                 f"{_pp(p.get('h1_diff'))} / {_pp(p.get('h2_diff'))} | {_pct(m.get('turnover_annual_judged'), nd=0)} | "
                 f"{_won((m.get('totals') or {}).get('capital_gains_tax_krw', float('nan')))} |")
    L += ["", "## 이것이 증명하는 것과 증명하지 못하는 것", "",
          "- 미국 시장 한 경로(2010~2024)의 과거 결과다. 같은 일이 앞으로 반복된다는 보장은 없다.",
          "- 생존편향: 상장폐지 종목은 가격 소스에 없어 후보에서 빠진다. 풀(champion40 시점 기준)은 시점 기준이지만 가격은 살아남은 종목 위주다.",
          "- 이미 본 데이터: 2010~2024 는 다른 새틀라이트 연구들(sat-exit-ladder-v1·sat-pool-v1 등)이 여러 번 본 기간이다. "
          "그래서 PASS 도 '전진 원장에 올릴 후보'일 뿐 채택이 아니다. 2024-10 이후는 보고만 한다.",
          "- 풀 밖으로 빠진 보유 종목은 자기 가격으로 추세 활성·순위(그날 풀 후보와 비교)를 계산해 조건을 채울 때만 유지한다. 가격이 없으면 교체.",
          "- 세금은 한국 해외주식 양도소득세(연 250만 원 공제, 22%, 이월 없음)와 카카오페이증권 기본 가정(`core/tax_fx.py`). 실제 계좌와 다를 수 있다.",
          "- 엔진(챔피언)은 바뀌지 않았다. 반영은 사용자 확인 뒤 별도 작업이다.", ""]
    return "\n".join(L)


def smoke_coverage(r: dict) -> dict:
    st = r["schedule_stats"]
    sch = r["schedules"]
    return {"kept_some": any((st[n]["mean_kept_per_reselection"] or 0) > 0 for n in JUDGED),
            "h12_january_only": all(pd.Timestamp(x["date"]).month == 1 for n in ("K6_H12", "K10_H12") for x in sch[n]),
            "verdicts": len(r["verdicts"]) == len(JUDGED),
            "tax_engine": "capital_gains_tax_krw" in r["metrics"]["base_30m"]["champ"]["B0"]["totals"],
            "sleeve": len(r["metrics"]["base_30m"].get("sleeve", {})) == len(VARIANTS)}


# =================================================================================================
# 실행
# =================================================================================================

def _weights(prep: dict, lvl: str, name: str) -> pd.DataFrame:
    core = prep["core_w"] if lvl == "champ" else pd.DataFrame(0.0, index=prep["core_w"].index, columns=prep["core_w"].columns)
    w = tx.champion_weights(core, schedule_log(prep["schedules"][name]), SAT_WEIGHT if lvl == "champ" else 1.0)
    return w.loc[:, w.abs().sum() > 0]


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
        jobs = [(lvl, n, "base_30m") for lvl in LEVELS for n in VARIANTS] + [("champ", n, "base_100m") for n in VARIANTS]
        sims = {}
        for key in jobs:
            lvl, name, setup = key
            path = ck / f"sim_{lvl}_{name}_{setup}.pkl"
            got = SV._load_ckpt(path, fp)
            if got is None:
                step()
                w = _weights(prep, lvl, name)
                cfg = tx.AccountConfig(**SETUPS[setup])
                s = tx.simulate(w, prep["close"], prep["adj"], prep["fx"], cfg)
                got = sim_summary(s, w, prep["adj"], cfg.initial_krw)
                SV._atomic_pickle(path, {"fingerprint": fp, "payload": got})
                log(f"시뮬레이션 {key} 판정 구간 세후 {got['cagr_judged']:.4f}")
            sims[key] = got
        result, rep = analyze(prep, sims, a.smoke)
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
