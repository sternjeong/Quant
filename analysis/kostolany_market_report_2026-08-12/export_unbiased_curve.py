import sys
sys.path.insert(0, "/workspaces/Quant")
import json
import pickle

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"

with open(f"{OUT_DIR}/momentum_rotation_unbiased_curves.pkl", "rb") as f:
    data = pickle.load(f)

curves = data["curves"]
bench_eq = data["bench_eq"]

top15_none = curves["top15_none"]
bench_w = bench_eq.reindex(top15_none.index).resample("W-FRI").last().dropna()
top15_w = top15_none.resample("W-FRI").last().dropna()
common = top15_w.index.intersection(bench_w.index)

out = {
    "dates": [d.strftime("%Y-%m-%d") for d in common],
    "strategy": [round(float(v), 2) for v in top15_w.loc[common]],
    "bh": [round(float(v), 2) for v in top15_w.loc[common]],
    "bench": [round(float(v), 2) for v in bench_w.loc[common]],
}
with open(f"{OUT_DIR}/momentum_rotation_unbiased_equity.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)

print("saved, points:", len(common), "ok_tickers:", len(data["ok_tickers"]), "sample:", len(data["sample"]))
