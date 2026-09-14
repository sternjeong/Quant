"""S&P500 + 미국 10대 섹터 대표 종목에 코스톨라니 달걀 이론 매매 시나리오를 돌려
전략 vs 매수보유 vs S&P500 벤치마크 성과를 비교한다.

core.kostolany_scenario_engine의 기존 함수를 그대로 재사용한다(신규 계산 로직 없음).
"""
import json
import sys
from datetime import date

sys.path.insert(0, "/workspaces/Quant")

import pandas as pd

from core.kostolany_scenario_engine import (
    compute_broad_universe_scenario_runs,
    run_ticker_scenario,
    scenario_runs_to_summary_df,
)

SECTORS = {
    "반도체": ["NVDA", "TSM", "AVGO", "AMD", "QCOM"],
    "커뮤니케이션서비스": ["META", "GOOGL", "NFLX", "T", "VZ"],
    "소프트웨어/클라우드": ["MSFT", "ORCL", "CRM", "ADBE", "NOW"],
    "금융/은행": ["JPM", "BAC", "WFC", "GS", "MS"],
    "헬스케어": ["UNH", "JNJ", "LLY", "PFE", "ABBV"],
    "에너지": ["XOM", "CVX", "COP", "SLB", "EOG"],
    "임의소비재": ["AMZN", "TSLA", "HD", "MCD", "NKE"],
    "필수소비재": ["PG", "KO", "PEP", "WMT", "COST"],
    "산업재": ["BA", "CAT", "GE", "HON", "UPS"],
    "리츠/부동산": ["PLD", "AMT", "EQIX", "SPG", "O"],
}
INDEX_TICKER = "^GSPC"
INDEX_LABEL = "S&P500"

TICKER_TO_SECTOR = {t: sector for sector, tickers in SECTORS.items() for t in tickers}
ALL_SECTOR_TICKERS = [t for tickers in SECTORS.values() for t in tickers]

START = "2015-01-01"
END = None
STYLES = ["장기", "스윙"]

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"


def main():
    all_results = {}
    equity_curves = {}  # style -> {label: {"strategy":..., "bh":..., "bench":...}} (for plotting, only a subset saved)

    for style in STYLES:
        print(f"=== style={style}: fetching + backtesting {len(ALL_SECTOR_TICKERS)} tickers ===", flush=True)
        runs = compute_broad_universe_scenario_runs(
            ALL_SECTOR_TICKERS, style=style, start=START, end=END
        )
        print(f"  got {len(runs)}/{len(ALL_SECTOR_TICKERS)} runs", flush=True)

        index_run = run_ticker_scenario(INDEX_TICKER, style=style, start=START, end=END)
        runs[INDEX_LABEL] = index_run

        summary = scenario_runs_to_summary_df(runs, style=style)
        summary["sector"] = summary["theme"].map(lambda t: TICKER_TO_SECTOR.get(t, INDEX_LABEL))
        all_results[style] = summary

        # 대표 자산곡선 저장 (전체 티커, plotting 단계에서 선별)
        curves = {}
        for label, run in runs.items():
            curves[label] = {
                "strategy": run.equity_curve,
                "bh": run.buy_and_hold_equity_curve,
                "bench": run.benchmark_equity_curve,
            }
        equity_curves[style] = curves

        summary.to_csv(f"{OUT_DIR}/summary_{style}.csv", index=False, encoding="utf-8-sig")
        print(summary[["theme", "sector", "cumulative_return", "cagr", "mdd", "sharpe", "win_rate", "trade_count", "excess_return", "excess_return_vs_benchmark"]].to_string(), flush=True)

    # equity curve pickle (다음 단계에서 차트 생성용)
    import pickle
    with open(f"{OUT_DIR}/equity_curves.pkl", "wb") as f:
        pickle.dump(equity_curves, f)

    with open(f"{OUT_DIR}/sectors.json", "w", encoding="utf-8") as f:
        json.dump({"sectors": SECTORS, "index_ticker": INDEX_TICKER, "index_label": INDEX_LABEL,
                    "start": START, "generated": date.today().isoformat()}, f, ensure_ascii=False, indent=2)

    print("DONE", flush=True)


if __name__ == "__main__":
    main()
