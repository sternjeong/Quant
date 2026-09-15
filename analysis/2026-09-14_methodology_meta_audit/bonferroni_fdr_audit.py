"""리서치 에이전트 G — 다중비교 보정(Bonferroni / Benjamini-Hochberg FDR) 실제 계산.

입력: `research_program_synthesis`의 confidence_table(12) + track_c_table(5) = 17개 "최종" 결론 중,
p-value 또는 p-value로 환산 가능한 승률(win_rate)이 실제로 존재하는 항목만 뽑아 보정한다(순수
서술/정성 판단만 있는 항목은 보정 대상에서 제외하고 별도로 논한다 — 이유는 report_data.json 및
PROGRESS.md 원문 인용과 함께 아래 SOURCE_NOTES에 기록).

승률(win_rate, block bootstrap/Monte Carlo로 계산된 "A가 B를 이길 확률")을 단측 p-value로 환산하는
방법: p = 1 - win_rate (귀무가설 = "두 대안에 차이 없음", win_rate가 0.5에 가까울수록 p가 커진다).
순수 순열검정(permutation test)은 이미 그 자체로 p-value/percentile을 보고하므로 그대로 쓴다.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 1) "최종 층위" 17개 결론 중 정량적 유의성 지표가 존재하는 항목
# ---------------------------------------------------------------------------
# p_or_implied: permutation test는 실제 p-value, win_rate 기반은 1-win_rate로 환산(주석에 명시)
CLAIMS = [
    {
        "id": "momentum_ranking_vs_random",
        "label": "모멘텀 랭킹 방식(12개월) — 무작위 선택 대비",
        "program_grade": "moderate",
        "method": "permutation test, N=200 reshuffle (작업21 5라운드)",
        "p_or_implied": 0.025,
        "note": "97.5th percentile ≈ p=0.025. 이것이 이 프로그램 전체에서 가장 강한 '정식' 유의성 근거.",
    },
    {
        "id": "momentum_ranking_12m_vs_9m",
        "label": "모멘텀 랭킹 12개월 vs 9개월 lookback",
        "program_grade": "moderate(위 결론의 강건성 체크)",
        "method": "H30 몬테카를로 민감도, win_rate=0.555",
        "p_or_implied": round(1 - 0.5551, 4),
        "note": "동전던지기에 가까움 — 같은 '모멘텀 랭킹' 결론의 파라미터 선택 자체가 이미 약함.",
    },
    {
        "id": "rebalance_monthly_vs_quarterly",
        "label": "리밸런싱 주기(월간 vs 분기)",
        "program_grade": "weak",
        "method": "H34 결합전파(가중치+표본오차) win_rate=0.496",
        "p_or_implied": round(1 - 0.496, 4),
        "note": "부호조차 방향이 사실상 반전(월간 우위가 근거 없음).",
    },
    {
        "id": "binary_market_filter",
        "label": "이진 시장필터(SPY<200일선 → 50% 축소)",
        "program_grade": "weak",
        "method": "H35 결합전파 win_rate=0.552(무필터 우세)",
        "p_or_implied": round(1 - 0.552, 4),
        "note": "가중치만 99.97%였던 것이 표본오차 반영 후 55.2%로 붕괴.",
    },
    {
        "id": "core_vol_targeting",
        "label": "코어 레벨 변동성 타겟팅 오버레이",
        "program_grade": "reversed",
        "method": "H34 결합전파 win_rate=0.497",
        "p_or_implied": round(1 - 0.497, 4),
        "note": "완전한 동전던지기.",
    },
    {
        "id": "satellite_inclusion",
        "label": "새틀라이트 포함 여부(15%, point-in-time 추세추종)",
        "program_grade": "weak",
        "method": "H33/H34 결합전파 win_rate=0.579",
        "p_or_implied": round(1 - 0.579, 4),
        "note": "가중치만 99.7%였던 것이 결합전파 후 57.9%.",
    },
    {
        "id": "satellite_trend_following_vs_random",
        "label": "새틀라이트 선정방식(추세추종) — 무작위 대비",
        "program_grade": "weak",
        "method": "H10 순열검정, 93rd percentile",
        "p_or_implied": 0.07,
        "note": "95% 유의 문턱 미달로 이미 프로그램 스스로 'weak' 판정.",
    },
    {
        "id": "satellite_momentum_vs_random",
        "label": "새틀라이트 선정방식(순수 모멘텀) — 무작위 대비",
        "program_grade": "weak(위 항목에 앞선 이전 버전)",
        "method": "H9 순열검정, 88th percentile",
        "p_or_implied": 0.12,
        "note": "위 항목으로 대체되기 전 버전.",
    },
    {
        "id": "collar_hedge_sleeve",
        "label": "칼라 옵션 헤지(새틀라이트 슬리브 단독)",
        "program_grade": "weak",
        "method": "부트스트랩 슬리브 단독 승률 55~59%(중앙값 57% 사용)",
        "p_or_implied": round(1 - 0.57, 4),
        "note": "90% CI가 부호조차 확정 못함.",
    },
    {
        "id": "risk_adjusted_momentum",
        "label": "위험조정 모멘텀 랭킹 (원시모멘텀 대비 우위 주장)",
        "program_grade": "reversed",
        "method": "순열검정 N=200 (작업48/49)",
        "p_or_implied": 0.667,
        "note": "이미 프로그램 스스로 기각.",
    },
    {
        "id": "iren_basket_trend_following",
        "label": "IREN류 바스켓 추세추종 — 무작위 대비",
        "program_grade": "weak",
        "method": "순열검정, 93rd percentile (작업27/29)",
        "p_or_implied": 0.075,
        "note": "5% 문턱 미달로 이미 스스로 인지.",
    },
    {
        "id": "iren_single_trend_following",
        "label": "IREN 단일종목 추세추종 — 무작위 대비",
        "program_grade": "weak(부트스트랩 CI 폭이 바스켓과 동일해 하향)",
        "method": "순열검정, 100th percentile (작업27/29)",
        "p_or_implied": 0.005,
        "note": "프로그램 전체에서 명목 p-value가 가장 작은 단일 결과. 그런데도 부트스트랩 감사(작업48)에서" \
                " 신뢰구간 폭이 바스켓과 사실상 동일해 'weak'로 하향 조정됨.",
    },
]

# 정성적 판단만 있고 p-value/win_rate 자체가 존재하지 않아 보정 계산에서 제외한 "final" 결론 2건
QUALITATIVE_ONLY_CLAIMS = [
    {
        "id": "core_universe_17asset",
        "label": "코어 자산군(17자산 유니버스) — robust 등급",
        "program_grade": "robust",
        "why_excluded": "단일 2008 GFC 실제 역사적 위기 구간에서의 실현 성과(+8.4% vs SPY -40.4%)에 "
                         "근거 — 재표본추출/순열검정 등 형식적 유의성 검정이 이 결정 자체에는 한 번도 "
                         "적용된 적이 없다(하위 파라미터들은 여러 라운드에 걸쳐 검정됨). p-value가 "
                         "존재하지 않아 Bonferroni/FDR을 기계적으로 적용할 수 없다 — 본문에서 별도로 "
                         "'유효 독립 위기표본 개수' 관점으로 논한다.",
    },
    {
        "id": "satellite_exit_mechanism_static",
        "label": "새틀라이트 청산/스위치 메커니즘(정적보유가 기댓값 최적) — moderate 등급",
        "program_grade": "moderate",
        "why_excluded": "H12~H23 6라운드에 걸쳐 반복 재현된 패턴이라는 '정성적' 근거로 moderate를 "
                         "부여했다고 원문(작업47/50)이 명시 — '아직 블록부트스트랩 감사를 거치지 않았다'고 "
                         "스스로 인정. 형식적 p-value가 없어 계산 대상에서 제외.",
    },
    {
        "id": "per_pbr_valuation_frame",
        "label": "PER/PBR 대수적 밸류에이션 프레임 — moderate 등급 (트랙C)",
        "program_grade": "moderate",
        "why_excluded": "이론적 유도의 견고함에 근거한 정성적 판단 — 실증 스크리닝은 오히려 스코프 "
                         "한계를 드러냈을 뿐 별도의 통계적 검정을 거치지 않음.",
    },
]


def bh_fdr(pvalues: list[float], q: float = 0.05):
    n = len(pvalues)
    order = sorted(range(n), key=lambda i: pvalues[i])
    sorted_p = [pvalues[i] for i in order]
    thresholds = [(i + 1) / n * q for i in range(n)]
    # 표준 BH 절차: p_(i) <= (i/n)*q 를 만족하는 가장 큰 i를 찾아 그 이하 전부 채택(귀무기각)
    largest_i = -1
    for i in range(n):
        if sorted_p[i] <= thresholds[i]:
            largest_i = i
    survivors_sorted_idx = set(range(largest_i + 1)) if largest_i >= 0 else set()
    survivors_original_idx = {order[i] for i in survivors_sorted_idx}
    return {
        "n": n,
        "q": q,
        "sorted_p": sorted_p,
        "thresholds": thresholds,
        "largest_i_satisfying": largest_i,
        "survivor_count": len(survivors_original_idx),
        "survivor_original_indices": sorted(survivors_original_idx),
    }


def bonferroni(pvalues: list[float], alpha: float, family_size: int):
    threshold = alpha / family_size
    return {
        "alpha": alpha,
        "family_size": family_size,
        "per_test_threshold": threshold,
        "results": [
            {"p": p, "survives": p <= threshold} for p in pvalues
        ],
        "survivor_count": sum(1 for p in pvalues if p <= threshold),
    }


def main():
    pvals = [c["p_or_implied"] for c in CLAIMS]

    # --- BH-FDR on the 13-claim "final layer" p-value vector (모든 p/환산p 보유 항목) ---
    fdr_result = bh_fdr(pvals, q=0.05)

    # --- Bonferroni under three plausible family-size definitions ---
    alpha = 0.05
    family_sizes = {
        "N=9 (가장 관대함: 작업20-21 파라미터 탐색 라운드 수만, 모멘텀랭킹 주장 하나 기준)": 9,
        "N=25 (Track B 전체 헤드라인 가설 수)": 25,
        "N=80 (챔피언 계보 전체 헤드라인 가설 수, count_tests.py 산출)": 80,
        "N=1022 (report_data.json 전수 스캔 granular 리프 수, 상한 추정)": 1022,
    }
    bonferroni_results = {
        name: bonferroni(pvals, alpha, n) for name, n in family_sizes.items()
    }

    out = {
        "claims": CLAIMS,
        "qualitative_only_claims_excluded_from_calc": QUALITATIVE_ONLY_CLAIMS,
        "bh_fdr_on_final_layer_pvalues": fdr_result,
        "bonferroni_by_family_size": bonferroni_results,
    }
    (OUT_DIR / "bonferroni_fdr_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("=== Claims ranked by p (or implied p) ===")
    for c in sorted(CLAIMS, key=lambda c: c["p_or_implied"]):
        print(f"  p={c['p_or_implied']:.4f}  [{c['program_grade']:>10}]  {c['label']}")

    print()
    print(f"=== BH-FDR (q=0.05) over the {len(pvals)}-claim final-layer p-vector ===")
    print(f"  survivor count: {fdr_result['survivor_count']} / {fdr_result['n']}")
    for i, p in enumerate(fdr_result["sorted_p"]):
        print(f"    rank {i+1}: p={p:.4f}  threshold={fdr_result['thresholds'][i]:.5f}  "
              f"{'PASS' if p <= fdr_result['thresholds'][i] else 'fail'}")

    print()
    print("=== Bonferroni survivor counts by assumed family size ===")
    for name, res in bonferroni_results.items():
        print(f"  {name}: threshold={res['per_test_threshold']:.6f}  survivors={res['survivor_count']}/{len(pvals)}")

    print("\nsaved -> bonferroni_fdr_results.json")


if __name__ == "__main__":
    main()
