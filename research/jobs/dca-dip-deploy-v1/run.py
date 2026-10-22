"""검증 연구 dca-dip-deploy-v1 (2026-10-22 사전 등록): 팔지 않고 매달 적립할 때, 새 돈을 '바닥 신호'까지 기다렸다 넣으면 바로 넣는 것보다 낫나.

사용자 요청(2026-10-22): 웬만해서는 팔지 않고 보유하며 월 10만 원 정도를 늘 추가로 넣을 때, 언제 밑바닥을 잡을지 기준을 세우는 연구.
테스트는 길게 — 최대한 저점에 사서 누리자는 주의.

두 부분:
  1) 바닥 신호 진단: 신호가 켜진 날 산 시장의 앞으로 1·3·5년 수익이 아무 날이나 산 것보다 높은가(1927~2007 두 반쪽에서 모두).
  2) 적립 타이밍: 같은 적립금을 (a) 들어오는 날 바로 시장에 넣기(DCA, 기준) 대 (b) 현금으로 기다렸다가 신호가 켜지면 한꺼번에 넣기.
     기다림에는 대가가 있다(그동안 시장이 오르면 놓친다). 그래서 1) 에서 신호가 쓸모 있어도 2) 에서 질 수 있다 — 둘을 함께 본다.
자료: Ken French 일별 시장 총수익(1926-07~), 무위험 이자. 시장 = 미국 전체 주식(SPY 와 거의 같은 대상).
보고만: 같은 규칙을 2000 년 이후 실제 SPY(원화·실제 환율)로, 그리고 '신의 손'(다음 1년 안 최저가에 사는 완벽한 사후 매수) 상한.
규칙 전체는 SPEC.md 와 아래 상수에 결과를 보기 전에 고정했다. 엔진은 바뀌지 않는다.
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

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(HERE))

import lab as L  # noqa: E402

from core import tax_fx as tx  # noqa: E402

JOB_ID = "dca-dip-deploy-v1"
RULES_VERSION = "dca-dip-deploy-v1/2026-10-22"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
MONTHLY_KRW = 100_000
SCENARIOS = {"M": (0, MONTHLY_KRW),             # 판정: 적립만(타이밍 결정만 따로 본다)
             "H": (10_000_000, MONTHLY_KRW)}    # 보고: 이미 1,000만 원 보유(첫날 바로 삼) + 월 10만 원 타이밍
PRIMARY = "M"
HORIZONS = (10, 20)
JUDGED_SETS = ("selection", "confirmation")
BASE = "DCA"
SIGNALS = ("DD10", "DD20", "DD30", "RSIW30", "BELOW20W", "LOWVAL")
ARMS = SIGNALS + ("HALF_DD20", "CAP12_DD20")
N_TRIALS = len(ARMS)
LABELS = {"DCA": "바로 넣기(기준)",
          "DD10": "고점 대비 −10% 이하일 때만 산다", "DD20": "고점 대비 −20% 이하", "DD30": "고점 대비 −30% 이하",
          "RSIW30": "주봉 RSI(14) < 30", "BELOW20W": "주 종가 < 20주선", "LOWVAL": "가격/10년 평균이 역사 하위 20%",
          "HALF_DD20": "절반 바로, 절반은 −20% 까지 기다림", "CAP12_DD20": "−20% 까지 기다리되 최대 12개월",
          "ORACLE": "신의 손: 다음 1년 안 최저가에 산다(사후, 상한)"}
DD_LEVELS = {"DD10": -0.10, "DD20": -0.20, "DD30": -0.30}
RSI_OVERSOLD = 30.0
MA_WEEKS = 20
LOWVAL_LOOKBACK = 2520           # 10년 평균 가격(거래일)
LOWVAL_PCT = 0.20                # 그 비율의 '지금까지' 분포 하위 20%
LOWVAL_MIN_HISTORY = 2520        # 비율 기록이 10년 미만이면 판단 불가 → 바로 산다
CAP_ROWS = 252

# 판정(각 팔 대 DCA, 시나리오 M, 청산 세후 IRR): 선택·확인 두 반쪽 × 10·20년 모두에서
WIN_SHARE_MIN = 0.65
MEDIAN_IRR_MIN = 0.003
P10_IRR_MIN = -0.015
MDD_TOL = 0.05
PASS, FAIL = "BEATS_DCA", "FAIL"

# 바닥 신호 진단
FWD_ROWS = {"1y": 252, "3y": 756, "5y": 1260}
PRIMARY_FWD = "3y"
DIAG_ALPHA = 0.05
DIAG_BOOT = 400
USEFUL, NOT_USEFUL = "USEFUL_SIGNAL", "NOT_USEFUL"

ETF_FIRST_START = "2000-01-01"
ETF_JUDGED_END = "2024-09-30"
DEADLINE_MARGIN = 120.0
SIZE_LIMIT = 190_000


class _Stop(Exception):
    pass


# =================================================================================================
# 신호 (각 행 d 의 값은 d 일 종가까지만 사용)
# =================================================================================================

def signal_flags(price: pd.Series) -> pd.DataFrame:
    days = price.index
    dd = L.drawdown(price)
    out = {k: (dd <= v) for k, v in DD_LEVELS.items()}
    wc = L.weekly_close(price)
    rsi = L.weekly_to_daily(L.wilder_rsi(wc), days)
    out["RSIW30"] = rsi < RSI_OVERSOLD
    sma = wc.rolling(MA_WEEKS, min_periods=MA_WEEKS).mean()
    out["BELOW20W"] = L.weekly_to_daily(((wc < sma) & sma.notna()).astype(float), days).fillna(0.0) > 0.5
    ratio = price / price.rolling(LOWVAL_LOOKBACK, min_periods=LOWVAL_LOOKBACK).mean()
    hist_n = ratio.notna().cumsum()
    thr = ratio.expanding(min_periods=1).quantile(LOWVAL_PCT)
    lv = (ratio <= thr) & ratio.notna()
    out["LOWVAL"] = lv | (hist_n < LOWVAL_MIN_HISTORY)       # 판단 불가 기간에는 '켜짐'(바로 산다)
    out["LOWVAL_ONLY_VALID"] = lv & (hist_n >= LOWVAL_MIN_HISTORY)
    return pd.DataFrame({k: pd.Series(v, index=days).fillna(False).astype(bool) for k, v in out.items()})


def deploy_rows(flags: pd.DataFrame) -> dict[str, np.ndarray]:
    """각 행 r 에 들어온 돈을 사는 행: d 일 종가 신호 → d+1 일 매수. 즉 r 이후 처음으로 '전날 신호 켜짐'인 행."""
    out = {}
    for k in SIGNALS:
        f = flags[k].to_numpy()
        shifted = np.concatenate([[False], f[:-1]])
        out[k] = L.next_true_row(shifted)
    return out


# =================================================================================================
# 한 구간
# =================================================================================================

def arm_plan(arm: str, rows: np.ndarray, dep: dict, lump_rows: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(금액 배수, 사는 행) 두 줄로 나눈 계획 — HALF 는 한 적립을 두 조각으로 나눈다. lump_rows: 앞쪽 몇 개가 목돈(바로 산다)."""
    if arm in (BASE,):
        return rows, np.ones(len(rows)), rows.copy()
    if arm == "HALF_DD20":
        d = dep["DD20"][rows]
        d[:lump_rows] = rows[:lump_rows]
        return np.concatenate([rows, rows]), np.full(2 * len(rows), 0.5), np.concatenate([rows.copy(), d])
    sig = "DD20" if arm == "CAP12_DD20" else arm
    d = dep[sig][rows].copy()
    if arm == "CAP12_DD20":
        d = np.minimum(d, rows + CAP_ROWS)
    d[:lump_rows] = rows[:lump_rows]
    return rows, np.ones(len(rows)), d


def oracle_deploy(px: np.ndarray, rows: np.ndarray, end_row: int, lump_rows: int) -> np.ndarray:
    d = rows.copy()
    for i, r in enumerate(rows):
        if i < lump_rows:
            continue
        hi = min(r + CAP_ROWS, end_row)
        d[i] = r + int(np.argmin(px[r:hi + 1]))
    return d


def run_window(px: np.ndarray, cg: np.ndarray, days: pd.DatetimeIndex, dep: dict, s, e, scen: str, arms) -> dict[str, dict]:
    init, monthly = SCENARIOS[scen]
    rows = L.contribution_rows(days, s, e)
    end_row = days.searchsorted(e, side="right") - 1
    start_row = rows[0]
    amounts = np.full(len(rows), float(monthly))
    lump = 0
    if init > 0:
        rows = np.concatenate([[rows[0]], rows])
        amounts = np.concatenate([[float(init)], amounts])
        lump = 1
    px2 = px.reshape(-1, 1)
    out = {}
    for arm in arms:
        if arm == "ORACLE":
            r_, mult, d_ = rows, np.ones(len(rows)), oracle_deploy(px, rows, end_row, lump)
        else:
            r_, mult, d_ = arm_plan(arm, rows, dep, lump)
            if arm == "HALF_DD20":
                amounts_ = np.concatenate([amounts, amounts]) * mult
            else:
                amounts_ = amounts * mult
        if arm == "ORACLE":
            amounts_ = amounts
        sim = L.simulate_buy_only(px2, cg, r_, amounts_, d_, np.zeros(len(r_), dtype=int), end_row, start_row)
        irr = L.xirr_monthly(amounts, rows, end_row, sim["terminal"], days)
        out[arm] = {"irr": irr, "terminal": sim["terminal"], "terminal_pre": sim["terminal_pre"], "mdd": sim["mdd"],
                    "invested_share": sim["invested_share"], "mean_wait_days": sim["mean_wait_days"],
                    "contributed": float(np.sum(amounts))}
    return out


def pair_rows(win_results: list, arm: str) -> list[dict]:
    rows = []
    for (s, e), res in win_results:
        a, b = res[arm], res[BASE]
        rows.append({"start": str(s.date()), "end": str(e.date()), "strategy_irr": a["irr"], "base_irr": b["irr"],
                     "strategy_terminal": a["terminal"], "base_terminal": b["terminal"],
                     "strategy_mdd": a["mdd"], "base_mdd": b["mdd"], "invested_share": a["invested_share"]})
    return rows


def checks_for(s: dict) -> Optional[dict]:
    if not s.get("n_windows"):
        return None
    gap = (s["median_strategy_mdd"] - s["median_base_mdd"]) if "median_strategy_mdd" in s else None
    return {"win_share": s["share_win"] >= WIN_SHARE_MIN, "median_irr": s["median_diff_irr"] >= MEDIAN_IRR_MIN,
            "p10_irr": s["p10_diff_irr"] >= P10_IRR_MIN, "mdd": (gap >= -MDD_TOL) if gap is not None else None}


# =================================================================================================
# 바닥 신호 진단
# =================================================================================================

def diag_sets(days: pd.DatetimeIndex, h: int) -> dict[str, np.ndarray]:
    """신호일 d 의 집합(앞으로 h 행 + 1 이 같은 반쪽 안에 끝나야 한다)."""
    n = len(days)
    pos = np.arange(n)
    ok = pos + 1 + h < n
    end_day = days[np.minimum(pos + 1 + h, n - 1)]
    sel = ok & (days >= pd.Timestamp(L.SEL_FIRST_START)) & (end_day <= pd.Timestamp(L.SEL_END_CUTOFF))
    conf = ok & (days >= pd.Timestamp(L.CONF_FIRST_START)) & (end_day <= pd.Timestamp(L.CONF_END_CUTOFF))
    post = ok & (days >= pd.Timestamp("2008-01-01"))
    return {"selection": np.flatnonzero(sel), "confirmation": np.flatnonzero(conf), "post2008": np.flatnonzero(post)}


def block_boot_excess(fwd: np.ndarray, on: np.ndarray, block: int, n_boot: int, rng) -> tuple[float, float, float]:
    """초과 = 신호일 평균 앞 수익 − 전체 평균. 원형 블록 부트스트랩(블록 = 앞 기간)으로 분포 → 단측 p(초과 ≤ 0 비율)."""
    n = len(fwd)
    if on.sum() < 2:
        return float("nan"), float("nan"), float("nan")
    obs = float(fwd[on].mean() - fwd.mean())
    nb = max(1, int(math.ceil(n / block)))
    stats = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, nb)
        idx = ((starts[:, None] + np.arange(block)[None, :]) % n).ravel()[:n]
        f, o = fwd[idx], on[idx]
        stats[b] = f[o].mean() - f.mean() if o.sum() >= 2 else np.nan
    stats = stats[np.isfinite(stats)]
    p = float(np.mean(stats <= 0)) if len(stats) else float("nan")
    return obs, p, float(np.mean(on))


def diagnostic(price: pd.Series, flags: pd.DataFrame, smoke: bool) -> dict:
    days = price.index
    lp = np.log(price.to_numpy())
    rng = np.random.default_rng(20261022)
    n_boot = 40 if smoke else DIAG_BOOT
    out: dict[str, Any] = {}
    alpha = DIAG_ALPHA / len(SIGNALS)
    for sig in SIGNALS:
        col = "LOWVAL_ONLY_VALID" if sig == "LOWVAL" else sig
        f = flags[col].to_numpy()
        cell = {}
        for hn, h in FWD_ROWS.items():
            sets = diag_sets(days, h)
            for sn, idx in sets.items():
                fwd = lp[idx + 1 + h] - lp[idx + 1]
                on = f[idx]
                ex, p, share = block_boot_excess(fwd, on, h, n_boot, rng)
                cell[f"{hn}|{sn}"] = {"excess_log": ex, "excess_ann": (math.exp(ex / (h / 252)) - 1) if L.fin(ex) else None,
                                      "p_one_sided": p, "share_days_on": share, "n_days": int(len(idx)), "n_on": int(on.sum()),
                                      "mean_fwd_on_ann": (math.exp(fwd[on].mean() / (h / 252)) - 1) if on.sum() else None,
                                      "mean_fwd_all_ann": math.exp(fwd.mean() / (h / 252)) - 1}
        ok = all(L.fin(cell[f"{PRIMARY_FWD}|{s}"]["excess_log"]) and cell[f"{PRIMARY_FWD}|{s}"]["excess_log"] > 0
                 and L.fin(cell[f"{PRIMARY_FWD}|{s}"]["p_one_sided"]) and cell[f"{PRIMARY_FWD}|{s}"]["p_one_sided"] < alpha
                 for s in JUDGED_SETS)
        out[sig] = {"cells": cell, "verdict": USEFUL if ok else NOT_USEFUL}
    out["alpha_each"] = alpha
    return out


# =================================================================================================
# ETF 시대 실제 SPY (보고만) — 원화·실제 환율·수수료
# =================================================================================================

def etf_part(smoke: bool) -> dict:
    ssb = L._load_mod("_dca_ssb", "research/jobs/spy-sector-blend-v1/run.py")
    inp = ssb.synthetic_etf() if smoke else ssb.load_etf_real()
    adj = inp["adj"]["SPY"].dropna()
    bil = inp["adj"]["BIL"].reindex(adj.index).ffill()
    bil_r = bil.pct_change().fillna(0.0)          # BIL 상장 전 0
    cg = np.cumprod(1 + bil_r.to_numpy() * (1 - L.INTEREST_TAX))
    fx = inp["fx"].reindex(adj.index).ffill().bfill().to_numpy()
    days = adj.index
    flags = signal_flags(adj)
    dep = deploy_rows(flags)
    px = adj.to_numpy()
    first = "2012-01-01" if smoke else ETF_FIRST_START
    judged_end = "2016-06-30" if smoke else ETF_JUDGED_END
    out = {}
    for hz in ((2,) if smoke else (10,)):
        wins = L.re_.rolling_windows(days, hz, step="A" if smoke else "M", first_start=first)
        res = []
        for s, e in wins:
            if e > pd.Timestamp(judged_end):
                continue
            rows = L.contribution_rows(days, s, e)
            end_row = days.searchsorted(e, side="right") - 1
            amounts = np.full(len(rows), float(MONTHLY_KRW))
            r_all = {}
            for arm in (BASE,) + ARMS:
                r_, mult, d_ = arm_plan(arm, rows, dep, 0)
                am = (np.concatenate([amounts, amounts]) if arm == "HALF_DD20" else amounts) * mult
                d_ = np.minimum(d_, end_row + 1)
                bought = d_ <= end_row
                dc = np.minimum(d_, end_row)
                cash_mult = cg[dc] / cg[r_]
                usd = am * cash_mult / (fx[dc] * (1 + L.FX_SPREAD))
                units = np.where(bought, usd * (1 - L.FEE) / px[dc], 0.0)
                cost = float(np.sum(np.where(bought, am * cash_mult, 0.0)))
                eq = float(units.sum() * px[end_row] * fx[end_row] * (1 - L.FX_SPREAD))
                cash_left = float(np.sum(np.where(bought, 0.0, am * cg[end_row] / cg[r_])))
                term = L.liquidation_value(eq, cost) + cash_left
                r_all[arm] = {"irr": L.xirr_monthly(amounts, rows, end_row, term, days), "terminal": term, "mdd": None,
                              "invested_share": float(am[bought].sum() / am.sum())}
            res.append(((s, e), r_all))
        out[f"{hz}y"] = {arm: L.summarize_pairs(pair_rows(res, arm)) for arm in ARMS}
    out["source"] = inp.get("source")
    return out


# =================================================================================================
# 실행
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
    dl_epoch = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    t0 = time.time()

    def log(s):
        print(s, flush=True)

    def check_time():
        if dl_epoch is not None and time.time() > dl_epoch - DEADLINE_MARGIN:
            raise _Stop()

    def stage(name, fn):
        path = ck / f"{name}.pkl"
        got = _load_ckpt(path, fp)
        if got is None:
            check_time()
            got = fn()
            _atomic_pickle(path, {"fingerprint": fp, "payload": got})
            log(f"단계 저장: {name} ({time.time() - t0:.0f}초)")
        return got

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        data = stage("inputs", lambda: L.load_long_synthetic() if a.smoke else L.load_long_real())
        mkt = data["mkt"].dropna()
        days = mkt.index
        price = L.level(mkt)
        cg = np.cumprod(1 + data["rf"].reindex(days).fillna(0.0).to_numpy() * (1 - L.INTEREST_TAX))
        flags = signal_flags(price)
        dep = deploy_rows(flags)
        px = price.to_numpy()
        diag = stage("diagnostic", lambda: diagnostic(price, flags, a.smoke))
        all_arms = (BASE,) + ARMS + ("ORACLE",)
        cells: dict[str, dict] = {}
        for hz in HORIZONS:
            sets = L.window_sets(days, hz, a.smoke)
            for scen in SCENARIOS:
                def compute(hz=hz, sets=sets, scen=scen):
                    res = {}
                    for sn, wins in sets.items():
                        rr = []
                        for s, e in wins:
                            rr.append(((s, e), run_window(px, cg, days, dep, s, e, scen, all_arms)))
                            check_time()
                        res[sn] = {arm: L.summarize_pairs(pair_rows(rr, arm)) for arm in ARMS + ("ORACLE",)}
                        res[sn]["_base"] = {"median_irr": float(np.nanmedian([r[1][BASE]["irr"] for r in rr])) if rr else None,
                                            "median_mdd": float(np.nanmedian([r[1][BASE]["mdd"] for r in rr])) if rr else None}
                    return res
                cells[f"{scen}|{hz}y"] = stage(f"cell_{scen}_{hz}y", compute)
        etf = stage("etf", lambda: etf_part(a.smoke))
        result = build_result(cells, diag, etf, flags, price, a.smoke, data.get("source"))
        if a.smoke:
            cov = {"all_cells": len(cells) == len(SCENARIOS) * len(HORIZONS),
                   "judged_sets_nonempty": all(cells[f"{PRIMARY}|{h}y"][s][ARMS[0]].get("n_windows", 0) > 0
                                               for h in HORIZONS for s in JUDGED_SETS),
                   "signals_fire": all(flags[k].any() for k in SIGNALS),
                   "waiting_happens": any(cells[f"{PRIMARY}|10y"]["selection"][k].get("median_invested_share", 1) < 1 for k in ARMS),
                   "oracle_present": cells[f"{PRIMARY}|10y"]["selection"]["ORACLE"].get("n_windows", 0) > 0,
                   "diag_cells": all(len(diag[s]["cells"]) == len(FWD_ROWS) * 3 for s in SIGNALS),
                   "etf_part": bool(etf.get("2y"))}
            result["smoke_coverage"] = cov
            bad = [k for k, v in cov.items() if not v]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
    except _Stop:
        log(f"시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서 ({time.time() - t0:.0f}초)")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text.encode("utf-8")) > SIZE_LIMIT:
        result.pop("etf_SPY", None)
        result["note_size"] = "크기 상한 때문에 ETF 부분을 뺐다(REPORT.md 에는 있다)"
        text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    (out / "results.json").write_text(text, encoding="utf-8")
    (out / "REPORT.md").write_text(render(build_result(cells, diag, etf, flags, price, a.smoke, data.get("source"))), encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    log(f"완료 ({time.time() - t0:.0f}초)")
    return 0


# =================================================================================================
# 결과·보고서
# =================================================================================================

def _r(x, nd=4):
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return round(x, nd) if math.isfinite(x) else None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    return x


def build_result(cells, diag, etf, flags, price, smoke, source) -> dict:
    verdicts: dict[str, Any] = {}
    checks: dict[str, dict] = {}
    for arm in ARMS:
        ch = {f"{s}|{h}y": checks_for(cells[f"{PRIMARY}|{h}y"][s][arm]) for h in HORIZONS for s in JUDGED_SETS}
        checks[arm] = ch
        ok = all(c is not None and all(v is True for v in c.values()) for c in ch.values())
        verdicts[arm] = (f"SMOKE_ONLY({PASS if ok else FAIL})" if smoke else (PASS if ok else FAIL))
    verdicts["passed"] = f"{sum(PASS in v for k, v in verdicts.items() if k in ARMS and 'SMOKE' not in v)}/{N_TRIALS}"
    verdicts["bottom_signals"] = ", ".join(f"{s}={diag[s]['verdict']}" for s in SIGNALS)
    verdicts["scenario"] = f"M: {MONTHLY_KRW:,} KRW/month, never sell, after liquidation tax, 1927-2007 halves, 10y+20y"
    last = {k: bool(flags[k].iloc[-1]) for k in SIGNALS}
    dd_now = float(L.drawdown(price).iloc[-1])
    return _r({"judge_version": RULES_VERSION, "smoke": smoke, "source": source,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "verdicts": verdicts, "checks": checks, "diagnostic": diag, "cells": cells, "etf_SPY": etf,
               "signals_on_last_day": last, "market_drawdown_last_day": dd_now, "last_day": str(price.index[-1].date()),
               "rule": {"monthly_krw": MONTHLY_KRW, "scenarios": {k: {"initial_krw": v[0], "monthly_krw": v[1]} for k, v in SCENARIOS.items()},
                        "horizons": list(HORIZONS), "sets": {"selection": f"{L.SEL_FIRST_START}..end<={L.SEL_END_CUTOFF}",
                                                              "confirmation": f"{L.CONF_FIRST_START}..end<={L.CONF_END_CUTOFF}",
                                                              "post2008": f"end>={L.POST_FIRST_END} (report)"},
                        "thresholds": {"win_share_min": WIN_SHARE_MIN, "median_irr_min": MEDIAN_IRR_MIN,
                                       "p10_irr_min": P10_IRR_MIN, "mdd_tol": MDD_TOL},
                        "diag": {"primary_fwd": PRIMARY_FWD, "alpha_each": diag["alpha_each"], "boot": DIAG_BOOT},
                        "account": "buy-only, fee 0.1% + FX 0.05%, cash at RF after 15.4% interest tax, liquidation CGT 22% over 2.5M KRW, FX fixed 1300",
                        "labels": LABELS}})


def _p(x, signed=False, nd=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _yn(v):
    return "—" if v is None else ("통과" if v else "미달")


def render(r: dict) -> str:
    v = r["verdicts"]
    smoke = r["smoke"]
    Lines = [f"# 팔지 않는 적립 — 바닥까지 기다렸다 살까, 바로 살까 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
             f"매달 {MONTHLY_KRW // 10000}만 원을 넣고 절대 팔지 않는 계좌에서, 새 돈을 '바닥 신호'가 켜질 때까지 현금으로 기다렸다가 넣는 것이 "
             "들어오는 날 바로 넣는 것(DCA)보다 세후로 많이 남기는지 1927~2024 미국 시장 전체로 본다. "
             "그리고 그 바닥 신호 자체가 앞으로의 수익을 예측하는지 따로 잰다.", "",
             f"**적립 타이밍 판정: 통과 {v['passed']}** — " + " · ".join(f"{LABELS[a]} **{v[a]}**" for a in ARMS), "",
             f"**바닥 신호 진단(3년 앞 수익, 두 반쪽 모두):** {v['bottom_signals']}", "",
             "통과는 엔진 반영이 아니다. 엔진은 바뀌지 않았다.", "",
             "## 규칙 (결과를 보기 전에 고정)", "",
             "- 계좌: 매달 첫 거래일 10만 원 입금, 절대 팔지 않음, 기다리는 돈은 무위험 이자(이자소득세 15.4% 뺌), "
             "구간 끝에 모두 판다고 보고 양도세 22%(250만 원 공제). 매수 수수료 0.1% + 환전 0.05%, 환율 1,300 원 고정.",
             "- 신호는 그날 종가로 정하고 다음 거래일 종가에 산다. 신호가 켜져 있는 동안 들어온 돈은 바로 산다.",
             "- 구간: 매달 시작하는 10년·20년. 선택 반쪽(1927-07 시작 ~ 끝 ≤ 1966), 확인 반쪽(1967 시작 ~ 끝 ≤ 2007). 2008 이후 끝나는 구간은 보고만.",
             f"- 통과(BEATS_DCA): 두 반쪽 × 두 길이 모두에서 ① 바로 넣기보다 많이 남은 구간 ≥ {WIN_SHARE_MIN:.0%} "
             f"② 세후 IRR 차이 중앙값 ≥ +{MEDIAN_IRR_MIN * 100:.1f}%p ③ 10분위 ≥ {P10_IRR_MIN * 100:.1f}%p "
             f"④ 계좌 최대낙폭 중앙값이 {MDD_TOL * 100:.0f}%p 넘게 나쁘지 않음.",
             f"- 바닥 신호 진단: 신호가 켜진 날 다음 날 산 시장의 3년 앞 로그 수익 평균 − 모든 날 평균 > 0 이고, "
             f"블록 부트스트랩(블록 = 3년) 단측 p < {r['rule']['diag']['alpha_each']:.4f}(0.05 ÷ 신호 6개) 이 선택·확인 두 반쪽 모두에서 성립하면 USEFUL_SIGNAL.", ""]
    # 진단표
    Lines += ["## 1) 바닥 신호가 앞으로의 수익을 예측하나", "",
              "연 환산 앞 수익: 신호가 켜진 날 산 것 vs 아무 날이나 산 것. 켜진 날 비율 = 그 반쪽에서 신호가 켜져 있던 날의 비율.", "",
              "| 신호 | 반쪽 | 켜진 날 비율 | 1년 앞 (전체) | 3년 앞 (전체) | 3년 초과 p | 5년 앞 (전체) | 판정 |", "|---|---|---|---|---|---|---|---|"]
    for s in SIGNALS:
        c = r["diagnostic"][s]["cells"]
        for sn in ("selection", "confirmation", "post2008"):
            def cc(h):
                x = c.get(f"{h}|{sn}", {})
                return f"{_p(x.get('mean_fwd_on_ann'))} ({_p(x.get('mean_fwd_all_ann'))})"
            x3 = c.get(f"3y|{sn}", {})
            Lines.append(f"| {LABELS[s]} | {sn} | {_p(x3.get('share_days_on'), nd=0)} | {cc('1y')} | {cc('3y')} | "
                         f"{x3.get('p_one_sided') if x3.get('p_one_sided') is not None else '—'} | {cc('5y')} | "
                         f"{r['diagnostic'][s]['verdict'] if sn == 'confirmation' else ''} |")
    # 타이밍 판정표
    Lines += ["", "## 2) 기다렸다 넣기 대 바로 넣기 — 시나리오 M(월 10만 원만), 세후", ""]
    for h in HORIZONS:
        for sn in ("selection", "confirmation", "post2008"):
            cell = r["cells"][f"M|{h}y"][sn]
            Lines += [f"### {h}년 구간 — {sn}{' (보고만)' if sn == 'post2008' else ''}", "",
                      f"바로 넣기 세후 IRR 중앙값 {_p(cell['_base']['median_irr'], nd=2)}, 계좌 최대낙폭 중앙값 {_p(cell['_base']['median_mdd'])}", "",
                      "| 방식 | 구간 | 이긴 비율 | IRR 차이 중앙값 / 10분위 | 남은 돈 비율 중앙값 | 실제로 산 비율 중앙값 | 최대낙폭 중앙값 (기준) | ①②③④ |",
                      "|---|---|---|---|---|---|---|---|"]
            for arm in ARMS + ("ORACLE",):
                s = cell[arm]
                if not s.get("n_windows"):
                    continue
                ch = r["checks"].get(arm, {}).get(f"{sn}|{h}y") if arm != "ORACLE" else None
                chs = "".join(_yn(x)[0] for x in ch.values()) if ch else "—"
                Lines.append(f"| {LABELS[arm]} | {s['n_windows']} | {_p(s['share_win'], nd=0)} | {_p(s['median_diff_irr'], True, 2)}p / "
                             f"{_p(s['p10_diff_irr'], True, 2)}p | {s['median_terminal_ratio']:.3f} | {_p(s.get('median_invested_share'), nd=0)} | "
                             f"{_p(s.get('median_strategy_mdd'))} ({_p(s.get('median_base_mdd'))}) | {chs} |")
            Lines.append("")
    Lines += ["## 보고 — 이미 1,000만 원 보유 + 월 10만 원 타이밍(시나리오 H)", "",
              "| 방식 | 길이 | 반쪽 | 이긴 비율 | IRR 차이 중앙값 |", "|---|---|---|---|---|"]
    for h in HORIZONS:
        for sn in JUDGED_SETS:
            for arm in ARMS:
                s = r["cells"][f"H|{h}y"][sn][arm]
                if s.get("n_windows"):
                    Lines.append(f"| {LABELS[arm]} | {h}년 | {sn} | {_p(s['share_win'], nd=0)} | {_p(s['median_diff_irr'], True, 2)}p |")
    etf = r.get("etf_SPY") or {}
    for hk, tbl in etf.items():
        if not isinstance(tbl, dict) or hk == "source":
            continue
        Lines += ["", f"## 보고 — 실제 SPY, 원화·실제 환율, 2000 년부터 매달 시작하는 {hk} 구간(끝 ≤ 2024-09)", "",
                  "| 방식 | 구간 | 이긴 비율 | IRR 차이 중앙값 / 10분위 | 실제로 산 비율 중앙값 |", "|---|---|---|---|---|"]
        for arm in ARMS:
            s = tbl.get(arm, {})
            if s.get("n_windows"):
                Lines.append(f"| {LABELS[arm]} | {s['n_windows']} | {_p(s['share_win'], nd=0)} | {_p(s['median_diff_irr'], True, 2)}p / "
                             f"{_p(s['p10_diff_irr'], True, 2)}p | {_p(s.get('median_invested_share'), nd=0)} |")
    Lines += ["", f"## 지금 신호 ({r['last_day']}, 자료 마지막 날)", "",
              f"시장 고점 대비 {_p(r['market_drawdown_last_day'])}. 켜진 신호: " +
              (", ".join(LABELS[k] for k, on in r["signals_on_last_day"].items() if on) or "없음"), "",
              "## 주의", "",
              "- 구간이 크게 겹친다. 1927~2007 두 반쪽에서 독립적인 20년은 반쪽마다 2개 남짓이다.",
              "- 시장 = Ken French 미국 전체 주식(시가총액 가중, 배당 포함). SPY 와 거의 같지만 같지는 않다. 배당 원천징수 15% 는 넣지 않았다 "
              "(현금으로 기다리는 팔은 그동안 이자에 15.4% 를 냈으므로 기다리는 쪽에 약간 불리하지 않게 한 근사).",
              "- '신의 손'은 사후 정보로 다음 1년 안 최저가에 산다고 친 상한이다. 실제로는 불가능하다 — 바닥 잡기로 얻을 수 있는 최대치를 보여 줄 뿐이다.",
              "- 환율은 긴 역사에서 1,300 원 고정. 세금은 근사이며 신고용이 아니다. 투자 조언이 아니다."]
    if smoke:
        Lines += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(Lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
