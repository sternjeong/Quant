"""가장 중요한 남은 검증: 지금까지 모든 실험이 2015~2026년(대체로 강세장, 코로나 급락 제외)
기간에서만 이뤄졌다. "리스크패리티 가중 + 변동성타게팅"이 진짜 일반적인 효과라면, 닷컴버블 붕괴
(2000~2002)와 금융위기(2007~2009)가 모두 낀 2000~2012년에도 통해야 한다.

2000-01-01 시점 실제 S&P500 구성종목(core.point_in_time_universe, 생존편향 없음)에서 무작위
표본을 뽑아, 코스톨라니 신호 없이 순수 매수보유 + 리스크패리티 가중 + 변동성타게팅만으로
(지난 실험들이 "신호는 무관하다"를 반복 확인했으므로) S&P500과 비교한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import random
import json
import pandas as pd

from core.backtest_engine import calculate_metrics, run_buy_and_hold
from core.market_data import get_multiple_price_history
from core.point_in_time_universe import get_constituents_as_of
from core.position_sizing import portfolio_volatility_target_weights
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
START, END = "2000-01-03", "2012-12-31"
SAMPLE_N = 100
SEED = 7
WARMUP_DAYS = 400


def main():
    constituents = get_constituents_as_of("2000-01-01")
    print(f"2000-01-01 시점 S&P500 구성종목 수: {len(constituents)}")

    random.seed(SEED)
    sample = sorted(random.sample(constituents, min(SAMPLE_N, len(constituents))))
    print(f"무작위 표본 {len(sample)}종목(seed={SEED})")

    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    print("가격 데이터 수집 중...", flush=True)
    histories = get_multiple_price_history(sample, start=fetch_start, end=END, interval="1d")
    ok_tickers = [t for t, df in histories.items() if df is not None and not df.empty and len(df) > WARMUP_DAYS]
    print(f"데이터 확보된 종목 수: {len(ok_tickers)} / {len(sample)}", flush=True)

    bench = run_buy_and_hold("^GSPC", START, END)
    print("S&P500 매수보유(2000~2012):", bench.metrics, flush=True)

    daily_rets_bh = {}
    for t in ok_tickers:
        df = histories[t]
        sliced = df[df.index >= pd.Timestamp(START)]
        if sliced.empty:
            continue
        daily_rets_bh[t] = sliced["Close"].pct_change().fillna(0.0)
    bh_df = pd.DataFrame(daily_rets_bh)
    print(f"수익률 계산 완료: {bh_df.shape[1]}종목 x {bh_df.shape[0]}일", flush=True)

    # 1) 동일가중, 오버레이 없음
    equal_ret = bh_df.mean(axis=1, skipna=True)
    m_equal, _ = metrics_from_returns(equal_ret)
    print("\n[동일가중, 오버레이 없음]:", m_equal, flush=True)

    # 2) 리스크패리티 가중, 오버레이 없음
    rp_weights = portfolio_volatility_target_weights(bh_df.dropna(how="all", axis=0))
    w = pd.Series(rp_weights)
    rp_ret = (bh_df[w.index] * w).sum(axis=1)
    m_rp, _ = metrics_from_returns(rp_ret)
    print("[리스크패리티, 오버레이 없음]:", m_rp, flush=True)

    # 3) 리스크패리티 + 변동성타게팅 스윕
    results = []
    curves = {}
    for window in [5, 20]:
        for target_vol in [12.0, 15.0, 20.0]:
            scale = vol_target_scale(rp_ret, target_vol, 1.0, window=window)
            scaled = rp_ret * scale.shift(1).fillna(1.0)
            m, eq = metrics_from_returns(scaled)
            results.append({"window": window, "target_vol": target_vol, **m})
            curves[f"w{window}_tv{target_vol}"] = eq
            print(f"  [리스크패리티+vol-target(window={window}, target={target_vol})]:", m, flush=True)

    res_df = pd.DataFrame(results)
    res_df.to_csv(f"{OUT_DIR}/bear_market_robustness_results.csv", index=False, encoding="utf-8-sig")

    print("\n=== 전체 요약 (샤프 내림차순) ===")
    print(res_df.sort_values("sharpe", ascending=False).to_string())
    print(f"\n참고 S&P500(2000~2012): cagr={bench.metrics['cagr']}, mdd={bench.metrics['mdd']}, sharpe={bench.metrics['sharpe']}")

    import pickle
    with open(f"{OUT_DIR}/bear_market_robustness_curves.pkl", "wb") as f:
        pickle.dump({"curves": curves, "bench_eq": bench.equity_curve, "bench_metrics": bench.metrics,
                     "m_equal": m_equal, "m_rp": m_rp, "sample": sample, "ok_tickers": ok_tickers}, f)

    with open(f"{OUT_DIR}/bear_market_robustness_summary.json", "w", encoding="utf-8") as f:
        json.dump({"equal_no_overlay": m_equal, "riskparity_no_overlay": m_rp,
                    "sp500_bh": bench.metrics, "n_tickers": len(ok_tickers)}, f, ensure_ascii=False, indent=2)
    print("DONE")


if __name__ == "__main__":
    main()
