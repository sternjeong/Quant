"""H3 - 콜라 노셔널을 바스켓의 실측 시장베타로 스케일링하면 1배(순진한 SPY 1:1) 사이징보다 나은가.

배경: h1/h2가 쓴 1배 노셔널은 "바스켓 1달러당 SPY 콜라 1달러"라는 임의 기준이다. 하지만 작업28
(iren_beta_alpha_hedging_research)이 이미 실측한 이 바스켓의 시장베타는 1.5~3배(개별 종목 평균
롤링베타 약 2.5~3배) - SPY 대비 훨씬 변동성이 크고 SPY와 같이 움직이는 성분도 그만큼 크다는 뜻이다.
1배 노셔널 콜라는 이 바스켓의 실제 "SPY-등가 익스포저"를 구조적으로 과소헤지한다는 가설을 세우고,
같은 콜라 오버레이 수익률 시리즈에 스케일 인자만 바꿔가며(0.5~4.0배 스윕 + 실측 정적베타) 재현한다.

방법론: 새 옵션가격 로직을 만들지 않는다 - h1/h2가 이미 계산한 콜라 오버레이 수익률(overlay_ret,
SPY 100% 노셔널 기준)에 스칼라만 곱해 더한다. 이는 core.champion_strategy.run_champion_backtest_
with_collar가 이미 satellite_weight를 이 방식으로 곱하는 것과 동일한 컨벤션(오버레이 계약 수량을
비례 조정)이다. 정적베타는 iren_beta_alpha_hedging_research/common.py의 one_factor_ols를 그대로
재사용해 계산한다.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from hedge_common import OUT_DIR, END, metrics_from_ret
import importlib.util
from pathlib import Path

BETA_DIR = Path(__file__).resolve().parents[1] / "2026-08-19_iren_beta_alpha_hedging"
_spec = importlib.util.spec_from_file_location("beta_hedge_common", BETA_DIR / "common.py")
_beta_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_beta_common)
fetch_close = _beta_common.fetch_close
daily_returns = _beta_common.daily_returns
align = _beta_common.align
one_factor_ols = _beta_common.one_factor_ols

SWEEP_WEIGHTS = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]


def log(msg):
    print(f"[h3] {msg}", flush=True)


def load_series(label: str) -> tuple[pd.Series, pd.Series]:
    base = pd.read_csv(OUT_DIR / f"{label}_unhedged_ret.csv", index_col=0, parse_dates=True)["ret"]
    overlay = pd.read_csv(OUT_DIR / f"{label}_collar_overlay_ret.csv", index_col=0, parse_dates=True)["ret"]
    return base, overlay


def compute_static_beta(label: str, base_ret: pd.Series) -> dict:
    """base_ret(바스켓/전략 수익률) vs SPY 일간수익률 정적 OLS 베타."""
    start = base_ret.index[0].date().isoformat()
    spy_close = fetch_close("SPY", start, END)
    spy_ret = daily_returns(spy_close)
    r_strat, r_mkt = align(base_ret, spy_ret)
    if len(r_strat) < 60:
        return {"beta": None, "r2": None, "n": len(r_strat)}
    alpha, beta, r2 = one_factor_ols(r_strat.values, r_mkt.values)
    return {"beta": round(beta, 3), "alpha_ann": round(alpha * 252, 4), "r2": round(r2, 3), "n": int(len(r_strat))}


def sweep_one(label: str) -> dict:
    base_ret, overlay_ret = load_series(label)
    beta_info = compute_static_beta(label, base_ret)
    weights = sorted(set(SWEEP_WEIGHTS + ([beta_info["beta"]] if beta_info["beta"] else [])))
    rows = []
    for w in weights:
        if w < 0:
            continue
        combined = base_ret + overlay_ret.reindex(base_ret.index).fillna(0.0) * w
        m = metrics_from_ret(combined)
        rows.append({"weight": round(w, 3), "is_beta_estimate": beta_info["beta"] is not None and abs(w - beta_info["beta"]) < 1e-9, **m})
    rows_sorted_by_sharpe = sorted(rows, key=lambda r: r["sharpe"], reverse=True)
    return {
        "label": label, "static_beta": beta_info, "sweep": rows,
        "best_by_sharpe": rows_sorted_by_sharpe[0],
        "unhedged_sharpe": next(r["sharpe"] for r in rows if r["weight"] == 0.0),
    }


def main():
    results = {}
    for label in ["basket_bh", "basket_trend", "iren_bh", "iren_trend"]:
        log(f"스윕: {label}")
        res = sweep_one(label)
        results[label] = res
        log(f"  정적베타={res['static_beta']} / 최선(샤프기준)={res['best_by_sharpe']}")

    out = {"meta": {"generated": END, "sweep_weights": SWEEP_WEIGHTS}, "h3_results": results}
    with open(OUT_DIR / "h3_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    log("저장 완료: h3_results.json")


if __name__ == "__main__":
    main()
