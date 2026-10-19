# 대형주 모멘텀 실제 ETF 이전 — SPY+MTUM 50/50

판정: **FAIL_UNDERPOWERED**

이 결과는 기존 French 대형주 승자 포트폴리오 50% 혼합을 실제 MTUM ETF로 옮긴 단일 고정 비교다. 통과해도 채택이 아니라 전진 검토 후보이며 엔진은 바뀌지 않는다.

- 기간: 2014-05-01 ~ 2024-09-03, 65개의 월별 시작 5년 창(스모크는 합성 2년 창)
- 승률 50.8%; 세후 IRR 차이 중앙값 +0.45%p, 10분위 -2.08%p
- 시간가중 MDD 중앙값 후보 -29.85% / SPY -29.69%
- paired 126일 block bootstrap 90% CAGR 차이: [-2.14, 2.77]%p; 관측 IR 0.093
- 판정 관문: `{"win_share_ge_70pct": false, "median_irr_diff_ge_0.5pp": false, "p10_irr_diff_ge_minus_1.5pp": false, "median_mdd_within_5pp": true, "paired_bootstrap_low90_gt_minus_0.5pp": false}`

- 검정력 사전 계산: 검정력(사전 계산): 10.34년·시도 1개에서 통과에 필요한 연 IR ≈ 0.51 (참 효과별 통과 확률 IR 0.20→16%, IR 0.30→25%, IR 0.50→48%). FAIL 이어도 관측 IR 이 이보다 작으면 '판별 불가'에 가깝다.

- 겹침 주의: 65 windows overlap heavily; only about 2.1 non-overlapping 5-year windows fit in 10.3 years, so the win share is far less certain than 65 independent trials would suggest.

세금·배당 및 가격 조정은 근사다. 매매 엔진·챔피언·전진 원장은 변경하지 않았다.
