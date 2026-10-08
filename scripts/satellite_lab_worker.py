"""새틀라이트 R&D 센터 계산기 — VM 연구 실행기가 빈 실행 창에 돌린다(core.research_jobs 의 빈 창 훅).

  python scripts/satellite_lab_worker.py --out <dir> --checkpoint <dir> [--smoke]

할 일: 시작 목록·에이전트 아이디어 동결 → 현 규칙 기준선 계산 → 대기열의 후보를 하나씩 심판(core.satellite_lab).
결과는 data/satellite_lab/registry.json 에 바로 기록되므로 중간에 끊겨도 이어서 한다.
종료 코드(docs/RESEARCH_JOBS.md 계약): 0 = 대기열 비움, 3 = 시간 예산이 끝나 남은 것은 다음 창에, 그 외 = 실패.
--smoke: 합성 가격·임시 등록부로 몇 초 안에 끝까지 돌려 본다(대화 세션·Codespace 에서는 이것만).
AI 를 부르지 않고 주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import satellite_lab as sl  # noqa: E402

EXIT_DONE, EXIT_IN_PROGRESS = 0, 3
SAFETY_SECONDS = 90


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def deadline_epoch() -> float:
    raw = os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH")
    return (float(raw) if raw else time.time() + 3 * 3600) - SAFETY_SECONDS


# ---------------------------------------------------------------- 본체
def ready_agent_variant(d: Path) -> bool:
    """야간 배치가 검사·Critic 승인을 확인한 내용과 지금 폴더가 같아야 동결한다(core.satellite_lab.agent_ready)."""
    return sl.agent_ready(d)


def baseline_for(spec: dict, data: sl.LabData, split, cache_dir: Path, n: int, deadline: float):
    end = str(data.trading_days[-1].date())
    path = cache_dir / f"{sl.structure_key(spec).replace('|', '_')}__{end}__n{n}__{sl.JUDGE_VERSION.replace('/', '_')}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    base = sl.random_baseline(spec, data, split, n=n, deadline=deadline)
    if base is not None:
        sl._atomic_write(path, json.dumps(base))
    return base


def _ensure_fundamentals(data: sl.LabData, spec: dict, deadline: float, smoke: bool) -> bool:
    """재무를 쓰는 아이디어 전에 그 풀의 모든 리밸런싱일 종목 재무를 미리 받는다(SEC, 디스크 저장 — 끊겨도 이어 받음)."""
    from core import fundamentals_pit as fp

    if data.fundamentals is not None:
        return True
    if smoke:
        data.fundamentals = fp.SyntheticStore()
        return True
    tickers = set()
    for d in sl.rebalance_dates(data.trading_days, spec["portfolio"]["hold_months"]):
        tickers.update(data.pool(spec["pool"]["type"], d))
    store = fp.Store()
    res = store.prefetch(tickers, deadline=deadline - 120, log=log)
    log(f"재무 데이터 {res['done']}종목 준비, 남음 {res['left']}")
    if not res["complete"]:
        return False
    data.fundamentals = store
    return True


def run(args) -> int:
    deadline = deadline_epoch()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.smoke:
        state_dir = Path(args.checkpoint) / "smoke_state"
        price_provider, pool_provider = sl.synthetic_providers()
        variants_dir = Path(args.checkpoint) / "smoke_variants"
        n_random, start, context_path = 20, "2010-01-01", Path(args.checkpoint) / "smoke_context.md"
    else:
        state_dir, price_provider, pool_provider = sl.STATE_DIR, None, None
        variants_dir, n_random, start, context_path = sl.VARIANTS_DIR, sl.N_RANDOM, sl.LAB_START, sl.LAB_DIR / "context.md"
    cache_dir = state_dir / "baselines"

    migrated = sl.migrate_registry(state_dir)
    if migrated:
        log(f"판정 버전 {sl.JUDGE_VERSION} 로 전환 — 이전 결과는 {migrated} 에 보관, 모든 아이디어 재심판")
    frozen = sl.sync_dir(sl.SEEDS_DIR, "seed", state_dir=state_dir, log=log)
    frozen += sl.sync_dir(variants_dir, "agent", state_dir=state_dir, ready=ready_agent_variant, log=log)
    if frozen:
        log(f"동결 {len(frozen)}건: {', '.join(frozen)}")
    reg = sl.load_registry(state_dir)
    inc_entry = reg["variants"].get(sl.INCUMBENT_ID)
    if inc_entry is None:
        log("현 규칙(S-SEED-000)이 등록되지 않음")
        return 1
    todo = sl.queue(reg)[: args.max_variants] if args.max_variants else sl.queue(reg)
    pool_types = {inc_entry["spec"]["pool"]["type"]} | {v["spec"]["pool"]["type"] for v in todo}

    log(f"데이터 준비(풀 {sorted(pool_types)}, 대기 {len(todo)}건)")
    data = sl.build_data(pool_types, start=start, end=args.end, pool_provider=pool_provider,
                         price_provider=price_provider, log=log)
    log(f"거래일 {len(data.trading_days)}일, 가격 {len(data.ohlcv)}종목")

    inc_spec = inc_entry["spec"]
    incumbent = sl.run_variant(inc_spec, inc_spec["signal"]["params_grid"][0],
                               sl.load_signal(inc_entry["signal_code"]), data)
    split = sl.holdout_split(incumbent["returns"].index)
    base = baseline_for(inc_spec, data, split, cache_dir, n_random, deadline)
    if base is None:
        log("시간 예산 소진(현 규칙 무작위 기준선 계산 중) — 다음 창에 이어서")
        return EXIT_IN_PROGRESS
    report = sl.incumbent_report(incumbent, base)
    report["computed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["latest_picks"] = incumbent["schedule"][-1] if incumbent["schedule"] else None
    with sl.edit_registry(state_dir) as r:
        r["incumbent"] = report
        r["variants"][sl.INCUMBENT_ID]["status"] = "reference"
    log(f"현 규칙: IS 샤프 {report['stats']['is'].get('sharpe_annual')}, 무작위 대비 IS 백분위 {report['random_percentile_is']}")

    judged = 0
    for entry in todo:
        if time.time() > deadline:
            break
        spec = entry["spec"]
        if "fundamentals" in (spec.get("data") or []) and not _ensure_fundamentals(data, spec, deadline, args.smoke):
            log(f"{entry['id']}: 재무 데이터 받는 중 시간 예산 소진 — 다음 창에 이어서(받은 것은 저장됨)")
            break
        log(f"심판 시작 {entry['id']} ({sl.structure_key(spec)})")
        try:
            vbase = baseline_for(spec, data, split, cache_dir, n_random, deadline)
            if vbase is None:
                break
            reg = sl.load_registry(state_dir)
            prior = [x for v in reg["variants"].values() if v.get("result") for x in v["result"].get("trial_active_srs") or []]
            result = sl.judge_variant(spec, entry["signal_code"], data, incumbent=incumbent, baseline=vbase,
                                      cumulative_trials=reg.get("cumulative_trials", 0), prior_active_srs=prior)
            result["judged_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with sl.edit_registry(state_dir) as r:
                v = r["variants"][entry["id"]]
                v.update(status=result["verdict"], result=result, attempts=v.get("attempts", 0) + 1, error=None)
            log(f"판정 {entry['id']}: {result['verdict']} {'; '.join(result['reasons'])[:300]}")
        except Exception as exc:  # noqa: BLE001 - 한 후보의 오류가 대기열 전체를 막지 않게
            with sl.edit_registry(state_dir) as r:
                v = r["variants"][entry["id"]]
                v["attempts"] = v.get("attempts", 0) + 1
                v["error"] = f"{type(exc).__name__}: {exc}"[:500]
                if v["attempts"] >= sl.MAX_JUDGE_ATTEMPTS:
                    v["status"] = sl.STATUS_ERROR
            log(f"오류 {entry['id']}: {type(exc).__name__}: {exc}")
        judged += 1

    reg = sl.load_registry(state_dir)
    sl._atomic_write(context_path, sl.context_markdown(reg))
    remaining = len(sl.queue(reg))
    summary = {"judged_this_run": judged, "remaining": remaining, "cumulative_trials": reg.get("cumulative_trials"),
               "incumbent": reg.get("incumbent"), "leaderboard": sl.leaderboard(reg)[:20]}
    (out_dir / "status.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log(f"이번 실행 심판 {judged}건, 남은 대기 {remaining}건")
    if remaining and not args.max_variants:
        return EXIT_IN_PROGRESS
    return EXIT_DONE


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--end", default=None, help="평가 마지막 날(기본 오늘)")
    p.add_argument("--max-variants", type=int, default=0, help="이번 실행에서 심판할 최대 수(0=제한 없음)")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
