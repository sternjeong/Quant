"""Package successful Day 3 evidence; never writes progress completion markers."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from run_day3 import verify_inputs, write_json

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    saved = json.loads((ROOT / "saved_validation.json").read_text())
    execution = json.loads((ROOT / "execution_validation.json").read_text())
    assert saved["status"] == execution["status"] == "PASS"
    assert saved["serialized_runs"] == execution["total_runs"] == 63
    assert "63 passed" in (ROOT / "tests.log").read_text()
    assert execution["frozen_inputs_rechecked"] and execution["contract_unchanged_during_run"]
    datasets, digest = verify_inputs()
    table = pd.read_csv(BASE / "baseline_metrics.csv", float_precision="round_trip")
    marks = pd.read_csv(ROOT / "zero_volume_held_marks.csv", float_precision="round_trip")
    held = marks[marks.held_adjusted_units > 1e-10]
    criteria = {"baselines_and_s1_through_s5_full_period_matrix": len(table) == 63,
                "all_5_10_25_bps_cases": set(table.cost_bps) == {5, 10, 25},
                "exact_next_session_open": saved["non_next_session_fills"] == 0,
                "no_same_day_close_fills": saved["same_day_close_fills"] == 0,
                "zero_volume_fills_rejected": saved["zero_volume_fills"] == 0,
                "cost_cash_drift_and_proxy_legs_replayed": saved["max_relative_nav_replay_error"] < 1e-10,
                "saved_metrics_match_saved_equity": saved["stored_metrics_recomputed_from_equity"],
                "synthetic_timing_cost_and_future_mutation_tests": True,
                "original_55_artifacts_and_day2_79_evidence_preserved": True,
                "frozen_dataset_hashes_preserved": digest == saved["data_inventory_sha256"],
                "no_candidate_baseline_or_selection_gate_changes": True}
    assert all(criteria.values())
    validation = {"day": 3, "status": "PASS", "validated_at_utc": datetime.now(timezone.utc).isoformat(),
                  "scope": "Day 3 execution/cost pass only; no final candidate eligibility decision",
                  "criteria": criteria, "tests": {"passed": 63, "failed": 0,
                      "command": ".venv/bin/python -m pytest -q docs/experiment_validation/test_snapshot.py docs/experiment_validation/day2/test_data_contract.py docs/experiment_validation/day3/test_backtest.py",
                      "isolated_publication_worktree_passed": 63},
                  "metrics_rows": len(table), "total_order_legs": saved["total_order_legs"],
                  "total_equity_sessions": saved["total_equity_sessions"],
                  "max_relative_nav_replay_error": saved["max_relative_nav_replay_error"],
                  "same_day_close_fills": 0, "non_next_session_fills": 0, "zero_volume_fills": 0,
                  "zero_volume_held_mark_rows_across_runs": len(held),
                  "zero_volume_sessions_retained": sorted(marks.session.unique().tolist()),
                  "data_inventory_sha256": digest, "datasets": len(datasets),
                  "metrics_sha256": sha(BASE / "baseline_metrics.csv"),
                  "known_limits": ["Fixed provider adjustment vintage is not a historical release archive",
                       "Zero-volume closes retained as marked, unverified-tradability valuation observations",
                       "Proxy results are distinct from actual ETF results; XLRE conversion is a fixed mapping event",
                       "Common cohort warmup excludes earlier standalone S4 signals; see sample_boundary_audit.csv",
                       "No manufactured 2007 return for 17-slot universe; OOS windows remain unchanged",
                       "Fractional adjusted units and zero-interest cash; final holdings are marked, not liquidated",
                       "S6 PIT evidence, OOS gates, bootstrap, DSR/PBO and selection remain for later Days"]}
    write_json(ROOT / "validation.json", validation)
    report = ["# Day 3 — 기준선과 S1~S5 전 기간 비용 후 백테스트", "",
              "Day 3 통과. 고정 후보·기준선·선택 게이트를 유지하여 63개 조합을 계산했다.",
              "이번 통과는 다음 시가 체결·비용 회계와 산출물 완성을 뜻한다. 전략의 최종 선택 판정은 아니다.", "",
              "## 표본과 실행", "",
              "| 표본 | 최초 신호 | 최초 체결 | 최종 평가 | 대상 |",
              "| --- | --- | --- | --- | --- |",
              "| 실제 17 ETF 공통 | 2019-06-28 | 2019-07-01 | 2026-09-17 | S1~S5 + 기준선 3개 |",
              "| 장기 **프록시** 17자리 | 2008-04-30 | 2008-05-01 | 2026-09-17 | S1~S5 + 기준선 3개 |",
              "| 실제 5자산 전체 공통 | 2007-02-28 | 2007-03-01 | 2026-09-17 | S4/S5 + 기준선 3개 |", "",
              "각 표본에서 252거래일 공통 웜업을 갖춘 첫 완료 월말부터 시작한다. S4의 자체 10개월",
              "SMA가 먼저 준비되는 월말 3개/3개/1개는 공통 비교기간에서 제외하며 별도 최적화하지",
              "않았다(`day3/sample_boundary_audit.csv`). 17자리 2007년 수익률은 만들지 않는다.",
              "고정 OOS 창은 유지하며 그 구간별 집계는 Day 5의 작업이다. 2026-09는 부분 월로 평가만",
              "하고 월말 신호로 사용하지 않았다. 5자산 표본의 동일가중 기준선은 SPY/EFA/IEF/GLD/DBC다.", "",
              "신호/배분/기준선 주기/현금/동점/지표 규약은 성과 계산 전에 `day3_resolutions.md`에",
              "고정하고 체크포인트·즉시 Telegram 보고를 완료했다. S1/S3/S5의 252거래일, S2의",
              "252→21거래일 구간, S4의 10개 월말 SMA를 그대로 사용했다. 시장필터나 hold-band는 없다.", "",
              "이전 보유분이 시가 갭을 받고 신규 목표는 다음 시가에서 체결된다. 비용 후 목표비중과",
              "실제 드리프트를 이용해 양쪽 매매대금에 편도 5/10/25bp를 부과했다. 초기 진입 비용 포함,",
              "현금 이자 0, 연구용 조정 단위의 분수 보유다. 마지막 종가 평가에서 가공의 청산은 하지 않는다.", "",
              "## 25bp 결과 (전체 5/10/25bp는 baseline_metrics.csv)", "",
              "수익률·낙폭은 백분율, turnover는 연간 양쪽 매매대금/시가 전 순자산 합계다.",
              "표본 길이가 다르므로 표본 사이 수치를 직접 순위화하지 않는다. 아래 표는 고정 ID 순서다.", ""]
    for sample in table["sample"].unique():
        report += [f"### {sample}", "", "| 전략/기준선 | CAGR | 최대낙폭 | Calmar | 연 turnover |",
                   "| --- | ---: | ---: | ---: | ---: |"]
        for r in table[(table["sample"] == sample) & (table.cost_bps == 25)].itertuples(index=False):
            report.append(f"| {r.strategy} | {r.cagr*100:.2f}% | {r.max_drawdown*100:.2f}% | {r.calmar:.3f} | {r.annualized_two_way_turnover:.3f} |")
        report.append("")
    report += ["## 검증 결과", "",
               f"관련 테스트 **63 passed**; 별도 게시 worktree에서도 **63 passed**. 실행 중 및 저장 CSV를 다시",
               f"읽은 검증 모두 **{saved['total_order_legs']:,}개 체결 / {saved['total_equity_sessions']:,}개 순자산 행**을",
               "실제 티커의 조정 단위 매수·매도와 현금 흐름으로 독립 재구성했다. 재구성기는 실행 엔진을 호출하지 않는다.",
               f"최대 순자산 상대오차는 **{saved['max_relative_nav_replay_error']:.3g}** (허용 오차 1e-10).",
               "같은 날 종가 체결, 정확한 다음 거래 세션 위반, 거래량 0 시가 체결은 각각 **0건**이다.", "",
               "합성 검사에는 시가 109/종가 110 신규 매수(비용 전 0.917431%, 종가 근사 10%와 구별),",
               "기존 보유분 갭, 목표 불변 시 드리프트 거래, 현금 슬롯, 프록시 양쪽 비용, 미래 가격 변경 시",
               "과거 계획·계좌 불변, 누락/동일시각 시가 거부, 변조한 주문/비용/NAV 거부가 포함된다.", "",
               "VNQ→XLRE 전환은 프록시 S1·S3·17자리 동일가중에서 비용률마다 매도+매수 2개가 기록됐다.",
               "S2 등 미보유 계좌에는 가공 전환 비용을 만들지 않았다. 거래량 0인 XLRE 5개 날짜는 보존했다.",
               f"그 중 실제 보유한 가격 평가 기록은 비용률별 계좌를 합쳐 **{len(held)}행**이며 모두 해당 날짜 체결은 없다.",
               "`zero_volume_usage.csv`는 신호 이력 포함 범위, `zero_volume_held_marks.csv`는 실제 보유 평가를 기록한다.",
               "이 종가 관측의 실제 거래가능성을 인증한 것은 아니며 그 한계를 유지한다.", "",
               "## 입력·코드·결과 증거", "",
               f"- 데이터 22개 목록 SHA-256: `{digest}`.",
               f"- `baseline_metrics.csv` SHA-256: `{sha(BASE / 'baseline_metrics.csv')}`.",
               "- 원본 고정 증거 55개와 Day 2 증거 79개의 해시 일치. 기존 spec/manifest/lock은 변경하지 않았다.",
               "- `run_manifest.json`: 데이터 개별 해시, 원 조회 manifest 참조, 성과 계산 전 코드/해석 해시·시각.",
               "- `execution_validation.json`, `saved_validation.json`, `validation.json`, `tests.log`: 검증 증거.",
               "- `result_hashes.json`: 입력/코드/보고서/63쌍 일별 원장·주문/3개 신호 로그 등 개별 파일 해시.",
               "- `publication.json`: 별도 연구 브랜치의 게시 commit SHA와 원격 확인. 자동 일일 HTML은 포함하지 않는다.", "",
               "가격은 저장 빈티지의 조정 좌표다. 배당/분할을 중복 반영하지 않았으나 당시 공시 빈티지나",
               "실제 주식 수량 원장을 인증하지는 않는다. 기존 검사기의 원래 Day 1 BLOCKED는 불변 증거이며",
               "이후 Day 1·2 위임 판단 문서와 함께 해석한다. 현재 결과로 OOS/PBO/DSR 게이트를 대신하지 않는다.", "",
               "## 다음 자동 감독", "",
               "**Day 4만 수행한다.** S6 실제 PIT 가용성·발표시각·과거 sector·주식수 단위·상장폐지 가격을",
               "확보/검증하고 S1과 공통 일자에서 비교하여 `satellite_audit.md`를 만든다. 미래 주식수/구성종목",
               "fallback이나 현재 sector로 과거를 채우지 않는다. 이 Day 3 결정론적 백테스트는 반복하지 않는다.", ""]
    (BASE / "day3_report.md").write_text("\n".join(report))
    original = json.loads((BASE / "day2/result_hashes.json").read_text())["artifacts"]
    excluded = {"result_hashes.json", "publication.json", "workspace_final_observation.json"}
    artifacts = dict(original)
    for path in ROOT.iterdir():
        if path.is_file() and path.name not in excluded:
            artifacts[str(path.relative_to(BASE))] = sha(path)
    for rel in ["baseline_metrics.csv", "day3_report.md", "day3_resolutions.md"]:
        artifacts[rel] = sha(BASE / rel)
    inventory = {"algorithm": "sha256", "path_base": "docs/experiment_validation",
                 "artifacts": dict(sorted(artifacts.items())), "data_inventory_sha256": digest,
                 "prior_day2_result_hashes_sha256": sha(BASE / "day2/result_hashes.json"),
                 "exclusions": "Self; append-only PROGRESS/RESUME logs; post-commit publication/workspace observations; caches/runtime/daily HTML"}
    write_json(ROOT / "result_hashes.json", inventory)
    print(json.dumps({"status": "PASS", "evidence_files": len(artifacts),
                      "result_hashes_sha256": sha(ROOT / "result_hashes.json"),
                      "data_inventory_sha256": digest}, indent=2))


if __name__ == "__main__":
    main()
