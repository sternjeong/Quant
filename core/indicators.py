"""기술적 지표 계산 유틸 (모듈 A 백테스팅 엔진에서 사용).

`ta` 패키지(requirements.txt에 이미 포함)를 활용해 RSI/볼린저밴드를 계산하고,
이동평균은 pandas rolling으로 직접 계산한다.

모든 함수는 OHLCV DataFrame(core.market_data.get_price_history 반환 형식,
"Close" 컬럼 포함)을 입력으로 받아 pandas Series/DataFrame을 반환한다.
전략 엔진(core/strategy_engine.py)이 이 함수들을 조합해서 사용한다.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands
from ta.volume import MFIIndicator


def sma(close: pd.Series, window: int) -> pd.Series:
    """단순이동평균."""
    return close.rolling(window=window, min_periods=window).mean()


def ema(close: pd.Series, window: int) -> pd.Series:
    """지수이동평균."""
    return close.ewm(span=window, adjust=False, min_periods=window).mean()


def roc(close: pd.Series, window: int) -> pd.Series:
    """변화율(Rate of Change, %). window 거래일 전 대비 현재 종가의 변화율."""
    return (close / close.shift(window) - 1) * 100


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


def compute_bbw(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    """볼린저 밴드폭(Band Width) = (상단-하단)/중심선.

    변동성이 줄어들수록(스퀴즈 구간) 값이 작아지고, 변동성이 커지면(추세 시작) 값이 커진다.
    """
    bb = compute_bollinger(df, period=period, std_dev=std_dev)
    return (bb["upper"] - bb["lower"]) / bb["mid"]


def compute_percent_b(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    """볼린저 밴드 %B = (종가-하단)/(상단-하단). 1 이상이면 상단 밖, 0 이하면 하단 밖에 위치."""
    bb = compute_bollinger(df, period=period, std_dev=std_dev)
    return (df["Close"] - bb["lower"]) / (bb["upper"] - bb["lower"])


def compute_mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """MFI(자금흐름지수) — 거래량을 반영한 RSI 격 모멘텀 지표. 80 이상 과매수/20 이하 과매도로 본다."""
    return MFIIndicator(
        high=df["High"], low=df["Low"], close=df["Close"], volume=df["Volume"], window=period
    ).money_flow_index()


def compute_bbw_squeeze_release(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    threshold: float = 0.1,
    lookback: int = 20,
    hold_bars: int = 3,
) -> pd.Series:
    """볼린저 밴드폭 스퀴즈 해제 이벤트.

    최근 lookback봉(오늘 이전) 안에 밴드폭이 threshold 아래로 내려간 적이 있고, 오늘 밴드폭이
    threshold를 상향 돌파하면 이벤트가 뜬다. threshold는 종목/시간대마다 다르다고 알려져 있어(원본
    설명 기준 경험적으로 정해야 함) 튜닝 가능한 파라미터로 노출한다(core.strategy_tuning의 숫자
    파라미터 자동 탐색 대상). 돌파(밴드 이탈) 확인까지 며칠 걸릴 수 있어 hold_bars만큼 이벤트를
    유지한다(그 사이 다른 조건과 같은 바 AND 결합이 가능하도록).
    """
    bbw = compute_bbw(df, period=period, std_dev=std_dev)
    was_squeezed = (bbw < threshold).shift(1).rolling(lookback, min_periods=1).max().astype(bool)
    crossed_up = (bbw >= threshold) & (bbw.shift(1) < threshold)
    release_event = (crossed_up & was_squeezed).fillna(False)
    return release_event.rolling(hold_bars, min_periods=1).max().astype(bool).fillna(False)


def compute_lowest_low(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """최근 period봉 중 최저 저가 (직전 저점 근사 — 손절 레벨 산출용)."""
    return df["Low"].rolling(window=period, min_periods=period).min()


def compute_highest_high(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """최근 period봉 중 최고 고가 (직전 고점 근사 — 손절 레벨 산출용)."""
    return df["High"].rolling(window=period, min_periods=period).max()


def _is_pivot_low(series: pd.Series, lookback: int) -> pd.Series:
    """좌우 lookback봉보다 낮은 저점(스윙 로우) 여부. 중심 윈도우라 lookback봉 뒤에야 '확정'된다."""
    win = 2 * lookback + 1
    return (series == series.rolling(win, center=True, min_periods=win).min()).fillna(False)


def _is_pivot_high(series: pd.Series, lookback: int) -> pd.Series:
    """좌우 lookback봉보다 높은 고점(스윙 하이) 여부. 중심 윈도우라 lookback봉 뒤에야 '확정'된다."""
    win = 2 * lookback + 1
    return (series == series.rolling(win, center=True, min_periods=win).max()).fillna(False)


def compute_double_pattern(
    df: pd.DataFrame,
    band_period: int = 20,
    band_std: float = 2.0,
    pivot_lookback: int = 5,
    pattern_window: int = 40,
    volume_mult: float = 1.5,
) -> pd.DataFrame:
    """쌍바닥(bullish)/쌍봉(bearish) 추세 반전 패턴 이벤트.

    쌍바닥: 첫 번째 저점이 볼린저 하단 밴드 밖에서 형성되고, 그 뒤 pattern_window봉 이내에 두 번째
    저점이 하단 밴드 안에서 형성되면 패턴이 "준비"된 상태가 된다. 그 이후 종가가 중심선을 상향
    돌파하면서(진입 확인) 거래량이 최근 평균 대비 volume_mult배 이상 급증한 바에서 이벤트가 뜬다.
    쌍봉은 방향만 반대인 대칭 로직. 스윙 저점/고점은 좌우 pivot_lookback봉보다 낮/높아야 확정되므로,
    확정 시점은 실제 저점/고점보다 pivot_lookback봉 뒤다(미래 데이터를 앞당겨 쓰지 않기 위함).

    Returns:
        원본 인덱스를 유지한 DataFrame with columns: bullish(bool), bearish(bool)
    """
    high, low, close, volume = df["High"], df["Low"], df["Close"], df["Volume"]
    bb = compute_bollinger(df, period=band_period, std_dev=band_std)
    lower, upper, mid = bb["lower"], bb["upper"], bb["mid"]
    avg_volume = volume.rolling(band_period).mean()

    is_low_pivot = _is_pivot_low(low, pivot_lookback)
    is_high_pivot = _is_pivot_high(high, pivot_lookback)

    n = len(df)
    idx = df.index
    bullish = pd.Series(False, index=idx)
    bearish = pd.Series(False, index=idx)

    last_low_pivot: Optional[int] = None
    last_high_pivot: Optional[int] = None
    bullish_ready_until = -1
    bearish_ready_until = -1

    low_v, lower_v, mid_v, close_v = low.to_numpy(), lower.to_numpy(), mid.to_numpy(), close.to_numpy()
    high_v, upper_v, vol_v, avgvol_v = high.to_numpy(), upper.to_numpy(), volume.to_numpy(), avg_volume.to_numpy()
    is_low_v, is_high_v = is_low_pivot.to_numpy(), is_high_pivot.to_numpy()
    bullish_v, bearish_v = bullish.to_numpy(), bearish.to_numpy()

    for i in range(n):
        confirm_idx = i - pivot_lookback
        if confirm_idx < 0:
            continue
        if is_low_v[confirm_idx]:
            if (
                last_low_pivot is not None
                and 0 < confirm_idx - last_low_pivot <= pattern_window
                and low_v[last_low_pivot] < lower_v[last_low_pivot]
                and low_v[confirm_idx] >= lower_v[confirm_idx]
            ):
                bullish_ready_until = i + pattern_window
            last_low_pivot = confirm_idx
        if is_high_v[confirm_idx]:
            if (
                last_high_pivot is not None
                and 0 < confirm_idx - last_high_pivot <= pattern_window
                and high_v[last_high_pivot] > upper_v[last_high_pivot]
                and high_v[confirm_idx] <= upper_v[confirm_idx]
            ):
                bearish_ready_until = i + pattern_window
            last_high_pivot = confirm_idx

        if i > 0 and i <= bullish_ready_until:
            if close_v[i] > mid_v[i] and close_v[i - 1] <= mid_v[i - 1] and vol_v[i] >= volume_mult * avgvol_v[i]:
                bullish_v[i] = True
                bullish_ready_until = -1
        if i > 0 and i <= bearish_ready_until:
            if close_v[i] < mid_v[i] and close_v[i - 1] >= mid_v[i - 1] and vol_v[i] >= volume_mult * avgvol_v[i]:
                bearish_v[i] = True
                bearish_ready_until = -1

    return pd.DataFrame({"bullish": bullish_v, "bearish": bearish_v}, index=idx)


def compute_rsi_divergence(
    df: pd.DataFrame,
    rsi_period: int = 14,
    band_period: int = 20,
    pivot_lookback: int = 5,
    pattern_window: int = 40,
) -> pd.DataFrame:
    """가격-RSI 다이버전스 추세 반전 패턴 이벤트.

    상승 다이버전스(bullish): 가격 저점은 낮아지는데(전 저점보다 낮음) RSI 저점은 높아짐(전 저점보다
    높음) — 하락 추세의 힘이 빠지고 있다는 신호. 그 뒤 pattern_window봉 이내에 종가가 중심선(SMA)을
    상향 돌파하는 바에서 이벤트가 뜬다. 하락 다이버전스(bearish)는 고점 기준 대칭 로직.
    """
    close, low, high = df["Close"], df["Low"], df["High"]
    rsi = compute_rsi(df, period=rsi_period)
    mid = sma(close, band_period)

    is_low_pivot = _is_pivot_low(low, pivot_lookback)
    is_high_pivot = _is_pivot_high(high, pivot_lookback)

    n = len(df)
    idx = df.index
    bullish = pd.Series(False, index=idx)
    bearish = pd.Series(False, index=idx)

    last_low_pivot: Optional[int] = None
    last_high_pivot: Optional[int] = None
    bullish_ready_until = -1
    bearish_ready_until = -1

    low_v, high_v, rsi_v, close_v, mid_v = (
        low.to_numpy(),
        high.to_numpy(),
        rsi.to_numpy(),
        close.to_numpy(),
        mid.to_numpy(),
    )
    is_low_v, is_high_v = is_low_pivot.to_numpy(), is_high_pivot.to_numpy()
    bullish_v, bearish_v = bullish.to_numpy(), bearish.to_numpy()

    for i in range(n):
        confirm_idx = i - pivot_lookback
        if confirm_idx < 0:
            continue
        if is_low_v[confirm_idx]:
            if (
                last_low_pivot is not None
                and 0 < confirm_idx - last_low_pivot <= pattern_window
                and low_v[confirm_idx] < low_v[last_low_pivot]
                and rsi_v[confirm_idx] > rsi_v[last_low_pivot]
            ):
                bullish_ready_until = i + pattern_window
            last_low_pivot = confirm_idx
        if is_high_v[confirm_idx]:
            if (
                last_high_pivot is not None
                and 0 < confirm_idx - last_high_pivot <= pattern_window
                and high_v[confirm_idx] > high_v[last_high_pivot]
                and rsi_v[confirm_idx] < rsi_v[last_high_pivot]
            ):
                bearish_ready_until = i + pattern_window
            last_high_pivot = confirm_idx

        if i > 0 and i <= bullish_ready_until:
            if close_v[i] > mid_v[i] and close_v[i - 1] <= mid_v[i - 1]:
                bullish_v[i] = True
                bullish_ready_until = -1
        if i > 0 and i <= bearish_ready_until:
            if close_v[i] < mid_v[i] and close_v[i - 1] >= mid_v[i - 1]:
                bearish_v[i] = True
                bearish_ready_until = -1

    return pd.DataFrame({"bullish": bullish_v, "bearish": bearish_v}, index=idx)


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


def _candle_geometry(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """캔들 하나의 몸통/전체범위/위꼬리/아래꼬리를 계산한다 (캔들 패턴 함수들의 공용 기하 계산).

    range(고가-저가)가 0인 바(시가=고가=저가=종가)는 몸통 비율 계산 시 0으로 나누지 않도록 NaN으로
    둔다 — 이후 비교 연산에서 자연히 False 취급된다.
    """
    open_, high, low, close = df["Open"], df["High"], df["Low"], df["Close"]
    body = (close - open_).abs()
    rng = (high - low)
    rng = rng.where(rng != 0)
    upper_wick = high - pd.concat([open_, close], axis=1).max(axis=1)
    lower_wick = pd.concat([open_, close], axis=1).min(axis=1) - low
    return body, rng, upper_wick, lower_wick


def compute_marubozu(df: pd.DataFrame, body_ratio_threshold: float = 0.9) -> pd.DataFrame:
    """마루보즈(장대양봉/장대음봉) 캔들: 몸통이 전체 범위의 대부분을 차지하고 꼬리가 거의 없는 캔들.

    강력한 단방향 매수세(bullish)/매도세(bearish)를 나타낸다. 추세 중간에 나오면 추세 지속,
    과매수/과매도 구간에서 나오면 추세 반전, 지지/저항선 돌파와 함께 나오면 새 추세 시작 신호로
    해석된다 (해석은 전략/조합 조건의 몫 — 이 함수는 캔들 형태 판정만 한다).
    """
    open_, close = df["Open"], df["Close"]
    body, rng, _, _ = _candle_geometry(df)
    strong_body = (body / rng >= body_ratio_threshold).fillna(False)
    bullish = strong_body & (close > open_)
    bearish = strong_body & (close < open_)
    return pd.DataFrame({"bullish": bullish, "bearish": bearish}, index=df.index)


def compute_pin_bar(
    df: pd.DataFrame, body_ratio_max: float = 0.3, wick_body_mult: float = 2.0
) -> pd.DataFrame:
    """핀바 캔들: 몸통이 짧고 한쪽 꼬리만 긴 캔들 — 강력한 반전 신호.

    강세 핀바: 몸통이 짧고(body/range <= body_ratio_max) 아래꼬리가 몸통의 wick_body_mult배 이상
    길며 위꼬리는 몸통 이하. 약세 핀바는 대칭(위꼬리가 길고 아래꼬리는 짧음).
    """
    body, rng, upper_wick, lower_wick = _candle_geometry(df)
    small_body = (body / rng <= body_ratio_max).fillna(False)
    bullish = small_body & (lower_wick >= wick_body_mult * body) & (upper_wick <= body)
    bearish = small_body & (upper_wick >= wick_body_mult * body) & (lower_wick <= body)
    return pd.DataFrame({"bullish": bullish.fillna(False), "bearish": bearish.fillna(False)}, index=df.index)


def compute_doji(
    df: pd.DataFrame,
    body_ratio_max: float = 0.1,
    long_wick_ratio: float = 0.3,
    extreme_wick_ratio: float = 0.6,
    short_wick_ratio: float = 0.1,
) -> pd.DataFrame:
    """도지 캔들 4종: 일반(standard)/키다리형(long_legged)/잠자리형(dragonfly)/비석형(gravestone).

    시가와 종가가 거의 같아(몸통/범위 <= body_ratio_max) 매수/매도 세력이 균형을 이루는 캔들.
    잠자리형(아래꼬리만 김)이 하락 추세 저점에서, 비석형(위꼬리만 김)이 상승 추세 고점에서 나오면
    추세 반전 신호로 신뢰도가 가장 높고, 키다리형(양쪽 다 김)/일반 순으로 신뢰도가 낮아진다.

    Returns:
        원본 인덱스를 유지한 DataFrame with columns: standard, long_legged, dragonfly, gravestone (bool)
    """
    body, rng, upper_wick, lower_wick = _candle_geometry(df)
    upper_ratio, lower_ratio = upper_wick / rng, lower_wick / rng
    is_doji = (body / rng <= body_ratio_max).fillna(False)

    dragonfly = (
        is_doji & (lower_ratio >= extreme_wick_ratio).fillna(False) & (upper_ratio <= short_wick_ratio).fillna(False)
    )
    gravestone = (
        is_doji & (upper_ratio >= extreme_wick_ratio).fillna(False) & (lower_ratio <= short_wick_ratio).fillna(False)
    )
    long_legged = (
        is_doji
        & (upper_ratio >= long_wick_ratio).fillna(False)
        & (lower_ratio >= long_wick_ratio).fillna(False)
        & ~dragonfly
        & ~gravestone
    )
    standard = is_doji & ~dragonfly & ~gravestone & ~long_legged
    return pd.DataFrame(
        {"standard": standard, "long_legged": long_legged, "dragonfly": dragonfly, "gravestone": gravestone},
        index=df.index,
    )


def compute_inside_bar(df: pd.DataFrame) -> pd.Series:
    """인사이드바: 당일 고가/저가가 직전 캔들("마더 바")의 범위 안에 완전히 포함되는 캔들.

    추세 지속형 패턴으로, 돌파 방향(마더 바 고점/저점 이탈)이 이후 방향을 결정한다 — 방향 판정은
    별도 조건(예: level_break)과 조합해서 표현한다.
    """
    high, low = df["High"], df["Low"]
    inside = (high <= high.shift(1)) & (low >= low.shift(1))
    return inside.fillna(False)


def compute_inside_bar_breakout(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """인사이드바 돌파: 인사이드바 출현 후 lookback봉 이내에 마더 바(인사이드바 직전 캔들)의
    고점/저점을 종가가 돌파하는 이벤트. bullish=마더 바 고점 상향 돌파, bearish=마더 바 저점 하향 이탈
    (표준 인사이드바 매매법 — 방향이 없는 compute_inside_bar와 달리 돌파 방향까지 판정된 상태다).
    """
    high, low, close = df["High"], df["Low"], df["Close"]
    inside = compute_inside_bar(df)
    mother_high, mother_low = high.shift(1), low.shift(1)

    n = len(df)
    idx = df.index
    inside_v, mh_v, ml_v, close_v = inside.to_numpy(), mother_high.to_numpy(), mother_low.to_numpy(), close.to_numpy()
    bull_v = [False] * n
    bear_v = [False] * n

    ready_until = -1
    ready_high = float("nan")
    ready_low = float("nan")
    for i in range(n):
        if inside_v[i]:
            ready_until = i + lookback
            ready_high = mh_v[i]
            ready_low = ml_v[i]
        if i <= ready_until:
            if close_v[i] > ready_high:
                bull_v[i] = True
                ready_until = -1
            elif close_v[i] < ready_low:
                bear_v[i] = True
                ready_until = -1

    return pd.DataFrame({"bullish": bull_v, "bearish": bear_v}, index=idx)


def compute_piercing_dark_cloud(
    df: pd.DataFrame, band_period: int = 20, band_std: float = 2.0
) -> pd.DataFrame:
    """관통형 캔들 패턴: 상승 관통형(피어싱, bullish)/하락 관통형(흑운형·다크클라우드, bearish).

    전일 몸통 중간값(prev_mid)보다 더 파고들어 마감하지만, 전일 몸통을 완전히 감싸지는 않는(장악형과
    구분되는 지점) 2봉 반전 패턴. 실전 신뢰도를 높이기 위해 볼린저 밴드 이탈→복귀 확인까지 지표 안에서
    함께 판정한다: 상승 관통형은 당일 저가가 하단 밴드 아래로 뚫었다가 종가는 하단 밴드 위로 복귀,
    하락 관통형은 대칭적으로 상단 밴드 기준.
    """
    open_, high, low, close = df["Open"], df["High"], df["Low"], df["Close"]
    prev_open, prev_close = open_.shift(1), close.shift(1)
    prev_mid = (prev_open + prev_close) / 2
    prev_bearish = prev_close < prev_open
    prev_bullish = prev_close > prev_open

    bb = compute_bollinger(df, period=band_period, std_dev=band_std)

    bullish = (
        prev_bearish
        & (close > open_)
        & (open_ < prev_close)
        & (close > prev_mid)
        & (close < prev_open)
        & (low < bb["lower"])
        & (close > bb["lower"])
    )
    bearish = (
        prev_bullish
        & (close < open_)
        & (open_ > prev_close)
        & (close < prev_mid)
        & (close > prev_open)
        & (high > bb["upper"])
        & (close < bb["upper"])
    )
    return pd.DataFrame({"bullish": bullish.fillna(False), "bearish": bearish.fillna(False)}, index=df.index)


def compute_star_pattern(
    df: pd.DataFrame, star_body_ratio_max: float = 0.3, big_body_ratio_min: float = 0.5
) -> pd.DataFrame:
    """모닝스타(bullish)/이브닝스타(bearish): 3봉 반전 패턴.

    모닝스타: 몸통 큰 음봉(1번) -> 몸통이 작은 별(2번, 1번 몸통 아래/위로 갭) -> 몸통 큰 양봉(3번,
    1번 몸통 중간값 이상에서 마감). 1번-3번 몸통 크기가 비슷할수록, 3번이 1번의 고점 위에서 마감할수록
    신뢰도가 높다(신뢰도 가중치는 전략 몫 — 이 함수는 최소 성립 조건만 판정). 이브닝스타는 대칭.
    """
    open_, close = df["Open"], df["Close"]
    body, rng, _, _ = _candle_geometry(df)
    body_ratio = body / rng

    c1_open, c1_close, c1_body_ratio = open_.shift(2), close.shift(2), body_ratio.shift(2)
    c2_open, c2_close, c2_body_ratio = open_.shift(1), close.shift(1), body_ratio.shift(1)
    c1_mid = (c1_open + c1_close) / 2

    star_small = (c2_body_ratio <= star_body_ratio_max).fillna(False)
    c1_big_bear = (c1_close < c1_open) & (c1_body_ratio >= big_body_ratio_min).fillna(False)
    c1_big_bull = (c1_close > c1_open) & (c1_body_ratio >= big_body_ratio_min).fillna(False)
    c3_big_bull = (close > open_) & (body_ratio >= big_body_ratio_min).fillna(False)
    c3_big_bear = (close < open_) & (body_ratio >= big_body_ratio_min).fillna(False)

    gapped_down = pd.concat([c2_open, c2_close], axis=1).max(axis=1) < c1_close
    gapped_up = pd.concat([c2_open, c2_close], axis=1).min(axis=1) > c1_close

    bullish = c1_big_bear & star_small & gapped_down & c3_big_bull & (close > c1_mid)
    bearish = c1_big_bull & star_small & gapped_up & c3_big_bear & (close < c1_mid)
    return pd.DataFrame({"bullish": bullish.fillna(False), "bearish": bearish.fillna(False)}, index=df.index)


def compute_three_soldiers_crows(df: pd.DataFrame, body_ratio_min: float = 0.6) -> pd.DataFrame:
    """적삼병(bullish)/흑삼병(bearish): 몸통이 큰 같은 방향 캔들 3개가 연속으로 진행되는 추세 패턴.

    각 캔들의 시가가 직전 캔들 몸통 안에서 시작하고, 종가가 매번 직전보다 더 멀리(적삼병=더 높게,
    흑삼병=더 낮게) 진행되어야 한다.
    """
    open_, close = df["Open"], df["Close"]
    body, rng, _, _ = _candle_geometry(df)
    strong = (body / rng >= body_ratio_min).fillna(False)

    o1, c1, s1 = open_.shift(2), close.shift(2), strong.shift(2, fill_value=False)
    o2, c2, s2 = open_.shift(1), close.shift(1), strong.shift(1, fill_value=False)
    o3, c3, s3 = open_, close, strong

    bullish = (
        s1 & s2 & s3
        & (c1 > o1) & (c2 > o2) & (c3 > o3)
        & (c2 > c1) & (c3 > c2)
        & (o2 > o1) & (o2 < c1)
        & (o3 > o2) & (o3 < c2)
    )
    bearish = (
        s1 & s2 & s3
        & (c1 < o1) & (c2 < o2) & (c3 < o3)
        & (c2 < c1) & (c3 < c2)
        & (o2 < o1) & (o2 > c1)
        & (o3 < o2) & (o3 > c2)
    )
    return pd.DataFrame({"bullish": bullish.fillna(False), "bearish": bearish.fillna(False)}, index=df.index)


def compute_rising_falling_three_methods(
    df: pd.DataFrame, n_pause: int = 3, big_body_ratio_min: float = 0.5
) -> pd.DataFrame:
    """상승/하락 삼법형: 추세 지속형 패턴.

    큰 캔들 하나(0번) -> 그 범위(고가~저가) 안에 완전히 갇힌 조정 캔들 n_pause개 -> 원래 방향으로
    0번 종가를 갱신하며 마감하는 마무리 큰 캔들, 총 (n_pause+2)개의 캔들로 구성된다.
    """
    open_, high, low, close = df["Open"], df["High"], df["Low"], df["Close"]
    body, rng, _, _ = _candle_geometry(df)
    body_ratio = body / rng

    first_shift = n_pause + 1
    c0_open, c0_high, c0_low, c0_close = (
        open_.shift(first_shift),
        high.shift(first_shift),
        low.shift(first_shift),
        close.shift(first_shift),
    )
    c0_body_ratio = body_ratio.shift(first_shift)
    c0_big_bull = (c0_close > c0_open) & (c0_body_ratio >= big_body_ratio_min).fillna(False)
    c0_big_bear = (c0_close < c0_open) & (c0_body_ratio >= big_body_ratio_min).fillna(False)

    contained = pd.Series(True, index=df.index)
    for shift in range(1, n_pause + 1):
        contained = contained & (high.shift(shift) <= c0_high) & (low.shift(shift) >= c0_low)
    contained = contained.fillna(False)

    last_big_bull = (close > open_) & (body_ratio >= big_body_ratio_min).fillna(False)
    last_big_bear = (close < open_) & (body_ratio >= big_body_ratio_min).fillna(False)

    bullish = c0_big_bull & contained & last_big_bull & (close > c0_close)
    bearish = c0_big_bear & contained & last_big_bear & (close < c0_close)
    return pd.DataFrame({"bullish": bullish.fillna(False), "bearish": bearish.fillna(False)}, index=df.index)


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


def compute_volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """당일 거래량을 직전 period일(당일 제외) 평균 거래량으로 나눈 배수.

    "거래량이 최근 평균 대비 몇 배 터졌는지"를 재는 지표 — 여러 유튜브 차트분석 강의(2026-07-16
    거래량 매매법 3영상)에서 공통으로 강조하는 "매집/주도세력 진입" 국면(장대양봉+거래량 급증)을
    판별하는 데 쓴다. 당일 거래량이 그 평균 계산에 섞이지 않도록 shift(1) 후 rolling한다(당일 거래량
    자체가 급증의 대상이므로, 그 값이 자기 자신을 포함한 평균에 섞이면 배수가 실제보다 과소평가된다).
    """
    volume = df["Volume"]
    avg_volume = volume.shift(1).rolling(window=period, min_periods=period).mean()
    return volume / avg_volume


def compute_volume_dryup_ratio(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """당일 거래량을 직전 lookback일(당일 제외) 중 최고 거래량으로 나눈 비율.

    1.0에 가까울수록 아직 최근 거래량 고점(대개 매집/급등 국면) 수준이 유지되고 있다는 뜻이고,
    0에 가까울수록 그 이후 거래대금이 크게 말라붙었다는 뜻이다. 거래량 매매법 영상들이 공통으로
    강조하는 "눌림목 구간에서 거래량이 확 줄면(=팔 사람이 다 팔았으면) 매물 소화가 끝난 것"이라는
    판단 근거를 수치화한다.
    """
    volume = df["Volume"]
    recent_peak = volume.shift(1).rolling(window=lookback, min_periods=lookback).max()
    return volume / recent_peak
