"""모멘텀 섹터 로테이션(momentum_rotation.py로 재구현한 No.05 전략)의 일별 수익률 자체에
포트폴리오 레벨 변동성 타게팅을 얹는다 — 코스톨라니 리포트(No.04) 07장에서 검증한 것과 동일한
기법을 다른 전략에 적용해보는 것(사용자 요청: "분산+변동성관리를 기점으로 연구를 이어서").
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import pickle
import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"


def main():
    with open(f"{OUT_DIR}/momentum_rotation_extended.pkl", "rb") as f:
        data = pickle.load(f)

    eq = data["eq"]
    bench_eq = data["bench_eq"].reindex(eq.index).ffill()
    rotation_ret = eq.pct_change().fillna(0.0)
    bench_ret = bench_eq.pct_change().fillna(0.0)

    print("=== 오버레이 없음(기준) ===")
    print("모멘텀 로테이션:", data["rotation_metrics"])
    print("S&P500 매수보유:", data["bench_metrics"])

    results = []
    curves = {}
    for target_vol in [10.0, 12.0, 15.0, 18.0]:
        for cap in [1.0, 1.3, 1.5]:
            scale = vol_target_scale(rotation_ret, target_vol, cap)
            scaled_ret = rotation_ret * scale.shift(1).fillna(1.0)
            m, e = metrics_from_returns(scaled_ret)
            results.append({"target_vol": target_vol, "cap": cap, **m})
            curves[(target_vol, cap)] = e

    res_df = pd.DataFrame(results)
    res_df.to_csv(f"{OUT_DIR}/momentum_rotation_vol_target_results.csv", index=False, encoding="utf-8-sig")
    print("\n=== 모멘텀 로테이션 + 변동성타게팅 스윕 (샤프 내림차순) ===")
    print(res_df.sort_values("sharpe", ascending=False).to_string())

    # 무레버리지(cap=1.0) 최선 조합 선택
    no_lev = res_df[res_df["cap"] == 1.0].sort_values("sharpe", ascending=False).iloc[0]
    print("\n무레버리지(cap=1.0) 최선:", no_lev.to_dict())

    best_tv, best_cap = float(no_lev["target_vol"]), 1.0
    scale = vol_target_scale(rotation_ret, best_tv, best_cap)
    scaled_ret = rotation_ret * scale.shift(1).fillna(1.0)
    m_final, eq_final = metrics_from_returns(scaled_ret)

    eq_w = eq_final.resample("W-FRI").last().dropna()
    rotation_w = eq.resample("W-FRI").last().dropna()
    bench_w = bench_eq.resample("W-FRI").last().dropna()
    common = eq_w.index.intersection(rotation_w.index).intersection(bench_w.index)

    import json
    with open(f"{OUT_DIR}/momentum_rotation_vol_target_final.json", "w", encoding="utf-8") as f:
        json.dump({
            "vol_targeted": m_final,
            "no_overlay": data["rotation_metrics"],
            "sp500_bh": data["bench_metrics"],
            "params": {"target_vol": best_tv, "cap": best_cap},
        }, f, ensure_ascii=False, indent=2)

    with open(f"{OUT_DIR}/momentum_rotation_vol_target_curves.json", "w", encoding="utf-8") as f:
        json.dump({
            "dates": [d.strftime("%Y-%m-%d") for d in common],
            "strategy": [round(float(v), 2) for v in eq_w.loc[common]],
            "bh": [round(float(v), 2) for v in rotation_w.loc[common]],
            "bench": [round(float(v), 2) for v in bench_w.loc[common]],
        }, f, ensure_ascii=False)

    print("\n최종 채택:", m_final)
    print("DONE")


if __name__ == "__main__":
    main()
