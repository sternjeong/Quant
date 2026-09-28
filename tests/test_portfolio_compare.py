"""core/portfolio_compare.py — 여러 포트폴리오를 나란히 비교하는 기록·계산."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pandas as pd
import pytest

from core import portfolio_compare


@pytest.fixture(autouse=True)
def patched_session(db_session, monkeypatch):
    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(portfolio_compare, "get_session", _fake_get_session)
    return db_session


def _prices(ticker_to_closes: dict[str, list[float]], start: str = "2026-01-02") -> dict[str, pd.DataFrame]:
    """영업일 기준 종가 시계열."""
    return {
        ticker: pd.DataFrame({"Close": closes}, index=pd.bdate_range(start=start, periods=len(closes)))
        for ticker, closes in ticker_to_closes.items()
    }


# ---- 저장 ---------------------------------------------------------------------------------------

def test_create_and_list_portfolios():
    first = portfolio_compare.create_portfolio("내 포트폴리오", date(2026, 1, 2), note="실제 매수")
    portfolio_compare.create_portfolio("그냥 SPY", date(2026, 1, 2), kind="benchmark")

    rows = portfolio_compare.list_portfolios()
    assert [r["name"] for r in rows] == ["내 포트폴리오", "그냥 SPY"]
    assert rows[0]["id"] == first and rows[0]["kind"] == "actual" and rows[1]["kind"] == "benchmark"


def test_duplicate_name_and_bad_input_are_refused():
    portfolio_compare.create_portfolio("A", date(2026, 1, 2))
    with pytest.raises(ValueError, match="이미 있습니다"):
        portfolio_compare.create_portfolio("A", date(2026, 1, 2))
    with pytest.raises(ValueError, match="이름"):
        portfolio_compare.create_portfolio("   ", date(2026, 1, 2))
    with pytest.raises(ValueError):
        portfolio_compare.create_portfolio("B", date(2026, 1, 2), kind="nonsense")


def test_trades_record_buys_and_sells():
    pid = portfolio_compare.create_portfolio("A", date(2026, 1, 2))
    portfolio_compare.add_trade(pid, "aapl", date(2026, 1, 2), 10, 100.0)
    portfolio_compare.add_trade(pid, "AAPL", date(2026, 2, 2), -4, 120.0, fee_usd=1.5)

    trades = portfolio_compare.list_trades(pid)
    assert [t["ticker"] for t in trades] == ["AAPL", "AAPL"]  # 대문자로 정규화
    assert trades[0]["shares"] == 10 and trades[1]["shares"] == -4
    assert trades[1]["fee_usd"] == 1.5


def test_trade_validation():
    pid = portfolio_compare.create_portfolio("A", date(2026, 1, 2))
    with pytest.raises(ValueError, match="티커"):
        portfolio_compare.add_trade(pid, "", date(2026, 1, 2), 1, 10.0)
    with pytest.raises(ValueError, match="주수"):
        portfolio_compare.add_trade(pid, "AAPL", date(2026, 1, 2), 0, 10.0)
    with pytest.raises(ValueError, match="단가"):
        portfolio_compare.add_trade(pid, "AAPL", date(2026, 1, 2), 1, 0)
    with pytest.raises(ValueError, match="포트폴리오"):
        portfolio_compare.add_trade(9999, "AAPL", date(2026, 1, 2), 1, 10.0)


def test_archive_hides_without_deleting():
    pid = portfolio_compare.create_portfolio("A", date(2026, 1, 2))
    portfolio_compare.add_trade(pid, "AAPL", date(2026, 1, 2), 1, 10.0)
    portfolio_compare.archive_portfolio(pid)

    assert portfolio_compare.list_portfolios() == []
    archived = portfolio_compare.list_portfolios(include_archived=True)
    assert len(archived) == 1 and archived[0]["archived_at"] is not None
    assert portfolio_compare.list_trades(pid)  # 거래는 그대로 남는다

    portfolio_compare.archive_portfolio(pid, archived=False)
    assert len(portfolio_compare.list_portfolios()) == 1


def test_delete_trade():
    pid = portfolio_compare.create_portfolio("A", date(2026, 1, 2))
    tid = portfolio_compare.add_trade(pid, "AAPL", date(2026, 1, 2), 1, 10.0)
    assert portfolio_compare.delete_trade(tid) is True
    assert portfolio_compare.list_trades(pid) == []
    assert portfolio_compare.delete_trade(tid) is False


def test_shares_for_amount_supports_fractional_buying():
    assert portfolio_compare.shares_for_amount(400.0, 1000.0) == 2.5
    with pytest.raises(ValueError):
        portfolio_compare.shares_for_amount(0, 1000.0)


# ---- 수익률 계산 ---------------------------------------------------------------------------------

def _evaluate(trades, prices, fx=None, today=date(2026, 1, 9), started=date(2026, 1, 2)):
    portfolio = {"id": 1, "name": "T", "kind": "actual", "started_on": started}
    return portfolio_compare.evaluate_portfolio(portfolio, trades, prices, fx, today)


def test_a_frozen_portfolio_return_matches_the_price_move():
    """한 번 사고 가만히 두면 수익률은 그냥 주가 상승률이어야 한다."""
    trades = [{"ticker": "AAA", "trade_date": date(2026, 1, 2), "shares": 10, "price_usd": 100.0, "fee_usd": 0.0}]
    prices = _prices({"AAA": [100, 110, 120, 120, 150]})

    out = _evaluate(trades, prices)

    assert out["error"] is None
    assert out["value_usd"] == pytest.approx(1500.0)
    assert out["cost_usd"] == pytest.approx(1000.0)
    assert out["return_pct_usd"] == pytest.approx(50.0)
    assert out["twr_pct_usd"] == pytest.approx(50.0, abs=1e-6)  # 유입이 한 번뿐이면 TWR = 단순 수익률


def test_later_deposit_does_not_inflate_the_time_weighted_return():
    """나중에 돈을 더 넣었다고 성적이 좋아 보이면 안 된다 — 비교의 공정성이 이 기능의 핵심이다."""
    trades = [
        {"ticker": "AAA", "trade_date": date(2026, 1, 2), "shares": 1, "price_usd": 100.0, "fee_usd": 0.0},
        {"ticker": "AAA", "trade_date": date(2026, 1, 6), "shares": 100, "price_usd": 110.0, "fee_usd": 0.0},
    ]
    prices = _prices({"AAA": [100, 110, 110, 110, 110]})

    out = _evaluate(trades, prices)

    # 주가는 100 → 110 (10%)만 올랐다. 추가 매수는 그 뒤라 수익률을 바꾸면 안 된다.
    assert out["twr_pct_usd"] == pytest.approx(10.0, abs=1e-6)
    assert out["value_usd"] == pytest.approx(101 * 110.0)


def test_selling_reduces_holdings_without_faking_a_loss():
    trades = [
        {"ticker": "AAA", "trade_date": date(2026, 1, 2), "shares": 10, "price_usd": 100.0, "fee_usd": 0.0},
        {"ticker": "AAA", "trade_date": date(2026, 1, 6), "shares": -5, "price_usd": 120.0, "fee_usd": 0.0},
    ]
    prices = _prices({"AAA": [100, 120, 120, 120, 120]})

    out = _evaluate(trades, prices)

    assert out["value_usd"] == pytest.approx(5 * 120.0)  # 5주만 남는다
    assert out["twr_pct_usd"] == pytest.approx(20.0, abs=1e-6)  # 판 것 때문에 손실로 보이지 않는다


def test_multiple_tickers_are_summed():
    trades = [
        {"ticker": "AAA", "trade_date": date(2026, 1, 2), "shares": 10, "price_usd": 100.0, "fee_usd": 0.0},
        {"ticker": "BBB", "trade_date": date(2026, 1, 2), "shares": 5, "price_usd": 200.0, "fee_usd": 0.0},
    ]
    prices = _prices({"AAA": [100, 100, 100, 100, 110], "BBB": [200, 200, 200, 200, 200]})

    out = _evaluate(trades, prices)

    assert out["tickers"] == ["AAA", "BBB"]
    assert out["value_usd"] == pytest.approx(10 * 110 + 5 * 200)
    assert out["cost_usd"] == pytest.approx(2000.0)


def test_fees_count_as_money_put_in():
    trades = [{"ticker": "AAA", "trade_date": date(2026, 1, 2), "shares": 10, "price_usd": 100.0, "fee_usd": 50.0}]
    prices = _prices({"AAA": [100, 100, 100, 100, 100]})

    out = _evaluate(trades, prices)

    assert out["cost_usd"] == pytest.approx(1050.0)
    assert out["return_pct_usd"] < 0  # 수수료만큼은 실제로 손해다


def test_currency_effect_shows_up_as_a_gap_between_usd_and_krw():
    """달러로는 안 움직였는데 환율이 10% 오르면 원화 수익률만 10%여야 한다."""
    trades = [{"ticker": "AAA", "trade_date": date(2026, 1, 2), "shares": 10, "price_usd": 100.0, "fee_usd": 0.0}]
    prices = _prices({"AAA": [100, 100, 100, 100, 100]})
    fx = pd.Series([1300.0, 1300.0, 1300.0, 1300.0, 1430.0], index=pd.bdate_range("2026-01-02", periods=5))

    out = _evaluate(trades, prices, fx)

    assert out["twr_pct_usd"] == pytest.approx(0.0, abs=1e-6)
    assert out["twr_pct_krw"] == pytest.approx(10.0, abs=1e-6)
    assert out["value_krw"] == pytest.approx(1000 * 1430.0)


def test_missing_fx_still_reports_usd():
    trades = [{"ticker": "AAA", "trade_date": date(2026, 1, 2), "shares": 1, "price_usd": 100.0, "fee_usd": 0.0}]
    out = _evaluate(trades, _prices({"AAA": [100, 120, 120, 120, 120]}), fx=pd.Series(dtype=float))
    assert out["twr_pct_usd"] is not None and out["twr_pct_krw"] is None


def test_a_trade_on_a_market_holiday_lands_on_the_next_session():
    """휴장일(주말) 날짜로 입력해도 버려지지 않고 다음 거래일부터 반영돼야 한다."""
    saturday = date(2026, 1, 3)
    trades = [{"ticker": "AAA", "trade_date": saturday, "shares": 10, "price_usd": 100.0, "fee_usd": 0.0}]
    prices = _prices({"AAA": [100, 100, 100, 100, 130]})

    out = _evaluate(trades, prices)

    assert out["error"] is None
    assert out["value_usd"] == pytest.approx(1300.0)


def test_missing_price_data_is_reported_not_silently_zero():
    trades = [{"ticker": "NOPE", "trade_date": date(2026, 1, 2), "shares": 1, "price_usd": 10.0, "fee_usd": 0.0}]
    out = _evaluate(trades, _prices({"AAA": [100, 100]}))
    assert out["error"] and "NOPE" in out["error"]
    assert out["value_usd"] is None


def test_empty_portfolio_says_so():
    out = _evaluate([], {})
    assert out["error"] and "거래가 없습니다" in out["error"]


def test_start_date_in_the_future_is_reported():
    trades = [{"ticker": "AAA", "trade_date": date(2026, 1, 2), "shares": 1, "price_usd": 100.0, "fee_usd": 0.0}]
    out = _evaluate(trades, _prices({"AAA": [100, 100]}), started=date(2030, 1, 1))
    assert out["error"] and "시세가 없습니다" in out["error"]


def test_curve_starts_at_zero_percent_so_portfolios_can_be_compared():
    trades = [{"ticker": "AAA", "trade_date": date(2026, 1, 2), "shares": 1, "price_usd": 100.0, "fee_usd": 0.0}]
    out = _evaluate(trades, _prices({"AAA": [100, 110, 120, 120, 150]}))
    assert out["curve_usd"].iloc[0] == pytest.approx(0.0)
    assert out["curve_usd"].iloc[-1] == pytest.approx(50.0, abs=1e-6)


def test_evaluate_all_reads_saved_portfolios(monkeypatch):
    mine = portfolio_compare.create_portfolio("내 것", date(2026, 1, 2))
    spy = portfolio_compare.create_portfolio("그냥 SPY", date(2026, 1, 2), kind="benchmark")
    portfolio_compare.add_trade(mine, "AAA", date(2026, 1, 2), 10, 100.0)
    portfolio_compare.add_trade(spy, "SPY", date(2026, 1, 2), 2, 500.0)

    prices = _prices({"AAA": [100, 100, 100, 100, 150], "SPY": [500, 500, 500, 500, 505]})
    monkeypatch.setattr("core.market_data.get_multiple_price_history", lambda tickers, start=None: prices)
    monkeypatch.setattr("core.fred_data.get_series", lambda series_id, start=None: pd.Series(dtype=float))

    results = portfolio_compare.evaluate_all(today=date(2026, 1, 9))

    assert [r["name"] for r in results] == ["내 것", "그냥 SPY"]
    assert results[0]["twr_pct_usd"] == pytest.approx(50.0, abs=1e-6)
    assert results[1]["twr_pct_usd"] == pytest.approx(1.0, abs=1e-6)  # 내 선택이 더 나았다


def test_evaluate_all_survives_an_fx_outage(monkeypatch):
    pid = portfolio_compare.create_portfolio("A", date(2026, 1, 2))
    portfolio_compare.add_trade(pid, "AAA", date(2026, 1, 2), 1, 100.0)
    monkeypatch.setattr("core.market_data.get_multiple_price_history",
                        lambda tickers, start=None: _prices({"AAA": [100, 120]}))

    def _boom(series_id, start=None):
        raise RuntimeError("FRED down")

    monkeypatch.setattr("core.fred_data.get_series", _boom)
    results = portfolio_compare.evaluate_all(today=date(2026, 1, 9))
    assert results[0]["twr_pct_usd"] is not None  # 달러 기준은 계속 나온다
