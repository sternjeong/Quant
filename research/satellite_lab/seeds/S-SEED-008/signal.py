"""꾸준한 상승(frog-in-the-pan): 12개월 모멘텀 상위 절반 중 '오른 날 비율 − 내린 날 비율'이 큰 순."""
import math

import numpy as np


def score(prices, as_of, params):
    lb = int(params.get("lookback", 252))
    moms, smooth = {}, {}
    for t, df in prices.items():
        c = df["Close"].dropna()
        if len(c) < lb + 2:
            continue
        m = c.iloc[-1] / c.iloc[-1 - lb] - 1.0
        if not math.isfinite(m) or m <= 0:
            continue
        d = np.diff(c.iloc[-lb - 1:].to_numpy())
        moms[t] = float(m)
        smooth[t] = float((d > 0).mean() - (d < 0).mean())
    if not moms:
        return {}
    cut = float(np.median(list(moms.values())))
    return {t: smooth[t] for t, m in moms.items() if m >= cut}
