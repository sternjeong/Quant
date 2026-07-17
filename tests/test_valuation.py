"""core/valuation.py 단위 테스트 (모듈 F: 밸류에이션 도구).

순수 계산 함수는 직접 검증하고, 네트워크가 필요한 fetch_valuation_inputs / get_valuation_band /
get_peer_comparison 은 monkeypatch 로 대체한다.
"""

import pandas as pd
import pytest

import core.valuation as valuation


@pytest.fixture(autouse=True)
def _isolated_valuation_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(valuation, "_CACHE_DIR", tmp_path)
    return tmp_path


# ----------------------------------------------------------------------------
# 개별 방법론
# ----------------------------------------------------------------------------


def test_dcf_intrinsic_value_positive_case():
    value = valuation.dcf_intrinsic_value(
        fcf=1000.0, shares_outstanding=100.0, growth_rate=0.05, discount_rate=0.10, terminal_growth=0.02, years=5
    )
    assert value is not None
    assert value > 0


def test_dcf_intrinsic_value_returns_none_when_missing_inputs():
    assert valuation.dcf_intrinsic_value(None, 100.0) is None
    assert valuation.dcf_intrinsic_value(1000.0, None) is None
    assert valuation.dcf_intrinsic_value(-100.0, 100.0) is None


def test_dcf_intrinsic_value_returns_none_when_model_diverges():
    # discount_rate <= terminal_growth 이면 터미널 가치가 발산하므로 None
    assert valuation.dcf_intrinsic_value(1000.0, 100.0, discount_rate=0.02, terminal_growth=0.03) is None


def test_ddm_intrinsic_value_gordon_growth_formula():
    # next_dividend = 2 * 1.03 = 2.06, value = 2.06 / (0.09 - 0.03) = 34.333...
    value = valuation.ddm_intrinsic_value(dividend_per_share=2.0, required_return=0.09, growth_rate=0.03)
    assert value == pytest.approx(34.333, rel=1e-3)


def test_ddm_intrinsic_value_none_for_non_dividend_stock():
    assert valuation.ddm_intrinsic_value(None) is None
    assert valuation.ddm_intrinsic_value(0.0) is None


def test_ddm_intrinsic_value_none_when_growth_exceeds_required_return():
    assert valuation.ddm_intrinsic_value(2.0, required_return=0.05, growth_rate=0.08) is None


def test_per_relative_value():
    assert valuation.per_relative_value(eps=5.0, peer_per=20.0) == 100.0
    assert valuation.per_relative_value(None, 20.0) is None
    assert valuation.per_relative_value(5.0, None) is None


def test_pbr_relative_value():
    assert valuation.pbr_relative_value(book_value_per_share=10.0, peer_pbr=3.0) == 30.0
    assert valuation.pbr_relative_value(None, 3.0) is None


def test_ev_ebitda_relative_value():
    # implied_ev = 500 * 10 = 5000, equity = 5000 - 1000 = 4000, per share = 4000/100 = 40
    value = valuation.ev_ebitda_relative_value(ebitda=500.0, peer_multiple=10.0, net_debt=1000.0, shares_outstanding=100.0)
    assert value == 40.0


def test_ev_ebitda_relative_value_none_when_missing():
    assert valuation.ev_ebitda_relative_value(None, 10.0, 0.0, 100.0) is None
    assert valuation.ev_ebitda_relative_value(500.0, 10.0, 0.0, None) is None


def test_peg_ratio():
    assert valuation.peg_ratio(per=20.0, earnings_growth_pct=10.0) == 2.0
    assert valuation.peg_ratio(20.0, None) is None
    assert valuation.peg_ratio(20.0, 0) is None


def test_graham_number():
    # sqrt(22.5 * 5 * 8) = sqrt(900) = 30
    assert valuation.graham_number(eps=5.0, book_value_per_share=8.0) == pytest.approx(30.0)


def test_graham_number_none_for_negative_eps():
    assert valuation.graham_number(eps=-1.0, book_value_per_share=8.0) is None


# ----------------------------------------------------------------------------
# fetch_valuation_inputs (네트워크 mock)
# ----------------------------------------------------------------------------


def test_fetch_valuation_inputs_maps_info_fields(monkeypatch):
    class _FakeTicker:
        def __init__(self, ticker):
            pass

        @property
        def info(self):
            return {
                "currentPrice": 150.0,
                "trailingEps": 6.0,
                "bookValue": 20.0,
                "trailingPE": 25.0,
                "priceToBook": 7.5,
                "dividendRate": 1.0,
                "freeCashflow": 90_000_000_000,
                "sharesOutstanding": 15_000_000_000,
                "totalDebt": 100_000_000_000,
                "totalCash": 50_000_000_000,
                "enterpriseValue": 2_500_000_000_000,
                "ebitda": 130_000_000_000,
                "earningsGrowth": 0.12,
                "sector": "Technology",
                "longName": "Apple Inc.",
            }

    monkeypatch.setattr(valuation.yf, "Ticker", _FakeTicker)

    result = valuation.fetch_valuation_inputs("AAPL")
    assert result["currentPrice"] == 150.0
    assert result["trailingEps"] == 6.0
    assert result["longName"] == "Apple Inc."


def test_fetch_valuation_inputs_handles_failure_gracefully(monkeypatch):
    class _FailingTicker:
        def __init__(self, ticker):
            pass

        @property
        def info(self):
            raise RuntimeError("network down")

    monkeypatch.setattr(valuation.yf, "Ticker", _FailingTicker)

    result = valuation.fetch_valuation_inputs("BAD")
    assert result["currentPrice"] is None
    assert result["ticker"] == "BAD"


def test_fetch_valuation_inputs_falls_back_to_regular_market_price(monkeypatch):
    class _FakeTicker:
        def __init__(self, ticker):
            pass

        @property
        def info(self):
            return {"regularMarketPrice": 99.0}

    monkeypatch.setattr(valuation.yf, "Ticker", _FakeTicker)
    result = valuation.fetch_valuation_inputs("XYZ")
    assert result["currentPrice"] == 99.0


# ----------------------------------------------------------------------------
# compute_all_valuations
# ----------------------------------------------------------------------------


def _sample_inputs(**overrides):
    base = {
        "currentPrice": 150.0,
        "trailingEps": 6.0,
        "bookValue": 20.0,
        "trailingPE": 25.0,
        "priceToBook": 7.5,
        "dividendRate": 1.0,
        "freeCashflow": 90_000_000_000.0,
        "sharesOutstanding": 15_000_000_000.0,
        "totalDebt": 100_000_000_000.0,
        "totalCash": 50_000_000_000.0,
        "enterpriseValue": 2_500_000_000_000.0,
        "ebitda": 130_000_000_000.0,
        "earningsGrowth": 0.12,
        "sector": "Technology",
        "longName": "Apple Inc.",
    }
    base.update(overrides)
    return base


def test_compute_all_valuations_returns_all_methods():
    result = valuation.compute_all_valuations("AAPL", inputs=_sample_inputs())

    assert result["ticker"] == "AAPL"
    assert result["current_price"] == 150.0
    assert set(result["methods"].keys()) == {"dcf", "ddm", "per_relative", "pbr_relative", "ev_ebitda", "graham_number"}
    for method in result["methods"].values():
        assert method["value"] is not None
        assert method["value"] > 0
    assert result["peg"]["value"] is not None


def test_compute_all_valuations_handles_missing_dividend():
    result = valuation.compute_all_valuations("XYZ", inputs=_sample_inputs(dividendRate=None))
    assert result["methods"]["ddm"]["value"] is None
    # 다른 방법론은 정상 계산되어야 함
    assert result["methods"]["dcf"]["value"] is not None


def test_compute_all_valuations_respects_assumption_overrides():
    result_default = valuation.compute_all_valuations("AAPL", inputs=_sample_inputs())
    result_override = valuation.compute_all_valuations(
        "AAPL", inputs=_sample_inputs(), assumptions={"peer_per": 40.0}
    )
    assert result_override["methods"]["per_relative"]["value"] == 6.0 * 40.0
    assert result_override["methods"]["per_relative"]["value"] != result_default["methods"]["per_relative"]["value"]


# ----------------------------------------------------------------------------
# get_valuation_band / get_peer_comparison
# ----------------------------------------------------------------------------


def test_get_valuation_band_computes_per_pbr_series(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    price_df = pd.DataFrame({"Close": [100.0, 110.0, 120.0]}, index=idx)
    monkeypatch.setattr(valuation, "get_price_history", lambda ticker, start=None: price_df)

    band = valuation.get_valuation_band("AAPL", inputs=_sample_inputs(trailingEps=10.0, bookValue=20.0))
    assert list(band["PER"]) == [10.0, 11.0, 12.0]
    assert list(band["PBR"]) == [5.0, 5.5, 6.0]


def test_get_valuation_band_empty_price_history(monkeypatch):
    monkeypatch.setattr(valuation, "get_price_history", lambda ticker, start=None: pd.DataFrame())
    band = valuation.get_valuation_band("AAPL", inputs=_sample_inputs())
    assert band.empty


def test_get_peer_comparison(monkeypatch):
    def _fake_fetch(ticker):
        return _sample_inputs(longName=f"{ticker} Inc.")

    monkeypatch.setattr(valuation, "fetch_valuation_inputs", _fake_fetch)

    df = valuation.get_peer_comparison(["AAPL", "MSFT"])
    assert list(df["ticker"]) == ["AAPL", "MSFT"]
    assert df.iloc[0]["ev_ebitda"] == pytest.approx(2_500_000_000_000.0 / 130_000_000_000.0)


# ----------------------------------------------------------------------------
# fetch_valuation_inputs 캐싱
# ----------------------------------------------------------------------------


def test_fetch_valuation_inputs_caches_to_disk(monkeypatch, tmp_path):
    call_count = {"n": 0}

    class _FakeTicker:
        def __init__(self, ticker):
            pass

        @property
        def info(self):
            call_count["n"] += 1
            return {"currentPrice": 100.0, "sector": "Technology", "longName": "Test Co."}

    monkeypatch.setattr(valuation.yf, "Ticker", _FakeTicker)

    first = valuation.fetch_valuation_inputs("AAPL")
    second = valuation.fetch_valuation_inputs("AAPL")
    assert call_count["n"] == 1  # 두 번째 호출은 캐시 파일을 읽어 네트워크를 안 탐
    assert first == second
    assert (tmp_path / "valuation_inputs_AAPL.json").exists()


def test_fetch_valuation_inputs_bypasses_cache_when_use_cache_false(monkeypatch):
    call_count = {"n": 0}

    class _FakeTicker:
        def __init__(self, ticker):
            pass

        @property
        def info(self):
            call_count["n"] += 1
            return {"currentPrice": 100.0}

    monkeypatch.setattr(valuation.yf, "Ticker", _FakeTicker)

    valuation.fetch_valuation_inputs("AAPL", use_cache=False)
    valuation.fetch_valuation_inputs("AAPL", use_cache=False)
    assert call_count["n"] == 2


def test_fetch_valuation_inputs_expired_cache_refetches(monkeypatch, tmp_path):
    call_count = {"n": 0}

    class _FakeTicker:
        def __init__(self, ticker):
            pass

        @property
        def info(self):
            call_count["n"] += 1
            return {"currentPrice": 100.0}

    monkeypatch.setattr(valuation.yf, "Ticker", _FakeTicker)

    valuation.fetch_valuation_inputs("AAPL")
    valuation.fetch_valuation_inputs("AAPL", cache_ttl=0)  # TTL 0 → 항상 만료 취급
    assert call_count["n"] == 2


# ----------------------------------------------------------------------------
# select_auto_peers (규칙 기반 자동 피어 선정)
# ----------------------------------------------------------------------------


def test_select_auto_peers_picks_closest_market_cap_in_same_sector(monkeypatch):
    monkeypatch.setattr(
        valuation, "fetch_valuation_inputs",
        lambda ticker, **kw: {"sector": "Technology", "marketCap": 1_000_000_000_000},
    )

    import core.screener as screener

    universe = pd.DataFrame(
        {"Symbol": ["AAPL", "MSFT", "TINY", "OTHER_SECTOR"], "Sector": ["Technology", "Technology", "Technology", "Energy"]}
    )
    monkeypatch.setattr(screener, "get_universe", lambda: universe)

    fundamentals_by_ticker = {
        "MSFT": {"market_cap": 1_100_000_000_000},  # 대상과 가장 가까움
        "TINY": {"market_cap": 10_000_000_000},  # 훨씬 멂
    }
    monkeypatch.setattr(screener, "get_fundamentals", lambda t, **kw: fundamentals_by_ticker.get(t, {"market_cap": None}))

    peers = valuation.select_auto_peers("AAPL", n=2)
    assert peers == ["MSFT", "TINY"]


def test_select_auto_peers_returns_empty_without_sector(monkeypatch):
    import core.screener as screener

    monkeypatch.setattr(valuation, "fetch_valuation_inputs", lambda ticker, **kw: {"sector": None, "marketCap": None})
    monkeypatch.setattr(screener, "get_universe", lambda: pd.DataFrame({"Symbol": ["AAPL"], "Sector": ["Technology"]}))
    assert valuation.select_auto_peers("UNKNOWN") == []


def test_select_auto_peers_falls_back_to_first_n_without_market_cap_data(monkeypatch):
    monkeypatch.setattr(
        valuation, "fetch_valuation_inputs",
        lambda ticker, **kw: {"sector": "Technology", "marketCap": None},
    )

    import core.screener as screener

    universe = pd.DataFrame({"Symbol": ["AAPL", "MSFT", "GOOGL"], "Sector": ["Technology", "Technology", "Technology"]})
    monkeypatch.setattr(screener, "get_universe", lambda: universe)
    monkeypatch.setattr(screener, "get_fundamentals", lambda t, **kw: {"market_cap": None})

    peers = valuation.select_auto_peers("AAPL", n=2)
    assert peers == ["MSFT", "GOOGL"]
