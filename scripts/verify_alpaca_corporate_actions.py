#!/usr/bin/env python3
"""Alpaca Corporate Actions API 실제 응답 스키마 검증 (읽기 전용, 사람이 VM 에서 실행).

core/corporate_actions.py 의 파싱 가정이 실제 응답과 맞는지 확인한다. 알려진 사례를 조회해
PASS / FAIL / UNEXPECTED 로 판정하고 결과 JSON 을 stdout 으로 출력한다.

- 읽기 전용이다. 주문·계좌 변경 API 는 건드리지 않는다.
- 자격증명은 환경변수 ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET 에서만 읽으며,
  키·시크릿 값은 출력에 절대 포함하지 않는다.
- 판정 기준(사전 고정):
    PASS       기대한 기업행동을 찾았고 필수 필드(ex_date, 금액 또는 분할비율)가 채워졌다.
    FAIL       기대한 기업행동을 못 찾았거나 필수 필드가 비어 있다(파싱 가정이 틀렸을 수 있다).
    UNEXPECTED 조회 자체가 실패했거나(HTTP/네트워크), 응답에 모르는 그룹/필드가 있었다.

사용:  python scripts/verify_alpaca_corporate_actions.py [--no-cache] [--symbol AAPL]
종료코드: 0 = 전부 PASS, 1 = FAIL 있음, 2 = UNEXPECTED/실행 불가.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.corporate_actions import (  # noqa: E402
    GROUP_TO_TYPE,
    AlpacaCorporateActionsClient,
    CorporateActionsError,
)

# 알려진 사례(공개 정보). 기대값은 코드가 아니라 공시 사실에서 정했다.
CASES = [
    {
        "name": "AAPL 4:1 forward split 2020-08-31",
        "symbol": "AAPL",
        "start": "2020-08-01",
        "end": "2020-09-30",
        "expect_type": "forward_split",
        "expect_ex_date": "2020-08-31",
        "expect_split_ratio": 4.0,
    },
    {
        "name": "AAPL regular cash dividends 2024",
        "symbol": "AAPL",
        "start": "2024-01-01",
        "end": "2024-12-31",
        "expect_type": "cash_dividend",
        "expect_min_count": 3,          # 분기 배당이면 최소 3회는 나와야 한다
        "expect_amount_range": [0.05, 2.0],  # 주당 배당금의 상식적 범위
    },
]


def _check_case(client, case, use_cache: bool) -> dict:
    out = {"case": case["name"], "symbol": case["symbol"], "verdict": "UNEXPECTED",
           "notes": [], "found": 0}
    try:
        actions, from_cache = client.fetch_symbol(
            case["symbol"], case["start"], case["end"],
            ttl_seconds=None if use_cache else 0, use_cache=use_cache)
    except (CorporateActionsError, Exception) as exc:  # noqa: BLE001 - 사유만 기록
        out["notes"].append(f"fetch failed: {type(exc).__name__}: {exc}")
        return out
    out["from_cache"] = bool(from_cache)

    # 모르는 그룹/타입이 섞여 있으면 스키마 변화 신호
    unknown = [a for a in actions if a.type == "unknown"]
    if unknown:
        out["notes"].append(f"{len(unknown)} row(s) parsed as type=unknown "
                            f"(raw keys: {sorted({k for a in unknown for k in a.raw})})")

    matched = [a for a in actions if a.type == case["expect_type"]
               or (case["expect_type"] == "cash_dividend" and a.type == "special_cash_dividend")]
    out["found"] = len(matched)
    out["sample"] = [a.to_dict() for a in matched[:3]]
    for s in out["sample"]:
        s.pop("raw", None)

    problems: list[str] = []
    if not matched:
        problems.append(f"no {case['expect_type']} row found in {case['start']}..{case['end']}")
    if "expect_ex_date" in case and not any(a.ex_date == case["expect_ex_date"] for a in matched):
        problems.append(f"expected ex_date {case['expect_ex_date']} not present; "
                        f"got {[a.ex_date for a in matched]}")
    if "expect_split_ratio" in case:
        ratios = [a.split_ratio for a in matched]
        if case["expect_split_ratio"] not in [r for r in ratios if r is not None]:
            problems.append(f"expected split_ratio {case['expect_split_ratio']}; got {ratios}")
    if "expect_min_count" in case and len(matched) < case["expect_min_count"]:
        problems.append(f"expected at least {case['expect_min_count']} rows; got {len(matched)}")
    if "expect_amount_range" in case:
        lo, hi = case["expect_amount_range"]
        amounts = [a.amount for a in matched]
        if any(a is None for a in amounts):
            problems.append("some rows have amount=None (rate field missing or renamed)")
        elif matched and not all(lo <= a <= hi for a in amounts):
            problems.append(f"amount outside sanity range {lo}..{hi}: {amounts}")
    if any(a.ex_date is None for a in matched):
        problems.append("some rows have ex_date=None (ex_date field missing or renamed)")

    out["problems"] = problems
    out["verdict"] = "FAIL" if problems else ("PASS" if not unknown else "UNEXPECTED")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-cache", action="store_true", help="파일 캐시를 쓰지 않고 항상 새로 조회")
    ap.add_argument("--symbol", help="모든 케이스의 심볼을 이 값으로 덮어쓴다(선택)")
    args = ap.parse_args()

    report = {"endpoint": "https://data.alpaca.markets/v1/corporate-actions",
              "known_groups": sorted(GROUP_TO_TYPE), "results": []}

    if not (os.getenv("ALPACA_PAPER_API_KEY") and os.getenv("ALPACA_PAPER_API_SECRET")):
        report["error"] = ("ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET 환경변수가 없다. "
                           "값은 출력하지 않는다.")
        report["overall"] = "UNEXPECTED"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    try:
        client = AlpacaCorporateActionsClient.from_env()
    except CorporateActionsError as exc:
        report["error"] = str(exc)
        report["overall"] = "UNEXPECTED"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    for case in CASES:
        c = dict(case)
        if args.symbol:
            c["symbol"] = args.symbol
        report["results"].append(_check_case(client, c, use_cache=not args.no_cache))

    verdicts = {r["verdict"] for r in report["results"]}
    report["overall"] = ("UNEXPECTED" if "UNEXPECTED" in verdicts
                         else "FAIL" if "FAIL" in verdicts else "PASS")
    report["requests_made"] = client.request_count
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {"PASS": 0, "FAIL": 1, "UNEXPECTED": 2}[report["overall"]]


if __name__ == "__main__":
    raise SystemExit(main())
