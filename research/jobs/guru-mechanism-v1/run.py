"""검증 연구 guru-mechanism-v1: S-SEED-019(거장 보유 우선)의 효과는 거장의 안목인가, 대형주·품질 쏠림인가 (사전 등록, 2026-10-10).

배경: S-SEED-019 는 sat-judge/v3 에서 지금까지 가장 강한 새틀라이트 신호였다(IS 무작위 대비 99백분위, 떼어 둔 구간 샤프 1.82 vs
현 규칙 0.73). 그러나 DSR 0.20(누적 시도 27)·이웃 파라미터 관문 탈락. 떼어 둔 구간은 이미 소진되었으므로(docs/RESEARCH_JOBS.md
'판정 설계 규칙' 3) 정직한 다음 단계는 '메커니즘 시험'이다: 거장이 고른 종목이라서인가, 아니면 버핏의 AAPL 같은 초대형주 쏠림인가.

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
평가 구간(IS): 거장 13F 공시가 하나라도 알려진 첫 리밸런싱일(13F XML 은 2013년 2분기 보고분부터) ~ 2024-10-08.
2024-10-09 이후는 보고만 하고 판정에 쓰지 않는다. 풀 sp500_pit, 엔진·비용·리밸런싱은 새틀라이트 R&D 와 같다(core.satellite_lab).
변형:
  G0 현 규칙 S-SEED-000 을 sp500_pit 에서(기준선)
  G1 S-SEED-019 재현(core.satellite_lab.run_variant 그대로) — 등록부 IS 통계와 차이를 보고
  P1 시총 위약: 리밸런싱마다 G1 이 우선한 '수'만큼, 추세 후보 중 그 시점 시총 최상위 종목을 우선
  P2 무작위 위약: 같은 수를 추세 후보 중 무작위로 우선, 1,000회(시드 고정) → G0 대비 IS 활성 샤프 분포
  P3 거장 한 명씩 빼기(7개)   P4 버핏만   P5 G1 에서 AAPL 을 후보에서 제외
판정 guru-mechanism/v1:
  (a) G1 의 IS 활성 샤프(G0 대비) ≥ P2 분포의 95백분위
  (b) G1 의 IS 활성 샤프 > P1 의 IS 활성 샤프
  (c) P3 7개 중 6개 이상에서 활성 샤프 > 0
  모두 → GURU_MECHANISM_SUPPORTED, 하나만 실패 → PARTIAL(실패 항목 표기), 그 외 → NOT_SUPPORTED.
  G1 이 G0 와 매일 같으면(noop_guard) NOT_EVALUABLE. 분해 검산(019 = 현 규칙 점수 + 거장 보유 +1000)이 run_variant 와 다르면 NOT_EVALUABLE.
  추세 후보의 시총 커버리지 < 80% 이면 (b) 를 판정할 수 없어 NOT_EVALUABLE.
판정과 무관하게 S-SEED-019 는 전진 원장(core/forward_tournament_v2.py — 다른 작업에서 구현)에 오른다.
한계: 13F 종목명→티커 매칭이 보유 평가액의 약 72~78% 만 덮는다. 상장폐지 종목 가격 결측(생존편향). 시총은 발행주식수×종가 근사.
AI 를 부르지 않고 주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal as _signal
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import guru_history as gh  # noqa: E402
from core import research_power as rp  # noqa: E402
from core import satellite_lab as sl  # noqa: E402

JOB_ID = "guru-mechanism-v1"
JUDGE_VERSION = "guru-mechanism/v1"
CKPT_VERSION = 1
EXIT_DONE, EXIT_IN_PROGRESS, EXIT_FAIL = 0, 3, 1

# ---- 사전 고정 값 (2026-10-10) ------------------------------------------------------------------
INCUMBENT_ID, GURU_ID = "S-SEED-000", "S-SEED-019"
POOL = "sp500_pit"
IS_END = "2024-10-08"            # 평가 구간 끝(포함)
HOLDOUT_START = "2024-10-09"     # 보고만
DATA_END = "2026-10-08"          # 등록부가 S-SEED-019 를 심판한 날과 같은 끝(재현용)
REGISTRY_SPLIT = "2024-10-08"    # 등록부 IS = 수익 날짜 < 이 날(holdout_split 결과)
BOOST = 1000.0                   # S-SEED-019 signal.py 와 같은 가점
GURUS = ("워런 버핏", "마이클 버리", "빌 애크먼", "캐시 우드", "스탠리 드러켄밀러", "데이비드 테퍼", "세스 클라만")
BUFFETT = "워런 버핏"
EXCLUDE_TICKER = "AAPL"
N_PLACEBO = 1000
P2_SEED = 20261010
P2_BATCH = 50
A_PCTL = 0.95
C_MIN_POSITIVE = 6
MCAP_MIN_COVERAGE = 0.80
TOP_N_MCAP = 10
REPLICATION_TOL_SHARPE = 0.05
# 등록부(VM data/satellite_lab/registry.json, sat-judge/v3, 2026-10-08 심판)의 S-SEED-019 값 — 재현 비교용
REGISTRY_REF = {"is_sharpe_annual": 0.9999, "is_ann_return": 0.2905, "is_max_drawdown": -0.3949, "is_n_days": 3590,
                "oos_sharpe_annual": 1.8193, "active_is_sharpe_vs_champion40": 0.354, "random_is_percentile": 0.99}
SAFETY_SECONDS = 90

# 스모크(합성 데이터) 설정
SMOKE = {"data_end": "2026-09-30", "n_placebo": 100, "batch": 20, "exclude": "T00"}

_STOP = {"flag": False}


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def deadline_epoch() -> float:
    raw = os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH")
    return (float(raw) if raw else time.time() + 3 * 3600) - SAFETY_SECONDS


def out_of_time(deadline: float) -> bool:
    return _STOP["flag"] or time.time() > deadline


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# =================================================================================================
# 거장 데이터 (시점 규칙은 core.guru_history.view_from_filings 그대로: 기준일까지 '공시된' 13F 만)
# =================================================================================================

class FilingsStore:
    """거장 일부만 쓰는 13F 보기(core.guru_history.Store.view 와 같은 계산)."""

    def __init__(self, per_guru: dict[str, list[dict]], gurus: Optional[tuple] = None):
        self.per_guru = {g: f for g, f in per_guru.items() if gurus is None or g in gurus}

    def view(self, ticker: str, asof: date) -> dict:
        return gh.view_from_filings(self.per_guru, ticker, asof)


def holders_at(per_guru: dict[str, list[dict]], ticker: str, asof: date) -> list[str]:
    """asof(리밸런싱 전날)까지 공시된 마지막 13F 에 ticker 가 있는 거장들."""
    return sorted(g for g, f in per_guru.items() if gh.view_from_filings({g: f}, ticker, asof).get("n_holders", 0) >= 1)


def any_filing_known(per_guru: dict[str, list[dict]], asof: date) -> bool:
    return any(date.fromisoformat(f["filed"]) <= asof for fs in per_guru.values() for f in fs)


def synthetic_filings(tickers: list[str], seed: int = 11) -> dict[str, list[dict]]:
    """스모크용 가짜 13F 이력(분기마다, 2013-08 공시부터). 실데이터가 아니다."""
    rng = np.random.default_rng(seed)
    out = {}
    for gi, g in enumerate(GURUS):
        filings = []
        for y in range(2013, 2027):
            for q, (pm, pd_, fm) in enumerate(((3, 31, 5), (6, 30, 8), (9, 30, 11), (12, 31, 2))):
                if (y, q) < (2013, 1):
                    continue
                fy = y + 1 if fm == 2 else y
                filed = date(fy, fm, 14)
                if filed > date(2026, 9, 30):
                    continue
                k = 4 + gi
                picks = rng.choice(tickers, size=min(k, len(tickers)), replace=False)
                w = rng.dirichlet(np.ones(len(picks)))
                filings.append({"accession": f"{gi}-{y}-{q}", "filed": filed.isoformat(), "period": date(y, pm, pd_).isoformat(),
                                "holdings": [{"name": t, "cusip": "", "ticker": str(t), "weight": float(x)} for t, x in zip(picks, w)]})
        out[g] = filings
    return out


# =================================================================================================
# 시총(그 시점) — core.point_in_time_market_cap.get_market_cap_asof 와 같은 식(발행주식수 × 그 시점 종가, 이후 분할 보정).
# 분할 이력을 종목당 한 번만 받도록 여기서 묶는다(코어 함수는 부를 때마다 yfinance 를 다시 부른다).
# =================================================================================================

def real_mcap_fn(data: sl.LabData) -> Callable[[str, date], Optional[float]]:
    from core import point_in_time_market_cap as pm

    shares_c: dict[str, pd.Series] = {}
    splits_c: dict[str, pd.Series] = {}

    def splits(t: str) -> pd.Series:
        if t not in splits_c:
            try:
                import yfinance as yf

                s = yf.Ticker(t).splits
                idx = pd.DatetimeIndex(s.index)
                if getattr(idx, "tz", None) is not None:
                    idx = idx.tz_localize(None)
                splits_c[t] = pd.Series(s.values, index=idx).astype(float)
            except Exception:  # noqa: BLE001
                splits_c[t] = pd.Series(dtype=float)
        return splits_c[t]

    def factor_after(t: str, ts: pd.Timestamp) -> float:
        s = splits(t)
        after = s[s.index > ts] if not s.empty else s
        f = 1.0
        for r in after:
            f *= float(r)
        return f

    def fn(t: str, asof: date) -> Optional[float]:
        if t not in shares_c:
            shares_c[t] = pm.get_shares_outstanding_history(t)
        sh = shares_c[t]
        if sh is None or sh.empty:
            return None
        ts = pd.Timestamp(asof)
        prior = sh[sh.index <= ts]
        shares = (float(sh.iloc[0]) * factor_after(t, sh.index[0])) if prior.empty else float(prior.iloc[-1]) * factor_after(t, ts)
        df = data.ohlcv.get(t)
        if df is None:
            return None
        px = df["Close"][df.index <= ts].dropna()
        if px.empty:
            return None
        v = float(px.iloc[-1]) * shares
        return v if math.isfinite(v) and v > 0 else None

    return fn


def synthetic_mcap_fn(data: sl.LabData) -> Callable[[str, date], Optional[float]]:
    def fn(t: str, asof: date) -> Optional[float]:
        df = data.ohlcv.get(t)
        if df is None:
            return None
        px = df["Close"][df.index <= pd.Timestamp(asof)].dropna()
        return float(px.iloc[-1]) * (1e6 * (1 + sum(map(ord, t)) % 13)) if len(px) else None

    return fn


# =================================================================================================
# 선정 분해: S-SEED-019 점수 = 현 규칙(S-SEED-000) 점수 + (우선 집합이면 +1000). 위약은 '우선 집합'만 바꾼다.
# =================================================================================================

def boosted_picks(base: dict, eligible: list[str], boost: set, k: int) -> list[str]:
    scores = {t: s + (BOOST if t in boost else 0.0) for t, s in base.items()}
    return sl.pick_top(scores, k, set(eligible))


def g1_boost_set(row: dict, drop: Optional[str] = None, only: Optional[str] = None) -> set:
    out = set()
    for t, hs in row["holders"].items():
        hs = [g for g in hs if g != drop and (only is None or g == only)]
        if hs:
            out.add(t)
    return out


def mcap_boost_set(row: dict, caps: dict, n: int) -> set:
    """추세 후보 중 시총(알려진 것) 최상위 n 개."""
    ranked = sorted(((c, t) for t, c in caps.items() if t in row["base"] and c is not None), key=lambda x: (-x[0], x[1]))
    return {t for _, t in ranked[:n]}


def random_boost_set(row: dict, n: int, rng: np.random.Generator) -> set:
    cands = sorted(row["base"])
    if n <= 0 or not cands:
        return set()
    return {str(x) for x in rng.choice(cands, size=min(n, len(cands)), replace=False)}


def build_panel_row(data: sl.LabData, d: pd.Timestamp, spec0: dict, signal0, params0: dict,
                    per_guru: dict[str, list[dict]]) -> Optional[dict]:
    """run_variant 의 리밸런싱일 계산 그대로(전날 종가까지의 가격·적격 종목) + 후보별 보유 거장."""
    cutoff = sl._prev_day(data.trading_days, d)
    if cutoff is None:
        return None
    members = data.pool(POOL, d)
    prices = sl._signal_prices(data, members, cutoff, d)
    eligible = sorted(t for t in prices if t in data.closes.columns and pd.notna(data.closes.at[d, t]))
    base = sl._call_signal(signal0, spec0, data, {t: prices[t] for t in eligible}, cutoff, params0) or {}
    base = {t: float(s) for t, s in base.items() if t in eligible and s is not None and math.isfinite(float(s))}
    asof = cutoff.date()
    holders = {t: hs for t in sorted(base) if (hs := holders_at(per_guru, t, asof))}
    return {"cutoff": asof.isoformat(), "eligible": eligible, "base": base, "holders": holders,
            "guru_known": any_filing_known(per_guru, asof)}


# =================================================================================================
# 판정
# =================================================================================================

def decide(g1_active: float, p2_dist: list[float], p1_active: float, p3_actives: dict[str, float], *,
           g1_noop: Optional[str] = None, decomposition_ok: bool = True, mcap_coverage: float = 1.0) -> dict:
    """사전 등록 판정 guru-mechanism/v1."""
    pct = sl.percentile_of(g1_active, p2_dist)
    a = pct is not None and pct >= A_PCTL
    b = g1_active > p1_active
    n_pos = sum(1 for x in p3_actives.values() if x > 0)
    c = n_pos >= C_MIN_POSITIVE
    crit = {"a_beats_random_placebo": {"pass": a, "g1_percentile_in_p2": pct, "threshold": A_PCTL},
            "b_beats_mcap_placebo": {"pass": b, "g1": g1_active, "p1": p1_active},
            "c_leave_one_guru_out": {"pass": c, "n_positive": n_pos, "of": len(p3_actives), "need": C_MIN_POSITIVE}}
    reasons = []
    if g1_noop:
        reasons.append(f"G1 무효 실행: {g1_noop}")
    if not decomposition_ok:
        reasons.append("분해 검산 실패(위약과 G1 이 같은 선정 경로가 아님)")
    if mcap_coverage < MCAP_MIN_COVERAGE:
        reasons.append(f"추세 후보 시총 커버리지 {mcap_coverage:.0%} < {MCAP_MIN_COVERAGE:.0%}")
    if reasons:
        return {"verdict": "NOT_EVALUABLE", "failed": [], "criteria": crit, "reasons": reasons}
    failed = [k for k, v in (("a", a), ("b", b), ("c", c)) if not v]
    verdict = "GURU_MECHANISM_SUPPORTED" if not failed else ("PARTIAL" if len(failed) == 1 else "NOT_SUPPORTED")
    return {"verdict": verdict, "failed": failed, "criteria": crit, "reasons": []}


# =================================================================================================
# 본체
# =================================================================================================

def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


def prepare(smoke: bool):
    seed0, code0 = sl.read_variant_dir(sl.SEEDS_DIR / INCUMBENT_ID)
    seed19, code19 = sl.read_variant_dir(sl.SEEDS_DIR / GURU_ID)
    spec0 = sl.validate_spec({**seed0, "pool": {"type": POOL}})
    if smoke:
        price_provider, pool_provider = sl.synthetic_providers()
        data = sl.build_data({POOL}, start=sl.LAB_START, end=SMOKE["data_end"], pool_provider=pool_provider,
                             price_provider=price_provider, log=log)
        per_guru = synthetic_filings(sorted(t for t in data.ohlcv if t != "SPY"))
        mcap = synthetic_mcap_fn(data)
    else:
        data = sl.build_data({POOL}, start=sl.LAB_START, end=DATA_END, log=log)
        store = gh.Store(fetch=False)
        have = [g for g, cik in store.gurus().items() if store._path(cik).exists()]
        if len(have) < len(store.gurus()):
            store = gh.Store(fetch=True)
            res = store.prefetch(deadline=deadline_epoch() - 120, log=log)
            if not res["complete"]:
                raise TimeoutError("거장 13F 받는 중 시간 예산 소진")
        per_guru = store.load()
        missing = [g for g in GURUS if g not in per_guru]
        if missing:
            raise RuntimeError(f"거장 13F 이력 없음: {missing}")
        mcap = real_mcap_fn(data)
    data.guru = FilingsStore(per_guru)
    return data, per_guru, mcap, (spec0, code0), (seed19, code19)


def load_ckpt(path: Path, mode: str) -> dict:
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
        if st.get("version") == CKPT_VERSION and st.get("mode") == mode:
            return st
    except (OSError, ValueError):
        pass
    return {"version": CKPT_VERSION, "mode": mode, "panel": {}, "mcaps": {}, "p2": {"next": 0, "is": [], "holdout": []}}


def run(args) -> int:
    deadline = deadline_epoch()
    smoke = bool(args.smoke)
    out_dir, ck_dir = Path(args.out), Path(args.checkpoint)
    out_dir.mkdir(parents=True, exist_ok=True)
    ck_path = ck_dir / "state.json"
    st = load_ckpt(ck_path, "smoke" if smoke else "real")
    save = lambda: atomic_write(ck_path, json.dumps(st, ensure_ascii=False, separators=(",", ":")))  # noqa: E731
    n_placebo = SMOKE["n_placebo"] if smoke else N_PLACEBO
    batch = SMOKE["batch"] if smoke else P2_BATCH
    exclude = SMOKE["exclude"] if smoke else EXCLUDE_TICKER

    try:
        data, per_guru, mcap_fn, (spec0, code0), (spec19, code19) = prepare(smoke)
    except TimeoutError as exc:
        log(str(exc))
        return EXIT_IN_PROGRESS
    from core.champion_strategy import SATELLITE_COST_BPS_PER_SIDE as BPS

    signal0, signal19 = sl.load_signal(code0), sl.load_signal(code19)
    params0, params19 = spec0["signal"]["params_grid"][0], spec19["signal"]["params_grid"][0]
    k = spec19["portfolio"]["top_k"]
    dates = [d for d in sl.rebalance_dates(data.trading_days, spec19["portfolio"]["hold_months"])
             if sl._prev_day(data.trading_days, d) is not None]
    end = data.trading_days[-1]
    log(f"거래일 {len(data.trading_days)}일, 가격 {len(data.ohlcv)}종목, 리밸런싱 {len(dates)}회")

    # 1) G0·G1: 새틀라이트 R&D 와 같은 경로(run_variant). 선정만 저장하고 수익은 매번 다시 계산(빠름).
    if "g1_schedule" not in st:
        st["g0_schedule"] = sl.run_variant(spec0, params0, signal0, data)["schedule"]
        st["g1_schedule"] = sl.run_variant(spec19, params19, signal19, data)["schedule"]
        save()
        log("G0·G1 선정 저장")
    if out_of_time(deadline):
        return EXIT_IN_PROGRESS

    # 2) 리밸런싱일별 후보·보유 거장
    for d in dates:
        key = d.date().isoformat()
        if key in st["panel"]:
            continue
        if out_of_time(deadline):
            save()
            return EXIT_IN_PROGRESS
        st["panel"][key] = build_panel_row(data, d, spec0, signal0, params0, per_guru)
        save()
    panel = {k2: v for k2, v in st["panel"].items() if v is not None}
    keys = sorted(panel)
    known = [k2 for k2 in keys if panel[k2]["guru_known"]]
    if not known:
        raise RuntimeError("거장 13F 가 알려진 리밸런싱일이 없음")
    d0 = known[0]
    is_keys = [k2 for k2 in known if k2 <= IS_END]

    # 3) 시총(거장 데이터가 있는 날의 추세 후보만)
    for k2 in known:
        if k2 in st["mcaps"]:
            continue
        if out_of_time(deadline):
            save()
            return EXIT_IN_PROGRESS
        asof = date.fromisoformat(panel[k2]["cutoff"])
        st["mcaps"][k2] = {t: mcap_fn(t, asof) for t in sorted(panel[k2]["base"])}
        save()
    caps = st["mcaps"]

    # 선정 → 수익
    sma_cache = data.__dict__.setdefault("_sma_cache", {})

    def returns_of(sched: dict[str, list[str]]) -> pd.Series:
        schedule = [(_ts(k2), sched.get(k2, [])) for k2 in keys]
        return sl.simulate(data.closes, schedule, end, None, BPS, entry=spec19.get("entry"), exit_rule=spec19.get("exit"),
                           cache=sma_cache)["returns"]

    def sched_from(boost_of: Callable[[str, dict], set], drop_ticker: Optional[str] = None) -> dict[str, list[str]]:
        out = {}
        for k2 in keys:
            row = panel[k2]
            base, el = row["base"], row["eligible"]
            if drop_ticker:
                base = {t: s for t, s in base.items() if t != drop_ticker}
                el = [t for t in el if t != drop_ticker]
            out[k2] = boosted_picks(base, el, boost_of(k2, row) if k2 >= d0 else set(), k)
        return out

    nb = {k2: len(g1_boost_set(panel[k2])) for k2 in keys}
    g0_sched = sched_from(lambda k2, row: set())
    g1_sched = sched_from(lambda k2, row: g1_boost_set(row))
    lab_g0 = {d_: p for d_, p in st["g0_schedule"]}
    lab_g1 = {d_: p for d_, p in st["g1_schedule"]}
    decomp_ok = all(lab_g1.get(k2) == g1_sched[k2] for k2 in keys) and all(lab_g0.get(k2) == g0_sched[k2] for k2 in keys)

    start_ts, is_end_ts, ho_ts = _ts(d0), _ts(IS_END), _ts(HOLDOUT_START)
    seg_is = lambda r: r[(r.index > start_ts) & (r.index <= is_end_ts)]  # noqa: E731
    seg_ho = lambda r: r[r.index >= ho_ts]  # noqa: E731
    from core import hypothesis_engine as he

    r_g0 = returns_of(lab_g0)
    years = len(seg_is(r_g0)) / sl.TRADING_DAYS
    power = rp.power_report(years, 1)  # 결과를 보기 전에 정해지는 값(구간 길이·시도 수)

    def act(r: pd.Series) -> tuple[float, float, Optional[str]]:
        a = sl._active(r, r_g0)
        return (he.stats(seg_is(a)).get("sharpe_annual", 0.0), he.stats(seg_ho(a)).get("sharpe_annual", 0.0),
                rp.noop_guard(seg_is(a).tolist()))

    # 4) P2 무작위 위약(배치마다 체크포인트, 뽑기마다 시드 [P2_SEED, i] 라 이어서 해도 같은 결과)
    p2 = st["p2"]
    batches_this_run = 0
    while p2["next"] < n_placebo:
        if out_of_time(deadline) or (args.max_batches_per_run and batches_this_run >= args.max_batches_per_run):
            save()
            log(f"P2 {p2['next']}/{n_placebo} 저장 후 중단")
            return EXIT_IN_PROGRESS
        hi = min(p2["next"] + batch, n_placebo)
        for i in range(p2["next"], hi):
            rng = np.random.default_rng([P2_SEED, i])
            sched = {}
            for k2 in keys:
                row = panel[k2]
                boost = random_boost_set(row, nb[k2], rng) if k2 >= d0 else set()
                sched[k2] = boosted_picks(row["base"], row["eligible"], boost, k)
            a_is, a_ho, _ = act(returns_of(sched))
            p2["is"].append(a_is)
            p2["holdout"].append(a_ho)
        p2["next"] = hi
        batches_this_run += 1
        save()
        log(f"P2 {hi}/{n_placebo}")

    # 5) 결정론 변형
    variants: dict[str, tuple[str, dict]] = {
        "G0": ("현 규칙 S-SEED-000 (sp500_pit, 기준선)", g0_sched),
        "G1": ("S-SEED-019 재현(거장 1명 이상 보유 우선)", lab_g1),
        "P1": ("시총 위약(같은 수, 시총 최상위 우선)", sched_from(lambda k2, row: mcap_boost_set(row, caps.get(k2, {}), nb[k2]))),
        "P4": ("버핏만", sched_from(lambda k2, row: g1_boost_set(row, only=BUFFETT))),
        "P5": (f"G1, {exclude} 후보 제외", sched_from(lambda k2, row: g1_boost_set(row), drop_ticker=exclude)),
    }
    for g in GURUS:
        variants[f"P3[{g}]"] = (f"거장 빼기: {g}", sched_from(lambda k2, row, g=g: g1_boost_set(row, drop=g)))
    rets = {vid: returns_of(s) for vid, (_, s) in variants.items()}
    g0_ex = returns_of(sched_from(lambda k2, row: set(), drop_ticker=exclude))
    vres = {}
    for vid, (label, s) in variants.items():
        a_is, a_ho, noop = act(rets[vid])
        sis, sho = he.stats(seg_is(rets[vid])), he.stats(seg_ho(rets[vid]))
        vres[vid] = {"label": label, "is_active_sharpe": round(a_is, 4), "holdout_active_sharpe_report_only": round(a_ho, 4),
                     "noop": "기준선 자신(해당 없음)" if vid == "G0" else noop, "is_sharpe": round(sis.get("sharpe_annual", 0.0), 4),
                     "is_ann_return": round(sis.get("ann_return", 0.0), 4), "is_max_drawdown": round(sis.get("max_drawdown", 0.0), 4),
                     "holdout_sharpe_report_only": round(sho.get("sharpe_annual", 0.0), 4)}
    vres["P5"]["is_active_sharpe_vs_G0_ex"] = round(he.stats(seg_is(sl._active(rets["P5"], g0_ex))).get("sharpe_annual", 0.0), 4)

    # 6) 재현(등록부 IS = 2010~ 수익 날짜 < 2024-10-08)
    r_g1 = rets["G1"]
    reg_is = he.stats(r_g1[r_g1.index < _ts(REGISTRY_SPLIT)])
    reg_oos = he.stats(r_g1[r_g1.index >= _ts(REGISTRY_SPLIT)])
    ours = {"is_sharpe_annual": round(reg_is.get("sharpe_annual", 0.0), 4), "is_ann_return": round(reg_is.get("ann_return", 0.0), 4),
            "is_max_drawdown": round(reg_is.get("max_drawdown", 0.0), 4), "is_n_days": reg_is.get("n_days"),
            "oos_sharpe_annual": round(reg_oos.get("sharpe_annual", 0.0), 4)}
    replication = {"registry": REGISTRY_REF, "ours": ours, "decomposition_matches_run_variant": decomp_ok}
    if smoke:
        replication.update(ok=None, note="스모크(합성 데이터) — 등록부와 비교하지 않음")
    else:
        diff = {k2: round(ours[k2] - REGISTRY_REF[k2], 4) for k2 in ours}
        replication.update(diff=diff, ok=abs(diff["is_sharpe_annual"]) <= REPLICATION_TOL_SHARPE)
        if "champion40_active" not in st:
            try:
                seed0, _ = sl.read_variant_dir(sl.SEEDS_DIR / INCUMBENT_ID)
                inc40 = sl.run_variant(seed0, params0, signal0, data)["returns"]
                st["champion40_active"] = round(he.stats(sl._active(r_g1, inc40)[lambda s: s.index < _ts(REGISTRY_SPLIT)])
                                                .get("sharpe_annual", 0.0), 4)
            except Exception as exc:  # noqa: BLE001 - 보고용
                st["champion40_active"] = f"계산 못함: {type(exc).__name__}: {str(exc)[:120]}"
            save()
        replication["active_is_sharpe_vs_champion40_ours"] = st["champion40_active"]

    # 7) 판정
    cov_n = sum(len(caps.get(k2, {})) for k2 in is_keys)
    cov_ok = sum(1 for k2 in is_keys for v in caps.get(k2, {}).values() if v is not None)
    coverage = cov_ok / cov_n if cov_n else 0.0
    p3 = {g: vres[f"P3[{g}]"]["is_active_sharpe"] for g in GURUS}
    g1a = vres["G1"]["is_active_sharpe"]
    dec = decide(g1a, p2["is"], vres["P1"]["is_active_sharpe"], p3, g1_noop=vres["G1"]["noop"],
                 decomposition_ok=decomp_ok, mcap_coverage=coverage)
    fail_kind = rp.classify_fail(g1a, power) if dec["verdict"] not in ("GURU_MECHANISM_SUPPORTED", "NOT_EVALUABLE") else None

    # 8) 보고: 시총 겹침, 거장별 기여
    overlap_rows = []
    for k2 in is_keys:
        row, cp = panel[k2], caps.get(k2, {})
        top10 = mcap_boost_set(row, cp, TOP_N_MCAP)
        b = g1_boost_set(row)
        pmc = mcap_boost_set(row, cp, len(b))
        picks = lab_g1.get(k2, [])
        overlap_rows.append({"date": k2, "n_candidates": len(row["base"]), "n_boosted": len(b),
                             "boosted_in_top10": len(b & top10), "frac_boosted_in_top10": (len(b & top10) / len(b)) if b else None,
                             "g1_picks_in_top10": len(set(picks) & top10), "jaccard_g1_vs_p1": (len(b & pmc) / len(b | pmc)) if b else None,
                             "g1_picks": picks, "g0_picks": lab_g0.get(k2, [])})
    mean = lambda xs: (round(float(np.mean(xs)), 4) if xs else None)  # noqa: E731
    overlap = {"mean_frac_boosted_in_top10": mean([r["frac_boosted_in_top10"] for r in overlap_rows if r["frac_boosted_in_top10"] is not None]),
               "mean_g1_picks_in_top10_share": mean([r["g1_picks_in_top10"] / max(1, len(r["g1_picks"])) for r in overlap_rows]),
               "mean_jaccard_g1_vs_p1": mean([r["jaccard_g1_vs_p1"] for r in overlap_rows if r["jaccard_g1_vs_p1"] is not None]),
               "g1_is_picks_with_excluded_ticker": sum(exclude in r["g1_picks"] for r in overlap_rows),
               "mcap_coverage": round(coverage, 4), "rows": overlap_rows}

    def period_ret(t: str, k2: str) -> Optional[float]:
        i = keys.index(k2)
        stop = min(_ts(keys[i + 1]) if i + 1 < len(keys) else end, is_end_ts)
        s = data.closes[t].loc[_ts(k2):stop].dropna() if t in data.closes.columns else pd.Series(dtype=float)
        return float(s.iloc[-1] / s.iloc[0] - 1) if len(s) >= 2 else None

    per_guru_rep = {}
    for g in GURUS:
        exc = []
        for k2 in is_keys:
            row = panel[k2]
            cand = [x for x in (period_ret(t, k2) for t in row["base"]) if x is not None]
            avg = float(np.mean(cand)) if cand else 0.0
            for t in lab_g1.get(k2, []):
                if g in row["holders"].get(t, []):
                    pr = period_ret(t, k2)
                    if pr is not None:
                        exc.append(pr - avg)
        per_guru_rep[g] = {"loo_delta_active_sharpe": round(g1a - p3[g], 4), "p3_active_sharpe": p3[g],
                           "g1_is_picks_held": len(exc), "mean_period_excess_vs_candidates": mean(exc),
                           "mean_boosted_names_held": mean([sum(g in hs for hs in panel[k2]["holders"].values()) for k2 in is_keys])}

    p2_is = p2["is"]
    p2_rep = {"n": len(p2_is), "seed": P2_SEED, "pctl": {q: round(float(np.percentile(p2_is, q)), 4) for q in (5, 50, 95)} if p2_is else {},
              "g1_percentile": dec["criteria"]["a_beats_random_placebo"]["g1_percentile_in_p2"],
              "holdout_g1_percentile_report_only": sl.percentile_of(vres["G1"]["holdout_active_sharpe_report_only"], p2["holdout"]),
              "noop_draws": sum(1 for x in p2_is if x == 0.0)}

    verdict = dec["verdict"]
    crit = dec["criteria"]
    verdicts = {
        "guru_mechanism": ("SMOKE_ONLY" if smoke else verdict) + (f" (실패: {','.join(dec['failed'])})" if dec["failed"] else ""),
        "a_random_placebo": f"{'PASS' if crit['a_beats_random_placebo']['pass'] else 'FAIL'} — G1 {g1a:.2f}, P2 백분위 "
                            f"{(p2_rep['g1_percentile'] or 0) * 100:.1f}",
        "b_mcap_placebo": f"{'PASS' if crit['b_beats_mcap_placebo']['pass'] else 'FAIL'} — G1 {g1a:.2f} vs P1 {vres['P1']['is_active_sharpe']:.2f}",
        "c_leave_one_out": f"{'PASS' if crit['c_leave_one_guru_out']['pass'] else 'FAIL'} — {crit['c_leave_one_guru_out']['n_positive']}/7 양수",
        "replication": "스모크" if smoke else (f"{'OK' if replication['ok'] else 'MISMATCH'} — IS 샤프 {ours['is_sharpe_annual']:.3f} "
                                               f"(등록부 {REGISTRY_REF['is_sharpe_annual']:.3f})"),
        "forward_ledger": "S-SEED-019 는 판정과 무관하게 전진 원장에 오른다",
    }
    if smoke:
        verdicts["would_be"] = verdict
    if fail_kind:
        verdicts["power"] = fail_kind

    results = {
        "job": JOB_ID, "judge_version": JUDGE_VERSION, "mode": "smoke" if smoke else "real",
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixed_rules": {"pool": POOL, "is_end": IS_END, "holdout_start_report_only": HOLDOUT_START, "data_end": SMOKE["data_end"] if smoke else DATA_END,
                        "n_placebo": n_placebo, "p2_seed": P2_SEED, "a_pctl": A_PCTL, "c_min_positive": C_MIN_POSITIVE,
                        "mcap_min_coverage": MCAP_MIN_COVERAGE, "boost": BOOST, "excluded_ticker_p5": exclude, "gurus": list(GURUS),
                        "replication_tol_sharpe": REPLICATION_TOL_SHARPE},
        "eval_window": {"first_guru_rebalance": d0, "is_end": IS_END, "years": round(years, 2), "n_is_rebalances": len(is_keys)},
        "power": power, "power_line": rp.power_line(power),
        "verdicts": verdicts, "decision": dec, "fail_kind": fail_kind,
        "replication": replication, "variants": vres, "p2": p2_rep, "overlap_top10_mcap": overlap, "per_guru": per_guru_rep,
        "boosted_counts": {k2: {"boosted": nb[k2], "candidates": len(panel[k2]["base"])} for k2 in known},
        "limitations": ["13F 종목명→티커 매칭이 보유 평가액의 약 72~78% 만 덮는다(못 맞춘 보유는 '보유 안 함'으로 보임)",
                        "상장폐지 종목 가격 결측(생존편향)", "시총은 발행주식수 이력 × 종가 근사(core.point_in_time_market_cap 과 같은 식)",
                        "같은 기간을 여러 연구가 봤다 — 이 연구는 메커니즘 확인이며 채택 근거가 아니다"],
        "forward_ledger": "S-SEED-019 는 판정과 무관하게 전진 원장(core/forward_tournament_v2.py, 다른 작업에서 구현)에 올린다.",
    }
    atomic_write(out_dir / "results.json", json.dumps(results, ensure_ascii=False, indent=1, default=str))
    atomic_write(out_dir / "REPORT.md", report_md(results))
    log(f"완료: {verdicts['guru_mechanism']}")
    return EXIT_DONE


def report_md(r: dict) -> str:
    v, dec, rep = r["variants"], r["decision"], r["replication"]
    L = [f"# 거장 보유 우선(S-SEED-019) 메커니즘 시험 — {r['job']}{' (스모크·합성 데이터)' if r['mode'] == 'smoke' else ''}", "",
         f"**판정 {r['verdicts']['guru_mechanism']}** ({r['judge_version']}, 사전 등록 2026-10-10). "
         f"평가 구간 {r['eval_window']['first_guru_rebalance']} ~ {r['eval_window']['is_end']} "
         f"({r['eval_window']['years']}년, 리밸런싱 {r['eval_window']['n_is_rebalances']}회). 2024-10-09 이후는 보고만.", "",
         r["power_line"], ""]
    if dec["reasons"]:
        L += ["판정 불가 사유: " + "; ".join(dec["reasons"]), ""]
    c = dec["criteria"]
    L += ["## 사전 등록 기준", "", "| 기준 | 결과 | 값 |", "|---|---|---|",
          f"| (a) G1 활성 샤프 ≥ 무작위 위약 95백분위 | {'통과' if c['a_beats_random_placebo']['pass'] else '실패'} | "
          f"백분위 {c['a_beats_random_placebo']['g1_percentile_in_p2']} |",
          f"| (b) G1 > 시총 위약 | {'통과' if c['b_beats_mcap_placebo']['pass'] else '실패'} | "
          f"{c['b_beats_mcap_placebo']['g1']:.3f} vs {c['b_beats_mcap_placebo']['p1']:.3f} |",
          f"| (c) 거장 한 명 빼도 양수 ≥ 6/7 | {'통과' if c['c_leave_one_guru_out']['pass'] else '실패'} | "
          f"{c['c_leave_one_guru_out']['n_positive']}/7 |", ""]
    if r.get("fail_kind"):
        L += [f"FAIL 성격: {r['fail_kind']} (관측 IR 과 최소 검출 효과 비교).", ""]
    L += ["## 변형별 (G0 대비 활성 샤프, 연율)", "", "| 변형 | 설명 | IS 활성 샤프 | IS 샤프 | IS 최대낙폭 | 떼어 둔 구간 활성(보고만) | 무효 실행 |",
          "|---|---|---|---|---|---|---|"]
    for vid, x in v.items():
        L.append(f"| {vid} | {x['label']} | {x['is_active_sharpe']:.3f} | {x['is_sharpe']:.3f} | {x['is_max_drawdown']:.1%} | "
                 f"{x['holdout_active_sharpe_report_only']:.3f} | {x['noop'] or '-'} |")
    L += ["", f"P5 를 같은 종목을 뺀 G0 와 비교하면 활성 샤프 {v['P5']['is_active_sharpe_vs_G0_ex']:.3f}.", ""]
    p2 = r["p2"]
    L += ["## 무작위 위약(P2)", "", f"{p2['n']}회(시드 {p2['seed']}), 활성 샤프 5/50/95 백분위 {p2['pctl']}. "
          f"G1 백분위 {p2['g1_percentile']}, 떼어 둔 구간 백분위(보고만) {p2['holdout_g1_percentile_report_only']}.", ""]
    o = r["overlap_top10_mcap"]
    L += ["## 초대형주 쏠림", "", f"- 우선 집합 중 추세 후보 시총 상위 10 비율(평균): {o['mean_frac_boosted_in_top10']}",
          f"- G1 매수 종목 중 시총 상위 10 비율(평균): {o['mean_g1_picks_in_top10_share']}",
          f"- G1 우선 집합과 시총 위약 집합의 자카드(평균): {o['mean_jaccard_g1_vs_p1']}",
          f"- G1 IS 매수에 {r['fixed_rules']['excluded_ticker_p5']} 가 들어간 리밸런싱 수: {o['g1_is_picks_with_excluded_ticker']}",
          f"- 추세 후보 시총 커버리지: {o['mcap_coverage']}", ""]
    L += ["## 거장별 기여", "", "| 거장 | 빼면 활성 샤프 | 빼서 줄어든 양 | G1 매수 중 보유 | 후보 평균 대비 구간 초과(평균) |", "|---|---|---|---|---|"]
    for g, x in r["per_guru"].items():
        L.append(f"| {g} | {x['p3_active_sharpe']:.3f} | {x['loo_delta_active_sharpe']:.3f} | {x['g1_is_picks_held']} | "
                 f"{x['mean_period_excess_vs_candidates']} |")
    L += ["", "## 재현", ""]
    if r["mode"] == "smoke":
        L.append("스모크에서는 등록부와 비교하지 않는다.")
    else:
        L.append(f"등록부 S-SEED-019 IS 샤프 {rep['registry']['is_sharpe_annual']} vs 이번 {rep['ours']['is_sharpe_annual']} "
                 f"(차이 {rep['diff']['is_sharpe_annual']}, 허용 ±{REPLICATION_TOL_SHARPE} → {'OK' if rep['ok'] else 'MISMATCH'}). "
                 f"champion40 현 규칙 대비 활성 샤프: 등록부 {rep['registry']['active_is_sharpe_vs_champion40']} vs 이번 "
                 f"{rep.get('active_is_sharpe_vs_champion40_ours')}. 전체 비교: {rep['diff']}")
    L.append(f"분해 검산(019 = 현 규칙 점수 + 거장 보유 가점, run_variant 와 날짜마다 같은 선정): "
             f"{'일치' if rep['decomposition_matches_run_variant'] else '불일치'}")
    L += ["", "## 다음 단계", "", r["forward_ledger"], "엔진 반영은 사용자 확인 뒤 별도 작업으로 한다.", "",
          "## 한계", ""] + [f"- {x}" for x in r["limitations"]]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-batches-per-run", type=int, default=0, help="검사용: 이번 실행의 P2 배치 상한(0=제한 없음)")
    args = p.parse_args(argv)
    _STOP["flag"] = False
    try:
        _signal.signal(_signal.SIGTERM, lambda *_: _STOP.__setitem__("flag", True))
    except ValueError:  # 메인 스레드가 아닐 때(검사)
        pass
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
