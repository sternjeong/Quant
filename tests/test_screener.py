"""core/screener.py 단위 테스트 (모듈 E: 퀀트 스크리너).

네트워크(Wikipedia/yfinance)를 타지 않도록 관련 함수를 모두 monkeypatch 로 대체한다.
"""

import json

import pandas as pd
import pytest

import core.screener as screener


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(screener, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(screener, "UNIVERSE_CACHE_FILE", tmp_path / "sp500_universe.csv")
    return tmp_path


# ----------------------------------------------------------------------------
# get_universe / fetch_sp500_from_wikipedia
# ----------------------------------------------------------------------------


def test_get_universe_uses_wikipedia_result_and_caches(monkeypatch):
    fetched = pd.DataFrame(
        {"Symbol": ["AAPL", "MSFT"], "Security": ["Apple", "Microsoft"], "Sector": ["Tech", "Tech"]}
    )
    call_count = {"n": 0}

    def _fake_fetch():
        call_count["n"] += 1
        return fetched

    monkeypatch.setattr(screener, "fetch_sp500_from_wikipedia", _fake_fetch)

    df1 = screener.get_universe()
    assert list(df1["Symbol"]) == ["AAPL", "MSFT"]
    assert call_count["n"] == 1

    # 캐시 파일이 유효한 동안은 다시 fetch하지 않아야 한다.
    df2 = screener.get_universe()
    assert call_count["n"] == 1
    assert list(df2["Symbol"]) == ["AAPL", "MSFT"]


def test_get_universe_falls_back_when_fetch_fails_and_no_cache(monkeypatch):
    monkeypatch.setattr(screener, "fetch_sp500_from_wikipedia", lambda: pd.DataFrame(columns=["Symbol", "Security", "Sector"]))

    df = screener.get_universe()
    assert not df.empty
    assert "AAPL" in df["Symbol"].values  # _FALLBACK_UNIVERSE 에 포함된 종목


def test_get_universe_prefers_stale_cache_over_fallback(monkeypatch):
    fetched = pd.DataFrame({"Symbol": ["NVDA"], "Security": ["Nvidia"], "Sector": ["Tech"]})
    monkeypatch.setattr(screener, "fetch_sp500_from_wikipedia", lambda: fetched)
    screener.get_universe()  # 캐시 파일 생성

    # 이후 fetch가 실패해도, 오래됐지만 존재하는 캐시를 우선 사용
    monkeypatch.setattr(
        screener, "fetch_sp500_from_wikipedia", lambda: pd.DataFrame(columns=["Symbol", "Security", "Sector"])
    )
    df = screener.get_universe(cache_ttl=0)  # 캐시를 즉시 만료 처리
    assert list(df["Symbol"]) == ["NVDA"]


# ----------------------------------------------------------------------------
# get_fundamentals
# ----------------------------------------------------------------------------


def test_get_fundamentals_caches_result(monkeypatch, tmp_path):
    call_count = {"n": 0}

    class _FakeTicker:
        def __init__(self, ticker):
            call_count["n"] += 1

        @property
        def info(self):
            return {"longName": "Apple Inc.", "sector": "Technology", "trailingPE": 30.0, "priceToBook": 40.0, "marketCap": 3_000_000_000_000}

    monkeypatch.setattr(screener.yf, "Ticker", _FakeTicker)

    result1 = screener.get_fundamentals("AAPL")
    assert result1["per"] == 30.0
    assert result1["market_cap"] == 3_000_000_000_000
    assert call_count["n"] == 1

    result2 = screener.get_fundamentals("AAPL")
    assert result2 == result1
    assert call_count["n"] == 1  # 캐시 히트


def test_get_fundamentals_handles_failure_gracefully(monkeypatch):
    class _FailingTicker:
        def __init__(self, ticker):
            pass

        @property
        def info(self):
            raise RuntimeError("network error")

    monkeypatch.setattr(screener.yf, "Ticker", _FailingTicker)

    result = screener.get_fundamentals("BADTICKER", use_cache=False)
    assert result["per"] is None
    assert result["market_cap"] is None


# ----------------------------------------------------------------------------
# _passes_filters
# ----------------------------------------------------------------------------


def test_passes_filters_per_range():
    row = {"per": 15.0, "pbr": None, "market_cap": None, "rsi": None, "sector": "Tech"}
    assert screener._passes_filters(row, {"per_min": 10, "per_max": 20})
    assert not screener._passes_filters(row, {"per_min": 16})
    assert not screener._passes_filters(row, {"per_max": 14})


def test_passes_filters_sector():
    row = {"per": None, "pbr": None, "market_cap": None, "rsi": None, "sector": "Tech"}
    assert screener._passes_filters(row, {"sectors": ["Tech", "Health Care"]})
    assert not screener._passes_filters(row, {"sectors": ["Energy"]})


def test_passes_filters_above_sma200():
    row_above = {"per": None, "pbr": None, "market_cap": None, "rsi": None, "sector": None, "above_sma200": True}
    row_below = {**row_above, "above_sma200": False}
    assert screener._passes_filters(row_above, {"above_sma200": True})
    assert not screener._passes_filters(row_below, {"above_sma200": True})


def test_passes_filters_none_value_excluded_when_range_specified():
    row = {"per": None, "pbr": None, "market_cap": None, "rsi": None, "sector": None}
    assert not screener._passes_filters(row, {"per_min": 10})


# ----------------------------------------------------------------------------
# screen (end-to-end with mocked fundamentals/technicals)
# ----------------------------------------------------------------------------


def test_screen_filters_and_sorts_by_market_cap(monkeypatch):
    fundamentals_by_ticker = {
        "AAPL": {"ticker": "AAPL", "name": "Apple", "sector": "Tech", "per": 25.0, "pbr": 30.0, "market_cap": 3_000_000_000_000},
        "SMALLCO": {"ticker": "SMALLCO", "name": "Small Co", "sector": "Tech", "per": 60.0, "pbr": 5.0, "market_cap": 1_000_000_000},
        "NOPE": {"ticker": "NOPE", "name": "Energy Co", "sector": "Energy", "per": 10.0, "pbr": 1.0, "market_cap": 2_000_000_000},
    }

    monkeypatch.setattr(screener, "get_fundamentals", lambda t, **kw: fundamentals_by_ticker[t])

    result = screener.screen(
        tickers=["AAPL", "SMALLCO", "NOPE"],
        filters={"sectors": ["Tech"], "per_max": 30},
        include_technicals=False,
    )

    assert list(result["ticker"]) == ["AAPL"]


def test_screen_includes_technicals_when_requested(monkeypatch):
    fundamentals = {"ticker": "AAPL", "name": "Apple", "sector": "Tech", "per": 25.0, "pbr": 30.0, "market_cap": 100}
    monkeypatch.setattr(screener, "get_fundamentals", lambda t, **kw: fundamentals)

    price_df = pd.DataFrame({"Close": [float(i) for i in range(1, 251)]})
    monkeypatch.setattr(screener, "get_price_history", lambda t: price_df)

    result = screener.screen(tickers=["AAPL"], filters={"above_sma200": True}, include_technicals=True)
    assert len(result) == 1
    assert result.iloc[0]["above_sma200"] == True  # noqa: E712 (pandas may store as numpy bool)
    assert result.iloc[0]["rsi"] is not None


def test_screen_returns_empty_dataframe_with_expected_columns_when_no_match(monkeypatch):
    monkeypatch.setattr(
        screener,
        "get_fundamentals",
        lambda t, **kw: {"ticker": t, "name": None, "sector": "Tech", "per": 999.0, "pbr": None, "market_cap": None},
    )

    result = screener.screen(tickers=["AAPL"], filters={"per_max": 10}, include_technicals=False)
    assert result.empty
    assert list(result.columns) == ["ticker", "name", "sector", "per", "pbr", "market_cap", "price", "rsi", "above_sma200"]


def test_screen_defaults_to_full_universe_when_no_tickers_given(monkeypatch):
    universe = pd.DataFrame({"Symbol": ["AAPL"], "Security": ["Apple"], "Sector": ["Tech"]})
    monkeypatch.setattr(screener, "get_universe", lambda: universe)
    monkeypatch.setattr(
        screener,
        "get_fundamentals",
        lambda t, **kw: {"ticker": t, "name": "Apple", "sector": "Tech", "per": 20.0, "pbr": 10.0, "market_cap": 100},
    )

    result = screener.screen(filters=None, include_technicals=False)
    assert list(result["ticker"]) == ["AAPL"]


def test_list_sectors(monkeypatch):
    universe = pd.DataFrame({"Symbol": ["A", "B", "C"], "Security": ["x", "y", "z"], "Sector": ["Tech", "Energy", "Tech"]})
    monkeypatch.setattr(screener, "get_universe", lambda: universe)
    assert screener.list_sectors() == ["Energy", "Tech"]
