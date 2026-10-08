"""S-SEED-018 거장 보유 우선 — 현 규칙 후보 중 거장 1명 이상이 보유한 종목을 먼저 산다 — 거장의 판단을 추세 신호의 확인 장치로.

거장 13F(core/guru_history.py — 리밸런싱 전날까지 공시된 것만, 2013년 2분기 이전에는 데이터 없음)를 쓴다. 거장 데이터가 없는 때·종목은
현 규칙대로 다룬다. 거장 = 관제 센터 '거장 포트폴리오'의 기본 목록(버핏·버리·애크먼·우드·드러켄밀러·테퍼·클라만). 2026-10-08 사전 등록.
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


def score(prices, as_of, params, ctx=None):
    base = _base(prices, params)
    out = {}
    for t, s in base.items():
        g = ctx.guru(t) or {}
        out[t] = s + (1000.0 if g.get("n_holders", 0) >= 1 else 0.0)  # 거장 조건을 만족하면 현 규칙 후보 중 맨 앞으로
    return out
