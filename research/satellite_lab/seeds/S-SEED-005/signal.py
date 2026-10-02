"""12-1 모멘텀: 최근 1개월을 뺀 12개월 수익률(단기 반전 효과 회피), 돌파 필터 없음."""
import math


def score(prices, as_of, params):
    lb, skip = int(params.get("lookback", 252)), int(params.get("skip", 21))
    out = {}
    for t, df in prices.items():
        c = df["Close"].dropna()
        if len(c) < lb + 2:
            continue
        v = c.iloc[-1 - skip] / c.iloc[-1 - lb] - 1.0
        if math.isfinite(v):
            out[t] = float(v)
    return out
