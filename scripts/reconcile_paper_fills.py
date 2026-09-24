#!/usr/bin/env python3
"""실제 Alpaca *paper* 계정의 최근 체결을 조회해 백테스트 예상 체결과 대조한다 (읽기 전용).

이 도구는 GET 만 한다. 주문 제출·취소·수정 코드는 없다(제출은 core/paper_execution.py 만 한다).
자격증명은 환경변수에서만 읽고, 값은 출력하지도 저장하지도 않는다:
  ALPACA_PAPER_API_KEY, ALPACA_PAPER_API_SECRET

사용법 (VM 에서 사람이 실행):
  python scripts/reconcile_paper_fills.py --days 30
  python scripts/reconcile_paper_fills.py --days 30 --expectations /tmp/expected.json
  python scripts/reconcile_paper_fills.py --days 30 --reference-open   # 다음 시가를 캐시에서 채움
  python scripts/reconcile_paper_fills.py --days 30 --include-activities

--expectations 는 백테스트가 예상한 체결을 담은 JSON 이다(없으면 슬리피지는 계산되지 않고
체결 분류·지연·수량만 나온다):
  {"<client_order_id>": {"expected_price": 100.0, "expected_quantity": 3.0,
                         "signal_time": "2026-09-01T20:00:00Z", "symbol": "AAPL", "side": "BUY"}}
client_order_id 는 core.paper_execution.client_order_id() 가 만든 값 그대로다.

--reference-open 은 expectations 에 expected_price 가 없는 주문에 대해 core.market_data 캐시에서
체결일 시가(백테스트의 체결 기준가)를 채운다. 가격 조회가 실패하면 그 주문은 슬리피지 없이 남는다.

출력은 stdout JSON 하나다. 표본이 30건 미만이면 요약에 'insufficient_sample' 이 찍히며
대표 슬리피지는 주장하지 않는다. 가정 비용(5/10/25bp)과의 비교표는 차이를 보여줄 뿐,
어느 쪽이 옳다는 판단이나 백테스트 결과 갱신은 하지 않는다.

종료 코드: 0 정상, 2 부분 실패(일부 페이지 조회 실패), 3 설정 오류(자격증명 없음 등).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.execution_reconciliation import (  # noqa: E402
    KEY_ENV, SECRET_ENV, MIN_SAMPLE_FOR_REPRESENTATIVE, AlpacaFillReader, FillQueryError, build_report,
)

EXIT_OK, EXIT_PARTIAL, EXIT_SETUP = 0, 2, 3


def _load_expectations(path: str | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("--expectations 파일은 {client_order_id: {...}} 형태여야 합니다")
    return data


def _fill_reference_opens(orders: list[dict[str, Any]], expectations: dict[str, dict[str, Any]]) -> list[str]:
    """expected_price 가 없는 주문에 체결일 시가를 채운다(캐시/네트워크 가격 조회). 실패는 메모만."""
    notes: list[str] = []
    try:
        from core.market_data import get_price_history
    except Exception as exc:  # pragma: no cover - 환경 의존
        return [f"market_data unavailable: {type(exc).__name__}"]
    wanted: dict[str, set[str]] = {}
    for order in orders:
        cid = str(order.get("client_order_id") or "")
        if not cid or expectations.get(cid, {}).get("expected_price"):
            continue
        filled_at = str(order.get("filled_at") or "")[:10]
        symbol = str(order.get("symbol") or "")
        if filled_at and symbol:
            wanted.setdefault(symbol, set()).add(filled_at)
    cache: dict[tuple[str, str], float] = {}
    for symbol, days in wanted.items():
        start = min(days)
        end = (datetime.fromisoformat(max(days)) + timedelta(days=5)).date().isoformat()
        try:
            history = get_price_history(symbol, start=start, end=end)
        except Exception as exc:
            notes.append(f"{symbol}: price lookup failed ({type(exc).__name__})")
            continue
        if history is None or getattr(history, "empty", True):
            notes.append(f"{symbol}: no price rows")
            continue
        for ts, row in history.iterrows():
            cache[(symbol, str(ts)[:10])] = float(row["Open"])
    for order in orders:
        cid = str(order.get("client_order_id") or "")
        if not cid or expectations.get(cid, {}).get("expected_price"):
            continue
        key = (str(order.get("symbol") or ""), str(order.get("filled_at") or "")[:10])
        if key in cache:
            entry = expectations.setdefault(cid, {})
            entry["expected_price"] = cache[key]
            entry.setdefault("expected_price_source", "market_data open of fill date")
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alpaca paper 체결 vs 백테스트 예상 체결 대조 (읽기 전용)")
    parser.add_argument("--days", type=int, default=30, help="최근 N일 (기본 30)")
    parser.add_argument("--expectations", help="예상 체결 JSON 경로")
    parser.add_argument("--reference-open", action="store_true", help="expected_price 없는 주문에 체결일 시가를 채운다")
    parser.add_argument("--include-activities", action="store_true", help="/v2/account/activities FILL 건수도 조회")
    parser.add_argument("--min-sample", type=int, default=MIN_SAMPLE_FOR_REPRESENTATIVE)
    parser.add_argument("--rows", action="store_true", help="주문별 상세 행도 출력")
    args = parser.parse_args(argv)

    if not os.getenv(KEY_ENV) or not os.getenv(SECRET_ENV):
        print(json.dumps({"error": f"{KEY_ENV} / {SECRET_ENV} 환경변수가 필요합니다 (값은 출력되지 않음)"},
                         ensure_ascii=False))
        return EXIT_SETUP
    try:
        expectations = _load_expectations(args.expectations)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"expectations 파일을 읽을 수 없습니다: {type(exc).__name__}"}, ensure_ascii=False))
        return EXIT_SETUP

    since = datetime.now(timezone.utc) - timedelta(days=max(1, args.days))
    reader = AlpacaFillReader.from_env()
    try:
        fetched = reader.list_closed_orders(after=since)
    except FillQueryError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return EXIT_PARTIAL
    orders = fetched["orders"]
    notes: list[str] = []
    if args.reference_open:
        notes += _fill_reference_opens(orders, expectations)

    activities_meta: dict[str, Any] = {}
    if args.include_activities:
        try:
            activities = reader.list_fill_activities(after=since)
            activities_meta = {"n_fill_activities": len(activities["activities"]),
                               "partial": activities["partial"], "errors": activities["errors"]}
        except FillQueryError as exc:
            activities_meta = {"error": str(exc)}

    report = build_report(orders, expectations, min_sample=args.min_sample, query_meta={
        "since": since.isoformat(), "days": args.days, "pages": fetched["pages"],
        "n_closed_orders": len(orders), "partial": fetched["partial"], "errors": fetched["errors"],
        "expectations_supplied": len(expectations), "activities": activities_meta, "notes": notes,
    })
    if not args.rows:
        report.pop("rows", None)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return EXIT_PARTIAL if fetched["partial"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
