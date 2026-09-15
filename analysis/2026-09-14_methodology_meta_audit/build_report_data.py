#!/usr/bin/env python3
"""세 소스(test_count_estimate.json, bonferroni_fdr_results.json,
consistency_and_leakage_audit.json)를 하나의 report_data.json으로 합친다."""
import json
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def load(name):
    with open(f"{OUT_DIR}/{name}", encoding="utf-8") as f:
        return json.load(f)


test_counts = load("test_count_estimate.json")
bfdr = load("bonferroni_fdr_results.json")
consistency = load("consistency_and_leakage_audit.json")

meta_conclusion = {
    "headline": (
        "research_program_synthesis.confidence_table + track_c_table가 매긴 17개 '최종' 결론 중 "
        "정량적 유의성 지표(p-value 또는 부트스트랩/몬테카를로 승률)를 보유한 12개를 다중비교 "
        "보정하면, Bonferroni는 어떤 현실적인 가설-족(family) 크기(N=9~1022)를 가정해도 12개 중 "
        "최대 1개(가장 관대한 N=9 가정에서 IREN 단일종목 추세추종, p=0.005)만 살아남고, "
        "Benjamini-Hochberg FDR(q=0.05)은 이 12개짜리 '최종 층위'만 놓고 봐도 단 하나도 살아남지 "
        "못한다(가장 작은 p=0.005조차 순위 1의 임계값 0.00417을 넘지 못함)."
    ),
    "on_robust_grade": (
        "'robust' 등급은 프로그램 전체에서 딱 1개(코어 자산군 17자산 유니버스)뿐인데, 이 결론은애초에 "
        "p-value가 존재하지 않는 단일 역사적 사건(2008 GFC) 기반 정성 판단이라 Bonferroni/FDR을 "
        "기계적으로 적용할 대상 자체가 아니다. 이 결론이 진짜로 안전한지는 '유효 독립 위기표본 개수' "
        "관점에서 봐야 하는데, 이 프로그램이 반복 사용하는 위기구간은 실질적으로 6개뿐이고 그중 "
        "2008 GFC 하나에 이 결론 전체가 의존한다 -- 표본 크기 1의 '아웃오브샘플 검증'이다. "
        "따라서 'robust'라는 라벨은 과장이며, 최소한 'moderate(단일 강한 사례, 재현 불가)'로 낮춰야 한다."
    ),
    "on_moderate_grades": (
        "'moderate' 등급 3개(모멘텀 랭킹 방식, 새틀라이트 청산 메커니즘, PER/PBR 밸류에이션 프레임) "
        "중 형식적 p-value가 있는 것은 모멘텀 랭킹 방식 하나뿐(p=0.025)이며, 이마저 어떤 다중비교 "
        "보정도 통과하지 못한다(Bonferroni 최소요구 N=2에서조차 경계선). 나머지 둘은 애초에 형식적 "
        "검정이 없다. 세 항목 모두 'moderate'에서 'weak'로 낮추는 것이 맞다."
    ),
    "verdict_on_champion_strategy": (
        "결론적으로, 오늘(2026-09-14) 라이브로 도는 core/champion_strategy.py의 최종 설정 중 "
        "다중비교 보정을 통과해 '통계적으로 유의미하다'고 부를 수 있는 구성요소는 하나도 없다. "
        "이 전략이 지금 이대로 운용을 지속할 근거는 '통계적으로 증명된 우위'가 아니라 "
        "(1) 2008년 한 차례의 강력한 실제 위기 대응 사례, (2) 정적 배분이 여러 라운드에 걸쳐 "
        "반복적으로 동적 스위치를 이겼다는 정성적 패턴, (3) 다른 대안들이 이보다 더 나쁜 증거를 "
        "가졌다는 상대적 우위 -- 세 가지 경제적/서사적 근거이지, 가설검정으로 확정된 근거가 아니다. "
        "이 구분을 운용자(사용자)에게 명시적으로 알려야 한다."
    ),
}

report = {
    "meta": {
        "title": "방법론 메타 감사 -- 다중비교 보정(Bonferroni/FDR)",
        "generated": "2026-09-14",
        "agent": "리서치 에이전트 G (방법론 메타 감사관)",
        "scope": "PROGRESS.md 작업 1-67 전체 + analysis/ 29개 report_data.json + "
                 "research_program_synthesis 확신도 등급표(17개 결론)",
    },
    "test_counts": test_counts,
    "bonferroni_fdr": bfdr,
    "consistency_and_leakage_audit": consistency,
    "meta_conclusion": meta_conclusion,
}

with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print("saved -> report_data.json")
