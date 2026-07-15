"""yfinance 기반 시장 데이터 fetch 유틸 (로컬 영구 저장소 기반 캐싱 래퍼).

core 패키지는 Streamlit에 의존하지 않으므로(스케줄러 스크립트에서도 사용) st.cache_data
대신 data/cache/ 아래에 (ticker, interval)별로 하나씩 Parquet 파일을 두고 "지금까지 받아온
전체 이력"을 계속 누적하는 자체 로컬 저장소를 사용한다. (start, end)가 정확히 같아야만
캐시가 맞아떨어지던 예전 방식과 달리, 요청 범위가 이미 저장된 범위 안에 있으면 조회 날짜가
달라도 네트워크 호출 없이 바로 응답하고, 저장된 범위를 벗어난 부분(더 과거로 확장되는 구간 /
아직 안 받은 최신 구간)만 델타로 받아와 이어붙인다. 이미 확정된 과거 봉은 다시 받아오지 않으므로,
백테스트/다종목 튜닝처럼 같은 과거 구간을 반복 조회하는 워크로드는 최초 1회 이후 완전히 로컬
데이터만으로 응답한다 (캐시 나이(cache_ttl)와 무관 — 과거 구간을 벗어나지 않는 요청은 절대
재다운로드하지 않는다. 아래 get_price_history() 참고).

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

# 저장된 범위가 이미 "오늘"까지 닿아 있을 때, 최신 구간(오늘자 봉 등)을 다시 확인하기까지
# 기다리는 시간(초). 명시적 end가 있는(=완전히 과거로 국한된) 요청은 이 값과 무관하게 저장된
# 데이터만으로 즉시 응답한다 — 확정된 과거 봉은 바뀌지 않기 때문.
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


def _store_path(ticker: str, interval: str) -> Path:
    safe = ticker.replace("/", "-").replace(":", "-")
    return CACHE_DIR / f"{safe}_{interval}.parquet"


def _full_history_marker(store_file: Path) -> Path:
    """store_file 옆에 두는 빈 마커 파일 경로. 존재하면 "start=None(전체 이력)"으로 이미 한 번
    받아봤다는 뜻이라, 이후로는 더 과거로 확장해서 받아올 필요가 없다(그게 실제 상장일 기준
    가장 이른 데이터이므로)."""
    return store_file.with_suffix(".full")


def _load_store(store_file: Path) -> pd.DataFrame:
    if not store_file.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(store_file)
        df.index = pd.DatetimeIndex(df.index)
        return df
    except Exception:
        return pd.DataFrame()  # 저장소 파일이 손상된 경우 처음부터 다시 받아온다


def _save_store(store_file: Path, df: pd.DataFrame) -> None:
    try:
        df.to_parquet(store_file)
    except Exception:
        pass  # 저장 실패는 무시 (조회 결과 반환은 정상 진행)


def _download(ticker: str, start: Optional[str], end: Optional[str], interval: str) -> pd.DataFrame:
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
    if not df.empty and getattr(df.index, "tz", None) is not None:
        # 분봉/시간봉은 tz-aware 인덱스로 오는 경우가 있는데, 로컬 저장소는 항상 tz-naive로
        # 통일해야 저장된 범위와 요청 범위를 안전하게 비교할 수 있다 (표시되는 날짜/시각 값 자체는
        # 그대로 유지되고 tz 라벨만 제거됨).
        df.index = df.index.tz_localize(None)

    return df


def _merge_price_data(*frames: pd.DataFrame) -> pd.DataFrame:
    """여러 구간의 OHLCV DataFrame을 하나로 합친다. 날짜가 겹치면 뒤에 온(더 최신에 받아온)
    프레임의 값으로 덮어쓴다 (수정종가 정정 등을 반영하기 위함)."""
    non_empty = [f for f in frames if f is not None and not f.empty]
    if not non_empty:
        return pd.DataFrame()
    combined = pd.concat(non_empty)
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


def get_price_history(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    interval: str = "1d",
    use_cache: bool = True,
    cache_ttl: int = DEFAULT_CACHE_TTL_SECONDS,
) -> pd.DataFrame:
    """yfinance로 OHLCV 가격 데이터를 가져온다 ((ticker, interval)별 로컬 영구 저장소 사용).

    처음 조회하는 (ticker, interval)이면 요청 범위를 그대로 받아와 저장한다. 이미 저장된 데이터가
    있으면: 요청 시작일이 저장된 범위보다 더 과거면 그 차이만큼만 앞쪽을 추가로 받아오고, 명시적
    end가 저장된 범위를 벗어나거나(아직 없는 구간) end가 없는(=오늘까지) 요청인데 저장 범위가
    부족하거나 캐시가 cache_ttl보다 오래됐으면 뒤쪽(델타)만 추가로 받아온다.

    명시적 end가 있고 그 범위가 이미 저장소 안에 있는 요청(예: 고정된 기간을 반복 조회하는
    백테스트/다종목 튜닝)은 캐시 나이와 무관하게 로컬 데이터만으로 즉시 응답하고 네트워크를
    타지 않는다 — 확정된 과거 봉은 바뀌지 않기 때문이다. "최신 구간"을 원하는 요청(end=None)만
    cache_ttl에 따라 주기적으로 다시 확인한다.

    Args:
        ticker: 종목 티커 (예: "AAPL")
        start: 조회 시작일 "YYYY-MM-DD" (None이면 상장일부터 전체 이력)
        end: 조회 종료일 "YYYY-MM-DD", yfinance 관례대로 배타적(해당 날짜 미포함) (None이면 오늘까지)
        interval: 캔들 주기 ("1d", "1wk", "1mo" 등, yfinance 지원값)
        use_cache: True면 로컬 저장소를 읽고/쓴다. False면 매번 yfinance에서 직접 받아오고
            저장소를 건드리지 않는다.
        cache_ttl: 최신 구간을 다시 확인하기까지의 유효 시간(초). 위 설명 참고.

    Returns:
        DatetimeIndex(Date)와 Open/High/Low/Close/Adj Close/Volume 컬럼을 가진 DataFrame.
        데이터가 없으면 빈 DataFrame을 반환한다 (예외를 던지지 않음).
    """
    if not use_cache:
        return _download(ticker, start, end, interval)

    store_file = _store_path(ticker, interval)
    full_marker = _full_history_marker(store_file)
    stored = _load_store(store_file)

    req_start = pd.Timestamp(start) if start else None
    updated = False

    need_older = (
        not stored.empty
        and not full_marker.exists()
        and (req_start is None or req_start < stored.index.min())
    )
    if need_older:
        older_end = (stored.index.min() - pd.Timedelta(1, unit="D")).strftime("%Y-%m-%d")
        older = _download(ticker, start=start, end=older_end, interval=interval)
        if not older.empty:
            stored = _merge_price_data(older, stored)
            updated = True
        if req_start is None:
            full_marker.touch()  # start=None으로 받아봤으니 이게 진짜 전체 이력의 시작

    if stored.empty:
        need_tail = True
    elif end is not None:
        # 명시적(배타적) end 요청: 이미 그 범위를 커버하면(1일 버퍼로 yfinance의 end-배타 관례를
        # 맞춤) 과거 데이터이므로 캐시 나이와 무관하게 네트워크 불필요. 커버 못하면 무조건 받아옴.
        need_tail = pd.Timestamp(end) > stored.index.max() + pd.Timedelta(1, unit="D")
    else:
        # end=None(오늘까지): 저장 범위가 오늘에 못 미치면 무조건, 닿아 있어도 캐시가 오래됐으면
        # 한 번 더 확인한다.
        is_stale = (not store_file.exists()) or (time.time() - store_file.stat().st_mtime >= cache_ttl)
        need_tail = (pd.Timestamp(date.today()) > stored.index.max()) or is_stale

    if need_tail:
        tail_start = start if stored.empty else stored.index.max().strftime("%Y-%m-%d")
        fresh = _download(ticker, start=tail_start, end=end, interval=interval)
        if not fresh.empty:
            stored = _merge_price_data(stored, fresh)
            updated = True

    if stored.empty:
        return pd.DataFrame()

    if updated:
        _save_store(store_file, stored)

    result = stored
    if req_start is not None:
        result = result[result.index >= req_start]
    if end is not None:
        result = result[result.index < pd.Timestamp(end)]  # yfinance와 동일하게 end는 배타적
    return result.copy()


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
    """여러 티커의 가격 데이터를 한 번에 가져온다 (관심 티커 스캔, 다종목 백테스트 등에서 사용).

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
    """로컬 가격 저장소 파일을 삭제한다. ticker를 지정하면 해당 티커(전체 interval)만,
    None이면 전체 삭제.

    Returns:
        삭제한 파일 개수.
    """
    count = 0
    prefix = f"{ticker}_" if ticker else ""
    for pattern in (f"{prefix}*.parquet", f"{prefix}*.full"):
        for f in CACHE_DIR.glob(pattern):
            f.unlink()
            count += 1
    return count
