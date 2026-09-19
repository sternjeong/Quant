#!/usr/bin/env python3
"""선조치 후보고(act-first-report-after) 자율 결정을 위한 체크포인트 + 텔레그램 알림 도구.

2주 전략 검증 실험(docs/TWO_WEEK_STRATEGY_VALIDATION_PROTOCOL.md)의 감독 에이전트가 사전등록
모호함(B1/B2/B3류)이나 명백한 코드 결함을 스스로 판단해 처리할 때 쓴다. 사용자가 매번 응답할 때까지
멈추는 대신, (1) 손대기 전 스냅샷을 남기고 (2) 즉시 처리하고 (3) 텔레그램으로 "무엇을 왜 했는지 +
되돌리는 방법"을 보고한다. 사용자가 그 판단에 불만이면 체크포인트 ID로 정확히 그 시점 상태로 되돌릴
수 있다.

이 파일 자체는 core/ 관례를 따르지 않는다(core는 Streamlit app 전용 로직) — deploy/의 다른 무인
서비스(experiment_supervisor.py 등)와 동일하게 stdlib + core.telegram_notify만 사용하는 독립
스크립트다.

사용 예:
    python3 deploy/checkpoint_notify.py create --label b1-b2-b3-resolution \
        docs/experiment_validation .experiment-control
    python3 deploy/checkpoint_notify.py notify "B1/B2/B3 해결하고 Day 1 진행함. 되돌리려면: ..."
    python3 deploy/checkpoint_notify.py list
    python3 deploy/checkpoint_notify.py revert <checkpoint_id>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CHECKPOINT_DIR_NAME = "checkpoints"
LOG_NAME = "checkpoints.jsonl"


def _control_dir(root: Path) -> Path:
    d = root / ".experiment-control"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _checkpoint_dir(root: Path) -> Path:
    d = _control_dir(root) / CHECKPOINT_DIR_NAME
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _log_path(root: Path) -> Path:
    return _control_dir(root) / LOG_NAME


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _append_log(root: Path, entry: dict) -> None:
    with _log_path(root).open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_log(root: Path) -> list[dict]:
    path = _log_path(root)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def create_checkpoint(root: Path, label: str, paths: list[str], reason: str = "") -> dict:
    """paths(디렉터리/파일, root 기준 상대경로)를 tar.gz로 스냅샷하고 로그에 기록한다.

    되돌릴 때는 이 tar를 그대로 다시 풀어 그 시점 바이트로 덮어쓴다(현재 상태는 별도로
    보존하지 않음 — 필요하면 되돌리기 전에 새 체크포인트를 먼저 만들 것).
    """
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    checkpoint_id = f"{ts}_{label}"
    archive_path = _checkpoint_dir(root) / f"{checkpoint_id}.tar.gz"

    resolved = [(p, root / p) for p in paths]
    missing = [p for p, full in resolved if not full.exists()]

    with tarfile.open(archive_path, "w:gz") as tar:
        for rel, full in resolved:
            if full.exists():
                tar.add(full, arcname=rel)

    entry = {
        "id": checkpoint_id,
        "created_at": time.time(),
        "created_at_iso": ts,
        "label": label,
        "reason": reason,
        "paths": paths,
        "missing_paths_at_snapshot": missing,
        "archive": str(archive_path.relative_to(root)),
        "archive_sha256": _sha256_file(archive_path),
        "reverted": False,
    }
    _append_log(root, entry)
    return entry


def list_checkpoints(root: Path) -> list[dict]:
    return _read_log(root)


def find_checkpoint(root: Path, checkpoint_id: str) -> dict | None:
    matches = [e for e in _read_log(root) if e["id"] == checkpoint_id]
    return matches[-1] if matches else None


def revert_checkpoint(root: Path, checkpoint_id: str) -> dict:
    """체크포인트 tar를 그대로 풀어 스냅샷 당시 상태로 되돌린다.

    스냅샷 이후 새로 생긴 파일은 지우지 않는다(파괴적 삭제를 피하기 위해 의도적으로 additive-only
    복원 — 완전한 원상복구가 필요하면 별도로 diff를 확인할 것). 되돌리기 자체도 하나의 체크포인트로
    다시 기록되어, "되돌리기를 되돌리는" 것도 항상 가능하다.
    """
    entry = find_checkpoint(root, checkpoint_id)
    if entry is None:
        raise SystemExit(f"체크포인트를 찾을 수 없음: {checkpoint_id}")

    archive_path = root / entry["archive"]
    if not archive_path.exists():
        raise SystemExit(f"체크포인트 아카이브 파일이 없음: {archive_path}")

    actual_sha = _sha256_file(archive_path)
    if actual_sha != entry["archive_sha256"]:
        raise SystemExit(
            f"체크포인트 아카이브 무결성 불일치 (기록된 해시와 다름) — 복원 중단: {checkpoint_id}"
        )

    pre_revert = create_checkpoint(
        root,
        label=f"pre-revert-of-{checkpoint_id}",
        paths=entry["paths"],
        reason=f"revert_checkpoint({checkpoint_id}) 실행 직전 현재 상태 보존",
    )

    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(root, filter="data")

    revert_entry = {
        "id": f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_revert-{checkpoint_id}",
        "created_at": time.time(),
        "created_at_iso": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
        "label": f"revert-of-{checkpoint_id}",
        "reason": f"사용자 요청으로 {checkpoint_id} 시점으로 되돌림. 되돌리기 직전 상태는 "
                  f"{pre_revert['id']}에 보존됨.",
        "paths": entry["paths"],
        "missing_paths_at_snapshot": [],
        "archive": entry["archive"],
        "archive_sha256": entry["archive_sha256"],
        "reverted_to": checkpoint_id,
        "pre_revert_checkpoint": pre_revert["id"],
        "reverted": False,
    }
    _append_log(root, revert_entry)
    return revert_entry


def notify(text: str, checkpoint_id: str | None = None) -> bool:
    from core import telegram_notify  # 지연 import: root가 core/를 찾을 수 있는 상태일 때만 필요

    if checkpoint_id:
        text = (
            f"{text}\n\n"
            f"— 이 조치가 마음에 안 들면 답장으로 이렇게 보내세요 —\n"
            f"체크포인트 {checkpoint_id} 되돌려"
        )
    return telegram_notify.send_message(text)


def _cmd_create(args):
    entry = create_checkpoint(Path(args.root), args.label, args.paths, args.reason or "")
    print(json.dumps(entry, ensure_ascii=False, indent=2))


def _cmd_list(args):
    for e in list_checkpoints(Path(args.root)):
        print(f"{e['id']}\t{e.get('label','')}\t{'REVERTED' if e.get('reverted') else ''}")


def _cmd_revert(args):
    entry = revert_checkpoint(Path(args.root), args.checkpoint_id)
    print(json.dumps(entry, ensure_ascii=False, indent=2))


def _cmd_notify(args):
    ok = notify(args.text, args.checkpoint_id)
    print("전송 성공" if ok else "전송 실패 (설정 없음 또는 네트워크 오류)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="실험 루트 디렉터리 (기본: 현재 디렉터리)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="체크포인트 생성")
    p_create.add_argument("--label", required=True)
    p_create.add_argument("--reason", default="")
    p_create.add_argument("paths", nargs="+", help="root 기준 상대경로 (파일/디렉터리)")
    p_create.set_defaults(func=_cmd_create)

    p_list = sub.add_parser("list", help="체크포인트 목록")
    p_list.set_defaults(func=_cmd_list)

    p_revert = sub.add_parser("revert", help="체크포인트로 되돌리기")
    p_revert.add_argument("checkpoint_id")
    p_revert.set_defaults(func=_cmd_revert)

    p_notify = sub.add_parser("notify", help="텔레그램 알림 전송")
    p_notify.add_argument("text")
    p_notify.add_argument("--checkpoint-id", dest="checkpoint_id", default=None)
    p_notify.set_defaults(func=_cmd_notify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
