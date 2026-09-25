"""core/alpaca_market_meta.py — Alpaca 로 '주문이 실제로 가능한가'와 '시장이 열리는 날인가'를 확인한다(읽기 전용).

엔진 구멍 두 가지에 대응한다.
1. 챔피언이 고른 종목이 브로커에서 거래 불가(상장폐지·거래정지·비활성)여도 지금은 주문 단계에서야 발견된다.
   → `check_tradability` 가 종목별 status/tradable/fractionable/shortable 을 정규화해 **주문 전 사전 점검**을 가능하게 한다.
2. 휴장일은 코드에 하드코딩하거나 추정한다. → `fetch_trading_days` 가 브로커 캘린더(조기 폐장 포함)를 그대로 준다.

응답 스키마는 Alpaca 문서 기준 가정이며 실 API 로 아직 검증하지 않았다. 파싱 지점은 `_normalize_asset`,
`_normalize_calendar_row` 두 곳뿐이다. 네트워크는 주입 가능한 `get_json` 으로만 일어난다(테스트는 mock).
이 모듈은 GET 만 쓰고 주문 경로를 import 하지 않는다. 판정은 알림용이며 주문을 스스로 막지 않는다.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from core import account_sync

GetJson = Callable[[str], Any]

TRADABLE = "tradable"
NOT_TRADABLE = "not_tradable"
INACTIVE = "inactive"
NOT_FOUND = "not_found"
LOOKUP_FAILED = "lookup_failed"


def _normalize_asset(raw: dict) -> dict[str, Any]:
    status = str(raw.get("status") or "").lower()
    tradable = bool(raw.get("tradable"))
    if status and status != "active":
        verdict = INACTIVE
    elif not tradable:
        verdict = NOT_TRADABLE
    else:
        verdict = TRADABLE
    return {
        "symbol": raw.get("symbol"), "verdict": verdict, "status": status or None, "tradable": tradable,
        "fractionable": bool(raw.get("fractionable")), "shortable": bool(raw.get("shortable")),
        "exchange": raw.get("exchange"),
    }


def check_tradability(symbols: Iterable[str], *, get_json: Optional[GetJson] = None) -> dict[str, dict[str, Any]]:
    """종목별 거래 가능 여부. 한 종목 조회 실패가 나머지를 막지 않는다(lookup_failed 로 격리)."""
    get = get_json or account_sync._get_json
    out: dict[str, dict[str, Any]] = {}
    for sym in dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()):
        try:
            out[sym] = _normalize_asset(get(f"/v2/assets/{sym}"))
        except Exception as exc:  # noqa: BLE001 — 격리가 목적
            msg = str(exc)
            verdict = NOT_FOUND if ("404" in msg or "not found" in msg.lower()) else LOOKUP_FAILED
            out[sym] = {"symbol": sym, "verdict": verdict, "error": f"{type(exc).__name__}: {msg}"[:200]}
    return out


def untradable(report: dict[str, dict[str, Any]]) -> list[str]:
    """거래 가능이 '확인되지 않은' 종목. 조회 실패는 안전하게 여기 포함하지 않고 별도로 본다."""
    return sorted(s for s, r in report.items() if r["verdict"] in (NOT_TRADABLE, INACTIVE, NOT_FOUND))


def _normalize_calendar_row(raw: dict) -> dict[str, Any]:
    open_t, close_t = raw.get("open"), raw.get("close")
    return {
        "date": raw.get("date"), "open": open_t, "close": close_t,
        # 정규장은 16:00 마감. 그보다 이르면 조기 폐장(예: 13:00)이다.
        "early_close": bool(close_t) and str(close_t) < "16:00",
    }


def fetch_trading_days(start: str, end: str, *, get_json: Optional[GetJson] = None) -> list[dict[str, Any]]:
    """[start, end] (YYYY-MM-DD) 사이 개장일 목록. 목록에 없는 평일이 휴장일이다."""
    get = get_json or account_sync._get_json
    rows = get(f"/v2/calendar?start={start}&end={end}")
    if not isinstance(rows, list):
        raise ValueError("calendar 응답이 리스트가 아닙니다")
    return [_normalize_calendar_row(r) for r in rows]


def is_trading_day(day: str, *, get_json: Optional[GetJson] = None) -> Optional[bool]:
    """day 가 개장일이면 True, 휴장이면 False. 조회 실패 시 None(모르면 모른다고 답한다)."""
    try:
        return any(r["date"] == day for r in fetch_trading_days(day, day, get_json=get_json))
    except Exception:  # noqa: BLE001
        return None
