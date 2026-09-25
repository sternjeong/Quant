"""가설 레지스트리 사람용 관리 도구.

  list [상태...]                 가설 목록
  show <id>                      스펙·심판 결과
  add <spec.json> <signal.py>    사람이 쓴 가설을 등록→동결→즉시 심판(시도 수에 똑같이 누적된다)
  promote <id>                   승격 후보 → promoted_paper (paper 편입 자체는 아직 수동, 설계 6절 S6)
  retire <id> [사유]             retired 로 종료
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import hypothesis_judge as hj  # noqa: E402
from core import hypothesis_registry as reg  # noqa: E402


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    if cmd == "list":
        for h in reg.list_by_status(*rest):
            print(f"{h['id']}  {h['status']:<20} trials={h['n_trials']}  {h['spec']['thesis'][:70]}")
        print(json.dumps(reg.funnel(), ensure_ascii=False))
    elif cmd == "show":
        h = reg.get(rest[0])
        print(json.dumps({k: v for k, v in (h or {}).items() if k != "signal_code"}, ensure_ascii=False, indent=2, default=str))
    elif cmd == "add":
        spec = json.loads(Path(rest[0]).read_text(encoding="utf-8"))
        hid = reg.register_draft(spec)
        reg.freeze(hid, Path(rest[1]).read_text(encoding="utf-8"))
        out = hj.judge_frozen(hid)
        print(json.dumps({"id": hid, **{k: v for k, v in out.items() if k != "judge"},
                          "reasons": (out.get("judge") or {}).get("reasons")}, ensure_ascii=False, indent=2))
    elif cmd == "promote":
        reg.transition(rest[0], reg.PROMOTED, "사람 승인")
        print(f"{rest[0]} → {reg.PROMOTED}")
    elif cmd == "retire":
        reg.transition(rest[0], reg.RETIRED, " ".join(rest[1:]) or "사람 결정")
        print(f"{rest[0]} → {reg.RETIRED}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
