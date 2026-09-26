"""H5 — 코어 월중 드리프트(기술 통계): '오늘 종가로 다시 계산한 top4' vs '그 달 월초 확정 top4'.
규칙은 core.champion_strategy._build_core_weights 와 같다(252일 모멘텀>0 상위 4, NaN 제외)."""
import json

import pandas as pd

from common import HERE, W_START, W_END
from core.champion_strategy import CORE_UNIVERSE, CORE_MOMENTUM_LOOKBACK_DAYS, CORE_TOP_N, _closes_from_histories
from core.backtest_engine import _first_trading_day_of_month_mask
from core.market_data import get_multiple_price_history

hist = get_multiple_price_history(list(CORE_UNIVERSE) + ["SPY"], start="2006-01-01", end="2026-09-01")
closes_all = _closes_from_histories(hist, list(CORE_UNIVERSE) + ["SPY"])
closes = closes_all[[t for t in CORE_UNIVERSE if t in closes_all.columns]]
mom = closes.pct_change(CORE_MOMENTUM_LOOKBACK_DAYS)


def top(row):
    c = row[row > 0].sort_values(ascending=False)
    return frozenset(c.index[:CORE_TOP_N])


is_rebal = _first_trading_day_of_month_mask(closes.index)
idx = closes.index
monthly = {}
cur = None
for i, dt in enumerate(idx):
    if is_rebal.iloc[i] and i > 0:
        cur = top(mom.iloc[i - 1])  # 전일 종가 신호(백테스트 규칙)
    monthly[dt] = cur

rows = []
for dt in idx[(idx >= pd.Timestamp(W_START)) & (idx <= pd.Timestamp(W_END))]:
    a, b = monthly[dt], top(mom.loc[dt])
    nd = max(len(a - b), len(b - a))
    rows.append({"date": dt, "differs": nd > 0, "n_diff": nd, "dom": None})
df = pd.DataFrame(rows).set_index("date")
# 월 내 거래일 순번(1=월초)
per = df.index.to_period("M")
df["day_of_month_td"] = pd.Series(1, index=df.index).groupby(per).cumsum().values

frac = float(df["differs"].mean())
res = {
    "window": [W_START, W_END], "n_days": int(len(df)),
    "mismatch_day_fraction": round(frac, 4),
    "mean_n_diff_when_differs": round(float(df.loc[df["differs"], "n_diff"].mean()), 3),
    "n_diff_distribution": {int(k): int(v) for k, v in df["n_diff"].value_counts().sort_index().items()},
    "mismatch_fraction_by_trading_day_of_month": {int(k): round(float(v), 4) for k, v in
                                                   df.groupby("day_of_month_td")["differs"].mean().items()},
    "mismatch_fraction_by_year": {int(k): round(float(v), 4) for k, v in df.groupby(df.index.year)["differs"].mean().items()},
    "months_with_any_mismatch_fraction": round(float(df.groupby(per)["differs"].any().mean()), 4),
    "rule": "불일치 비율 > 10% 이면 화면 주 표시를 '이번 달 보유(검증 기준)'로 바꿀 근거로 기록",
    "rule_triggered": bool(frac > 0.10),
    "note": "XLC(2018-06)·XLRE(2015-10) 상장 전은 모멘텀 NaN → 후보 제외(백테스트와 동일).",
}
(HERE / "h5_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in res.items() if "by_" not in k}, ensure_ascii=False, indent=1))
