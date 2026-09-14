"""공통 유틸: 가격 조회, 수익률, 롤링 베타, 성과지표.

이 폴더의 h1~h4 스크립트가 전부 이 모듈을 공유한다. core.market_data.get_price_history()로
로컬 parquet 캐시를 그대로 재사용하고(중복 다운로드 없음), Sharpe 계산은 core.backtest_engine의
관례(rf=0, mean/std*sqrt(252))를 그대로 따른다 — 이 저장소 다른 리포트와 숫자를 비교할 때
정의가 갈리지 않도록.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.market_data import get_price_history  # noqa: E402

TRADING_DAYS_PER_YEAR = 252


def fetch_close(ticker: str, start: str, end: str) -> pd.Series:
    """종가(Adj Close 있으면 그걸, 없으면 Close) 시계열. 빈 데이터면 빈 Series."""
    df = get_price_history(ticker, start=start, end=end)
    if df.empty:
        return pd.Series(dtype=float, name=ticker)
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    s = df[col].astype(float)
    s.name = ticker
    s.index = pd.DatetimeIndex(s.index).normalize()
    return s


def daily_returns(close: pd.Series) -> pd.Series:
    return close.pct_change().dropna()


def rolling_beta(y: pd.Series, x: pd.Series, window: int) -> pd.Series:
    """단순회귀 베타 = Cov(y,x)/Var(x), 롤링 window. y, x는 이미 같은 인덱스로 정렬돼 있어야 함."""
    cov = y.rolling(window).cov(x)
    var = x.rolling(window).var()
    beta = cov / var
    return beta


def two_factor_ols(y: np.ndarray, x1: np.ndarray, x2: np.ndarray) -> tuple[float, float, float, float]:
    """y = alpha + b1*x1 + b2*x2 + e, 최소자승. numpy.linalg.lstsq 사용(statsmodels 없이).

    Returns: (alpha, b1, b2, r_squared)
    """
    n = len(y)
    X = np.column_stack([np.ones(n), x1, x2])
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    alpha, b1, b2 = coef
    fitted = X @ coef
    resid = y - fitted
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(alpha), float(b1), float(b2), r2


def one_factor_ols(y: np.ndarray, x: np.ndarray) -> tuple[float, float, float]:
    """y = alpha + b*x + e. Returns (alpha, b, r_squared)."""
    n = len(y)
    X = np.column_stack([np.ones(n), x])
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    alpha, b = coef
    fitted = X @ coef
    resid = y - fitted
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(alpha), float(b), r2


def perf_metrics(ret: pd.Series) -> dict:
    """일간수익률 Series -> {cagr_pct, ann_vol_pct, sharpe, mdd_pct, total_return_pct, n_days}.
    core.backtest_engine과 동일한 정의(무위험수익률=0, Sharpe=mean/std*sqrt(252))."""
    ret = ret.dropna()
    if len(ret) < 2:
        return {"cagr_pct": None, "ann_vol_pct": None, "sharpe": None, "mdd_pct": None,
                "total_return_pct": None, "n_days": len(ret)}
    equity = (1.0 + ret).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    n_years = len(ret) / TRADING_DAYS_PER_YEAR
    cagr = (equity.iloc[-1]) ** (1.0 / n_years) - 1.0 if n_years > 0 and equity.iloc[-1] > 0 else float("nan")
    std = ret.std(ddof=0)
    sharpe = float(ret.mean() / std * math.sqrt(TRADING_DAYS_PER_YEAR)) if std > 0 else 0.0
    ann_vol = float(std * math.sqrt(TRADING_DAYS_PER_YEAR))
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    mdd = float(drawdown.min())
    return {
        "cagr_pct": round(cagr * 100.0, 2),
        "ann_vol_pct": round(ann_vol * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "mdd_pct": round(mdd * 100.0, 2),
        "total_return_pct": round(total_return * 100.0, 2),
        "n_days": int(len(ret)),
    }


def align(*series: pd.Series) -> list[pd.Series]:
    """여러 Series를 공통 인덱스(교집합)로 정렬."""
    common_idx = series[0].index
    for s in series[1:]:
        common_idx = common_idx.intersection(s.index)
    common_idx = common_idx.sort_values()
    return [s.reindex(common_idx) for s in series]


PEER_TICKERS = ["IREN", "CIFR", "CLSK", "WULF", "HUT", "CORZ", "BTDR"]
MARKET_TICKER = "SPY"
BTC_TICKER = "BTC-USD"
