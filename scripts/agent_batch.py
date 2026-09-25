"""에이전트 야간 배치 진입점 (스케줄러 03:00 KST 잡이 서브프로세스로 실행). core/agent_batch.py 참고.

사용: python scripts/agent_batch.py [--dry-plan]
  --dry-plan : 에이전트를 실행하지 않고 지금 계획될 첫 작업과 예산만 출력한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from core import agent_batch, agent_budget  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-plan", action="store_true")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    if a.dry_plan:
        print(json.dumps({"next": agent_batch.plan(now, set()), "budget": agent_budget.summary(now)},
                         ensure_ascii=False, indent=2, default=str))
        return 0
    claude = os.environ.get("CLAUDE_BIN", "/usr/local/bin/claude")
    if not Path(claude).exists():
        print(f"Claude CLI 없음({claude}) — 배치 건너뜀")
        return 0
    from core.telegram_notify import send_message

    res = agent_batch.run_batch(notify=send_message)
    print(agent_batch.format_summary(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
