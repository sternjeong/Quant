"""deploy/auto_deploy.sh 전체 흐름 — 운영 폴더는 테스트 관문을 통과한 뒤에만 새 커밋으로 옮긴다(2026-10-08).

배경: 예전엔 운영 폴더(/opt/quant)를 먼저 pull 하고 5~9분짜리 테스트를 돌려, 그동안 실행 중인 Streamlit 이 옛 모듈을 메모리에 든 채
새 화면 파일을 읽다가 ImportError 가 났고, 테스트가 실패하면 그 불일치가 다음 커밋까지 남았다.

진짜 git 저장소(bare origin, 개발자 클론, '운영 폴더' 클론)를 만들고 실제 스크립트를 돌린다. sudo/systemctl/curl/python3 와
운영 폴더의 .venv/bin/python 은 PATH·파일 스텁으로 대체한다. venv python 스텁은 '검증 폴더'의 gate_result.txt 를 읽어
통과/실패를 흉내 내고, 호출된 작업 디렉터리와 그 순간 운영 폴더의 HEAD 를 기록한다.
"""

from __future__ import annotations

import getpass
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
AUTO_DEPLOY = DEPLOY / "auto_deploy.sh"
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]

STUBS = {
    # sudo -n -u <user> cmd... -> cmd... (현재 사용자로 그대로 실행)
    "sudo": r'''#!/usr/bin/env bash
while [ $# -gt 0 ]; do
  case "$1" in
    -n) shift ;;
    -u) shift 2 ;;
    *) break ;;
  esac
done
exec "$@"
''',
    "systemctl": r'''#!/usr/bin/env bash
echo "$*" >> "$FAKE_STATE/systemctl.log"
exit 0
''',
    "curl": "#!/usr/bin/env bash\nexit 0\n",
    "python3": r'''#!/usr/bin/env bash
echo "unittest $PWD" >> "$FAKE_STATE/gate.log"
exit 0
''',
}

# 운영 폴더의 .venv/bin/python 자리(미추적 파일). pytest 게이트를 흉내 낸다.
VENV_PYTHON = r'''#!/usr/bin/env bash
echo "pytest cwd=$PWD live_head=$(git -C "$FAKE_APP" rev-parse HEAD)" >> "$FAKE_STATE/gate.log"
if [ -n "${FAKE_PUSH_DURING_GATE:-}" ] && [ ! -f "$FAKE_STATE/pushed_during_gate" ]; then
  touch "$FAKE_STATE/pushed_during_gate"
  echo "later" > "$FAKE_DEV/later.txt"
  git -C "$FAKE_DEV" add -A >/dev/null
  git -C "$FAKE_DEV" -c user.name=t -c user.email=t@example.com -c commit.gpgsign=false commit -q -m "pushed during gate"
  git -C "$FAKE_DEV" push -q origin main
  git -C "$FAKE_APP" fetch -q origin
fi
[ "$(cat "$PWD/gate_result.txt" 2>/dev/null)" = "pass" ]
'''

ALERT_STUB = r'''#!/usr/bin/env bash
printf '%s\n----\n' "$1" >> "$FAKE_STATE/alerts.log"
'''


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *GIT_ID, *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def env(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git 없음")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    dev = tmp_path / "dev"
    subprocess.run(["git", "clone", "-q", str(origin), str(dev)], check=True, capture_output=True)
    _git(dev, "checkout", "-q", "-b", "main")
    (dev / "deploy" / "codex_telegram").mkdir(parents=True)
    (dev / "deploy" / "codex_telegram" / "test_runner.py").write_text("# 게이트가 이 폴더에서 python3 -m unittest 를 돌린다(스텁)\n")
    for helper in ("progress_reconcile.sh", "post_deploy_check.sh"):
        shutil.copy(DEPLOY / helper, dev / "deploy" / helper)
    (dev / "deploy" / "send_telegram_alert.sh").write_text(ALERT_STUB)
    (dev / "deploy" / "send_telegram_alert.sh").chmod(0o755)
    (dev / "tests").mkdir()
    (dev / "tests" / "test_x.py").write_text("def test_x():\n    pass\n")
    (dev / "gate_result.txt").write_text("pass\n")
    (dev / "app.txt").write_text("v1\n")
    (dev / "PROGRESS.md").write_text("# PROGRESS\n")
    (dev / ".gitignore").write_text(".venv/\n")
    _git(dev, "add", "-A")
    _git(dev, "commit", "-q", "-m", "init")
    _git(dev, "push", "-q", "origin", "main")

    app = tmp_path / "app"
    subprocess.run(["git", "clone", "-q", str(origin), str(app)], check=True, capture_output=True)
    (app / ".venv" / "bin").mkdir(parents=True)
    (app / ".venv" / "bin" / "python").write_text(VENV_PYTHON)
    (app / ".venv" / "bin" / "python").chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    fake_state = tmp_path / "fake"
    fake_state.mkdir()
    return {
        "tmp": tmp_path, "dev": dev, "app": app, "bin": bin_dir, "fake": fake_state,
        "state": tmp_path / "deploy-state", "staging": tmp_path / "deploy-staging",
    }


def _run(env, **extra) -> subprocess.CompletedProcess:
    full_env = {
        "PATH": f"{env['bin']}:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(env["tmp"]),
        "AUTO_DEPLOY_APP_DIR": str(env["app"]),
        "AUTO_DEPLOY_SERVICE_USER": getpass.getuser(),
        "AUTO_DEPLOY_STATE_DIR": str(env["state"]),
        "AUTO_DEPLOY_STAGING_DIR": str(env["staging"]),
        "AUTO_DEPLOY_POST_CHECK_TIMEOUT_SECONDS": "2",
        # 에이전트 배치 창(03:00~05:55 KST) 보류 로직이 실제 벽시계 시간에 따라 테스트를 흔들지 않게 고정.
        "AUTO_DEPLOY_NOW_KST_HM": "12:00",
        "VERIFY_POLL_SECONDS": "0.1",
        "VERIFY_SETTLE_SECONDS": "0",
        "FAKE_STATE": str(env["fake"]),
        "FAKE_APP": str(env["app"]),
        "FAKE_DEV": str(env["dev"]),
    }
    full_env.update(extra)
    return subprocess.run(["bash", str(AUTO_DEPLOY)], env=full_env, capture_output=True, text=True, timeout=120)


def _push(env, *, gate: str = "pass", app_text: str | None = None, message: str = "change") -> str:
    dev = env["dev"]
    (dev / "gate_result.txt").write_text(gate + "\n")
    (dev / "app.txt").write_text((app_text or message) + "\n")
    _git(dev, "add", "-A")
    _git(dev, "commit", "-q", "-m", message)
    _git(dev, "push", "-q", "origin", "main")
    return _git(dev, "rev-parse", "HEAD")


def _read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def _gate_lines(env) -> list[str]:
    return [l for l in _read(env["fake"] / "gate.log").splitlines() if l.startswith("pytest")]


def _restarts(env) -> list[str]:
    return [l for l in _read(env["fake"] / "systemctl.log").splitlines() if l.startswith("restart")]


def _assert_staging_gone(env):
    assert not env["staging"].exists()
    worktrees = _git(env["app"], "worktree", "list", "--porcelain")
    assert worktrees.count("worktree ") == 1  # 운영 폴더 자신만 남는다


def test_no_new_commit_is_a_quiet_noop(env):
    result = _run(env)
    assert result.returncode == 0 and result.stdout == ""
    assert _gate_lines(env) == [] and _restarts(env) == []


def test_defers_entirely_during_the_agent_batch_window(env):
    """2026-10-09: 03:00~05:55 KST 에는 테스트/반영/재시작을 전부 보류한다 — quant-scheduler 재시작이
    그 시간대의 AI 에이전트 야간 배치(agent_batch)를 매번 중간에 죽이던 문제 때문(진단: 최근 23일 중
    20일이 이 창에서 재시작됨, 가설이 전부 draft 에 멈춤)."""
    old = _git(env["app"], "rev-parse", "HEAD")
    _push(env, gate="pass", app_text="v2")

    result = _run(env, AUTO_DEPLOY_NOW_KST_HM="03:30")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(env["app"], "rev-parse", "HEAD") == old  # 운영 폴더는 그대로
    assert _gate_lines(env) == [] and _restarts(env) == []  # 테스트도, 재시작도 없음
    assert _read(env["fake"] / "alerts.log") == ""

    result = _run(env, AUTO_DEPLOY_NOW_KST_HM="06:00")  # 창이 끝나면 평소처럼 바로 반영
    assert result.returncode == 0, result.stdout + result.stderr
    assert _gate_lines(env) != [] and _restarts(env) != []


def test_gate_runs_in_staging_before_the_live_tree_moves_then_restarts(env):
    old = _git(env["app"], "rev-parse", "HEAD")
    new = _push(env, gate="pass", app_text="v2")

    result = _run(env)

    assert result.returncode == 0, result.stdout + result.stderr
    gate = _gate_lines(env)
    assert len(gate) == 1
    # 테스트는 검증 폴더에서, 그동안 운영 폴더는 옛 커밋 그대로였다
    assert f"cwd={env['staging']}" in gate[0] and f"live_head={old}" in gate[0]
    assert f"unittest {env['staging']}/deploy/codex_telegram" in _read(env["fake"] / "gate.log")
    # 통과 후 운영 폴더가 그 커밋으로 이동하고 곧바로 재시작
    assert _git(env["app"], "rev-parse", "HEAD") == new
    assert (env["app"] / "app.txt").read_text() == "v2\n"
    assert _restarts(env) == ["restart codex-telegram quant-streamlit quant-scheduler quant-hub"]
    assert "[자동배포] 성공" in _read(env["fake"] / "alerts.log")
    _assert_staging_gone(env)


def test_failed_gate_leaves_the_live_tree_on_the_old_commit_and_is_not_retried(env):
    old = _git(env["app"], "rev-parse", "HEAD")
    bad = _push(env, gate="fail", app_text="broken")

    result = _run(env)

    assert result.returncode == 1
    assert _git(env["app"], "rev-parse", "HEAD") == old  # 운영 폴더는 그대로 — 실행 중 서비스와 파일이 계속 일치
    assert (env["app"] / "app.txt").read_text() == "v1\n"
    assert _git(env["app"], "status", "--porcelain") == ""
    assert _restarts(env) == []
    alerts = _read(env["fake"] / "alerts.log")
    assert "[자동배포] 테스트 실패 — 반영하지 않음" in alerts
    assert (env["state"] / "last_test_failure_commit").read_text().strip() == bad
    _assert_staging_gone(env)

    # 같은 커밋으로는 재시도·재알림 없음
    again = _run(env)
    assert again.returncode == 0 and again.stdout == ""
    assert len(_gate_lines(env)) == 1
    assert _read(env["fake"] / "alerts.log") == alerts

    # 고친 커밋이 오면 다시 테스트하고 배포, '복구됨'을 붙인다
    fixed = _push(env, gate="pass", app_text="fixed")
    recovered = _run(env)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert _git(env["app"], "rev-parse", "HEAD") == fixed
    assert "(이전 테스트 실패 상태에서 복구됨)" in _read(env["fake"] / "alerts.log")
    assert not (env["state"] / "last_test_failure_commit").exists()


def test_only_the_tested_commit_is_deployed_even_if_main_moves_during_the_gate(env):
    tested = _push(env, gate="pass", app_text="v2")

    result = _run(env, FAKE_PUSH_DURING_GATE="1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(env["app"], "rev-parse", "HEAD") == tested  # 테스트하지 않은 later 커밋은 아직 반영하지 않는다
    assert not (env["app"] / "later.txt").exists()
    # 다음 틱에서 later 커밋을 따로 테스트한 뒤 반영
    nxt = _run(env)
    assert nxt.returncode == 0 and len(_gate_lines(env)) == 2
    assert (env["app"] / "later.txt").exists()


def test_blocked_fast_forward_after_a_passing_gate_keeps_local_edits_and_retries_without_retesting(env):
    old = _git(env["app"], "rev-parse", "HEAD")
    (env["app"] / "app.txt").write_text("VM 로컬 수정\n")  # 새 커밋이 바꾸는 파일의 미커밋 수정 -> fast-forward 불가
    new = _push(env, gate="pass", app_text="v2")

    result = _run(env)

    assert result.returncode == 1
    assert _git(env["app"], "rev-parse", "HEAD") == old
    assert (env["app"] / "app.txt").read_text() == "VM 로컬 수정\n"  # 로컬 수정은 건드리지 않는다
    assert _restarts(env) == []
    assert "[자동배포] 실패 — 수동 확인 필요" in _read(env["fake"] / "alerts.log")
    assert (env["state"] / "last_gate_pass_commit").read_text().strip() == new
    _assert_staging_gone(env)

    # 막힌 동안: 테스트를 다시 돌리지 않고, 쿨다운 동안 재알림도 없다
    alerts = _read(env["fake"] / "alerts.log")
    blocked = _run(env)
    assert blocked.returncode == 1 and len(_gate_lines(env)) == 1
    assert _read(env["fake"] / "alerts.log") == alerts

    # 사람이 막힘을 풀면 테스트 없이 반영·재시작
    (env["app"] / "app.txt").write_text("v1\n")
    done = _run(env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert _git(env["app"], "rev-parse", "HEAD") == new and len(_gate_lines(env)) == 1
    assert len(_restarts(env)) == 1
    assert "(이전 배포 실패 상태에서 복구됨)" in _read(env["fake"] / "alerts.log")
    assert not (env["state"] / "last_gate_pass_commit").exists()


def test_diverged_history_fails_fast_without_running_the_gate(env):
    app = env["app"]
    (app / "local.txt").write_text("VM 전용 커밋\n")
    _git(app, "add", "local.txt")
    _git(app, "commit", "-q", "-m", "vm local commit")
    local = _git(app, "rev-parse", "HEAD")
    _push(env, gate="pass", app_text="v2")

    result = _run(env)

    assert result.returncode == 1
    assert _gate_lines(env) == [] and _restarts(env) == []
    assert _git(app, "rev-parse", "HEAD") == local
    assert "[자동배포] 실패 — 수동 확인 필요" in _read(env["fake"] / "alerts.log")
    assert not env["staging"].exists()


def test_leftover_staging_from_an_interrupted_run_is_cleaned_first(env):
    env["staging"].mkdir()
    (env["staging"] / "junk.txt").write_text("지난 실행이 끊겨 남은 파일\n")
    new = _push(env, gate="pass", app_text="v2")

    result = _run(env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(env["app"], "rev-parse", "HEAD") == new
    _assert_staging_gone(env)


def test_record_files_are_still_reconciled_when_the_tested_commit_touches_them(env):
    (env["app"] / "PROGRESS.md").write_text("# PROGRESS\n\n### VM 기록\n미커밋\n")
    dev = env["dev"]
    (dev / "PROGRESS.md").write_text("# PROGRESS\n\n### 작업 1\n개발\n")
    new = _push(env, gate="pass", app_text="v2")

    result = _run(env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(env["app"], "rev-parse", "HEAD") == new
    merged = (env["app"] / "PROGRESS.md").read_text()
    assert "미커밋" in merged and "### 작업 1" in merged


def test_gate_happens_before_the_live_fast_forward_in_the_script():
    text = AUTO_DEPLOY.read_text()
    worktree = text.index('worktree add --detach "$STAGING_DIR" "$remote_head"')
    gate = text.index('-m pytest "$STAGING_DIR/tests"')
    merge = text.index('git_as_quant merge --ff-only "$remote_head"')
    restart = text.index('systemctl restart "${SERVICES[@]}"')
    assert worktree < gate < merge < restart
    assert "pull --ff-only 2>&1" not in text  # 운영 폴더를 테스트 전에 옮기는 pull 은 없다
    for forbidden in ("reset --hard", "git clean", "stash"):
        assert forbidden not in text.replace("`git reset --hard`, `git clean`", "").replace("stash/drop", "")
