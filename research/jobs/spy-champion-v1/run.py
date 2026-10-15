"""검증 spy-champion-v1 (2026-10-15 사전 등록): 코어 대신 SPY 를 바탕에 두고 새틀라이트를 얹으면 현 챔피언보다 나은가.

사용자 요청(2026-10-15): 지금까지의 증거로는 새틀라이트(모멘텀 종목 6개월 보유)가 수익 엔진이고, ETF 코어는 주로 방어하면서
세금·수수료로 연 약 2%p 를 쓰며 2008 이후 확인된 초과 수익이 없다. SPY 그냥 보유는 한국 세금 뒤에도 강하다(실현 이익 없음).
시험하지 않은 조합: SPY 바탕 + 새틀라이트(+ 폭락 방어용 작은 코어).

규칙 전체는 SPEC.md(한국어)에 고정. 판정 기준을 바꾸려면 새 id 로 다시 등록한다. 엔진 반영은 사용자 확인 뒤 별도 작업이다.
satellite-value-v1 의 입력 구성·통계 함수를 import 해서 그대로 쓴다(챔피언 = 그 연구의 A 와 같은 목표 비중).
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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "spy-champion-v1"
RULES_VERSION = "spy-champion-v1/2026-10-15"
START = "2010-01-01"
CHAMP_SAT_WEIGHT = 0.15

# 구간(각 구간은 새 계좌) — 시작·끝은 그 날 이후 첫 / 그 날 이전 마지막 거래일
WINDOWS = {"judged": ("2010-01-04", "2024-09-30"), "h1": ("2010-01-04", "2017-05-31"),
           "h2": ("2017-06-01", "2024-09-30"), "post": ("2024-10-01", None)}
JUDGED_WINDOWS = ("judged", "h1", "h2")

# 후보(SPY, 새틀라이트, 코어 목표 비중)
CANDIDATES = {"P1": (0.85, 0.15, 0.0), "P2": (0.80, 0.20, 0.0), "P3": (0.70, 0.30, 0.0),
              "P4": (0.50, 0.30, 0.20), "P5": (0.40, 0.40, 0.20)}
REFS = ("CHAMP", "SPY")
PORTFOLIOS = tuple(CANDIDATES) + REFS
NAMES = {"P1": "SPY 85% + 새틀라이트 15%", "P2": "SPY 80% + 새틀라이트 20%", "P3": "SPY 70% + 새틀라이트 30%",
         "P4": "SPY 50% + 새틀라이트 30% + 코어 20%", "P5": "SPY 40% + 새틀라이트 40% + 코어 20%",
         "CHAMP": "현 챔피언(코어 85% + 새틀라이트 15%, 참고)", "SPY": "SPY 그냥 보유(참고)"}
SETUPS = {"base_30m": {}, "base_100m": {"initial_krw": 100_000_000}}
DECISION_SETUP = "base_30m"

# 판정(사전 등록)
MIN_DIFF_CHAMP = 0.010        # (a) +1.0%p
CI_LOW_FLOOR = -0.005         # (d) 90% 하한 > −0.5%p
SPY_MARGIN = 0.005            # BEATS_SPY: +0.5%p
N_BOOT = 1000
BLOCK_DAYS = 126
BOOT_SEED = 20261016
CI_PCT = (5.0, 95.0)
POWER_YEARS = 14.7
N_TRIALS = 5
STRESS_YEARS = (2020, 2022)
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def _sv():
    spec = importlib.util.spec_from_file_location("satellite_value_v1_for_spy_champion",
                                                  PROJECT_ROOT / "research/jobs/satellite-value-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SV = _sv()


# =================================================================================================
# 슬리브 목표 비중(순수 함수)
# =================================================================================================

def january_resets(index: pd.DatetimeIndex) -> set:
    """각 1월의 첫 거래일(인덱스 안) + 인덱스 첫날."""
    s = pd.Series(index, index=index)
    jan = s[index.month == 1]
    out = set(jan.groupby(jan.index.year).min()) if len(jan) else set()
    return out | {index[0]}


def inner_frame_from_log(index: pd.DatetimeIndex, log: list) -> pd.DataFrame:
    """반기 선정 기록 → 새틀라이트 슬리브 안 비중(선정일 값 유지, 첫 선정 전 0 = 현금)."""
    cols = sorted({t for r in log for t in r["weights"]})
    f = pd.DataFrame(np.nan, index=index, columns=cols)
    marks = pd.Series(False, index=index)
    for r in sorted(log, key=lambda x: x["date"]):
        d = pd.Timestamp(r["date"])
        if d in f.index:
            f.loc[d] = [float(r["weights"].get(t, 0.0)) for t in cols]
            marks.loc[d] = True
    f = f.ffill().fillna(0.0)
    f.attrs["marks"] = marks       # 선정일(같은 종목이어도 그날 슬리브 안을 균등으로 다시 맞춘다)
    return f


def sleeve_weights(index: pd.DatetimeIndex, adj: pd.DataFrame, sleeves: list, resets: Optional[set] = None
                   ) -> tuple[pd.DataFrame, dict]:
    """sleeves: [(이름, 목표 비중, 슬리브 안 비중 DataFrame(index×종목, 합 ≤ 1 — 나머지는 슬리브 현금))].
    - 리셋일(각 1월 첫 거래일·첫날): 모든 슬리브를 목표 비중으로, 안은 그날 안 비중으로.
    - 그 밖에 한 슬리브의 안 비중이 바뀌는 날(코어 신호 변경, 새틀라이트 선정일): 그 슬리브의 표류한 크기 그대로 안만 다시 나눈다.
      다른 슬리브는 표류한 비중 그대로 둔다(tax_fx 는 그날 모든 종목을 목표로 맞추므로 표류값을 목표로 준다).
    - 그 밖의 날: 전날 목표 그대로(매매 없음, 실제 보유는 가격대로 표류)."""
    resets = january_resets(index) if resets is None else resets
    cols = list(dict.fromkeys(c for _, _, f in sleeves for c in f.columns))
    ci = {c: k for k, c in enumerate(cols)}
    tr = adj.reindex(index=index, columns=cols).ffill().pct_change(fill_method=None).fillna(0.0).to_numpy()
    S = len(sleeves)
    inner = np.zeros((S, len(index), len(cols)))
    changed = np.zeros((S, len(index)), dtype=bool)
    for s, (_, _, f) in enumerate(sleeves):
        g = f.reindex(index).fillna(0.0)
        for c in g.columns:
            inner[s, :, ci[c]] = g[c].to_numpy(dtype=float)
        ch = np.r_[True, np.abs(np.diff(inner[s], axis=0)).sum(axis=1) > 1e-12]
        marks = f.attrs.get("marks")
        if marks is not None:
            ch |= marks.reindex(index).fillna(False).to_numpy(dtype=bool)
        changed[s] = ch
    targets = np.array([w for _, w, _ in sleeves], dtype=float)
    H = np.zeros((S, len(cols)))
    cash = np.zeros(S)
    out = np.zeros((len(index), len(cols)))
    row = None
    info = {"reset_days": [], "sleeve_trades": {n: 0 for n, _, _ in sleeves}, "drift_at_reset": []}
    for i, d in enumerate(index):
        if i > 0:
            H *= (1 + tr[i])[None, :]
            tot = H.sum() + cash.sum()
            if tot > 0:
                H /= tot
                cash /= tot
        reset = i == 0 or d in resets
        trade = False
        if reset:
            if i > 0:
                info["drift_at_reset"].append(float(np.abs(H.sum(axis=1) + cash - targets).sum()))
            info["reset_days"].append(str(d.date()))
        for s in range(S):
            if reset or changed[s, i]:
                size = targets[s] if reset else H[s].sum() + cash[s]
                H[s] = size * inner[s, i]
                cash[s] = size * (1 - inner[s, i].sum())
                trade = True
                if not reset:
                    info["sleeve_trades"][sleeves[s][0]] += 1
        if trade or row is None:
            new = H.sum(axis=0)
            if row is not None and np.abs(new - row).sum() <= 1e-9:
                # tax_fx 는 목표가 바뀌는 날에만 매매한다. 목표가 지난 매매일과 같아도(표류는 있음) 매매하도록
                # 전체를 1e-8 만큼만 줄여 '바뀐 날'로 표시한다(현금 1e-8 — 결과에 영향 없음).
                new = new * (1 - 1e-8)
            row = new
        out[i] = row
    return pd.DataFrame(out, index=index, columns=cols), info


def candidate_weights(name: str, index: pd.DatetimeIndex, core_w: pd.DataFrame, sat_inner: pd.DataFrame,
                      adj: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    spy_w, sat_w, core_wt = CANDIDATES[name]
    sleeves = [("spy", spy_w, pd.DataFrame({"SPY": 1.0}, index=index)), ("sat", sat_w, sat_inner.reindex(index).fillna(0.0))]
    sleeves[1][2].attrs["marks"] = sat_inner.attrs.get("marks")
    if core_wt > 0:
        sleeves.append(("core", core_wt, core_w.reindex(index).fillna(0.0)))
    return sleeve_weights(index, adj, sleeves)


def champion_weights(core_w: pd.DataFrame, log: list) -> pd.DataFrame:
    """현 챔피언 = satellite-value-v1 의 A(tax_fx.champion_weights, 15%)."""
    return tx.champion_weights(core_w, log, CHAMP_SAT_WEIGHT)


def window_bounds(index: pd.DatetimeIndex) -> dict:
    out = {}
    for k, (a, b) in WINDOWS.items():
        sub = index[(index >= pd.Timestamp(a)) & ((index <= pd.Timestamp(b)) if b else True)]
        if len(sub) >= 2:
            out[k] = (sub[0], sub[-1])
    return out


def annual_turnover(weights: pd.DataFrame, adj: pd.DataFrame) -> float:
    """연간 편도 회전율(Σ|목표 − 표류|/2 ÷ 연수), 첫날 매수 제외."""
    W = weights.to_numpy()
    tr = adj.reindex(index=weights.index, columns=weights.columns).ffill().pct_change(fill_method=None).fillna(0.0).to_numpy()
    chg = np.r_[True, np.abs(np.diff(W, axis=0)).sum(axis=1) > 1e-9]
    drift = W[0].copy()
    tot = 0.0
    for i in range(1, len(W)):
        g = drift * (1 + tr[i])
        port = g.sum() + (1 - drift.sum())
        drift = g / port if port > 0 else drift
        if chg[i]:
            tot += 0.5 * float(np.abs(W[i] - drift).sum())
            drift = W[i].copy()
    years = (weights.index[-1] - weights.index[0]).days / 365.25
    return tot / years if years > 0 else float("nan")


# =================================================================================================
# 판정(순수 함수)
# =================================================================================================

def liq_cagr(final_liq: float, initial: float, t0: pd.Timestamp, t1: pd.Timestamp) -> float:
    years = (t1 - t0).days / 365.25
    if years <= 0 or initial <= 0 or not final_liq > 0:
        return float("nan")
    return (final_liq / initial) ** (1 / years) - 1


def calendar_mdd(values: pd.Series, year: int) -> Optional[float]:
    """그해 안의 최대 낙폭(전년 마지막 값에서 시작). 그해 자료가 없으면 None."""
    y = values[values.index.year == year]
    if y.empty:
        return None
    prev = values[values.index.year < year]
    s = pd.concat([prev.iloc[-1:], y]) if len(prev) else y
    return float((s / s.cummax() - 1).min())


def decide(d_judged, d_h1, d_h2, mdd_cand, mdd_spy, ci_low, noop: Optional[str] = None) -> tuple[str, list]:
    """후보 − 챔피언 세후(청산 반영) 연수익 차이로 판정. 돌려주는 값: (판정, 미충족 조건)."""
    if noop:
        return NOT_EVALUABLE, ["noop"]
    vals = (d_judged, d_h1, d_h2, mdd_cand, mdd_spy, ci_low)
    if any(v is None or not math.isfinite(float(v)) for v in vals):
        return NOT_EVALUABLE, ["non_finite"]
    miss = []
    if not d_judged >= MIN_DIFF_CHAMP:
        miss.append("a_judged_ge_champ_plus_1pp")
    if not (d_h1 > 0 and d_h2 > 0):
        miss.append("b_both_halves_gt_champ")
    if not mdd_cand >= mdd_spy:
        miss.append("c_mdd_not_worse_than_spy")
    if not ci_low > CI_LOW_FLOOR:
        miss.append("d_boot_ci90_low_gt_minus_0.5pp")
    return (PASS if not miss else FAIL), miss


def beats_spy(d_judged, d_h1, d_h2) -> bool:
    vals = (d_judged, d_h1, d_h2)
    if any(v is None or not math.isfinite(float(v)) for v in vals):
        return False
    return bool(d_judged >= SPY_MARGIN and d_h1 > 0 and d_h2 > 0)


def bootstrap_diff(ra: np.ndarray, rb: np.ndarray, ppy: float) -> np.ndarray:
    return SV.block_bootstrap_diff(ra, rb, ppy, n_boot=N_BOOT, block=BLOCK_DAYS, seed=BOOT_SEED)


# =================================================================================================
# 체크포인트·입력
# =================================================================================================

_atomic_pickle = SV._atomic_pickle
_load_ckpt = SV._load_ckpt


def _real_inputs(log) -> dict:
    """champion40 풀만 읽는다(satellite-value-v1 의 A 와 같은 일정)."""
    from core import champion_strategy as cs
    from core import satellite_lab as sl
    from core.market_data import get_multiple_price_history

    log("코어 백테스트(일별 목표 비중)")
    core_w = cs.run_core_backtest(START)["weights"]
    pool = SV._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", pool_provider=pool, log=log)
    spec, signal, params = SV._incumbent()
    sp = json.loads(json.dumps(spec))
    sp["pool"] = {"type": "champion40"}
    sat_log = SV.schedule_to_log(sl.run_variant(sp, params, signal, data)["schedule"])
    picks = sorted({t for r in sat_log for t in r["weights"]})
    others = sorted((set(core_w.columns) | {"SPY"}) - set(picks))
    hist = get_multiple_price_history(others, start="2009-06-01", end=None, interval="1d")
    frames = {t: hist.get(t) for t in others}
    frames.update({t: data.ohlcv.get(t) for t in picks})
    close, adj = SV._panel(frames)
    return {"core_w": core_w, "log": sat_log, "close": close, "adj": adj, "fx": tx.usdkrw_series(),
            "meta": {"live_satellite_weight": cs.SATELLITE_WEIGHT, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
                     "judge_version": sl.JUDGE_VERSION, "pool_cache_tag": sl.POOL_CACHE_TAG,
                     "core_universe": list(core_w.columns)}}


def _smoke_inputs(log) -> dict:
    """합성 데이터(네트워크 없음) — satellite-value-v1 스모크 입력 그대로. 실데이터가 아니다."""
    s = SV._smoke_inputs(log)
    return {"core_w": s["core_w"], "log": s["logs"]["A"], "close": s["close"], "adj": s["adj"], "fx": s["fx"],
            "meta": {**s["meta"], "synthetic": True}}


def build_all_weights(inputs: dict) -> tuple[dict, dict]:
    """{(포트폴리오, 구간): 목표 비중}, {(포트폴리오, 구간): 슬리브 정보}. 각 구간은 새 계좌(첫날 목표로 매수)."""
    champ = champion_weights(inputs["core_w"], inputs["log"])
    idx = champ.index
    wins = window_bounds(idx)
    sat_inner = inner_frame_from_log(idx, inputs["log"])
    W, info = {}, {}
    for win, (t0, t1) in wins.items():
        sub = idx[(idx >= t0) & (idx <= t1)]
        for p in CANDIDATES:
            W[(p, win)], info[(p, win)] = candidate_weights(p, sub, inputs["core_w"], sat_inner, inputs["adj"])
        W[("CHAMP", win)] = champ.loc[sub]
        W[("SPY", win)] = tx.buy_and_hold_weights(sub)
    for k in list(W):
        w = W[k]
        W[k] = w.loc[:, w.abs().sum() > 0]
    return W, info


def sim_jobs(wins: dict) -> list:
    jobs = [(p, win, DECISION_SETUP) for win in wins for p in PORTFOLIOS]
    if "judged" in wins:
        jobs += [(p, "judged", "base_100m") for p in PORTFOLIOS]
    return jobs


def _summ(s: dict, w: pd.DataFrame, adj: pd.DataFrame, initial: float) -> dict:
    v = s["values_krw"]
    t0, t1 = v.index[0], v.index[-1]
    return {"cagr_after_liq": liq_cagr(s["final_after_liquidation_krw"], initial, t0, t1),
            "cagr_after": s["cagr_after"], "cagr_pre": s["cagr_pre"], "mdd_after": s["mdd_after"],
            "final_krw": s["final_krw"], "final_after_liquidation_krw": s["final_after_liquidation_krw"],
            "totals": s["totals"], "unpaid_tax_if_sold_now_krw": s["unpaid_tax_if_sold_now_krw"],
            "turnover": annual_turnover(w, adj), "calendar_mdd": {str(y): calendar_mdd(v, y) for y in STRESS_YEARS},
            "start": str(t0.date()), "end": str(t1.date()), "values": v}


# =================================================================================================
# 분석·보고
# =================================================================================================

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


def analyze(sims: dict, info: dict, inputs: dict, wins: dict, smoke: bool) -> tuple[dict, str]:
    initial = tx.AccountConfig(**SETUPS[DECISION_SETUP]).initial_krw
    metrics = {}
    for (p, win, setup), s in sims.items():
        metrics.setdefault(setup, {}).setdefault(p, {})[win] = {k: v for k, v in s.items() if k != "values"}
    m = metrics[DECISION_SETUP]
    power = rp.power_report(POWER_YEARS, N_TRIALS)
    verdicts, details, beats = {}, {}, {}
    for p in CANDIDATES:
        g = {w: m[p][w]["cagr_after_liq"] for w in JUDGED_WINDOWS}
        c = {w: m["CHAMP"][w]["cagr_after_liq"] for w in JUDGED_WINDOWS}
        sp = {w: m["SPY"][w]["cagr_after_liq"] for w in JUDGED_WINDOWS}
        dc = {w: g[w] - c[w] for w in JUDGED_WINDOWS}
        ds = {w: g[w] - sp[w] for w in JUDGED_WINDOWS}
        pc = _pair(sims[(p, "judged", DECISION_SETUP)], sims[("CHAMP", "judged", DECISION_SETUP)], initial)
        ps = _pair(sims[(p, "judged", DECISION_SETUP)], sims[("SPY", "judged", DECISION_SETUP)], initial)
        v, miss = decide(dc["judged"], dc["h1"], dc["h2"], m[p]["judged"]["mdd_after"], m["SPY"]["judged"]["mdd_after"],
                         pc["boot_ci90_low"], pc["noop_reason"])
        b = beats_spy(ds["judged"], ds["h1"], ds["h2"])
        verdicts[p] = f"SMOKE_ONLY({v})" if smoke else v
        beats[p] = f"SMOKE_ONLY({b})" if smoke else b
        details[p] = {"verdict_raw": v, "failed_conditions": miss, "diff_vs_champ": dc, "diff_vs_spy": ds,
                      "vs_champ": pc, "vs_spy": ps, "beats_spy": b,
                      "power_class": rp.classify_fail(pc["daily_diff_ir"], power) if v == FAIL else None}
    post = {}
    if "post" in wins:
        for p in PORTFOLIOS:
            post[p] = m[p]["post"]["cagr_after_liq"]
    effic = {}
    for p in PORTFOLIOS:
        j = m[p]["judged"]
        ratio = j["cagr_after_liq"] / abs(j["mdd_after"]) if j["mdd_after"] < 0 else float("nan")
        effic[p] = {"return_per_mdd": ratio}
    for p in PORTFOLIOS:
        effic[p]["vs_champ"] = effic[p]["return_per_mdd"] - effic["CHAMP"]["return_per_mdd"]
        effic[p]["vs_spy"] = effic[p]["return_per_mdd"] - effic["SPY"]["return_per_mdd"]
    sleeve_info = {f"{p}|{w}": {"reset_days": len(i["reset_days"]), "sleeve_trades": i["sleeve_trades"],
                                "mean_drift_at_reset": float(np.mean(i["drift_at_reset"])) if i["drift_at_reset"] else 0.0}
                   for (p, w), i in info.items() if w == "judged"}
    used = sorted({t for r in inputs["log"] for t in r["weights"]} | set(inputs["core_w"].columns) | {"SPY"})
    missing = sorted(t for t in used if t not in inputs["close"].columns or inputs["close"][t].dropna().empty)
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windows": {k: [str(a.date()), str(b.date())] for k, (a, b) in wins.items()},
        "rules": {"candidates": {k: {"spy": a, "sat": b, "core": c} for k, (a, b, c) in CANDIDATES.items()},
                  "rebalance": "1월 첫 거래일에만 슬리브 비중을 목표로, 그 사이 표류. 새틀라이트 선정·코어 신호는 슬리브 안에서만.",
                  "min_diff_champ": MIN_DIFF_CHAMP, "ci_low_floor": CI_LOW_FLOOR, "spy_margin": SPY_MARGIN,
                  "n_boot": N_BOOT, "block_days": BLOCK_DAYS, "boot_seed": BOOT_SEED, "ci_percentiles": list(CI_PCT),
                  "metric": "세후 원화, 끝날 청산 시 낼 세금 반영 연복리", "post_2024_10": "report only"},
        "names": NAMES, "metrics": metrics, "details": details, "efficiency": effic, "post_2024_10": post,
        "power": power, "power_line": rp.power_line(power), "verdicts": verdicts, "beats_spy": beats,
        "sleeve_info": sleeve_info, "inputs_meta": inputs.get("meta", {}), "missing_prices": missing,
        "satellite_schedule": [{"date": r["date"], "picks": sorted(r["weights"])} for r in inputs["log"]],
    }
    return result, report(result)


def _pct(x, signed=False) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x:+.2%}" if signed else f"{x:.2%}"


def _pp(x) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x * 100:+.2f}%p"


def report(r: dict) -> str:
    m = r["metrics"][DECISION_SETUP]
    w = r["windows"]
    L = [f"# SPY 바탕 + 새틀라이트 — 현 챔피언·SPY 대비 세후 원화{' (스모크 — 합성 데이터)' if r['smoke'] else ''}", "",
         f"판정 구간 {w['judged'][0]} ~ {w['judged'][1]} · 앞 절반 {w['h1'][0]} ~ {w['h1'][1]} · 뒤 절반 {w['h2'][0]} ~ {w['h2'][1]} "
         "(구간마다 새 계좌, 초기 3,000만 원, 카카오페이증권 가정, 세후 = 끝날 다 팔면 낼 세금까지 뺀 원화 연복리).", "",
         "## 판정", "",
         "| 후보 | 판정 | 챔피언 대비(판정 구간) | 앞 절반 | 뒤 절반 | 부트스트랩 90% | SPY 대비 | SPY 를 이김 | 미충족 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for p in CANDIDATES:
        d = r["details"][p]
        L.append(f"| {p} {NAMES[p]} | **{r['verdicts'][p]}** | {_pp(d['diff_vs_champ']['judged'])} | {_pp(d['diff_vs_champ']['h1'])} | "
                 f"{_pp(d['diff_vs_champ']['h2'])} | {_pp(d['vs_champ']['boot_ci90_low'])} ~ {_pp(d['vs_champ']['boot_ci90_high'])} | "
                 f"{_pp(d['diff_vs_spy']['judged'])} | {r['beats_spy'][p]} | {', '.join(d['failed_conditions']) or '없음'}"
                 + (f" ({d['power_class']})" if d["power_class"] else "") + " |")
    L += ["", "통과(PASS_FORWARD_CANDIDATE) = 모두 만족: (a) 판정 구간 세후가 챔피언 +1.0%p 이상 (b) 두 절반 모두 챔피언보다 높음 "
          "(c) 원화 MDD 가 SPY 그냥 보유보다 나쁘지 않음 (d) 126일 블록 부트스트랩 1,000회(시드 20261016) 연수익 차이 90% 하한 > −0.5%p. "
          "'SPY 를 이김' = 판정 구간 SPY +0.5%p 이상이고 두 절반 모두 SPY 보다 높음(따로 보는 표시).", "",
          f"- {r['power_line']}",
          "- 무효 실행 가드(후보 vs 챔피언 일별 수익): " + ", ".join(f"{p} {r['details'][p]['vs_champ']['noop_reason'] or '통과'}" for p in CANDIDATES),
          "", "## 모든 후보·기준(3,000만 원)", "",
          "| | 세후(판정) | 세전(판정) | 원화 MDD | 앞 절반 | 뒤 절반 | 2024-10~ (보고) | 2020 MDD | 2022 MDD | 양도세(백만) | 수수료(백만) | 회전율/년 | 수익/MDD |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in PORTFOLIOS:
        j = m[p]["judged"]
        L.append(f"| {p} {NAMES[p]} | {_pct(j['cagr_after_liq'])} | {_pct(j['cagr_pre'])} | {_pct(j['mdd_after'])} | "
                 f"{_pct(m[p]['h1']['cagr_after_liq'])} | {_pct(m[p]['h2']['cagr_after_liq'])} | {_pct(r['post_2024_10'].get(p))} | "
                 f"{_pct(j['calendar_mdd']['2020'])} | {_pct(j['calendar_mdd']['2022'])} | "
                 f"{j['totals']['capital_gains_tax_krw'] / 1e6:.1f} | {j['totals']['fees_krw'] / 1e6:.1f} | {j['turnover']:.2f} | "
                 f"{r['efficiency'][p]['return_per_mdd']:.2f} |")
    L += ["", "수익/MDD = 세후 연수익 ÷ |원화 MDD|. 챔피언 대비·SPY 대비 차이: "
          + ", ".join(f"{p} {r['efficiency'][p]['vs_champ']:+.2f} / {r['efficiency'][p]['vs_spy']:+.2f}" for p in CANDIDATES) + ".",
          "2008 같은 금융위기 스트레스는 이 자료(2010 이후)에 없어 볼 수 없다. 2020(코로나)·2022(금리 인상) 그해 안의 최대 낙폭만 보인다.", ""]
    m1 = r["metrics"].get("base_100m", {})
    if m1:
        L += ["## 초기 1억 원(판정 구간, 보고만)", "",
              ", ".join(f"{p} {_pct(m1[p]['judged']['cagr_after_liq'])}" for p in PORTFOLIOS if p in m1) + ".", ""]
    L += ["## 규약", "",
          "- SPY 는 처음 사서 1월 리밸런싱 때만 판다. 새틀라이트 = 현 챔피언의 S-SEED-000 그대로(그 시점 champion40 풀, 돈치안 20일 추세 활성, "
          "252일 모멘텀 상위 3, 균등, 1·7월 재선정, 중간 매도 없음). 코어 = 라이브 코어(satellite-value-v1 과 같은 일별 목표 비중).",
          "- 슬리브 비중은 매년 1월 첫 거래일에만 목표로 되돌린다. 그 사이는 표류. 새틀라이트 재선정·코어 신호 변경은 그 슬리브 안에서만 다시 나눈다.",
          "- 현 챔피언 기준은 satellite-value-v1 의 A 와 같은 목표 비중(코어 신호가 바뀌는 날마다 전체를 85/15 로 맞춤 — 라이브와 같은 방식).",
          "- 양도세 납부 현금이 모자라면 모든 보유를 비중대로 판다(tax_fx). 2024-10 이후는 판정에 쓰지 않는다(보고만).",
          f"- 가격 없는 보유 종목: {', '.join(r['missing_prices']) or '없음'}.", "",
          "## 한계(꼭 읽기)", "",
          "- 새틀라이트 생존편향: 상장폐지 종목이 가격 소스에 없어 후보에서 빠진다. 새틀라이트를 실제보다 좋게 보이게 하며, 새틀라이트 비중이 클수록(P3·P5) 편향이 결과에 더 크게 실린다.",
          "- champion40 의 과거 시총은 근사이고, 섹터 분류는 시점 기준이 아니다. 랩 풀은 1/1·7/1 기준, 라이브는 그 달 첫 거래일 기준.",
          "- 이 구간(2010~2024)은 앞선 여러 연구(satellite-value-v1, sleeve-weight-v1, sat-trend-v1 등)가 이미 본 자료다. "
          "PASS 는 '전진 원장에 올릴 후보'까지만 뜻한다.",
          "- 더 큰 새틀라이트 비중을 채택하기 전에 CRSP(상장폐지 포함) 자료로 다시 검증할 것을 권한다.",
          "- 일봉 종가 체결, 금융소득 종합과세 미반영. 과거 결과이며 앞으로의 수익을 뜻하지 않는다. 엔진 반영은 사용자 확인 뒤 별도 작업이다."]
    return "\n".join(L) + "\n"


def smoke_coverage(r: dict, info: dict) -> dict:
    m = r["metrics"][DECISION_SETUP]
    ji = {p: info[(p, "judged")] for p in CANDIDATES}
    return {
        "all_candidates_judged": len(r["verdicts"]) == len(CANDIDATES),
        "annual_resets": all(len(i["reset_days"]) >= 10 for i in ji.values()),
        "drift_between_resets": all(i["drift_at_reset"] and max(i["drift_at_reset"]) > 1e-6 for i in ji.values()),
        "satellite_reselection_inside_sleeve": all(i["sleeve_trades"]["sat"] > 0 for i in ji.values()),
        "core_inside_sleeve": all(ji[p]["sleeve_trades"].get("core", 0) > 0 for p in ("P4", "P5")),
        "tax_engine": any(m[p]["judged"]["totals"]["capital_gains_tax_krw"] > 0 for p in PORTFOLIOS),
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
        inputs = _load_ckpt(ck / "inputs.pkl", fp)
        if inputs is None:
            check_time()
            inputs = _smoke_inputs(log) if a.smoke else _real_inputs(log)
            _atomic_pickle(ck / "inputs.pkl", {"fingerprint": fp, "payload": inputs})
            log("입력 체크포인트 저장")
        W, info = build_all_weights(inputs)
        wins = window_bounds(champion_weights(inputs["core_w"], inputs["log"]).index)
        sims, new = {}, 0
        for key in sim_jobs(wins):
            pname, win, setup = key
            path = ck / f"sim_{pname}_{win}_{setup}.pkl"
            got = _load_ckpt(path, fp)
            if got is None:
                if a.max_sims_per_run and new >= a.max_sims_per_run:
                    raise _Stop()
                check_time()
                cfg = tx.AccountConfig(**SETUPS[setup])
                w = W[(pname, win)]
                s = tx.simulate(w, inputs["close"], inputs["adj"], inputs["fx"], cfg)
                got = _summ(s, w, inputs["adj"], cfg.initial_krw)
                _atomic_pickle(path, {"fingerprint": fp, "payload": got})
                new += 1
                log(f"시뮬레이션 {key} 세후(청산) {got['cagr_after_liq']:.4f}")
            sims[key] = got
        result, rep = analyze(sims, info, inputs, wins, a.smoke)
        if a.smoke:
            cov = smoke_coverage(result, info)
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
    log(json.dumps({"verdicts": result["verdicts"], "beats_spy": result["beats_spy"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
