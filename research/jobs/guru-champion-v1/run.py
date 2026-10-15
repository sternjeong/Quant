"""검증 guru-champion-v1 (2026-10-15 사전 등록): 거장 보유 우선 새틀라이트(S-SEED-019)는 챔피언을 세후 원화로 낫게 하는가.

계기: guru-mechanism-v1 은 S-SEED-019 의 효과가 대형주 쏠림이 아니라 거장 보유에서 온다는 쪽을 지지했다(무작위·시총 위약,
거장 한 명씩 빼기). 그러나 새틀라이트 슬리브 단독·세전·같은 풀(sp500_pit)의 현 규칙 대비였다. 이 연구는 '챔피언 전체'(코어 85% +
새틀라이트 15%)와 'SPY 85% + 새틀라이트 15%' 에서 한국 세금(core/tax_fx.py)까지 넣어 잰다.
**이미 본 데이터(2014~2024, 같은 13F)를 다시 쓰므로 PASS 여도 '전진 원장 수준의 발견'일 뿐이다.** S-SEED-019 는 이미 전진 원장
(core/forward_tournament_v2.py 의 S1)에 올라 있다. 엔진 변경은 사용자 확인 뒤 별도 작업이다.

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
새틀라이트 일정(core.satellite_lab.run_variant 그대로, 반기 1·7월 첫 거래일, 상위 3 균등):
  S0  S-SEED-000(라이브 현 규칙) — champion40 풀(라이브와 같음)
  S0p S-SEED-000 — sp500_pit 풀(풀 대조군)
  S1  S-SEED-019(거장 보유 우선) — sp500_pit 풀. 13F 는 리밸런싱 전날까지 '공시된' 것만(core.guru_history.view_from_filings)
챔피언(tax_fx.simulate, 카카오페이증권 기본값, 3,000만 원 판정 / 1억 원 보고):
  C0  코어 85% + S0 15% [기준 — satellite-value-v1 의 A 와 같은 비중]
  C1  코어 85% + S1 15%
  C1p 코어 85% + S0p 15% [풀 대조군, 보고]
  D0  SPY 85% + S0 15% [기준]
  D1  SPY 85% + S1 15%
  C 계열 슬리브 규약은 satellite-value-v1 과 같다(목표가 바뀌는 날 모든 종목을 목표로). D 계열은 SPY 를 사서 들고 있고,
  매년 1월 첫 거래일에만 85/15 로 맞춘다. 7월 새틀라이트 교체일의 목표 = 1월 이후 가격(배당 포함)대로 표류한 비중
  (SPY 몫 그대로, 새틀라이트 몫은 새 종목에 균등) — tax_fx 가 그날 SPY 를 거의 건드리지 않는다(세금 현금·배당 차이만큼의 잔매매).
구간: 판정 = 2014-01-02(첫 13F 반영 리밸런싱) ~ 2024-09-30. 절반 = ~2019-05-31 / 2019-06-01~. 2024-10 이후는 보고만.
판정(두 비교 각각: C1 vs C0, D1 vs D0): PASS_FORWARD_CANDIDATE ⇔ 모두
  (a) 판정 구간 세후 연수익 차이 > 0   (b) 두 절반 모두 > 0
  (c) 판정 구간 원화 MDD 가 기준보다 3%p 넘게 나쁘지 않음(후보 MDD − 기준 MDD ≥ −0.03)
  (d) 126거래일 블록 부트스트랩 1,000회(시드 20261018) 90% 구간 하한 > −0.5%p
  그 밖 FAIL(classify_fail 로 FAIL_UNDERPOWERED 구분), noop_guard 걸리거나 수치가 유한하지 않거나 첫 리밸런싱에 13F 가 없으면 NOT_EVALUABLE.
  C1 vs C1p(풀 고정 거장 효과)·C1p vs C0(풀 효과)는 보고만. 검정력 power_report(10.75, 2).
한계: 13F 종목명→티커 매칭은 보유 평가액의 약 72~78% 만 덮는다. 상장폐지 종목 가격 결측(생존편향). 이미 본 구간.
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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402


def _load_job(name: str, job: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "research" / "jobs" / job / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sv = _load_job("_gc_satellite_value_v1", "satellite-value-v1")   # 세후 계좌·부트스트랩·구간 함수 재사용
gm = _load_job("_gc_guru_mechanism_v1", "guru-mechanism-v1")     # 13F 보기·합성 13F 재사용

JOB_ID = "guru-champion-v1"
RULES_VERSION = "guru-champion-v1/2026-10-15"
CORE_START = sv.START             # 코어 백테스트는 satellite-value-v1 과 같은 시작(같은 코어 비중)
DATA_START = "2013-12-01"         # 새틀라이트 가격·풀 읽기 시작(첫 리밸런싱 2014-01 의 전날이 있게)
JUDGE_START = "2014-01-01"        # 이 날 이후 첫 리밸런싱일부터 모든 변형 시작
H1_END = "2019-05-31"
DECISION_END = "2024-09-30"
SAT_WEIGHT = 0.15
SPY_WEIGHT = 0.85
MDD_TOL = 0.03
CI_LOW_FLOOR = -0.005
N_BOOT = 1000
BLOCK_DAYS = 126
BOOT_SEED = 20261018
CI_PCT = (5.0, 95.0)
POWER_YEARS, POWER_TRIALS = 10.75, 2
VARIANTS = ("C0", "C1", "C1p", "D0", "D1")
SETUPS = {"base_30m": {}, "base_100m": {"initial_krw": 100_000_000}}
DECISION_SETUP = "base_30m"
JUDGED = {"C1_vs_C0": ("C1", "C0"), "D1_vs_D0": ("D1", "D0")}
REPORTED = {"C1_vs_C1p": ("C1", "C1p"), "C1p_vs_C0": ("C1p", "C0"), "D1_vs_C0": ("D1", "C0")}
NAMES = {"C0": "코어 85% + S0 15%(현 챔피언, champion40)", "C1": "코어 85% + S1 15%(거장 우선, sp500_pit)",
         "C1p": "코어 85% + S0p 15%(현 규칙, sp500_pit — 풀 대조군)", "D0": "SPY 85% + S0 15%",
         "D1": "SPY 85% + S1 15%"}
SLEEVE_OF = {"C0": "S0", "C1": "S1", "C1p": "S0p", "D0": "S0", "D1": "S1"}

PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


# =================================================================================================
# 판정·구간 (순수 함수 — tests/test_guru_champion.py)
# =================================================================================================

def decide(full_diff, h1_diff, h2_diff, mdd_cand, mdd_ref, ci_low, noop_reason: Optional[str] = None) -> dict:
    """사전 등록 판정. 수익 차이는 소수(0.005 = 0.5%p), MDD 는 음수(−0.30 = −30%)."""
    vals = (full_diff, h1_diff, h2_diff, mdd_cand, mdd_ref, ci_low)
    if noop_reason:
        return {"verdict": NOT_EVALUABLE, "failed": [], "reason": noop_reason}
    if any(v is None or not math.isfinite(float(v)) for v in vals):
        return {"verdict": NOT_EVALUABLE, "failed": [], "reason": "유한하지 않은 수치"}
    checks = {"a_diff_positive": full_diff > 0, "b_both_halves_positive": h1_diff > 0 and h2_diff > 0,
              "c_mdd_within_3pp": (mdd_cand - mdd_ref) >= -MDD_TOL, "d_boot_ci_low": ci_low > CI_LOW_FLOOR}
    failed = [k for k, ok in checks.items() if not ok]
    return {"verdict": PASS if not failed else FAIL, "failed": failed, "reason": None}


def segments(index: pd.DatetimeIndex) -> dict:
    """판정 구간·고정 절반(~2019-05-31 / 2019-06-01~)·2024-10 이후·전체. t0=None 은 시작일·초기 원금 기준."""
    last = index[-1]
    dec = index[index <= pd.Timestamp(DECISION_END)]
    h1 = index[index <= pd.Timestamp(H1_END)]
    if len(dec) < 2 or len(h1) < 1 or h1[-1] >= dec[-1]:
        raise ValueError("판정 구간 데이터가 부족합니다")
    out = {"decision": (None, dec[-1]), "h1": (None, h1[-1]), "h2": (h1[-1], dec[-1]), "whole": (None, last)}
    if last > dec[-1]:
        out["post_2024_10"] = (dec[-1], last)
    return out


def mdd_window(values: pd.Series, initial: float, t1: pd.Timestamp) -> float:
    """시작 ~ t1 원화 평가액 최대 낙폭(초기 원금을 첫 고점으로)."""
    v = np.concatenate([[initial], values.loc[:t1].to_numpy(dtype=float)])
    peak = np.maximum.accumulate(v)
    return float((v / peak - 1).min())


def filter_log(log: list[dict], start: pd.Timestamp) -> list[dict]:
    return [r for r in log if pd.Timestamp(r["date"]) >= start]


def spy_sleeve_weights(index: pd.DatetimeIndex, log: list[dict], adj: pd.DataFrame,
                       spy_w: float = SPY_WEIGHT, ticker: str = "SPY") -> pd.DataFrame:
    """SPY 85% 그냥 보유 + 새틀라이트 15%. 매년 1월 첫 거래일에만 85/15 로 맞추고, 그 밖의 새틀라이트 교체일에는
    직전 맞춤 이후 배당 포함 가격대로 표류한 비중을 목표로 둔다(SPY 몫 유지, 새틀라이트 몫을 새 종목에 균등)."""
    log = sorted(({"date": pd.Timestamp(r["date"]), "weights": dict(r.get("weights") or {})} for r in log), key=lambda r: r["date"])
    log = [r for r in log if r["date"] in index]
    if not log:
        raise ValueError("새틀라이트 선정 기록이 없습니다.")
    idx = index[index >= log[0]["date"]]
    years = pd.Series(idx.year, index=idx)
    resets = set(years.groupby(years).apply(lambda s: s.index.min()))
    resets = {d for d in resets if d.month == 1} | {idx[0]}
    by_date = {r["date"]: r["weights"] for r in log}
    change = sorted(set(by_date) | resets)
    px = adj.reindex(idx).ffill()
    cols = sorted({ticker} | {t for r in log for t in r["weights"]})
    rows = {}
    picks: dict = {}
    spy_val = sat_val = 0.0
    sat_hold: dict = {}       # 종목 → 직전 교체일의 금액(새틀라이트 몫 안)
    prev = None

    def g(t, d0, d1):
        if t not in px.columns:
            return 1.0
        a, b = px.at[d0, t], px.at[d1, t]
        return float(b / a) if pd.notna(a) and pd.notna(b) and a > 0 else 1.0

    for d in change:
        if d in by_date:
            picks = by_date[d]
        if prev is not None:
            spy_val *= g(ticker, prev, d)
            cash = sat_val - sum(sat_hold.values())
            sat_val = cash + sum(v * g(t, prev, d) for t, v in sat_hold.items())
        if d in resets:
            spy_val, sat_val = spy_w, 1 - spy_w
        tot = spy_val + sat_val
        sat_hold = {t: sat_val * w for t, w in picks.items()}
        row = dict.fromkeys(cols, 0.0)
        row[ticker] = spy_val / tot
        for t, v in sat_hold.items():
            row[t] += v / tot
        rows[d] = row
        prev = d
    w = pd.DataFrame.from_dict(rows, orient="index").reindex(columns=cols).reindex(idx).ffill().fillna(0.0)
    return w


def build_weights(core_w: pd.DataFrame, logs: dict, adj: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """다섯 변형의 일별 목표 비중(같은 날짜 축 — 판정 시작 리밸런싱일부터). logs 는 이미 시작일로 거른 S0·S0p·S1."""
    c0 = tx.champion_weights(core_w, logs["S0"], SAT_WEIGHT)
    idx = c0.index
    out = {"C0": c0,
           "C1": tx.champion_weights(core_w, logs["S1"], SAT_WEIGHT).reindex(idx).fillna(0.0),
           "C1p": tx.champion_weights(core_w, logs["S0p"], SAT_WEIGHT).reindex(idx).fillna(0.0),
           "D0": spy_sleeve_weights(idx, logs["S0"], adj).reindex(idx).fillna(0.0),
           "D1": spy_sleeve_weights(idx, logs["S1"], adj).reindex(idx).fillna(0.0)}
    return out


def target_turnover(w: pd.DataFrame) -> float:
    """목표 비중 기준 연 회전율(한쪽, Σ|Δw|/2 ÷ 연수). 표류 차이는 빼고 본 근사."""
    d = w.diff().abs().sum(axis=1).iloc[1:].sum() / 2
    years = max((w.index[-1] - w.index[0]).days / 365.25, 1e-9)
    return float(d / years)


# =================================================================================================
# 입력
# =================================================================================================

def _seed(sid: str):
    from core import satellite_lab as sl

    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sid)
    return spec, sl.load_signal(code), dict(spec["signal"]["params_grid"][0])


def sleeve_schedules(data, per_guru: dict) -> dict:
    """S0(champion40)·S0p(sp500_pit)·S1(S-SEED-019, sp500_pit) 일정 — run_variant 그대로."""
    from core import satellite_lab as sl

    data.guru = gm.FilingsStore(per_guru)
    spec0, sig0, p0 = _seed("S-SEED-000")
    spec19, sig19, p19 = _seed("S-SEED-019")
    out = {}
    for key, spec, sig, p, pool in (("S0", spec0, sig0, p0, "champion40"), ("S0p", spec0, sig0, p0, "sp500_pit"),
                                    ("S1", spec19, sig19, p19, "sp500_pit")):
        sp = json.loads(json.dumps(spec))
        sp["pool"] = {"type": pool}
        out[key] = sl.run_variant(sp, p, sig, data)["schedule"]
    return out


def guru_meta(schedule: list, per_guru: dict, trading_days: pd.DatetimeIndex, start: pd.Timestamp) -> dict:
    """S1 매수 종목 중 리밸런싱 전날 기준 거장 보유 수, 첫 리밸런싱의 13F 반영 여부."""
    from core import satellite_lab as sl

    rows, first_known = [], None
    for d, picks in schedule:
        ts = pd.Timestamp(d)
        if ts < start:
            continue
        cutoff = sl._prev_day(trading_days, ts)
        asof = cutoff.date()
        held = [t for t in picks if gm.holders_at(per_guru, t, asof)]
        if first_known is None:
            first_known = gm.any_filing_known(per_guru, asof)
        rows.append({"date": str(ts.date()), "picks": list(picks), "guru_held": held})
    n = sum(len(r["picks"]) for r in rows)
    return {"first_rebalance_guru_known": bool(first_known), "rows": rows,
            "share_picks_guru_held": (sum(len(r["guru_held"]) for r in rows) / n) if n else float("nan")}


def _assemble(data, per_guru, core_w, other_frames: dict, fx, meta: dict) -> dict:
    sch = sleeve_schedules(data, per_guru)
    start = next(pd.Timestamp(d) for d, _ in sch["S1"] if pd.Timestamp(d) >= pd.Timestamp(JUDGE_START))
    logs = {k: filter_log(sv.schedule_to_log(v), start) for k, v in sch.items()}
    gmeta = guru_meta(sch["S1"], per_guru, data.trading_days, start)
    picks = sorted({t for lg in logs.values() for r in lg for t in r["weights"]})
    frames = dict(other_frames)
    frames.update({t: data.ohlcv.get(t) for t in picks})
    close, adj = sv._panel(frames)
    return {"core_w": core_w, "logs": logs, "close": close, "adj": adj, "fx": fx, "start": str(start.date()),
            "guru": gmeta, "meta": meta}


def _real_inputs(log) -> dict:
    from core import champion_strategy as cs
    from core import guru_history as gh
    from core import satellite_lab as sl
    from core.market_data import get_multiple_price_history

    log("거장 13F 이력")
    store = gh.Store(fetch=False)
    have = [g for g, cik in store.gurus().items() if store._path(cik).exists()]
    if len(have) < len(store.gurus()):
        store = gh.Store(fetch=True)
        dl = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or (time.time() + 3 * 3600)
        res = store.prefetch(deadline=dl - 300, log=log)
        if not res["complete"]:
            raise _Stop()
    per_guru = store.load()
    missing = [g for g in gm.GURUS if g not in per_guru]
    if missing:
        raise RuntimeError(f"거장 13F 이력 없음: {missing}")
    log("코어 백테스트(일별 목표 비중)")
    core_w = cs.run_core_backtest(CORE_START)["weights"]
    pool = sv._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(JUDGE_START))
    data = sl.build_data({"champion40", "sp500_pit"}, start=DATA_START, pool_provider=pool, log=log)
    others = sorted(set(core_w.columns) | {"SPY"})
    hist = get_multiple_price_history(others, start="2013-01-01", end=None, interval="1d")
    log("새틀라이트 일정(S0·S0p·S1)")
    return _assemble(data, per_guru, core_w, {t: hist.get(t) for t in others}, tx.usdkrw_series(),
                     {"strategy_version": cs.CHAMPION_STRATEGY_VERSION, "judge_version": sl.JUDGE_VERSION,
                      "pool_cache_tag": sl.POOL_CACHE_TAG, "live_satellite_weight": cs.SATELLITE_WEIGHT})


SMOKE_END = "2026-06-30"


def smoke_data():
    """합성 가격·풀·13F(네트워크 없음). 실데이터가 아니다."""
    from core import satellite_lab as sl

    pp, poolp = sl.synthetic_providers(n_tickers=50, start="2008-01-01", end=SMOKE_END, seed=7)
    pool = sv._pool_wrapper(poolp, date.fromisoformat(JUDGE_START))
    data = sl.build_data({"champion40", "sp500_pit"}, start=DATA_START, end=SMOKE_END, pool_provider=pool, price_provider=pp)
    per_guru = gm.synthetic_filings(sorted(t for t in data.ohlcv if t != "SPY"))
    return data, per_guru, pp


def _smoke_inputs(log) -> dict:
    data, per_guru, pp = smoke_data()
    rng = np.random.default_rng(5)
    full = pd.bdate_range("2008-01-01", SMOKE_END)
    frames = {"SPY": pp("SPY", "2008-01-01", SMOKE_END)}
    for t in ("C1", "C2"):
        c = 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, len(full))))
        frames[t] = pd.DataFrame({"Close": c, "Adj Close": c * np.exp(np.linspace(0, 0.3, len(full)))}, index=full)
    idx = full[full >= pd.Timestamp(CORE_START)]
    core_w = pd.DataFrame(0.0, index=idx, columns=["C1", "C2"])
    core_w.loc[core_w.index.month % 2 == 0, "C1"] = 1.0
    core_w.loc[core_w.index.month % 2 == 1, "C2"] = 1.0
    core_w.loc[core_w.index.month == 3, "C2"] = 0.5
    fx = pd.Series(1100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(full)))), index=full)
    return _assemble(data, per_guru, core_w, frames, fx, {"synthetic": True})


# =================================================================================================
# 분석
# =================================================================================================

def _pair(va, vb, initial, segs, with_boot: bool) -> dict:
    out = {f"{k}_diff": sv.seg_ann(va, initial, t0, t1) - sv.seg_ann(vb, initial, t0, t1) for k, (t0, t1) in segs.items()}
    dec_end = segs["decision"][1]
    ra, rb = sv.window_returns(va, initial, dec_end), sv.window_returns(vb, initial, dec_end)
    years = (dec_end - va.index[0]).days / 365.25
    ppy = len(ra) / years
    d = (ra - rb).to_numpy()
    sd = float(np.std(d, ddof=1)) if len(d) > 1 else float("nan")
    out["daily_diff_ir"] = float(np.mean(d) / sd * math.sqrt(ppy)) if sd and math.isfinite(sd) and sd > 0 else float("nan")
    out["noop_reason"] = rp.noop_guard(d)
    out["mdd_a"], out["mdd_b"] = mdd_window(va, initial, dec_end), mdd_window(vb, initial, dec_end)
    out["decision_years"] = years
    if with_boot:
        boot = sv.block_bootstrap_diff(ra.to_numpy(), rb.to_numpy(), ppy, n_boot=N_BOOT, block=BLOCK_DAYS, seed=BOOT_SEED)
        lo, hi = np.percentile(boot, CI_PCT)
        out.update({"boot_ci90_low": float(lo), "boot_ci90_high": float(hi), "boot_median": float(np.median(boot)),
                    "boot_share_positive": float(np.mean(boot > 0))})
    return out


def analyze(sims: dict, inputs: dict, smoke: bool) -> tuple[dict, str]:
    idx = sims[DECISION_SETUP]["C0"]["values"].index
    segs = segments(idx)
    seg_dates = {k: [str(t0.date()) if t0 is not None else str(idx[0].date()), str(t1.date())] for k, (t0, t1) in segs.items()}
    weights = build_weights(inputs["core_w"], inputs["logs"], inputs["adj"])
    metrics, pairs = {}, {}
    for sname, over in SETUPS.items():
        initial = tx.AccountConfig(**over).initial_krw
        metrics[sname] = {}
        for v in VARIANTS:
            s = sims[sname][v]
            vals = s["values"]
            metrics[sname][v] = {**{k: s[k] for k in ("cagr_pre", "cagr_after", "mdd_after", "final_krw",
                                                      "final_after_liquidation_krw", "totals")},
                                 "mdd_decision": mdd_window(vals, initial, segs["decision"][1]),
                                 "target_turnover_per_year": target_turnover(weights[v]),
                                 "segments_after_tax": {k: sv.seg_ann(vals, initial, t0, t1) for k, (t0, t1) in segs.items()}}
        pairs[sname] = {k: _pair(sims[sname][a]["values"], sims[sname][b]["values"], initial, segs, sname == DECISION_SETUP)
                        for k, (a, b) in {**JUDGED, **REPORTED}.items()}
    power = rp.power_report(POWER_YEARS, POWER_TRIALS)
    guru_ok = inputs["guru"]["first_rebalance_guru_known"]
    verdicts, details = {}, {}
    for k in JUDGED:
        p = pairs[DECISION_SETUP][k]
        noop = p["noop_reason"] or (None if guru_ok else "첫 리밸런싱에 공시된 13F 가 없음")
        dec = decide(p["decision_diff"], p["h1_diff"], p["h2_diff"], p["mdd_a"], p["mdd_b"], p.get("boot_ci90_low"), noop)
        dec["power_class"] = rp.classify_fail(p["daily_diff_ir"], power) if dec["verdict"] == FAIL else None
        details[k] = dec
        verdicts[k] = f"SMOKE_ONLY({dec['verdict']})" if smoke else dec["verdict"]
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": str(idx[0].date()), "end": str(idx[-1].date()), "segments": seg_dates,
        "rules": {"decision_setup": DECISION_SETUP, "decision_end": DECISION_END, "h1_end": H1_END, "mdd_tol": MDD_TOL,
                  "ci_low_floor": CI_LOW_FLOOR, "n_boot": N_BOOT, "block_days": BLOCK_DAYS, "boot_seed": BOOT_SEED,
                  "ci_percentiles": list(CI_PCT), "satellite_weight": SAT_WEIGHT, "spy_weight": SPY_WEIGHT,
                  "judged": {k: list(v) for k, v in JUDGED.items()}, "reported": {k: list(v) for k, v in REPORTED.items()},
                  "post_2024_10": "report only", "data_status": "already-seen data → forward-ledger-level finding only"},
        "variants": NAMES, "sleeve_of": SLEEVE_OF,
        "metrics": metrics, "pairs": pairs, "power": power, "power_line": rp.power_line(power),
        "decisions": details, "verdicts": verdicts,
        "guru_coverage": {"first_rebalance_guru_known": guru_ok, "share_s1_picks_guru_held": inputs["guru"]["share_picks_guru_held"],
                          "name_match_coverage_note": "13F 종목명→티커 매칭은 보유 평가액의 약 72~78%"},
        "inputs_meta": inputs.get("meta", {}),
        "missing_prices": sorted(t for w in weights.values() for t in w.columns[(w.abs().sum() > 0)]
                                 if t not in inputs["close"].columns or inputs["close"][t].dropna().empty),
        "satellite_schedule": {k: [{"date": r["date"], "picks": sorted(r["weights"])} for r in lg]
                               for k, lg in inputs["logs"].items()},
        "s1_guru_held": inputs["guru"]["rows"],
    }
    result["missing_prices"] = sorted(set(result["missing_prices"]))
    return result, _report(result)


def _pct(x) -> str:
    return f"{x:.2%}" if isinstance(x, (int, float)) and math.isfinite(x) else "—"


def _pp(x) -> str:
    return f"{x * 100:+.2f}%p" if isinstance(x, (int, float)) and math.isfinite(x) else "—"


CRIT_KO = {"a_diff_positive": "(a) 차이 > 0", "b_both_halves_positive": "(b) 두 절반 > 0",
           "c_mdd_within_3pp": "(c) MDD 3%p 이내", "d_boot_ci_low": "(d) 부트스트랩 하한 > −0.5%p"}


def _report(r: dict) -> str:
    m, pr = r["metrics"][DECISION_SETUP], r["pairs"][DECISION_SETUP]
    sg = r["segments"]
    L = [f"# 거장 보유 우선 새틀라이트(S-SEED-019)를 챔피언에 넣으면 — 세후 원화{' (스모크 — 합성 데이터)' if r['smoke'] else ''}", "",
         "> **주의: 이미 본 데이터(2014~2024 가격과 같은 13F)를 다시 쓴 연구다. PASS 여도 '전진 원장 수준의 발견'일 뿐 채택 근거가 아니다.** "
         "S-SEED-019 는 이미 전진 원장(core/forward_tournament_v2.py 의 S1)에 기록되고 있다. 엔진 반영은 사용자 확인 뒤 별도 작업이다.", "",
         f"판정 구간 {sg['decision'][0]} ~ {sg['decision'][1]}, 3,000만 원, 카카오페이증권 기본값.", "",
         "| 비교 | 판정 | 차이 | 앞 절반 | 뒤 절반 | MDD(후보/기준) | 부트스트랩 90% | 실패 항목 |", "|---|---|---|---|---|---|---|---|"]
    for k in JUDGED:
        p, d = pr[k], r["decisions"][k]
        fails = ", ".join(CRIT_KO[f] for f in d["failed"]) or (d.get("reason") or "없음")
        if d.get("power_class"):
            fails += f" · {d['power_class']}"
        L.append(f"| {k} | **{r['verdicts'][k]}** | {_pp(p['decision_diff'])} | {_pp(p['h1_diff'])} | {_pp(p['h2_diff'])} | "
                 f"{_pct(p['mdd_a'])} / {_pct(p['mdd_b'])} | {_pp(p.get('boot_ci90_low'))} ~ {_pp(p.get('boot_ci90_high'))} | {fails} |")
    L += ["", f"- {r['power_line']}",
          f"- 관측 일별 차이 연 IR: " + ", ".join(f"{k} {pr[k]['daily_diff_ir']:.2f}" for k in JUDGED), "",
          "## 세후 연수익(3,000만 원)", "",
          "| 변형 | 판정 구간 | 앞 절반 | 뒤 절반 | 2024-10~ (보고) | 전체 | 원화 MDD(판정 구간) | 양도세(백만 원) | 수수료(백만 원) | 목표 회전율/년 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for v in VARIANTS:
        s, t = m[v]["segments_after_tax"], m[v]["totals"]
        L.append(f"| {v} {NAMES[v]} | {_pct(s['decision'])} | {_pct(s['h1'])} | {_pct(s['h2'])} | {_pct(s.get('post_2024_10'))} | "
                 f"{_pct(s['whole'])} | {_pct(m[v]['mdd_decision'])} | {t.get('capital_gains_tax_krw', 0) / 1e6:.1f} | "
                 f"{t.get('fees_krw', 0) / 1e6:.1f} | {m[v]['target_turnover_per_year']:.2f} |")
    L += ["", "## 풀 효과와 거장 효과 나누기(보고만)", "",
          "| 비교 | 뜻 | 판정 구간 | 앞 절반 | 뒤 절반 | 부트스트랩 90% |", "|---|---|---|---|---|---|"]
    mean = {"C1_vs_C1p": "거장 효과(풀은 sp500_pit 로 고정)", "C1p_vs_C0": "풀 효과(champion40 → sp500_pit, 같은 규칙)",
            "D1_vs_C0": "SPY 기반 거장 챔피언 vs 현 챔피언"}
    for k in REPORTED:
        p = pr[k]
        L.append(f"| {k} | {mean[k]} | {_pp(p['decision_diff'])} | {_pp(p['h1_diff'])} | {_pp(p['h2_diff'])} | "
                 f"{_pp(p.get('boot_ci90_low'))} ~ {_pp(p.get('boot_ci90_high'))} |")
    L += ["", "C1 − C0 ≈ (C1p − C0: 풀 효과) + (C1 − C1p: 거장 효과). 세후 연복리라 정확히 더해지지는 않는다.", ""]
    m1, p1 = r["metrics"]["base_100m"], r["pairs"]["base_100m"]
    L += ["## 초기 1억 원(보고만)", "",
          "판정 구간 세후 연수익: " + ", ".join(f"{v} {_pct(m1[v]['segments_after_tax']['decision'])}" for v in VARIANTS)
          + ". 차이: " + ", ".join(f"{k} {_pp(p1[k]['decision_diff'])}" for k in JUDGED) + ".", ""]
    gc = r["guru_coverage"]
    L += ["## 거장 데이터", "",
          f"- 첫 리밸런싱({r['start']}) 전날까지 공시된 13F 있음: {'예' if gc['first_rebalance_guru_known'] else '아니오'}.",
          f"- S1 매수 종목 중 리밸런싱 전날 기준 거장 보유 비율: {_pct(gc['share_s1_picks_guru_held'])}.",
          "- 13F 종목명→티커 매칭은 보유 평가액의 약 72~78% 만 덮는다. 못 맞춘 보유는 '거장 미보유'로 처리되어 효과를 흐린다.", "",
          "## 규약", "",
          "- 새틀라이트 일정은 core.satellite_lab.run_variant 그대로(반기 1·7월 첫 거래일, 전날 종가까지, 상위 3 균등, 빈 선정 = 현금).",
          "- C 계열: 코어 85% + 새틀라이트 15%, 목표가 바뀌는 날(코어 신호 변경일·새틀라이트 교체일) 모든 종목을 목표로(satellite-value-v1 A 와 같음).",
          "- D 계열: SPY 85% 를 사서 보유, 매년 1월 첫 거래일에만 85/15 로 맞춤. 7월 교체일 목표는 표류 비중(SPY 는 거의 매매 안 함).",
          "- 계좌: 수수료 0.1%, 달러 보유·환전 스프레드 0.05%, 양도세 250만 원 공제 후 22%, 이동평균, 배당 원천징수 15% 재투자.",
          f"- 가격 없는 보유 종목: {', '.join(r['missing_prices']) or '없음'}.", "",
          "## 한계", "",
          "- 이미 본 구간: 2014~2024 는 guru-mechanism-v1·새틀라이트 R&D 가 이미 썼다. 이 결과로 엔진을 바꾸지 않는다 — 전진 원장으로 확인한다.",
          "- 상장폐지 종목은 가격 소스에 없어 후보에서 빠진다(생존편향 — sp500_pit 풀에서 더 크다).",
          "- 일봉 종가 체결, 금융소득 종합과세 미반영. 과거 결과이며 앞으로의 수익을 뜻하지 않는다."]
    return "\n".join(L) + "\n"


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

    def check_time(margin: float = 120.0) -> None:
        if deadline is not None and time.time() > deadline - margin:
            raise _Stop()

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old_handler = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        inputs = sv._load_ckpt(ck / "inputs.pkl", fp)
        if inputs is None:
            check_time()
            inputs = _smoke_inputs(log) if a.smoke else _real_inputs(log)
            sv._atomic_pickle(ck / "inputs.pkl", {"fingerprint": fp, "payload": inputs})
            log("입력 체크포인트 저장")
        weights = build_weights(inputs["core_w"], inputs["logs"], inputs["adj"])
        sims: dict = {}
        new = 0
        for sname, over in SETUPS.items():
            cfg = tx.AccountConfig(**over)
            for v in VARIANTS:
                path = ck / f"sim_{sname}_{v}.pkl"
                got = sv._load_ckpt(path, fp)
                if got is None:
                    if a.max_sims_per_run and new >= a.max_sims_per_run:
                        raise _Stop()
                    check_time()
                    log(f"시뮬레이션 {sname} {v}")
                    s = tx.simulate(weights[v], inputs["close"], inputs["adj"], inputs["fx"], cfg)
                    got = {k: s[k] for k in ("cagr_pre", "cagr_after", "mdd_after", "final_krw", "final_after_liquidation_krw", "totals")}
                    got["values"] = s["values_krw"]
                    sv._atomic_pickle(path, {"fingerprint": fp, "payload": got})
                    new += 1
                sims.setdefault(sname, {})[v] = got
        result, report = analyze(sims, inputs, a.smoke)
    except _Stop:
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old_handler is not None:
            _signal.signal(_signal.SIGTERM, old_handler)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
