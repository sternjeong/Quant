"""core/planner.py · hub/planner_page.py 검증 — 할 일 저장·분류·반복·허브 화면."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from core import planner as pl
from core.contests import KST
from hub import planner_page

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=KST)  # 수요일


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = tmp_path / "planner.json"
    monkeypatch.setattr(pl, "STATE_PATH", path)
    monkeypatch.setattr(pl, "contest_tasks", lambda now=None: [])
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
    monkeypatch.setattr(ct, "list_contests", lambda: [
        ct.Contest(slug="demo", title="데모 해커톤", deadline="2026-11-18T23:00", status="진행"),
        ct.Contest(slug="old", title="끝난 대회", deadline="2026-11-18", status="종료"),
        ct.Contest(slug="stale", title="한참 지난 대회", deadline="2026-11-10", status="진행")])
    b = pl.buckets(now=NOW)
    assert [(t.title, t.source, t.link) for t in b.today] == [("데모 해커톤 마감 23:00", "contest", "/contests/demo")]


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
    assert f'href="{pl.DEFAULT_NOTION_URL}" target="_blank"' in page
    assert page.index("할 일 · 일정") < page.index("퀀트 대시보드")  # 맨 위 묶음
    notion = next(s for s in SLOTS if s.id == "notion")
    assert server._slot_href(notion, "host").startswith("https://")
