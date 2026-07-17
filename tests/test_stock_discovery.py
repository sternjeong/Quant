"""core/stock_discovery.py 단위 테스트.

tests/test_strategy_tuning.py 와 동일한 스타일: 네트워크(yfinance)를 타지 않도록 screener /
valuation / market_data 관련 함수를 모두 monkeypatch 로 대체하고, 작은 합성(synthetic) 유니버스로
스코어링 로직만 검증한다.
"""

import numpy as np
import pandas as pd
import pytest

import core.stock_discovery as sd_mod

UNIVERSE_DF = pd.DataFrame(
    [
        ("AAA", "AAA Inc.", "Information Technology"),
        ("BBB", "BBB Inc.", "Information Technology"),
        ("CCC", "CCC Inc.", "Health Care"),
        ("DDD", "DDD Inc.", "Health Care"),
        ("EEE", "EEE Inc.", "Financials"),
        ("FFF", "FFF Inc.", "Financials"),
        ("GGG", "GGG Inc.", "Energy"),  # 데이터 완전 실패 케이스
    ],
    columns=["Symbol", "Security", "Sector"],
)

# 티커별 합성 밸류에이션 입력. AAA는 모든 팩터에서 최상급이 되도록 설계(모멘텀 최고 + 최고 성장 +
# 최저 PER/PBR + 최고 FCF수익률/무차입) -> composite_score 1위가 되어야 함.
VAL_INPUTS = {
    "AAA": {
        "sector": "Information Technology",
        "longName": "AAA Inc.",
        "trailingPE": 8.0,
        "priceToBook": 1.0,
        "earningsGrowth": 0.40,
        "freeCashflow": 500_000_000,
        "marketCap": 2_000_000_000,
        "totalCash": 1_000_000_000,
        "totalDebt": 0,
    },
    "BBB": {
        "sector": "Information Technology",
        "longName": "BBB Inc.",
        "trailingPE": 40.0,
        "priceToBook": 12.0,
        "earningsGrowth": 0.05,
        "freeCashflow": 10_000_000,
        "marketCap": 5_000_000_000,
        "totalCash": 100_000_000,
        "totalDebt": 4_000_000_000,
    },
    "CCC": {
        "sector": "Health Care",
        "longName": "CCC Inc.",
        "trailingPE": 20.0,
        "priceToBook": 3.0,
        "earningsGrowth": 0.15,
        "freeCashflow": 200_000_000,
        "marketCap": 3_000_000_000,
        "totalCash": 500_000_000,
        "totalDebt": 500_000_000,
    },
    "DDD": {
        "sector": "Health Care",
        "longName": "DDD Inc.",
        "trailingPE": -5.0,  # 적자 기업 (음수 PER)
        "priceToBook": 2.0,
        "earningsGrowth": None,
        "freeCashflow": None,
        "marketCap": 1_000_000_000,
        "totalCash": None,
        "totalDebt": None,
    },
    "EEE": {
        "sector": "Financials",
        "longName": "EEE Inc.",
        "trailingPE": 15.0,
        "priceToBook": 2.5,
        "earningsGrowth": 0.10,
        "freeCashflow": 100_000_000,
        "marketCap": 2_500_000_000,
        "totalCash": 300_000_000,
        "totalDebt": 300_000_000,
    },
    "FFF": {  # 펀더멘털 완전 결측(None들) 이지만 가격 데이터는 있음 -> 제외되면 안 됨
        "sector": "Financials",
        "longName": None,
        "trailingPE": None,
        "priceToBook": None,
        "earningsGrowth": None,
        "freeCashflow": None,
        "marketCap": None,
        "totalCash": None,
        "totalDebt": None,
    },
    "GGG": {},  # 완전 데이터 실패 케이스(빈 dict) + 빈 가격 데이터 -> 결과에서 제외돼야 함
}


def _flat_price_df(n=300, start_price=100.0, daily_return=0.0):
    """일정한(또는 완만히 상승하는) 종가 시계열의 합성 OHLCV DataFrame."""
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    prices = start_price * (1 + daily_return) ** np.arange(n)
    return pd.DataFrame(
        {
            "Open": prices,
            "High": prices * 1.01,
            "Low": prices * 0.99,
            "Close": prices,
            "Adj Close": prices,
            "Volume": 1_000_000,
        },
        index=idx,
    )


PRICE_DATA = {
    "AAA": _flat_price_df(300, 100.0, daily_return=0.004),  # 강한 상승 모멘텀
    "BBB": _flat_price_df(300, 100.0, daily_return=-0.001),  # 하락
    "CCC": _flat_price_df(300, 100.0, daily_return=0.0005),
    "DDD": _flat_price_df(300, 100.0, daily_return=0.0002),
    "EEE": _flat_price_df(300, 100.0, daily_return=0.0003),
    "FFF": _flat_price_df(300, 100.0, daily_return=0.0001),
    "GGG": pd.DataFrame(),  # 가격 데이터도 없음
}


def _install_mocks(monkeypatch, universe_df=UNIVERSE_DF, val_inputs=VAL_INPUTS, price_data=PRICE_DATA):
    monkeypatch.setattr(sd_mod.screener, "get_universe", lambda use_cache=True: universe_df.copy())

    def _fake_fundamentals(ticker, use_cache=True):
        v = val_inputs.get(ticker, {})
        if not v:
            return {}
        return {
            "ticker": ticker,
            "name": v.get("longName"),
            "sector": v.get("sector"),
            "per": v.get("trailingPE"),
            "pbr": v.get("priceToBook"),
            "market_cap": v.get("marketCap"),
        }

    monkeypatch.setattr(sd_mod.screener, "get_fundamentals", _fake_fundamentals)
    monkeypatch.setattr(sd_mod.valuation, "fetch_valuation_inputs", lambda ticker, use_cache=True: dict(val_inputs.get(ticker, {})))
    monkeypatch.setattr(sd_mod, "get_price_history", lambda ticker, start=None, use_cache=True: price_data.get(ticker, pd.DataFrame()).copy())


def test_composite_ranking_best_ticker_ranks_first(monkeypatch):
    """AAA는 모멘텀/성장/가치/퀄리티 모두 최상급으로 설계했으므로 composite 1위여야 한다."""
    _install_mocks(monkeypatch)
    result = sd_mod.discover_candidates(use_cache=False, top_n=10)
    assert not result.empty
    assert result.iloc[0]["ticker"] == "AAA"


def test_sector_filter_restricts_candidates(monkeypatch):
    _install_mocks(monkeypatch)
    result = sd_mod.discover_candidates(use_cache=False, top_n=10, sector_filter=["Health Care"])
    assert set(result["sector"]) <= {"Health Care"}
    assert set(result["ticker"]) <= {"CCC", "DDD"}


def test_top_n_is_respected(monkeypatch):
    _install_mocks(monkeypatch)
    result = sd_mod.discover_candidates(use_cache=False, top_n=2)
    assert len(result) == 2


def test_missing_fundamentals_ticker_excluded_but_others_survive(monkeypatch):
    """GGG는 펀더멘털/가격 데이터 모두 없으므로 결과에서 제외되지만, 다른 티커는 정상 랭크되어야 한다."""
    _install_mocks(monkeypatch)
    result = sd_mod.discover_candidates(use_cache=False, top_n=10)
    assert "GGG" not in set(result["ticker"])
    assert "AAA" in set(result["ticker"])
    assert "FFF" in set(result["ticker"])  # 펀더멘털 결측이어도 가격 데이터가 있으면 포함


def test_custom_weights_change_order(monkeypatch):
    """value에 극단적으로 큰 가중치를 주면 기본 가중치와 다른 1위가 나올 수 있는 케이스를 검증."""
    _install_mocks(monkeypatch)
    default_result = sd_mod.discover_candidates(use_cache=False, top_n=10)

    momentum_only_weights = {"momentum": 1.0, "growth": 0.0, "value": 0.0, "quality": 0.0}
    momentum_result = sd_mod.discover_candidates(use_cache=False, top_n=10, weights=momentum_only_weights)

    value_only_weights = {"momentum": 0.0, "growth": 0.0, "value": 1.0, "quality": 0.0}
    value_result = sd_mod.discover_candidates(use_cache=False, top_n=10, weights=value_only_weights)

    # 모멘텀만 볼 때는 AAA(가장 강한 상승), 가치만 볼 때는 AAA(가장 낮은 PER/PBR)가 1위 -> 대신
    # BBB(최악의 모멘텀+최악의 가치)의 순위가 momentum-only와 value-only 사이에서 달라지는지로 확인.
    momentum_rank = list(momentum_result["ticker"]).index("BBB")
    value_rank = list(value_result["ticker"]).index("BBB")
    assert momentum_result.iloc[0]["ticker"] == "AAA"
    assert value_result.iloc[0]["ticker"] == "AAA"
    # BBB는 모멘텀(하락)과 가치(고평가) 둘 다에서 최하위권이어야 하지만, 최소한 가중치를 바꾸면
    # 전체 순서(list)가 달라짐을 확인해 custom weights가 실제로 결과에 영향을 준다는 것을 보장.
    assert list(momentum_result["ticker"]) != list(value_result["ticker"])
    assert not default_result.empty


def test_universe_n_limits_scanned_tickers(monkeypatch):
    _install_mocks(monkeypatch)
    result = sd_mod.discover_candidates(use_cache=False, top_n=10, universe_n=2)
    # universe_n=2 -> 유니버스 앞 2개(AAA, BBB)만 스캔되므로 나머지는 절대 포함될 수 없음
    assert set(result["ticker"]) <= {"AAA", "BBB"}
