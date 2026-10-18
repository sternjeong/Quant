"""검증 contrib-reval-champion-v1 (2026-10-17 사전 등록): 처음 목돈 + 매달 적립으로 굴릴 때, 여러 시작일에서 SPY 를 세후로 이기는가.

사용자 목표(2026-10-17): 엔진을 처음 목돈(기본 1,000만 원) + 매달 15만 원 적립으로 끝없이 굴리고, 한국 세금 뒤 장기적으로 SPY 를 이긴다.
지금까지 후보 연구(spy-champion-v1·sat-buffer-v1·sat-stagger-v1·signal-swap-v1·lev-base-v1·guru-champion-v1)는 한 시작일 + 목돈 한 번으로
쟀다. 이 연구는 같은 전략 목표 비중을 그대로 가져와(import — 다시 구현하지 않음) core/rolling_eval 로 매달 시작하는 5년(판정)·10년(보고)
구간마다 core/tax_fx 세후·적립 계좌로 굴리고, 같은 돈을 받는 SPY 그냥 보유와 비교한다.

규칙 전체는 SPEC.md(한국어)에 고정. 판정 기준을 바꾸려면 새 id 로 다시 등록한다. 엔진 반영은 사용자 확인 뒤 별도 작업이다.
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import math
import os
import signal as _signal
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import rolling_eval as re_  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "contrib-reval-champion-v1"
RULES_VERSION = "contrib-reval-champion-v1/2026-10-17"
START = "2010-01-01"
DECISION_END = "2024-09-30"       # 판정 구간은 이 날 이하에서 끝나는 구간만. 그 뒤에 끝나는 구간은 보고만
HORIZONS = (5, 10)                # 5년 = 판정(ETF 시대 자료가 약 14.7년뿐), 10년 = 보고
PRIMARY_HORIZON = 5
STEP_MONTHS = 1                   # 매달 첫 거래일 시작
SMOKE_STEP_MONTHS = 24            # 스모크만(합성 자료, 속도)
SAT_WEIGHT = 0.15

# --- 전략(각각 전체 기간 일별 목표 비중 표를 한 번 만들고 구간마다 자른다). SPY = 기준(같은 적립금을 받는 그냥 보유)
STRATEGIES = ("CHAMP", "P1", "P3", "P4", "P1ST", "KRS", "CHAMP_K6", "L15F", "D1")
JUDGED = ("CHAMP", "P1", "P3", "P4", "P1ST", "KRS", "CHAMP_K6", "L15F")
REPORTED_ONLY = ("D1",)           # 13F 자료가 2014 부터 — 구간 시작 2014-01 부터, 보고만
N_TRIALS = 8
POWER_YEARS = 14.7
NAMES = {"SPY": "SPY 그냥 보유(기준, 같은 적립금)",
         "CHAMP": "현 챔피언(라이브 코어 85% + S-SEED-000 15%)",
         "P1": "SPY 85% + 새틀라이트 15%(1월 리셋)",
         "P3": "SPY 70% + 새틀라이트 30%(1월 리셋)",
         "P4": "SPY 50% + 새틀라이트 30% + 코어 20%(1월 리셋)",
         "P1ST": "SPY 85% + 새틀라이트 5%×3 엇갈린 재선정·K6 버퍼(1월 리셋)",
         "KRS": "상대강도 코어(SPY 를 이긴 자산만) 85% + 새틀라이트 15%",
         "CHAMP_K6": "현 챔피언, 새틀라이트만 K6_H6 순위 버퍼",
         "L15F": "SPY 85% + 합성 2배 15%(200일선 완충 필터)",
         "D1": "SPY 85% + 거장 우선 새틀라이트 S-SEED-019 15%(2014~, 보고만)"}
SOURCES = {"CHAMP": "spy-champion-v1 CHAMP = satellite-value-v1 A (tax_fx.champion_weights 15%)",
           "P1": "spy-champion-v1 candidate_weights('P1')", "P3": "spy-champion-v1 candidate_weights('P3')",
           "P4": "spy-champion-v1 candidate_weights('P4')",
           "P1ST": "core/forward_tournament_v3 P1ST 규칙을 과거에: spy-champion-v1 sleeve_weights + sat-buffer-v1 select_with_buffer(K6) + sat-stagger-v1 sim_dates",
           "KRS": "signal-swap-v1 core_variant_weights('KRS') + tax_fx.champion_weights 15%",
           "CHAMP_K6": "sat-buffer-v1 _weights('champ', 'K6_H6')",
           "L15F": "lev-base-v1 portfolio_weights(L=0.15, filtered=True)",
           "D1": "guru-champion-v1 build_weights()['D1']"}
P1ST_SPY = 0.85
P1ST_SUB = {"ST_A": (1, 7), "ST_B": (3, 9), "ST_C": (5, 11)}   # 하위 슬리브 재선정 달
P1ST_SUB_WEIGHT = 0.05
BUFFER_K = 6
LEV_L = 0.15

# --- 계좌 시나리오(core/tax_fx.AccountConfig, 카카오페이증권 기본값, 적립 정책 underweight_first)
SCENARIOS = {"B": {"initial_krw": 10_000_000, "monthly_contribution_krw": 150_000},
             "A": {"initial_krw": 10_000_000, "monthly_contribution_krw": 0.0},
             "C": {"initial_krw": 3_000_000, "monthly_contribution_krw": 150_000},
             "B10": {"initial_krw": 100_000_000, "monthly_contribution_krw": 1_500_000}}
SCENARIO_NAMES = {"B": "B 1,000만 원 + 매달 15만 원(판정)", "A": "A 1,000만 원 목돈만(적립 없음)",
                  "C": "C 300만 원 + 매달 15만 원", "B10": "B10 1억 원 + 매달 150만 원(규모 민감도)"}
PRIMARY_SCENARIO = "B"
CONTRIBUTION_POLICY = "underweight_first"

# --- 사전 등록 판정(시나리오 B, 5년 구간, 판정 구간 안에서 끝나는 구간): 모두 만족하면 CONTRIB_BEATS_SPY
MIN_SHARE_WIN = 0.70              # 청산 후 최종 금액이 SPY 보다 큰 구간 비율 ≥ 70%
MIN_MEDIAN_DIFF = 0.005           # IRR 차이 중앙값 ≥ +0.5%p
MIN_P10_DIFF = -0.015             # IRR 차이 10분위 ≥ −1.5%p
MDD_TW_TOL = 0.05                 # 시간가중 최대낙폭 중앙값이 SPY 보다 5%p 넘게 나쁘지 않음
EPS = 1e-12
PASS, FAIL, NOT_EVALUABLE = "CONTRIB_BEATS_SPY", "FAIL", "NOT_EVALUABLE"
CHUNK = 25                        # evaluate_windows 한 번에 새로 할 시뮬레이션 수(기준 캐시 저장 간격)


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def _load_mod(name: str, rel: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SC = _load_mod("spy_champion_v1_for_contrib_reval", "research/jobs/spy-champion-v1/run.py")
SV = SC.SV
BUF = _load_mod("sat_buffer_v1_for_contrib_reval", "research/jobs/sat-buffer-v1/run.py")
STG = _load_mod("sat_stagger_v1_for_contrib_reval", "research/jobs/sat-stagger-v1/run.py")
SW = _load_mod("signal_swap_v1_for_contrib_reval", "research/jobs/signal-swap-v1/run.py")
LB = _load_mod("lev_base_v1_for_contrib_reval", "research/jobs/lev-base-v1/run.py")
GC = _load_mod("guru_champion_v1_for_contrib_reval", "research/jobs/guru-champion-v1/run.py")


# =================================================================================================
# 계좌·구간 (순수 함수)
# =================================================================================================

def scenario_config(name: str) -> tx.AccountConfig:
    s = SCENARIOS[name]
    return tx.AccountConfig(initial_krw=float(s["initial_krw"]), monthly_contribution_krw=float(s["monthly_contribution_krw"]),
                            contribution_policy=CONTRIBUTION_POLICY)


def split_windows(calendar: pd.DatetimeIndex, horizon: float, step, first_start) -> dict[str, list]:
    """{"judged": 판정 끝 이하에서 끝나는 구간, "post": 그 뒤에 끝나는 구간(보고만)} — 매 step 개월 첫 거래일 시작."""
    ws = re_.rolling_windows(calendar, horizon, step=step, first_start=first_start)
    end = pd.Timestamp(DECISION_END)
    return {"judged": [w for w in ws if w[1] <= end], "post": [w for w in ws if w[1] > end]}


# =================================================================================================
# 판정 (순수 함수)
# =================================================================================================

def decide(s: Optional[dict], power: Optional[dict] = None, noop: Optional[str] = None) -> tuple[str, dict]:
    """s = rolling_eval.summarize 결과(또는 compact). 반환 (판정, 조건별 bool). FAIL 이면 classify_fail(중앙 IRR 차이, power)."""
    if noop:
        return NOT_EVALUABLE, {}
    if not s or not s.get("n_windows"):
        return NOT_EVALUABLE, {}
    vals = [s.get(k) for k in ("share_terminal_win", "median_diff_irr", "p10_diff_irr",
                               "median_strategy_mdd_tw", "median_benchmark_mdd_tw")]
    if any(v is None or not math.isfinite(float(v)) for v in vals):
        return NOT_EVALUABLE, {}
    c = {"a_share_win_ge_70pct": s["share_terminal_win"] >= MIN_SHARE_WIN - EPS,
         "b_median_irr_diff_ge_0.5pp": s["median_diff_irr"] >= MIN_MEDIAN_DIFF - EPS,
         "c_p10_irr_diff_ge_minus_1.5pp": s["p10_diff_irr"] >= MIN_P10_DIFF - EPS,
         "d_median_mdd_tw_within_5pp": s["median_strategy_mdd_tw"] - s["median_benchmark_mdd_tw"] >= -MDD_TW_TOL - EPS}
    if all(c.values()):
        return PASS, c
    return (rp.classify_fail(s["median_diff_irr"], power) if power else FAIL), c


def compact(s: dict, rows: list) -> dict:
    """results.json 용 요약(구간별 행은 넣지 않는다)."""
    if not rows:
        return {"n_windows": 0}

    def med(f):
        a = np.array([f(r) for r in rows], dtype=float)
        return float(np.nanmedian(a)) if np.isfinite(a).any() else None

    keys = ("n_windows", "share_terminal_win", "median_diff_irr", "mean_diff_irr", "p10_diff_irr", "p90_diff_irr",
            "median_terminal_ratio", "min_terminal_ratio", "median_strategy_irr", "median_benchmark_irr",
            "median_strategy_mdd_tw", "median_benchmark_mdd_tw", "horizon_years", "span_years", "effective_independent_windows")
    out = {k: s.get(k) for k in keys}
    out.update({"first_start": rows[0]["start"], "last_start": rows[-1]["start"], "last_end": rows[-1]["end"],
                "median_strategy_mdd_mw": med(lambda r: r["strategy"]["mdd_mw"]),
                "median_benchmark_mdd_mw": med(lambda r: r["benchmark"]["mdd_mw"]),
                "median_strategy_cgt_krw": med(lambda r: r["strategy"]["capital_gains_tax_krw"]),
                "median_benchmark_cgt_krw": med(lambda r: r["benchmark"]["capital_gains_tax_krw"]),
                "median_strategy_unpaid_tax_krw": med(lambda r: r["strategy"]["unpaid_tax_if_sold_now_krw"]),
                "median_total_contributed_krw": med(lambda r: r["strategy"]["total_contributed_krw"]),
                "median_strategy_terminal_krw": med(lambda r: r["strategy"]["terminal_krw"]),
                "median_benchmark_terminal_krw": med(lambda r: r["benchmark"]["terminal_krw"]),
                "worst_window": {k: s["worst_window"][k] for k in ("start", "end", "diff_irr")},
                "best_window": {k: s["best_window"][k] for k in ("start", "end", "diff_irr")}})
    return out


def _rnd(x):
    """results.json 크기를 줄이려고 소수 6자리(원화 금액은 정수)로."""
    if isinstance(x, dict):
        return {k: _rnd(v) for k, v in x.items()}
    if isinstance(x, float):
        if not math.isfinite(x):
            return None
        return round(x) if abs(x) >= 1000 else round(x, 6)
    return x


def bench_compact(rows: list) -> dict:
    """SPY(기준) 자체의 분포."""
    if not rows:
        return {"n_windows": 0}
    b = [r["benchmark"] for r in rows]
    m = lambda k: float(np.nanmedian([x[k] for x in b]))  # noqa: E731
    return {"n_windows": len(rows), "median_irr": m("irr"), "p10_irr": float(np.nanpercentile([x["irr"] for x in b], 10)),
            "median_mdd_tw": m("mdd_tw"), "median_mdd_mw": m("mdd_mw"), "median_cgt_krw": m("capital_gains_tax_krw"),
            "median_terminal_krw": m("terminal_krw"), "median_total_contributed_krw": m("total_contributed_krw")}


# =================================================================================================
# 전략 목표 비중 (출처 연구의 함수를 그대로 부른다)
# =================================================================================================

def scores_on_dates(data, dates: list) -> tuple[dict, Any]:
    """sat-buffer-v1 score_inputs 와 같은 식을 '주어진 날짜'(매달)에 적용: 그날 풀의 S-SEED-000 점수(추세 활성 후보)와 풀 밖 보유 점수 함수.
    (score_inputs 는 1·7월만 계산하므로 하위 슬리브 3·5·9·11월용으로 날짜만 넓혔다 — 식은 같다.)"""
    from core import satellite_lab as sl

    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    signal = sl.load_signal(code)
    params = dict(spec["signal"]["params_grid"][0])
    pool_scores, cutoffs = {}, {}
    for d in dates:
        d = pd.Timestamp(d)
        cutoff = sl._prev_day(data.trading_days, d)
        if cutoff is None:
            continue
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


def p1st_schedules(data) -> dict[str, list]:
    """P1ST 하위 슬리브 일정(forward_tournament_v3 와 같은 규칙): 셋 다 첫 달(2010-01)에 처음 고르고, 그 뒤 자기 재선정 달에만,
    K6 순위 버퍼(sat-buffer-v1 select_with_buffer). 후보일 = sat-stagger-v1 sim_dates(매달 첫 거래일)."""
    mdates = STG.sim_dates(data.trading_days)
    pool_scores, extra = scores_on_dates(data, mdates)
    mdates = [d for d in mdates if d in pool_scores]
    d0 = mdates[0]
    out = {}
    for k, months in P1ST_SUB.items():
        ds = [d0] + [d for d in mdates[1:] if d.month in months]
        out[k] = BUF.build_schedules(ds, pool_scores, extra, {k: (BUFFER_K, tuple(range(1, 13)))})[k]
    return out


def rows_to_log(rows: list) -> list[dict]:
    return SV.schedule_to_log([(r["date"], r["picks"]) for r in rows])


def p1st_weights(index: pd.DatetimeIndex, adj: pd.DataFrame, sub_logs: dict) -> pd.DataFrame:
    """SPY 85% + 하위 슬리브 5%×3. spy-champion-v1 sleeve_weights(1월 리셋, 하위 슬리브는 자기 재선정일에 자기 크기 안에서만)."""
    sleeves = [("spy", P1ST_SPY, pd.DataFrame({"SPY": 1.0}, index=index))]
    for k in P1ST_SUB:
        sleeves.append((k, P1ST_SUB_WEIGHT, SC.inner_frame_from_log(index, sub_logs[k])))
    return SC.sleeve_weights(index, adj, sleeves)[0]


def satellite_log(data) -> list[dict]:
    """S-SEED-000(champion40) 일정 — spy-champion-v1 _real_inputs 와 같은 호출."""
    from core import satellite_lab as sl

    spec, signal, params = SV._incumbent()
    sp = json.loads(json.dumps(spec))
    sp["pool"] = {"type": "champion40"}
    return SV.schedule_to_log(sl.run_variant(sp, params, signal, data)["schedule"])


def base_frames(data, core_w: pd.DataFrame, frames: dict, fx: pd.Series) -> dict:
    """CHAMP·P1·P3·P4·P1ST·CHAMP_K6 목표 비중 + 가격 패널."""
    s0 = satellite_log(data)
    d6, ps6, ex6 = BUF.score_inputs(data)
    k6 = BUF.build_schedules(d6, ps6, ex6, {"K6_H6": BUF.VARIANT_RULES["K6_H6"]})["K6_H6"]
    subs = p1st_schedules(data)
    picks = ({t for r in s0 for t in r["weights"]} | {t for r in k6 for t in r["picks"]}
             | {t for rows in subs.values() for r in rows for t in r["picks"]})
    pf = dict(frames)
    pf.update({t: data.ohlcv.get(t) for t in sorted(picks)})
    close, adj = SV._panel(pf)
    champ = SC.champion_weights(core_w, s0)
    idx = champ.index
    sat_inner = SC.inner_frame_from_log(idx, s0)
    W = {"CHAMP": champ}
    for p in ("P1", "P3", "P4"):
        W[p] = SC.candidate_weights(p, idx, core_w, sat_inner, adj)[0]
    sub_logs = {k: rows_to_log(v) for k, v in subs.items()}
    W["P1ST"] = p1st_weights(idx, adj, sub_logs)
    W["CHAMP_K6"] = BUF._weights({"core_w": core_w, "schedules": {"K6_H6": k6}}, "champ", "K6_H6")
    sched = {"S0": [{"date": r["date"], "picks": sorted(r["weights"])} for r in s0],
             "K6_H6": [{"date": str(pd.Timestamp(r["date"]).date()), "picks": r["picks"], "kept": r["kept"]} for r in k6]}
    sched.update({k: [{"date": str(pd.Timestamp(r["date"]).date()), "picks": r["picks"], "kept": r["kept"]} for r in v]
                  for k, v in subs.items()})
    return {"frames": W, "close": close, "adj": adj, "fx": fx, "s0_log": s0, "schedules": sched}


def krs_frame(closes: pd.DataFrame, market_close: pd.Series, s0_log: list, cash: Optional[str] = "BIL") -> pd.DataFrame:
    """signal-swap-v1 A_KRS_S12: KRS 코어 85% + S-SEED-000 15%(S12 = S-SEED-000 기본 252일)."""
    w = SW.core_variant_weights(closes, market_close, "KRS", cash if cash in closes.columns else None)
    w = w.loc[w.index >= pd.Timestamp(START)]
    return tx.champion_weights(w, s0_log, SAT_WEIGHT)


def lev_parts(index: pd.DatetimeIndex, base_close: pd.DataFrame, base_adj: pd.DataFrame, fx: pd.Series) -> dict:
    """lev-base-v1: _assemble(합성 2배 = 조정가 기준, 상태 = SPY 종가 200일선 완충) → portfolio_weights(L=15%, 필터)."""
    a = LB._assemble(base_close, base_adj, pd.DataFrame(), pd.DataFrame(), fx, [], {})
    w, _ = LB.portfolio_weights(index, a["adj"], LEV_L, True, a["state"])
    return {"frame": w, "close": a["close"][[LB.X2]], "adj": a["adj"][[LB.X2]],
            "time_on": float(a["state"].reindex(index).fillna(False).astype(float).mean())}


def guru_frame(g: dict) -> pd.DataFrame:
    w = GC.build_weights(g["core_w"], g["logs"], g["adj"])["D1"]
    return w.loc[:, w.abs().sum() > 0]


def merge_panel(close: pd.DataFrame, adj: pd.DataFrame, add_close: pd.DataFrame, add_adj: pd.DataFrame
                ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """없는 종목만 덧붙인다(같은 종목은 먼저 있던 가격을 쓴다)."""
    new = [c for c in add_close.columns if c not in close.columns]
    if not new:
        return close, adj
    return (pd.concat([close, add_close[new]], axis=1).sort_index(),
            pd.concat([adj, add_adj.reindex(columns=new)], axis=1).sort_index())


def align_frames(frames: dict, calendar: pd.DatetimeIndex) -> tuple[dict, dict]:
    """모든 전략을 같은 거래일 축(CHAMP 축)에 맞춘다 — 같은 (시작, 끝) 구간의 기준(SPY)이 모든 전략에 같은 날짜로 돌게."""
    out, info = {}, {}
    for k, f in frames.items():
        cal = calendar[calendar >= f.index[0]]
        g = f.reindex(cal).ffill().fillna(0.0)
        out[k] = g.loc[:, g.abs().sum() > 0]
        info[k] = {"start": str(cal[0].date()), "days_not_in_calendar": int((~f.index.isin(calendar) & (f.index >= cal[0])).sum())}
    return out, info


# =================================================================================================
# 입력 (실데이터 / 합성)
# =================================================================================================

def _real_base(log) -> dict:
    from core import champion_strategy as cs
    from core import satellite_lab as sl
    from core.market_data import get_multiple_price_history

    log("코어 백테스트(일별 목표 비중)")
    core_w = cs.run_core_backtest(START)["weights"]
    pool = SV._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", pool_provider=pool, log=log)
    others = sorted(set(core_w.columns) | {"SPY", "BIL"})
    hist = get_multiple_price_history(others, start="2009-06-01", end=None, interval="1d")
    log("새틀라이트 일정(S-SEED-000·K6_H6·P1ST 하위 슬리브)")
    out = base_frames(data, core_w, {t: hist.get(t) for t in others}, tx.usdkrw_series())
    out["meta"] = {"live_satellite_weight": cs.SATELLITE_WEIGHT, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
                   "judge_version": sl.JUDGE_VERSION, "pool_cache_tag": sl.POOL_CACHE_TAG, "core_universe": list(core_w.columns)}
    del data
    return out


def _real_krs(base: dict, log) -> dict:
    from core import champion_strategy as cs
    from core.market_data import get_multiple_price_history

    log("KRS 코어(상대강도)")
    tickers = list(cs.CORE_UNIVERSE) + [SW.CASH_ETF]
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=SW.CORE_WARMUP_DAYS)).date().isoformat()
    hist = get_multiple_price_history(tickers + [SW.MARKET], start=fetch_start, end=None, interval="1d")
    closes_all = cs._closes_from_histories(hist, tickers + [SW.MARKET])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    f = krs_frame(closes, closes_all[SW.MARKET], base["s0_log"])
    c, a = SV._panel({t: hist.get(t) for t in tickers + [SW.MARKET]})
    return {"frame": f, "close": c, "adj": a}


def _real_lev(base: dict, log) -> dict:
    from core.market_data import get_multiple_price_history

    log("L15F(합성 2배)")
    h = get_multiple_price_history([LB.SPY, LB.BIL], start="2005-01-01", end=None, interval="1d")
    bc = pd.DataFrame({t: h[t]["Close"] for t in (LB.SPY, LB.BIL) if t in h and not h[t].empty}).sort_index()
    ba = pd.DataFrame({t: h[t]["Adj Close"] for t in (LB.SPY, LB.BIL) if t in h and not h[t].empty}).sort_index()
    for need in (LB.SPY, LB.BIL):
        if need not in bc.columns:
            raise RuntimeError(f"{need} 가격을 받지 못함")
    return lev_parts(base["frames"]["CHAMP"].index, bc, ba, base["fx"])


def _real_guru(log) -> dict:
    log("D1(거장 우선 S-SEED-019) — guru-champion-v1 입력")
    try:
        g = GC._real_inputs(log)
    except GC._Stop as exc:   # 13F 받기가 이번 예산에 안 끝남 → 다음 회차에 이어서
        raise _Stop() from exc
    f = guru_frame(g)
    cols = [c for c in f.columns if c in g["close"].columns]
    return {"frame": f, "close": g["close"][cols], "adj": g["adj"][cols], "guru": g.get("guru"), "start": g.get("start")}


SMOKE_END = "2026-06-30"


def _smoke_data():
    """합성 champion40 자료(satellite-value-v1 스모크와 같은 생성기·시드 7). 실데이터가 아니다."""
    from core import satellite_lab as sl

    pp, poolp = sl.synthetic_providers(n_tickers=50, start="2008-01-01", end=SMOKE_END, seed=7)
    pool = SV._pool_wrapper(poolp, date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", end=SMOKE_END, pool_provider=pool, price_provider=pp)
    return data, pp


def _smoke_base(log) -> dict:
    s = SV._smoke_inputs(log)          # 코어(C1·C2)·환율·SPY = satellite-value-v1 스모크 그대로
    data, _ = _smoke_data()
    frames = {}
    for t in s["close"].columns:
        frames[t] = pd.DataFrame({"Close": s["close"][t], "Adj Close": s["adj"][t]}).dropna()
    out = base_frames(data, s["core_w"], frames, s["fx"])
    out["meta"] = {"synthetic": True}
    return out


def _smoke_krs(base: dict, log) -> dict:
    _, pp = _smoke_data()
    spy = pp("SPY", "2008-01-01", SMOKE_END)
    core_frames, closes = SW._smoke_core(spy.index, spy["Close"])
    f = krs_frame(closes, spy["Close"], base["s0_log"])
    c, a = SV._panel(core_frames)
    return {"frame": f, "close": c, "adj": a}


def _smoke_lev(base: dict, krs: dict, log) -> dict:
    """합성: SPY 는 기본 패널, BIL 은 signal-swap-v1 합성 코어의 BIL."""
    close, adj = merge_panel(base["close"], base["adj"], krs["close"], krs["adj"])
    bc = close[["SPY", "BIL"]].dropna()
    ba = adj[["SPY", "BIL"]].reindex(bc.index)
    return lev_parts(base["frames"]["CHAMP"].index, bc, ba, base["fx"])


def _smoke_guru(log) -> dict:
    g = GC._smoke_inputs(log)
    f = guru_frame(g)
    cols = [c for c in f.columns if c in g["close"].columns]
    return {"frame": f, "close": g["close"][cols], "adj": g["adj"][cols], "guru": g.get("guru"), "start": g.get("start")}


def assemble(base: dict, krs: dict, lev: dict, guru: dict) -> dict:
    close, adj = base["close"], base["adj"]
    for part in (krs, lev, guru):
        close, adj = merge_panel(close, adj, part["close"], part["adj"])
    raw = dict(base["frames"])
    raw.update({"KRS": krs["frame"], "L15F": lev["frame"], "D1": guru["frame"]})
    cal = raw["CHAMP"].index
    frames, info = align_frames(raw, cal)
    missing = sorted(t for f in frames.values() for t in f.columns if t not in close.columns or close[t].dropna().empty)
    return {"frames": frames, "frame_info": info, "panels": {"close": close, "adj": adj, "fx": base["fx"]},
            "calendar": cal, "schedules": base["schedules"], "meta": base.get("meta", {}),
            "lev_time_on": lev.get("time_on"), "guru": {"start": guru.get("start"),
                                                        "first_rebalance_guru_known": (guru.get("guru") or {}).get("first_rebalance_guru_known"),
                                                        "share_picks_guru_held": (guru.get("guru") or {}).get("share_picks_guru_held")},
            "missing_prices": sorted(set(missing))}


# =================================================================================================
# 평가
# =================================================================================================

def strategy_windows(prep: dict, strat: str, step) -> dict:
    """{horizon: {"judged": [...], "post": [...]}} — D1 은 자기 첫 날(2014-01) 이후 시작."""
    first = prep["frames"][strat].index[0] if strat in prep["frames"] else pd.Timestamp(START)
    first = max(pd.Timestamp(first), pd.Timestamp(START))
    return {h: split_windows(prep["calendar"], h, step, first) for h in HORIZONS}


def all_windows(wmap: dict) -> list:
    out = []
    for h in HORIZONS:
        out += wmap[h]["judged"] + wmap[h]["post"]
    return out


def _deadline_mono(epoch: Optional[float], margin: float = 90.0) -> Optional[float]:
    if epoch is None:
        return None
    return time.monotonic() + (epoch - margin - time.time())


def analyze(prep: dict, results: dict, wmaps: dict, smoke: bool, step) -> tuple[dict, str]:
    power = rp.power_report(POWER_YEARS, N_TRIALS)
    stats: dict = {}
    spy: dict = {}
    for scen in SCENARIOS:
        stats[scen] = {}
        for strat in STRATEGIES:
            rows = {(r["start"], r["end"]): r for r in results[(strat, scen)]["rows"]}
            stats[scen][strat] = {}
            for h in HORIZONS:
                for part in ("judged", "post"):
                    sel = [rows[(str(s.date()), str(e.date()))] for s, e in wmaps[strat][h][part]
                           if (str(s.date()), str(e.date())) in rows]
                    key = f"{h}y_{part}"
                    stats[scen][strat][key] = compact(re_.summarize(sel, h), sel) if sel else {"n_windows": 0}
                    if strat == "CHAMP":
                        spy.setdefault(scen, {})[key] = bench_compact(sel)
                    if part == "judged" and h == PRIMARY_HORIZON:
                        stats[scen][strat][key]["noop_reason"] = rp.noop_guard([r["diff_terminal_krw"] for r in sel]) if sel else None
    key5 = f"{PRIMARY_HORIZON}y_judged"
    verdicts, details, same_rule = {}, {}, {}
    for scen in SCENARIOS:
        same_rule[scen] = {}
        for strat in STRATEGIES:
            s = stats[scen][strat][key5]
            v, checks = decide(s, power, s.get("noop_reason"))
            same_rule[scen][strat] = v
            if scen == PRIMARY_SCENARIO and strat in JUDGED:
                verdicts[strat] = f"SMOKE_ONLY({v})" if smoke else v
                details[strat] = {"verdict_raw": v, "checks": checks, "observed_effect_median_irr_diff": s.get("median_diff_irr"),
                                  "fail_kind": v if v in ("FAIL", "FAIL_UNDERPOWERED") else None}
    framing = {strat: {"A_lump_sum": same_rule["A"][strat], "B_contrib": same_rule["B"][strat],
                       "changed": _passed(same_rule["A"][strat]) != _passed(same_rule["B"][strat])} for strat in STRATEGIES}
    ranking = {}
    for scen in SCENARIOS:
        order = sorted(JUDGED, key=lambda c: -(stats[scen][c][key5].get("median_diff_irr") or -math.inf))
        ranking[scen] = order
    counts = {strat: {f"{h}y_{p}": len(wmaps[strat][h][p]) for h in HORIZONS for p in ("judged", "post")} for strat in STRATEGIES}
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rules": {"horizons": list(HORIZONS), "primary_horizon": PRIMARY_HORIZON, "step_months": step,
                  "decision_end": DECISION_END, "start": START, "primary_scenario": PRIMARY_SCENARIO,
                  "scenarios": SCENARIOS, "contribution_policy": CONTRIBUTION_POLICY,
                  "min_share_win": MIN_SHARE_WIN, "min_median_irr_diff": MIN_MEDIAN_DIFF, "min_p10_irr_diff": MIN_P10_DIFF,
                  "mdd_tw_tol": MDD_TW_TOL, "n_trials": N_TRIALS, "power_years": POWER_YEARS, "judged": list(JUDGED),
                  "reported_only": list(REPORTED_ONLY), "post_windows": "report only",
                  "fail_kind": "classify_fail(median IRR difference, power_report(14.7, 8)) — units differ (return vs IR), approximate"},
        "names": NAMES, "sources": SOURCES, "verdicts": verdicts, "details": details, "same_rule": same_rule,
        "framing_change": framing, "ranking_by_median_irr_diff_5y": ranking, "stats": _rnd(stats), "spy": _rnd(spy),
        "window_counts": counts, "power": power, "power_line": rp.power_line(power),
        "frame_info": prep["frame_info"], "missing_prices": prep["missing_prices"], "lev_time_on": prep.get("lev_time_on"),
        "guru": prep.get("guru"), "inputs_meta": prep.get("meta", {}),
    }
    return result, report(result)


def _passed(v: str) -> bool:
    return v == PASS


# =================================================================================================
# 보고
# =================================================================================================

def _pct(x, nd=1) -> str:
    return "—" if x is None or not isinstance(x, (int, float)) or not math.isfinite(x) else f"{x * 100:.{nd}f}%"


def _pp(x) -> str:
    return "—" if x is None or not isinstance(x, (int, float)) or not math.isfinite(x) else f"{x * 100:+.2f}%p"


def _won(x) -> str:
    return "—" if x is None or not isinstance(x, (int, float)) or not math.isfinite(x) else f"{x / 10_000:,.0f}만"


def _table(r: dict, scen: str, key: str, strategies=STRATEGIES) -> list[str]:
    L = ["| 전략 | 구간 수 | 겹치지 않는 구간 | SPY 보다 많이 남은 비율 | IRR 차이 중앙 | 10분위 | 90분위 | 전략 IRR 중앙 | SPY IRR 중앙 | "
         "시간가중 MDD 중앙(전략/SPY) | 양도세 중앙(전략/SPY, 원) | 최악 구간 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in strategies:
        s = r["stats"][scen][c].get(key) or {}
        if not s.get("n_windows"):
            L.append(f"| {c} | 0 | — | — | — | — | — | — | — | — | — | — |")
            continue
        w = s["worst_window"]
        L.append(f"| {c} | {s['n_windows']} | {s['effective_independent_windows']:.1f} | {_pct(s['share_terminal_win'], 0)} | "
                 f"{_pp(s['median_diff_irr'])} | {_pp(s['p10_diff_irr'])} | {_pp(s['p90_diff_irr'])} | {_pct(s['median_strategy_irr'])} | "
                 f"{_pct(s['median_benchmark_irr'])} | {_pct(s['median_strategy_mdd_tw'])} / {_pct(s['median_benchmark_mdd_tw'])} | "
                 f"{_won(s['median_strategy_cgt_krw'])} / {_won(s['median_benchmark_cgt_krw'])} | {w['start']}~ {_pp(w['diff_irr'])} |")
    return L


def report(r: dict) -> str:
    sm = " (스모크 — 합성 데이터, 실측 아님)" if r["smoke"] else ""
    key5 = f"{PRIMARY_HORIZON}y_judged"
    L = [f"# 처음 목돈 + 매달 적립으로 다시 본 챔피언·후보 — 여러 시작일에서 SPY 를 세후로 이기나{sm}", "",
         "같은 전략(출처 연구의 목표 비중을 그대로 가져옴)을 매달 첫 거래일에 시작하는 5년(판정)·10년(보고) 구간마다 새 계좌로 굴렸다. "
         "계좌는 카카오페이증권 가정·한국 해외주식 양도소득세(연 250만 원 공제, 22%)를 넣은 core/tax_fx, 적립금은 시작 다음 달부터 매달 첫 거래일에 "
         "들어와 목표보다 모자란 종목부터 산다(underweight_first). 기준은 같은 돈을 같은 날 받는 SPY 그냥 보유. "
         "끝 금액은 마지막 날 다 팔고 세금까지 낸 뒤의 원화, 수익률은 적립금 흐름을 넣은 연 IRR.", "",
         f"## 판정 (시나리오 {SCENARIO_NAMES[PRIMARY_SCENARIO]}, 5년 구간, {DECISION_END} 이전에 끝나는 구간)", "",
         "| 전략 | 판정 | SPY 보다 많이 남은 비율 | IRR 차이 중앙 | 10분위 | 시간가중 MDD 차이(중앙) | 미충족 |", "|---|---|---|---|---|---|---|"]
    for c in JUDGED:
        s = r["stats"][PRIMARY_SCENARIO][c][key5]
        d = r["details"][c]
        miss = [k for k, ok in d["checks"].items() if not ok]
        mdd_d = (s.get("median_strategy_mdd_tw") - s.get("median_benchmark_mdd_tw")) if s.get("n_windows") else None
        L.append(f"| {c} {NAMES[c]} | **{r['verdicts'][c]}** | {_pct(s.get('share_terminal_win'), 0)} | {_pp(s.get('median_diff_irr'))} | "
                 f"{_pp(s.get('p10_diff_irr'))} | {_pp(mdd_d)} | {', '.join(miss) or '없음'} |")
    s_d1 = r["stats"][PRIMARY_SCENARIO]["D1"][key5]
    L += [f"| D1 {NAMES['D1']} | 보고만({r['same_rule'][PRIMARY_SCENARIO]['D1']}, 같은 규칙) | {_pct(s_d1.get('share_terminal_win'), 0)} | "
          f"{_pp(s_d1.get('median_diff_irr'))} | {_pp(s_d1.get('p10_diff_irr'))} | — | — |", "",
          f"통과(CONTRIB_BEATS_SPY) = 모두: (a) SPY 보다 많이 남은 구간 비율 ≥ {MIN_SHARE_WIN:.0%} (b) IRR 차이 중앙값 ≥ +{MIN_MEDIAN_DIFF * 100:.1f}%p "
          f"(c) IRR 차이 10분위 ≥ {MIN_P10_DIFF * 100:.1f}%p (d) 시간가중 최대낙폭 중앙값이 SPY 보다 {MDD_TW_TOL * 100:.0f}%p 넘게 나쁘지 않음. "
          "그 밖은 FAIL, 중앙 IRR 차이가 0 보다 크지만 검정력 문턱보다 작으면 FAIL_UNDERPOWERED(판별 불가에 가까움).",
          f"- {r['power_line']} 여기서는 관측 효과로 '중앙 IRR 차이(연 수익률 차이)'를 MDE(연 정보비율)와 비교한다 — 단위가 달라 근사다. "
          "사실상 '중앙 차이가 양수면 FAIL_UNDERPOWERED, 0 이하면 FAIL' 이다.",
          f"- 구간이 크게 겹친다: 5년 판정 구간 {r['window_counts']['CHAMP']['5y_judged']}개지만 겹치지 않는 5년 구간은 약 "
          f"{(r['stats'][PRIMARY_SCENARIO]['CHAMP'][key5].get('effective_independent_windows') or 0):.1f}개뿐이다. "
          "비율 70% 는 독립 시행 수십 번의 70% 보다 훨씬 덜 확실하다.", ""]
    for scen in SCENARIOS:
        L += [f"## 시나리오 {SCENARIO_NAMES[scen]} — 5년 구간(판정 구간)", ""] + _table(r, scen, key5) + [""]
        sp = r["spy"][scen][key5]
        if sp.get("n_windows"):
            L += [f"SPY 자체: IRR 중앙 {_pct(sp['median_irr'])} · 10분위 {_pct(sp['p10_irr'])} · 시간가중 MDD 중앙 {_pct(sp['median_mdd_tw'])} · "
                  f"끝 금액 중앙 {_won(sp['median_terminal_krw'])}원(넣은 돈 {_won(sp['median_total_contributed_krw'])}원) · 양도세 중앙 {_won(sp['median_cgt_krw'])}원.", ""]
    L += ["## 10년 구간(보고만, 판정 구간)", ""]
    for scen in ("B", "A"):
        L += [f"### {SCENARIO_NAMES[scen]}", ""] + _table(r, scen, "10y_judged") + [""]
    L += [f"## {DECISION_END} 뒤에 끝나는 구간(보고만 — 20개 넘는 연구가 이미 본 구간)", ""]
    for h in HORIZONS:
        L += [f"### {SCENARIO_NAMES[PRIMARY_SCENARIO]}, {h}년", ""] + _table(r, PRIMARY_SCENARIO, f"{h}y_post") + [""]
    L += ["## 적립 방식이 결론을 바꿨나(같은 규칙을 목돈만 A 와 적립 B 에 적용, 5년)", "",
          "| 전략 | A 목돈만 | B 적립 | 바뀜 |", "|---|---|---|---|"]
    for c in STRATEGIES:
        f = r["framing_change"][c]
        L.append(f"| {c}{' (보고만)' if c in REPORTED_ONLY else ''} | {f['A_lump_sum']} | {f['B_contrib']} | {'예' if f['changed'] else '아니오'} |")
    L += ["", "같은 규칙으로 C·B10 에 적용한 결과(보고만): "
          + "; ".join(f"{c} C {r['same_rule']['C'][c]} / B10 {r['same_rule']['B10'][c]}" for c in STRATEGIES) + ".", "",
          "## 적립이 순위를 어떻게 바꿨나(5년, IRR 차이 중앙값 순)", "",
          "| 순위 | " + " | ".join(SCENARIO_NAMES[s].split(" ")[0] for s in SCENARIOS) + " |",
          "|---|" + "---|" * len(SCENARIOS)]
    for i in range(len(JUDGED)):
        L.append(f"| {i + 1} | " + " | ".join(r["ranking_by_median_irr_diff_5y"][s][i] for s in SCENARIOS) + " |")
    L += ["", "## 구간 수", "", "| 전략 | 5년 판정 | 5년 보고(2024-10 뒤 끝) | 10년 판정 | 10년 보고 | 첫 시작 |", "|---|---|---|---|---|---|"]
    for c in STRATEGIES:
        n = r["window_counts"][c]
        L.append(f"| {c} | {n['5y_judged']} | {n['5y_post']} | {n['10y_judged']} | {n['10y_post']} | {r['frame_info'][c]['start']} |")
    L += ["", "## 전략 출처(다시 구현하지 않고 그 연구의 함수를 부름)", ""]
    L += [f"- {c}: {NAMES[c]} — {SOURCES[c]}" for c in STRATEGIES]
    L += ["", "## 한계(꼭 읽기)", "",
          "- 구간이 크게 겹친다. 매달 시작하는 5년 구간 100여 개는 독립 표본이 아니다(겹치지 않는 구간은 약 3개). 비율·분위수는 '시작일 운'을 보여 줄 뿐 통계적 증거가 약하다.",
          "- 새틀라이트 생존편향: 상장폐지 종목이 가격 소스에 없다. 새틀라이트 비중이 큰 전략(P3·P4)일수록 결과가 좋게 기울어진다.",
          "- 이미 본 자료: 2010~2024 는 이 전략들을 만든 연구들이 이미 본 기간이다. 2024-10 뒤에 끝나는 구간은 보고만 한다. "
          "통과(CONTRIB_BEATS_SPY)는 '전진 원장에 올릴 후보'까지만 뜻한다.",
          "- 전체 기간 목표 비중 표를 한 번 만들어 구간마다 잘랐다. 구간 첫날은 그날의 (표류한) 목표 비중대로 산다 — 1월 리셋 전략은 1월이 아닌 달에 시작하면 "
          "목표 비율(예: 85/15)이 아니라 그때까지 표류한 비율로 시작한다. 새틀라이트는 그때 들고 있을 종목을 그대로 산다.",
          "- D1 은 13F 자료가 2014 부터라 구간이 2014-01 부터 시작하고 판정하지 않는다. L15F 의 2배 상품은 합성(SPY 총수익 × 2 − 차입·보수)이다.",
          "- 적립금은 시작 다음 달부터 매달 첫 거래일 종가에 넣는다. 금융소득 종합과세는 넣지 않았다. 세금은 추정이다.",
          "- 엔진(챔피언)은 바뀌지 않았다. 반영은 사용자 확인 뒤 별도 작업이다.",
          f"- 가격 없는 보유 종목: {', '.join(r['missing_prices']) or '없음'}.", ""]
    return "\n".join(L)


def smoke_coverage(r: dict, size: int) -> dict:
    key5 = f"{PRIMARY_HORIZON}y_judged"
    b, a = r["stats"]["B"]["CHAMP"][key5], r["stats"]["A"]["CHAMP"][key5]
    return {"verdicts": len(r["verdicts"]) == len(JUDGED),
            "all_scenarios": all(r["stats"][s][c][key5].get("n_windows", 0) > 0 for s in SCENARIOS for c in STRATEGIES),
            "contributions_applied": (b.get("median_total_contributed_krw") or 0) > (a.get("median_total_contributed_krw") or 0),
            "post_windows": r["window_counts"]["CHAMP"]["5y_post"] > 0,
            "d1_starts_2014": r["frame_info"]["D1"]["start"] >= "2014-01-01",
            "ten_year": r["window_counts"]["CHAMP"]["10y_judged"] > 0,
            "results_small": size < 200_000}


# =================================================================================================
# 실행
# =================================================================================================

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-sims-per-run", type=int, default=0, help="재개 확인용: 이번 실행의 새 시뮬레이션 수 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    step = SMOKE_STEP_MONTHS if a.smoke else STEP_MONTHS
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke), "step": step}
    epoch = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    mono = _deadline_mono(epoch)
    budget = {"new": 0}

    def log(s: str) -> None:
        print(s, flush=True)

    def check_time() -> None:
        if epoch is not None and time.time() > epoch - 90:
            raise _Stop()

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    def stage(name: str, fn):
        got = SV._load_ckpt(ck / f"{name}.pkl", fp)
        if got is None:
            check_time()
            got = fn()
            SV._atomic_pickle(ck / f"{name}.pkl", {"fingerprint": fp, "payload": got})
            log(f"입력 체크포인트 저장: {name}")
            gc.collect()
        return got

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    benches: dict = {}

    def save_bench(scen: str) -> None:
        if scen in benches:
            SV._atomic_pickle(ck / f"bench_{scen}.pkl", {"fingerprint": fp, "payload": benches[scen]})

    try:
        def prep_fn():
            base = stage("base", lambda: _smoke_base(log) if a.smoke else _real_base(log))
            krs = stage("krs", lambda: _smoke_krs(base, log) if a.smoke else _real_krs(base, log))
            lev = stage("lev", lambda: _smoke_lev(base, krs, log) if a.smoke else _real_lev(base, log))
            guru = stage("guru", lambda: _smoke_guru(log) if a.smoke else _real_guru(log))
            return assemble(base, krs, lev, guru)

        prep = stage("prep", prep_fn)
        wmaps = {s: strategy_windows(prep, s, step) for s in STRATEGIES}
        results = {}
        for scen in SCENARIOS:     # B(판정)부터
            benches[scen] = SV._load_ckpt(ck / f"bench_{scen}.pkl", fp) or {}
            cfg = scenario_config(scen)
            for strat in STRATEGIES:
                wins = all_windows(wmaps[strat])
                path = ck / f"win_{strat}_{scen}.pkl"
                while True:
                    lim = CHUNK
                    if a.max_sims_per_run:
                        lim = min(lim, a.max_sims_per_run - budget["new"])
                        if lim <= 0:
                            res = re_.evaluate_windows(prep["frames"][strat], prep["panels"], wins, cfg, cache_path=path,
                                                       benchmark_cache=benches[scen], fingerprint=fp, max_new=0)
                            if res["complete"]:
                                break
                            raise _Stop()
                    res = re_.evaluate_windows(prep["frames"][strat], prep["panels"], wins, cfg, cache_path=path,
                                               benchmark_cache=benches[scen], fingerprint=fp, max_new=lim, deadline=mono)
                    budget["new"] += res["new_sims"]
                    if res["new_sims"]:
                        save_bench(scen)
                    if res["complete"]:
                        break
                    if res["new_sims"] == 0 or (mono is not None and time.monotonic() >= mono):
                        raise _Stop()
                results[(strat, scen)] = res
                log(f"{scen} {strat}: 구간 {res['done']}개 완료")
        result, rep = analyze(prep, results, wmaps, a.smoke, step)
        text = json.dumps(result, ensure_ascii=False, default=str, separators=(",", ":"))
        if a.smoke:
            cov = smoke_coverage(result, len(text.encode("utf-8")))
            result["smoke_coverage"] = cov
            bad = [k for k, v in cov.items() if not v]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
            text = json.dumps(result, ensure_ascii=False, default=str, separators=(",", ":"))
    except _Stop:
        for scen in list(benches):
            save_bench(scen)
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    (out / "results.json").write_text(text, encoding="utf-8")
    (out / "REPORT.md").write_text(rep, encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
