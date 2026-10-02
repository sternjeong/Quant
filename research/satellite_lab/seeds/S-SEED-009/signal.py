"""저변동 추세: 돈치안 추세가 활성인 종목 중 최근 변동성이 가장 낮은 순."""
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
    vw = int(params.get("vol_window", 63))
    out = {}
    for t, df in prices.items():
        c = df["Close"].dropna()
        if len(c) < max(80, vw + 2) or not _trend_active(c, 20, 0.15):
            continue
        vol = float(np.std(np.diff(np.log(c.iloc[-vw - 1:].to_numpy())), ddof=1))
        if vol > 0 and math.isfinite(vol):
            out[t] = -vol
    return out
