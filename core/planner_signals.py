"""할 일 화면용 주식 시그널 스냅샷 — '무엇을 팔고/보고/점검할지'를 엔진 결과에서 뽑아 파일 하나로 (2026-11-15).

관제 허브 '할 일'(core/planner.py)이 읽는 data/planner_signals.json 을 만든다. 새 신호를 계산하지 않고 이미 있는
결과만 모은다:
  - 보유 재선정 점검: core.portfolio.get_holding_review_actions() — '포트폴리오'에 입력한 보유 × 최신 챔피언 추천
    (예: 'XLE 6주 매도하기 — 11/02 코어 재선정에서 빠짐')
  - 관심종목 타점: AlertLog(장마감 후 관심종목 스캔이 남긴 신규 진입 신호), 최근 ALERT_DAYS 일
  - 다음 코어 리밸런싱: core.champion_recommendation.next_checkpoints()
pandas·백테스트 캐시를 읽어 10초 넘게 걸리므로 허브 요청 안에서 부르지 않는다 — planner.refresh_signals() 가
`nice -n 19 python -m core.planner_signals` 로 따로 띄운다(허브 메모리에 pandas 를 올리지 않음).
주문은 하지 않는다 — 문구만 만든다.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

KST = timezone(timedelta(hours=9))
SIGNALS_PATH = Path(os.environ.get("QUANT_PLANNER_SIGNALS_FILE", PROJECT_ROOT / "data" / "planner_signals.json"))
ALERT_DAYS = 5
APP_URL = "https://app.hessejeong.duckdns.org/"

ACTION_TITLES = {"매도 확인": "매도하기", "보유 재검토": "보유 비중 재검토", "재추천 필요": "판단할 추천이 없음 — 챔피언 전략 다시 계산"}


def review_items(actions: list[dict]) -> list[dict]:
    out = []
    for a in actions:
        verb = ACTION_TITLES.get(a.get("action"), a.get("action", "점검"))
        qty = a.get("quantity")
        title = (f"{a['ticker']} {qty:g}주 {verb}" if a.get("action") != "재추천 필요"
                 else f"{a['ticker']} {qty:g}주 · {verb}")
        out.append({"id": f"sig:review:{a['ticker']}:{a.get('holding_id')}:{a.get('due_date')}", "title": title,
                    "due": a.get("due_date", ""), "project": f"{a['ticker']} · {a.get('strategy_role', '')}",
                    "note": a.get("detail", ""), "link": APP_URL, "kind": "sell" if a.get("action") == "매도 확인" else "review"})
    return out


def alert_items(rows: list[dict], now: datetime) -> list[dict]:
    out = []
    for r in rows:
        when = r["detected_at"]
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        day = when.astimezone(KST).date()
        if (now.astimezone(KST).date() - day).days > ALERT_DAYS:
            continue
        strategy = f" ({r['strategy']})" if r.get("strategy") else ""
        out.append({"id": f"sig:alert:{r['id']}", "title": f"{r['ticker']} 타점 포착{strategy} — 진입 검토",
                    "due": day.isoformat(), "project": r["ticker"], "note": r.get("message") or "", "link": APP_URL,
                    "kind": "signal"})
    return out


def rebalance_items(checkpoints: dict) -> list[dict]:
    nxt = checkpoints.get("core_next")
    if not nxt:
        return []
    return [{"id": f"sig:rebalance:{nxt}", "title": "코어 리밸런싱 점검 — 챔피언 전략 다시 계산 후 보유와 비교",
             "due": nxt, "project": "챔피언 코어", "note": "매달 첫 거래일에 코어 4종목을 다시 고릅니다.",
             "link": APP_URL, "kind": "rebalance"}]


def build(now: datetime | None = None) -> dict:
    now = now or datetime.now(KST)
    items: list[dict] = []
    errors: list[str] = []
    try:
        from core import portfolio

        items += review_items(portfolio.get_holding_review_actions(now.astimezone(KST).date()))
    except Exception as exc:  # noqa: BLE001 - 한 원천이 실패해도 나머지는 보여 준다
        errors.append(f"보유 점검: {exc}"[:200])
    try:
        from core.db import get_session
        from core.models import AlertLog

        since = (now - timedelta(days=ALERT_DAYS + 1)).astimezone(timezone.utc).replace(tzinfo=None)
        with get_session() as s:
            rows = [{"id": r.id, "ticker": r.ticker, "detected_at": r.detected_at, "message": r.message,
                     "strategy": getattr(r.strategy, "name", "") if r.strategy_id else ""}
                    for r in s.query(AlertLog).filter(AlertLog.detected_at >= since).order_by(AlertLog.id.desc()).limit(30)]
        items += alert_items(rows, now)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"관심종목 타점: {exc}"[:200])
    try:
        from core import champion_recommendation as cr

        items += rebalance_items(cr.next_checkpoints(now.astimezone(KST).date()))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"리밸런싱 일정: {exc}"[:200])
    return {"generated_at": now.isoformat(timespec="seconds"), "items": items, "errors": errors}


def write(data: dict, path: Path | None = None) -> None:
    path = path or SIGNALS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


if __name__ == "__main__":
    write(build())
