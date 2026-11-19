"""core/planner.py · hub/planner_page.py 검증 — 할 일 저장·분류·반복·허브 화면."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from core import planner as pl
from core.contests import KST
from hub import planner_page

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=KST)  # 수요일
REAL_SIGNAL_TASKS = pl.signal_tasks


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = tmp_path / "planner.json"
    monkeypatch.setattr(pl, "STATE_PATH", path)
    monkeypatch.setattr(pl, "contest_tasks", lambda now=None: [])
    monkeypatch.setattr(pl, "signal_tasks", lambda path=None: [])
    return path


def test_parse_due_shortcuts():
    today = date(2026, 11, 18)
    assert pl.parse_due("오늘", today) == "2026-11-18"
    assert pl.parse_due("내일", today) == "2026-11-19"
    assert pl.parse_due("+3", today) == "2026-11-21"
    assert pl.parse_due("2026-12-01", today) == "2026-12-01"
    assert pl.parse_due("", today) == ""
    with pytest.raises(pl.PlannerError):
        pl.parse_due("다음주쯤", today)


def test_buckets_split_by_due_date(state):
    for title, due in (("지난 일", "2026-11-17"), ("오늘 일", "2026-11-18"), ("7일 안", "2026-11-25"),
                       ("8일 뒤", "2026-11-26"), ("언젠가", "")):
        pl.add_task(title, area="주식", due=due, now=NOW)
    b = pl.buckets(now=NOW)
    assert [t.title for t in b.overdue] == ["지난 일"]
    assert [t.title for t in b.today] == ["오늘 일"]
    assert [t.title for t in b.week] == ["7일 안"]
    assert [t.title for t in b.later] == ["8일 뒤"]
    assert [t.title for t in b.someday] == ["언젠가"]


def test_done_undo_and_delete(state):
    t = pl.add_task("녹화 영상 찍기", area="AI 대회", due="+2", now=NOW)
    pl.set_done(t.id, now=NOW)
    assert [x.title for x in pl.buckets(now=NOW).done] == ["녹화 영상 찍기"]
    pl.set_done(t.id, False, now=NOW)
    assert [x.title for x in pl.buckets(now=NOW).week] == ["녹화 영상 찍기"]
    pl.delete_task(t.id)
    assert pl.list_tasks() == []
    with pytest.raises(pl.PlannerError):
        pl.delete_task(t.id)


def test_repeating_task_rolls_forward_instead_of_finishing(state):
    t = pl.add_task("포트폴리오 점검", area="주식", due="2026-11-11", repeat="weekly", now=NOW)
    t = pl.set_done(t.id, now=NOW)
    assert not t.done and t.due == "2026-11-25"
    assert pl.next_due(date(2026, 11, 20), "weekdays", date(2026, 11, 20)) == date(2026, 11, 23)
    assert pl.next_due(date(2026, 1, 31), "monthly", date(2026, 1, 31)) == date(2026, 2, 28)


def test_validation_errors(state):
    with pytest.raises(pl.PlannerError):
        pl.add_task("", now=NOW)
    with pytest.raises(pl.PlannerError):
        pl.add_task("x", area="없는 분야", now=NOW)
    with pytest.raises(pl.PlannerError):
        pl.add_task("x", link="javascript:alert(1)", now=NOW)
    with pytest.raises(pl.PlannerError):
        pl.add_task("x", repeat="weekly", now=NOW)  # 반복엔 첫 마감 필요


def test_notion_url_default_and_override(state):
    assert pl.notion_url() == pl.DEFAULT_NOTION_URL
    pl.set_notion_url("https://www.notion.so/me/Home-abc")
    assert pl.notion_url() == "https://www.notion.so/me/Home-abc"
    with pytest.raises(pl.PlannerError):
        pl.set_notion_url("http://insecure")
    pl.set_notion_url("")
    assert pl.notion_url() == pl.DEFAULT_NOTION_URL


def test_contest_deadlines_show_as_read_only_tasks(tmp_path, monkeypatch):
    from core import contests as ct

    monkeypatch.setattr(pl, "STATE_PATH", tmp_path / "planner.json")
    monkeypatch.setattr(pl, "signal_tasks", lambda path=None: [])
    monkeypatch.setattr(ct, "list_contests", lambda: [
        ct.Contest(slug="demo", title="데모 해커톤", deadline="2026-11-18T23:00", status="진행"),
        ct.Contest(slug="old", title="끝난 대회", deadline="2026-11-18", status="종료"),
        ct.Contest(slug="stale", title="한참 지난 대회", deadline="2026-11-10", status="진행")])
    b = pl.buckets(now=NOW)
    assert [(t.title, t.source, t.link) for t in b.today] == [("데모 해커톤 제출하기 · 마감 23:00", "contest", "/contests/demo")]


def test_page_renders_and_escapes(state):
    pl.add_task("<b>녹화</b>", area="AI 대회", due="오늘", link="https://www.notion.so/x", now=datetime.now(KST))
    body = planner_page.render_body()
    assert "&lt;b&gt;녹화&lt;/b&gt;" in body and "<b>녹화</b>" not in body
    assert "Notion ↗" in body and "오늘 할 일 1개" in body
    assert "오늘 1" in planner_page.card_badge()


def test_handle_post_add_done_and_error(state):
    target, err, _ = planner_page.handle_post("/planner/add", {"title": ["시연 영상"], "area": ["AI 대회"], "due": ["+1"]})
    assert err is None and target.startswith("/planner?msg=")
    task = pl.list_tasks()[0]
    assert planner_page.handle_post("/planner/done", {"id": [task.id]})[1] is None
    assert pl.list_tasks()[0].done
    _, err, values = planner_page.handle_post("/planner/add", {"title": [""], "area": ["기타"]})
    assert err and values["area"] == "기타"


def test_dashboard_has_planner_and_notion_slots(state):
    from unittest.mock import patch
    import subprocess
    from hub import server
    from hub.apps_registry import SLOTS

    out = "ActiveState=active\nSubState=running\nActiveEnterTimestamp=n/a\n"
    run = lambda *a, **k: subprocess.CompletedProcess(args=a, returncode=0, stdout=out, stderr="")  # noqa: E731
    with patch("subprocess.run", side_effect=run):
        page = server.render_dashboard("host")
    assert 'href="/planner"' in page
    assert 'href="/notion"' in page  # 2026-11-16: 외부 링크 대신 VM 크롬 자동 로그인 화면
    assert page.index("할 일 · 일정") < page.index("퀀트 대시보드")  # 맨 위 묶음
    notion = next(s for s in SLOTS if s.id == "notion")
    assert server._slot_href(notion, "host") == "/notion"


# ---- 2026-11-16: Notion 자동 로그인 화면(hub/notion_page.py)

def test_notion_page_starts_by_post_and_embeds_authenticated_viewer(state):
    from hub import notion_page

    page = notion_page.render_page()
    assert 'fetch("/notion/start", {method: "POST"' in page  # GET 만으로는 로그인을 시작하지 않는다(CSRF)
    assert "/vm-browser/vnc.html" in page and "path=vm-browser/websockify" in page
    assert "127.0.0.1" not in page and "6080" not in page
    assert f'href="{pl.DEFAULT_NOTION_URL}"' in page  # 내 브라우저로 여는 길도 남긴다


def test_notion_start_sends_configured_url_to_gpu_hub(state, monkeypatch):
    from hub import notion_page

    calls = []
    monkeypatch.setattr(notion_page, "_gpu_hub", lambda path, payload=None, timeout=15: calls.append((path, payload)) or {"state": "checking"})
    pl.set_notion_url("https://www.notion.so/me/Home-abc")
    assert notion_page.start() == {"state": "checking"}
    assert calls == [("/api/notion/login", {"url": "https://www.notion.so/me/Home-abc"})]
    notion_page.status()
    assert calls[-1] == ("/api/notion/status", None)


def test_notion_gpu_hub_down_is_reported(monkeypatch):
    from hub import notion_page

    monkeypatch.setattr(notion_page, "GPU_HUB", "http://127.0.0.1:9")  # 닫힌 포트
    s = notion_page.status()
    assert s["done"] is True and s["state"] == "error" and "gpu-hub" in s["message"]


def test_notion_start_rejects_cross_site_post(monkeypatch):
    import io
    from hub import server, notion_page

    monkeypatch.setattr(notion_page, "start", lambda: (_ for _ in ()).throw(AssertionError("must not start")))
    h = server.HubRequestHandler.__new__(server.HubRequestHandler)
    h.path, h.command, h.request_version = "/notion/start", "POST", "HTTP/1.1"
    h.headers = {"Sec-Fetch-Site": "cross-site", "Host": "hub"}
    h.wfile, h.rfile = io.BytesIO(), io.BytesIO()
    sent = []
    h.send_response = lambda code, msg=None: sent.append(code)
    h.send_header = lambda *a: None
    h.end_headers = lambda: None
    h.do_POST()
    assert sent == [403]


def test_gateway_template_keeps_viewer_behind_login():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "deploy" / "setup_gateway.sh").read_text(encoding="utf-8")
    block = text[text.index("location /vm-browser/ {"):]
    block = block[:block.index("\n    }\n")]
    assert "cookie_qt_session != \\$qt_token" in block and "return 302" in block
    assert "proxy_pass http://127.0.0.1:6080/;" in block and "Upgrade" in block


# ---- 2026-11-15: 세션 기록(plan CLI), 주식 시그널, 대회 '제출하기'

def test_upsert_and_done_by_key(state):
    t, created = pl.upsert_by_key("arbiter:demo-video", "시연 영상 녹화", area="AI 대회", due="+3",
                                  origin="claude:arbiter", now=NOW)
    assert created and t.key == "arbiter:demo-video" and t.due == "2026-11-21"
    t2, created2 = pl.upsert_by_key("arbiter:demo-video", "시연 영상 녹화(3분)", area="AI 대회", due="+2", now=NOW)
    assert not created2 and t2.id == t.id and len(pl.list_tasks()) == 1
    assert pl.list_tasks()[0].title == "시연 영상 녹화(3분)"
    assert pl.done_by_key("arbiter:demo-video", now=NOW) == 1
    assert pl.done_by_key("arbiter:demo-video", now=NOW) == 0
    # 끝난 뒤 같은 key 로 다시 기록하면 새 할 일
    _, created3 = pl.upsert_by_key("arbiter:demo-video", "다시", now=NOW)
    assert created3
    with pytest.raises(pl.PlannerError):
        pl.upsert_by_key("Bad Key!", "x", now=NOW)


def test_api_add_list_done(state):
    status, res = planner_page.handle_api("add", {"key": ["quant:check"], "title": ["백테스트 결과 검토"],
                                                  "area": ["프로젝트"], "project": ["Quant"]})
    assert status == 200 and res["created"]
    status, res = planner_page.handle_api("list", {"project": ["quant"]})
    assert [t["key"] for t in res["tasks"]] == ["quant:check"]
    status, res = planner_page.handle_api("done", {"key": ["quant:check"]})
    assert res["closed"] == 1
    assert planner_page.handle_api("add", {"key": ["k"], "title": [""]})[0] == 400
    assert planner_page.handle_api("nope", {})[0] == 404


def test_signal_tasks_and_dismiss(state, tmp_path, monkeypatch):
    from core import planner_signals as ps

    sig = tmp_path / "signals.json"
    monkeypatch.setattr(ps, "SIGNALS_PATH", sig)
    monkeypatch.setattr(pl, "signal_tasks", REAL_SIGNAL_TASKS)
    sig.write_text(json.dumps({"generated_at": "x", "errors": [], "items": ps.review_items([
        {"ticker": "XLE", "quantity": 6.0, "action": "매도 확인", "due_date": "2026-11-02", "holding_id": 4,
         "detail": "추천에서 제외", "strategy_role": "코어"}]) + ps.rebalance_items({"core_next": "2026-12-01"})}))
    b = pl.buckets(now=NOW)
    assert [t.title for t in b.overdue] == ["XLE 6주 매도하기"]
    assert b.overdue[0].kind == "sell" and b.overdue[0].source == "signal"
    assert any("코어 리밸런싱" in t.title for t in b.later)
    pl.dismiss(b.overdue[0].id, now=NOW)
    assert pl.buckets(now=NOW).overdue == []
    with pytest.raises(pl.PlannerError):
        pl.dismiss("contest:demo", now=NOW)


def test_alert_items_keep_recent_only():
    from core import planner_signals as ps

    rows = [{"id": 1, "ticker": "AAPL", "detected_at": datetime(2026, 11, 17, 21, 0), "message": "골든크로스", "strategy": "MA"},
            {"id": 2, "ticker": "OLD", "detected_at": datetime(2026, 11, 1, 21, 0), "message": "", "strategy": ""}]
    items = ps.alert_items(rows, NOW)
    assert [i["title"] for i in items] == ["AAPL 타점 포착 (MA) — 진입 검토"]


def test_contest_task_says_submit_with_memo(tmp_path, monkeypatch):
    from core import contests as ct

    monkeypatch.setattr(pl, "STATE_PATH", tmp_path / "planner.json")
    memo = "위비티 · 상금\n할 일 아이디어 제안서 제출\n사람 몫 접수 사이트 가입·제출\n왜 이 등급 ..."
    monkeypatch.setattr(ct, "list_contests", lambda: [
        ct.Contest(slug="daegu", title="대구 기후 대회", deadline="2026-11-20T17:00", status="준비", memo=memo)])
    t = pl.contest_tasks(NOW)[0]
    assert t.title == "대구 기후 대회 제출하기 · 마감 17:00"
    assert "아직 시작 전" in t.project
    assert t.note == "할 일 아이디어 제안서 제출 · 사람 몫 접수 사이트 가입·제출"
