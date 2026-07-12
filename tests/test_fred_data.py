"""core/fred_data.py 단위 테스트 (모듈 G: 매크로 대시보드).

실제 FRED API를 타지 않도록 fredapi.Fred 를 monkeypatch 로 대체한다.
"""

import pandas as pd
import pytest

import core.fred_data as fred_data


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fred_data, "CACHE_DIR", tmp_path)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    return tmp_path


def test_is_configured_reflects_env_var(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert fred_data.is_configured() is False
    monkeypatch.setenv("FRED_API_KEY", "abc123")
    assert fred_data.is_configured() is True


def test_get_series_returns_empty_without_api_key():
    result = fred_data.get_series("FEDFUNDS", use_cache=False)
    assert result.empty


def test_get_series_fetches_and_caches(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    call_count = {"n": 0}

    class _FakeFred:
        def __init__(self, api_key):
            pass

        def get_series(self, series_id, observation_start=None, observation_end=None):
            call_count["n"] += 1
            idx = pd.date_range("2024-01-01", periods=3, freq="ME")
            return pd.Series([5.0, 5.25, 5.5], index=idx)

    import sys
    import types

    fake_module = types.ModuleType("fredapi")
    fake_module.Fred = _FakeFred
    monkeypatch.setitem(sys.modules, "fredapi", fake_module)

    result1 = fred_data.get_series("FEDFUNDS")
    assert list(result1) == [5.0, 5.25, 5.5]
    assert call_count["n"] == 1

    # 캐시가 유효한 동안 재호출하지 않아야 한다.
    result2 = fred_data.get_series("FEDFUNDS")
    assert call_count["n"] == 1
    assert list(result2) == [5.0, 5.25, 5.5]


def test_get_series_handles_api_failure_gracefully(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    class _FailingFred:
        def __init__(self, api_key):
            pass

        def get_series(self, series_id, observation_start=None, observation_end=None):
            raise RuntimeError("FRED API down")

    import sys
    import types

    fake_module = types.ModuleType("fredapi")
    fake_module.Fred = _FailingFred
    monkeypatch.setitem(sys.modules, "fredapi", fake_module)

    result = fred_data.get_series("FEDFUNDS", use_cache=False)
    assert result.empty


def test_get_latest_value(monkeypatch):
    monkeypatch.setattr(
        fred_data, "get_series", lambda series_id, **kw: pd.Series([1.0, 2.0, 3.0])
    )
    assert fred_data.get_latest_value("UNRATE") == 3.0


def test_get_latest_value_none_for_empty_series(monkeypatch):
    monkeypatch.setattr(fred_data, "get_series", lambda series_id, **kw: pd.Series(dtype=float))
    assert fred_data.get_latest_value("UNRATE") is None


def test_get_indicator_snapshot_structure(monkeypatch):
    def _fake_get_series(series_id, **kw):
        if series_id == "FEDFUNDS":
            return pd.Series([5.0, 5.5], index=pd.date_range("2024-01-01", periods=2, freq="ME"))
        return pd.Series(dtype=float)

    monkeypatch.setattr(fred_data, "get_series", _fake_get_series)

    snapshot = fred_data.get_indicator_snapshot({"FEDFUNDS": {"label": "기준금리", "unit": "%"}, "UNRATE": {"label": "실업률", "unit": "%"}})
    by_id = {row["series_id"]: row for row in snapshot}

    assert by_id["FEDFUNDS"]["latest_value"] == 5.5
    assert by_id["FEDFUNDS"]["latest_date"] is not None
    assert by_id["UNRATE"]["latest_value"] is None
    assert by_id["UNRATE"]["latest_date"] is None
