"""core/process_registry.py 단위 테스트. 파일 기반 상태라 tmp_path로 격리한다."""

import pytest

from core import process_registry


@pytest.fixture(autouse=True)
def _isolate_state_file(monkeypatch, tmp_path):
    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", tmp_path / "process_toggles.json")


def test_is_enabled_uses_registry_default_when_no_saved_state():
    assert process_registry.is_enabled("champion_signal_alert") is True
    assert "strategy_nightly_tuning" not in process_registry.PROCESS_REGISTRY  # 2026-09-24 삭제


def test_is_enabled_unknown_key_defaults_true():
    assert process_registry.is_enabled("totally_made_up_key") is True


def test_set_enabled_persists_and_overrides_default():
    process_registry.set_enabled("champion_signal_alert", False, actor="user")
    assert process_registry.is_enabled("champion_signal_alert") is False
    process_registry.set_enabled("champion_signal_alert", True, actor="user")
    assert process_registry.is_enabled("champion_signal_alert") is True


def test_set_enabled_rejects_unknown_key():
    with pytest.raises(ValueError):
        process_registry.set_enabled("not_a_real_process", False)


def test_set_enabled_records_timestamp_and_actor():
    result = process_registry.set_enabled("data_integrity_check", False, actor="telegram:12345")
    assert result["enabled"] is False
    assert result["actor"] == "telegram:12345"
    assert result["updated_at"]


def test_list_processes_reflects_registry_order_and_defaults():
    processes = process_registry.list_processes()
    keys = [p["key"] for p in processes]
    assert keys == list(process_registry.PROCESS_REGISTRY.keys())
    signal = next(p for p in processes if p["key"] == "champion_signal_alert")
    assert signal["enabled"] is True


def test_list_processes_reflects_saved_overrides():
    process_registry.set_enabled("champion_signal_alert", False)
    processes = process_registry.list_processes()
    signal = next(p for p in processes if p["key"] == "champion_signal_alert")
    assert signal["enabled"] is False
    assert signal["updated_at"] is not None


def test_state_file_persists_across_reloads(tmp_path):
    process_registry.set_enabled("champion_earnings_reminder", False)
    # 새로 읽어도(다른 프로세스가 다시 시작해도) 같은 값이 나와야 한다 — 파일에 실제로 쓰였는지 확인.
    assert process_registry.TOGGLE_STATE_PATH.exists()
    reloaded = process_registry._load_state()
    assert reloaded["champion_earnings_reminder"]["enabled"] is False
