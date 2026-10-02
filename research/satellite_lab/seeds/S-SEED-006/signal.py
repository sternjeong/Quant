"""52주 신고가 근접도: 현재가 / 최근 1년 최고가. 1에 가까울수록 높은 점수."""
import math


def score(prices, as_of, params):
    w = int(params.get("window", 252))
    out = {}
    for t, df in prices.items():
        c = df["Close"].dropna()
        if len(c) < w:
            continue
        hi = c.iloc[-w:].max()
        v = c.iloc[-1] / hi if hi > 0 else float("nan")
        if math.isfinite(v):
            out[t] = float(v)
    return out
