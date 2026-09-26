# 발행사 가이던스 변화 실험 사전 등록 스펙 (RES-04 1단계)

상태: **사전 등록 제안 (사람 승인 전)**. 이 문서의 규칙은 아직 어떤 수익 데이터로도 열어보지 않았고, 주문 경로·DB·스케줄러·화면에 연결하지 않았다. 작성일 2026-09-21.

이 문서는 [정보 수집·판단 엔진 연구](./INFORMATION_DECISION_ENGINE_RESEARCH.md)의 RES-04(기대 변화 엔진) 중 **발행사가 직접 낸 가이던스의 직전 발표 대비 변화**만 다룬다. 컨센서스는 쓰지 않는다. 결과가 어떻게 나와도 개별주 위성의 shadow 판단에 대한 결론이며, ETF 코어나 전체 포트폴리오 성과 개선으로 표현하지 않는다.

## 0. 진행 상태 (제안 / 구현 / 검증 구분)

| 항목 | 제안 | 구현 | 검증 |
|---|---|---|---|
| 본 스펙(가설·유니버스·지표·판정 규칙) | 완료(이 문서) | 해당 없음 | 사람 승인 전. 수익 데이터로 검증된 바 없음 |
| SEC EDGAR fetcher (`core/earnings_events.py`) | 완료 | 구현됨(요청 규칙·캐시·재시도) | 오프라인 단위 테스트만. 실제 SEC 접속은 8절 참고 |
| 규칙 기반 추출기·변화 분류 (`core/earnings_events.py`) | 완료 | 구현됨(LLM 호출 없음) | 오프라인 fixture 테스트만. 실제 문서 정확도는 미검증 |
| 실제 보도자료 추출 표본 (`docs/experiment_validation/earnings_guidance_extraction_sample.md`) | 완료 | 표본 문서 작성 | **사람 정답 대조 미수행.** 작성자=검증자 문제 때문에 정확도를 주장하지 않는다 |
| shadow 원장 연결(RES-01), 후보별 veto 플래그 계산 | 완료(이 문서) | 위성 shadow 연결 완료(관측 전용, `core/guidance_shadow.py`, strategy_version=`champion_satellite/guidance_shadow_v1`) | 단위 테스트만(`tests/test_guidance_shadow.py`, 합성 데이터). 실제 표본 0건, 사람 검증 대기 |
| 비교 정책 `annual_same_fy_v1`(3절 '비교 정책', 2026-09-25) | 완료(이 문서. 정의는 수익 데이터를 열기 전에 정했고 문서와 구현을 같은 변경에 넣음) | 구현됨(`compare_guidance`·`compute_guidance_changes`, 판정 근거 필드 추가) | 오프라인 fixture 테스트와 캐시된 실제 보도자료 19개 기업 재계산만(6절 '가이던스 공급 조사'). 사람 정답 대조 없음 |
| 수익 실험(H1) | 제안 | 미구현 | 미검증. 검정력·표본 조건(6절) 미확인 |
| forward shadow 수집 | 제안 | 미구현 | 미검증 |
| RES-03 KPI 계약 필드(부록 A) | 제안 | 미구현 | 미검증 |

수익·승률 개선은 이 문서 어디에서도 입증된 사실이 아니다.

## 1. 주 가설 (정확히 하나)

**H1.** 기존 위성 전략의 후보(돈치안 20일 돌파 활성 S&P 500 종목)가 결정 cutoff 직전 20거래일 안에 발행사 가이던스를 **하향 또는 철회**했고 상향한 주 지표가 없다면, 그 후보를 매수하지 않고 보류(veto)해 자금을 벤치마크(SPY)에 두는 정책은 **후보 전원을 동일 규칙으로 매수하는 기준선**보다 20거래일, 비용 후, SPY 대비 초과수익의 기대값이 크다.

- 방향은 사전에 고정한다: veto 규칙이 기대값을 **높인다**는 단측 가설. 상향 가이던스 가중, 다른 horizon, 다른 metric으로 가설을 늘리지 않는다.
- 검정 대상은 "가이던스 하향 후보의 기대 초과수익이 나머지보다 낮다"는 사실과, 그 차이가 보류 비용(선택률 하락)을 넘어 기대값을 개선하느냐이다.
- 이미 보유 중인 종목의 가이던스 하향을 청산 신호로 쓰는 문제는 별도 탐색 대상이며 이 가설에 포함하지 않는다.

## 2. 유니버스와 표본 단위

**후보 집합 C(주 표본).** 기존 위성 스캔(`core/champion_strategy.py`의 `compute_satellite_recommendation`, `_pick_satellite_at_date` 계열)이 그날 돈치안 20일 돌파를 활성으로 본 S&P 500 종목 전체다. 상위 N개 채택 여부와 무관하게 후보 전원을 같은 진입·청산 규칙으로 기록한다(RES-01 원칙). 과거 구간은 `core/point_in_time_universe.py`의 당시 구성 종목만 쓰고, 상장폐지 종목의 가격이 없으면 그 표본 수를 보고하며 결론을 보류한다.

**채택 집합 A(보조 표본).** C 중 원전략이 실제로 채택했을 상위 N개. A만의 결과는 표본이 훨씬 작아 검정력이 없을 가능성이 크다. C에서 나온 결과를 "위성 전략이 개선됐다"고 말하려면 A에서 같은 방향의 별도 확인이 필요하며, 그 전에는 "후보 집합 수준의 신호"로만 표현한다.

**독립 표본 단위(episode).** 같은 종목의 연속 후보일은 같은 가이던스 사건과 겹치는 20일 창을 공유한다. 종목별로 후보 연속 구간의 첫날만 한 표본으로 세고, 이전 표본 진입 후 20거래일 안에 다시 나온 후보일은 같은 episode로 합친다. 결과 표에는 후보일 수와 episode 수를 함께 적는다.

## 3. 사건과 feature 정의

**사건.** 발행사가 낸 Form 8-K의 Item 2.02(Results of Operations and Financial Condition)이며 첨부 EX-99.1(또는 EX-99) 보도자료 본문에서 가이던스 문장이나 표를 규칙으로 추출한 것이다. 8-K/A는 사건을 새로 만들지 않고 원본과 연결해 표시만 한다. 같은 내용을 전재한 기사·IR 페이지는 같은 사건으로 묶고 별도 근거로 세지 않는다. SEC의 accession number가 사건 ID다.

**추출 항목(item) 1건의 필드.**

| 필드 | 내용 |
|---|---|
| metric | `revenue`, `revenue_growth`, `eps`, `gross_margin`, `operating_margin`, `operating_income`, `ebitda` 중 하나. 주 가설의 규칙은 `revenue`와 `eps`만 사용하고 나머지는 기록·진단용 |
| basis | `gaap` / `non_gaap` / `unspecified` (EPS와 이익 지표는 basis가 다르면 비교하지 않는다. 매출은 `non_gaap` 명시 여부만 구분) |
| period_key | `FY2026`(연간), `FY2026Q4`, `FY2026H2`, `QEND:2026-09-30` 등 정규화 키. 연도를 알 수 없으면 `None` |
| shape | `range` / `point` / `lower_bound` / `upper_bound` / `withdrawn` |
| low, high | 정규화된 수치. 통화 금액은 기준통화 단위(백만 등 스케일 반영 후), EPS는 주당 금액, 마진·성장률은 퍼센트 값 |
| unit / currency | `currency` / `per_share` / `percent`, 통화 코드(불명이면 `None`) |
| 중간값 | 범위는 (low+high)/2, 점 추정은 그 값. bound형은 경계값(같은 bound 방향끼리만 비교) |
| anchor | 근거 원문 문장(표는 행과 제목). 필드 수치는 anchor 안에 나타나야 한다 |
| 출처 | 문서 accession, EDGAR acceptance 시각(UTC), 문서 URL, 원문 해시 |
| 진단 | flags(예: 스케일·부호·기간 모호), 발행사 문구의 상향/하향/유지 단어(stated_action), 같은 문장에 적힌 직전 범위(prior_stated) |

**변화(change) 분류.** 같은 발행사·같은 metric·같은 basis·같은 `period_key`의 **직전** 발행사 가이던스(acceptance 시각이 더 이른 것 중 가장 최근)와 비교한다. 방향을 내는 범위는 아래 '비교 정책'이 제한한다.

- `raised`/`lowered`: 중간값이 커지거나 작아짐. 하한·상한이 서로 반대로 움직이면 `mixed_direction` 플래그를 함께 남긴다.
- `maintained`: 하한·상한이 모두 같음(중간값이 같고 폭만 달라지면 유지로 두되 `width_changed`를 남긴다).
- `initiated`: 해당 (metric, period)의 직전 가이던스가 없음이 확인된 경우. 수집한 이력이 완전하다고 표시됐거나 발행사가 "initial outlook"류 문구를 쓴 경우에만. 이력 부족은 `unknown`이다.
- `withdrawn`: 발행사가 가이던스를 철회·중단한다고 밝힘.
- `unknown` + 이유 코드: 기간·단위·통화·basis·부호가 모호하거나 다름, 직전 항목이 없거나 시간 순서가 맞지 않음, 같은 문장에 후보가 여럿이라 새 값을 특정할 수 없음, 발행사 문구와 계산 방향이 충돌함 등. **애매하면 추측하지 않고 `unknown`이다.**

**비교 정책 `annual_same_fy_v1` (2026-09-25 추가. 정의는 수익 데이터를 전혀 열지 않은 상태에서 정했고, 이 절과 구현을 같은 변경에 넣었다. `annual_period_superseded_in_release` 규칙만은 추출 표본의 텍스트(CSCO 실적 행)를 보고 추가한 데이터 무결성 규칙이며 수익과는 무관하다).**

문제: 분기 가이던스는 매 발표가 새 분기(예: `FY2027Q3`)를 가리키므로 같은 `period_key`의 직전 값이 원래 없다. 실제 점검에서 NVDA 4건·MSFT 2건이 전부 `unknown(no_previous_in_retrieved_history)`였다. 반대로 같은 분기 키가 두 발표에 나오는 경우는 대부분 **다음 발표의 실적표(실제치)가 가이던스처럼 추출된 것**이었다(아래 조사: 옛 규칙이 낸 분기 방향 판정 13건이 모두 실적·배당 문장).

| 기간 종류(`period_key`) | 처리 | change / 사유 코드 |
|---|---|---|
| 연간: `FY2027`, `CY2026`, `YEND:2026-12-31` | 같은 키의 직전 발표와 중간값 비교(재확인·상향·하향). **방향 판정은 이 경우에만** | `raised`/`lowered`/`maintained`, `comparison_method=annual_same_fy` |
| 연간인데 직전 같은 FY 항목이 수집 이력에 없음 | 추측하지 않음 | `unknown`, reason `no_previous_in_retrieved_history`(기존 코드 유지), 세부 `no_prior_same_fy` |
| 같은 발표에 **바로 다음 연도**(+1) 연간 항목이 함께 있는 연간 항목 | 끝난 연도의 실적·비교열로 보고 비교하지 않음(예: 8월 발표의 FY2027 가이던스 표 안 FY2026 실적 행). +2년 이상은 장기 목표일 수 있어 근거로 쓰지 않음 | `unknown`, `annual_period_superseded_in_release` |
| 분기: `FY2027Q3`, `QEND:...` | 방향 판정 안 함. 같은 분기의 직전 값이 있어도, 발행사가 'initiate'라고 써도 마찬가지 | `unknown`, `quarterly_not_comparable` |
| 반기 `FY2026H2`, 기타(`PEND:` 등) | 방향 판정 안 함 | `unknown`, `half_year_not_comparable` / `period_type_not_comparable` |
| 철회 | 비교가 아닌 발행사 진술이므로 기간 종류와 무관 | `withdrawn`, `comparison_method=issuer_statement` |

**기각한 대안(명시).**
- 분기끼리 비교(예: Q3 가이던스 중간값 vs 직전 Q2 가이던스 중간값)로 방향을 만들지 않는다. 두 값은 다른 기간이라 차이가 계절성·성장·일회성으로 오염되고, 그것을 '상향/하향'이라 부르면 정의 자체가 달라진다.
- 분기 가이던스를 '실적 대비 가이던스'나 '컨센서스 대비 가이던스' feature로 바꾸지 않는다. 컨센서스는 PIT 확보 전 금지(9절)이고, 실적 대비 비교는 위 오염 문제와 같다.
- `FY`와 `CY`, `FY2026`과 `YEND:2026-12-31`처럼 표기 계열이 다른 키를 같은 연도로 맞추지 않는다(회계연도 말 정보를 모르면 틀린 짝을 만들 수 있다). 이 경우 `no_prior_same_fy`로 남는다.

**판정 근거 기록(하위 호환, 필드 추가만).** `GuidanceChange`에 `reason_detail`(세분화 사유: `no_prior_same_fy`, `quarterly_not_comparable`, `unit_mismatch`, `currency_mismatch`, `basis_mismatch`, `annual_period_superseded_in_release` 등), `comparison_method`(`annual_same_fy`/`issuer_statement`/`complete_history`/`not_compared`), `period_type`, `policy`를 더했고, 비교에 실제로 쓴 직전 항목의 `previous_accession`·`previous_acceptance_utc`·`previous_period_key`와 `evidence()` 요약을 남긴다. 비교에 쓰지 않은 직전 항목은 근거로 남기지 않는다(분기에서 같은 기간 값이 있었으면 `same_period_previous_available` 플래그만). 기존 `change`·`reason` 코드는 바꾸지 않았으므로 `core/guidance_shadow.py`의 feature 계산은 그대로 동작한다. 수집 캐시(`core/guidance_event_provider.py`)는 형식 2로 올려 옛 정책의 같은 날 캐시를 재사용하지 않는다.

**이 정책이 H1에 주는 제약.** veto `V`는 사실상 **연간 가이던스를 8-K 보도자료에 내는 기업의 연간 revenue·eps 재발표**에서만 켜질 수 있다. 분기 가이던스만 주는 기업(NVDA·TXN·MU 등)과 보도자료에 가이던스가 없는 기업(AAPL·MSFT·NKE·BX 등)은 항상 `unknown` 또는 `no_release`이며 coverage 보고에 그대로 드러난다.

**수치 feature(진단·이후 확장용).** 중간값 변화율 `(mid_new − mid_old)/|mid_old|`(EPS가 0에 가까우면 변화율 없이 절대 변화만), 범위 폭 `(high − low)/|mid|`와 폭 변화, 퍼센트 지표는 %p 변화. 한 발표를 하나의 긍정·부정 점수로 합치지 않고 item별로 저장한다.

**H1의 veto 플래그 `V`(결정 cutoff 시점 기준).** 후보 i에 대해 (a) 그 종목의 가장 최근 Item 2.02 발표 중 available_at ≤ 결정 cutoff이고 (b) 진입 예정 시점보다 20거래일 이내인 것에서, `revenue`·`eps` item 중 유효한 비교가 있는 것이 `lowered`/`withdrawn`을 하나 이상 포함하고 `raised`가 없으면 `V=1`이다. 나머지는 `V=0`이며, 비교 불가(`unknown`)이거나 발표·추출이 없는 후보는 `V=0`으로 두되 `V`의 근거 상태(`no_release`, `unknown`, `clear`)를 함께 기록해 coverage를 보고한다. 룩백 20거래일은 주 horizon과 같은 값으로 미리 고정하며 튜닝하지 않는다.

## 4. 시간 계약: 발표 시각, 장전/장후, 결정 cutoff, 다음 실행가능 진입

시각은 연구 문서의 공통 시간 계약을 따른다: `source_publication → system_first_seen → extraction_completed → decision_cutoff → next_executable_fill`.

- `source_publication`: 8-K의 **EDGAR acceptance 시각**(submissions API의 `acceptanceDateTime`, UTC)이다. 보도자료가 통신사로 먼저 나갔더라도 SEC가 관측한 시각은 그보다 늦거나 같으므로, 이 값은 "시스템이 알 수 있는 가장 이른 SEC 관측 시각"이다. 통신사 시각은 이 데이터에 없어서 사용하지 않는다.
- `system_first_seen`: 우리 수집기가 그 문서를 처음 받은 시각(캐시 메타의 fetched_at). 과거 자료를 소급해 받은 경우는 실제 수신 시각이 아니므로 **PIT 인증을 하지 않고** 아래 민감도 시나리오로만 쓴다.
- `extraction_completed`: 추출기 실행 완료 시각.
- `decision_cutoff = max(source_publication, system_first_seen, extraction_completed)`.
- `next_executable_fill`: 결정 cutoff에 지연 L=15분(사전 고정, 시작 예시)을 더한 시각 **이후에 처음 열리는** 정규장 시가다. 정확히 시가 시각과 같으면 그 시가는 쓰지 않는다(strict).

발표 시각별 처리(뉴욕 시각, 서머타임은 `America/New_York`으로 계산):

| acceptance 시각 | 분류 | 진입 |
|---|---|---|
| 정규장 전(09:30 이전) | 장전 | cutoff+L이 09:30 이전이면 같은 날 시가, 아니면 다음 거래일 시가 |
| 09:30~16:00 | 장중 | 다음 거래일 시가 (같은 날 종가·시가 진입 없음) |
| 16:00 이후 | 장후 | 다음 거래일 시가 |
| 주말·휴장일 | 비거래일 | 다음 거래일 시가 |

장전과 장후 발표는 같은 날짜라는 이유로 합치지 않는다. 거래일 달력은 실제 가격 데이터의 인덱스를 넘겨서 쓰고, 달력이 없으면 주말만 제외하며 휴장일을 반영하지 못한 사실을 결과에 표시한다.

**확증용 진입 규칙 vs 소급 재현.** 확증 분석은 실제 `system_first_seen`이 남은 forward shadow 자료만 PIT로 본다. 과거 EDGAR 자료로 소급 재현한 결과는 "탐색"이며, 수신 지연을 세 가지로 두고 모두 보고한다: (D0) acceptance+15분 이후 첫 시가, (D1) acceptance 다음 거래일의 다음 시가(하루 지연), (D2) 이틀 지연. 세 시나리오 모두에서 점추정 부호가 같지 않으면 채택하지 않는다(7절).

이 진입 규칙은 발표 직후 갭(첫 반응)을 수익에 포함하지 않는다. 즉 H1이 측정하는 것은 **발표 반응 이후 후속 표류**이며, 발표 반응 자체를 잡는다고 주장하지 않는다.

## 5. 주 지표, 기준선, horizon

- **주 horizon:** 진입 시가에서 20거래일 뒤의 시가(진입 시가를 0일로 셈)까지. 5·60거래일은 진단 표시일 뿐 검정에 쓰지 않는다. 결과를 본 뒤 horizon을 바꾸면 탐색 결과로만 남긴다.
- **개별 표본 수익 `x_i`:** 진입 시가→청산 시가의 후보 수익(배당 재투자 총수익 기준 조정가격, 종목과 SPY 동일 기준) − 같은 창의 SPY 수익 − 왕복 거래비용. 주 비용은 위성 편도 8bp(왕복 16bp, `SATELLITE_COST_BPS_PER_SIDE`)이고 5bp/25bp 편도는 민감도다. 슬리피지는 이 비용에 포함한 가정이며 실측이 아니다.
- **보류 시 자금 처리:** veto된 후보의 자금은 SPY(코어)에 그대로 있다고 보므로 초과수익 0, 비용 0이다. 이 가정이 기회비용을 반영한다.
- **주 지표: 증분 기대값** `ΔEV = mean_i( x_i·(1−V_i) ) − mean_i( x_i ) = −mean_i( V_i·x_i )`. 원전략(후보 전원 매수) 대비 후보 1건당 비용 후 초과수익 기대값의 변화다.
- **기준선(동일 선택률 무작위 보류):** 같은 표본에서 veto 개수(선택률 q)를 그대로 두고 후보를 무작위로 보류했을 때의 `ΔEV_random`. 월(진입 달) 단위로 층화해 뽑고 10,000회 반복한다. `E[ΔEV_random] = −q·mean(x)`이므로 후보가 평균적으로 SPY를 못 이기면 무작위 보류도 이득처럼 보인다. 이 기준선이 그 착시를 차단한다.
- **함께 보고하는 것(판정에는 위 두 값이 우선):** 승률, 선택률 q, 손익비, 회전율, 최대낙폭, 수익분포 분위수, 보류된 후보의 상승 기회비용. 승률 상승은 선택률 하락으로 설명될 수 있어 판정에 쓰지 않는다.
- **불확실성:** 후보의 기업·달 군집을 리샘플하는 cluster bootstrap(군집 = 종목×진입 분기, 민감도로 진입 달 군집을 추가하고 **두 신뢰구간 중 넓은 쪽**을 채택). 90% 양측 구간(= 단측 5%)을 쓴다. 서로 겹치는 20일 창은 episode(2절)로 합치고 label 겹침이 남는 분할에는 purge/embargo(20거래일)를 둔다.

## 6. 최소 독립 사건 수와 검정력 근거

**가정(모두 가정이며 데이터로 확인하지 않았다).**

| 가정 | 값 | 근거 상태 |
|---|---|---|
| 20거래일 SPY 대비 초과수익의 표준편차 σ | 9% | 개별주 연 변동성 약 30~35%·SPY와의 공통 요인 제거를 가정한 대략값. 위성 후보(돌파 종목)는 더 클 수 있다 |
| 검출하려는 효과 δ = 하향 후보의 기대 초과수익이 나머지보다 낮은 정도 | 2.0% (20거래일) | "의미 있는 최소 효과"로 사전에 정한 값. 문헌 재현값이 아니다 |
| 군집·겹침에 따른 design effect | 1.3 | 가정 |
| 단측 유의수준 / 검정력 | 5% / 80% | 사전 고정 |
| veto 비율 q | 약 5% | 가정. 가이던스 하향·철회가 후보 중 드물다고 봄. 실제 비율은 표본으로 확인 |

**계산.** 두 집단 평균 차이의 검정에서 veto된 집단 크기를 `n_v`라 하고 비교집단이 훨씬 크다고 보면, 필요 표본은 `n_v = ((z_0.95 + z_0.80)·σ / δ)² × deff`이다(`z_0.95 = 1.645`, `z_0.80 = 0.842`, 합 2.486).

| δ(20거래일) | 필요 독립 veto 사건 수 (deff 1.3 반영) |
|---|---|
| 1.0% | 약 650 |
| 1.5% | 약 290 |
| **2.0% (사전 고정)** | **약 165** |
| 3.0% | 약 72 |

역으로 독립 veto 사건 수별 최소 검출 효과(σ=9%, deff 1.3, 단측 5%, 검정력 80%): 50건 3.6%, 100건 2.6%, 150건 2.1%, 200건 1.8%, 300건 1.5%.

**사전 고정 최소 조건(모두 충족해야 판정 단계로 진행).**

1. 독립 veto 사건(가이던스 발표 기준 episode) **≥ 165**, 후보 episode 전체 **≥ 2,000**(q≈5% 가정에서 veto가 약 100건 이상 나오려면 필요한 규모이며, 실제 q가 다르면 veto 건수 조건이 우선한다).
2. veto 사건이 **5개 이상 서로 다른 달력연도**와 **3개 이상 GICS 섹터**에 분포하고, 한 종목이 veto의 5%를, 한 연도가 30%를 넘지 않는다(한 기간·종목·섹터 의존 차단; 이 비율은 제안값).
3. veto 상태를 결정한 발표의 추출 coverage와 unknown 비율을 보고한다. unknown이 30%를 넘으면 표본이 충분해도 `미입증`이다(제안값).

**표본 가용성 경고.** 위성 후보는 종목·날짜당 소수이고, 가이던스 하향은 드물다. 이 스펙의 forward shadow만으로 veto 165건을 모으려면 수 년 이상 걸릴 수 있으며 그 기간을 약속하지 않는다. 조건이 충족되기 전에는 결론을 내지 않고 `미입증`으로 둔다. 조건을 채우려고 정의(룩백, 가이던스 metric, 후보 집합)를 넓히는 것은 결과를 본 뒤 변경이므로 금지한다. 과거 소급 재현(2004년 이후 EDGAR 8-K 2.02는 존재)은 표본 규모 면에서는 가능하지만 3·4절의 PIT 한계와 규칙 고정 시점 제약 때문에 "탐색 → 확증 보류" 순서로만 쓴다.

**가이던스 공급 조사(2026-09-25, 비교 정책 결정용. 수익은 보지 않았다).** 대상: (A) 기존 추출 표본 12개 기업 + 이미 캐시된 MSFT·NKE = 14개 기업(기술·비달력 회계연도 쪽으로 치우친 **비무작위** 표본), (B) 2026-09-01 S&P 500 구성 종목에서 시드 20260925로 무작위 추출한 5개 기업(EXR, ZBH, BX, SNPS, KMB; 이번에 SEC 요청 45회, 초당 4회 이하, 403 없음). 기업당 최근 8-K Item 2.02 4건, 첫 건은 이력으로만 쓰고 나머지 57개 발표를 현재 추출기 + 새 정책으로 다시 계산했다(스크립트는 저장소에 남기지 않은 일회성 점검).

| 항목 | 값 |
|---|---|
| 추출 표본 문서(A의 최신 발표 12건) item 121개의 기간 종류 | 분기 45(37%), 연간 44(36%), 기간 미확정 32(26%) |
| 같은 문서의 옛 규칙 change: 분기 45개 | 방향 3개(모두 CSCO 실적표 행), unknown 42 |
| 같은 문서의 옛 규칙 change: 연간 44개 | raised 22, lowered 4, maintained 5, unknown 13 → 연간은 같은 FY 재발표 비교가 이미 대부분 가능했다 |
| 57개 발표의 revenue·eps item 287개(새 정책) | 연간 방향 56(raised 41, lowered 11, maintained 4), 분기 `quarterly_not_comparable` 107, 기간 미확정·스케일 모호 등 89, 연간 `no_prior_same_fy` 27, 연간 `annual_period_superseded_in_release` 7, 발행사 문구 충돌 1 → **unknown 80%** |
| 옛 규칙과 달라진 판정 | 16건(옛 방향 → 새 unknown). 13건은 분기 실적·배당 문장, 3건은 끝난 FY의 실적 행. 사람 확인 전이지만 anchor 문장상 모두 가이던스가 아니었다 |
| 연간 revenue·eps 같은 FY 방향 판정이 1건 이상 나온 기업 | 19개 중 7개(A: BBY, CRM, DELL, CSCO, ADBE, SNOW 6/14; **B 무작위: ZBH 1/5**). SNPS·KMB·EXR는 연간 가이던스를 내지만 표 형식·metric(FFO)·기간 표기 때문에 현재 추출기로 비교 가능한 항목이 나오지 않았다 |
| 방향 판정이 1건 이상 있는 발표 | 57개 중 13개(23%). B만 보면 15개 중 2개(13%) |
| 그중 `V=1` 형태(lowered/withdrawn 있고 raised 없음) | **0/57**. 13개 중 4개는 같은 발표 안에 raised와 lowered가 섞였다(basis·열 추출 차이일 수 있음, 미검증) |
| 같은 FY 직전 값까지의 거리 | 직전 분기 발표(약 90일 전)가 대부분. 한 FY의 첫 발표~마지막 재발표 간격 약 9~10개월 |

**수집 범위와 요청량.** 같은 FY의 직전 값은 보통 바로 앞 발표에 있으므로 `history_days=400`, `max_filings_per_ticker=6`(관측 창 45일 + 직전 발표 1~3건에 여유)으로 충분하다고 판단해 **기본값을 바꾸지 않았다.** 요청량: 티커당 최대 1(submissions) + 2 × 6(filing 인덱스 + 보도자료) = 13회, 야간 상한 20티커면 260회로 300회 안이다. 초당 4회 간격만으로 65초, 응답 지연을 요청당 1초로 크게 잡아도 약 260초로 300초 안이다(재시도가 겹치면 넘을 수 있으나 예산은 티커 사이에서 검사하는 소프트 상한이라 최대 1티커분 13회만 초과한다). 보도자료·인덱스는 영구 캐시이므로 평시 야간 요청은 submissions 20회 + 새 발표분 정도다. CIK 매핑(`company_tickers.json`)은 별도 클라이언트의 캐시를 쓴다.

**최소 사건 수 도달 가능성(정직한 평가).** 위 조사로 대략 계산하면(모두 가정): S&P 500 발표 약 2,000건/년 × 방향 판정 가능 발표 13~23% ≈ 260~460건/년. `V=1` 형태 비율은 관측 0/57이고 rule of three 95% 상한이 약 5%이므로 **universe 전체에서도 연 100건 이하**(점추정은 그보다 훨씬 작다). 여기에 '그 종목이 발표 후 20거래일 안에 위성 후보(돈치안 돌파 활성)'라는 조건이 붙는다. 하향 직후 돌파는 드물고, 후보 비율을 넉넉히 10~20%로 잡아도 **veto episode는 연 10~20건 이하가 상한**이다. 사전 고정 조건 165건을 forward shadow로 채우려면 상한 기준으로도 8~16년 이상이며, 실제로는 그보다 길 가능성이 크다. 또 새 정책에서도 revenue·eps item의 unknown이 80%로 6절 조건 3(unknown 30% 초과면 `미입증`)을 현재 추출기로는 통과하지 못한다. **결론: 현재 추출기·정책으로 최소 사건 수 도달은 비현실적이다.** 과거 소급(2004년 이후)은 규모 면에서 상한 수준에 닿을 수 있으나 PIT 한계로 탐색 전용이다. 조건을 채우려고 정의(분기 비교 허용, metric 확대, 룩백 연장)를 넓히는 것은 6절 경고대로 금지하며, 이 실험은 당분간 `미입증`으로 남는 것이 정상 결과다. 이 조사 표본(19개 기업, 57개 발표)은 작고 A는 비무작위라 위 비율의 오차가 크다.

**기간 분할(제안).** 추출 규칙 개발·튜닝: 2004-01-01~2019-12-31(텍스트 추출 품질만 볼 수 있고 수익은 열지 않는다). 잠긴 최종 구간: 2020-01-01부터 스펙 동결일 직전까지. forward shadow는 동결일 이후 별도 확증. 잠긴 구간을 본 뒤 규칙·임계값·horizon·metric을 바꾸면 그 결과는 탐색으로만 남긴다.

## 7. 채택 / 기각 / 미입증 규칙

연구 문서의 "검증과 거절 계약"을 그대로 따르며 여기서 새로 완화하지 않는다.

**단계 게이트(앞 단계 미충족 시 다음 단계 금지).**

| 게이트 | 통과 조건 |
|---|---|
| G0 추출 품질 | 사람이 작성한 정답 표본에서 scalar 핵심필드(metric·기간·low/high·단위) exact match ≥ 95%, 거래 방향을 바꿀 수치·단위·기간 오류 0건, 출처·시간 누수 0건. 정답 작성자는 추출기 작성자와 다른 사람이며 표본 구성·작성자를 사전에 고정 |
| G1 시간·출처 감사 | 모든 사용 표본에서 `source_publication ≤ decision_cutoff < next_executable_fill`이고 미래 자료 참조 0건 |
| G2 표본·검정력 | 6절의 최소 조건 충족 |
| G3 판정 | 아래 |

G0 표본 크기 근거: 표본 n건에서 오류 0건이라도 모집단 오류율의 95% 상한은 약 `1 − 0.05^(1/n)`이다(n=60이면 4.9%, n=100이면 3.0%). 따라서 사람 정답 표본은 **최소 60 item, 30건 이상의 서로 다른 발표, 8개 이상 기업**을 권장하고, 관측 exact match와 그 Wilson 신뢰구간을 함께 보고한다(예: n=100에서 관측 95%의 Wilson 95% 하한은 약 89%). 표본에서 오류가 0건이어도 모집단 무오류를 뜻하지 않는다.

**G3 판정.**

- **채택(shadow 승격 후보이며 주문 채택이 아님):** G0~G2 충족, `ΔEV`의 90% cluster bootstrap 구간 **하한 > 0**, `ΔEV`가 무작위 보류 분포의 95번째 백분위수보다 큼, 비용 25bp 시나리오와 수신 지연 D1·D2에서도 `ΔEV` 점추정이 양수, 잠긴 최종 구간에서 산출한 값이며 1개 기간·종목·섹터에 의존하지 않음. 이후에도 forward shadow의 별도 확인과 사람 승인 전에는 어떤 주문 경로에도 연결하지 않는다.
- **기각:** G0~G2를 충족한 뒤 `ΔEV` 신뢰구간 **상한 ≤ 0**이거나, 승률만 오르고 `ΔEV`·손익비·기회비용이 개선되지 않았거나, `ΔEV`가 동일 선택률 무작위 보류 기준선에 못 미침. 작은 표본이라는 이유만으로 기각하지 않는다.
- **미입증:** 그 밖의 모든 경우. 특히 신뢰구간이 0을 포함, G0·G2 미충족, 민감도 시나리오 간 부호 불일치, 잠긴 구간 재사용, 단일 기간·종목·섹터 의존.

추출 정확도, 수치 예측력, 주문 정책은 각각 따로 판정한다. 추출 정확도가 높아도 예측력이나 투자성과가 입증된 것은 아니다.

## 8. 데이터 출처 타당성 (2026-09-21 이 환경에서 확인한 사실)

이 절은 관측 기록이며 SEC의 정책 보증이 아니다. 접속 상태는 IP·User-Agent·시간에 따라 달라질 수 있다.

| 경로 | 결과 |
|---|---|
| `https://data.sec.gov/submissions/CIK##########.json` | 개인정보 없는 일반 User-Agent(`QuantResearch personal-project`)로 HTTP 200. 제출 목록에 `form`, `items`(예: `2.02,9.01`), `acceptanceDateTime`(UTC, 초 단위), `primaryDocument`, `filingDate`, `reportDate`가 있고, `filings.recent`에 최대 약 1,000건, 더 오래된 항목은 `filings.files` 페이지로 나뉨 |
| `https://www.sec.gov/Archives/edgar/data/...`(문서 본문·`-index.htm`·`index.json`), `https://www.sec.gov/files/company_tickers.json`, `cgi-bin/browse-edgar` | 같은 User-Agent로 **HTTP 403, "Your Request Originates from an Undeclared Automated Tool"**(연락처가 포함된 User-Agent를 요구). 첫 요청 하나는 "Request Rate Threshold Exceeded"였다 |

결론: 이 환경에서 개인정보 없는 일반 User-Agent만으로는 **8-K 2.02 목록과 acceptance 시각은 얻을 수 있지만 EX-99.1 본문은 얻지 못했다.** 본문을 받으려면 사용자가 실행 환경의 `SEC_USER_AGENT`에 SEC가 요구하는 식별·연락처 문자열을 직접 설정해야 한다(그 값은 코드·테스트·문서·저장소에 기록하지 않는다). 그 조건에서 접속이 되는지는 **확인하지 못했다.** 수집기는 403을 받으면 재시도하지 않고 명시적 오류로 중단한다. SEC 정책은 초당 10회 이하를 안내하며 이 프로젝트의 수집기는 초당 5회 이하, 파일 캐시, 5xx·429·네트워크 오류에만 지수 백오프 재시도를 쓴다.

유료 컨센서스·IR 벤더 API는 이 실험의 범위 밖이다. SEC 공개 자료라는 이유로 파싱·모니터링·검증 비용이 없다고 보지 않는다.

## 9. 컨센서스와 LLM 사용 규칙

**컨센서스는 PIT 확보 전까지 사용 금지.** 다음이 계약으로 확인되기 전에는 `실제치 대 컨센서스` feature, 서프라이즈, 컨센서스 대비 가이던스 gap을 만들지 않는다: 추정치별 타임스탬프와 revision history, 과거 snapshot 재현, 장기 보관·파생 데이터·재배포·LLM 입력 권리. yfinance·무료 API의 현재 컨센서스, 사후에 정제된 추정치, 가격 반응으로 역산한 "기대"는 모두 금지한다. 현재 `get_upcoming_earnings`(yfinance `Ticker.calendar`)는 발표 예정 알림용이며 사건 시각의 근거로 쓰지 않는다. 사건 시각의 근거는 EDGAR acceptance 시각뿐이다.

**LLM.** 1단계 추출은 규칙 기반이며 LLM을 호출하지 않는다. 이후 LLM을 도입하더라도 역할은 **제공된 원문에서 근거가 연결된 필드를 구조화하는 것**으로 한정한다.

- 출력의 모든 수치·기간·단위는 anchor 문장에 그대로 나타나야 하며 결정론적 검사기가 확인하고, 통과하지 못하면 `unknown`이다. 근거 없는 사실·확률·전망·confidence를 필드로 받지 않는다.
- PIT 문서만 넣어도 모델의 사전학습 지식에 이후 사건이 들어 있을 수 있으므로 **historical LLM backtest는 금지**한다. 최종 근거는 동결일 이후 수집한 forward shadow뿐이다.
- 규칙 추출과 LLM 추출이 다르면 `unknown`으로 두고 사람 검토 큐에 넣는다. LLM 비용·지연·사람 수정 횟수도 비용 원장에 남긴다(RES-02).

## 10. 구현 위치와 한계

- 구현: `core/earnings_events.py`(fetcher, 8-K 2.02 목록, 보도자료 본문 추출, 규칙 기반 추출기, 변화 분류, 시각 처리 함수). 테스트: `tests/test_earnings_events.py`(오프라인 fixture). 표본: `docs/experiment_validation/earnings_guidance_extraction_sample.md`.
- 규칙 기반 추출의 알려진 한계: 표 형식 다양성, 기간 표기 다양성(연도 없는 분기 표기는 `unknown`), 회사별 fiscal 연도 표기 차이, "낮은 두 자릿수 성장" 같은 정성 가이던스는 추출하지 않음, 원문이 HTML 표로만 있는 경우의 셀 병합 오류 가능성, 8-K 본문 외 IR 자료(컨퍼런스콜 발언)에만 있는 가이던스는 범위 밖.
- 8-K/A와 원본, 통화가 다른 발표, 회계연도 변경은 자동으로 비교하지 않고 `unknown`이다.
- 비교 정책 `annual_same_fy_v1`의 한계: (1) 발표가 FY 종료 직후 해당 FY 실적만 싣고 다음 연도 가이던스를 싣지 않으면, 그 실적 수치가 같은 FY 가이던스와 비교될 수 있다(`annual_period_superseded_in_release`는 다음 연도 항목이 같이 있을 때만 막는다). (2) 같은 발표에서 올해 가이던스와 내년 예비 전망(+1년)을 함께 내면 올해 항목이 보수적으로 `unknown`이 된다. (3) 표 형식에서 '직전 가이던스 열'과 '새 가이던스 열'이 서로 다른 basis로 추출되는 경우가 있다(ZBH 표본). 모두 사람 정답 대조(G0) 전에는 정확도를 주장하지 않는다.
- 이 문서의 수치(σ, δ, q, deff, 20거래일, 15분 지연, 비용)는 시작 예시이며 최적값이나 성과 주장이 아니다.

## 부록 A. RES-03 사전 KPI 계약을 위한 `PortfolioThesisReview` 필드안 (제안 전용)

**이번에는 구현하지 않는다.** DB 스키마 변경이 필요하며 `core/models.py`·`core/db.py`는 이번 작업의 수정 대상이 아니다. 기존 `PortfolioThesisReview`(holding_id, ticker, thesis_snapshot, review_text, purchase_price, price_at_review, price_change_pct, elapsed_days, created_at)는 자유 서술과 가격 변화만 담는다. 아래는 그 위에 얹을 제안이며 컬럼명·구조는 확정이 아니다.

**원칙.** (1) KPI 계약은 매수 판단 시점에 동결하고 이후 수정은 새 버전으로 추가한다. (2) 가격 하락 자체를 사업가설 반증으로 간주하지 않는다. 가격 결과는 별도 성과 라벨로 두고, 가설 상태는 가격 외 공시·KPI로만 갱신한다. (3) 각 근거는 원문 anchor와 시각을 가진다.

**A-1. KPI 계약(매수 시점에 동결, 항목별 1행 또는 JSON 배열).**

| 필드 | 설명 |
|---|---|
| `kpi_id`, `contract_version`, `frozen_at` | 계약 식별·버전·동결 시각. 동결 후 수정 불가, 개정은 새 `contract_version` |
| `metric`, `basis`, `unit`, `currency` | 본 스펙의 metric·basis 정의 재사용(예: revenue, eps, gross_margin, 가이던스 유지 여부) |
| `period_key` | 평가 대상 기간(본 스펙 정규화 키) |
| `baseline_value`, `baseline_anchor_text`, `baseline_source_id` | 판단 당시 기준값과 그 근거 문장, 문서 accession·URL·해시 |
| `expected_low`, `expected_high` 또는 `expected_direction` | 사업가설이 예측하는 범위나 방향 |
| `evaluation_deadline` | 평가 기한(날짜 또는 "해당 기간 실적 발표 이후 첫 Item 2.02") |
| `refutation_threshold`, `refutation_rule` | 반증 임계값과 규칙(예: 가이던스 중간값이 기준 대비 X% 이상 하향, 마진 하한 이탈, 가이던스 철회) |
| `evidence_kind` | `issuer_filing` / `financial_statement` / `price_outcome` 등. `price_outcome`은 반증 근거로 쓰지 않음 |

**A-2. 가격 외 증거 업데이트(append-only, 별도 자식 테이블 제안).**

| 필드 | 설명 |
|---|---|
| `review_id`, `kpi_id` | 어느 리뷰·KPI에 대한 증거인지 |
| `observed_value`, `observed_period_key` | 관측 수치와 대상 기간 |
| `source_publication_at`, `first_seen_at`, `extraction_completed_at` | 공통 시간 계약의 세 시각 |
| `source_url`, `source_doc_id`, `content_hash`, `revision` | 원문 링크·문서 ID·해시·수정본 |
| `anchor_text` | 근거 원문 문장(수치가 그 안에 있어야 함) |
| `verdict` | `supports` / `refutes` / `neutral` / `unknown`. 가격만으로는 `refutes`를 못 낸다 |
| `extractor_version`, `human_checked` | 규칙/LLM 버전과 사람 검토 여부 |

**A-3. 성과 라벨(가설 상태와 분리).** `price_change_pct`(기존)는 성과 라벨로 유지하고, 가설 상태(`intact` / `weakened` / `refuted` / `unknown`)는 A-2의 가격 외 증거로만 갱신한다. 평가 지표는 수익이 아니라 감사 가능성과 판단 품질(반증 조건이 사전에 있었는지, 근거가 원문에 연결되는지)이다. `generate_thesis_review`가 자유 서술 리뷰를 만드는 방식은 유지하되, KPI 계약이 있으면 그 계약의 각 항목을 기준으로 리뷰 프롬프트를 구성하는 것을 후속 검토로 남긴다.

## 부록 B. 이 문서가 다루지 않는 것

컨센서스 기반 서프라이즈, 실적 발표 가격반응 feature, SEC 공시 문구 diff(RES-05), 확률 선택기(RES-06), 공급망 graph(RES-07), 실제 주문 연결, DB 스키마 변경, 스케줄러 등록은 이번 범위가 아니다.
