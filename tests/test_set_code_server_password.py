"""deploy/set_code_server_password.sh 검증.

진짜 code-server/systemd 없이 돌리도록 설정 파일은 tmp_path, systemctl/curl은 PATH 앞에 둔 스텁으로 대체한다.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "set_code_server_password.sh"
ORIGINAL_CONFIG = "bind-addr: 127.0.0.1:8080\nauth: password\npassword: oldRandomPassword1234567890\ncert: false\n"
GOOD_PASSWORD = "blue-moon-cat-42"


def _run(config: Path, stdin: str, *, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "CODE_SERVER_CONFIG": str(config), "CODE_SERVER_SERVICE": ""}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT)], input=stdin, capture_output=True, text=True, env=env, timeout=30
    )


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(ORIGINAL_CONFIG)
    path.chmod(0o600)
    return path


def _leftovers(config: Path) -> list[str]:
    return [p.name for p in config.parent.iterdir() if p.name != config.name]


def test_valid_password_replaces_only_the_password_line(config):
    result = _run(config, f"{GOOD_PASSWORD}\n{GOOD_PASSWORD}\n")
    assert result.returncode == 0, result.stderr
    assert config.read_text() == (
        "bind-addr: 127.0.0.1:8080\nauth: password\n" f"password: '{GOOD_PASSWORD}'\n" "cert: false\n"
    )
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert _leftovers(config) == []  # 백업/임시 파일이 남지 않는다(옛 비밀번호가 든 백업 포함)


def test_password_is_never_echoed_back(config):
    result = _run(config, f"{GOOD_PASSWORD}\n{GOOD_PASSWORD}\n")
    assert GOOD_PASSWORD not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "stdin, reason",
    [
        (f"{GOOD_PASSWORD}\nsomething-else-entirely\n", "mismatch"),
        ("0315\n0315\n", "too short"),
        ("12345678901\n12345678901\n", "one char under the minimum"),
        ("has space in it 123\nhas space in it 123\n", "space"),
        ("한글비밀번호열두글자이상입니다\n한글비밀번호열두글자이상입니다\n", "non-ascii"),
        ("quote'inside-abcdef\nquote'inside-abcdef\n", "quote"),
        ("", "no input at all"),
    ],
)
def test_rejected_input_leaves_config_untouched(config, stdin, reason):
    result = _run(config, stdin)
    assert result.returncode != 0, reason
    assert config.read_text() == ORIGINAL_CONFIG, reason
    assert _leftovers(config) == [], reason


def test_hashed_password_setup_is_refused(config):
    config.write_text(ORIGINAL_CONFIG + "hashed-password: $argon2i$v=19$abc\n")
    before = config.read_text()
    result = _run(config, f"{GOOD_PASSWORD}\n{GOOD_PASSWORD}\n")
    assert result.returncode != 0
    assert config.read_text() == before


def test_config_without_password_line_is_refused(config):
    config.write_text("bind-addr: 127.0.0.1:8080\nauth: none\n")
    result = _run(config, f"{GOOD_PASSWORD}\n{GOOD_PASSWORD}\n")
    assert result.returncode != 0
    assert config.read_text() == "bind-addr: 127.0.0.1:8080\nauth: none\n"


def _stub_bin(tmp_path: Path) -> Path:
    """systemctl은 무조건 성공, curl은 로그인 요청(-d @-)에만 FAKE_LOGIN_CODE를 돌려주는 스텁."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    (bin_dir / "systemctl").write_text("#!/usr/bin/env bash\nexit 0\n")
    (bin_dir / "curl").write_text(
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  if [ "$a" = "@-" ]; then cat >/dev/null; printf "%s" "$FAKE_LOGIN_CODE"; exit 0; fi\n'
        "done\n"
        "exit 0\n"
    )
    for name in ("systemctl", "curl"):
        (bin_dir / name).chmod(0o755)
    return bin_dir


def _run_with_restart(config: Path, tmp_path: Path, login_code: str) -> subprocess.CompletedProcess:
    stub = _stub_bin(tmp_path)
    return _run(
        config,
        f"{GOOD_PASSWORD}\n{GOOD_PASSWORD}\n",
        env_extra={
            "CODE_SERVER_SERVICE": "code-server@test.service",
            "PATH": f"{stub}:{os.environ['PATH']}",
            "FAKE_LOGIN_CODE": login_code,
        },
    )


def test_successful_login_check_keeps_new_password(config, tmp_path):
    result = _run_with_restart(config, tmp_path, "302")
    assert result.returncode == 0, result.stderr
    assert f"password: '{GOOD_PASSWORD}'" in config.read_text()
    assert [n for n in _leftovers(config) if n != "stub-bin"] == []


def test_failed_login_check_rolls_back_to_the_old_config(config, tmp_path):
    result = _run_with_restart(config, tmp_path, "200")
    assert result.returncode != 0
    assert config.read_text() == ORIGINAL_CONFIG
    assert [n for n in _leftovers(config) if n != "stub-bin"] == []
    assert GOOD_PASSWORD not in result.stdout + result.stderr
