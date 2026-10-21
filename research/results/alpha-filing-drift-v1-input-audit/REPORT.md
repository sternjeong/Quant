# alpha-filing-drift-v1 자료 적격성 검사

**NOT_EVALUABLE_DATA** — 전략 수익률·알파·통과 판정은 계산하지 않았다.

필수 근거: 8-K Item 2.02 접수시각, 해당 시점 증권·업종 식별, 공시 후 완전한 3거래일

공통: 당시 구성종목·증권 식별·상장폐지 수익·요인·환율이 모두 있어야 한다.

- daily.csv: MISSING
- names.csv: MISSING
- delists.csv: MISSING
- sp500.csv: MISSING
- security_map.csv: MISSING
- ff5_umd_monthly.csv: MISSING
- fx_daily.csv: MISSING
- 8k_item202_pit.csv: MISSING
- sector_daily.csv: MISSING
- sector_pit.csv: MISSING

기존 캐시 요약: {"legacy_cache": "no validated source cache"}

계획 구간만 가정한 사전 검정력(적격 관측치 0건): 검정력(사전 계산): 14.75년·시도 4개에서 통과에 필요한 연 IR ≈ 0.70 (참 효과별 통과 확률 IR 0.20→3%, IR 0.30→6%, IR 0.50→22%). FAIL 이어도 관측 IR 이 이보다 작으면 '판별 불가'에 가깝다.

다음: 원본 데이터의 시점별 완전성·상장폐지 결합을 검증한 뒤 고정 규칙으로 별도 성과 작업을 실행한다.
