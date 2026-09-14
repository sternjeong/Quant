"""리서치 에이전트(B/C)가 쌓아둔 새 리포트가 일정 개수 이상이면 텔레그램으로 한 번에 알린다.

git commit/push는 절대 하지 않는다는 원칙(사용자 요청) 때문에, `analysis/` 밑에 새로 생긴
리포트 폴더는 커밋되지 않은 채(untracked) 계속 쌓인다. 매번 알리면 스팸이 되므로, 마지막으로
알린 시점 이후 새로 쌓인 개수가 ACCUMULATION_THRESHOLD 이상일 때만 알리고, 알릴 때마다
"지금까지 총 몇 개 쌓였는지" 기준선을 갱신한다(data/cache/research_agent_notify_state.json).

core/ 관례를 그대로 따른다: core.telegram_notify.send_message()가 이미 조용히 실패를 삼키므로
여기서도 예외 없이 동작한다. Streamlit에 의존하지 않는다(core/*.py와 동일 원칙 — 이 스크립트는
core/ 밖에 있지만 같은 컨벤션을 따름).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from core.telegram_notify import send_message  # noqa: E402

# core.telegram_notify는 자체적으로 .env를 로드하지 않는다(다른 core 모듈을 거쳐 간접적으로
# 로드되는 걸 우연히 기대하면 안 됨) — 이 스크립트는 단독 실행되므로 직접 로드한다.
load_dotenv(PROJECT_ROOT / ".env")

STATE_PATH = PROJECT_ROOT / "data" / "cache" / "research_agent_notify_state.json"
ACCUMULATION_THRESHOLD = 3  # 마지막 알림 이후 새 리포트 폴더가 이 개수 이상 쌓이면 알림


def _list_untracked_analysis_dirs() -> list[str]:
    """`analysis/` 바로 밑의 untracked(커밋 안 된) 최상위 폴더 이름 목록을 반환한다."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "analysis/"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True, timeout=30,
        )
    except Exception:
        return []

    dirs = set()
    for line in result.stdout.splitlines():
        if not line.startswith("??"):
            continue
        path = line[3:].strip()
        if not path.startswith("analysis/"):
            continue
        # "analysis/2026-09-15_foo/" 형태(전체 untracked 폴더) -> 최상위 폴더명만 추출
        parts = path.split("/")
        if len(parts) >= 2 and parts[1]:
            dirs.add(parts[1].rstrip("/"))
    return sorted(dirs)


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"last_notified_count": 0, "last_notified_dirs": []}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"last_notified_count": 0, "last_notified_dirs": []}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main(agent_name: str) -> None:
    current_dirs = _list_untracked_analysis_dirs()
    state = _load_state()
    last_notified_dirs = set(state.get("last_notified_dirs", []))

    new_dirs = [d for d in current_dirs if d not in last_notified_dirs]
    print(f"[notify_if_accumulated] 에이전트={agent_name}, 전체 미커밋 리포트={len(current_dirs)}개, "
          f"마지막 알림 이후 신규={len(new_dirs)}개")

    if len(new_dirs) < ACCUMULATION_THRESHOLD:
        print("[notify_if_accumulated] 아직 임계치 미달 — 알림 생략")
        return

    lines = [
        f"🔬 리서치 에이전트가 새 리포트 {len(new_dirs)}개를 쌓았습니다 (커밋 전, 검토 필요):",
        *[f"  - {d}" for d in new_dirs],
        f"총 미커밋 리포트: {len(current_dirs)}개 (analysis/ 폴더 확인 후 직접 커밋해주세요)",
    ]
    message = "\n".join(lines)
    sent = send_message(message)
    print(f"[notify_if_accumulated] 텔레그램 전송 {'성공' if sent else '실패/미설정'}")

    _save_state({"last_notified_count": len(current_dirs), "last_notified_dirs": current_dirs})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="?", help="방금 실행된 에이전트 이름(로그용)")
    args = parser.parse_args()
    main(args.agent)
