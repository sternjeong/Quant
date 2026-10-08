"""S-SEED-014 실적 발표 반응 모멘텀 — 현 규칙 후보 중 최근 100일 안 실적 발표(8-K 2.02) 전후 3거래일 반응이 후보 전체 중앙값보다 좋은 종목만(발표가 없거나 모르면 유지) — 실적 후 상승 지속(PEAD).

현 규칙(S-SEED-000: 돈치안 20일 추세 활성 중 12개월 모멘텀 순)에 재무·실적 정보(core/fundamentals_pit — 리밸런싱 전날까지 공시된 것만)를 더한다.
재무 데이터가 없는 종목('모름')은 빼지 않고 현 규칙대로 다룬다(상장폐지 회사가 데이터에서 빠지는 쪽으로 기울지 않게). 2026-10-08 사전 등록.
"""
import math

import numpy as np


def _trend_active(close, window, stop_pct):
    v = close.to_numpy(dtype=float)
    roll_max = close.shift(1).rolling(window, min_periods=window).max().to_numpy()
    in_pos, peak = False, None
    for i in range(len(v)):
        c = v[i]
        if in_pos:
            peak = max(peak, c)
            if c <= peak * (1 - stop_pct):
                in_pos, peak = False, None
        elif not np.isnan(roll_max[i]) and c > roll_max[i]:
            in_pos, peak = True, c
    return in_pos




def _base(prices, params):
    window = int(params.get("donchian", 20))
    stop = float(params.get("stop_pct", 0.15))
    mom_w = int(params.get("mom_window", 252))
    out = {}
    for t, df in prices.items():
        close = df["Close"].dropna()
        if len(close) < window + 60 or not _trend_active(close, window, stop):
            continue
        mom = close.iloc[-1] / close.iloc[-1 - mom_w] - 1.0 if len(close) >= mom_w + 5 else close.iloc[-1] / close.iloc[0] - 1.0
        if math.isfinite(mom):
            out[t] = float(mom)
    return out


import pandas as pd


def _reaction(df, day):
    close = df["Close"].dropna()
    d = pd.Timestamp(day)
    before = close[close.index < d]
    after = close[close.index > d]
    if len(before) == 0 or len(after) < 2:
        return None
    return float(after.iloc[1] / before.iloc[-1] - 1.0)


def score(prices, as_of, params, ctx=None):
    base = _base(prices, params)
    asof = pd.Timestamp(as_of)
    react = {}
    for t in base:
        last = (ctx.fundamentals(t) or {}).get("last_earnings")
        if last and (asof - pd.Timestamp(last)).days <= 100:
            react[t] = _reaction(prices[t], last)
    known = sorted(v for v in react.values() if v is not None)
    if not known:
        return base
    med = known[len(known) // 2]
    return {t: s for t, s in base.items() if react.get(t) is None or react[t] >= med}
