"""매수·매도 기록(core/portfolio_trades.py) — 문장 읽기, 보유 비율 축소, 현금·세금 반영, 되돌리기."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pandas as pd
import pytest

from core import portfolio, portfolio_trades as pt, tax_planner as tp

TODAY = date(2026, 11, 20)
FX = pd.Series([1000.0, 1400.0], index=pd.to_datetime(["2026-01-02", "2026-11-01"]))


@pytest.fixture()
def db(db_session, monkeypatch):
    @contextmanager
    def _fake():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(portfolio, "get_session", _fake)
    monkeypatch.setattr(pt, "get_session", _fake)
    from core import portfolio_account_history as ah

    monkeypatch.setattr(ah, "load_ledger", lambda: None)  # 장부 없음
    return db_session


def test_parse_free_order_dates_fee_and_sell_all():
    rows = pt.parse_trade_text("XLK 3주 매도 $210.5\n매수 SPY 2 @650.1 11/19\nXLE 전량 매도 95 수수료 0.5\n# 메모", TODAY)
    assert rows[0] == {"side": "SELL", "ticker": "XLK", "quantity": 3.0, "price": 210.5, "fee": 0.0, "trade_date": TODAY}
    assert rows[1]["side"] == "BUY" and rows[1]["trade_date"] == date(2026, 11, 19) and rows[1]["price"] == 650.1
    assert rows[2]["quantity"] is None and rows[2]["fee"] == 0.5
    assert pt.parse_trade_text("sell QQQ 1 400 12/31", TODAY)[0]["trade_date"] == date(2025, 12, 31)  # 미래 M/D → 작년


@pytest.mark.parametrize("bad", ["XLK 3 210", "매도 3 210", "XLK 매도 210", "XLK 3 매도", "XLK 전량 매수 10", "XLK 1 2 3 매도"])
def test_parse_rejects_incomplete_lines(bad):
    with pytest.raises(ValueError):
        pt.parse_trade_text(bad, TODAY)


def test_sell_shrinks_lots_keeps_average_and_updates_cash_and_tax(db):
    portfolio.add_holding("XLK", 2, 100.0, date(2026, 1, 5))
    portfolio.add_holding("XLK", 2, 200.0, date(2026, 6, 1))
    portfolio.set_cash_balance(10.0)
    tp.save_realized(2026, 0.0)
    [r] = pt.record_trades(pt.parse_trade_text("XLK 1 매도 250", TODAY), fx=FX)
    lots = [h for h in portfolio.list_holdings() if h["ticker"] == "XLK"]
    assert sum(h["quantity"] for h in lots) == pytest.approx(3.0)
    avg = sum(h["quantity"] * h["purchase_price"] for h in lots) / 3
    assert avg == pytest.approx(150.0)                                   # 이동평균 유지
    assert r["realized_usd"] == pytest.approx(100.0)
    assert portfolio.get_cash_balance() == pytest.approx(260.0)
    cost_krw = (2 * 100 + 2 * 200) * (1 + tp.KAKAO_FEE) * 1000 / 4      # 한 주의 원화 취득가(두 매입 모두 1000원대 환율)
    assert r["realized_krw"] == pytest.approx(250 * 1400 - cost_krw)
    assert tp.load_realized(2026) == pytest.approx(r["realized_krw"])


def test_sell_all_deletes_and_overselling_is_refused(db):
    portfolio.add_holding("XLE", 3, 60.0, date(2026, 1, 5))
    with pytest.raises(ValueError, match="많이 팔 수 없습니다"):
        pt.record_trades(pt.parse_trade_text("XLE 4 매도 70", TODAY), fx=FX)
    pt.record_trades(pt.parse_trade_text("XLE 전량 매도 70", TODAY), fx=FX)
    assert [h for h in portfolio.list_holdings() if h["ticker"] == "XLE"] == []


def test_buy_adds_lot_inherits_role_and_spends_cash(db):
    portfolio.add_holding("GEV", 1, 900.0, date(2026, 1, 5), strategy_role="새틀라이트")
    portfolio.set_cash_balance(1000.0)
    [r] = pt.record_trades(pt.parse_trade_text("GEV 1 매수 950 수수료 1", TODAY), fx=FX)
    lots = [h for h in portfolio.list_holdings() if h["ticker"] == "GEV"]
    assert len(lots) == 2 and all(h["strategy_role"] == "새틀라이트" for h in lots)
    assert portfolio.get_cash_balance() == pytest.approx(49.0) and r["realized_usd"] is None


def test_buy_beyond_cash_clamps_to_zero_with_warning(db):
    portfolio.set_cash_balance(5.0)
    [r] = pt.record_trades(pt.parse_trade_text("SPY 1 매수 650", TODAY), fx=FX)
    assert portfolio.get_cash_balance() == 0.0 and any("0 으로" in m for m in r["messages"])


def test_tax_untouched_when_year_not_entered(db):
    portfolio.add_holding("XLV", 1, 100.0, date(2026, 1, 5))
    [r] = pt.record_trades(pt.parse_trade_text("XLV 1 매도 120", TODAY), fx=FX)
    assert tp.load_realized(2026) is None and any("입력하지 않아" in m for m in r["messages"])


def test_undo_restores_lots_cash_and_tax(db):
    portfolio.add_holding("XLK", 2, 100.0, date(2026, 1, 5), thesis="근거")
    portfolio.set_cash_balance(10.0)
    tp.save_realized(2026, 500_000.0)
    pt.record_trades(pt.parse_trade_text("XLK 전량 매도 150", TODAY), fx=FX)
    info = pt.undo_last_trade()
    assert info["ticker"] == "XLK"
    [lot] = portfolio.list_holdings()
    assert (lot["quantity"], lot["purchase_price"], lot["thesis"]) == (2, 100.0, "근거")
    assert portfolio.get_cash_balance() == pytest.approx(10.0)
    assert tp.load_realized(2026) == pytest.approx(500_000.0)
    assert pt.list_trades() == []
    with pytest.raises(ValueError):
        pt.undo_last_trade()


def test_cli_dry_run_does_not_write(db, capsys, monkeypatch):
    import importlib.util
    from pathlib import Path

    from core import db as core_db

    monkeypatch.setattr(core_db, "init_db", lambda: None)
    spec = importlib.util.spec_from_file_location("ptcli", Path(__file__).resolve().parents[1] / "scripts" / "portfolio_trade.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    portfolio.add_holding("XLK", 2, 100.0, date(2026, 1, 5))
    assert cli.main(["XLK 1 매도 150", "--dry-run"]) == 0
    assert "2 → 1주" in capsys.readouterr().out
    assert sum(h["quantity"] for h in portfolio.list_holdings()) == 2
    assert cli.main(["XLK 5 매도 150"]) == 2
