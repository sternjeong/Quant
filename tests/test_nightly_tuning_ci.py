"""scripts/nightly_tuning_ci.py 단위 테스트 — 반복마다 커밋+푸시하는 안전장치(2026-07-21) 커버.

scripts/ 밑은 core/처럼 패키지가 아니라 importlib로 파일 경로를 직접 로드한다. subprocess로 실제
git을 부르지 않도록 monkeypatch로 대체한다(네트워크/실제 저장소 상태에 의존하지 않기 위함).
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "nightly_tuning_ci", PROJECT_ROOT / "scripts" / "nightly_tuning_ci.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def nightly_ci():
    return _load_module()


def _completed(returncode: int, stderr: str = ""):
    result = MagicMock()
    result.returncode = returncode
    result.stderr = stderr
    return result


class TestMergeAndTruncate:
    def test_dedupes_by_ticker_run_created_at_run_id(self, nightly_ci):
        row = {"ticker": "AAPL", "run_created_at": "2026-01-01", "run_id": 1, "excess_return": 5.0}
        merged = nightly_ci._merge_and_truncate([row], [dict(row)])
        assert len(merged) == 1

    def test_drops_rows_without_excess_return(self, nightly_ci):
        rows = [
            {"ticker": "AAPL", "run_created_at": "2026-01-01", "run_id": 1, "excess_return": None},
            {"ticker": "MSFT", "run_created_at": "2026-01-01", "run_id": 2, "excess_return": 3.0},
        ]
        merged = nightly_ci._merge_and_truncate(rows, [])
        assert len(merged) == 1
        assert merged[0]["ticker"] == "MSFT"

    def test_sorts_descending_and_truncates_to_top_k(self, nightly_ci, monkeypatch):
        monkeypatch.setattr(nightly_ci, "_KEEP_TOP_K", 2)
        rows = [
            {"ticker": "A", "run_created_at": "d", "run_id": 1, "excess_return": 1.0},
            {"ticker": "B", "run_created_at": "d", "run_id": 2, "excess_return": 3.0},
            {"ticker": "C", "run_created_at": "d", "run_id": 3, "excess_return": 2.0},
        ]
        merged = nightly_ci._merge_and_truncate(rows, [])
        assert [r["ticker"] for r in merged] == ["B", "C"]


class TestCommitAndPush:
    def test_no_changes_skips_commit(self, nightly_ci, monkeypatch):
        calls = []

        def _fake_run_git(*args):
            calls.append(args)
            if args[0] == "diff":
                return _completed(0)  # 변경 없음
            return _completed(0)

        monkeypatch.setattr(nightly_ci, "_run_git", _fake_run_git)
        monkeypatch.setattr(nightly_ci, "FRED_CACHE_DIR", Path("/nonexistent"))
        assert nightly_ci._commit_and_push("msg") is True
        assert not any(c[0] == "commit" for c in calls)

    def test_commit_and_push_succeeds(self, nightly_ci, monkeypatch):
        def _fake_run_git(*args):
            if args[0] == "diff":
                return _completed(1)  # 변경 있음
            return _completed(0)

        monkeypatch.setattr(nightly_ci, "_run_git", _fake_run_git)
        monkeypatch.setattr(nightly_ci, "FRED_CACHE_DIR", Path("/nonexistent"))
        assert nightly_ci._commit_and_push("msg") is True

    def test_push_rejected_then_rebase_retry_succeeds(self, nightly_ci, monkeypatch):
        push_calls = {"n": 0}

        def _fake_run_git(*args):
            if args[0] == "diff":
                return _completed(1)
            if args[0] == "commit":
                return _completed(0)
            if args[0] == "push":
                push_calls["n"] += 1
                return _completed(0) if push_calls["n"] > 1 else _completed(1, "rejected")
            if args[0] == "fetch":
                return _completed(0)
            if args[0] == "rebase":
                return _completed(0)
            return _completed(0)

        monkeypatch.setattr(nightly_ci, "_run_git", _fake_run_git)
        monkeypatch.setattr(nightly_ci, "FRED_CACHE_DIR", Path("/nonexistent"))
        assert nightly_ci._commit_and_push("msg") is True
        assert push_calls["n"] == 2

    def test_rebase_failure_aborts_and_returns_false(self, nightly_ci, monkeypatch):
        abort_called = []

        def _fake_run_git(*args):
            if args[0] == "diff":
                return _completed(1)
            if args[0] == "commit":
                return _completed(0)
            if args[0] == "push":
                return _completed(1, "rejected")
            if args[0] == "fetch":
                return _completed(0)
            if args[0] == "rebase" and "--abort" in args:
                abort_called.append(True)
                return _completed(0)
            if args[0] == "rebase":
                return _completed(1, "conflict")
            return _completed(0)

        monkeypatch.setattr(nightly_ci, "_run_git", _fake_run_git)
        monkeypatch.setattr(nightly_ci, "FRED_CACHE_DIR", Path("/nonexistent"))
        assert nightly_ci._commit_and_push("msg") is False
        assert abort_called

    def test_commit_failure_returns_false_without_pushing(self, nightly_ci, monkeypatch):
        push_called = []

        def _fake_run_git(*args):
            if args[0] == "diff":
                return _completed(1)
            if args[0] == "commit":
                return _completed(1, "commit failed")
            if args[0] == "push":
                push_called.append(True)
            return _completed(0)

        monkeypatch.setattr(nightly_ci, "_run_git", _fake_run_git)
        monkeypatch.setattr(nightly_ci, "FRED_CACHE_DIR", Path("/nonexistent"))
        assert nightly_ci._commit_and_push("msg") is False
        assert not push_called


class TestSaveAndPushLeaderboard:
    def test_writes_merged_results_and_calls_commit(self, nightly_ci, monkeypatch, tmp_path):
        leaderboard_path = tmp_path / "leaderboard.json"
        monkeypatch.setattr(nightly_ci, "_LEADERBOARD_PATH", leaderboard_path)
        monkeypatch.setattr(
            nightly_ci, "get_top_tuning_results",
            lambda strategy_id, limit: [{"ticker": "AAPL", "run_created_at": "d", "run_id": 1, "excess_return": 4.0}],
        )
        commit_calls = []
        monkeypatch.setattr(nightly_ci, "_commit_and_push", lambda msg: commit_calls.append(msg) or True)

        nightly_ci._save_and_push_leaderboard(strategy_id=3, message="test message")

        assert leaderboard_path.exists()
        assert commit_calls == ["test message"]
