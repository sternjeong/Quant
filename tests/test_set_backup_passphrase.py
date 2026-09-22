"""deploy/set_backup_passphrase.sh 검증. QUANT_BACKUP_DIR로 실제 /opt/quant-backup을 건드리지 않는다."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "set_backup_passphrase.sh"
GOOD = "correct horse battery staple extra"  # 20자 이상, 공백 포함(허용돼야 함)


def _run(backup_dir: Path, stdin: str) -> subprocess.CompletedProcess:
    import os
    env = {**os.environ, "QUANT_BACKUP_DIR": str(backup_dir)}
    return subprocess.run(["bash", str(SCRIPT)], input=stdin, capture_output=True, text=True, env=env, timeout=30)


def _target(backup_dir: Path) -> Path:
    return backup_dir / "secrets_passphrase"


def _leftovers(backup_dir: Path) -> list[str]:
    return [p.name for p in backup_dir.iterdir()] if backup_dir.exists() else []


def test_valid_passphrase_is_saved_with_strict_permissions(tmp_path):
    backup = tmp_path / "backup"
    result = _run(backup, f"{GOOD}\n{GOOD}\n")
    assert result.returncode == 0, result.stderr
    target = _target(backup)
    assert target.read_text() == GOOD  # 줄바꿈 없이 그대로
    assert oct(target.stat().st_mode)[-3:] == "600"
    assert _leftovers(backup) == ["secrets_passphrase"]  # 임시 파일이 남지 않는다


def test_passphrase_is_never_echoed_back(tmp_path):
    result = _run(tmp_path / "backup", f"{GOOD}\n{GOOD}\n")
    assert GOOD not in result.stdout + result.stderr


def test_spaces_are_allowed_unlike_the_code_server_password_script(tmp_path):
    value = "이것은 스페이스가 있는 충분히 긴 문구 입니다"  # 공백·한글도 허용(파일로만 저장되므로 안전)
    backup = tmp_path / "backup"
    result = _run(backup, f"{value}\n{value}\n")
    assert result.returncode == 0, result.stderr
    assert _target(backup).read_text() == value


@pytest.mark.parametrize(
    "stdin, reason",
    [
        (f"{GOOD}\nsomething else entirely long enough\n", "mismatch"),
        ("too short\ntoo short\n", "under 20 chars"),
        ("", "no input at all"),
    ],
)
def test_rejected_input_creates_nothing(tmp_path, stdin, reason):
    backup = tmp_path / "backup"
    result = _run(backup, stdin)
    assert result.returncode != 0, reason
    assert not _target(backup).exists(), reason


def test_an_existing_passphrase_is_left_alone_on_rejection(tmp_path):
    backup = tmp_path / "backup"
    _run(backup, f"{GOOD}\n{GOOD}\n")
    before = _target(backup).read_text()
    _run(backup, "short\nshort\n")
    assert _target(backup).read_text() == before


def test_result_round_trips_with_backup_vm_decrypt(tmp_path):
    """스크립트가 만든 파일이 backup_vm.py의 openssl 파라미터와 실제로 호환되는지 교차 확인."""
    import importlib.util

    backup = tmp_path / "backup"
    _run(backup, f"{GOOD}\n{GOOD}\n")
    spec = importlib.util.spec_from_file_location("backup_vm", Path(__file__).resolve().parent.parent / "deploy" / "backup_vm.py")
    backup_vm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup_vm)
    pass_file = backup_vm.passphrase_path(backup)
    ciphertext = backup_vm.encrypt_bytes(b"cross-check", pass_file)
    assert backup_vm.decrypt_bytes(ciphertext, pass_file) == b"cross-check"


def test_scripts_have_valid_bash_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
