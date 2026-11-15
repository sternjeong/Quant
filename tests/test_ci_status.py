"""deploy/ci_status.py — GitHub check-runs 응답을 auto_deploy 가 쓰는 한 단어로 바꾼다(네트워크 없음)."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("ci_status", Path(__file__).resolve().parent.parent / "deploy" / "ci_status.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def _run(name="test-gate", status="completed", conclusion="success", started="2026-11-15T01:00:00Z", url="u"):
    return {"name": name, "status": status, "conclusion": conclusion, "started_at": started, "html_url": url}


def test_no_gate_run_is_none_not_success():
    assert ci.classify({"check_runs": []}) == ("none", "")
    assert ci.classify({"check_runs": [_run(name="shard (0)")]}) == ("none", "")


def test_completed_states():
    assert ci.classify({"check_runs": [_run()]}) == ("success", "u")
    assert ci.classify({"check_runs": [_run(conclusion="failure")]})[0] == "failure"
    assert ci.classify({"check_runs": [_run(conclusion="cancelled")]})[0] == "failure"
    assert ci.classify({"check_runs": [_run(conclusion="skipped")]})[0] == "failure"  # 건너뜀은 통과가 아니다


def test_in_progress_is_pending():
    assert ci.classify({"check_runs": [_run(status="in_progress", conclusion=None)]})[0] == "pending"


def test_latest_rerun_wins():
    runs = [_run(conclusion="failure", started="2026-11-15T01:00:00Z", url="old"),
            _run(conclusion="success", started="2026-11-15T02:00:00Z", url="new")]
    assert ci.classify({"check_runs": runs}) == ("success", "new")


def test_main_never_raises_on_network_error(monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(ci, "fetch", boom)
    assert ci.main(["ci_status.py", "abc"]) == 0
    assert capsys.readouterr().out.startswith("error")
