from datetime import datetime, timezone

from core.today_dashboard import build_today_dashboard


def _sources(**overrides):
    values = {
        "holdings": {"as_of": "2026-09-21", "core_top4": ["XLK"], "satellite_selected": ["NVDA"]},
        "market": {"regime": "강세장", "total_score": 50, "computed_at": datetime(2026, 9, 21)},
        "jobs": {"counts": {"problem": 0}},
        "backup": {"level": "ok", "lines": ["정상"]},
        "unread_alerts": 0,
        "watchlist_count": 3,
    }
    values.update(overrides)
    return {key: (lambda value=value: value) for key, value in values.items()}


def test_today_dashboard_is_read_only_snapshot_summary():
    dashboard = build_today_dashboard(_sources(), now=datetime(2026, 9, 22, tzinfo=timezone.utc))

    assert dashboard["watchlist_count"] == 3
    assert dashboard["backup_status"] == "fresh"
    assert dashboard["actions"][0]["level"] == "ok"


def test_today_dashboard_surfaces_unknown_and_operations():
    dashboard = build_today_dashboard(_sources(
        market={"regime": "unknown"},
        jobs={"counts": {"problem": 2}},
        backup={"level": "bad", "lines": ["마지막 백업 실패"]},
        unread_alerts=4,
    ))

    titles = [action["title"] for action in dashboard["actions"]]
    assert "시장 국면 판단 보류" in titles
    assert "운영 작업 문제 2건" in titles
    assert "백업 상태 확인 필요" in titles
    assert "읽지 않은 관심종목 알림 4건" in titles


def test_today_dashboard_handles_unavailable_sources():
    def broken():
        raise RuntimeError("offline")

    sources = _sources()
    sources["holdings"] = broken
    sources["market"] = broken
    dashboard = build_today_dashboard(sources)

    assert dashboard["holdings"] is None
    assert dashboard["market"] is None
    assert len(dashboard["actions"]) >= 2
