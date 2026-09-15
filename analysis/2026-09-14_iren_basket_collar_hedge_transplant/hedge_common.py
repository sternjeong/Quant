"""공통 유틸 — IREN류 피벗 바스켓에 SPY 합성 칼라 옵션 헤지를 이식하는 리서치용.

트랙 C의 미해결 과제(agent_c_tenbagger.md, `iren_beta_alpha_hedging_research`가 "옵션 헤지 H5는
인프라 부재로 정성 논의만 했다"고 명시적으로 남긴 갭)를 다룬다. 새 로직을 발명하지 않고 세 기존
모듈을 그대로 이어붙인다:
  1. `analysis/2026-08-16_iren_volatile_momentum_stocks/{common,backtest}.py` — 피벗 바스켓 정의,
     돈치안+트레일링스탑 챔피언 전략, 비용모델.
  2. `core.champion_strategy.build_collar_overlay_returns` — 트랙D가 라이브로 구현한 합성
     블랙숄즈 칼라(SPY 종가+VIX 대리변동성+FRED 금리, ATM풋 매수+5%OTM콜 매도, 매월 첫 거래일 롤).
  3. `analysis/2026-08-23_block_bootstrap_sample_error_quantification/h33_block_bootstrap_sample_error.py`
     의 원형 이동블록부트스트랩 — 트랙C가 이미 `track_c_bootstrap_confidence_audit`에서 자기 자신의
     결론에 적용한 것과 동일한 감사 기계를 여기에도 적용한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

IREN_DIR = PROJECT_ROOT / "analysis" / "2026-08-16_iren_volatile_momentum_stocks"
sys.path.insert(0, str(IREN_DIR))
BOOT_DIR = PROJECT_ROOT / "analysis" / "2026-08-23_block_bootstrap_sample_error_quantification"
sys.path.insert(0, str(BOOT_DIR))

OUT_DIR = Path(__file__).resolve().parent

import numpy as np
import pandas as pd

from common import PIVOT_BASKET, COST_RATE, load_histories, closes_frame, metrics_from_returns, cost_series  # noqa: E402
from backtest import (  # noqa: E402
    find_common_start,
    donchian_trailing_stop_positions,
    run_trend_following_single,
    run_trend_following_basket,
)
from h33_block_bootstrap_sample_error import moving_block_bootstrap_sharpe, annualized_sharpe  # noqa: E402

from core.champion_strategy import build_collar_overlay_returns  # noqa: E402
from core.market_data import get_price_history  # noqa: E402
from core.backtest_engine import calculate_metrics  # noqa: E402

END = "2026-09-14"  # 오늘 — 원본(2026-08-16_iren_volatile_momentum_stocks, END=2026-08-18)보다 약 1개월 더 최신
ENTRY_WINDOW = 20  # 작업27이 채택한 챔피언(트랙C No.2) 그대로
STOP_PCT = 0.15
MOM_WINDOW = 126  # 원본과 동일한 웜업 정의(공통시작일 산출용)
N_BOOT = 2000
BLOCK_LENGTHS = [10, 20, 40]
SEED = 20260914


def basket_static_buy_hold_returns(closes: pd.DataFrame, start: pd.Timestamp) -> pd.Series:
    """바스켓 정적 균등가중 매수후보유(리밸런싱 없음)의 일별 수익률. backtest.py 3)절과 동일 로직을
    '수익률 시계열'로 재구성(원본은 지수만 만들고 일별수익률을 저장하지 않았음)."""
    sliced = closes[closes.index >= start].ffill()
    norm = sliced / sliced.iloc[0]
    equity = norm.mean(axis=1) * 100.0
    ret = equity.pct_change().fillna(0.0)
    ret.iloc[0] = 0.0
    return ret


def collar_overlay_for_index(trading_index: pd.DatetimeIndex, start: str, end: str) -> tuple[pd.Series, list]:
    overlay = build_collar_overlay_returns(trading_index, start, end)
    return overlay["overlay_ret"].reindex(trading_index).fillna(0.0), overlay["roll_log"]


def metrics_from_ret(ret: pd.Series) -> dict:
    m, _ = metrics_from_returns(ret)
    return m
