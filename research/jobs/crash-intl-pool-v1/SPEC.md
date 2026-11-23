# crash-intl-pool-v1 — 해외 급락 합치기: 유럽·일본·아시아태평양 사건을 학습에 더하기 (사전 등록 2026-11-23)

가설 장부 H-026(parent: crash-cycle-model-v1). 규칙 버전 `crash-intl-pool/v1`, 판정 버전 `crash-adv-judge/v1`, 공용 정의 `research/jobs/crash-cycle-lab/SPEC.md`.
규칙·판정은 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 새로 사전 등록한다.
실행: `python research/jobs/crash-intl-pool-v1/run.py --out DIR --checkpoint DIR [--smoke]`.

## 사용자 요청

> "예측모델을 더욱 고도화시키는 전략을 …" (2026-11-23) — 급락 예측모델 고도화 7전략 중 5.

## 이미 본 관련 결과

- crash-cycle-model-v1: 판정 14/14 FAIL. 한계: 사건 28개, 미국 한 시장(가장 잘된 시장의 생존 편향).
- 해외 사건은 이 저장소의 급락 질문에 한 번도 쓰이지 않았다(regime-playbook-intl-v1 은 같은 자료로 다른 질문). v1 결과를 본 영향이 없는 확인 시험.
- 막다른 길: 급락 중 매수 시점 신호, 업종 고르기, 인버스. 이 연구는 예측만 한다.

## 자료

- 미국: `lab.load_us(smoke)` → `lab.us_context`.
- 해외 3지역(판정 자료): `lab.load_intl(smoke, required=True)` — Ken French `Europe`·`Japan`·`Asia_Pacific_ex_Japan` 3팩터 일별(USD), 시장 = Mkt-RF + RF, 평일 달력,
  L = (1 + 시장).cumprod(). 한 지역이라도 못 받으면 RuntimeError(실행기 재시도, VM 에는 캐시가 있다).
- 해외 사건 목록: `lab.market_context(L_r, region)` — v1 정의 그대로(252일 고점 −15%, 첫 발생 가능일 = 자료 시작 + 252일 ≈ 1991-07).
- 스모크: `lab.synthetic_intl()`.

## 사건·층

- 판정 사건: 해외 3지역 사건, 층 **I1**(< 2008-01-01)·**I2**(2008-01-01 ~ 2024-09-30). 2024-10 이후(IX)는 보고만.
- 미국 사건(A·B·C)은 이 연구에서 판정에 쓰지 않는다(보고만, "1992 이전은 POOL = BASE"). 공용 정의의 '미국 C 포함' 결정은 이 연구의 판정과 무관하다.
  미국 사건의 결과는 crash-cycle-model-v1 보고서에서 이미 보았다.

## 방법

1. us_recs = 미국 사건, intl_recs = 세 지역 사건 전부, all_recs = us_recs + intl_recs.
2. 해외 사건 i(층 I1·I2·IX), D = 발생일:
   BASE = base_m1(m1_pool(us_recs, D), dd0_i), base_m2(m2_pool(us_recs, D), 0) — 미국만 학습(v1 계산).
   POOL = base_m1(m1_pool(all_recs, D), dd0_i), base_m2(m2_pool(all_recs, D), 0) — 사건 i 자신은 날짜 조건으로 자동 제외.
3. 쌍 차이 d1_i = 핀볼(BASE) − 핀볼(POOL)(깊이 확정·둘 다 있음), d2_i = 브라이어(BASE) − 브라이어(POOL)(자료 안 회복·둘 다 있음).
   그 발생일까지 확정된 해외 사건이 없으면 POOL = BASE 라 d = 0 으로 들어간다(설계 그대로; 보고서에 개수를 적는다).
4. 군집: 모델 1 은 d1 이 있는 I1·I2 사건으로 `lab.clusters`(날짜순, 직전 사건 발생일과 평일 63일 넘게 떨어지면 새 군집, 값 = 구성 평균, 층 = 첫 사건 날짜),
   모델 2 는 d2 로 따로.
5. 판정: POOL_M1 = judge_intl({I1: 군집 값, I2: 군집 값}), POOL_M2 같은 방식.

## 판정

| 키 | 비교 | 점수 | 통과 라벨 |
|---|---|---|---|
| POOL_M1 | POOL vs BASE(미국만 학습) | 평균 핀볼 | BEATS_BASELINE |
| POOL_M2 | POOL vs BASE(미국만 학습) | 브라이어(1·2·3·5년) | BEATS_BASELINE |

`lab.judge_intl`: 군집 I1 ≥ 3·I2 ≥ 3·합친 ≥ 10, 무효 가드, I1·I2 평균 모두 양수 + 합친 한쪽 부호 뒤집기 p < α = 0.05/15. 그 밖 FAIL(두 평균 양수면 FAIL_UNDERPOWERED),
표본 미달·무효 → NOT_EVALUABLE. 족 15개 공통 α.

## 검정력·사전 기대

- 해외 사건 예상(역사 짐작): 유럽 약 10·일본 약 12·아시아태평양 약 9 → 판정 층 약 28. 63일 간격 군집 약 14~16. 모델 2 는 자료 안 미회복(USD 기준 일본·유럽 장기 약세)
  사건이 빠져 약 11~14. 예상 n ≈ 13 → 필요 효과 0.91 sd, δ0.8 통과 약 57%. 검정력이 낮다는 것을 미리 밝힌다.
- POOL_M1 통과 약 10%, POOL_M2 약 18%(문장 전체는 run.py EXPECTED).

## 편향 방지

해외 사건은 급락 질문에 처음 쓴다. 방법에 모수가 없다(단순 합치기). 판정 층·군집 규칙·표본 조건은 결과 전에 고정했다.

## 지금 읽기 (설명용 — 추천 아님)

미국 현재 상태에서 BASE vs POOL — "만약 오늘이 발생일이라면"(dd0 = −15%) 또는 진행 중 사건(발생일 깊이로 변환, 회복은 경과일 조건부). 학습은 마지막 날까지 확정된 사건.
READING_HEADER 문구, SPY 확인 한 줄. 판정은 해외 사건이라 미국 읽기는 참고만.

## 보고만

- 한눈에 아래 '해외 판정 사건 목록'(지역·발생일·층·군집 번호·FD·회복 기간·d). 지역별 표, 군집 표(구성·평균 d), 보정표.
- 사건 단위(군집 아님) p, 미국 사건의 POOL vs BASE(1992 이전은 같은 값), POOL = BASE 인 해외 판정 사건 수.
- 7개 사건: 미국 사건의 BASE vs POOL(보고만, "판정은 해외 사건으로 한다") + 실제.
- predictions.csv: US·해외 랜드마크 0 = BASE, POOL. judged 는 해외 I1·I2 판정 사건의 쌍.

## 한계

USD 수익(환율 포함). 선진국 지수만. 지역끼리·미국과 강하게 겹친다(군집으로 일부만 처리). 1990 이전 해외 사건 없음.

## 의도적으로 뺀 것

현지 통화 해외 수익(French 지역 파일은 USD 만), 신흥국, 지역 가중(단순 합치기만), 미국 사건으로 판정(1992 이전에는 해외 사건이 없어 기준선과 같아 퇴화).
