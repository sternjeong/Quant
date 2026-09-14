"""08장의 가장 많이 인용된 숫자(편향제거 68종목, 리스크패리티+변동성타게팅, 샤프 0.92)도 정적
(룩어헤드 있는) 리스크패리티 대신 롤링(분기 재계산, 룩어헤드 없음) 버전으로 다시 확인한다.
개별 종목은 섹터 ETF보다 변동성 레짐이 더 크게 바뀔 수 있어(성장주가 성숙주로 바뀌는 등) 영향이
더 클 가능성이 있다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pickle
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from hyperparam_grid_search import classify_cycle_phase_series_param
from trend_gate_search import STYLE, START, END, WARMUP_DAYS, TUNED, build_position_trend_gated
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns
from rolling_risk_parity import rolling_risk_parity_weights

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
BEST_UP, BEST_DOWN = 15.0, -25.0
FINAL_SELL_WEIGHT = 0.5


def main():
    with open(f"{OUT_DIR}/momentum_rotation_unbiased_curves.pkl", "rb") as f:
        meta = pickle.load(f)
    ok_tickers = meta["ok_tickers"]

    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(ok_tickers, start=fetch_start, end=END, interval="1d")

    daily_rets_full = {}
    for t, df in histories.items():
        if df is None or df.empty or len(df) < WARMUP_DAYS:
            continue
        phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **TUNED)
        position_full = build_position_trend_gated(phase_full, df["Close"], STYLE, BEST_UP, BEST_DOWN, FINAL_SELL_WEIGHT)
        executed_position = position_full.shift(1).fillna(0.0)
        daily_ret = df["Close"].pct_change().fillna(0.0)
        daily_rets_full[t] = daily_ret * executed_position

    full_df = pd.DataFrame(daily_rets_full)
    sliced_df = full_df[full_df.index >= pd.Timestamp(START)]
    print(f"유니버스: {sliced_df.shape[1]}종목", flush=True)

    weights_daily = rolling_risk_parity_weights(full_df, lookback_days=252, rebal_freq="QS")
    weights_daily = weights_daily.loc[sliced_df.index]
    executed_weights = weights_daily.shift(1).fillna(1.0 / weights_daily.shape[1])
    rolling_ret = (sliced_df * executed_weights).sum(axis=1)
    m_rolling_no_overlay, _ = metrics_from_returns(rolling_ret)
    print("[롤링 리스크패리티, 오버레이 없음]:", m_rolling_no_overlay, flush=True)

    scale = vol_target_scale(rolling_ret, 20.0, 1.0, window=5)
    scaled = rolling_ret * scale.shift(1).fillna(1.0)
    m_rolling_final, eq_rolling = metrics_from_returns(scaled)
    print("[롤링+vol(window=5,target=20)] (07장 최종안과 비교):", m_rolling_final, flush=True)
    print("(참고: 정적/룩어헤드 버전은 CAGR 12.09%/MDD -17.42%/샤프 0.92 였음)")

    bench = run_buy_and_hold("^GSPC", sliced_df.index[0].date().isoformat(), sliced_df.index[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)

    with open(f"{OUT_DIR}/unbiased_portfolio_rolling_check.json", "w", encoding="utf-8") as f:
        json.dump({
            "rolling_no_overlay": m_rolling_no_overlay, "rolling_final": m_rolling_final,
            "sp500_bh": bench.metrics,
            "static_lookahead_reference": {"cagr": 12.09, "mdd": -17.42, "sharpe": 0.92},
        }, f, ensure_ascii=False, indent=2)
    print("DONE")


if __name__ == "__main__":
    main()
