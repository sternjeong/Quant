"""검증 연구 weekly-ma-rsi-v1 (2026-10-18 사전 등록): 주봉 20주선·RSI 과매도 매매가 적립식 세후로 SPY 를 이기나 (곁가지로 QQQ).

사용자 요청(2026-10-18): 주봉으로 봤을 때 20일선(20주 이동평균)과 RSI 과매도를 이용한 매매 기법을 실험하고, QQQ 도 함께 확인.
사용자 목표(2026-10-17): 처음 1,000만 원 + 매달 15만 원을 넣으며 끝없이 굴리고, 한국 세금 뒤 장기적으로 SPY 를 이기기.
그래서 contrib-reval-sector-v1 과 같은 틀(core/rolling_eval, 2000-01 부터 매달 시작하는 10년 구간, 시나리오 B 판정)로 잰다.

주봉: 각 주의 마지막 거래일 조정 종가. 신호는 그 주 마지막 거래일 종가로 계산하고 '다음 거래일' 종가에 매매(미리 보기 없음).
밖에 있을 때는 BIL(상장 2007-05 전에는 이자 없는 달러 현금). 대상 X ∈ {SPY, QQQ}.
  X_MA20     주 종가 > 20주 단순 이동평균이면 X 100%, 아니면 BIL.
  X_RSI      RSI(14주, Wilder) < 30 이면 X 를 사고, RSI ≥ 70 이 되면 판다(그 사이 보유). 처음에는 밖.
  X_MA20RSI  20주선 위면 보유 + 20주선 아래라도 RSI < 30 이 나오면 사서 RSI ≥ 50 회복까지 보유(눌림목 매수).
판정(시나리오 B, 10년 구간, 구간 끝 ≤ 2024-09-30): 6개 전략 모두 SPY 그냥 보유와 비교, CONTRIB_BEATS_SPY ⇔ 이긴 구간 비율 ≥ 70% ·
  IRR 차이 중앙값 ≥ +0.5%p · 10분위 ≥ −1.5%p · 시간가중 MDD 중앙값이 SPY 보다 5%p 넘게 나쁘지 않음. 아니면 classify_fail.
보고만: QQQ 그냥 보유 대 SPY(QQQ 는 사후에 고른 지수라 판정하지 않음), QQQ_* 대 QQQ 그냥 보유(기법 자체가 QQQ 를 낫게 하나),
  시나리오 A·C·B10, 5년 구간(B 만). 규칙은 SPEC.md 와 아래 상수에 결과를 보기 전에 고정했다. 엔진은 바뀌지 않는다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import signal as _signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import rolling_eval as re_  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "weekly-ma-rsi-v1"
RULES_VERSION = "weekly-ma-rsi-v1/2026-10-18"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
SPY, QQQ, BIL = "SPY", "QQQ", "BIL"
TICKERS = [SPY, QQQ, BIL]
DATA_START = "1998-12-01"
MA_WEEKS = 20
RSI_WEEKS = 14
RSI_OVERSOLD = 30.0
RSI_EXIT = 70.0          # X_RSI 매도
RSI_RECOVER = 50.0       # X_MA20RSI 눌림목 보유 끝
RULES = ("MA20", "RSI", "MA20RSI")
STRATEGIES = tuple(f"{u}_{r}" for u in (SPY, QQQ) for r in RULES)   # 판정 6개(모두 대 SPY)
N_TRIALS = len(STRATEGIES)
POWER_YEARS = 24.7
SCENARIOS = {                       # 처음 금액, 매달 적립(원)
    "B": (10_000_000, 150_000),     # 판정
    "A": (10_000_000, 0),
    "C": (3_000_000, 150_000),
    "B10": (100_000_000, 1_500_000),
}
SCENARIO_ORDER = ("B", "A", "C", "B10")
PRIMARY_SCENARIO = "B"
POLICY = "underweight_first"
PRIMARY_HORIZON = 10
SECOND_HORIZON = 5                  # 시나리오 B 만, 보고
STEP = "M"
FIRST_START = "2000-01-01"
JUDGED_END = "2024-09-30"
FULL_SPAN = ("2000-01-03", "2024-09-30")

WIN_SHARE_MIN = 0.70
MEDIAN_IRR_MARGIN = 0.005
P10_IRR_FLOOR = -0.015
MDD_TW_TOL = 0.05
EPS = 1e-12

PASS = "CONTRIB_BEATS_SPY"
FAIL, NOT_EVALUABLE = "FAIL", "NOT_EVALUABLE"
DEADLINE_MARGIN = 90.0
SIZE_LIMIT = 190_000


def smoke_params() -> dict:
    return {"primary_horizon": 2, "second_horizon": 1, "step": "A", "first_start": "2012-01-01", "last_start": "2016-12-31",
            "judged_end": "2016-06-30", "full_span": ("2012-01-03", "2016-06-30")}


def real_params() -> dict:
    return {"primary_horizon": PRIMARY_HORIZON, "second_horizon": SECOND_HORIZON, "step": STEP, "first_start": FIRST_START,
            "last_start": None, "judged_end": JUDGED_END, "full_span": FULL_SPAN}


class _Stop(Exception):
    """시간 예산 끝·새 계산 수 상한·SIGTERM — 캐시는 이미 저장돼 있다."""


# =================================================================================================
# 자료
# =================================================================================================

def synthetic(seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-04", "2018-12-31")
    n = len(idx)
    shock = np.where((idx >= "2011-07-25") & (idx < "2011-10-03"), -0.006, 0.0) \
        + np.where((idx >= "2015-08-03") & (idx < "2015-10-05"), -0.007, 0.0)   # 주봉 RSI < 30 이 생기게
    spy = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, n) + shock))
    qqq = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, n) + 1.3 * shock))
    bil = 90 * np.cumprod(np.full(n, 1.00008))
    adj = pd.DataFrame({SPY: spy, QQQ: qqq, BIL: bil}, index=idx)
    close = adj * 0.995
    fx = pd.Series(1300.0 + np.cumsum(rng.normal(0, 3, n)), index=idx)
    return {"close": close, "adj": adj, "fx": fx, "source": "synthetic (smoke)", "missing": []}


def load_real() -> dict:
    from core.market_data import get_multiple_price_history

    h = get_multiple_price_history(TICKERS, start=DATA_START, end=None, interval="1d") or {}
    close, adj = {}, {}
    for t in TICKERS:
        df = h.get(t)
        if df is None or df.empty:
            continue
        for store, col in ((close, "Close"), (adj, "Adj Close" if "Adj Close" in df and df["Adj Close"].notna().any() else "Close")):
            s = df[col].dropna()
            s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
            store[t] = s[~s.index.duplicated(keep="last")]
    if SPY not in adj or QQQ not in adj:
        raise RuntimeError(f"필수 ETF 가격을 받지 못함: {[t for t in (SPY, QQQ) if t not in adj]}")
    days = adj[SPY].index
    close, adj = pd.DataFrame(close).reindex(days), pd.DataFrame(adj).reindex(days)
    for t in TICKERS:
        if t not in adj:
            adj[t], close[t] = np.nan, np.nan
    fx = tx.usdkrw_series()
    if fx.index.min() > pd.Timestamp("2000-01-31"):
        raise RuntimeError("원/달러 환율이 2000-01 이전부터 없음")
    return {"close": close[TICKERS], "adj": adj[TICKERS], "fx": fx, "source": "yfinance (Close / Adj Close), USDKRW via tax_fx.usdkrw_series",
            "missing": [t for t in TICKERS if adj[t].isna().all()]}


def prepare(inp: dict) -> dict:
    adj = inp["adj"].ffill(limit=3)
    close = inp["close"].ffill(limit=3)
    return {"adj": adj, "close": close, "tax_adj": adj.bfill(), "tax_close": close.bfill(), "fx": inp["fx"],
            "bil_ok": adj[BIL].notna()}


# =================================================================================================
# 신호 (결과를 보기 전에 고정)
# =================================================================================================

def weekly_close(px: pd.Series) -> pd.Series:
    """각 주(월~금)의 마지막 거래일 종가. 인덱스는 그 실제 거래일."""
    px = px.dropna()
    last_day = px.groupby(px.index.to_period("W-FRI")).apply(lambda s: s.index[-1])
    return px.loc[pd.DatetimeIndex(last_day.values)]


def wilder_rsi(c: pd.Series, n: int = RSI_WEEKS) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = up / dn
    rsi = 100 - 100 / (1 + rs)
    return rsi.where(dn > 0, 100.0).where(up.notna())


def weekly_flags(c: pd.Series) -> pd.DataFrame:
    """주별 보유 여부(그 주 종가 기준 결정). 자료가 모자라는 앞쪽 주는 밖(False)."""
    sma = c.rolling(MA_WEEKS, min_periods=MA_WEEKS).mean()
    rsi = wilder_rsi(c)
    above = (c > sma) & sma.notna()
    rsi_in, dip = [], []
    hold, dip_on = False, False
    for r in rsi.to_numpy():
        if np.isfinite(r):
            if not hold and r < RSI_OVERSOLD:
                hold = True
            elif hold and r >= RSI_EXIT:
                hold = False
            if not dip_on and r < RSI_OVERSOLD:
                dip_on = True
            elif dip_on and r >= RSI_RECOVER:
                dip_on = False
        rsi_in.append(hold)
        dip.append(dip_on)
    out = pd.DataFrame({"MA20": above.to_numpy(), "RSI": rsi_in}, index=c.index)
    out["MA20RSI"] = out["MA20"].to_numpy() | np.array(dip)
    out["rsi"] = rsi
    out["sma"] = sma
    return out


def daily_weights(prep: dict, under: str, rule: str, flags: pd.DataFrame) -> pd.DataFrame:
    """주 마지막 거래일에 정한 보유 여부를 다음 거래일부터 적용. 밖이면 BIL(없으면 현금)."""
    days = prep["adj"].index
    f = flags[rule].astype(float).reindex(days).ffill().fillna(0.0).shift(1).fillna(0.0)
    f = f.where(prep["adj"][under].notna(), 0.0)
    bil = prep["bil_ok"].astype(float)
    return pd.DataFrame({under: f, BIL: (1.0 - f) * bil}, index=days)


def build_frames(prep: dict) -> tuple[dict, dict]:
    frames, info = {}, {}
    for u in (SPY, QQQ):
        fl = weekly_flags(weekly_close(prep["adj"][u]))
        info[u] = fl
        for r in RULES:
            frames[f"{u}_{r}"] = daily_weights(prep, u, r, fl)
    return frames, info


def trades_per_year(w: pd.DataFrame, under: str) -> float:
    s = w[under]
    sw = int((s.diff().abs() > 0.5).sum())
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    return sw / yrs if yrs > 0 else float("nan")


# =================================================================================================
# 판정 (결과를 보기 전에 고정)
# =================================================================================================

def _ok(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def contrib_checks(s: dict) -> Optional[dict[str, Optional[bool]]]:
    if not s or not s.get("n_windows"):
        return None
    gap = (s["median_strategy_mdd_tw"] - s["median_benchmark_mdd_tw"]) \
        if _ok(s.get("median_strategy_mdd_tw")) and _ok(s.get("median_benchmark_mdd_tw")) else None
    return {
        "win_share": (s["share_terminal_win"] >= WIN_SHARE_MIN - EPS) if _ok(s.get("share_terminal_win")) else None,
        "median_irr": (s["median_diff_irr"] >= MEDIAN_IRR_MARGIN - EPS) if _ok(s.get("median_diff_irr")) else None,
        "p10_irr": (s["p10_diff_irr"] >= P10_IRR_FLOOR - EPS) if _ok(s.get("p10_diff_irr")) else None,
        "mdd_tw": (gap >= -MDD_TW_TOL - EPS) if gap is not None else None,
    }


def contrib_verdict(checks, noop, observed_ir, power) -> str:
    if checks is None or noop:
        return NOT_EVALUABLE
    if all(v is True for v in checks.values()):
        return PASS
    return rp.classify_fail(observed_ir, power)


def information_ratio(a, b, ppy: float = 252.0) -> float:
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    if len(d) < 2:
        return float("nan")
    sd = float(np.std(d, ddof=1))
    return float(np.mean(d) / sd * math.sqrt(ppy)) if sd > 0 else float("nan")


# =================================================================================================
# 체크포인트
# =================================================================================================

def _atomic_pickle(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_ckpt(path: Path, fp):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
        return obj["payload"] if obj.get("fingerprint") == fp else None
    except Exception:  # noqa: BLE001
        return None


# =================================================================================================
# 계산
# =================================================================================================

def account(scenario: str) -> tx.AccountConfig:
    init, monthly = SCENARIOS[scenario]
    return tx.AccountConfig(initial_krw=float(init), monthly_contribution_krw=float(monthly), contribution_policy=POLICY)


def bh_frame(prep: dict, t: str) -> pd.DataFrame:
    return tx.buy_and_hold_weights(prep["adj"].index, t)


def full_span_sim(prep: dict, frames: dict, span) -> dict:
    a, b = pd.Timestamp(span[0]), pd.Timestamp(span[1])
    cfg = account(PRIMARY_SCENARIO)
    out = {}
    allf = {"SPY_BH": bh_frame(prep, SPY), "QQQ_BH": bh_frame(prep, QQQ), **frames}
    for name, w in allf.items():
        w0 = w.loc[a:b]
        w = w0.loc[:, w0.abs().sum() > 0]
        s = tx.simulate(w, prep["tax_close"], prep["tax_adj"], prep["fx"], cfg)
        twr = s["twr_index"]
        under = name.split("_")[0]
        out[name] = {"irr_after_liquidation": float(s["irr_after_liquidation"]), "irr_pre_cost": float(s["irr_pre_cost"]),
                     "terminal_after_liquidation_krw": float(s["terminal_after_liquidation_krw"]),
                     "total_contributed_krw": float(s["total_contributed_krw"]),
                     "capital_gains_tax_krw": float(s["totals"]["capital_gains_tax_krw"]),
                     "fees_krw": float(s["totals"]["fees_krw"]),
                     "mdd_tw": re_.max_drawdown(twr),
                     "time_in_market": float(w0[under].mean()),
                     "switches_per_year": 0.0 if name.endswith("_BH") else round(trades_per_year(w0, under), 1),
                     "twr_daily": twr.pct_change().fillna(0.0).to_numpy(dtype=float)[1:]}
    return out


def cell_plan(params: dict) -> list[tuple[str, float, str, str, str]]:
    """(시나리오, 구간 길이, 전략, 기준, 역할). 역할: judged(판정) / report(같은 규칙 보고)."""
    hz0, hz1 = params["primary_horizon"], params["second_horizon"]
    plan = []
    for scen in SCENARIO_ORDER:
        hzs = (hz0, hz1) if scen == PRIMARY_SCENARIO else (hz0,)
        for hz in hzs:
            role = "judged" if (scen == PRIMARY_SCENARIO and hz == hz0) else "report"
            for n in STRATEGIES:
                plan.append((scen, hz, n, SPY, role))
            plan.append((scen, hz, "QQQ_BH", SPY, "report"))
            for r in RULES:
                plan.append((scen, hz, f"QQQ_{r}", QQQ, "report"))
    return plan


def cell_key(scen, hz, name, bench) -> str:
    return f"{scen}|{hz:g}y|{name}|vs{bench}"


def cell_summary(rows: list[dict], horizon: float, judged_end: str) -> dict:
    lim = pd.Timestamp(judged_end)
    out = {}
    for key, rr in (("judged", [r for r in rows if pd.Timestamp(r["end"]) <= lim]),
                    ("reported", [r for r in rows if pd.Timestamp(r["end"]) > lim])):
        s = re_.summarize(rr, horizon) if rr else {"n_windows": 0, "share_terminal_win": None}
        if rr:
            def med(f):
                return float(np.nanmedian([f(r) for r in rr]))
            s.update({"median_strategy_terminal_krw": med(lambda r: r["strategy"]["terminal_krw"]),
                      "median_benchmark_terminal_krw": med(lambda r: r["benchmark"]["terminal_krw"]),
                      "median_total_contributed_krw": med(lambda r: r["strategy"]["total_contributed_krw"]),
                      "median_strategy_tax_krw": med(lambda r: r["strategy"]["capital_gains_tax_krw"]),
                      "median_benchmark_tax_krw": med(lambda r: r["benchmark"]["capital_gains_tax_krw"]),
                      "first_start": rr[0]["start"], "last_end": rr[-1]["end"]})
        out[key] = s
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-new-per-run", type=int, default=0)
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    (ck / "cells").mkdir(parents=True, exist_ok=True)
    params = smoke_params() if a.smoke else real_params()
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    power = rp.power_report(POWER_YEARS, N_TRIALS)
    dl_epoch = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    t0 = time.time()
    budget = {"left": a.max_new_per_run or None}
    bench: dict[str, dict] = {}

    def log(s):
        print(s, flush=True)

    def mono_deadline():
        return None if dl_epoch is None else time.monotonic() + (dl_epoch - time.time() - DEADLINE_MARGIN)

    def stage(name, fn):
        path = ck / f"{name}.pkl"
        got = _load_ckpt(path, fp)
        if got is None:
            if dl_epoch is not None and time.time() > dl_epoch - DEADLINE_MARGIN:
                raise _Stop()
            got = fn()
            _atomic_pickle(path, {"fingerprint": fp, "payload": got})
            log(f"단계 저장: {name}")
        return got

    def save_bench():
        for k, d in bench.items():
            _atomic_pickle(ck / f"bench_{k}.pkl", {"fingerprint": {**fp, "bench": k}, "payload": d})

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        inp = stage("inputs", lambda: synthetic() if a.smoke else load_real())
        prep = prepare(inp)
        frames, info = build_frames(prep)
        frames_all = {**frames, "QQQ_BH": bh_frame(prep, QQQ)}
        full = stage("full_span", lambda: full_span_sim(prep, frames, params["full_span"]))
        start0 = prep["adj"].index[prep["adj"].index >= pd.Timestamp(params["first_start"])][0]
        days = prep["adj"].loc[start0:].index
        panels = {"close": prep["tax_close"], "adj": prep["tax_adj"], "fx": prep["fx"]}
        rows_by_cell, roles = {}, {}
        for scen, hz, name, bname, role in cell_plan(params):
            bk = f"{scen}_{bname}"
            if bk not in bench:
                bench[bk] = _load_ckpt(ck / f"bench_{bk}.pkl", {**fp, "bench": bk}) or {}
            wins = re_.rolling_windows(days, hz, step=params["step"], first_start=params["first_start"],
                                       last_start=params["last_start"])
            key = cell_key(scen, hz, name, bname)
            left = budget["left"]
            res = re_.evaluate_windows(frames_all[name], panels, wins, account(scen),
                                       benchmark_weights_fn=(lambda idx, t=bname: tx.buy_and_hold_weights(idx, t)),
                                       cache_path=ck / f"cells/{key.replace('|', '_')}.pkl", benchmark_cache=bench[bk],
                                       fingerprint={**fp, "cell": key}, max_new=left, deadline=mono_deadline())
            save_bench()
            if left is not None:
                budget["left"] = max(0, left - res["new_sims"])
            log(f"{key}: {res['done']}/{len(wins)} 구간 (새 시뮬레이션 {res['new_sims']})")
            if not res["complete"]:
                raise _Stop()
            rows_by_cell[key], roles[key] = res["rows"], role
        cells = {k: cell_summary(v, float(k.split("|")[1][:-1]), params["judged_end"]) for k, v in rows_by_cell.items()}
        result = build_result(cells, roles, full, info, power, params, a.smoke, inp)
        if a.smoke:
            cov = {"all_cells": len(cells) == len(cell_plan(params)),
                   "judged_windows": all(c["judged"]["n_windows"] > 0 for c in cells.values()),
                   "every_rule_trades": all(full[n]["switches_per_year"] > 0 for n in STRATEGIES),
                   "rules_differ": len({round(full[n]["time_in_market"], 6) for n in STRATEGIES}) > 1,
                   "contributions_counted": full["SPY_BH"]["total_contributed_krw"] > SCENARIOS["B"][0],
                   "verdicts_valid": all(v in (PASS, FAIL, "FAIL_UNDERPOWERED", NOT_EVALUABLE)
                                         for v in result["judged_raw"].values())}
            result["smoke_coverage"] = cov
            bad = [k for k, v in cov.items() if not v]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
    except _Stop:
        save_bench()
        log(f"시간 예산·계산 상한 끝 — 캐시 저장됨, 다음 회차에 이어서 ({time.time() - t0:.0f}초)")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text.encode("utf-8")) > SIZE_LIMIT:
        result.pop("recent_signals", None)
        text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    (out / "results.json").write_text(text, encoding="utf-8")
    (out / "REPORT.md").write_text(render(result), encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    log(f"완료 ({time.time() - t0:.0f}초)")
    return 0


# =================================================================================================
# 결과
# =================================================================================================

def _r(x, nd=4):
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return round(x, nd) if math.isfinite(x) else None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    return x


def build_result(cells, roles, full, info, power, params, smoke, inp) -> dict:
    hz0 = params["primary_horizon"]
    spy_d = full["SPY_BH"]["twr_daily"]
    obs, noop, judged_raw, checks = {}, {}, {}, {}
    for n in STRATEGIES:
        d = full[n]["twr_daily"]
        m = min(len(d), len(spy_d))
        obs[n] = information_ratio(d[-m:], spy_d[-m:])
        noop[n] = rp.noop_guard((d[-m:] - spy_d[-m:]).tolist())
        k = cell_key(PRIMARY_SCENARIO, hz0, n, SPY)
        checks[n] = contrib_checks(cells[k]["judged"])
        judged_raw[n] = contrib_verdict(checks[n], noop[n], obs[n], power)
    for k, c in cells.items():
        c["role"] = roles[k]
        c["checks"] = contrib_checks(c["judged"])
        c["same_rule_met"] = bool(c["checks"] and all(v is True for v in c["checks"].values()))
    verdicts: dict[str, Any] = {n: (f"SMOKE_ONLY({v})" if smoke else v) for n, v in judged_raw.items()}
    verdicts["passed"] = f"{sum(v == PASS for v in judged_raw.values())}/{N_TRIALS}"
    verdicts["scenario"] = f"B: {SCENARIOS['B'][0]:,} KRW + {SCENARIOS['B'][1]:,}/month, {hz0:g}y windows vs SPY buy-and-hold"
    verdicts["qqq_vs_qqq_bh_same_rule"] = ", ".join(
        f"QQQ_{r}={'met' if cells[cell_key(PRIMARY_SCENARIO, hz0, f'QQQ_{r}', QQQ)]['same_rule_met'] else 'not met'}" for r in RULES)
    recent = {}
    for u, fl in info.items():
        t = fl.tail(4)
        recent[u] = [{"week": str(i.date()), "rsi": float(r.rsi) if np.isfinite(r.rsi) else None,
                      "above_ma20": bool(r.MA20), "rsi_hold": bool(r.RSI), "ma20rsi_hold": bool(r.MA20RSI)} for i, r in t.iterrows()]
    fullc = {k: {kk: vv for kk, vv in v.items() if kk != "twr_daily"} for k, v in full.items()}
    return _r({
        "judge_version": RULES_VERSION, "smoke": smoke, "source": inp.get("source"), "missing": inp.get("missing", []),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdicts": verdicts, "judged_raw": judged_raw, "power": power,
        "rule": {"weekly_bar": "last trading day of each Mon-Fri week, adjusted close; signal at that close, trade at next trading day's close",
                 "MA20": f"hold underlying iff weekly close > {MA_WEEKS}-week SMA, else BIL (0% USD cash before BIL)",
                 "RSI": f"buy when weekly RSI({RSI_WEEKS}, Wilder) < {RSI_OVERSOLD:g}, sell when RSI >= {RSI_EXIT:g}; start out",
                 "MA20RSI": f"hold if above {MA_WEEKS}-week SMA, or after RSI < {RSI_OVERSOLD:g} until RSI >= {RSI_RECOVER:g}",
                 "scenarios": {k: {"initial_krw": v[0], "monthly_krw": v[1]} for k, v in SCENARIOS.items()},
                 "policy": POLICY, "windows": {"primary_horizon": hz0, "second_horizon_B_only": params["second_horizon"],
                                               "step": params["step"], "first_start": params["first_start"],
                                               "judged_end": params["judged_end"]},
                 "thresholds": {"win_share_min": WIN_SHARE_MIN, "median_irr_margin": MEDIAN_IRR_MARGIN,
                                "p10_irr_floor": P10_IRR_FLOOR, "mdd_tw_tol": MDD_TW_TOL},
                 "n_trials": N_TRIALS, "full_span": list(params["full_span"])},
        "observed_ir_full_span": obs, "noop": noop, "checks": checks,
        "cells": cells, "full_span_B": fullc, "recent_signals": recent,
    })


# =================================================================================================
# 보고서
# =================================================================================================

def _p(x, signed=False, nd=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _man(x):
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x / 10000:,.0f}만 원"


def _yn(v):
    return "—" if v is None else ("통과" if v else "미달")


NAMES = {"SPY_BH": "SPY 그냥 보유", "QQQ_BH": "QQQ 그냥 보유",
         **{f"{u}_MA20": f"{u} 20주선" for u in (SPY, QQQ)},
         **{f"{u}_RSI": f"{u} RSI 과매도" for u in (SPY, QQQ)},
         **{f"{u}_MA20RSI": f"{u} 20주선 + RSI 눌림목" for u in (SPY, QQQ)}}


def render(r: dict) -> str:
    v, rule = r["verdicts"], r["rule"]
    hz0 = rule["windows"]["primary_horizon"]
    je = rule["windows"]["judged_end"]
    L = [f"# 주봉 20주선·RSI 과매도 매매 — 적립식 세후 대 SPY v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
         "주봉 기준 20주 이동평균선과 RSI 과매도로 사고파는 기법이, 처음 목돈 + 매달 적립으로 오래 굴릴 때 한국 세금 뒤 "
         "SPY 그냥 보유보다 많이 남기는지 본다. QQQ 에도 같은 기법을 적용해 곁가지로 확인한다.", "",
         f"**판정 (시나리오 B, {hz0:g}년 구간, 대 SPY): 통과 {v['passed']}** — " + " · ".join(f"{n} **{v[n]}**" for n in STRATEGIES), "",
         "통과는 '전진 원장 후보'일 뿐 채택이 아니다. 엔진은 바뀌지 않았다.", "",
         rp.power_line(r["power"]), "",
         "## 규칙 (결과를 보기 전에 고정)", "",
         "- 주봉 = 각 주의 마지막 거래일 조정 종가. 그 종가로 신호를 정하고 다음 거래일 종가에 매매한다. 밖에 있을 때는 BIL(초단기 국채, 2007-05 상장 전은 이자 없는 달러 현금).",
         f"- 20주선: 주 종가가 20주 평균보다 위면 보유, 아래면 BIL.",
         f"- RSI 과매도: 주봉 RSI(14) < 30 이면 사고, 70 이상이면 판다.",
         f"- 20주선 + RSI 눌림목: 20주선 위면 보유, 아래라도 RSI < 30 이 나오면 사서 RSI 50 회복까지 보유.",
         f"- 시나리오 B(1,000만 원 + 매달 15만 원), 2000-01 부터 매달 시작하는 {hz0:g}년 구간, 구간 끝 ≤ {je} 만 판정. 기준 SPY 도 같은 날 같은 돈을 받는다.",
         f"- 통과: ① SPY 보다 많이 남은 구간 ≥ {WIN_SHARE_MIN:.0%} ② IRR 차이 중앙값 ≥ +{MEDIAN_IRR_MARGIN * 100:.1f}%p "
         f"③ 10분위 ≥ {P10_IRR_FLOOR * 100:.1f}%p ④ 시간가중 MDD 중앙값이 SPY 보다 {MDD_TW_TOL * 100:.0f}%p 넘게 나쁘지 않음.",
         "- 팔 때마다 양도세(22%, 연 250만 원 공제)가 생긴다. SPY 그냥 보유는 끝까지 팔지 않아 세금이 미뤄진다(끝에 모두 판다고 보고 비교).", "",
         f"## 판정 — 시나리오 B, {hz0:g}년, 대 SPY 그냥 보유", "",
         "| 전략 | 이긴 구간 비율 | IRR 차이 중앙값 | 10분위 | 시간가중 MDD 중앙값 (SPY) | ① | ② | ③ | ④ | 판정 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for n in STRATEGIES:
        c = r["cells"][cell_key("B", hz0, n, SPY)]
        s, ch = c["judged"], c.get("checks") or {}
        L.append(f"| {NAMES[n]} | {_p(s.get('share_terminal_win'), nd=0)} ({s.get('n_windows')}구간) | {_p(s.get('median_diff_irr'), True, 2)}p | "
                 f"{_p(s.get('p10_diff_irr'), True, 2)}p | {_p(s.get('median_strategy_mdd_tw'))} ({_p(s.get('median_benchmark_mdd_tw'))}) | "
                 f"{_yn(ch.get('win_share'))} | {_yn(ch.get('median_irr'))} | {_yn(ch.get('p10_irr'))} | {_yn(ch.get('mdd_tw'))} | **{r['judged_raw'][n]}** |")
    c0 = r["cells"][cell_key("B", hz0, STRATEGIES[0], SPY)]["judged"]
    if c0.get("n_windows"):
        L += ["", f"주의: {c0['n_windows']}개 구간이 크게 겹쳐 겹치지 않는 {hz0:g}년 구간은 약 {c0['effective_independent_windows']:.1f}개뿐이다."]
    # QQQ 곁가지
    L += ["", f"## 곁가지 — QQQ (시나리오 B, {hz0:g}년, 보고만)", "",
          "QQQ 는 지난 25년 가장 강했던 지수라 '그때 QQQ 를 고를 근거'가 없으면 사후 선택이다. 그래서 판정하지 않고 두 가지를 본다: "
          "QQQ 그냥 보유가 SPY 를 얼마나 이겼나, 기법이 QQQ 그냥 보유를 더 낫게 하나.", "",
          "| 전략 | 기준 | 이긴 구간 비율 | IRR 차이 중앙값 | 10분위 | 시간가중 MDD 중앙값 (기준) | 같은 규칙 |", "|---|---|---|---|---|---|---|"]
    for n, b in [("QQQ_BH", SPY)] + [(f"QQQ_{x}", QQQ) for x in RULES]:
        c = r["cells"][cell_key("B", hz0, n, b)]
        s = c["judged"]
        L.append(f"| {NAMES[n]} | {NAMES[b + '_BH']} | {_p(s.get('share_terminal_win'), nd=0)} | {_p(s.get('median_diff_irr'), True, 2)}p | "
                 f"{_p(s.get('p10_diff_irr'), True, 2)}p | {_p(s.get('median_strategy_mdd_tw'))} ({_p(s.get('median_benchmark_mdd_tw'))}) | "
                 f"{'충족' if c['same_rule_met'] else '미충족'} |")
    # 전체 표
    L += ["", "## 모든 칸 (같은 규칙, B·10년·대 SPY 외에는 보고만)", "",
          "| 칸 | 부분 | 구간 수 | 이긴 비율 | IRR 중앙값 (기준) | IRR 차이 중앙값 / 10분위 | 남은 돈 중앙값 (기준) | 넣은 돈 | 낸 양도세 중앙값 (기준) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for k, c in r["cells"].items():
        for part in ("judged", "reported"):
            s = c[part]
            if not s.get("n_windows"):
                continue
            L.append(f"| {k} | {'판정 구간' if part == 'judged' else '끝 > ' + je} | {s['n_windows']} | {_p(s.get('share_terminal_win'), nd=0)} | "
                     f"{_p(s.get('median_strategy_irr'))} ({_p(s.get('median_benchmark_irr'))}) | "
                     f"{_p(s.get('median_diff_irr'), True, 2)}p / {_p(s.get('p10_diff_irr'), True, 2)}p | "
                     f"{_man(s.get('median_strategy_terminal_krw'))} ({_man(s.get('median_benchmark_terminal_krw'))}) | "
                     f"{_man(s.get('median_total_contributed_krw'))} | {_man(s.get('median_strategy_tax_krw'))} ({_man(s.get('median_benchmark_tax_krw'))}) |")
    fs = r["full_span_B"]
    L += ["", f"## 한 계좌 전체 기간 (시나리오 B, {rule['full_span'][0]} ~ {rule['full_span'][1]})", "",
          "| 전략 | IRR(청산 후) | 세전 IRR | 시간가중 MDD | 시장에 있던 비율 | 매매 전환/년 | 낸 양도세 | 수수료 |", "|---|---|---|---|---|---|---|---|"]
    for n in ("SPY_BH", "QQQ_BH") + STRATEGIES:
        x = fs[n]
        L.append(f"| {NAMES[n]} | {_p(x['irr_after_liquidation'], nd=2)} | {_p(x['irr_pre_cost'], nd=2)} | {_p(x['mdd_tw'])} | "
                 f"{_p(x['time_in_market'], nd=0)} | {x['switches_per_year'] if x['switches_per_year'] is not None else '—'} | "
                 f"{_man(x['capital_gains_tax_krw'])} | {_man(x['fees_krw'])} |")
    L += ["", "## 주의", "",
          "- 구간이 크게 겹친다. 실제로 독립적인 10년은 2~3개뿐이다.",
          "- 2000~2024 는 닷컴 붕괴·금융위기가 앞쪽에 몰린 구간이라 20주선 같은 하락 회피 기법에 유리할 수 있다. 결과를 일반화하지 말 것.",
          "- 매매 비용은 수수료 0.1%·환전 비용만 넣었다. 호가 차이·체결 지연은 없다(다음 날 종가 체결).",
          "- 세금은 tax_fx 추정이며 신고용이 아니다. 투자 조언이 아니다. 엔진 반영은 사용자 확인 뒤 별도 작업이다."]
    if r["smoke"]:
        L += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
