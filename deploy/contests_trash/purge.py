"""AI 대회 휴지통 비우기 — /srv/contests/.trash/<slug>-<YYYYmmdd-HHMMSS> 중 TRASH_DAYS 일 지난 것을 완전히 지운다.

관제 센터 'VM 폴더 삭제' 는 폴더를 이 휴지통으로 옮기기만 한다(core/contests.py trash_local — 허브(quant)는
폴더 안의 ubuntu 소유 파일을 지울 수 없다). quant-contests-trash.timer 가 하루 한 번 root 로 이 스크립트를 돌린다.
이름 형식이 맞는 휴지통 바로 아래 항목만 지우고, 심볼릭 링크는 따라가지 않는다. --dry-run 은 목록만 출력한다.
"""

from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

TRASH = Path("/srv/contests/.trash")
TRASH_DAYS = 7
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}-(\d{8}-\d{6})$")


def due(trash: Path = TRASH, now: datetime | None = None, days: int = TRASH_DAYS) -> list[Path]:
    now = now or datetime.now()
    out = []
    for p in sorted(trash.iterdir()) if trash.is_dir() else []:
        m = NAME_RE.match(p.name)
        if not m or p.is_symlink() or not p.is_dir():
            continue
        if now - datetime.strptime(m.group(1), "%Y%m%d-%H%M%S") >= timedelta(days=days):
            out.append(p)
    return out


def main() -> int:
    dry = "--dry-run" in sys.argv
    for p in due():
        print(("지울 예정: " if dry else "삭제: ") + str(p))
        if not dry:
            shutil.rmtree(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
