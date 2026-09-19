"""챔피언 전략 엔진 — 리서치 프로그램 종합 결론을 "오늘 기준" 라이브 신호로 계산.

`analysis/2026-09-05_research_program_synthesis/`가 49개 작업·26개 이상의 리포트(순열검정/블록
부트스트랩/국면분해/워크포워드 등으로 감사됨)를 종합해 도출한 코어+새틀라이트 자산배분 결론을,
그동안 정적 HTML 리포트 안에만 머물러 있던 것에서 꺼내 실제 시장 데이터에 적용한 라이브 추천으로
계산한다.

이 모듈은 새 전략을 발명하지 않는다 — report_data.json의 final_config/confidence_table을 그대로
따르고, 확신도가 낮은(weak/reversed) 구성요소도 숨기지 않는다:
  - 코어(robust~weak): 17자산(11개 GICS 섹터 ETF + 채권2 + 금 + 국제주식 + 하이일드 + 원자재)
    유니버스에서 12개월 트레일링 모멘텀 상위 4개(절대모멘텀>0 필터 선행) 동일비중, SPY 200일선
    하회 시 코어 비중 50% 축소(이 시장필터 자체는 확신도 "weak" — 방향은 살아있으나 통계적으로
    약함, report_data.json 참고).
  - 새틀라이트(weak~moderate): 코어의 15%를 돈치안 20일 브레이크아웃 추세추종 종목(현재 S&P500
    유니버스에서 스캔)으로 구성.
  - 옵션 칼라 헤지는 확신도가 가장 낮고("조건부 고려") 라이브 옵션 가격 데이터 인프라가 없어
    1차 범위에서 제외(app/pages 쪽 안내 문구로 명시).

베타헤지/개별주 전면 확장/텐베거 스크리닝 등 이 리서치 프로그램에서 이미 기각(reversed/unsupported)된
아이디어는 이 엔진이 추천하지 않는다 — `load_rejected_ideas()`로 그 기각 근거를 그대로 노출한다.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from core import fred_data
from core.backtest_engine import _first_trading_day_of_month_mask, calculate_metrics
from core.db import get_session
from core.indicators import sma
from core.market_data import get_multiple_price_history, get_price_history
from core.models import ChampionLedgerEntry, CorrelationSnapshot
from core.portfolio import compute_correlation_matrix, compute_daily_returns
from core.screener import get_universe
from core.strategy_tuning import sample_universe, train_test_split_dates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_SYNTHESIS_JSON = (
    PROJECT_ROOT / "analysis" / "2026-09-05_research_program_synthesis" / "report_data.json"
)

# final_config.core (report_data.json) 그대로 — GICS 11개 섹터 ETF + 채권2 + 금 + 국제주식 + 하이일드 + 원자재
CORE_UNIVERSE = [
    "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU",
    "TLT", "IEF", "GLD", "EFA", "HYG", "DBC",
]
CORE_MOMENTUM_LOOKBACK_DAYS = 252  # 약 12개월(거래일 기준)
CORE_TOP_N = 4
CORE_WEIGHT = 0.85
MARKET_FILTER_TICKER = "SPY"
MARKET_FILTER_SMA_WINDOW = 200
MARKET_FILTER_EXPOSURE_CUT = 0.5  # 200일선 하회 시 코어 비중에 곱하는 배수

# 2026-09-19 추가: 새틀라이트(SATELLITE_SIZING_METHODS)에는 이미 있던 "inverse_vol" 옵션을
# 코어에도 동일한 원칙으로 제공한다 — 새 방법론 발명 없이 core.position_sizing의 기존 함수를
# top4 종목에 그대로 적용. 새틀라이트와 마찬가지로 미검증 opt-in이며 기본값("equal")은 기존
# 동작을 그대로 유지한다.
CORE_SIZING_METHODS = ("equal", "inverse_vol")
CORE_SIZING_MAX_WEIGHT = 0.50  # top4 중 한 종목이 코어 슬리브 내에서 가질 수 있는 최대 비중
CORE_SIZING_VOL_LOOKBACK_DAYS = 20  # SATELLITE_SIZING_VOL_LOOKBACK_DAYS와 동일 관례

SATELLITE_WEIGHT = 0.15
SATELLITE_DONCHIAN_WINDOW = 20
SATELLITE_MOMENTUM_LOOKBACK_DAYS = 63  # 약 3개월 — 브레이크아웃 후보 간 순위 매길 때만 사용
SATELLITE_TOP_N = 5


def _fetch_history_tail_length(ticker: str, lookback_days: int, buffer_days: int = 40) -> Optional[pd.DataFrame]:
    """모멘텀/이평 계산에 필요한 만큼 과거 가격을 받아온다 (휴장일 감안해 여유(buffer_days)를 더 둠).

    데이터를 못 받아오거나(빈 값) 요청한 lookback_days보다 짧으면 None을 반환한다 — 계산은
    호출부가 아예 건너뛰도록(부분 데이터로 왜곡된 모멘텀을 계산하지 않도록).
    """
    calendar_days_back = int((lookback_days + buffer_days) * 365.25 / 252) + 10
    start = (pd.Timestamp.today().normalize() - pd.Timedelta(calendar_days_back, unit="D")).strftime("%Y-%m-%d")
    try:
        df = get_price_history(ticker, start=start, use_cache=True)
    except Exception:
        return None
    if df is None or df.empty or len(df) < lookback_days + 1:
        return None
    return df


def compute_core_recommendation(sizing_method: str = "equal") -> dict:
    """코어 17자산 유니버스의 오늘 기준 모멘텀 랭킹 + 시장필터 상태를 계산한다.

    sizing_method(2026-09-19 추가): "equal"(기본, 기존 동작 그대로 top4 균등가중) 또는
    "inverse_vol"(compute_satellite_recommendation과 동일 원칙 — top4 종목의 최근
    CORE_SIZING_VOL_LOOKBACK_DAYS일 변동성 역가중, CORE_SIZING_MAX_WEIGHT로 상한). 새틀라이트와
    마찬가지로 "어떤 종목을 고를지"가 아니라 "고른 종목 안에서 비중을 어떻게 나눌지"만 바꾸는
    미검증 opt-in 옵션 — 기본값이 아니다.

    Returns:
        as_of, ranked(전체 17종목 momentum_pct/passes_absolute_momentum/in_top4 DataFrame),
        top4(list[str]), above_200dma, exposure_multiplier, per_ticker_weight(하위호환용, 균등가중 값),
        per_ticker_weights(dict[str,float], 실제 배분), cash_weight_from_filter
    """
    if sizing_method not in CORE_SIZING_METHODS:
        raise ValueError(f"알 수 없는 sizing_method: {sizing_method}")
    rows = []
    histories: dict[str, pd.DataFrame] = {}
    for ticker in CORE_UNIVERSE:
        df = _fetch_history_tail_length(ticker, CORE_MOMENTUM_LOOKBACK_DAYS)
        if df is None:
            rows.append({"ticker": ticker, "momentum_pct": None, "last_close": None})
            continue
        histories[ticker] = df
        close = df["Close"]
        momentum_pct = float(close.iloc[-1] / close.iloc[-1 - CORE_MOMENTUM_LOOKBACK_DAYS] - 1) * 100
        rows.append({"ticker": ticker, "momentum_pct": round(momentum_pct, 2), "last_close": float(close.iloc[-1])})

    ranked = pd.DataFrame(rows)
    ranked["passes_absolute_momentum"] = ranked["momentum_pct"].apply(lambda v: pd.notna(v) and v > 0)
    ranked = ranked.sort_values("momentum_pct", ascending=False, na_position="last").reset_index(drop=True)

    eligible = ranked[ranked["passes_absolute_momentum"]]
    top4 = eligible.head(CORE_TOP_N)["ticker"].tolist()
    ranked["in_top4"] = ranked["ticker"].isin(top4)

    spy = _fetch_history_tail_length(MARKET_FILTER_TICKER, MARKET_FILTER_SMA_WINDOW)
    above_200dma: Optional[bool] = None
    spy_price: Optional[float] = None
    spy_sma200: Optional[float] = None
    if spy is not None:
        sma200 = sma(spy["Close"], MARKET_FILTER_SMA_WINDOW)
        if pd.notna(sma200.iloc[-1]):
            spy_price = float(spy["Close"].iloc[-1])
            spy_sma200 = float(sma200.iloc[-1])
            above_200dma = spy_price > spy_sma200

    exposure_multiplier = 1.0 if (above_200dma is None or above_200dma) else MARKET_FILTER_EXPOSURE_CUT
    invested_core_weight = CORE_WEIGHT * exposure_multiplier
    per_ticker_weight = invested_core_weight / len(top4) if top4 else 0.0

    per_ticker_weights: dict[str, float] = {t: per_ticker_weight for t in top4}
    if sizing_method == "inverse_vol" and top4:
        vol_weights = _inverse_vol_weights(
            {t: histories[t] for t in top4 if t in histories}, top4, CORE_SIZING_VOL_LOOKBACK_DAYS,
            max_weight=CORE_SIZING_MAX_WEIGHT,
        )
        if vol_weights:
            per_ticker_weights = {t: invested_core_weight * w for t, w in vol_weights.items()}

    return {
        "as_of": date.today().isoformat(),
        "ranked": ranked,
        "top4": top4,
        "above_200dma": above_200dma,
        "spy_price": spy_price,
        "spy_sma200": spy_sma200,
        "exposure_multiplier": exposure_multiplier,
        "sizing_method": sizing_method,
        "per_ticker_weight": per_ticker_weight,  # 하위호환용(균등가중 값) — 실제 배분은 per_ticker_weights 참고
        "per_ticker_weights": per_ticker_weights,
        "cash_weight_from_filter": CORE_WEIGHT - invested_core_weight,
    }


SATELLITE_SIZING_METHODS = ("equal", "inverse_vol")
SATELLITE_SIZING_MAX_WEIGHT = 0.40  # inverse_vol 사이징에서 한 종목이 새틀라이트 슬리브 내 가질 수 있는 최대 비중
SATELLITE_SIZING_VOL_LOOKBACK_DAYS = 20  # position_sizing.realized_annual_volatility_pct 기본값과 동일
# 2026-09-19 추가: "kelly"는 run_satellite_backtest/_pick_satellite_at_date(반기 point-in-time
# 리밸런싱)가 검증한 방법론이 아니라서 위 SATELLITE_SIZING_METHODS(백테스트로 재현 가능한 집합)에는
# 넣지 않는다 — compute_satellite_kelly_exposure()가 "현재 시점" 풀링된 거래 통계로 슬리브 전체
# 익스포저를 한 번 스케일하는 것뿐이라, 리밸런싱일마다 다시 계산하는 point-in-time 백테스트에는
# 아직 못 붙인다(회고적으로 매 리밸런싱일 시점의 풀링 통계를 재계산하면 더 정직하겠지만 계산비용이
# 크다 — 다음 단계로 미룸). compute_satellite_recommendation()의 "지금 기준 라이브 추천"에서만
# 쓸 수 있는 별도 opt-in이라는 걸 명시하려고 별도 튜플로 둔다.
SATELLITE_LIVE_SIZING_METHODS = SATELLITE_SIZING_METHODS + ("kelly",)
SATELLITE_KELLY_LOOKBACK_YEARS = 5
SATELLITE_KELLY_SAMPLE_SIZE = 120  # 500종목 전부를 매번 스캔하면 느려서(수 분) 쓰는 결정적 부분표본 크기
SATELLITE_KELLY_MIN_TRADES = 20  # 이보다 적으면 승률/손익비 추정이 통계적으로 불안정하다고 보고 미적용
SATELLITE_KELLY_SAFETY_FRACTION = 0.5  # 하프켈리 — position_sizing.DEFAULT_KELLY_SAFETY_FRACTION과 동일


def compute_satellite_kelly_exposure(
    lookback_years: int = SATELLITE_KELLY_LOOKBACK_YEARS, sample_size: int = SATELLITE_KELLY_SAMPLE_SIZE
) -> dict:
    """새틀라이트 돈치안 브레이크아웃+트레일링스탑 신호 자체의 과거 승률/손익비로, 새틀라이트
    슬리브 전체 익스포저에 곱할 켈리 기준 배율(0~1)을 구한다.

    종목별로 켈리를 따로 구하지 않는다 — 개별 종목은 최근 lookback_years년간 브레이크아웃이 몇
    번 안 일어나 거래 수가 너무 적다(승률 추정이 불안정). 대신 여러 종목의 거래를 모아(pooled)
    "이 신호가 반복됐을 때의 승률/평균손익"을 하나로 추정한다 — "어떤 종목을 고를지"가 아니라
    "이 신호를 얼마나 믿고 실을지"를 묻는 것이므로 종목별로 나눌 이유가 없다.

    core.strategy_engine.extract_trades + core.position_sizing.{compute_trade_stats,kelly_fraction}를
    그대로 재사용한다(새 백테스트 엔진을 새로 만들지 않음). 표본은 sample_size개로 제한한다
    (500종목 전부를 스캔하면 compute_satellite_recommendation과 같은 이유로 느리다) — get_universe()
    순서대로 앞에서부터 결정적으로 골라 호출마다 같은 종목을 봐서 재현 가능하게 한다.

    Returns:
        {"trade_count", "win_rate", "payoff_ratio", "full_kelly", "recommended_fraction",
         "sampled_tickers", "note"}
        recommended_fraction(0~1)이 새틀라이트 슬리브 익스포저에 곱할 배율 — 1.0이면 기존과 동일,
        0에 가까울수록 "이 신호의 과거 승률/손익비로는 통계적 엣지가 약하다"는 뜻. 거래 표본이
        SATELLITE_KELLY_MIN_TRADES 미만이면 recommended_fraction=1.0(변경 없음)과 함께 note에
        이유를 남긴다 — 데이터가 부족하면 부족하다고 알리지, 억지로 추정치를 만들지 않는다.
    """
    from core.position_sizing import compute_trade_stats, kelly_fraction
    from core.strategy_engine import extract_trades

    universe = get_universe()["Symbol"].tolist()
    sample = [t for t in universe if t not in CORE_UNIVERSE and t != MARKET_FILTER_TICKER][:sample_size]

    fetch_start = (pd.Timestamp.today().normalize() - pd.DateOffset(years=lookback_years)).date().isoformat()
    histories = get_multiple_price_history(sample, start=fetch_start, interval="1d")

    all_trades = []
    sampled_tickers = []
    for t in sample:
        df = histories.get(t)
        if df is None or df.empty or len(df) < SATELLITE_DONCHIAN_WINDOW + 60:
            continue
        position = donchian_trailing_stop_positions(df["Close"])
        trades = extract_trades(df, position)
        if trades:
            all_trades.extend(trades)
            sampled_tickers.append(t)

    stats = compute_trade_stats(all_trades)
    if stats is None or stats.trade_count < SATELLITE_KELLY_MIN_TRADES:
        return {
            "trade_count": stats.trade_count if stats else 0,
            "win_rate": None, "payoff_ratio": None, "full_kelly": None,
            "recommended_fraction": 1.0, "sampled_tickers": sampled_tickers,
            "note": f"거래 표본이 {SATELLITE_KELLY_MIN_TRADES}건 미만이라 켈리 추정을 적용하지 않고 익스포저를 그대로 둠(1.0).",
        }
    kelly = kelly_fraction(
        stats.win_rate, stats.avg_win_pct, stats.avg_loss_pct, safety_fraction=SATELLITE_KELLY_SAFETY_FRACTION
    )
    return {
        "trade_count": stats.trade_count,
        "win_rate": round(stats.win_rate, 4),
        "payoff_ratio": kelly["payoff_ratio"],
        "full_kelly": kelly["full_kelly"],
        "recommended_fraction": min(kelly["recommended_fraction"], 1.0),
        "sampled_tickers": sampled_tickers,
        "note": "",
    }


def compute_satellite_recommendation(
    universe: Optional[list[str]] = None, sizing_method: str = "equal"
) -> dict:
    """S&P500 유니버스를 스캔해 돈치안 20일 브레이크아웃 중인 종목을 찾고, 그중 최근 3개월
    모멘텀 상위 SATELLITE_TOP_N개를 새틀라이트 후보로 선정한다.

    500종목을 순차 조회하므로(기존 core/screener.py::screen()과 동일한 방식) 시간이 걸릴 수 있다 —
    호출부(페이지)가 job_manager로 감싸 백그라운드 실행해야 한다. 개별 종목 조회 실패는
    건너뛴다(전체 스캔이 종목 하나 때문에 멈추지 않도록).

    sizing_method (2026-09-14 추가, 2026-09-19에 "kelly" 추가):
      - "equal"(기본, 기존 동작 그대로): 선정 종목에 새틀라이트 비중을 균등 배분.
      - "inverse_vol": core.position_sizing.portfolio_volatility_target_weights(최근
        SATELLITE_SIZING_VOL_LOOKBACK_DAYS일 변동성의 역수 가중, SATELLITE_SIZING_MAX_WEIGHT로 상한)로
        배분. **주의**: 이 리서치 프로그램은 "어떤 종목을 고를지"에서는 위험조정 랭킹이 원시모멘텀에
        졌다는 걸 확인했지만(confidence_table의 "위험조정 모멘텀 랭킹" reversed 등급 — 종목 선정
        기준 얘기), "선정된 종목 안에서 비중을 어떻게 나눌지"는 이 프로그램이 아직 감사하지 않은
        별개 질문이다 — 그래서 이 옵션은 기본값이 아니라 opt-in이며, UI에서도 "미검증" 라벨을 유지한다.
      - "kelly": compute_satellite_kelly_exposure()로 슬리브 전체 익스포저(SATELLITE_WEIGHT)를
        먼저 스케일한 뒤, 그 안에서는 균등 배분한다(inverse_vol과 동시에 쓰지 않음 — 한 번에 실험
        변수 하나만 바꾸자는 이 프로젝트의 원칙). SATELLITE_SIZING_METHODS가 아니라
        SATELLITE_LIVE_SIZING_METHODS에만 있다 — 아직 반기 point-in-time 백테스트로 재현되지
        않은 라이브 전용 실험(위 compute_satellite_kelly_exposure 문서 참고).
    """
    if sizing_method not in SATELLITE_LIVE_SIZING_METHODS:
        raise ValueError(f"알 수 없는 sizing_method: {sizing_method}")
    if universe is None:
        universe = get_universe()["Symbol"].tolist()

    candidates = []
    breakout_histories: dict[str, pd.DataFrame] = {}
    scanned = 0
    for ticker in universe:
        scanned += 1
        df = _fetch_history_tail_length(ticker, max(SATELLITE_DONCHIAN_WINDOW, SATELLITE_MOMENTUM_LOOKBACK_DAYS))
        if df is None:
            continue
        prior_high = df["High"].shift(1).rolling(SATELLITE_DONCHIAN_WINDOW).max()
        if pd.isna(prior_high.iloc[-1]):
            continue
        last_close = float(df["Close"].iloc[-1])
        breakout = last_close > float(prior_high.iloc[-1])
        if not breakout:
            continue
        momentum_pct = float(last_close / df["Close"].iloc[-1 - SATELLITE_MOMENTUM_LOOKBACK_DAYS] - 1) * 100
        candidates.append({"ticker": ticker, "last_close": last_close, "momentum_3m_pct": round(momentum_pct, 2)})
        breakout_histories[ticker] = df

    candidates_df = pd.DataFrame(candidates)
    if not candidates_df.empty:
        candidates_df = candidates_df.sort_values("momentum_3m_pct", ascending=False).reset_index(drop=True)
    selected = candidates_df.head(SATELLITE_TOP_N)["ticker"].tolist() if not candidates_df.empty else []

    kelly_info: Optional[dict] = None
    effective_satellite_weight = SATELLITE_WEIGHT
    if sizing_method == "kelly" and selected:
        kelly_info = compute_satellite_kelly_exposure()
        effective_satellite_weight = SATELLITE_WEIGHT * kelly_info["recommended_fraction"]

    per_ticker_weight = effective_satellite_weight / len(selected) if selected else 0.0

    per_ticker_weights: dict[str, float] = {t: per_ticker_weight for t in selected}
    if sizing_method == "inverse_vol" and selected:
        vol_weights = _inverse_vol_weights(breakout_histories, selected, SATELLITE_SIZING_VOL_LOOKBACK_DAYS)
        if vol_weights:
            per_ticker_weights = {t: SATELLITE_WEIGHT * w for t, w in vol_weights.items()}

    return {
        "as_of": date.today().isoformat(),
        "scanned_count": scanned,
        "candidates": candidates_df,
        "selected": selected,
        "sizing_method": sizing_method,
        "kelly_info": kelly_info,  # sizing_method=="kelly"일 때만 채워짐(익스포저 배율 근거)
        "per_ticker_weight": per_ticker_weight,  # 하위호환용(균등가중 값) — 실제 배분은 per_ticker_weights 참고
        "per_ticker_weights": per_ticker_weights,
        "unallocated_weight": SATELLITE_WEIGHT - sum(per_ticker_weights.values()) if selected else SATELLITE_WEIGHT,
    }


def _inverse_vol_weights(
    histories: dict[str, pd.DataFrame],
    tickers: list[str],
    lookback_days: int = SATELLITE_SIZING_VOL_LOOKBACK_DAYS,
    max_weight: float = SATELLITE_SIZING_MAX_WEIGHT,
) -> dict[str, float]:
    """core.portfolio.compute_daily_returns + core.position_sizing.portfolio_volatility_target_weights를
    그대로 재사용해 선정 종목들의 최근 변동성 역가중 비중을 계산한다(새 방법론 발명 없음).

    max_weight(2026-09-19 추가, 기본값은 기존 새틀라이트 상한 그대로)는 호출부가 코어(더 적은
    종목수라 상한을 더 넉넉히 줄 수 있음)와 새틀라이트에서 서로 다른 집중도 상한을 쓸 수 있게 한다.

    데이터가 부족해(2종목 미만 등) 계산 불가하면 빈 dict(호출부가 균등가중으로 폴백)."""
    from core.portfolio import compute_daily_returns
    from core.position_sizing import portfolio_volatility_target_weights

    trimmed = {t: histories[t].tail(lookback_days + 1) for t in tickers if t in histories}
    if len(trimmed) < 2:
        return {}
    daily_returns = compute_daily_returns(trimmed)
    return portfolio_volatility_target_weights(daily_returns, max_weight=max_weight)


def _load_research_synthesis() -> dict:
    if not RESEARCH_SYNTHESIS_JSON.exists():
        return {}
    with open(RESEARCH_SYNTHESIS_JSON, encoding="utf-8") as f:
        return json.load(f)


def load_confidence_table() -> list[dict]:
    """final_config를 구성하는 각 결정의 확신도 등급(robust/moderate/weak/reversed)과 근거를
    반환한다 (report_data.json::confidence_table 그대로, 이 엔진이 자체적으로 등급을 매기지 않음)."""
    return _load_research_synthesis().get("confidence_table", [])


def load_rejected_ideas() -> list[dict]:
    """이 리서치 프로그램에서 검토했지만 기각(reversed/unsupported)된 아이디어 목록
    (report_data.json::track_c_table 중 일부가 여기 해당 — 베타헤지, 개별주 전면확장 등).
    이 엔진이 왜 그런 기능을 추천하지 않는지의 근거로 그대로 노출한다."""
    return [
        row for row in _load_research_synthesis().get("track_c_table", [])
        if row.get("grade") in ("reversed", "unsupported")
    ]


def load_research_meta() -> dict:
    return _load_research_synthesis().get("meta", {})


def load_final_config() -> dict:
    """report_data.json::final_config 원문 그대로 반환 (옵션 칼라 헤지 등 이 엔진이 라이브로
    계산하지 않는 부분도 근거 텍스트를 그대로 인용해서 보여주기 위함)."""
    return _load_research_synthesis().get("final_config", {})


# ----------------------------------------------------------------------------
# 과거 백테스트 (2026-09-13 추가)
#
# 위 compute_core_recommendation()/compute_satellite_recommendation()은 "오늘 하루"만 계산하는
# 라이브 신호다 — "이 전략을 과거 몇 년간 실제로 썼다면 어땠을지"는 별도의 시계열 시뮬레이션이
# 필요하다. 이 섹션은 그 시뮬레이션을 새로 발명하지 않고, 이미 검증이 끝난 리서치 코드를 core/로
# 이식한다:
#   - 코어: analysis/2026-08-19_champion_beta_and_satellite_research/champion_strategy.py
#     (PROGRESS.md 작업22/23이 검증한 스펙의 "재사용 가능한 재구현체").
#   - 새틀라이트: analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test/
#     h10_trend_following_satellite.py (final_config.satellite.inclusion이 실제로 채택한
#     "point-in-time 후보 풀에서 돈치안 20일 브레이크아웃이 활성인 종목 중 12개월 모멘텀 상위"
#     선정 로직 — h1의 순수 모멘텀 버전보다 이게 최종 채택된 버전).
#
# 주의: compute_satellite_recommendation()(라이브)은 매번 S&P500 전체(약 500종목)를 스캔하는
# 단순화된 근사치이고, 여기 새틀라이트 백테스트는 리서치가 실제로 검증한 "반기 리밸런싱 +
# point-in-time 40종목 풀" 방법론을 그대로 쓴다 — 두 로직이 완전히 같지는 않다(알려진 차이,
# PROGRESS.md 참고).
# ----------------------------------------------------------------------------

BACKTEST_COST_BPS_PER_SIDE = 5.0  # 왕복 0.1% = 편도 5bp — _compute_portfolio_returns의 기본값(미지정 호출부용)
# 2026-09-19 추가: 코어(17자산, 전부 대형 ETF)와 새틀라이트(개별 S&P500 종목, 시총/유동성이
# 훨씬 다양함)에 같은 5bp를 쓰는 건 새틀라이트 쪽 실전 비용을 과소평가한다 — ETF는 스프레드가
# 매우 좁지만(SPY/XLK 등은 보통 1bp 미만) 개별주는 중소형주가 섞여 스프레드+시장충격이 더 크다.
# run_core_backtest/run_satellite_backtest가 각각 이 상수를 명시적으로 넘긴다(아래 참고) —
# 정교한 유동성 추정(호가창, ADV 대비 거래규모)까지는 안 갔고, 자산군별 보수적인 고정값 두 개로
# 나눈 것뿐이다.
CORE_COST_BPS_PER_SIDE = 3.0
SATELLITE_COST_BPS_PER_SIDE = 8.0
BACKTEST_WARMUP_DAYS = 400
SATELLITE_BACKTEST_POOL_N = 40
SATELLITE_BACKTEST_TOP_K = 3
SATELLITE_BACKTEST_MOMENTUM_WINDOW = 252
SATELLITE_DONCHIAN_STOP_PCT = 0.15
SATELLITE_BACKTEST_WARMUP_DAYS = 730  # 돈치안 신호가 안정되도록 코어보다 여유있게(2년)
SATELLITE_REBAL_MONTHS = (1, 7)  # 1월/7월 첫 거래일 = 반기 리밸런싱


def donchian_trailing_stop_positions(close: pd.Series, entry_window: int = SATELLITE_DONCHIAN_WINDOW, stop_pct: float = SATELLITE_DONCHIAN_STOP_PCT) -> pd.Series:
    """돈치안 채널 상단 돌파로 진입, 고점 대비 stop_pct% 하락 시 청산하는 포지션(0/1) 시계열.

    `analysis/2026-08-16_iren_volatile_momentum_stocks/backtest.py`가 원안이고
    `h10_trend_following_satellite.py`가 그대로 복사해 쓴 함수를 여기 core/로 옮겨 정식 재사용
    가능하게 만든다(더 이상 여러 analysis 스크립트에 복붙하지 않도록)."""
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


def _closes_from_histories(histories: dict[str, pd.DataFrame], tickers: list[str]) -> pd.DataFrame:
    closes = pd.DataFrame({t: histories[t]["Close"] for t in tickers if t in histories and not histories[t].empty})
    return closes.ffill()


def _build_core_weights(
    closes: pd.DataFrame,
    market_close: pd.Series,
    apply_market_filter: bool = True,
    top_n: int = CORE_TOP_N,
    exposure_cut: float = MARKET_FILTER_EXPOSURE_CUT,
    sizing_method: str = "equal",
) -> pd.DataFrame:
    """월별 리밸런싱 목표 비중(리밸런싱일 이후 다음 리밸런싱일까지 ffill)을 계산한다.

    리밸런싱일에는 그 전일 종가 기준으로 신호를 계산해(lookahead 방지) 시장필터도 같은 날 평가한다.

    top_n/exposure_cut을 기본 상수(CORE_TOP_N/MARKET_FILTER_EXPOSURE_CUT)와 다르게 주면(2026-09-13
    추가 — 파라미터 민감도 분석용) 그 값으로 계산한다. 기존 호출부(run_core_backtest 기본 인자)의
    동작은 그대로 유지된다.

    sizing_method(2026-09-19 추가, 기본값 "equal"이면 기존 동작 그대로): "inverse_vol"이면 리밸런싱일마다
    선정된 top_n 종목의 그 시점까지 CORE_SIZING_VOL_LOOKBACK_DAYS일 변동성 역가중으로 배분한다
    (compute_core_recommendation의 라이브 버전과 동일 원칙 — point-in-time으로, signal_date까지의
    데이터만 사용해 lookahead를 피한다). 데이터가 부족하면 그 리밸런싱일만 균등가중으로 폴백한다.
    """
    if sizing_method not in CORE_SIZING_METHODS:
        raise ValueError(f"알 수 없는 sizing_method: {sizing_method}")
    from core.position_sizing import portfolio_volatility_target_weights

    momentum = closes.pct_change(CORE_MOMENTUM_LOOKBACK_DAYS)
    is_rebal = _first_trading_day_of_month_mask(closes.index)
    sma200 = market_close.rolling(MARKET_FILTER_SMA_WINDOW, min_periods=MARKET_FILTER_SMA_WINDOW).mean()

    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_weights = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]
            mom = momentum.loc[signal_date]
            candidates = mom[mom > 0].sort_values(ascending=False)
            picks = candidates.index[:top_n]
            w = pd.Series(0.0, index=closes.columns)
            if len(picks) > 0:
                vol_w: dict[str, float] = {}
                if sizing_method == "inverse_vol":
                    window = closes[picks].loc[:signal_date].tail(CORE_SIZING_VOL_LOOKBACK_DAYS + 1)
                    if len(window) >= CORE_SIZING_VOL_LOOKBACK_DAYS + 1:
                        daily_ret = window.pct_change().dropna()
                        vol_w = portfolio_volatility_target_weights(daily_ret, max_weight=CORE_SIZING_MAX_WEIGHT)
                if vol_w:
                    for t, wt in vol_w.items():
                        w[t] = wt
                else:
                    w[picks] = 1.0 / top_n
            if apply_market_filter and signal_date in sma200.index and not pd.isna(sma200.loc[signal_date]):
                if market_close.loc[signal_date] < sma200.loc[signal_date]:
                    w = w * exposure_cut
            last_weights = w
        weights.iloc[i] = last_weights.values
    return weights


def _compute_portfolio_returns(closes: pd.DataFrame, weights: pd.DataFrame, cost_bps_per_side: float = BACKTEST_COST_BPS_PER_SIDE) -> dict:
    """비중 시계열로부터 (비용반영 순수익률, 회전율, 자산가치곡선)을 계산한다.

    weights.shift(1)로 "비중이 결정된 다음 거래일부터 체결"하는 lookahead 방지 관례를 쓴다.
    """
    daily_ret = closes.pct_change().fillna(0.0)
    executed_weights = weights.shift(1).fillna(0.0)
    port_ret_gross = (daily_ret * executed_weights).sum(axis=1)

    prev_executed = executed_weights.shift(1).fillna(0.0)
    turnover = (executed_weights - prev_executed).abs().sum(axis=1)
    cost = turnover * (cost_bps_per_side / 10000.0)
    port_ret_net = port_ret_gross - cost

    equity_net = (1.0 + port_ret_net).cumprod() * 100.0
    equity_net.iloc[0] = 100.0

    return {"ret_net": port_ret_net, "turnover": turnover, "equity_net": equity_net}


def run_core_backtest(
    start: str,
    end: Optional[str] = None,
    apply_market_filter: bool = True,
    top_n: int = CORE_TOP_N,
    exposure_cut: float = MARKET_FILTER_EXPOSURE_CUT,
    sizing_method: str = "equal",
) -> dict:
    """순수 코어(17자산 로테이션)를 지정 구간에서 실행하고 지표+수익률 시계열을 반환한다.

    top_n/exposure_cut(2026-09-13 추가)은 기본값을 쓰면 기존 동작 그대로이고, 다른 값을 주면
    (`run_core_param_sensitivity`가 하듯) 그 파라미터로 재계산한다.

    sizing_method(2026-09-19 추가, 기본값 "equal"이면 기존 동작 그대로): _build_core_weights에
    그대로 전달 — "inverse_vol"은 미검증 opt-in 옵션(위 _build_core_weights 참고)."""
    tickers = list(CORE_UNIVERSE)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=BACKTEST_WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(tickers + [MARKET_FILTER_TICKER], start=fetch_start, end=end, interval="1d")
    closes_all = _closes_from_histories(histories, tickers + [MARKET_FILTER_TICKER])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    market_close = closes_all[MARKET_FILTER_TICKER]

    weights_full = _build_core_weights(
        closes, market_close, apply_market_filter=apply_market_filter, top_n=top_n, exposure_cut=exposure_cut,
        sizing_method=sizing_method,
    )

    sliced_idx = closes.index[closes.index >= pd.Timestamp(start)]
    if end:
        sliced_idx = sliced_idx[sliced_idx <= pd.Timestamp(end)]
    closes_sliced = closes.loc[sliced_idx]
    weights_sliced = weights_full.loc[sliced_idx]

    result = _compute_portfolio_returns(closes_sliced, weights_sliced, cost_bps_per_side=CORE_COST_BPS_PER_SIDE)
    metrics = calculate_metrics(result["equity_net"], [], sliced_idx[0], sliced_idx[-1])

    return {
        "start": str(sliced_idx[0].date()), "end": str(sliced_idx[-1].date()), "metrics": metrics,
        "ret_net": result["ret_net"], "equity_net": result["equity_net"], "weights": weights_sliced,
    }


def _semiannual_rebal_dates(trading_index: pd.DatetimeIndex, start: str, end: str) -> list[pd.Timestamp]:
    """1월/7월 첫 거래일마다 리밸런싱하는 반기 스케줄 (final_config가 채택한 "정적 반기 리밸런싱")."""
    idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]
    months = pd.Series(idx.month, index=idx)
    is_target_month = months.isin(SATELLITE_REBAL_MONTHS)
    marked = pd.Series(idx.to_period("M"), index=idx)
    is_first_of_month = marked.ne(marked.shift(1))
    return idx[is_target_month & is_first_of_month].tolist()


def _pick_satellite_at_date(
    rebal_date: pd.Timestamp,
    top_k: int = SATELLITE_BACKTEST_TOP_K,
    pool_n: int = SATELLITE_BACKTEST_POOL_N,
    sizing_method: str = "equal",
) -> dict:
    """rebal_date 시점 point-in-time 유니버스에서, 돈치안 브레이크아웃이 활성인 종목 중 12개월
    모멘텀 상위 top_k를 고른다 (h10_trend_following_satellite.py와 동일 로직).

    pool_n(2026-09-13 추가)은 기본값(SATELLITE_BACKTEST_POOL_N)을 쓰면 기존 동작 그대로이고, 다른
    값을 주면 point-in-time 후보 풀 크기 자체를 바꿔 재스캔한다(파라미터 민감도 분석용).

    sizing_method(2026-09-14 추가): "equal"(기본, top_k개 균등가중) 또는 "inverse_vol"(선정 종목의
    직전 변동성 역가중 — compute_satellite_recommendation과 동일한 opt-in 실험적 옵션, 미검증)."""
    as_of_str = rebal_date.date().isoformat()
    pool = sample_universe(n=pool_n, as_of_date=as_of_str, use_point_in_time_market_cap=True, use_cache=True)
    candidates = [t for t in pool["ticker"].tolist() if t not in CORE_UNIVERSE and t != MARKET_FILTER_TICKER]

    fetch_start = (rebal_date - pd.DateOffset(days=SATELLITE_BACKTEST_WARMUP_DAYS)).date().isoformat()
    fetch_end = rebal_date.date().isoformat()
    histories = get_multiple_price_history(candidates, start=fetch_start, end=fetch_end, interval="1d")

    active_scores: dict[str, float] = {}
    for t in candidates:
        df = histories.get(t)
        if df is None or df.empty:
            continue
        close = df["Close"]
        close = close[close.index < rebal_date]  # 전일까지만(당일 미포함, 룩어헤드 방지)
        if len(close) < SATELLITE_DONCHIAN_WINDOW + 60:
            continue
        pos = donchian_trailing_stop_positions(close)
        if pos.iloc[-1] != 1:
            continue  # 활성 추세 신호 없음 -> 후보 제외
        if len(close) >= SATELLITE_BACKTEST_MOMENTUM_WINDOW + 5:
            mom = close.iloc[-1] / close.iloc[-1 - SATELLITE_BACKTEST_MOMENTUM_WINDOW] - 1.0
        else:
            mom = close.iloc[-1] / close.iloc[0] - 1.0
        if pd.notna(mom):
            active_scores[t] = float(mom)

    ranked = sorted(active_scores.items(), key=lambda kv: kv[1], reverse=True)
    picks = [t for t, _ in ranked[:top_k]]

    pick_weights = {t: 1.0 / len(picks) for t in picks} if picks else {}
    if sizing_method == "inverse_vol" and len(picks) >= 2:
        pick_histories = {t: histories[t][histories[t].index < rebal_date] for t in picks if t in histories}
        vol_weights = _inverse_vol_weights(pick_histories, picks, SATELLITE_SIZING_VOL_LOOKBACK_DAYS)
        if vol_weights:
            pick_weights = vol_weights

    return {
        "date": as_of_str, "pool_size": len(candidates), "n_active_trend": len(active_scores),
        "picks": picks, "weights": pick_weights,
    }


def run_satellite_backtest(
    start: str,
    end: str,
    trading_index: pd.DatetimeIndex,
    top_k: int = SATELLITE_BACKTEST_TOP_K,
    pool_n: int = SATELLITE_BACKTEST_POOL_N,
    sizing_method: str = "equal",
) -> dict:
    """반기 리밸런싱 point-in-time 새틀라이트를 지정 구간에서 실행한다 (느림 — 리밸런싱일마다
    point-in-time 유니버스 표본추출+가격조회가 필요해 job_manager로 감싸서 호출해야 함).

    pool_n(2026-09-13 추가)은 기본값을 쓰면 기존 동작 그대로이고, 다른 값을 주면 후보 풀 크기 자체를
    바꿔 재스캔한다(파라미터 민감도 분석용 — 클수록 스캔 시간도 늘어난다).

    sizing_method(2026-09-14 추가): "equal"(기본, 기존 동작과 완전히 동일 — top_k개 균등가중)
    또는 "inverse_vol"(리밸런싱일마다 선정 종목의 직전 변동성 역가중 재계산 — 미검증 opt-in 옵션,
    확신도 등급이 없으므로 채택 여부는 이 백테스트로 직접 비교해서 사람이 판단해야 한다)."""
    rebal_dates = _semiannual_rebal_dates(trading_index, start, end)
    if not rebal_dates:
        raise ValueError("이 구간에는 반기 리밸런싱일(1월/7월 첫 거래일)이 하나도 없습니다 — 기간을 늘려주세요.")

    rebal_log = []
    all_tickers: set[str] = set()
    per_period_weights: list[tuple[pd.Timestamp, dict[str, float]]] = []
    for d in rebal_dates:
        info = _pick_satellite_at_date(d, top_k=top_k, pool_n=pool_n, sizing_method=sizing_method)
        rebal_log.append(info)
        per_period_weights.append((d, info["weights"]))
        all_tickers.update(info["picks"])

    all_tickers = sorted(all_tickers)
    if not all_tickers:
        return {
            "start": start, "end": end, "rebal_log": rebal_log, "tickers_ever_held": [],
            "metrics": calculate_metrics(pd.Series(dtype=float), [], start, end),
            "ret_net": pd.Series(dtype=float), "equity_net": pd.Series(dtype=float),
        }

    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=SATELLITE_BACKTEST_WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(all_tickers, start=fetch_start, end=end, interval="1d")
    closes = _closes_from_histories(histories, all_tickers)

    full_idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]
    closes = closes.reindex(full_idx).ffill()

    weights = pd.DataFrame(0.0, index=full_idx, columns=closes.columns)
    last_w = pd.Series(0.0, index=closes.columns)
    rebal_set = dict(per_period_weights)
    for dt in full_idx:
        if dt in rebal_set:
            w_map = rebal_set[dt]
            w = pd.Series(0.0, index=closes.columns)
            for t, wt in w_map.items():
                if t in w.index:
                    w[t] = wt
            last_w = w
        weights.loc[dt] = last_w.values

    result = _compute_portfolio_returns(closes, weights, cost_bps_per_side=SATELLITE_COST_BPS_PER_SIDE)
    metrics = calculate_metrics(result["equity_net"], [], full_idx[0], full_idx[-1])

    return {
        "start": str(full_idx[0].date()), "end": str(full_idx[-1].date()), "rebal_log": rebal_log,
        "tickers_ever_held": all_tickers, "metrics": metrics,
        "ret_net": result["ret_net"], "equity_net": result["equity_net"],
    }


def _next_semiannual_month_start(dt: pd.Timestamp) -> pd.Timestamp:
    """dt 이후 가장 가까운 반기 리밸런싱 월의 1일(달력상 1일 — 실제 거래일이 아님, 근사치 계산용)."""
    for target_month in SATELLITE_REBAL_MONTHS:
        if target_month > dt.month:
            return pd.Timestamp(year=dt.year, month=target_month, day=1)
    return pd.Timestamp(year=dt.year + 1, month=SATELLITE_REBAL_MONTHS[0], day=1)


def compute_satellite_recommendation_point_in_time(
    as_of_date: Optional[str] = None,
    pool_n: int = SATELLITE_BACKTEST_POOL_N,
    top_k: int = SATELLITE_BACKTEST_TOP_K,
    sizing_method: str = "equal",
) -> dict:
    """새틀라이트의 "라이브" 추천을, 백테스트(run_satellite_backtest/_pick_satellite_at_date)가 실제로
    검증한 방법론 그대로 계산한다 — 반기(1월/7월 첫 거래일) point-in-time 유니버스 표본(기본
    40종목)에서 돈치안 브레이크아웃+트레일링스탑이 활성인 종목 중 12개월 모멘텀 상위(기본 3개)를
    고르는 로직을 새로 만들지 않고 `_pick_satellite_at_date`를 그대로 호출한다.

    compute_satellite_recommendation()(매번 S&P500 전체를 스캔하는 단순화된 근사치 — 3개월 모멘텀
    상위 5개)과 이 함수가 서로 다른 숫자를 보여주던 문제(라이브 추천과 백테스트 성과가 같은 전략을
    측정하지 않는 문제)를 해결하기 위해 2026-09-14 추가.

    as_of_date(기본값: 오늘)를 기준으로 "그 시점 이전 가장 최근 반기 리밸런싱일에 이 방법을
    기계적으로 실행한 뒤 계속 보유했다면, 지금 들고 있을 종목"을 계산한다. as_of_date가 3월이면
    직전 1월 리밸런싱 결과를, 8월이면 직전 7월 리밸런싱 결과를 쓴다.

    pool_n/top_k(2026-09-13 파라미터 민감도 분석과 동일한 의미)와 sizing_method(2026-09-14 추가,
    "equal"/"inverse_vol" — compute_satellite_recommendation과 동일한 opt-in 실험적 옵션)는 모두
    run_satellite_backtest/_pick_satellite_at_date에 그대로 전달된다. 기본값은 곧 백테스트가 실제로
    검증한 값이다.

    point-in-time 유니버스 표본추출 + 가격 조회가 필요해 느리다(compute_satellite_recommendation과
    같은 비용 등급) — 호출부가 job_manager로 감싸 백그라운드 실행해야 한다.

    Returns:
        as_of, rebal_date(사용된 직전 리밸런싱일), trading_days_to_next_rebal(다음 리밸런싱까지
        대략적인 영업일수 — 미래 거래일력을 알 수 없어 주말만 제외한 근사치, 공휴일 미반영),
        pool_size, n_active_trend, selected(list[str], 곧 picks), sizing_method,
        per_ticker_weight(하위호환용 균등가중 값), per_ticker_weights(dict, 포트폴리오 전체 비중
        기준 — compute_satellite_recommendation과 동일한 스케일), picks(DataFrame:
        ticker/price_at_rebal/current_price/return_since_rebal_pct), unallocated_weight
    """
    if sizing_method not in SATELLITE_SIZING_METHODS:
        raise ValueError(f"알 수 없는 sizing_method: {sizing_method}")

    as_of = pd.Timestamp(as_of_date) if as_of_date else pd.Timestamp(date.today())

    # 반기 리밸런싱일을 찾으려면 실제 거래일력이 필요하다(_pick_satellite_at_date는 진짜
    # pd.Timestamp 거래일을 받아야 하므로) — 시장필터 티커(SPY) 가격 이력의 인덱스를 거래일력으로
    # 재사용한다(run_champion_backtest가 core 백테스트 결과 인덱스를 trading_index로 쓰는 것과 같은
    # 관례). BACKTEST_WARMUP_DAYS(약 400일)만큼 여유를 둬 직전 반기 리밸런싱일을 반드시 포함시킨다.
    calendar_start = (as_of - pd.DateOffset(days=BACKTEST_WARMUP_DAYS)).date().isoformat()
    calendar = get_price_history(MARKET_FILTER_TICKER, start=calendar_start, end=as_of.date().isoformat(), use_cache=True)
    if calendar is None or calendar.empty:
        raise ValueError("거래일력을 구성할 가격 데이터를 불러오지 못했습니다.")

    rebal_dates = _semiannual_rebal_dates(calendar.index, calendar_start, as_of.date().isoformat())
    if not rebal_dates:
        raise ValueError(
            "as_of_date 이전에 반기 리밸런싱일(1월/7월 첫 거래일)이 없습니다 — as_of_date를 늦추거나 "
            "데이터 기간을 확인하세요."
        )
    rebal_date = rebal_dates[-1]

    next_rebal_month_start = _next_semiannual_month_start(rebal_date)
    next_rebal_approx = pd.bdate_range(next_rebal_month_start, periods=5)[0]
    trading_days_to_next_rebal = (
        int(len(pd.bdate_range(as_of + pd.Timedelta(1, unit="D"), next_rebal_approx)))
        if next_rebal_approx > as_of else 0
    )

    info = _pick_satellite_at_date(rebal_date, top_k=top_k, pool_n=pool_n, sizing_method=sizing_method)
    picks: list[str] = info["picks"]
    sleeve_weights: dict[str, float] = info["weights"]

    per_ticker_weights = {t: SATELLITE_WEIGHT * w for t, w in sleeve_weights.items()}
    per_ticker_weight = SATELLITE_WEIGHT / len(picks) if picks else 0.0

    picks_rows = []
    if picks:
        histories = get_multiple_price_history(
            picks, start=rebal_date.date().isoformat(), end=as_of.date().isoformat(), interval="1d"
        )
        for t in picks:
            df = histories.get(t)
            if df is None or df.empty:
                picks_rows.append(
                    {"ticker": t, "price_at_rebal": None, "current_price": None, "return_since_rebal_pct": None}
                )
                continue
            price_at_rebal = float(df["Close"].iloc[0])
            current_price = float(df["Close"].iloc[-1])
            ret_pct = (current_price / price_at_rebal - 1.0) * 100 if price_at_rebal else None
            picks_rows.append({
                "ticker": t,
                "price_at_rebal": round(price_at_rebal, 2),
                "current_price": round(current_price, 2),
                "return_since_rebal_pct": round(ret_pct, 2) if ret_pct is not None else None,
            })
    picks_df = pd.DataFrame(picks_rows, columns=["ticker", "price_at_rebal", "current_price", "return_since_rebal_pct"])

    return {
        "as_of": as_of.date().isoformat(),
        "rebal_date": rebal_date.date().isoformat(),
        "trading_days_to_next_rebal": trading_days_to_next_rebal,
        "pool_size": info["pool_size"],
        "n_active_trend": info["n_active_trend"],
        "selected": picks,
        "sizing_method": sizing_method,
        "per_ticker_weight": per_ticker_weight,
        "per_ticker_weights": per_ticker_weights,
        "picks": picks_df,
        "unallocated_weight": SATELLITE_WEIGHT if not picks else 0.0,
    }


def run_champion_backtest(
    start: str, end: str, satellite_weight: float = SATELLITE_WEIGHT, satellite_sizing_method: str = "equal"
) -> dict:
    """코어+새틀라이트 통합 백테스트 — 두 슬리브를 각자 실행한 뒤 (1-sw)*core + sw*satellite로
    선형 블렌드한다 (analysis/2026-08-19.../h1_core_satellite.py::run()과 동일 방식).

    새틀라이트가 한 번도 종목을 고르지 못한 극단적 케이스(예: 기간이 반기 스케줄을 못 채움)에는
    새틀라이트 비중 없이 코어 100%로 대체한다.

    satellite_sizing_method(2026-09-14 추가, 기본값 "equal"이면 기존 동작 그대로): run_satellite_
    backtest에 그대로 전달 — "inverse_vol"은 미검증 opt-in 옵션(위 run_satellite_backtest 참고)."""
    core = run_core_backtest(start, end)
    trading_index = core["ret_net"].index

    satellite = run_satellite_backtest(start, end, trading_index, sizing_method=satellite_sizing_method)
    if satellite["ret_net"].empty:
        blended = core["ret_net"]
        satellite_weight_applied = 0.0
    else:
        core_a, sat_a = core["ret_net"].align(satellite["ret_net"], join="inner")
        blended = (1 - satellite_weight) * core_a + satellite_weight * sat_a
        satellite_weight_applied = satellite_weight

    equity = (1.0 + blended).cumprod() * 100.0
    equity.iloc[0] = 100.0
    metrics = calculate_metrics(equity, [], equity.index[0], equity.index[-1])

    return {
        "start": start, "end": end, "satellite_weight_applied": satellite_weight_applied,
        "metrics": metrics, "equity_net": equity, "ret_net": blended,
        "core": core, "satellite": satellite,
    }


# ----------------------------------------------------------------------------
# 파라미터 민감도/견고성 분석 (2026-09-13 추가)
#
# "알고리즘 매매를 위한 최적 전략을 찾는 슬롯"을, 이 프로젝트가 이미 확립한 관례를 그대로 재사용해
# 만든다 — 새 방법론을 발명하지 않는다:
#   - train/test 분리는 core.strategy_tuning.train_test_split_dates(75/25, 시계열 순서 그대로)를
#     그대로 재사용한다.
#   - "견고함" 판정은 core.backtest_engine.run_sensitivity_sweep과 동일한 휴리스틱(이웃 값 간
#     최대 변화폭이 전체 값 범위의 절반을 넘으면 "특정 값에서만 튀는" 것으로 보고 견고하지 않음으로
#     판정)을 그대로 재사용한다 — 여기서는 train 곡선에 적용한다.
#   - "train에서만 좋고 test에서 갈라지는지"는 core.strategy_tuning.compute_overfitting_curve의
#     정신(rank 기반 train/test 곡선을 나란히 보여주고 사람이 판단)을 계승하되, 여기서는 그리드
#     서치 랭크가 아니라 파라미터 값 자체가 자연스러운 x축이라 "train에서 최적인 값 vs test에서
#     최적인 값이 서로 다른가"로 단순화했다(peaks_agree).
#
# 이 모듈의 다른 함수들과 마찬가지로 **단일 최고 설정을 추천하지 않는다** — train/test 각 곡선과
# 견고성 판정만 반환하고, 채택 여부는 항상 사람(UI 사용자)이 본다. Day3 스크린샷 코멘트("This is for
# evaluating a strategy, Not for data-mining which is useless")와 동일한 원칙.
# ----------------------------------------------------------------------------

# 파라미터별 UI 기본 탐색값/설명 — app 페이지가 selectbox/multiselect 기본값으로 그대로 쓴다.
# "note"는 이 파라미터를 스윕할 때 왜 빠르거나 느린지(재사용 가능한 계산 vs point-in-time 재스캔)를
# 사용자에게 미리 알려주기 위함 — 새틀라이트 파라미터는 값마다 반기 스캔을 다시 돌아야 해 느리다.
CHAMPION_TUNABLE_PARAMS: dict[str, dict] = {
    "satellite_weight": {
        "label": "새틀라이트 비중",
        "default_values": [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30],
        "current": SATELLITE_WEIGHT,
        "note": "코어·새틀라이트 백테스트를 각각 1회만 실행해두고 값마다 재블렌드만 합니다 — 빠름.",
    },
    "core_top_n": {
        "label": "코어 상위 N종목",
        "default_values": [2, 3, 4, 5, 6],
        "current": CORE_TOP_N,
        "note": "코어 백테스트만 값마다 재실행합니다(17자산뿐이라 빠름).",
    },
    "market_filter_exposure_cut": {
        "label": "시장필터 비중 축소 배수(200일선 하회 시)",
        "default_values": [0.0, 0.3, 0.5, 0.7, 1.0],
        "current": MARKET_FILTER_EXPOSURE_CUT,
        "note": "코어 백테스트만 값마다 재실행합니다(빠름). 1.0 = 필터 사실상 무효화.",
    },
    "satellite_top_k": {
        "label": "새틀라이트 선정 종목 수",
        "default_values": [1, 2, 3, 4, 5],
        "current": SATELLITE_BACKTEST_TOP_K,
        "note": "값마다 새틀라이트 반기 point-in-time 스캔을 재실행합니다 — 느림.",
    },
    "satellite_pool_n": {
        "label": "새틀라이트 후보 풀 크기",
        "default_values": [20, 30, 40, 60, 80],
        "current": SATELLITE_BACKTEST_POOL_N,
        "note": "값마다 새틀라이트 반기 point-in-time 스캔을 재실행합니다 — 느림(풀이 클수록 더 느림).",
    },
}


def _robustness_from_points(metrics: list[Optional[float]]) -> dict:
    """core.backtest_engine.run_sensitivity_sweep과 동일한 이웃-점프 휴리스틱을 재사용한다
    (파라미터 값 오름차순으로 이미 정렬된 metrics 리스트를 받는다). None(계산 실패)은 건너뛴다."""
    valid = [m for m in metrics if m is not None]
    if len(valid) < 2:
        return {"is_robust": None, "max_jump": None, "metric_range": None}
    jumps = [abs(valid[i + 1] - valid[i]) for i in range(len(valid) - 1)]
    metric_range = max(valid) - min(valid)
    max_jump = max(jumps)
    is_robust = metric_range == 0 or (max_jump / metric_range) <= 0.5
    return {"is_robust": is_robust, "max_jump": round(max_jump, 4), "metric_range": round(metric_range, 4)}


def _finalize_param_sensitivity(
    param_name: str, metric: str, train_start: str, train_end: str, test_start: str, test_end: str, points: list[dict]
) -> dict:
    """points(파라미터 값 오름차순, {"value","train_metric","test_metric"})로부터 견고성 판정 +
    train/test 최적값 비교를 계산한다. run_core_param_sensitivity/run_satellite_param_sensitivity/
    run_satellite_weight_sensitivity가 공유하는 마무리 단계.

    Returns:
        {
            "param_name", "metric", "train_period": (start, end), "test_period": (start, end),
            "points": [{"value", "train_metric", "test_metric"}, ...]  (값 오름차순),
            "is_train_robust": bool|None (train 곡선이 완만한지 — run_sensitivity_sweep의 is_robust와
                동일 의미. 유효 포인트 2개 미만이면 None),
            "train_max_jump", "train_metric_range",
            "best_train_value": train_metric이 최고인 값(유효 포인트 없으면 None),
            "best_test_value": test_metric이 최고인 값(유효 포인트 없으면 None),
            "peaks_agree": best_train_value == best_test_value (둘 다 있을 때만 bool, 아니면 None) —
                False면 "train에서 최적인 값이 실제로는(test에서) 최적이 아니었다"는 뜻 — 과최적화 의심 신호.
            "n_valid_train", "n_valid_test": 각각 계산에 성공한(None이 아닌) 포인트 개수.
        }
    """
    train_metrics = [p["train_metric"] for p in points]
    test_metrics = [p["test_metric"] for p in points]
    robustness = _robustness_from_points(train_metrics)

    valid_train = [(p["value"], p["train_metric"]) for p in points if p["train_metric"] is not None]
    valid_test = [(p["value"], p["test_metric"]) for p in points if p["test_metric"] is not None]
    best_train_value = max(valid_train, key=lambda vp: vp[1])[0] if valid_train else None
    best_test_value = max(valid_test, key=lambda vp: vp[1])[0] if valid_test else None
    peaks_agree = None if (best_train_value is None or best_test_value is None) else (best_train_value == best_test_value)

    return {
        "param_name": param_name,
        "metric": metric,
        "train_period": (train_start, train_end),
        "test_period": (test_start, test_end),
        "points": points,
        "is_train_robust": robustness["is_robust"],
        "train_max_jump": robustness["max_jump"],
        "train_metric_range": robustness["metric_range"],
        "best_train_value": best_train_value,
        "best_test_value": best_test_value,
        "peaks_agree": peaks_agree,
        "n_valid_train": len(valid_train),
        "n_valid_test": len(valid_test),
    }


_CHAMPION_SENSITIVITY_TRAIN_RATIO = 0.75  # core.strategy_tuning._DEFAULT_TRAIN_RATIO와 동일 값(75/25, SPEC 5절)


def run_core_param_sensitivity(
    param_name: str,
    values: list[float],
    start: str,
    end: str,
    train_ratio: float = _CHAMPION_SENSITIVITY_TRAIN_RATIO,
    metric: str = "sharpe",
) -> dict:
    """코어 전용 파라미터(core_top_n/market_filter_exposure_cut)를 값마다 train/test 구간에서 각각
    재실행한다. 코어는 17자산뿐이라(캐시된 가격 데이터 재사용) 값 개수만큼 반복해도 빠르다."""
    if param_name not in ("core_top_n", "market_filter_exposure_cut"):
        raise ValueError(f"run_core_param_sensitivity가 다루지 않는 파라미터: {param_name}")
    train_start, train_end, test_start, test_end = train_test_split_dates(start, end, train_ratio)

    points = []
    for v in sorted(values):
        kwargs = {"top_n": int(v)} if param_name == "core_top_n" else {"exposure_cut": float(v)}
        train_m = test_m = None
        try:
            train_m = run_core_backtest(train_start, train_end, **kwargs)["metrics"].get(metric)
        except Exception:
            pass
        try:
            test_m = run_core_backtest(test_start, test_end, **kwargs)["metrics"].get(metric)
        except Exception:
            pass
        points.append({"value": v, "train_metric": train_m, "test_metric": test_m})

    return _finalize_param_sensitivity(param_name, metric, train_start, train_end, test_start, test_end, points)


def run_satellite_weight_sensitivity(
    values: list[float],
    start: str,
    end: str,
    train_ratio: float = _CHAMPION_SENSITIVITY_TRAIN_RATIO,
    metric: str = "sharpe",
    satellite_top_k: int = SATELLITE_BACKTEST_TOP_K,
    satellite_pool_n: int = SATELLITE_BACKTEST_POOL_N,
) -> dict:
    """satellite_weight는 코어·새틀라이트 수익률을 블렌드하는 비중일 뿐이라, 두 슬리브의 백테스트를
    (전체 구간 기준) 각각 1회만 실행해두고 값마다 재블렌드만 한다 — 값 개수만큼 새틀라이트
    point-in-time 스캔을 반복하지 않는다(가장 느린 계산을 딱 한 번만 하도록 하는 최적화)."""
    train_start, train_end, test_start, test_end = train_test_split_dates(start, end, train_ratio)

    core = run_core_backtest(start, end)
    trading_index = core["ret_net"].index
    satellite = run_satellite_backtest(start, end, trading_index, top_k=satellite_top_k, pool_n=satellite_pool_n)

    def _metric_for_period(period_start: str, period_end: str, sw: float) -> Optional[float]:
        idx_mask = (core["ret_net"].index >= pd.Timestamp(period_start)) & (core["ret_net"].index <= pd.Timestamp(period_end))
        core_slice = core["ret_net"][idx_mask]
        if core_slice.empty:
            return None
        if satellite["ret_net"].empty:
            blended = core_slice
        else:
            sat_mask = (satellite["ret_net"].index >= pd.Timestamp(period_start)) & (satellite["ret_net"].index <= pd.Timestamp(period_end))
            sat_slice = satellite["ret_net"][sat_mask]
            core_a, sat_a = core_slice.align(sat_slice, join="inner")
            if core_a.empty:
                blended = core_slice
            else:
                blended = (1 - sw) * core_a + sw * sat_a
        if blended.empty:
            return None
        equity = (1.0 + blended).cumprod() * 100.0
        equity.iloc[0] = 100.0
        return calculate_metrics(equity, [], blended.index[0], blended.index[-1]).get(metric)

    points = []
    for v in sorted(values):
        points.append(
            {
                "value": v,
                "train_metric": _metric_for_period(train_start, train_end, v),
                "test_metric": _metric_for_period(test_start, test_end, v),
            }
        )

    return _finalize_param_sensitivity("satellite_weight", metric, train_start, train_end, test_start, test_end, points)


def run_satellite_param_sensitivity(
    param_name: str,
    values: list[float],
    start: str,
    end: str,
    train_ratio: float = _CHAMPION_SENSITIVITY_TRAIN_RATIO,
    metric: str = "sharpe",
) -> dict:
    """새틀라이트 전용 파라미터(satellite_top_k/satellite_pool_n)를 값마다 train/test 구간에서 각각
    재실행한다 — 값마다 반기 point-in-time 스캔을 다시 돌아야 해 가장 느린 스윕이다.

    train 또는 test 구간이 짧아 반기 리밸런싱일(1월/7월 첫 거래일)을 하나도 포함하지 못하면
    run_satellite_backtest가 ValueError를 던진다 — 그 구간의 metric은 None으로 남기고(계산 불가를
    정직하게 표시) 스윕 자체는 계속 진행한다."""
    if param_name not in ("satellite_top_k", "satellite_pool_n"):
        raise ValueError(f"run_satellite_param_sensitivity가 다루지 않는 파라미터: {param_name}")
    train_start, train_end, test_start, test_end = train_test_split_dates(start, end, train_ratio)

    # 코어는 새틀라이트 파라미터와 무관하므로 trading_index 조달용으로 딱 한 번만 실행한다.
    core = run_core_backtest(start, end)
    full_trading_index = core["ret_net"].index

    def _metric_for_period(period_start: str, period_end: str, kwargs: dict) -> Optional[float]:
        try:
            result = run_satellite_backtest(period_start, period_end, full_trading_index, **kwargs)
        except ValueError:
            return None
        if result["ret_net"].empty:
            return None
        return result["metrics"].get(metric)

    points = []
    for v in sorted(values):
        kwargs = {"top_k": int(v)} if param_name == "satellite_top_k" else {"pool_n": int(v)}
        points.append(
            {
                "value": v,
                "train_metric": _metric_for_period(train_start, train_end, kwargs),
                "test_metric": _metric_for_period(test_start, test_end, kwargs),
            }
        )

    return _finalize_param_sensitivity(param_name, metric, train_start, train_end, test_start, test_end, points)


def run_champion_param_sweep(
    param_name: str,
    values: list[float],
    start: str,
    end: str,
    train_ratio: float = _CHAMPION_SENSITIVITY_TRAIN_RATIO,
    metric: str = "sharpe",
) -> dict:
    """CHAMPION_TUNABLE_PARAMS의 파라미터 이름으로 적절한 민감도 함수에 위임하는 단일 진입점
    (app 페이지/job_manager가 파라미터 종류를 몰라도 이거 하나만 부르면 되도록)."""
    if param_name == "satellite_weight":
        return run_satellite_weight_sensitivity(values, start, end, train_ratio=train_ratio, metric=metric)
    if param_name in ("core_top_n", "market_filter_exposure_cut"):
        return run_core_param_sensitivity(param_name, values, start, end, train_ratio=train_ratio, metric=metric)
    if param_name in ("satellite_top_k", "satellite_pool_n"):
        return run_satellite_param_sensitivity(param_name, values, start, end, train_ratio=train_ratio, metric=metric)
    raise ValueError(f"알 수 없는 챔피언 전략 파라미터: {param_name}")


# ----------------------------------------------------------------------------
# 옵션 칼라 헤지 — 라이브 계산 (2026-09-14 추가)
#
# report_data.json::options_overlay가 "조건부 고려"(확신도 weak)로 채택한 합성 Black-Scholes 칼라를
# 지금까지(작업52) 이 엔진은 "라이브 옵션 가격 데이터 인프라가 없다"며 계산 없이 리서치 결론 인용만
# 해왔다. 그러나 이 칼라는 애초에 실제 옵션체인이 아니라 SPY 종가 + VIX(내재변동성 대리치) +
# FRED 무위험금리로 합성 가격을 만드는 방식이라(analysis/2026-08-30_synthetic_options_tail_hedge/
# h_options_hedge.py, analysis/2026-09-05_options_hedge_bootstrap_and_combined_system/) 실시간
# 옵션 시세 없이도 라이브 계산이 가능하다 — 새 방법론을 발명하지 않고 그 스크립트를 그대로 이식한다.
#
# 확신도는 여전히 weak다(부트스트랩 90% CI가 부호조차 확정 못함, 슬리브 단독 승률 55~59%) — 그래서
# 기본 run_champion_backtest()/compute_satellite_recommendation()의 동작에는 섞지 않고, 별도
# 함수로만 노출한다(선택적 비교/참고용, 항상 사람이 채택 여부를 판단 — 이 프로젝트 전체의 관례).
# ----------------------------------------------------------------------------

COLLAR_PUT_MONEYNESS = 1.00  # ATM 풋 매수
COLLAR_CALL_MONEYNESS = 1.05  # 5% OTM 콜 매도
COLLAR_TENOR_DAYS = 21  # 약 1개월(거래일 기준), 매월 첫 거래일 롤(표준 월물 만기 근사)
COLLAR_FALLBACK_VOL = 0.20  # VIX 결측 시 폴백(연 20%, 장기 평균 근사)
COLLAR_DEFAULT_RATE = 0.02  # FEDFUNDS 결측 시 폴백
VIX_TICKER = "^VIX"


def _norm_cdf(x: float) -> float:
    """표준정규 누적분포함수 (scipy 미설치 환경 대응 — math.erf로 정확한 폐형식 계산,
    h_options_hedge.py::_NormCDF와 동일)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes 유러피언 풋 이론가. T<=0이거나 sigma<=0이면 내재가치로 대체."""
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes 유러피언 콜 이론가."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def _fedfunds_rate_asof(as_of: pd.Timestamp) -> float:
    """as_of 시점 최근 FEDFUNDS(실효 연방기금금리, 월간·%)를 소수(연율)로 반환. 실패 시 폴백."""
    try:
        series = fred_data.get_series("FEDFUNDS", use_cache=True)
        if series is None or series.empty:
            return COLLAR_DEFAULT_RATE
        value = series.asof(as_of)
        if pd.isna(value):
            return COLLAR_DEFAULT_RATE
        return float(value) / 100.0
    except Exception:
        return COLLAR_DEFAULT_RATE


def build_collar_overlay_returns(
    trading_index: pd.DatetimeIndex,
    start: str,
    end: str,
    put_moneyness: float = COLLAR_PUT_MONEYNESS,
    call_moneyness: float = COLLAR_CALL_MONEYNESS,
    tenor_days: int = COLLAR_TENOR_DAYS,
) -> dict:
    """월별 롤링 합성 칼라(ATM 풋 매수 + OTM 콜 매도)의 일별 수익률(SPY 100% 노셔널 기준, 새틀라이트
    비중을 곱하기 전 "옵션 자체의" 수익률)을 계산한다 —
    h_options_hedge.py::build_option_overlay_returns(mode="collar")를 그대로 이식.

    Returns: {"overlay_ret": pd.Series(trading_index와 동일 인덱스), "roll_log": [...]}
    """
    warmup_days = 60
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_days)).date().isoformat()
    spy_close = get_price_history("SPY", start=fetch_start, end=end, use_cache=True)["Close"]
    vix_close = get_price_history(VIX_TICKER, start=fetch_start, end=end, use_cache=True)["Close"]
    px = pd.DataFrame({"spy": spy_close}).join(pd.DataFrame({"vix": vix_close}), how="left")
    px["vix"] = px["vix"].ffill()
    px = px.reindex(trading_index).ffill()

    roll_mask = _first_trading_day_of_month_mask(trading_index)
    roll_dates = list(trading_index[roll_mask])
    if len(roll_dates) == 0 or roll_dates[0] != trading_index[0]:
        roll_dates = [trading_index[0]] + roll_dates

    overlay_ret = pd.Series(0.0, index=trading_index)
    roll_log = []
    for rd in roll_dates:
        pos = trading_index.get_loc(rd)
        exp_pos = min(pos + tenor_days, len(trading_index) - 1)
        expiry = trading_index[exp_pos]
        S0 = float(px.loc[rd, "spy"])
        vix0 = px.loc[rd, "vix"]
        sigma = float(vix0) / 100.0 if pd.notna(vix0) else COLLAR_FALLBACK_VOL
        r = _fedfunds_rate_asof(rd)
        T = tenor_days / 252.0
        K_put = S0 * put_moneyness
        K_call = S0 * call_moneyness
        put0 = bs_put_price(S0, K_put, T, r, sigma)
        call0 = bs_call_price(S0, K_call, T, r, sigma)
        S_T = float(px.loc[expiry, "spy"])
        put_payoff = max(K_put - S_T, 0.0)
        call_payoff = max(S_T - K_call, 0.0)

        net_premium_pct_debit = (call0 - put0) / S0  # 콜 매도 수취 - 풋 매수 지불 (양수=순수취)
        net_payoff_pct_credit = (put_payoff - call_payoff) / S0

        overlay_ret.loc[rd] += net_premium_pct_debit
        overlay_ret.loc[expiry] += net_payoff_pct_credit
        roll_log.append(
            {
                "roll_date": str(rd.date()),
                "expiry_date": str(expiry.date()),
                "spy_at_roll": round(S0, 2),
                "spy_at_expiry": round(S_T, 2),
                "vix_at_roll": round(float(vix0), 2) if pd.notna(vix0) else None,
                "implied_vol": round(sigma, 4),
                "risk_free_rate": round(r, 4),
                "put_strike": round(K_put, 2),
                "call_strike": round(K_call, 2),
                "net_premium_pct": round(net_premium_pct_debit, 5),
                "net_payoff_pct": round(net_payoff_pct_credit, 5),
            }
        )
    return {"overlay_ret": overlay_ret, "roll_log": roll_log}


def run_champion_backtest_with_collar(
    start: str,
    end: str,
    satellite_weight: float = SATELLITE_WEIGHT,
    put_moneyness: float = COLLAR_PUT_MONEYNESS,
    call_moneyness: float = COLLAR_CALL_MONEYNESS,
    satellite_sizing_method: str = "equal",
) -> dict:
    """run_champion_backtest() 결과에 새틀라이트 노셔널(satellite_weight)만큼만 방어하는 칼라
    오버레이 비교선을 추가로 계산한다 — 기본 백테스트 동작(다른 키)은 바꾸지 않는다.

    Returns: run_champion_backtest()의 모든 키 + collar_ret_net, collar_equity_net, collar_metrics,
    collar_roll_log.
    """
    champion = run_champion_backtest(start, end, satellite_weight=satellite_weight, satellite_sizing_method=satellite_sizing_method)
    trading_index = champion["ret_net"].index
    overlay = build_collar_overlay_returns(trading_index, start, end, put_moneyness, call_moneyness)
    overlay_scaled = overlay["overlay_ret"].reindex(trading_index).fillna(0.0) * satellite_weight

    collar_ret_net = champion["ret_net"] + overlay_scaled
    collar_equity_net = (1.0 + collar_ret_net).cumprod() * 100.0
    collar_equity_net.iloc[0] = 100.0
    collar_metrics = calculate_metrics(collar_equity_net, [], trading_index[0], trading_index[-1])

    return {
        **champion,
        "collar_ret_net": collar_ret_net,
        "collar_equity_net": collar_equity_net,
        "collar_metrics": collar_metrics,
        "collar_roll_log": overlay["roll_log"],
    }


def compute_live_collar_state(
    satellite_weight: float = SATELLITE_WEIGHT,
    put_moneyness: float = COLLAR_PUT_MONEYNESS,
    call_moneyness: float = COLLAR_CALL_MONEYNESS,
    tenor_days: int = COLLAR_TENOR_DAYS,
) -> Optional[dict]:
    """오늘 기준 "이번 롤 사이클" 칼라의 상태(행사가/만기까지 남은 거래일/사이클 시작 이후
    마크투모델 손익)를 계산한다. SPY/VIX 데이터를 못 받아오면 None(계산 불가를 정직하게 표시).
    """
    lookback_days = int((tenor_days + 40) * 1.6) + 10
    start = (pd.Timestamp.today().normalize() - pd.Timedelta(lookback_days, unit="D")).strftime("%Y-%m-%d")
    spy = get_price_history("SPY", start=start, use_cache=True)
    vix = get_price_history(VIX_TICKER, start=start, use_cache=True)
    if spy is None or spy.empty or vix is None or vix.empty:
        return None

    trading_index = spy.index
    roll_mask = _first_trading_day_of_month_mask(trading_index)
    roll_dates = trading_index[roll_mask]
    if len(roll_dates) == 0:
        return None
    roll_date = roll_dates[-1]  # 가장 최근(이번 달) 첫 거래일 = 현재 진행 중인 롤 사이클의 시작

    vix_aligned = vix["Close"].reindex(trading_index).ffill()
    S0 = float(spy.loc[roll_date, "Close"])
    vix0 = vix_aligned.loc[roll_date]
    sigma0 = float(vix0) / 100.0 if pd.notna(vix0) else COLLAR_FALLBACK_VOL
    r = _fedfunds_rate_asof(roll_date)
    K_put = S0 * put_moneyness
    K_call = S0 * call_moneyness
    put0 = bs_put_price(S0, K_put, tenor_days / 252.0, r, sigma0)
    call0 = bs_call_price(S0, K_call, tenor_days / 252.0, r, sigma0)
    net_premium_pct_at_roll = (call0 - put0) / S0  # 양수 = 롤 시점에 순수취(콜 프리미엄이 더 큼)

    S_now = float(spy["Close"].iloc[-1])
    vix_now = vix_aligned.iloc[-1]
    sigma_now = float(vix_now) / 100.0 if pd.notna(vix_now) else COLLAR_FALLBACK_VOL
    days_elapsed = len(trading_index[trading_index >= roll_date]) - 1
    days_remaining = max(tenor_days - days_elapsed, 0)
    put_now = bs_put_price(S_now, K_put, days_remaining / 252.0, r, sigma_now)
    call_now = bs_call_price(S_now, K_call, days_remaining / 252.0, r, sigma_now)
    net_value_pct_now = (call_now - put_now) / S0
    mark_to_model_pnl_pct = net_value_pct_now - net_premium_pct_at_roll  # 사이클 시작 이후 순가치 변화

    return {
        "roll_date": str(roll_date.date()),
        "days_remaining": days_remaining,
        "spy_at_roll": round(S0, 2),
        "spy_now": round(S_now, 2),
        "put_strike": round(K_put, 2),
        "call_strike": round(K_call, 2),
        "implied_vol_at_roll": round(sigma0, 4),
        "implied_vol_now": round(sigma_now, 4),
        "net_premium_pct_at_roll": round(net_premium_pct_at_roll * 100, 3),
        "mark_to_model_pnl_pct_of_satellite_notional": round(mark_to_model_pnl_pct * satellite_weight * 100, 4),
        "satellite_weight": satellite_weight,
    }


# ----------------------------------------------------------------------------
# 시장 국면 맥락 (2026-09-14 추가, 참고용 — 배분 결정에 반영하지 않음)
#
# confidence_table이 감사한 결과, 국면조건부 동적 스위치(H12/H13)·실시간 VIX 신속신호(H20/H21) 등
# "감지 후 반응하는" 모든 방어 메커니즘은 기댓값 기준으로 정적 배분에 반복적으로 졌다(reversed/weak
# 등급). 그래서 이 함수는 core.market_regime이 매일 밤 이미 계산해둔 국면 스냅샷을 그대로 노출만
# 하고, compute_core_recommendation/compute_satellite_recommendation의 계산에는 전혀 관여하지
# 않는다 — 사용자가 "지금 거시적으로 어떤 국면인지" 맥락을 참고할 수 있게 보여주는 용도로 한정한다.
# ----------------------------------------------------------------------------


def load_market_regime_context() -> Optional[dict]:
    """가장 최근 저장된 시장 국면 스냅샷을 참고 정보로 반환한다 (이 엔진의 배분 결정에는 영향을
    주지 않는다 — 위 설명 참고). 저장된 스냅샷이 없으면 None.

    Returns: core.market_regime.select_regime_for_trading()과 동일 형식
        ({"trading_regime", "is_ambiguous", "total_score", "snapshot"}).
    """
    try:
        from core.market_regime import select_regime_for_trading

        result = select_regime_for_trading()
        return result if result.get("snapshot") is not None else None
    except Exception:
        return None


# ----------------------------------------------------------------------------
# 리밸런싱 diff — 엔진 추천 vs 실제 보유 (2026-09-14 추가)
#
# 지금까지 이 엔진은 "오늘의 추천"만 계산했고, 사용자가 실제로 뭘 들고 있는지(core/portfolio.py,
# app/pages/8_포트폴리오_관리.py — 수동 입력 방식, 증권사 자동연동 없음)와는 전혀 연결되지 않았다.
# 이 함수는 새 신호를 만들지 않는다 — 이미 계산된 core_result/satellite_result와 이미 저장된
# 보유 종목을 그대로 비교해서 "무엇을 얼마나 사고 팔아야 하는지"의 차이표만 만든다.
#
# 총 계좌가치는 "현재 보유 종목 시가총액 합계 + 현금 잔고(core.portfolio.get_cash_balance())"로
# 계산한다(2026-09-14 — 이전에는 현금 잔고를 입력받지 않아 보유 종목 시가총액 합계로만 근사했다).
# ----------------------------------------------------------------------------

REBALANCE_DIFF_COLUMNS = [
    "ticker", "source", "target_weight_pct", "current_weight_pct", "diff_pct",
    "current_value", "target_value", "delta_value", "action",
]
REBALANCE_HOLD_BAND_PCT = 1.0  # 목표-현재 비중 차이가 이 값(%p) 미만이면 "유지"로 표시(소액 리밸런싱 노이즈 방지)


def compute_rebalance_diff(
    core_result: dict,
    satellite_result: Optional[dict] = None,
    holdings_pnl: Optional[pd.DataFrame] = None,
    cash_balance: Optional[float] = None,
) -> pd.DataFrame:
    """챔피언 엔진의 오늘 추천 배분과 실제 보유(core.portfolio.get_portfolio_pnl())를 비교해
    종목별 목표비중/현재비중/차액(비중%p, 금액)을 계산한다.

    Args:
        core_result: compute_core_recommendation()의 반환값(필수 — 코어 top4는 항상 계산되므로).
        satellite_result: compute_satellite_recommendation()의 반환값. None이면(아직 스캔 안 함)
            새틀라이트 목표비중은 diff에 포함하지 않는다(모르는 것을 안다고 표시하지 않음).
        holdings_pnl: core.portfolio.get_portfolio_pnl()과 동일한 형식(ticker/market_value/
            weight_pct 컬럼). None이면 직접 호출한다(테스트에서 주입 가능하도록 인자화).
        cash_balance: 현금 잔고(달러). None이면 core.portfolio.get_cash_balance()를 직접 호출한다
            (holdings_pnl과 동일한 지연 임포트 패턴 — 테스트에서 주입 가능하도록 인자화, 2026-09-14 추가).

    Returns: REBALANCE_DIFF_COLUMNS 컬럼의 DataFrame, diff_pct 내림차순(가장 많이 사야 할 것부터)
        정렬. 총 계좌가치(보유 종목 시가총액 + 현금 잔고)가 0이면 빈 DataFrame.
    """
    if holdings_pnl is None:
        from core.portfolio import get_portfolio_pnl

        holdings_pnl = get_portfolio_pnl()

    if cash_balance is None:
        from core.portfolio import get_cash_balance

        cash_balance = get_cash_balance()

    holdings_value = float(holdings_pnl["market_value"].sum(skipna=True)) if not holdings_pnl.empty else 0.0
    total_value = holdings_value + cash_balance
    if total_value <= 0:
        return pd.DataFrame(columns=REBALANCE_DIFF_COLUMNS)

    target_weights: dict[str, float] = {}
    sources: dict[str, str] = {}
    for t in core_result.get("top4", []):
        target_weights[t] = target_weights.get(t, 0.0) + core_result.get("per_ticker_weight", 0.0)
        sources[t] = "코어"

    if satellite_result is not None:
        sat_weights = satellite_result.get("per_ticker_weights") or {
            t: satellite_result.get("per_ticker_weight", 0.0) for t in satellite_result.get("selected", [])
        }
        for t, w in sat_weights.items():
            target_weights[t] = target_weights.get(t, 0.0) + w
            sources[t] = f"{sources[t]}+새틀라이트" if t in sources else "새틀라이트"

    # 현재비중은 holdings_pnl에 이미 있는 weight_pct(보유 종목끼리의 비중)를 그대로 쓰지 않고
    # current_value/total_value로 다시 계산한다 — total_value가 이제 현금까지 포함하므로 분모가
    # 다르다(보유 종목만의 합계가 아님).
    current_weights: dict[str, float] = {}
    current_values: dict[str, float] = {}
    for _, row in holdings_pnl.iterrows():
        current_values[row["ticker"]] = float(row["market_value"] or 0.0)
        current_weights[row["ticker"]] = current_values[row["ticker"]] / total_value

    # CASH도 다른 종목과 동일한 target/current 딕셔너리에 넣어 아래 루프에서 diff_pct/action을
    # 특별취급 없이 똑같은 방식으로 계산한다(현금 잔고를 몰랐던 예전과 달리 이제는 실제 값을 아니까).
    cash_weight = core_result.get("cash_weight_from_filter", 0.0)
    if satellite_result is not None:
        cash_weight += satellite_result.get("unallocated_weight", 0.0)
    if cash_weight > 1e-9 or cash_balance > 1e-9:
        target_weights["CASH"] = target_weights.get("CASH", 0.0) + cash_weight
        sources["CASH"] = "현금(시장필터 축소분" + ("/새틀라이트 미배정" if satellite_result is not None else "") + ")"
        current_values["CASH"] = cash_balance
        current_weights["CASH"] = cash_balance / total_value

    rows = []
    for t in sorted(set(target_weights) | set(current_weights)):
        target_w = target_weights.get(t, 0.0)
        current_w = current_weights.get(t, 0.0)
        current_v = current_values.get(t, 0.0)
        target_v = target_w * total_value
        delta_v = target_v - current_v
        diff_pct = (target_w - current_w) * 100
        if abs(diff_pct) < REBALANCE_HOLD_BAND_PCT:
            action = "유지"
        elif delta_v > 0:
            action = "매수"
        else:
            action = "매도"
        rows.append(
            {
                "ticker": t,
                "source": sources.get(t, "보유중(추천 목록 밖)"),
                "target_weight_pct": round(target_w * 100, 2),
                "current_weight_pct": round(current_w * 100, 2),
                "diff_pct": round(diff_pct, 2),
                "current_value": round(current_v, 2),
                "target_value": round(target_v, 2),
                "delta_value": round(delta_v, 2),
                "action": action,
            }
        )

    df = pd.DataFrame(rows, columns=REBALANCE_DIFF_COLUMNS)
    return df.sort_values("diff_pct", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------------
# 신호 변경 텔레그램 알림 (2026-09-14 추가)
#
# 지금까지는 사용자가 직접 페이지를 열어야만 코어 top4/시장필터/새틀라이트 종목이 바뀌었는지 알 수
# 있었다. 이 함수는 새 판단을 만들지 않는다 — compute_core_recommendation/compute_satellite_
# recommendation이 이미 계산한 오늘의 상태를, 어제 저장해둔 상태와 비교만 해서 달라졌을 때만
# core.telegram_notify로 알린다. scheduler/run_scheduler.py가 매일 밤 호출한다.
# ----------------------------------------------------------------------------

SIGNAL_STATE_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "champion_signal_state.json"


def _load_last_signal_state() -> Optional[dict]:
    if not SIGNAL_STATE_CACHE_PATH.exists():
        return None
    try:
        with open(SIGNAL_STATE_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_signal_state(state: dict) -> None:
    SIGNAL_STATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SIGNAL_STATE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_and_notify_signal_changes(include_satellite: bool = True, notify_fn=None) -> dict:
    """코어 top4/시장필터 상태(+선택적으로 새틀라이트 보유종목)가 마지막으로 저장된 상태와
    다르면 텔레그램으로 알린다.

    Args:
        include_satellite: True면 compute_satellite_recommendation()도 실행해 비교한다
            (500종목 순차 스캔이라 느림 — 매일 밤 배치로 실행하는 걸 전제로 한다. 빠른 확인만
            필요하면 False로 코어만 비교).
        notify_fn: 텔레그램 전송 함수(테스트 주입용). None이면 core.telegram_notify.send_message.

    Returns: {"changed": bool, "message": str|None, "state": 이번에 계산해 저장한 새 상태}
    """
    if notify_fn is None:
        from core.telegram_notify import send_message as notify_fn

    core_result = compute_core_recommendation()
    new_state = {
        "as_of": core_result["as_of"],
        "core_top4": sorted(core_result["top4"]),
        "above_200dma": core_result["above_200dma"],
    }
    if include_satellite:
        satellite_result = compute_satellite_recommendation()
        new_state["satellite_selected"] = sorted(satellite_result["selected"])

    old_state = _load_last_signal_state()
    core_changed = old_state is None or (
        old_state.get("core_top4") != new_state["core_top4"] or old_state.get("above_200dma") != new_state["above_200dma"]
    )
    satellite_changed = (
        include_satellite and old_state is not None and old_state.get("satellite_selected") != new_state.get("satellite_selected")
    )
    changed = core_changed or satellite_changed or old_state is None

    message = None
    if changed:
        lines = [f"🏆 챔피언 전략 신호 변경 ({new_state['as_of']})"]
        if old_state is None:
            lines.append(f"최초 신호 기록: 코어 top4={new_state['core_top4']}")
            if include_satellite:
                lines.append(f"새틀라이트={new_state.get('satellite_selected')}")
        else:
            if old_state.get("core_top4") != new_state["core_top4"]:
                lines.append(f"코어 top4: {old_state.get('core_top4')} → {new_state['core_top4']}")
            if old_state.get("above_200dma") != new_state["above_200dma"]:
                lines.append(f"시장필터: {'200일선 위' if new_state['above_200dma'] else '200일선 아래'}로 변경")
            if satellite_changed:
                lines.append(f"새틀라이트: {old_state.get('satellite_selected')} → {new_state.get('satellite_selected')}")
        message = "\n".join(lines)
        notify_fn(message)

    _save_signal_state(new_state)
    return {"changed": changed, "message": message, "state": new_state}


# ----------------------------------------------------------------------------
# 리밸런싱 예정일 사전 알림 (2026-09-14 추가)
#
# check_and_notify_signal_changes()는 리밸런싱이 "이미 일어난 뒤"(전날 신호와 비교)에만 알린다 —
# 사용자가 실제로 다음날 아침 주문을 넣으려면 "내일이 리밸런싱일"이라는 사전 예고가 따로 필요하다.
# 이 함수는 새 배분 로직을 만들지 않는다 — 코어는 _build_core_weights가 쓰는
# core.backtest_engine._first_trading_day_of_month_mask("매월 첫 거래일")와, 새틀라이트는
# _semiannual_rebal_dates/SATELLITE_REBAL_MONTHS("1월/7월 첫 거래일")와 동일한 규칙을 그대로
# 따르되, "내일(들)"은 아직 실현되지 않은 미래라 실제 거래소 캘린더(휴장일 포함)를 알 수 없다는
# 근본적 제약이 있다 — get_price_history 등은 과거 거래일만 반환하므로 "내일이 거래일인지"조차
# 데이터로 확인할 수 없다.
#
# 그래서 아래 _is_calendar_first_trading_day_of_month()는 **달력 요일 기준 근사치**를 쓴다:
# "그 날짜 이전의 가장 가까운 평일(주말이 아닌 날)이 다른 달에 속하면 이 달의 첫 거래일로 본다."
# 미국 거래소 휴장일(신정/추수감사절/성탄절 등, 주말이 아닌 날)이 달 첫 며칠에 끼면 최대 며칠 오차가
# 날 수 있다 — 예: 어느 해 1월 1일이 평일이면 실제 첫 거래일은 1월 2일이지만 이 함수는 1월 1일을
# 오판할 수 있다. 이 오차는 의도적으로 감수한다(휴장일 캘린더 라이브러리를 새로 도입하는 대신, 이미
# 이 코드베이스에 있는 "달력 기준" 관례를 재사용 — 다른 core 모듈에서 별도 거래캘린더 유틸을 찾지
# 못했다). 알림은 "리마인더"일 뿐 실제 리밸런싱 계산(compute_core_recommendation 등)의 정확한 날짜
# 판정에는 관여하지 않으므로, 하루 이틀의 오차가 있어도 사용자가 달력을 다시 확인하는 정도의
# 영향으로 그친다.
# ----------------------------------------------------------------------------

REBALANCE_REMINDER_STATE_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "champion_rebalance_reminder_state.json"


def _is_calendar_first_trading_day_of_month(d: date) -> bool:
    """d가 그 달의 첫 거래일인지 달력 요일만으로 근사 판정한다 (주말 제외, 미국 거래소 휴장일은
    미반영 — 위 섹션 설명의 알려진 오차 참고)."""
    if d.weekday() >= 5:  # 토(5)/일(6)이면 애초에 거래일이 아님
        return False
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev.month != d.month


def _is_core_rebalance_date(d: date) -> bool:
    """코어(17자산) 리밸런싱일 여부 — 매월 첫 거래일, 달력 근사치."""
    return _is_calendar_first_trading_day_of_month(d)


def _is_satellite_rebalance_date(d: date) -> bool:
    """새틀라이트 리밸런싱일 여부 — 1월/7월 첫 거래일(SATELLITE_REBAL_MONTHS), 달력 근사치."""
    return d.month in SATELLITE_REBAL_MONTHS and _is_calendar_first_trading_day_of_month(d)


def _upcoming_weekdays(start: date, n: int) -> list[date]:
    """start(포함)부터 주말을 건너뛰며 평일 n개를 모아 반환한다 — "다음 n거래일"의 달력 기준
    근사치(휴장일 미반영, 위 섹션 설명 참고)."""
    days: list[date] = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _load_last_reminder_state() -> Optional[dict]:
    if not REBALANCE_REMINDER_STATE_CACHE_PATH.exists():
        return None
    try:
        with open(REBALANCE_REMINDER_STATE_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_reminder_state(state: dict) -> None:
    REBALANCE_REMINDER_STATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REBALANCE_REMINDER_STATE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_and_notify_upcoming_rebalance(days_before: int = 1, notify_fn=None) -> dict:
    """향후 days_before 거래일(달력 근사치, 위 섹션 설명 참고) 이내에 코어/새틀라이트 리밸런싱일이
    있으면 텔레그램으로 미리 알린다. check_and_notify_signal_changes()(사후 알림)와 짝을 이루는
    사전 알림.

    Args:
        days_before: 오늘로부터 며칠(거래일 근사치) 이내를 "곧 다가올 리밸런싱"으로 볼지. 기본 1 =
            "내일"만 확인.
        notify_fn: 텔레그램 전송 함수(테스트 주입용). None이면 core.telegram_notify.send_message.

    Returns:
        {"as_of", "core_rebalance_date", "satellite_rebalance_date" (있으면 ISO 날짜 문자열,
         없으면 None), "notified": bool, "message": str|None}

    같은 리밸런싱 날짜 조합에 대해서는 한 번만 알린다(data/cache/champion_rebalance_reminder_state.json에
    직전에 알린 날짜 조합을 저장해두고 비교 — days_before가 1보다 커서 같은 미래 날짜가 여러 날에
    걸쳐 "곧 다가옴"으로 반복 감지돼도 매일 알림이 가지 않도록 dedupe한다).
    """
    if notify_fn is None:
        from core.telegram_notify import send_message as notify_fn

    today = date.today()
    upcoming = _upcoming_weekdays(today + timedelta(days=1), days_before)

    core_date = next((d for d in upcoming if _is_core_rebalance_date(d)), None)
    satellite_date = next((d for d in upcoming if _is_satellite_rebalance_date(d)), None)

    result = {
        "as_of": today.isoformat(),
        "core_rebalance_date": core_date.isoformat() if core_date else None,
        "satellite_rebalance_date": satellite_date.isoformat() if satellite_date else None,
        "notified": False,
        "message": None,
    }
    if core_date is None and satellite_date is None:
        return result

    dedupe_key = f"{result['core_rebalance_date']}|{result['satellite_rebalance_date']}"
    last_state = _load_last_reminder_state()
    already_sent = last_state is not None and last_state.get("dedupe_key") == dedupe_key

    if not already_sent:
        lines = ["⏰ 챔피언 전략 리밸런싱 예정 알림"]
        if core_date and satellite_date:
            if core_date == satellite_date:
                lines.append(f"{core_date.isoformat()}: 코어+새틀라이트 동시 리밸런싱 예정")
            else:
                lines.append(f"코어 리밸런싱 예정일: {core_date.isoformat()}")
                lines.append(f"새틀라이트 리밸런싱 예정일: {satellite_date.isoformat()}")
        elif core_date:
            lines.append(f"코어 리밸런싱 예정일: {core_date.isoformat()}")
        else:
            lines.append(f"새틀라이트 리밸런싱 예정일: {satellite_date.isoformat()}")
        if core_date:
            # 칼라 헤지도 코어와 같은 월별 스케줄(매월 첫 거래일)로 롤되므로, 코어 리밸런싱이
            # 임박했을 때만 같이 확인한다 — 별도 알림/스케줄링을 새로 만들지 않고 이 자리에 붙인다.
            collar_line = _collar_roll_reminder_line()
            if collar_line:
                lines.append(collar_line)
        lines.append("(달력 요일 기준 근사치 — 실제 거래소 휴장일 미반영, 최대 며칠 오차 가능)")
        message = "\n".join(lines)
        notify_fn(message)
        result["notified"] = True
        result["message"] = message

    _save_reminder_state({"as_of": result["as_of"], "dedupe_key": dedupe_key})
    return result


# ----------------------------------------------------------------------------
# 보유종목 상관관계 (2026-09-18 추가)
#
# core.portfolio(내 실제 보유종목, kind="portfolio")와 core.backtest_engine(전략 라이브러리 간,
# kind="strategy")가 이미 같은 CorrelationSnapshot 테이블에 상관관계 이력을 쌓고 있다 — 여기서는
# 새 계산 로직을 만들지 않고 같은 테이블을 kind="champion"으로 공유해, "지금 챔피언 전략이 실제로
# 추천 중인" 코어 top4 + 새틀라이트 조합이 얼마나 분산돼 있는지를 같은 원칙(매번 새 스냅샷, 덮어쓰지
# 않고 이력을 쌓음)으로 확인한다.
# ----------------------------------------------------------------------------

CHAMPION_CORRELATION_LOOKBACK_DAYS = 365


def get_current_holdings() -> Optional[dict]:
    """check_and_notify_signal_changes()가 매일 밤 저장해둔 상태(data/cache/champion_signal_state.json)에서
    "지금 챔피언 전략이 추천 중인" 코어+새틀라이트 종목 목록을 읽는다.

    이 함수는 새로 스캔하지 않는다 — compute_satellite_recommendation()은 S&P500 500종목을 순차
    조회하는 무거운 작업(수 분 소요)이라, 상관관계/실적알림/주간보고처럼 "지금 뭘 들고 있는지만
    알면 되는" 기능들은 스케줄러가 매일 00:10에 미리 계산해둔 캐시를 재사용해야 한다.

    Returns: {"as_of", "core_top4", "satellite_selected", "tickers"(코어+새틀라이트 합집합, 중복
        제거, 정렬됨)} — 아직 한 번도 계산된 적 없으면(캐시 파일 없음) None.
    """
    state = _load_last_signal_state()
    if state is None:
        return None
    core_top4 = state.get("core_top4", [])
    satellite_selected = state.get("satellite_selected", [])
    return {
        "as_of": state.get("as_of"),
        "core_top4": core_top4,
        "satellite_selected": satellite_selected,
        "tickers": sorted(set(core_top4) | set(satellite_selected)),
    }


def compute_champion_correlation(lookback_days: int = CHAMPION_CORRELATION_LOOKBACK_DAYS) -> dict:
    """현재 챔피언 전략 보유종목(코어+새틀라이트) 간 최근 lookback_days일 일간수익률 상관관계를
    계산한다. core.portfolio.compute_correlation_matrix를 그대로 재사용한다 — 상관관계 계산 자체는
    보유 이유(직접 매수든 챔피언 전략 추천이든)와 무관하므로 새 로직이 필요 없다.

    Returns: {"as_of", "tickers", "correlation": DataFrame} — 아직 신호 캐시가 없거나 종목이
        2개 미만이면 correlation은 빈 DataFrame.
    """
    holdings = get_current_holdings()
    tickers = holdings["tickers"] if holdings else []
    if len(tickers) < 2:
        return {"as_of": holdings["as_of"] if holdings else None, "tickers": tickers, "correlation": pd.DataFrame()}
    start = (pd.Timestamp.today() - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    price_histories = get_multiple_price_history(tickers, start=start)
    daily_returns = compute_daily_returns(price_histories)
    return {"as_of": holdings["as_of"], "tickers": tickers, "correlation": compute_correlation_matrix(daily_returns)}


def save_champion_correlation_snapshot(correlation: pd.DataFrame) -> int:
    """compute_champion_correlation()의 상관행렬을 이력으로 저장한다 (core.portfolio의
    save_portfolio_correlation_snapshot과 동일한 CorrelationSnapshot 테이블을 kind="champion"으로
    공유)."""
    labels = list(correlation.columns)
    n = len(labels)
    if n < 2:
        raise ValueError("상관관계 스냅샷을 저장하려면 2종목 이상이 필요합니다.")
    off_diag = correlation.to_numpy()[~np.eye(n, dtype=bool)]
    with get_session() as session:
        row = CorrelationSnapshot(
            kind="champion",
            labels=json.dumps(labels, ensure_ascii=False),
            avg_correlation=float(off_diag.mean()),
            max_correlation=float(off_diag.max()),
            matrix=correlation.to_json(),
        )
        session.add(row)
        session.flush()
        return row.id


def list_champion_correlation_snapshots(limit: int = 12) -> list[dict]:
    """챔피언 전략 보유종목 상관관계 체크 이력을 최신순으로 반환한다."""
    with get_session() as session:
        rows = (
            session.query(CorrelationSnapshot)
            .filter(CorrelationSnapshot.kind == "champion")
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


# ----------------------------------------------------------------------------
# 새틀라이트 실적 발표일 사전 알림 (2026-09-18 추가)
#
# 코어(CORE_UNIVERSE)는 전부 섹터/채권/금/국제주식 ETF라 개별 기업 실적이 없다 — 이 알림이 실제로
# 값을 주는 건 새틀라이트(개별 종목 브레이크아웃) 쪽뿐이다. check_and_notify_upcoming_rebalance()와
# 같은 이유의 사전 알림이지만, 실적 발표는 리밸런싱일보다 주가를 더 크게 흔들 수 있는 이벤트인데도
# 지금까지 아무 사전 경고가 없었다.
# ----------------------------------------------------------------------------

EARNINGS_REMINDER_STATE_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "champion_earnings_reminder_state.json"


def get_upcoming_earnings(tickers: list[str], within_days: int = 5) -> list[dict]:
    """개별 종목의 향후 within_days일 이내 실적 발표 예정일을 찾는다 (yfinance Ticker.calendar).

    ETF나 데이터 없는 종목은 자연히 빈 calendar를 반환하므로 별도 분기 없이 건너뛴다. 종목 하나
    조회가 실패해도(일시적 오류 등) 나머지는 계속 진행한다.

    Returns: [{"ticker", "earnings_date"(ISO 날짜문자열)}, ...] — within_days 이내인 것만, 날짜순.
        종목당 가장 이른 예정일 하나만 포함한다.
    """
    import yfinance as yf

    today = date.today()
    cutoff = today + timedelta(days=within_days)
    upcoming = []
    for ticker in tickers:
        try:
            calendar = yf.Ticker(ticker).calendar
        except Exception:
            continue
        if not calendar:
            continue
        for raw in calendar.get("Earnings Date") or []:
            try:
                d = raw if isinstance(raw, date) else pd.Timestamp(raw).date()
            except (TypeError, ValueError):
                continue
            if today <= d <= cutoff:
                upcoming.append({"ticker": ticker, "earnings_date": d.isoformat()})
                break
    upcoming.sort(key=lambda r: r["earnings_date"])
    return upcoming


def _load_last_earnings_reminder_state() -> Optional[dict]:
    if not EARNINGS_REMINDER_STATE_CACHE_PATH.exists():
        return None
    try:
        with open(EARNINGS_REMINDER_STATE_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_earnings_reminder_state(state: dict) -> None:
    EARNINGS_REMINDER_STATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EARNINGS_REMINDER_STATE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_and_notify_upcoming_earnings(within_days: int = 5, notify_fn=None) -> dict:
    """지금 챔피언 전략이 들고 있는 새틀라이트 종목 중 향후 within_days일 이내 실적 발표가 있으면
    텔레그램으로 미리 알린다. 같은 (종목, 실적일) 조합에 대해서는 한 번만 알린다(dedupe, 리밸런싱
    리마인더와 동일 원칙).

    Args:
        within_days: 오늘로부터 며칠 이내를 "곧 다가올 실적"으로 볼지. 기본 5.
        notify_fn: 텔레그램 전송 함수(테스트 주입용). None이면 core.telegram_notify.send_message.

    Returns: {"as_of", "upcoming"(get_upcoming_earnings 반환값), "notified", "message"}
    """
    if notify_fn is None:
        from core.telegram_notify import send_message as notify_fn

    holdings = get_current_holdings()
    satellite_tickers = holdings["satellite_selected"] if holdings else []
    upcoming = get_upcoming_earnings(satellite_tickers, within_days=within_days) if satellite_tickers else []

    result = {"as_of": date.today().isoformat(), "upcoming": upcoming, "notified": False, "message": None}
    if not upcoming:
        return result

    dedupe_key = json.dumps(upcoming, sort_keys=True)
    already_sent = (_load_last_earnings_reminder_state() or {}).get("dedupe_key") == dedupe_key

    if not already_sent:
        lines = ["📅 챔피언 전략 새틀라이트 실적 발표 예정"]
        lines.extend(f"{item['ticker']}: {item['earnings_date']}" for item in upcoming)
        lines.append(f"(향후 {within_days}일 이내, yfinance 제공 예정일 — 기업이 발표 전 날짜를 바꿀 수 있음)")
        message = "\n".join(lines)
        notify_fn(message)
        result["notified"] = True
        result["message"] = message

    _save_earnings_reminder_state({"as_of": result["as_of"], "dedupe_key": dedupe_key})
    return result


# ----------------------------------------------------------------------------
# 주간 성과 HTML 보고 (2026-09-18 추가)
#
# deploy/experiment_supervisor.py가 이미 "상태를 HTML로 만들어 텔레그램 문서로 전송"하는 패턴을
# 2주 실험 감독에 쓰고 있다 — 그 파일은 stdlib만 쓰는 별도 무인 서비스라 코드를 그대로 가져올 수는
# 없지만, 같은 발상(새 인프라 없이 기존 데이터로 정기 보고서 조립)을 챔피언 전략에도 적용한다.
# core.telegram_notify.send_document가 이미 있어 멀티파트 전송을 직접 구현할 필요가 없다.
# ----------------------------------------------------------------------------

CHAMPION_REPORT_DIR = PROJECT_ROOT / "data" / "cache" / "champion_reports"


def generate_weekly_report_html() -> str:
    """챔피언 전략의 이번 주 상태를 사람이 읽는 HTML 문서로 만든다.

    코어는 compute_core_recommendation()으로 매번 새로 계산한다(17종목뿐이라 빠름). 새틀라이트는
    get_current_holdings()의 캐시된 선정 결과를 쓴다(500종목 재스캔은 이 보고서엔 과함 — 이미
    스케줄러가 매일 밤 갱신해둔 값으로 충분).
    """
    core_result = compute_core_recommendation()
    holdings = get_current_holdings()
    satellite_selected = holdings["satellite_selected"] if holdings else []

    core_rows = "".join(f"<li><code>{t}</code> (모멘텀 {r:.1f}%)</li>"
                        for t, r in zip(core_result["top4"],
                                        core_result["ranked"].set_index("ticker").loc[core_result["top4"], "momentum_pct"]
                                        if core_result["top4"] else [])) or "<li>없음(절대모멘텀 통과 종목 없음)</li>"
    satellite_rows = "".join(f"<li><code>{t}</code></li>" for t in satellite_selected) or "<li>없음(브레이크아웃 종목 없음)</li>"

    corr_history = list_champion_correlation_snapshots(limit=1)
    corr_html = (
        f"평균 {corr_history[0]['avg_correlation']:.2f} / 최대 {corr_history[0]['max_correlation']:.2f} "
        f"({corr_history[0]['computed_at'].strftime('%Y-%m-%d')} 기준)"
        if corr_history else "아직 계산된 적 없음 — Streamlit 챔피언 전략 페이지에서 확인 가능"
    )
    market_filter = "200일선 위 (정상 비중)" if core_result["above_200dma"] else "200일선 아래 (코어 비중 50% 축소)"
    now = date.today().isoformat()

    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>챔피언 전략 주간 보고</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;line-height:1.6;color:#1a1a1a}}
code{{background:#f3f4f6;padding:.1rem .3rem;border-radius:3px}}ul{{padding-left:1.2rem}}
.disclaimer{{color:#6b6b6b;font-size:.9em}}</style></head><body>
<h1>🏆 챔피언 전략 주간 보고</h1><p>생성: <code>{now}</code></p>
<h2>코어 — 섹터 로테이션 모멘텀 (85%)</h2>
<p>시장필터: {market_filter}</p>
<ul>{core_rows}</ul>
<h2>새틀라이트 — 돈치안 브레이크아웃 (15%)</h2>
<ul>{satellite_rows}</ul>
<h2>보유종목 상관관계</h2>
<p>{corr_html}</p>
<p class="disclaimer">참고용 요약이며 투자 조언이 아닙니다. 백테스트·확신도 등 상세 내용은
Streamlit 챔피언 전략 페이지에서 확인하세요.</p>
</body></html>'''


def send_weekly_report(dry_run: bool = False) -> dict:
    """generate_weekly_report_html()을 파일로 저장하고 텔레그램 문서로 전송한다.

    dry_run=True면 파일만 저장하고 전송은 생략한다(테스트/수동 미리보기용 — experiment_supervisor.py의
    --dry-run과 같은 용도).

    Returns: {"path": str, "sent": bool}
    """
    CHAMPION_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = CHAMPION_REPORT_DIR / f"champion_weekly_{date.today().isoformat()}.html"
    report_path.write_text(generate_weekly_report_html(), encoding="utf-8")
    sent = False
    if not dry_run:
        from core.telegram_notify import send_document
        sent = send_document(report_path, caption="🏆 챔피언 전략 주간 보고")
    return {"path": str(report_path), "sent": sent}


# ----------------------------------------------------------------------------
# 알파 감쇠(드리프트) 자동 체크 (2026-09-19 추가)
#
# core.backtest_engine.compute_alpha_decay는 "지표 하나짜리 단일 종목" 백테스트(run_backtest,
# indicator_config 기반)를 위해 만들어져 있어 챔피언 전략(코어 17자산 로테이션 + 새틀라이트
# 반기 point-in-time)의 자체 백테스트 함수(run_champion_backtest)와는 시그니처가 다르다 — 그래서
# 새로 만들지만, 판정 로직(전체기간 대비 최근 구간 성과 비율이 임계값 아래로 떨어지거나 최근
# 성과가 마이너스로 돌아서면 "감쇠")은 compute_alpha_decay와 동일한 원칙을 그대로 따른다(같은
# 임계값 상수를 재사용).
# ----------------------------------------------------------------------------

from core.backtest_engine import DEFAULT_DECAY_METRIC, _DECAY_RATIO_THRESHOLD  # noqa: E402

CHAMPION_DECAY_FULL_LOOKBACK_YEARS = 8  # 챔피언 백테스트가 흔히 쓰는 구간(analysis 리서치와 동일 규모)
CHAMPION_DECAY_RECENT_MONTHS = 6  # backtest_engine.DEFAULT_DECAY_RECENT_MONTHS와 동일
CHAMPION_DECAY_METRIC = DEFAULT_DECAY_METRIC  # "sharpe" — backtest_engine과 같은 지표를 써서 서로 비교 가능하게
DECAY_STATE_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "champion_decay_state.json"


def compute_champion_alpha_decay(
    full_lookback_years: int = CHAMPION_DECAY_FULL_LOOKBACK_YEARS,
    recent_months: int = CHAMPION_DECAY_RECENT_MONTHS,
    metric: str = CHAMPION_DECAY_METRIC,
) -> dict:
    """챔피언 전략(run_champion_backtest) 전체기간 대비 최근 recent_months개월 성과가 얼마나
    이탈했는지 비교한다 — core.backtest_engine.compute_alpha_decay와 동일한 판정 원칙(비율
    임계값/부호전환)을 챔피언 전용 백테스트 함수에 적용한 버전.

    Returns:
        {"full_metrics", "recent_metrics", "metric", "decay_ratio", "is_decayed",
         "full_start", "full_end", "recent_start"}
        decay_ratio: recent_metric / full_metric (full_metric<=0이면 None).
        is_decayed: decay_ratio < _DECAY_RATIO_THRESHOLD 이거나 최근 metric이 음수로 돌아섰으면 True.
    """
    full_end = date.today().isoformat()
    full_start = (pd.Timestamp(full_end) - pd.DateOffset(years=full_lookback_years)).date().isoformat()
    recent_start = (pd.Timestamp(full_end) - pd.DateOffset(months=recent_months)).date().isoformat()

    full_run = run_champion_backtest(full_start, full_end)
    recent_run = run_champion_backtest(recent_start, full_end)

    full_metric = full_run["metrics"].get(metric)
    recent_metric = recent_run["metrics"].get(metric)

    decay_ratio: Optional[float] = None
    is_decayed = False
    if full_metric is not None and recent_metric is not None:
        if full_metric > 0:
            decay_ratio = recent_metric / full_metric
            is_decayed = decay_ratio < _DECAY_RATIO_THRESHOLD or recent_metric < 0
        else:
            is_decayed = recent_metric < full_metric

    return {
        "full_metrics": full_run["metrics"],
        "recent_metrics": recent_run["metrics"],
        "metric": metric,
        "decay_ratio": round(decay_ratio, 3) if decay_ratio is not None else None,
        "is_decayed": is_decayed,
        "full_start": full_start,
        "full_end": full_end,
        "recent_start": recent_start,
    }


def _load_last_decay_state() -> Optional[dict]:
    if not DECAY_STATE_CACHE_PATH.exists():
        return None
    try:
        with open(DECAY_STATE_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_decay_state(state: dict) -> None:
    DECAY_STATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DECAY_STATE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_and_notify_champion_alpha_decay(notify_fn=None) -> dict:
    """compute_champion_alpha_decay()를 실행해 is_decayed면 텔레그램으로 알린다.

    같은 감쇠 상태가 계속되는 동안은 매일 재알림하지 않는다(dedupe — as_of 날짜만 다르고
    is_decayed/decay_ratio가 바뀌지 않았으면 조용히 넘어감) — 감쇠에서 회복되거나(is_decayed가
    False로 바뀜) decay_ratio가 눈에 띄게(0.05 이상) 더 나빠졌을 때만 다시 알린다. 다른
    check_and_notify_* 함수들과 동일한 "조용한 기본값" 원칙.

    Args:
        notify_fn: 텔레그램 전송 함수(테스트 주입용). None이면 core.telegram_notify.send_message.

    Returns: {"as_of", "decay", "notified", "message"}
    """
    if notify_fn is None:
        from core.telegram_notify import send_message as notify_fn

    decay = compute_champion_alpha_decay()
    as_of = date.today().isoformat()
    result = {"as_of": as_of, "decay": decay, "notified": False, "message": None}

    last_state = _load_last_decay_state() or {}
    last_is_decayed = bool(last_state.get("is_decayed"))
    last_ratio = last_state.get("decay_ratio")
    ratio = decay["decay_ratio"]

    should_notify = decay["is_decayed"] and (
        not last_is_decayed
        or last_ratio is None
        or ratio is None
        or abs(ratio - last_ratio) >= 0.05
    )

    if should_notify:
        message = (
            "⚠️ 챔피언 전략 알파 감쇠 감지\n"
            f"지표: {decay['metric']}, 전체기간({decay['full_start']}~{decay['full_end']}): "
            f"{decay['full_metrics'].get(decay['metric'])}\n"
            f"최근 {CHAMPION_DECAY_RECENT_MONTHS}개월({decay['recent_start']}~{decay['full_end']}): "
            f"{decay['recent_metrics'].get(decay['metric'])}\n"
            f"비율(최근/전체): {ratio}\n"
            "이건 이 전략의 백테스트 성과가 최근 이탈했다는 신호일 뿐, 자동으로 전략을 멈추거나 "
            "비중을 바꾸지 않습니다 — 직접 확인해보세요."
        )
        notify_fn(message)
        result["notified"] = True
        result["message"] = message

    _save_decay_state({"as_of": as_of, "is_decayed": decay["is_decayed"], "decay_ratio": ratio})
    return result


# ----------------------------------------------------------------------------
# 페이퍼 트레이딩 원장 (2026-09-19 추가)
#
# 지금까지의 알림들(신호 변경/리밸런싱/실적/상관관계/알파 감쇠)은 전부 "추천"이나 "과거 백테스트"만
# 다뤘다 — 이 전략을 실제로 매일 따랐다면 지금 어떤 성과였을지는 아무 데도 기록되지 않았다. 이
# 섹션은 매일 밤 그날의 실현 수익률을 누적 기록해서(get_current_holdings가 읽는 신호 캐시와는
# 별개로, 실제 "매매를 실행했다면"의 관점) 나중에 알파 감쇠 체크나 벤치마크 비교의 근거로 쓸 수
# 있게 한다. 새 백테스트 엔진이 아니라 이미 있는 compute_core_recommendation/
# compute_satellite_recommendation의 라이브 추천을 그대로 누적 기록하는 것뿐이다.
# ----------------------------------------------------------------------------

LEDGER_HISTORY_FETCH_DAYS = 10  # 어제 종가 대비 오늘 종가만 필요하지만, 휴장일/데이터 지연에 대비해 여유를 둠


def record_daily_ledger_entry() -> dict:
    """오늘자 원장 항목을 기록한다 — 어제 저장해둔 비중으로 오늘 실현된 수익률을 계산하고,
    오늘 기준 새 추천 비중을 다음날 쓸 값으로 저장한다.

    같은 날짜에 이미 항목이 있으면(하루 여러 번 실행돼도) 아무것도 하지 않고 건너뛴다 — 원장은
    "하루에 정확히 한 번"이 불변조건이어야 나중에 계산하는 누적수익률이 왜곡되지 않는다.

    Returns:
        {"skipped": bool, "as_of", "realized_return_pct", "cumulative_equity"} (skipped=True면
        나머지 필드는 직전 항목 값 또는 없음)
    """
    today = date.today()
    with get_session() as session:
        last_entry = (
            session.query(ChampionLedgerEntry).order_by(ChampionLedgerEntry.entry_date.desc()).first()
        )
        if last_entry is not None and last_entry.entry_date >= today:
            return {
                "skipped": True, "as_of": today.isoformat(),
                "realized_return_pct": last_entry.realized_return_pct,
                "cumulative_equity": last_entry.cumulative_equity,
            }

        realized_return_pct = 0.0
        prev_equity = last_entry.cumulative_equity if last_entry is not None else 100.0
        if last_entry is not None:
            prev_weights: dict[str, float] = {
                **json.loads(last_entry.core_weights), **json.loads(last_entry.satellite_weights)
            }
            if prev_weights:
                tickers = list(prev_weights.keys())
                fetch_start = (pd.Timestamp.today() - pd.Timedelta(days=LEDGER_HISTORY_FETCH_DAYS)).date().isoformat()
                histories = get_multiple_price_history(tickers, start=fetch_start, interval="1d")
                total = 0.0
                for ticker, weight in prev_weights.items():
                    df = histories.get(ticker)
                    if df is None or len(df) < 2:
                        continue  # 데이터를 못 받아온 종목은 그날 기여분을 0으로 본다(원장 전체를 막지 않음)
                    day_return = float(df["Close"].iloc[-1] / df["Close"].iloc[-2] - 1.0)
                    total += weight * day_return
                realized_return_pct = round(total * 100, 4)

        new_equity = round(prev_equity * (1 + realized_return_pct / 100), 4)

        core_rec = compute_core_recommendation()
        satellite_rec = compute_satellite_recommendation()

        entry = ChampionLedgerEntry(
            entry_date=today,
            core_weights=json.dumps(core_rec["per_ticker_weights"]),
            satellite_weights=json.dumps(satellite_rec["per_ticker_weights"]),
            realized_return_pct=realized_return_pct,
            cumulative_equity=new_equity,
        )
        session.add(entry)
        session.flush()

        return {
            "skipped": False, "as_of": today.isoformat(),
            "realized_return_pct": realized_return_pct, "cumulative_equity": new_equity,
        }


def list_ledger_entries(limit: int = 400) -> list[dict]:
    """원장 항목을 날짜 오름차순으로 최근 limit개 반환한다 (성과 계산/차트용)."""
    with get_session() as session:
        rows = (
            session.query(ChampionLedgerEntry)
            .order_by(ChampionLedgerEntry.entry_date.desc())
            .limit(limit)
            .all()
        )
        rows = list(reversed(rows))
        return [
            {
                "entry_date": row.entry_date.isoformat(),
                "core_weights": json.loads(row.core_weights),
                "satellite_weights": json.loads(row.satellite_weights),
                "realized_return_pct": row.realized_return_pct,
                "cumulative_equity": row.cumulative_equity,
            }
            for row in rows
        ]


def compute_ledger_performance_summary() -> dict:
    """원장 누적 자산가치 곡선으로 실현 성과 지표(core.backtest_engine.calculate_metrics 재사용)를
    계산한다. 항목이 하나도 없으면 {"available": False}."""
    entries = list_ledger_entries()
    if not entries:
        return {"available": False, "entry_count": 0}

    equity = pd.Series(
        [e["cumulative_equity"] for e in entries],
        index=pd.to_datetime([e["entry_date"] for e in entries]),
    )
    metrics = calculate_metrics(equity, [], equity.index[0], equity.index[-1])
    return {
        "available": True,
        "entry_count": len(entries),
        "start_date": entries[0]["entry_date"],
        "end_date": entries[-1]["entry_date"],
        "metrics": metrics,
    }


# ----------------------------------------------------------------------------
# 벤치마크 대비 실시간 아웃퍼폼 추적 (2026-09-19 추가)
#
# 위 페이퍼 트레이딩 원장이 쌓이기 시작해야만 의미가 있다 — 원장이 없으면(또는
# BENCHMARK_MIN_LEDGER_DAYS일 미만이면) "비교할 실현 성과 자체가 아직 없다"고 정직하게 답한다.
# 60/40(SPY/TLT)을 참고 벤치마크로 쓴다 — 둘 다 이미 CORE_UNIVERSE에 있는 자산이라 새 데이터
# 소스가 필요 없다.
# ----------------------------------------------------------------------------

BENCHMARK_MIN_LEDGER_DAYS = 20  # 이보다 적으면 비교가 통계적으로 무의미하다고 보고 비교를 건너뜀
BENCHMARK_6040_EQUITY_TICKER = "SPY"
BENCHMARK_6040_BOND_TICKER = "TLT"
BENCHMARK_6040_EQUITY_WEIGHT = 0.6
BENCHMARK_GAP_ALERT_THRESHOLD_PCT = -5.0  # 벤치마크 대비 이 %p 이상 뒤처지면 알림 (예: -5.0 = 5%p 뒤처짐)
BENCHMARK_STATE_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "champion_benchmark_state.json"


def compute_benchmark_comparison() -> dict:
    """원장의 실현 성과를 같은 기간의 SPY 매수보유 및 60/40(SPY/TLT) 벤치마크와 비교한다.

    Returns:
        {"available": bool, "reason"(available=False일 때만), "start_date", "end_date",
         "ledger_total_return_pct", "spy_total_return_pct", "sixty_forty_total_return_pct",
         "gap_vs_spy_pct", "gap_vs_sixty_forty_pct"}
        gap_* = 원장 누적수익률 - 벤치마크 누적수익률(%p) — 음수면 벤치마크보다 뒤처짐.
    """
    entries = list_ledger_entries()
    if len(entries) < BENCHMARK_MIN_LEDGER_DAYS:
        return {
            "available": False,
            "reason": f"원장 기록이 {BENCHMARK_MIN_LEDGER_DAYS}일 미만이라 벤치마크 비교를 건너뜀 (현재 {len(entries)}일).",
        }

    start_date = entries[0]["entry_date"]
    end_date = entries[-1]["entry_date"]
    ledger_total_return_pct = (entries[-1]["cumulative_equity"] / 100.0 - 1.0) * 100

    histories = get_multiple_price_history(
        [BENCHMARK_6040_EQUITY_TICKER, BENCHMARK_6040_BOND_TICKER], start=start_date, end=end_date, interval="1d"
    )
    spy = histories.get(BENCHMARK_6040_EQUITY_TICKER)
    tlt = histories.get(BENCHMARK_6040_BOND_TICKER)
    if spy is None or spy.empty:
        return {"available": False, "reason": "SPY 가격 데이터를 가져오지 못해 벤치마크 비교를 건너뜀."}

    spy_total_return_pct = float(spy["Close"].iloc[-1] / spy["Close"].iloc[0] - 1.0) * 100
    if tlt is not None and not tlt.empty:
        tlt_total_return_pct = float(tlt["Close"].iloc[-1] / tlt["Close"].iloc[0] - 1.0) * 100
        sixty_forty_total_return_pct = (
            BENCHMARK_6040_EQUITY_WEIGHT * spy_total_return_pct
            + (1 - BENCHMARK_6040_EQUITY_WEIGHT) * tlt_total_return_pct
        )
    else:
        sixty_forty_total_return_pct = None

    return {
        "available": True,
        "start_date": start_date,
        "end_date": end_date,
        "ledger_total_return_pct": round(ledger_total_return_pct, 3),
        "spy_total_return_pct": round(spy_total_return_pct, 3),
        "sixty_forty_total_return_pct": round(sixty_forty_total_return_pct, 3) if sixty_forty_total_return_pct is not None else None,
        "gap_vs_spy_pct": round(ledger_total_return_pct - spy_total_return_pct, 3),
        "gap_vs_sixty_forty_pct": (
            round(ledger_total_return_pct - sixty_forty_total_return_pct, 3)
            if sixty_forty_total_return_pct is not None else None
        ),
    }


def _load_last_benchmark_state() -> Optional[dict]:
    if not BENCHMARK_STATE_CACHE_PATH.exists():
        return None
    try:
        with open(BENCHMARK_STATE_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_benchmark_state(state: dict) -> None:
    BENCHMARK_STATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BENCHMARK_STATE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_and_notify_benchmark_gap(notify_fn=None) -> dict:
    """compute_benchmark_comparison()의 60/40 대비 격차가 BENCHMARK_GAP_ALERT_THRESHOLD_PCT보다
    더 나쁘면 텔레그램으로 알린다.

    같은 격차 상태가 계속되는 동안은 매일 재알림하지 않는다(check_and_notify_champion_alpha_decay와
    동일한 dedupe 원칙 — gap_vs_sixty_forty_pct가 2.0%p 이상 더 나빠지거나 격차 상태에서
    회복됐을 때만 다시 알림).

    Returns: {"as_of", "comparison", "notified", "message"}
    """
    if notify_fn is None:
        from core.telegram_notify import send_message as notify_fn

    comparison = compute_benchmark_comparison()
    as_of = date.today().isoformat()
    result = {"as_of": as_of, "comparison": comparison, "notified": False, "message": None}

    if not comparison["available"] or comparison.get("gap_vs_sixty_forty_pct") is None:
        return result

    gap = comparison["gap_vs_sixty_forty_pct"]
    is_lagging = gap <= BENCHMARK_GAP_ALERT_THRESHOLD_PCT

    last_state = _load_last_benchmark_state() or {}
    last_is_lagging = bool(last_state.get("is_lagging"))
    last_gap = last_state.get("gap")

    should_notify = is_lagging and (
        not last_is_lagging or last_gap is None or (last_gap - gap) >= 2.0
    )

    if should_notify:
        message = (
            "📉 챔피언 전략, 60/40 벤치마크 대비 부진\n"
            f"기간: {comparison['start_date']}~{comparison['end_date']} (페이퍼 트레이딩 원장 실현 기준)\n"
            f"원장 누적수익률: {comparison['ledger_total_return_pct']}%\n"
            f"SPY: {comparison['spy_total_return_pct']}% | 60/40(SPY/TLT): {comparison['sixty_forty_total_return_pct']}%\n"
            f"격차(60/40 대비): {gap}%p\n"
            "이건 실현 성과가 단순 벤치마크에 못 미친다는 신호일 뿐, 자동으로 전략을 멈추지 않습니다."
        )
        notify_fn(message)
        result["notified"] = True
        result["message"] = message

    _save_benchmark_state({"as_of": as_of, "is_lagging": is_lagging, "gap": gap})
    return result


# ----------------------------------------------------------------------------
# 칼라 헤지 롤 예정 알림 (2026-09-19 추가) — check_and_notify_upcoming_rebalance 확장
# ----------------------------------------------------------------------------

def _collar_roll_reminder_line() -> Optional[str]:
    """compute_live_collar_state()의 남은 만기가 1거래일 이하면 알림 문구 한 줄을 만든다.
    SPY/VIX 데이터를 못 받아오면(계산 불가) None — 리밸런싱 알림 자체는 막지 않는다."""
    try:
        collar = compute_live_collar_state()
    except Exception:
        return None
    if collar is None or collar["days_remaining"] > 1:
        return None
    return (
        f"🛡️ 칼라 헤지도 곧 롤 예정 (만기 {collar['days_remaining']}거래일 남음, "
        f"이번 사이클 마크투모델 손익 {collar['mark_to_model_pnl_pct_of_satellite_notional']}%)"
    )
