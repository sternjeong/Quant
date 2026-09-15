"""H(문헌대조) - Novy-Marx(2012)/Jegadeesh-Titman(1993) "12-2" 관행(최근 1개월 제외) 재현.

analysis/2026-08-30_risk_adjusted_momentum_ranking/risk_adjusted_champion.py 의 구조를 그대로
따르되, 랭킹 신호에 "raw_skip1m" 모드를 추가한다:

  - "raw":         close.pct_change(momentum_window)                      (기존 챔피언, 252일 그대로)
  - "raw_skip1m":  close.shift(skip_days).pct_change(momentum_window - skip_days)
                   즉 t-12개월~t-1개월 구간 누적수익률로 랭킹하고, 가장 최근 1개월(21거래일)은
                   신호 계산에서 제외한다 - Jegadeesh & Titman(1993)이 쓰기 시작해 이후 momentum
                   문헌의 표준이 된 "12-2" 관행, Novy-Marx(2012)가 "최근월 제외가 모멘텀 수익을
                   개선시킨다"고 명시적으로 재확인.

절대모멘텀 게이트(양수 여부)는 원 스크립트와 동일하게 항상 raw(스킵 없는) 12개월 모멘텀 부호로
고정한다 - 신호 종류 차이를 "랭킹 순서"로만 국한하기 위한 설계를 그대로 계승.
"""
from __future__ import annotations

import sys
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant/.claude/worktrees/agent-ab5b3cdcd18a01aae"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))

import numpy as np
import pandas as pd

from core.backtest_engine import _first_trading_day_of_month_mask, calculate_metrics
from champion_strategy import (  # noqa: E402
    CHAMPION_UNIVERSE, MARKET_FILTER_TICKER, MARKET_FILTER_MA, MARKET_FILTER_SCALE_BELOW,
    MOMENTUM_WINDOW, TOP_N, COST_BPS_PER_SIDE, WARMUP_DAYS,
    fetch_champion_histories, _closes_from_histories, compute_portfolio_returns,
)

SKIP_DAYS = 21  # 약 1개월(거래일 기준) - Jegadeesh & Titman(1993)/Novy-Marx(2012) "12-2" 관행


def compute_ranking_signal(
    closes: pd.DataFrame,
    mode: str,
    momentum_window: int = MOMENTUM_WINDOW,
    skip_days: int = SKIP_DAYS,
) -> pd.DataFrame:
    if mode == "raw":
        return closes.pct_change(momentum_window)
    if mode == "raw_skip1m":
        # t-12개월~t-1개월 누적수익률: 21거래일 전 종가를 기준으로 (window-skip)일 수익률을 계산
        shifted = closes.shift(skip_days)
        return shifted.pct_change(momentum_window - skip_days)
    raise ValueError(f"unknown mode: {mode}")


def build_weights_with_ranking(
    closes: pd.DataFrame,
    market_close: pd.Series,
    ranking_mode: str = "raw",
    top_n: int = TOP_N,
    momentum_window: int = MOMENTUM_WINDOW,
    skip_days: int = SKIP_DAYS,
    apply_market_filter: bool = True,
) -> pd.DataFrame:
    raw_mom = closes.pct_change(momentum_window)  # 절대모멘텀 게이트는 항상 스킵 없는 raw 부호
    ranking = compute_ranking_signal(closes, ranking_mode, momentum_window, skip_days)

    is_rebal = _first_trading_day_of_month_mask(closes.index)
    sma200 = market_close.rolling(MARKET_FILTER_MA, min_periods=MARKET_FILTER_MA).mean()

    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_weights = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]
            gate = raw_mom.loc[signal_date] > 0
            rank_vals = ranking.loc[signal_date][gate].dropna().sort_values(ascending=False)
            picks = rank_vals.index[:top_n]
            w = pd.Series(0.0, index=closes.columns)
            if len(picks) > 0:
                w[picks] = 1.0 / top_n
            if apply_market_filter and signal_date in sma200.index and not pd.isna(sma200.loc[signal_date]):
                if market_close.loc[signal_date] < sma200.loc[signal_date]:
                    w = w * MARKET_FILTER_SCALE_BELOW
            last_weights = w
        weights.iloc[i] = last_weights.values
    return weights


def run_variant(
    start: str,
    end: str,
    tickers: list[str] | None = None,
    ranking_mode: str = "raw",
    top_n: int = TOP_N,
    momentum_window: int = MOMENTUM_WINDOW,
    skip_days: int = SKIP_DAYS,
    cost_bps_per_side: float = COST_BPS_PER_SIDE,
    extra_warmup_days: int = 0,
) -> dict:
    tickers = list(tickers or CHAMPION_UNIVERSE)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + extra_warmup_days)).date().isoformat()
    histories = fetch_champion_histories(fetch_start, end, tickers)
    closes_all = _closes_from_histories(histories, tickers + [MARKET_FILTER_TICKER])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    market_close = closes_all[MARKET_FILTER_TICKER]

    weights_full = build_weights_with_ranking(
        closes, market_close, ranking_mode=ranking_mode, top_n=top_n,
        momentum_window=momentum_window, skip_days=skip_days,
    )

    sliced_idx = closes.index[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
    closes_sliced = closes.loc[sliced_idx]
    weights_sliced = weights_full.loc[sliced_idx]

    result = compute_portfolio_returns(closes_sliced, weights_sliced, cost_bps_per_side=cost_bps_per_side)
    metrics = calculate_metrics(result["equity_net"], [], sliced_idx[0], sliced_idx[-1])
    return {
        "start": str(sliced_idx[0].date()) if len(sliced_idx) else start,
        "end": str(sliced_idx[-1].date()) if len(sliced_idx) else end,
        "metrics": metrics,
        "ret_net": result["ret_net"],
        "n_days": int(len(sliced_idx)),
    }
