"""변동성 조정 모멘텀: 12개월 수익률 / 연환산 변동성."""
import math

import numpy as np


def score(prices, as_of, params):
    lb, vw = int(params.get("lookback", 252)), int(params.get("vol_window", 126))
    out = {}
    for t, df in prices.items():
        c = df["Close"].dropna()
        if len(c) < max(lb, vw) + 2:
            continue
        mom = c.iloc[-1] / c.iloc[-1 - lb] - 1.0
        vol = float(np.std(np.diff(np.log(c.iloc[-vw - 1:].to_numpy())), ddof=1)) * math.sqrt(252)
        if vol > 0 and math.isfinite(mom):
            out[t] = float(mom / vol)
    return out
