"""검증 sat-sizing-v1 (2026-10-15 사전 등록): 새틀라이트 3종목에 '얼마씩' 넣을지(종목별 비중·슬리브 익스포저).

사용자 요청(2026-10-15): 진입 가격 조정(지정가·분할·눌림목)은 모두 실패했다. 아직 안 본 것은 진입 시 3종목에 각각 얼마를 넣느냐다.
라이브 엔진에는 검증되지 않은 사이징 옵션 "inverse_vol"(변동성 역가중)과 하프 "kelly"(슬리브 익스포저)가 있다 — 이를 검증한다.

종목 선정은 S-SEED-000 그대로(바꾸지 않음). 바뀌는 것은 슬리브 안 비중(그리고 Kelly 는 슬리브 전체 익스포저)뿐이다.
규칙 전체는 SPEC.md(한국어)에 고정. 판정 기준을 바꾸려면 새 id 로 다시 등록한다. 엔진 반영은 사용자 확인 뒤 별도 작업.
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

from core import champion_strategy as cs  # noqa: E402
from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "sat-sizing-v1"
RULES_VERSION = "sat-sizing-v1/2026-10-15"
START = "2010-01-01"
SAT_WEIGHT = 0.15
DECISION_END = "2024-09-30"
HALF_SPLIT = "2017-05-31"
N_BOOT = 1000
BLOCK_DAYS = 126
BOOT_SEED = 20261020
CI_PCT = (5.0, 95.0)
CI_LOW_FLOOR = -0.005
MDD_TOL = 0.02
POWER_YEARS = 14.7
N_TRIALS = 3
BIL = "BIL"
SPY = "SPY"
KELLY_PRICE_START = "2004-06-01"   # 2010-01 재선정의 5년 창을 덮도록
PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"

# 라이브 상수를 그대로 쓴다(테스트가 값도 고정해 확인)
CAP = cs.SATELLITE_SIZING_MAX_WEIGHT                     # 0.40
LIVE_VOL_LB = cs.SATELLITE_SIZING_VOL_LOOKBACK_DAYS      # 20
KELLY_LOOKBACK_YEARS = cs.SATELLITE_KELLY_LOOKBACK_YEARS  # 5
KELLY_SAMPLE_SIZE = cs.SATELLITE_KELLY_SAMPLE_SIZE        # 120
KELLY_MIN_TRADES = cs.SATELLITE_KELLY_MIN_TRADES          # 20
KELLY_SAFETY = cs.SATELLITE_KELLY_SAFETY_FRACTION         # 0.5
VOL_LB = {"Z1": LIVE_VOL_LB, "Z2": 63}

JUDGED = ("Z1", "Z2", "Z3")
VARIANTS = ("Z0",) + JUDGED
NAMES = {"Z0": "균등가중(라이브 기본, S-SEED-000)",
         "Z1": "변동성 역가중 — 라이브 _inverse_vol_weights, 20일, 상한 40%",
         "Z2": "변동성 역가중 — 같은 함수, 63일, 상한 40%",
         "Z3": "하프 켈리 슬리브 익스포저(시점 기준), 남는 비중은 BIL"}
LEVELS = ("champ", "sleeve")
SETUPS = {"base_30m": {}, "base_100m": {"initial_krw": 100_000_000}}


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SV = _load("satellite_value_v1_for_sizing", "research/jobs/satellite-value-v1/run.py")
EL = _load("sat_exit_ladder_v1_for_sizing", "research/jobs/sat-exit-ladder-v1/run.py")


# =================================================================================================
# 사이징 (순수 함수 — tests/test_sat_sizing.py)
# =================================================================================================

def equal_weights(picks: list[str]) -> dict:
    return {t: 1.0 / len(picks) for t in picks} if picks else {}


def inverse_vol_sleeve(ohlcv: dict, picks: list[str], d: pd.Timestamp, lookback: int) -> tuple[dict, bool]:
    """라이브 백테스트(champion_strategy 의 반기 선정)와 같은 방식: 재선정일 d '이전' 가격만으로 라이브
    _inverse_vol_weights(lookback, 상한 CAP)를 그대로 부른다. 2종목 미만이거나 빈 결과면 균등(라이브 폴백). (비중, 폴백 여부)."""
    eq = equal_weights(picks)
    if len(picks) < 2:
        return eq, True
    d = pd.Timestamp(d)
    hist = {t: ohlcv[t][ohlcv[t].index < d] for t in picks if t in ohlcv}
    vw = cs._inverse_vol_weights(hist, picks, lookback, CAP)
    return (dict(vw), False) if vw else (eq, True)


def kelly_sample(pool_members: list[str]) -> list[str]:
    """라이브: 유니버스 순서(티커순)에서 코어·SPY 를 뺀 앞 120. 시점 기준: 그날 S&P500 편입 종목(코어·SPY 제외) 티커순 앞 120."""
    ex = set(cs.CORE_UNIVERSE) | {cs.MARKET_FILTER_TICKER}
    return [t for t in sorted(pool_members) if t not in ex][:KELLY_SAMPLE_SIZE]


def kelly_exposure_pit(closes: dict, sample: list[str], d: pd.Timestamp) -> dict:
    """compute_satellite_kelly_exposure 를 시점 기준으로 재구현(같은 상수·같은 core 함수). 거래는 [d − 5년, d) 가격으로만
    만든다(그 창 끝에 열려 있는 거래는 라이브처럼 마지막 종가로 평가). closes[t] = 종가(Close) Series."""
    from core.position_sizing import compute_trade_stats, kelly_fraction
    from core.strategy_engine import extract_trades

    d = pd.Timestamp(d)
    lo = d - pd.DateOffset(years=KELLY_LOOKBACK_YEARS)
    trades, used = [], []
    for t in sample:
        s = closes.get(t)
        if s is None:
            continue
        s = s[(s.index >= lo) & (s.index < d)].dropna()
        if len(s) < cs.SATELLITE_DONCHIAN_WINDOW + 60:
            continue
        df = pd.DataFrame({"Close": s})
        tr = extract_trades(df, cs.donchian_trailing_stop_positions(df["Close"]))
        if tr:
            trades.extend(tr)
            used.append(t)
    stats = compute_trade_stats(trades)
    n = stats.trade_count if stats else 0
    if stats is None or n < KELLY_MIN_TRADES:
        return {"trade_count": n, "recommended_fraction": 1.0, "applied": False, "full_kelly": None,
                "win_rate": None, "n_sampled": len(used)}
    k = kelly_fraction(stats.win_rate, stats.avg_win_pct, stats.avg_loss_pct, safety_fraction=KELLY_SAFETY)
    return {"trade_count": n, "recommended_fraction": min(k["recommended_fraction"], 1.0), "applied": True,
            "full_kelly": k["full_kelly"], "win_rate": round(stats.win_rate, 4), "n_sampled": len(used)}


def kelly_sleeve(picks: list[str], f: float) -> dict:
    """3종목 균등 × f, 남는 1 − f 는 BIL(슬리브 안)."""
    if not picks:
        return {}
    w = {t: f / len(picks) for t in picks}
    if f < 1.0:
        w[BIL] = w.get(BIL, 0.0) + (1.0 - f)
    return w


def build_logs(schedule: list, ohlcv: dict, kelly: dict) -> tuple[dict, dict]:
    """{변형: champion_weights 용 기록}, {변형: 재선정별 비중 진단}. schedule = [(날짜 문자열, picks)]."""
    logs = {v: [] for v in VARIANTS}
    diag = {v: [] for v in VARIANTS}
    for ds, picks in schedule:
        d = pd.Timestamp(ds)
        picks = list(picks)
        ws = {"Z0": (equal_weights(picks), False)}
        for v in ("Z1", "Z2"):
            ws[v] = inverse_vol_sleeve(ohlcv, picks, d, VOL_LB[v])
        kinfo = kelly.get(str(d.date()), {"recommended_fraction": 1.0, "applied": False, "trade_count": 0})
        ws["Z3"] = (kelly_sleeve(picks, float(kinfo["recommended_fraction"])), not kinfo["applied"])
        for v, (w, fb) in ws.items():
            logs[v].append({"date": str(d.date()), "weights": w})
            stock = [w[t] for t in picks if t in w]
            diag[v].append({"date": str(d.date()), "n": len(picks), "fallback": bool(fb),
                            "max_w": max(stock) if stock else None, "min_w": min(stock) if stock else None,
                            "spread": (max(stock) - min(stock)) if stock else None,
                            "stock_sum": sum(stock), "bil": w.get(BIL, 0.0) if v == "Z3" else 0.0,
                            "kelly_trades": kinfo.get("trade_count") if v == "Z3" else None})
    return logs, diag


def diag_summary(diag: dict, end: pd.Timestamp) -> dict:
    out = {}
    for v, rows in diag.items():
        rows = [r for r in rows if pd.Timestamp(r["date"]) <= end and r["n"] >= 2]
        sp = [r["spread"] for r in rows if r["spread"] is not None]
        mx = [r["max_w"] for r in rows if r["max_w"] is not None]
        ex = [r["stock_sum"] for r in rows]
        out[v] = {"n_rebalances": len(rows), "mean_spread": float(np.mean(sp)) if sp else None,
                  "max_spread": float(np.max(sp)) if sp else None, "mean_max_weight": float(np.mean(mx)) if mx else None,
                  "max_weight_seen": float(np.max(mx)) if mx else None,
                  "n_over_cap": int(sum(1 for x in mx if x > CAP + 1e-9)),
                  "n_fallback": int(sum(1 for r in rows if r["fallback"])),
                  "mean_stock_exposure": float(np.mean(ex)) if ex else None}
    return out


# =================================================================================================
# 판정 (순수 함수)
# =================================================================================================

def decide(diff: float, h1: float, h2: float, sharpe_v: float, sharpe_0: float, mdd_v: float, mdd_0: float,
           ci_low: float, *, noop: Optional[str] = None, observed_ir: Optional[float] = None,
           power: Optional[dict] = None) -> str:
    """사전 등록 판정(챔피언 수준). 차이는 소수(0.01 = 1%p), MDD 는 음수."""
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


def segments(index: pd.DatetimeIndex) -> dict:
    dec_end = index[index <= pd.Timestamp(DECISION_END)][-1]
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
    if with_boot and len(d) > 2:
        boot = block_bootstrap_diff(ra.to_numpy(), rb.to_numpy(), ppy)
        lo, hi = np.percentile(boot, CI_PCT)
        out.update({"boot_ci90_low": float(lo), "boot_ci90_high": float(hi), "boot_share_positive": float(np.mean(boot > 0))})
    return out


# =================================================================================================
# 입력
# =================================================================================================

def _schedule(data) -> list:
    from core import satellite_lab as sl

    spec, signal, params = SV._incumbent()
    return [(str(pd.Timestamp(d).date()), list(p)) for d, p in sl.run_variant(spec, params, signal, data)["schedule"]]


def _prepare(data, core_w, frames: dict, fx, meta: dict, price_provider, end: Optional[str]) -> dict:
    from core import hypothesis_engine as he

    schedule = _schedule(data)
    samples = {ds: kelly_sample(data.pool("sp500_pit", pd.Timestamp(ds))) for ds, _ in schedule}
    union = sorted({t for s in samples.values() for t in s})
    end_d = date.fromisoformat(end) if end else date.today()
    kp = he.load_prices(union, date.fromisoformat(KELLY_PRICE_START), end_d, price_provider)
    kcloses = {t: SV._norm(df)["Close"].astype(float) for t, df in kp.items() if df is not None and not df.empty}
    picks = sorted({t for _, p in schedule for t in p})
    pf = dict(frames)
    pf.update({t: data.ohlcv.get(t) for t in picks})
    close, adj = SV._panel(pf)
    ohlcv = {t: SV._norm(data.ohlcv[t])[["Close"]] for t in picks if t in data.ohlcv}
    return {"schedule": schedule, "samples": samples, "kcloses": kcloses, "ohlcv": ohlcv, "core_w": core_w,
            "close": close, "adj": adj, "fx": fx, "meta": meta}


def _real_prep(log) -> dict:
    from core import satellite_lab as sl
    from core.market_data import get_multiple_price_history

    log("코어 백테스트(일별 목표 비중)")
    core_w = cs.run_core_backtest(START)["weights"]
    pool = SV._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(START))
    data = sl.build_data({"champion40"}, start="2009-12-01", pool_provider=pool, log=log)
    others = sorted(set(core_w.columns) | {SPY, BIL})
    hist = get_multiple_price_history(others, start="2009-06-01", end=None, interval="1d")
    frames = {t: hist.get(t) for t in others}
    meta = {"live_satellite_weight": cs.SATELLITE_WEIGHT, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
            "judge_version": sl.JUDGE_VERSION, "pool_cache_tag": sl.POOL_CACHE_TAG}
    log("Kelly 표본(그 시점 S&P500 앞 120) 가격 읽는 중")
    return _prepare(data, core_w, frames, tx.usdkrw_series(), meta, None, None)


def _smoke_prep(log) -> dict:
    """합성 데이터(네트워크 없음). 실데이터가 아니다."""
    from core import satellite_lab as sl

    end = "2026-06-30"
    pp, poolp = sl.synthetic_providers(n_tickers=50, start="2004-01-01", end=end, seed=11)
    base = SV._pool_wrapper(poolp, date.fromisoformat(START))

    def pool(pt, d):  # 2010 년엔 Kelly 표본을 비워 '20건 미만 → 미적용' 경로도 지나가게
        if pt == "sp500_pit" and d.year == 2010:
            return []
        m = base(pt, d)
        return m[:15] if pt == "sp500_pit" else m   # 스모크 시간 단축(표본 15종목)
    data = sl.build_data({"champion40"}, start="2009-12-01", end=end, pool_provider=pool, price_provider=pp)
    full = pd.bdate_range("2008-01-01", end)
    rng = np.random.default_rng(5)
    idx = data.trading_days[data.trading_days >= pd.Timestamp(START)]
    frames = {}
    for t, mu, sd in (("C1", 0.0003, 0.008), ("C2", 0.0002, 0.006), (BIL, 0.00005, 0.0003)):
        c = 50 * np.exp(np.cumsum(rng.normal(mu, sd, len(full))))
        frames[t] = pd.DataFrame({"Close": c, "Adj Close": c}, index=full)
    frames[SPY] = pp(SPY, "2008-01-01", end)
    core_w = pd.DataFrame(0.0, index=idx, columns=["C1", "C2"])
    core_w.loc[core_w.index.month % 2 == 0, "C1"] = 1.0
    core_w.loc[core_w.index.month % 2 == 1, "C2"] = 1.0
    fx = pd.Series(1100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(full)))), index=full)
    return _prepare(data, core_w, frames, fx, {"synthetic": True}, pp, end)


# =================================================================================================
# 시뮬레이션·분석
# =================================================================================================

def _mdd(v: pd.Series) -> float:
    return float((v / v.cummax() - 1).min())


def weights_for(prep: dict, logs: dict, lvl: str, name: str) -> pd.DataFrame:
    if name == "SPY":
        log = [{"date": r["date"], "weights": {SPY: 1.0}} for r in logs["Z0"]]
    else:
        log = logs[name]
    core = prep["core_w"] if lvl == "champ" else pd.DataFrame(0.0, index=prep["core_w"].index, columns=prep["core_w"].columns)
    w = tx.champion_weights(core, log, SAT_WEIGHT if lvl == "champ" else 1.0)
    return w.loc[:, w.abs().sum() > 0]


def sim_summary(s: dict, w: pd.DataFrame, adj: pd.DataFrame, initial: float) -> dict:
    vals = s["values_krw"]
    segs = segments(vals.index)
    dec_end = segs["judged"][1]
    r = EL.pretax_returns(w, adj).loc[:dec_end]
    bil_r = adj[BIL].reindex(w.index).ffill().pct_change(fill_method=None).fillna(0.0) if BIL in adj else pd.Series(0.0, index=w.index)
    return {"values": vals, "initial": initial, "cagr_judged": SV.seg_ann(vals, initial, None, dec_end),
            "mdd_judged": _mdd(vals.loc[:dec_end]), "cagr_post": SV.seg_ann(vals, initial, *segs["post"]) if "post" in segs else None,
            "sharpe_pretax_judged": EL.sharpe_excess(r, bil_r), "totals": s["totals"]}


def analyze(prep: dict, logs_diag: tuple, kelly: dict, sims: dict, smoke: bool) -> tuple[dict, str]:
    logs, diag = logs_diag
    power = rp.power_report(POWER_YEARS, N_TRIALS)
    pairs, verdicts, raw = {}, {}, {}
    for (lvl, setup) in (("champ", "base_30m"), ("champ", "base_100m"), ("sleeve", "base_30m")):
        k0 = (lvl, "Z0", setup)
        names = JUDGED + (("SPY",) if lvl == "sleeve" else ())
        for n in names:
            kv = (lvl, n, setup)
            if kv in sims and k0 in sims:
                boot = lvl == "champ" and setup == "base_30m"
                pairs.setdefault(setup, {}).setdefault(lvl, {})[n] = pair_stats(sims[kv]["values"], sims[k0]["values"],
                                                                                 sims[kv]["initial"], with_boot=boot)
    main = pairs["base_30m"]["champ"]
    s0 = sims[("champ", "Z0", "base_30m")]
    for n in JUDGED:
        c, sv = main[n], sims[("champ", n, "base_30m")]
        v = decide(c["judged_diff"], c["h1_diff"], c["h2_diff"], sv["sharpe_pretax_judged"], s0["sharpe_pretax_judged"],
                   sv["mdd_judged"], s0["mdd_judged"], c.get("boot_ci90_low", float("nan")),
                   noop=c["noop_reason"], observed_ir=c["daily_diff_ir"], power=power)
        raw[n] = v
        verdicts[n] = f"SMOKE_ONLY({v})" if smoke else v
    metrics = {}
    for (lvl, name, setup), s in sims.items():
        metrics.setdefault(setup, {}).setdefault(lvl, {})[name] = {k: v for k, v in s.items() if k not in ("values", "initial")}
    dec_end = pd.Timestamp(DECISION_END)
    kj = [k for ds, k in kelly.items() if pd.Timestamp(ds) <= dec_end]
    kelly_sum = {"n_rebalances": len(kj), "n_not_applied": sum(1 for k in kj if not k["applied"]),
                 "mean_exposure": float(np.mean([k["recommended_fraction"] for k in kj])) if kj else None,
                 "min_exposure": float(np.min([k["recommended_fraction"] for k in kj])) if kj else None,
                 "mean_trade_count": float(np.mean([k["trade_count"] for k in kj])) if kj else None}
    v0 = s0["values"]
    segs = {k: [None if a is None else str(a.date()), str(b.date())] for k, (a, b) in segments(v0.index).items()}
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": str(v0.index[0].date()), "segments": segs, "verdicts": verdicts, "verdicts_raw": raw,
        "pairs": pairs, "metrics": metrics, "weight_dispersion": diag_summary(diag, dec_end),
        "kelly_summary": kelly_sum, "kelly_by_date": kelly,
        "weights_by_rebalance": {v: [{"date": r["date"], "w": {t: round(x, 4) for t, x in r["weights"].items()}} for r in logs[v]]
                                 for v in VARIANTS},
        "power": power, "power_line": rp.power_line(power), "variants": NAMES, "inputs_meta": prep.get("meta", {}),
        "rules": {"sat_weight": SAT_WEIGHT, "cap": CAP, "vol_lookbacks": VOL_LB, "kelly": {
            "lookback_years": KELLY_LOOKBACK_YEARS, "sample_size": KELLY_SAMPLE_SIZE, "min_trades": KELLY_MIN_TRADES,
            "safety": KELLY_SAFETY}, "n_boot": N_BOOT, "block_days": BLOCK_DAYS, "boot_seed": BOOT_SEED,
            "ci_low_floor": CI_LOW_FLOOR, "mdd_tol": MDD_TOL, "decision_end": DECISION_END, "half_split": HALF_SPLIT,
            "power_years": POWER_YEARS, "n_trials": N_TRIALS},
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


def _f(x, nd=2) -> str:
    return "—" if x is None or not isinstance(x, (int, float)) or not math.isfinite(x) else f"{x:.{nd}f}"


def report(r: dict) -> str:
    sm = " (스모크 — 합성 데이터, 실측 아님)" if r["smoke"] else ""
    m30 = r["metrics"]["base_30m"]
    c30 = m30["champ"]
    p30 = r["pairs"]["base_30m"]["champ"]
    p100 = r["pairs"].get("base_100m", {}).get("champ", {})
    sg = r["segments"]
    L = [f"# 새틀라이트 3종목에 얼마씩 넣을까(사이징){sm}", "",
         "종목 선정은 지금 규칙(S-SEED-000) 그대로이고, 3종목 사이 비중(그리고 Kelly 는 슬리브 전체를 얼마나 실을지)만 바꿨다.",
         "기준선 Z0 = 3종목 균등(라이브 기본).", "",
         f"## 판정(챔피언 = 코어 85% + 새틀라이트 15%, 세후 원화 3,000만 원, {r['start']} ~ {sg['judged'][1]})", "",
         "| 변형 | 판정 | 세후 연수익 차이 | 앞/뒤 절반 | 세전 샤프(본/Z0) | 부트스트랩 90% | 원화 MDD(본/Z0) | 2024-10~(보고) | 1억 원 차이 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for n in JUDGED:
        c = p30[n]
        L.append(f"| {n} {NAMES[n]} | **{r['verdicts'][n]}** | {_pp(c['judged_diff'])} | {_pp(c['h1_diff'])} / {_pp(c['h2_diff'])} | "
                 f"{_f(c30[n]['sharpe_pretax_judged'])} / {_f(c30['Z0']['sharpe_pretax_judged'])} | "
                 f"{_pp(c.get('boot_ci90_low'))} ~ {_pp(c.get('boot_ci90_high'))} | {_pct(c30[n]['mdd_judged'])} / {_pct(c30['Z0']['mdd_judged'])} | "
                 f"{_pp(c.get('post_diff'))} | {_pp(p100.get(n, {}).get('judged_diff'))} |")
    L += ["", f"통과 조건(모두, Z0 대비): 세후 연수익 차이 > 0, 앞 절반(~{sg['h1'][1]})·뒤 절반 모두 > 0, 세전 샤프가 더 높음, "
          f"원화 MDD 가 {MDD_TOL:.0%}p 넘게 나빠지지 않음, 126일 블록 부트스트랩 1,000회(시드 {BOOT_SEED}) 90% 하한 > −0.5%p.",
          f"- {r['power_line']}"]
    for n in JUDGED:
        if p30[n].get("noop_reason"):
            L.append(f"- {n}: 무효 실행 가드 — {p30[n]['noop_reason']}(Z0 와 사실상 같은 결과)")
    wd, ks = r["weight_dispersion"], r["kelly_summary"]
    L += ["", "## 재선정별 비중 차이(판정 구간)", "", "| 변형 | 재선정 수 | 평균 최대−최소 비중 | 최대 비중(평균/최대) | 40% 초과 횟수 | 폴백(균등/미적용) | 평균 주식 비중(슬리브 안) |",
          "|---|---|---|---|---|---|---|"]
    for n in VARIANTS:
        w = wd[n]
        L.append(f"| {n} | {w['n_rebalances']} | {_pct(w['mean_spread'])} | {_pct(w['mean_max_weight'])} / {_pct(w['max_weight_seen'])} | "
                 f"{w['n_over_cap']} | {w['n_fallback']} | {_pct(w['mean_stock_exposure'])} |")
    L += ["", f"Kelly(Z3): 평균 슬리브 익스포저 {_pct(ks['mean_exposure'])}, 최소 {_pct(ks['min_exposure'])}, "
          f"거래 20건 미만이라 적용 안 함 {ks['n_not_applied']}/{ks['n_rebalances']}회, 평균 표본 거래 수 {_f(ks['mean_trade_count'], 0)}건.",
          "라이브 _inverse_vol_weights 는 상한을 한 번 자른 뒤 다시 합 1로 나누므로, 결과가 40%를 넘을 수 있다(라이브 동작 그대로 썼다 — '40% 초과 횟수' 열).",
          "", "## 보조: 새틀라이트 3종목만 100%(세후 원화 3,000만 원, 판정 구간)", "",
          "| 변형 | 세후 연수익 | 원화 MDD | 세전 샤프 | Z0 대비 | 앞/뒤 절반 |", "|---|---|---|---|---|---|"]
    s30 = m30.get("sleeve", {})
    ps = r["pairs"]["base_30m"].get("sleeve", {})
    for n in VARIANTS + ("SPY",):
        m, p = s30.get(n, {}), ps.get(n, {})
        L.append(f"| {n} | {_pct(m.get('cagr_judged'), nd=2)} | {_pct(m.get('mdd_judged'))} | {_f(m.get('sharpe_pretax_judged'))} | "
                 f"{_pp(p.get('judged_diff'))} | {_pp(p.get('h1_diff'))} / {_pp(p.get('h2_diff'))} |")
    L += ["", "SPY 줄 = 같은 날짜에 SPY 100% 보유(세후). 'Z0 대비'가 음수면 SPY 가 균등 3종목보다 못했다는 뜻.", "",
          "## 이것이 증명하는 것과 증명하지 못하는 것", "",
          "- 미국 시장 한 경로(2010~2024)의 과거 결과다. 앞으로 반복된다는 보장은 없다.",
          "- 생존편향: 상장폐지 종목은 가격 소스에 없어 선정 후보와 Kelly 거래 표본 모두에서 빠진다(Kelly 승률이 실제보다 좋게 나올 수 있다).",
          "- 이미 본 데이터: 2010~2024 는 다른 새틀라이트 연구들이 여러 번 본 기간이다. PASS 도 '전진 원장 후보'일 뿐 채택이 아니다. 2024-10 이후는 보고만 한다.",
          "- 변동성 역가중은 코어 ETF 에서 이미 실패했다(ETF 들은 변동성이 비슷하고 서로 상관이 높아 비중이 거의 안 바뀌거나, 낮은 변동성 = 채권 쪽으로 쏠려 수익을 깎았다). "
          "개별 주식 3종목은 변동성 차이가 훨씬 커서(예: 연 25% 대 70%) 비중이 실제로 달라지고, 한 종목 급락의 손해를 줄일 여지가 있다 — 그래서 따로 검증했다. "
          "반대로 모멘텀 상위 종목의 고변동성 자체가 수익원이면 오히려 손해일 수 있다.",
          "- Kelly 는 라이브 함수가 '오늘' 기준으로 계산하는 것을 재선정일 이전 5년 가격만으로 다시 계산했다(상수 동일). 표본은 그 시점 S&P500 편입 종목 티커순 앞 120(라이브는 현재 유니버스 순서 앞 120).",
          "- 세금은 한국 해외주식 양도소득세(연 250만 원 공제, 22%)와 카카오페이증권 기본 가정(`core/tax_fx.py`). 실제 계좌와 다를 수 있다.",
          "- 엔진(챔피언)은 바뀌지 않았다. 반영은 사용자 확인 뒤 별도 작업이다.", ""]
    return "\n".join(L)


def smoke_coverage(r: dict, sims: dict) -> dict:
    wd, ks = r["weight_dispersion"], r["kelly_summary"]
    return {"inverse_vol_differs": (wd["Z1"]["mean_spread"] or 0) > 0 and (wd["Z2"]["mean_spread"] or 0) > 0,
            "kelly_applied": ks["n_not_applied"] < ks["n_rebalances"],
            "kelly_fallback": ks["n_not_applied"] > 0,
            "verdicts": len(r["verdicts"]) == len(JUDGED),
            "tax_engine": "capital_gains_tax_krw" in r["metrics"]["base_30m"]["champ"]["Z0"]["totals"],
            "sleeve_and_spy": ("sleeve", "SPY", "base_30m") in sims}


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
        kelly = SV._load_ckpt(ck / "kelly.pkl", fp) or {}
        for ds, _ in prep["schedule"]:
            if ds in kelly:
                continue
            step()
            kelly[ds] = kelly_exposure_pit(prep["kcloses"], prep["samples"][ds], pd.Timestamp(ds))
            SV._atomic_pickle(ck / "kelly.pkl", {"fingerprint": fp, "payload": kelly})
            log(f"Kelly {ds}: {kelly[ds]['trade_count']}건 → {kelly[ds]['recommended_fraction']:.3f}")
        logs, diag = build_logs(prep["schedule"], prep["ohlcv"], kelly)
        jobs = ([(lvl, n, "base_30m") for lvl in LEVELS for n in VARIANTS] + [("sleeve", "SPY", "base_30m")]
                + [("champ", n, "base_100m") for n in VARIANTS])
        sims = {}
        for key in jobs:
            lvl, name, setup = key
            path = ck / f"sim_{lvl}_{name}_{setup}.pkl"
            got = SV._load_ckpt(path, fp)
            if got is None:
                step()
                w = weights_for(prep, logs, lvl, name)
                cfg = tx.AccountConfig(**SETUPS[setup])
                s = tx.simulate(w, prep["close"], prep["adj"], prep["fx"], cfg)
                got = sim_summary(s, w, prep["adj"], cfg.initial_krw)
                SV._atomic_pickle(path, {"fingerprint": fp, "payload": got})
                log(f"시뮬레이션 {key} 판정 구간 세후 {got['cagr_judged']:.4f}")
            sims[key] = got
        result, rep = analyze(prep, (logs, diag), kelly, sims, a.smoke)
        if a.smoke:
            cov = smoke_coverage(result, sims)
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
