"""감사 1 - IREN 추세추종 챔피언(작업27)의 통계적 유의성, 블록부트스트랩 신뢰구간으로 재감사.

작업27이 채택한 챔피언(20일 돈치안 브레이크아웃 + 15% 트레일링스탑)은 작업32(H3, 트랙D)에서 셔플
순열검정(200회)만 받았다 — 바스켓은 93번째 백분위(p≈0.075, 5% 문턱 미달), IREN 단일종목은 100번째
백분위(p≈0.005). 순열검정은 "우연한 신호 대비 얼마나 특별한가"를 보여주지만, "그 샤프비율 자체가
표본오차로 얼마나 흔들리는가"는 별개 질문이다 — 트랙D H33/H34가 정확히 이 갭을 메웠던 방식(원형
이동블록부트스트랩)을 그대로 재사용해 여기에도 적용한다.

방법론:
  1. common.py/backtest.py의 로직을 그대로 재사용(donchian_trailing_stop_positions, run_trend_following_
     single/basket)해서 원본과 동일한 조건(entry_window=20, stop_pct=0.15, 공통시작일, 왕복 0.1% 비용)
     으로 IREN 단일종목·6종목 바스켓의 일별 전략수익률 시계열을 복원한다.
  2. h33_block_bootstrap_sample_error.moving_block_bootstrap_sharpe와 완전히 동일한 함수(순환 wrap-
     around 이동블록부트스트랩, L=10/20/40일, 2000회)를 그대로 재사용해 각각의 샤프비율 표본분포를
     만든다.
  3. 신뢰구간 폭, 그리고 "샤프<=0"이 되는 표본 비율(신뢰도 프록시)을 보고한다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
IREN_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-16_iren_volatile_momentum_stocks"
sys.path.insert(0, str(IREN_DIR))
BOOT_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_block_bootstrap_sample_error_quantification"
sys.path.insert(0, str(BOOT_DIR))

import numpy as np
import pandas as pd

from common import PIVOT_BASKET, END, load_histories, closes_frame
from backtest import (
    find_common_start,
    run_trend_following_single,
    run_trend_following_basket,
)
from h33_block_bootstrap_sample_error import moving_block_bootstrap_sharpe, annualized_sharpe

OUT_DIR = Path(__file__).resolve().parent
ENTRY_WINDOW = 20
STOP_PCT = 0.15  # 작업27이 채택한 챔피언 스탑폭
MOM_WINDOW = 126  # 원본과 동일한 웜업 정의(공통시작일 산출용)
BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
SEED = 20260830


def log(msg):
    print(f"[audit1] {msg}", flush=True)


def strategy_daily_returns(close: pd.Series, start: pd.Timestamp, entry_window: int, stop_pct: float) -> pd.Series:
    """run_trend_following_single과 동일한 신호/집행 로직에서 '일별 전략수익률 시계열'만 추출."""
    from backtest import donchian_trailing_stop_positions
    from common import COST_RATE
    position = donchian_trailing_stop_positions(close, entry_window, stop_pct)
    sliced_close = close[close.index >= start]
    pos_sliced = position.loc[sliced_close.index]
    daily_ret = sliced_close.pct_change().fillna(0.0)
    executed = pos_sliced.shift(1).fillna(0).astype(float)
    turnover = executed.diff().abs().fillna(0.0)
    strat_ret = daily_ret * executed - turnover * COST_RATE
    return strat_ret


def basket_daily_returns(closes: pd.DataFrame, start: pd.Timestamp, entry_window: int, stop_pct: float) -> pd.Series:
    from backtest import donchian_trailing_stop_positions
    from common import COST_RATE, cost_series
    positions = pd.DataFrame({t: donchian_trailing_stop_positions(closes[t].dropna(), entry_window, stop_pct)
                               for t in closes.columns})
    positions = positions.reindex(closes.index).fillna(0).astype(int)
    n_active = positions.sum(axis=1).replace(0, np.nan)
    weights = positions.div(n_active, axis=0).fillna(0.0)
    sliced_closes = closes[closes.index >= start]
    w = weights.loc[sliced_closes.index]
    daily_ret = sliced_closes.pct_change().fillna(0.0)
    executed_w = w.shift(1).fillna(0.0)
    port_ret = (daily_ret * executed_w).sum(axis=1)
    cost = cost_series(executed_w)
    return port_ret - cost


def summarize_boot(ret: pd.Series, rng: np.random.Generator) -> dict:
    arr = ret.values.astype(float)
    point = annualized_sharpe(arr)
    by_block = {}
    for L in BLOCK_LENGTHS:
        boot = moving_block_bootstrap_sharpe(arr, L, N_BOOT, rng)
        boot = boot[~np.isnan(boot)]
        by_block[str(L)] = {
            "block_len": L,
            "n_boot_valid": int(len(boot)),
            "n_nonoverlapping_blocks_approx": round(len(arr) / L, 1),
            "mean": float(np.mean(boot)),
            "std": float(np.std(boot)),
            "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))],
            "ci50": [float(np.percentile(boot, 25)), float(np.percentile(boot, 75))],
            "pct_le_zero": float(np.mean(boot <= 0.0)),
            "pct_le_point_est_half": float(np.mean(boot <= point * 0.5)),
        }
    return {
        "n_obs": int(len(arr)),
        "point_estimate_sharpe": point,
        "bootstrap_by_block_len": by_block,
    }


def main():
    t0 = time.time()
    log("가격 데이터 로딩...")
    hist = load_histories(PIVOT_BASKET)
    closes_all = closes_frame(hist)
    closes_main = closes_all[PIVOT_BASKET].dropna(how="all")
    common_start = find_common_start(closes_main, MOM_WINDOW)
    log(f"공통 시작일: {common_start.date()}")

    iren_close = closes_all["IREN"].dropna()
    iren_ret = strategy_daily_returns(iren_close, common_start, ENTRY_WINDOW, STOP_PCT)
    basket_ret = basket_daily_returns(closes_main, common_start, ENTRY_WINDOW, STOP_PCT)

    iren_ret.to_csv(OUT_DIR / "iren_single_trend_ret.csv", header=["ret"])
    basket_ret.to_csv(OUT_DIR / "basket_trend_ret.csv", header=["ret"])

    rng = np.random.default_rng(SEED)
    result = {
        "meta": {
            "entry_window": ENTRY_WINDOW, "stop_pct": STOP_PCT, "common_start": str(common_start.date()),
            "end": END, "n_boot": N_BOOT, "block_lengths": BLOCK_LENGTHS, "seed": SEED,
            "basket": PIVOT_BASKET,
        },
        "iren_single": summarize_boot(iren_ret, rng),
        "basket": summarize_boot(basket_ret, rng),
    }
    log(f"IREN 단일: point={result['iren_single']['point_estimate_sharpe']:.3f}, "
        f"L20 CI90={result['iren_single']['bootstrap_by_block_len']['20']['ci90']}")
    log(f"바스켓  : point={result['basket']['point_estimate_sharpe']:.3f}, "
        f"L20 CI90={result['basket']['bootstrap_by_block_len']['20']['ci90']}")

    (OUT_DIR / "audit1_results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"저장 완료 ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
