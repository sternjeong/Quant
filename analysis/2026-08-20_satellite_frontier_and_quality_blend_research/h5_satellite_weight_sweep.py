"""H5 — 새틀라이트 비중 프런티어.

작업30 H1은 point-in-time 개별주 새틀라이트를 트랙B 17자산 챔피언에 10%/20%만 얹어봤다(둘 다 샤프
개선, 챔피언 단독 1.03 -> 10% 1.06 -> 20% 1.05). 이 스크립트는 H1과 정확히 같은 새틀라이트 구축
로직(point-in-time sample_universe, 반기 리밸런싱, 12개월 모멘텀 상위 3개)을 재사용하되, 새틀라이트
비중만 0%~50%로 촘촘히 스윕해서 샤프가 어디서 정점을 찍고 어디서부터 악화되는지 본다.

core/ 참고 주의사항: 이 워크트리(agent-a3cb7703ff189d4dd)는 point-in-time 시가총액 인프라(작업25,
core/point_in_time_market_cap.py)가 main에 올라오기 전 시점에서 분기되어 그 파일 자체가 없고,
core/strategy_tuning.py의 sample_universe()에도 use_point_in_time_market_cap 파라미터가 없다(구버전).
이 워크트리의 core/를 복사해서 언블록하는 대신(작업30이 명시적으로 경고한 실수), main 체크아웃
(/workspaces/Quant)의 core/를 sys.path 최상단에 꽂아 항상 "지금 main의" 코드를 그대로 참조한다 —
core/를 이 워크트리에 복사하거나 수정하지 않는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"  # 항상 최신 core/를 참조(이 워크트리의 core/는 구버전)
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))

OUT_DIR = Path(__file__).resolve().parent

import numpy as np
import pandas as pd

from champion_strategy import run_champion
from h1_core_satellite import build_satellite_returns, blend_returns
from core.backtest_engine import calculate_metrics

START, END = "2019-08-12", "2026-08-19"  # H1과 동일 기간(직접 비교 가능하도록)
SATELLITE_WEIGHTS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]


def log(msg):
    print(f"[h5] {msg}", flush=True)


def main():
    log(f"코어(17자산 챔피언) 실행: {START} ~ {END}")
    core = run_champion(START, END)
    trading_index = core["ret_net"].index
    log(f"코어 지표: {core['metrics']}")

    log("새틀라이트(point-in-time 반기 리밸런싱) 구축...")
    sat = build_satellite_returns(START, END, trading_index)
    log(f"새틀라이트 지표: {sat['metrics']}")

    frontier = []
    for sw in SATELLITE_WEIGHTS:
        if sw == 0.0:
            eq = core["equity_net"]
            m = core["metrics"]
        else:
            br = blend_returns(core["ret_net"], sat["ret_net"], sw)
            eq = (1 + br).cumprod() * 100.0
            eq.iloc[0] = 100.0
            m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
        frontier.append({"satellite_weight": sw, "metrics": m})
        log(f"  sw={sw:.2f}: sharpe={m['sharpe']:.3f} cagr={m['cagr']:.2f}% mdd={m['mdd']:.2f}% calmar={m['calmar']:.3f}")

    sharpes = [f["metrics"]["sharpe"] for f in frontier]
    peak_idx = int(np.argmax(sharpes))
    peak = frontier[peak_idx]

    # MDD가 샤프 개선 속도보다 빨리 악화되는지 보기 위한 참고 지표: 각 비중에서 코어 대비
    # 샤프 변화율(%) vs MDD 변화율(%) — MDD는 음수이므로 "악화"는 더 음수가 되는 쪽.
    core_sharpe = core["metrics"]["sharpe"]
    core_mdd = core["metrics"]["mdd"]
    for f in frontier:
        m = f["metrics"]
        f["sharpe_delta_vs_core"] = round(m["sharpe"] - core_sharpe, 4)
        f["mdd_delta_vs_core_pct_points"] = round(m["mdd"] - core_mdd, 2)

    result = {
        "period": {"start": START, "end": END},
        "methodology_note": "H1(2026-08-19)과 동일한 point-in-time 새틀라이트 구축 로직을 그대로 재사용, 비중만 0~50%로 스윕",
        "core_metrics": core["metrics"],
        "satellite_standalone_metrics": sat["metrics"],
        "satellite_rebal_log": sat["rebal_log"],
        "satellite_tickers_ever_held": sat["tickers_ever_held"],
        "frontier": frontier,
        "peak_sharpe_weight": peak["satellite_weight"],
        "peak_sharpe_metrics": peak["metrics"],
    }

    with open(OUT_DIR / "h5_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h5_results.json'}")
    log(f"샤프 정점: sw={peak['satellite_weight']} sharpe={peak['metrics']['sharpe']}")


if __name__ == "__main__":
    main()
