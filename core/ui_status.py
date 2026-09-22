"""상세 화면에서 공통으로 쓰는 데이터 신뢰 상태 헤더."""

from __future__ import annotations

import html
from datetime import date, datetime, time, timezone
from typing import Any, Callable, Mapping

import streamlit as st


_PAGE_META: dict[str, dict[str, str]] = {
    "strategy_studio": {"pit": "혼합", "version": "미버전"},
    "threads": {"pit": "미검증", "version": "해당 없음"},
    "watchlist": {"pit": "혼합", "version": "전략별 상이"},
    "guru": {"pit": "미검증", "version": "해당 없음"},
    "screening": {"pit": "미검증", "version": "미버전"},
    "valuation": {"pit": "미검증", "version": "해당 없음"},
    "market": {"pit": "혼합", "version": "미버전"},
    "portfolio": {"pit": "해당 없음", "version": "해당 없음"},
    "chart": {"pit": "해당 없음", "version": "해당 없음"},
    "settings": {"pit": "해당 없음", "version": "UI v2"},
    "champion": {"pit": "부분 검증", "version": "미버전"},
    "champion_optimization": {"pit": "부분 검증", "version": "미버전"},
    "news": {"pit": "미검증", "version": "해당 없음"},
}


def _to_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def classify_freshness(value: Any, *, now: datetime | None = None, max_age_hours: float = 48) -> str:
    timestamp = _to_utc(value)
    if timestamp is None:
        return "Unknown"
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_hours = (current - timestamp).total_seconds() / 3600
    return "Fresh" if -1 <= age_hours <= max_age_hours else "Stale"


def _safe_load(loader: Callable[[], Any] | None) -> Any:
    if loader is None:
        return None
    try:
        return loader()
    except Exception:
        return None


def _latest_local_snapshot(page_key: str) -> Any:
    """페이지별로 이미 저장된 로컬 결과의 최신 메타데이터만 읽는다.

    이 함수는 계산기/수집기를 호출하지 않는다. 각 페이지가 결과를 저장하는 기존
    DB/JSON 조회 함수만 사용하며, 결과가 없으면 ``None``을 반환해 헤더를 Unknown으로
    남긴다. 페이지를 렌더링하는 동안 네트워크 요청이나 가격 재계산이 발생하지 않도록
    여기서 직접 호출하는 함수 목록을 의도적으로 좁게 유지한다.
    """
    if page_key == "strategy_studio":
        from core.strategy_tuning import list_tuning_runs

        rows = list_tuning_runs()
        if not rows:
            return None
        row = rows[0]
        snapshot = dict(row)
        version = row.get("style_score_version")
        if version is not None:
            snapshot["strategy_version"] = f"튜닝 점수 v{version}"
        return snapshot

    if page_key == "threads":
        from core.threads_summary import list_summaries

        rows = list_summaries(limit=1)
        return rows[0] if rows else None

    if page_key == "watchlist":
        # WatchlistItem에는 평가 시각이 없으므로 등록 시각을 기준 시각으로
        # 표시하지 않는다. 실제 스캔 결과가 저장된 alerts_log만 사용한다.
        from core.watchlist import get_recent_alerts

        rows = get_recent_alerts(limit=1)
        return rows[0] if rows else None

    if page_key == "news":
        from core.news_digest import list_latest_digests

        rows = list_latest_digests(limit=1)
        return rows[0] if rows else None

    if page_key == "portfolio":
        # 손익/리스크 계산은 현재가 조회를 포함하므로 호출하지 않는다. 사용자가
        # 이미 저장한 상관관계 스냅샷이 있을 때만 그 계산 시각을 사용한다.
        from core.portfolio import list_portfolio_correlation_snapshots

        rows = list_portfolio_correlation_snapshots(limit=1)
        return rows[0] if rows else None

    if page_key == "guru":
        # 페이지 전체가 여러 거장을 보여주므로 기존 로컬 집계 조회 함수의
        # 거장별 마지막 filing 중 가장 최근 날짜를 사용한다.
        from core.guru_tracker import get_last_sync_info

        dates = [value for value in get_last_sync_info().values() if value]
        return {"as_of": max(dates), "pit": "미검증"} if dates else None

    return None


def _load_default_snapshot(page_key: str) -> Any:
    """기본 로더의 예외를 페이지 상태 전체에 전파하지 않는다."""
    try:
        return _latest_local_snapshot(page_key)
    except Exception:
        return None


def _snapshot_value(snapshot: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = snapshot.get(key)
        if value not in (None, ""):
            return value
    return None


def resolve_page_status(
    page_key: str,
    *,
    now: datetime | None = None,
    sources: Mapping[str, Callable[[], Any]] | None = None,
) -> dict[str, str]:
    """네트워크 호출 없이 저장된 스냅샷만 읽어 표시용 상태를 만든다."""
    meta = dict(_PAGE_META.get(page_key, {"pit": "Unknown", "version": "Unknown"}))
    loaders = dict(sources or {})
    if sources is None:
        if page_key in {"champion", "champion_optimization"}:
            from core import champion_strategy

            loaders[page_key] = champion_strategy.get_current_holdings
            meta["version"] = getattr(champion_strategy, "CHAMPION_STRATEGY_VERSION", "미버전")
        elif page_key == "market":
            from core.market_regime import get_latest_market_regime_snapshot

            loaders[page_key] = get_latest_market_regime_snapshot
        else:
            loaders[page_key] = lambda key=page_key: _load_default_snapshot(key)

    snapshot = _safe_load(loaders.get(page_key))
    as_of = None
    if isinstance(snapshot, Mapping):
        as_of = _snapshot_value(
            snapshot,
            "computed_at",
            "last_trading_date",
            "period_end",
            "detected_at",
            "created_at",
            "as_of",
        )
        pit = _snapshot_value(snapshot, "pit_status", "pit")
        if pit is not None:
            meta["pit"] = str(pit)
        version = _snapshot_value(snapshot, "strategy_version", "version")
        if version is not None:
            meta["version"] = str(version)

    timestamp = _to_utc(as_of)
    as_of_text = timestamp.strftime("%Y-%m-%d %H:%M UTC") if timestamp else "확인되지 않음"
    return {
        "as_of": as_of_text,
        "freshness": classify_freshness(as_of, now=now),
        "pit": meta["pit"],
        "version": meta["version"],
    }


def render_status_header(page_key: str) -> dict[str, str]:
    """기준 시각 / 신선도 / PIT / 전략 버전을 같은 순서와 어휘로 표시한다."""
    status = resolve_page_status(page_key)
    freshness_tone = status["freshness"].lower()
    pit_tone = "warning" if status["pit"] in {"미검증", "혼합", "부분 검증"} else "neutral"
    items = (
        ("기준 시각", status["as_of"], "neutral"),
        ("신선도", status["freshness"], freshness_tone),
        ("PIT", status["pit"], pit_tone),
        ("전략 버전", status["version"], "neutral"),
    )
    markup = '<div class="quant-trust-header">' + "".join(
        f'<span class="quant-trust-item {tone}"><small>{html.escape(label)}</small>'
        f'<strong>{html.escape(value)}</strong></span>'
        for label, value, tone in items
    ) + "</div>"
    st.markdown(markup, unsafe_allow_html=True)
    return status
