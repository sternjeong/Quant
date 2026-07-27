"""포지션 사이징 계산기 (모듈 A 확장): 얼마나 살지 계산하는 4가지 방법.

core.backtest_engine/core.strategy_engine이 "언제 사고 팔지"(엔트리/엑싯)를 다룬다면, 이 모듈은
"한 번에 얼마나 살지"를 다룬다. 백테스트 엔진 자체는 항상 그 시점 자산 전액을 싣는 0/1(또는 1:2:6
비중) 모델이라 실제 매매 시 계좌 크기 대비 얼마를 태울지는 별도로 계산해야 한다 — 이 모듈은 순수
계산 함수만 제공하고(DB/시세 조회 없음), 호출부(Streamlit 페이지, core.portfolio)가 백테스트 결과의
거래 이력이나 실시간 시세와 조합해서 쓴다.

네 가지 방법(난이도/정교함 순):
    1. fixed_fractional_size — 고정 % 리스크: 손절가까지의 거리로 살 수량을 역산
    2. equal_weight_size — 동일가중: 계좌를 포지션 개수로 균등 분배
    3. kelly_fraction — 켈리 기준: 과거 승률/평균손익으로 이론상 최적 비중을 구하되, 풀 켈리는
       과도하게 공격적이라 위험하므로 하프켈리(기본 50%) 상한을 함께 제시
    4. volatility_target_weight / portfolio_volatility_target_weights — 변동성 타겟팅: 변동성이
       클수록 비중을 줄여 종목/전략 간 리스크를 맞춤 (개별용/포트폴리오 레벨용 두 함수)

포지션 크기를 정하는 것만큼, 계좌 대비 리스크를 과도하게 태우지 않는 것이 중요하다는 게 이 네
방법의 공통 전제다 — 특히 켈리 기준은 이론상 최적이어도 실전에서는 그대로 쓰면 위험하다는 경고를
함께 반환한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional

import pandas as pd

TRADING_DAYS_PER_YEAR = 252
DEFAULT_KELLY_SAFETY_FRACTION = 0.5  # 하프켈리 — 풀 켈리는 실전에서 지나치게 공격적이라는 경고가 널리 알려져 있음


@dataclass
class TradeStats:
    """켈리/기대값 계산에 필요한 거래 통계."""

    trade_count: int
    win_rate: float  # 0~1
    avg_win_pct: float  # 승리 거래 평균 수익률(%), 양수
    avg_loss_pct: float  # 손실 거래 평균 손실률(%), 양수(절대값)


def compute_trade_stats(trades: Iterable) -> Optional[TradeStats]:
    """core.strategy_engine.Trade 리스트(또는 return_pct 속성을 가진 객체 리스트)에서 승률/평균
    손익을 뽑는다. 완료된(청산된, return_pct가 있는) 거래가 하나도 없으면 None."""
    completed = [t.return_pct for t in trades if getattr(t, "return_pct", None) is not None]
    if not completed:
        return None
    wins = [r for r in completed if r > 0]
    losses = [r for r in completed if r < 0]
    return TradeStats(
        trade_count=len(completed),
        win_rate=len(wins) / len(completed),
        avg_win_pct=(sum(wins) / len(wins)) if wins else 0.0,
        avg_loss_pct=(abs(sum(losses)) / len(losses)) if losses else 0.0,
    )


def fixed_fractional_size(account_value: float, risk_pct: float, entry_price: float, stop_price: float) -> dict:
    """방법 1: 고정 % 리스크. 계좌 대비 이번 거래에서 감수할 손실 비율(risk_pct, 예: 2 = 2%)을
    정해두고, 손절가까지의 거리로 살 수량을 역산한다 — 가장 널리 쓰이는 기본형 사이징.

    Returns: {"risk_amount", "shares", "position_value", "position_pct_of_account"}
    """
    if account_value <= 0:
        raise ValueError("account_value는 0보다 커야 합니다.")
    if entry_price <= 0 or stop_price <= 0:
        raise ValueError("entry_price/stop_price는 0보다 커야 합니다.")
    if entry_price == stop_price:
        raise ValueError("entry_price와 stop_price가 같으면 리스크 거리가 0이라 계산할 수 없습니다.")

    risk_amount = account_value * (risk_pct / 100.0)
    per_share_risk = abs(entry_price - stop_price)
    shares = risk_amount / per_share_risk
    position_value = shares * entry_price
    return {
        "risk_amount": round(risk_amount, 2),
        "shares": round(shares, 4),
        "position_value": round(position_value, 2),
        "position_pct_of_account": round(position_value / account_value * 100.0, 2),
    }


def equal_weight_size(account_value: float, n_positions: int) -> dict:
    """방법 2: 동일가중. n_positions개 포지션에 계좌를 균등 분배한다.

    Returns: {"position_value", "position_pct_of_account"}
    """
    if account_value <= 0:
        raise ValueError("account_value는 0보다 커야 합니다.")
    if n_positions <= 0:
        raise ValueError("n_positions는 1 이상이어야 합니다.")

    position_value = account_value / n_positions
    return {
        "position_value": round(position_value, 2),
        "position_pct_of_account": round(100.0 / n_positions, 2),
    }


def kelly_fraction(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    safety_fraction: float = DEFAULT_KELLY_SAFETY_FRACTION,
) -> dict:
    """방법 3: 켈리 기준. f* = W - (1-W)/R (W=승률, R=평균승리/평균손실 페이오프 비율).

    풀 켈리(f*)는 이론상 장기 성장률을 최대화하지만 계좌 변동성이 매우 커서 실전에서는 위험하다고
    널리 알려져 있다 — safety_fraction(기본 0.5=하프켈리)을 곱한 recommended_fraction을 함께
    반환하니, 실제 사이징에는 recommended_fraction을 쓰는 걸 권장한다.

    Args:
        win_rate: 0~1 사이 승률.
        avg_win_pct/avg_loss_pct: 승리/손실 거래 평균 수익률(%), 둘 다 양수로 넘긴다
            (compute_trade_stats가 이 형태로 반환).
        safety_fraction: 풀 켈리에 곱할 안전계수. None이면 풀 켈리 그대로.

    Returns: {"full_kelly", "recommended_fraction", "payoff_ratio"} — 전부 0~1 사이 비율(또는 None).
        엣지가 없으면(full_kelly<=0) 둘 다 0.0.
    """
    if not (0.0 <= win_rate <= 1.0):
        raise ValueError("win_rate는 0~1 사이여야 합니다.")
    if avg_loss_pct <= 0:
        return {"full_kelly": 0.0, "recommended_fraction": 0.0, "payoff_ratio": None}

    payoff_ratio = avg_win_pct / avg_loss_pct
    full_kelly = win_rate - (1.0 - win_rate) / payoff_ratio
    full_kelly = max(full_kelly, 0.0)  # 음수면 이 거래에는 통계적 엣지가 없다는 뜻 — 베팅하지 않음
    factor = 1.0 if safety_fraction is None else safety_fraction
    recommended_fraction = full_kelly * factor

    return {
        "full_kelly": round(full_kelly, 4),
        "recommended_fraction": round(recommended_fraction, 4),
        "payoff_ratio": round(payoff_ratio, 4),
    }


def realized_annual_volatility_pct(close: pd.Series, lookback_days: int = 20) -> Optional[float]:
    """최근 lookback_days 종가로 연환산 실현 변동성(%)을 계산한다 (표준편차 기반, 연환산 방식은
    core.portfolio.compute_portfolio_volatility와 동일하게 √252를 곱한다)."""
    if close is None or len(close) < 2:
        return None
    returns = close.pct_change().dropna()
    if len(returns) < 2:
        return None
    window = returns.tail(lookback_days) if len(returns) > lookback_days else returns
    std = window.std(ddof=0)
    if std == 0:
        return None
    return float(std * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0)


def volatility_target_weight(target_annual_vol_pct: float, asset_annual_vol_pct: float, max_weight: float = 1.0) -> float:
    """방법 4 (개별 자산): 변동성 타겟팅. 목표 변동성 ÷ 자산 변동성으로 비중을 정한다 — 변동성이
    큰 자산일수록 비중이 줄어 종목 간 리스크 기여도를 비슷하게 맞춘다. 롱온리/레버리지 없음을
    전제로 max_weight(기본 1.0=100%)로 상한을 씌운다."""
    if target_annual_vol_pct <= 0:
        raise ValueError("target_annual_vol_pct는 0보다 커야 합니다.")
    if asset_annual_vol_pct <= 0:
        return 0.0
    weight = target_annual_vol_pct / asset_annual_vol_pct
    return round(min(weight, max_weight), 4)


def portfolio_volatility_target_weights(
    daily_returns: pd.DataFrame, max_weight: float = 1.0
) -> dict[str, float]:
    """방법 4 (포트폴리오 레벨): 종목별 변동성의 역수(inverse-volatility)로 비중을 정해, 변동성이
    큰 종목의 비중을 낮추고 낮은 종목의 비중을 높인다 — 상관관계까지 반영하는 완전한 공분산 최적화
    대신, 계산이 직관적이고 실전에서 흔히 쓰이는 근사법을 쓴다.

    daily_returns: core.portfolio.compute_daily_returns()와 동일한 형태
        (컬럼=티커, 값=일간수익률, 공통 거래일만 정렬됨).
    max_weight: 종목 하나가 가질 수 있는 최대 비중 (기본 1.0=제한 없음, 집중도 제한에 사용 가능).

    Returns: {ticker: 비중(0~1)} — 전체 합이 1이 되도록 정규화된다. daily_returns가 비어있거나
        전 종목의 변동성이 0이면 빈 dict.
    """
    if daily_returns.empty:
        return {}

    ann_vol = daily_returns.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR)
    ann_vol = ann_vol[ann_vol > 0]
    if ann_vol.empty:
        return {}

    inv_vol = 1.0 / ann_vol
    raw_weights = inv_vol / inv_vol.sum()
    capped = raw_weights.clip(upper=max_weight)
    normalized = capped / capped.sum()
    return {str(k): round(float(v), 4) for k, v in normalized.items()}
