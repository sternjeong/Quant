"""GitHub Actions에서 매일 00:00 KST 직후 실행되는 시장 국면/섹터 강도/코스톨라니 스냅샷 사전계산.

scheduler/run_scheduler.py::market_snapshot_job()과 계산 로직은 동일하지만(S&P500 유니버스 기반
시장 국면 + 섹터/테마 강도 + 코스톨라니 달걀 국면), 실행 환경이 다르다:

- market_snapshot_job()은 상시 서버(Oracle VM 등)에서 로컬 SQLite에 매일 새 행으로 쌓는다. 이
  프로젝트는 아직 그 VM을 확보하지 못했다(2026-07-21, Oracle Always Free A1.Flex가 인기 리전
  capacity 부족으로 대기 중) — 그동안은 Streamlit Community Cloud 배포본이 상시 프로세스 없이
  돌아가므로, 로컬 DB가 항상 비어 있어 사용자가 페이지를 열 때마다 무거운 실시간 계산(S&P500 전종목
  조회)이 매번 돌아 로딩이 느렸다.
- 그래서 scripts/nightly_tuning_ci.py(야간 튜닝 리더보드)와 동일한 패턴으로, GitHub Actions
  러너에서 계산한 결과를 저장소에 커밋된 JSON(data/market_regime_snapshot_ci.json,
  data/theme_strength_snapshot_ci.json, data/kostolany_cycle_snapshot_ci.json)으로 남긴다.
  core.market_regime/core.sector_strength/core.kostolany_cycle의 get_latest_*_snapshot()이 로컬
  DB와 이 JSON 중 더 최신인 쪽을 반환하도록 폴백을 추가해뒀으므로, 나중에 Oracle VM이 붙어 로컬
  스케줄러가 매일 새 DB 행을 쌓기 시작하면 자동으로 그쪽이 우선하게 된다(이관 작업 불필요).
- GitHub Actions 러너는 잡이 끝나면 디스크가 사라지는 휘발성 환경이라 "누적 이력"이 아니라 최신
  스냅샷 하나만 덮어쓰면 된다(리더보드처럼 병합할 필요 없음).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.kostolany_cycle import compute_theme_cycle_phases, get_market_cycle_phase  # noqa: E402
from core.market_regime import get_market_regime_snapshot  # noqa: E402
from core.screener import get_universe  # noqa: E402
from core.sector_strength import compute_theme_strength  # noqa: E402

_REGIME_PATH = PROJECT_ROOT / "data" / "market_regime_snapshot_ci.json"
_THEME_STRENGTH_PATH = PROJECT_ROOT / "data" / "theme_strength_snapshot_ci.json"
_KOSTOLANY_PATH = PROJECT_ROOT / "data" / "kostolany_cycle_snapshot_ci.json"
_ALL_PATHS = (_REGIME_PATH, _THEME_STRENGTH_PATH, _KOSTOLANY_PATH)


def _run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)


def _commit_and_push(message: str) -> None:
    _run_git("config", "user.name", "github-actions[bot]")
    _run_git("config", "user.email", "github-actions[bot]@users.noreply.github.com")
    _run_git("add", *[str(p.relative_to(PROJECT_ROOT)) for p in _ALL_PATHS])

    if _run_git("diff", "--cached", "--quiet").returncode == 0:
        print("변경 없음, 커밋 스킵", flush=True)
        return

    commit = _run_git("commit", "-m", message)
    if commit.returncode != 0:
        print(f"커밋 실패: {commit.stderr.strip()}", flush=True)
        return

    ref_name = os.environ.get("GITHUB_REF_NAME", "main")
    push = _run_git("push", "origin", f"HEAD:{ref_name}")
    if push.returncode == 0:
        return

    print(f"푸시 거절, fetch+rebase 후 재시도: {push.stderr.strip()}", flush=True)
    _run_git("fetch", "origin", ref_name)
    if _run_git("rebase", f"origin/{ref_name}").returncode != 0:
        print("rebase 실패, 이번 실행 커밋은 로컬에만 남음", flush=True)
        _run_git("rebase", "--abort")
        return
    if _run_git("push", "origin", f"HEAD:{ref_name}").returncode != 0:
        print("재시도 푸시도 실패", flush=True)


def main() -> None:
    # DB의 computed_at(datetime.utcnow(), naive)과 그대로 비교 가능하도록 naive UTC로 저장한다
    # (core.market_regime.get_latest_market_regime_snapshot 등의 폴백 비교 로직 참고).
    now_iso = datetime.utcnow().isoformat()

    print("S&P500 유니버스 조회 중...", flush=True)
    tickers = get_universe()["Symbol"].tolist()
    if not tickers:
        print("S&P500 유니버스를 가져오지 못했습니다. 스냅샷 계산을 건너뜁니다.", flush=True)
        return

    print("시장 국면 계산 중...", flush=True)
    regime_snapshot = get_market_regime_snapshot(tickers)
    regime_snapshot["computed_at"] = now_iso
    _REGIME_PATH.write_text(json.dumps(regime_snapshot, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    print(f"  -> {regime_snapshot['regime']} (종합 {regime_snapshot['total_score']:+.0f}점)", flush=True)

    print("섹터/테마 강도 계산 중...", flush=True)
    theme_df = compute_theme_strength()
    theme_strength_snapshot = {
        "theme_scores": json.loads(theme_df.to_json(orient="records", force_ascii=False)),
        "computed_at": now_iso,
    }
    _THEME_STRENGTH_PATH.write_text(
        json.dumps(theme_strength_snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  -> {len(theme_df)}개 테마 계산 완료", flush=True)

    print("코스톨라니 달걀 국면 계산 중...", flush=True)
    market_phase = get_market_cycle_phase()
    theme_cycle_df = compute_theme_cycle_phases()
    kostolany_snapshot = {
        "market_phase": market_phase,
        "theme_phases": json.loads(theme_cycle_df.to_json(orient="records", force_ascii=False)),
        "computed_at": now_iso,
    }
    _KOSTOLANY_PATH.write_text(json.dumps(kostolany_snapshot, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    cycle_label = market_phase["phase"] if market_phase else "N/A"
    print(f"  -> 시장={cycle_label}, {len(theme_cycle_df)}개 테마 계산 완료", flush=True)

    _commit_and_push("chore: nightly market regime + sector strength + kostolany snapshot update")


if __name__ == "__main__":
    main()
