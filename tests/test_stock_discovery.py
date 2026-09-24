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


# ---- ENG-07: 업종 내 percentile / 결측 플래그 / 기여도 / PIT 메타 ----

def test_sector_percentile_ranks_within_sector_not_global():
    vals = pd.Series([1.0, 2.0, 3.0, 100.0, 200.0, 300.0])
    sectors = pd.Series(["A", "A", "A", "B", "B", "B"])
    score, fb = sd_mod._sector_percentile(vals, sectors)
    # 원시값이 훨씬 큰 B 업종이어도 업종 내 순위이므로 두 업종의 최고점은 동일
    assert score.iloc[2] == score.iloc[5] == 100.0
    assert score.iloc[0] == score.iloc[3]
    assert not fb.any()


def test_sector_percentile_small_sector_falls_back_and_flags():
    vals = pd.Series([1.0, 2.0, 3.0, 4.0, np.nan])
    sectors = pd.Series(["A", "A", "A", "B", "B"])
    score, fb = sd_mod._sector_percentile(vals, sectors)
    assert bool(fb.iloc[3]) is True  # B 는 유효 1개 -> 전체 대체 + 플래그
    assert score.iloc[4] == 0.0 and not fb.iloc[4]  # 결측은 0점, 대체 대상 아님


def test_result_has_missing_flags_and_contributions(monkeypatch):
    _install_mocks(monkeypatch)
    w = {"momentum": 0.3, "growth": 0.3, "value": 0.25, "quality": 0.15}
    raw = sd_mod.discover_candidates(use_cache=False, top_n=10, weights=w)
    for col in sd_mod.RESULT_COLUMNS:
        assert col in raw.columns
    res = raw.set_index("ticker")
    assert set(res.loc["FFF", "missing_factors"]) == {"growth", "value", "quality"}
    assert bool(res.loc["FFF", "growth_missing"]) and not bool(res.loc["AAA", "growth_missing"])
    assert res.loc["AAA", "n_missing_factors"] == 0
    for t in res.index:
        contrib = sum(res.loc[t, f"{f}_contrib"] for f in sd_mod.FACTORS)
        assert contrib == pytest.approx(res.loc[t, "composite_score"])


def test_fallback_flags_explicit(monkeypatch):
    _install_mocks(monkeypatch)
    res = sd_mod.discover_candidates(use_cache=False, top_n=10).set_index("ticker")
    # FFF: longName 없음 -> fundamentals 는 {} (v 가 all-None dict 이라 truthy) 이므로 name 대체가 flag 로 남는다
    assert "name_is_ticker" in res.loc["FFF", "fallback_flags"] or "name_from_fundamentals" in res.loc["FFF", "fallback_flags"]
    assert "value_loss_making" in res.loc["DDD", "fallback_flags"]
    # 2종목 업종뿐인 합성 유니버스 -> 업종 내 표본 부족 대체가 명시됨
    assert bool(res.loc["AAA", "sector_rank_fallback"])


def test_data_errors_recorded_not_silent(monkeypatch):
    _install_mocks(monkeypatch)

    def boom(ticker, use_cache=True):
        raise RuntimeError("x")

    monkeypatch.setattr(sd_mod.valuation, "fetch_valuation_inputs", boom)
    res = sd_mod.discover_candidates(use_cache=False, top_n=10)
    assert all("valuation_inputs" in e for e in res["data_errors"])


def test_pit_meta_marks_not_verified(monkeypatch):
    _install_mocks(monkeypatch)
    res = sd_mod.discover_candidates(use_cache=False, top_n=10)
    assert res.attrs["meta"]["pit_verified"] is False
    assert res.attrs["meta"]["as_of_filter_applied"] is False

    import core.point_in_time_universe as pit

    monkeypatch.setattr(pit, "get_constituents_as_of", lambda d: (_ for _ in ()).throw(ValueError("no data")))
    res2 = sd_mod.discover_candidates(use_cache=False, top_n=10, as_of_date="2020-01-01")
    assert res2.attrs["meta"]["pit_verified"] is False
    assert "no data" in res2.attrs["meta"]["as_of_filter_error"]
    assert not res2.empty
