"""GitHub Actions에서 매일 밤(00:05 KST경) 실행되는 야간 미세튜닝 잡 — CI 전용 버전.

scheduler/run_scheduler.py::strategy_nightly_tuning_job()과 튜닝 로직(core.strategy_tuning.
run_and_save_tuning 반복 호출)은 동일하지만, 실행 환경이 근본적으로 다르다:

- GitHub Actions 러너는 잡이 끝나면 디스크가 통째로 사라지는 휘발성 환경이다. 로컬 스케줄러처럼
  같은 SQLite에 영원히 이력을 쌓는 방식이 안 통한다 — 그래서 매 실행마다 결과를 저장소에 커밋된
  JSON(data/nightly_tuning_leaderboard.json)으로 내보내고, 다음 실행 시작 시 그 파일을 다시 읽어
  이번에 새로 나온 결과와 합친 뒤 상위 K개만 남겨 다시 저장한다 — JSON 파일 자체가 곧 "누적 이력"
  역할을 한다.
- "한국시간 00:05~04:00까지" 같은 벽시계 기준 대신, 실행 시작 후 고정된 예산(분) 동안 반복한다 —
  GitHub Actions의 스케줄 트리거 자체가 몇 분 정도 지연될 수 있어(공식적으로 보장 안 됨) 정각 기준
  컷오프가 의미가 없다.

scheduler/run_scheduler.py::strategy_nightly_tuning_job()과 마찬가지로 2026-07-21부터 매 반복
max_holding_days=_SWING_MAX_HOLDING_DAYS(SPEC 15절, 126거래일≈6개월)를 항상 넘겨 스윙 트레이딩
보유기간 상한 하에서 탐색/검증한다(사용자가 스스로를 스윙 트레이더로 확정 — SPEC 15.1절).

**반복마다 커밋+푸시(SPEC 16절, 2026-07-21)**: 과거에는 모든 반복이 끝난 뒤 딱 한 번만 리더보드를
커밋했는데, 오라클 VM 등 상시 서버 없이 GitHub Actions 하나에만 의존하는 지금 상태에서는 이게 치명적
결함이었다 — 한 반복(특히 "정밀" 강도)이 오래 걸려 잡 예산(budget_minutes)을 넘기면 GitHub Actions의
잡 하드 타임리밋(.github/workflows/nightly_tuning.yml의 timeout-minutes)에 걸려 잡 전체가 강제
종료되는데, 그 시점엔 아직 한 번도 커밋을 안 한 상태라 그날 밤 계산한 모든 반복 결과가 통째로
유실됐다(2026-07-17~19 사흘 연속 발생, 리더보드가 3.65일간 정체됐던 원인). 이제는 반복 하나가 끝날
때마다 즉시 커밋+푸시하므로, 잡이 언제 강제 종료되든 그 직전 반복까지의 결과는 이미 원격에 안전하게
저장돼 있다 — 유실 구간이 "그날 밤 전체"에서 "죽는 순간 진행 중이던 반복 1개"로 줄어든다.

app/pages/1_전략_스튜디오.py("🌙 야간 미세튜닝 리더보드" 탭)가 로컬 DB에 쌓인 결과가 없을 때(Streamlit Community Cloud
배포본처럼) 이 JSON 파일을 폴백으로 읽도록 되어 있어, 로컬 스케줄러를 띄우지 않아도 클라우드
배포본에서 결과를 볼 수 있게 된다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.db import get_session, init_db  # noqa: E402
from core.fred_data import CACHE_DIR as FRED_CACHE_DIR, DEFAULT_INDICATORS, _cache_file, get_series  # noqa: E402
from core.models import Strategy  # noqa: E402
from core.strategy_tuning import (  # noqa: E402
    _SWING_MAX_HOLDING_DAYS,
    get_top_tuning_results,
    run_and_save_tuning,
    sample_universe,
)

_SEED_STRATEGY_PATH = PROJECT_ROOT / "scripts" / "seed_strategy_3.json"
_UNIVERSE_N = 100
_LOOKBACK_YEARS = 5
_INTENSITIES = ["빠름", "보통", "정밀"]
_LEADERBOARD_PATH = PROJECT_ROOT / "data" / "nightly_tuning_leaderboard.json"
_KEEP_TOP_K = 50
# GitHub Actions 잡 하드 리밋(.github/workflows/nightly_tuning.yml의 timeout-minutes=350)보다
# 넉넉히 짧게 잡는다 — 예산 체크는 반복 "시작 전"에만 이뤄지므로, 여유가 너무 작으면 마지막 반복
# 하나가 길어질 때 하드 리밋에 그대로 부딪힐 수 있다(2026-07-17~19 사흘 실제로 발생). 반복마다
# 커밋(아래 _commit_and_push)하므로 하드 킬이 나도 데이터 유실은 없지만, 그래도 예산을 줄여두면
# 하드 킬 자체가 덜 발생해 실행 로그가 "cancelled"가 아니라 "success"로 깔끔하게 끝난다.
_DEFAULT_BUDGET_MINUTES = 270


def _load_existing_leaderboard() -> list[dict]:
    if not _LEADERBOARD_PATH.exists():
        return []
    try:
        return json.loads(_LEADERBOARD_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _merge_and_truncate(existing: list[dict], new: list[dict]) -> list[dict]:
    combined = [r for r in (existing + new) if r.get("excess_return") is not None]
    combined.sort(key=lambda r: r["excess_return"], reverse=True)

    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in combined:
        key = (r.get("ticker"), str(r.get("run_created_at")), r.get("run_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
        if len(deduped) >= _KEEP_TOP_K:
            break
    return deduped


def _refresh_macro_cache() -> None:
    """FRED_API_KEY가 있으면 기본 거시지표 캐시를 강제로 최신화한다.

    get_series()의 24시간 TTL 캐시는 "오래되면 다음 호출 때 갱신"이라 그 자체로는 순서를
    보장 못 한다 - 여기서는 캐시 파일을 먼저 지우고 다시 불러와 이번 실행에서 반드시
    최신값으로 덮어쓰게 한다. 사용자가 사이트 방문 시 FRED를 직접 안 때리고 이 커밋된
    캐시를 바로 읽도록 하는 게 목적(로딩 시간 단축).
    """
    if not os.getenv("FRED_API_KEY"):
        print("FRED_API_KEY 미설정 - 거시지표 캐시 갱신 스킵", flush=True)
        return
    FRED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for series_id in DEFAULT_INDICATORS:
        _cache_file(series_id).unlink(missing_ok=True)
        series = get_series(series_id)
        print(f"  거시지표 갱신: {series_id} ({'OK' if not series.empty else '실패'})", flush=True)


def _get_or_seed_strategy() -> tuple[int, dict]:
    """대상 전략을 이름으로 찾고, 없으면(=CI의 빈 DB) 저장소에 커밋된 시드 JSON으로 생성한다.

    GitHub Actions는 매 실행마다 빈 DB로 시작한다(data/*.db는 gitignore 대상) - 로컬에서
    UI로 만든 전략(id=3)은 그 로컬 DB에만 있어 CI에는 없다. id를 하드코딩하는 대신 이름으로
    찾고, 없으면 seed_strategy_3.json(로컬 전략을 그대로 export해 커밋해둔 것)으로 만든다.
    """
    seed = json.loads(_SEED_STRATEGY_PATH.read_text(encoding="utf-8"))
    with get_session() as session:
        strategy = session.query(Strategy).filter(Strategy.name == seed["name"]).first()
        if strategy is None:
            strategy = Strategy(
                name=seed["name"],
                indicator_config=json.dumps(seed["indicator_config"], ensure_ascii=False),
                source=seed.get("source"),
                description=seed.get("description"),
            )
            session.add(strategy)
            session.commit()
            session.refresh(strategy)
            print(f"전략 '{strategy.name}' 시드에서 신규 생성 (id={strategy.id})", flush=True)
        return strategy.id, json.loads(strategy.indicator_config)


def _run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    )


def _configure_git_identity() -> None:
    """워크플로 yml의 마지막 "Commit" 스텝과 동일한 봇 아이덴티티를 이 스크립트 안에서도 설정한다.

    반복마다 직접 git commit/push를 하려면(아래 _commit_and_push) 스크립트 실행 시점에 이미
    user.name/email이 잡혀 있어야 한다 — actions/checkout은 이걸 자동으로 설정해주지 않는다.
    """
    _run_git("config", "user.name", "github-actions[bot]")
    _run_git("config", "user.email", "github-actions[bot]@users.noreply.github.com")


def _commit_and_push(message: str) -> bool:
    """리더보드/거시지표 캐시 변경분을 즉시 커밋하고 원격에 푸시한다.

    잡이 언제 하드 타임아웃으로 죽어도 "죽기 직전 마지막으로 성공한 이 호출까지"는 원격에 안전하게
    남아있도록 하는 게 목적이다(모듈 docstring 참고). 변경이 없으면(diff --cached가 비어있으면)
    조용히 스킵한다. 푸시가 거절되면(다른 워크플로/수동 커밋과 경합) 한 번 fetch+rebase 후 재시도하고,
    그래도 실패하면 다음 반복에서 다시 시도하도록 False만 반환하고 계속 진행한다(커밋 실패로 전체
    튜닝 루프를 멈추지 않음 — 로컬 파일에는 이미 최신 병합 결과가 있어 다음 반복의 병합 기준은
    안전하다).
    """
    _run_git("add", "data/nightly_tuning_leaderboard.json")
    for csv_path in FRED_CACHE_DIR.glob("*.csv"):
        _run_git("add", str(csv_path.relative_to(PROJECT_ROOT)))

    diff_check = _run_git("diff", "--cached", "--quiet")
    if diff_check.returncode == 0:
        return True  # 변경 없음

    commit_result = _run_git("commit", "-m", message)
    if commit_result.returncode != 0:
        print(f"  [git] 커밋 실패: {commit_result.stderr.strip()}", flush=True)
        return False

    ref_name = os.environ.get("GITHUB_REF_NAME", "main")
    push_result = _run_git("push", "origin", f"HEAD:{ref_name}")
    if push_result.returncode == 0:
        return True

    print(f"  [git] 푸시 거절, fetch+rebase 후 1회 재시도: {push_result.stderr.strip()}", flush=True)
    _run_git("fetch", "origin", ref_name)
    rebase_result = _run_git("rebase", f"origin/{ref_name}")
    if rebase_result.returncode != 0:
        print(f"  [git] rebase 실패, 이번 반복 커밋은 로컬에만 남음: {rebase_result.stderr.strip()}", flush=True)
        _run_git("rebase", "--abort")
        return False

    retry_result = _run_git("push", "origin", f"HEAD:{ref_name}")
    if retry_result.returncode != 0:
        print(f"  [git] 재시도 푸시도 실패: {retry_result.stderr.strip()}", flush=True)
        return False
    return True


def _save_and_push_leaderboard(strategy_id: int, message: str) -> None:
    new_results = get_top_tuning_results(strategy_id, limit=_KEEP_TOP_K)
    existing = _load_existing_leaderboard()
    merged = _merge_and_truncate(existing, new_results)

    _LEADERBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LEADERBOARD_PATH.write_text(json.dumps(merged, ensure_ascii=False, default=str, indent=2), encoding="utf-8")

    pushed = _commit_and_push(message)
    status = "커밋+푸시 완료" if pushed else "커밋 실패(다음 반복에서 재시도됨)"
    print(f"  -> 리더보드 저장: 상위 {len(merged)}건 ({status})", flush=True)


def main() -> None:
    init_db()
    _configure_git_identity()
    _refresh_macro_cache()

    strategy_id, base_config = _get_or_seed_strategy()
    # 거시지표 캐시만 갱신된 상태로도 한 번 커밋해둔다 — 아래 튜닝 루프가 시작하자마자 죽더라도
    # 이 캐시 갱신만큼은 유실되지 않게.
    _commit_and_push("chore: nightly macro cache refresh")

    budget_minutes = int(os.environ.get("NIGHTLY_TUNING_BUDGET_MINUTES", str(_DEFAULT_BUDGET_MINUTES)))
    budget_seconds = budget_minutes * 60
    print(f"전략(#{strategy_id}) 야간 미세튜닝 시작 (예산 {budget_minutes}분)", flush=True)

    end_date = date.today()
    start_date = end_date - timedelta(days=365 * _LOOKBACK_YEARS)
    seed_base = int(date.today().strftime("%Y%m%d")) * 100

    t0 = time.time()
    iteration = 0
    while time.time() - t0 < budget_seconds:
        intensity = _INTENSITIES[iteration % len(_INTENSITIES)]
        seed = seed_base + iteration
        print(f"[반복 {iteration + 1}] 탐색 강도={intensity}, 종목 표본 시드={seed}", flush=True)
        try:
            tickers_df = sample_universe(_UNIVERSE_N, random_seed=seed)
            run_id = run_and_save_tuning(
                base_config, _UNIVERSE_N, start_date.isoformat(), end_date.isoformat(),
                intensity=intensity, base_strategy_id=strategy_id, tickers_df=tickers_df,
                max_holding_days=_SWING_MAX_HOLDING_DAYS,
            )
            print(f"  -> run_id={run_id} 저장 완료 ({time.time() - t0:.0f}s 경과)", flush=True)
            _save_and_push_leaderboard(
                strategy_id, f"chore: nightly tuning leaderboard update (iteration {iteration + 1}, run_id={run_id})"
            )
        except Exception as e:  # noqa: BLE001 - 반복 하나의 실패가 나머지를 막지 않게 함
            print(f"  -> 반복 실패: {e!r}", flush=True)
        iteration += 1

    print(f"총 {iteration}회 반복, {time.time() - t0:.0f}초 소요", flush=True)

    # 루프가 정상 종료된 경우에도(마지막 반복 이후 변경 없음이 보통이라 대부분 no-op) 한 번 더
    # 확인 — _commit_and_push는 변경 없으면 조용히 스킵하므로 안전.
    _save_and_push_leaderboard(strategy_id, "chore: nightly tuning leaderboard final sync")


if __name__ == "__main__":
    main()
