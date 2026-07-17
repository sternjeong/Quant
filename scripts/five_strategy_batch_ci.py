"""GitHub Actions에서 1회 실행되는 5개 활성 전략 배치 미세튜닝 (2026-07-17, 사용자 긴급 요청).

원래 코드스페이스 로컬에서 9시간(540분) 동안 돌리려던 .tuning_runs/five_strategy_batch/run.py를
GitHub Actions로 옮긴 버전 - GitHub Actions 호스티드 러너는 잡 하나가 최대 6시간(360분)까지만
허용되므로 전략당 예산을 108분 -> 72분(360/5)으로 줄였다.

CI는 매 실행마다 빈 DB로 시작한다(data/*.db는 gitignore 대상) - 로컬 UI로 만든 5개 전략(id
14/15/16/17/20)은 그 로컬 DB에만 있어 CI에는 없다. scripts/seed_five_active_strategies.json
(로컬 전략들을 그대로 export해 커밋해둔 것)으로 이름 기준 시드-또는-조회한다.

결과 저장 방식도 nightly_tuning_ci.py와 같은 이유로 다르다: CI에서 Strategy 테이블에 저장해도
잡이 끝나면 DB 자체가 사라지므로, 최종 선정된 상위 10개를 JSON으로 내보내
data/five_strategy_batch_top10.json에 커밋한다 - 코드스페이스가 다시 켜지면
scripts/import_five_strategy_batch_results.py로 이 JSON을 로컬 Strategy 라이브러리에
반영한다(다음 단계, 아직 미실행).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.db import get_session, init_db  # noqa: E402
from core.models import Strategy  # noqa: E402
from core.strategy_tuning import get_top_tuning_results, run_and_save_tuning, sample_universe  # noqa: E402

SEED_PATH = PROJECT_ROOT / "scripts" / "seed_five_active_strategies.json"
REPORT_PATH = PROJECT_ROOT / "TUNING_BATCH_REPORT_2026-07-17.md"
TOP10_JSON_PATH = PROJECT_ROOT / "data" / "five_strategy_batch_top10.json"
LOG_PATH = PROJECT_ROOT / "five_strategy_batch_ci.log"

TOTAL_BUDGET_MINUTES = 360  # GitHub Actions 호스티드 러너 잡 하드 리밋(6시간)
UNIVERSE_N = 100
LOOKBACK_YEARS = 5
INTENSITIES = ["빠름", "보통", "정밀"]
TOP_N_TO_SAVE = 10
MIN_PER_STRATEGY = 2


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)


def _seed_strategies() -> list[int]:
    """seed_five_active_strategies.json의 전략을 이름으로 찾고, 없으면 새로 만든다."""
    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    ids: list[int] = []
    with get_session() as session:
        for seed in seeds:
            strategy = session.query(Strategy).filter(Strategy.name == seed["name"]).first()
            if strategy is None:
                strategy = Strategy(
                    name=seed["name"],
                    indicator_config=json.dumps(seed["indicator_config"], ensure_ascii=False),
                    source=seed.get("source"),
                    description=seed.get("description"),
                )
                session.add(strategy)
                session.flush()
                _log(f"전략 '{strategy.name}' 시드에서 신규 생성 (id={strategy.id})")
            ids.append(strategy.id)
    return ids


def _tune_one_strategy(strategy_id: int, per_strategy_budget_minutes: float) -> None:
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        base_config = json.loads(strategy.indicator_config)
        strategy_name = strategy.name

    budget_seconds = per_strategy_budget_minutes * 60
    _log(f"'{strategy_name}'(#{strategy_id}) 시작 (예산 {per_strategy_budget_minutes:.0f}분)")
    end_date = date.today()
    start_date = end_date - timedelta(days=365 * LOOKBACK_YEARS)
    seed_base = int(date.today().strftime("%Y%m%d")) * 100 + strategy_id * 1000

    t0 = time.time()
    iteration = 0
    while time.time() - t0 < budget_seconds:
        intensity = INTENSITIES[iteration % len(INTENSITIES)]
        seed = seed_base + iteration
        _log(f"  [{strategy_name}] 반복 {iteration + 1} - 강도={intensity}, 시드={seed}")
        try:
            tickers_df = sample_universe(UNIVERSE_N, random_seed=seed)
            run_id = run_and_save_tuning(
                base_config, UNIVERSE_N, start_date.isoformat(), end_date.isoformat(),
                intensity=intensity, base_strategy_id=strategy_id, tickers_df=tickers_df,
            )
            _log(f"    -> run_id={run_id} 저장 완료 ({time.time() - t0:.0f}s 경과)")
        except Exception as e:  # noqa: BLE001 - 반복 하나의 실패가 전체를 막지 않게 함
            _log(f"    -> 반복 실패: {e!r}")
        iteration += 1

    _log(f"'{strategy_name}'(#{strategy_id}) 예산 소진, 총 {iteration}회 반복")


def _select_and_export(strategy_ids: list[int]) -> None:
    _log("=== 최종 집계 시작 ===")
    candidates: list[dict] = []
    for strategy_id in strategy_ids:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            base_name = strategy.name
        top_for_strategy = get_top_tuning_results(strategy_id, limit=50)
        for r in top_for_strategy:
            r["_base_strategy_id"] = strategy_id
            r["_base_strategy_name"] = base_name
        candidates.append({"strategy_id": strategy_id, "base_name": base_name, "results": top_for_strategy})

    selected: list[dict] = []
    selected_keys: set[tuple] = set()
    for c in candidates:
        for r in c["results"][:MIN_PER_STRATEGY]:
            key = (r["_base_strategy_id"], r["ticker"], r["trained_regime"], r["run_id"])
            if key not in selected_keys:
                selected.append(r)
                selected_keys.add(key)

    all_results = [r for c in candidates for r in c["results"]]
    all_results.sort(key=lambda r: r["excess_return"], reverse=True)
    for r in all_results:
        if len(selected) >= TOP_N_TO_SAVE:
            break
        key = (r["_base_strategy_id"], r["ticker"], r["trained_regime"], r["run_id"])
        if key not in selected_keys:
            selected.append(r)
            selected_keys.add(key)

    selected.sort(key=lambda r: r["excess_return"], reverse=True)
    selected = selected[:TOP_N_TO_SAVE]

    export = []
    for rank, r in enumerate(selected, start=1):
        name = (
            f"[미세튜닝#{rank}] {r['_base_strategy_name']} - {r['ticker']} "
            f"({r['trained_regime']}, {r['style_type'] or '-'})"
        )
        desc = (
            f"6시간 GitHub Actions 배치 미세튜닝(2026-07-17) 결과 {rank}위. 원본 전략 "
            f"'{r['_base_strategy_name']}'(#{r['_base_strategy_id']})의 국면별({r['trained_regime']}) "
            f"학습 config를 종목 {r['ticker']}에 맞춰 튜닝. test 구간 초과수익 {r['excess_return']}%p, "
            f"강도={r.get('run_intensity')}, 백본변경={'예' if r.get('backbone_changed') else '아니오'}."
        )
        export.append(
            {
                "rank": rank,
                "name": name,
                "description": desc,
                "source": "GitHub Actions 6시간 배치 미세튜닝",
                "indicator_config": r["tuned_config"],
                "base_strategy_id": r["_base_strategy_id"],
                "base_strategy_name": r["_base_strategy_name"],
                "ticker": r["ticker"],
                "trained_regime": r["trained_regime"],
                "excess_return": r["excess_return"],
            }
        )

    TOP10_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOP10_JSON_PATH.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"상위 {len(export)}개 JSON 저장: {TOP10_JSON_PATH}")

    lines = [
        "# 6시간 GitHub Actions 배치 미세튜닝 결과 리포트 (2026-07-17)",
        "",
        f"활성 전략 5개(id {strategy_ids})를 각각 {TOTAL_BUDGET_MINUTES // len(strategy_ids)}분씩, "
        f"총 {TOTAL_BUDGET_MINUTES}분(6시간) 동안 GitHub Actions에서 반복 미세튜닝했습니다 "
        "(코드스페이스를 꺼야 해서 로컬 9시간 계획에서 전환).",
        "",
        "## 전략별 누적 결과 건수",
        "",
        "| 전략 | 결과 건수 |",
        "|---|---|",
    ]
    for c in candidates:
        lines.append(f"| #{c['strategy_id']} {c['base_name']} | {len(c['results'])}건 |")

    lines += [
        "",
        "## 선정된 상위 10개 (data/five_strategy_batch_top10.json에도 저장됨)",
        "",
        "**코드스페이스를 다시 켜면 `python scripts/import_five_strategy_batch_results.py`로 이 JSON을 "
        "실제 전략 라이브러리에 반영해야 합니다** (GitHub Actions의 DB는 잡이 끝나면 사라지므로 여기 "
        "JSON으로만 남아있음).",
        "",
        "| 순위 | 이름 | 초과수익(%p) |",
        "|---|---|---|",
    ]
    for e in export:
        lines.append(f"| {e['rank']} | {e['name']} | {e['excess_return']:+.2f} |")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"리포트 저장: {REPORT_PATH}")


def main() -> None:
    init_db()
    strategy_ids = _seed_strategies()
    per_strategy_budget = TOTAL_BUDGET_MINUTES / len(strategy_ids)
    for strategy_id in strategy_ids:
        _tune_one_strategy(strategy_id, per_strategy_budget)
    _select_and_export(strategy_ids)
    _log("=== 전체 완료 ===")


if __name__ == "__main__":
    main()
