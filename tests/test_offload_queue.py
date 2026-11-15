"""core/offload_queue.py · hub/offload_page.py 검증 — 로컬 bare 저장소를 GitHub 대기열 대신 쓴다."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core import offload_queue as oq
from hub import offload_page


def _run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def queue(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    _run("git", "init", "-q", "--bare", "-b", "main", str(remote))
    seed = tmp_path / "seed"
    _run("git", "init", "-q", "-b", "main", str(seed))
    (seed / "jobs").mkdir()
    (seed / "jobs" / ".gitkeep").write_text("")
    _run("git", "add", "-A", cwd=seed)
    _run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=seed)
    _run("git", "push", "-q", str(remote), "main", cwd=seed)
    monkeypatch.setattr(oq, "REPO_URL", str(remote))
    monkeypatch.setattr(oq, "QUEUE_DIR", tmp_path / "clone")
    monkeypatch.setattr(oq, "_last_fetch", 0.0)
    return remote, tmp_path


def _worker_reports(remote: Path, tmp: Path, job_id: str, text: str, artifact: bool = False) -> None:
    w = tmp / "worker"
    if not w.exists():
        _run("git", "clone", "-q", str(remote), str(w))
    _run("git", "fetch", "-q", "origin", cwd=w)
    _run("git", "checkout", "-q", "-B", f"claude/result-{job_id}", "origin/main", cwd=w)
    d = w / "jobs" / job_id
    (d / "RESULT.md").write_text(text)
    if artifact:
        (d / "artifacts").mkdir(exist_ok=True)
        (d / "artifacts" / "pytest.log").write_text("ok\n")
    _run("git", "add", "-A", cwd=w)
    _run("git", "-c", "user.name=w", "-c", "user.email=w@w", "commit", "-q", "-m", "result", cwd=w)
    _run("git", "push", "-q", "-f", "origin", f"claude/result-{job_id}", cwd=w)


def test_submit_list_and_result_flow(queue):
    remote, tmp = queue
    job = oq.submit("전체 테스트 돌리기\n자세한 설명", repo="sternjeong/Quant", timeout_min=99)
    assert job.timeout_min == 55  # 상한
    jobs = oq.list_jobs()
    assert [(j.id, j.status, j.title) for j in jobs] == [(job.id, "queued", "전체 테스트 돌리기")]

    _worker_reports(remote, tmp, job.id, "status: running\nstarted: now\n")
    oq.sync(force=True)
    assert oq.get_job(job.id).status == "running"

    _worker_reports(remote, tmp, job.id, "status: done\n3000 passed\n", artifact=True)
    oq.sync(force=True)
    got = oq.get_job(job.id)
    assert got.status == "done" and "3000 passed" in got.result
    assert oq.artifacts(job.id) == [("pytest.log", 3)]
    assert oq.summary([got])["done"] == 1


def test_submit_validation(queue):
    with pytest.raises(oq.OffloadError):
        oq.submit("")
    with pytest.raises(oq.OffloadError):
        oq.submit("x", repo="someone/else")
    with pytest.raises(oq.OffloadError):
        oq.submit("x", ref="--upload-pack=evil")


def test_get_job_rejects_path_tricks(queue):
    assert oq.get_job("../etc") is None
    assert oq.get_job("nope") is None


def test_pages_render_and_escape(queue):
    job = oq.submit("<script>x</script> 돌리기", repo="sternjeong/Quant")
    body = offload_page.render_body()
    assert "&lt;script&gt;" in body and "<script>x" not in body
    assert f'href="/offload/{job.id}"' in body
    assert "대기 1" in offload_page.card_badge()
    detail = offload_page.render_detail_body(job.id)
    assert "아직 결과가 없습니다" in detail
    assert offload_page.render_detail_body("missing") is None


def test_handle_submit_error_keeps_values(queue):
    target, err, values = offload_page.handle_submit({"task": [""], "repo": ["sternjeong/Quant"]})
    assert err and values["repo"] == "sternjeong/Quant" and target == "/offload"
    target, err, _ = offload_page.handle_submit({"task": ["일"], "repo": [""], "timeout": ["10"]})
    assert err is None and target.startswith("/offload/")


def test_card_badge_survives_github_failure(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(oq, "QUEUE_DIR", tmp_path)
    monkeypatch.setattr(oq, "list_jobs", lambda limit=20: (_ for _ in ()).throw(oq.OffloadError("down")))
    assert "확인 불가" in offload_page.card_badge()


def test_card_badge_does_not_clone_from_dashboard(monkeypatch, tmp_path):
    monkeypatch.setattr(oq, "QUEUE_DIR", tmp_path / "none")
    monkeypatch.setattr(oq, "list_jobs", lambda limit=20: pytest.fail("dashboard must not fetch"))
    assert "열어서 확인" in offload_page.card_badge()
