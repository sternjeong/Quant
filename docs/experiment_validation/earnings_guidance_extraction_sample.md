# 가이던스 추출 품질 검증 표본 (실제 EDGAR 보도자료)

상태: **검증 대기**. 이 문서는 사람이 원문과 대조해 정답을 확인하기 위한 표본이다. 추출기 작성자가 이 표를 만들었으므로 (작성자=검증자 문제) **정확도를 주장하지 않는다.** 아래 '사람 확인' 열은 비어 있다.

- 생성: 2026-09-22 10:00 UTC, 스크립트 `scripts/earnings_guidance_extraction_sample.py`, `core/earnings_events.py` sha256 앞 12자 `703f4f80b327`
- 표본 규칙(결과를 보기 전에 고정): TICKERS 12개 각각의 최신 8-K Item 2.02 1건. 직전 3건은 자동 change 계산용 이력으로만 추출했다. 문서 선택에 추출 성공 여부를 쓰지 않았다.
- 이 표본은 스펙 G0(scalar 필드 exact match ≥95%, 방향 오류 0건)을 판정하기에 부족하다: 스펙은 최소 60 item, 30개 이상 서로 다른 발표, 8개 이상 기업과 추출기 작성자와 다른 정답 작성자를 요구한다.
- 추출기를 이 표본 결과에 맞춰 조정하지 않았다(표본 생성 전에 규칙을 고정했고, 표본 생성 이후 규칙 변경은 아래 '수정 이력'에 따로 적는다).

## 요약(추출 상태 분포 — 정답 대비 정확도가 아니다)

- 대상 발표 12건 중 본문 확보 12건, 수집 실패 0건
- `guidance_found`: 11건
- `guidance_language_unparsed`: 0건
- `no_guidance_language`: 1건
- 가이던스 item을 하나도 얻지 못한 발표(= 추출 unknown 성격): 1/12 (8%). 이 중 원문에 실제로 가이던스가 없는 경우와 추출기가 놓친 경우는 사람 확인 전에는 구분되지 않는다.
- 추출 item 총 121건, 그중 비교 불가 문제(기간 미확정·스케일/부호 모호 등) 보유 34건
- 자동 change 분포(최신 발표 item 기준, 미검증): lowered 4, maintained 5, raised 25, unknown 87

## 발표별 결과

### NVDA — NVIDIA CORP (0001045810-26-000073)

- 8-K acceptance: 2026-08-26 20:21:19 UTC = 2026-08-26 16:21 ET (after_hours); 다음 실행가능 시가(주말만 제외): 2026-08-27
- 보도자료: EX-99.1 — https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073/q2fy27pr.htm
- 원문 해시(sha256, 앞 12자): 3e3140c8413a / 텍스트 23,197자
- 추출 상태: **guidance_found** (item 4건, skipped 4건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0001045810-25-000228[guidance_found, 3건], 0001045810-26-000019[guidance_found, 4건], 0001045810-26-000051[guidance_found, 3건]

| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | revenue | unspecified | FY2027Q3 | 105,840,000,000 ~ 110,160,000,000 | currency/USD | range | range_from_tolerance | unknown(no_previous_in_retrieved_history) | •Revenue is expected to be $108.0 billion, plus or minus 2%. | [ ] |
| 2 | gross_margin | unspecified | FY2027Q3 | 74 ~ 74 | percent | point | - | unknown(no_previous_in_retrieved_history) | •GAAP and non-GAAP gross margins are expected to be 74.0%, plus or minus 50 basis points. | [ ] |
| 3 | gross_margin | gaap | FY2027Q3 | 74 ~ 74 | percent | point | - | unknown(no_previous_in_retrieved_history) | [Q3 FY2027 Outlook] GAAP gross margin 74.0% | [ ] |
| 4 | gross_margin | non_gaap | FY2027Q3 | 74 ~ 74 | percent | point | - | unknown(no_previous_in_retrieved_history) | [Q3 FY2027 Outlook] Non-GAAP gross margin 74.0% | [ ] |

추출기가 건너뛴 후보(사유):
- `guidance_language_without_parsable_values` — NVIDIA is not assuming any Data Center compute revenue from China in its outlook.
- `guidance_language_without_parsable_values` — •GAAP and non-GAAP operating expenses are expected to be approximately $9.2 billion and $9.0 billion, respectively.
- `guidance_language_without_parsable_values` — For the full year fiscal 2027, NVIDIA expects GAAP and non-GAAP tax rates to be between 16.0% and 18.0%, excluding any discrete items and material changes to NVIDIA's tax environment.
- `ignored:prior_or_actual_reference_only` — •Second-quarter revenue was $89.0 billion, up 18% from the previous quarter and up 117% from a year ago.

### CSCO — CISCO SYSTEMS, INC. (0000858877-26-000106)

- 8-K acceptance: 2026-08-12 20:07:06 UTC = 2026-08-12 16:07 ET (after_hours); 다음 실행가능 시가(주말만 제외): 2026-08-13
- 보도자료: EX-99.1 — https://www.sec.gov/Archives/edgar/data/858877/000085887726000106/exhibit991pressrelease-q4f.htm
- 원문 해시(sha256, 앞 12자): 6c9792cde5aa / 텍스트 37,122자
- 추출 상태: **guidance_found** (item 27건, skipped 11건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0001193125-25-277624[guidance_found, 18건], 0000858877-26-000006[guidance_found, 30건], 0000858877-26-000075[guidance_found, 31건]

| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | revenue | unspecified | FY2027Q1 | 18,000,000,000 ~ 18,200,000,000 | currency/USD | range | - | unknown(no_previous_in_retrieved_history) | ◦Revenue: $18.0 billion to $18.2 billion | [ ] |
| 2 | eps | unspecified | FY2027Q1 | 1.08 ~ 1.1 | per_share/USD | range | - | unknown(no_previous_in_retrieved_history) | ◦Earnings per Share: GAAP: $1.08 to $1.10; Non-GAAP: $1.32 to $1.34 | [ ] |
| 3 | revenue | unspecified | FY2027 | 72,200,000,000 ~ 73,400,000,000 | currency/USD | range | - | unknown(no_previous_in_retrieved_history) | ◦Revenue: $72.2 billion to $73.4 billion | [ ] |
| 4 | eps | unspecified | FY2027 | 4 ~ 4.06 | per_share/USD | range | - | unknown(no_previous_in_retrieved_history) | ◦Earnings per Share: GAAP: $4.00 to $4.06; Non-GAAP: $5.05 to $5.11 | [ ] |
| 5 | revenue | unspecified | (미확정) fourth quarter | 17,300,000,000 ~ 17,300,000,000 | currency/USD | point | period_year_missing:Q4 | unknown(current_not_comparable:period_unresolved) | Cisco reported fourth quarter revenue of $17.3 billion, net income on a generally accepted accounting principles (GAAP) basis of $3.9 billion or $0.97 per share, and non-GAAP net income of $4.9 billion or $1.22 per shar… | [ ] |
| 6 | eps | non_gaap | (미확정) fourth quarter | 0.97 ~ 0.97 | per_share/USD | point | period_year_missing:Q4 | unknown(current_not_comparable:period_unresolved) | Cisco reported fourth quarter revenue of $17.3 billion, net income on a generally accepted accounting principles (GAAP) basis of $3.9 billion or $0.97 per share, and non-GAAP net income of $4.9 billion or $1.22 per shar… | [ ] |
| 7 | eps | unspecified | (미확정) fourth quarter | 1.22 ~ 1.22 | per_share/USD | point | period_year_missing:Q4 | unknown(current_not_comparable:period_unresolved) | Cisco reported fourth quarter revenue of $17.3 billion, net income on a generally accepted accounting principles (GAAP) basis of $3.9 billion or $0.97 per share, and non-GAAP net income of $4.9 billion or $1.22 per shar… | [ ] |
| 8 | revenue | unspecified | FY2026Q4 | 17,300,000,000 ~ 17,300,000,000 | currency/USD | point | - | raised(midpoint_comparison) | [•FY 2027 Guidance:] Q4 FY 2026: Revenue $17.3 billion | [ ] |
| 9 | revenue | unspecified | FY2025Q4 | 14,700,000,000 ~ 14,700,000,000 | currency/USD | point | - | unknown(no_previous_in_retrieved_history) | [•FY 2027 Guidance:] Q4 FY 2025: Revenue $14.7 billion | [ ] |
| 10 | eps | unspecified | FY2026Q4 | 0.97 ~ 0.97 | per_share/USD | point | - | raised(midpoint_comparison) | [•FY 2027 Guidance:] Q4 FY 2026: Diluted Earnings per Share (EPS) $0.97 | [ ] |
| 11 | eps | unspecified | FY2025Q4 | 0.64 ~ 0.64 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | [•FY 2027 Guidance:] Q4 FY 2025: Diluted Earnings per Share (EPS) $0.64 | [ ] |
| 12 | eps | unspecified | FY2026Q4 | 1.22 ~ 1.22 | per_share/USD | point | - | raised(midpoint_comparison) | [•FY 2027 Guidance:] Q4 FY 2026: EPS $1.22 | [ ] |
| 13 | eps | unspecified | FY2025Q4 | 0.99 ~ 0.99 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | [•FY 2027 Guidance:] Q4 FY 2025: EPS $0.99 | [ ] |
| 14 | revenue | unspecified | FY2026 | 63,300,000,000 ~ 63,300,000,000 | currency/USD | point | - | raised(midpoint_comparison) | [•FY 2027 Guidance:] FY 2026: Revenue $63.3 billion | [ ] |
| 15 | revenue | unspecified | FY2025 | 56,700,000,000 ~ 56,700,000,000 | currency/USD | point | - | unknown(no_previous_in_retrieved_history) | [•FY 2027 Guidance:] FY 2025: Revenue $56.7 billion | [ ] |
| 16 | eps | unspecified | FY2026 | 3.33 ~ 3.33 | per_share/USD | point | - | raised(midpoint_comparison) | [•FY 2027 Guidance:] FY 2026: EPS $3.33 | [ ] |
| 17 | eps | unspecified | FY2025 | 2.55 ~ 2.55 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | [•FY 2027 Guidance:] FY 2025: EPS $2.55 | [ ] |
| 18 | eps | unspecified | FY2026 | 4.33 ~ 4.33 | per_share/USD | point | - | raised(midpoint_comparison) | [•FY 2027 Guidance:] FY 2026: EPS $4.33 | [ ] |
| 19 | eps | unspecified | FY2025 | 3.81 ~ 3.81 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | [•FY 2027 Guidance:] FY 2025: EPS $3.81 | [ ] |
| 20 | revenue | unspecified | FY2027Q1 | 18,000,000,000 ~ 18,200,000,000 | currency/USD | range | - | unknown(no_previous_in_retrieved_history) | [Guidance] Revenue $18.0 billion - $18.2 billion | [ ] |
| 21 | gross_margin | non_gaap | FY2027Q1 | 65 ~ 66 | percent | range | - | unknown(no_previous_in_retrieved_history) | [Guidance] Non-GAAP gross margin 65% - 66% | [ ] |
| 22 | operating_margin | non_gaap | FY2027Q1 | 35.5 ~ 36.5 | percent | range | - | unknown(no_previous_in_retrieved_history) | [Guidance] Non-GAAP operating margin 35.5% - 36.5% | [ ] |
| 23 | eps | non_gaap | FY2027Q1 | 1.32 ~ 1.34 | per_share/USD | range | - | unknown(no_previous_in_retrieved_history) | [Guidance] Non-GAAP EPS $1.32 - $1.34 | [ ] |
| 24 | eps | gaap | FY2027Q1 | 1.08 ~ 1.1 | per_share/USD | range | - | unknown(no_previous_in_retrieved_history) | Cisco estimates that GAAP EPS will be $1.08 to $1.10 for the first quarter of fiscal 2027. | [ ] |
| 25 | revenue | unspecified | FY2027 | 72,200,000,000 ~ 73,400,000,000 | currency/USD | range | - | unknown(no_previous_in_retrieved_history) | [Guidance] Revenue $72.2 billion - $73.4 billion | [ ] |
| 26 | eps | non_gaap | FY2027 | 5.05 ~ 5.11 | per_share/USD | range | - | unknown(no_previous_in_retrieved_history) | [Guidance] Non-GAAP EPS $5.05 - $5.11 | [ ] |
| 27 | eps | gaap | FY2027 | 4 ~ 4.06 | per_share/USD | range | - | unknown(no_previous_in_retrieved_history) | Cisco estimates that GAAP EPS will be $4.00 to $4.06 for fiscal 2027. | [ ] |

추출기가 건너뛴 후보(사유):
- `multiple_candidates_same_metric_period` — ◦Delivered approximately $4 billion of revenue in FY 2026; $7.5 billion expected in FY 2027
- `eps_unit_mismatch` — Cisco reported fourth quarter revenue of $17.3 billion, net income on a generally accepted accounting principles (GAAP) basis of $3.9 billion or $0.97 per share, and non-GAAP net income of $4.9 billi…
- `guidance_language_without_parsable_values` — "In Q4, we delivered record revenue, non-GAAP operating income and EPS, all exceeding the high end of our guidance ranges and demonstrating strong financial discipline and operating leverage," said M…
- `percent_without_growth_context` — [•FY 2027 Guidance:] Q4 FY 2025: Revenue 18%
- `eps_unit_mismatch` — [•FY 2027 Guidance:] Q4 FY 2025: Diluted Earnings per Share (EPS) 52%

### MU — MICRON TECHNOLOGY INC (0000723125-26-000013)

- 8-K acceptance: 2026-06-24 20:02:01 UTC = 2026-06-24 16:02 ET (after_hours); 다음 실행가능 시가(주말만 제외): 2026-06-25
- 보도자료: EX-99.1 — https://www.sec.gov/Archives/edgar/data/723125/000072312526000013/a2026q3ex991-pressrelease.htm
- 원문 해시(sha256, 앞 12자): 85b4a1bc91a4 / 텍스트 18,435자
- 추출 상태: **guidance_found** (item 4건, skipped 3건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0000723125-25-000024[guidance_found, 3건], 0000723125-25-000044[guidance_found, 2건], 0000723125-26-000004[guidance_found, 8건]

| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | revenue | unspecified | FY2026Q4 | 50,000,000,000 ~ 50,000,000,000 | currency/USD | point | - | unknown(no_previous_in_retrieved_history) | [The following table presents Micron's guidance for the fourth quarter of 2026:] Revenue $50.0 billion ± $1.0 billion $50.0 billion ± $1.0 billion | [ ] |
| 2 | gross_margin | unspecified | FY2026Q4 | 86 ~ 86 | percent | point | - | unknown(no_previous_in_retrieved_history) | [The following table presents Micron's guidance for the fourth quarter of 2026:] Gross margin Approximately 86% Approximately 86% | [ ] |
| 3 | revenue | unspecified | (미확정)  | 50,000,000,000 ~ 50,000,000,000 | currency/USD | point | period_missing | unknown(current_not_comparable:period_unresolved) | [RECONCILIATION OF GAAP TO NON-GAAP OUTLOOK] Revenue $50.0 billion ± $1.0 billion - $50.0 billion ± $1.0 billion | [ ] |
| 4 | gross_margin | unspecified | (미확정)  | 86 ~ 86 | percent | point | period_missing | unknown(current_not_comparable:period_unresolved) | [RECONCILIATION OF GAAP TO NON-GAAP OUTLOOK] Gross margin Approximately 86% -% A Approximately 86% | [ ] |

추출기가 건너뛴 후보(사유):
- `multiple_candidates_same_metric_period` — [The following table presents Micron's guidance for the fourth quarter of 2026:] Diluted earnings per share $30.73 ± $1.00 $31.00 ± $1.00
- `multiple_candidates_same_metric_period` — [RECONCILIATION OF GAAP TO NON-GAAP OUTLOOK] Diluted earnings per share(1) $30.73 ± $1.00 $0.27 A, B, C $31.00 ± $1.00
- `eps_unit_mismatch` — (1)GAAP earnings per share and non-GAAP earnings per share based on approximately 1.15 billion diluted shares.

### ADBE — ADOBE INC. (0000796343-26-000147)

- 8-K acceptance: 2026-09-10 20:06:14 UTC = 2026-09-10 16:06 ET (after_hours); 다음 실행가능 시가(주말만 제외): 2026-09-11
- 보도자료: EX-99.1 — https://www.sec.gov/Archives/edgar/data/796343/000079634326000147/adbeex991q326.htm
- 원문 해시(sha256, 앞 12자): 05b84610ec75 / 텍스트 20,312자
- 추출 상태: **guidance_found** (item 22건, skipped 2건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0000796343-25-000135[guidance_found, 22건], 0000796343-26-000048[guidance_found, 11건], 0000796343-26-000109[guidance_found, 23건]

| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | revenue | unspecified | (미확정)  | 6,800,000,000 ~ 6,850,000,000 | currency/USD | range | period_missing | unknown(current_not_comparable:period_unresolved) | [Financial Targets] Total revenue $6.80 billion to $6.85 billion | [ ] |
| 2 | revenue | unspecified | (미확정)  | 1,930,000,000 ~ 1,950,000,000 | currency/USD | range | period_missing | unknown(current_not_comparable:period_unresolved) | [Financial Targets] Business Professionals & Consumers subscription revenue $1.93 billion to $1.95 billion | [ ] |
| 3 | revenue | unspecified | (미확정)  | 4,665,000,000 ~ 4,695,000,000 | currency/USD | range | period_missing | unknown(current_not_comparable:period_unresolved) | [Financial Targets] Creative & Marketing Professionals subscription revenue $4.665 billion to $4.695 billion | [ ] |
| 4 | eps | unspecified | (미확정)  | 4.65 ~ 4.7 | per_share/USD | range | period_missing | unknown(current_not_comparable:period_unresolved) | [Financial Targets] Earnings per share1 GAAP: $4.65 to $4.70 Non-GAAP: $6.30 to $6.35 | [ ] |
| 5 | operating_margin | unspecified | (미확정) fourth quarter | 44 ~ 44 | percent | point | period_year_missing:Q4 | unknown(current_not_comparable:period_unresolved) | 1Targets assume non-GAAP operating margin of ~44.0%, GAAP tax rate of ~22.0%, non-GAAP tax rate of ~18.0% and diluted share count of ~389 million for fourth quarter FY2026. | [ ] |
| 6 | revenue | unspecified | FY2026 | 26,576,000,000 ~ 26,626,000,000 | currency/USD | range | - | raised(midpoint_comparison) | [Financial Targets] Total revenue $26.576 billion to $26.626 billion | [ ] |
| 7 | revenue | unspecified | FY2026 | 7,470,000,000 ~ 7,490,000,000 | currency/USD | range | - | lowered(midpoint_comparison) | [Financial Targets] Business Professionals & Consumers subscription revenue $7.470 billion to $7.490 billion | [ ] |
| 8 | revenue | unspecified | FY2026 | 18,242,000,000 ~ 18,272,000,000 | currency/USD | range | - | lowered(midpoint_comparison) | [Financial Targets] Creative & Marketing Professionals subscription revenue $18.242 billion to $18.272 billion | [ ] |
| 9 | eps | unspecified | FY2026 | 18.12 ~ 18.17 | per_share/USD | range | - | raised(midpoint_comparison) | [Financial Targets] Earnings per share2 GAAP: $18.12 to $18.17 Non-GAAP: $24.45 to $24.50 | [ ] |
| 10 | operating_margin | unspecified | FY2026 | 45 ~ 45 | percent | point | - | maintained(midpoint_comparison) | 2Targets assume non-GAAP operating margin of ~45.0%, GAAP tax rate of ~22.5%, non-GAAP tax rate of ~18.0% and diluted share count of ~400 million for FY2026. | [ ] |
| 11 | eps | gaap | FY2026Q4 | 4.65 ~ 4.65 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions] GAAP diluted net income per share $4.65 $4.70 | [ ] |
| 12 | eps | unspecified | FY2026Q4 | 4.7 ~ 4.7 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions] GAAP diluted net income per share $4.65 $4.70 | [ ] |
| 13 | eps | non_gaap | FY2026Q4 | 6.3 ~ 6.3 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions] Non-GAAP diluted net income per share $6.30 $6.35 | [ ] |
| 14 | eps | unspecified | FY2026Q4 | 6.35 ~ 6.35 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions] Non-GAAP diluted net income per share $6.30 $6.35 | [ ] |
| 15 | operating_margin | gaap | (미확정) Fourth Quarter | 34 ~ 34 | percent | point | period_year_missing:Q4 | unknown(current_not_comparable:period_unresolved) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions] GAAP operating margin 34.0% | [ ] |
| 16 | operating_margin | non_gaap | (미확정) Fourth Quarter | 44 ~ 44 | percent | point | period_year_missing:Q4 | unknown(current_not_comparable:period_unresolved) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions] Non-GAAP operating margin 44.0% | [ ] |
| 17 | eps | gaap | FY2026 | 18.12 ~ 18.12 | per_share/USD | point | - | raised(midpoint_comparison) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions (continued)] GAAP diluted net income per share $18.12 $18.17 | [ ] |
| 18 | eps | unspecified | FY2026 | 18.17 ~ 18.17 | per_share/USD | point | - | raised(midpoint_comparison) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions (continued)] GAAP diluted net income per share $18.12 $18.17 | [ ] |
| 19 | eps | non_gaap | FY2026 | 24.45 ~ 24.45 | per_share/USD | point | - | raised(midpoint_comparison) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions (continued)] Non-GAAP diluted net income per share $24.45 $24.50 | [ ] |
| 20 | eps | unspecified | FY2026 | 24.5 ~ 24.5 | per_share/USD | point | - | raised(midpoint_comparison) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions (continued)] Non-GAAP diluted net income per share $24.45 $24.50 | [ ] |
| 21 | operating_margin | gaap | FY2026 | 35 ~ 35 | percent | point | - | maintained(midpoint_comparison) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions (continued)] GAAP operating margin 35.0% | [ ] |
| 22 | operating_margin | non_gaap | FY2026 | 45 ~ 45 | percent | point | - | maintained(midpoint_comparison) | [Reconciliation of GAAP to Non-GAAP Financial Targets and Assumptions (continued)] Non-GAAP operating margin 45.0% | [ ] |

추출기가 건너뛴 후보(사유):
- `guidance_language_without_parsable_values` — "Adobe delivered double-digit revenue and EPS growth in Q3 and we're raising full year revenue and EPS targets," said Steve Day, senior vice president and interim CFO, Adobe.
- `guidance_language_without_parsable_values` — Factors that might cause or contribute to such differences include, but are not limited to: failure to innovate effectively and meet customer needs; failure to compete effectively; issues relating to…

### CRM — Salesforce, Inc. (0001108524-26-000187)

- 8-K acceptance: 2026-08-26 20:03:53 UTC = 2026-08-26 16:03 ET (after_hours); 다음 실행가능 시가(주말만 제외): 2026-08-27
- 보도자료: EX-99.1 — https://www.sec.gov/Archives/edgar/data/1108524/000110852426000187/crm-q2fy27xexhibit991.htm
- 원문 해시(sha256, 앞 12자): 3505a75ce5cd / 텍스트 48,601자
- 추출 상태: **guidance_found** (item 18건, skipped 25건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0001108524-25-000234[guidance_found, 16건], 0001108524-26-000056[guidance_found, 16건], 0001108524-26-000125[guidance_found, 16건]

| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | revenue_growth | unspecified | FY2027 | 14 ~ 14 | percent | point | - | unknown(bound_type_mismatch) | cRPO growth accelerates to 14% Y/Y CC; Raises FY27 revenue guidance by $200M, $300M in CC | [ ] |
| 2 | revenue | unspecified | FY2027 | 46,100,000,000 ~ 46,400,000,000 | currency/USD | range | - | raised(midpoint_comparison) | Salesforce raises full year FY27 revenue guidance to $46.1 billion to $46.4 billion, up 11% - 12% Y/Y and 11% Y/Y in CC. | [ ] |
| 3 | revenue | unspecified | FY2027 | 11,420,000,000 ~ 11,500,000,000 | currency/USD | range | - | raised(midpoint_comparison) | •Initiates third quarter FY27 revenue guidance of $11.42 billion to $11.5 billion, up 11% - 12% Y/Y and in CC, including slightly above 4pts Informatica contribution | [ ] |
| 4 | revenue | unspecified | FY2027 | 46,100,000,000 ~ 46,400,000,000 | currency/USD | range | - | raised(midpoint_comparison) | •Raises full year FY27 revenue guidance, now expects full year FY27 revenue of $46.1 billion to $46.4 billion, up 11% - 12% Y/Y and 11% in CC, including slightly above 3pts Informatica contribution. | [ ] |
| 5 | revenue_growth | unspecified | FY2027 | 12 ~ 12 | percent | point | - | unknown(bound_type_mismatch) | •Raises full year FY27 subscription and support revenue growth guidance to slightly above 12% Y/Y and slightly under 12% in CC, including slightly above 3pts Informatica contribution | [ ] |
| 6 | operating_margin | unspecified | FY2027 | 20.1 ~ 20.1 | percent | point | - | unknown(issuer_wording_conflicts_with_computed:maintain->lowered) | •Updates full year FY27 GAAP operating margin guidance to 20.1%, and maintains non-GAAP operating margin guidance of 34.3% | [ ] |
| 7 | operating_margin | non_gaap | FY2027 | 34.3 ~ 34.3 | percent | point | - | maintained(midpoint_comparison) | •Updates full year FY27 GAAP operating margin guidance to 20.1%, and maintains non-GAAP operating margin guidance of 34.3% | [ ] |
| 8 | revenue | unspecified | FY2027Q3 | 11,420,000,000 ~ 11,500,000,000 | currency/USD | range | - | unknown(no_previous_in_retrieved_history) | [Q3 FY27 Guidance] Revenue $11.42 - $11.5 billion N/A | [ ] |
| 9 | revenue_growth | unspecified | FY2027Q3 | 11 ~ 12 | percent | range | - | unknown(no_previous_in_retrieved_history) | [Q3 FY27 Guidance] Revenue growth(2) 11% - 12% 11% - 12% CC, $0M Y/Y FX | [ ] |
| 10 | revenue | unspecified | FY2027 | 46,100,000,000 ~ 46,400,000,000 | currency/USD | range | - | raised(midpoint_comparison) | [Full Year FY27 Guidance] Revenue $46.1 - $46.4 billion N/A | [ ] |
| 11 | revenue_growth | unspecified | FY2027 | 11 ~ 12 | percent | range | - | unknown(bound_type_mismatch) | [Full Year FY27 Guidance] Revenue growth(2) 11% - 12% Approximately 11% CC, $200M Y/Y FX | [ ] |
| 12 | revenue_growth | unspecified | FY2027 | 12 ~ 12 | percent | point | - | unknown(bound_type_mismatch) | [Full Year FY27 Guidance] Subscription and support revenue growth(4) Slightly above 12% Slightly under 12% CC | [ ] |
| 13 | operating_margin | gaap | FY2027 | 20.1 ~ 20.1 | percent | point | - | lowered(midpoint_comparison) | [Full Year FY27 Guidance] GAAP operating margin(1) 20.1% | [ ] |
| 14 | operating_margin | non_gaap | FY2027 | 34.3 ~ 34.3 | percent | point | - | maintained(midpoint_comparison) | [Full Year FY27 Guidance] Non-GAAP operating margin(1) 34.3% | [ ] |
| 15 | eps | gaap | (미확정) Q3 | 1.81 ~ 1.83 | per_share/USD | range | period_year_missing:Q3 | unknown(current_not_comparable:period_unresolved) | [Full Year FY27 Guidance] Q3: GAAP diluted net income per share range(1)(2) $1.81 - $1.83 | [ ] |
| 16 | eps | gaap | FY2027 | 10.21 ~ 10.25 | per_share/USD | range | - | raised(midpoint_comparison) | [Full Year FY27 Guidance] FY27: GAAP diluted net income per share range(1)(2) $10.21 - $10.25 | [ ] |
| 17 | eps | non_gaap | (미확정) Q3 | 3.42 ~ 3.44 | per_share/USD | range | period_year_missing:Q3 | unknown(current_not_comparable:period_unresolved) | [Full Year FY27 Guidance] Q3: Non-GAAP diluted net income per share(2) $3.42 - $3.44 | [ ] |
| 18 | eps | non_gaap | FY2027 | 16.67 ~ 16.71 | per_share/USD | range | - | raised(midpoint_comparison) | [Full Year FY27 Guidance] FY27: Non-GAAP diluted net income per share(2) $16.67 - $16.71 | [ ] |

추출기가 건너뛴 후보(사유):
- `multiple_candidates_same_metric_period` — cRPO growth accelerates to 14% Y/Y CC; Raises FY27 revenue guidance by $200M, $300M in CC
- `guidance_language_without_parsable_values` — The Company now expects both transactions to close independently in the coming weeks, during the third quarter of Salesforce's fiscal year 2027.
- `guidance_language_without_parsable_values` — With the U.S. dollar strengthening in Q2, Salesforce now expects a reduced currency tailwind for the business relative to prior guidance.
- `guidance_language_without_parsable_values` — •Initiates third quarter FY27 cRPO growth guidance of approximately 14% Y/Y and in CC, which does not include any contribution from the pending acquisitions of Contentful and Fin
- `guidance_language_without_parsable_values` — •Maintains full year FY27 operating cash flow growth guidance and free cash flow growth guidance of approximately 4% - 5% Y/Y

### AVGO — Broadcom Inc. (0001730168-26-000076)

- 8-K acceptance: 2026-09-02 20:26:04 UTC = 2026-09-02 16:26 ET (after_hours); 다음 실행가능 시가(주말만 제외): 2026-09-03
- 보도자료: EX-99.1 — https://www.sec.gov/Archives/edgar/data/1730168/000173016826000076/avgo-08022026x8kxex99.htm
- 원문 해시(sha256, 앞 12자): 995beb2ac2ce / 텍스트 24,307자
- 추출 상태: **guidance_found** (item 8건, skipped 11건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0001730168-25-000116[guidance_found, 8건], 0001730168-26-000011[guidance_found, 9건], 0001730168-26-000051[guidance_found, 9건]

| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | revenue | unspecified | FY2026Q4 | 34,800,000,000 ~ 34,800,000,000 | currency/USD | point | - | unknown(no_previous_in_retrieved_history) | •Fourth quarter fiscal year 2026 revenue guidance of approximately $34.8 billion, an increase of 93 percent from the prior year period | [ ] |
| 2 | revenue | unspecified | (미확정) Q3 | 16,700,000,000 ~ 16,700,000,000 | currency/USD | point | period_year_missing:Q3 | unknown(current_not_comparable:period_unresolved) | Q3 AI semiconductor revenue of $16.7 billion grew 221% year-over-year, and 54% quarter-over-quarter," said Hock Tan, President and CEO of Broadcom Inc. | [ ] |
| 3 | revenue | unspecified | (미확정) Q4 | 21,700,000,000 ~ 21,700,000,000 | currency/USD | point | period_year_missing:Q4 | unknown(current_not_comparable:period_unresolved) | "In Q4 the momentum continues, and we expect AI semiconductor revenue to accelerate to $21.7 billion, up 236% year-over-year." | [ ] |
| 4 | revenue_growth | unspecified | (미확정) Q4 | 93 ~ 93 | percent | point | period_year_missing:Q4 | unknown(current_not_comparable:period_unresolved) | "Q4 consolidated revenue growth is forecasted to increase 93% year-over-year to $34.8 billion, and we expect to maintain our non-GAAP operating margin at 66%, flat from a year ago." | [ ] |
| 5 | operating_margin | non_gaap | (미확정) Q4 | 66 ~ 66 | percent | point | period_year_missing:Q4 | unknown(current_not_comparable:period_unresolved) | "Q4 consolidated revenue growth is forecasted to increase 93% year-over-year to $34.8 billion, and we expect to maintain our non-GAAP operating margin at 66%, flat from a year ago." | [ ] |
| 6 | eps | unspecified | FY2026Q3 | 0.65 ~ 0.65 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | On June 30, 2026, the Company paid a cash dividend of $0.65 per share, totaling $3.1 billion. | [ ] |
| 7 | revenue | unspecified | (미확정) Fourth quarter | 34,800,000,000 ~ 34,800,000,000 | currency/USD | point | period_year_missing:Q4 | unknown(current_not_comparable:period_unresolved) | •Fourth quarter revenue guidance of approximately $34.8 billion; | [ ] |
| 8 | eps | unspecified | FY2026Q4 | 0.65 ~ 0.65 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | The Board of Directors of Broadcom has approved a quarterly cash dividend of $0.65 per share. | [ ] |

추출기가 건너뛴 후보(사유):
- `operating_income_unit_mismatch` — We delivered non-GAAP operating income growth of 92% year-over-year, as consolidated revenue grew 86% year-over-year to $29.6 billion," said Amie Thuener, CFO of Broadcom Inc.
- `percent_without_growth_context` — We delivered non-GAAP operating income growth of 92% year-over-year, as consolidated revenue grew 86% year-over-year to $29.6 billion," said Amie Thuener, CFO of Broadcom Inc.
- `multiple_candidates_same_metric_period` — [•Fourth quarter fiscal year 2026 Non-GAAP operating income guidance of approximately 66 percent of …] Net revenue $29,591 $15,952 +86% $29,591 $15,952 +86%
- `multiple_candidates_same_metric_period` — [•Fourth quarter fiscal year 2026 Non-GAAP operating income guidance of approximately 66 percent of …] Operating income $15,955 $5,887 +171% $20,095 $10,455 +92%
- `multiple_candidates_same_metric_period` — [•Fourth quarter fiscal year 2026 Non-GAAP operating income guidance of approximately 66 percent of …] Earnings per common share - diluted $2.68 $0.85 +215% $3.32 $1.69 +96%

### LULU — lululemon athletica inc. (0001397187-26-000126)

- 8-K acceptance: 2026-09-03 20:07:59 UTC = 2026-09-03 16:07 ET (after_hours); 다음 실행가능 시가(주말만 제외): 2026-09-04
- 보도자료: EX-99.1 — https://www.sec.gov/Archives/edgar/data/1397187/000139718726000126/lulu-20260802xex991.htm
- 원문 해시(sha256, 앞 12자): 0a617b5f6f42 / 텍스트 18,480자
- 추출 상태: **guidance_found** (item 5건, skipped 0건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0001397187-25-000054[guidance_found, 5건], 0001397187-26-000019[guidance_found, 4건], 0001397187-26-000077[guidance_found, 4건]

| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | revenue | unspecified | FY2026Q3 | 2,290,000,000 ~ 2,320,000,000 | currency/USD | range | - | unknown(no_previous_in_retrieved_history) | For the third quarter of 2026, the Company expects net revenue to be in the range of $2.290 billion to $2.320 billion, representing a decline of 10% to 11%. | [ ] |
| 2 | eps | unspecified | (미확정)  | 0.93 ~ 0.98 | per_share/USD | range | period_missing | unknown(current_not_comparable:period_unresolved) | Diluted earnings per share are expected to be in the range of $0.93 to $0.98 for the quarter. | [ ] |
| 3 | revenue | unspecified | (미확정)  | 10,350,000,000 ~ 10,500,000,000 | currency/USD | range | period_missing | unknown(current_not_comparable:period_unresolved) | For 2026, the Company now expects net revenue to be in the range of $10.350 billion to $10.500 billion, representing a decline of 5% to 7%. | [ ] |
| 4 | eps | unspecified | (미확정)  | 9.48 ~ 9.73 | per_share/USD | range | period_missing | unknown(current_not_comparable:period_unresolved) | Diluted earnings per share are now expected to be in the range of $9.48 to $9.73 for the year. | [ ] |
| 5 | eps | unspecified | FY2026Q2 | 0.86 ~ 0.86 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | The 2026 outlook includes $0.86 per share from tariff refunds and associated interest, net of tax recognized in the second quarter of 2026, but does not reflect any further potential tariff refunds. | [ ] |

### TXN — TEXAS INSTRUMENTS INC (0000097476-26-000148)

- 8-K acceptance: 2026-07-22 20:04:06 UTC = 2026-07-22 16:04 ET (after_hours); 다음 실행가능 시가(주말만 제외): 2026-07-23
- 보도자료: EX-99 — https://www.sec.gov/Archives/edgar/data/97476/000009747626000148/q22026txnex99-eredgar.htm
- 원문 해시(sha256, 앞 12자): e561f264ccd7 / 텍스트 14,667자
- 추출 상태: **guidance_found** (item 2건, skipped 1건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0000097476-25-000056[guidance_found, 2건], 0000097476-26-000003[guidance_found, 2건], 0000097476-26-000097[guidance_found, 2건]

| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | revenue | unspecified | (미확정) third quarter | 5,650,000,000 ~ 6,150,000,000 | currency/USD | range | period_year_missing:Q3 | unknown(current_not_comparable:period_unresolved) | •"TI's third quarter outlook is for revenue in the range of $5.65 billion to $6.15 billion and earnings per share between $2.23 and $2.57." | [ ] |
| 2 | eps | unspecified | (미확정) third quarter | 2.23 ~ 2.57 | per_share/USD | range | period_year_missing:Q3 | unknown(current_not_comparable:period_unresolved) | •"TI's third quarter outlook is for revenue in the range of $5.65 billion to $6.15 billion and earnings per share between $2.23 and $2.57." | [ ] |

추출기가 건너뛴 후보(사유):
- `guidance_language_without_parsable_values` — Earnings per share included a 5-cent benefit that was not in the company's original guidance.

### SNOW — Snowflake Inc. (0001640147-26-000033)

- 8-K acceptance: 2026-09-02 20:08:29 UTC = 2026-09-02 16:08 ET (after_hours); 다음 실행가능 시가(주말만 제외): 2026-09-03
- 보도자료: EX-99.1 — https://www.sec.gov/Archives/edgar/data/1640147/000164014726000033/fy2027q2earnings.htm
- 원문 해시(sha256, 앞 12자): 22e08b1d9f52 / 텍스트 50,061자
- 추출 상태: **guidance_found** (item 9건, skipped 9건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0001640147-25-000207[guidance_found, 2건], 0001628280-26-011631[guidance_found, 2건], 0001640147-26-000027[guidance_found, 8건]

| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | revenue_growth | unspecified | (미확정)  | 36 ~ 36 | percent | point | period_missing | unknown(current_not_comparable:period_unresolved) | Balancing growth with discipline remains a top priority, and we are raising our full-year product revenue growth guidance to 36% year-over-year." | [ ] |
| 2 | revenue | unspecified | FY2027Q3 | 1,588,000,000 ~ 1,593,000,000 | currency/USD | range | - | unknown(no_previous_in_retrieved_history) | •Product revenue of $1,588 million to $1,593 million, representing 37% to 38% year-over-year growth | [ ] |
| 3 | operating_margin | non_gaap | FY2027Q3 | 15.5 ~ 15.5 | percent | point | - | unknown(no_previous_in_retrieved_history) | •Non-GAAP operating margin2 of 15.5% | [ ] |
| 4 | revenue | unspecified | FY2027 | 6,070,000,000 ~ 6,070,000,000 | currency/USD | point | - | raised(midpoint_comparison) | •Product revenue of $6,070 million, representing 36% year-over-year growth, up from previous guidance of $5,840 million, or 31% year-over-year growth | [ ] |
| 5 | revenue_growth | unspecified | FY2027 | 31 ~ 31 | percent | point | - | raised(midpoint_comparison) | •Product revenue of $6,070 million, representing 36% year-over-year growth, up from previous guidance of $5,840 million, or 31% year-over-year growth | [ ] |
| 6 | gross_margin | non_gaap | FY2027 | 74 ~ 74 | percent | point | - | lowered(midpoint_comparison) | •Non-GAAP product gross margin2 of 74.0% | [ ] |
| 7 | operating_margin | non_gaap | FY2027 | 14.5 ~ 14.5 | percent | point | - | raised(midpoint_comparison) | •Non-GAAP operating margin2 of 14.5%, up from previous guidance of 13.5% | [ ] |
| 8 | revenue | unspecified | FY2027Q2 | 1,492 ~ 1,492 | currency/USD | point | scale_ambiguous | unknown(current_not_comparable:scale_ambiguous) | [Financial Outlook:] Second Quarter Fiscal 2027: Product revenue $1,491.9 | [ ] |
| 9 | operating_income | unspecified | (미확정)  | -263 ~ -263 | currency/USD | point | scale_ambiguous, period_missing | unknown(current_not_comparable:scale_ambiguous,period_unresolved) | [Financial Outlook:] Operating income (loss) ($263.0) (17.0 %) $237.0 15.3% | [ ] |

추출기가 건너뛴 후보(사유):
- `eps_unit_mismatch` — •Non-GAAP weighted-average shares used in computing net income per share attributable to common stockholders-diluted2,3 of 382 million
- `eps_unit_mismatch` — •Non-GAAP weighted-average shares used in computing net income per share attributable to common stockholders-diluted2,3 of 380 million
- `guidance_language_without_parsable_values` — 3 The potential impact of future repurchases under our stock repurchase program is not reflected in our guidance for weighted-average shares used in computing net income per share attributable to com…
- `guidance_language_without_parsable_values` — Additionally, the dilutive effect of the shares issuable upon conversion of our 0% convertible senior notes due 2027 and 0% convertible senior notes due 2029 (the Notes) using the if-converted method…
- `percent_without_growth_context` — [Financial Outlook:] Second Quarter Fiscal 2027: Product revenue 37%

### DELL — Dell Technologies Inc. (0001571996-26-000039)

- 8-K acceptance: 2026-09-01 20:10:14 UTC = 2026-09-01 16:10 ET (after_hours); 다음 실행가능 시가(주말만 제외): 2026-09-02
- 보도자료: EX-99.1 — https://www.sec.gov/Archives/edgar/data/1571996/000157199626000039/exhibit991earnings8kq2fy27.htm
- 원문 해시(sha256, 앞 12자): 9efeecdf28cd / 텍스트 30,006자
- 추출 상태: **guidance_found** (item 12건, skipped 28건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0001571996-25-000118[guidance_found, 12건], 0001571996-26-000003[guidance_found, 13건], 0001571996-26-000021[guidance_found, 15건]

| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | revenue | unspecified | FY2027 | 192,000,000,000 ~ 192,000,000,000 | currency/USD | point | - | raised(midpoint_comparison) | •Full-year FY27 revenue guidance of $192.0 billion, up 69% year over year | [ ] |
| 2 | revenue | unspecified | FY2027 | 25,000,000,000 ~ 192,000,000,000 | currency/USD | range | - | raised(midpoint_comparison) | With AI momentum accelerating and our opportunity expanding across the portfolio, we're raising our full-year FY27 revenue outlook by $25 billion to $192 billion, up nearly 70% year over year." | [ ] |
| 3 | revenue | unspecified | FY2027Q3 | 49 ~ 49 | currency/USD | point | scale_ambiguous | unknown(current_not_comparable:scale_ambiguous) | [Third-Quarter Guidance] Revenue $49.0 81% | [ ] |
| 4 | eps | gaap | FY2027Q3 | 6.1 ~ 6.1 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | [Third-Quarter Guidance] GAAP diluted EPS $6.10 168% | [ ] |
| 5 | eps | non_gaap | FY2027Q3 | 6.5 ~ 6.5 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | [Third-Quarter Guidance] Non-GAAP diluted EPS $6.50 151% | [ ] |
| 6 | eps | gaap | (미확정)  | 17.31 ~ 17.31 | per_share/USD | point | period_missing | unknown(current_not_comparable:period_unresolved) | [Full-Year Guidance] GAAP diluted EPS $17.31 $24.37 181% | [ ] |
| 7 | eps | unspecified | (미확정)  | 24.37 ~ 24.37 | per_share/USD | point | period_missing | unknown(current_not_comparable:period_unresolved) | [Full-Year Guidance] GAAP diluted EPS $17.31 $24.37 181% | [ ] |
| 8 | eps | non_gaap | (미확정)  | 17.9 ~ 17.9 | per_share/USD | point | period_missing | unknown(current_not_comparable:period_unresolved) | [Full-Year Guidance] Non-GAAP diluted EPS $17.90 $25.50 148% | [ ] |
| 9 | eps | unspecified | (미확정)  | 25.5 ~ 25.5 | per_share/USD | point | period_missing | unknown(current_not_comparable:period_unresolved) | [Full-Year Guidance] Non-GAAP diluted EPS $17.90 $25.50 148% | [ ] |
| 10 | operating_income | non_gaap | FY2027Q2 | 5,929,000,000 ~ 5,929,000,000 | currency/USD | point | - | unknown(no_previous_in_retrieved_history) | [Full-Year Guidance] Non-GAAP operating income $5,929 $2,284 160% $10,164 $3,950 157% | [ ] |
| 11 | eps | non_gaap | FY2027Q2 | 7.04 ~ 7.04 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | [Full-Year Guidance] Non-GAAP earnings per share - diluted $7.04 $2.32 203% $11.90 $3.86 208% | [ ] |
| 12 | eps | non_gaap | (미확정)  | 6.5 ~ 6.5 | per_share/USD | point | period_missing | unknown(current_not_comparable:period_unresolved) | [Reconciliation of Non-GAAP Financial Measures in Summary Guidance] Non-GAAP earnings per share - diluted $6.50 $17.90 $25.50 | [ ] |

추출기가 건너뛴 후보(사유):
- `eps_unit_mismatch` — •Full-year FY27 EPS guidance of $24.37 and non-GAAP EPS guidance of $25.50, up 181% and 148% year over year, respectively
- `multiple_candidates_same_metric_period` — •Full-year FY27 EPS guidance of $24.37 and non-GAAP EPS guidance of $25.50, up 181% and 148% year over year, respectively
- `percent_without_growth_context` — [Third-Quarter Guidance] Revenue $49.0 81%
- `eps_unit_mismatch` — [Third-Quarter Guidance] GAAP diluted EPS $6.10 168%
- `eps_unit_mismatch` — [Third-Quarter Guidance] Non-GAAP diluted EPS $6.50 151%

### BBY — BEST BUY CO INC (0000764478-26-000037)

- 8-K acceptance: 2026-08-27 11:00:56 UTC = 2026-08-27 07:00 ET (pre_market); 다음 실행가능 시가(주말만 제외): 2026-08-27
- 보도자료: EX-99 — https://www.sec.gov/Archives/edgar/data/764478/000076447826000037/bby-fy27q2xexx99.htm
- 원문 해시(sha256, 앞 12자): 35e5b5a0158f / 텍스트 26,209자
- 추출 상태: **guidance_found** (item 10건, skipped 13건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0000764478-25-000050[guidance_found, 10건], 0000764478-26-000005[guidance_found, 8건], 0000764478-26-000018[guidance_found, 13건]

| # | metric | basis | 기간 | 값(low ~ high) | 단위 | shape | flags | 자동 change(미검증) | anchor(원문 문장) | 사람 확인 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | eps | non_gaap | FY2027 | 6.7 ~ 6.9 | per_share/USD | range | - | raised(midpoint_comparison) | Raises FY27 Adjusted Diluted EPS Guidance to $6.70 to $6.90 | [ ] |
| 2 | revenue_growth | non_gaap | (미확정) second quarter | 4.1 ~ 4.1 | percent | point | period_year_missing:Q2 | unknown(current_not_comparable:period_unresolved) | "We are very pleased to report we outperformed expectations in the second quarter with comparable sales growth of 4.1% and a higher-than-expected adjusted operating income rate," said Corie Barry, Best Buy CEO. | [ ] |
| 3 | revenue | unspecified | FY2027 | 42,300,000,000 ~ 42,800,000,000 | currency/USD | range | - | raised(midpoint_comparison) | •Revenue of $42.3 billion to $42.8 billion, compared to prior guidance of $41.2 billion to $42.1 billion | [ ] |
| 4 | revenue | unspecified | FY2027Q2 | 9,070,000,000 ~ 9,070,000,000 | currency/USD | point | - | unknown(no_previous_in_retrieved_history) | Domestic revenue of $9.07 billion increased 4.3% versus last year, primarily driven by comparable sales growth of 4.5%. | [ ] |
| 5 | revenue_growth | unspecified | FY2027Q2 | 4.5 ~ 4.5 | percent | point | - | unknown(no_previous_in_retrieved_history) | Domestic revenue of $9.07 billion increased 4.3% versus last year, primarily driven by comparable sales growth of 4.5%. | [ ] |
| 6 | revenue | unspecified | FY2027Q2 | 3,000,000,000 ~ 3,000,000,000 | currency/USD | point | - | unknown(no_previous_in_retrieved_history) | Domestic online revenue of $3.00 billion increased 5.1% on a comparable basis, and as a percentage of total Domestic revenue, online revenue was 33.1% versus 32.8% last year. | [ ] |
| 7 | revenue | unspecified | FY2027Q2 | 1,680,000,000 ~ 1,680,000,000 | currency/USD | point | - | unknown(no_previous_in_retrieved_history) | Domestic adjusted SG&A was $1.78 billion, or 19.6% of revenue, versus $1.68 billion, or 19.3% of revenue, last year. | [ ] |
| 8 | revenue | unspecified | FY2027Q2 | 709,000,000 ~ 709,000,000 | currency/USD | point | - | unknown(no_previous_in_retrieved_history) | International revenue of $709 million decreased 4.2% versus last year. | [ ] |
| 9 | revenue | unspecified | FY2027Q2 | 143,000,000 ~ 143,000,000 | currency/USD | point | - | unknown(no_previous_in_retrieved_history) | International adjusted SG&A was $145 million, or 20.5% of revenue, versus $143 million, or 19.3% of revenue, last year. | [ ] |
| 10 | eps | unspecified | FY2027Q2 | 0.96 ~ 0.96 | per_share/USD | point | - | unknown(no_previous_in_retrieved_history) | Today, the company announced its board of directors has authorized the payment of a regular quarterly cash dividend of $0.96 per common share. | [ ] |

추출기가 건너뛴 후보(사유):
- `percent_without_growth_context` — Raises FY27 Comparable Sales Guidance to 1.9% to 3.0%
- `percent_without_growth_context` — •Comparable sales % change1 of 1.9% to 3.0%, compared to prior guidance of (1.0%) to 1.0%
- `operating_income_unit_mismatch` — •Adjusted operating income rate2 of 4.4% to 4.5%, compared to prior guidance of 4.3% to 4.4%
- `percent_without_growth_context` — The company expects Q3 FY27 comparable sales to be in the range of 1.0% to 3.0% and adjusted operating income rate to be in the range of 4.1% to 4.2%.
- `operating_income_unit_mismatch` — The company expects Q3 FY27 comparable sales to be in the range of 1.0% to 3.0% and adjusted operating income rate to be in the range of 4.1% to 4.2%.

### AAPL — Apple Inc. (0000320193-26-000018)

- 8-K acceptance: 2026-07-30 20:30:28 UTC = 2026-07-30 16:30 ET (after_hours); 다음 실행가능 시가(주말만 제외): 2026-07-31
- 보도자료: EX-99.1 — https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/a8-kex991q3202606272026.htm
- 원문 해시(sha256, 앞 12자): 7f1ece28e748 / 텍스트 10,889자
- 추출 상태: **no_guidance_language** (item 0건, skipped 0건)
- 이력 릴리스(변화 비교용, 같은 방식으로 추출): 0000320193-25-000077[no_guidance_language, 0건], 0000320193-26-000005[guidance_found, 1건], 0000320193-26-000011[no_guidance_language, 0건]

recall 검토용: 추출기가 가이던스로 잡지 못했지만 전망 표현과 숫자가 함께 있는 문장(최대 3개)
- (해당 문장 없음: 사람이 원문에서 가이던스 유무를 직접 확인)

## 사람 검증 절차(제안)

1. 정답 작성자는 추출기 작성자와 다른 사람으로 정하고, 이 표를 보기 전에 원문에서 가이던스 항목을 독립적으로 기록한다.
2. 항목별로 metric, 기간, low/high, 단위·통화, basis가 원문과 일치하는지 확인하고, 거래 방향을 바꿀 수 있는 오류(스케일·기간·부호)를 따로 센다.
3. 'guidance_found'가 아닌 발표는 원문에 가이던스가 실제로 없는지(진짜 unknown) 놓친 것인지 확인한다(recall).
4. 결과는 관측 비율과 Wilson 신뢰구간으로 보고하고, 표본 크기가 스펙 G0 요건에 못 미치면 통과로 표시하지 않는다.
