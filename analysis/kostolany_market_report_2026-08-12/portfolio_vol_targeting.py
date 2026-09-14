"""H5: 개별 종목이 아니라 '50종목 동일가중 포트폴리오의 일별 수익률 자체'에 변동성 타게팅을 적용.

앞선 실험(H1)에서 종목별로 vol-targeting을 걸면 평균이 나빠졌다 — NVDA 같은 원래 고변동성
구조적 성장주의 노출을 획일적으로 깎아버려서다. 하지만 포트폴리오(50종목 동일가중) 수준의
일별 수익률은 개별 종목보다 훨씬 안정적(분산 효과)이라, 여기에 목표 변동성을 씌우는 건 완전히
다른 이야기일 수 있다 — 이게 실제 리스크패리티/변동성 타게팅 펀드들이 쓰는 표준적인 적용 지점이다
(개별 종목이 아니라 이미 분산된 포트폴리오/전체 계좌 수익률에 적용).

E4(final_recommended.py에서 이미 계산해 둔 전략) 포트폴리오와 매수보유 포트폴리오 둘 다에 대해
같은 방식으로 vol-targeting을 적용해 비교한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, run_buy_and_hold
from core.market_data import get_multiple_price_history, get_price_history
from hyperparam_grid_search import classify_cycle_phase_series_param
from trend_gate_search import STYLE, START, END, WARMUP_DAYS, TUNED, build_position_trend_gated

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
BEST_UP, BEST_DOWN = 15.0, -25.0
FINAL_SELL_WEIGHT = 0.5
TRADING_DAYS = 252


def vol_target_scale(daily_ret: pd.Series, target_vol_annual: float, cap: float, window: int = 20, floor: float = 0.0) -> pd.Series:
    realized_vol = daily_ret.rolling(window, min_periods=window).std() * np.sqrt(TRADING_DAYS)
    scale = (target_vol_annual / 100.0) / realized_vol
    return scale.clip(lower=floor, upper=cap).fillna(1.0)


def metrics_from_returns(rets: pd.Series) -> dict:
    eq = (1.0 + rets.fillna(0.0)).cumprod() * 100.0
    return calculate_metrics(eq, [], eq.index[0], eq.index[-1]), eq


def main():
    baseline_df = pd.read_csv(f"{OUT_DIR}/summary_장기.csv").set_index("theme")
    sector_tickers = [t for t in baseline_df.index if t != "S&P500"]
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(sector_tickers, start=fetch_start, end=END, interval="1d")

    daily_rets_strategy = {}
    daily_rets_bh = {}
    for ticker in sector_tickers:
        df = histories[ticker]
        phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **TUNED)
        position_full = build_position_trend_gated(phase_full, df["Close"], STYLE, BEST_UP, BEST_DOWN, FINAL_SELL_WEIGHT)
        sliced = df[df.index >= pd.Timestamp(START)]
        position = position_full.loc[sliced.index]
        executed_position = position.shift(1).fillna(0.0)
        daily_ret = sliced["Close"].pct_change().fillna(0.0)
        daily_rets_strategy[ticker] = daily_ret * executed_position
        daily_rets_bh[ticker] = daily_ret

    strat_df = pd.DataFrame(daily_rets_strategy).dropna(how="all")
    bh_df = pd.DataFrame(daily_rets_bh).reindex(strat_df.index)
    port_strategy_ret = strat_df.mean(axis=1)
    port_bh_ret = bh_df.mean(axis=1)

    bench_run = run_buy_and_hold("^GSPC", port_strategy_ret.index[0].date().isoformat(), port_strategy_ret.index[-1].date().isoformat())
    sp500_metrics = bench_run.metrics
    print("S&P500 buy&hold:", sp500_metrics, flush=True)

    port_strategy_metrics, _ = metrics_from_returns(port_strategy_ret)
    port_bh_metrics, _ = metrics_from_returns(port_bh_ret)
    print("portfolio strategy (no overlay):", port_strategy_metrics, flush=True)
    print("portfolio buy&hold (no overlay):", port_bh_metrics, flush=True)

    results = []
    curves = {}
    for target_vol in [10.0, 12.0, 15.0, 18.0]:
        for cap in [1.0, 1.5, 2.0]:
            for label, rets in [("strategy", port_strategy_ret), ("bh", port_bh_ret)]:
                scale = vol_target_scale(rets, target_vol, cap)
                scaled_rets = rets * scale.shift(1).fillna(1.0)  # 전일 종가까지의 vol로 오늘 스케일 결정(lookahead 방지)
                m, eq = metrics_from_returns(scaled_rets)
                results.append({"target_vol": target_vol, "cap": cap, "base": label, **m})
                if label == "strategy":
                    curves[f"vt{target_vol}_cap{cap}"] = eq

    res_df = pd.DataFrame(results)
    res_df.to_csv(f"{OUT_DIR}/portfolio_vol_targeting_results.csv", index=False, encoding="utf-8-sig")
    print("\n=== 포트폴리오 변동성타게팅 스윕 (샤프 내림차순) ===")
    print(res_df.sort_values("sharpe", ascending=False).to_string())

    print(f"\n참고: S&P500 buy&hold sharpe={sp500_metrics['sharpe']}, cagr={sp500_metrics['cagr']}, mdd={sp500_metrics['mdd']}")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
