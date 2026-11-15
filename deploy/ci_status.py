#!/usr/bin/env python3
"""GitHub Actions 테스트 관문(.github/workflows/tests.yml 의 test-gate 잡)이 한 커밋에서 어떻게 끝났는지 한 단어로 출력한다.

auto_deploy.sh 가 VM 에서 전체 테스트(2코어에서 30~45분)를 돌리는 대신 이 결과를 본다. 시스템 python3 표준 라이브러리만 쓴다
(deploy/codex_telegram/runner.py 와 같은 전제 — 프로젝트 venv 없이도 돈다).

출력(표준출력 한 줄, 종료 코드는 항상 0):
    success   test-gate 가 성공으로 끝남
    failure   test-gate 가 실패·취소·시간 초과로 끝남 (같은 줄에 탭 뒤로 실행 주소)
    pending   test-gate 가 아직 대기·실행 중
    none      이 커밋에 test-gate 실행이 아직 없음(워크플로가 안 돌았거나 시작 전)
    error     GitHub API 를 읽지 못함(네트워크·요청 한도 등)

저장소는 공개라 토큰 없이 읽는다(IP 당 시간 60회 — auto_deploy 는 새 커밋을 기다릴 때만 5분마다 1회 묻는다).
환경변수 GITHUB_TOKEN 이 있으면 붙인다(값은 출력·기록하지 않는다).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_REPO = "sternjeong/Quant"
GATE_NAME = "test-gate"
FAILED = {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"}


def classify(payload: dict, gate_name: str = GATE_NAME) -> tuple[str, str]:
    """check-runs 응답 → (상태, 실행 주소). 같은 이름이 여러 번 돌았으면 가장 최근 것을 본다."""
    runs = [r for r in payload.get("check_runs", []) if r.get("name") == gate_name]
    if not runs:
        return "none", ""
    run = max(runs, key=lambda r: r.get("started_at") or "")
    url = run.get("html_url") or ""
    if run.get("status") != "completed":
        return "pending", url
    if run.get("conclusion") == "success":
        return "success", url
    if run.get("conclusion") in FAILED:
        return "failure", url
    return "failure", url  # neutral/skipped 등 — 통과로 보지 않는다


def fetch(sha: str, repo: str, timeout: float = 20.0) -> dict:
    url = f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs?check_name={GATE_NAME}&per_page=20"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "quant-auto-deploy"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("error\tusage: ci_status.py <commit-sha> [owner/repo]")
        return 0
    sha = argv[1]
    repo = argv[2] if len(argv) > 2 else os.environ.get("AUTO_DEPLOY_GITHUB_REPO", DEFAULT_REPO)
    try:
        state, url = classify(fetch(sha, repo))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"error\t{type(exc).__name__}")
        return 0
    print(f"{state}\t{url}" if url else state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
