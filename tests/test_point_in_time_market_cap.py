"""core/point_in_time_market_cap.py 단위 테스트.

네트워크(yfinance)를 타지 않도록 yf.Ticker.get_shares_full과 core.market_data.get_price_history를
모두 monkeypatch로 대체한다 (core.screener 테스트와 동일한 격리 방식).
"""

import pandas as pd
import pytest

import core.point_in_time_market_cap as pit_cap


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pit_cap, "CACHE_DIR", tmp_path)
    return tmp_path


class _FakeTicker:
    def __init__(self, shares_series, splits=None):
        self._shares_series = shares_series
        self.splits = splits if splits is not None else pd.Series(dtype="float64")

    def get_shares_full(self, start=None, end=None):
        return self._shares_series


def _fake_shares_series():
    return pd.Series(
        [1000.0, 900.0, 800.0],
        index=pd.DatetimeIndex(["2018-01-01", "2019-01-01", "2020-01-01"]),
    )


def test_get_shares_outstanding_history_parses_and_sorts(monkeypatch):
    raw = pd.Series(
        [800.0, 1000.0, 900.0],
        index=pd.DatetimeIndex(["2020-01-01", "2018-01-01", "2019-01-01"]),
    )
    monkeypatch.setattr(pit_cap.yf, "Ticker", lambda t: _FakeTicker(raw))

    series = pit_cap.get_shares_outstanding_history("AAPL")
    assert list(series.index) == sorted(series.index)
    assert series.loc["2018-01-01"] == 1000.0


def test_get_shares_outstanding_history_caches(monkeypatch):
    call_count = {"n": 0}

    def _ticker_factory(t):
        call_count["n"] += 1
        return _FakeTicker(_fake_shares_series())

    monkeypatch.setattr(pit_cap.yf, "Ticker", _ticker_factory)

    pit_cap.get_shares_outstanding_history("AAPL")
    assert call_count["n"] == 1

    # 캐시가 유효한 동안은 다시 네트워크를 타지 않아야 한다.
    pit_cap.get_shares_outstanding_history("AAPL")
    assert call_count["n"] == 1


def test_get_shares_outstanding_history_empty_on_failure(monkeypatch):
    def _raise(t):
        raise RuntimeError("network down")

    monkeypatch.setattr(pit_cap.yf, "Ticker", _raise)

    series = pit_cap.get_shares_outstanding_history("BADTICKER")
    assert series.empty


def test_get_market_cap_asof_uses_shares_asof_and_price(monkeypatch):
    monkeypatch.setattr(pit_cap.yf, "Ticker", lambda t: _FakeTicker(_fake_shares_series()))

    def _fake_price_history(ticker, start=None, end=None, interval="1d", use_cache=True):
        return pd.DataFrame(
            {"Close": [50.0, 52.0]},
            index=pd.DatetimeIndex(["2019-06-01", "2019-06-02"]),
        )

    monkeypatch.setattr(pit_cap, "get_price_history", _fake_price_history)

    # as_of 2019-06-02 -> shares는 2019-01-01 스냅샷(900) 사용, 가격은 2019-06-02 종가(52.0)
    cap = pit_cap.get_market_cap_asof("AAPL", "2019-06-02")
    assert cap == pytest.approx(900.0 * 52.0)


def test_get_market_cap_asof_adjusts_shares_for_splits_after_asof(monkeypatch):
    # as_of 시점 이후 4:1, 10:1 두 번 분할(NVDA 사례 재현) -> 발행주식수를 40배로 보정해야
    # get_price_history의 분할조정 종가와 맞아떨어진다.
    splits = pd.Series(
        [4.0, 10.0],
        index=pd.DatetimeIndex(["2021-07-20", "2024-06-10"]),
    )
    monkeypatch.setattr(pit_cap.yf, "Ticker", lambda t: _FakeTicker(_fake_shares_series(), splits=splits))

    def _fake_price_history(ticker, start=None, end=None, interval="1d", use_cache=True):
        return pd.DataFrame({"Close": [3.78625]}, index=pd.DatetimeIndex(["2019-08-12"]))

    monkeypatch.setattr(pit_cap, "get_price_history", _fake_price_history)

    # shares as-of 2019-08-12 -> 2019-01-01 스냅샷(900, 가장 최근 이전 값) x 40배 분할보정
    cap = pit_cap.get_market_cap_asof("NVDA", "2019-08-12")
    assert cap == pytest.approx(900.0 * 40.0 * 3.78625)


def test_get_market_cap_asof_ignores_splits_before_asof(monkeypatch):
    # as_of 이전에만 분할이 있었으면(이미 그 분할이 shares_full 스냅샷에도 반영돼 있을 것이므로)
    # 추가 보정하면 안 된다.
    splits = pd.Series([2.0], index=pd.DatetimeIndex(["2015-01-01"]))
    monkeypatch.setattr(pit_cap.yf, "Ticker", lambda t: _FakeTicker(_fake_shares_series(), splits=splits))

    def _fake_price_history(ticker, start=None, end=None, interval="1d", use_cache=True):
        return pd.DataFrame({"Close": [52.0]}, index=pd.DatetimeIndex(["2019-06-02"]))

    monkeypatch.setattr(pit_cap, "get_price_history", _fake_price_history)

    cap = pit_cap.get_market_cap_asof("AAPL", "2019-06-02")
    assert cap == pytest.approx(900.0 * 52.0)


def test_get_market_cap_asof_falls_back_to_earliest_shares_before_history_start(monkeypatch):
    monkeypatch.setattr(pit_cap.yf, "Ticker", lambda t: _FakeTicker(_fake_shares_series()))

    def _fake_price_history(ticker, start=None, end=None, interval="1d", use_cache=True):
        return pd.DataFrame({"Close": [10.0]}, index=pd.DatetimeIndex(["2016-01-04"]))

    monkeypatch.setattr(pit_cap, "get_price_history", _fake_price_history)

    # as_of 2016년은 발행주식수 이력(2018년부터)보다 과거 -> 가장 이른 값(1000)으로 근사
    cap = pit_cap.get_market_cap_asof("AAPL", "2016-01-05")
    assert cap == pytest.approx(1000.0 * 10.0)


def test_get_market_cap_asof_none_when_no_shares_data(monkeypatch):
    monkeypatch.setattr(pit_cap.yf, "Ticker", lambda t: _FakeTicker(pd.Series(dtype="float64")))

    cap = pit_cap.get_market_cap_asof("NODATA", "2020-01-01")
    assert cap is None


def test_get_market_cap_asof_none_when_no_price_data(monkeypatch):
    monkeypatch.setattr(pit_cap.yf, "Ticker", lambda t: _FakeTicker(_fake_shares_series()))
    monkeypatch.setattr(pit_cap, "get_price_history", lambda *a, **k: pd.DataFrame())

    cap = pit_cap.get_market_cap_asof("AAPL", "2020-01-01")
    assert cap is None


def test_get_market_caps_asof_batch_returns_dict_for_all_tickers(monkeypatch):
    monkeypatch.setattr(pit_cap.yf, "Ticker", lambda t: _FakeTicker(_fake_shares_series()))
    monkeypatch.setattr(
        pit_cap,
        "get_price_history",
        lambda *a, **k: pd.DataFrame({"Close": [20.0]}, index=pd.DatetimeIndex(["2019-06-01"])),
    )

    result = pit_cap.get_market_caps_asof_batch(["AAPL", "MSFT"], "2019-06-01")
    assert set(result.keys()) == {"AAPL", "MSFT"}
    assert all(v is not None for v in result.values())


def test_get_market_caps_asof_batch_empty_list():
    assert pit_cap.get_market_caps_asof_batch([], "2019-06-01") == {}
