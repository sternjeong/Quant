"""core/sector_leaders.py 단위 테스트 (섹터별 대표 ETF/대장주/성장주 관계 분석).

네트워크(yfinance)를 타지 않도록 core.screener/core.valuation/core.market_data 호출을 전부
monkeypatch 로 대체한다.
"""

import numpy as np
import pandas as pd
import pytest

import core.sector_leaders as sector_leaders


def _close_df(values: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.DataFrame({"Close": values}, index=idx)


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx)


def _price_path_from_returns(start: float, returns: np.ndarray) -> list[float]:
    prices = [start]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    return prices


# ----------------------------------------------------------------------------
# get_theme_candidate_tickers
# ----------------------------------------------------------------------------


def test_get_theme_candidate_tickers_gics_theme_filters_by_sector(monkeypatch):
    universe = pd.DataFrame(
        {
            "Symbol": ["AAPL", "MSFT", "JPM"],
            "Security": ["Apple", "Microsoft", "JPMorgan"],
            "Sector": ["Information Technology", "Information Technology", "Financials"],
        }
    )
    monkeypatch.setattr(sector_leaders.screener, "get_universe", lambda **k: universe)

    tickers = sector_leaders.get_theme_candidate_tickers("기술")
    assert set(tickers) == {"AAPL", "MSFT"}


def test_get_theme_candidate_tickers_niche_theme_uses_preset():
    tickers = sector_leaders.get_theme_candidate_tickers("반도체")
    assert "NVDA" in tickers
    assert "AVGO" in tickers


def test_get_theme_candidate_tickers_covers_2026_07_15_new_themes():
    # 방산이 우주에서 완전히 분리됐는지 + 냉각/사이버보안/클라우드/로보틱스가 새로 생겼는지 확인.
    assert "KTOS" in sector_leaders.get_theme_candidate_tickers("방산")
    assert "LMT" in sector_leaders.get_theme_candidate_tickers("방산")
    assert "LMT" not in sector_leaders.get_theme_candidate_tickers("우주")
    assert "ASTS" in sector_leaders.get_theme_candidate_tickers("우주")
    assert "VRT" in sector_leaders.get_theme_candidate_tickers("냉각")
    assert "CRWD" in sector_leaders.get_theme_candidate_tickers("사이버보안")
    assert "CRM" in sector_leaders.get_theme_candidate_tickers("클라우드")
    assert "ISRG" in sector_leaders.get_theme_candidate_tickers("로보틱스")


def test_get_theme_candidate_tickers_unknown_theme_returns_empty():
    assert sector_leaders.get_theme_candidate_tickers("존재하지않는테마") == []


# ----------------------------------------------------------------------------
# compute_leader_and_growth
# ----------------------------------------------------------------------------


def test_compute_leader_and_growth_picks_largest_market_cap_as_leader(monkeypatch):
    monkeypatch.setattr(sector_leaders, "get_theme_candidate_tickers", lambda theme: ["BIG", "MID", "SMALL"])

    fundamentals = {
        "BIG": {"name": "Big Corp", "market_cap": 3_000_000_000_000},
        "MID": {"name": "Mid Corp", "market_cap": 500_000_000_000},
        "SMALL": {"name": "Small Corp", "market_cap": 50_000_000_000},
    }
    valuations = {
        "BIG": {"earningsGrowth": 0.05, "trailingPE": 30},
        "MID": {"earningsGrowth": 0.40, "trailingPE": 25},
        "SMALL": {"earningsGrowth": 0.60, "trailingPE": 40},
    }
    monkeypatch.setattr(sector_leaders.screener, "get_fundamentals", lambda t, use_cache=True: fundamentals[t])
    monkeypatch.setattr(sector_leaders.valuation, "fetch_valuation_inputs", lambda t: valuations[t])

    result = sector_leaders.compute_leader_and_growth("기술", top_n_growth=2)
    assert result["candidates_count"] == 3
    assert result["leader"]["ticker"] == "BIG"

    growth_tickers = [g["ticker"] for g in result["growth_stocks"]]
    assert growth_tickers == ["SMALL", "MID"]  # 성장 점수 내림차순, 대장주(BIG)는 제외


def test_compute_leader_and_growth_falls_back_to_per_when_earnings_growth_missing(monkeypatch):
    monkeypatch.setattr(sector_leaders, "get_theme_candidate_tickers", lambda theme: ["A", "B", "C"])

    fundamentals = {
        "A": {"name": "A", "market_cap": 100},
        "B": {"name": "B", "market_cap": 90},
        "C": {"name": "C", "market_cap": 80},
    }
    # earningsGrowth가 전부 없으면 PER로 대체(고PER=성장주로 취급)
    valuations = {
        "A": {"earningsGrowth": None, "trailingPE": 10},
        "B": {"earningsGrowth": None, "trailingPE": 50},
        "C": {"earningsGrowth": None, "trailingPE": 20},
    }
    monkeypatch.setattr(sector_leaders.screener, "get_fundamentals", lambda t, use_cache=True: fundamentals[t])
    monkeypatch.setattr(sector_leaders.valuation, "fetch_valuation_inputs", lambda t: valuations[t])

    result = sector_leaders.compute_leader_and_growth("기술", top_n_growth=2)
    assert result["leader"]["ticker"] == "A"
    growth_tickers = [g["ticker"] for g in result["growth_stocks"]]
    assert growth_tickers[0] == "B"  # PER 50이 가장 높음 -> 성장 점수 1위


def test_compute_leader_and_growth_excludes_all_mega_caps_not_just_leader(monkeypatch):
    # 12개 후보 중 3개는 초대형주(2~3조 달러), 9개는 200억 달러 이하 중소형주. 대장주 한 종목만
    # 빼는 예전 방식이면 두 번째/세 번째로 큰 초대형주가 이익성장률만 높으면 "성장주"로 잡혔다 —
    # 이번엔 시가총액 상위 25%(여기선 3/12) 전체가 제외돼야 한다.
    non_mega_caps = {
        "N100": 100e9, "N90": 90e9, "N80": 80e9, "N70": 70e9, "N60": 60e9,
        "N50": 50e9, "N40": 40e9, "N30": 30e9, "N20": 20e9,
    }
    mega_caps = {"MEGA_BIGGEST": 3000e9, "MEGA_MID": 2500e9, "MEGA_SMALLEST": 2000e9}
    market_caps = {**non_mega_caps, **mega_caps}
    tickers = list(market_caps.keys())
    monkeypatch.setattr(sector_leaders, "get_theme_candidate_tickers", lambda theme: tickers)

    # MEGA_MID의 이익성장률을 가장 높게 줘서, "초대형주도 성장률만 높으면 성장주로 뽑히는" 예전
    # 버그가 재발하면 이 테스트가 바로 잡아낸다.
    earnings_growth = {t: 0.05 for t in tickers}
    earnings_growth["MEGA_MID"] = 0.95
    earnings_growth["N20"] = 0.50  # 비-초대형주 중에서는 성장률 1위

    fundamentals = {t: {"name": t, "market_cap": market_caps[t]} for t in tickers}
    valuations = {t: {"earningsGrowth": earnings_growth[t], "trailingPE": 20} for t in tickers}
    monkeypatch.setattr(sector_leaders.screener, "get_fundamentals", lambda t, use_cache=True: fundamentals[t])
    monkeypatch.setattr(sector_leaders.valuation, "fetch_valuation_inputs", lambda t: valuations[t])

    result = sector_leaders.compute_leader_and_growth("기술", top_n_growth=3)
    assert result["leader"]["ticker"] == "MEGA_BIGGEST"

    growth_tickers = {g["ticker"] for g in result["growth_stocks"]}
    assert growth_tickers.isdisjoint({"MEGA_BIGGEST", "MEGA_MID", "MEGA_SMALLEST"})
    assert "N20" in growth_tickers  # 비-초대형주 중 성장률 1위는 여전히 뽑혀야 함
    for g in result["growth_stocks"]:
        assert g["market_cap"] < 2000e9


def test_compute_leader_and_growth_empty_candidates_returns_empty_structure(monkeypatch):
    monkeypatch.setattr(sector_leaders, "get_theme_candidate_tickers", lambda theme: [])
    result = sector_leaders.compute_leader_and_growth("기술")
    assert result == {"theme": "기술", "candidates_count": 0, "leader": None, "growth_stocks": []}


# ----------------------------------------------------------------------------
# compute_relationship_metrics
# ----------------------------------------------------------------------------


def test_compute_relationship_metrics_perfect_tracker_has_beta_and_corr_near_one(monkeypatch):
    # 진짜 변동성이 있는(상수 아닌) 수익률 시퀀스를 써서 beta/corr 계산이 부동소수점 잡음이 아니라
    # 실제 공분산/분산 비율을 반영하는지 확인한다.
    rng = np.random.default_rng(7)
    etf_returns = rng.normal(loc=0.0005, scale=0.01, size=100)
    etf_prices = _price_path_from_returns(100.0, etf_returns)
    etf_series = _series(etf_prices)
    # 종목이 ETF와 정확히 동일한 수익률로 움직이면(시작가만 다름) beta=1, correlation=1,
    # RS비율(stock/etf)은 시작가 비율로 항상 일정 -> 추세 없음("횡보")
    stock_df = _close_df(_price_path_from_returns(50.0, etf_returns))
    monkeypatch.setattr(sector_leaders, "get_price_history", lambda t, start=None: stock_df)

    metrics = sector_leaders.compute_relationship_metrics("STOCK", etf_series)
    assert metrics is not None
    assert metrics["beta"] == pytest.approx(1.0, abs=1e-9)
    assert metrics["correlation"] == pytest.approx(1.0, abs=1e-9)
    assert metrics["rs_ratio_now"] == pytest.approx(100.0, abs=1e-6)  # 비율이 일정하므로 추세 없음
    assert metrics["trend"] == "횡보"


def test_compute_relationship_metrics_amplified_mover_has_beta_above_one(monkeypatch):
    # 종목 수익률 = ETF 수익률 * 2 (결정론적 선형관계) -> beta는 창/구간과 무관하게 정확히 2.0,
    # correlation은 1.0. 뚜렷한 상승 드리프트(일평균 0.3%)를 줘서 RS비율 추세 판정도 안정적으로 "상승".
    rng = np.random.default_rng(42)
    etf_returns = rng.normal(loc=0.003, scale=0.003, size=280)
    etf_series = _series(_price_path_from_returns(100.0, etf_returns))
    stock_df = _close_df(_price_path_from_returns(50.0, etf_returns * 2))
    monkeypatch.setattr(sector_leaders, "get_price_history", lambda t, start=None: stock_df)

    metrics = sector_leaders.compute_relationship_metrics("STOCK", etf_series)
    assert metrics is not None
    assert metrics["beta"] == pytest.approx(2.0, abs=1e-6)
    assert metrics["correlation"] == pytest.approx(1.0, abs=1e-6)
    assert metrics["trend"] == "상승"
    assert metrics["rs_change_3m"] > 0


def test_compute_relationship_metrics_abs_trend_up_when_price_above_200sma_and_golden_cross(monkeypatch):
    # 뚜렷한 상승 드리프트(일평균 0.3%)의 280거래일 시퀀스 -> 종가가 200일선 위 + 50일선이
    # 200일선 위(골든크로스)이므로 abs_trend는 "상승"이어야 한다.
    rng = np.random.default_rng(5)
    etf_returns = rng.normal(loc=0.003, scale=0.003, size=280)
    etf_series = _series(_price_path_from_returns(100.0, etf_returns))
    stock_df = _close_df(_price_path_from_returns(50.0, etf_returns))
    monkeypatch.setattr(sector_leaders, "get_price_history", lambda t, start=None: stock_df)

    metrics = sector_leaders.compute_relationship_metrics("STOCK", etf_series)
    assert metrics is not None
    assert metrics["abs_trend"] == "상승"


def test_compute_relationship_metrics_abs_trend_na_when_insufficient_history(monkeypatch):
    # 200일선 계산에 필요한 데이터(200거래일)보다 짧으면 abs_trend는 "N/A"여야 한다.
    etf_series = _series([100.0 * (1.002**i) for i in range(100)])
    stock_df = _close_df([50.0 * (1.002**i) for i in range(100)])
    monkeypatch.setattr(sector_leaders, "get_price_history", lambda t, start=None: stock_df)

    metrics = sector_leaders.compute_relationship_metrics("STOCK", etf_series)
    assert metrics is not None
    assert metrics["abs_trend"] == "N/A"


def test_compute_relationship_metrics_returns_none_when_no_price_data(monkeypatch):
    etf_series = _series([100.0] * 50)
    monkeypatch.setattr(sector_leaders, "get_price_history", lambda t, start=None: pd.DataFrame())
    assert sector_leaders.compute_relationship_metrics("STOCK", etf_series) is None


def test_compute_relationship_metrics_returns_none_when_overlap_too_short(monkeypatch):
    etf_series = _series([100.0] * 50)
    # 종목 데이터가 ETF와 겹치는 구간이 거의 없음(다른 날짜 범위)
    short_df = pd.DataFrame(
        {"Close": [10.0, 11.0]}, index=pd.date_range("2030-01-01", periods=2, freq="B")
    )
    monkeypatch.setattr(sector_leaders, "get_price_history", lambda t, start=None: short_df)
    assert sector_leaders.compute_relationship_metrics("STOCK", etf_series) is None


# ----------------------------------------------------------------------------
# analyze_theme_relationships (오케스트레이션)
# ----------------------------------------------------------------------------


def test_analyze_theme_relationships_attaches_metrics_to_leader_and_growth(monkeypatch):
    etf_series = _series([100.0 * (1.002**i) for i in range(280)])
    monkeypatch.setattr(sector_leaders, "THEME_UNIVERSE", {"기술": ["XLK"]})
    monkeypatch.setattr(sector_leaders, "theme_price_history", lambda proxies: etf_series)
    monkeypatch.setattr(
        sector_leaders,
        "compute_leader_and_growth",
        lambda theme, top_n_growth=3: {
            "theme": theme,
            "candidates_count": 3,
            "leader": {"ticker": "LEAD", "name": "Leader Co", "market_cap": 1_000_000_000_000},
            "growth_stocks": [
                {"ticker": "GROW1", "name": "Growth One", "earnings_growth": 0.5, "per": 40, "growth_score": 90.0}
            ],
        },
    )
    stock_df = _close_df([50.0 * (1.002**i) for i in range(280)])
    monkeypatch.setattr(sector_leaders, "get_price_history", lambda t, start=None: stock_df)

    result = sector_leaders.analyze_theme_relationships("기술")
    assert result["leader"]["ticker"] == "LEAD"
    assert result["leader"]["beta"] == pytest.approx(1.0, abs=1e-6)
    assert result["growth_stocks"][0]["ticker"] == "GROW1"
    assert result["growth_stocks"][0]["correlation"] == pytest.approx(1.0, abs=1e-6)
    assert set(result["chart_series"].keys()) == {"ETF", "LEAD", "GROW1"}
    assert result["chart_series"]["ETF"].iloc[0] == pytest.approx(100.0)


def test_analyze_theme_relationships_flags_lag_candidates(monkeypatch):
    # 대장주는 뚜렷한 절대 상승추세로 설정한다. 성장주 하나(LAGGER)는 대장주/ETF와 완전히 동일한
    # 수익률로 움직여 베타/상관계수는 1에 가깝지만(연동 강함), RS비율(종목가/ETF가)은 시작가 비율
    # 그대로라 "횡보"로 판정된다 -> 레깅 후보 조건(대장주 상승 + 연동 강함 + RS 미상승) 충족.
    # 다른 성장주(UNRELATED)는 완전히 무관한 수익률로 움직여 상관계수가 낮다 -> 레깅 후보 아님.
    rng = np.random.default_rng(11)
    etf_returns = rng.normal(loc=0.003, scale=0.003, size=280)
    etf_series = _series(_price_path_from_returns(100.0, etf_returns))
    leader_df = _close_df(_price_path_from_returns(200.0, etf_returns))
    lagger_df = _close_df(_price_path_from_returns(10.0, etf_returns))

    rng2 = np.random.default_rng(99)
    unrelated_returns = rng2.normal(loc=0.0, scale=0.02, size=280)
    unrelated_df = _close_df(_price_path_from_returns(10.0, unrelated_returns))

    price_by_ticker = {"LEAD": leader_df, "LAGGER": lagger_df, "UNRELATED": unrelated_df}
    monkeypatch.setattr(sector_leaders, "get_price_history", lambda t, start=None: price_by_ticker[t])
    monkeypatch.setattr(sector_leaders, "THEME_UNIVERSE", {"기술": ["XLK"]})
    monkeypatch.setattr(sector_leaders, "theme_price_history", lambda proxies: etf_series)
    monkeypatch.setattr(
        sector_leaders,
        "compute_leader_and_growth",
        lambda theme, top_n_growth=3: {
            "theme": theme,
            "candidates_count": 3,
            "leader": {"ticker": "LEAD", "name": "Leader Co", "market_cap": 1_000_000_000_000},
            "growth_stocks": [
                {"ticker": "LAGGER", "name": "Lagger Co", "market_cap": 1e10, "earnings_growth": 0.5, "per": 40, "growth_score": 90.0},
                {"ticker": "UNRELATED", "name": "Unrelated Co", "market_cap": 1e10, "earnings_growth": 0.3, "per": 20, "growth_score": 60.0},
            ],
        },
    )

    result = sector_leaders.analyze_theme_relationships("기술")
    assert result["leader"]["abs_trend"] == "상승"

    by_ticker = {g["ticker"]: g for g in result["growth_stocks"]}
    assert by_ticker["LAGGER"]["trend"] == "횡보"
    assert by_ticker["LAGGER"]["lag_candidate"] is True
    assert by_ticker["UNRELATED"]["lag_candidate"] is False


def test_analyze_theme_relationships_handles_missing_etf_data(monkeypatch):
    monkeypatch.setattr(sector_leaders, "THEME_UNIVERSE", {"기술": ["XLK"]})
    monkeypatch.setattr(sector_leaders, "theme_price_history", lambda proxies: None)
    monkeypatch.setattr(
        sector_leaders,
        "compute_leader_and_growth",
        lambda theme, top_n_growth=3: {
            "theme": theme, "candidates_count": 0, "leader": None, "growth_stocks": []
        },
    )

    result = sector_leaders.analyze_theme_relationships("기술")
    assert result["leader"] is None
    assert result["growth_stocks"] == []
    assert result["etf_series"] is None
