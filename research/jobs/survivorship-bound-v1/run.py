"""검증 연구 survivorship-bound-v1 (사전 등록, 2026-10-11): 새틀라이트 연구들(satellite-value-v1·sleeve-weight-v1 등)은
야후 가격 소스로 만든 champion40(pit2) 후보 풀을 쓰고, 상장폐지·흡수합병 종목은 그 소스에 가격이 없어 후보에서 빠진다
(생존편향). CRSP·WRDS 같은 유료 PIT 데이터가 없어 실제 편향 크기는 추정할 수 없다 — 이 연구는 추정하지 않고 **한계를
긋는다**: 그럴듯한 편향 시나리오를 주입해도 기존 결론(새틀라이트 15% > SPY 15%, 35% > 15%)이 버티는지를 본다.

계약·격자·판정은 같은 폴더 SPEC.md(결과를 보기 전에 고정). 1부(결측 측정)·2부(유령 대체 스트레스)는 SPEC.md 그대로.
satellite-value-v1 의 입력·엔진을 importlib 로 재사용한다(복사하지 않음). 가설검정이 아니므로 power_report 는 쓰지
않는다(results.json 의 "power" 는 null + 이유). A−B·A35−A15 비교에는 noop_guard 를 쓴다.
전체 계산은 VM 연구 실행기만 한다. 대화·Codespace 에서는 --smoke(가짜 데이터, 네트워크 없음)만.
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

_spec = importlib.util.spec_from_file_location(
    "survivorship_bound_satval_engine", PROJECT_ROOT / "research" / "jobs" / "satellite-value-v1" / "run.py")
satval = sys.modules.setdefault("survivorship_bound_satval_engine", importlib.util.module_from_spec(_spec))
_spec.loader.exec_module(satval)

JOB_ID = "survivorship-bound-v1"
RULES_VERSION = "survivorship-bound-v1/2026-10-11"
DECISION_END = satval.DECISION_END                # "2024-09-30"
SAT_WEIGHTS = {"A15": 0.15, "A35": 0.35}
MIN_AB_EDGE = 0.003                                # +0.3%p (A-B)
MIN_SLEEVE_GAIN = 0.010                            # +1.0%p (35% vs 15%)
K_VALUES = (1, 2)
D_PP_VALUES = (0.0, 5.0, 10.0, 20.0, 40.0)         # 연 %p
Q_VALUES = (0.02, 0.05)
ROBUST_CELL = {"g": "upper", "k": 2, "d_pp": 10.0}
ROBUST_DISTRESS_CELL = {"g": "upper", "k": 2, "q": 0.05}
FRAGILE_CELL = {"g": "central", "k": 1, "d_pp": 10.0}
REBAL_MONTHS = (1, 7)
MEMBERSHIP_START_YEAR, MEMBERSHIP_END_YEAR = 2010, 2026
PRICE_WINDOW_DAYS = 10                             # 리밸런싱일 ±거래일 — "쓸 수 있는 가격" 판정
ROBUST, FRAGILE, INCONCLUSIVE, NOT_EVALUABLE = (
    "ROBUST_TO_SURVIVORSHIP", "FRAGILE", "INCONCLUSIVE_BIAS_SENSITIVE", "NOT_EVALUABLE")


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


# =================================================================================================
# 1부 — 결측 측정 (순수 함수 — tests/test_survivorship_bound.py)
# =================================================================================================

def pit_members_at(dates: tuple, members: tuple, d: date) -> frozenset:
    """정렬된 (날짜, 그 날 이후부터 유효한 편입 집합) 테이블에서 d 시점 편입 명단."""
    from bisect import bisect_right

    i = bisect_right(dates, d) - 1
    return members[i] if i >= 0 else frozenset()


def rebalance_calendar(start_year: int, end_year: int, months: tuple = REBAL_MONTHS) -> list[date]:
    return [date(y, m, 1) for y in range(start_year, end_year + 1) for m in months if date(y, m, 1) <= date.today()]


def membership_gap_stats(dates: tuple, members: tuple, available: set, cap_rank: dict,
                          end_of_window: date, *, start_year: int = MEMBERSHIP_START_YEAR,
                          end_year: int = MEMBERSHIP_END_YEAR) -> dict:
    """SPEC.md 1부. dates/members 는 pit_members_at 과 같은 PIT 테이블. available 은 "쓸 수 있는 가격이 있는" 티커 집합.
    cap_rank 는 (티커, 리밸런싱일 iso문자열) -> 그 날 시총 순위(1=최대, available 종목 안에서만) — 없으면 생략해도 된다.
    end_of_window 이전에 그 티커가 PIT 명단에서 영구히 사라졌으면(편출) removed_before_end 로 센다."""
    cal = rebalance_calendar(start_year, end_year)
    rows, by_year = [], {}
    all_missing: set = set()
    for d in cal:
        mem = pit_members_at(dates, members, d)
        if not mem:
            continue
        missing = sorted(mem - available)
        n = len(mem)
        f_all = len(missing) / n if n else float("nan")
        ranks = sorted(r for t in mem if t in available for r in [cap_rank.get((t, d.isoformat()))] if r is not None)
        rows.append({"date": d.isoformat(), "n_members": n, "n_missing": len(missing), "f_all": f_all,
                     "missing": missing, "available_cap_rank_count": len(ranks)})
        by_year.setdefault(d.year, []).append(f_all)
        all_missing.update(missing)

    def _removed_before_end(t: str) -> bool:
        # 그 티커가 포함된 가장 마지막 PIT 행의 날짜가 end_of_window 보다 전이면 "편출됨"(계속 있는데 가격만 없는 것과 구분).
        last_seen = None
        for dt, mem in zip(dates, members):
            if t in mem:
                last_seen = dt
        return last_seen is not None and last_seen < end_of_window

    removed = sorted(t for t in all_missing if _removed_before_end(t))
    avg_f_all = float(np.mean([r["f_all"] for r in rows])) if rows else float("nan")
    f_top40_upper = avg_f_all
    f_top40_central = avg_f_all / 2.0
    return {
        "rebalance_rows": rows,
        "by_year_avg_f_all": {y: float(np.mean(vs)) for y, vs in by_year.items()},
        "avg_f_all": avg_f_all,
        "n_missing_distinct": len(all_missing),
        "n_removed_before_end": len(removed),
        "removed_before_end": removed,
        "f_top40": {
            "upper": f_top40_upper, "central": f_top40_central,
            "method_upper": "f_all 그대로(상한) — 상위 40 만 떼어 봐도 결측 종목 시총을 모름",
            "method_central": "가정: 결측 종목이 상위 40 자격에 들 확률은 평균 편입 종목의 절반(f_all/2). 실측 아님.",
            "method_ii_derivable": False,
            "method_ii_reason": "결측 종목은 가격이 전혀 없어 point_in_time_market_cap 도 그 종목의 과거 시총을 "
                                 "계산할 수 없다(시총 = 발행주식수 x 그 시점 종가, 가격이 없으면 계산 불가) — "
                                 "결측 종목 쪽으로 가중한 상한 보정은 이 데이터로는 끌어낼 수 없다.",
        },
    }


def _usable_price_mask(close_by_ticker: dict, rebal_dates: list[date], window_days: int = PRICE_WINDOW_DAYS) -> dict:
    """{티커: 그 날 ±window_days 거래일 안에 쓸 수 있는(Close 결측 아닌) 가격이 있는 날짜 집합(iso)}."""
    out = {}
    for t, s in close_by_ticker.items():
        s = s.dropna()
        if s.empty:
            out[t] = set()
            continue
        idx = s.index
        ok = set()
        for d in rebal_dates:
            ts = pd.Timestamp(d)
            near = idx[(idx >= ts - pd.Timedelta(days=window_days * 2)) & (idx <= ts + pd.Timedelta(days=window_days * 2))]
            if len(near):
                ok.add(d.isoformat())
        out[t] = ok
    return out


# =================================================================================================
# 2부 — 유령 대체 (순수 함수)
# =================================================================================================

def ghost_period_return(pick_ret: float, period_years: float, *, d_pp: Optional[float] = None,
                        q: Optional[float] = None, market_ret: Optional[float] = None) -> float:
    """SPEC.md 2부. d_pp 가 주어지면 부족분 모형(연 d%p 를 구간 연수에 비례해 뺀다), q 가 주어지면 파산 모형
    (기댓값: q*(-0.5) + (1-q)*시장수익)."""
    if d_pp is not None:
        return pick_ret - (d_pp / 100.0) * period_years
    if q is not None:
        mkt = 0.0 if market_ret is None else market_ret
        return q * -0.5 + (1 - q) * mkt
    raise ValueError("d_pp 또는 q 중 하나는 있어야 합니다")


def blended_period_return(pick_ret: float, ghost_ret: float, frac: float) -> float:
    frac = min(1.0, max(0.0, frac))
    return (1 - frac) * pick_ret + frac * ghost_ret


def scale_daily_log_returns(log_r: np.ndarray, target_period_ret: float) -> np.ndarray:
    """구간의 일별 로그수익 모양은 유지하고 합계만 target_period_ret 에 맞춘다(선형 스케일).
    원래 구간 수익이 -100%에 가까우면(분모 0) 균등 분배로 대체한다."""
    n = len(log_r)
    if n == 0:
        return log_r
    orig_total = float(log_r.sum())
    target_total = math.log1p(target_period_ret) if target_period_ret > -1 else -50.0
    if abs(orig_total) < 1e-12:
        return np.full(n, target_total / n)
    return log_r * (target_total / orig_total)


def interpolate_break_even(d_values: list, diff_values: list) -> Optional[float]:
    """diff(d) 가 d 증가에 따라 내려간다고 보고(부족분이 커질수록 우위가 줄어듦) diff=0 이 되는 d 를 선형 보간.
    격자 안에서 부호가 안 바뀌면 None(격자 범위 밖)."""
    pts = sorted(zip(d_values, diff_values))
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        if (v0 >= 0) != (v1 >= 0) or v0 == 0 or v1 == 0:
            if v1 == v0:
                continue
            return d0 + (0 - v0) * (d1 - d0) / (v1 - v0)
    return None


def judge(ab_diff_by_cell: dict, ab_distress_by_cell: dict, sleeve_gain_by_cell: dict,
          sleeve_distress_by_cell: dict, noop_ab: Optional[str], noop_sleeve: Optional[str]) -> dict:
    """SPEC.md 사전 등록 판정. 각 *_by_cell 은 (g, k, d_pp_또는_q) -> 차이(소수) 딱, 키는 run_grid() 가 만드는 튜플."""
    def classify(cell_diff: dict, distress_diff: dict, fragile_v: float, threshold: float) -> str:
        robust_key = (ROBUST_CELL["g"], ROBUST_CELL["k"], ROBUST_CELL["d_pp"])
        robust_distress_key = (ROBUST_DISTRESS_CELL["g"], ROBUST_DISTRESS_CELL["k"], ROBUST_DISTRESS_CELL["q"])
        robust_v, robust_dv = cell_diff.get(robust_key), distress_diff.get(robust_distress_key)
        if robust_v is not None and robust_dv is not None and robust_v >= threshold and robust_dv >= threshold:
            return ROBUST
        if fragile_v is not None and fragile_v <= 0:
            return FRAGILE
        return INCONCLUSIVE

    fragile_key = (FRAGILE_CELL["g"], FRAGILE_CELL["k"], FRAGILE_CELL["d_pp"])
    ab_verdict = NOT_EVALUABLE if noop_ab else classify(ab_diff_by_cell, ab_distress_by_cell,
                                                        ab_diff_by_cell.get(fragile_key), MIN_AB_EDGE)
    sleeve_verdict = NOT_EVALUABLE if noop_sleeve else classify(sleeve_gain_by_cell, sleeve_distress_by_cell,
                                                               sleeve_gain_by_cell.get(fragile_key), MIN_SLEEVE_GAIN)
    return {"satellite_vs_spy15": ab_verdict, "sleeve_35_vs_15": sleeve_verdict}


# =================================================================================================
# 체크포인트 (satellite-value-v1 과 같은 패턴)
# =================================================================================================

def _atomic_pickle(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_ckpt(path: Path, fingerprint: dict):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
    except Exception:  # noqa: BLE001
        return None
    return obj["payload"] if obj.get("fingerprint") == fingerprint else None


# =================================================================================================
# 입력·파이프라인
# =================================================================================================

def _membership_table():
    from core import hypothesis_engine as he

    return he._sp500_rows()


def _real_membership_gap(log) -> dict:
    from core.market_data import get_multiple_price_history

    dates, members = _membership_table()
    cal = rebalance_calendar(MEMBERSHIP_START_YEAR, MEMBERSHIP_END_YEAR)
    universe = sorted({t for d in cal for t in pit_members_at(dates, members, d)})
    log(f"결측 측정: 종목 {len(universe)}개 가격 조회")
    hist = get_multiple_price_history(universe, start="2008-01-01", end=None, interval="1d")
    close_by = {t: df["Close"].dropna() for t, df in hist.items() if df is not None and not df.empty and "Close" in df}
    usable = _usable_price_mask(close_by, cal)
    available = {t for t, days in usable.items() if days}

    cap_rank: dict = {}
    for d in cal:
        mem = sorted(pit_members_at(dates, members, d) & available)
        if not mem:
            continue
        from core.point_in_time_market_cap import get_market_caps_asof_batch
        caps = get_market_caps_asof_batch(mem, d.isoformat())
        ranked = sorted((t for t in mem if caps.get(t)), key=lambda t: caps[t], reverse=True)
        for i, t in enumerate(ranked, start=1):
            cap_rank[(t, d.isoformat())] = i
    return membership_gap_stats(dates, members, available, cap_rank, date(2026, 10, 1))


def _smoke_membership_gap() -> dict:
    """합성 결측 측정(네트워크 없음) — 손으로 만든 소형 PIT 테이블로 대신한다."""
    dates = (date(2010, 1, 1), date(2015, 1, 1), date(2020, 1, 1))
    members = (frozenset({"A", "B", "C", "D"}), frozenset({"A", "B", "D", "E"}), frozenset({"A", "D", "E", "F"}))
    available = {"A", "D", "E", "F"}  # B, C 는 가격 없음(합성)
    return membership_gap_stats(dates, members, available, {}, date(2026, 10, 1), start_year=2010, end_year=2020)


def _build_ghost_price_panel(close: pd.DataFrame, adj: pd.DataFrame, log: list[dict], spy_col: str,
                             frac: float, *, d_pp: Optional[float] = None, q: Optional[float] = None) -> pd.Series:
    """반기 선정 로그(각 항목 picks=weights 의 키)의 구간마다 유령 대체를 섞은 합성 "GHOST" 가격 열(시작값 100)."""
    entries = sorted(({"date": pd.Timestamp(r["date"]), "picks": sorted((r.get("weights") or {}).keys())} for r in log),
                     key=lambda r: r["date"])
    idx = adj.index
    end = idx[-1]
    px = pd.Series(np.nan, index=idx)
    level = 100.0
    prev_end = None
    for i, e in enumerate(entries):
        d0 = e["date"]
        d1 = entries[i + 1]["date"] if i + 1 < len(entries) else end
        window = idx[(idx >= d0) & (idx <= d1)]
        if len(window) < 2:
            continue
        picks = [t for t in e["picks"] if t in adj.columns]
        if picks:
            basket = adj.loc[window, picks].ffill()
            daily = basket.pct_change().iloc[1:].mean(axis=1).fillna(0.0)
        else:
            daily = pd.Series(0.0, index=window[1:])
        log_r = np.log1p(daily.to_numpy())
        pick_ret = float(np.exp(log_r.sum()) - 1.0)
        years = (window[-1] - window[0]).days / 365.25
        mkt_ret = None
        if q is not None and spy_col in adj.columns:
            s = adj.loc[window, spy_col].ffill()
            mkt_ret = float(s.iloc[-1] / s.iloc[0] - 1.0)
        ghost_ret = ghost_period_return(pick_ret, years, d_pp=d_pp, q=q, market_ret=mkt_ret)
        target = blended_period_return(pick_ret, ghost_ret, frac)
        scaled = scale_daily_log_returns(log_r, target)
        mult = np.exp(np.concatenate([[0.0], np.cumsum(scaled)]))
        seg = level * mult
        px.loc[window] = seg
        level = float(seg[-1])
        prev_end = d1
    px = px.ffill().bfill()
    return px


def _pair_diff(va: pd.Series, vb: pd.Series, initial: float, segs: dict) -> dict:
    out = {k: satval.seg_ann(va, initial, t0, t1) - satval.seg_ann(vb, initial, t0, t1) for k, (t0, t1) in segs.items()}
    dec_end = segs["decision"][1]
    ra, rb = satval.window_returns(va, initial, dec_end), satval.window_returns(vb, initial, dec_end)
    out["noop_reason"] = rp.noop_guard((ra - rb).to_numpy())
    return out


def _simulate_variant(core_w: pd.DataFrame, close: pd.DataFrame, adj: pd.DataFrame, fx: pd.Series, cfg,
                      sat_log: list[dict], weight: float) -> pd.Series:
    w = tx.champion_weights(core_w, sat_log, weight)
    r = tx.simulate(w.reindex(w.index), close, adj, fx, cfg)
    return r["values_krw"]


def _reproduction_check(real_decision_a: float, real_decision_b: float) -> dict:
    path = PROJECT_ROOT / "research" / "results" / "satellite-value-v1" / "results.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        a = old["metrics"]["base_30m"]["A"]["segments_after_tax"]["decision"]
        b = old["metrics"]["base_30m"]["B"]["segments_after_tax"]["decision"]
    except (OSError, ValueError, KeyError):
        return {"available": False}
    gap_a, gap_b = abs(real_decision_a - a), abs(real_decision_b - b)
    return {"available": True, "old_A_decision": a, "old_B_decision": b, "new_A_decision_no_ghost": real_decision_a,
            "new_B_decision": real_decision_b, "gap_A_pp": gap_a * 100, "gap_B_pp": gap_b * 100,
            "reproduced_within_0.05pp": gap_a <= 0.0005 and gap_b <= 0.0005}


def run_pipeline(inputs: dict, membership: dict, log, check_time, state: dict, ck: Path, fp: dict, *, smoke: bool = False) -> dict:
    core_w, sat_log, close, adj, fx = inputs["core_w"], inputs["logs"]["A"], inputs["close"], inputs["adj"], inputs["fx"]
    cfg = tx.AccountConfig()
    initial = cfg.initial_krw
    idx = tx.champion_weights(core_w, sat_log, 0.15).index
    segs = satval.segments(idx)

    def _ckpt_sim(name: str, fn) -> pd.Series:
        path = ck / f"sim_{name}.pkl"
        got = _load_ckpt(path, fp)
        if got is not None:
            return got
        check_time()
        log(f"시뮬레이션 {name}")
        v = fn()
        _atomic_pickle(path, {"fingerprint": fp, "payload": v})
        return v

    values_a = {w: _ckpt_sim(f"A{int(w*100)}_noghost", lambda w=w: _simulate_variant(core_w, close, adj, fx, cfg, sat_log, w))
                for w in SAT_WEIGHTS.values()}
    spy_log = [{"date": r["date"], "weights": {"SPY": 1.0}} for r in sat_log]
    values_b15 = _ckpt_sim("B15", lambda: _simulate_variant(core_w, close, adj, fx, cfg, spy_log, SAT_WEIGHTS["A15"]))

    f_top40 = membership["f_top40"]
    cells, distress_cells = {}, {}
    ab_diff, ab_distress, sleeve_gain, sleeve_distress = {}, {}, {}, {}
    noop_ab = noop_sleeve = None
    for gname, gval in f_top40.items():
        if gname not in ("upper", "central"):
            continue
        for k in K_VALUES:
            frac = min(1.0, gval * k)
            for d_pp in D_PP_VALUES:
                tag = f"ghost_{gname}_k{k}_d{d_pp:g}"
                ghost_px = _ckpt_sim(f"px_{tag}", lambda frac=frac, d_pp=d_pp: _build_ghost_price_panel(
                    close, adj, sat_log, "SPY", frac, d_pp=d_pp))
                close_g, adj_g = close.copy(), adj.copy()
                close_g["GHOST"], adj_g["GHOST"] = ghost_px, ghost_px
                ghost_log = [{"date": r["date"], "weights": {"GHOST": 1.0}} for r in sat_log]
                v15 = _ckpt_sim(f"{tag}_w15", lambda: _simulate_variant(core_w, close_g, adj_g, fx, cfg, ghost_log, SAT_WEIGHTS["A15"]))
                v35 = _ckpt_sim(f"{tag}_w35", lambda: _simulate_variant(core_w, close_g, adj_g, fx, cfg, ghost_log, SAT_WEIGHTS["A35"]))
                diff_ab = _pair_diff(v15, values_b15, initial, segs)
                diff_sleeve = _pair_diff(v35, v15, initial, segs)
                key = (gname, k, d_pp)
                ab_diff[key] = diff_ab["decision"]
                sleeve_gain[key] = diff_sleeve["decision"]
                cells[key] = {"ab_decision_diff": diff_ab["decision"], "sleeve_decision_gain": diff_sleeve["decision"]}
                if key == (ROBUST_CELL["g"], ROBUST_CELL["k"], ROBUST_CELL["d_pp"]) or \
                   key == (FRAGILE_CELL["g"], FRAGILE_CELL["k"], FRAGILE_CELL["d_pp"]):
                    noop_ab = noop_ab or diff_ab["noop_reason"]
                    noop_sleeve = noop_sleeve or diff_sleeve["noop_reason"]
            for q in Q_VALUES:
                tag = f"ghostq_{gname}_k{k}_q{q:g}"
                ghost_px = _ckpt_sim(f"px_{tag}", lambda frac=frac, q=q: _build_ghost_price_panel(
                    close, adj, sat_log, "SPY", frac, q=q))
                close_g, adj_g = close.copy(), adj.copy()
                close_g["GHOST"], adj_g["GHOST"] = ghost_px, ghost_px
                ghost_log = [{"date": r["date"], "weights": {"GHOST": 1.0}} for r in sat_log]
                v15 = _ckpt_sim(f"{tag}_w15", lambda: _simulate_variant(core_w, close_g, adj_g, fx, cfg, ghost_log, SAT_WEIGHTS["A15"]))
                v35 = _ckpt_sim(f"{tag}_w35", lambda: _simulate_variant(core_w, close_g, adj_g, fx, cfg, ghost_log, SAT_WEIGHTS["A35"]))
                diff_ab = _pair_diff(v15, values_b15, initial, segs)
                diff_sleeve = _pair_diff(v35, v15, initial, segs)
                key = (gname, k, q)
                ab_distress[key] = diff_ab["decision"]
                sleeve_distress[key] = diff_sleeve["decision"]
                distress_cells[key] = {"ab_decision_diff": diff_ab["decision"], "sleeve_decision_gain": diff_sleeve["decision"]}

    break_even_ab, break_even_sleeve = {}, {}
    for gname in ("upper", "central"):
        for k in K_VALUES:
            ds = list(D_PP_VALUES)
            break_even_ab[(gname, k)] = interpolate_break_even(ds, [ab_diff[(gname, k, d)] for d in ds])
            break_even_sleeve[(gname, k)] = interpolate_break_even(ds, [sleeve_gain[(gname, k, d)] for d in ds])

    verdicts = judge(ab_diff, ab_distress, sleeve_gain, sleeve_distress, noop_ab, noop_sleeve)
    repro = ({"available": False, "reason": "스모크(합성 데이터) — satellite-value-v1 실데이터와 비교하지 않음"} if smoke else
             _reproduction_check(satval.seg_ann(values_a[SAT_WEIGHTS["A15"]], initial, *segs["decision"]),
                                 satval.seg_ann(values_b15, initial, *segs["decision"])))
    return {
        "segments": {k: [str(t0.date()) if t0 is not None else str(idx[0].date()), str(t1.date())] for k, (t0, t1) in segs.items()},
        "f_top40": f_top40, "cells": {str(k): v for k, v in cells.items()}, "distress_cells": {str(k): v for k, v in distress_cells.items()},
        "break_even_d_pp_ab": {str(k): v for k, v in break_even_ab.items()},
        "break_even_d_pp_sleeve": {str(k): v for k, v in break_even_sleeve.items()},
        "verdicts": verdicts, "noop_ab": noop_ab, "noop_sleeve": noop_sleeve, "reproduction": repro,
        "no_ghost_decision": {"A15": satval.seg_ann(values_a[SAT_WEIGHTS["A15"]], initial, *segs["decision"]),
                              "A35": satval.seg_ann(values_a[SAT_WEIGHTS["A35"]], initial, *segs["decision"]),
                              "B15": satval.seg_ann(values_b15, initial, *segs["decision"])},
    }


def _report(result: dict, smoke: bool) -> str:
    v = result["verdicts"]
    L = [f"# 생존편향 한계 측정 — champion40 새틀라이트 결론이 그럴듯한 편향 아래서도 버티는가"
         f"{' (스모크 — 합성 데이터)' if smoke else ''}", "",
         f"판정(새틀라이트 15% vs SPY 15%, A−B): **{v['satellite_vs_spy15']}**",
         f"판정(새틀라이트 35% vs 15%, 세후 CAGR 이득): **{v['sleeve_35_vs_15']}**", "",
         "이 연구는 실제 생존편향 크기를 추정하지 않는다 — 그럴듯한 편향 시나리오에서도 기존 결론이 버티는지만 본다.",
         f"검정력(power_report): 쓰지 않음(가설검정이 아니라 사전 고정 스트레스 격자). "
         f"무효 실행 가드 — A−B: {result['noop_ab'] or '통과'}, 35%−15%: {result['noop_sleeve'] or '통과'}.", "",
         "## 1부 — champion40 결측 추정", "",
         f"- f_top40 상한(= 멤버십 결측 비율 f_all 그대로) {result['f_top40']['upper']:.1%}",
         f"- f_top40 중심값(가정: f_all/2) {result['f_top40']['central']:.1%}",
         f"- 방법(ii)(결측 종목 시총으로 가중 보정): {result['f_top40']['method_ii_reason']}", "",
         "## 2부 — 손익분기 d*(연 %p, A−B = 0)", "",
         "| g | k | d* |", "|---|---|---|"]
    for key, d in result["break_even_d_pp_ab"].items():
        L.append(f"| {key} | — | {'격자 범위 밖' if d is None else f'{d:.1f}%p/년'} |")
    L += ["", "## 손익분기 d*(35% vs 15% 세후 CAGR 이득 = 0)", "", "| (g,k) | d* |", "|---|---|"]
    for key, d in result["break_even_d_pp_sleeve"].items():
        L.append(f"| {key} | {'격자 범위 밖' if d is None else f'{d:.1f}%p/년'} |")
    repro = result["reproduction"]
    if repro.get("available"):
        L += ["", "## satellite-value-v1 기준 재현", "",
              f"옛 A(판정 구간) {repro['old_A_decision']:.2%} vs 이번(유령 없음) {repro['new_A_decision_no_ghost']:.2%} "
              f"(차이 {repro['gap_A_pp']:.3f}%p), 옛 B {repro['old_B_decision']:.2%} vs 이번 {repro['new_B_decision']:.2%} "
              f"(차이 {repro['gap_B_pp']:.3f}%p) — {'재현됨(±0.05%p 이내)' if repro['reproduced_within_0.05pp'] else '재현 안 됨'}."]
    L += ["", "## 격자(모두 사전 고정 — 추정 아님)", "",
          f"g ∈ {{central={result['f_top40']['central']:.1%}, upper={result['f_top40']['upper']:.1%}}}, k ∈ {K_VALUES}, "
          f"d ∈ {D_PP_VALUES}%p/년(부족분 모형), q ∈ {Q_VALUES}(파산 모형, 기댓값).", "",
          "## 한계", "",
          "- 실제 생존편향 크기를 추정하지 않는다(CRSP·WRDS 없음) — 한계(bound)만 긋는다.",
          "- 유령 섞인 합성 가격 열은 배당을 주지 않는다(A 를 실제보다 보수적으로 — 더 나쁘게 — 만드는 방향).",
          "- 파산 확률 q 는 몬테카를로가 아니라 기댓값이다(재현성 우선).",
          "- 구간 내 수익 재배분은 '같은 모양, 다른 합계' 스케일링이다(실제 유령 종목의 날짜별 경로가 아니다).",
          "- ROBUST_TO_SURVIVORSHIP 도 사람 검토 후보일 뿐이며 엔진 반영은 사용자 확인 뒤 별도 작업이다."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH", "inf"))

    def log(s: str) -> None:
        print(s, flush=True)

    def check_time(margin: float = 90.0) -> None:
        if time.time() > deadline - margin:
            raise _Stop()

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old_handler = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        membership = _load_ckpt(ck / "membership.pkl", fp)
        if membership is None:
            membership = _smoke_membership_gap() if a.smoke else _real_membership_gap(log)
            _atomic_pickle(ck / "membership.pkl", {"fingerprint": fp, "payload": membership})
            log("결측 측정 체크포인트 저장")
        inputs = _load_ckpt(ck / "inputs.pkl", fp)
        if inputs is None:
            inputs = satval._smoke_inputs(log) if a.smoke else satval._real_inputs(log)
            _atomic_pickle(ck / "inputs.pkl", {"fingerprint": fp, "payload": inputs})
            log("입력 체크포인트 저장")
        state: dict = {}
        result = run_pipeline(inputs, membership, log, check_time, state, ck, fp, smoke=a.smoke)
    except _Stop:
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old_handler is not None:
            _signal.signal(_signal.SIGTERM, old_handler)

    payload = {"id": JOB_ID, "rules_version": RULES_VERSION, "smoke": a.smoke,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "power": None, "power_reason": "가설검정이 아니라 사전 고정 스트레스 격자라 검정력 사전 계산을 쓰지 않는다.",
               **result}
    if a.smoke:
        payload["verdicts"] = {k: f"SMOKE_ONLY({v})" for k, v in result["verdicts"].items()}
    report = _report(result, a.smoke)
    tmp = out / "results.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, out / "results.json")
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    log(json.dumps(payload["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
