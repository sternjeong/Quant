"""연구 실행기 스모크 작업 — 계산 없이 계약(docs/RESEARCH_JOBS.md)만 보여 주는 예제.

단계 수(--steps)를 --steps-per-run 개씩 나눠 처리한다: 체크포인트에 진행 단계를 저장하고, 이번 실행 몫을 다 하면
종료 코드 3(진행 중)으로 끝난다. 모든 단계가 끝나면 results.json·REPORT.md 를 쓰고 0 으로 끝난다.
--smoke 는 한 번에 끝까지 돈다(Codespace·대화 세션 확인용).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

EXIT_DONE, EXIT_IN_PROGRESS = 0, 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--steps-per-run", type=int, default=2)
    parser.add_argument("--out", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)

    out, ckpt = Path(args.out), Path(args.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ckpt.mkdir(parents=True, exist_ok=True)
    state_file = ckpt / "progress.json"
    done = json.loads(state_file.read_text())["done"] if state_file.exists() else 0
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or time.time() + 3600)

    ran = 0
    while done < args.steps:
        if not args.smoke and (ran >= args.steps_per_run or time.time() > deadline - 30):
            tmp = state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"done": done}))
            tmp.replace(state_file)
            print(f"checkpoint: {done}/{args.steps}")
            return EXIT_IN_PROGRESS
        done += 1  # 실제 연구라면 여기서 한 단위(예: 한 기간·한 변형)를 계산한다
        ran += 1

    verdicts = {"runner_contract": "PASS"}  # 사전 등록 판정은 코드로: 여기서는 '끝까지 왔다' 하나뿐
    (out / "results.json").write_text(json.dumps({"steps": done, "verdicts": verdicts}, ensure_ascii=False, indent=2))
    (out / "REPORT.md").write_text(f"# 실행기 스모크\n\n- 단계: {done}\n- 판정: runner_contract = PASS\n", encoding="utf-8")
    print("done")
    return EXIT_DONE


if __name__ == "__main__":
    sys.exit(main())
