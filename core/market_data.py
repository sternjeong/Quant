"""yfinance 기반 시장 데이터 fetch 유틸 (파일 캐싱 래퍼).

core 패키지는 Streamlit에 의존하지 않으므로(스케줄러 스크립트에서도 사용) st.cache_data
대신 data/cache/ 아래에 CSV로 결과를 캐싱하는 자체 캐시를 사용한다.
Streamlit 페이지에서 반복 호출로 인한 재계산이 신경 쓰이면, 각 페이지에서 이 함수를
@st.cache_data 로 한 번 더 감싸서 써도 무방하다 (아래 예시 참고).

    import streamlit as st
    from core.market_data import get_price_history

    @st.cache_data(ttl=3600)
    def _cached_price_history(ticker, start, end, interval="1d"):
        return get_price_history(ticker, start, end, interval)
"""

import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 캐시 유효 시간(초). 미국 장은 하루 1번 마감 후 스캔하는 용도이므로 넉넉하게 잡는다.
DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6시간

# yfinance가 interval별로 과거 조회를 허용하는 최대 기간(일). None이면 제한 없음(일봉 이상).
# (Yahoo Finance 쪽 제약이며 yfinance 공식 문서 기준. 실제 경계에서 종종 며칠 짧게 잘리는 경우가
# 있어 1m만 하루 여유를 뺐다.)
INTERVAL_MAX_LOOKBACK_DAYS: dict[str, Optional[int]] = {
    "1m": 6,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "60m": 730,
    "90m": 60,
    "1d": None,
    "5d": None,
    "1wk": None,
    "1mo": None,
    "3mo": None,
}


def clamp_start_for_interval(interval: str, start: date, end: date) -> tuple[date, bool]:
    """interval이 지원하는 최대 조회 기간을 벗어나면 start를 당겨서 보정한다.

    분봉/시간봉 등 짧은 interval은 yfinance가 최근 N일치만 제공하므로, UI에서
    사용자가 그보다 오래된 start를 고르더라도 여기서 자동으로 당겨준다.

    Returns:
        (보정된 start 날짜, 보정이 발생했는지 여부)
    """
    max_days = INTERVAL_MAX_LOOKBACK_DAYS.get(interval)
    if max_days is None:
        return start, False
    earliest_allowed = end - timedelta(days=max_days)
    if start < earliest_allowed:
        return earliest_allowed, True
    return start, False


def _cache_key(ticker: str, start: Optional[str], end: Optional[str], interval: str) -> Path:
    safe = f"{ticker}_{start}_{end}_{interval}".replace("/", "-").replace(":", "-")
    return CACHE_DIR / f"{safe}.csv"


def get_price_history(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    interval: str = "1d",
    use_cache: bool = True,
    cache_ttl: int = DEFAULT_CACHE_TTL_SECONDS,
) -> pd.DataFrame:
    """yfinance로 OHLCV 가격 데이터를 가져온다 (파일 캐시 적용).

    Args:
        ticker: 종목 티커 (예: "AAPL")
        start: 조회 시작일 "YYYY-MM-DD" (None이면 yfinance 기본 최대 기간)
        end: 조회 종료일 "YYYY-MM-DD" (None이면 오늘까지)
        interval: 캔들 주기 ("1d", "1wk", "1mo" 등, yfinance 지원값)
        use_cache: True면 data/cache/ 의 CSV 캐시를 읽고/쓴다
        cache_ttl: 캐시 유효 시간(초). 이보다 오래된 캐시는 새로 받아온다.

    Returns:
        DatetimeIndex(Date)와 Open/High/Low/Close/Adj Close/Volume 컬럼을 가진 DataFrame.
        데이터가 없으면 빈 DataFrame을 반환한다 (예외를 던지지 않음).
    """
    cache_file = _cache_key(ticker, start, end, interval)

    if use_cache and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < cache_ttl:
            try:
                return pd.read_csv(cache_file, index_col=0, parse_dates=True)
            except Exception:
                pass  # 캐시 파일이 손상된 경우 다시 받아온다

    df = yf.download(
        ticker,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=False,
        progress=False,
    )

    if df is None:
        df = pd.DataFrame()

    # yfinance가 멀티 티커 조회 형식(MultiIndex 컬럼)으로 반환하는 경우 평탄화
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.index.name = "Date"

    if use_cache and not df.empty:
        try:
            df.to_csv(cache_file)
        except Exception:
            pass  # 캐시 저장 실패는 무시 (조회 결과 반환은 정상 진행)

    return df


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """일봉 OHLCV를 주/월/분기 등 더 긴 봉으로 리샘플링한다.

    yfinance가 직접 제공하는 "1wk"/"1mo"/"3mo" 데이터는 일봉과 별도 피드라 최신 데이터 반영이
    하루 이상 늦어져 일봉과 날짜가 안 맞는 경우가 있다. 그 대신 항상 일봉을 받아 여기서 직접
    집계하면 어떤 봉 주기를 선택해도 같은 일봉 데이터에서 파생되어 항상 동기화된다.

    Open=구간 내 첫 거래일의 시가, High/Low=구간 내 최고/최저, Close=구간 내 마지막 거래일의 종가,
    Volume=구간 합계. 인덱스는 달력상 주/월/분기의 마지막 날이 아니라 그 구간의 실제 마지막 거래일로
    맞춘다 (주말/공휴일에 걸리면 실제로는 존재하지 않는 날짜가 라벨이 되는 것을 방지).

    Args:
        df: DatetimeIndex를 가진 일봉 OHLCV DataFrame.
        rule: pandas resample 규칙 ("W-FRI"=주봉/금요일 기준, "ME"=월봉, "QE"=분기봉 등).
    """
    if df.empty:
        return df
    agg_map = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    if "Adj Close" in df.columns:
        agg_map["Adj Close"] = "last"
    grouped = df.resample(rule)
    out = grouped.agg(agg_map).dropna(subset=["Open", "High", "Low", "Close"])
    real_dates = df.index.to_series().resample(rule).last().reindex(out.index)
    out.index = pd.DatetimeIndex(real_dates.values)
    out.index.name = "Date"
    return out


def get_latest_price(ticker: str) -> Optional[float]:
    """가장 최근 종가(Close)를 반환한다. 데이터가 없으면 None."""
    df = get_price_history(ticker, start=None, end=None, interval="1d", use_cache=True)
    if df is None or df.empty:
        return None
    return float(df["Close"].iloc[-1])


def get_multiple_price_history(
    tickers: list[str],
    start: Optional[str] = None,
    end: Optional[str] = None,
    interval: str = "1d",
    use_cache: bool = True,
) -> dict[str, pd.DataFrame]:
    """여러 티커의 가격 데이터를 한 번에 가져온다 (관심 티커 스캔 등에서 사용).

    Returns:
        {ticker: DataFrame} 딕셔너리. 개별 티커 조회 실패 시 해당 티커는 빈 DataFrame.
    """
    result: dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            result[t] = get_price_history(t, start=start, end=end, interval=interval, use_cache=use_cache)
        except Exception:
            result[t] = pd.DataFrame()
    return result


def clear_cache(ticker: Optional[str] = None) -> int:
    """캐시 파일을 삭제한다. ticker를 지정하면 해당 티커 캐시만, None이면 전체 삭제.

    Returns:
        삭제한 파일 개수.
    """
    count = 0
    pattern = f"{ticker}_*.csv" if ticker else "*.csv"
    for f in CACHE_DIR.glob(pattern):
        f.unlink()
        count += 1
    return count
