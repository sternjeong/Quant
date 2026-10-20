# sleeve-local-execution-v1

판정 **FAIL**. 117개 중첩 평가창(비중첩 환산 2.9개).

SPY 대비 IRR 차이 중앙 +1.09%p, 10분위 -0.23%p, 승리 73.5%.

| 관문 | 통과 |
|---|---|
| win_share | True |
| median_irr_plus_1pp | True |
| p10_irr_ge_minus_1_5pp | True |
| full_mdd_within_5pp | True |
| full_worst252_within_5pp | True |
| absolute_mdd_within_40pct | True |
| cost_stress_positive | True |
| p1st_median_plus_0_3pp | False |
| fee_reduction_20pct | False |

활성 일수익 블록 부트스트랩: IR 0.4881537339891143, 단측 p 0.04995004995004995; 여섯 작업의 Holm 보정은 전체 결과를 모은 뒤에만 계산한다. 이 값은 세후 IRR 유의확률이 아니다.

검정력(사전 계산): 14.66년·시도 6개에서 통과에 필요한 연 IR ≈ 0.77 (참 효과별 통과 확률 IR 0.20→2%, IR 0.30→4%, IR 0.50→15%). FAIL 이어도 관측 IR 이 이보다 작으면 '판별 불가'에 가깝다.

중첩 구간은 독립 표본이 아니며 2010~2024 이력은 반복 사용됐다. P1ST가 포함된 작업은 상장폐지 종목 누락 가능성이 있다. 2024-10 이후는 판정에 사용하지 않았다. 엔진 반영은 별도 결정이다.
