"""백테스팅 엔진 (모듈 A): 전략 vs S&P500 매수보유 vs 개별종목 매수보유 비교.

core.strategy_engine 이 만든 포지션(0/1) 시리즈를 받아 자산가치 곡선(equity curve)과
누적수익률/CAGR/MDD/샤프지수/승률/매매횟수를 계산한다.

핵심 함수:
    run_backtest(ticker, indicator_config, start, end) -> BacktestRun
    run_buy_and_hold(ticker, start, end) -> BacktestRun
    compare_with_benchmarks(ticker, indicator_config, start, end, benchmark_ticker="^GSPC") -> dict
    save_backtest_result(strategy_id, ticker, start, end, metrics, extra_metrics=None) -> int (BacktestResult.id)
    diagnose_strategy_health(indicator_config) -> list[str] (진입/청산 조건 자기모순 등 흔한 결함 경고)

거래비용/슬리피지는 고려하지 않는 단순 모델이다 (추후 확장 가능).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from core.market_data import get_price_history
from core.strategy_engine import (
    Trade,
    extract_staged_trades,
    extract_trades,
    generate_positions,
    is_staged_config,
    simulate_staged_positions,
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


def _slice_by_date(df: pd.DataFrame, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if start:
        out = out[out.index >= pd.Timestamp(start)]
    if end:
        out = out[out.index <= pd.Timestamp(end)]
    return out


def compute_equity_curve(df: pd.DataFrame, position: pd.Series, initial_value: float = 100.0) -> pd.Series:
    """포지션 시리즈로부터 자산가치 곡선을 계산한다.

    position은 0/1(일반 전략) 또는 0~1 사이의 비중(1:2:6 단계별 전략)을 모두 지원한다.
    신호가 발생한 다음 거래일부터 실제 체결된다고 가정한다 (lookahead bias 방지).
    """
    daily_return = df["Close"].pct_change().fillna(0.0)
    executed_position = position.shift(1).fillna(0).astype(float)
    strategy_return = daily_return * executed_position
    equity = (1.0 + strategy_return).cumprod() * initial_value
    equity.iloc[0] = initial_value
    return equity


def calculate_metrics(equity_curve: pd.Series, trades: list[Trade], start_date, end_date) -> dict:
    """누적수익률/CAGR/MDD/샤프지수/승률/매매횟수를 계산한다."""
    if equity_curve.empty or len(equity_curve) < 2:
        return {
            "cumulative_return": 0.0,
            "cagr": 0.0,
            "mdd": 0.0,
            "sharpe": 0.0,
            "win_rate": 0.0,
            "trade_count": 0,
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

    running_max = equity_curve.cummax()
    drawdown = (equity_curve / running_max - 1) * 100
    mdd = float(drawdown.min())

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

    return {
        "cumulative_return": round(cumulative_return, 2),
        "cagr": round(cagr, 2),
        "mdd": round(mdd, 2),
        "sharpe": round(sharpe, 2),
        "win_rate": round(win_rate, 2),
        "trade_count": trade_count,
    }


def run_backtest(
    ticker: str,
    indicator_config: str | dict,
    start: str,
    end: str,
    label: str = "전략",
) -> BacktestRun:
    """지표 조합 전략을 특정 종목/기간에 대해 백테스팅한다.

    indicator_config가 1:2:6 식 단계별(staged) 전략 스키마("entry_stages" 포함)이면
    자동으로 core.strategy_engine.simulate_staged_positions 를 사용해 가중치 기반 포지션으로
    백테스팅한다 (별도 함수를 호출할 필요 없이 이 함수 하나로 두 전략 유형을 모두 처리한다).
    """
    staged = is_staged_config(indicator_config)
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

    df = _slice_by_date(raw, start, end)

    if staged:
        position_full, events_full = simulate_staged_positions(raw, indicator_config)
        position = position_full.loc[df.index]
        df_index_set = set(df.index)
        stage_events = [e for e in events_full if e.date in df_index_set]
        trades = extract_staged_trades(df, stage_events)
    else:
        position_full = generate_positions(raw, indicator_config)
        position = position_full.loc[df.index]
        stage_events = []
        trades = extract_trades(df, position, indicator_config)

    equity_curve = compute_equity_curve(df, position)
    metrics = calculate_metrics(equity_curve, trades, df.index[0], df.index[-1])

    return BacktestRun(
        label=label,
        ticker=ticker,
        df=df,
        position=position,
        equity_curve=equity_curve,
        trades=trades,
        metrics=metrics,
        stage_events=stage_events,
    )


def compute_regime_breakdown(run: BacktestRun, benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER) -> dict:
    """백테스트 결과를 국면별(강세장/약세장/중립)로 나눠 각 국면에 해당하는 날들만 모아
    누적수익률/거래일수를 계산한다 (core.market_regime.classify_daily_regime 재사용).

    국면이 바뀌는 날짜를 기준으로 구간을 자르는 게 아니라, 그 국면에 속한 날들의 일간수익률을
    전부 모아 복리로 계산한다(연속 구간일 필요 없음) — "이 전략이 약세장인 날들에는 대체로 어떻게
    움직였는지"를 보여주는 참고 지표다. market_regime을 여기서 모듈 최상단에 import하면
    market_regime.py가 이미 core.backtest_engine을 import하고 있어 순환참조가 나므로 함수 안에서
    지연 import한다.

    Returns:
        {"강세장": {"trading_days": int, "cumulative_return": float|None}, "약세장": {...}, "중립": {...}}
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

    regime = market_regime.classify_daily_regime(bench["Close"]).reindex(run.equity_curve.index).ffill()
    daily_return = run.equity_curve.pct_change().fillna(0.0)

    breakdown: dict = {}
    for label in ("강세장", "약세장", "중립"):
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
    자연어 전략 등록 UI에서 자동으로 호출된다 (app/pages/1_백테스팅.py 참고).

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


def run_buy_and_hold(ticker: str, start: str, end: str, label: Optional[str] = None) -> BacktestRun:
    """매수 후 보유(첫날 매수, 끝까지 보유) 벤치마크를 계산한다."""
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
    equity_curve = compute_equity_curve(df, position)
    # 매수 후 보유는 첫날부터 보유하는 것이므로 shift로 인해 비는 첫날 수익을 보정한다.
    equity_curve.iloc[0] = 100.0
    trades = [
        Trade(
            entry_date=df.index[0],
            exit_date=df.index[-1],
            entry_price=float(df["Close"].iloc[0]),
            exit_price=float(df["Close"].iloc[-1]),
            return_pct=(float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1) * 100,
        )
    ]
    metrics = calculate_metrics(equity_curve, trades, df.index[0], df.index[-1])

    return BacktestRun(
        label=label,
        ticker=ticker,
        df=df,
        position=position,
        equity_curve=equity_curve,
        trades=trades,
        metrics=metrics,
    )


def compare_with_benchmarks(
    ticker: str,
    indicator_config: str | dict,
    start: str,
    end: str,
    benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER,
) -> dict[str, BacktestRun]:
    """SPEC 모듈 A의 3-way 비교: 전략 적용 vs S&P500 매수보유 vs 개별종목 매수보유.

    Returns:
        {"strategy": BacktestRun, "buy_and_hold_ticker": BacktestRun, "buy_and_hold_benchmark": BacktestRun}
    """
    return {
        "strategy": run_backtest(ticker, indicator_config, start, end, label=f"{ticker} 전략 적용"),
        "buy_and_hold_ticker": run_buy_and_hold(ticker, start, end, label=f"{ticker} 매수 후 보유"),
        "buy_and_hold_benchmark": run_buy_and_hold(
            benchmark_ticker, start, end, label="S&P500 매수 후 보유"
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
            extra_metrics=json.dumps(extra_metrics) if extra_metrics else None,
        )
        session.add(row)
        session.flush()
        return row.id
