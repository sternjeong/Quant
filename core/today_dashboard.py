"""Read-only view model for the Streamlit "Today" command center.

Opening the home page must not trigger a market scan or change a paper-order
state. This module combines only snapshots and lightweight operational records
already maintained by other engines.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping


def _safe(call: Callable[[], Any], default: Any) -> Any:
    try:
        return call()
    except Exception:
        return default


def _backup_status(backup: Mapping[str, Any]) -> str:
    return {"ok": "fresh", "warn": "stale", "bad": "blocked"}.get(backup.get("level", "none"), "unknown")


def build_today_dashboard(
    sources: Mapping[str, Callable[[], Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a small home-dashboard view model, with optional test sources."""
    if sources is None:
        from core.backup_status import describe_backup, load_backup_status
        from core.champion_strategy import get_current_holdings
        from core.job_health import compute_job_health
        from core.market_regime import get_latest_market_regime_snapshot
        from core.watchlist import get_unread_alert_count, get_watchlist_count

        sources = {
            "holdings": get_current_holdings,
            "market": get_latest_market_regime_snapshot,
            "jobs": compute_job_health,
            "backup": lambda: describe_backup(load_backup_status()),
            "unread_alerts": get_unread_alert_count,
            "watchlist_count": get_watchlist_count,
        }

    holdings = _safe(sources["holdings"], None)
    market = _safe(sources["market"], None)
    jobs = _safe(sources["jobs"], None)
    backup = _safe(sources["backup"], {"level": "none", "lines": []})
    unread_alerts = _safe(sources["unread_alerts"], 0)
    watchlist_count = _safe(sources["watchlist_count"], 0)

    actions: list[dict[str, str]] = []
    if holdings is None:
        actions.append({"level": "info", "title": "챔피언 신호 스냅샷 없음", "detail": "저장된 추천 상태가 없어 오늘의 목표 배분을 표시할 수 없습니다.", "destination": "pages/11_챔피언_전략.py"})
    if market is None:
        actions.append({"level": "info", "title": "시장 국면 스냅샷 없음", "detail": "저장된 시장 국면이 없어 국면 기반 참고 정보를 표시할 수 없습니다.", "destination": "pages/7_시장_진단.py"})
    elif market.get("regime") == "unknown":
        actions.append({"level": "warning", "title": "시장 국면 판단 보류", "detail": "시장폭 또는 필수 데이터가 부족합니다. 약세 신호와 같은 뜻이 아닙니다.", "destination": "pages/7_시장_진단.py"})
    if jobs and jobs.get("counts", {}).get("problem", 0):
        actions.append({"level": "warning", "title": f"운영 작업 문제 {jobs['counts']['problem']}건", "detail": "데이터·알림·브리핑의 최신 상태를 확인하세요.", "destination": "pages/10_환경설정.py"})
    status = _backup_status(backup)
    if status in {"stale", "blocked"}:
        actions.append({"level": "warning", "title": "백업 상태 확인 필요", "detail": (backup.get("lines") or ["백업 상태를 읽지 못했습니다."])[0], "destination": "pages/10_환경설정.py"})
    if unread_alerts:
        actions.append({"level": "info", "title": f"읽지 않은 관심종목 알림 {unread_alerts}건", "detail": "신호의 기준일과 적용 전략을 확인하세요.", "destination": "pages/3_관심종목_모니터링.py"})
    if not actions:
        actions.append({"level": "ok", "title": "현재 확인할 새 조치 없음", "detail": "저장된 상태에서 차단·경고·읽지 않은 알림을 찾지 못했습니다.", "destination": "pages/11_챔피언_전략.py"})

    return {
        "generated_at": now or datetime.now(timezone.utc),
        "holdings": holdings,
        "market": market,
        "jobs": jobs,
        "backup": backup,
        "backup_status": status,
        "unread_alerts": int(unread_alerts or 0),
        "watchlist_count": int(watchlist_count or 0),
        "actions": actions,
    }
