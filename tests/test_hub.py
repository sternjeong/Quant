"""hub/ 모듈 검증. systemctl 호출은 실제 systemd에 의존하지 않도록 subprocess.run을 목킹한다."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from hub import server
from hub.apps_registry import SLOTS
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
        if slot.kind in ("web", "tunnel"):
            assert slot.port is not None
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
    web_slot = next(slot for slot in SLOTS if slot.kind == "web")
    href = server._slot_href(web_slot, "203.0.113.10")
    assert href == f"http://203.0.113.10:{web_slot.port}/"


def test_slot_href_tunnel_points_to_guide_page_not_a_public_port():
    tunnel_slot = next(slot for slot in SLOTS if slot.kind == "tunnel")
    href = server._slot_href(tunnel_slot, "203.0.113.10")
    assert href == f"/tunnel/{tunnel_slot.id}"
    assert "203.0.113.10" not in href  # 외부에 열지 않은 포트로 직접 링크하면 타임아웃이 난다


def test_code_server_is_a_tunnel_slot_not_publicly_linked():
    slot = next(slot for slot in SLOTS if slot.id == "code-server")
    assert slot.kind == "tunnel"


def test_render_tunnel_page_shows_ssh_command_with_host_and_port():
    tunnel_slot = next(slot for slot in SLOTS if slot.kind == "tunnel")
    with _mock_active_status():
        page = server.render_tunnel_page(tunnel_slot, "203.0.113.10")
    assert f"ssh -L {tunnel_slot.port}:localhost:{tunnel_slot.port} ubuntu@203.0.113.10" in page
    assert f"http://localhost:{tunnel_slot.port}/" in page
    assert "Ports" in page


def test_render_tunnel_page_escapes_host_header():
    tunnel_slot = next(slot for slot in SLOTS if slot.kind == "tunnel")
    with _mock_active_status():
        page = server.render_tunnel_page(tunnel_slot, '"><script>alert(1)</script>')
    assert "<script>alert(1)</script>" not in page


def test_slot_href_report_points_to_reports_route():
    report_slot = next(slot for slot in SLOTS if slot.kind == "report")
    assert server._slot_href(report_slot, "host") == f"/reports/{report_slot.id}"


def test_slot_href_engine_points_to_status_route():
    engine_slot = next(slot for slot in SLOTS if slot.kind == "engine")
    assert server._slot_href(engine_slot, "host") == f"/status/{engine_slot.id}"


def test_find_slot_by_id_and_kind():
    web_slot = next(slot for slot in SLOTS if slot.kind == "web")
    assert server.find_slot(web_slot.id) is web_slot
    assert server.find_slot(web_slot.id, kind="report") is None
    assert server.find_slot("no-such-id") is None


def test_latest_report_path_picks_newest_file(tmp_path, monkeypatch):
    report_slot = next(slot for slot in SLOTS if slot.kind == "report")
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
    report_slot = next(slot for slot in SLOTS if slot.kind == "report")
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)
    assert server.latest_report_path(report_slot) is None


def test_render_status_page_shows_unit_name():
    engine_slot = next(slot for slot in SLOTS if slot.kind == "engine")
    with _mock_active_status():
        page = server.render_status_page(engine_slot)
    assert engine_slot.unit in page
    assert engine_slot.title in page
