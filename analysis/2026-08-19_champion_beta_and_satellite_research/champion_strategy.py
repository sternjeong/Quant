"""17자산 듀얼모멘텀 섹터 로테이션 "챔피언" 전략의 재사용 가능한 재구현체.

PROGRESS.md 작업22/23이 검증한 최종 스펙을 그대로 따른다 (원본 스크립트는 연구용 스크래치라 작업
완료 후 삭제됐으므로 스펙 문서 — "11개 GICS 섹터+TLT+IEF+GLD+EFA+HYG+DBC(17자산)·top4·12개월
모멘텀·SPY<200일선이면 이진 50%축소·월간 리밸런싱·왕복0.1%비용" — 를 그대로 재구현했다. 독립
재구현이라 원 리포트가 발표한 수치(샤프 1.10)와 소수점 단위로는 다를 수 있으나, 방법론은 동일):

- 유니버스: GICS 11개 핵심 섹터 ETF + TLT/IEF(채권) + GLD(금) + EFA(국제주식) + HYG(하이일드) +
  DBC(원자재) = 17자산.
- 매월 첫 거래일 리밸런싱. 전일 종가 기준 12개월(252거래일) 수익률로 절대모멘텀(>0)을 통과한
  자산 중 상대모멘텀(같은 수익률) 상위 4개를 동일비중(각 25%) 보유, 후보 부족분은 현금.
- SPY 종가가 200일 이동평균 아래면(리밸런싱 신호일 기준) 그 달의 목표 비중 전체를 50%로 축소
  (이진 시장필터).
- 왕복 0.1% 거래비용 = 편도(비중 변화 1단위당) 5bp, `core.backtest_engine.compute_equity_curve`의
  fee_bps/slippage_bps 관례와 동일하게 "비중 변화분의 절대값 x cost_rate"로 계산.

이 파일은 H1(코어-새틀라이트)·H2(베타 헤지) 양쪽에서 "순수 17자산 코어"를 만들 때 공유해서 쓴다.
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))

import numpy as np
import pandas as pd

from core.backtest_engine import _first_trading_day_of_month_mask, calculate_metrics
from core.market_data import get_multiple_price_history

CHAMPION_UNIVERSE = [
    "XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC",  # GICS 11섹터
    "TLT", "IEF", "GLD",  # 채권·금
    "EFA", "HYG", "DBC",  # 국제주식·하이일드·원자재
]
MOMENTUM_WINDOW = 252
TOP_N = 4
MARKET_FILTER_TICKER = "SPY"
MARKET_FILTER_MA = 200
MARKET_FILTER_SCALE_BELOW = 0.5
COST_BPS_PER_SIDE = 5.0  # 왕복 0.1% = 편도 5bp
WARMUP_DAYS = 400


def fetch_champion_histories(start: str, end: str | None = None, tickers: list[str] | None = None) -> dict[str, pd.DataFrame]:
    tickers = list(tickers or CHAMPION_UNIVERSE)
    if MARKET_FILTER_TICKER not in tickers:
        tickers = tickers + [MARKET_FILTER_TICKER]
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    return get_multiple_price_history(tickers, start=fetch_start, end=end, interval="1d")


def _closes_from_histories(histories: dict[str, pd.DataFrame], tickers: list[str]) -> pd.DataFrame:
    closes = pd.DataFrame({t: histories[t]["Close"] for t in tickers if t in histories and not histories[t].empty})
    return closes.ffill()


def build_champion_weights(
    closes: pd.DataFrame,
    market_close: pd.Series,
    top_n: int = TOP_N,
    momentum_window: int = MOMENTUM_WINDOW,
    apply_market_filter: bool = True,
) -> pd.DataFrame:
    """월별 리밸런싱 목표 비중(리밸런싱일 이후 다음 리밸런싱일까지 ffill)을 계산한다.

    momentum_rotation.py(작업19)와 동일한 단일 루프 패턴 — 리밸런싱일에는 그 전일 종가 기준으로
    신호를 계산하고(lookahead 방지), 시장필터도 같은 signal_date에 평가해 한 번의 월간 결정으로
    같이 적용한다(월간 리밸런싱 전략이므로 필터도 월 단위로 갱신되는 것이 자연스러움 — 원 리서치가
    "월별 실제 로테이션 로그"를 기준으로 보고한 것과 일치하는 해석).
    """
    momentum = closes.pct_change(momentum_window)
    is_rebal = _first_trading_day_of_month_mask(closes.index)
    sma200 = market_close.rolling(MARKET_FILTER_MA, min_periods=MARKET_FILTER_MA).mean()

    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_weights = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]
            mom = momentum.loc[signal_date]
            candidates = mom[mom > 0].sort_values(ascending=False)
            picks = candidates.index[:top_n]
            w = pd.Series(0.0, index=closes.columns)
            if len(picks) > 0:
                w[picks] = 1.0 / top_n
            if apply_market_filter and signal_date in sma200.index and not pd.isna(sma200.loc[signal_date]):
                if market_close.loc[signal_date] < sma200.loc[signal_date]:
                    w = w * MARKET_FILTER_SCALE_BELOW
            last_weights = w
        weights.iloc[i] = last_weights.values
    return weights


def compute_portfolio_returns(
    closes: pd.DataFrame, weights: pd.DataFrame, cost_bps_per_side: float = COST_BPS_PER_SIDE
) -> dict:
    """비중 시계열로부터 (비용반영 순수익률, 비용전 총수익률, 회전율, 자산가치곡선)을 계산한다.

    weights.shift(1)로 "그 비중이 결정된 다음 거래일부터 체결"하는 lookahead 방지 관례를
    momentum_rotation.py와 동일하게 적용한다.
    """
    daily_ret = closes.pct_change().fillna(0.0)
    executed_weights = weights.shift(1).fillna(0.0)
    port_ret_gross = (daily_ret * executed_weights).sum(axis=1)

    prev_executed = executed_weights.shift(1).fillna(0.0)
    turnover = (executed_weights - prev_executed).abs().sum(axis=1)
    cost = turnover * (cost_bps_per_side / 10000.0)
    port_ret_net = port_ret_gross - cost

    equity_gross = (1.0 + port_ret_gross).cumprod() * 100.0
    equity_gross.iloc[0] = 100.0
    equity_net = (1.0 + port_ret_net).cumprod() * 100.0
    equity_net.iloc[0] = 100.0

    return {
        "ret_net": port_ret_net,
        "ret_gross": port_ret_gross,
        "turnover": turnover,
        "equity_net": equity_net,
        "equity_gross": equity_gross,
    }


def run_champion(start: str, end: str | None = None, tickers: list[str] | None = None, apply_market_filter: bool = True) -> dict:
    """지정 구간에서 순수 17자산 챔피언을 실행하고 지표+수익률 시계열을 반환한다."""
    tickers = list(tickers or CHAMPION_UNIVERSE)
    histories = fetch_champion_histories(start, end, tickers)
    closes_all = _closes_from_histories(histories, tickers + [MARKET_FILTER_TICKER])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    market_close = closes_all[MARKET_FILTER_TICKER]

    weights_full = build_champion_weights(closes, market_close, apply_market_filter=apply_market_filter)

    sliced_idx = closes.index[(closes.index >= pd.Timestamp(start))]
    if end:
        sliced_idx = sliced_idx[sliced_idx <= pd.Timestamp(end)]
    closes_sliced = closes.loc[sliced_idx]
    weights_sliced = weights_full.loc[sliced_idx]

    result = compute_portfolio_returns(closes_sliced, weights_sliced)
    metrics = calculate_metrics(result["equity_net"], [], sliced_idx[0], sliced_idx[-1])

    return {
        "start": str(sliced_idx[0].date()),
        "end": str(sliced_idx[-1].date()),
        "metrics": metrics,
        "ret_net": result["ret_net"],
        "ret_gross": result["ret_gross"],
        "equity_net": result["equity_net"],
        "weights": weights_sliced,
        "closes": closes_sliced,
        "market_close": market_close.loc[sliced_idx],
    }


if __name__ == "__main__":
    r = run_champion("2015-01-01", "2026-08-19")
    print("Champion 17-asset (2015-01-01~2026-08-19):", r["metrics"])
