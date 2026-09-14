"""가설: No.05의 듀얼 모멘텀 로테이션을 11개 섹터 ETF 대신, 코스톨라니 리포트(No.04)의 50종목
유니버스(10섹터x5) 전체에 적용하면 — 후보 풀이 훨씬 크고 분산이 더 잘 되므로 — 변동성타게팅과
결합했을 때 더 좋은 결과가 나오는가?

Top N(10, 15) x 동일비중, 매월 리밸런싱, 절대모멘텀(12개월>0) 필터는 momentum_rotation.py의
build_momentum_weights를 그대로 재사용(범용적으로 짜여 있어 종목 수와 무관하게 동작).
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pandas as pd

from core.backtest_engine import calculate_metrics, run_buy_and_hold
from core.market_data import get_multiple_price_history
from momentum_rotation import build_momentum_weights, compute_rotation_equity, WARMUP_DAYS
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
START, END = "2015-01-01", "2026-08-12"


def main():
    with open(f"{OUT_DIR}/sectors.json", encoding="utf-8") as f:
        meta = json.load(f)
    tickers = [t for sector_list in meta["sectors"].values() for t in sector_list]
    print(f"유니버스 {len(tickers)}종목: {tickers}")

    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(tickers, start=fetch_start, end=END, interval="1d")

    bench = run_buy_and_hold("^GSPC", START, END)
    print("S&P500 매수보유:", bench.metrics)

    results = []
    curves = {}
    for top_n in [10, 15]:
        eq, weights = compute_rotation_equity(histories, START, END, top_n=top_n)
        m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
        print(f"\nTop{top_n} 동일비중 모멘텀 로테이션(50종목 유니버스):", m)
        results.append({"top_n": top_n, "overlay": "none", **m})
        curves[f"top{top_n}_none"] = eq

        rot_ret = eq.pct_change().fillna(0.0)
        for target_vol in [10.0, 12.0, 15.0]:
            scale = vol_target_scale(rot_ret, target_vol, 1.0)
            scaled_ret = rot_ret * scale.shift(1).fillna(1.0)
            m2, eq2 = metrics_from_returns(scaled_ret)
            print(f"  + vol-target(target={target_vol}, cap=1.0):", m2)
            results.append({"top_n": top_n, "overlay": f"vt{target_vol}_cap1.0", **m2})
            curves[f"top{top_n}_vt{target_vol}"] = eq2

    res_df = pd.DataFrame(results)
    res_df.to_csv(f"{OUT_DIR}/momentum_rotation_50universe_results.csv", index=False, encoding="utf-8-sig")
    print("\n=== 전체 요약 (샤프 내림차순) ===")
    print(res_df.sort_values("sharpe", ascending=False).to_string())
    print(f"\n참고 S&P500: cagr={bench.metrics['cagr']}, mdd={bench.metrics['mdd']}, sharpe={bench.metrics['sharpe']}")

    import pickle
    with open(f"{OUT_DIR}/momentum_rotation_50universe_curves.pkl", "wb") as f:
        pickle.dump({"curves": curves, "bench_eq": bench.equity_curve, "bench_metrics": bench.metrics}, f)
    print("DONE")


if __name__ == "__main__":
    main()
