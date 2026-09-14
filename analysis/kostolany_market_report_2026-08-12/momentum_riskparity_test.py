"""가설: Top-N 동일비중 대신 위험균등(inverse-vol) 가중을 쓰면 모멘텀 로테이션의 샤프비율이
더 개선되는가? momentum_rotation.py의 weighting="inverse_vol" 옵션(이미 구현, 미검증)을 처음
테스트한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pandas as pd

from core.backtest_engine import calculate_metrics, run_buy_and_hold
from core.market_data import get_multiple_price_history
from momentum_rotation import compute_rotation_equity, WARMUP_DAYS
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
START, END = "2015-01-01", "2026-08-12"


def main():
    with open(f"{OUT_DIR}/sectors.json", encoding="utf-8") as f:
        meta = json.load(f)
    tickers = [t for sector_list in meta["sectors"].values() for t in sector_list]

    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(tickers, start=fetch_start, end=END, interval="1d")
    bench = run_buy_and_hold("^GSPC", START, END)

    results = []
    for top_n in [10, 15]:
        for weighting in ["equal", "inverse_vol"]:
            eq, weights = compute_rotation_equity(histories, START, END, top_n=top_n, weighting=weighting)
            m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
            print(f"Top{top_n} {weighting}:", m, flush=True)
            results.append({"top_n": top_n, "weighting": weighting, "overlay": "none", **m})

            # 위험균등 버전도 무레버리지 변동성타게팅까지 함께 확인
            rot_ret = eq.pct_change().fillna(0.0)
            for target_vol in [12.0, 15.0]:
                scale = vol_target_scale(rot_ret, target_vol, 1.0)
                scaled_ret = rot_ret * scale.shift(1).fillna(1.0)
                m2, _ = metrics_from_returns(scaled_ret)
                print(f"  + vol-target({target_vol}):", m2, flush=True)
                results.append({"top_n": top_n, "weighting": weighting, "overlay": f"vt{target_vol}", **m2})

    res_df = pd.DataFrame(results)
    res_df.to_csv(f"{OUT_DIR}/momentum_riskparity_results.csv", index=False, encoding="utf-8-sig")
    print("\n=== 요약 (샤프 내림차순) ===")
    print(res_df.sort_values("sharpe", ascending=False).to_string())
    print(f"\nS&P500: cagr={bench.metrics['cagr']}, mdd={bench.metrics['mdd']}, sharpe={bench.metrics['sharpe']}")
    print("DONE")


if __name__ == "__main__":
    main()
