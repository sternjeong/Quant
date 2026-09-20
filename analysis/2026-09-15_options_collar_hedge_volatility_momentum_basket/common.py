"""공통 유틸 — 옵션 칼라 헤지를 트랙C 변동성모멘텀 바스켓에 이식하는 리서치의 데이터/신호 공통부.

트랙C 두 번째 리포트(2026-08-16, analysis/2026-08-16_iren_volatile_momentum_stocks)가 채택한
챔피언(20일 돈치안 브레이크아웃 + 15% 트레일링스탑, 6종목 바스켓 동일가중)을 그대로 재구성하고,
core.champion_strategy 의 합성 Black-Scholes 칼라 헤지 엔진(SPY 종가+VIX 대리변동성+FRED 금리)을
재사용해 이 바스켓에 이식한다. 새 백테스트 로직은 최소화하고 기존 엔진 함수를 그대로 호출한다.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/opt/quant")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, run_buy_and_hold
from core.market_data import get_multiple_price_history

OUT_DIR = "/opt/quant/analysis/2026-09-15_options_collar_hedge_volatility_momentum_basket"

# 트랙C 2026-08-16/08-19 리포트와 동일한 피벗 바스켓(비트코인 채굴 -> AI/HPC 데이터센터 전환 테마)
PIVOT_BASKET = ["IREN", "CIFR", "CLSK", "WULF", "HUT", "BTDR"]
BENCH = ["SPY", "^VIX", "BTC-USD"]

END = "2026-09-11"  # 오늘(2026-09-15) 기준 실제 확보되는 가장 최근 거래일(yfinance 실측 확인)
FEE_BPS = 5.0  # 편도 5bp = 왕복 0.1%(저장소 관례, 작업27과 동일)
COST_RATE = FEE_BPS / 10000.0

# 트랙C 작업27이 채택한 챔피언 파라미터
ENTRY_WINDOW = 20
STOP_PCT = 0.15
MOM_WARMUP_DAYS = 126


def log(msg: str) -> None:
    print(f"[common] {msg}", flush=True)


def load_histories(tickers, start="2014-01-01", end=END):
    return get_multiple_price_history(tickers, start=start, end=end, interval="1d")


def closes_frame(histories: dict) -> pd.DataFrame:
    closes = pd.DataFrame({t: df["Close"] for t, df in histories.items() if not df.empty})
    return closes.sort_index()


def find_common_start(closes: pd.DataFrame, warmup_days: int) -> pd.Timestamp:
    """전 종목이 warmup_days 만큼 유효 이력을 확보하는 가장 이른 날짜(작업27 backtest.py와 동일 로직)."""
    first_valid = {c: closes[c].first_valid_index() for c in closes.columns}
    starts = []
    for c, fv in first_valid.items():
        if fv is None:
            continue
        idx = closes.index.get_indexer([fv])[0]
        if idx + warmup_days >= len(closes.index):
            starts.append(closes.index[-1])
        else:
            starts.append(closes.index[idx + warmup_days])
    return max(starts)


def donchian_trailing_stop_positions(close: pd.Series, entry_window: int = ENTRY_WINDOW, stop_pct: float = STOP_PCT) -> pd.Series:
    """단일종목 돈치안 브레이크아웃 진입 + % 트레일링스탑 청산(작업27 backtest.py와 동일 로직 재구현)."""
    rolling_max = close.shift(1).rolling(entry_window, min_periods=entry_window).max()
    breakout = close > rolling_max

    position = pd.Series(0, index=close.index, dtype=int)
    in_pos = False
    peak = None
    for i in range(len(close)):
        c = close.iloc[i]
        if in_pos:
            peak = max(peak, c)
            if c <= peak * (1 - stop_pct):
                in_pos = False
                peak = None
        else:
            if breakout.iloc[i]:
                in_pos = True
                peak = c
        position.iloc[i] = 1 if in_pos else 0
    return position


def cost_series(weights: pd.DataFrame) -> pd.Series:
    turnover = weights.diff().abs().sum(axis=1).fillna(0.0)
    return turnover * COST_RATE


def run_trend_following_basket_returns(closes: pd.DataFrame, start: pd.Timestamp,
                                        entry_window: int = ENTRY_WINDOW, stop_pct: float = STOP_PCT) -> pd.Series:
    """바스켓의 각 종목에 독립적으로 돈치안+트레일링스탑 신호를 적용, 신호 켜진 종목에 동일가중
    배분(나머지 현금) — 작업27이 채택한 챔피언과 동일 구성. 일별 전략수익률(비용 반영 후) 반환."""
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


def metrics_from_returns(ret: pd.Series) -> dict:
    equity = (1.0 + ret.fillna(0.0)).cumprod() * 100.0
    if len(equity) > 0:
        equity.iloc[0] = 100.0
    return calculate_metrics(equity, [], equity.index[0], equity.index[-1])


def equity_from_returns(ret: pd.Series) -> pd.Series:
    equity = (1.0 + ret.fillna(0.0)).cumprod() * 100.0
    if len(equity) > 0:
        equity.iloc[0] = 100.0
    return equity


def max_drawdown_episode(equity: pd.Series) -> dict:
    """equity 곡선에서 최대낙폭(peak->trough) 구간을 찾아 반환. 이 바스켓은 2021-11 상장이라
    2008/2020 같은 공인된 거시위기 표본이 없으므로, "이 바스켓 자체의 최악 낙폭 구간"을 데이터
    주도로 객관적으로 정의해 위기 대용 표본으로 쓴다(사후에 유리한 구간을 임의로 고르지 않기 위함)."""
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    trough_date = drawdown.idxmin()
    trough_val = float(drawdown.loc[trough_date])
    peak_date = equity.loc[:trough_date].idxmax()
    # 회복(직전 고점 재돌파) 시점도 함께 기록 (없으면 데이터 끝)
    after = equity.loc[trough_date:]
    recovery_candidates = after[after >= equity.loc[peak_date]]
    recovery_date = recovery_candidates.index[0] if len(recovery_candidates) > 0 else equity.index[-1]
    return {
        "peak_date": str(peak_date.date()),
        "trough_date": str(trough_date.date()),
        "recovery_date": str(recovery_date.date()),
        "drawdown_pct": round(trough_val * 100, 2),
    }
