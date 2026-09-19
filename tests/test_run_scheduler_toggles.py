"""scheduler/run_scheduler.py의 잡들이 core.process_registry.is_enabled()를 존중하는지 검증한다.

모든 잡 함수를 다 찍어보지는 않는다(반복적) — strategy_nightly_tuning_job(기본값이 꺼짐으로
바뀐 당사자)과, 대표로 알림류/유지보수류 각각 하나씩만 확인해 가드 패턴 자체가 제대로 동작함을
검증한다. 실제 작업(DB 조회, API 호출 등)까지 가지 않고 가드에서 바로 return하는지만 본다.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from core import process_registry
from scheduler import run_scheduler


@pytest.fixture(autouse=True)
def _isolate_toggle_state(monkeypatch, tmp_path):
    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", tmp_path / "process_toggles.json")


def test_strategy_nightly_tuning_job_disabled_by_default_does_nothing(monkeypatch):
    called = {"hit": False}
    monkeypatch.setattr(run_scheduler, "get_session", lambda: called.update(hit=True) or (_ for _ in ()).throw(AssertionError("should not reach DB")))

    run_scheduler.strategy_nightly_tuning_job()

    assert called["hit"] is False


def test_strategy_nightly_tuning_job_runs_when_explicitly_enabled(monkeypatch):
    process_registry.set_enabled("strategy_nightly_tuning", True)
    from contextlib import contextmanager

    @contextmanager
    def _fake_session():
        class _Session:
            def get(self, model, pk):
                return None  # 전략을 못 찾은 것처럼 만들어 얕게(가드 통과만) 확인
        yield _Session()

    monkeypatch.setattr(run_scheduler, "get_session", _fake_session)

    run_scheduler.strategy_nightly_tuning_job()  # 예외 없이 "전략을 찾을 수 없음" 경로로 조용히 종료되면 성공


def test_champion_signal_alert_job_skips_when_disabled(monkeypatch):
    process_registry.set_enabled("champion_signal_alert", False)
    called = {"hit": False}
    monkeypatch.setattr(
        run_scheduler, "check_and_notify_signal_changes",
        lambda *a, **kw: called.update(hit=True),
    )

    run_scheduler.champion_signal_alert_job()

    assert called["hit"] is False


def test_champion_signal_alert_job_runs_when_enabled(monkeypatch):
    called = {"hit": False}
    monkeypatch.setattr(
        run_scheduler, "check_and_notify_signal_changes",
        lambda *a, **kw: called.update(hit=True) or {"changed": False, "message": None},
    )

    run_scheduler.champion_signal_alert_job()

    assert called["hit"] is True


def test_data_integrity_check_job_skips_when_disabled(monkeypatch):
    process_registry.set_enabled("data_integrity_check", False)
    called = {"hit": False}
    import core.data_integrity as data_integrity
    monkeypatch.setattr(data_integrity, "run_integrity_checks", lambda: called.update(hit=True))

    run_scheduler.data_integrity_check_job()

    assert called["hit"] is False


def test_all_registered_job_keys_have_a_corresponding_scheduler_job():
    import inspect

    source = inspect.getsource(run_scheduler)
    for key in process_registry.PROCESS_REGISTRY:
        assert f'is_enabled("{key}")' in source, f"{key}에 대응하는 가드가 scheduler/run_scheduler.py에 없습니다"
