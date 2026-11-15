"""백테스팅 공용 계산 (모듈 A): 자산곡선·성과 지표·매수보유·적립식 시뮬레이션.

포지션(0/1 또는 비중) 시리즈를 받아 자산가치 곡선(equity curve)과
누적수익률/CAGR/MDD/샤프지수/승률/매매횟수/손익비(Profit Factor)/칼마지수/평균낙폭지속기간을 계산한다.
챔피언 전략·성과·연구 잡이 이 함수들을 가져다 쓴다.

핵심 함수:
    compute_equity_curve(...) / calculate_metrics(equity_curve, trades, start, end) -> dict
    run_buy_and_hold(ticker, start, end, fee_bps=0, slippage_bps=0) -> BacktestRun
    simulate_contribution_equity(...) / calculate_contribution_metrics(...)   적립식(DCA) 자산곡선과 XIRR
    compute_drawdown_series / compute_monthly_returns

단일 종목 지표 전략 백테스트(run_backtest)와 그 위의 민감도·순열·팩터·몬테카를로·전략 상관 도구는
쓰는 화면이 사라져 2026-11-15 지웠다.

거래비용은 fee_bps(수수료)+slippage_bps(슬리피지)를 매매 회전율에 곱해 차감하는 단순 모델이다
(기본값 0=비용 없음, compute_equity_curve/simulate_contribution_equity 참고). 포지션 사이징(얼마나
살지)은 이 모듈이 아니라 core.position_sizing 이 담당한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from core.market_data import get_price_history
from core.strategy_engine import (
    Trade,
)

TRADING_DAYS_PER_YEAR = 252
DEFAULT_BENCHMARK_TICKER = "^GSPC"  # S&P500 지수


@dataclass
class BacktestRun:
    """단일 종목 x 전략(또는 매수보유) 백테스팅 실행 결과."""

    label: str
    ticker: str
    df: pd.DataFrame  # 가격 + 지표가 포함된 원본 구간 DataFrame
    position: pd.Series  # 포지션 시그널(신호 발생일 기준). 일반 전략은 0/1, 1:2:6 단계별 전략은 0~1 비중(float)
    equity_curve: pd.Series  # 기준 100에서 시작하는 자산가치 곡선
    trades: list[Trade] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    stage_events: list = field(default_factory=list)  # 1:2:6 단계별 전략의 진입/청산 이벤트 로그 (일반 전략은 빈 리스트)
    contributed_capital: Optional[pd.Series] = None  # 월 적립 옵션 사용 시 그 시점까지 투입된 누적 원금(본전선)
    execution_meta: dict = field(default_factory=dict)  # 옵트인 체결 모델/가격 기준/배당 반영 여부 메타(기본 빈 dict)


EXECUTION_CLOSE = "close"  # 기본: 종가->종가 수익률, 신호 다음날 포지션 반영 (기존 동작)
EXECUTION_NEXT_OPEN = "next_open_ledger"  # 옵트인: 다음 거래일 시가 체결 원장 (core.trade_ledger)


def compute_equity_curve(
    df: pd.DataFrame,
    position: pd.Series,
    initial_value: float = 100.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    execution_model: Optional[str] = None,
    tax_bps: float = 0.0,
) -> pd.Series:
    """포지션 시리즈로부터 자산가치 곡선을 계산한다.

    position은 0/1(일반 전략) 또는 0~1 사이의 비중(1:2:6 단계별 전략)을 모두 지원한다.
    신호가 발생한 다음 거래일부터 실제 체결된다고 가정한다 (lookahead bias 방지).

    fee_bps/slippage_bps(선택, 기본 0=비용 없음)를 주면 매매 회전율(포지션 비중이 바뀐 만큼)에
    비례해 비용을 차감한다 — bps 단위(1bps=0.01%)이며 두 값은 더해서 하루치 비용률로 쓴다
    (예: fee_bps=5, slippage_bps=10 → 왕복이 아닌 편도 비중변화당 0.15%). 0/1 전략은 진입/청산
    시점에, 1:2:6 단계별 전략은 단계가 바뀔 때마다 그 변화분만큼만 비용이 발생한다.
    """
    if execution_model not in (None, EXECUTION_CLOSE):
        if execution_model != EXECUTION_NEXT_OPEN:
            raise ValueError(f"알 수 없는 execution_model: {execution_model!r}")
        from core.trade_ledger import run_ledger_backtest  # 지연 import: 옵트인 경로 전용

        return run_ledger_backtest(
            df, position, initial_cash=initial_value, fee_bps=fee_bps,
            slippage_bps=slippage_bps, tax_bps=tax_bps,
        ).nav.copy()
    daily_return = df["Close"].pct_change().fillna(0.0)
    executed_position = position.shift(1).fillna(0).astype(float)
    cost_rate = (fee_bps + slippage_bps) / 10000.0
    if cost_rate > 0:
        prev_executed = executed_position.shift(1).fillna(0.0)
        turnover = (executed_position - prev_executed).abs()
        strategy_return = daily_return * executed_position - turnover * cost_rate
    else:
        strategy_return = daily_return * executed_position
    equity = (1.0 + strategy_return).cumprod() * initial_value
    equity.iloc[0] = initial_value
    return equity


def _first_trading_day_of_month_mask(index: pd.DatetimeIndex) -> pd.Series:
    """월별 첫 거래일에 True를 표시한다 (월 적립금이 들어오는 시점 기준)."""
    months = pd.Series(index.to_period("M"), index=index)
    is_first = months.ne(months.shift(1))
    is_first.iloc[0] = True
    return is_first


def simulate_contribution_equity(
    df: pd.DataFrame,
    position: pd.Series,
    initial_value: float = 100.0,
    monthly_contribution: float = 0.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> tuple[pd.Series, pd.Series]:
    """월 적립금이 있을 때의 총자산가치 곡선을 시뮬레이션한다 (매달 첫 거래일에 납입).

    핵심 아이디어는 하나뿐이다: 매일 "현재 포지션 비중(weight)만큼만 시장에 투입되어 있어야
    한다"는 목표로 현금↔투자금을 리밸런싱한다. 이 규칙 하나로 두 가지 요청 사항이 자연스럽게
    모두 나온다.

    - 매수보유(포지션이 항상 1): 매달 들어온 적립금이 그 즉시 100% 시장에 투입된다 →
      "매달 초 정액을 계속 사는" 정액적립식(DCA)과 동일한 결과.
    - 신호 기반 전략(포지션이 0/1 또는 0~1 비중으로 바뀜): 포지션이 0인(관망) 동안 들어온
      적립금은 다음 리밸런싱에서 목표 비중이 0이라 현금에 그대로 쌓이고, 매수 시그널이 떠서
      비중이 양수로 바뀌는 순간 쌓여있던 현금이 한꺼번에 시장에 투입된다 → 코스톨로니 법칙
      ("현금을 모아뒀다가 신호가 오면 몰빵한다")과 동일한 결과.

    lookahead 방지를 위해 position은 compute_equity_curve와 동일하게 하루 shift해서 사용한다.

    fee_bps/slippage_bps(선택, 기본 0)는 compute_equity_curve와 동일한 의미로, 목표 비중(weight)이
    전날 대비 바뀐 만큼(리밸런싱 회전율) 그날의 총자산(total)에서 비용을 차감한다.

    Returns:
        (equity_curve, contributed_capital) — 둘 다 df.index와 같은 인덱스의 Series.
        contributed_capital은 그 시점까지 실제로 납입된 누적 원금(초기자본 포함)이다.
    """
    if df.empty:
        empty = pd.Series(dtype=float)
        return empty, empty

    daily_return = df["Close"].pct_change().fillna(0.0)
    executed_position = position.shift(1).fillna(0).astype(float).clip(lower=0.0, upper=1.0)
    is_contribution_day = _first_trading_day_of_month_mask(df.index)
    cost_rate = (fee_bps + slippage_bps) / 10000.0

    invested = 0.0
    cash = initial_value
    total_contributed = initial_value
    prev_weight = 0.0
    equity_vals = []
    contributed_vals = []

    for i in range(len(df.index)):
        weight = float(executed_position.iloc[i])

        if i > 0:
            invested *= 1.0 + float(daily_return.iloc[i])
            if monthly_contribution > 0 and bool(is_contribution_day.iloc[i]):
                cash += monthly_contribution
                total_contributed += monthly_contribution

        total = invested + cash
        if cost_rate > 0:
            total -= abs(weight - prev_weight) * total * cost_rate
        target_invested = weight * total
        invested, cash = target_invested, total - target_invested
        prev_weight = weight

        equity_vals.append(total)
        contributed_vals.append(total_contributed)

    equity_curve = pd.Series(equity_vals, index=df.index)
    contributed_capital = pd.Series(contributed_vals, index=df.index)
    return equity_curve, contributed_capital


def _xirr(cashflows: list[tuple[pd.Timestamp, float]]) -> float:
    """일별 현금흐름(음수=납입, 양수=회수)으로 연환산 자금가중수익률(XIRR)을 이분법으로 구한다.

    scipy 등 외부 의존성 없이 순수 이분법을 쓴다 — 월 적립 시나리오에서는 현금흐름이 전부
    "납입 후 최종 회수 1건"이라 NPV(rate)가 rate에 대해 단조감소라 근이 유일하게 존재한다.
    """
    if not cashflows:
        return 0.0
    t0 = cashflows[0][0]

    def npv(rate: float) -> float:
        return sum(amt / ((1.0 + rate) ** ((dt - t0).days / 365.25)) for dt, amt in cashflows)

    lo, hi = -0.9999, 10.0
    npv_lo, npv_hi = npv(lo), npv(hi)
    if npv_lo * npv_hi > 0:
        return 0.0
    for _ in range(100):
        mid = (lo + hi) / 2
        npv_mid = npv(mid)
        if abs(npv_mid) < 1e-6:
            return mid
        if npv_lo * npv_mid < 0:
            hi, npv_hi = mid, npv_mid
        else:
            lo, npv_lo = mid, npv_mid
    return (lo + hi) / 2


def calculate_contribution_metrics(
    equity_curve: pd.Series,
    contributed_capital: pd.Series,
    trades: list[Trade],
    start_date,
    end_date,
) -> dict:
    """월 적립금이 있는 백테스트의 성과 지표.

    일반 calculate_metrics의 누적수익률/CAGR은 "처음에 목돈을 한 번 넣고 끝까지 둔다"는
    전제라 중간에 계속 돈을 넣는 적립식에는 그대로 쓸 수 없다(같은 이름이라도 의미가 달라짐).
    그래서 이 함수는 두 지표만 다시 정의하고, MDD/샤프/승률/매매횟수/손익비/평균낙폭지속기간은
    원래 계산을 그대로 재사용한다(둘 다 자산가치 곡선/거래 기준이라 적립 여부와 무관하게 유효):
      - cumulative_return → 원금(총 납입액) 대비 손익률로 재정의
      - cagr → XIRR(자금가중 연환산수익률)로 재정의 — "언제 얼마를 넣었는지"까지 반영한
        진짜 연환산 수익률이라 정액적립식 vs 신호기반 몰빵 전략의 비교 기준으로 적합하다
      - calmar → cagr이 XIRR로 바뀌므로, mdd는 그대로 두고 이 새 cagr 기준으로 다시 계산한다
    """
    base = calculate_metrics(equity_curve, trades, start_date, end_date)
    if equity_curve.empty or len(equity_curve) < 2:
        return {**base, "total_contributed": 0.0, "total_profit": 0.0}

    final_value = float(equity_curve.iloc[-1])
    total_contributed = float(contributed_capital.iloc[-1])
    total_profit = final_value - total_contributed
    profit_pct = (total_profit / total_contributed * 100) if total_contributed > 0 else 0.0

    contribution_diff = contributed_capital.diff()
    contribution_diff.iloc[0] = contributed_capital.iloc[0]
    cashflows = [(dt, -float(amt)) for dt, amt in contribution_diff.items() if amt > 0]
    cashflows.append((equity_curve.index[-1], final_value))
    xirr = _xirr(cashflows) * 100

    base.update(
        {
            "cumulative_return": round(profit_pct, 2),
            "cagr": round(xirr, 2),
            "calmar": round(_compute_calmar(xirr, base["mdd"]), 2),
            "total_contributed": round(total_contributed, 2),
            "total_profit": round(total_profit, 2),
        }
    )
    return base


# 분모가 0이 되는 경우(진 거래가 하나도 없거나 낙폭이 전혀 없는 경우)에 수학적으로는 +무한대가
# 맞지만, DB(Float 컬럼)/JSON 직렬화/Streamlit 데이터프레임 전 구간에서 inf를 안전하게 다루기
# 번거로워 대신 "사실상 무한대"를 뜻하는 유한한 상한값으로 캡을 씌운다.
_RATIO_METRIC_CAP = 999.0


def _compute_calmar(cagr: float, mdd: float) -> float:
    """칼마지수 = CAGR / |MDD|. 낙폭이 아예 없으면(mdd=0) 나눗셈이 정의되지 않으므로,
    CAGR이 양수면 상한값(_RATIO_METRIC_CAP, 낙폭 없이 계속 오른 극단적으로 좋은 경우),
    0 이하면 0.0으로 처리한다."""
    if mdd != 0:
        return cagr / abs(mdd)
    return _RATIO_METRIC_CAP if cagr > 0 else 0.0


def compute_drawdown_series(equity_curve: pd.Series) -> pd.Series:
    """자산가치 곡선에서 매 시점의 낙폭(%, 신고점 대비 하락률)을 계산한다. 항상 0 이하 값이며,
    신고점 갱신 시점은 0. UI의 underwater(드로다운) 차트와 calculate_metrics()의 MDD 계산이 이 함수를
    공유한다."""
    if equity_curve.empty:
        return equity_curve.copy()
    running_max = equity_curve.cummax()
    return (equity_curve / running_max - 1) * 100


def compute_monthly_returns(equity_curve: pd.Series) -> pd.DataFrame:
    """자산가치 곡선을 월별 수익률(%) 피벗 테이블(행=연도, 열=월 1~12)로 변환한다.

    각 달의 수익률은 그 달 마지막 거래일 자산가치를 직전 달 마지막 거래일 자산가치와 비교해 구한다
    (거래일 기준 리샘플이라 휴장일과 무관). 데이터가 2개월 미만이면(수익률을 하나도 못 구하면) 빈
    DataFrame을 반환한다.
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return pd.DataFrame()

    month_end = equity_curve.resample("ME").last()
    monthly_return = month_end.pct_change().dropna() * 100
    if monthly_return.empty:
        return pd.DataFrame()

    table = monthly_return.to_frame("return")
    table["year"] = table.index.year
    table["month"] = table.index.month
    pivot = table.pivot(index="year", columns="month", values="return")
    return pivot.reindex(columns=range(1, 13))


def _compute_avg_drawdown_duration_days(equity_curve: pd.Series) -> float:
    """평균 낙폭 지속기간(일) — 신고점을 갱신하지 못한 채(running_max 미만) 있다가 다시 신고점을
    회복하기까지 걸린 일수들의 평균이다. MDD는 "얼마나 깊게 빠졌는지"만 알려주지만, 이 지표는
    "그 낙폭 속에서 며칠을 버텨야 했는지"를 알려준다 — 회복까지 평균 60일 걸리는 전략을 30일
    인내심으로 포기하면 항상 최악의 타이밍에 손절하게 된다.

    아직 회복하지 못한(현재진행형) 마지막 낙폭은 끝나는 시점을 알 수 없어 평균 계산에서 제외한다
    (완결된 낙폭 구간이 하나도 없으면 0.0).
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return 0.0
    running_max = equity_curve.cummax()
    in_drawdown = equity_curve < running_max

    durations: list[int] = []
    start = None
    for dt, flag in in_drawdown.items():
        if flag and start is None:
            start = dt
        elif not flag and start is not None:
            durations.append((dt - start).days)
            start = None
    return float(np.mean(durations)) if durations else 0.0


def calculate_metrics(equity_curve: pd.Series, trades: list[Trade], start_date, end_date) -> dict:
    """누적수익률/CAGR/MDD/샤프지수/승률/매매횟수/손익비(Profit Factor)/칼마지수/평균낙폭지속기간을
    계산한다."""
    if equity_curve.empty or len(equity_curve) < 2:
        return {
            "cumulative_return": 0.0,
            "cagr": 0.0,
            "mdd": 0.0,
            "sharpe": 0.0,
            "win_rate": 0.0,
            "trade_count": 0,
            "avg_holding_days": 0.0,
            "profit_factor": 0.0,
            "calmar": 0.0,
            "avg_drawdown_days": 0.0,
        }

    start_value = float(equity_curve.iloc[0])
    end_value = float(equity_curve.iloc[-1])
    cumulative_return = (end_value / start_value - 1) * 100

    days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
    years = max(days / 365.25, 1e-9)
    if end_value > 0 and start_value > 0:
        cagr = ((end_value / start_value) ** (1 / years) - 1) * 100
    else:
        cagr = 0.0

    mdd = float(compute_drawdown_series(equity_curve).min())

    daily_returns = equity_curve.pct_change().dropna()
    if daily_returns.std(ddof=0) > 0:
        sharpe = float(daily_returns.mean() / daily_returns.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        sharpe = 0.0

    completed = [t for t in trades if t.return_pct is not None]
    trade_count = len(completed)
    if trade_count > 0:
        wins = sum(1 for t in completed if t.return_pct > 0)
        win_rate = wins / trade_count * 100
    else:
        win_rate = 0.0

    holding_days = [
        (t.exit_date - t.entry_date).days for t in completed if t.exit_date is not None and t.entry_date is not None
    ]
    avg_holding_days = sum(holding_days) / len(holding_days) if holding_days else 0.0

    # 손익비(Profit Factor) = 이긴 거래 수익률 합 / 진 거래 손실률 합(절대값). 이 엔진은 매매마다
    # 항상 그 시점 자산 전액을 싣는 모델(포지션 사이징 없음)이라, 거래별 수익률(%) 합으로 계산해도
    # 달러 손익 기준과 동일한 비율이 나온다. 진 거래가 하나도 없으면(분모 0) _RATIO_METRIC_CAP으로 캡핑한다.
    gross_profit = sum(t.return_pct for t in completed if t.return_pct > 0)
    gross_loss = abs(sum(t.return_pct for t in completed if t.return_pct < 0))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = _RATIO_METRIC_CAP if gross_profit > 0 else 0.0

    return {
        "cumulative_return": round(cumulative_return, 2),
        "cagr": round(cagr, 2),
        "mdd": round(mdd, 2),
        "sharpe": round(sharpe, 2),
        "win_rate": round(win_rate, 2),
        "avg_holding_days": round(avg_holding_days, 1),
        "trade_count": trade_count,
        "profit_factor": round(profit_factor, 2),
        "calmar": round(_compute_calmar(cagr, mdd), 2),
        "avg_drawdown_days": round(_compute_avg_drawdown_duration_days(equity_curve), 1),
    }


def run_buy_and_hold(
    ticker: str,
    start: str,
    end: str,
    label: Optional[str] = None,
    monthly_contribution: float = 0.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> BacktestRun:
    """매수 후 보유(첫날 매수, 끝까지 보유) 벤치마크를 계산한다.

    monthly_contribution > 0이면 매달 첫 거래일마다 그 금액을 추가로 시장가 매수하는
    정액적립식(DCA)으로 시뮬레이션한다 — 포지션이 항상 1이라 들어온 돈이 즉시 전부 투입된다.

    fee_bps/slippage_bps는 run_backtest와 동일한 의미 — 매수보유는 최초 진입 1회만 회전율이
    발생하므로(월 적립 시에는 매달 추가 매수마다) 그 시점에만 비용이 반영된다.
    """
    df = get_price_history(ticker, start=start, end=end, use_cache=True)
    label = label or f"{ticker} 매수 후 보유"

    if df is None or df.empty:
        empty_idx = pd.DatetimeIndex([])
        return BacktestRun(
            label=label,
            ticker=ticker,
            df=pd.DataFrame(),
            position=pd.Series(dtype=int, index=empty_idx),
            equity_curve=pd.Series(dtype=float, index=empty_idx),
            trades=[],
            metrics=calculate_metrics(pd.Series(dtype=float), [], start, end),
        )

    position = pd.Series(1, index=df.index)
    trades = [
        Trade(
            entry_date=df.index[0],
            exit_date=df.index[-1],
            entry_price=float(df["Close"].iloc[0]),
            exit_price=float(df["Close"].iloc[-1]),
            return_pct=(float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1) * 100,
        )
    ]

    contributed_capital = None
    if monthly_contribution > 0:
        equity_curve, contributed_capital = simulate_contribution_equity(
            df, position, monthly_contribution=monthly_contribution, fee_bps=fee_bps, slippage_bps=slippage_bps
        )
        metrics = calculate_contribution_metrics(equity_curve, contributed_capital, trades, df.index[0], df.index[-1])
    else:
        equity_curve = compute_equity_curve(df, position, fee_bps=fee_bps, slippage_bps=slippage_bps)
        # 매수 후 보유는 첫날부터 보유하는 것이므로 shift로 인해 비는 첫날 수익을 보정한다.
        equity_curve.iloc[0] = 100.0
        metrics = calculate_metrics(equity_curve, trades, df.index[0], df.index[-1])

    return BacktestRun(
        label=label,
        ticker=ticker,
        df=df,
        position=position,
        equity_curve=equity_curve,
        trades=trades,
        metrics=metrics,
        contributed_capital=contributed_capital,
    )


# =============================================================================
# 검증 테스트 4종 (Timothy Masters, 《Testing and Tuning Market Trading Systems》)
# 백테스트 수익률이 실제 통계적 엣지인지, 우연/과최적화인지를 가려낸다.
# =============================================================================


def _shuffle_daily_bars(raw: pd.DataFrame, window_start: pd.Timestamp, window_end: pd.Timestamp, rng: np.random.Generator) -> pd.DataFrame:
    """raw의 [window_start, window_end] 구간에서, 각 날짜의 '전일 종가 대비 시가/고가/저가/종가/
    거래량 비율(그 날의 캔들 모양)'은 그대로 둔 채 날짜의 등장 순서만 무작위로 섞은 가짜 시계열을
    만든다. window 이전 구간(지표 warmup)은 실제 데이터 그대로 남겨 재구성 시작점(직전 종가)만
    실제 값을 앵커로 쓴다.

    변동성/평균수익률(드리프트) 분포는 실제 데이터와 동일하게 유지되면서 날짜 순서에 담긴
    추세·자기상관만 사라지므로, "전략이 이 순서/패턴이 아니라 순수 노이즈에도 통계적으로 우연히
    좋아 보일 수 있는가"를 검정하는 재료가 된다 (Masters가 "가장 강력한 과최적화 탐지기"라 부른
    순열검정의 핵심 아이디어).
    """
    window_mask = (raw.index >= window_start) & (raw.index <= window_end)
    window_positions = np.flatnonzero(window_mask)
    if len(window_positions) == 0:
        return raw.copy()

    price_cols = [c for c in ("Open", "High", "Low", "Close") if c in raw.columns]
    has_volume = "Volume" in raw.columns
    close_vals = raw["Close"].to_numpy(dtype=float)

    first_pos = window_positions[0]
    anchor_close = float(close_vals[first_pos - 1]) if first_pos > 0 else float(close_vals[first_pos])
    prior_positions = np.maximum(window_positions - 1, 0)
    prev_close_vals = np.where(window_positions > 0, close_vals[prior_positions], close_vals[window_positions])

    window_block = raw.iloc[window_positions]
    ratios = window_block[price_cols].to_numpy(dtype=float) / prev_close_vals[:, None]
    volume_vals = window_block["Volume"].to_numpy() if has_volume else None

    order = rng.permutation(len(window_positions))
    shuffled_ratios = ratios[order]
    shuffled_volume = volume_vals[order] if has_volume else None

    close_idx = price_cols.index("Close")
    close_ratios = shuffled_ratios[:, close_idx]
    # t번째 날 시작 시점의(=전날 종가) 합성 가격 = 앵커 * (그 이전까지의 합성 종가 비율 누적곱)
    prev_synthetic_close = anchor_close * np.concatenate(([1.0], np.cumprod(close_ratios)[:-1]))
    new_values = shuffled_ratios * prev_synthetic_close[:, None]

    synthetic = raw.copy()
    col_positions = [synthetic.columns.get_loc(c) for c in price_cols]
    synthetic.iloc[window_positions, col_positions] = new_values
    if has_volume:
        synthetic.iloc[window_positions, synthetic.columns.get_loc("Volume")] = shuffled_volume

    return synthetic


# =============================================================================
# 알파 감쇠 판정 기준 — core.champion_strategy.compute_champion_alpha_decay 가 쓴다.
# 같은 설정을 재튜닝 없이 최근 구간에 재적용해 전체 기간 대비 성과 비율이 이 아래로 떨어지면 감쇠 의심.
# =============================================================================

DEFAULT_DECAY_METRIC = "sharpe"
_DECAY_RATIO_THRESHOLD = 0.3  # 최근/전체 비율이 이 아래로 떨어지면 감쇠 의심
