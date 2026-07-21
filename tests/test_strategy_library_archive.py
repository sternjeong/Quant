"""core/strategy_library.py 의 보관(archive)/복원(unarchive) 기능 단위 테스트 (DB 접근).

archive_strategy/unarchive_strategy는 삭제가 아니라 is_archived 플래그만 토글한다는 것,
list_strategies()는 기본적으로 보관된 전략을 제외하지만 include_archived=True면 전부
보여준다는 것을 검증한다.
"""

from contextlib import contextmanager

import pytest

import core.strategy_library as strategy_library
from core.models import Strategy


@pytest.fixture()
def patched_session(db_session, monkeypatch):
    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(strategy_library, "get_session", _fake_get_session)
    return db_session


def _make_strategy(db_session, name="테스트 전략") -> int:
    strategy = Strategy(name=name, indicator_config="{}", source="manual")
    db_session.add(strategy)
    db_session.commit()
    return strategy.id


def test_new_strategy_is_not_archived_by_default(patched_session):
    sid = _make_strategy(patched_session)
    ids = [s["id"] for s in strategy_library.list_strategies()]
    assert sid in ids


def test_archive_strategy_hides_from_default_list(patched_session):
    sid = _make_strategy(patched_session)
    strategy_library.archive_strategy(sid)

    active_ids = [s["id"] for s in strategy_library.list_strategies()]
    assert sid not in active_ids

    all_ids = [s["id"] for s in strategy_library.list_strategies(include_archived=True)]
    assert sid in all_ids


def test_archive_does_not_delete(patched_session):
    sid = _make_strategy(patched_session)
    strategy_library.archive_strategy(sid)

    strategy = strategy_library.get_strategy(sid)
    assert strategy is not None
    assert strategy["is_archived"] is True


def test_unarchive_restores_to_default_list(patched_session):
    sid = _make_strategy(patched_session)
    strategy_library.archive_strategy(sid)
    strategy_library.unarchive_strategy(sid)

    active_ids = [s["id"] for s in strategy_library.list_strategies()]
    assert sid in active_ids
    assert strategy_library.get_strategy(sid)["is_archived"] is False


def test_archive_unknown_strategy_raises():
    with pytest.raises(ValueError):
        strategy_library.archive_strategy(999999)


def test_unarchive_unknown_strategy_raises():
    with pytest.raises(ValueError):
        strategy_library.unarchive_strategy(999999)
