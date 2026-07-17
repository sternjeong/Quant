"""모듈 G 확장: S&P500 기반 시장 국면(강세/약세) 룰 기반 복합지표.

MARKET_REGIME_SECTOR_STRENGTH_SPEC.md 참고. 4개 신호(200일선 대비 위치, 50/200일 골든·데드크로스,
시장폭[S&P500 중 200일선 위 종목 비율], 52주 고점 대비 낙폭)를 각각 점수화해 합산하는 투명한
간이 프레임워크다 — `core/macro_cycle.py`와 동일하게 특정 데이터 제공자의 실시간 판단이 아니라
참고용 경험칙임을 UI에 명시한다.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from core import fred_data
from core.backtest_engine import DEFAULT_BENCHMARK_TICKER
from core.db import get_session
from core.indicators import sma
from core.market_data import get_multiple_price_history, get_price_history
from core.models import MarketRegimeSnapshot

KST = ZoneInfo("Asia/Seoul")

BULLISH_THRESHOLD = 35
BEARISH_THRESHOLD = -35

BREADTH_BULLISH_PCT = 70.0
BREADTH_BEARISH_PCT = 30.0
BEAR_MARKET_DRAWDOWN_PCT = -20.0  # 통상적인 "공식 약세장" 정의 기준

# 국면별(약세장/강세장) 분리 트레이닝용 일별 이력 라벨링 (STRATEGY_TUNING_ENGINE_SPEC.md 13.3절).
# 200일선 위여도 이 이상 조정 중이면 "강세장"으로 보지 않고 "중립"으로 남긴다(애매한 날을
# 트레이닝에 안 씀). 세그먼트가 이보다 짧은 거래일이면 국면 경계의 flicker로 보고 버린다 — 실제
# 2018~2023 데이터로 검증하다가 20 거래일로는 2020년 코로나 급락(고점 대비 -20% 이상이 지속된
# 기간이 약 17거래일)이 flicker로 오인돼 통째로 버려지는 것을 발견해 10으로 낮췄다(역사상 가장
# 빠른 약세장 중 하나였던 급락 자체가 짧아서 생긴 문제 — 회복이 빨라도 실제 약세장이었던 구간을
# 놓치면 안 되므로, 노이즈는 걸러내되 이 정도 급락은 살아남을 만큼 보수적으로 낮춤).
_TREND_CORRECTION_PCT = -10.0
_MIN_REGIME_SEGMENT_TRADING_DAYS = 10

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


SHORT_TERM_WINDOWS_TRADING_DAYS = {"1개월": 21, "3개월": 63}
SHORT_TERM_BULLISH_PCT = 5.0
SHORT_TERM_BEARISH_PCT = -5.0


def classify_period_return_regime(
    close: pd.Series,
    window_days: int,
    bullish_pct: float = SHORT_TERM_BULLISH_PCT,
    bearish_pct: float = SHORT_TERM_BEARISH_PCT,
) -> Optional[dict]:
    """단기 국면: window_days(거래일) 전 대비 현재 종가의 등락률 부호만으로 단순 판단한다.

    장기 4신호 합산 방식과 달리 추세선/시장폭 없이 "최근 N거래일 수익률(%)"만 본다 — 더 직관적이지만
    노이즈에 민감해 자주 뒤바뀔 수 있음을 감안한 참고 지표(SPEC 상 의도된 트레이드오프).
    """
    s = close.dropna()
    if len(s) < window_days + 1:
        return None
    period_return_pct = (float(s.iloc[-1]) / float(s.iloc[-window_days - 1]) - 1) * 100
    if period_return_pct >= bullish_pct:
        regime = "강세장"
    elif period_return_pct <= bearish_pct:
        regime = "약세장"
    else:
        regime = "중립/혼조"
    return {"regime": regime, "period_return_pct": period_return_pct, "window_days": window_days}


def get_short_term_regimes(close: pd.Series) -> dict:
    """1개월/3개월 단기 국면을 함께 계산한다 (get_market_regime_snapshot()이 이미 가져온 벤치마크
    종가를 재사용 — 별도 조회 없음).

    Returns: {"1개월": dict|None, "3개월": dict|None} — 각 값은 classify_period_return_regime() 결과.
    """
    return {
        label: classify_period_return_regime(close, window_days)
        for label, window_days in SHORT_TERM_WINDOWS_TRADING_DAYS.items()
    }


def score_breadth(pct_above_200sma: float) -> dict:
    """S&P500 중 200일선 위 종목 비율(0~100)로 ±25점을 매긴다(50%=0점 기준, 30%/70%에서 클립)."""
    score = _clip((pct_above_200sma - 50.0) * 1.25, -25.0, 25.0)
    return {
        "score": score,
        "pct_above_200sma": pct_above_200sma,
        "is_overheated": pct_above_200sma >= 85.0,
    }


VIX_TICKER = "^VIX"

# 심층 리스크 신호(참고용) 임계값 — 종합 점수(total_score)에는 섞지 않는다. 기존 4신호 합산
# 로직과 core.strategy_tuning의 국면별 분리 트레이닝(classify_daily_regime)이 이미 검증된 상태라
# 건드리지 않고, "더 엄밀한 판단을 돕는 보조 신호"로 UI에 별도 표시하는 용도다(2026-07-17,
# 인터넷 조사 근거는 함수 docstring 참고).
_VIX_BANDS = [  # (미만 임계값, 점수, 라벨) — CBOE 공식 정의(S&P500 30일 내재변동성 기대치) +
    # 실무 관행 임계값(< 15 안정/복부감, 25~30 이상 공포, 40 이상 패닉). Cboe·업계 해설 다수 확인.
    (15.0, 10.0, "안정(낮은 변동성)"),
    (20.0, 0.0, "평상"),
    (25.0, -10.0, "경계"),
    (30.0, -18.0, "공포 고조"),
    (float("inf"), -25.0, "패닉"),
]

# ICE BofA US High Yield OAS(FRED: BAMLH0A0HYM2) 기준. 장기 평균 약 500bp, 정상범위 350~700bp,
# 300bp 미만은 "복부감" 구간(과거 사이클 고점 부근에서 자주 관측), 800bp 이상 중간 스트레스,
# 1000bp 이상 급성 스트레스로 보는 것이 다수 신용시장 해설의 공통 견해.
_CREDIT_SPREAD_BANDS = [
    (300.0, 10.0, "복부감(과열 주의)"),
    (500.0, 0.0, "정상"),
    (800.0, -15.0, "스트레스 고조"),
    (1000.0, -20.0, "높은 스트레스"),
    (float("inf"), -25.0, "급성 스트레스"),
]


def _band_score(value: float, bands: list[tuple[float, float, str]]) -> tuple[float, str]:
    for upper, score, label in bands:
        if value < upper:
            return score, label
    return bands[-1][1], bands[-1][2]


def score_vix(vix_close: pd.Series) -> Optional[dict]:
    """VIX(S&P500 옵션 내재변동성 기대치) 종가 수준으로 시장의 단기 공포/안정 정도를 점수화한다.

    참고용 심층 리스크 신호 — 기존 4신호 종합 점수(total_score)에는 섞지 않는다. CBOE 공식 정의와
    업계에서 통용되는 관행적 임계값(15/20/25/30)을 근거로 한다.
    """
    s = vix_close.dropna()
    if s.empty:
        return None
    level = float(s.iloc[-1])
    score, band = _band_score(level, _VIX_BANDS)
    return {"score": score, "level": level, "band": band}


def score_credit_spread(hy_oas: pd.Series) -> Optional[dict]:
    """하이일드 회사채 신용 스프레드(OAS, bp)로 신용시장 스트레스를 점수화한다.

    FRED `BAMLH0A0HYM2`(ICE BofA US High Yield Index Option-Adjusted Spread)를 사용한다.
    투기등급 회사채가 국채 대비 얼마나 더 높은 금리를 요구받는지를 나타내며, 주식시장보다
    먼저 스트레스를 반영하는 경우가 많다고 알려진 신호다. 참고용 — 종합 점수에는 미반영.
    """
    s = hy_oas.dropna()
    if s.empty:
        return None
    level_bp = float(s.iloc[-1]) * 100  # FRED 값은 % 단위이므로 bp로 환산
    score, band = _band_score(level_bp, _CREDIT_SPREAD_BANDS)
    result = {"score": score, "level_bp": level_bp, "band": band}
    if len(s) > 20:
        change_20d_bp = level_bp - float(s.iloc[-21]) * 100
        result["change_20d_bp"] = change_20d_bp
    return result


def score_yield_curve_3m(spread_pct: Optional[float]) -> Optional[dict]:
    """10년물-3개월물 국채금리차(T10Y3M)로 경기침체 선행경보를 점수화한다.

    뉴욕 연준의 공식 경기침체 확률 모형이 사용하는 스프레드로(10Y-2Y보다 이 스프레드를 더
    신뢰할 수 있는 선행지표로 보는 연구가 많음), 역전(음수)은 1968년 이후 모든 미국 침체에
    선행했다고 알려져 있다(선행 시차는 통상 6~18개월로 길어 단기 매매 신호는 아님). 참고용 —
    종합 점수에는 미반영.
    """
    if spread_pct is None:
        return None
    inverted = spread_pct < 0
    if inverted:
        score, band = -20.0, "역전(침체 선행경보)"
    elif spread_pct < 0.5:
        score, band = -5.0, "평탄화(주의)"
    else:
        score, band = 5.0, "정상(우상향)"
    return {"score": score, "spread_pct": spread_pct, "inverted": inverted, "band": band}


def get_advisory_risk_signals(benchmark_start: Optional[str] = None) -> dict:
    """VIX·하이일드 신용스프레드·10Y-3M 금리차 3개 심층 리스크 신호를 계산한다.

    기존 4신호 종합 점수(get_market_regime_snapshot)와 국면별 분리 트레이닝용 일별 라벨링
    (classify_daily_regime)은 이미 검증되어 있어 건드리지 않고, 이 함수는 시장 국면을 "더 엄밀하게"
    판단하고 싶을 때 참고할 수 있는 보조 신호만 별도로 제공한다(2026-07-17, 사용자 요청으로 웹
    리서치 후 추가 — CBOE VIX 공식 정의, FRED BAMLH0A0HYM2(ICE BofA), 뉴욕 연은 공식 침체확률
    모형(10Y-3M)을 근거로 함). FRED_API_KEY가 없으면 credit_spread/yield_curve_3m은 None(VIX는
    yfinance라 키 없이도 계산됨) — 예외는 던지지 않는다.
    """
    vix_df = get_price_history(VIX_TICKER, start=benchmark_start or _default_start(), end=None, interval="1d")
    vix = score_vix(vix_df["Close"]) if not vix_df.empty else None

    credit_spread: Optional[dict] = None
    yield_curve_3m: Optional[dict] = None
    if fred_data.is_configured():
        hy_series = fred_data.get_series("BAMLH0A0HYM2")
        credit_spread = score_credit_spread(hy_series)
        t10y3m_series = fred_data.get_series("T10Y3M").dropna()
        if not t10y3m_series.empty:
            yield_curve_3m = score_yield_curve_3m(float(t10y3m_series.iloc[-1]))

    return {"vix": vix, "credit_spread": credit_spread, "yield_curve_3m": yield_curve_3m}


def classify_daily_regime(close: pd.Series) -> pd.Series:
    """종가 시계열 하나로 일별 국면("강세장"/"약세장"/"중립")을 결정론적으로 라벨링한다.

    STRATEGY_TUNING_ENGINE_SPEC.md 13.3절 — core.strategy_tuning의 국면별 분리 트레이닝이 5년치
    이력 전체를 매일 밤 훑어야 해서, get_market_regime_snapshot()의 시장폭(전종목 200일선 조회)
    신호는 비용 문제로 빼고 벤치마크 종가 하나로 벡터 연산 가능한 2개 신호만 재사용한다: 200일선
    대비 위치 + 52주 고점 대비 낙폭(BEAR_MARKET_DRAWDOWN_PCT). 낙폭이 -20% 이하면 다른 신호와
    무관하게 무조건 "약세장". 200일선 위 + 조정폭이 -10% 이내면 "강세장". 나머지(200일선 아래인데
    -20%까지는 아니거나, 200일선 위인데 -10~-20% 조정 중)는 "중립"으로 남겨 국면별 트레이닝
    어느 쪽에도 쓰지 않는다.

    Returns:
        close와 같은 인덱스의 문자열 Series ("강세장"|"약세장"|"중립"). 200일 미만이라 SMA200을
        계산할 수 없는 앞부분은 "중립".
    """
    close = close.dropna()
    if close.empty:
        return pd.Series(dtype=object)

    sma200 = sma(close, 200)
    rolling_high = close.rolling(252, min_periods=1).max()
    drawdown_pct = (close / rolling_high - 1) * 100

    is_bear = drawdown_pct <= BEAR_MARKET_DRAWDOWN_PCT
    is_bull = (close > sma200).fillna(False) & (drawdown_pct > _TREND_CORRECTION_PCT) & ~is_bear

    regime = pd.Series("중립", index=close.index)
    regime[is_bear] = "약세장"
    regime[is_bull] = "강세장"
    regime[sma200.isna()] = "중립"
    return regime


def find_regime_segments(
    regime: pd.Series, target_regime: str, min_trading_days: int = _MIN_REGIME_SEGMENT_TRADING_DAYS
) -> list[tuple[str, str]]:
    """국면 라벨 시계열에서 target_regime인 연속 구간들을 (시작일, 종료일) 문자열 튜플로 뽑는다.

    STRATEGY_TUNING_ENGINE_SPEC.md 13.4절 — 이 리스트가 core.strategy_tuning의 워크포워드 폴드로
    그대로 재사용된다. min_trading_days 미만인 짧은 구간(국면 경계의 flicker)은 다른 국면에
    편입하지 않고 그냥 버린다.
    """
    if regime.empty:
        return []
    dates = regime.index
    labels = regime.to_numpy()
    segments: list[tuple[str, str]] = []
    seg_start: Optional[int] = None
    for i, label in enumerate(labels):
        matches = label == target_regime
        if matches and seg_start is None:
            seg_start = i
        elif not matches and seg_start is not None:
            if i - seg_start >= min_trading_days:
                segments.append((dates[seg_start].date().isoformat(), dates[i - 1].date().isoformat()))
            seg_start = None
    if seg_start is not None and len(labels) - seg_start >= min_trading_days:
        segments.append((dates[seg_start].date().isoformat(), dates[-1].date().isoformat()))
    return segments


def historical_regime_segments(
    start: str,
    end: str,
    benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER,
    min_trading_days: int = _MIN_REGIME_SEGMENT_TRADING_DAYS,
) -> dict[str, list[tuple[str, str]]]:
    """[start, end] 구간을 국면별 연속 세그먼트로 나눠 반환한다 (13.4절 — 워크포워드 폴드 재사용용).

    200일선 계산을 위해 start보다 앞서서(DEFAULT_LOOKBACK_DAYS) 넉넉히 가격을 가져온 뒤 라벨링하고
    [start, end] 범위로 다시 잘라낸다.

    Returns:
        {"강세장": [(구간시작, 구간종료), ...], "약세장": [...]} — 구간 안의 "중립" 날짜는 버려진다.
        가격 데이터 조회 실패 시 양쪽 다 빈 리스트.
    """
    fetch_start = (pd.Timestamp(start) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).date().isoformat()
    df = get_price_history(benchmark_ticker, start=fetch_start, end=end, interval="1d")
    if df is None or df.empty:
        return {"강세장": [], "약세장": []}

    regime = classify_daily_regime(df["Close"])
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    regime = regime.loc[(regime.index >= start_ts) & (regime.index <= end_ts)]
    return {
        "강세장": find_regime_segments(regime, "강세장", min_trading_days),
        "약세장": find_regime_segments(regime, "약세장", min_trading_days),
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
            "short_term": {"1개월": dict|None, "3개월": dict|None},
        }

    "regime"/"total_score"는 위 4개 신호(200일선 등 중장기·1년 안팎 추세) 기준이고, "short_term"은
    별도로 최근 1개월/3개월 수익률(%) 부호만 보는 단기 참고 지표다 — 종합 점수 계산에는 섞이지 않는다
    (장기 국면 판정 로직/임계값을 바꾸지 않기 위함, 화면에는 나란히 표시).
    """
    df = get_price_history(benchmark_ticker, start=_default_start(), end=None, interval="1d")
    close = df["Close"] if not df.empty else pd.Series(dtype=float)

    trend_position = score_trend_position(close)
    ma_cross = score_ma_cross(close)
    drawdown = score_drawdown(close)
    breadth_raw = compute_market_breadth(universe_tickers)
    breadth = score_breadth(breadth_raw["pct_above_200sma"])
    breadth.update(breadth_raw)
    short_term = get_short_term_regimes(close)

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
        "short_term": short_term,
        "benchmark_ticker": benchmark_ticker,
    }


def save_market_regime_snapshot(snapshot: dict) -> int:
    """get_market_regime_snapshot()의 결과를 DB에 저장한다.

    scheduler/run_scheduler.py::market_snapshot_job()이 매일 한국시간 00:00에 호출하는 게 기본
    경로이고, Streamlit 페이지에서 사용자가 "지금 다시 계산"을 눌렀을 때도 결과를 여기 저장해
    다음 조회부터 최신값을 즉시 보여준다.
    """
    with get_session() as session:
        row = MarketRegimeSnapshot(
            regime=snapshot["regime"],
            total_score=snapshot["total_score"],
            detail=json.dumps(snapshot, ensure_ascii=False),
        )
        session.add(row)
        session.flush()
        return row.id


def get_latest_market_regime_snapshot() -> Optional[dict]:
    """가장 최근에 저장된 시장 국면 스냅샷을 반환한다. 아직 하나도 없으면 None.

    Returns: get_market_regime_snapshot()과 동일한 키에 "computed_at"(datetime)이 더해진 dict.
    """
    with get_session() as session:
        row = (
            session.query(MarketRegimeSnapshot)
            .order_by(MarketRegimeSnapshot.id.desc())
            .first()
        )
        if row is None:
            return None
        detail = json.loads(row.detail)
        detail["computed_at"] = row.computed_at
        return detail


def to_kst(computed_at: datetime) -> datetime:
    """DB에 UTC(naive)로 저장된 computed_at을 한국시간(KST, tz-aware)으로 변환한다 (표시용)."""
    return computed_at.replace(tzinfo=timezone.utc).astimezone(KST)


def is_snapshot_stale_for_today_kst(computed_at: datetime, now_kst: Optional[datetime] = None) -> bool:
    """저장된 스냅샷이 "오늘"(한국시간 00:00 이후) 계산된 게 아니면 True(=다시 계산해야 함).

    로컬에서 scheduler/run_scheduler.py를 상시로 띄워두면 매일 00:00(KST)에 미리 계산돼 있어 이
    함수는 사실상 항상 False를 반환하지만, Streamlit Community Cloud처럼 별도 백그라운드 프로세스를
    띄울 수 없는 환경(앱 컨테이너 자체가 방문이 없으면 잠들어 스레드도 같이 멈춘다)에서는 이게
    유일하게 기댈 수 있는 갱신 트리거가 된다 — 자정이 지난 뒤 누군가 페이지를 열면(로컬이든
    클라우드든 상관없이) 그 방문이 스스로 재계산을 트리거하고, 그날의 나머지 방문은 DB에 저장된 값을
    그대로 재사용한다(2026-07-15, Streamlit Cloud 배포 대응).

    computed_at은 DB에 datetime.utcnow()(naive, UTC 기준)로 저장돼 있으므로 여기서 KST로 변환한다.
    now_kst는 테스트에서 "지금 시각"을 주입하기 위한 선택 인자(기본은 실제 현재 KST 시각).
    """
    if now_kst is None:
        now_kst = datetime.now(KST)
    return to_kst(computed_at).date() < now_kst.date()
