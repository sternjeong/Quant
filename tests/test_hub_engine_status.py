"""hub/engine_status.py — 엔진 카드를 눌렀을 때 보이는 잡 목록과 켜고 끄기."""

from __future__ import annotations

import pytest

from core import process_registry
from hub import engine_status


@pytest.fixture(autouse=True)
def isolated_toggles(monkeypatch, tmp_path):
    """진짜 토글 상태 파일을 건드리지 않는다(운영 중인 VM의 잡을 테스트가 꺼버리면 안 된다)."""
    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", tmp_path / "process_toggles.json")


# ---- cron 사람말로 옮기기 ----------------------------------------------------------------------

@pytest.mark.parametrize("cron, expected", [
    ({"hour": 0, "minute": 10, "timezone": "Asia/Seoul"}, "매일 00:10 KST"),
    ({"hour": 7, "minute": 30, "timezone": "Asia/Seoul"}, "매일 07:30 KST"),
    ({"day_of_week": "mon-fri", "hour": 16, "minute": 30, "timezone": "America/New_York"}, "평일 16:30 ET"),
    ({"day_of_week": "sun", "hour": 20, "minute": 0, "timezone": "America/New_York"}, "매주 일 20:00 ET"),
])
def test_cron_is_described_with_its_timezone(cron, expected):
    """KST와 ET가 섞여 있어서 시간대를 안 쓰면 오해한다."""
    assert engine_status.describe_cron(cron) == expected


# ---- 목록 수집 --------------------------------------------------------------------------------

def test_every_registered_process_appears_with_a_schedule(monkeypatch):
    monkeypatch.setattr(engine_status, "_health_by_job_id", lambda: {})
    rows = engine_status.collect_processes()

    assert len(rows) == len(process_registry.PROCESS_REGISTRY)
    assert all(row["schedule"] != "예약 없음" for row in rows), "스케줄 표에 없는 잡이 있다"
    assert {row["key"] for row in rows} == set(process_registry.PROCESS_REGISTRY)


def test_disabled_jobs_show_as_off_rather_than_missing(monkeypatch):
    process_registry.set_enabled("daily_briefing", False, "test")
    monkeypatch.setattr(engine_status, "_health_by_job_id",
                        lambda: {"daily_briefing": {"state": "overdue", "last_recorded_at": None}})

    row = next(r for r in engine_status.collect_processes() if r["key"] == "daily_briefing")

    assert row["enabled"] is False
    assert row["state"] == "disabled"  # 꺼둔 잡을 "기록 없음"이라고 하면 고장으로 오해한다


def test_health_state_is_carried_through(monkeypatch):
    monkeypatch.setattr(engine_status, "_health_by_job_id",
                        lambda: {"daily_briefing": {"state": "error", "last_recorded_at": "2026-09-25 00:25"}})
    row = next(r for r in engine_status.collect_processes() if r["key"] == "daily_briefing")
    assert row["state"] == "error" and row["last_run"] == "2026-09-25 00:25"


def test_collection_survives_an_unreadable_job_history(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(engine_status, "_health_by_job_id", _boom)
    with pytest.raises(RuntimeError):
        engine_status.collect_processes()  # 헬퍼 자체가 던지면 그대로 드러나는 게 맞다


def test_job_health_failure_inside_the_helper_is_swallowed(monkeypatch):
    """compute_job_health가 죽어도 페이지는 떠야 한다 — 상태만 '확인 불가'가 된다."""
    import core.job_health as job_health

    monkeypatch.setattr(job_health, "compute_job_health", lambda: (_ for _ in ()).throw(RuntimeError("db")))
    assert engine_status._health_by_job_id() == {}

    rows = engine_status.collect_processes()
    assert rows and all(row["state"] in (None, "disabled") for row in rows)


def test_summary_counts(monkeypatch):
    monkeypatch.setattr(engine_status, "_health_by_job_id",
                        lambda: {"daily_briefing": {"state": "error", "last_recorded_at": None}})
    process_registry.set_enabled("market_snapshot", False, "test")
    counts = engine_status.summarize(engine_status.collect_processes())

    assert counts["total"] == len(process_registry.PROCESS_REGISTRY)
    assert counts["disabled"] >= 1 and counts["enabled"] == counts["total"] - counts["disabled"]
    assert counts["problem"] == 1


# ---- 켜고 끄기 --------------------------------------------------------------------------------

def test_toggle_turns_a_normal_job_off_and_on():
    applied, message = engine_status.apply_toggle("daily_briefing", False)
    assert applied and "꺼짐" in message
    assert process_registry.is_enabled("daily_briefing") is False

    applied, message = engine_status.apply_toggle("daily_briefing", True)
    assert applied and "켜짐" in message
    assert process_registry.is_enabled("daily_briefing") is True


def test_an_order_placing_job_needs_confirmation_to_turn_on():
    """웹 클릭 한 번으로 주문을 내는 잡이 켜지면 안 된다 — 텔레그램과 같은 규칙."""
    key = "paper_auto_trade"
    assert process_registry.PROCESS_REGISTRY[key]["places_orders"] is True

    applied, message = engine_status.apply_toggle(key, True)
    assert applied is False and "확인" in message
    assert process_registry.is_enabled(key) is False  # 켜지지 않았다

    applied, _ = engine_status.apply_toggle(key, True, confirmed=True)
    assert applied and process_registry.is_enabled(key) is True


def test_turning_an_order_placing_job_off_needs_no_confirmation():
    key = "paper_auto_trade"
    engine_status.apply_toggle(key, True, confirmed=True)
    applied, _ = engine_status.apply_toggle(key, False)
    assert applied and process_registry.is_enabled(key) is False


def test_unknown_key_is_refused():
    applied, message = engine_status.apply_toggle("nope_not_a_job", True)
    assert applied is False and "알 수 없는" in message


# ---- 렌더링 -----------------------------------------------------------------------------------

def test_scheduler_page_lists_jobs_grouped_with_toggle_buttons(monkeypatch):
    monkeypatch.setattr(engine_status, "_health_by_job_id", lambda: {})
    body = engine_status.render_engine_body("scheduler")

    for label in ("알림", "연구·기록", "유지보수"):
        assert label in body
    assert body.count('action="/processes/toggle"') >= 25  # 잡마다 버튼
    assert "/processes" in body  # 텔레그램으로도 된다는 안내


def test_order_placing_job_renders_a_confirm_step_not_a_direct_toggle(monkeypatch):
    monkeypatch.setattr(engine_status, "_health_by_job_id", lambda: {})
    rows = [r for r in engine_status.collect_processes() if r["key"] == "paper_auto_trade"]
    assert rows and rows[0]["enabled"] is False

    button = engine_status._toggle_button(rows[0])
    assert 'action="/processes/confirm"' in button and "💸" not in button
    assert "/processes/toggle" not in button


def test_confirm_page_warns_and_offers_both_choices():
    body = engine_status.render_confirm_body("paper_auto_trade")
    assert "주문을 냅니다" in body
    assert 'name="confirm" value="1"' in body  # 확인해야만 켜진다
    assert "취소" in body


def test_confirm_page_handles_an_unknown_key():
    assert "알 수 없는" in engine_status.render_confirm_body("nope")


def test_non_scheduler_engines_explain_themselves_instead_of_dead_ending(monkeypatch):
    monkeypatch.setattr(engine_status, "_recent_timer_lines", lambda slot_id: "")
    for slot_id in ("codex-telegram", "vm-health", "experiment-supervisor"):
        body = engine_status.render_engine_body(slot_id)
        assert "별도 웹 UI 없이" not in body, slot_id  # 예전 막다른 문장
        assert "/status/scheduler" in body, slot_id  # 잡 목록으로 갈 길을 알려준다
        assert len(body) > 150, slot_id


def test_unknown_engine_still_renders_something_useful():
    body = engine_status.render_engine_body("something-new")
    assert "/status/scheduler" in body


# ---- 실제 라우팅 (서버를 띄워서 요청한다 — 배선 실수는 여기서만 잡힌다) ---------------------------

import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from hub import server as hub_server


@pytest.fixture
def live_hub():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), hub_server.HubRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _post(base, path, data, headers=None, follow=False):
    request = urllib.request.Request(base + path, data=data.encode(), method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              **(headers or {})})
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    try:
        return opener.open(request, timeout=10)
    except urllib.error.HTTPError as error:
        return error


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def test_toggle_post_switches_the_job_and_redirects_back(live_hub):
    assert process_registry.is_enabled("daily_briefing") is True

    response = _post(live_hub, "/processes/toggle", "key=daily_briefing&enabled=0")

    assert response.status == 303 and response.headers["Location"] == "/status/scheduler"
    assert process_registry.is_enabled("daily_briefing") is False


def test_cross_site_post_is_refused(live_hub):
    response = _post(live_hub, "/processes/toggle", "key=daily_briefing&enabled=0",
                     headers={"Sec-Fetch-Site": "cross-site"})

    assert response.status == 403
    assert process_registry.is_enabled("daily_briefing") is True  # 바뀌지 않았다


def test_order_placing_job_post_returns_the_confirm_page_not_a_toggle(live_hub):
    key = "paper_auto_trade"
    response = _post(live_hub, "/processes/toggle", f"key={key}&enabled=1")
    body = response.read().decode()

    assert response.status == 200
    assert "주문을 냅니다" in body
    assert process_registry.is_enabled(key) is False  # 아직 안 켜졌다

    confirmed = _post(live_hub, "/processes/toggle", f"key={key}&enabled=1&confirm=1")
    assert confirmed.status == 303
    assert process_registry.is_enabled(key) is True


def test_confirm_route_shows_the_warning_page(live_hub):
    response = _post(live_hub, "/processes/confirm", "key=paper_auto_trade&enabled=1")
    assert response.status == 200 and "주문을 냅니다" in response.read().decode()


def test_scheduler_status_page_is_served_with_the_job_list(live_hub):
    body = urllib.request.urlopen(live_hub + "/status/scheduler", timeout=10).read().decode()
    assert "자동 잡" in body and 'action="/processes/toggle"' in body


def test_unknown_post_path_is_404(live_hub):
    assert _post(live_hub, "/processes/nope", "key=x").status == 404
