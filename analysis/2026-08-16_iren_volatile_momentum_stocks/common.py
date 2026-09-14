"""공통 유틸 — 가격 로딩, 지표, 비용모델. IREN 유사 변동성종목 백테스트 파이프라인 공통 모듈."""
import sys
PROJECT_ROOT = "/workspaces/Quant/.claude/worktrees/agent-ac951b793786976b4"
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd

from core.market_data import get_multiple_price_history
from core.backtest_engine import calculate_metrics, run_buy_and_hold, _first_trading_day_of_month_mask
from core.position_sizing import realized_annual_volatility_pct, volatility_target_weight

OUT_DIR = f"{PROJECT_ROOT}/analysis/2026-08-16_iren_volatile_momentum_stocks"

# 피벗 바스켓: 비트코인 채굴 -> AI/HPC 데이터센터 전환 종목
PIVOT_BASKET = ["IREN", "CIFR", "CLSK", "WULF", "HUT", "BTDR"]
PIVOT_BASKET_WITH_CORZ = PIVOT_BASKET + ["CORZ"]  # CORZ는 2024-01 파산 재상장이라 별도 표기
CONTRAST_BASKET = ["MARA", "RIOT"]  # 상대적으로 덜 피벗한(여전히 채굴 매출 비중 높은) 대조군
ALL_TICKERS = PIVOT_BASKET_WITH_CORZ + CONTRAST_BASKET
BENCH = ["SPY", "BTC-USD"]

END = "2026-08-18"
FEE_BPS = 5.0  # 편도 5bp = 왕복 0.1% (저장소 모멘텀 로테이션 시리즈와 동일 관례)
COST_RATE = FEE_BPS / 10000.0  # 편도 turnover 1단위당 비용률


def cost_series(weights: pd.DataFrame) -> pd.Series:
    """일별 turnover(자산별 비중변화 절대값의 합)에 COST_RATE를 곱한 비용률 시리즈."""
    turnover = weights.diff().abs().sum(axis=1).fillna(0.0)
    return turnover * COST_RATE


def load_histories(tickers, start="2014-01-01", end=END):
    return get_multiple_price_history(tickers, start=start, end=end, interval="1d")


def closes_frame(histories: dict) -> pd.DataFrame:
    closes = pd.DataFrame({t: df["Close"] for t, df in histories.items() if not df.empty})
    return closes.sort_index()


def metrics_from_returns(ret: pd.Series) -> tuple[dict, pd.Series]:
    equity = (1.0 + ret.fillna(0.0)).cumprod() * 100.0
    if len(equity) > 0:
        equity.iloc[0] = 100.0
    m = calculate_metrics(equity, [], equity.index[0], equity.index[-1])
    return m, equity
