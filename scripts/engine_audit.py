"""주간 엔진 점검을 지금 바로 돌린다(core/engine_audit.py). 읽기 전용 — 상태를 고치지 않는다.

  python scripts/engine_audit.py            # 화면에만 출력
  python scripts/engine_audit.py --notify   # 텔레그램으로도 보내고 data/engine_audit/ 에 저장
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import engine_audit as ea  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--notify", action="store_true", help="텔레그램 전송 + 결과 저장")
    a = p.parse_args(argv)
    if a.notify:
        from core.telegram_notify import send_message

        report = ea.run_and_notify(send_message)
    else:
        report = ea.run_audit()
    print(ea.format_message(report))
    return 0 if report["overall"] != ea.FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
