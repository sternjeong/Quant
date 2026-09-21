"""deploy/backup_vm.py 검증 — 진짜 git 저장소(앱 디렉터리, 백업 저장소, 로컬 bare '원격')로 재현한다."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "backup_vm.py"
spec = importlib.util.spec_from_file_location("backup_vm", SCRIPT)
backup_vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup_vm)

GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *GIT_ID, *args], check=True, capture_output=True, text=True).stdout


def _write(path: Path, content: str | bytes = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    return path


@pytest.fixture
def app(tmp_path):
    """/opt/quant 흉내: 커밋된 파일 몇 개 + VM에만 있는 미추적/수정 파일 + 인증 정보가 든 점 폴더들."""
    root = tmp_path / "app"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    _write(root / "PROGRESS.md", "# progress\n")
    _write(root / "tracked.py", "print('hi')\n")
    _write(root / "analysis" / "committed_report.md", "already on GitHub\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")

    # VM에만 있는 것들
    _write(root / "PROGRESS.md", "# progress\n\n### VM entry\nDAY_4_BLOCKED\n")  # 수정됨
    _write(root / "analysis" / "2026-09-20_new" / "report.md", "new research\n")
    _write(root / "analysis" / "2026-09-20_new" / "data.csv", "a,b\n1,2\n")
    _write(root / "analysis.root_backup_20260914" / "old.md", "old snapshot\n")
    _write(root / "docs" / "experiment_validation" / "day4.md", "day 4\n")
    _write(root / "RESUME_NOTE.md", "resume here\n")
    _write(root / ".experiment-control" / "state.json", '{"phase": "validation"}')
    _write(root / ".experiment-control" / "checkpoints" / "big.tar.gz", b"\0" * 1024)  # 제외 대상
    _write(root / ".experiment-control" / "agent.lock", "")
    # 절대 들어가면 안 되는 것들
    _write(root / ".claude" / ".credentials.json", '{"token": "SECRET-CLAUDE"}')
    _write(root / ".codex" / "auth.json", '{"token": "SECRET-CODEX"}')
    _write(root / ".codex-telegram-runtime" / "telegram.env", "BOT=SECRET-TELEGRAM")
    _write(root / ".ssh" / "id_ed25519", "-----BEGIN OPENSSH PRIVATE KEY-----\nSECRET\n")
    _write(root / ".env", "FRED_API_KEY=SECRET-FRED")
    _write(root / "cache_junk" / "x.bin", b"junk")  # 허용 목록에 없음

    db = root / "data" / "quant.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE portfolio_holdings (ticker TEXT, shares REAL)")
    conn.execute("INSERT INTO portfolio_holdings VALUES ('AAPL', 10)")
    conn.commit()
    conn.close()
    return root


def _run(app: Path, backup: Path, **kwargs):
    alerts: list[str] = []
    status = backup_vm.run_backup(app, backup, alert=alerts.append, **kwargs)
    return status, alerts


def _repo_files(backup: Path) -> set[str]:
    repo = backup / "repo"
    return {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}


def test_backs_up_only_uncommitted_allowlisted_files_and_the_db(app, tmp_path):
    backup = tmp_path / "backup"
    status, alerts = _run(app, backup)

    assert status["ok"] and status["error"] is None
    files = _repo_files(backup)
    assert files >= {
        "files/PROGRESS.md",
        "files/analysis/2026-09-20_new/report.md",
        "files/analysis/2026-09-20_new/data.csv",
        "files/analysis.root_backup_20260914/old.md",
        "files/docs/experiment_validation/day4.md",
        "files/RESUME_NOTE.md",
        "files/.experiment-control/state.json",
        "db/quant.db",
        "MANIFEST.json",
    }
    # 이미 커밋된 파일, 허용 목록 밖, 제외 대상은 없다
    assert "files/tracked.py" not in files
    assert "files/analysis/committed_report.md" not in files
    assert "files/cache_junk/x.bin" not in files
    assert not any("checkpoints" in f or "agent.lock" in f for f in files)
    # VM의 PROGRESS.md는 수정된 전체 내용이 백업된다
    assert "DAY_4_BLOCKED" in (backup / "repo" / "files" / "PROGRESS.md").read_text()
    assert alerts == []


def test_credential_directories_and_secret_files_never_enter_the_backup(app, tmp_path):
    backup = tmp_path / "backup"
    _run(app, backup)
    everything = ""
    for path in (backup / "repo").rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            everything += path.name + "\n" + path.read_bytes().decode("utf-8", "ignore")
    for secret in ("SECRET-CLAUDE", "SECRET-CODEX", "SECRET-TELEGRAM", "SECRET-FRED", "PRIVATE KEY"):
        assert secret not in everything
    names = _repo_files(backup)
    assert not any(part in n for n in names for part in (".claude", ".codex", ".ssh", ".env", "telegram.env", "auth.json"))


def test_secret_looking_content_inside_an_allowed_folder_is_quarantined_and_reported(app, tmp_path):
    _write(app / "analysis" / "2026-09-20_new" / "notes.md", "my key is ghp_" + "a" * 36 + " oops\n")
    _write(app / "docs" / "leak.txt", "-----BEGIN RSA PRIVATE KEY-----\nabc\n")
    _write(app / "docs" / "credentials.json", "{}")  # 파일명만으로 격리
    backup = tmp_path / "backup"
    status, alerts = _run(app, backup)

    quarantined = {q["path"] for q in status["quarantined"]}
    assert quarantined == {"analysis/2026-09-20_new/notes.md", "docs/leak.txt", "docs/credentials.json"}
    files = _repo_files(backup)
    assert "files/analysis/2026-09-20_new/notes.md" not in files and "files/docs/leak.txt" not in files
    assert "files/analysis/2026-09-20_new/report.md" in files  # 나머지는 정상 백업
    assert any("비밀 의심" in a for a in alerts)
    assert "ghp_" not in json.dumps(status)  # status에 내용이 새지 않는다


def test_oversized_files_are_skipped_and_reported(app, tmp_path):
    _write(app / "analysis" / "2026-09-20_new" / "huge.bin", b"\0" * (3 * 1024 * 1024))
    status, alerts = _run(app, tmp_path / "backup", max_file_mb=2)
    assert [s["path"] for s in status["skipped"]] == ["analysis/2026-09-20_new/huge.bin"]
    assert "files/analysis/2026-09-20_new/huge.bin" not in _repo_files(tmp_path / "backup")
    assert any("너무 커서" in a for a in alerts)


def test_db_copy_is_consistent_and_readable(app, tmp_path):
    backup = tmp_path / "backup"
    _run(app, backup)
    conn = sqlite3.connect(backup / "repo" / "db" / "quant.db")
    try:
        assert conn.execute("SELECT ticker, shares FROM portfolio_holdings").fetchall() == [("AAPL", 10.0)]
    finally:
        conn.close()


def test_second_run_without_changes_makes_no_commit_and_deletions_propagate(app, tmp_path):
    backup = tmp_path / "backup"
    first, _ = _run(app, backup)
    assert first["committed"] is True
    second, _ = _run(app, backup)
    assert second["committed"] is False  # 바뀐 게 없으면 커밋하지 않는다

    (app / "docs" / "experiment_validation" / "day4.md").unlink()
    third, _ = _run(app, backup)
    assert third["committed"] is True
    assert "files/docs/experiment_validation/day4.md" not in _repo_files(backup)
    log = _git(backup / "repo", "log", "--oneline")
    assert len(log.strip().splitlines()) == 2  # 이력은 남는다(첫 커밋 + 삭제 커밋)


def test_history_keeps_old_versions(app, tmp_path):
    backup = tmp_path / "backup"
    _run(app, backup)
    _write(app / "PROGRESS.md", "# progress\n\n### VM entry\nchanged again\n")
    _run(app, backup)
    old = _git(backup / "repo", "show", "HEAD~1:files/PROGRESS.md")
    assert "DAY_4_BLOCKED" in old and "changed again" not in old


def test_offsite_push_to_a_remote_and_status(app, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "remote").write_text(str(remote) + "\n")

    status, alerts = _run(app, backup)

    assert status["offsite_configured"] is True and status["push_error"] is None
    assert status["last_push_success_epoch"] is not None
    assert alerts == []
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
    assert (clone / "files" / "analysis" / "2026-09-20_new" / "report.md").read_text() == "new research\n"
    assert (clone / "db" / "quant.db").is_file()
    assert not (clone / "files" / ".claude").exists()
    persisted = json.loads((backup / "status.json").read_text())
    assert persisted["ok"] is True and persisted["offsite_configured"] is True


def test_push_failure_keeps_local_backup_and_alerts(app, tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "remote").write_text(str(tmp_path / "does-not-exist.git") + "\n")

    status, alerts = _run(app, backup)

    assert status["ok"] is True  # 로컬 백업은 성공
    assert status["offsite_configured"] is True and status["push_error"]
    assert status["last_push_success_epoch"] is None
    assert any("push 실패" in a for a in alerts)
    assert "files/analysis/2026-09-20_new/report.md" in _repo_files(backup)


def test_no_remote_configured_is_reported_as_local_only(app, tmp_path):
    status, alerts = _run(app, tmp_path / "backup")
    assert status["offsite_configured"] is False and status["push_error"] is None
    assert alerts == []  # 미설정은 매일 알림을 보내지 않는다(브리핑에서 보여준다)


def test_success_timestamps_survive_a_later_failed_push(app, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "remote").write_text(str(remote) + "\n")
    t0 = datetime(2026, 9, 20, 21, 30, tzinfo=timezone.utc)
    first, _ = _run(app, backup, now=lambda: t0)
    (backup / "remote").write_text(str(tmp_path / "gone.git") + "\n")
    second, _ = _run(app, backup, now=lambda: t0 + timedelta(days=1))
    assert second["last_success_epoch"] == (t0 + timedelta(days=1)).timestamp()
    assert second["last_push_success_epoch"] == first["last_push_success_epoch"]  # 마지막 성공 push 시각은 유지


def test_backup_failure_is_recorded_and_alerted(tmp_path):
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    backup = tmp_path / "backup"
    status, alerts = _run(not_a_repo, backup)
    assert status["ok"] is False and status["error"]
    assert json.loads((backup / "status.json").read_text())["ok"] is False
    assert any("백업 실패" in a for a in alerts)


def test_dry_run_writes_nothing(app, tmp_path):
    backup = tmp_path / "backup"
    status, alerts = _run(app, backup, dry_run=True)
    assert status["ok"] and status["files"] > 0
    assert not (backup / "repo").exists() and not (backup / "status.json").exists()
    assert alerts == []
