"""생존편향 제거 실험: 08장의 Top10 모멘텀 로테이션이 극적으로 좋았던(CAGR 29%) 이유가 "2026년
현재 기준 각 업종 승자만 골라놓은 50종목 유니버스" 때문이라는 게 08장의 핵심 caveat였다. 이를
직접 검증하기 위해, 미래를 모른 채 2015-01-01 시점에 실제로 S&P500에 속해 있던 종목 목록에서
(2026년 결과를 보고 고른 게 아니라) 무작위로 표본을 뽑아 같은 로테이션을 돌린다.

완전한 시점별(월별 재구성) point-in-time 유니버스까지는 아니지만("이번 세션 다음 우선순위"로
남겨둠 — 매달 유니버스를 다시 불러오려면 수백 종목의 재구성 이력을 전부 추적해야 해서 비용이 큼),
"시작 시점에 이미 알려진 종목만 쓴다"는 조건만으로도 "2026년 승자를 사후에 골랐다"는 편향은
제거된다 — 종목이 중간에 상장폐지/편입제외되어도 유니버스에서 빼지 않고 그대로 들고 가므로
오히려 실전보다도 보수적인(약간 불리한 방향의) 조건이다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import random
import pandas as pd

from core.backtest_engine import calculate_metrics, run_buy_and_hold
from core.market_data import get_multiple_price_history
from core.point_in_time_universe import get_constituents_as_of
from momentum_rotation import compute_rotation_equity, WARMUP_DAYS
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
START, END = "2015-01-01", "2026-08-12"
SAMPLE_N = 100
SEED = 42


def main():
    constituents = get_constituents_as_of(START)
    print(f"2015-01-01 시점 S&P500 구성종목 수: {len(constituents)}")

    random.seed(SEED)
    sample = sorted(random.sample(constituents, min(SAMPLE_N, len(constituents))))
    print(f"무작위 표본 {len(sample)}종목(seed={SEED}): {sample}")

    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    print("가격 데이터 수집 중 (시간이 걸릴 수 있음)...", flush=True)
    histories = get_multiple_price_history(sample, start=fetch_start, end=END, interval="1d")
    ok_tickers = [t for t, df in histories.items() if df is not None and not df.empty and len(df) > WARMUP_DAYS]
    print(f"데이터 확보된 종목 수: {len(ok_tickers)} / {len(sample)}")
    histories = {t: histories[t] for t in ok_tickers}

    bench = run_buy_and_hold("^GSPC", START, END)
    print("S&P500 매수보유:", bench.metrics, flush=True)

    results = []
    curves = {}
    for top_n in [10, 15]:
        eq, weights = compute_rotation_equity(histories, START, END, top_n=top_n)
        m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
        print(f"\nTop{top_n} 동일비중 모멘텀 로테이션(편향제거 {len(histories)}종목 유니버스):", m, flush=True)
        results.append({"top_n": top_n, "overlay": "none", **m})
        curves[f"top{top_n}_none"] = eq

        rot_ret = eq.pct_change().fillna(0.0)
        for target_vol in [12.0, 15.0, 18.0]:
            scale = vol_target_scale(rot_ret, target_vol, 1.0)
            scaled_ret = rot_ret * scale.shift(1).fillna(1.0)
            m2, eq2 = metrics_from_returns(scaled_ret)
            print(f"  + vol-target({target_vol}, cap=1.0):", m2, flush=True)
            results.append({"top_n": top_n, "overlay": f"vt{target_vol}", **m2})
            curves[f"top{top_n}_vt{target_vol}"] = eq2

    res_df = pd.DataFrame(results)
    res_df.to_csv(f"{OUT_DIR}/momentum_rotation_unbiased_results.csv", index=False, encoding="utf-8-sig")
    print("\n=== 전체 요약 (샤프 내림차순) ===")
    print(res_df.sort_values("sharpe", ascending=False).to_string())
    print(f"\n참고 S&P500: cagr={bench.metrics['cagr']}, mdd={bench.metrics['mdd']}, sharpe={bench.metrics['sharpe']}")
    print(f"참고(08장, 사후편향 있는 50종목 유니버스): Top10 no-overlay cagr=29.11, mdd=-29.88, sharpe=1.15")

    import pickle, json
    with open(f"{OUT_DIR}/momentum_rotation_unbiased_curves.pkl", "wb") as f:
        pickle.dump({"curves": curves, "bench_eq": bench.equity_curve, "bench_metrics": bench.metrics,
                     "sample": sample, "ok_tickers": ok_tickers}, f)
    print("DONE")


if __name__ == "__main__":
    main()
