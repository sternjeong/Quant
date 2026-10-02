"""현 챔피언 새틀라이트 규칙 — core.champion_strategy._pick_satellite_at_date 와 같은 선정 로직.

돈치안 20일 돌파로 진입, 고점 대비 15% 하락 시 이탈하는 추세 상태가 '활성'인 종목 중 12개월 모멘텀 순.
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


def score(prices, as_of, params):
    window = int(params.get("donchian", 20))
    stop = float(params.get("stop_pct", 0.15))
    mom_w = int(params.get("mom_window", 252))
    out = {}
    for t, df in prices.items():
        close = df["Close"].dropna()
        if len(close) < window + 60 or not _trend_active(close, window, stop):
            continue
        if len(close) >= mom_w + 5:
            mom = close.iloc[-1] / close.iloc[-1 - mom_w] - 1.0
        else:
            mom = close.iloc[-1] / close.iloc[0] - 1.0
        if math.isfinite(mom):
            out[t] = float(mom)
    return out
