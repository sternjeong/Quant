"""주간 대회 탐색(deploy/contest_scout/finalize.py)과 관제 화면(hub/contest_scout_page.py)."""

from __future__ import annotations

import importlib.util
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("contest_scout_finalize", ROOT / "deploy" / "contest_scout" / "finalize.py")
finalize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(finalize)

KST = timezone(timedelta(hours=9))


def _item(tier="auto", url="https://devpost.com/a", **kw):
    return {"tier": tier, "title": kw.pop("title", "대회 A"), "url": url, "deadline": "2026-11-30", "effort_hours": 2, **kw}


def test_normalize_drops_bad_items_and_dedupes():
    draft = {"items": [_item(), _item(title="중복"), _item(tier="hard", url="https://x/b"), _item(url="ftp://x"),
                       _item(tier="LIGHT", url="https://x/c", effort_hours="abc"), "junk"],
             "skipped": [{"title": "본선 합숙", "reason": "오프라인"}]}
    out = finalize.normalize(draft)
    assert [(i["tier"], i["url"]) for i in out["items"]] == [("auto", "https://devpost.com/a"), ("light", "https://x/c")]
    assert out["items"][1]["effort_hours"] == 0
    assert out["skipped"] == [{"title": "본선 합숙", "reason": "오프라인"}]


@pytest.mark.parametrize("draft", [{}, {"items": []}, {"items": [_item(tier="nope")]}])
def test_normalize_rejects_empty(draft):
    with pytest.raises(ValueError):
        finalize.normalize(draft)


def test_finalize_marks_new_and_keeps_previous_on_failure(tmp_path):
    now = datetime(2026, 11, 16, 9, tzinfo=KST)
    (tmp_path / "draft.json").write_text(json.dumps({"items": [_item()]}), encoding="utf-8")
    first = finalize.finalize(tmp_path, now)
    assert first["items"][0]["new"] is False  # 첫 실행은 비교 대상이 없으니 NEW 표시 안 함
    (tmp_path / "draft.json").write_text(json.dumps({"items": [_item(), _item(url="https://x/new")]}), encoding="utf-8")
    second = finalize.finalize(tmp_path, now + timedelta(days=7))
    assert [i["new"] for i in second["items"]] == [False, True]
    assert (tmp_path / "history" / "2026-11-23.json").exists() and not (tmp_path / "draft.json").exists()

    (tmp_path / "draft.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError):
        finalize.finalize(tmp_path, now + timedelta(days=14))
    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["items"] == second["items"]


def test_hub_page_render_badge_and_request(tmp_path, monkeypatch):
    from hub import contest_scout_page as page

    monkeypatch.setattr(page, "SCOUT_DIR", tmp_path)
    data = page.collect()
    assert "아직 없음" in page.card_badge(data)
    assert "지금 찾기" in page.render_body(data)

    latest = {"generated_at": "2026-11-16T09:30:00+09:00", "notes": "이번 주 요약",
              "items": [_item(new=True, what_to_do="<b>코드</b> 제출"), _item(tier="light", url="https://x/l", deadline="")]}
    (tmp_path / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    (tmp_path / "status.json").write_text(json.dumps({"state": "ok", "message": "finalize 완료"}), encoding="utf-8")
    data = page.collect()
    assert "딸깍 1 · 신경 1 · 새 1" in page.card_badge(data)
    body = page.render_body(data, today=date(2026, 11, 20))
    assert "D-10" in body and "NEW" in body and "마감 미정" in body and "이번 주 요약" in body
    assert "<b>코드</b>" not in body and "&lt;b&gt;코드" in body

    assert page.request_run() is None and (tmp_path / "run-request").exists()
    data = page.collect()
    assert "찾는 중" in page.card_badge(data) and "지금 찾기</button>" not in page.render_body(data)


def test_hub_slot_and_route(tmp_path, monkeypatch):
    from hub import contest_scout_page as page, server
    from hub.apps_registry import SLOTS

    monkeypatch.setattr(page, "SCOUT_DIR", tmp_path)
    slot = next(s for s in SLOTS if s.id == "contest-scout")
    assert server._slot_href(slot, "h") == "/contest-scout"
    assert "대회 탐색" in server.render_contest_scout_page()


def test_fetch_sources_keeps_going_when_one_site_fails(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("contest_scout_fetch", ROOT / "deploy" / "contest_scout" / "fetch_sources.py")
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)

    def fake_get(url):
        if "aichallenge4all" in url:
            raise OSError("down")
        return {"meta": {"per_page": 40, "total_count": 1},
                "hackathons": [{"title": "H", "url": "https://h.devpost.com/", "prize_amount": "$<span>1,000</span>",
                                "themes": [{"name": "AI"}]}]}

    monkeypatch.setattr(fetch, "_get", fake_get)
    monkeypatch.setattr(fetch.sys, "argv", ["x", str(tmp_path)])
    assert fetch.main() == 0
    rows = json.loads((tmp_path / "sources" / "devpost.json").read_text(encoding="utf-8"))
    assert rows[0]["prize"] == "$1,000" and rows[0]["themes"] == ["AI"]
    assert not (tmp_path / "sources" / "aichallenge4all.json").exists()


def test_register_button_prefills_new_contest_form(tmp_path, monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from core import contests as ct
    from hub import contest_scout_page as page, contests_page

    item = _item(title="Kiroween 2026", url="https://kiroween.devpost.com/", platform="Devpost", what_to_do="앱 제출")
    href = page.register_href(item)
    q = {k: v[0] for k, v in parse_qs(urlparse(href).query).items()}
    assert q["slug"] == "kiroween-2026" and q["platform"] == "기타" and q["deadline"] == "2026-11-30"
    assert "앱 제출" in q["memo"]
    form = contests_page.render_new("", values=q)
    assert 'value="kiroween-2026"' in form and 'value="https://kiroween.devpost.com/"' in form
    assert page.suggest_slug(_item(title="클릭온 AI 시즌2", url="https://clickon.or.kr/x")) == "clickon"

    monkeypatch.setattr(page, "SCOUT_DIR", tmp_path)
    monkeypatch.setattr(page, "registered_slugs", lambda: {"https://kiroween.devpost.com": "kiroween-2026"})
    (tmp_path / "latest.json").write_text(json.dumps({"items": [item, _item(url="https://x/other")]}), encoding="utf-8")
    body = page.render_body(page.collect())
    assert body.count("대회로 등록") == 1 and 'href="/contests/kiroween-2026"' in body
