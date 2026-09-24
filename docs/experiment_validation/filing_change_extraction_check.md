# 공시 변화 추출 소규모 점검 (RES-05)

상태: **사람 확인용 표본 점검**. 추출 정확도·예측력·성과를 주장하지 않는다. 표본이 5개 기업이라 성공률의 일반화도 불가능하다. DB·주문 경로와 무관하며 shadow 준비 단계의 코드 동작 확인이다.

## 조건

- 실행일: 2026-09-22
- 도구: `scripts/filing_change_extraction_check.py` (`core/filing_changes.py`의 `EdgarClient`, `extract_sections`, `build_filing_change_event`)
- User-Agent 출처: 환경변수 `SEC_EDGAR_USER_AGENT` (값은 기록하지 않는다). 초당 5회 이하, 정정본(10-K/A 등) 제외
- 이번 실행의 HTTP 요청 수(캐시 적중 제외): 12
- 비교: 기업마다 최근 원본 공시 2개(현재, 직전 동종). 옵션은 기본값(최소 길이 1,200자 등)

## 10-K 결과

| 기업 | 현재 / 직전 보고기간 | Item 1A 현재 | Item 1A 직전 | 유동성 현재 | 유동성 직전 | 비고 |
|---|---|---|---|---|---|---|
| AAPL | 2025-09-27 / 2024-09-28 | ok (68,020자) | ok (68,735자) | ok (3,149자) | ok (3,553자) |  |
| F | 2025-12-31 / 2024-12-31 | ok (93,569자) | ok (86,974자) | ok (2,536자) | ok (2,487자) |  |
| GME | 2026-01-31 / 2025-02-01 | ok (80,223자) | ok (55,642자) | ok (15,123자) | ok (9,079자) |  |
| JPM | - | - | - | - | - | 오류: 공시 1개뿐이라 비교 불가 |
| PTON | 2026-06-30 / 2025-06-30 | ok (181,784자) | ok (203,628자) | ok (14,166자) | ok (22,822자) |  |

**섹션 추출 상태 집계** (공시 문서 8개 기준, 문서마다 두 절을 추출)

| 절 | ok | reference_only | not_applicable | section_not_found | ok 비율 |
|---|---|---|---|---|---|
| item_1a_risk_factors | 8 | 0 | 0 | 0 | 8/8 |
| mdna_liquidity | 8 | 0 | 0 | 0 | 8/8 |

**diff 크기와 이벤트 결과** (현재 vs 직전, 절이 둘 다 ok 일 때만 비교)

| 기업 | 절 | 문장(현재/직전) | 동일 | 숫자변경 | 재서술 | 신규 | 삭제 | 이동 | 신규 태그(is_new) | 플래그 |
|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | item_1a_risk_factors | 311/317 | 152 | 0 | 66 | 93 | 97 | 0 | competition:3, customer:1, litigation:11 | - |
| AAPL | mdna_liquidity | 24/27 | 13 | 8 | 2 | 1 | 4 | 0 | 0 | - |
| F | item_1a_risk_factors | 421/385 | 249 | 0 | 64 | 108 | 72 | 0 | cybersecurity:2, litigation:10 | - |
| F | mdna_liquidity | 22/21 | 10 | 8 | 2 | 2 | 1 | 0 | 0 | - |
| GME | item_1a_risk_factors | 399/302 | 232 | 1 | 19 | 147 | 45 | 0 | cybersecurity:1, liquidity:9, litigation:3 | - |
| GME | mdna_liquidity | 95/62 | 26 | 5 | 8 | 54 | 23 | 2 | 0 | length_shock, mostly_new_text |
| PTON | item_1a_risk_factors | 875/975 | 668 | 3 | 89 | 114 | 213 | 1 | competition:2, liquidity:1, litigation:9 | - |
| PTON | mdna_liquidity | 92/124 | 43 | 6 | 13 | 30 | 51 | 0 | accounting:3 | length_shock |

**이벤트 수준** (veto 는 후보 규칙의 출력일 뿐이며 옳고 그름을 평가하지 않았다)

| 기업 | 이벤트 플래그 | veto 출력(as_of 미지정) | 문서 크기(현재/직전, MB) | 조회/처리 초 |
|---|---|---|---|---|
| AAPL | accounting_standard_change_suspected | pass (no_qualifying_change) | 1.5/1.5 | 0.4/0.9 |
| F | business_combination_suspected, accounting_standard_change_suspected | hold (new_major_litigation) | 5.3/5.5 | 0.7/2.8 |
| GME | length_shock:mdna_liquidity, mostly_new_text:mdna_liquidity, business_combination_suspected, accounting_standard_change_suspected, template_restructure_suspected | hold (new_liquidity_distress_language) | 1.9/1.6 | 0.6/1.2 |
| PTON | length_shock:mdna_liquidity, accounting_standard_change_suspected | pass (no_qualifying_change) | 2.4/2.3 | 0.7/2.0 |

**사람이 확인할 발췌** (경계·머리글이 맞는지 눈으로 확인하는 용도)

- AAPL 현재 `item_1a_risk_factors`: 머리글 `Item 1A. Risk Factors`, 끝 `next_item:1B`, 시작 "The following summarizes factors that could have a material adverse effect on the Company’s business, reputation, result...", 끝부분 "ectations, the price of the Company’s stock may decline significantly, which could have a material adverse impact on inv..."
- AAPL 현재 `mdna_liquidity`: 머리글 `Liquidity and Capital Resources`, 끝 `terminator:Recent Accounting Pronouncements`, 시작 "The Company believes its balances of cash, cash equivalents and marketable securities, which totaled $132.4 billion as o...", 끝부분 "hare beginning in May 2025. During 2025, the Company repurchased $89.3 billion of its common stock and paid dividends an..."
- AAPL 직전 `item_1a_risk_factors`: 머리글 `Item 1A. Risk Factors`, 끝 `next_item:1B`, 시작 "The Company’s business, reputation, results of operations, financial condition and stock price can be affected by a numb...", 끝부분 "ectations, the price of the Company’s stock may decline significantly, which could have a material adverse impact on inv..."
- AAPL 직전 `mdna_liquidity`: 머리글 `Liquidity and Capital Resources`, 끝 `terminator:Recent Accounting Pronouncements`, 시작 "The Company believes its balances of unrestricted cash, cash equivalents and marketable securities, which totaled $140.8...", 끝부분 "hare beginning in May 2024. During 2024, the Company repurchased $95.0 billion of its common stock and paid dividends an..."
  - 신규 태그 예 [competition/moderate/asserted/new_sentence] "These markets are characterized by aggressive price competition, downward pressure on gross margins, continual improvement in product performance, and price sensitivity on the part of consumers and bu..."
  - 신규 태그 예 [litigation_regulatory/strong/asserted/new_sentence] "Regulatory requirements, government investigations and litigation can force the Company to withdraw from, or modify its products and services for, certain countries and limit its ability to derive val..."
  - 신규 태그 예 [competition/moderate/asserted/new_sentence] "In addition, the Company faces significant competition as competitors imitate the Company’s product features and applications within their products to offer more competitive solutions."
- F 현재 `item_1a_risk_factors`: 머리글 `ITEM 1A. Risk Factors.`, 끝 `next_item:1B`, 시작 "We have listed below the material risk factors applicable to us grouped into the following categories: Operational Risks...", 끝부분 "gulatory authorities, Ford Credit has in the past modified and may in the future modify its operations or take other act..."
- F 현재 `mdna_liquidity`: 머리글 `LIQUIDITY AND CAPITAL RESOURCES`, 끝 `terminator:Item 7. Management’s Discussion and Analysis of Financial Co`, 시작 "At December 31, 2025, total cash, cash equivalents, marketable securities, and restricted cash, including Ford Credit an...", 끝부분 "roximately one year and is adjusted based on market conditions and liquidity needs. We monitor our Company cash levels a..."
- F 직전 `item_1a_risk_factors`: 머리글 `ITEM 1A. Risk Factors.`, 끝 `next_item:1B`, 시작 "We have listed below the material risk factors applicable to us grouped into the following categories: Operational Risks...", 끝부분 "ound even an allegation that Ford Credit has not complied with applicable laws or regulations could harm Ford Credit’s r..."
- F 직전 `mdna_liquidity`: 머리글 `LIQUIDITY AND CAPITAL RESOURCES`, 끝 `terminator:Item 7. Management’s Discussion and Analysis of Financial Co`, 시작 "At December 31, 2024, total balance sheet cash, cash equivalents, marketable securities, and restricted cash, including ...", 끝부분 "roximately one year and is adjusted based on market conditions and liquidity needs. We monitor our Company cash levels a..."
  - 신규 태그 예 [litigation_regulatory/strong/asserted/new_sentence] "For example, as part of a consent order we entered into with NHTSA in 2024, we have retained an independent third party selected by NHTSA to assess the Company’s adherence to the consent order and Saf..."
  - 신규 태그 예 [litigation_regulatory/moderate/asserted/new_sentence] "In order to secure critical materials to manufacture our products, we have entered into and may, in the future, enter into offtake agreements and other long-term purchase contracts with raw materials ..."
  - 신규 태그 예 [cybersecurity/moderate/asserted/new_sentence] "Additionally, any outage, security breach, misconfiguration, or loss of data within networks and systems managed by or reliant on the products and services of unaffiliated third parties could lead to ..."
- GME 현재 `item_1a_risk_factors`: 머리글 `ITEM 1A. RISK FACTORS`, 끝 `next_item:1B`, 시작 "An investment in our Company involves a high degree of risk. You should carefully consider the risks below, together wit...", 끝부분 "ed in the “Description of the Warrants-Adjustment and Amendment Provisions-Adjustments to Strike Price, Warrant Exercise..."
- GME 현재 `mdna_liquidity`: 머리글 `LIQUIDITY AND CAPITAL RESOURCES`, 끝 `terminator:CRITICAL ACCOUNTING ESTIMATES`, 시작 "Cash, cash equivalents and marketable securities January 31, 2026 February 1, 2025 Cash and cash equivalents $ 6,304.7 $...", 끝부분 "angements as of January 31, 2026 other than those disclosed in Item 8, Notes to the Consolidated Financial Statements, N..."
- GME 직전 `item_1a_risk_factors`: 머리글 `ITEM 1A. RISK FACTORS`, 끝 `next_item:1B`, 시작 "An investment in our Company involves a high degree of risk. You should carefully consider the risks below, together wit...", 끝부분 "r confidence and become subject to litigation or investigations, which could adversely affect our business, operations, ..."
- GME 직전 `mdna_liquidity`: 머리글 `LIQUIDITY AND CAPITAL RESOURCES`, 끝 `terminator:CRITICAL ACCOUNTING ESTIMATES`, 시작 "Cash, cash equivalents and marketable securities February 3, 2024 January 28, 2023 Cash and cash equivalents $ 4,756.9 $...", 끝부분 "angements as of February 1, 2025 other than those disclosed in Item 8, Notes to the Consolidated Financial Statements, N..."
  - 신규 태그 예 [cybersecurity/moderate/hypothetical/new_sentence] "If we or our third-party service providers experience a security breach or cyberattack and unauthorized parties obtain access to our Bitcoin, or other similar circumstances or events occur, we may los..."
  - 신규 태그 예 [liquidity_going_concern/moderate/hypothetical/new_category] "If the custodian of our collateral becomes subject to bankruptcy or liquidation proceedings, our ability to reclaim such collateral may be subject to competing claims from other creditors."
  - 신규 태그 예 [liquidity_going_concern/strong/hypothetical/new_category] "In addition, if our transactions are early terminated or unwound following an event of default or termination event, including one resulting from the insolvency of a counterparty, our claim for any te..."
- PTON 현재 `item_1a_risk_factors`: 머리글 `Item 1A. Risk Factors`, 끝 `next_item:1B`, 시작 "Investing in our Class A common stock involves a high degree of risk. You should carefully consider the risks and uncert...", 끝부분 "hich may make it more difficult for us to obtain additional capital and to pursue business opportunities, including pote..."
- PTON 현재 `mdna_liquidity`: 머리글 `Liquidity and Capital Resources`, 끝 `terminator:Recent Accounting Pronouncements`, 시작 "Our operations have been funded primarily through net proceeds from the sales of our equity and convertible debt securit...", 끝부분 "ervices and adequately manage our inventory.” Off-Balance Sheet Arrangements We did not have any undisclosed off-balance..."
- PTON 직전 `item_1a_risk_factors`: 머리글 `Item 1A. Risk Factors`, 끝 `next_item:1B`, 시작 "Investing in our Class A common stock involves a high degree of risk. You should carefully consider the risks and uncert...", 끝부분 "ational matters, which may make it more difficult for us to obtain additional capital and to pursue business opportuniti..."
- PTON 직전 `mdna_liquidity`: 머리글 `Liquidity and Capital Resources`, 끝 `terminator:Recent Accounting Pronouncements`, 시작 "Our operations have been funded primarily through net proceeds from the sales of our equity and convertible debt securit...", 끝부분 "ervices and adequately manage our inventory.” Off-Balance Sheet Arrangements We did not have any undisclosed off-balance..."
  - 신규 태그 예 [liquidity_going_concern/moderate/asserted/new_sentence] "Although we reported net income in fiscal year 2026, we have incurred significant operating losses in prior periods and may not be able to sustain profitability on a quarterly or annual basis."
  - 신규 태그 예 [competition/moderate/hypothetical/new_sentence] "Our revenue may also decline due to, among other reasons, decreased numbers of subscribers, reduced demand, increased competition, or contraction of our overall market."
  - 신규 태그 예 [litigation_regulatory/moderate/hypothetical/new_sentence] "Any such delays could result in adverse publicity, loss of revenue or market acceptance, and litigation, and these effects may be heightened if delays coincide with periods of seasonally high demand."

<!-- manual-notes: 이 줄 아래는 스크립트가 다시 실행돼도 보존된다 -->
