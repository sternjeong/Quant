"""공통 유틸 — 새틀라이트 선정 약점 3종 검증(PREREGISTRATION.md).

기존 core 함수를 최소 래핑만 한다(새 방법론 없음). `analysis/2026-09-26_satellite_stagger_entry_delay/common.py`
의 래핑 방식을 그대로 가져와 (a) 후보 풀 스캔에 섹터·RSI 를 더하고, (b) 변형별 비중표 생성을 추가했다.

여기의 상수·정의는 PREREGISTRATION.md 에 적힌 것과 같아야 한다. 결과를 본 뒤 바꾸지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core.backtest_engine import calculate_metrics  # noqa: E402
from core.champion_strategy import (  # noqa: E402
    CORE_UNIVERSE,
    MARKET_FILTER_TICKER,
    SATELLITE_BACKTEST_MOMENTUM_WINDOW,
    SATELLITE_BACKTEST_POOL_N,
    SATELLITE_BACKTEST_TOP_K,
    SATELLITE_BACKTEST_WARMUP_DAYS,
    SATELLITE_COST_BPS_PER_SIDE,
    SATELLITE_DONCHIAN_WINDOW,
    _compute_portfolio_returns,
    _pick_satellite_at_date,
    _semiannual_rebal_dates,
    donchian_trailing_stop_positions,
)
from core.indicators import compute_rsi  # noqa: E402
from core.market_data import get_multiple_price_history, get_price_history  # noqa: E402
from core.strategy_tuning import sample_universe  # noqa: E402

# ------------------------------------------------------------------ 사전 등록 상수
W_START, W_END = "2008-07-01", "2026-06-30"   # 평가 구간(반기 36개)
HOLDOUT_MONTH_START = "2026-07-01"            # 홀드아웃 선정일이 속한 달(판정에 쓰지 않음)
PRICE_START = "2005-07-01"                    # 첫 선정일 − 730일보다 여유있게
SEED = 20260928
N_BOOT = 2000
BLOCK = 63                                    # 보조(탐색) 블록 부트스트랩 블록 길이
TD = 252

RSI_PERIOD = 14
RSI_PRIMARY_THRESHOLD = 70.0                  # H7 주검정
RSI_SECONDARY_THRESHOLD = 80.0                # H7 보조(탐색)
SECTOR_CAP_PRIMARY = 1                        # H6 주검정
SECTOR_CAP_SECONDARY = 2                      # H6 보조(탐색)

# 변형 정의 — 키가 results.json 에 그대로 쓰인다.
VARIANT_SPECS: dict[str, dict] = {
    "baseline": {},
    "h6_sector_cap1": {"sector_cap": SECTOR_CAP_PRIMARY},
    "h6_sector_cap2": {"sector_cap": SECTOR_CAP_SECONDARY},
    "h6_sector_cap1_cashpad": {"sector_cap": SECTOR_CAP_PRIMARY, "cash_pad": True},
    "h7_rsi70_excl": {"rsi_max": RSI_PRIMARY_THRESHOLD},
    "h7_rsi80_excl": {"rsi_max": RSI_SECONDARY_THRESHOLD},
    "h8_trend_exit": {"trend_exit": True},
}
BASELINE = "baseline"
# 판정 대상(주검정) — 가설 이름 -> 변형 키. 본페로니 보정의 가설 수가 이 크기다.
PRIMARY_VARIANTS: dict[str, str] = {
    "H6_sector_cap": "h6_sector_cap1",
    "H7_overheat_exclusion": "h7_rsi70_excl",
    "H8_trend_exit": "h8_trend_exit",
}
SECONDARY_VARIANTS = ["h6_sector_cap2", "h6_sector_cap1_cashpad", "h7_rsi80_excl"]


# ------------------------------------------------------------------ 가격
_PRICE_CACHE: dict[str, pd.Series] = {}
_PRICE_FAILURES: dict[str, int] = {}


def price_failures() -> dict[str, int]:
    return dict(_PRICE_FAILURES)


def reset_price_cache() -> None:
    _PRICE_CACHE.clear()
    _PRICE_FAILURES.clear()


def _store(ticker: str, df) -> pd.Series:
    if df is None or getattr(df, "empty", True) or "Close" not in df:
        _PRICE_CACHE[ticker] = pd.Series(dtype=float)
        _PRICE_FAILURES[ticker] = _PRICE_FAILURES.get(ticker, 0) + 1
    else:
        s = df["Close"].dropna()
        _PRICE_CACHE[ticker] = s
        if s.empty:
            _PRICE_FAILURES[ticker] = _PRICE_FAILURES.get(ticker, 0) + 1
    return _PRICE_CACHE[ticker]


def prefetch_prices(tickers: list[str]) -> None:
    """캐시에 없는 종목만 한 번에(병렬) 받아 모듈 캐시에 담는다. 이미 받은 것은 다시 받지 않는다."""
    need = [t for t in dict.fromkeys(tickers) if t not in _PRICE_CACHE]
    if not need:
        return
    hist = get_multiple_price_history(need, start=PRICE_START, end=None, interval="1d")
    for t in need:
        _store(t, (hist or {}).get(t))


def price_series(ticker: str) -> pd.Series:
    """종목의 조정 전 종가 전체 계열(캐시). 실패하면 빈 계열을 돌려주고 실패로 기록한다."""
    if ticker in _PRICE_CACHE:
        return _PRICE_CACHE[ticker]
    try:
        df = get_price_history(ticker, start=PRICE_START, end=None, interval="1d")
    except Exception:  # noqa: BLE001 — 실패는 조용히 넘기지 않고 기록한다
        df = None
    return _store(ticker, df)


def spy_close() -> pd.Series:
    return price_series(MARKET_FILTER_TICKER)


# ------------------------------------------------------------------ 일정
def pick_dates_in_window(idx: pd.DatetimeIndex, start: str = W_START, end: str = W_END) -> list[pd.Timestamp]:
    """1·7월 첫 거래일(라이브 엔진과 같은 `_semiannual_rebal_dates`)."""
    return _semiannual_rebal_dates(idx, start, end)


def period_ends(idx: pd.DatetimeIndex, picks: list[pd.Timestamp], window_end: pd.Timestamp) -> list[pd.Timestamp]:
    """반기 h 의 마지막 거래일 = 다음 선정일 직전 거래일(마지막 반기는 구간 끝)."""
    ends = []
    for i, d in enumerate(picks):
        if i + 1 < len(picks):
            prior = idx[idx < picks[i + 1]]
            ends.append(prior[-1])
        else:
            within = idx[(idx >= d) & (idx <= window_end)]
            ends.append(within[-1] if len(within) else d)
    return ends


# ------------------------------------------------------------------ 후보 풀 스캔(가장 무거운 단계)
def scan_pool(pick_date: pd.Timestamp, pool_n: int = SATELLITE_BACKTEST_POOL_N) -> dict:
    """선정일의 point-in-time 후보 풀을 훑어 변형 계산에 필요한 모든 것을 한 번에 모은다.

    `_pick_satellite_at_date` 와 **같은** 정의(같은 풀, 같은 이력 구간, 같은 돈치안·모멘텀 식)를 쓰고,
    거기에 섹터(GICS)와 RSI(14)를 덧붙인다. 되돌아가 다시 계산하지 않도록 이 결과를 반기 단위로 체크포인트한다.
    """
    as_of = pd.Timestamp(pick_date).date().isoformat()
    pool = sample_universe(n=pool_n, as_of_date=as_of, use_point_in_time_market_cap=True, use_cache=True)
    candidates = [t for t in pool["ticker"].tolist() if t not in CORE_UNIVERSE and t != MARKET_FILTER_TICKER]
    sectors = {}
    for row in pool.itertuples():
        sec = getattr(row, "sector", None)
        sectors[row.ticker] = sec if isinstance(sec, str) and sec else "Unknown"

    prefetch_prices(candidates)
    fetch_start = pd.Timestamp(pick_date) - pd.DateOffset(days=SATELLITE_BACKTEST_WARMUP_DAYS)

    active: dict[str, tuple[float, float | None]] = {}
    missing: list[str] = []
    rejected: list[str] = []
    rsi_nan: list[str] = []
    n_with_history = 0
    for t in candidates:
        full = price_series(t)
        close = full[(full.index >= fetch_start) & (full.index < pd.Timestamp(pick_date))]
        if len(close) == 0:
            missing.append(t)
            continue
        n_with_history += 1
        if len(close) < SATELLITE_DONCHIAN_WINDOW + 60:
            missing.append(t)
            continue
        pos = donchian_trailing_stop_positions(close)
        if pos.iloc[-1] != 1:
            rejected.append(t)
            continue
        if len(close) >= SATELLITE_BACKTEST_MOMENTUM_WINDOW + 5:
            mom = close.iloc[-1] / close.iloc[-1 - SATELLITE_BACKTEST_MOMENTUM_WINDOW] - 1.0
        else:
            mom = close.iloc[-1] / close.iloc[0] - 1.0
        if pd.isna(mom):
            missing.append(t)
            continue
        rsi = compute_rsi(pd.DataFrame({"Close": close}), period=RSI_PERIOD)
        rsi_v = float(rsi.iloc[-1]) if len(rsi) and pd.notna(rsi.iloc[-1]) else None
        if rsi_v is None:
            rsi_nan.append(t)
        active[t] = (float(mom), rsi_v)

    # `_pick_satellite_at_date` 와 같은 정렬(후보 순서 안정 정렬, 모멘텀 내림차순)
    ranked = sorted(active.items(), key=lambda kv: kv[1][0], reverse=True)
    return {
        "date": as_of,
        "pool_size": len(candidates),
        "n_with_history": n_with_history,
        "n_active_trend": len(active),
        "sectors": {t: sectors.get(t, "Unknown") for t in candidates},
        "ranked_active": [[t, mom, rsi] for t, (mom, rsi) in ranked],
        "rejected_tickers": rejected,
        "missing_tickers": missing,
        "rsi_nan_active": rsi_nan,
    }


def verify_baseline_picks(pick_date: pd.Timestamp, scan: dict) -> dict:
    """기준 재현 관문 — 자체 스캔의 기준 선정이 라이브 엔진 `_pick_satellite_at_date` 와 같은지 확인."""
    ref = _pick_satellite_at_date(pd.Timestamp(pick_date))
    mine, _ = picks_for_variant(scan, VARIANT_SPECS[BASELINE])
    return {
        "date": pd.Timestamp(pick_date).date().isoformat(),
        "engine_picks": list(ref["picks"]),
        "scan_picks": list(mine),
        "picks_match": list(ref["picks"]) == list(mine),
        "pool_size_match": int(ref["pool_size"]) == int(scan["pool_size"]),
        "n_with_history_match": int(ref["n_with_history"]) == int(scan["n_with_history"]),
    }


# ------------------------------------------------------------------ 변형별 선정
def picks_for_variant(scan: dict, spec: dict, top_k: int = SATELLITE_BACKTEST_TOP_K) -> tuple[list[str], dict[str, float]]:
    """스캔 결과에서 변형 규칙대로 선정 종목·비중을 만든다(PREREGISTRATION.md H6·H7 정의).

    - `rsi_max`: RSI(14) 가 그 값 이상이면 후보 제외(빈 자리는 다음 순위가 채운다). RSI 가 없으면 제외하지 않는다.
    - `sector_cap`: 같은 GICS 섹터를 cap 개까지만. `Unknown` 은 종목마다 다른 섹터로 취급한다.
    - 비중: 기준과 같은 관례로 선정 종목 수 균등(`1/len(picks)`). `cash_pad` 면 종목당 `1/top_k`(못 채운 칸은 현금).
    """
    sectors = scan.get("sectors", {})
    rsi_max = spec.get("rsi_max")
    cap = spec.get("sector_cap")
    used: dict[str, int] = {}
    picks: list[str] = []
    for entry in scan["ranked_active"]:
        if len(picks) >= top_k:
            break
        ticker, _mom, rsi = entry[0], entry[1], entry[2]
        if rsi_max is not None and rsi is not None and float(rsi) >= float(rsi_max):
            continue
        if cap is not None:
            sec = sectors.get(ticker) or "Unknown"
            key = f"Unknown::{ticker}" if sec == "Unknown" else sec
            if used.get(key, 0) >= cap:
                continue
            used[key] = used.get(key, 0) + 1
        picks.append(ticker)
    if not picks:
        return [], {}
    per = 1.0 / top_k if spec.get("cash_pad") else 1.0 / len(picks)
    return picks, {t: per for t in picks}


def trend_exit_path(ticker: str, pick_date: pd.Timestamp, period_end: pd.Timestamp) -> pd.Series:
    """H8 — 선정 때와 같은 시작점에서 돈치안 신호를 이어 계산하고 1거래일 지연한 계열(비중에 곱할 값).

    t일 비중에는 t−1일 종가로 확정된 신호를 쓴다(선정 관례와 같은 지연). 선정일의 값은 곧 선정 근거 신호다.
    """
    full = price_series(ticker)
    fetch_start = pd.Timestamp(pick_date) - pd.DateOffset(days=SATELLITE_BACKTEST_WARMUP_DAYS)
    close = full[(full.index >= fetch_start) & (full.index <= pd.Timestamp(period_end))]
    if len(close) == 0:
        return pd.Series(dtype=float)
    pos = donchian_trailing_stop_positions(close)
    return pos.shift(1)


def variant_weights(
    scans: dict[str, dict],
    picks: list[pd.Timestamp],
    ends: list[pd.Timestamp],
    spec: dict,
    idx: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, list[dict]]:
    """변형의 일별 목표비중표와 반기별 기록(선정 종목·청산 이벤트)을 만든다."""
    per_period: list[tuple[pd.Timestamp, pd.Timestamp, list[str], dict[str, float]]] = []
    cols: set[str] = set()
    for d, e in zip(picks, ends):
        p, w = picks_for_variant(scans[pd.Timestamp(d).date().isoformat()], spec)
        per_period.append((d, e, p, w))
        cols.update(p)
    columns = sorted(cols)
    weights = pd.DataFrame(0.0, index=idx, columns=columns)
    log: list[dict] = []
    for d, e, p, w in per_period:
        dates = idx[(idx >= d) & (idx <= e)]
        rec = {"pick_date": pd.Timestamp(d).date().isoformat(), "period_end": pd.Timestamp(e).date().isoformat(),
               "picks": list(p), "n_picks": len(p), "exits": []}
        if len(dates) == 0 or not p:
            log.append(rec)
            continue
        for t, wt in w.items():
            if spec.get("trend_exit"):
                lagged = trend_exit_path(t, d, e).reindex(dates)
                rec.setdefault("signal_at_pick", {})[t] = None if pd.isna(lagged.iloc[0]) else int(lagged.iloc[0])
                still = lagged.fillna(0.0).astype(int).cumprod()
                weights.loc[dates, t] = still.values * wt
                off = still[still == 0]
                if len(off):
                    rec["exits"].append({"ticker": t, "exit_weight_date": off.index[0].date().isoformat()})
            else:
                weights.loc[dates, t] = wt
        log.append(rec)
    return weights, log


# ------------------------------------------------------------------ 수익률·지표
def closes_frame(tickers: list[str], idx: pd.DatetimeIndex) -> pd.DataFrame:
    """`_closes_from_histories` 와 같은 관례: 공통 거래일로 reindex 후 ffill."""
    prefetch_prices(tickers)
    data = {t: price_series(t) for t in tickers}
    frame = pd.DataFrame({t: s for t, s in data.items() if not s.empty}, index=None)
    for t in tickers:
        if t not in frame.columns:
            frame[t] = np.nan
    return frame[tickers].reindex(idx).ffill()


def returns_from_weights(weights: pd.DataFrame) -> pd.Series:
    if weights.shape[1] == 0:
        return pd.Series(0.0, index=weights.index)
    closes = closes_frame(list(weights.columns), weights.index)
    return _compute_portfolio_returns(closes, weights, cost_bps_per_side=SATELLITE_COST_BPS_PER_SIDE)["ret_net"]


def metrics_of(ret: pd.Series) -> dict:
    r = ret.fillna(0.0)
    if len(r) < 2:
        return {"cagr": 0.0, "sharpe": 0.0, "mdd": 0.0, "n_days": int(len(r))}
    equity = (1.0 + r).cumprod() * 100.0
    equity.iloc[0] = 100.0
    m = calculate_metrics(equity, [], r.index[0], r.index[-1])
    return {"cagr": round(float(m["cagr"]), 3), "sharpe": round(float(m["sharpe"]), 4),
            "mdd": round(float(m["mdd"]), 3), "n_days": int(len(r))}


def half_year_excess(ret: pd.Series, bench: pd.Series, picks: list[pd.Timestamp], ends: list[pd.Timestamp]) -> list[float | None]:
    """반기별 연율 초과수익(%) — 체결 관례상 선정일 다음 거래일부터 반기 끝까지."""
    diff = (ret.fillna(0.0) - bench.reindex(ret.index).fillna(0.0))
    out: list[float | None] = []
    for d, e in zip(picks, ends):
        seg = diff[(diff.index > pd.Timestamp(d)) & (diff.index <= pd.Timestamp(e))]
        out.append(None if len(seg) == 0 else float(seg.mean() * TD * 100.0))
    return out


def bench_returns(idx: pd.DatetimeIndex) -> pd.Series:
    return spy_close().reindex(idx).ffill().pct_change().fillna(0.0)


# ------------------------------------------------------------------ 부트스트랩(보조 — 블록)
def _sharpe(x: np.ndarray) -> float:
    sd = x.std(axis=-1)
    return float(x.mean(axis=-1) / sd * np.sqrt(TD)) if sd > 0 else 0.0


def paired_block_boot_sharpe_diff(a: np.ndarray, b: np.ndarray, seed: int = SEED,
                                  n_boot: int = N_BOOT, block: int = BLOCK) -> np.ndarray:
    """원형 이동블록 부트스트랩(두 계열에 같은 블록 위치) → sharpe(a) − sharpe(b) 분포. 보조 보고용."""
    rng = np.random.default_rng(seed)
    n = len(a)
    if n < block or n == 0:
        return np.zeros(1)
    nb = int(np.ceil(n / block))
    ea, eb = np.concatenate([a, a]), np.concatenate([b, b])
    offs = np.arange(block)
    out = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n, size=nb)
        ix = (starts[:, None] + offs[None, :]).ravel()[:n]
        out[i] = _sharpe(ea[ix]) - _sharpe(eb[ix])
    return out
