"""core/market_data.py 캐싱 래퍼 동작 검증 (네트워크 접근 없이 캐시 파일만 검증)."""

from datetime import date, timedelta

import pandas as pd

from core import market_data


def test_cache_key_generation():
    key = market_data._cache_key("AAPL", "2020-01-01", "2020-12-31", "1d")
    assert key.name == "AAPL_2020-01-01_2020-12-31_1d.csv"


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


def test_get_price_history_uses_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)

    call_count = {"n": 0}

    def fake_download(*args, **kwargs):
        call_count["n"] += 1
        idx = pd.date_range("2024-01-01", periods=3, freq="D")
        return pd.DataFrame(
            {
                "Open": [1, 2, 3],
                "High": [1, 2, 3],
                "Low": [1, 2, 3],
                "Close": [1, 2, 3],
                "Adj Close": [1, 2, 3],
                "Volume": [100, 200, 300],
            },
            index=idx,
        )

    monkeypatch.setattr(market_data.yf, "download", fake_download)

    df1 = market_data.get_price_history("FAKE", start="2024-01-01", end="2024-01-04")
    df2 = market_data.get_price_history("FAKE", start="2024-01-01", end="2024-01-04")

    assert call_count["n"] == 1  # 두 번째 호출은 캐시 파일에서 읽어야 함
    assert len(df1) == 3
    assert len(df2) == 3
