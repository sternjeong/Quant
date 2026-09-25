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


# ---- 검증(verify) / 복구 리허설 / 원격 HEAD 확인 -------------------------------------------------------------------

def _setup_remote(tmp_path: Path, backup: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    backup.mkdir(exist_ok=True)
    (backup / "remote").write_text(str(remote) + "\n")
    return remote


def test_verify_passes_on_a_fresh_backup_and_names_the_broken_file(app, tmp_path):
    backup = tmp_path / "backup"
    _run(app, backup)
    repo = backup / "repo"
    assert backup_vm.verify_backup(repo) == []

    victim = repo / "files" / "analysis" / "2026-09-20_new" / "report.md"
    victim.write_text("tampered")
    problems = backup_vm.verify_backup(repo, check_git=False)
    assert any("내용 불일치: analysis/2026-09-20_new/report.md" in p for p in problems)

    victim.unlink()
    assert any("파일 없음: analysis/2026-09-20_new/report.md" in p for p in backup_vm.verify_backup(repo, check_git=False))


def test_verify_detects_a_corrupted_db_copy_and_a_missing_manifest(app, tmp_path):
    backup = tmp_path / "backup"
    _run(app, backup)
    repo = backup / "repo"
    (repo / "db" / "quant.db").write_bytes(b"not a database" * 100)
    problems = backup_vm.verify_backup(repo, check_git=False)
    assert any("DB" in p or "내용 불일치: db/quant.db" in p for p in problems)

    (repo / "MANIFEST.json").unlink()
    assert backup_vm.verify_backup(repo, check_git=False)[0].startswith("MANIFEST.json을 읽을 수 없음")


def test_a_failed_verification_aborts_the_run_and_never_pushes(app, tmp_path, monkeypatch):
    backup = tmp_path / "backup"
    remote = _setup_remote(tmp_path, backup)
    monkeypatch.setattr(backup_vm, "verify_backup", lambda repo, **kw: ["내용 불일치: db/quant.db"])

    status, alerts = _run(app, backup)

    assert status["ok"] is False and "백업 검증 실패" in status["error"]
    assert status["last_success_epoch"] is None  # 검증 실패는 성공으로 치지 않는다
    assert subprocess.run(["git", "-C", str(remote), "branch", "--list"], capture_output=True, text=True).stdout.strip() == ""  # 밖으로 안 올림
    assert any("백업 실패" in a for a in alerts)


def test_restore_drill_runs_on_the_first_run_from_the_local_repo_and_then_weekly(app, tmp_path):
    backup = tmp_path / "backup"
    t0 = datetime(2026, 9, 20, 21, 30, tzinfo=timezone.utc)

    first, alerts = _run(app, backup, now=lambda: t0)
    assert first["restore_drill_ok"] is True and first["restore_drill_source"] == "local"
    assert first["last_restore_drill_epoch"] == t0.timestamp() and alerts == []
    assert list(backup.glob("restore-drill-*")) == []  # 임시 클론은 지워진다

    second, _ = _run(app, backup, now=lambda: t0 + timedelta(days=3))
    assert second["last_restore_drill_epoch"] == t0.timestamp()  # 7일이 안 됐으니 다시 안 한다

    third, _ = _run(app, backup, now=lambda: t0 + timedelta(days=8))
    assert third["last_restore_drill_epoch"] == (t0 + timedelta(days=8)).timestamp()


def test_restore_drill_uses_the_offsite_remote_when_configured(app, tmp_path):
    backup = tmp_path / "backup"
    _setup_remote(tmp_path, backup)
    status, alerts = _run(app, backup)
    assert status["restore_drill_ok"] is True and status["restore_drill_source"] == "offsite"
    assert status["push_error"] is None and alerts == []


def test_a_failing_restore_drill_is_recorded_and_alerted(app, tmp_path, monkeypatch):
    backup = tmp_path / "backup"
    monkeypatch.setattr(backup_vm, "restore_drill", lambda b, r: (False, "offsite", "복구본 검증 실패: 내용 불일치: db/quant.db"))
    status, alerts = _run(app, backup)
    assert status["ok"] is True  # 백업 자체는 성공
    assert status["restore_drill_ok"] is False
    assert any("복구 리허설 실패(offsite)" in a for a in alerts)


def test_restore_drill_detects_a_backup_that_cannot_be_restored(app, tmp_path):
    backup = tmp_path / "backup"
    _run(app, backup)
    repo = backup / "repo"
    # 저장소 안의 DB 사본을 커밋까지 망가뜨린다 — 로컬 파일이 아니라 "받아온 복구본"에서 잡혀야 한다.
    (repo / "db" / "quant.db").write_bytes(b"garbage" * 200)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "corrupt")
    ok, source, error = backup_vm.restore_drill(backup, repo)
    assert ok is False and source == "local" and "복구본 검증 실패" in error


def test_remote_head_mismatch_is_reported_as_a_push_error(app, tmp_path, monkeypatch):
    backup = tmp_path / "backup"
    _setup_remote(tmp_path, backup)
    monkeypatch.setattr(backup_vm, "remote_head_matches", lambda b, r: (False, "push 뒤 원격 HEAD가 로컬과 다름"))
    status, alerts = _run(app, backup)
    assert status["push_error"] == "push 뒤 원격 HEAD가 로컬과 다름"
    assert status["last_push_success_epoch"] is None
    assert any("push 실패" in a for a in alerts)
    assert status["restore_drill_ok"] is None  # push가 미확인이면 원격 리허설은 건너뛴다


# ---- 비밀(선택, opt-in) 암호화 백업 --------------------------------------------------------------------------------

def _write_passphrase(backup: Path, value: str = "correct horse battery staple long") -> Path:
    backup.mkdir(parents=True, exist_ok=True)
    path = backup_vm.passphrase_path(backup)
    path.write_text(value)
    path.chmod(0o600)
    return path


@pytest.fixture
def secrets_env(app, tmp_path, monkeypatch):
    """app 픽스처는 이미 app_env/telegram_env/claude_credentials/codex_auth를 갖고 있다 — nginx/code-server만
    APP_DIR 밖이라 환경변수로 위치를 만들어 겹치지 않게 한다."""
    nginx = tmp_path / "etc-nginx" / ".htpasswd-quant"
    code_server = tmp_path / "code-server-config" / "config.yaml"
    nginx.parent.mkdir(parents=True)
    code_server.parent.mkdir(parents=True)
    nginx.write_text("sternjeong:$apr1$SECRET-HTPASSWD-HASH\n")
    code_server.write_text("bind-addr: 127.0.0.1:8080\npassword: SECRET-CODE-SERVER\n")
    monkeypatch.setenv(backup_vm.NGINX_HTPASSWD_PATH_ENV, str(nginx))
    monkeypatch.setenv(backup_vm.CODE_SERVER_CONFIG_PATH_ENV, str(code_server))
    return {"nginx_htpasswd": nginx, "code_server_config": code_server}


ALL_SIX_LABELS = {"nginx_htpasswd", "code_server_config", "app_env", "telegram_env", "claude_credentials", "codex_auth"}


def test_secrets_backup_is_skipped_entirely_without_a_passphrase_file(app, secrets_env, tmp_path):
    backup = tmp_path / "backup"
    status, alerts = _run(app, backup)
    assert status["secrets_backup_configured"] is False
    assert status["secrets_backup_files"] == 0
    assert not (backup / "repo" / "secrets").exists()
    assert alerts == []


def test_secrets_backup_encrypts_all_six_and_round_trips(app, secrets_env, tmp_path):
    backup = tmp_path / "backup"
    _write_passphrase(backup)
    status, alerts = _run(app, backup)

    assert status["secrets_backup_configured"] is True
    assert status["secrets_backup_files"] == 6 and status["secrets_backup_missing"] == []
    assert alerts == []

    pass_file = backup_vm.passphrase_path(backup)
    plaintexts = {
        "nginx_htpasswd": secrets_env["nginx_htpasswd"].read_bytes(),
        "code_server_config": secrets_env["code_server_config"].read_bytes(),
        "app_env": (app / ".env").read_bytes(),
        "telegram_env": (app / ".codex-telegram-runtime" / "telegram.env").read_bytes(),
        "claude_credentials": (app / ".claude" / ".credentials.json").read_bytes(),
        "codex_auth": (app / ".codex" / "auth.json").read_bytes(),
    }
    for label, plaintext in plaintexts.items():
        ciphertext = (backup / "repo" / "secrets" / f"{label}.enc").read_bytes()
        assert ciphertext != plaintext  # 암호화됐다
        assert backup_vm.decrypt_bytes(ciphertext, pass_file) == plaintext  # 그리고 되돌릴 수 있다

    # passphrase 값 자체나 평문 비밀은 저장소 어디에도 그대로 나타나지 않는다(암호문 안에 섞여 있을 수 있는
    # 순수 바이트 우연 일치까지 완전히 배제할 순 없지만, ASCII 원문 문자열이 그대로 보이면 안 된다).
    everything = b"".join(p.read_bytes() for p in (backup / "repo").rglob("*") if p.is_file() and ".git" not in p.parts)
    for secret_text in (b"SECRET-HTPASSWD-HASH", b"SECRET-CODE-SERVER", b"SECRET-FRED", b"SECRET-TELEGRAM", b"SECRET-CLAUDE", b"SECRET-CODEX"):
        assert secret_text not in everything
    assert b"correct horse battery staple long" not in everything  # passphrase 원문도 새지 않는다


def test_missing_secret_files_are_skipped_without_error(app, secrets_env, tmp_path):
    (app / ".codex" / "auth.json").unlink()  # 이 VM엔 Codex를 안 씀
    backup = tmp_path / "backup"
    _write_passphrase(backup)
    status, alerts = _run(app, backup)

    assert status["secrets_backup_missing"] == ["codex_auth"]
    assert status["secrets_backup_files"] == 5
    assert not (backup / "repo" / "secrets" / "codex_auth.enc").exists()
    assert alerts == []


def test_a_secret_that_disappears_has_its_old_ciphertext_removed(app, secrets_env, tmp_path):
    backup = tmp_path / "backup"
    _write_passphrase(backup)
    _run(app, backup)
    assert (backup / "repo" / "secrets" / "codex_auth.enc").exists()

    (app / ".codex" / "auth.json").unlink()
    _run(app, backup)
    assert not (backup / "repo" / "secrets" / "codex_auth.enc").exists()


def test_encrypted_secrets_never_enter_the_plaintext_files_tree(app, secrets_env, tmp_path):
    backup = tmp_path / "backup"
    _write_passphrase(backup)
    _run(app, backup)
    names = _repo_files(backup)
    assert not any(n.startswith("files/") and n.split("/")[-1] in
                   ("nginx_htpasswd", "config.yaml", ".env", "telegram.env", ".credentials.json", "auth.json") for n in names)


def test_verify_backup_catches_tampering_in_an_encrypted_secret(app, secrets_env, tmp_path):
    backup = tmp_path / "backup"
    _write_passphrase(backup)
    _run(app, backup)
    victim = backup / "repo" / "secrets" / "app_env.enc"
    victim.write_bytes(b"tampered" + victim.read_bytes())
    assert any("내용 불일치: secrets/app_env.enc" in p for p in backup_vm.verify_backup(backup / "repo", check_git=False))


def test_wrong_passphrase_cannot_decrypt(app, secrets_env, tmp_path):
    backup = tmp_path / "backup"
    _write_passphrase(backup, "correct horse battery staple long")
    _run(app, backup)
    ciphertext = (backup / "repo" / "secrets" / "app_env.enc").read_bytes()

    wrong = tmp_path / "wrong_passphrase"
    wrong.write_text("a completely different long passphrase")
    with pytest.raises(RuntimeError, match="복호화 실패"):
        backup_vm.decrypt_bytes(ciphertext, wrong)


def test_secrets_round_trip_failure_aborts_the_whole_run_and_pushes_nothing(app, secrets_env, tmp_path, monkeypatch):
    backup = tmp_path / "backup"
    _write_passphrase(backup)
    remote = _setup_remote(tmp_path, backup)
    monkeypatch.setattr(backup_vm, "decrypt_bytes", lambda data, pass_file: b"not the same bytes")  # 왕복 실패를 강제

    status, alerts = _run(app, backup)

    assert status["ok"] is False and "왕복 검증 실패" in status["error"]
    assert not (backup / "repo" / "secrets").exists() or list((backup / "repo" / "secrets").glob("*.enc")) == []
    assert subprocess.run(["git", "-C", str(remote), "branch", "--list"], capture_output=True, text=True).stdout.strip() == ""
    assert any("백업 실패" in a for a in alerts)


def test_empty_passphrase_file_is_treated_as_not_configured(app, secrets_env, tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    backup_vm.passphrase_path(backup).touch()  # 빈 파일
    status, _ = _run(app, backup)
    assert status["secrets_backup_configured"] is False


def test_an_unreadable_secret_does_not_abort_the_rest_of_the_backup(app, secrets_env, tmp_path):
    """실제로 있었던 사고 재현: nginx 로그인 파일이 quant 권한 밖이라 전체 백업이 죽었었다."""
    victim = secrets_env["nginx_htpasswd"]
    victim.chmod(0o000)
    try:
        backup = tmp_path / "backup"
        _write_passphrase(backup)
        status, alerts = _run(app, backup)

        assert status["ok"] is True, status.get("error")  # DB·연구 파일 백업은 그대로 성공
        assert status["committed"] is True
        assert status["secrets_backup_unreadable"] == [{"label": "nginx_htpasswd", "error": status["secrets_backup_unreadable"][0]["error"]}]
        assert status["secrets_backup_missing"] == []
        assert status["secrets_backup_files"] == 5  # 나머지 5개는 정상 백업됨
        assert not (backup / "repo" / "secrets" / "nginx_htpasswd.enc").exists()
        assert (backup / "repo" / "secrets" / "app_env.enc").exists()
        assert any("권한 문제로 못 읽은 비밀 파일" in a and "nginx_htpasswd" in a for a in alerts)
        assert not any("root" in a or "www-data" in a for a in alerts)  # OS 오류 메시지가 지나치게 상세히 새지 않는지
    finally:
        victim.chmod(0o600)  # 정리(다음 테스트에 영향 없게)


def test_unreadable_secrets_do_not_leak_file_contents_into_the_alert(app, secrets_env, tmp_path):
    secrets_env["code_server_config"].chmod(0o000)
    try:
        backup = tmp_path / "backup"
        _write_passphrase(backup)
        status, alerts = _run(app, backup)
        assert status["ok"] is True
        assert "SECRET-CODE-SERVER" not in " ".join(alerts)
    finally:
        secrets_env["code_server_config"].chmod(0o600)


def test_gitignored_allowlisted_state_files_are_backed_up(app, tmp_path):
    """data/process_toggles.json·agent_models.json 은 .gitignore 대상이라 예전에는 허용 목록에 있어도 빠졌다."""
    _write(app / ".gitignore", "data/process_toggles.json\ndata/agent_models.json\ndata/agent_usage.jsonl\nignored_other.txt\n")
    _write(app / "data" / "process_toggles.json", '{"paper_auto_trade": {"enabled": true}}')
    _write(app / "data" / "agent_models.json", '{"writer": {"model": "sonnet"}}')
    _write(app / "data" / "agent_usage.jsonl", '{"role": "scout"}\n')
    _write(app / "ignored_other.txt", "not allowlisted")
    status, _ = _run(app, tmp_path / "backup")
    files = _repo_files(tmp_path / "backup")
    assert {"files/data/process_toggles.json", "files/data/agent_models.json", "files/data/agent_usage.jsonl"} <= files
    assert "files/ignored_other.txt" not in files
