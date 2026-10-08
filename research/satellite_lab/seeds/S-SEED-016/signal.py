"""S-SEED-016 섹터 분산 모멘텀 — 현 규칙 순위대로 고르되 같은 업종(SIC 앞 두 자리)은 업종마다 첫 종목만 앞에 두고 나머지는 뒤로 미룬다 — 한 업종 몰림(2026 산업재) 위험을 줄인다.

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


def score(prices, as_of, params, ctx=None):
    base = _base(prices, params)
    seen = set()
    out = {}
    for t, s in sorted(base.items(), key=lambda kv: (-kv[1], kv[0])):
        sic = (ctx.fundamentals(t) or {}).get("sic")
        group = (sic // 100) if sic else None
        if group is not None and group in seen:
            out[t] = s - 1000.0  # 같은 업종 두 번째부터는 다른 업종 뒤로
        else:
            out[t] = s
            if group is not None:
                seen.add(group)
    return out
