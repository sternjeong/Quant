"""VM 백업(deploy/backup_vm.py)이 남기는 status.json을 읽어 브리핑/워치독용 한 줄 요약으로 바꾼다 (2026-09-21 추가).

status.json은 백업 스크립트가 쓰고(BACKUP_DIR=/opt/quant-backup), 이 모듈은 읽기만 한다. 파일이 없으면(개발 PC 등 백업 미설치)
None — 호출자가 "백업 상태 없음"으로 정직하게 표시한다.

판정 기준(deploy/watchdog.py도 같은 숫자를 쓴다):
  - 마지막 성공 백업이 36시간 넘게 지남 → bad (매일 도는 백업이 하루 이상 빠짐)
  - 마지막 실행이 실패 → bad
  - 비공개 원격이 설정돼 있는데 마지막 push 성공이 72시간 넘게 지남 / 지금 push가 실패 → bad
  - 원격 미설정 → warn (같은 디스크에만 있어 디스크 소실을 못 막는다)
  - 비밀 의심으로 격리됐거나 너무 커서 건너뛴 파일 있음 → warn
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

STATUS_PATH = Path(os.environ.get("QUANT_BACKUP_STATUS_PATH", "/opt/quant-backup/status.json"))
STALE_BACKUP_HOURS = 36
STALE_PUSH_HOURS = 72


def load_backup_status(path: Path | None = None) -> dict | None:
    try:
        return json.loads((path or STATUS_PATH).read_text())
    except (OSError, ValueError):
        return None


def _hours_ago(epoch: float | None, now: float) -> float | None:
    return None if epoch is None else (now - epoch) / 3600


def describe_backup(status: dict | None, now: float | None = None) -> dict:
    """{"level": "none"|"ok"|"warn"|"bad", "lines": [str, ...]}"""
    if status is None:
        return {"level": "none", "lines": ["백업 상태 없음 — 이 환경에는 백업이 설치돼 있지 않거나 아직 한 번도 안 돌았음"]}
    now = time.time() if now is None else now
    level = "ok"
    lines: list[str] = []

    def raise_level(new: str) -> None:
        nonlocal level
        if {"ok": 0, "warn": 1, "bad": 2}[new] > {"ok": 0, "warn": 1, "bad": 2}[level]:
            level = new

    since_success = _hours_ago(status.get("last_success_epoch"), now)
    if not status.get("ok"):
        raise_level("bad")
        lines.append(f"마지막 백업 실패: {status.get('error') or '알 수 없는 오류'}")
    if since_success is None:
        raise_level("bad")
        lines.append("성공한 백업이 아직 한 번도 없음")
    elif since_success > STALE_BACKUP_HOURS:
        raise_level("bad")
        lines.append(f"마지막 성공 백업이 {since_success:.0f}시간 전 — 매일 도는 백업이 빠졌음")
    else:
        lines.append(f"마지막 백업 {since_success:.0f}시간 전 · 파일 {status.get('files', 0)}개 · {status.get('bytes', 0) / 1e6:.0f}MB")

    if not status.get("offsite_configured"):
        raise_level("warn")
        lines.append("비공개 저장소 미설정 — VM 같은 디스크에만 저장 중이라 디스크가 사라지면 복구 불가")
    elif status.get("push_error"):
        raise_level("bad")
        lines.append(f"비공개 저장소 push 실패: {status['push_error']}")
    else:
        since_push = _hours_ago(status.get("last_push_success_epoch"), now)
        if since_push is None or since_push > STALE_PUSH_HOURS:
            raise_level("bad")
            lines.append("비공개 저장소로 마지막 push 성공이 3일을 넘겼음")
        else:
            lines.append(f"비공개 저장소 push 정상 ({since_push:.0f}시간 전)")

    if status.get("quarantined"):
        raise_level("warn")
        lines.append(f"비밀 의심으로 백업에서 제외된 파일 {len(status['quarantined'])}개")
    if status.get("skipped"):
        raise_level("warn")
        lines.append(f"너무 커서 건너뛴 파일 {len(status['skipped'])}개")
    return {"level": level, "lines": lines}
