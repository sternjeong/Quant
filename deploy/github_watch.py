#!/usr/bin/env python3
"""GitHub Actions 실행 결과를 감시해 **새로 실패한 것만** 텔레그램으로 알린다 (stdlib만, quant 계정).

왜 필요한가: GitHub에서 벌어지는 일이 폰까지 오는 경로가 없었다. 실제로 `Oracle capacity retry` 워크플로가
2026-09-09부터 15일간 **100회 연속 실패**하는 동안 아무도 몰랐다(docs/TELEGRAM_REPO_BRIDGE_SPEC.md 2번).
사용자는 폰 텔레그램으로만 운영하므로 "조용한 실패"가 가장 위험하다.

설계상 중요한 점: 이 저장소는 **공개**라서 GitHub API를 **토큰 없이** 읽을 수 있다(VM에서 직접 확인).
따라서 저장소 시크릿도, VM의 GitHub 토큰도 필요 없다 — 사람이 할 설정이 0이다. 비인증 한도는 시간당 60회인데
15분 간격이면 시간당 4회라 충분하다.

무엇을 알리나:
  - 새로 실패(failure/timed_out/startup_failure)한 워크플로 실행 → 한 번만 알린다(같은 실행을 반복 알리지 않음).
  - 실패했다가 다시 성공한 워크플로 → "복구됨"을 한 번 알린다(계속 신경 쓰지 않아도 되게).
  - 취소(cancelled)/건너뜀(skipped)은 사람이 의도한 것이므로 알리지 않는다.

상태는 STATE_PATH(JSON)에 남긴다: 마지막으로 본 실행 id와 워크플로별 마지막 결론.
처음 실행할 때는 과거 실패를 한꺼번에 쏟아내지 않고 현재 상태만 기록하고 조용히 끝낸다(도입 직후 폭탄 방지).

사용법: python3 deploy/github_watch.py [--dry-run] [--limit N]
환경변수: QUANT_GITHUB_REPO(기본 sternjeong/Quant), QUANT_GITHUB_WATCH_STATE(상태 파일 경로)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

DEFAULT_REPO = "sternjeong/Quant"
DEFAULT_STATE = "/opt/quant/.auto-deploy-state/github_watch.json"
API_TIMEOUT = 20
FETCH_COUNT = 30  # 15분 간격이면 이 정도면 충분히 겹친다
FAILURE_CONCLUSIONS = ("failure", "timed_out", "startup_failure")
KEEP_SEEN = 200  # 상태 파일이 무한정 커지지 않게

STATE_PATH = Path(os.environ.get("QUANT_GITHUB_WATCH_STATE", DEFAULT_STATE))
REPO = os.environ.get("QUANT_GITHUB_REPO", DEFAULT_REPO)


def fetch_runs(repo: str, limit: int = FETCH_COUNT) -> list[dict]:
    """최근 워크플로 실행 목록(완료된 것만). 공개 저장소라 인증 없이 읽는다."""
    url = f"https://api.github.com/repos/{repo}/actions/runs?per_page={limit}&status=completed"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "quant-vm-github-watch",
    })
    with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
        payload = json.load(response)
    return payload.get("workflow_runs", [])


def load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True))
    os.replace(tmp, path)


def summarize(run: dict) -> str:
    return (f"{run.get('name', '?')} #{run.get('run_number', '?')}"
            f" ({run.get('head_branch', '?')}) — {run.get('html_url', '')}")


def classify(runs: list[dict], state: dict) -> tuple[list[dict], list[dict], dict]:
    """(새 실패, 복구됨, 새 상태). 이미 알린 실행은 다시 알리지 않는다."""
    seen = set(state.get("seen_run_ids", []))
    last_conclusion = dict(state.get("last_conclusion", {}))
    first_run = not state  # 도입 직후엔 과거를 쏟아내지 않는다

    new_failures: list[dict] = []
    recovered: list[dict] = []
    # 오래된 것부터 봐야 "실패 → 성공" 전이를 제대로 잡는다(API는 최신순으로 준다).
    for run in sorted(runs, key=lambda r: r.get("id", 0)):
        run_id = run.get("id")
        conclusion = run.get("conclusion")
        name = run.get("name", "?")
        if run_id is None or conclusion in (None, "cancelled", "skipped"):
            continue
        previous = last_conclusion.get(name)
        if run_id not in seen and not first_run:
            if conclusion in FAILURE_CONCLUSIONS:
                new_failures.append(run)
            elif conclusion == "success" and previous in FAILURE_CONCLUSIONS:
                recovered.append(run)
        seen.add(run_id)
        last_conclusion[name] = conclusion

    new_state = {
        "seen_run_ids": sorted(seen)[-KEEP_SEEN:],
        "last_conclusion": last_conclusion,
    }
    return new_failures, recovered, new_state


def build_message(new_failures: list[dict], recovered: list[dict]) -> str:
    lines: list[str] = []
    if new_failures:
        lines.append(f"[GitHub] 워크플로 실패 {len(new_failures)}건")
        lines += [f"- {summarize(run)}" for run in new_failures[:6]]
        if len(new_failures) > 6:
            lines.append(f"  … 외 {len(new_failures) - 6}건")
    if recovered:
        if lines:
            lines.append("")
        lines.append(f"[GitHub] 복구됨 {len(recovered)}건")
        lines += [f"- {summarize(run)}" for run in recovered[:6]]
    return "\n".join(lines)


def default_alert(message: str) -> None:
    script = Path(__file__).resolve().parent / "send_telegram_alert.sh"
    if not script.is_file():
        print("send_telegram_alert.sh 가 없어 알림을 보내지 못함", file=sys.stderr)
        return
    result = subprocess.run(["bash", str(script), message], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"텔레그램 알림 전송 실패: {result.stderr.strip()[:200]}", file=sys.stderr)


def run_watch(
    repo: str = REPO,
    state_path: Path | None = None,
    *,
    dry_run: bool = False,
    limit: int = FETCH_COUNT,
    alert: Callable[[str], None] | None = None,
    fetch: Callable[[str, int], list[dict]] | None = None,
) -> dict:
    """한 번 확인한다. 반환: {"new_failures": n, "recovered": n, "message": str|None, "error": str|None}

    alert/fetch를 기본 인자로 묶지 않고 호출 시점에 모듈 전역에서 찾는다 — 그래야 테스트나 VM에서 디버깅할 때
    monkeypatch가 실제로 먹는다(기본 인자는 import 시점에 고정돼 갈아끼워도 무시된다).
    """
    alert = alert or default_alert
    fetch = fetch or fetch_runs
    path = state_path or STATE_PATH
    outcome = {"new_failures": 0, "recovered": 0, "message": None, "error": None, "first_run": not load_state(path)}
    try:
        runs = fetch(repo, limit)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        # API 일시 장애로 매번 알림을 보내면 그게 더 소음이다 — 저널에만 남기고 조용히 넘어간다.
        outcome["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return outcome

    state = load_state(path)
    new_failures, recovered, new_state = classify(runs, state)
    outcome["new_failures"], outcome["recovered"] = len(new_failures), len(recovered)

    if new_failures or recovered:
        message = build_message(new_failures, recovered)
        outcome["message"] = message
        if not dry_run:
            alert(message)
    if not dry_run:
        save_state(path, new_state)
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="알림을 보내지 않고 상태도 저장하지 않는다")
    parser.add_argument("--limit", type=int, default=FETCH_COUNT, help=f"한 번에 확인할 실행 수 (기본 {FETCH_COUNT})")
    args = parser.parse_args(argv)

    outcome = run_watch(dry_run=args.dry_run, limit=args.limit)
    if outcome["error"]:
        print(f"GitHub API 조회 실패(이번 회차 건너뜀): {outcome['error']}", file=sys.stderr)
        return 0  # 일시 장애로 타이머가 실패 상태로 남지 않게 한다
    if outcome["first_run"]:
        print("첫 실행 — 현재 상태만 기록하고 과거 실패는 알리지 않음")
    elif outcome["message"]:
        print(outcome["message"])
    else:
        print("새 실패/복구 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
