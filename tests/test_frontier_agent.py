"""core/frontier_agent.py — 결정론 관문(id·금지 코드·job.json·스모크)과 한 번 실행의 흐름(가짜 에이전트·가짜 저장소 반영)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core import frontier_agent as fa

OK_RUN = '''import argparse, json, pathlib
p = argparse.ArgumentParser(); p.add_argument("--out"); p.add_argument("--checkpoint"); p.add_argument("--smoke", action="store_true")
a = p.parse_args()
o = pathlib.Path(a.out); o.mkdir(parents=True, exist_ok=True)
(o / "results.json").write_text(json.dumps({"verdicts": {"x": "SMOKE_ONLY(FAIL)"}}))
(o / "REPORT.md").write_text("# ok\\n")
'''


def _job(job_id: str, **over) -> dict:
    d = {"id": job_id, "title": "테스트 연구", "entrypoint": f"research/jobs/{job_id}/run.py", "args": [],
         "timeout_seconds": 9999, "max_attempts": 3, "resumable": True, "outputs": ["results.json", "REPORT.md"],
         "summary_from": "verdicts", "priority": 5, "revision": 1, "max_memory_mb": 4000, "max_runs": 99}
    d.update(over)
    return d


def _make(dirp: Path, job_id: str, run_py: str = OK_RUN, **over) -> Path:
    d = dirp / job_id
    d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps(_job(job_id, **over), ensure_ascii=False), encoding="utf-8")
    (d / "run.py").write_text(run_py, encoding="utf-8")
    (d / "SPEC.md").write_text("# spec\n", encoding="utf-8")
    return d


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "research" / "jobs" / "old-job").mkdir(parents=True)
    (root / "research" / "results").mkdir(parents=True)
    (root / "core").mkdir()
    return root


def test_gate_accepts_valid_job_and_tightens_limits(repo, tmp_path):
    d = _make(tmp_path / "work", "frontier-test-idea-v1")
    job, files, why = fa.gate(d, repo)
    assert why == "ok" and job is not None
    assert job["priority"] >= fa.MIN_PRIORITY and job["timeout_seconds"] <= fa.MAX_TIMEOUT_S
    assert job["max_memory_mb"] <= fa.MAX_MEMORY_MB and job["max_runs"] <= fa.MAX_RUNS
    assert job["title"].startswith("[프런티어]")
    assert set(files) == {"job.json", "run.py", "SPEC.md"}


@pytest.mark.parametrize("name,code,expect", [
    ("frontier-bad-proc-v1", "import subprocess\n" + OK_RUN, "금지 코드"),
    ("frontier-bad-order-v1", "# submit_order(x)\n" + OK_RUN, "금지 코드"),
    ("frontier-bad-smoke-v1", "raise SystemExit(1)\n", "스모크"),
])
def test_gate_rejects_forbidden_code_and_failed_smoke(repo, tmp_path, name, code, expect):
    job, _files, why = fa.gate(_make(tmp_path / "work", name, code), repo)
    assert job is None and expect in why


def test_gate_rejects_bad_or_existing_id(repo, tmp_path):
    assert fa.gate(_make(tmp_path / "w1", "not-frontier-v1"), repo)[0] is None
    (repo / "research" / "jobs" / "frontier-dup-idea-v1").mkdir()
    job, _f, why = fa.gate(_make(tmp_path / "w2", "frontier-dup-idea-v1"), repo)
    assert job is None and "이미 있는" in why


def _fake_env(monkeypatch):
    monkeypatch.setattr(fa.budget, "can_launch", lambda role, now=None: (True, "ok"))
    monkeypatch.setattr(fa.budget, "record", lambda entry, path=None: None)
    monkeypatch.setattr(fa.budget, "seconds_until_hard_stop", lambda now=None: 3000.0)
    monkeypatch.setattr(fa.ab, "_porcelain", lambda: set())
    monkeypatch.setattr(fa.ab, "_guard", lambda before: [])


def test_run_promotes_one_job_and_publishes_doc(repo, monkeypatch):
    _fake_env(monkeypatch)
    seen = {}

    def runner(role, prompt, tools, cfg, timeout, system=None):
        work = next((repo / "research" / "frontier" / "work").iterdir())
        assert (work / "context.md").is_file() and any(t.startswith("Write(") for t in tools)
        (work / "FRONTIER.md").write_text("# 목표 문서\n" + "내용 " * 100, encoding="utf-8")
        (work / "journal.md").write_text("판단 기록\n", encoding="utf-8")
        _make(work, "frontier-first-idea-v1")
        _make(work, "frontier-second-idea-v1")
        return {"ok": True}

    def publish(root, files, message):
        seen.update(files=files, message=message)
        return {"status": "pushed", "sha": "abc"}

    out = fa.run(now_fn=lambda: datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc), runner=runner, publish=publish,
                 repo_root=repo)
    assert out["promoted"] == ["frontier-first-idea-v1"]          # 한 번에 하나만
    assert "research/frontier/FRONTIER.md" in seen["files"]
    assert "research/jobs/frontier-first-idea-v1/run.py" in seen["files"]
    assert not any("second" in k for k in seen["files"])
    assert any(k.startswith("research/frontier/journal/") for k in seen["files"])


def test_run_does_not_promote_when_pending_is_full(repo, monkeypatch):
    _fake_env(monkeypatch)
    for j in ("frontier-a-idea-v1", "frontier-b-idea-v1"):
        (repo / "research" / "jobs" / j).mkdir()                 # 결과 없음 = 대기 중

    def runner(role, prompt, tools, cfg, timeout, system=None):
        assert "새 연구를 만들지 말고" in prompt
        work = next((repo / "research" / "frontier" / "work").iterdir())
        _make(work, "frontier-c-idea-v1")
        return {"ok": True}

    out = fa.run(now_fn=lambda: datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc), runner=runner,
                 publish=lambda *a, **k: {"status": "pushed"}, repo_root=repo)
    assert out["promoted"] == []


def test_run_respects_budget_gate(monkeypatch, repo):
    monkeypatch.setattr(fa.budget, "can_launch", lambda role, now=None: (False, "주간 소진"))
    out = fa.run(runner=lambda *a, **k: pytest.fail("에이전트가 돌면 안 됨"), repo_root=repo)
    assert out == {"status": "skipped", "reason": "주간 소진"}


def test_prompt_and_role_are_registered():
    assert fa.PROMPT.is_file() and "SPY" in fa.PROMPT.read_text(encoding="utf-8")
    assert "frontier" in fa.budget.ROLES and fa.FRONTIER_DOC.is_file()
