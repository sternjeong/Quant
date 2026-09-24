#!/usr/bin/env python3
"""Alpaca paper 계좌 스냅샷 1회 + 목표 대비 이탈 리포트를 stdout 에 JSON 으로 출력한다.

조회 전용이다 — 주문을 만들지도 제출하지도 않으며, core.paper_execution 을 import 하지 않는다.
API 키는 환경변수에서만 읽고 값은 절대 출력하지 않는다(있는지 여부만 표시한다).

VM 실행 예:
    export ALPACA_PAPER_API_KEY=...        # 값은 셸 히스토리에 남지 않게 주의
    export ALPACA_PAPER_API_SECRET=...
    cd /opt/quant && python scripts/sync_paper_account.py            # 저장 + 리포트
    python scripts/sync_paper_account.py --no-save                   # 저장 없이 리포트만

종료 코드: 0 성공, 2 키 없음(건너뜀), 1 조회 실패.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.account_sync import credentials_available, summarize_drift, sync_paper_account  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Alpaca paper 계좌 스냅샷 + 이탈 리포트 (조회 전용)")
    parser.add_argument("--no-save", action="store_true", help="DB에 저장하지 않고 리포트만 출력")
    args = parser.parse_args()

    result = sync_paper_account(persist=not args.no_save)
    payload = {
        "credentials_present": credentials_available(),  # 키 존재 여부만, 값은 없음
        "ok": result["ok"],
        "skipped": result["skipped"],
        "reason": result["reason"],
        "saved": result["saved"],
        "snapshot_id": result["snapshot_id"],
        "errors": result["errors"],
        "summary": summarize_drift(result["drift"]) if result.get("drift") else None,
        "drift": result["drift"],
        "informational_only": True,
        "note": "조회 전용 리포트입니다. 이 스크립트는 주문을 생성하거나 제출하지 않습니다.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if result["skipped"]:
        return 2
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
