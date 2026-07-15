"""모듈 G 확장: S&P500 기반 시장 국면(강세/약세) 룰 기반 복합지표.

MARKET_REGIME_SECTOR_STRENGTH_SPEC.md 참고. 4개 신호(200일선 대비 위치, 50/200일 골든·데드크로스,
시장폭[S&P500 중 200일선 위 종목 비율], 52주 고점 대비 낙폭)를 각각 점수화해 합산하는 투명한
간이 프레임워크다 — `core/macro_cycle.py`와 동일하게 특정 데이터 제공자의 실시간 판단이 아니라
참고용 경험칙임을 UI에 명시한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd

from core.backtest_engine import DEFAULT_BENCHMARK_TICKER
from core.indicators import sma
from core.market_data import get_multiple_price_history, get_price_history

BULLISH_THRESHOLD = 35
BEARISH_THRESHOLD = -35

BREADTH_BULLISH_PCT = 70.0
BREADTH_BEARISH_PCT = 30.0
BEAR_MARKET_DRAWDOWN_PCT = -20.0  # 통상적인 "공식 약세장" 정의 기준

# core.market_data.get_price_history(start=None)는 로컬 캐시가 아예 없는 티커에 대해서는
# yfinance 기본기간("1mo")만 받아와 200일선 계산에 필요한 이력이 부족해질 수 있다(캐시가 이미
# 있는 티커는 문제없음). 시장폭 계산은 S&P500 전종목을 훑어 처음 캐싱되는 티커도 섞여 있을 수
# 있으므로 명시적 시작일을 넘겨 이 함정을 피한다.
DEFAULT_LOOKBACK_DAYS = 800  # 200일선 + 52주 고점 계산 대비 넉넉한 여유


def _default_start() -> str:
    return (date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def score_trend_position(close: pd.Series) -> Optional[dict]:
    """종가가 200일선 위/아래인지로 ±25점을 매긴다."""
    s = close.dropna()
    if len(s) < 200:
        return None
    sma200 = sma(s, 200)
    if sma200.dropna().empty:
        return None
    last_close = float(s.iloc[-1])
    last_sma200 = float(sma200.iloc[-1])
    above = last_close > last_sma200
    return {
        "score": 25.0 if above else -25.0,
        "above_200sma": above,
        "close": last_close,
        "sma200": last_sma200,
        "pct_vs_sma200": (last_close / last_sma200 - 1) * 100,
    }


def score_ma_cross(close: pd.Series) -> Optional[dict]:
    """50일선이 200일선 위(골든)/아래(데드)인지로 ±25점을 매긴다."""
    s = close.dropna()
    if len(s) < 200:
        return None
    sma50 = sma(s, 50)
    sma200 = sma(s, 200)
    if sma50.dropna().empty or sma200.dropna().empty:
        return None
    last_sma50 = float(sma50.iloc[-1])
    last_sma200 = float(sma200.iloc[-1])
    golden = last_sma50 > last_sma200
    return {
        "score": 25.0 if golden else -25.0,
        "golden_cross": golden,
        "sma50": last_sma50,
        "sma200": last_sma200,
    }


def score_drawdown(close: pd.Series, lookback: int = 252) -> Optional[dict]:
    """52주(거래일 기준) 고점 대비 낙폭으로 -25~0점(패널티 전용)을 매긴다."""
    s = close.dropna()
    if s.empty:
        return None
    window = s.iloc[-lookback:] if len(s) > lookback else s
    high = float(window.max())
    last = float(s.iloc[-1])
    drawdown_pct = (last / high - 1) * 100
    score = _clip(drawdown_pct / abs(BEAR_MARKET_DRAWDOWN_PCT) * 25, -25.0, 0.0)
    return {
        "score": score,
        "drawdown_pct": drawdown_pct,
        "is_bear_market_drawdown": drawdown_pct <= BEAR_MARKET_DRAWDOWN_PCT,
        "week52_high": high,
    }


def score_breadth(pct_above_200sma: float) -> dict:
    """S&P500 중 200일선 위 종목 비율(0~100)로 ±25점을 매긴다(50%=0점 기준, 30%/70%에서 클립)."""
    score = _clip((pct_above_200sma - 50.0) * 1.25, -25.0, 25.0)
    return {
        "score": score,
        "pct_above_200sma": pct_above_200sma,
        "is_overheated": pct_above_200sma >= 85.0,
    }


def compute_market_breadth(
    tickers: list[str],
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict:
    """유니버스 종목들의 종가가 각각 200일선 위인지 확인해 비율(%)을 계산한다.

    Args:
        tickers: 대상 종목 티커 목록 (보통 S&P500 전체, core.screener.get_universe() 결과)

    Returns:
        {"pct_above_200sma": float, "n_total": int, "n_above": int, "n_data_ok": int}
    """
    histories = get_multiple_price_history(tickers, start=start or _default_start(), end=end, interval="1d")
    n_above = 0
    n_data_ok = 0
    for df in histories.values():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        close = df["Close"].dropna()
        if len(close) < 200:
            continue
        n_data_ok += 1
        sma200 = sma(close, 200)
        if sma200.dropna().empty:
            continue
        if float(close.iloc[-1]) > float(sma200.iloc[-1]):
            n_above += 1
    pct = (n_above / n_data_ok * 100) if n_data_ok else 0.0
    return {
        "pct_above_200sma": pct,
        "n_total": len(tickers),
        "n_above": n_above,
        "n_data_ok": n_data_ok,
    }


def classify_regime(total_score: float) -> str:
    if total_score >= BULLISH_THRESHOLD:
        return "강세장"
    if total_score <= BEARISH_THRESHOLD:
        return "약세장"
    return "중립/혼조"


def get_market_regime_snapshot(
    universe_tickers: list[str],
    benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER,
) -> dict:
    """벤치마크(기본 S&P500 지수) + 유니버스 시장폭으로 종합 국면 점수를 계산한다.

    Returns:
        {
            "regime": "강세장"|"중립/혼조"|"약세장", "total_score": float,
            "trend_position": dict|None, "ma_cross": dict|None,
            "drawdown": dict|None, "breadth": dict,
        }
    """
    df = get_price_history(benchmark_ticker, start=_default_start(), end=None, interval="1d")
    close = df["Close"] if not df.empty else pd.Series(dtype=float)

    trend_position = score_trend_position(close)
    ma_cross = score_ma_cross(close)
    drawdown = score_drawdown(close)
    breadth_raw = compute_market_breadth(universe_tickers)
    breadth = score_breadth(breadth_raw["pct_above_200sma"])
    breadth.update(breadth_raw)

    total_score = sum(
        part["score"] for part in (trend_position, ma_cross, drawdown, breadth) if part is not None
    )

    return {
        "regime": classify_regime(total_score),
        "total_score": total_score,
        "trend_position": trend_position,
        "ma_cross": ma_cross,
        "drawdown": drawdown,
        "breadth": breadth,
        "benchmark_ticker": benchmark_ticker,
    }
