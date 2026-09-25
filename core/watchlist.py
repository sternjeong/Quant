"""모듈 C: 관심 티커 리스트(최대 50개) + 매일 타점 모니터링 공용 로직.

app/pages/3_관심종목_모니터링.py (Streamlit UI) 와 scheduler/run_scheduler.py
(독립 스케줄러) 양쪽에서 동일한 함수를 재사용한다.

핵심 흐름:
    1. add_to_watchlist / update_watchlist_item / remove_from_watchlist 로
       관심 티커(최대 MAX_WATCHLIST_SIZE개)와 적용 전략을 관리한다.
    2. scan_watchlist() 가 각 (ticker, strategy) 조합에 대해
       core.strategy_engine.evaluate() 로 신규 진입 신호 여부를 계산하고,
       신호가 발생하면 alerts_log 에 기록 + notify_fn(title, message) 를 호출한다.
       (스케줄러는 notify_fn=core.notify.send_desktop_notification 을 넘겨서 쓰고,
        UI 페이지의 "지금 스캔 실행" 버튼도 동일한 함수를 그대로 재사용한다.)
    3. get_recent_alerts / mark_alert_read 등으로 알림 이력을 대시보드에 표시한다.
    4. send_triggered_summary_telegram() 이 스캔 결과 중 충족 종목을 텔레그램 요약 1건으로 보낸다
       (2026-09-25 추가 — 서버(VM)에는 화면이 없어 데스크톱 알림이 콘솔 출력으로만 대체되므로,
       폰으로 보는 사용자가 충족을 알 수 있게 스케줄러 잡이 이것을 부른다). 충족 0건이면 보내지 않고,
       같은 (종목, 전략, 기준일)은 작은 상태 파일로 한 번만 보낸다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

from core import telegram_notify
from core.db import get_session
from core.models import AlertLog, WatchlistItem
from core.strategy_engine import evaluate

MAX_WATCHLIST_SIZE = 50

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 텔레그램으로 이미 보낸 (종목, 전략, 기준일) 키. 재실행·재시작 시 같은 알림이 두 번 가지 않게 한다.
TELEGRAM_SENT_STATE_PATH = PROJECT_ROOT / "data" / "cache" / "watchlist_telegram_sent.json"
TELEGRAM_SUMMARY_MAX_ITEMS = 10
_SENT_KEY_RETENTION_DAYS = 30


@dataclass
class ScanResult:
    ticker: str
    strategy_id: Optional[int]
    strategy_name: Optional[str]
    triggered: bool  # 오늘 신규로 발생한 타점인지
    in_position: bool  # 조건 자체는 충족 중인지(레짐 유지 포함)
    as_of: Optional[str]  # 기준일(YYYY-MM-DD)
    message: str


def get_watchlist_count() -> int:
    """관심 티커(중복 제외) 개수를 반환한다."""
    with get_session() as session:
        return session.query(WatchlistItem.ticker).distinct().count()


def list_watchlist() -> list[dict]:
    """관심 티커 목록을 UI에 표시하기 좋은 dict 리스트로 반환한다 (최신 등록순)."""
    with get_session() as session:
        items = session.query(WatchlistItem).order_by(WatchlistItem.added_at.desc()).all()
        return [
            {
                "id": item.id,
                "ticker": item.ticker,
                "strategy_id": item.strategy_id,
                "strategy_name": item.strategy.name if item.strategy else None,
                "memo": item.memo or "",
                "added_at": item.added_at,
            }
            for item in items
        ]


def add_to_watchlist(ticker: str, strategy_id: Optional[int] = None, memo: Optional[str] = None) -> int:
    """관심 티커를 추가한다.

    이미 등록된 티커면 새로 추가하지 않고 전략/메모만 갱신한다(upsert).
    신규 티커 추가로 인해 총 개수가 MAX_WATCHLIST_SIZE 를 넘으면 ValueError.

    Returns:
        추가/갱신된 WatchlistItem 의 id.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("티커를 입력해주세요.")

    with get_session() as session:
        existing = session.query(WatchlistItem).filter(WatchlistItem.ticker == ticker).first()
        if existing is None:
            current_count = session.query(WatchlistItem.ticker).distinct().count()
            if current_count >= MAX_WATCHLIST_SIZE:
                raise ValueError(
                    f"관심 티커는 최대 {MAX_WATCHLIST_SIZE}개까지 등록할 수 있습니다 (현재 {current_count}개)."
                )
            item = WatchlistItem(ticker=ticker, strategy_id=strategy_id, memo=memo)
            session.add(item)
        else:
            existing.strategy_id = strategy_id
            existing.memo = memo
            item = existing
        session.flush()
        return item.id


def update_watchlist_item(item_id: int, strategy_id: Optional[int] = None, memo: Optional[str] = None) -> None:
    """기존 관심 티커의 적용 전략/메모를 갱신한다."""
    with get_session() as session:
        item = session.get(WatchlistItem, item_id)
        if item is None:
            raise ValueError(f"관심 티커(id={item_id})를 찾을 수 없습니다.")
        item.strategy_id = strategy_id
        item.memo = memo


def remove_from_watchlist(item_id: int) -> None:
    """관심 티커를 제거한다."""
    with get_session() as session:
        item = session.get(WatchlistItem, item_id)
        if item is not None:
            session.delete(item)


def scan_watchlist(notify_fn: Optional[Callable[[str, str], None]] = None) -> list[ScanResult]:
    """관심 종목 전체를 스캔해서 저장된 전략 조건 충족 여부를 확인한다.

    전략이 연결된 종목만 실제로 평가하며, 신규 진입 신호(triggered)가 발생하면
    alerts_log 에 기록하고 notify_fn(title, message) 이 주어졌으면 호출한다.
    전략이 연결되지 않은 관심 종목은 결과 목록에는 포함하되(스캔 건너뜀 안내) 알림은 발생시키지 않는다.
    """
    results: list[ScanResult] = []

    with get_session() as session:
        items = session.query(WatchlistItem).all()

        for item in items:
            if item.strategy is None:
                results.append(
                    ScanResult(
                        ticker=item.ticker,
                        strategy_id=None,
                        strategy_name=None,
                        triggered=False,
                        in_position=False,
                        as_of=None,
                        message=f"{item.ticker}: 연결된 전략이 없어 스캔을 건너뜁니다.",
                    )
                )
                continue

            strategy_id = item.strategy_id
            strategy_name = item.strategy.name
            indicator_config = item.strategy.indicator_config

            try:
                eval_result = evaluate(item.ticker, indicator_config)
            except Exception as e:
                results.append(
                    ScanResult(
                        ticker=item.ticker,
                        strategy_id=strategy_id,
                        strategy_name=strategy_name,
                        triggered=False,
                        in_position=False,
                        as_of=None,
                        message=f"{item.ticker}: 스캔 실패 ({e})",
                    )
                )
                continue

            results.append(
                ScanResult(
                    ticker=item.ticker,
                    strategy_id=strategy_id,
                    strategy_name=strategy_name,
                    triggered=eval_result["triggered"],
                    in_position=eval_result["in_position"],
                    as_of=eval_result["as_of"],
                    message=eval_result["message"],
                )
            )

            if eval_result["triggered"]:
                session.add(
                    AlertLog(
                        ticker=item.ticker,
                        strategy_id=strategy_id,
                        message=eval_result["message"],
                    )
                )
                if notify_fn is not None:
                    notify_fn(
                        f"타점 발생: {item.ticker}",
                        f"{strategy_name} 조건 충족 (기준일 {eval_result['as_of']})",
                    )

    return results


def _sent_key(result: ScanResult) -> str:
    day = result.as_of or date.today().isoformat()
    return f"{result.ticker}|{result.strategy_id}|{day}"


def _load_sent_keys(path: Path) -> dict[str, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        sent = data.get("sent", {})
        return dict(sent) if isinstance(sent, dict) else {}
    except Exception:
        return {}


def _save_sent_keys(path: Path, sent: dict[str, str]) -> None:
    cutoff = (date.today() - timedelta(days=_SENT_KEY_RETENTION_DAYS)).isoformat()
    kept = {k: v for k, v in sent.items() if str(v) >= cutoff}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"sent": kept}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def format_triggered_summary(triggered: list[ScanResult], max_items: int = TELEGRAM_SUMMARY_MAX_ITEMS) -> str:
    """충족 종목 목록을 텔레그램 한 건 분량의 요약 문자열로 만든다(상위 max_items개 + '외 k건')."""
    lines = [f"🔔 관심종목 타점 발생 {len(triggered)}건"]
    for r in triggered[:max_items]:
        detail = (r.message or "").strip().replace("\n", " ")
        if len(detail) > 120:
            detail = detail[:117] + "..."
        lines.append(f"- {r.ticker} · {r.strategy_name or '전략?'} (기준일 {r.as_of or '-'})")
        if detail:
            lines.append(f"  {detail}")
    extra = len(triggered) - max_items
    if extra > 0:
        lines.append(f"외 {extra}건")
    lines.append("신호일 뿐 주문이 아닙니다. 자세한 내용은 화면 '운용 알림'에서 확인하세요.")
    return "\n".join(lines)


def send_triggered_summary_telegram(
    results: list[ScanResult],
    state_path: Optional[Path] = None,
    max_items: int = TELEGRAM_SUMMARY_MAX_ITEMS,
) -> dict:
    """스캔 결과 중 신규 충족(triggered) 종목을 텔레그램 요약 1건으로 보낸다.

    - 충족 0건(또는 전부 이미 보낸 것)이면 보내지 않는다 → status "nothing".
    - 텔레그램 설정이 없으면 보내지 않는다 → status "not_configured" (예외 없음).
    - 전송 실패 → status "failed" (예외 없음, 상태 파일도 갱신하지 않아 다음 실행에서 재시도).
    - 성공 → status "sent", 보낸 키를 상태 파일에 기록해 같은 (종목, 전략, 기준일)을 다시 보내지 않는다.
    """
    path = Path(state_path) if state_path is not None else TELEGRAM_SENT_STATE_PATH
    sent = _load_sent_keys(path)

    pending: list[ScanResult] = []
    seen: set[str] = set()
    for r in results or []:
        if not r.triggered:
            continue
        key = _sent_key(r)
        if key in sent or key in seen:
            continue
        seen.add(key)
        pending.append(r)

    if not pending:
        return {"status": "nothing", "count": 0}
    if not telegram_notify.is_configured():
        return {"status": "not_configured", "count": len(pending)}

    text = format_triggered_summary(pending, max_items=max_items)
    try:
        ok = bool(telegram_notify.send_message(text))
    except Exception:
        ok = False
    if not ok:
        return {"status": "failed", "count": len(pending), "text": text}

    for r in pending:
        sent[_sent_key(r)] = r.as_of or date.today().isoformat()
    try:
        _save_sent_keys(path, sent)
    except Exception as exc:  # 상태 저장 실패가 잡을 죽이면 안 된다(최악의 경우 다음 실행에서 한 번 더 감)
        print(f"[watchlist] 텔레그램 전송 상태 저장 실패(무시): {exc}")
    return {"status": "sent", "count": len(pending), "text": text}


def get_recent_alerts(limit: int = 100, unread_only: bool = False) -> list[dict]:
    """최근 타점 알림 이력을 최신순으로 반환한다."""
    with get_session() as session:
        query = session.query(AlertLog).order_by(AlertLog.detected_at.desc())
        if unread_only:
            query = query.filter(AlertLog.is_read.is_(False))
        rows = query.limit(limit).all()
        return [
            {
                "id": a.id,
                "ticker": a.ticker,
                "strategy_id": a.strategy_id,
                "strategy_name": a.strategy.name if a.strategy else None,
                "detected_at": a.detected_at,
                "message": a.message,
                "is_read": a.is_read,
            }
            for a in rows
        ]


def get_unread_alert_count() -> int:
    with get_session() as session:
        return session.query(AlertLog).filter(AlertLog.is_read.is_(False)).count()


def mark_alert_read(alert_id: int) -> None:
    with get_session() as session:
        alert = session.get(AlertLog, alert_id)
        if alert is not None:
            alert.is_read = True


def mark_all_alerts_read() -> None:
    with get_session() as session:
        session.query(AlertLog).filter(AlertLog.is_read.is_(False)).update({AlertLog.is_read: True})
