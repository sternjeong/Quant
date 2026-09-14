"""가장 중요한 미해결 질문: 07장의 헤드라인 발견("50종목 포트폴리오 + 변동성타게팅 = 레버리지 없이
샤프비율로 시장을 이긴다")도 사실 50종목 유니버스 자체가 2026년 기준 각 업종 승자 위주로 골라진
생존편향 유니버스였다 — 08장에서 그 편향을 제거했더니 모멘텀 로테이션의 우위가 사라졌다. 그렇다면
07장의 (코스톨라니 E4 전략 + 포트폴리오 변동성타게팅) 결과도 같은 이유로 무너지는가?

이 스크립트는 08장에서 만든 생존편향 없는 68종목 유니버스(2015-01-01 시점 실제 S&P500 구성종목
무작위 표본)에 07장과 완전히 동일한 파이프라인(E4 코스톨라니 전략 각 종목에 적용 -> 동일가중
포트폴리오 -> core.position_sizing의 변동성타게팅 로직)을 그대로 걸어 검증한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import pickle
import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, run_buy_and_hold
from core.market_data import get_multiple_price_history
from core.position_sizing import portfolio_volatility_target_weights
from hyperparam_grid_search import classify_cycle_phase_series_param
from trend_gate_search import STYLE, START, END, WARMUP_DAYS, TUNED, build_position_trend_gated
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
BEST_UP, BEST_DOWN = 15.0, -25.0
FINAL_SELL_WEIGHT = 0.5


def main():
    with open(f"{OUT_DIR}/momentum_rotation_unbiased_curves.pkl", "rb") as f:
        unbiased_meta = pickle.load(f)
    ok_tickers = unbiased_meta["ok_tickers"]
    print(f"생존편향 제거 유니버스: {len(ok_tickers)}종목")

    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(ok_tickers, start=fetch_start, end=END, interval="1d")

    bench = run_buy_and_hold("^GSPC", START, END)
    print("S&P500 매수보유:", bench.metrics, flush=True)

    # --- 1) E4 코스톨라니 전략을 종목별로 적용 ---
    daily_rets_strategy = {}
    daily_rets_bh = {}
    for ticker, df in histories.items():
        if df is None or df.empty or len(df) < WARMUP_DAYS:
            continue
        phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **TUNED)
        position_full = build_position_trend_gated(phase_full, df["Close"], STYLE, BEST_UP, BEST_DOWN, FINAL_SELL_WEIGHT)
        sliced = df[df.index >= pd.Timestamp(START)]
        if sliced.empty:
            continue
        position = position_full.reindex(sliced.index).fillna(0.0)
        executed_position = position.shift(1).fillna(0.0)
        daily_ret = sliced["Close"].pct_change().fillna(0.0)
        daily_rets_strategy[ticker] = daily_ret * executed_position
        daily_rets_bh[ticker] = daily_ret

    strat_df = pd.DataFrame(daily_rets_strategy)
    bh_df = pd.DataFrame(daily_rets_bh)
    print(f"전략 계산 완료: {strat_df.shape[1]}종목 x {strat_df.shape[0]}일", flush=True)

    # --- 2) 동일가중 포트폴리오 (07장과 동일 방식) ---
    port_strategy_ret_eq = strat_df.mean(axis=1, skipna=True)
    port_bh_ret_eq = bh_df.mean(axis=1, skipna=True)

    m_strat_eq, _ = metrics_from_returns(port_strategy_ret_eq)
    m_bh_eq, _ = metrics_from_returns(port_bh_ret_eq)
    print("\n[동일가중] 전략 포트폴리오(오버레이 없음):", m_strat_eq, flush=True)
    print("[동일가중] 매수보유 포트폴리오(오버레이 없음):", m_bh_eq, flush=True)

    results = []
    curves = {}
    for target_vol in [10.0, 12.0, 15.0, 18.0]:
        scale = vol_target_scale(port_strategy_ret_eq, target_vol, 1.0)
        scaled = port_strategy_ret_eq * scale.shift(1).fillna(1.0)
        m, eq = metrics_from_returns(scaled)
        results.append({"weighting": "equal", "target_vol": target_vol, "base": "strategy", **m})
        curves[f"eq_strategy_vt{target_vol}"] = eq
        print(f"  [동일가중+vol-target({target_vol})] 전략:", m, flush=True)

        scale_bh = vol_target_scale(port_bh_ret_eq, target_vol, 1.0)
        scaled_bh = port_bh_ret_eq * scale_bh.shift(1).fillna(1.0)
        m_bh, eq_bh = metrics_from_returns(scaled_bh)
        results.append({"weighting": "equal", "target_vol": target_vol, "base": "bh", **m_bh})
        curves[f"eq_bh_vt{target_vol}"] = eq_bh

    # --- 3) core.position_sizing의 inverse-vol 리스크패리티 가중(전 종목) + 변동성타게팅 결합 ---
    rp_weights = portfolio_volatility_target_weights(strat_df.dropna(how="all", axis=0))
    print(f"\n리스크패리티 가중치 상위 5개: {sorted(rp_weights.items(), key=lambda x: -x[1])[:5]}", flush=True)
    w_series = pd.Series(rp_weights)
    port_strategy_ret_rp = (strat_df[w_series.index] * w_series).sum(axis=1)
    port_bh_ret_rp = (bh_df[w_series.index] * w_series).sum(axis=1)

    m_strat_rp, _ = metrics_from_returns(port_strategy_ret_rp)
    m_bh_rp, _ = metrics_from_returns(port_bh_ret_rp)
    print("\n[리스크패리티 가중] 전략 포트폴리오(오버레이 없음):", m_strat_rp, flush=True)
    print("[리스크패리티 가중] 매수보유 포트폴리오(오버레이 없음):", m_bh_rp, flush=True)

    for target_vol in [10.0, 12.0, 15.0]:
        scale = vol_target_scale(port_strategy_ret_rp, target_vol, 1.0)
        scaled = port_strategy_ret_rp * scale.shift(1).fillna(1.0)
        m, eq = metrics_from_returns(scaled)
        results.append({"weighting": "risk_parity", "target_vol": target_vol, "base": "strategy", **m})
        curves[f"rp_strategy_vt{target_vol}"] = eq
        print(f"  [리스크패리티+vol-target({target_vol})] 전략:", m, flush=True)

    res_df = pd.DataFrame(results)
    res_df.to_csv(f"{OUT_DIR}/unbiased_kostolany_portfolio_results.csv", index=False, encoding="utf-8-sig")

    print("\n=== 전체 요약 (샤프 내림차순) ===")
    print(res_df.sort_values("sharpe", ascending=False).to_string())
    print(f"\n참고 S&P500: cagr={bench.metrics['cagr']}, mdd={bench.metrics['mdd']}, sharpe={bench.metrics['sharpe']}")
    print(f"참고(07장, 사후편향 50종목): 전략 무오버레이 cagr=16.6, sharpe=0.97; vt12/cap1.0 cagr=12.02, sharpe=1.08")

    import json
    with open(f"{OUT_DIR}/unbiased_kostolany_portfolio_summary.json", "w", encoding="utf-8") as f:
        json.dump({
            "no_overlay_equal_strategy": m_strat_eq, "no_overlay_equal_bh": m_bh_eq,
            "no_overlay_riskparity_strategy": m_strat_rp, "no_overlay_riskparity_bh": m_bh_rp,
            "sp500_bh": bench.metrics, "n_tickers": strat_df.shape[1],
        }, f, ensure_ascii=False, indent=2)

    with open(f"{OUT_DIR}/unbiased_kostolany_portfolio_curves.pkl", "wb") as f:
        pickle.dump({"curves": curves, "bench_eq": bench.equity_curve,
                     "port_strategy_ret_eq": port_strategy_ret_eq, "port_bh_ret_eq": port_bh_ret_eq}, f)
    print("DONE")


if __name__ == "__main__":
    main()
