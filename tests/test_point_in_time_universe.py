"""core/point_in_time_universe.py 테스트.

실제로 다운로드된 data/sp500_historical_constituents.csv 파일에 대해
직접 검증한다 (정적 데이터 파일이므로 mocking 불필요).
"""

from core.point_in_time_universe import (
    get_constituents_as_of,
    load_historical_constituents_table,
)


def test_load_historical_constituents_table_basic_shape():
    df = load_historical_constituents_table()
    assert not df.empty
    assert list(df.columns) >= ["date", "tickers", "tickers_list"]
    assert df["date"].is_monotonic_increasing
    # 첫 번째 행은 1996년대여야 함 (fja05680 데이터셋은 1996년까지 거슬러 올라간다)
    assert df["date"].iloc[0].year == 1996


def test_get_constituents_as_of_2020_includes_large_well_known_universe():
    tickers = get_constituents_as_of("2020-01-01")
    assert isinstance(tickers, list)
    assert tickers == sorted(tickers)
    # 대략 S&P500 규모여야 함
    assert 450 <= len(tickers) <= 520
    assert "AAPL" in tickers
    assert "MSFT" in tickers


def test_get_constituents_as_of_before_earliest_date_uses_earliest_row_without_error():
    # 데이터 시작(1996년 초)보다 이전 날짜를 넣어도 에러 없이 가장 이른 행을 사용해야 함
    tickers = get_constituents_as_of("1990-01-01")
    assert isinstance(tickers, list)
    assert len(tickers) > 0


def test_point_in_time_behavior_differs_across_dates():
    # 이 모듈이 고치려는 핵심 버그: "현재" 목록이 아니라 실제 그 시점의 목록을 반환해야 한다.
    early = get_constituents_as_of("1996-06-01")
    later = get_constituents_as_of("2020-01-01")

    assert early != later

    # 1996년 당시엔 없었지만 이후 S&P500에 편입된 종목이 later에는 있어야 한다
    # (Facebook은 2012년 IPO, 2013년에 S&P500에 편입됨)
    assert "FB" not in early
    assert "FB" in later

    # Amazon도 1996년에는 상장 전(1997년 IPO)이라 없어야 하고, 2020년에는 있어야 한다
    assert "AMZN" not in early
    assert "AMZN" in later


def test_ticker_normalization_uses_dash_not_dot():
    # BRK.B 같은 표기는 core/screener.py 관례와 동일하게 BRK-B로 정규화되어야 한다
    tickers = get_constituents_as_of("2020-01-01")
    assert "BRK-B" in tickers or "BRK.B" not in tickers
    for t in tickers:
        assert "." not in t

    # 이탈일자 접미사(-YYYYMM)가 제거되어 있어야 한다
    for t in tickers:
        assert not t.split("-")[-1].isdigit() or len(t.split("-")[-1]) != 6


def test_repeated_calls_use_cache_and_return_consistent_results():
    first = get_constituents_as_of("2015-01-01")
    second = get_constituents_as_of("2015-01-01")
    assert first == second
