"""core/db.py, core/models.py 기본 동작 검증."""

import json
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.db as db
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


def _fresh_engine(tmp_path, name="init_db_test.db"):
    return create_engine(f"sqlite:///{tmp_path / name}", connect_args={"check_same_thread": False})


def test_existing_portfolio_schema_adds_tracking_columns_without_changing_rows(monkeypatch, tmp_path):
    from sqlalchemy import text, inspect

    engine = _fresh_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE portfolio_holdings (id INTEGER PRIMARY KEY, ticker VARCHAR(20), quantity FLOAT)"))
        conn.execute(text("INSERT INTO portfolio_holdings VALUES (1, 'XLK', 3)"))
    monkeypatch.setattr(db, "engine", engine)
    db._add_missing_columns()
    assert {"strategy_role", "review_date"} <= {c["name"] for c in inspect(engine).get_columns("portfolio_holdings")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT ticker, quantity, strategy_role, review_date FROM portfolio_holdings")).one() == ("XLK", 3, None, None)


def test_init_db_runs_once_per_engine(monkeypatch, tmp_path):
    """같은 engine에 두 번 init_db()를 불러도 실제 초기화(테이블 생성)는 한 번만 수행된다."""
    engine = _fresh_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "_initialized_engine", None)

    calls = []
    original_add_missing = db._add_missing_columns

    def _counting_add_missing():
        calls.append(1)
        original_add_missing()

    monkeypatch.setattr(db, "_add_missing_columns", _counting_add_missing)

    db.init_db()
    db.init_db()

    assert len(calls) == 1


def test_init_db_reinitializes_after_engine_swap(monkeypatch, tmp_path):
    """engine이 교체되면(테스트의 monkeypatch 패턴) init_db()가 새 engine에도 다시 동작한다."""
    monkeypatch.setattr(db, "_initialized_engine", None)

    engine_a = _fresh_engine(tmp_path, "a.db")
    monkeypatch.setattr(db, "engine", engine_a)
    db.init_db()
    session_a = sessionmaker(bind=engine_a)()
    session_a.add(Strategy(name="a", indicator_config="{}", source="manual"))
    session_a.commit()
    session_a.close()

    engine_b = _fresh_engine(tmp_path, "b.db")
    monkeypatch.setattr(db, "engine", engine_b)
    db.init_db()
    session_b = sessionmaker(bind=engine_b)()
    # engine_b가 방금 초기화됐다면 테이블이 비어 있어야 한다(engine_a의 데이터가 섞이지 않음).
    assert session_b.query(Strategy).count() == 0
    session_b.close()


def test_add_missing_columns_skips_write_transaction_when_nothing_pending(monkeypatch, tmp_path):
    """추가할 컬럼이 없으면 engine.begin() 쓰기 트랜잭션을 아예 열지 않는다."""
    engine = _fresh_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "_initialized_engine", None)
    db.init_db()  # 최신 스키마로 생성 → 이후 _add_missing_columns 호출에서는 추가할 컬럼이 없어야 함

    original_begin = engine.begin
    begin_calls = []

    def _tracking_begin(*args, **kwargs):
        begin_calls.append(1)
        return original_begin(*args, **kwargs)

    monkeypatch.setattr(engine, "begin", _tracking_begin)

    db._add_missing_columns()

    assert begin_calls == []
