import sys
sys.path.insert(0, "/workspaces/Quant")
import json
import pickle

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"

with open(f"{OUT_DIR}/momentum_rotation_50universe_curves.pkl", "rb") as f:
    data = pickle.load(f)

curves = data["curves"]
bench_eq = data["bench_eq"]

top10_none = curves["top10_none"]
bench_w = bench_eq.reindex(top10_none.index).resample("W-FRI").last().dropna()
top10_w = top10_none.resample("W-FRI").last().dropna()
common = top10_w.index.intersection(bench_w.index)

out = {
    "dates": [d.strftime("%Y-%m-%d") for d in common],
    "strategy": [round(float(v), 2) for v in top10_w.loc[common]],
    # renderEquityLine은 bench(아쿠아)->bh(오렌지)->strategy(블루) 순서로 겹쳐 그린다. 실제로 보여줄
    # 두 선은 전략(블루, 항상 맨 위)과 S&P500(아쿠아)뿐이므로, bh는 전략과 동일한 값으로 둬서
    # strategy 밑에 완전히 가려지게 하고 bench(아쿠아)만 S&P500으로 남긴다(원래처럼 bh=bench로
    # 두면 오렌지가 아쿠아 위에 그려져 범례와 실제 색이 어긋난다).
    "bh": [round(float(v), 2) for v in top10_w.loc[common]],
    "bench": [round(float(v), 2) for v in bench_w.loc[common]],
}
with open(f"{OUT_DIR}/momentum_rotation_50universe_equity.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)

print("saved, points:", len(common))
