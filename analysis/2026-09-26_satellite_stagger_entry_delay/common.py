"""공통 유틸 — 기존 core.champion_strategy 함수를 최소 래핑만 한다(새 방법론 없음).

- 월별 point-in-time 선정 결과(_pick_satellite_at_date)를 picks_part*.json 에 체크포인트(재시작 시 이어서).
- 변형별 비중표·수익률, SPY 수익률, 짝지은 블록 부트스트랩.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from core.champion_strategy import (  # noqa: E402
    _pick_satellite_at_date, _compute_portfolio_returns, _closes_from_histories,
    SATELLITE_COST_BPS_PER_SIDE, SATELLITE_BACKTEST_TOP_K, SATELLITE_BACKTEST_WARMUP_DAYS,
)
from core.market_data import get_multiple_price_history, get_price_history  # noqa: E402

W_START, W_END = "2008-07-01", "2026-06-30"
PICK_FROM = "2008-01-01"
VARIANTS = [(1, 7), (2, 8), (3, 9), (4, 10), (5, 11), (6, 12)]
BASE = (1, 7)
SEED = 20260926
N_BOOT = 2000
BLOCK = 63
TD = 252


def vkey(v):
    return f"{v[0]}_{v[1]}"


def spy_close() -> pd.Series:
    df = get_price_history("SPY", start="2005-01-01", end="2026-09-01")
    return df["Close"]


def trading_index() -> pd.DatetimeIndex:
    return spy_close().index


def month_first_days(idx: pd.DatetimeIndex, start=PICK_FROM, end=W_END) -> list[pd.Timestamp]:
    sub = idx[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))]
    per = pd.Series(sub.to_period("M"), index=sub)
    return sub[per.ne(per.shift(1)).values].tolist()


def load_picks() -> dict:
    out = {}
    for f in sorted(HERE.glob("picks_part*.json")):
        out.update(json.loads(f.read_text(encoding="utf-8")))
    return out


def variant_dates(idx, v) -> list[pd.Timestamp]:
    return [d for d in month_first_days(idx) if d.month in v]


def build_weights(idx_w: pd.DatetimeIndex, schedule: list[tuple[pd.Timestamp, dict]], cols: list[str]) -> pd.DataFrame:
    """schedule: [(설정일, {ticker: w})] 오름차순. 설정일부터 다음 설정일 전까지 ffill.
    W 시작 이전 설정은 W 첫날 비중으로 이어짐."""
    w = pd.DataFrame(np.nan, index=idx_w, columns=cols)
    first = pd.Series(0.0, index=cols)
    for d, m in schedule:
        row = pd.Series(0.0, index=cols)
        for t, x in m.items():
            if t in row.index:
                row[t] = x
        if d < idx_w[0]:
            first = row
        elif d in w.index:
            w.loc[d] = row.values
    if pd.isna(w.iloc[0]).all():
        w.iloc[0] = first.values
    return w.ffill().fillna(0.0)


_close_cache: dict = {}


def closes_for(tickers: list[str], idx_w: pd.DatetimeIndex) -> pd.DataFrame:
    need = [t for t in tickers if t not in _close_cache]
    if need:
        fs = (pd.Timestamp(PICK_FROM) - pd.DateOffset(days=SATELLITE_BACKTEST_WARMUP_DAYS)).date().isoformat()
        hist = get_multiple_price_history(need, start=fs, end="2026-09-01", interval="1d")
        for t in need:
            df = hist.get(t)
            _close_cache[t] = df["Close"] if df is not None and not df.empty else pd.Series(dtype=float)
    c = pd.DataFrame({t: _close_cache[t] for t in tickers})
    # 원 백테스트와 같은 처리: 공통 거래일로 reindex 후 ffill
    return c.reindex(idx_w).ffill()


def returns_from_weights(weights: pd.DataFrame) -> pd.Series:
    closes = closes_for(list(weights.columns), weights.index)
    return _compute_portfolio_returns(closes, weights, cost_bps_per_side=SATELLITE_COST_BPS_PER_SIDE)["ret_net"]


def metrics(ret: pd.Series) -> dict:
    r = ret.fillna(0.0).values
    eq = np.cumprod(1 + r)
    years = len(r) / TD
    cagr = (eq[-1] ** (1 / years) - 1) * 100
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    mdd = float(((eq / peak) - 1).min() * 100)
    sd = r.std(ddof=0)
    sharpe = float(r.mean() / sd * np.sqrt(TD)) if sd > 0 else 0.0
    return {"cagr": round(float(cagr), 3), "sharpe": round(sharpe, 4), "mdd": round(mdd, 3), "n_days": int(len(r))}


def sharpe_arr(x: np.ndarray) -> np.ndarray:
    sd = x.std(axis=-1)
    return np.where(sd > 0, x.mean(axis=-1) / sd * np.sqrt(TD), 0.0)


def paired_block_boot_sharpe_diff(a: np.ndarray, b: np.ndarray, rng, n_boot=N_BOOT, block=BLOCK) -> np.ndarray:
    """원형 이동블록 부트스트랩, 두 계열에 같은 블록 위치 → sharpe(a) − sharpe(b) 분포."""
    n = len(a)
    nb = int(np.ceil(n / block))
    ea, eb = np.concatenate([a, a]), np.concatenate([b, b])
    offs = np.arange(block)
    out = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n, size=nb)
        ix = (starts[:, None] + offs[None, :]).ravel()[:n]
        out[i] = sharpe_arr(ea[ix]) - sharpe_arr(eb[ix])
    return out


def ci(x: np.ndarray) -> list[float]:
    return [round(float(np.percentile(x, 2.5)), 4), round(float(np.percentile(x, 97.5)), 4)]


def mean_boot_ci(vals: np.ndarray, rng, n_boot=N_BOOT) -> dict:
    n = len(vals)
    ix = rng.integers(0, n, size=(n_boot, n))
    bm = vals[ix].mean(axis=1)
    return {"mean": round(float(vals.mean()), 4), "ci95": ci(bm), "n": int(n)}
