"""검증 sat-stagger-v1 (2026-10-15 사전 등록): 새틀라이트를 엇갈린 달에 재선정하는 하위 슬리브로 나누면 타이밍 운이 줄어드는가.

사용자 요청(2026-10-15): 새틀라이트는 1·7월 첫 거래일에만 산다. 그 하루가 반년을 좌우하고 큰 실패가 특정 재선정일에 몰린다.
가설: 15% 를 서로 다른 달에 재선정하는 하위 슬리브로 나누면 수익을 잃지 않고 날짜 운(분산)이 줄어든다.

규칙 전체는 SPEC.md(한국어)에 고정. 판정 기준을 바꾸려면 새 id 로 다시 등록한다. 엔진(챔피언) 반영은 사용자 확인 뒤 별도 작업이다.
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

JOB_ID = "sat-stagger-v1"
RULES_VERSION = "sat-stagger-v1/2026-10-15"
START = "2010-01-01"              # 모든 변형의 시뮬레이션 시작 = 2010-01 첫 거래일(아직 시작 안 한 하위 슬리브는 현금)
JUDGE_START = "2010-07-01"        # 판정 구간 시작(모든 하위 슬리브가 투자된 뒤 첫 날 — 이 날 이후 첫 거래일)
DECISION_END = "2024-09-30"       # 판정 구간 끝(포함). 이후는 보고만
HALF_SPLIT = "2017-05-31"
SAT_WEIGHT = 0.15
ROLL_DAYS = 126                   # 새틀라이트 슬리브 롤링 수익 창(거래일)
DIFF_FLOOR = -0.003               # (a)(b) 세후 연수익 차이 ≥ −0.3%p
SD_REDUCTION = 0.20               # (c) 롤링 126일 수익 표준편차가 G1 보다 20% 이상 낮음
MDD_TOL = 0.01                    # (e) 챔피언 원화 MDD 가 1%p 넘게 나빠지지 않음
POWER_YEARS = 14.2
N_TRIALS = 2
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"

# 변형 = 하위 슬리브들의 재선정 달(각 슬리브는 새틀라이트의 1/n)
SLEEVES = {"G1": ((1, 7),), "G2": ((1, 7), (4, 10)), "G3": ((1, 7), (3, 9), (5, 11))}
JUDGED = ("G2", "G3")
VARIANTS = ("G1",) + JUDGED
# 타이밍 운 진단(보고만): 단일 슬리브를 시작 달 1~6월로. P1 = G1
PHASES = {f"P{m}": ((m, m + 6),) for m in range(1, 7)}
NAMES = {"G1": "현행: 한 슬리브 15%, 1·7월", "G2": "두 하위 슬리브 7.5%씩: 1·7월 + 4·10월",
         "G3": "세 하위 슬리브 5%씩: 1·7월 + 3·9월 + 5·11월"}
SETUPS = {"base_30m": {}, "base_100m": {"initial_krw": 100_000_000}}


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SV = _load("satellite_value_v1_for_stagger", "research/jobs/satellite-value-v1/run.py")
BUF = _load("sat_buffer_v1_for_stagger", "research/jobs/sat-buffer-v1/run.py")


# =================================================================================================
# 일정 (순수 함수 — tests/test_sat_stagger.py)
# =================================================================================================

def sim_dates(trading_days: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """START 이후 매월 첫 거래일(전날이 있는 날만) — 하위 슬리브 재선정 후보일."""
    from core import satellite_lab as sl

    return [d for d in sl.rebalance_dates(trading_days, 1)
            if d >= pd.Timestamp(START) and sl._prev_day(trading_days, d) is not None]


def sleeve_dates(dates: list, months: tuple) -> list[pd.Timestamp]:
    return [pd.Timestamp(d) for d in dates if pd.Timestamp(d).month in months]


def picks_by_date(data, dates: list) -> dict:
    """S-SEED-000 을 각 날짜에 그대로 적용(sl.run_variant 안쪽 루프와 같은 식): 그날 풀, 전날까지 신호, 상위 3."""
    from core import satellite_lab as sl

    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    signal = sl.load_signal(code)
    params = dict(spec["signal"]["params_grid"][0])
    k = spec["portfolio"]["top_k"]
    out = {}
    for d in dates:
        d = pd.Timestamp(d)
        cutoff = sl._prev_day(data.trading_days, d)
        members = data.pool(spec["pool"]["type"], d)
        prices = sl._signal_prices(data, members, cutoff, d)
        eligible = {t for t in prices if t in data.closes.columns and pd.notna(data.closes.at[d, t])}
        scores = sl._call_signal(signal, spec, data, {t: prices[t] for t in eligible}, cutoff, params)
        out[d] = sl.pick_top(scores, k, eligible)
    return out


def combined_log(picks: dict, sleeves: tuple, dates: list) -> list[dict]:
    """하위 슬리브 합산 기록(champion_weights 용, 새틀라이트 안 비중 합 ≤ 1).
    각 슬리브 = 1/n, 자기 재선정 달에 그날 S-SEED-000 상위 3 균등. 겹치는 종목은 비중을 더한다.
    첫 재선정 전 슬리브·빈 선정은 현금. 기록은 시작일(dates[0])과 어느 슬리브든 재선정하는 날마다."""
    dates = [pd.Timestamp(d) for d in dates]
    n = len(sleeves)
    cur: list[Optional[list]] = [None] * n
    out = []
    for i, d in enumerate(dates):
        upd = False
        for k, months in enumerate(sleeves):
            if d.month in months:
                cur[k] = list(picks[d])
                upd = True
        if not upd and i > 0:
            continue
        w: dict[str, float] = {}
        for p in cur:
            if p:
                for t in p:
                    w[t] = w.get(t, 0.0) + (1.0 / n) / len(p)
        out.append({"date": str(d.date()), "weights": w})
    return out


def gross_values(weights: pd.DataFrame, adj: pd.DataFrame) -> pd.Series:
    """세전·비용 전 달러 가치(1 에서 시작). tax_fx 와 같은 규약: 목표가 바뀌는 날 그날 종가에 맞추고 그 사이 표류, 나머지는 현금(0%)."""
    W = weights.to_numpy(dtype=float)
    a = adj.reindex(index=weights.index, columns=weights.columns).ffill()
    tr = a.pct_change(fill_method=None).fillna(0.0).to_numpy()
    chg = np.r_[True, np.abs(np.diff(W, axis=0)).sum(axis=1) > 1e-9]
    drift = W[0].copy()
    v, vals = 1.0, []
    for i in range(len(W)):
        if i > 0:
            g = drift * (1 + tr[i])
            port = g.sum() + (1 - drift.sum())
            v *= port
            drift = g / port if port > 0 else drift
        if chg[i]:
            drift = W[i].copy()
        vals.append(v)
    return pd.Series(vals, index=weights.index)


def rolling_stats(values: pd.Series, t0: pd.Timestamp, t1: pd.Timestamp, window: int = ROLL_DAYS) -> dict:
    """[t0, t1] 안 가치로 롤링 window 거래일 수익 v[t]/v[t−window] − 1 의 표준편차(ddof=1)·최솟값·최댓값·개수."""
    v = values.loc[t0:t1]
    r = (v / v.shift(window) - 1.0).dropna()
    if len(r) < 2:
        return {"sd": float("nan"), "worst": float("nan"), "best": float("nan"), "n": int(len(r))}
    return {"sd": float(r.std(ddof=1)), "worst": float(r.min()), "best": float(r.max()), "n": int(len(r)),
            "worst_end": str(r.idxmin().date())}


# =================================================================================================
# 판정 (순수 함수)
# =================================================================================================

def decide(diff, h1, h2, sd_v, sd_0, worst_v, worst_0, mdd_v, mdd_0, *, noop: Optional[str] = None,
           observed_ir: Optional[float] = None, power: Optional[dict] = None) -> str:
    """사전 등록 판정 vs G1. 차이는 소수(0.01 = 1%p), MDD·worst 는 음수 가능."""
    if noop:
        return NOT_EVALUABLE
    vals = (diff, h1, h2, sd_v, sd_0, worst_v, worst_0, mdd_v, mdd_0)
    if any(v is None or not math.isfinite(float(v)) for v in vals) or sd_0 <= 0:
        return NOT_EVALUABLE
    ok = (diff >= DIFF_FLOOR and h1 >= DIFF_FLOOR and h2 >= DIFF_FLOOR
          and sd_v <= (1 - SD_REDUCTION) * sd_0 and worst_v > worst_0 and mdd_v >= mdd_0 - MDD_TOL)
    if ok:
        return PASS
    return rp.classify_fail(observed_ir, power) if power else FAIL


def segments(index: pd.DatetimeIndex) -> dict:
    j0 = index[index >= pd.Timestamp(JUDGE_START)][0]
    dec_end = index[index <= pd.Timestamp(DECISION_END)][-1]
    h1_end = index[index <= pd.Timestamp(HALF_SPLIT)][-1]
    out = {"judged": (j0, dec_end), "h1": (j0, h1_end), "h2": (h1_end, dec_end)}
    if index[-1] > dec_end:
        out["post"] = (dec_end, index[-1])
    return out


def _mdd(v: pd.Series) -> float:
    return float((v / v.cummax() - 1).min())


def pair_stats(va: pd.Series, vb: pd.Series, initial: float) -> dict:
    segs = segments(va.index)
    out = {f"{k}_diff": SV.seg_ann(va, initial, t0, t1) - SV.seg_ann(vb, initial, t0, t1) for k, (t0, t1) in segs.items()}
    j0, j1 = segs["judged"]
    ra, rb = va.loc[j0:j1].pct_change().dropna(), vb.loc[j0:j1].pct_change().dropna()
    years = (j1 - j0).days / 365.25
    ppy = len(ra) / years if years > 0 else 252.0
    d = (ra - rb).to_numpy()
    sd = float(np.std(d, ddof=1)) if len(d) > 1 else float("nan")
    out["daily_diff_ir"] = float(np.mean(d) / sd * math.sqrt(ppy)) if sd and math.isfinite(sd) and sd > 0 else float("nan")
    out["noop_reason"] = rp.noop_guard(d)
    out["judged_years"] = years
    return out


def sim_summary(s: dict, w: pd.DataFrame, adj: pd.DataFrame, initial: float) -> dict:
    vals = s["values_krw"]
    segs = segments(vals.index)
    j0, j1 = segs["judged"]
    years = {y["year"]: y for y in s["years"]}
    return {"values": vals, "initial": initial, "ann_judged": SV.seg_ann(vals, initial, j0, j1),
            "mdd_judged": _mdd(vals.loc[j0:j1]),
            "ann_post": SV.seg_ann(vals, initial, *segs["post"]) if "post" in segs else None,
            "totals": s["totals"],
            "cg_tax_judged_years_krw": sum(y.get("tax_krw", 0.0) for yr, y in years.items() if j0.year <= yr <= j1.year - 1),
            "turnover_annual_judged": BUF.annual_turnover(w.loc[j0:], adj, j1)}


# =================================================================================================
# 입력
# =================================================================================================

def _prepare(data, core_w: pd.DataFrame, frames: dict, fx: pd.Series, meta: dict) -> dict:
    dates = sim_dates(data.trading_days)
    picks = picks_by_date(data, dates)
    logs = {n: combined_log(picks, sl_, dates) for n, sl_ in {**SLEEVES, **PHASES}.items()}
    names = sorted({t for p in picks.values() for t in p})
    pf = dict(frames)
    pf.update({t: data.ohlcv.get(t) for t in names})
    close, adj = SV._panel(pf)
    return {"dates": dates, "picks": picks, "logs": logs, "core_w": core_w, "close": close, "adj": adj, "fx": fx,
            "meta": meta}


def _real_prep(log) -> dict:
    from core import champion_strategy as cs
    from core import satellite_lab as sl
    from core.market_data import get_multiple_price_history

    log("코어 백테스트(일별 목표 비중)")
    core_w = cs.run_core_backtest(START)["weights"]
    pool = SV._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", pool_provider=pool, log=log)
    others = sorted(set(core_w.columns) | {"SPY"})
    hist = get_multiple_price_history(others, start="2009-06-01", end=None, interval="1d")
    frames = {t: hist.get(t) for t in others}
    meta = {"live_satellite_weight": cs.SATELLITE_WEIGHT, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
            "judge_version": sl.JUDGE_VERSION, "pool_cache_tag": sl.POOL_CACHE_TAG, "core_universe": list(core_w.columns)}
    return _prepare(data, core_w, frames, tx.usdkrw_series(), meta)


def _smoke_prep(log) -> dict:
    """합성 데이터(네트워크 없음). 실데이터가 아니다."""
    from core import satellite_lab as sl

    end = "2026-06-30"
    pp, poolp = sl.synthetic_providers(n_tickers=40, start="2008-01-01", end=end, seed=11)
    pool = SV._pool_wrapper(poolp, date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", end=end, pool_provider=pool, price_provider=pp)
    full = pd.bdate_range("2008-01-01", end)
    rng = np.random.default_rng(5)
    idx = data.trading_days[data.trading_days >= pd.Timestamp(START)]
    frames = {}
    for t in ("C1", "C2", "SPY"):
        c = 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, len(full))))
        frames[t] = pd.DataFrame({"Close": c, "Adj Close": c * np.exp(np.linspace(0, 0.3, len(full)))}, index=full)
    core_w = pd.DataFrame(0.0, index=idx, columns=["C1", "C2"])
    core_w.loc[core_w.index.month % 2 == 0, "C1"] = 1.0
    core_w.loc[core_w.index.month % 2 == 1, "C2"] = 1.0
    fx = pd.Series(1100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(full)))), index=full)
    return _prepare(data, core_w, frames, fx, {"synthetic": True})


def _weights(prep: dict, lvl: str, name: str) -> pd.DataFrame:
    core = prep["core_w"]
    if lvl == "champ":
        w = tx.champion_weights(core, prep["logs"][name], SAT_WEIGHT)
    else:
        zero = pd.DataFrame(0.0, index=core.index, columns=core.columns)
        if name == "SPY":
            idx = tx.champion_weights(zero, prep["logs"]["G1"], 1.0).index
            return tx.buy_and_hold_weights(idx)
        w = tx.champion_weights(zero, prep["logs"][name], 1.0)
    return w.loc[:, w.abs().sum() > 0]


def sim_jobs() -> list[tuple]:
    phases = [p for p in PHASES if p != "P1"]
    return ([("champ", n, "base_30m") for n in VARIANTS + tuple(phases)]
            + [("sleeve", n, "base_30m") for n in VARIANTS + ("SPY",)]
            + [("champ", n, "base_100m") for n in VARIANTS])


# =================================================================================================
# 분석·보고
# =================================================================================================

def _spread(xs: list) -> dict:
    a = np.array([x for x in xs if x is not None and math.isfinite(x)], dtype=float)
    if not len(a):
        return {"min": None, "median": None, "max": None, "range": None}
    return {"min": float(a.min()), "median": float(np.median(a)), "max": float(a.max()), "range": float(a.max() - a.min())}


def analyze(prep: dict, sims: dict, smoke: bool) -> tuple[dict, str]:
    power = rp.power_report(POWER_YEARS, N_TRIALS)
    base = sims[("champ", "G1", "base_30m")]
    segs = segments(base["values"].index)
    j0, j1 = segs["judged"]
    # 새틀라이트 슬리브(세전·비용 전 달러) 롤링 126일 수익
    roll = {}
    for n in VARIANTS + tuple(PHASES):
        if n == "P1":
            continue
        zero = pd.DataFrame(0.0, index=prep["core_w"].index, columns=prep["core_w"].columns)
        w = tx.champion_weights(zero, prep["logs"][n], 1.0)
        w = w.loc[:, w.abs().sum() > 0]
        roll[n] = rolling_stats(gross_values(w, prep["adj"]), j0, j1)
    roll["P1"] = roll["G1"]
    pairs = {setup: {lvl: {} for lvl in ("champ", "sleeve")} for setup in SETUPS}
    for (lvl, name, setup), s in sims.items():
        k0 = (lvl, "G1", setup)
        if name in JUDGED + ("SPY",) and k0 in sims:
            pairs[setup][lvl][name] = pair_stats(s["values"], sims[k0]["values"], s["initial"])
    for n in VARIANTS:
        k = ("sleeve", n, "base_30m")
        if k in sims and ("sleeve", "SPY", "base_30m") in sims:
            pairs["base_30m"]["sleeve"][f"{n}_vs_SPY"] = pair_stats(sims[k]["values"], sims[("sleeve", "SPY", "base_30m")]["values"],
                                                                     sims[k]["initial"])
    main = pairs["base_30m"]["champ"]
    verdicts, raw, checks = {}, {}, {}
    for n in JUDGED:
        c, sv = main[n], sims[("champ", n, "base_30m")]
        args = (c["judged_diff"], c["h1_diff"], c["h2_diff"], roll[n]["sd"], roll["G1"]["sd"], roll[n]["worst"],
                roll["G1"]["worst"], sv["mdd_judged"], base["mdd_judged"])
        v = decide(*args, noop=c["noop_reason"], observed_ir=c["daily_diff_ir"], power=power)
        checks[n] = {"a_diff": args[0] >= DIFF_FLOOR, "b_halves": args[1] >= DIFF_FLOOR and args[2] >= DIFF_FLOOR,
                     "c_sd_reduction": (1 - args[3] / args[4]) if args[4] else None,
                     "c_ok": args[3] <= (1 - SD_REDUCTION) * args[4], "d_worst_ok": args[5] > args[6],
                     "e_mdd_ok": args[7] >= args[8] - MDD_TOL}
        raw[n] = v
        verdicts[n] = f"SMOKE_ONLY({v})" if smoke else v
    ph = {p: {"ann_judged": (sims[("champ", "G1" if p == "P1" else p, "base_30m")]["ann_judged"]),
              "mdd_judged": sims[("champ", "G1" if p == "P1" else p, "base_30m")]["mdd_judged"],
              "sleeve_roll_sd": roll[p]["sd"], "sleeve_roll_worst": roll[p]["worst"]} for p in PHASES}
    phase_diag = {"per_phase": ph, "ann_spread": _spread([x["ann_judged"] for x in ph.values()]),
                  "mdd_spread": _spread([x["mdd_judged"] for x in ph.values()])}
    metrics = {}
    for (lvl, name, setup), s in sims.items():
        metrics.setdefault(setup, {}).setdefault(lvl, {})[name] = {k: v for k, v in s.items() if k not in ("values", "initial")}
    # 겹침: 한 종목 비중이 슬리브 하나 몫(1/n ÷ 3)보다 큰 기록 수 = 두 슬리브 이상이 같은 종목을 든 때
    overlap = {n: sum(1 for r in prep["logs"][n] if any(w > (1.0 / len(SLEEVES[n])) / 3 + 1e-12 for w in r["weights"].values()))
               for n in JUDGED}
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": str(base["values"].index[0].date()),
        "segments": {k: [str(a.date()), str(b.date())] for k, (a, b) in segs.items()},
        "verdicts": verdicts, "verdicts_raw": raw, "checks": checks, "pairs": pairs, "metrics": metrics,
        "sleeve_rolling": roll, "phase_diagnostic": phase_diag, "overlap_log_entries": overlap,
        "picks": {str(d.date()): p for d, p in prep["picks"].items()},
        "power": power, "power_line": rp.power_line(power), "variants": NAMES, "inputs_meta": prep.get("meta", {}),
        "rules": {"sleeves": {k: [list(m) for m in v] for k, v in SLEEVES.items()}, "sat_weight": SAT_WEIGHT,
                  "roll_days": ROLL_DAYS, "diff_floor": DIFF_FLOOR, "sd_reduction": SD_REDUCTION, "mdd_tol": MDD_TOL,
                  "judge_start": JUDGE_START, "decision_end": DECISION_END, "half_split": HALF_SPLIT,
                  "power_years": POWER_YEARS, "n_trials": N_TRIALS},
    }
    return result, report(result)


_pct, _pp, _won = BUF._pct, BUF._pp, BUF._won


def report(r: dict) -> str:
    sm = " (스모크 — 합성 데이터, 실측 아님)" if r["smoke"] else ""
    sg = r["segments"]
    c30 = r["metrics"]["base_30m"]["champ"]
    p30 = r["pairs"]["base_30m"]["champ"]
    p100 = r["pairs"].get("base_100m", {}).get("champ", {})
    ro = r["sleeve_rolling"]
    L = [f"# 새틀라이트 엇갈린 재선정(하위 슬리브 나누기){sm}", "",
         "새틀라이트 15% 를 서로 다른 달에 재선정하는 하위 슬리브로 나눈다. 각 하위 슬리브는 지금 규칙(S-SEED-000: 그날 champion40 풀, "
         "돈치안 20일 추세 활성, 12개월 모멘텀 상위 3, 균등, 6개월 보유, 중간 매도 없음)을 자기 재선정일에 그대로 쓴다. 겹치는 종목은 비중을 더한다.",
         "기준선 G1 = 지금 규칙(한 슬리브, 1·7월).", "",
         f"## 판정(챔피언 = 코어 85% + 새틀라이트 15%, 세후 원화 3,000만 원, 판정 구간 {sg['judged'][0]} ~ {sg['judged'][1]})", "",
         "| 변형 | 판정 | 세후 연수익 차이 | 앞/뒤 절반 | 슬리브 126일 수익 표준편차(본/G1) | 최악 126일(본/G1) | 원화 MDD(본/G1) | 2024-10~(보고) | 1억 원 차이 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for n in JUDGED:
        c = p30[n]
        L.append(f"| {n} {NAMES[n]} | **{r['verdicts'][n]}** | {_pp(c['judged_diff'])} | {_pp(c['h1_diff'])} / {_pp(c['h2_diff'])} | "
                 f"{_pct(ro[n]['sd'])} / {_pct(ro['G1']['sd'])} | {_pct(ro[n]['worst'])} / {_pct(ro['G1']['worst'])} | "
                 f"{_pct(c30[n]['mdd_judged'])} / {_pct(c30['G1']['mdd_judged'])} | {_pp(c.get('post_diff'))} | "
                 f"{_pp(p100.get(n, {}).get('judged_diff'))} |")
    L += ["", f"통과 조건(모두, G1 대비): (a) 판정 구간 세후 연수익 차이 ≥ −0.3%p, (b) 앞 절반(~{sg['h1'][1]})·뒤 절반 모두 ≥ −0.3%p, "
          "(c) 새틀라이트 슬리브의 롤링 126거래일 수익 표준편차가 G1 보다 20% 이상 낮음, (d) 최악 롤링 126일 수익이 G1 보다 나음, "
          "(e) 챔피언 원화 MDD 가 1%p 넘게 나빠지지 않음. (c)(d)는 세전·비용 전 달러 슬리브 가치로 잰다.",
          f"- {r['power_line']} (c)(d)는 IR 검정이 아니므로 이 검정력은 (a)(b) 쪽에만 해당한다."]
    for n in JUDGED:
        if p30[n].get("noop_reason"):
            L.append(f"- {n}: 무효 실행 가드 — {p30[n]['noop_reason']}")
    pd_ = r["phase_diagnostic"]
    L += ["", "## 타이밍 운 진단(보고만): 지금 규칙을 시작 달만 바꿔(1·7월 … 6·12월) 돌리면", "",
          "| 시작 달 | 챔피언 세후 연수익 | 원화 MDD | 슬리브 126일 표준편차 | 최악 126일 |", "|---|---|---|---|---|"]
    for p, x in pd_["per_phase"].items():
        m = int(p[1:])
        L.append(f"| {m}·{m + 6}월 | {_pct(x['ann_judged'], nd=2)} | {_pct(x['mdd_judged'])} | {_pct(x['sleeve_roll_sd'])} | {_pct(x['sleeve_roll_worst'])} |")
    a, d = pd_["ann_spread"], pd_["mdd_spread"]
    L += ["", f"재선정 날짜만 바꿨을 때 챔피언 세후 연수익: 최소 {_pct(a['min'], nd=2)} · 중앙 {_pct(a['median'], nd=2)} · 최대 {_pct(a['max'], nd=2)} "
          f"(폭 {_pp(a['range'])}). 원화 MDD: 최소 {_pct(d['min'])} · 중앙 {_pct(d['median'])} · 최대 {_pct(d['max'])}.",
          "", "## 보조: 새틀라이트 슬리브만 100%(세후 원화 3,000만 원, 판정 구간)", "",
          "| 변형 | 세후 연수익 | 원화 MDD | G1 대비 | SPY 대비 | 연 회전율(한쪽) | 양도세(판정 구간 해) |", "|---|---|---|---|---|---|---|"]
    s30 = r["metrics"]["base_30m"].get("sleeve", {})
    ps = r["pairs"]["base_30m"].get("sleeve", {})
    for n in VARIANTS + ("SPY",):
        m = s30.get(n, {})
        L.append(f"| {n} | {_pct(m.get('ann_judged'), nd=2)} | {_pct(m.get('mdd_judged'))} | {_pp(ps.get(n, {}).get('judged_diff'))} | "
                 f"{_pp(ps.get(f'{n}_vs_SPY', {}).get('judged_diff'))} | {_pct(m.get('turnover_annual_judged'), nd=0)} | "
                 f"{_won(m.get('cg_tax_judged_years_krw', float('nan')))} |")
    L += ["", "## 세금·회전율(챔피언 수준 3,000만 원)", "", "| 변형 | 세후 연수익 | 양도세(판정 구간 해) | 양도세(전체) | 연 회전율(한쪽) |",
          "|---|---|---|---|---|"]
    for n in VARIANTS:
        m = c30[n]
        L.append(f"| {n} | {_pct(m['ann_judged'], nd=2)} | {_won(m['cg_tax_judged_years_krw'])} | "
                 f"{_won(m['totals']['capital_gains_tax_krw'])} | {_pct(m['turnover_annual_judged'], nd=0)} |")
    L += ["", "## 이것이 증명하는 것과 증명하지 못하는 것", "",
          "- 미국 시장 한 경로(2010~2024)의 과거 결과다. 앞으로 같다는 보장은 없다.",
          "- 생존편향: 상장폐지 종목은 가격 소스에 없어 후보에서 빠진다. 풀(champion40)은 시점 기준이지만 가격은 살아남은 종목 위주다.",
          "- champion40 풀은 엔진처럼 반기(1/1·7/1) 기준으로만 갱신된다. 3·4·5·9·10·11월 하위 슬리브는 직전 1/1·7/1 풀에서 고른다(신호는 그날 전날까지의 가격).",
          "- 코어의 4분할 시차 리밸런싱(core-rnd-v2 C02)은 FAIL 이었다: 매달 갱신되는 코어 신호에서는 나누면 신호가 늦게 반영될 뿐 이득이 없었다. "
          "새틀라이트는 6개월에 한 번 사서 그대로 들고 가므로 재선정일 한 날의 운이 반년을 좌우한다 — 그래서 결과가 다를 수 있다고 보고 따로 시험한다. 같다는 보장은 없다.",
          "- 하위 슬리브 하나가 재선정하는 날 다른 슬리브도 각자 목표 비중(1/n, 종목 균등)으로 다시 맞춰진다(기존 tax_fx 규약: 목표가 바뀌는 날 전체를 목표로 맞춤). 종목을 바꾸지는 않는다.",
          "- 이미 본 데이터: 2010~2024 는 여러 새틀라이트 연구가 이미 본 기간이다. PASS 도 '전진 원장에 올릴 후보'일 뿐 채택이 아니다. 2024-10 이후는 보고만.",
          "- 세금은 한국 해외주식 양도소득세(연 250만 원 공제, 22%)와 카카오페이증권 기본 가정(`core/tax_fx.py`). 실제 계좌와 다를 수 있다.",
          "- 엔진(챔피언)은 바뀌지 않았다. 반영은 사용자 확인 뒤 별도 작업이다.", ""]
    return "\n".join(L)


def smoke_coverage(r: dict, prep: dict) -> dict:
    g3_first = prep["logs"]["G3"][0]["weights"]
    return {"verdicts": len(r["verdicts"]) == len(JUDGED),
            "phases": len(r["phase_diagnostic"]["per_phase"]) == 6
            and all(math.isfinite(x["ann_judged"]) for x in r["phase_diagnostic"]["per_phase"].values()),
            "sub_sleeves_start_in_cash": 0 < sum(g3_first.values()) < 0.5,
            "tax_engine": "capital_gains_tax_krw" in r["metrics"]["base_30m"]["champ"]["G1"]["totals"],
            "sleeve_vs_spy": "G1_vs_SPY" in r["pairs"]["base_30m"]["sleeve"],
            "rolling": all(math.isfinite(r["sleeve_rolling"][n]["sd"]) for n in VARIANTS)}


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
        sims = {}
        for key in sim_jobs():
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
                log(f"시뮬레이션 {key} 판정 구간 세후 {got['ann_judged']:.4f}")
            sims[key] = got
        result, rep = analyze(prep, sims, a.smoke)
        if a.smoke:
            cov = smoke_coverage(result, prep)
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
