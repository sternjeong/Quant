from datetime import datetime, timezone

import core.ui_status as ui_status
from core.ui_status import classify_freshness, resolve_page_status


NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def test_freshness_contract():
    assert classify_freshness("2026-09-22T00:00:00+00:00", now=NOW) == "Fresh"
    assert classify_freshness("2026-09-18T00:00:00+00:00", now=NOW) == "Stale"
    assert classify_freshness(None, now=NOW) == "Unknown"


def test_market_status_uses_saved_snapshot_metadata():
    status = resolve_page_status(
        "market",
        now=NOW,
        sources={"market": lambda: {"computed_at": "2026-09-22T06:00:00+00:00", "strategy_version": "regime-v2"}},
    )
    assert status == {
        "as_of": "2026-09-22 06:00 UTC",
        "freshness": "Fresh",
        "pit": "혼합",
        "version": "regime-v2",
    }


def test_missing_snapshot_is_explicitly_unknown():
    status = resolve_page_status("champion", now=NOW, sources={"champion": lambda: None})
    assert status["as_of"] == "확인되지 않음"
    assert status["freshness"] == "Unknown"
    assert status["pit"] == "부분 검증"


def test_saved_metadata_aliases_override_header_fields():
    status = resolve_page_status(
        "news",
        now=NOW,
        sources={
            "news": lambda: {
                "period_end": "2026-09-22T08:30:00+00:00",
                "pit_status": "미검증",
                "version": "digest-v3",
            }
        },
    )
    assert status == {
        "as_of": "2026-09-22 08:30 UTC",
        "freshness": "Fresh",
        "pit": "미검증",
        "version": "digest-v3",
    }


def test_default_local_loader_uses_latest_strategy_run_metadata(monkeypatch):
    monkeypatch.setattr(
        ui_status,
        "_latest_local_snapshot",
        lambda page_key: {
            "created_at": "2026-09-22T09:00:00+00:00",
            "strategy_version": "튜닝 점수 v2",
        }
        if page_key == "strategy_studio"
        else None,
    )
    status = resolve_page_status("strategy_studio", now=NOW)
    assert status["as_of"] == "2026-09-22 09:00 UTC"
    assert status["freshness"] == "Fresh"
    assert status["version"] == "튜닝 점수 v2"


def test_default_local_loader_failure_is_fail_soft(monkeypatch):
    def broken(_page_key):
        raise RuntimeError("broken local store")

    monkeypatch.setattr(ui_status, "_latest_local_snapshot", broken)
    status = resolve_page_status("news", now=NOW)
    assert status["as_of"] == "확인되지 않음"
    assert status["freshness"] == "Unknown"
