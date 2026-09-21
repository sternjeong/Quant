"""deploy/post_deploy_check.sh — 재시작 뒤 서비스가 실제로 살아 있는지 확인하는 함수.

systemctl/curl은 PATH 앞에 둔 스텁으로 대체한다(호출 횟수를 세서 "늦게 뜸", "뜬 뒤 다시 죽음"도 재현).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
LIB = DEPLOY / "post_deploy_check.sh"
AUTO_DEPLOY = DEPLOY / "auto_deploy.sh"


@pytest.fixture
def stubs(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    # is-active: FAKE_INACTIVE(항상 내려감), FAKE_LATE="svc:N"(N번째 호출부터 active), FAKE_DIES="svc:N"(N번째 호출부터 다시 내려감)
    (bin_dir / "systemctl").write_text(r'''#!/usr/bin/env bash
[ "$1" = "is-active" ] || exit 0
svc="${@: -1}"
count_file="$FAKE_STATE/$svc.count"
n=$(( $(cat "$count_file" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$count_file"
for s in $FAKE_INACTIVE; do [ "$s" = "$svc" ] && exit 3; done
for spec in $FAKE_LATE; do [ "${spec%%:*}" = "$svc" ] && [ "$n" -lt "${spec##*:}" ] && exit 3; done
for spec in $FAKE_DIES; do [ "${spec%%:*}" = "$svc" ] && [ "$n" -ge "${spec##*:}" ] && exit 3; done
exit 0
''')
    (bin_dir / "curl").write_text(r'''#!/usr/bin/env bash
url="${@: -1}"
for u in $FAKE_BAD_URLS; do [ "$u" = "$url" ] && exit 22; done
exit 0
''')
    for name in ("systemctl", "curl"):
        (bin_dir / name).chmod(0o755)
    return bin_dir, state


def _verify(stubs, *services, timeout=1, **env):
    bin_dir, state = stubs
    full_env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE_STATE": str(state),
        "VERIFY_POLL_SECONDS": "0.1", "VERIFY_SETTLE_SECONDS": "0",
        "FAKE_INACTIVE": "", "FAKE_LATE": "", "FAKE_DIES": "", "FAKE_BAD_URLS": "",
    }
    full_env.update(env)
    return subprocess.run(
        ["bash", "-c", f'source "{LIB}"; verify_services_after_restart {timeout} {" ".join(services)}'],
        env=full_env, capture_output=True, text=True, timeout=30,
    )


SERVICES = ("codex-telegram", "quant-streamlit", "quant-scheduler", "quant-hub")


def test_all_healthy_returns_zero_and_prints_nothing(stubs):
    result = _verify(stubs, *SERVICES)
    assert result.returncode == 0 and result.stdout == ""


def test_an_inactive_service_is_reported_after_the_timeout(stubs):
    result = _verify(stubs, *SERVICES, FAKE_INACTIVE="quant-scheduler")
    assert result.returncode == 1
    assert result.stdout.strip() == "quant-scheduler (비활성)"


def test_a_service_that_comes_up_late_but_within_the_timeout_is_fine(stubs):
    result = _verify(stubs, *SERVICES, timeout=5, FAKE_LATE="quant-streamlit:4")  # 앞 3번은 아직 안 떴다가 4번째 확인에서 active
    assert result.returncode == 0 and result.stdout == ""


def test_active_but_unresponsive_health_endpoint_is_reported(stubs):
    result = _verify(stubs, *SERVICES, FAKE_BAD_URLS="http://127.0.0.1:8501/_stcore/health")
    assert result.returncode == 1
    assert "quant-streamlit (활성이지만 헬스체크 실패)" in result.stdout


def test_hub_health_endpoint_is_checked_too(stubs):
    result = _verify(stubs, *SERVICES, FAKE_BAD_URLS="http://127.0.0.1:8000/")
    assert result.returncode == 1 and "quant-hub (활성이지만 헬스체크 실패)" in result.stdout


def test_a_service_that_dies_right_after_starting_is_caught_by_the_settle_recheck(stubs):
    # 첫 확인(대기 루프)은 통과, 잠깐 뒤 재확인에서는 내려가 있다 = 재시작 루프
    result = _verify(stubs, *SERVICES, FAKE_DIES="quant-scheduler:2")
    assert result.returncode == 1
    assert result.stdout.strip() == "quant-scheduler (기동 직후 다시 내려감)"


def test_multiple_problems_are_all_listed(stubs):
    result = _verify(stubs, *SERVICES, FAKE_INACTIVE="codex-telegram quant-hub")
    assert result.returncode == 1
    assert "codex-telegram (비활성)" in result.stdout and "quant-hub (비활성)" in result.stdout


def test_auto_deploy_checks_health_before_announcing_success():
    text = AUTO_DEPLOY.read_text()
    restart = text.index('systemctl restart "${SERVICES[@]}"')
    verify = text.index('verify_services_after_restart "$POST_DEPLOY_TIMEOUT_SECONDS"')
    success = text.index('message="[자동배포] 성공')
    assert restart < verify < success  # 재시작 → 상태 확인 → 그 다음에야 성공 알림
    assert 'source "$APP_DIR/deploy/post_deploy_check.sh"' in text
    subprocess.run(["bash", "-n", str(AUTO_DEPLOY)], check=True)
    subprocess.run(["bash", "-n", str(LIB)], check=True)
