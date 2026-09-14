"""17자산 챔피언의 랭킹 신호를 raw momentum vs risk-adjusted momentum으로 바꿔가며 비교하는
재사용 모듈. `champion_strategy.py`(작업22/23 스펙 재구현체)의 유니버스/리밸런싱/시장필터/비용
로직은 그대로 두고, 매월 top-4를 뽑는 랭킹 신호만 교체한다.

랭킹 신호 3종:
  - "raw":        trailing N일 총수익률 (기존 챔피언, close.pct_change(N))
  - "vol_scaled": trailing N일 총수익률 / (같은 N일 일간수익률 표준편차 * sqrt(252))
                  -- Barroso & Santa-Clara(2015, "Momentum has its Moments", JFE)와 유사한
                     변동성 스케일링 아이디어를 "랭킹 단계"에 적용한 변형(원 논문은 포지션 크기를
                     스케일링하지만, 여기서는 상대적 우선순위를 매기는 데 같은 비율을 쓴다).
  - "sortino":    trailing N일 총수익률 / (같은 N일 하방(음수)일간수익률만의 표준편차 * sqrt(252))
                  -- 상방 변동성은 페널티를 주지 않는 Sortino류 변형.

vol_lookback_days를 momentum_window와 별도로 줄 수 있어 "모멘텀은 12개월, 변동성은 더 짧은
창(예: 3개월)"같은 조합도 스윕 가능하다.
"""
from __future__ import annotations

import sys
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
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

RANKING_MODES = ("raw", "vol_scaled", "sortino")


def compute_ranking_signal(
    closes: pd.DataFrame,
    mode: str,
    momentum_window: int = MOMENTUM_WINDOW,
    vol_lookback_days: int | None = None,
) -> pd.DataFrame:
    """모드별 랭킹 신호(값이 클수록 상위) 시계열을 반환한다. index/columns는 closes와 동일."""
    vol_window = vol_lookback_days or momentum_window
    raw_mom = closes.pct_change(momentum_window)
    if mode == "raw":
        return raw_mom

    daily_ret = closes.pct_change()
    if mode == "vol_scaled":
        vol = daily_ret.rolling(vol_window, min_periods=vol_window).std() * np.sqrt(252)
    elif mode == "sortino":
        downside = daily_ret.clip(upper=0.0)
        # rolling std of downside-only series (성과 없는 날의 0은 상방을 죽이지 않도록 그대로 두되,
        # 표준편차 계산에는 포함 - 흔히 쓰는 실무적 Sortino 근사: 상방 0-clip 값은 분산을 낮춰줌)
        vol = downside.rolling(vol_window, min_periods=vol_window).std() * np.sqrt(252)
    else:
        raise ValueError(f"unknown mode: {mode}")

    vol_safe = vol.replace(0.0, np.nan)
    return raw_mom / vol_safe


def build_weights_with_ranking(
    closes: pd.DataFrame,
    market_close: pd.Series,
    ranking_mode: str = "raw",
    top_n: int = TOP_N,
    momentum_window: int = MOMENTUM_WINDOW,
    vol_lookback_days: int | None = None,
    apply_market_filter: bool = True,
) -> pd.DataFrame:
    """champion_strategy.build_champion_weights와 동일한 구조 - 랭킹 신호만 compute_ranking_signal
    로 교체. 절대모멘텀 통과 조건(raw_mom > 0)은 신호 종류와 무관하게 raw momentum 부호로 고정
    (risk-adjusted 신호는 음수 raw momentum에서도 낮은 변동성이면 비율이 양수가 될 수 있어, 신호
    자체가 아니라 항상 raw momentum으로 절대모멘텀 게이트를 건다 - 챔피언 원 스펙과의 유일한 차이를
    "랭킹 순서"로만 국한하기 위한 설계 선택)."""
    raw_mom = closes.pct_change(momentum_window)
    ranking = compute_ranking_signal(closes, ranking_mode, momentum_window, vol_lookback_days)

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
    vol_lookback_days: int | None = None,
    cost_bps_per_side: float = COST_BPS_PER_SIDE,
    extra_warmup_days: int = 0,
) -> dict:
    """지정 구간·유니버스·랭킹모드로 챔피언 변형을 실행하고 지표+수익률을 반환."""
    tickers = list(tickers or CHAMPION_UNIVERSE)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + extra_warmup_days)).date().isoformat()
    histories = fetch_champion_histories(fetch_start, end, tickers)
    closes_all = _closes_from_histories(histories, tickers + [MARKET_FILTER_TICKER])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    market_close = closes_all[MARKET_FILTER_TICKER]

    weights_full = build_weights_with_ranking(
        closes, market_close, ranking_mode=ranking_mode, top_n=top_n,
        momentum_window=momentum_window, vol_lookback_days=vol_lookback_days,
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
