"""검증 연구 작업 실행기 사람용 관리 도구 (core/research_jobs.py, 계약: docs/RESEARCH_JOBS.md).

  list                     작업 목록(상태·실패 수·실행 수·마지막 종료·사유)
  retry <id> [--fresh]     상태를 대기로 초기화(실패 수 0). --fresh 는 체크포인트도 지우고 처음부터
  cancel <id>              대기 작업은 즉시 취소, 실행 중이면 중단 요청(실행기가 몇 초 안에 멈춘다)

주문 경로와 무관하다. 실제 실행은 스케줄러 잡 research_job_runner 가 실행 창 안에서 한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import research_jobs as rj  # noqa: E402


def main(argv=None, cfg: rj.Config | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("list", "retry", "cancel"):
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "list":
            rows = rj.list_jobs(cfg)
            if not rows:
                print("등록된 작업이 없습니다 (research/jobs/<id>/job.json).")
            for row in rows:
                print(f"{row['id']:<32} {row['status']:<12} 실패 {row['failures']} · 실행 {row['runs']} · "
                      f"우선순위 {row['priority']} · 마지막 {row['last_finished_at'] or '-'}")
                if row["reason"]:
                    print(f"    사유: {rj.redact(row['reason'])[:200]}")
            return 0
        if not rest:
            print(f"사용법: {cmd} <id>")
            return 1
        if cmd == "retry":
            entry = rj.retry_job(rest[0], fresh="--fresh" in rest[1:], cfg=cfg)
            print(f"{rest[0]}: {entry['status']} 로 초기화 — 다음 실행 창에서 실행됩니다.")
            return 0
        print(f"{rest[0]}: {rj.cancel_job(rest[0], cfg=cfg)}")
        return 0
    except ValueError as exc:
        print(f"오류: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
