"""GitHub Actions에서 매일 밤(00:05 KST경) 실행되는 야간 미세튜닝 잡 — CI 전용 버전.

scheduler/run_scheduler.py::strategy_nightly_tuning_job()과 튜닝 로직(core.strategy_tuning.
run_and_save_tuning 반복 호출)은 동일하지만, 실행 환경이 근본적으로 다르다:

- GitHub Actions 러너는 잡이 끝나면 디스크가 통째로 사라지는 휘발성 환경이다. 로컬 스케줄러처럼
  같은 SQLite에 영원히 이력을 쌓는 방식이 안 통한다 — 그래서 매 실행마다 결과를 저장소에 커밋된
  JSON(data/nightly_tuning_leaderboard.json)으로 내보내고, 다음 실행 시작 시 그 파일을 다시 읽어
  이번에 새로 나온 결과와 합친 뒤 상위 K개만 남겨 다시 저장한다 — JSON 파일 자체가 곧 "누적 이력"
  역할을 한다(워크플로가 git commit + push까지 담당).
- "한국시간 00:05~04:00까지" 같은 벽시계 기준 대신, 실행 시작 후 고정된 예산(분) 동안 반복한다 —
  GitHub Actions의 스케줄 트리거 자체가 몇 분 정도 지연될 수 있어(공식적으로 보장 안 됨) 정각 기준
  컷오프가 의미가 없다.

app/pages/13_야간_미세튜닝_리더보드.py가 로컬 DB에 쌓인 결과가 없을 때(Streamlit Community Cloud
배포본처럼) 이 JSON 파일을 폴백으로 읽도록 되어 있어, 로컬 스케줄러를 띄우지 않아도 클라우드
배포본에서 결과를 볼 수 있게 된다.
"""

from __future__ import annotations

import json
import os
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
from core.strategy_tuning import get_top_tuning_results, run_and_save_tuning, sample_universe  # noqa: E402

_SEED_STRATEGY_PATH = PROJECT_ROOT / "scripts" / "seed_strategy_3.json"
_UNIVERSE_N = 100
_LOOKBACK_YEARS = 5
_INTENSITIES = ["빠름", "보통", "정밀"]
_LEADERBOARD_PATH = PROJECT_ROOT / "data" / "nightly_tuning_leaderboard.json"
_KEEP_TOP_K = 50
_DEFAULT_BUDGET_MINUTES = 300  # GitHub Actions 잡 하드 리밋(6시간)보다 넉넉히 짧게


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


def main() -> None:
    init_db()
    _refresh_macro_cache()

    strategy_id, base_config = _get_or_seed_strategy()

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
            )
            print(f"  -> run_id={run_id} 저장 완료 ({time.time() - t0:.0f}s 경과)", flush=True)
        except Exception as e:  # noqa: BLE001 - 반복 하나의 실패가 나머지를 막지 않게 함
            print(f"  -> 반복 실패: {e!r}", flush=True)
        iteration += 1

    print(f"총 {iteration}회 반복, {time.time() - t0:.0f}초 소요", flush=True)

    new_results = get_top_tuning_results(strategy_id, limit=_KEEP_TOP_K)
    existing = _load_existing_leaderboard()
    merged = _merge_and_truncate(existing, new_results)

    _LEADERBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LEADERBOARD_PATH.write_text(json.dumps(merged, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    print(f"리더보드 저장 완료: {_LEADERBOARD_PATH} (기존 {len(existing)}건 + 신규 {len(new_results)}건 -> 상위 {len(merged)}건)", flush=True)


if __name__ == "__main__":
    main()
