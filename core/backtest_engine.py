"""백테스팅 엔진 (모듈 A): 전략 vs S&P500 매수보유 vs 개별종목 매수보유 비교.

core.strategy_engine 이 만든 포지션(0/1) 시리즈를 받아 자산가치 곡선(equity curve)과
누적수익률/CAGR/MDD/샤프지수/승률/매매횟수/손익비(Profit Factor)/칼마지수/평균낙폭지속기간을 계산한다.

핵심 함수:
    run_backtest(ticker, indicator_config, start, end, fee_bps=0, slippage_bps=0) -> BacktestRun
    run_buy_and_hold(ticker, start, end, fee_bps=0, slippage_bps=0) -> BacktestRun
    compare_with_benchmarks(ticker, indicator_config, start, end, benchmark_ticker="^GSPC") -> dict
    save_backtest_result(strategy_id, ticker, start, end, metrics, extra_metrics=None) -> int (BacktestResult.id)
    diagnose_strategy_health(indicator_config) -> list[str] (진입/청산 조건 자기모순 등 흔한 결함 경고)
    trade_count_reliability_warning(trade_count) -> str|None (매매 횟수가 통계적으로 신뢰하기에
        충분한지 대수의 법칙 기준으로 경고)
    compute_alpha_decay(ticker, indicator_config, full_start, full_end, recent_months=6) -> dict (같은 설정을
        재튜닝 없이 최근 구간에 그대로 재적용해 성과가 전체 기간 대비 얼마나 이탈했는지 확인 — 전략 수명 체크)

검증(Masters, 《Testing and Tuning Market Trading Systems》) 함수 4종 — 백테스트 결과가 진짜 통계적
엣지인지 아니면 우연/과최적화인지 판별하는 도구:
    run_sensitivity_sweep(ticker, variants, start, end, metric="sharpe") -> dict (파라미터를 바꿔가며
        재실행해 결과가 완만하게 변하는지(견고) 특정 값에서만 튀는지(과최적화 의심) 확인)
    run_permutation_test(ticker, indicator_config, start, end, n_permutations=200) -> dict (일봉을
        무작위로 섞은 가짜 시계열 대비 실제 결과의 p-value/백분위 산출)
    run_partition_test(strategy_run, benchmark_run, bias_log_return=0.0) -> dict (총수익률을
        추세/실력/편향으로 분해)
    summarize_strategy_vs_benchmarks(comparison, regime_breakdown=None) -> dict (원수익률뿐 아니라
        CAGR/MDD/샤프 전 축에서 벤치마크 대비 승패를 구조화)

전략 포트폴리오 상관관계("홀리그레일") — 종목이 아니라 전략 간 상관관계를 다룬다:
    run_strategy_portfolio(strategies, start, end) -> dict[label, BacktestRun]
    compute_strategy_correlation(runs) -> pd.DataFrame
    compute_strategy_regime_correlation(runs) -> dict[국면, pd.DataFrame] (강세장/약세장/횡보장별)
    save_strategy_correlation_snapshot(corr_matrix) / list_strategy_correlation_snapshots() — "이번 달만
        보고 판단하지 말라"는 원칙대로 상관관계도 이력을 쌓아 추이를 볼 수 있게 저장(CorrelationSnapshot)

팩터 분해(Fama-French 스타일, ETF 프록시) — 전략 수익률이 "어디서" 왔는지(시장/사이즈/가치/모멘텀
노출) 설명한다. run_permutation_test가 "우연이 아닌가"를 검증하는 도구라면, 이 둘은 이미 검증을
통과한 전략이 왜 그런 성과를 냈는지 설명하는 보완 도구다:
    compute_factor_returns(start, end) -> pd.DataFrame (컬럼: MKT_RF/SMB/HML/MOM)
    run_factor_regression(strategy_daily_returns, factor_returns) -> dict (알파/베타/R²)

몬테카를로 시뮬레이션(블록 부트스트랩) — 실제로 벌어진 경로 단 하나만으로 미래를 낙관/비관하지
않도록, 과거 일간수익률의 변동성 군집 구조를 유지한 채 재표집한 대안 경로 분포를 만든다:
    run_monte_carlo_simulation(daily_returns, n_simulations=1000, horizon_days=None, block_size=20) -> dict

전략 스키마는 core.strategy_engine이 6종(레짐/직접수식/1:2:6 단계별/복합/코스톨라니/앙상블 스코어링)을
지원하며, 이 엔진은 스키마를 몰라도 되도록 run_backtest()가 내부적으로 적절한 포지션 생성 함수로
분기한다(_simulate_on_raw 참고) — 앙상블 스코어링은 여러 지표를 -1~1 연속 점수로 정규화해 가중평균한
뒤 포지션 비중(0~1)으로 쓰는 6번째 스키마다.

거래비용은 fee_bps(수수료)+slippage_bps(슬리피지)를 매매 회전율에 곱해 차감하는 단순 모델이다
(기본값 0=비용 없음, compute_equity_curve/simulate_contribution_equity 참고). 포지션 사이징(얼마나
살지)은 이 모듈이 아니라 core.position_sizing 이 담당한다 — 이 엔진 자체는 항상 그 시점 자산
전액을 싣는 0/1(또는 1:2:6 비중) 모델이다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history, get_price_history
from core.strategy_engine import (
    Trade,
    extract_staged_trades,
    extract_trades,
    extract_weighted_trades,
    generate_ensemble_position,
    generate_positions,
    is_ensemble_config,
    is_staged_config,
    simulate_staged_positions,
)

TRADING_DAYS_PER_YEAR = 252
DEFAULT_BENCHMARK_TICKER = "^GSPC"  # S&P500 지수

# 대수의 법칙(law of large numbers) — 표본(매매 건수)이 적을수록 승률/샤프 등의 지표가 실제 엣지가
# 아니라 우연에 의해 크게 흔들릴 수 있다. 절대 기준(30건 미만=위험, 300건 이상=신뢰 가능)은 통계적
# 증명이 아니라 실전에서 널리 쓰이는 경험칙이다 — 정밀한 검증은 run_permutation_test(p-value)를 쓴다.
MIN_TRADE_COUNT_CAUTION = 30
MIN_TRADE_COUNT_RELIABLE = 300


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


def _slice_by_date(df: pd.DataFrame, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if start:
        out = out[out.index >= pd.Timestamp(start)]
    if end:
        out = out[out.index <= pd.Timestamp(end)]
    return out


EXECUTION_CLOSE = "close"  # 기본: 종가->종가 수익률, 신호 다음날 포지션 반영 (기존 동작)
EXECUTION_NEXT_OPEN = "next_open_ledger"  # 옵트인: 다음 거래일 시가 체결 원장 (core.trade_ledger)


def compare_execution_models(
    df: pd.DataFrame,
    position: pd.Series,
    initial_value: float = 100.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    tax_bps: float = 0.0,
    cost_scenarios: bool = True,
    price_basis: Optional[str] = None,
) -> dict:
    """같은 입력에서 기존 종가 경로와 시가 체결 원장 경로를 나란히 비교한다(검증용, 성과 주장 아님).

    반환: baseline_equity(기존), ledger_equity(새), diff(ledger-baseline), final_diff_pct,
    max_abs_diff, scenario_nav(비용 시나리오명 -> NAV Series, cost_scenarios=True 일 때), meta.
    기존 경로는 tax_bps 를 지원하지 않으므로 baseline 에는 세금이 반영되지 않는다.
    """
    from core.trade_ledger import run_cost_scenarios, run_ledger_backtest

    baseline = compute_equity_curve(df, position, initial_value, fee_bps, slippage_bps)
    led = run_ledger_backtest(df, position, initial_cash=initial_value, fee_bps=fee_bps,
                              slippage_bps=slippage_bps, tax_bps=tax_bps, price_basis=price_basis)
    diff = led.nav - baseline
    out = {
        "baseline_equity": baseline,
        "ledger_equity": led.nav,
        "diff": diff,
        "final_diff_pct": float(led.nav.iloc[-1] / baseline.iloc[-1] - 1.0) if len(baseline) else float("nan"),
        "max_abs_diff": float(diff.abs().max()) if len(diff) else 0.0,
        "ledger": led.ledger,
        "meta": {**led.params, "baseline_tax_applied": False},
    }
    if cost_scenarios:
        sc = run_cost_scenarios(df, position, initial_cash=initial_value, tax_bps=tax_bps, price_basis=price_basis)
        out["scenario_nav"] = {k: v.nav for k, v in sc.items()}
    return out


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


def _cap_holding_period(position: pd.Series, max_holding_days: int) -> pd.Series:
    """진입 후 max_holding_days 거래일이 지나면 강제로 청산(0)시킨다 (스윙 트레이딩 보유기간 상한).

    연속으로 포지션(>0)이 유지된 구간을 하나의 보유로 보고, 그 구간의 (max_holding_days+1)번째
    날부터는 원래 신호가 계속 보유를 가리키더라도 0으로 덮어쓴다. 신호가 그 뒤에도 여전히 진입
    조건을 만족하면 다음 날 재진입할 수 있다 — "6개월 넘으면 무조건 판다"는 스윙 트레이더의 실제
    행동을 모사하는 것이지, 그 종목을 영구히 배제하는 것이 아니다.
    """
    if max_holding_days is None or position.empty:
        return position
    values = position.to_numpy(copy=True)
    streak = 0
    for i, v in enumerate(values):
        if v > 0:
            streak += 1
            if streak > max_holding_days:
                values[i] = 0.0
                streak = 0  # 강제 청산 — 다음 날부터 새 보유로 다시 센다(재진입 허용)
        else:
            streak = 0
    return pd.Series(values, index=position.index, name=position.name)


def _simulate_on_raw(
    raw: pd.DataFrame,
    df: pd.DataFrame,
    indicator_config: str | dict,
    max_holding_days: Optional[int],
) -> tuple[pd.Series, list[Trade], list]:
    """raw(지표 warmup 포함 원본)로 포지션을 계산해 df(실제 백테스트 구간)로 잘라낸다.

    run_backtest와 run_permutation_test(가짜/순열 데이터)가 동일한 시뮬레이션 로직을 공유하도록
    분리했다 — 순열검정은 raw 자체를 가짜 데이터로 바꿔치기만 하면 이 함수는 그대로 재사용된다.
    """
    staged = is_staged_config(indicator_config)
    ensemble = is_ensemble_config(indicator_config)
    if staged:
        position_full, events_full = simulate_staged_positions(raw, indicator_config)
        position = position_full.loc[df.index]
        if max_holding_days is not None:
            position = _cap_holding_period(position, max_holding_days)
        df_index_set = set(df.index)
        stage_events = [e for e in events_full if e.date in df_index_set]
        trades = extract_staged_trades(df, stage_events)
    elif ensemble:
        position_full = generate_ensemble_position(raw, indicator_config)
        position = position_full.loc[df.index]
        if max_holding_days is not None:
            position = _cap_holding_period(position, max_holding_days)
        stage_events = []
        trades = extract_weighted_trades(df, position)
    else:
        position_full = generate_positions(raw, indicator_config)
        position = position_full.loc[df.index]
        if max_holding_days is not None:
            position = _cap_holding_period(position, max_holding_days)
        stage_events = []
        trades = extract_trades(df, position, indicator_config)
    return position, trades, stage_events


def run_backtest(
    ticker: str,
    indicator_config: str | dict,
    start: str,
    end: str,
    label: str = "전략",
    max_holding_days: Optional[int] = None,
    monthly_contribution: float = 0.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    execution_model: Optional[str] = None,
    tax_bps: float = 0.0,
    adjust_prices: bool = False,
) -> BacktestRun:
    """지표 조합 전략을 특정 종목/기간에 대해 백테스팅한다.

    indicator_config가 1:2:6 식 단계별(staged) 전략 스키마("entry_stages" 포함)이면
    자동으로 core.strategy_engine.simulate_staged_positions 를 사용해 가중치 기반 포지션으로
    백테스팅한다 (별도 함수를 호출할 필요 없이 이 함수 하나로 두 전략 유형을 모두 처리한다).

    max_holding_days를 넘기면 스윙 트레이딩 보유기간 상한(예: 126거래일≈6개월)을 강제한다 —
    진입 후 그 날짜가 지나면 원래 신호와 무관하게 강제 청산한다.

    monthly_contribution > 0이면 매달 첫 거래일마다 그 금액을 추가 납입하는 적립식으로
    시뮬레이션한다 — 전략 포지션이 0인(관망) 동안 들어온 돈은 현금으로 누적만 되다가, 매수
    시그널이 뜨는 순간 그동안 쌓인 현금이 한꺼번에 투입된다(코스톨로니 법칙: 현금 누적 후 몰빵).
    이 경우 metrics의 cumulative_return/cagr은 원금대비 손익률/XIRR로 재정의된다
    (calculate_contribution_metrics 참고).

    fee_bps/slippage_bps(선택, 기본 0=비용 없음)는 compute_equity_curve/simulate_contribution_equity에
    그대로 전달되어 매매 회전율만큼 비용을 차감한다.

    execution_model(옵트인, 기본 None=기존 종가 기준): "next_open_ledger" 면 다음 거래일 시가 체결 원장
    (core.trade_ledger)으로 수익곡선을 계산하며 tax_bps 도 적용된다(월 적립과는 함께 쓸 수 없다).
    adjust_prices=True(옵트인)는 Adj Close/Close 비율로 OHLC 를 조정한다. 캐시 데이터의 Close 는 이미 분할 반영이므로 실제 효과는
    배당 재투자 가정의 총수익 기준 전환이며, 지표(이동평균 등) 계산에도 조정가격이 쓰인다.
    배당 현금 유입은 어느 경우에도 별도 반영하지 않으며 그 사실이 run.execution_meta 에 기록된다.
    """
    if execution_model not in (None, EXECUTION_CLOSE, EXECUTION_NEXT_OPEN):
        raise ValueError(f"알 수 없는 execution_model: {execution_model!r}")
    if execution_model == EXECUTION_NEXT_OPEN and monthly_contribution > 0:
        raise ValueError("next_open_ledger 는 월 적립(monthly_contribution)과 함께 쓸 수 없습니다")
    # 지표 warmup 기간(이동평균/일목균형표 등)을 위해 실제 조회는 시작일보다 앞서서 가져온 뒤 잘라낸다.
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=400)).date().isoformat()
    raw = get_price_history(ticker, start=fetch_start, end=end, use_cache=True)

    if raw is None or raw.empty:
        empty_idx = pd.DatetimeIndex([])
        return BacktestRun(
            label=label,
            ticker=ticker,
            df=pd.DataFrame(),
            position=pd.Series(dtype=float, index=empty_idx),
            equity_curve=pd.Series(dtype=float, index=empty_idx),
            trades=[],
            metrics=calculate_metrics(pd.Series(dtype=float), [], start, end),
        )

    if adjust_prices:
        from core.trade_ledger import adjust_ohlc_by_adj_close

        raw = adjust_ohlc_by_adj_close(raw)
    df = _slice_by_date(raw, start, end)
    position, trades, stage_events = _simulate_on_raw(raw, df, indicator_config, max_holding_days)

    contributed_capital = None
    if monthly_contribution > 0:
        equity_curve, contributed_capital = simulate_contribution_equity(
            df, position, monthly_contribution=monthly_contribution, fee_bps=fee_bps, slippage_bps=slippage_bps
        )
        metrics = calculate_contribution_metrics(equity_curve, contributed_capital, trades, df.index[0], df.index[-1])
    else:
        equity_curve = compute_equity_curve(df, position, fee_bps=fee_bps, slippage_bps=slippage_bps,
                                            execution_model=execution_model, tax_bps=tax_bps)
        metrics = calculate_metrics(equity_curve, trades, df.index[0], df.index[-1])

    execution_meta: dict = {}
    if execution_model == EXECUTION_NEXT_OPEN or adjust_prices:
        from core.trade_ledger import DIVIDEND_NOTE_ADJUSTED, DIVIDEND_NOTE_RAW

        execution_meta = {
            "execution_model": execution_model or EXECUTION_CLOSE,
            "adjust_prices": adjust_prices,
            "dividend_cash_flow_modeled": False,
            "dividend_note": DIVIDEND_NOTE_ADJUSTED if adjust_prices else DIVIDEND_NOTE_RAW,
        }

    return BacktestRun(
        label=label,
        ticker=ticker,
        df=df,
        position=position,
        equity_curve=equity_curve,
        trades=trades,
        metrics=metrics,
        stage_events=stage_events,
        contributed_capital=contributed_capital,
        execution_meta=execution_meta,
    )


def compute_regime_breakdown(run: BacktestRun, benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER) -> dict:
    """백테스트 결과를 국면별(강세장/약세장/횡보장)로 나눠 각 국면에 해당하는 날들만 모아
    누적수익률/거래일수를 계산한다 (core.market_regime.classify_daily_regime 재사용).

    국면이 바뀌는 날짜를 기준으로 구간을 자르는 게 아니라, 그 국면에 속한 날들의 일간수익률을
    전부 모아 복리로 계산한다(연속 구간일 필요 없음) — "이 전략이 약세장인 날들에는 대체로 어떻게
    움직였는지"를 보여주는 참고 지표다. market_regime을 여기서 모듈 최상단에 import하면
    market_regime.py가 이미 core.backtest_engine을 import하고 있어 순환참조가 나므로 함수 안에서
    지연 import한다.

    Returns:
        {"강세장": {"trading_days": int, "cumulative_return": float|None}, "약세장": {...}, "횡보장": {...}}
        equity_curve가 비어 있거나 벤치마크 데이터를 못 가져오면 빈 dict.
    """
    from core import market_regime

    if run.equity_curve.empty:
        return {}
    fetch_start = (run.equity_curve.index[0] - pd.DateOffset(days=400)).date().isoformat()
    bench = get_price_history(
        benchmark_ticker, start=fetch_start, end=run.equity_curve.index[-1].date().isoformat(), use_cache=True
    )
    if bench.empty:
        return {}

    regime = (
        market_regime.classify_daily_regime(bench["Close"], bench["High"], bench["Low"])
        .reindex(run.equity_curve.index)
        .ffill()
    )
    daily_return = run.equity_curve.pct_change().fillna(0.0)

    breakdown: dict = {}
    for label in ("강세장", "약세장", "횡보장"):
        mask = regime == label
        n_days = int(mask.sum())
        if n_days == 0:
            breakdown[label] = {"trading_days": 0, "cumulative_return": None}
            continue
        cum = float((1.0 + daily_return[mask]).prod() - 1) * 100
        breakdown[label] = {"trading_days": n_days, "cumulative_return": round(cum, 2)}
    return breakdown


_DIAGNOSTIC_TICKER = "AAPL"
_DIAGNOSTIC_LOOKBACK_YEARS = 5


def diagnose_strategy_health(indicator_config: str | dict) -> list[str]:
    """전략 설정을 대표 종목으로 미리 실행해, 진입/청산 조건이 서로 상충해 포지션이 사실상
    한 번도 유지되지 못하는(그래서 수익률이 항상 0%로 나오는) 흔한 결함을 조기에 경고한다.

    자연어 전략 등록(core.nl_strategy)은 AI가 만든 JSON이라 문법은 맞아도 의미상 자기모순인
    경우가 있다(예: 청산 조건이 진입 조건보다 항상 먼저/동시에 만족되는 경우). 이런 문제는
    특정 지표 조합에 국한되지 않으므로, 조건 자체를 정적으로 분석하는 대신 실제로 대표 종목
    한 종목·최근 몇 년 구간에 대해 돌려보고 "진입한 모든 매매가 진입 당일 바로 청산됐는지"를
    관찰하는 방식(경험적 검증)으로 판별한다. 사용자가 직접 프리뷰 백테스트를 돌려보기 전에
    자연어 전략 등록 UI에서 자동으로 호출된다 (app/pages/1_전략_스튜디오.py 참고).

    Returns:
        한국어 경고 메시지 리스트. 이상이 없거나 진단 자체가 불가능하면(가격 데이터 조회 실패 등)
        빈 리스트를 반환한다 — 사용자의 정상적인 등록 흐름을 막지 않기 위함이다.
    """
    end = pd.Timestamp.today().date().isoformat()
    start = (pd.Timestamp.today() - pd.DateOffset(years=_DIAGNOSTIC_LOOKBACK_YEARS)).date().isoformat()

    try:
        run = run_backtest(_DIAGNOSTIC_TICKER, indicator_config, start=start, end=end, label="자가진단")
    except Exception:
        return []

    if run.df.empty or not run.trades:
        return []

    same_day_trades = [t for t in run.trades if t.entry_date == t.exit_date]
    if not same_day_trades:
        return []

    ratio = len(same_day_trades) / len(run.trades)
    if ratio == 1.0:
        return [
            f"⚠️ 진입 조건과 청산 조건이 서로 겹쳐 보입니다 — {_DIAGNOSTIC_TICKER} 기준 최근 "
            f"{_DIAGNOSTIC_LOOKBACK_YEARS}년간 발생한 매매 {len(run.trades)}건이 전부 진입 당일 "
            "바로 청산됐습니다(포지션 보유 0일). 이 경우 실제로는 매수가 유지된 적이 없어 다른 종목/"
            "기간으로 백테스트를 돌려도 수익률이 항상 0%에 가깝게 나옵니다. 청산(exit_stages) 또는 "
            "긴급청산(emergency_exit) 조건이 진입 조건보다 더 쉽게 만족되지 않는지 확인해주세요."
        ]
    if ratio >= 0.5:
        return [
            f"⚠️ {_DIAGNOSTIC_TICKER} 기준 최근 {_DIAGNOSTIC_LOOKBACK_YEARS}년간 매매 {len(run.trades)}건 "
            f"중 {len(same_day_trades)}건이 진입 당일 바로 청산됐습니다. 청산 조건이 진입 조건과 자주 "
            "겹치는 것으로 보이니 결과를 그대로 믿기 전에 조건을 한 번 검토해보세요."
        ]
    return []


def trade_count_reliability_warning(trade_count: int) -> Optional[str]:
    """매매 횟수가 성과 지표(승률/샤프 등)를 신뢰하기에 통계적으로 충분한지 간단히 판정한다.

    대수의 법칙 — 표본이 적을수록 그 결과가 진짜 엣지인지 우연인지 구분하기 어렵다.
    MIN_TRADE_COUNT_CAUTION(30) 미만이면 강한 경고, MIN_TRADE_COUNT_RELIABLE(300) 미만이면
    약한 안내, 그 이상이면 None(경고 없음). run_permutation_test의 p-value처럼 정밀한 통계
    검증을 대체하지 않는, 화면에 바로 띄우기 위한 저비용 휴리스틱이다.
    """
    if trade_count < MIN_TRADE_COUNT_CAUTION:
        return (
            f"⚠️ 매매 횟수가 {trade_count}건으로 너무 적어 위 지표들(승률/샤프 등)을 신뢰하기 어렵습니다 "
            f"(최소 {MIN_TRADE_COUNT_CAUTION}건, 이상적으로는 {MIN_TRADE_COUNT_RELIABLE}건 이상 권장). "
            "표본이 적을수록 우연히 잘 나온 결과일 가능성이 큽니다 — 순열검정(p-value)으로 추가 검증을 권장합니다."
        )
    if trade_count < MIN_TRADE_COUNT_RELIABLE:
        return (
            f"ℹ️ 매매 횟수 {trade_count}건 — 통계적 신뢰도를 더 높이려면 {MIN_TRADE_COUNT_RELIABLE}건 "
            "이상을 권장합니다. 지금도 참고할 순 있지만 순열검정으로 함께 확인하는 걸 권장합니다."
        )
    return None


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


def compare_with_benchmarks(
    ticker: str,
    indicator_config: str | dict,
    start: str,
    end: str,
    benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER,
    max_holding_days: Optional[int] = None,
    monthly_contribution: float = 0.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> dict[str, BacktestRun]:
    """SPEC 모듈 A의 3-way 비교: 전략 적용 vs S&P500 매수보유 vs 개별종목 매수보유.

    max_holding_days는 "전략 적용" 쪽에만 적용된다 — 매수보유 벤치마크는 애초에 보유기간
    상한이라는 개념이 없는 순수 참고 지표라 그대로 둔다.

    monthly_contribution > 0이면 세 곡선 모두 동일한 금액을 매달 첫 거래일에 추가 납입하는
    적립식으로 계산한다. 매수보유 두 개는 자동으로 정액적립식(DCA, 매달 즉시 매수)이 되고,
    전략 적용 쪽은 관망 중 현금을 모았다가 매수 시그널이 뜰 때 몰빵하는 방식(코스톨로니 법칙)이
    된다 — run_backtest/run_buy_and_hold가 각자 이 차이를 알아서 반영하므로 여기서는 같은
    monthly_contribution 값만 그대로 넘기면 된다.

    fee_bps/slippage_bps(선택, 기본 0)도 세 곡선 모두에 동일하게 적용된다 — 전략 적용 쪽이
    매수보유보다 매매 회전율이 높은 게 보통이라, 비용을 반영하면 세 곡선의 격차가 실제보다
    부풀려져 있었는지(비용을 무시한 단순 비교의 함정) 확인할 수 있다.

    Returns:
        {"strategy": BacktestRun, "buy_and_hold_ticker": BacktestRun, "buy_and_hold_benchmark": BacktestRun}
    """
    return {
        "strategy": run_backtest(
            ticker,
            indicator_config,
            start,
            end,
            label=f"{ticker} 전략 적용",
            max_holding_days=max_holding_days,
            monthly_contribution=monthly_contribution,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        ),
        "buy_and_hold_ticker": run_buy_and_hold(
            ticker, start, end, label=f"{ticker} 매수 후 보유", monthly_contribution=monthly_contribution,
            fee_bps=fee_bps, slippage_bps=slippage_bps,
        ),
        "buy_and_hold_benchmark": run_buy_and_hold(
            benchmark_ticker, start, end, label="S&P500 매수 후 보유", monthly_contribution=monthly_contribution,
            fee_bps=fee_bps, slippage_bps=slippage_bps,
        ),
    }


def save_backtest_result(
    strategy_id: int,
    ticker: str,
    start: str,
    end: str,
    metrics: dict,
    extra_metrics: Optional[dict] = None,
) -> int:
    """백테스팅 결과를 backtest_results 테이블에 저장한다.

    Returns:
        생성된 BacktestResult.id
    """
    from core.db import get_session
    from core.models import BacktestResult

    with get_session() as session:
        row = BacktestResult(
            strategy_id=strategy_id,
            ticker=ticker,
            start_date=pd.Timestamp(start).date(),
            end_date=pd.Timestamp(end).date(),
            cumulative_return=metrics.get("cumulative_return"),
            cagr=metrics.get("cagr"),
            mdd=metrics.get("mdd"),
            sharpe=metrics.get("sharpe"),
            win_rate=metrics.get("win_rate"),
            trade_count=metrics.get("trade_count"),
            profit_factor=metrics.get("profit_factor"),
            calmar=metrics.get("calmar"),
            avg_drawdown_days=metrics.get("avg_drawdown_days"),
            extra_metrics=json.dumps(extra_metrics) if extra_metrics else None,
        )
        session.add(row)
        session.flush()
        return row.id


# =============================================================================
# 검증 테스트 4종 (Timothy Masters, 《Testing and Tuning Market Trading Systems》)
# 백테스트 수익률이 실제 통계적 엣지인지, 우연/과최적화인지를 가려낸다.
# =============================================================================


def run_sensitivity_sweep(
    ticker: str,
    variants: list[tuple[Any, str | dict]],
    start: str,
    end: str,
    metric: str = "sharpe",
    max_holding_days: Optional[int] = None,
) -> dict:
    """[테스트 1: 민감도] 파라미터 값을 바꿔가며 반복 백테스팅해 결과가 완만하게 변하는지(견고함)
    아니면 특정 값에서만 튀는지(과최적화 의심)를 확인한다.

    variants는 (파라미터 값, 그 값을 반영한 전략 설정) 튜플 리스트다 — 파라미터 값을 실제로
    전략 설정에 반영하는 방법은 스키마(단순 조건 dict / 1:2:6 staged / 자연어 표현식)마다 달라
    호출부가 만들어서 넘긴다. 이 함수는 "그 목록을 실제로 순서대로 돌려서 결과가 매끄러운지"
    측정하는 실행/평가만 담당한다. variants는 파라미터 값 기준 오름차순으로 정렬돼 있어야
    이웃 포인트 간 변화폭이 의미가 있다.

    Returns:
        {
            "points": [{"param_value": ..., "metric": float|None, "metrics": dict}, ...],
            "is_robust": bool|None,   # 이웃 값끼리 결과가 완만하게 변하는지 (포인트 2개 미만이면 None)
            "max_jump": float|None,   # 이웃 포인트 간 최대 변화폭(과최적화 스파이크 탐지용)
            "metric_range": float|None,
        }
    """
    points = []
    for param_value, config in variants:
        run = run_backtest(ticker, config, start, end, max_holding_days=max_holding_days)
        points.append({"param_value": param_value, "metric": run.metrics.get(metric), "metrics": run.metrics})

    metric_values = [p["metric"] for p in points if p["metric"] is not None]
    if len(metric_values) < 2:
        return {"points": points, "is_robust": None, "max_jump": None, "metric_range": None}

    jumps = [abs(metric_values[i + 1] - metric_values[i]) for i in range(len(metric_values) - 1)]
    metric_range = max(metric_values) - min(metric_values)
    max_jump = max(jumps)
    # 휴리스틱: 이웃 값 사이 단 한 번의 변화폭이 전체 값 범위의 절반을 넘으면 특정 파라미터
    # 값에서만 결과가 튀는 것으로 보고 '견고하지 않음'(과최적화 의심)으로 판정한다.
    is_robust = metric_range == 0 or (max_jump / metric_range) <= 0.5

    return {
        "points": points,
        "is_robust": is_robust,
        "max_jump": round(max_jump, 4),
        "metric_range": round(metric_range, 4),
    }


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


def run_permutation_test(
    ticker: str,
    indicator_config: str | dict,
    start: str,
    end: str,
    n_permutations: int = 200,
    metric: str = "cumulative_return",
    max_holding_days: Optional[int] = None,
    seed: Optional[int] = None,
) -> dict:
    """[테스트 2: 순열] 가격 데이터를 무작위로 섞은 가짜 시계열 n_permutations개에 동일한 전략을
    돌려 metric의 분포를 만들고, 실제 백테스트 결과가 그 분포에서 얼마나 특이한지(p-value)를 잰다.

    n_permutations가 클수록(예: 1000) 결과가 정밀해지지만 그만큼 백테스트를 반복 실행해야 해서
    느려진다 — 기본값 200은 정확도와 실행 시간의 절충이며, 최종 검증에는 더 큰 값을 권장한다.

    Returns:
        {
            "actual_metric": float|None,
            "actual_metrics": dict,
            "permuted_metrics": list[float],
            "p_value": float|None,     # (실제보다 같거나 좋은 순열 결과 수 + 1) / (n + 1), 작을수록 유의미
            "percentile": float|None,  # 실제 결과가 순열 분포에서 위치한 백분위(0~100)
            "n_permutations": int,
        }
    """
    actual_run = run_backtest(ticker, indicator_config, start, end, max_holding_days=max_holding_days)
    empty_result = {
        "actual_metric": None,
        "actual_metrics": actual_run.metrics,
        "permuted_metrics": [],
        "p_value": None,
        "percentile": None,
        "n_permutations": 0,
    }
    if actual_run.df.empty:
        return empty_result

    actual_metric = actual_run.metrics.get(metric)

    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=400)).date().isoformat()
    raw = get_price_history(ticker, start=fetch_start, end=end, use_cache=True)
    if raw is None or raw.empty:
        return empty_result
    df = _slice_by_date(raw, start, end)
    if df.empty:
        return empty_result

    rng = np.random.default_rng(seed)
    permuted_metrics = []
    for _ in range(n_permutations):
        synthetic_raw = _shuffle_daily_bars(raw, df.index[0], df.index[-1], rng)
        synthetic_df = synthetic_raw.loc[df.index]
        position, trades, _ = _simulate_on_raw(synthetic_raw, synthetic_df, indicator_config, max_holding_days)
        equity_curve = compute_equity_curve(synthetic_df, position)
        synthetic_metrics = calculate_metrics(equity_curve, trades, synthetic_df.index[0], synthetic_df.index[-1])
        permuted_metrics.append(synthetic_metrics.get(metric, 0.0))

    if actual_metric is None or not permuted_metrics:
        p_value = None
        percentile = None
    else:
        better_or_equal = sum(1 for m in permuted_metrics if m >= actual_metric)
        p_value = round((better_or_equal + 1) / (n_permutations + 1), 4)
        worse = sum(1 for m in permuted_metrics if m < actual_metric)
        percentile = round(100.0 * worse / len(permuted_metrics), 2)

    return {
        "actual_metric": actual_metric,
        "actual_metrics": actual_run.metrics,
        "permuted_metrics": permuted_metrics,
        "p_value": p_value,
        "percentile": percentile,
        "n_permutations": n_permutations,
    }


def run_partition_test(
    strategy_run: BacktestRun,
    benchmark_run: BacktestRun,
    bias_log_return: float = 0.0,
) -> dict:
    """[테스트 3: 분해] 총 로그수익률을 추세(trend) + 실력(skill) + 편향(bias)으로 분해한다.

    - trend: 전략이 실제로 시장에 노출돼 있었던 비율(exposure_fraction)만큼, 벤치마크에 아무
      타이밍 없이 무작위로 그 비율만큼만 노출됐어도 평균적으로 얻었을 로그수익률
      (exposure_fraction * 벤치마크 총 로그수익률).
    - skill: 총 로그수익률에서 trend와 bias를 뺀 나머지 — "언제 들어가고 나왔는지"의 타이밍이
      만든 몫.
    - bias: 파라미터 최적화로 인한 인플레이션 추정치. 단일 백테스트만으로는 추정할 수 없어(표본외
      검증이 별도로 필요) 이 함수는 계산하지 않는다 — 호출부가 walk-forward 등으로 따로 구한 값을
      넘기면 그만큼을 skill에서 떼어낸다. 넘기지 않으면 0(최적화를 하지 않았다고 가정).

    strategy_run/benchmark_run 모두 monthly_contribution 없이(적립식이 아닌) 계산된 결과여야
    한다 — 적립식은 equity_curve가 현금흐름을 포함해 로그수익률 분해의 전제가 깨진다.

    Returns:
        {"total_log_return": ..., "trend_log_return": ..., "skill_log_return": ...,
         "bias_log_return": ..., "skill_pct_of_total": float|None, "exposure_pct": ...}
    """
    empty = {
        "total_log_return": 0.0,
        "trend_log_return": 0.0,
        "skill_log_return": 0.0,
        "bias_log_return": bias_log_return,
        "skill_pct_of_total": None,
        "exposure_pct": 0.0,
    }
    if strategy_run.equity_curve.empty or benchmark_run.equity_curve.empty:
        return empty

    total_log_return = math.log(strategy_run.equity_curve.iloc[-1] / strategy_run.equity_curve.iloc[0])
    benchmark_log_return = math.log(benchmark_run.equity_curve.iloc[-1] / benchmark_run.equity_curve.iloc[0])

    # compute_equity_curve와 동일하게 신호 발생 다음 날 체결(shift)된 노출 비율 기준.
    executed_position = strategy_run.position.shift(1).fillna(0).astype(float).clip(lower=0.0, upper=1.0)
    exposure_fraction = float(executed_position.mean()) if len(executed_position) else 0.0

    trend_log_return = exposure_fraction * benchmark_log_return
    skill_log_return = total_log_return - trend_log_return - bias_log_return
    skill_pct_of_total = (skill_log_return / total_log_return * 100) if total_log_return != 0 else None

    return {
        "total_log_return": round(total_log_return, 4),
        "trend_log_return": round(trend_log_return, 4),
        "skill_log_return": round(skill_log_return, 4),
        "bias_log_return": round(bias_log_return, 4),
        "skill_pct_of_total": round(skill_pct_of_total, 2) if skill_pct_of_total is not None else None,
        "exposure_pct": round(exposure_fraction * 100, 2),
    }


def summarize_strategy_vs_benchmarks(comparison: dict[str, BacktestRun], regime_breakdown: Optional[dict] = None) -> dict:
    """[테스트 4: 벤치마크 비교] compare_with_benchmarks() 결과를 놓고 원수익률 하나만으로 끝내지
    않고 CAGR/MDD(방어력)/샤프(위험조정수익률) 네 축 전부에서 벤치마크(개별종목 매수보유) 대비
    승패를 구조화한다 — "원수익률은 졌지만 방어력·위험조정수익률은 이겼다" 같은 판단을 호출부(UI)가
    바로 문구로 보여줄 수 있게 한다. regime_breakdown(compute_regime_breakdown 결과)을 함께 넘기면
    국면별 성과도 그대로 담아 반환한다.

    Returns:
        {"beats_on_return": bool, "beats_on_cagr": bool, "beats_on_mdd": bool, "beats_on_sharpe": bool,
         "strategy_metrics": dict, "benchmark_metrics": dict, "regime_breakdown": dict|None}
    """
    strategy = comparison["strategy"].metrics
    benchmark = comparison["buy_and_hold_ticker"].metrics
    return {
        "beats_on_return": strategy["cumulative_return"] > benchmark["cumulative_return"],
        "beats_on_cagr": strategy["cagr"] > benchmark["cagr"],
        # mdd는 음수로 저장된다 — 0에 더 가까울수록(덜 마이너스일수록) 낙폭이 작아 방어적이다.
        "beats_on_mdd": strategy["mdd"] > benchmark["mdd"],
        "beats_on_sharpe": strategy["sharpe"] > benchmark["sharpe"],
        "strategy_metrics": strategy,
        "benchmark_metrics": benchmark,
        "regime_breakdown": regime_breakdown,
    }


# =============================================================================
# 전략 포트폴리오 상관관계 ("홀리그레일": 비상관 전략의 조합이 단일 전략보다 위험조정수익률이
# 낫다는 개념을 실제로 확인하는 도구). core.portfolio가 "종목" 간 상관관계를 다루는 것과 대칭으로,
# 여기서는 "전략" 간 상관관계를 다룬다 — 서로 다른 전략의 자산가치 곡선(equity curve)에서 일간
# 수익률을 뽑아 상관계수 행렬을 만든다.
# =============================================================================


def run_strategy_portfolio(
    strategies: list[tuple[str, str, str | dict]], start: str, end: str
) -> dict[str, BacktestRun]:
    """여러 (라벨, 종목, indicator_config) 조합을 각각 백테스트해 {라벨: BacktestRun}으로 반환한다.

    compute_strategy_correlation/compute_strategy_regime_correlation의 입력을 만드는 편의 함수 —
    호출부(UI)가 전략 라이브러리에서 여러 전략을 골라 이 형태로 넘기면 된다.
    """
    return {label: run_backtest(ticker, config, start, end, label=label) for label, ticker, config in strategies}


def _strategy_daily_returns(runs: dict[str, BacktestRun]) -> pd.DataFrame:
    """{라벨: BacktestRun}에서 자산가치 곡선의 일간수익률만 뽑아 하나의 DataFrame으로 정렬한다
    (컬럼=전략 라벨). equity_curve가 비어있는 항목은 건너뛴다."""
    returns = {}
    for label, run in runs.items():
        if run.equity_curve is not None and not run.equity_curve.empty:
            returns[label] = run.equity_curve.pct_change().dropna()
    if len(returns) < 2:
        return pd.DataFrame()
    return pd.DataFrame(returns).dropna(how="any")


def compute_strategy_correlation(runs: dict[str, BacktestRun]) -> pd.DataFrame:
    """여러 BacktestRun(전략별 실행 결과)의 일간수익률로 상관계수 행렬을 만든다.

    core.portfolio.compute_correlation_matrix와 동일한 계산이지만 대상이 종목이 아니라 전략이다 —
    "비상관 전략을 몇 개나 더할 수 있는가"라는 홀리그레일 개념을 실제 수치로 확인하기 위함.
    유효한 전략이 2개 미만이면 빈 DataFrame.
    """
    combined = _strategy_daily_returns(runs)
    if combined.empty:
        return pd.DataFrame()
    return combined.corr()


def compute_strategy_regime_correlation(
    runs: dict[str, BacktestRun], benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER
) -> dict[str, pd.DataFrame]:
    """compute_strategy_correlation을 국면별(강세장/약세장/횡보장)로 나눠 계산한다.

    평상시엔 낮아 보이는 전략 간 상관관계도 약세장(스트레스 이벤트)에는 다 같이 무너지며 급등할 수
    있다 — core.market_regime.compute_regime_conditional_correlation을 재사용한다. market_regime이
    이미 core.backtest_engine을 모듈 최상단에서 import하고 있어(순환참조 방지) 여기서는 지연 import한다.
    """
    from core import market_regime

    combined = _strategy_daily_returns(runs)
    if combined.empty:
        return {}
    return market_regime.compute_regime_conditional_correlation(combined, benchmark_ticker=benchmark_ticker)


def save_strategy_correlation_snapshot(corr_matrix: pd.DataFrame) -> int:
    """compute_strategy_correlation() 결과를 strategy_decay_checks와 같은 원칙(덮어쓰지 않고 계속
    쌓는 이력)으로 correlation_snapshots 테이블에 저장한다.

    "이번 달 상관관계가 높다고 바로 전략을 빼지 말고, 2~3개월치 이력을 보고 판단하라"는 원칙
    (2026-07-27 인사이트)을 UI가 실제로 실천할 수 있게 하는 저장소 — 대각선(자기 자신과의
    상관계수=1)을 제외한 비대각 원소의 평균/최댓값을 요약치로 함께 저장한다.
    """
    from core.db import get_session
    from core.models import CorrelationSnapshot

    labels = list(corr_matrix.columns)
    n = len(labels)
    if n < 2:
        raise ValueError("상관관계 스냅샷을 저장하려면 2개 이상의 전략이 필요합니다.")
    off_diag_mask = ~np.eye(n, dtype=bool)
    off_diag = corr_matrix.to_numpy()[off_diag_mask]

    with get_session() as session:
        row = CorrelationSnapshot(
            kind="strategy",
            labels=json.dumps(labels, ensure_ascii=False),
            avg_correlation=float(off_diag.mean()),
            max_correlation=float(off_diag.max()),
            matrix=corr_matrix.to_json(),
        )
        session.add(row)
        session.flush()
        return row.id


def list_strategy_correlation_snapshots(limit: int = 12) -> list[dict]:
    """전략 간 상관관계 체크 이력을 최신순으로 반환한다."""
    from core.db import get_session
    from core.models import CorrelationSnapshot

    with get_session() as session:
        rows = (
            session.query(CorrelationSnapshot)
            .filter(CorrelationSnapshot.kind == "strategy")
            .order_by(CorrelationSnapshot.computed_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "labels": json.loads(r.labels),
                "avg_correlation": r.avg_correlation,
                "max_correlation": r.max_correlation,
                "computed_at": r.computed_at,
            }
            for r in rows
        ]


# =============================================================================
# 전략 수명 / 알파 감쇠 모니터링
#
# 백테스트로 검증된 전략도 시간이 지나며 엣지가 사라질 수 있다("알파 감쇠"). 여기서는 같은
# indicator_config를 재튜닝(파라미터 재조정) 없이 최근 구간에 그대로 재적용해, "예전에 검증된
# 조건이 최근에도 여전히 통하는지"를 전체 기간 성과와 비교한다. 일부러 재튜닝을 하지 않는 이유는,
# 재튜닝을 섞으면 최근 성과가 좋아 보이는 게 원래 전략의 지속성 때문인지 파라미터를 최근 데이터에
# 새로 맞춰서(과최적화)인지 구분할 수 없기 때문이다.
# =============================================================================

DEFAULT_DECAY_RECENT_MONTHS = 6
DEFAULT_DECAY_METRIC = "sharpe"
_DECAY_RATIO_THRESHOLD = 0.3  # 최근/전체 비율이 이 아래로 떨어지면 감쇠 의심


def compute_alpha_decay(
    ticker: str,
    indicator_config: str | dict,
    full_start: str,
    full_end: str,
    recent_months: int = DEFAULT_DECAY_RECENT_MONTHS,
    metric: str = DEFAULT_DECAY_METRIC,
) -> dict:
    """전체 기간 백테스트 대비 최근 recent_months개월 성과가 얼마나 이탈했는지 비교한다.

    Returns:
        {
            "full_metrics": dict, "recent_metrics": dict, "metric": str,
            "decay_ratio": float|None,   # recent_metric / full_metric (full_metric<=0이면 비율 자체가
                무의미해 None) — 1.0에 가까울수록 성과가 그대로 유지, 0에 가까울거나 음수면 감쇠.
            "is_decayed": bool,          # decay_ratio < _DECAY_RATIO_THRESHOLD 이거나 최근 metric이
                음수로 돌아섰으면 True. full_metric<=0(원래도 엣지가 약했던 전략)이면 최근이 더
                나빠졌는지만 절대값으로 비교해 판정한다.
            "recent_start": str, "recent_end": str,
        }
        ticker 데이터를 가져오지 못하면 모든 metrics가 빈 값인 상태로 반환한다.
    """
    full_run = run_backtest(ticker, indicator_config, full_start, full_end, label="전체기간")
    empty_metrics = calculate_metrics(pd.Series(dtype=float), [], full_start, full_end)
    if full_run.df.empty:
        return {
            "full_metrics": empty_metrics,
            "recent_metrics": empty_metrics,
            "metric": metric,
            "decay_ratio": None,
            "is_decayed": False,
            "recent_start": full_end,
            "recent_end": full_end,
        }

    recent_start = (pd.Timestamp(full_end) - pd.DateOffset(months=recent_months)).date().isoformat()
    recent_run = run_backtest(ticker, indicator_config, recent_start, full_end, label="최근기간")

    full_metric = full_run.metrics.get(metric)
    recent_metric = recent_run.metrics.get(metric)

    decay_ratio: Optional[float] = None
    is_decayed = False
    if full_metric is not None and recent_metric is not None:
        if full_metric > 0:
            decay_ratio = recent_metric / full_metric
            is_decayed = decay_ratio < _DECAY_RATIO_THRESHOLD or recent_metric < 0
        else:
            # 전체 기간부터 이미 엣지가 약했던(0 이하) 전략 — 비율은 무의미하므로 절대값 악화 여부만 본다.
            is_decayed = recent_metric < full_metric

    return {
        "full_metrics": full_run.metrics,
        "recent_metrics": recent_run.metrics,
        "metric": metric,
        "decay_ratio": round(decay_ratio, 3) if decay_ratio is not None else None,
        "is_decayed": is_decayed,
        "recent_start": recent_start,
        "recent_end": full_end,
    }


def save_decay_check(ticker: str, result: dict, strategy_id: Optional[int] = None) -> int:
    """compute_alpha_decay() 결과를 strategy_decay_checks 테이블에 이력으로 저장한다 (덮어쓰지 않고
    계속 쌓음 — market_regime.save_market_regime_snapshot 등과 동일한 스냅샷 누적 원칙).

    strategy_id는 전략 라이브러리에 저장된 전략일 때만 채운다("직접 설정" 임시 백테스트는 None).
    """
    from core.db import get_session
    from core.models import StrategyDecayCheck

    with get_session() as session:
        row = StrategyDecayCheck(
            strategy_id=strategy_id,
            ticker=ticker,
            metric=result["metric"],
            full_metrics=json.dumps(result["full_metrics"], ensure_ascii=False),
            recent_metrics=json.dumps(result["recent_metrics"], ensure_ascii=False),
            decay_ratio=result["decay_ratio"],
            is_decayed=result["is_decayed"],
            recent_start=pd.Timestamp(result["recent_start"]).date(),
            recent_end=pd.Timestamp(result["recent_end"]).date(),
        )
        session.add(row)
        session.flush()
        return row.id


def list_decay_checks(strategy_id: int, limit: int = 20) -> list[dict]:
    """특정 전략의 알파 감쇠 체크 이력을 최신순으로 반환한다."""
    from core.db import get_session
    from core.models import StrategyDecayCheck

    with get_session() as session:
        rows = (
            session.query(StrategyDecayCheck)
            .filter(StrategyDecayCheck.strategy_id == strategy_id)
            .order_by(StrategyDecayCheck.computed_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "ticker": r.ticker,
                "metric": r.metric,
                "full_metrics": json.loads(r.full_metrics),
                "recent_metrics": json.loads(r.recent_metrics),
                "decay_ratio": r.decay_ratio,
                "is_decayed": r.is_decayed,
                "recent_start": r.recent_start,
                "recent_end": r.recent_end,
                "computed_at": r.computed_at,
            }
            for r in rows
        ]


# =============================================================================
# 팩터 분해 (Fama-French 스타일, ETF 프록시)
#
# 이 프로젝트는 정식 팩터 데이터(Ken French Data Library 등) 소스를 갖고 있지 않고 새로 추가하지도
# 않는다 — 대신 이미 이 프로젝트가 쓰고 있는 get_multiple_price_history로 받을 수 있는 유동성 높은
# ETF들의 수익률 차이로 각 팩터를 근사한다. 이는 Portfolio Visualizer 등에서 실제로 쓰이는, 개인/
# 실무 투자자 사이에 널리 알려진 정석적인 근사 기법이다 — 그러나 어디까지나 "근사치"이지 실제 Ken
# French 팩터 데이터가 아니므로, 아래 함수들과 UI 모두 이 점을 분명히 밝힌다.
#
# run_permutation_test(그 결과가 우연이 아닌지 검증)를 대체하지 않는다 — 이미 순열검정을 통과한
# 전략이 "왜" 그런 수익을 냈는지(시장/사이즈/가치/모멘텀 중 어디서 왔는지) 설명하는 보완 도구다.
# =============================================================================

# 시장(SPY) / 사이즈(소형주 IJR) / 가치(IWD) / 성장(IWF, HML 계산용) / 모멘텀(MTUM) 프록시.
# 전부 유동성이 매우 높은 대형 ETF라 get_multiple_price_history가 이미 캐싱까지 포함해 안정적으로
# 받아올 수 있다.
FACTOR_PROXY_TICKERS = ["SPY", "IJR", "IWD", "IWF", "MTUM"]

# 무위험수익률(risk-free rate) 프록시 — 이 프로젝트가 이미 매크로 대시보드에서 쓰고 있는 FRED
# 연방기금금리(연율 %) 시계열을 재사용한다 (core/fred_data.py DEFAULT_INDICATORS 참고).
_RISK_FREE_FRED_SERIES = "FEDFUNDS"

# run_factor_regression이 회귀분석을 신뢰하기 위한 최소 공통 관측치 수 — MIN_TRADE_COUNT_CAUTION과
# 같은 대수의 법칙 경험칙(표본이 적으면 회귀계수가 우연히 크게 흔들릴 수 있음)을 그대로 적용한다.
_FACTOR_REGRESSION_MIN_OBSERVATIONS = 30


def compute_factor_returns(start: str, end: str) -> pd.DataFrame:
    """Fama-French 스타일 4팩터(시장/사이즈/가치/모멘텀)를 ETF 수익률로 근사해 일별 시계열로 만든다.

    실제 Ken French 데이터 라이브러리의 팩터가 아니라, 유동성 높은 ETF들의 일간수익률 "차이"로
    근사한 프록시다:
      - MKT_RF(시장 초과수익률): SPY 일간수익률 - 무위험수익률(FRED FEDFUNDS 연율%를 252로 나눈
        일간 근사치)
      - SMB(사이즈, Small Minus Big): 소형주 ETF(IJR) 수익률 - SPY 수익률
      - HML(가치, High Minus Low): 가치주 ETF(IWD) 수익률 - 성장주 ETF(IWF) 수익률
      - MOM(모멘텀): 모멘텀 팩터 ETF(MTUM) 수익률 - SPY 수익률

    FRED_API_KEY가 설정되지 않았거나 조회가 실패해 무위험수익률을 못 가져오면(core.fred_data의
    기존 관례대로 예외 없이 빈 Series 반환) 0으로 대체하고 그대로 계산을 진행한다 — MKT_RF가
    사실상 SPY 총수익률이 되어 근사치의 정확도가 살짝 떨어질 뿐, 이 프로젝트의 "선택적 데이터가
    없으면 성능 저하 없이 계속 진행한다"는 기존 원칙(core.fred_data 독스트링 참고)을 그대로 따른다.

    Returns:
        DatetimeIndex 기준 일별 DataFrame, 컬럼 ["MKT_RF", "SMB", "HML", "MOM"]. 프록시 ETF 중
        하나라도 가격 데이터를 가져오지 못하면(네트워크 오류 등) 빈 DataFrame을 반환한다(예외를
        던지지 않음 — 호출부가 그대로 "계산 불가" 상태로 처리할 수 있게 함).
    """
    # core.portfolio는 core.market_regime을 import하고, market_regime은 다시 core.backtest_engine을
    # 모듈 최상단에서 import한다 — 순환참조를 피하려고(compute_regime_breakdown 등과 동일한 이유로)
    # 여기서 지연 import한다.
    from core.portfolio import compute_daily_returns

    price_histories = get_multiple_price_history(FACTOR_PROXY_TICKERS, start=start, end=end, use_cache=True)
    daily_returns = compute_daily_returns(price_histories)
    if daily_returns.empty or not set(FACTOR_PROXY_TICKERS).issubset(set(daily_returns.columns)):
        return pd.DataFrame()

    # 무위험수익률(FRED FEDFUNDS, 연율 %)은 월별 발표라, 일별 인덱스에 맞춰 직전 발표값을 그대로
    # 이어쓴다(reindex + ffill = as-of 방식). 일간수익률 시작일 바로 앞의 값이 필요할 수 있어 조회
    # 구간에 넉넉히 버퍼를 둔다.
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=90)).date().isoformat()
    rf_annual_pct = fred_data.get_series(_RISK_FREE_FRED_SERIES, start=fetch_start, end=end)
    if rf_annual_pct.empty:
        daily_rf = pd.Series(0.0, index=daily_returns.index)
    else:
        daily_rf = rf_annual_pct.reindex(daily_returns.index, method="ffill") / 100.0 / TRADING_DAYS_PER_YEAR
        # FEDFUNDS 이력이 일간수익률 시작일보다 짧아 ffill로도 못 채우는 극초반 구간은 0으로 둔다.
        daily_rf = daily_rf.fillna(0.0)

    factors = pd.DataFrame(
        {
            "MKT_RF": daily_returns["SPY"] - daily_rf,
            "SMB": daily_returns["IJR"] - daily_returns["SPY"],
            "HML": daily_returns["IWD"] - daily_returns["IWF"],
            "MOM": daily_returns["MTUM"] - daily_returns["SPY"],
        }
    )
    return factors.dropna(how="any")


_FACTOR_NAMES = ("MKT_RF", "SMB", "HML", "MOM")


def run_factor_regression(strategy_daily_returns: pd.Series, factor_returns: pd.DataFrame) -> dict:
    """전략 일간수익률을 4개 팩터(MKT_RF/SMB/HML/MOM)에 OLS 회귀분석해 알파/베타/R²를 구한다.

    scipy/statsmodels 없이(이 프로젝트의 의존성 정책, requirements.txt 참고) numpy.linalg.lstsq로
    직접 최소자승 회귀를 계산한다 — run_permutation_test 등 이 파일의 다른 통계 검증과 동일하게
    순수 numpy로 구현하는 방식을 따른다.

    "알파(alpha_daily)"의 의미: 회귀식의 절편(intercept) — 4개 팩터 노출로는 설명되지 않는, 하루
    평균 초과수익률이다. 양수면 팩터 노출만으로 설명 안 되는 몫(종목 선정/타이밍의 실력, 혹은 아직
    못 잡아낸 다른 요인)이 있다는 뜻이고, 음수면 팩터 노출을 감안했을 때 오히려 손해를 보고 있다는
    뜻이다.

    "베타(betas)"의 의미: 각 팩터에 대한 민감도(기여도) — 예를 들어 MKT_RF 베타가 1.2면 시장이 1%
    움직일 때 전략이 평균 1.2% 움직인다는 뜻이고, SMB 베타가 양수면 소형주 성향, HML 베타가 양수면
    가치주 성향, MOM 베타가 양수면 모멘텀 추종 성향을 보인다는 뜻이다. Portfolio Visualizer의 팩터
    회귀분석과 동일한 해석 방식이다.

    이 분석은 run_permutation_test(백테스트 결과가 우연인지 아닌지)를 대체하지 않는다 — 이미 순열
    검정을 통과한 전략이 "왜" 그런 수익을 냈는지 설명하는 보완 도구일 뿐이다.

    두 시리즈가 이미 정렬돼 있다고 가정하지 않고, 공통 거래일만 골라(inner join) 정렬한 뒤
    회귀한다.

    Returns:
        {
            "alpha_daily": float, "alpha_annualized_pct": float,
            "betas": {"MKT_RF": float, "SMB": float, "HML": float, "MOM": float},
            "r_squared": float, "n_observations": int,
        }
        공통 관측치가 _FACTOR_REGRESSION_MIN_OBSERVATIONS(30) 미만이면(회귀를 신뢰하기엔 표본이
        너무 적음) 대신 {"error": str, "n_observations": int}를 반환한다 — 예외를 던지거나 의미
        없는 계수를 그대로 내보내지 않는다.
    """
    aligned = factor_returns.join(strategy_daily_returns.rename("strategy"), how="inner").dropna()
    n = len(aligned)
    if n < _FACTOR_REGRESSION_MIN_OBSERVATIONS:
        return {
            "error": (
                f"공통 관측치가 {n}개로 너무 적어 팩터 회귀분석을 신뢰할 수 없습니다 "
                f"(최소 {_FACTOR_REGRESSION_MIN_OBSERVATIONS}개 필요)."
            ),
            "n_observations": n,
        }

    x = aligned[list(_FACTOR_NAMES)].to_numpy(dtype=float)
    y = aligned["strategy"].to_numpy(dtype=float)
    x_with_intercept = np.column_stack([np.ones(n), x])  # 절편(알파) 항을 첫 컬럼으로 추가

    coefs, _, _, _ = np.linalg.lstsq(x_with_intercept, y, rcond=None)
    alpha_daily = float(coefs[0])
    betas = {name: float(b) for name, b in zip(_FACTOR_NAMES, coefs[1:])}

    residuals = y - x_with_intercept @ coefs
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return {
        "alpha_daily": alpha_daily,
        "alpha_annualized_pct": ((1.0 + alpha_daily) ** TRADING_DAYS_PER_YEAR - 1.0) * 100.0,
        "betas": betas,
        "r_squared": r_squared,
        "n_observations": n,
    }


# =============================================================================
# 몬테카를로 시뮬레이션 (블록 부트스트랩)
#
# 실제로 벌어진 경로는 하나뿐이다 — 그 하나의 표본만으로 "이 전략은 이 정도 수익/낙폭이 난다"고
# 단정하면, 우연히 유리했던(또는 불리했던) 순서 하나에 과도하게 의존하게 된다. 여기서는 과거 일간
# 수익률을 재표집해 대안 경로 여러 개를 만들어, 최종 성과의 분포(그리고 손실로 끝날 확률)를 보여준다.
#
# 하루 단위로 독립적으로(i.i.d.) 재표집하지 않고 "연속된 블록" 단위로 복원추출하는 이유: 실제
# 수익률에는 변동성 군집(vol clustering)과 자기상관이 있는데, i.i.d. 재표집은 이 구조를 완전히
# 파괴해 꼬리 위험(tail risk)을 실제보다 과소평가하게 만든다. 블록 단위로 뽑으면 "변동성이 높았던
# 한 달"이 통째로 재사용되므로 이 구조가 어느 정도 보존된다.
# =============================================================================

# 블록 길이(거래일 기준) 기본값 — 약 1개월. 짧은 구간의 변동성 군집/자기상관을 보존하기에 충분히
# 길면서도 표집 다양성을 해칠 만큼 길지는 않은 절충값이다(이동블록 부트스트랩의 실무적 경험칙:
# 표본 크기의 제곱근~세제곱근 근방을 흔히 쓴다).
DEFAULT_MONTE_CARLO_BLOCK_SIZE = 20


def run_monte_carlo_simulation(
    daily_returns: pd.Series,
    n_simulations: int = 1000,
    horizon_days: Optional[int] = None,
    block_size: int = DEFAULT_MONTE_CARLO_BLOCK_SIZE,
    random_seed: Optional[int] = None,
) -> dict:
    """일간수익률 시계열을 블록 부트스트랩으로 재표집해 미래 경로 n_simulations개를 시뮬레이션한다.

    block_size(기본 20거래일 ≈ 1개월) 길이의 연속된 구간을 통째로 무작위 복원추출해 이어붙이는
    방식이다(모듈 상단 설명 참고 — i.i.d. 재표집과 달리 변동성 군집 구조를 보존한다).
    horizon_days(기본값: len(daily_returns), 즉 과거와 같은 길이만큼 미래를 시뮬레이션)에 도달할
    때까지 블록을 이어붙이고, 마지막 블록은 필요한 만큼만 잘라 정확히 horizon_days 길이를 맞춘다.

    random_seed를 주면 (테스트에서 값을 고정해 검증할 수 있도록) 항상 같은 결과가 나오고, 주지
    않으면 매번 새로운 난수열(np.random.default_rng())을 쓴다.

    1000개 시뮬레이션 x 수백 거래일 규모는 numpy만으로 1초 이내에 끝나는 계산량이라, Streamlit
    버튼 클릭에 동기적으로 실행해도 무방하다 — 별도 백그라운드 작업(core.job_manager)으로 뺄 필요는
    없다.

    Returns:
        {
            "paths": np.ndarray, shape (n_simulations, horizon_days) — 각 시뮬레이션의 누적수익률
                배수(1.0=원금 그대로, 1.2=+20%) 경로.
            "percentile_bands": {"p10": array, "p50": array, "p90": array} — 각 날짜별로 전체
                시뮬레이션 중 10/50/90 백분위수 누적수익률 배수 (길이 horizon_days).
            "final_return_pct": {"p10": float, "p50": float, "p90": float} — 마지막 날 누적수익률(%)
                의 10/50/90 백분위수.
            "prob_of_loss": float — 마지막 날 누적수익률이 0% 미만으로 끝난 시뮬레이션의 비율(0~1).
            "n_simulations": int, "horizon_days": int,
        }
        daily_returns가 비어있거나 horizon_days/n_simulations가 0 이하면, 예외를 던지는 대신 모든
        수치를 빈 값/0으로 채운 동일한 형태의 dict를 반환한다(이 프로젝트의 "데이터/입력이 부족하면
        그대로 진행한다" 기존 원칙).
    """
    horizon = horizon_days if horizon_days is not None else len(daily_returns)
    returns_arr = daily_returns.dropna().to_numpy(dtype=float)
    n_obs = len(returns_arr)

    if n_obs == 0 or horizon <= 0 or n_simulations <= 0:
        return {
            "paths": np.zeros((0, max(horizon, 0))),
            "percentile_bands": {"p10": np.array([]), "p50": np.array([]), "p90": np.array([])},
            "final_return_pct": {"p10": 0.0, "p50": 0.0, "p90": 0.0},
            "prob_of_loss": 0.0,
            "n_simulations": 0,
            "horizon_days": max(horizon, 0),
        }

    rng = np.random.default_rng(random_seed)
    # 표본이 block_size보다 짧으면(극단적으로 짧은 백테스트) 표본 길이 자체를 블록 길이로 줄인다 —
    # 그래도 최소 1은 되어야 블록을 하나 이상 뽑을 수 있다.
    effective_block = max(1, min(block_size, n_obs))
    n_blocks_needed = math.ceil(horizon / effective_block)
    max_start = n_obs - effective_block  # 블록이 표본 끝을 넘어가지 않는 가장 늦은 시작 인덱스

    paths = np.empty((n_simulations, horizon), dtype=float)
    for sim in range(n_simulations):
        block_starts = rng.integers(0, max_start + 1, size=n_blocks_needed)
        sim_returns = np.concatenate([returns_arr[s : s + effective_block] for s in block_starts])[:horizon]
        paths[sim] = np.cumprod(1.0 + sim_returns)

    percentile_bands = {
        "p10": np.percentile(paths, 10, axis=0),
        "p50": np.percentile(paths, 50, axis=0),
        "p90": np.percentile(paths, 90, axis=0),
    }
    final_return_pct_values = (paths[:, -1] - 1.0) * 100.0
    final_return_pct = {
        "p10": float(np.percentile(final_return_pct_values, 10)),
        "p50": float(np.percentile(final_return_pct_values, 50)),
        "p90": float(np.percentile(final_return_pct_values, 90)),
    }
    prob_of_loss = float(np.mean(final_return_pct_values < 0.0))

    return {
        "paths": paths,
        "percentile_bands": percentile_bands,
        "final_return_pct": final_return_pct,
        "prob_of_loss": prob_of_loss,
        "n_simulations": n_simulations,
        "horizon_days": horizon,
    }
