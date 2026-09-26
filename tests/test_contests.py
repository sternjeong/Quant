"""AI 대회 관리(core/contests.py, hub/contests_page.py) — git 은 실제로, gh 는 가짜로."""

import io
import json
import subprocess
from datetime import datetime

import pytest

from core import contests as ct

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=ct.KST)


def fake_runner(gh_ok=True, owner="me", calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append(cmd)
        if cmd[0] == ct.GH_BIN:
            if cmd[1:3] == ["api", "user"]:
                return subprocess.CompletedProcess(cmd, 0 if owner else 1, owner or "", "")
            return subprocess.CompletedProcess(cmd, 0 if gh_ok else 1, "", "" if gh_ok else "HTTP 401: Bad credentials")
        return subprocess.run(cmd, **kw)
    return run


@pytest.fixture()
def root(tmp_path, monkeypatch):
    r = tmp_path / "contests"
    r.mkdir()
    monkeypatch.setattr(ct, "CONTESTS_ROOT", r)
    return r


def test_create_scaffolds_commits_and_creates_private_repo(root):
    calls = []
    c = ct.create_contest("kaggle-titanic", "Titanic", "Kaggle", "https://kaggle.com/c/titanic", "2026-11-30", "첫 대회",
                          runner=fake_runner(calls=calls))
    d = root / "kaggle-titanic"
    for f in ("README.md", ".gitignore", "requirements.txt", "data/.gitkeep", "notebooks/.gitkeep", "src/__init__.py",
              "submissions/.gitkeep", "contest.json"):
        assert (d / f).exists(), f
    assert c.repo == "me/contest-kaggle-titanic" and c.repo_status == "created"
    gh_create = next(x for x in calls if x[:3] == [ct.GH_BIN, "repo", "create"])
    assert "--private" in gh_create and "--push" in gh_create
    log = subprocess.run(["git", "log", "--oneline"], cwd=d, capture_output=True, text=True).stdout
    assert "Start Titanic" in log
    shared = subprocess.run(["git", "config", "core.sharedRepository"], cwd=d, capture_output=True, text=True).stdout.strip()
    assert shared in ("group", "1")                      # code-server(ubuntu)도 커밋할 수 있게
    assert json.loads((d / "contest.json").read_text())["repo_status"] == "created"


def test_gh_failure_keeps_folder_and_retry_succeeds(root):
    c = ct.create_contest("dacon-x", "X", "Dacon", runner=fake_runner(gh_ok=False))
    assert c.repo_status.startswith("failed:") and "401" in c.repo_status and (root / "dacon-x" / ".git").is_dir()
    assert ct.create_repo("dacon-x", runner=fake_runner()).repo_status == "created"
    c = ct.create_contest("dacon-y", "Y", "Dacon", runner=fake_runner(owner=None))
    assert "gh 로그인" in c.repo_status


@pytest.mark.parametrize("slug", ["../etc", "Upper", "a", "has space", "x" * 50, "-lead"])
def test_bad_slugs_rejected(root, slug):
    with pytest.raises(ct.ContestError):
        ct.create_contest(slug, "t", "Kaggle", runner=fake_runner())
    assert ct.load(slug) is None


def test_validation_and_existing_folder(root):
    with pytest.raises(ct.ContestError) as e:
        ct.create_contest("ok-slug", "", "Nope", "ftp://x", "2026/1/1", runner=fake_runner())
    for part in ("대회 이름", "플랫폼", "대회 링크", "마감"):
        assert part in str(e.value)
    ct.create_contest("ok-slug", "t", "Kaggle", runner=fake_runner())
    with pytest.raises(ct.ContestError):
        ct.create_contest("ok-slug", "t", "Kaggle", runner=fake_runner())


def test_root_missing_gives_setup_instruction(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "CONTESTS_ROOT", tmp_path / "nope")
    ok, why = ct.root_status()
    assert not ok and "setup_contests.sh" in why
    with pytest.raises(ct.ContestError, match="setup_contests.sh"):
        ct.create_contest("a-b", "t", "Kaggle", runner=fake_runner())


def test_list_order_and_days_left(root):
    for slug, dl, st in (("far", "2026-12-31", "진행"), ("near", "2026-11-21", "진행"), ("none", "", "준비"),
                         ("done", "2026-11-22", "종료")):
        ct.create_contest(slug + "-c", slug, "Kaggle", deadline=dl, runner=fake_runner())
        ct.update(slug + "-c", status=st)
    assert [c.slug for c in ct.list_contests(now=NOW)] == ["near-c", "far-c", "none-c", "done-c"]
    assert ct.load("near-c").days_left(NOW) == 1
    assert ct.Contest("x", "x", deadline="2026-11-20T23:00").days_left(NOW) == 0


def test_deadline_alerts_once_per_stage_and_skip_finished(root, tmp_path):
    ct.create_contest("a-c", "A", "Kaggle", deadline="2026-11-27", runner=fake_runner())   # D-7
    ct.create_contest("b-c", "B", "Kaggle", deadline="2026-11-21", runner=fake_runner())   # D-1
    ct.create_contest("c-c", "C", "Kaggle", deadline="2026-11-21", runner=fake_runner())
    ct.update("c-c", status="제출 완료")
    msgs, state = [], tmp_path / "alerts.json"
    r = ct.run_deadline_alerts(now=NOW, notify=msgs.append, state_path=state)
    assert sorted(r["sent"]) == ["a-c:2026-11-27:7", "b-c:2026-11-21:1"] and len(msgs) == 2
    assert any("D-1" in m for m in msgs) and not any("C —" in m for m in msgs)
    assert ct.run_deadline_alerts(now=NOW, notify=msgs.append, state_path=state)["sent"] == []   # 같은 날 재실행
    later = datetime(2026, 11, 21, 9, 0, tzinfo=ct.KST)
    assert ct.run_deadline_alerts(now=later, notify=msgs.append, state_path=state)["sent"] == ["b-c:2026-11-21:0"]


def test_code_server_url_opens_folder(root):
    c = ct.Contest("kaggle-titanic", "t")
    assert ct.code_server_url(c, "https://code.example/") == f"https://code.example/?folder={root}/kaggle-titanic"


# ---------------------------------------------------------------- 허브
def _post(path, body, monkeypatch):
    from hub import contests_page
    from hub.server import HubRequestHandler

    raw = body.encode()
    h = HubRequestHandler.__new__(HubRequestHandler)
    h.path = path
    h.headers = {"Content-Length": str(len(raw)), "Host": "hub", "Origin": "null", "Sec-Fetch-Site": "same-origin"}
    h.rfile, h.wfile = io.BytesIO(raw), io.BytesIO()
    sent, headers = [], {}
    h.send_response = lambda code: sent.append(code)
    h.send_header = lambda k, v: headers.__setitem__(k, v)
    h.end_headers = lambda: None
    h.do_POST()
    return sent[0], headers, h.wfile.getvalue().decode()


@pytest.fixture()
def fake_gh(tmp_path, monkeypatch):
    """허브 경로는 runner 를 주입할 수 없으므로 실행 파일 형태의 가짜 gh 를 쓴다."""
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\nif [ \"$1\" = api ]; then echo me; fi\nexit 0\n")
    gh.chmod(0o755)
    monkeypatch.setattr(ct, "GH_BIN", str(gh))
    return gh


def test_hub_create_update_and_pages(root, fake_gh, monkeypatch):
    from urllib.parse import urlencode

    from hub import server

    code, headers, _ = _post("/contests/new", urlencode({"title": "Titanic", "slug": "kaggle-titanic", "platform": "Kaggle",
                                                         "url": "", "deadline": "2026-11-30", "memo": ""}), monkeypatch)
    assert code == 303 and headers["Location"] == "/contests/kaggle-titanic"
    code, _, body = _post("/contests/new", urlencode({"title": "", "slug": "BAD", "platform": "Kaggle"}), monkeypatch)
    assert code == 400 and "폴더 이름" in body and 'value="BAD"' in body          # 입력값 유지
    code, headers, _ = _post("/contests/kaggle-titanic/update", urlencode({"title": "Titanic", "status": "진행",
                             "platform": "Kaggle", "url": "", "deadline": "2026-12-01", "memo": "메모"}), monkeypatch)
    assert code == 303 and ct.load("kaggle-titanic").deadline == "2026-12-01"
    detail = server.contests_page.render_detail("kaggle-titanic", server.PAGE_STYLE)
    assert "VS Code 에서 열기" in detail and "folder=" in detail and "contest-kaggle-titanic" in detail
    assert "Titanic" in server.contests_page.render_list(server.PAGE_STYLE)
    assert "진행 1개" in server.contests_page.card_badge()
    assert "AI 대회" in server.render_dashboard("h")


def test_hub_post_rejects_cross_site(root, monkeypatch):
    from hub.server import HubRequestHandler

    h = HubRequestHandler.__new__(HubRequestHandler)
    h.path = "/contests/new"
    h.headers = {"Content-Length": "0", "Sec-Fetch-Site": "cross-site"}
    h.rfile, h.wfile = io.BytesIO(b""), io.BytesIO()
    sent = []
    h.send_response = lambda c: sent.append(c)
    h.send_header = lambda *a: None
    h.end_headers = lambda: None
    h.do_POST()
    assert sent == [403]
