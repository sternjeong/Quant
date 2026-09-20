"""systemd 유닛 상태 조회.

`quant` 계정(sudo 없음)도 `systemctl show`로 다른 유닛의 상태를 읽을 수 있음을 VM에서
직접 확인했다 (읽기 전용 조회는 systemd가 기본적으로 모든 사용자에게 허용). journalctl은
`adm`/`systemd-journal` 그룹이 아니면 권한이 없어 로그 조회는 지원하지 않는다.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class UnitStatus:
    active_state: str
    sub_state: str
    since: str

    @property
    def is_active(self) -> bool:
        return self.active_state == "active"

    @property
    def is_known(self) -> bool:
        return self.active_state != "unknown"


def get_unit_status(unit: str) -> UnitStatus:
    try:
        result = subprocess.run(
            [
                "systemctl", "show", unit,
                "-p", "ActiveState", "-p", "SubState", "-p", "ActiveEnterTimestamp",
            ],
            capture_output=True, text=True, timeout=5, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return UnitStatus(active_state="unknown", sub_state="unknown", since="")

    fields = dict(
        line.split("=", 1) for line in result.stdout.strip().splitlines() if "=" in line
    )
    since = fields.get("ActiveEnterTimestamp", "")
    return UnitStatus(
        active_state=fields.get("ActiveState") or "unknown",
        sub_state=fields.get("SubState") or "unknown",
        since="" if since in ("", "n/a") else since,
    )
