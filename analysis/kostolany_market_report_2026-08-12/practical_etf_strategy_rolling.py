"""practical_etf_strategy.py의 섹터 ETF 리스크패리티 부분을, 룩어헤드 없는 롤링(분기 재계산)
버전으로 다시 계산해 이전 결과(전체 구간 한 번에 계산 - 룩어헤드 있음)와 비교한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns
from rolling_risk_parity import rolling_risk_parity_weights

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
WARMUP_DAYS = 400

SECTOR_ETFS_MODERN = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
SECTOR_ETFS_LEGACY = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU"]


def run_period(label, start, end, sector_etfs):
    print(f"\n{'='*20} {label} ({start}~{end}) {'='*20}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")

    daily_rets_full = {}
    for t in sector_etfs:
        df = etf_hist.get(t)
        if df is None or df.empty:
            continue
        daily_rets_full[t] = df["Close"].pct_change().fillna(0.0)
    full_df = pd.DataFrame(daily_rets_full)  # warmup 포함 - 롤링 계산의 과거 데이터로 사용

    sliced_df = full_df[full_df.index >= pd.Timestamp(start)]
    print(f"사용 가능한 섹터 ETF: {[c for c in sliced_df.columns if sliced_df[c].abs().sum() > 0]}", flush=True)

    # 롤링(룩어헤드 없음): 분기마다 트레일링 1년으로 재계산
    weights_daily = rolling_risk_parity_weights(full_df, lookback_days=252, rebal_freq="QS")
    weights_daily = weights_daily.loc[sliced_df.index]
    # 신호 다음날 체결(기존 엔진 관례와 일치하도록 1일 지연)
    executed_weights = weights_daily.shift(1).fillna(1.0 / weights_daily.shape[1])
    rolling_ret = (sliced_df * executed_weights).sum(axis=1)
    m_rolling, _ = metrics_from_returns(rolling_ret)
    print("[롤링 리스크패리티, 오버레이 없음]:", m_rolling, flush=True)

    # 비교용: 기존 방식(전체 구간 한 번에 계산 - 룩어헤드 있음)
    from core.position_sizing import portfolio_volatility_target_weights
    static_w = pd.Series(portfolio_volatility_target_weights(sliced_df.dropna(how="all", axis=0)))
    static_ret = (sliced_df[static_w.index] * static_w).sum(axis=1)
    m_static, _ = metrics_from_returns(static_ret)
    print("[정적(룩어헤드 있음) 리스크패리티, 오버레이 없음]:", m_static, flush=True)

    results = {}
    for window, tv in [(5, 15.0), (5, 20.0)]:
        scale = vol_target_scale(rolling_ret, tv, 1.0, window=window)
        scaled = rolling_ret * scale.shift(1).fillna(1.0)
        m, _ = metrics_from_returns(scaled)
        results[f"w{window}_tv{tv}"] = m
        print(f"  [롤링+vol(window={window},target={tv})]:", m, flush=True)

    bench = run_buy_and_hold("^GSPC", start, end)
    print("S&P500:", bench.metrics, flush=True)

    return {"rolling_no_overlay": m_rolling, "static_lookahead_no_overlay": m_static,
            "rolling_vol_target": results, "sp500_bh": bench.metrics}


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2000_2012"] = run_period("약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)

    with open(f"{OUT_DIR}/practical_etf_rolling_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
