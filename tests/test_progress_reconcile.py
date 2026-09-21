"""deploy/progress_reconcile.sh 검증 — VM의 미커밋 PROGRESS.md 기록 때문에 자동배포 pull이 막히던 문제.

진짜 git 저장소 세 개(bare origin, 개발자 클론, VM 클론)를 만들고, auto_deploy.sh와 같은 순서
(prepare → pull --ff-only → reapply / 실패 시 restore)로 함수를 호출한다. sudo/quant 계정은 쓰지 않는다.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
LIB = DEPLOY / "progress_reconcile.sh"
AUTO_DEPLOY = DEPLOY / "auto_deploy.sh"

BASE_PROGRESS = "# PROGRESS\n\n### 작업 1\n첫 항목\n\n### 작업 2\n둘째 항목\n"
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]

FLOW = r"""
set -euo pipefail
APP_DIR="$1"; STATE_DIR="$2"; MODE="${3:-normal}"
mkdir -p "$STATE_DIR"
log() { echo "LOG: $*"; }
git_as_quant() { git -C "$APP_DIR" "$@"; }
source "$LIB"

git_as_quant fetch -q origin
local_head="$(git_as_quant rev-parse HEAD)"
remote_head="$(git_as_quant rev-parse origin/main)"
progress_prepare_for_pull "$local_head" "$remote_head" || echo "PREPARE-FAILED"
if git_as_quant pull --ff-only -q >/dev/null 2>&1; then
  new_head="$(git_as_quant rev-parse HEAD)"
  if [ "$MODE" = "show-fails" ]; then
    git_as_quant() { if [ "$1" = show ]; then return 1; fi; git -C "$APP_DIR" "$@"; }
  fi
  progress_reapply_after_pull "$new_head" || echo "REAPPLY-FAILED"
  echo "PULL-OK"
else
  progress_restore_after_failed_pull || echo "RESTORE-FAILED"
  echo "PULL-FAILED"
fi
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *GIT_ID, *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    dev = tmp_path / "dev"
    subprocess.run(["git", "clone", "-q", str(origin), str(dev)], check=True, capture_output=True)
    _git(dev, "checkout", "-q", "-b", "main")
    (dev / "PROGRESS.md").write_text(BASE_PROGRESS)
    (dev / "notes.txt").write_text("notes\n")
    _git(dev, "add", "-A")
    _git(dev, "commit", "-q", "-m", "init")
    _git(dev, "push", "-q", "origin", "main")
    vm = tmp_path / "vm"
    subprocess.run(["git", "clone", "-q", str(origin), str(vm)], check=True, capture_output=True)
    return dev, vm, tmp_path / "state"


def _push_dev_commit(dev: Path, *, progress: str | None = None, notes: str | None = None) -> None:
    if progress is not None:
        (dev / "PROGRESS.md").write_text(progress)
    if notes is not None:
        (dev / "notes.txt").write_text(notes)
    _git(dev, "add", "-A")
    _git(dev, "commit", "-q", "-m", "dev change")
    _git(dev, "push", "-q", "origin", "main")


def _flow(vm: Path, state: Path, mode: str = "normal") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", FLOW, "flow", str(vm), str(state), mode],
        env={"LIB": str(LIB), "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(vm.parent)},
        capture_output=True, text=True, timeout=60,
    )


def _backups(state: Path, kind: str = "local") -> list[Path]:
    return sorted(state.glob(f"PROGRESS.{kind}.*")) if state.exists() else []


def test_both_sides_append_at_the_end_keeps_both_and_deploys(repos):
    dev, vm, state = repos
    vm_entry = "\n### VM 슈퍼바이저 기록\nDAY_4_BLOCKED\n"
    dev_entry = "\n### 작업 3\n개발 쪽 새 항목\n"
    local_content = BASE_PROGRESS + vm_entry
    (vm / "PROGRESS.md").write_text(local_content)
    _push_dev_commit(dev, progress=BASE_PROGRESS + dev_entry)

    result = _flow(vm, state)

    assert "PULL-OK" in result.stdout and "FAILED" not in result.stdout, result.stdout + result.stderr
    assert _git(vm, "rev-parse", "HEAD") == _git(vm, "rev-parse", "origin/main")  # 배포(pull) 성공
    merged = (vm / "PROGRESS.md").read_text()
    assert "개발 쪽 새 항목" in merged and "DAY_4_BLOCKED" in merged
    assert "<<<<<<<" not in merged and ">>>>>>>" not in merged
    # VM의 미커밋 추가분은 계속 미커밋 상태로 남는다(에이전트가 이어서 쓰는 파일 그대로)
    assert _git(vm, "status", "--porcelain").strip() == "M PROGRESS.md"
    # 원본 로컬 내용이 백업으로 그대로 보존됐다
    backups = _backups(state)
    assert len(backups) == 1 and backups[0].read_text() == local_content
    assert _backups(state, "base") == []  # 재현 가능한 중간 파일은 성공하면 지운다
    assert list(state.glob("*.upstream")) == [] and list(state.glob("*.merged")) == []


def test_upstream_edit_in_the_middle_and_local_append_at_the_end(repos):
    dev, vm, state = repos
    (vm / "PROGRESS.md").write_text(BASE_PROGRESS + "\n### VM 기록\n끝에 추가\n")
    _push_dev_commit(dev, progress=BASE_PROGRESS.replace("### 작업 2", "### 작업 1.5\n중간 삽입\n\n### 작업 2"))

    result = _flow(vm, state)

    assert "PULL-OK" in result.stdout and "FAILED" not in result.stdout
    merged = (vm / "PROGRESS.md").read_text()
    assert merged.index("중간 삽입") < merged.index("둘째 항목") < merged.index("끝에 추가")
    assert "<<<<<<<" not in merged


def test_local_only_lines_survive_two_consecutive_deploys(repos):
    dev, vm, state = repos
    (vm / "PROGRESS.md").write_text(BASE_PROGRESS + "\n### VM 기록\n유지돼야 함\n")
    _push_dev_commit(dev, progress=BASE_PROGRESS + "\n### 작업 3\nA\n")
    assert "PULL-OK" in _flow(vm, state).stdout
    _push_dev_commit(dev, progress=BASE_PROGRESS + "\n### 작업 3\nA\n\n### 작업 4\nB\n")
    result = _flow(vm, state)
    assert "PULL-OK" in result.stdout and "FAILED" not in result.stdout
    merged = (vm / "PROGRESS.md").read_text()
    assert merged.count("유지돼야 함") == 1 and "### 작업 4" in merged


def test_untouched_when_upstream_does_not_change_progress(repos):
    dev, vm, state = repos
    local_content = BASE_PROGRESS + "\n### VM 기록\n그대로\n"
    (vm / "PROGRESS.md").write_text(local_content)
    _push_dev_commit(dev, notes="new notes\n")

    result = _flow(vm, state)

    assert "PULL-OK" in result.stdout and "FAILED" not in result.stdout
    assert (vm / "PROGRESS.md").read_text() == local_content
    assert (vm / "notes.txt").read_text() == "new notes\n"
    assert _backups(state) == []  # 겹치지 않으면 아무 것도 안 한다


def test_clean_local_progress_is_a_plain_pull(repos):
    dev, vm, state = repos
    _push_dev_commit(dev, progress=BASE_PROGRESS + "\n### 작업 3\n새 항목\n")

    result = _flow(vm, state)

    assert "PULL-OK" in result.stdout and "FAILED" not in result.stdout
    assert "새 항목" in (vm / "PROGRESS.md").read_text()
    assert _backups(state) == []
    assert _git(vm, "status", "--porcelain").strip() == ""


def test_pull_blocked_by_another_file_restores_progress_exactly(repos):
    dev, vm, state = repos
    local_progress = BASE_PROGRESS + "\n### VM 기록\n복원돼야 함\n"
    (vm / "PROGRESS.md").write_text(local_progress)
    (vm / "notes.txt").write_text("VM 쪽 로컬 수정\n")  # 다른 파일의 미커밋 수정 — 이건 여전히 pull을 막아야 한다
    _push_dev_commit(dev, progress=BASE_PROGRESS + "\n### 작업 3\nX\n", notes="dev notes\n")

    result = _flow(vm, state)

    assert "PULL-FAILED" in result.stdout and "RESTORE-FAILED" not in result.stdout
    assert (vm / "PROGRESS.md").read_text() == local_progress  # 예전 그대로 복원
    assert (vm / "notes.txt").read_text() == "VM 쪽 로컬 수정\n"  # 다른 파일은 건드리지 않았다
    assert _git(vm, "rev-parse", "HEAD") != _git(vm, "rev-parse", "origin/main")


def test_merge_failure_keeps_the_local_backup_and_reports_failure(repos):
    dev, vm, state = repos
    local_content = BASE_PROGRESS + "\n### VM 기록\n보관돼야 함\n"
    (vm / "PROGRESS.md").write_text(local_content)
    _push_dev_commit(dev, progress=BASE_PROGRESS + "\n### 작업 3\nX\n")

    result = _flow(vm, state, mode="show-fails")

    assert "REAPPLY-FAILED" in result.stdout
    backups = _backups(state)
    assert len(backups) == 1 and backups[0].read_text() == local_content  # 로컬 기록은 잃지 않는다
    assert "### 작업 3" in (vm / "PROGRESS.md").read_text()  # 워킹트리엔 새 upstream 버전
    assert list(state.glob("*.upstream")) == [] and list(state.glob("*.merged")) == []


def test_old_backups_are_pruned_but_the_newest_are_kept(repos):
    dev, vm, state = repos
    state.mkdir(parents=True)
    for i in range(12):
        (state / f"PROGRESS.local.20200101-0000{i:02d}-1").write_text(f"old {i}")
    (vm / "PROGRESS.md").write_text(BASE_PROGRESS + "\n### VM\n새 백업\n")
    _push_dev_commit(dev, progress=BASE_PROGRESS + "\n### 작업 3\nX\n")

    result = _flow(vm, state)

    assert "PULL-OK" in result.stdout and "FAILED" not in result.stdout
    names = [p.name for p in _backups(state)]
    assert len(names) == 10
    assert not any(n.endswith("000000-1") or n.endswith("000001-1") for n in names)  # 가장 오래된 것부터 삭제
    assert any(not n.startswith("PROGRESS.local.2020") for n in names)  # 방금 만든 백업은 남았다


def test_auto_deploy_wires_the_helpers_in_the_right_order():
    text = AUTO_DEPLOY.read_text()
    prepare = text.index("progress_prepare_for_pull \"$local_head\" \"$remote_head\"")
    pull = text.index("git_as_quant pull --ff-only")
    reapply = text.index("progress_reapply_after_pull \"$new_head\"")
    fail_branch = text.index("pull_status=$?")
    restore = text.index("progress_restore_after_failed_pull", fail_branch)
    assert prepare < pull < reapply < fail_branch < restore
    assert re.search(r"pull_status=\$\?\s*\n\s*progress_restore_after_failed_pull", text)  # $? 를 덮어쓰기 전에 잡는다
    assert 'source "$APP_DIR/deploy/progress_reconcile.sh"' in text


def test_scripts_have_valid_bash_syntax():
    for script in (LIB, AUTO_DEPLOY):
        subprocess.run(["bash", "-n", str(script)], check=True)


# ---- 여러 기록 파일(PROGRESS.md + docs/reports/README.md) ----------------------------------------------------------

REPORTS_BASE = "# reports\n\n## 색인\n- a.html\n\n## 끝\n"


def _add_reports_readme(dev: Path, vm: Path):
    """두 저장소 모두에 docs/reports/README.md를 커밋해 둔다(VM은 origin에서 다시 받는다)."""
    (dev / "docs" / "reports").mkdir(parents=True, exist_ok=True)
    (dev / "docs" / "reports" / "README.md").write_text(REPORTS_BASE)
    _git(dev, "add", "-A")
    _git(dev, "commit", "-q", "-m", "add reports readme")
    _git(dev, "push", "-q", "origin", "main")
    _git(vm, "pull", "-q", "--ff-only")


def test_reports_readme_local_inserts_survive_an_upstream_edit_elsewhere_in_the_file(repos):
    dev, vm, state = repos
    _add_reports_readme(dev, vm)
    local = REPORTS_BASE.replace("- a.html\n", "- a.html\n- vm_new.html — VM 에이전트가 끼워 넣은 색인\n")  # 중간 삽입(에이전트 방식)
    (vm / "docs" / "reports" / "README.md").write_text(local)
    (dev / "docs" / "reports" / "README.md").write_text(REPORTS_BASE + "- dev_added_at_end.html\n")
    _git(dev, "add", "-A")
    _git(dev, "commit", "-q", "-m", "dev edits reports readme")
    _git(dev, "push", "-q", "origin", "main")

    result = _flow(vm, state)

    assert "PULL-OK" in result.stdout and "FAILED" not in result.stdout, result.stdout + result.stderr
    merged = (vm / "docs" / "reports" / "README.md").read_text()
    assert "vm_new.html" in merged and "dev_added_at_end.html" in merged and "<<<<<<<" not in merged
    backups = sorted(state.glob("docs_reports_README.md.local.*"))
    assert len(backups) == 1 and backups[0].read_text() == local


def test_both_record_files_are_reconciled_in_one_pull(repos):
    dev, vm, state = repos
    _add_reports_readme(dev, vm)
    (vm / "PROGRESS.md").write_text(BASE_PROGRESS + "\n### VM 기록\n진행 기록\n")
    (vm / "docs" / "reports" / "README.md").write_text(REPORTS_BASE.replace("- a.html\n", "- a.html\n- vm.html\n"))
    (dev / "PROGRESS.md").write_text(BASE_PROGRESS + "\n### 작업 3\n개발\n")
    (dev / "docs" / "reports" / "README.md").write_text(REPORTS_BASE + "- dev.html\n")
    _git(dev, "add", "-A")
    _git(dev, "commit", "-q", "-m", "dev touches both")
    _git(dev, "push", "-q", "origin", "main")

    result = _flow(vm, state)

    assert "PULL-OK" in result.stdout and "FAILED" not in result.stdout, result.stdout + result.stderr
    progress = (vm / "PROGRESS.md").read_text()
    readme = (vm / "docs" / "reports" / "README.md").read_text()
    assert "진행 기록" in progress and "### 작업 3" in progress
    assert "vm.html" in readme and "dev.html" in readme
    assert len(_backups(state)) == 1 and len(sorted(state.glob("docs_reports_README.md.local.*"))) == 1
    changed = sorted(line.strip() for line in _git(vm, "status", "--porcelain").splitlines())
    assert changed == ["M PROGRESS.md", "M docs/reports/README.md"]  # VM 추가분은 계속 미커밋 상태로 남는다


def test_failed_pull_restores_every_pending_record_file(repos):
    dev, vm, state = repos
    _add_reports_readme(dev, vm)
    progress_local = BASE_PROGRESS + "\n### VM 기록\n복원 A\n"
    readme_local = REPORTS_BASE.replace("- a.html\n", "- a.html\n- vm.html\n")
    (vm / "PROGRESS.md").write_text(progress_local)
    (vm / "docs" / "reports" / "README.md").write_text(readme_local)
    (vm / "notes.txt").write_text("VM 쪽 로컬 수정\n")  # 목록에 없는 파일의 수정 — pull을 막아야 한다
    (dev / "PROGRESS.md").write_text(BASE_PROGRESS + "\n### 작업 3\nX\n")
    (dev / "docs" / "reports" / "README.md").write_text(REPORTS_BASE + "- dev.html\n")
    (dev / "notes.txt").write_text("dev notes\n")
    _git(dev, "add", "-A")
    _git(dev, "commit", "-q", "-m", "dev touches all")
    _git(dev, "push", "-q", "origin", "main")

    result = _flow(vm, state)

    assert "PULL-FAILED" in result.stdout and "RESTORE-FAILED" not in result.stdout
    assert (vm / "PROGRESS.md").read_text() == progress_local
    assert (vm / "docs" / "reports" / "README.md").read_text() == readme_local
    assert (vm / "notes.txt").read_text() == "VM 쪽 로컬 수정\n"


def test_unlisted_files_still_block_the_pull_untouched(repos):
    dev, vm, state = repos
    (vm / "notes.txt").write_text("로컬 수정\n")
    _push_dev_commit(dev, notes="dev notes\n")
    result = _flow(vm, state)
    assert "PULL-FAILED" in result.stdout
    assert (vm / "notes.txt").read_text() == "로컬 수정\n"
    assert _backups(state) == []
