"""core/db.py, core/models.py 기본 동작 검증."""

import json
from datetime import date

from core.models import (
    AlertLog,
    BacktestResult,
    GuruHolding,
    PortfolioHolding,
    Strategy,
    ThreadsSummary,
    WatchlistItem,
)


def test_create_strategy_and_watchlist(db_session):
    strategy = Strategy(
        name="골든크로스+RSI 눌림목",
        indicator_config=json.dumps(
            {
                "logic": "AND",
                "conditions": [
                    {"indicator": "ma_cross", "short": 20, "long": 60, "type": "golden"},
                    {"indicator": "rsi", "period": 14, "op": "<", "value": 30},
                ],
            }
        ),
        source="youtube_script",
    )
    db_session.add(strategy)
    db_session.commit()

    watch_item = WatchlistItem(ticker="AAPL", strategy_id=strategy.id)
    db_session.add(watch_item)
    db_session.commit()

    fetched = db_session.query(WatchlistItem).filter_by(ticker="AAPL").first()
    assert fetched is not None
    assert fetched.strategy.name == "골든크로스+RSI 눌림목"


def test_backtest_result(db_session):
    strategy = Strategy(name="후보1", indicator_config="{}", source="candidate")
    db_session.add(strategy)
    db_session.commit()

    result = BacktestResult(
        strategy_id=strategy.id,
        ticker="MSFT",
        start_date=date(2020, 1, 1),
        end_date=date(2024, 1, 1),
        cagr=12.5,
        mdd=-23.1,
        sharpe=1.1,
        win_rate=55.0,
        trade_count=42,
    )
    db_session.add(result)
    db_session.commit()

    fetched = db_session.query(BacktestResult).filter_by(ticker="MSFT").first()
    assert fetched.cagr == 12.5
    assert fetched.strategy.name == "후보1"


def test_threads_summary(db_session):
    summary = ThreadsSummary(
        raw_text="애플 실적 좋다는 글",
        tickers=json.dumps(["AAPL"]),
        ai_summary="애플 실적 호조 언급",
    )
    db_session.add(summary)
    db_session.commit()
    assert summary.id is not None


def test_guru_holding_and_portfolio_and_alert(db_session):
    guru = GuruHolding(
        guru_name="Warren Buffett",
        fund_name="Berkshire Hathaway",
        ticker="AAPL",
        shares=900000000,
        weight_pct=40.0,
        filing_date=date(2024, 3, 31),
    )
    holding = PortfolioHolding(
        ticker="AAPL",
        quantity=10,
        purchase_price=150.0,
        purchase_date=date(2023, 5, 1),
    )
    alert = AlertLog(ticker="AAPL", message="골든크로스 발생")

    db_session.add_all([guru, holding, alert])
    db_session.commit()

    assert guru.id is not None
    assert holding.id is not None
    assert alert.is_read is False
