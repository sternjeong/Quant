"""core/portfolio.py 단위 테스트 (모듈 H: 포트폴리오 관리)."""

from contextlib import contextmanager
from datetime import date

import pandas as pd
import pytest

import core.portfolio as portfolio


@pytest.fixture()
def patched_session(db_session, monkeypatch):
    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(portfolio, "get_session", _fake_get_session)
    return db_session


# ----------------------------------------------------------------------------
# CRUD
# ----------------------------------------------------------------------------


def test_add_and_list_holding(patched_session):
    holding_id = portfolio.add_holding("aapl", 10, 150.0, date(2024, 1, 15))
    assert isinstance(holding_id, int)

    holdings = portfolio.list_holdings()
    assert len(holdings) == 1
    assert holdings[0]["ticker"] == "AAPL"
    assert holdings[0]["quantity"] == 10


def test_add_holding_rejects_invalid_input(patched_session):
    with pytest.raises(ValueError):
        portfolio.add_holding("", 10, 150.0, date(2024, 1, 1))
    with pytest.raises(ValueError):
        portfolio.add_holding("AAPL", 0, 150.0, date(2024, 1, 1))
    with pytest.raises(ValueError):
        portfolio.add_holding("AAPL", 10, 0, date(2024, 1, 1))


def test_update_holding(patched_session):
    holding_id = portfolio.add_holding("AAPL", 10, 150.0, date(2024, 1, 1))
    portfolio.update_holding(holding_id, quantity=20)

    holdings = portfolio.list_holdings()
    assert holdings[0]["quantity"] == 20
    assert holdings[0]["purchase_price"] == 150.0


def test_update_holding_raises_for_missing_id(patched_session):
    with pytest.raises(ValueError):
        portfolio.update_holding(999, quantity=5)


def test_remove_holding(patched_session):
    holding_id = portfolio.add_holding("AAPL", 10, 150.0, date(2024, 1, 1))
    portfolio.remove_holding(holding_id)
    assert portfolio.list_holdings() == []


# ----------------------------------------------------------------------------
# compute_pnl
# ----------------------------------------------------------------------------


def test_compute_pnl_basic():
    holdings = [
        {"ticker": "AAPL", "quantity": 10, "purchase_price": 100.0},
        {"ticker": "MSFT", "quantity": 5, "purchase_price": 200.0},
    ]
    prices = {"AAPL": 150.0, "MSFT": 180.0}

    df = portfolio.compute_pnl(holdings, prices)

    aapl = df[df["ticker"] == "AAPL"].iloc[0]
    assert aapl["cost_basis"] == 1000.0
    assert aapl["market_value"] == 1500.0
    assert aapl["pnl"] == 500.0
    assert aapl["pnl_pct"] == pytest.approx(50.0)

    msft = df[df["ticker"] == "MSFT"].iloc[0]
    assert msft["pnl"] == -100.0  # 5*180 - 5*200 = -100

    total_value = 1500.0 + 900.0
    assert aapl["weight_pct"] == pytest.approx(1500.0 / total_value * 100)


def test_compute_pnl_handles_missing_price():
    holdings = [{"ticker": "UNKNOWN", "quantity": 1, "purchase_price": 100.0}]
    df = portfolio.compute_pnl(holdings, {"UNKNOWN": None})
    row = df.iloc[0]
    assert row["market_value"] is None
    assert row["pnl"] is None
    assert pd.isna(row["weight_pct"])


def test_compute_pnl_empty_holdings():
    df = portfolio.compute_pnl([], {})
    assert df.empty
    assert list(df.columns) == [
        "ticker",
        "quantity",
        "purchase_price",
        "current_price",
        "cost_basis",
        "market_value",
        "pnl",
        "pnl_pct",
        "weight_pct",
    ]


# ----------------------------------------------------------------------------
# 리스크 지표
# ----------------------------------------------------------------------------


def test_compute_daily_returns_aligns_common_dates():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    df_a = pd.DataFrame({"Close": [100, 102, 101, 105, 107]}, index=idx)
    df_b = pd.DataFrame({"Close": [50, 51, 49, 52, 53]}, index=idx)

    returns = portfolio.compute_daily_returns({"A": df_a, "B": df_b})
    assert list(returns.columns) == ["A", "B"]
    assert len(returns) == 4  # pct_change 로 첫 행 소실


def test_compute_daily_returns_skips_empty_df():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df_a = pd.DataFrame({"Close": [100, 101, 102]}, index=idx)
    returns = portfolio.compute_daily_returns({"A": df_a, "B": pd.DataFrame()})
    assert list(returns.columns) == ["A"]


def test_compute_daily_returns_empty_input():
    assert portfolio.compute_daily_returns({}).empty


def test_compute_portfolio_volatility():
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    returns = pd.DataFrame({"A": [0.01, -0.01, 0.02, -0.02], "B": [0.0, 0.0, 0.0, 0.0]}, index=idx)
    vol = portfolio.compute_portfolio_volatility(returns, {"A": 1.0, "B": 0.0})
    assert vol is not None
    assert vol > 0


def test_compute_portfolio_volatility_empty_returns():
    assert portfolio.compute_portfolio_volatility(pd.DataFrame(), {}) is None


def test_compute_correlation_matrix():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    returns = pd.DataFrame({"A": [0.01, 0.02, -0.01, 0.03, 0.0], "B": [0.01, 0.02, -0.01, 0.03, 0.0]}, index=idx)
    corr = portfolio.compute_correlation_matrix(returns)
    assert corr.loc["A", "B"] == pytest.approx(1.0)


def test_compute_sector_concentration():
    holdings_with_value = [
        {"ticker": "AAPL", "market_value": 300.0},
        {"ticker": "MSFT", "market_value": 300.0},
        {"ticker": "XOM", "market_value": 400.0},
    ]
    sectors = {"AAPL": "Technology", "MSFT": "Technology", "XOM": "Energy"}

    result = portfolio.compute_sector_concentration(holdings_with_value, sectors)
    assert result["Technology"] == pytest.approx(60.0)
    assert result["Energy"] == pytest.approx(40.0)


def test_compute_sector_concentration_unknown_sector_grouped_as_other():
    holdings_with_value = [{"ticker": "XYZ", "market_value": 100.0}]
    result = portfolio.compute_sector_concentration(holdings_with_value, {"XYZ": None})
    assert result == {"기타": 100.0}


def test_compute_sector_concentration_empty():
    assert portfolio.compute_sector_concentration([], {}) == {}


def test_get_portfolio_risk_returns_empty_defaults_for_empty_portfolio():
    result = portfolio.get_portfolio_risk(pnl_df=pd.DataFrame())
    assert result["volatility"] is None
    assert result["correlation"].empty
    assert result["sector_concentration"] == {}


# ----------------------------------------------------------------------------
# AI 코멘트
# ----------------------------------------------------------------------------


def test_generate_portfolio_comment_without_api_key_uses_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    pnl_df = portfolio.compute_pnl(
        [{"ticker": "AAPL", "quantity": 10, "purchase_price": 100.0}], {"AAPL": 150.0}
    )
    risk = {"volatility": 20.0, "sector_concentration": {"Technology": 100.0}}

    comment = portfolio.generate_portfolio_comment(pnl_df, risk)
    assert "자동 생성 실패" in comment
    assert "Technology" in comment


def test_generate_portfolio_comment_empty_portfolio(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    comment = portfolio.generate_portfolio_comment(pd.DataFrame(), {})
    assert "등록된 보유 종목이 없습니다" in comment


def test_generate_portfolio_comment_handles_api_failure_gracefully(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    class _FakeModels:
        @staticmethod
        def generate_content(**kwargs):
            raise RuntimeError("network down")

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    import google.genai as genai

    monkeypatch.setattr(genai, "Client", _FakeClient)

    pnl_df = portfolio.compute_pnl([{"ticker": "AAPL", "quantity": 1, "purchase_price": 100.0}], {"AAPL": 110.0})
    comment = portfolio.generate_portfolio_comment(pnl_df, {"volatility": None, "sector_concentration": {}})
    assert "AI 호출 실패" in comment
