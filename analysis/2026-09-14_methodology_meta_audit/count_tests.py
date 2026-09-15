"""리서치 에이전트 G(방법론 메타 감사관) — 통계적 검정 총 횟수 추정 스크립트.

이 저장소의 `analysis/*/report_data.json` 전부와 `PROGRESS.md`의 작업 1~67 서술을 근거로,
"작업(work item)" 단위가 아니라 "실제로 검정된 가설/변형" 단위로 통계적 검정 총 횟수를 두 층위로
추정한다:

  1. headline (이름이 붙은 가설/라운드 단위) — 트랙 B(No.04~10)·트랙 C(작업26~28,48)·
     트랙 D(H1~H36)·트랙D 이후 독립 라운드(작업48~49) 각각을 PROGRESS.md 서술을 직접 읽고 손으로
     집계했다(아래 TRACK_* 딕셔너리의 출처 주석 참고 — 전부 PROGRESS.md 작업 번호를 인용).
  2. granular (파라미터 스윕/위기구간/설정 조합 등 실제로 계산된 개별 비교) — report_data.json에
     저장된 win_rate(다중 설정 비교 dict)·p_value·verdict_hint 리프를 전부 순회해서 기계적으로
     집계한다(아래 scan_report_data_jsons() 참고).

두 숫자 모두 하한 추정이다: 트랙B(작업19~25)와 코스톨라니 원조 리포트(No.04)는 report_data.json
관례가 생기기 전이라 세부 스윕 값이 JSON으로 안 남아있고 PROGRESS.md 서술에만 있어 granular
집계에서는 빠져 있다(headline 집계에는 포함). macro_event_study(별도 스레드, 55개 이상의 독립
이벤트 스터디)와, core/strategy_tuning.py가 야간/온디맨드로 개별 종목마다 돌리는 순열검정
(_compute_tuning_significance)은 챔피언 전략 계보에 직접 쓰이지 않는 별개 계열이라 이 스크립트의
주 집계에서 의도적으로 제외했다 — 리포트 본문에서 "제외된 것"으로 명시하고 별도로 논한다.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 1) headline 가설/라운드 집계 (PROGRESS.md 작업 서술을 직접 읽고 손으로 집계, 출처 주석 포함)
# ---------------------------------------------------------------------------

TRACK_B_HEADLINE = {
    "no04_kostolany_baseline (사전, 작업19 이전)": 1,
    "작업19 (모멘텀로테이션 vs SPY vs 코스톨라니로테이션)": 1,
    "작업20 1라운드 (7가설: TopN/lookback/rebal빈도/필터방식/역변동성가중/레짐필터)": 7,
    "작업20 2라운드 (시장필터 축소율 0/25/50/75/100% 그리드)": 1,
    "작업20 3라운드 (강건성/하위기간 격차 재확인)": 1,
    "작업21 4라운드 (변동성타겟팅 기각 + 회전율버퍼 기각)": 2,
    "작업21 5라운드 (멀티에셋 확장 채택 + 순열검정 유의성확인, N=200, p≈0.025)": 2,
    "작업22 H18/H19/H20 (연속필터 기각/유니버스확장 채택/2008 GFC OOS)": 3,
    "작업23 H21/H22/H23 (닷컴버블/2022약세장/시그모이드필터 재기각)": 3,
    "작업24 H24 + 자기검증 재실행 + 비중상한(설계실패) + 금은오버레이": 4,
    "작업25 (point-in-time 최종 재검증, No.09 사후편향 확정)": 1,
}

TRACK_C_HEADLINE = {
    "작업26 텐베거 스크리닝 방법론(unsupported)": 1,
    "작업27 IREN 변동성모멘텀 (정적보유/모멘텀로테이션/추세추종+스탑/변동성타겟팅/강건성/대조바스켓, 6개 헤드라인 메커니즘)": 6,
    "작업28 iren_beta_alpha_hedging H1~H5": 5,
    "작업48 트랙C 부트스트랩 재감사 (audit1 IREN추세추종, audit2 베타헤지H1/BABH3)": 2,
}

TRACK_D_HEADLINE = {
    "작업29~47 Track D H1~H36 (H7은 설계만 되고 스킵됨 → 35개 실제 실행)": 35,
}

POST_TRACK_D_HEADLINE = {
    "작업48 risk_adjusted_momentum_ranking (4개 변형 + 순열검정 p=0.667)": 1,
    "작업48 synthetic_options_tail_hedge (main + otm5 민감도)": 2,
    "작업49 options_hedge_bootstrap_and_combined_system (bootstrap + combined)": 2,
}

ALL_TRACKS = {
    "Track B (No.04-10, 작업19-25)": TRACK_B_HEADLINE,
    "Track C (작업26-28, 48)": TRACK_C_HEADLINE,
    "Track D (작업29-47, H1-H36)": TRACK_D_HEADLINE,
    "Track D 이후 독립 라운드 (작업48-49)": POST_TRACK_D_HEADLINE,
}

EXCLUDED_FROM_HEADLINE_COUNT = {
    "macro_event_study_2026-08-21 (별도 스레드, 챔피언 전략 계보 밖)": 55,
    "core/strategy_tuning.py 야간/온디맨드 종목별 순열검정 (_compute_tuning_significance, "
    "작업16~ 현재까지 반복 실행 — 정확한 총 실행 횟수는 실행 로그가 남아있지 않아 이 스크립트로는 "
    "집계 불가, 100종목 표본 x 여러 스타일그룹 x 반복 실행 규모로 볼 때 최소 수백 회 이상으로 추정)": None,
}


def headline_total() -> int:
    return sum(sum(d.values()) for d in ALL_TRACKS.values())


# ---------------------------------------------------------------------------
# 2) granular 집계 — report_data.json 전수 스캔 (기계적, 재현 가능)
# ---------------------------------------------------------------------------

def scan_report_data_jsons() -> dict:
    files = sorted((REPO_ROOT / "analysis").glob("*/report_data.json"))
    p_value_count = 0
    multiarm_winrate_arms = 0
    multiarm_winrate_groups = 0
    verdict_hint_count = 0
    scalar_winrate_count = 0
    per_file = {}

    def walk(obj):
        nonlocal p_value_count, multiarm_winrate_arms, multiarm_winrate_groups, verdict_hint_count, scalar_winrate_count
        if isinstance(obj, dict):
            if "p_value" in obj and isinstance(obj["p_value"], (int, float)):
                p_value_count += 1
            if "verdict_hint" in obj:
                verdict_hint_count += 1
            if "win_rate" in obj:
                v = obj["win_rate"]
                if isinstance(v, dict):
                    multiarm_winrate_groups += 1
                    multiarm_winrate_arms += len(v)
                elif isinstance(v, (int, float)):
                    scalar_winrate_count += 1
            for vv in obj.values():
                walk(vv)
        elif isinstance(obj, list):
            for vv in obj:
                walk(vv)

    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        before = (p_value_count, multiarm_winrate_arms, multiarm_winrate_groups, verdict_hint_count, scalar_winrate_count)
        walk(d)
        after = (p_value_count, multiarm_winrate_arms, multiarm_winrate_groups, verdict_hint_count, scalar_winrate_count)
        per_file[str(f.relative_to(REPO_ROOT))] = {
            "p_value": after[0] - before[0],
            "multiarm_winrate_arms": after[1] - before[1],
            "multiarm_winrate_groups": after[2] - before[2],
            "verdict_hint": after[3] - before[3],
            "scalar_winrate": after[4] - before[4],
        }

    return {
        "per_file": per_file,
        "totals": {
            "formal_permutation_p_values": p_value_count,
            "multiarm_winrate_arms": multiarm_winrate_arms,
            "multiarm_winrate_groups": multiarm_winrate_arms and multiarm_winrate_groups,
            "explicit_verdict_hint_calls": verdict_hint_count,
            "scalar_descriptive_winrate_leaves": scalar_winrate_count,
        },
    }


if __name__ == "__main__":
    print("=== Headline hypothesis/round count by track ===")
    for track, d in ALL_TRACKS.items():
        sub = sum(d.values())
        print(f"{track}: {sub}")
        for k, v in d.items():
            print(f"   - {k}: {v}")
    print()
    print("HEADLINE TOTAL (champion-strategy lineage only):", headline_total())
    print()
    print("Excluded from headline total (separate/unquantifiable tracks):")
    for k, v in EXCLUDED_FROM_HEADLINE_COUNT.items():
        print(f"   - {k}: {v}")
    print()
    g = scan_report_data_jsons()
    print("=== Granular report_data.json scan ===")
    print(json.dumps(g["totals"], indent=2, ensure_ascii=False))

    out = {
        "headline_by_track": {k: {"subtotal": sum(v.values()), "items": v} for k, v in ALL_TRACKS.items()},
        "headline_total": headline_total(),
        "excluded_from_headline_total": EXCLUDED_FROM_HEADLINE_COUNT,
        "granular_scan": g,
    }
    (Path(__file__).resolve().parent / "test_count_estimate.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("\nsaved -> test_count_estimate.json")
