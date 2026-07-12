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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from core.db import get_session
from core.models import AlertLog, WatchlistItem
from core.strategy_engine import evaluate

MAX_WATCHLIST_SIZE = 50


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
