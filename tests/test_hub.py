"""hub/ 모듈 검증. systemctl 호출은 실제 systemd에 의존하지 않도록 subprocess.run을 목킹한다."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from hub import server
from hub.apps_registry import AppSlot, SLOTS
from hub.status import get_unit_status


def _fake_run(stdout: str):
    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")
    return _run


def test_slots_have_unique_non_empty_ids():
    ids = [slot.id for slot in SLOTS]
    assert len(ids) == len(set(ids))
    assert all(slot.title and slot.description and slot.unit for slot in SLOTS)


def test_slots_kind_specific_fields():
    for slot in SLOTS:
        if slot.kind == "web":
            assert slot.port is not None
        if slot.kind == "link":
            assert slot.url and slot.url.startswith("https://")
        if slot.kind == "report":
            assert slot.report_glob is not None


def test_get_unit_status_parses_systemctl_show_output():
    output = (
        "ActiveState=active\nSubState=running\n"
        "ActiveEnterTimestamp=Sun 2026-09-20 06:00:00 UTC\n"
    )
    with patch("subprocess.run", side_effect=_fake_run(output)):
        status = get_unit_status("quant-streamlit.service")
    assert status.active_state == "active"
    assert status.sub_state == "running"
    assert status.is_active is True
    assert status.is_known is True


def test_get_unit_status_handles_subprocess_failure():
    with patch("subprocess.run", side_effect=OSError("systemctl missing")):
        status = get_unit_status("does-not-exist.service")
    assert status.active_state == "unknown"
    assert status.is_active is False
    assert status.is_known is False


def _mock_active_status():
    output = "ActiveState=active\nSubState=running\nActiveEnterTimestamp=n/a\n"
    return patch("subprocess.run", side_effect=_fake_run(output))


def test_render_dashboard_lists_every_slot_title():
    with _mock_active_status():
        html_out = server.render_dashboard("203.0.113.10")
    for slot in SLOTS:
        assert slot.title in html_out


def test_slot_href_web_points_to_own_port():
    # 지금은 SLOTS 안에 "web" 종류가 없다(전부 HTTPS 하위 도메인 "link"로 전환) — 그래도 hub/server.py가
    # 이 종류를 계속 지원하는지는 합성 슬롯으로 독립 검증한다(나중에 도메인 없는 슬롯이 다시 생길 수 있음).
    web_slot = AppSlot(
        id="synthetic-web", title="t", description="d", unit="u.service", kind="web", port=9999,
    )
    href = server._slot_href(web_slot, "203.0.113.10")
    assert href == f"http://203.0.113.10:{web_slot.port}/"


def test_slot_href_link_uses_the_slots_own_https_url():
    link_slot = next(slot for slot in SLOTS if slot.kind == "link")
    assert server._slot_href(link_slot, "203.0.113.10") == link_slot.url


def test_code_server_is_an_https_link_slot():
    slot = next(slot for slot in SLOTS if slot.id == "code-server")
    assert slot.kind == "link"
    assert slot.url.startswith("https://")  # 평문 HTTP 포트로 직접 링크하면 안 된다


def test_streamlit_is_an_https_link_slot():
    slot = next(slot for slot in SLOTS if slot.id == "streamlit")
    assert slot.kind == "link"
    assert slot.url.startswith("https://")


def test_link_slots_each_point_to_their_own_subdomain():
    # 컨트롤 타워 구조: 기본 도메인=허브, code.<도메인>=code-server, app.<도메인>=Streamlit.
    # 게이트웨이 뒤에서 서로 다른 앱으로 갈라지려면 두 link 슬롯의 호스트명이 달라야 한다.
    link_urls = {slot.id: slot.url for slot in SLOTS if slot.kind == "link"}
    assert len(set(link_urls.values())) == len(link_urls)  # 전부 서로 다른 주소


def test_link_card_opens_in_a_new_tab():
    with _mock_active_status():
        page = server.render_dashboard("203.0.113.10")
    link_slot = next(slot for slot in SLOTS if slot.kind == "link")
    card_start = page.index(f'href="{link_slot.url}"')
    assert 'target="_blank"' in page[card_start:card_start + 80]


# 2026-09-25: 2주 실험 슈퍼바이저 삭제로 등록된 report 슬롯이 없어졌다. 허브의 리포트 보기 기능(/reports)은 그대로
# 남아 있으므로 그 기능은 테스트 전용 슬롯으로 계속 검증한다.
REPORT_SLOT = AppSlot(
    id="test-report", title="테스트 리포트", description="테스트 전용 report 슬롯", unit="test-report.service",
    kind="report", report_glob=".experiment-control/reports/*.html",
)


def test_report_slots_registered_and_supervisor_stays_removed():
    ids = [slot.id for slot in SLOTS if slot.kind == "report"]
    assert ids == ["report-daily-briefing", "report-champion-weekly", "report-news-digest"]
    assert all(slot.id != "experiment-supervisor" for slot in SLOTS)


def test_slot_href_report_points_to_reports_route():
    report_slot = REPORT_SLOT
    assert server._slot_href(report_slot, "host") == f"/reports/{report_slot.id}"


def test_slot_href_engine_points_to_status_route():
    engine_slot = next(slot for slot in SLOTS if slot.kind == "engine")
    assert server._slot_href(engine_slot, "host") == f"/status/{engine_slot.id}"


def test_find_slot_by_id_and_kind():
    link_slot = next(slot for slot in SLOTS if slot.kind == "link")
    assert server.find_slot(link_slot.id) is link_slot
    assert server.find_slot(link_slot.id, kind="report") is None
    assert server.find_slot("no-such-id") is None


def test_latest_report_path_picks_newest_file(tmp_path, monkeypatch):
    report_slot = REPORT_SLOT
    report_dir = tmp_path / Path(report_slot.report_glob).parent
    report_dir.mkdir(parents=True)
    older = report_dir / "quant_experiment_20260101_000000.html"
    newer = report_dir / "quant_experiment_20260102_000000.html"
    older.write_text("<html>old</html>")
    newer.write_text("<html>new</html>")
    import os
    import time
    os.utime(older, (time.time() - 100, time.time() - 100))

    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)
    assert server.latest_report_path(report_slot) == newer


def test_latest_report_path_returns_none_when_no_reports(tmp_path, monkeypatch):
    report_slot = REPORT_SLOT
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)
    assert server.latest_report_path(report_slot) is None


def test_render_status_page_shows_unit_name():
    engine_slot = next(slot for slot in SLOTS if slot.kind == "engine")
    with _mock_active_status():
        page = server.render_status_page(engine_slot)
    assert engine_slot.unit in page
    assert engine_slot.title in page


def test_alpaca_page_renders_empty_and_with_results(tmp_path):
    import json

    from hub import alpaca_status

    empty = alpaca_status.render_body(alpaca_status.collect(tmp_path))
    assert "아직 실행 전" in empty and "비교 구간 없음" in empty and "P3 자동 주문" in empty

    (tmp_path / "data" / "verification").mkdir(parents=True)
    (tmp_path / "data" / "verification" / "alpaca_20261001_0040.json").write_text(json.dumps(
        {"overall": "UNEXPECTED", "generated_at": "2026-10-01T00:40", "checks": {
            "market_meta_news": {"verdict": "UNEXPECTED", "summary": "가정과 다름", "failing": ["news: 0건 <b>"]}}}))
    (tmp_path / "data" / "cache").mkdir(parents=True)
    (tmp_path / "data" / "cache" / "paper_tracking.json").write_text(json.dumps(
        {"n_intervals": 3, "paper_cum_return_pct": 1.0, "champion_cum_return_pct": 0.5, "cum_gap_pct_points": 0.5,
         "tracking_error_annual_pct": None, "context": {"following": False}}))
    body = alpaca_status.render_body(alpaca_status.collect(tmp_path))
    assert "UNEXPECTED" in body and "&lt;b&gt;" in body          # 실패 문구는 이스케이프
    assert "+0.50%p" in body and "표본 부족" in body and "포지션 없음" in body
    assert "검증 UNEXPECTED" in alpaca_status.card_badge(tmp_path)


def test_alpaca_slot_links_to_its_page():
    from hub.server import _slot_href, render_alpaca_page

    slot = next(s for s in SLOTS if s.id == "alpaca")
    assert _slot_href(slot, "x") == "/alpaca"
    assert "Alpaca paper 검증" in render_alpaca_page()


def test_dashboard_groups_by_category_and_auto_refreshes():
    with _mock_active_status():
        page = server.render_dashboard("h")
    assert 'http-equiv="refresh"' in page and "마지막 갱신" in page
    cats = [c for c in ("앱", "엔진", "연구·검증", "운영", "리포트") if f'<h3 class="cat">{c}</h3>' in page]
    assert cats == ["앱", "엔진", "연구·검증", "운영", "리포트"]
    assert page.index('<h3 class="cat">앱</h3>') < page.index("퀀트 대시보드") < page.index('<h3 class="cat">엔진</h3>')


def test_report_card_shows_latest_or_missing(tmp_path, monkeypatch):
    slot = next(s for s in SLOTS if s.id == "report-news-digest")
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)
    assert "아직 없음" in server._report_badge(slot)
    (tmp_path / ".news-digest" / "reports").mkdir(parents=True)
    (tmp_path / ".news-digest" / "reports" / "news_1.html").write_text("<p>x</p>")
    assert "최신" in server._report_badge(slot)


def test_ops_page_degrades_per_section_and_flags_problems(tmp_path, monkeypatch):
    import json, time

    from hub import ops_status as ops

    good = tmp_path / "status.json"
    good.write_text(json.dumps({"last_success_epoch": time.time() - 3600, "last_success_at": "t", "ok": True,
                                "offsite_configured": False, "restore_drill_ok": True, "files": 5}))
    b = ops.read_backup(good)
    assert b["stale"] is False and b["drill_ok"] is True
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"last_success_epoch": time.time() - 100 * 3600, "ok": False, "error": "boom"}))
    assert ops.read_backup(old)["stale"] is True
    assert ops.read_backup(tmp_path / "missing.json") is None

    jobs = {"ok": True, "error": None, "counts": {"ok": 3, "problem": 1},
            "problems": [{"label": "L", "state": "error", "text": "L — 실행 중 오류 <b>"}]}
    body = ops.render_body(jobs, ops.read_backup(old), ops.system_info(), [("u.timer", "백업", "inactive")])
    assert "잡 이상 1개" in ops.jobs_badge(jobs) and "오류" in body and "&lt;b&gt;" in body
    assert "오래됨" in body and "실패" in body and "inactive" in body
    dead = {"ok": False, "counts": {}, "problems": [], "error": "OperationalError"}
    assert "확인 불가" in ops.render_body(dead, None, ops.system_info(), []) and "status.json 없음" in ops.render_body(dead, None, ops.system_info(), [])
    assert "잡 이력 확인 불가" in ops.jobs_badge(dead)


def test_ops_route_renders():
    with _mock_active_status():
        assert "운영 상태" in server.render_ops_page()


def test_overview_never_claims_all_ok_when_service_state_is_unknown(monkeypatch):
    """systemd 상태를 하나도 못 읽으면(개발 환경 등) '모든 시스템 정상'이라고 하지 않는다(2026-09-25)."""
    from hub.status import UnitStatus

    monkeypatch.setattr(server, "get_unit_status", lambda unit: UnitStatus("unknown", "unknown", ""))
    monkeypatch.setattr(server.ops_status, "job_health_summary", lambda: {"ok": True, "counts": {"ok": 3, "problem": 0}, "problems": [], "error": None})
    page = server.render_dashboard("h")
    assert "모든 시스템 정상" not in page and "서비스 상태를 확인할 수 없습니다" in page
