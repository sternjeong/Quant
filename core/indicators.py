"""기술적 지표 계산 유틸 (모듈 A 백테스팅 엔진에서 사용).

`ta` 패키지(requirements.txt에 이미 포함)를 활용해 RSI/볼린저밴드를 계산하고,
이동평균은 pandas rolling으로 직접 계산한다.

모든 함수는 OHLCV DataFrame(core.market_data.get_price_history 반환 형식,
"Close" 컬럼 포함)을 입력으로 받아 pandas Series/DataFrame을 반환한다.
전략 엔진(core/strategy_engine.py)이 이 함수들을 조합해서 사용한다.
"""

from __future__ import annotations

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands


def sma(close: pd.Series, window: int) -> pd.Series:
    """단순이동평균."""
    return close.rolling(window=window, min_periods=window).mean()


def ema(close: pd.Series, window: int) -> pd.Series:
    """지수이동평균."""
    return close.ewm(span=window, adjust=False, min_periods=window).mean()


def compute_ma_cross(df: pd.DataFrame, short: int, long: int, ma_type: str = "sma") -> pd.DataFrame:
    """단기/장기 이동평균과 골든/데드 크로스 여부를 계산한다.

    Args:
        df: "Close" 컬럼을 가진 OHLCV DataFrame
        short: 단기 이동평균 기간
        long: 장기 이동평균 기간
        ma_type: "sma" 또는 "ema"

    Returns:
        원본 인덱스를 유지한 DataFrame with columns:
            short_ma, long_ma, golden(bool, short_ma > long_ma),
            cross_up(bool, 이번 바에서 골든크로스 발생), cross_down(bool, 데드크로스 발생)
    """
    close = df["Close"]
    fn = ema if ma_type == "ema" else sma
    short_ma = fn(close, short)
    long_ma = fn(close, long)
    golden = short_ma > long_ma
    prev_golden = golden.shift(1, fill_value=False)
    cross_up = golden & (~prev_golden)
    cross_down = (~golden) & prev_golden

    return pd.DataFrame(
        {
            "short_ma": short_ma,
            "long_ma": long_ma,
            "golden": golden,
            "cross_up": cross_up,
            "cross_down": cross_down,
        },
        index=df.index,
    )


def compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI(상대강도지수)를 계산한다."""
    close = df["Close"]
    return RSIIndicator(close=close, window=period).rsi()


def compute_bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """볼린저밴드(상단/중단/하단)를 계산한다.

    Returns:
        DataFrame with columns: mid, upper, lower
    """
    close = df["Close"]
    bb = BollingerBands(close=close, window=period, window_dev=std_dev)
    return pd.DataFrame(
        {
            "mid": bb.bollinger_mavg(),
            "upper": bb.bollinger_hband(),
            "lower": bb.bollinger_lband(),
        },
        index=df.index,
    )


def compute_macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """MACD(이동평균수렴확산)을 계산한다.

    Returns:
        DataFrame with columns: macd(MACD선), signal(시그널선), hist(히스토그램 = macd - signal)
    """
    close = df["Close"]
    macd_ind = MACD(close=close, window_fast=fast, window_slow=slow, window_sign=signal)
    return pd.DataFrame(
        {
            "macd": macd_ind.macd(),
            "signal": macd_ind.macd_signal(),
            "hist": macd_ind.macd_diff(),
        },
        index=df.index,
    )


def compute_engulfing(df: pd.DataFrame) -> pd.DataFrame:
    """상승/하락 인걸(장악형) 캔들 패턴을 계산한다.

    상승 인걸: 전일이 음봉이고 당일이 양봉이며, 당일 몸통(시가~종가)이 전일 몸통을 완전히 감싼다
    (당일 시가 <= 전일 종가, 당일 종가 >= 전일 시가). 하락 인걸은 그 반대.
    캔들 두 개로 완성되는 1회성 "이벤트"이므로, 패턴이 완성된 그 바에서만 True다.

    Returns:
        원본 인덱스를 유지한 DataFrame with columns: bullish(bool), bearish(bool)
    """
    open_, close = df["Open"], df["Close"]
    prev_open, prev_close = open_.shift(1), close.shift(1)

    prev_bearish = prev_close < prev_open
    curr_bullish = close > open_
    bullish = prev_bearish & curr_bullish & (open_ <= prev_close) & (close >= prev_open)

    prev_bullish = prev_close > prev_open
    curr_bearish = close < open_
    bearish = prev_bullish & curr_bearish & (open_ >= prev_close) & (close <= prev_open)

    return pd.DataFrame(
        {"bullish": bullish.fillna(False), "bearish": bearish.fillna(False)},
        index=df.index,
    )


def compute_ichimoku(
    df: pd.DataFrame,
    tenkan_len: int = 9,
    kijun_len: int = 26,
    span_b_len: int = 52,
    displacement: int = 26,
) -> pd.DataFrame:
    """일목균형표(Ichimoku Cloud)를 계산한다.

    전환선(tenkan)/기준선(kijun)은 (최고가+최저가)/2 의 n기간 중간값(donchian mid) 방식으로 계산한다.
    선행스팬A/B는 원래 계산 시점 기준 displacement 만큼 "미래" 캔들 위치에 그려지는 것이 일반적인
    차트 관례다. 즉 오늘(T) 화면에 표시되는 구름대는 T-displacement 시점의 tenkan/kijun/선행스팬B로
    계산된 값이다. 이를 반영해 반환되는 cloud_top/cloud_bottom은 df.index와 동일한 타임라인에서
    "오늘 종가와 바로 비교 가능한" 값이 되도록 raw 계산값을 displacement 만큼 뒤(미래)로 shift 해서
    정렬한다 (전략 엔진이 별도 이동 없이 그대로 종가와 비교할 수 있게 하기 위함).

    Returns:
        DataFrame with columns: tenkan, kijun, cloud_top, cloud_bottom, chikou_ref
        (chikou_ref = displacement 만큼 이전 종가. 후행스팬 판정에 사용)
    """
    high, low, close = df["High"], df["Low"], df["Close"]

    def _donchian_mid(length: int) -> pd.Series:
        return (high.rolling(length).max() + low.rolling(length).min()) / 2

    tenkan = _donchian_mid(tenkan_len)
    kijun = _donchian_mid(kijun_len)
    span_a = ((tenkan + kijun) / 2).shift(displacement)
    span_b = _donchian_mid(span_b_len).shift(displacement)
    cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    cloud_bottom = pd.concat([span_a, span_b], axis=1).min(axis=1)
    chikou_ref = close.shift(displacement)

    return pd.DataFrame(
        {
            "tenkan": tenkan,
            "kijun": kijun,
            "span_a": span_a,
            "span_b": span_b,
            "cloud_top": cloud_top,
            "cloud_bottom": cloud_bottom,
            "chikou_ref": chikou_ref,
        },
        index=df.index,
    )
