"""core/paper_auto_trade.py — 챔피언 계획을 Alpaca **paper** 계좌에 자동 제출하는 1회차 실행기(로드맵 P3).

기본 꺼짐이다(process_registry 의 default_enabled=False). 사용자가 텔레그램 /processes 로 켜야만 돈다.
켜져 있어도 아래 조건이 **모두 확인될 때만** 제출하고, 하나라도 거짓이거나 모르면 제출하지 않는다(fail-closed).

  1. 주문 엔드포인트가 paper 인가 (core.paper_execution.PAPER_BASE_URL)
  2. 키가 있는가
  3. 최근 7일 안에 Alpaca 읽기 전용 검증 전체 PASS 가 있는가 (core.alpaca_verification, P0)
  4. 오늘(미 동부 날짜)이 개장일이었는가 — 캘린더 조회 실패는 '모름'으로 보고 건너뛴다
  5. 오늘 이미 자동 제출하지 않았는가 (data/paper_auto/state.json)
  6. 계좌가 막혀 있지 않은가
  7. 계획의 매수 종목이 전부 브로커에서 거래 가능한가 (P1 사전 점검; 조회 실패도 불가로 본다)
  8. 주문 총액이 자산의 MAX_ORDER_VALUE_FRACTION 이하인가 (버그로 인한 과대 주문 차단)

제출은 기존 AlpacaPaperBroker.submit_plan 을 그대로 쓴다 — 슬리브 보류 게이트·회차 ID·멱등성은 거기서 다시 적용된다.
사람의 --confirm 대신 방금 만든 계획 자신의 fingerprint 를 넘기므로, 자동화가 우회하는 것은 '사람 확인' 하나뿐이다.
결과는 텔레그램 1건으로 알린다. 제출 시각은 미 장 마감 뒤(06:10 KST)라 market/day 주문은 다음 개장 시가에 체결된다고
가정한다(Alpaca 문서 기준, 실계정 미검증). live 계좌 경로는 없다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "paper_auto" / "state.json"
MAX_ORDER_VALUE_FRACTION = 1.1
KEEP_STATE_DAYS = 60


def _order_value(order: dict, positions: dict) -> float:
    if order.get("notional"):
        return float(order["notional"])
    return float(order.get("qty") or 0) * float((positions.get(order["symbol"]) or {}).get("current_price") or 0)


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = dict(sorted(state.items())[-KEEP_STATE_DAYS:])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(keep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _skip(reason: str, **extra) -> dict:
    return {"status": "skipped", "reason": reason, **extra}


def run_auto_round(
    *, now: Optional[datetime] = None, broker=None, core: Optional[dict] = None, satellite: Optional[dict] = None,
    run_store=None, state_path: Optional[Path] = None,
    credentials_fn: Optional[Callable[[], bool]] = None, recent_pass_fn: Optional[Callable[[], Any]] = None,
    trading_day_fn: Optional[Callable[[str], Optional[bool]]] = None,
    tradability_fn: Optional[Callable[[list], dict]] = None,
) -> dict:
    """조건을 확인하고 통과하면 1회차를 제출한다. 예외 대신 status 로 결과를 돌려준다(주입점은 테스트용)."""
    from core import paper_execution as pe

    if "paper-api" not in pe.PAPER_BASE_URL:
        return _skip("order endpoint is not paper")
    if credentials_fn is None:
        from core.account_sync import credentials_available as credentials_fn
    if not credentials_fn():
        return _skip("no_credentials")
    if recent_pass_fn is None:
        from core.alpaca_verification import find_recent_pass as recent_pass_fn
    if not recent_pass_fn():
        return _skip("no recent Alpaca verification PASS (P0)")
    et_day = (now or datetime.now(timezone.utc)).astimezone(ET).date().isoformat()
    if trading_day_fn is None:
        from core.alpaca_market_meta import is_trading_day as trading_day_fn
    open_day = trading_day_fn(et_day)
    if open_day is None:
        return _skip("calendar lookup failed (unknown trading day)", et_day=et_day)
    if not open_day:
        return _skip("market closed today", et_day=et_day)
    path = state_path or STATE_PATH
    state = _load_state(path)
    if et_day in state:
        return _skip("already submitted today", et_day=et_day)

    broker = broker or pe.AlpacaPaperBroker.from_env()
    account = broker.account()
    if account.get("trading_blocked") or account.get("account_blocked"):
        return _skip("paper account is blocked", et_day=et_day)
    if core is None or satellite is None:
        from core.champion_strategy import compute_core_recommendation, compute_satellite_recommendation_point_in_time

        core = core if core is not None else compute_core_recommendation()
        satellite = satellite if satellite is not None else compute_satellite_recommendation_point_in_time()
    from scripts.champion_paper_trade import build_plan

    positions = broker.positions()
    equity = float(account["equity"])
    plan = build_plan(core, satellite, positions, equity)
    if not plan["orders"]:
        state[et_day] = {"status": "no_orders", "fingerprint": plan["fingerprint"]}
        _save_state(path, state)
        return {"status": "no_orders", "et_day": et_day}
    buys = sorted({o["symbol"] for o in plan["orders"] if o["side"] == "buy"})
    if buys:
        if tradability_fn is None:
            from core.alpaca_market_meta import check_tradability as tradability_fn
        report = tradability_fn(buys)
        bad = sorted(s for s in buys if (report.get(s) or {}).get("verdict") != "tradable")
        if bad:
            return _skip("buy symbols not confirmed tradable", et_day=et_day, symbols=bad)
    total = sum(_order_value(o, positions) for o in plan["orders"])
    if total > MAX_ORDER_VALUE_FRACTION * equity:
        return _skip("order value exceeds cap", et_day=et_day, order_value=round(total, 2), equity=equity)

    from core.champion_strategy import CHAMPION_STRATEGY_VERSION

    results = broker.submit_plan(plan, plan["fingerprint"], run_store=run_store or pe.RunStore(),
                                 strategy_version=CHAMPION_STRATEGY_VERSION)
    states: dict[str, int] = {}
    for r in results:
        states[r["reconcile_state"]] = states.get(r["reconcile_state"], 0) + 1
    state[et_day] = {"status": "submitted", "fingerprint": plan["fingerprint"], "n_orders": len(plan["orders"]),
                     "states": states, "run_id": results[0].get("run_id") if results else None}
    _save_state(path, state)
    return {"status": "submitted", "et_day": et_day, "n_orders": len(plan["orders"]), "states": states,
            "order_value": round(total, 2), "equity": equity}


def format_summary(res: dict) -> str:
    if res["status"] == "submitted":
        return (f"[paper 자동주문] {res['et_day']} 주문 {res['n_orders']}건 제출 (총 ${res['order_value']:,.0f} / 자산 "
                f"${res['equity']:,.0f}), 상태 {res['states']}")
    if res["status"] == "no_orders":
        return f"[paper 자동주문] {res['et_day']} 변경할 주문 없음"
    return f"[paper 자동주문] 건너뜀: {res['reason']}" + (f" {res['symbols']}" if res.get("symbols") else "")
