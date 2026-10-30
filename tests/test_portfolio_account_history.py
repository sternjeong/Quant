"""외부 입금만 벤치마크에 복제하고 내부 매매는 계좌 손익으로 처리한다."""

from datetime import date
from contextlib import contextmanager

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core import portfolio_account_history as pah
from core.models import PortfolioPerformanceBaseline, PortfolioPerformanceEvent


def _prices(tickers, **_kwargs):
    dates = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05"])
    values = {"AAA": [100, 105, 110], "BBB": [50, 55, 60]}
    return {t: pd.DataFrame({"Close": values[t]}, index=dates) for t in tickers}


def test_salary_deposit_goes_into_both_benchmarks_but_personal_may_hold_cash():
    dates = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05"])
    ledger = {"as_of": "2026-10-01", "cash_usd": 1000, "positions": {},
              "events": [{"as_of": "2026-10-02", "kind": "DEPOSIT", "amount_usd": 1000},
                         {"as_of": "2026-10-05", "kind": "BUY", "ticker": "AAA",
                          "quantity": 10, "price_usd": 100, "fee_usd": 1}]}
    actual = pah.account_curve(ledger, dates, price_fn=_prices)
    assert actual["nav"].tolist() == pytest.approx([1000, 2000, 2099])
    assert actual["flows"].tolist() == [0, 1000, 0]
    assert actual["ticker_pnl"]["AAA"] == pytest.approx(99)
    assert actual["daily_ticker_pnl"]["AAA"].tolist() == pytest.approx([0, 0, 99])
    allocation = [{"date": d.date().isoformat(), "allocation": [
        {"sleeve": "코어", "ticker": "AAA", "weight": 0.85},
        {"sleeve": "현금", "ticker": "CASH", "weight": 0.15}]}
                  for d in dates]
    result = pah.matched_benchmarks(pd.Series([1, 1.1, 1.21], index=dates),
                                    pd.Series([1, .9, .99], index=dates), actual,
                                    daily_allocation=allocation)
    fee = 0.85 * .0003
    assert result["champion"].tolist() == pytest.approx([1000, 2100 - 1000 * fee,
                                                         1210 + (1000 - 1000 * fee) * 1.1])
    assert result["spy"].tolist() == pytest.approx([1000, 1900, 2090])
    assert result["net_deposits_usd"] == 2000
    assert result["profit_usd"]["personal"] == pytest.approx(99)


def test_sell_and_rebuy_are_not_new_money_and_fees_reduce_actual_profit():
    dates = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05"])
    ledger = {"as_of": "2026-10-01", "cash_usd": 0, "positions": {"AAA": 10},
              "events": [{"as_of": "2026-10-02", "kind": "SELL", "ticker": "AAA",
                          "quantity": 10, "price_usd": 104, "fee_usd": 1},
                         {"as_of": "2026-10-02", "kind": "BUY", "ticker": "BBB",
                          "quantity": 10, "price_usd": 55, "fee_usd": 1}]}
    actual = pah.account_curve(ledger, dates, price_fn=_prices)
    assert actual["flows"].sum() == 0
    assert actual["nav"].tolist() == pytest.approx([1000, 1038, 1088])
    assert sum(actual["ticker_pnl"].values()) == pytest.approx(88)
    result = pah.matched_benchmarks(pd.Series([1, 1, 1], index=dates),
                                    pd.Series([1, 1, 1], index=dates), actual)
    assert result["champion"].tolist() == [1000, 1000, 1000]


def test_withdrawal_proportionally_reduces_comparison_units():
    dates = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05"])
    actual = {"nav": pd.Series([1000, 500, 500], index=dates),
              "flows": pd.Series([0, -500, 0], index=dates), "start_value": 1000}
    allocation = [{"date": d.date().isoformat(), "allocation": [
        {"sleeve": "현금", "ticker": "CASH", "weight": 1.0}]} for d in dates]
    result = pah.matched_benchmarks(pd.Series([1, 1.1, 1.21], index=dates),
                                    pd.Series([1, 1.1, 1.21], index=dates), actual,
                                    daily_allocation=allocation)
    assert result["spy"].tolist() == pytest.approx([1000, 600, 660])
    assert result["profit_usd"]["spy"] == pytest.approx(160)


def test_later_start_pays_champion_initial_entry_fee_once():
    dates = pd.to_datetime(["2026-10-01", "2026-10-02"])
    actual = {"nav": pd.Series([1000.0], index=dates[1:]),
              "flows": pd.Series([0.0], index=dates[1:]), "start_value": 1000}
    allocation = [{"date": "2026-10-02", "allocation": [
        {"sleeve": "코어", "ticker": "AAA", "weight": 1.0}]}]
    matched = pah.matched_benchmarks(pd.Series([1, 1.1], index=dates),
                                     pd.Series([1, 1.1], index=dates), actual,
                                     daily_allocation=allocation,
                                     ticker_pnl_daily=[])
    assert matched["champion"].iloc[0] == pytest.approx(999.7)
    assert matched["spy"].iloc[0] == 1000
    assert matched["champion_ticker_pnl"] == {("코어", "AAA"): pytest.approx(-.3)}


def test_missing_price_of_held_position_fails():
    dates = pd.to_datetime(["2026-10-01", "2026-10-02"])
    ledger = {"as_of": "2026-10-01", "cash_usd": 0, "positions": {"AAA": 1}, "events": []}
    def missing(tickers, **_kwargs):
        return {"AAA": pd.DataFrame({"Close": [100, None]}, index=dates)}
    with pytest.raises(ValueError, match="AAA 2026-10-02 종가"):
        pah.account_curve(ledger, dates, price_fn=missing)


def test_dividend_is_internal_profit_and_not_repeated_in_benchmarks():
    dates = pd.to_datetime(["2026-10-01", "2026-10-02"])
    ledger = {"as_of": "2026-10-01", "cash_usd": 0, "positions": {"AAA": 1},
              "events": [{"as_of": "2026-10-02", "kind": "DIVIDEND",
                          "ticker": "AAA", "amount_usd": 5}]}
    actual = pah.account_curve(ledger, dates, price_fn=lambda tickers, **kwargs: {
        "AAA": pd.DataFrame({"Close": [100, 105]}, index=dates)})
    assert actual["flows"].sum() == 0
    assert actual["ticker_pnl"]["AAA"] == pytest.approx(10)
    assert actual["daily_ticker_pnl"]["AAA"].tolist() == pytest.approx([0, 10])
    matched = pah.matched_benchmarks(pd.Series([1, 1], index=dates),
                                     pd.Series([1, 1], index=dates), actual)
    assert matched["profit_usd"]["personal"] == pytest.approx(10)
    assert matched["profit_usd"]["spy"] == 0


def test_persisted_ledger_validates_cash_and_keeps_sales_internal(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'account.db'}")
    PortfolioPerformanceBaseline.__table__.create(engine)
    PortfolioPerformanceEvent.__table__.create(engine)

    @contextmanager
    def session():
        with Session(engine) as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    monkeypatch.setattr(pah, "get_session", session)
    pah.save_baseline(date(2026, 10, 1), 100, [{"ticker": "AAA", "quantity": 1}])
    with pytest.raises(ValueError, match="현금이 부족"):
        pah.append_event(date(2026, 10, 2), "BUY", ticker="BBB", quantity=3, price_usd=50)
    assert pah.load_ledger()["events"] == []
    pah.append_event(date(2026, 10, 2), "SELL", ticker="AAA", quantity=1, price_usd=105)
    pah.append_event(date(2026, 10, 2), "BUY", ticker="BBB", quantity=3, price_usd=50)
    assert [e["kind"] for e in pah.load_ledger()["events"]] == ["SELL", "BUY"]
    with pytest.raises(ValueError, match="사건이 있어"):
        pah.delete_baseline_without_events()
    pah.delete_last_event()
    assert [e["kind"] for e in pah.load_ledger()["events"]] == ["SELL"]
