"""core/watchlist.py 단위 테스트 (모듈 C: 관심 티커 + 타점 모니터링).

DB는 conftest.py 의 db_session(임시 SQLite) fixture를 사용하도록
core.watchlist.get_session 을 바꿔치기한다 (core.watchlist 는 모듈 최상단에서
`from core.db import get_session` 을 임포트해두므로, core.db 가 아니라
core.watchlist 모듈의 get_session 속성 자체를 patch해야 한다).

core.strategy_engine.evaluate() 는 core.watchlist 에 이미 바인딩되어 있으므로
네트워크 호출(yfinance)을 피하기 위해 core.watchlist.evaluate 를 monkeypatch 한다.
"""

from contextlib import contextmanager

import pytest

import core.watchlist as watchlist
from core.models import AlertLog, Strategy


@pytest.fixture()
def patched_session(db_session, monkeypatch):
    """core.watchlist.get_session 이 테스트 전용 db_session 을 쓰도록 바꿔치기."""

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(watchlist, "get_session", _fake_get_session)
    return db_session


def _make_strategy(db_session, name="테스트 전략") -> int:
    strategy = Strategy(name=name, indicator_config="{}", source="manual")
    db_session.add(strategy)
    db_session.commit()
    return strategy.id


def test_add_to_watchlist_creates_item(patched_session):
    item_id = watchlist.add_to_watchlist("aapl", strategy_id=None, memo="관찰중")
    assert item_id is not None

    items = watchlist.list_watchlist()
    assert len(items) == 1
    assert items[0]["ticker"] == "AAPL"  # 대문자로 정규화
    assert items[0]["memo"] == "관찰중"


def test_add_to_watchlist_upserts_existing_ticker(patched_session):
    strategy_id = _make_strategy(patched_session)

    first_id = watchlist.add_to_watchlist("AAPL", memo="첫메모")
    second_id = watchlist.add_to_watchlist("AAPL", strategy_id=strategy_id, memo="수정메모")

    assert first_id == second_id
    items = watchlist.list_watchlist()
    assert len(items) == 1
    assert items[0]["memo"] == "수정메모"
    assert items[0]["strategy_id"] == strategy_id


def test_add_to_watchlist_rejects_blank_ticker(patched_session):
    with pytest.raises(ValueError):
        watchlist.add_to_watchlist("   ")


def test_add_to_watchlist_enforces_max_size(patched_session, monkeypatch):
    monkeypatch.setattr(watchlist, "MAX_WATCHLIST_SIZE", 2)

    watchlist.add_to_watchlist("AAA")
    watchlist.add_to_watchlist("BBB")
    with pytest.raises(ValueError):
        watchlist.add_to_watchlist("CCC")

    assert watchlist.get_watchlist_count() == 2


def test_update_and_remove_watchlist_item(patched_session):
    strategy_id = _make_strategy(patched_session)
    item_id = watchlist.add_to_watchlist("MSFT")

    watchlist.update_watchlist_item(item_id, strategy_id=strategy_id, memo="업데이트됨")
    items = watchlist.list_watchlist()
    assert items[0]["strategy_id"] == strategy_id
    assert items[0]["memo"] == "업데이트됨"

    watchlist.remove_from_watchlist(item_id)
    assert watchlist.list_watchlist() == []


def test_scan_watchlist_triggers_alert_and_notifies(patched_session, monkeypatch):
    strategy_id = _make_strategy(patched_session, name="항상 신호 전략")
    watchlist.add_to_watchlist("AAPL", strategy_id=strategy_id)
    watchlist.add_to_watchlist("MSFT")  # 전략 미연결

    def _fake_evaluate(ticker, indicator_config, lookback_days=400):
        return {
            "triggered": True,
            "in_position": True,
            "as_of": "2024-01-02",
            "message": f"{ticker}: 전략 조건 충족(신규 진입 신호) — 기준일 2024-01-02",
        }

    monkeypatch.setattr(watchlist, "evaluate", _fake_evaluate)

    notified = []

    def _fake_notify(title, message):
        notified.append((title, message))

    results = watchlist.scan_watchlist(notify_fn=_fake_notify)

    by_ticker = {r.ticker: r for r in results}
    assert by_ticker["AAPL"].triggered is True
    assert by_ticker["MSFT"].strategy_id is None  # 전략 미연결 -> 건너뜀 처리

    assert len(notified) == 1
    assert notified[0][0] == "타점 발생: AAPL"

    alerts = patched_session.query(AlertLog).filter_by(ticker="AAPL").all()
    assert len(alerts) == 1


def test_scan_watchlist_handles_evaluate_exception(patched_session, monkeypatch):
    strategy_id = _make_strategy(patched_session)
    watchlist.add_to_watchlist("BADTICKER", strategy_id=strategy_id)

    def _raise(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(watchlist, "evaluate", _raise)

    results = watchlist.scan_watchlist()
    assert len(results) == 1
    assert results[0].triggered is False
    assert "스캔 실패" in results[0].message


def test_alert_read_helpers(patched_session):
    patched_session.add(AlertLog(ticker="AAPL", message="타점 발생"))
    patched_session.commit()

    assert watchlist.get_unread_alert_count() == 1
    alerts = watchlist.get_recent_alerts()
    assert len(alerts) == 1
    alert_id = alerts[0]["id"]

    watchlist.mark_alert_read(alert_id)
    assert watchlist.get_unread_alert_count() == 0

    patched_session.add(AlertLog(ticker="MSFT", message="타점 발생2"))
    patched_session.commit()
    assert watchlist.get_unread_alert_count() == 1

    watchlist.mark_all_alerts_read()
    assert watchlist.get_unread_alert_count() == 0
