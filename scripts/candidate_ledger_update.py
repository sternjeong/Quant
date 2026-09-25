#!/usr/bin/env python3
"""RES-01 후보 shadow 원장: 아직 확정되지 않은 forward 결과를 채우고 요약을 출력한다.

- core.candidate_ledger.update_forward_outcomes(as_of) 를 실행한다(가격은 core.market_data 캐시 정책 사용).
- 이어서 채택 vs 보류/거절 요약(주 horizon 20거래일 1개 + 진단 horizon)을 출력한다. --no-report 로 생략.
- 관측 전용이다. 주문 경로를 호출하지 않는다. 같은 update_forward_outcomes() 는 스케줄러의
  candidate_ledger_outcome_update_job(매일 00:28 KST)이 매일 돌리므로, 이 스크립트는 수동 재실행·요약 확인용이다.
- 출력 수치는 성과·승률 개선의 증거가 아니다. '미입증'이 기본 판정이다(자세한 규칙: docs/CANDIDATE_LEDGER_SPEC.md).

사용 예:
    python scripts/candidate_ledger_update.py                      # 오늘 기준 갱신 + 요약
    python scripts/candidate_ledger_update.py --as-of 2026-09-30 --strategy-version stock_discovery/v2
    python scripts/candidate_ledger_update.py --no-report --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import candidate_ledger as cl  # noqa: E402


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.2f}%"


def _num(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def format_summary(summary: dict) -> list[str]:
    lines = [
        f"[갱신] as_of={summary['as_of']} horizons={summary['horizons']}",
        f"  검토한 후보 {summary['n_decisions_examined']}건 (이미 종결 {summary['skipped_terminal']}건 건너뜀), "
        f"가격 조회 티커 {summary['tickers_fetched']}개",
        f"  이번 실행 기록: 확정 {summary['finalized']} / 결측 확정 {summary['missing']} / 대기 {summary['pending']}",
    ]
    if summary["by_reason"]:
        lines.append("  사유별: " + ", ".join(f"{k}={v}" for k, v in sorted(summary["by_reason"].items())))
    for err in summary["errors"]:
        lines.append(f"  [가격 조회 오류] {err}")
    return lines


def _format_eval(rep: dict) -> list[str]:
    tag = "주 검정" if rep["role"] == "primary" else "진단 전용(다중검정 대상, 판정 불가)"
    g = rep["groups"]
    sel, rest, base = g["selected"], g["rest"], g["random_baseline_expected"]
    inc = (rep["incremental"] or {}).get("selected_minus_random")
    lines = [
        f"[{rep['horizon_days']}거래일 · {tag}] 대상={rep['target']} 비용={rep['cost_scenario']}",
        f"  후보 {sum(rep['n_decisions'].values())}건 {rep['n_decisions']} / 결과 결측 {rep['n_missing_outcome']} "
        f"(결측률 {_pct(rep['missing_outcome_rate'])})",
        f"  선택률 {_pct(rep['coverage'])} | 채택 n={sel['n']} 기대값 {_pct(sel['mean'])} 승률 {_pct(sel['win_rate'])} "
        f"최대손실 {_pct(sel['max_loss'])} 손익비 {_num(sel['profit_factor'])}",
        f"  보류·거절 n={rest['n']} 기대값 {_pct(rest['mean'])} 승률 {_pct(rest['win_rate'])} "
        f"(놓친 기회 비용 = 평균 {_pct(rep['missed_opportunity']['mean_excess'])})",
        f"  동일 선택률 무작위 보류 기준선(기대) 기대값 {_pct(base['mean'])} 승률 {_pct(base['win_rate'])}",
    ]
    if inc:
        lines.append(f"  채택-무작위 증분 {_pct(inc['estimate'])} 95%CI [{_pct(inc['ci_low'])}, {_pct(inc['ci_high'])}] "
                     f"(종목 군집 {inc['n_ticker_clusters']}, 날짜 블록 {inc['n_date_blocks']}, 시드 {inc['seed']})")
    for w in rep["warnings"]:
        lines.append(f"  [경고] {w}")
    lines.append(f"  판정: {rep['verdict']} (사유: {', '.join(rep['verdict_reasons']) or '없음'}) "
                 "— 자동 채택/폐기 아님")
    return lines


def format_report(report: dict) -> list[str]:
    lines = ["", f"[요약 리포트] {report['ledger_version']} strategy_version={report['strategy_version'] or '전체'}"]
    lines += _format_eval(report["primary"])
    for d in report["diagnostics"]:
        lines += _format_eval(d)
    lines += ["", report["disclaimer"]]
    return lines


def main(argv=None, *, price_provider=None, session=None) -> int:
    p = argparse.ArgumentParser(description="RES-01 후보 shadow 원장 forward 결과 갱신 + 요약")
    p.add_argument("--as-of", default=None, help="이 날짜까지의 가격만 사용(YYYY-MM-DD, 기본 오늘)")
    p.add_argument("--strategy-version", default=None, help="특정 전략 버전만 갱신/요약")
    p.add_argument("--horizons", default=",".join(str(h) for h in cl.ALL_HORIZONS), help="쉼표로 구분한 거래일 horizon")
    p.add_argument("--no-report", action="store_true", help="요약 리포트 생략(갱신만)")
    p.add_argument("--n-boot", type=int, default=cl.DEFAULT_N_BOOT, help="군집 부트스트랩 반복 수")
    p.add_argument("--json", action="store_true", help="사람이 읽는 출력 대신 JSON 출력")
    args = p.parse_args(argv)

    horizons = tuple(int(x) for x in args.horizons.split(",") if x.strip())
    summary = cl.update_forward_outcomes(
        args.as_of, price_provider=price_provider, session=session, horizons=horizons,
        strategy_version=args.strategy_version)
    report = None
    if not args.no_report:
        report = cl.build_ledger_report(
            session=session, strategy_version=args.strategy_version, horizons=horizons, n_boot=args.n_boot)

    if args.json:
        print(json.dumps({"update": summary, "report": report}, ensure_ascii=False, default=str, indent=2))
    else:
        print("\n".join(format_summary(summary)))
        if report is not None:
            print("\n".join(format_report(report)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
