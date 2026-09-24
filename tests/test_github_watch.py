"""deploy/github_watch.py — GitHub Actions 실패를 폰으로 전달하는 감시기.

실제 네트워크를 쓰지 않는다: fetch를 주입해 API 응답을 흉내 낸다.
"""

from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "github_watch.py"
spec = importlib.util.spec_from_file_location("github_watch", SCRIPT)
github_watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(github_watch)


def _run(run_id: int, name: str, conclusion: str, number: int = 1) -> dict:
    return {"id": run_id, "name": name, "conclusion": conclusion, "status": "completed",
            "run_number": number, "head_branch": "main", "html_url": f"https://github.com/x/y/actions/runs/{run_id}"}


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "github_watch.json"


def _watch(state_path, runs, **kwargs):
    alerts: list[str] = []
    outcome = github_watch.run_watch(
        "owner/repo", state_path, alert=alerts.append, fetch=lambda repo, limit: runs, **kwargs
    )
    return outcome, alerts


def test_first_run_records_state_without_shouting_about_the_past(state_path):
    """도입 직후 과거 실패 100건을 한꺼번에 쏟아내면 안 된다."""
    outcome, alerts = _watch(state_path, [_run(1, "Oracle capacity retry", "failure"),
                                          _run(2, "Uptime Check", "success")])
    assert outcome["first_run"] is True
    assert outcome["new_failures"] == 0 and alerts == []
    assert state_path.is_file()  # 다음 회차부터는 판정할 수 있게 상태는 남긴다


def test_a_new_failure_after_the_first_run_is_alerted_once(state_path):
    _watch(state_path, [_run(1, "Uptime Check", "success")])  # 기준선

    outcome, alerts = _watch(state_path, [_run(2, "Uptime Check", "failure", number=2),
                                          _run(1, "Uptime Check", "success")])
    assert outcome["new_failures"] == 1 and len(alerts) == 1
    assert "워크플로 실패 1건" in alerts[0] and "Uptime Check #2" in alerts[0]

    again, alerts2 = _watch(state_path, [_run(2, "Uptime Check", "failure", number=2)])
    assert again["new_failures"] == 0 and alerts2 == []  # 같은 실행을 두 번 알리지 않는다


def test_recovery_is_reported_once(state_path):
    _watch(state_path, [_run(1, "Uptime Check", "success")])
    _watch(state_path, [_run(2, "Uptime Check", "failure", number=2)])

    outcome, alerts = _watch(state_path, [_run(3, "Uptime Check", "success", number=3)])
    assert outcome["recovered"] == 1 and "복구됨 1건" in alerts[0]

    quiet, alerts2 = _watch(state_path, [_run(4, "Uptime Check", "success", number=4)])
    assert quiet["recovered"] == 0 and alerts2 == []  # 계속 성공하면 조용하다


def test_cancelled_and_skipped_runs_are_ignored(state_path):
    _watch(state_path, [_run(1, "Nightly", "success")])
    outcome, alerts = _watch(state_path, [_run(2, "Nightly", "cancelled"), _run(3, "Nightly", "skipped")])
    assert outcome["new_failures"] == 0 and alerts == []


@pytest.mark.parametrize("conclusion", ["failure", "timed_out", "startup_failure"])
def test_all_failure_kinds_count_as_failures(state_path, conclusion):
    _watch(state_path, [_run(1, "Nightly", "success")])
    outcome, alerts = _watch(state_path, [_run(2, "Nightly", conclusion)])
    assert outcome["new_failures"] == 1 and len(alerts) == 1


def test_several_failures_are_summarised_in_one_message(state_path):
    _watch(state_path, [_run(1, "A", "success")])
    runs = [_run(i, f"W{i}", "failure") for i in range(2, 12)]
    outcome, alerts = _watch(state_path, runs)
    assert outcome["new_failures"] == 10
    assert len(alerts) == 1  # 10개를 10통으로 보내지 않는다
    assert "외 4건" in alerts[0]


def test_api_failure_is_quiet_and_keeps_the_old_state(state_path):
    _watch(state_path, [_run(1, "Nightly", "success")])
    before = state_path.read_text()

    def _boom(repo, limit):
        raise urllib.error.URLError("network down")

    alerts: list[str] = []
    outcome = github_watch.run_watch("owner/repo", state_path, alert=alerts.append, fetch=_boom)

    assert outcome["error"] and alerts == []  # 일시 장애로 알림 스팸을 만들지 않는다
    assert state_path.read_text() == before


def test_dry_run_neither_alerts_nor_writes_state(state_path):
    _watch(state_path, [_run(1, "Nightly", "success")])
    before = state_path.read_text()
    outcome, alerts = _watch(state_path, [_run(2, "Nightly", "failure")], dry_run=True)
    assert outcome["new_failures"] == 1 and alerts == []
    assert state_path.read_text() == before


def test_state_file_does_not_grow_without_bound(state_path):
    _watch(state_path, [_run(1, "Nightly", "success")])
    for batch in range(3):
        _watch(state_path, [_run(1000 + batch * 100 + i, "Nightly", "success") for i in range(100)])
    seen = json.loads(state_path.read_text())["seen_run_ids"]
    assert len(seen) <= github_watch.KEEP_SEEN


def test_main_exits_zero_even_when_the_api_is_down(monkeypatch, capsys, state_path):
    monkeypatch.setattr(github_watch, "STATE_PATH", state_path)
    monkeypatch.setattr(github_watch, "fetch_runs", lambda repo, limit: (_ for _ in ()).throw(OSError("dns")))
    assert github_watch.main([]) == 0  # 타이머가 실패 상태로 남지 않게
    assert "건너뜀" in capsys.readouterr().err


def test_unwritable_state_suppresses_alerts_instead_of_spamming_every_run(tmp_path):
    """상태를 못 남기면 같은 실패를 15분마다 영원히 다시 알리게 된다 — 그럴 바엔 알리지 않는다.
    (2026-09-24 VM 배포에서 실제로 root 소유 디렉터리라 PermissionError가 났다.)"""
    blocked = tmp_path / "nodir" / "state.json"
    blocked.parent.mkdir()
    blocked.parent.chmod(0o500)  # 읽기·실행만 — 쓰기 불가
    try:
        alerts: list[str] = []
        outcome = github_watch.run_watch(
            "owner/repo", blocked, alert=alerts.append,
            fetch=lambda repo, limit: [_run(1, "Nightly", "failure")],
        )
        assert outcome["error"] and "상태 파일" in outcome["error"]
        assert alerts == []  # 알림 스팸을 만들지 않는다
    finally:
        blocked.parent.chmod(0o700)


def test_state_write_failure_surfaces_in_the_exit_code(monkeypatch, capsys, tmp_path):
    blocked = tmp_path / "nodir" / "state.json"
    blocked.parent.mkdir()
    blocked.parent.chmod(0o500)
    try:
        monkeypatch.setattr(github_watch, "STATE_PATH", blocked)
        monkeypatch.setattr(github_watch, "fetch_runs", lambda repo, limit: [_run(1, "N", "success")])
        assert github_watch.main([]) == 1  # systemctl --failed 에 드러나야 한다
        assert "상태 파일" in capsys.readouterr().err
    finally:
        blocked.parent.chmod(0o700)


def test_default_state_dir_is_the_systemd_one_not_the_root_owned_auto_deploy_dir():
    assert "auto-deploy-state" not in github_watch.DEFAULT_STATE
    assert github_watch.DEFAULT_STATE.startswith("/var/lib/quant-github-watch")
