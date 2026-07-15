"""core/market_data.py 캐싱 래퍼 동작 검증 (네트워크 접근 없이 캐시 파일만 검증)."""

import os
import time
from datetime import date, timedelta

import pandas as pd

from core import market_data


def test_store_path_generation():
    path = market_data._store_path("AAPL", "1d")
    assert path.name == "AAPL_1d.parquet"


def test_clamp_start_for_interval_unlimited_for_daily_plus():
    start = date(1990, 1, 1)
    end = date(2026, 7, 12)
    clamped, was_clamped = market_data.clamp_start_for_interval("1d", start, end)
    assert clamped == start
    assert was_clamped is False


def test_clamp_start_for_interval_clamps_intraday():
    end = date(2026, 7, 12)
    start = end - timedelta(days=400)  # 60분봉 최대(730일)보다는 짧지만 5분봉(60일) 한도는 초과
    clamped, was_clamped = market_data.clamp_start_for_interval("5m", start, end)
    assert was_clamped is True
    assert clamped == end - timedelta(days=60)


def test_clamp_start_for_interval_no_clamp_when_within_range():
    end = date(2026, 7, 12)
    start = end - timedelta(days=10)
    clamped, was_clamped = market_data.clamp_start_for_interval("5m", start, end)
    assert clamped == start
    assert was_clamped is False


def _make_daily_df(start: str, periods: int) -> pd.DataFrame:
    idx = pd.date_range(start, periods=periods, freq="B")  # 영업일(월~금)만
    n = len(idx)
    return pd.DataFrame(
        {
            "Open": [100 + i for i in range(n)],
            "High": [105 + i for i in range(n)],
            "Low": [95 + i for i in range(n)],
            "Close": [102 + i for i in range(n)],
            "Adj Close": [102 + i for i in range(n)],
            "Volume": [1000 + i * 10 for i in range(n)],
        },
        index=idx,
    )


def test_resample_ohlcv_weekly_aggregates_correctly():
    # 2024-01-01(월) ~ 2024-01-12(금) 영업일 10일 = 정확히 2주
    df = _make_daily_df("2024-01-01", 10)
    weekly = market_data.resample_ohlcv(df, "W-FRI")

    assert len(weekly) == 2
    first_week = df.iloc[0:5]
    assert weekly.iloc[0]["Open"] == first_week.iloc[0]["Open"]
    assert weekly.iloc[0]["Close"] == first_week.iloc[-1]["Close"]
    assert weekly.iloc[0]["High"] == first_week["High"].max()
    assert weekly.iloc[0]["Low"] == first_week["Low"].min()
    assert weekly.iloc[0]["Volume"] == first_week["Volume"].sum()
    # 인덱스는 실제 마지막 거래일(그 주의 금요일)이어야 함
    assert weekly.index[0] == first_week.index[-1]


def test_resample_ohlcv_uses_last_actual_trading_day_not_calendar_month_end():
    # 2024년 6월은 30일이 일요일이라 실제 마지막 거래일은 6/28(금)이어야 함
    df = _make_daily_df("2024-06-01", 30)
    monthly = market_data.resample_ohlcv(df, "ME")
    assert monthly.index[-1].strftime("%Y-%m-%d") != "2024-06-30"
    assert monthly.index[-1].weekday() < 5  # 평일


def test_resample_ohlcv_empty_input_returns_empty():
    empty = pd.DataFrame()
    assert market_data.resample_ohlcv(empty, "W-FRI").empty


def _fake_download_factory(calls: list):
    """호출될 때마다 start를 calls에 기록하고, start~end 사이의 영업일 더미 OHLCV를 반환하는
    fake yf.download. end는 yfinance 관례대로 배타적(포함 안 함)으로 흉내낸다."""

    def fake_download(ticker, start=None, end=None, interval="1d", **kwargs):
        calls.append(start)
        s = pd.Timestamp(start) if start else pd.Timestamp("2024-01-01")
        e = pd.Timestamp(end) if end else pd.Timestamp("2024-01-31")
        idx = pd.date_range(s, e, freq="B", inclusive="left")
        if len(idx) == 0:
            return pd.DataFrame()
        n = len(idx)
        return pd.DataFrame(
            {
                "Open": range(n),
                "High": range(n),
                "Low": range(n),
                "Close": range(n),
                "Adj Close": range(n),
                "Volume": [100] * n,
            },
            index=idx,
        )

    return fake_download


def test_get_price_history_uses_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)
    calls: list = []
    monkeypatch.setattr(market_data.yf, "download", _fake_download_factory(calls))

    df1 = market_data.get_price_history("FAKE", start="2024-01-01", end="2024-01-04")
    df2 = market_data.get_price_history("FAKE", start="2024-01-01", end="2024-01-04")

    assert len(calls) == 1  # 두 번째 호출은 로컬 저장소에서 읽어야 함(같은 범위, 이미 커버됨)
    assert len(df1) == 3  # 01-01(월)~01-03(수), end(01-04)는 배타적
    assert len(df2) == 3


def test_get_price_history_skips_network_for_fully_historical_stale_range(monkeypatch, tmp_path):
    """명시적 end가 있고 이미 저장소에 커버되는 요청은, 캐시가 TTL보다 오래됐어도 네트워크를
    타지 않아야 한다 (백테스트/다종목 튜닝이 같은 과거 구간을 반복 조회하는 상황을 흉내냄)."""
    monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)
    calls: list = []
    monkeypatch.setattr(market_data.yf, "download", _fake_download_factory(calls))

    market_data.get_price_history("FAKE", start="2024-01-01", end="2024-01-15")
    assert len(calls) == 1

    store_file = market_data._store_path("FAKE", "1d")
    old_time = time.time() - market_data.DEFAULT_CACHE_TTL_SECONDS - 10
    os.utime(store_file, (old_time, old_time))

    result = market_data.get_price_history("FAKE", start="2024-01-02", end="2024-01-05")
    assert len(calls) == 1  # 추가 네트워크 호출 없음
    assert len(result) == 3  # 01-02(화)~01-04(목)


def test_get_price_history_tail_delta_only_not_full_redownload(monkeypatch, tmp_path):
    """저장 범위를 벗어나는(=최신 구간이 더 필요한) 요청은, 처음부터 다시 받지 않고 저장된
    마지막 날짜부터만 델타로 받아와야 한다."""
    monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)
    calls: list = []
    monkeypatch.setattr(market_data.yf, "download", _fake_download_factory(calls))

    market_data.get_price_history("FAKE", start="2024-01-01", end="2024-01-10")
    assert calls[0] == "2024-01-01"

    # end=None(오늘까지)이면 저장 범위(~01-09)를 넘어서므로 델타 호출이 발생하지만, 그 시작점은
    # 저장된 마지막 날짜여야 한다(=전체 재다운로드 금지).
    market_data.get_price_history("FAKE", start="2024-01-01")
    assert len(calls) == 2
    assert calls[1] == "2024-01-09"


def test_get_price_history_backfills_only_missing_older_range(monkeypatch, tmp_path):
    """요청 시작일이 저장된 범위보다 이전이면, 부족한 앞부분만 추가로 받아와야 한다."""
    monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)
    calls: list = []
    monkeypatch.setattr(market_data.yf, "download", _fake_download_factory(calls))

    market_data.get_price_history("FAKE", start="2024-01-08", end="2024-01-10")
    assert calls[0] == "2024-01-08"

    result = market_data.get_price_history("FAKE", start="2024-01-01", end="2024-01-10")
    assert len(calls) == 2
    assert calls[1] == "2024-01-01"  # 앞쪽 부족분만 요청 (뒤쪽은 이미 있어서 재요청 안 함)
    assert result.index.min() == pd.Timestamp("2024-01-01")
