"""코스톨라니 달걀 이론 매매 시나리오 엔진 (2026-07-21, 사용자 요청).

core.kostolany_cycle이 "지금 이 순간"의 국면(A1~B3)만 스냅샷으로 계산하는 것과 달리, 이 모듈은
"과거 내내 이 국면 신호를 따라 매매했다면 어떤 결과가 나왔을까"를 백테스팅한다. 매매 규칙은
core.kostolany_cycle.STYLE_PHASE_STATUS를 그대로 재사용한다:
    매수 관심(buy)/보유·관망(hold) 국면 → 시장에 들어가 있음(포지션 1)
    매도 검토(sell) 국면 → 시장에서 나옴(포지션 0, 현금 보유)
장기/스윙 두 스타일 모두 지원하며(core.kostolany_cycle.STYLE_ORDER), 국면 판정 자체(zone/trend/volume
임계값)는 core.kostolany_cycle.classify_cycle_phase와 완전히 동일한 로직을 룩어헤드 없이(각 시점까지의
데이터만 사용하는 rolling 윈도) 벡터화한 것 — 두 구현이 같은 날에 같은 국면을 내는지는
tests/test_kostolany_scenario_engine.py에서 직접 대조 검증한다.

core.sector_strength.THEME_UNIVERSE의 모든 섹터/테마 각각에 대해 이 시나리오를 돌릴 수 있다
(run_theme_scenarios). 매수 후 보유(buy & hold) 대비 성과 비교는 core.backtest_engine의 기존
지표 계산(calculate_metrics)과 거래 추출(core.strategy_engine.extract_trades)을 그대로 재사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from core.backtest_engine import (
    DEFAULT_BENCHMARK_TICKER,
    calculate_contribution_metrics,
    calculate_metrics,
    compute_equity_curve,
    run_buy_and_hold,
    simulate_contribution_equity,
)
from core.indicators import roc
from core.kostolany_cycle import (
    DEFAULT_LOOKBACK_DAYS,
    STEEP_ROC_PCT,
    STYLE_LABELS,
    STYLE_ORDER,
    STYLE_PHASE_STATUS,
    TREND_ROC_WINDOW,
    VOLUME_HIGH_RATIO,
    VOLUME_LONG_WINDOW,
    VOLUME_SHORT_WINDOW,
    ZONE_HIGH_PCT,
    ZONE_LOW_PCT,
    POSITION_LOOKBACK_TRADING_DAYS,
    _combined_close_volume,
)
from core.market_data import get_price_history
from core.sector_strength import THEME_UNIVERSE
from core.strategy_engine import Trade, extract_trades

DEFAULT_STYLE = "장기"


def _default_start() -> str:
    return (date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()


def compute_position_pct_series(
    close: pd.Series, lookback: int = POSITION_LOOKBACK_TRADING_DAYS
) -> pd.Series:
    """core.kostolany_cycle.compute_position_pct의 rolling(룩어헤드 없는) 버전.

    각 시점 t는 [t-lookback+1, t] 구간의 min/max만 사용 — 미래 데이터를 보지 않는다.
    """
    roll_min = close.rolling(lookback, min_periods=2).min()
    roll_max = close.rolling(lookback, min_periods=2).max()
    denom = (roll_max - roll_min).replace(0, np.nan)
    pct = (close - roll_min) / denom * 100
    return pct.where(denom.notna(), 50.0)


def compute_volume_ratio_series(
    volume: pd.Series, short: int = VOLUME_SHORT_WINDOW, long: int = VOLUME_LONG_WINDOW
) -> pd.Series:
    """core.kostolany_cycle.compute_volume_ratio의 rolling 버전."""
    avg_short = volume.rolling(short, min_periods=short).mean()
    avg_long = volume.rolling(long, min_periods=long).mean()
    return avg_short / avg_long.replace(0, np.nan)


def classify_cycle_phase_series(close: pd.Series, volume: pd.Series) -> pd.Series:
    """core.kostolany_cycle.classify_cycle_phase와 동일한 분기 로직을 날짜별로 벡터화한 버전.

    Returns: close와 같은 인덱스의 문자열 Series(값은 "A1".."B3" 또는 데이터 부족 시 None).
    """
    position_pct = compute_position_pct_series(close)
    roc_pct = roc(close, TREND_ROC_WINDOW)
    volume_ratio = compute_volume_ratio_series(volume)

    trend_up = roc_pct > 0
    is_steep = roc_pct.abs() >= STEEP_ROC_PCT
    volume_high = volume_ratio >= VOLUME_HIGH_RATIO

    low = position_pct <= ZONE_LOW_PCT
    high = position_pct >= ZONE_HIGH_PCT
    mid = ~low & ~high

    phase = pd.Series(np.nan, index=close.index, dtype=object)
    phase[low & trend_up & volume_high.fillna(False)] = "A2"
    phase[low & trend_up & ~volume_high.fillna(False)] = "A1"
    phase[low & ~trend_up & (volume_high.fillna(False) & is_steep)] = "B3"
    phase[low & ~trend_up & ~(volume_high.fillna(False) & is_steep)] = "A1"
    phase[high & trend_up & volume_high.fillna(False)] = "A3"
    phase[high & trend_up & ~volume_high.fillna(False)] = "A2"
    phase[high & ~trend_up & volume_high.fillna(False)] = "B2"
    phase[high & ~trend_up & ~volume_high.fillna(False)] = "B1"
    phase[mid & trend_up] = "A2"
    phase[mid & ~trend_up] = "B2"

    invalid = position_pct.isna() | roc_pct.isna()
    phase[invalid] = None
    return phase


def build_position_from_phases(phase: pd.Series, style: str = DEFAULT_STYLE) -> pd.Series:
    """국면 시리즈를 포지션(0/1)으로 변환한다.

    STYLE_PHASE_STATUS[style]로 각 국면을 buy/hold/sell 중 하나로 묶은 뒤, buy=진입(1),
    sell=청산(0), hold=직전 상태 유지(그대로 들고 있거나, 아직 안 샀으면 관망 계속)로 매핑한다.
    "hold=투자 중"으로 단순화하면(즉 sell만 아니면 전부 1) 장기/스윙 두 스타일이 완전히 같은 포지션을
    내는 문제가 있다 — PHASE_STATUS/SWING_PHASE_STATUS는 A3/B1 이 두 국면만 공통으로 sell이고 나머지
    4국면은 buy<->hold 자리만 서로 뒤바뀌어 있기 때문(core.kostolany_cycle 모듈 docstring 참고).
    hold을 "직전 상태 유지"로 다루면 buy/hold이 갈리는 국면(A1/A2/B2/B3)에서 두 스타일의 진입 타이밍이
    실제로 달라져 스타일 차이가 백테스트 결과에 반영된다. 국면을 아직 판정할 수 없는 구간(None)은
    hold과 동일하게 직전 상태를 유지한다(맨 처음 구간은 미보유로 시작).
    """
    status_map = STYLE_PHASE_STATUS[style]
    status = phase.map(lambda p: status_map.get(p) if p else None)
    signal = status.map({"buy": 1.0, "sell": 0.0})
    return signal.ffill().fillna(0.0)


@dataclass
class KostolanyScenarioRun:
    """단일 종목/테마 x 스타일에 대한 코스톨라니 매매 시나리오 실행 결과.

    세 가지 자산가치 곡선(모두 기준 100)을 같은 기간에 대해 나란히 담는다: equity_curve(코스톨라니
    신호대로 매매), buy_and_hold_equity_curve(그 종목/테마를 그냥 매수 후 보유), benchmark_equity_curve
    (같은 기간 S&P500 매수 후 보유 — 사용자가 "이 결과가 그냥 시장 지수보다 나은지"를 항상 함께
    볼 수 있도록 요청해 추가, 2026-07-21).
    """

    label: str
    style: str
    df: pd.DataFrame
    phase: pd.Series
    position: pd.Series
    equity_curve: pd.Series
    trades: list[Trade] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    buy_and_hold_equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    buy_and_hold_metrics: dict = field(default_factory=dict)
    benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER
    benchmark_equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    benchmark_metrics: dict = field(default_factory=dict)
    contributed_capital: Optional[pd.Series] = None  # 월 적립 옵션 사용 시 그 시점까지 투입된 누적 원금(본전선)


def _empty_scenario_run(label: str, style: str) -> KostolanyScenarioRun:
    empty_idx = pd.DatetimeIndex([])
    empty_metrics = calculate_metrics(pd.Series(dtype=float), [], date.today(), date.today())
    return KostolanyScenarioRun(
        label=label,
        style=style,
        df=pd.DataFrame(),
        phase=pd.Series(dtype=object, index=empty_idx),
        position=pd.Series(dtype=float, index=empty_idx),
        equity_curve=pd.Series(dtype=float, index=empty_idx),
        trades=[],
        metrics=empty_metrics,
        buy_and_hold_equity_curve=pd.Series(dtype=float, index=empty_idx),
        buy_and_hold_metrics=empty_metrics,
        benchmark_equity_curve=pd.Series(dtype=float, index=empty_idx),
        benchmark_metrics=empty_metrics,
    )


def run_kostolany_scenario(
    df: pd.DataFrame,
    label: str,
    style: str = DEFAULT_STYLE,
    start: Optional[str] = None,
    end: Optional[str] = None,
    benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER,
    monthly_contribution: float = 0.0,
) -> KostolanyScenarioRun:
    """Close/Volume이 있는 가격 이력 DataFrame에 코스톨라니 매매 규칙을 적용해 백테스팅한다.

    df는 국면 판정용 warmup(최소 252거래일 이상 권장)을 포함해 넉넉히 받고, 실제 성과 계산은
    [start, end] 구간만 잘라서 한다(다른 백테스트 엔진과 동일하게 lookahead 방지 + warmup 분리).

    monthly_contribution > 0이면 코스톨라니 전략/섹터 매수보유/S&P500 매수보유 세 곡선 모두 매달
    첫 거래일에 동일한 금액을 추가 납입하는 적립식으로 시뮬레이션한다(core.backtest_engine의
    simulate_contribution_equity/calculate_contribution_metrics 재사용 — 전략 스튜디오 '월 적립
    옵션'과 동일한 로직).
    """
    if df is None or df.empty or "Close" not in df.columns or "Volume" not in df.columns:
        return _empty_scenario_run(label, style)

    phase_full = classify_cycle_phase_series(df["Close"], df["Volume"])
    position_full = build_position_from_phases(phase_full, style)

    sliced = df.copy()
    if start:
        sliced = sliced[sliced.index >= pd.Timestamp(start)]
    if end:
        sliced = sliced[sliced.index <= pd.Timestamp(end)]
    if sliced.empty:
        return _empty_scenario_run(label, style)

    phase = phase_full.loc[sliced.index]
    position = position_full.loc[sliced.index]
    trades = extract_trades(sliced, position)

    bh_position = pd.Series(1.0, index=sliced.index)
    bh_trade = Trade(
        entry_date=sliced.index[0],
        exit_date=sliced.index[-1],
        entry_price=float(sliced["Close"].iloc[0]),
        exit_price=float(sliced["Close"].iloc[-1]),
        return_pct=(float(sliced["Close"].iloc[-1]) / float(sliced["Close"].iloc[0]) - 1) * 100,
    )

    bench_start = sliced.index[0].date().isoformat()
    bench_end = sliced.index[-1].date().isoformat()

    if monthly_contribution > 0:
        equity_curve, contributed_capital = simulate_contribution_equity(
            sliced, position, monthly_contribution=monthly_contribution
        )
        metrics = calculate_contribution_metrics(
            equity_curve, contributed_capital, trades, sliced.index[0], sliced.index[-1]
        )

        bh_equity, bh_contributed = simulate_contribution_equity(
            sliced, bh_position, monthly_contribution=monthly_contribution
        )
        buy_and_hold_metrics = calculate_contribution_metrics(
            bh_equity, bh_contributed, [bh_trade], sliced.index[0], sliced.index[-1]
        )

        bench_run = run_buy_and_hold(
            benchmark_ticker, bench_start, bench_end, monthly_contribution=monthly_contribution
        )
    else:
        equity_curve = compute_equity_curve(sliced, position)
        metrics = calculate_metrics(equity_curve, trades, sliced.index[0], sliced.index[-1])
        contributed_capital = None

        bh_equity = compute_equity_curve(sliced, bh_position)
        bh_equity.iloc[0] = 100.0
        buy_and_hold_metrics = calculate_metrics(bh_equity, [bh_trade], sliced.index[0], sliced.index[-1])

        bench_run = run_buy_and_hold(benchmark_ticker, bench_start, bench_end)

    benchmark_equity_curve = bench_run.equity_curve
    benchmark_metrics = bench_run.metrics

    return KostolanyScenarioRun(
        label=label,
        style=style,
        df=sliced,
        phase=phase,
        position=position,
        equity_curve=equity_curve,
        trades=trades,
        metrics=metrics,
        buy_and_hold_equity_curve=bh_equity,
        buy_and_hold_metrics=buy_and_hold_metrics,
        benchmark_ticker=benchmark_ticker,
        benchmark_equity_curve=benchmark_equity_curve,
        benchmark_metrics=benchmark_metrics,
        contributed_capital=contributed_capital,
    )


WARMUP_DAYS = 400  # run_kostolany_scenario 자신의 docstring이 요구하는 "최소 252거래일 이상의
# warmup"(위치 판정 252거래일 + 거래량 60일 평균)을 넉넉히 커버하는 여유(core.backtest_engine.
# run_backtest와 동일한 관례). 분석 구간(start) 이전 이만큼을 추가로 더 받아온 뒤
# run_kostolany_scenario가 [start, end]로 다시 잘라내 실제 표시 구간에서는 제외한다.
# 2026-07-25: run_backtest에 코스톨라니 스키마를 연결해 교차검증하던 중, 이 여유 없이 start(또는
# _default_start())부터 바로 받아오던 기존 코드가 분석 구간 맨 앞 최대 1년 가까이를 아직 덜 채워진
# rolling 윈도(min_periods=2라 데이터가 며칠만 있어도 값은 나오지만 진짜 52주 구간을 다 못 본 상태)로
# 판정해왔던 것을 발견 — 국면 판정이 왜곡되던 버그였다(이 세션에서 새로 만든 코드가 아니라 기존
# 시장 진단 페이지의 "실제로 이 국면 신호대로 매매했다면?" 결과에도 이미 영향을 주고 있었음).


def run_ticker_scenario(
    ticker: str,
    style: str = DEFAULT_STYLE,
    start: Optional[str] = None,
    end: Optional[str] = None,
    monthly_contribution: float = 0.0,
) -> KostolanyScenarioRun:
    """단일 종목(또는 지수) 티커에 코스톨라니 매매 시나리오를 적용한다."""
    analysis_start = start or _default_start()
    fetch_start = (pd.Timestamp(analysis_start) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    df = get_price_history(ticker, start=fetch_start, end=end, interval="1d")
    return run_kostolany_scenario(
        df, label=ticker, style=style, start=analysis_start, end=end, monthly_contribution=monthly_contribution
    )


def run_theme_scenario(
    theme: str,
    proxies: list[str],
    style: str = DEFAULT_STYLE,
    start: Optional[str] = None,
    end: Optional[str] = None,
    monthly_contribution: float = 0.0,
) -> KostolanyScenarioRun:
    """섹터/테마(복수 프록시 ETF 평균) 하나에 코스톨라니 매매 시나리오를 적용한다."""
    analysis_start = start or _default_start()
    fetch_start = (pd.Timestamp(analysis_start) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    close, volume = _combined_close_volume(proxies, fetch_start, end)
    if close is None or volume is None or volume.empty:
        return _empty_scenario_run(theme, style)
    df = pd.DataFrame({"Close": close, "Volume": volume}).dropna()
    return run_kostolany_scenario(
        df, label=theme, style=style, start=analysis_start, end=end, monthly_contribution=monthly_contribution
    )


def compute_theme_scenario_runs(
    style: str = DEFAULT_STYLE,
    theme_universe: Optional[dict[str, list[str]]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    monthly_contribution: float = 0.0,
) -> dict[str, KostolanyScenarioRun]:
    """THEME_UNIVERSE의 모든 섹터/테마에 코스톨라니 매매 시나리오를 돌려 각각의 실행 결과(개별 매매
    내역 포함)를 그대로 보존한다. run_theme_scenarios()가 요약표를 만들 때 쓰는 원본 데이터이자,
    UI에서 특정 섹터를 클릭해 "언제 어디서 샀는지" 드릴다운할 때 필요한 run.trades를 여기서 얻는다.

    Returns: {theme: KostolanyScenarioRun}. 데이터 부족으로 계산 불가한 테마는 제외.
    """
    themes = THEME_UNIVERSE if theme_universe is None else theme_universe
    runs: dict[str, KostolanyScenarioRun] = {}
    for theme, proxies in themes.items():
        run = run_theme_scenario(theme, proxies, style=style, start=start, end=end, monthly_contribution=monthly_contribution)
        if run.df.empty:
            continue
        runs[theme] = run
    return runs


def scenario_runs_to_summary_df(runs: dict[str, KostolanyScenarioRun], style: str = DEFAULT_STYLE) -> pd.DataFrame:
    """compute_theme_scenario_runs() 결과를 한 표로 요약한다 (컬럼 정의는 run_theme_scenarios 참고).

    섹터 자체의 매수보유(bh_*) 뿐 아니라 같은 기간 S&P500 매수보유(bench_*)도 항상 함께 담는다 —
    "이 결과가 그냥 시장 지수보다 나은지"를 표만 봐도 바로 비교할 수 있도록(2026-07-21 사용자 요청).
    """
    columns = [
        "theme", "style", "cumulative_return", "cagr", "mdd", "sharpe", "win_rate", "trade_count",
        "bh_cumulative_return", "bh_cagr", "bh_mdd", "excess_return",
        "bench_cumulative_return", "bench_cagr", "bench_mdd", "excess_return_vs_benchmark",
    ]
    rows = []
    for theme, run in runs.items():
        m, bh, bench = run.metrics, run.buy_and_hold_metrics, run.benchmark_metrics
        rows.append(
            {
                "theme": theme,
                "style": style,
                "cumulative_return": m["cumulative_return"],
                "cagr": m["cagr"],
                "mdd": m["mdd"],
                "sharpe": m["sharpe"],
                "win_rate": m["win_rate"],
                "trade_count": m["trade_count"],
                "bh_cumulative_return": bh["cumulative_return"],
                "bh_cagr": bh["cagr"],
                "bh_mdd": bh["mdd"],
                "excess_return": round(m["cumulative_return"] - bh["cumulative_return"], 2),
                "bench_cumulative_return": bench["cumulative_return"],
                "bench_cagr": bench["cagr"],
                "bench_mdd": bench["mdd"],
                "excess_return_vs_benchmark": round(m["cumulative_return"] - bench["cumulative_return"], 2),
            }
        )
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows)[columns].sort_values("excess_return", ascending=False).reset_index(drop=True)


def run_theme_scenarios(
    style: str = DEFAULT_STYLE,
    theme_universe: Optional[dict[str, list[str]]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    monthly_contribution: float = 0.0,
) -> pd.DataFrame:
    """THEME_UNIVERSE의 모든 섹터/테마에 코스톨라니 매매 시나리오를 돌려 성과를 한 표로 모은다.

    Returns:
        columns: theme, style, cumulative_return, cagr, mdd, sharpe, win_rate, trade_count,
        bh_cumulative_return, bh_cagr, bh_mdd, excess_return(코스톨라니 전략 누적수익률 - 그 섹터
        매수보유 누적수익률, %p), bench_cumulative_return, bench_cagr, bench_mdd(같은 기간 S&P500
        매수보유), excess_return_vs_benchmark(코스톨라니 전략 누적수익률 - S&P500 매수보유 누적수익률,
        %p) — excess_return(섹터 자체 매수보유 대비) 내림차순 정렬.

    monthly_contribution > 0이면 세 곡선 모두 적립식(DCA)으로 계산한다 — cumulative_return은 원금
    대비 손익률, cagr은 XIRR로 재정의된다(calculate_contribution_metrics 참고).
    """
    runs = compute_theme_scenario_runs(
        style=style, theme_universe=theme_universe, start=start, end=end, monthly_contribution=monthly_contribution
    )
    return scenario_runs_to_summary_df(runs, style=style)
