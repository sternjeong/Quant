# alpha-customer-link-v1 자료 적격성 검사

**NOT_EVALUABLE_DATA** — 전략 수익률·알파·통과 판정은 계산하지 않았다.

필수 근거: 과거 10-K에 공개된 고객 실명·매출비중·접수시각과 양사 증권 매핑

공통: 당시 구성종목·증권 식별·상장폐지 수익·요인·환율이 모두 있어야 한다.

- daily.csv: MISSING
- names.csv: MISSING
- delists.csv: MISSING
- sp500.csv: MISSING
- security_map.csv: MISSING
- ff5_umd_monthly.csv: MISSING
- fx_daily.csv: MISSING
- customer_links_pit.csv: MISSING

기존 캐시 요약: {"legacy_cache": "no validated source cache"}

계획 구간만 가정한 사전 검정력(적격 관측치 0건): 검정력(사전 계산): 14.75년·시도 4개에서 통과에 필요한 연 IR ≈ 0.70 (참 효과별 통과 확률 IR 0.20→3%, IR 0.30→6%, IR 0.50→22%). FAIL 이어도 관측 IR 이 이보다 작으면 '판별 불가'에 가깝다.

다음: 원본 데이터의 시점별 완전성·상장폐지 결합을 검증한 뒤 고정 규칙으로 별도 성과 작업을 실행한다.
