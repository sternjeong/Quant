"""summary_*.csv + equity_curves.pkl을 읽어 리포트용 JSON(집계 통계 + 선별 자산곡선)을 만든다."""
import json
import pickle
import sys

sys.path.insert(0, "/workspaces/Quant")
import numpy as np
import pandas as pd

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
STYLES = ["장기", "스윙"]

with open(f"{OUT_DIR}/sectors.json", encoding="utf-8") as f:
    meta = json.load(f)

SECTOR_ORDER = list(meta["sectors"].keys())


def load(style):
    df = pd.read_csv(f"{OUT_DIR}/summary_{style}.csv")
    df["excess_cagr"] = (df["cagr"] - df["bh_cagr"]).round(2)
    df["excess_cagr_vs_bench"] = (df["cagr"] - df["bench_cagr"]).round(2)
    df["mdd_improvement"] = (df["mdd"] - df["bh_mdd"]).round(2)  # 양수면 낙폭이 더 얕음(개선)
    df["beats_bh"] = df["cumulative_return"] > df["bh_cumulative_return"]
    df["beats_bench"] = df["cumulative_return"] > df["bench_cumulative_return"]
    return df


data = {style: load(style) for style in STYLES}

report = {"meta": meta, "styles": {}}

for style, df in data.items():
    sector_rows = df[df["sector"] != "S&P500"]
    index_row = df[df["sector"] == "S&P500"].iloc[0]

    overall = {
        "n": int(len(sector_rows)),
        "win_rate_vs_bh_pct": round(100 * sector_rows["beats_bh"].mean(), 1),
        "win_rate_vs_bench_pct": round(100 * sector_rows["beats_bench"].mean(), 1),
        "median_excess_cagr": round(float(sector_rows["excess_cagr"].median()), 2),
        "mean_excess_cagr": round(float(sector_rows["excess_cagr"].mean()), 2),
        "median_excess_cagr_vs_bench": round(float(sector_rows["excess_cagr_vs_bench"].median()), 2),
        "avg_strategy_cagr": round(float(sector_rows["cagr"].mean()), 2),
        "avg_bh_cagr": round(float(sector_rows["bh_cagr"].mean()), 2),
        "avg_strategy_mdd": round(float(sector_rows["mdd"].mean()), 2),
        "avg_bh_mdd": round(float(sector_rows["bh_mdd"].mean()), 2),
        "avg_strategy_sharpe": round(float(sector_rows["sharpe"].mean()), 2),
        "index_cagr_strategy": float(index_row["cagr"]),
        "index_cagr_bh": float(index_row["bh_cagr"]),
        "index_mdd_strategy": float(index_row["mdd"]),
        "index_mdd_bh": float(index_row["bh_mdd"]),
        "index_sharpe_strategy": float(index_row["sharpe"]),
        "index_excess_cagr": round(float(index_row["cagr"] - index_row["bh_cagr"]), 2),
    }

    sector_agg = []
    for sector in SECTOR_ORDER:
        rows = sector_rows[sector_rows["sector"] == sector]
        sector_agg.append({
            "sector": sector,
            "tickers": rows["theme"].tolist(),
            "avg_cagr_strategy": round(float(rows["cagr"].mean()), 2),
            "avg_cagr_bh": round(float(rows["bh_cagr"].mean()), 2),
            "avg_cagr_bench": round(float(rows["bench_cagr"].mean()), 2),
            "avg_mdd_strategy": round(float(rows["mdd"].mean()), 2),
            "avg_mdd_bh": round(float(rows["bh_mdd"].mean()), 2),
            "avg_sharpe_strategy": round(float(rows["sharpe"].mean()), 2),
            "win_count_vs_bh": int(rows["beats_bh"].sum()),
            "win_count_vs_bench": int(rows["beats_bench"].sum()),
            "n": int(len(rows)),
            "avg_excess_cagr": round(float(rows["excess_cagr"].mean()), 2),
        })

    ticker_rows = []
    for _, r in df.iterrows():
        ticker_rows.append({
            "ticker": r["theme"], "sector": r["sector"],
            "cagr": round(float(r["cagr"]), 2), "bh_cagr": round(float(r["bh_cagr"]), 2),
            "bench_cagr": round(float(r["bench_cagr"]), 2),
            "mdd": round(float(r["mdd"]), 2), "bh_mdd": round(float(r["bh_mdd"]), 2),
            "sharpe": round(float(r["sharpe"]), 2), "win_rate": round(float(r["win_rate"]), 1),
            "trade_count": int(r["trade_count"]), "excess_cagr": round(float(r["excess_cagr"]), 2),
            "excess_cagr_vs_bench": round(float(r["excess_cagr_vs_bench"]), 2),
            "cumulative_return": round(float(r["cumulative_return"]), 1),
            "bh_cumulative_return": round(float(r["bh_cumulative_return"]), 1),
            "beats_bh": bool(r["beats_bh"]), "beats_bench": bool(r["beats_bench"]),
        })
    ticker_rows.sort(key=lambda x: x["excess_cagr"], reverse=True)

    report["styles"][style] = {"overall": overall, "sector_agg": sector_agg, "tickers": ticker_rows}

# --- 선별 자산곡선 (장기 스타일만, 스토리텔링용 대표 사례) ---
with open(f"{OUT_DIR}/equity_curves.pkl", "rb") as f:
    curves = pickle.load(f)

df_long = data["장기"]
sector_rows_long = df_long[df_long["sector"] != "S&P500"]
best = sector_rows_long.loc[sector_rows_long["excess_cagr"].idxmax(), "theme"]
worst = sector_rows_long.loc[sector_rows_long["excess_cagr"].idxmin(), "theme"]
# 방어적 사례: 낙폭도 얕아지고 CAGR도 매수보유를 넘어선(둘 다 개선된) 종목 = T(AT&T)
defensive = "T"

selected = {"S&P500": "S&P500", "best": best, "worst": worst, "defensive": defensive}
print("Selected representative tickers:", selected)

equity_export = {}
for key, ticker in selected.items():
    c = curves["장기"][ticker]
    strat, bh, bench = c["strategy"], c["bh"], c["bench"]
    idx = strat.index
    # 주간(금요일) 다운샘플로 payload 축소
    strat_w = strat.resample("W-FRI").last().dropna()
    bh_w = bh.reindex(strat.index).resample("W-FRI").last().dropna()
    bench_w = bench.reindex(strat.index).resample("W-FRI").last().dropna()
    common_idx = strat_w.index.intersection(bh_w.index).intersection(bench_w.index)
    equity_export[key] = {
        "ticker": ticker,
        "dates": [d.strftime("%Y-%m-%d") for d in common_idx],
        "strategy": [round(float(v), 2) for v in strat_w.loc[common_idx]],
        "bh": [round(float(v), 2) for v in bh_w.loc[common_idx]],
        "bench": [round(float(v), 2) for v in bench_w.loc[common_idx]],
    }

report["equity_examples"] = equity_export
report["selected_labels"] = selected

with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False)

print("overall 장기:", json.dumps(report["styles"]["장기"]["overall"], ensure_ascii=False, indent=2))
print("overall 스윙:", json.dumps(report["styles"]["스윙"]["overall"], ensure_ascii=False, indent=2))
print("sector_agg 장기:")
for s in report["styles"]["장기"]["sector_agg"]:
    print(" ", s)
print("json size bytes:", len(json.dumps(report, ensure_ascii=False)))
