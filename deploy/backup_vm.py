#!/usr/bin/env python3
"""VM에만 있는 비밀 아닌 산출물을 매일 버전 관리형으로 백업한다 (stdlib만 사용, quant 계정으로 실행).

왜 필요한가: 이 VM 한 대에만 있는 것들 — `data/quant.db`(포트폴리오/관심종목/전략 결과), 리서치 에이전트가 만든
미커밋 산출물(`analysis/`, `docs/experiment_validation/` …), 에이전트가 PROGRESS.md에 미커밋으로 덧붙인 기록 —
이 디스크 하나에 달려 있다. 디스크가 사라지면 전부 사라진다.

무엇을 백업하나 (허용 목록 방식 — 여기 없는 건 절대 안 들어간다):
  - `data/quant.db` : sqlite 온라인 백업 API로 일관된 사본을 만든다(쓰는 도중에 복사해도 안전).
  - git 기준 "아직 커밋 안 된" 파일(미추적 + 수정됨) 중 ALLOWED_PREFIXES 아래의 것만. 이미 GitHub에 있는 파일은 복사하지 않는다.
  - 점(.)으로 시작하는 런타임 폴더(.claude, .codex, .ssh, .codex-telegram-runtime, .config …)는 인증 정보가 들어 있어
    허용 목록에 없으므로 어떤 경우에도 제외된다. 허용 폴더 안이라도 비밀처럼 생긴 파일명/내용은 격리(quarantine)한다.

어디에 두나: BACKUP_DIR(기본 /opt/quant-backup)/repo — 로컬 git 저장소. 매일 바뀐 것만 커밋하므로 버전 이력이 남고(델타 압축),
같은 디스크에 있는 사본이라 "실수로 지움/파일 손상"은 막아주지만 디스크 소실은 못 막는다. 그래서 BACKUP_DIR/remote 파일에
**비공개** 저장소 URL이 있으면 거기로도 push한다(전용 배포 키 BACKUP_DIR/ssh/id_ed25519 사용). 이 저장소(Quant)는 공개라서
백업을 여기 올리면 안 된다 — 반드시 별도의 비공개 저장소여야 한다.

"써졌다"와 "복구된다"는 다르다 — 그래서 매 실행마다 (1) MANIFEST의 sha256로 저장본 전체를 다시 검증하고 DB 사본의 무결성을 확인하며,
원격 push 뒤에는 원격의 HEAD가 로컬과 같은지 확인한다. 또 7일에 한 번은 **복구 리허설**을 한다: 백업 저장소(원격이 있으면 원격, 없으면
로컬)를 임시 폴더에 새로 클론해 같은 검증을 통과하는지 본다(실제로 되살릴 수 있는 사본인지의 유일한 증거).

상태는 BACKUP_DIR/status.json 에 기록되어 브리핑/워치독이 읽는다. 원격이 설정 안 됐으면 status의 offsite_configured=false.

사용법: python3 deploy/backup_vm.py [--dry-run]
환경변수(테스트/운영 조정용): QUANT_APP_DIR, QUANT_BACKUP_DIR, BACKUP_MAX_FILE_MB(기본 90)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

DEFAULT_APP_DIR = "/opt/quant"
DEFAULT_BACKUP_DIR = "/opt/quant-backup"
DEFAULT_MAX_FILE_MB = 90  # GitHub은 100MB 넘는 파일 push를 거부한다
RESTORE_DRILL_EVERY_DAYS = 7
SECRET_SCAN_MAX_BYTES = 5 * 1024 * 1024

# 허용 목록: git 상 "커밋 안 된" 파일 중 이 경로 아래(또는 정확히 이 파일)만 백업한다.
ALLOWED_PREFIXES = (
    "analysis/",
    "analysis.root_backup_",
    "docs/",
    "deploy/research_agents/",
    ".experiment-control/",
    "PROGRESS.md",
    "RESUME_NOTE.md",
    "data/process_toggles.json",
)
# 허용 폴더 안에서도 뺄 것: 대용량 체크포인트 tar.gz(수백 MB, 매번 새 blob), 락 파일
EXCLUDED_PREFIXES = (
    ".experiment-control/checkpoints/",
    ".experiment-control/agent.lock",
)
SECRET_NAME_RE = re.compile(
    r"(^|/)(\.env[^/]*|.*\.pem|.*\.key|.*\.p12|id_(rsa|ed25519|ecdsa)[^/]*|auth\.json|credentials[^/]*|telegram\.env|.*\.token)$",
    re.IGNORECASE,
)
SECRET_CONTENT_RES = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    re.compile(rb"\bghp_[A-Za-z0-9]{30,}"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"\bsk-[A-Za-z0-9]{32,}"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(rb"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),  # 텔레그램 봇 토큰 모양
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def git_lines(app_dir: Path, *args: str) -> list[str]:
    """NUL 구분 출력을 안전하게 읽는다(한글/공백 경로 대비, -z)."""
    result = run(["git", "-C", str(app_dir), *args, "-z"])
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 실패: {result.stderr.strip()[:200]}")
    return [p for p in result.stdout.split("\0") if p]


def is_allowed(relpath: str) -> bool:
    if any(relpath.startswith(p) for p in EXCLUDED_PREFIXES):
        return False
    return any(relpath.startswith(p) for p in ALLOWED_PREFIXES)


def find_secret(path: Path, relpath: str) -> str | None:
    """비밀처럼 보이는 이유(문자열)를 돌려준다. 없으면 None. 이유에는 내용 일부를 넣지 않는다."""
    if SECRET_NAME_RE.search(relpath):
        return "파일명이 비밀 파일 패턴"
    try:
        if path.stat().st_size > SECRET_SCAN_MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return "읽을 수 없음"
    for pattern in SECRET_CONTENT_RES:
        if pattern.search(data):
            return "내용이 비밀(키/토큰) 패턴과 일치"
    return None


def collect_files(app_dir: Path, max_bytes: int) -> tuple[dict[str, Path], list[dict], list[dict]]:
    """(백업할 {상대경로: 원본}, 크기 초과로 건너뛴 목록, 비밀 의심으로 격리한 목록)."""
    candidates = set(git_lines(app_dir, "ls-files", "--others", "--exclude-standard"))
    candidates |= set(git_lines(app_dir, "ls-files", "--modified"))
    wanted: dict[str, Path] = {}
    skipped: list[dict] = []
    quarantined: list[dict] = []
    for rel in sorted(candidates):
        if not is_allowed(rel):
            continue
        src = app_dir / rel
        if src.is_symlink() or not src.is_file():
            continue
        size = src.stat().st_size
        if size > max_bytes:
            skipped.append({"path": rel, "size": size, "reason": "너무 큼"})
            continue
        reason = find_secret(src, rel)
        if reason:
            quarantined.append({"path": rel, "reason": reason})
            continue
        wanted[rel] = src
    return wanted, skipped, quarantined


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database(app_dir: Path, dest: Path) -> dict | None:
    """sqlite 온라인 백업으로 일관된 사본을 만든다. DB가 없으면 None."""
    source = app_dir / "data" / "quant.db"
    if not source.is_file():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(tmp)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    check = sqlite3.connect(tmp)
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if ok != "ok":
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"DB 백업 무결성 검사 실패: {ok}")
    os.replace(tmp, dest)
    return {"path": "db/quant.db", "size": dest.stat().st_size, "sha256": sha256_of(dest)}


def sync_tree(repo: Path, wanted: dict[str, Path]) -> dict[str, dict]:
    """repo/files 를 wanted 와 똑같이 맞춘다(바뀐 것만 복사, 사라진 것은 삭제). {상대경로: {size, sha256}} 반환."""
    files_root = repo / "files"
    files_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    for rel, src in wanted.items():
        digest = sha256_of(src)
        dest = files_root / rel
        if not dest.is_file() or sha256_of(dest) != digest:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
        manifest[rel] = {"size": src.stat().st_size, "sha256": digest}
    for existing in sorted(files_root.rglob("*"), reverse=True):
        if existing.is_file():
            if existing.relative_to(files_root).as_posix() not in wanted:
                existing.unlink()
        elif existing.is_dir() and not any(existing.iterdir()):
            existing.rmdir()
    return manifest


def ensure_repo(repo: Path) -> None:
    if (repo / ".git").is_dir():
        return
    repo.mkdir(parents=True, exist_ok=True)
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.name", "quant-vm-backup"],
        ["git", "config", "user.email", "quant-vm-backup@localhost"],
        ["git", "config", "commit.gpgsign", "false"],
    ):
        result = run(cmd, cwd=repo)
        if result.returncode != 0:
            raise RuntimeError(f"백업 저장소 초기화 실패: {result.stderr.strip()[:200]}")


def commit_if_changed(repo: Path, message: str) -> bool:
    run(["git", "add", "-A"], cwd=repo)
    if run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode == 0:
        return False
    result = run(["git", "commit", "-q", "-m", message], cwd=repo)
    if result.returncode != 0:
        raise RuntimeError(f"백업 커밋 실패: {result.stderr.strip()[:200]}")
    return True


def stored_path(repo: Path, key: str) -> Path:
    """MANIFEST 키 → 백업 저장소 안의 실제 위치. DB는 db/, 나머지는 files/ 아래."""
    return repo / key if key == "db/quant.db" else repo / "files" / key


def verify_backup(repo: Path, *, check_git: bool = True) -> list[str]:
    """저장된 백업이 MANIFEST와 바이트 단위로 일치하는지, DB 사본이 멀쩡한지 확인한다. 문제 목록(비어 있으면 정상)."""
    problems: list[str] = []
    try:
        manifest = json.loads((repo / "MANIFEST.json").read_text())["files"]
    except (OSError, ValueError, KeyError) as exc:
        return [f"MANIFEST.json을 읽을 수 없음: {type(exc).__name__}"]
    for key, meta in manifest.items():
        path = stored_path(repo, key)
        if not path.is_file():
            problems.append(f"파일 없음: {key}")
        elif path.stat().st_size != meta["size"] or sha256_of(path) != meta["sha256"]:
            problems.append(f"내용 불일치: {key}")
        if len(problems) >= 10:
            problems.append("… (문제가 더 있음)")
            break
    db_copy = repo / "db" / "quant.db"
    if db_copy.is_file():
        try:
            conn = sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True)
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    problems.append("DB 사본 무결성 검사 실패")
                elif conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 0:
                    problems.append("DB 사본에 테이블이 없음")
            finally:
                conn.close()
        except sqlite3.Error as exc:
            problems.append(f"DB 사본을 열 수 없음: {exc}")
    if check_git:
        dirty = run(["git", "status", "--porcelain"], cwd=repo)
        if dirty.stdout.strip():
            problems.append("커밋되지 않은 변경이 남아 있음")
        fsck = run(["git", "fsck", "--connectivity-only", "--no-dangling"], cwd=repo, timeout=300)
        if fsck.returncode != 0:
            problems.append("git 저장소 무결성 검사(fsck) 실패")
    return problems


def offsite_env(backup_dir: Path) -> dict:
    env = dict(os.environ)
    key = backup_dir / "ssh" / "id_ed25519"
    if key.is_file():
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {key} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes "
            f"-o UserKnownHostsFile={backup_dir / 'ssh' / 'known_hosts'}"
        )
    return env


def remote_url(backup_dir: Path) -> str:
    remote_file = backup_dir / "remote"
    return remote_file.read_text().strip() if remote_file.is_file() else ""


def restore_drill(backup_dir: Path, repo: Path) -> tuple[bool, str, str | None]:
    """복구 리허설: 백업을 임시 폴더에 새로 클론해 verify_backup을 통과하는지 본다. (성공 여부, 출처, 오류).

    원격이 설정돼 있으면 원격에서(=디스크가 사라진 뒤 실제로 하게 될 경로), 아니면 로컬 백업 저장소에서 받는다.
    """
    url = remote_url(backup_dir)
    source, src = ("offsite", url) if url else ("local", str(repo))
    work = Path(tempfile.mkdtemp(prefix="restore-drill-", dir=backup_dir))
    try:
        clone = run(["git", "clone", "-q", "--no-local", "--", src, str(work / "restore")], env=offsite_env(backup_dir), timeout=1200)
        if clone.returncode != 0:
            return False, source, f"클론 실패: {(clone.stderr.strip().splitlines() or ['?'])[-1][:160]}"
        problems = verify_backup(work / "restore", check_git=False)
        if problems:
            return False, source, f"복구본 검증 실패: {problems[0]}"
        return True, source, None
    except Exception as exc:  # noqa: BLE001
        return False, source, f"{type(exc).__name__}: {exc}"[:200]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def remote_head_matches(backup_dir: Path, repo: Path) -> tuple[bool, str | None]:
    """push 직후 원격 main의 HEAD가 로컬 HEAD와 같은지(=push가 실제로 반영됐는지)."""
    local = run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    remote = run(["git", "ls-remote", "origin", "refs/heads/main"], cwd=repo, env=offsite_env(backup_dir), timeout=120)
    if remote.returncode != 0:
        return False, "원격 HEAD를 확인하지 못함"
    remote_sha = remote.stdout.split()[0] if remote.stdout.strip() else ""
    return (local == remote_sha), (None if local == remote_sha else "push 뒤 원격 HEAD가 로컬과 다름")


def push_offsite(backup_dir: Path, repo: Path) -> tuple[bool, str | None]:
    """(설정됨, 오류). remote 파일이 없거나 비어 있으면 (False, None)."""
    url = remote_url(backup_dir)
    if not url:
        return False, None
    env = offsite_env(backup_dir)
    if run(["git", "remote", "get-url", "origin"], cwd=repo).returncode == 0:
        run(["git", "remote", "set-url", "origin", url], cwd=repo)
    else:
        run(["git", "remote", "add", "origin", url], cwd=repo)
    result = run(["git", "push", "-q", "origin", "HEAD:main"], cwd=repo, env=env, timeout=900)
    if result.returncode != 0:
        # 오류 문구에 URL/키 경로가 섞일 수 있어 앞부분만 짧게 남긴다.
        return True, (result.stderr.strip().splitlines() or ["push 실패"])[-1][:200]
    matches, mismatch_error = remote_head_matches(backup_dir, repo)
    return True, (None if matches else mismatch_error)


def read_status(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def write_status(path: Path, status: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2))
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def default_alert(message: str) -> None:
    script = Path(__file__).resolve().parent / "send_telegram_alert.sh"
    if script.is_file():
        try:
            run(["bash", str(script), message], timeout=60)
        except Exception:
            pass


def run_backup(
    app_dir: Path,
    backup_dir: Path,
    *,
    max_file_mb: int = DEFAULT_MAX_FILE_MB,
    dry_run: bool = False,
    alert: Callable[[str], None] = default_alert,
    now: Callable[[], datetime] = utc_now,
) -> dict:
    """백업 한 번을 수행하고 status dict를 돌려준다. 실패해도 status.json에 남긴다."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    status_path = backup_dir / "status.json"
    previous = read_status(status_path)
    started = now()
    status = {
        "last_run_at": started.isoformat(),
        "last_run_epoch": started.timestamp(),
        "last_success_at": previous.get("last_success_at"),
        "last_success_epoch": previous.get("last_success_epoch"),
        "last_push_success_at": previous.get("last_push_success_at"),
        "last_push_success_epoch": previous.get("last_push_success_epoch"),
        "last_restore_drill_at": previous.get("last_restore_drill_at"),
        "last_restore_drill_epoch": previous.get("last_restore_drill_epoch"),
        "restore_drill_ok": previous.get("restore_drill_ok"),
        "restore_drill_source": previous.get("restore_drill_source"),
        "restore_drill_error": previous.get("restore_drill_error"),
        "ok": False,
        "error": None,
        "push_error": None,
        "offsite_configured": False,
        "files": 0,
        "bytes": 0,
        "skipped": [],
        "quarantined": [],
        "committed": False,
    }
    drill_ran = False
    try:
        wanted, skipped, quarantined = collect_files(app_dir, max_file_mb * 1024 * 1024)
        status["skipped"], status["quarantined"] = skipped, quarantined
        if dry_run:
            status["files"] = len(wanted)
            status["bytes"] = sum(p.stat().st_size for p in wanted.values())
            status["ok"] = True
            return status

        repo = backup_dir / "repo"
        ensure_repo(repo)
        manifest = sync_tree(repo, wanted)
        db_entry = backup_database(app_dir, repo / "db" / "quant.db")
        if db_entry:
            manifest[db_entry["path"]] = {"size": db_entry["size"], "sha256": db_entry["sha256"]}
        (repo / "MANIFEST.json").write_text(json.dumps(
            {"files": manifest, "skipped": skipped, "quarantined": quarantined}, ensure_ascii=False, indent=1, sort_keys=True
        ))
        status["files"] = len(manifest)
        status["bytes"] = sum(v["size"] for v in manifest.values())
        status["committed"] = commit_if_changed(repo, f"backup {started.strftime('%Y-%m-%d %H:%M UTC')}")
        # 방금 쓴 백업이 MANIFEST와 일치하고 DB 사본이 멀쩡한지 확인한다 — 아니면 성공으로 치지 않고 밖으로 올리지도 않는다.
        verify_problems = verify_backup(repo)
        if verify_problems:
            raise RuntimeError("백업 검증 실패: " + "; ".join(verify_problems[:3]))
        status["ok"] = True
        status["last_success_at"], status["last_success_epoch"] = started.isoformat(), started.timestamp()

        configured, push_error = push_offsite(backup_dir, repo)
        status["offsite_configured"], status["push_error"] = configured, push_error
        if configured and push_error is None:
            status["last_push_success_at"], status["last_push_success_epoch"] = started.isoformat(), started.timestamp()

        # 7일에 한 번 복구 리허설(push가 실패한 회차에는 원격이 최신이 아니므로 건너뛴다).
        last_drill = previous.get("last_restore_drill_epoch")
        drill_due = last_drill is None or (started.timestamp() - last_drill) >= RESTORE_DRILL_EVERY_DAYS * 86400
        if drill_due and push_error is None:
            drill_ok, drill_source, drill_error = restore_drill(backup_dir, repo)
            status.update(
                last_restore_drill_at=started.isoformat(), last_restore_drill_epoch=started.timestamp(),
                restore_drill_ok=drill_ok, restore_drill_source=drill_source, restore_drill_error=drill_error,
            )
            drill_ran = True
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 status에 남기고 알린다
        status["error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        if not dry_run:
            write_status(status_path, status)

    problems = []
    if status["error"]:
        problems.append(f"백업 실패: {status['error']}")
    if status["push_error"]:
        problems.append(f"비공개 저장소 push 실패(로컬 백업은 성공): {status['push_error']}")
    if drill_ran and status["restore_drill_ok"] is False:
        problems.append(f"복구 리허설 실패({status['restore_drill_source']}): {status['restore_drill_error']}")
    if status["quarantined"]:
        problems.append(f"비밀 의심으로 백업에서 제외된 파일 {len(status['quarantined'])}개(예: {status['quarantined'][0]['path']})")
    if status["skipped"]:
        problems.append(f"너무 커서 건너뛴 파일 {len(status['skipped'])}개(예: {status['skipped'][0]['path']})")
    if problems and not dry_run:
        alert("[VM 백업] 확인 필요\n" + "\n".join(f"- {p}" for p in problems))
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="파일 목록만 계산하고 아무것도 쓰지 않는다")
    args = parser.parse_args(argv)
    app_dir = Path(os.environ.get("QUANT_APP_DIR", DEFAULT_APP_DIR))
    backup_dir = Path(os.environ.get("QUANT_BACKUP_DIR", DEFAULT_BACKUP_DIR))
    max_mb = int(os.environ.get("BACKUP_MAX_FILE_MB", DEFAULT_MAX_FILE_MB))
    started = time.time()
    status = run_backup(app_dir, backup_dir, max_file_mb=max_mb, dry_run=args.dry_run)
    summary = (
        f"백업 {'성공' if status['ok'] else '실패'}: 파일 {status['files']}개, {status['bytes'] / 1e6:.1f}MB, "
        f"커밋 {'있음' if status['committed'] else '없음(변경 없음)'}, "
        f"복구 리허설 {'정상' if status['restore_drill_ok'] else ('실패' if status['restore_drill_ok'] is False else '아직 없음')}, "
        f"비공개 저장소 {'push 성공' if status['offsite_configured'] and not status['push_error'] else ('push 실패' if status['offsite_configured'] else '미설정')}, "
        f"{time.time() - started:.1f}초"
    )
    print(summary)
    if status["error"]:
        print(status["error"], file=sys.stderr)
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
