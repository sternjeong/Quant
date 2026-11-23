# crash-internals-v1 — 시장 내부 상태: 산업 폭·산업 간 상관·변동성 비 (사전 등록 2026-11-23)

가설 장부 H-025(parent: crash-cycle-model-v1). 규칙 버전 `crash-internals/v1`, 판정 버전 `crash-adv-judge/v1`, 공용 정의 `research/jobs/crash-cycle-lab/SPEC.md`.
규칙·판정은 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 새로 사전 등록한다.
실행: `python research/jobs/crash-internals-v1/run.py --out DIR --checkpoint DIR [--smoke]`.

## 사용자 요청

> "예측모델을 더욱 고도화시키는 전략을 …" (2026-11-23) — 급락 예측모델 고도화 7전략 중 4.

## 이미 본 관련 결과

- crash-cycle-model-v1: 판정 14/14 FAIL. 가격·업종 특징(SPEED·RUNUP·FINREL)은 하나씩 커널 가중이라 잡음에 묻혔다.
- 막다른 길: 급락 중 매수 시점 신호, 업종 고르기, 인버스, '발생일 가격·업종 특징 하나를 띠폭·문턱만 바꿔 다시'. 이 연구는 v1 에 없던 특징 3개를 공용 두 갈래 모형으로
  함께 쓰며 띠폭·문턱 격자가 없다(BREADTH 의 −15% 는 사건 정의의 문턱을 그대로 씀).

## 자료

- 미국 시장 일별 총수익, 12 산업·49 산업 일별: `lab.load_us(smoke)`(`ind12`·`ind49`, 평일 달력, 시작 전 결측 유지·시작 뒤 결측일 0).
- 실제 실행에서 `ind49` 가 None 이면 RuntimeError("49 산업 자료를 받지 못함")(실행기 재시도). 스모크: 합성 16개 49 산업·12개 12 산업.

## 사건·층

공용 SPEC 과 같다. 판정 층 A·B·**C(2008-01~2024-09)**, 2024-10 이후 보고만.
**v1 관례와 다른 점**: v1 은 A·B 만 판정했다. 이 연구는 검정력 때문에 C 를 판정에 넣는다. C 의 사건들은 이미 crash-cycle-model-v1 보고서에서 본 것이다 — 그래서 A·B·C 각 층의 평균이 모두 양수여야 통과한다.

## 특징 (모두 발생일 t0 종가까지)

| 코드 | 식 | 근거 |
|---|---|---|
| BREADTH | `breadth(dd252_matrix(industry_tr(ind49)), t)` — 252일 이력이 있는 산업(10개 이상) 중 자기 252일 고점 대비 −15% 이하 비율, 10개 미만이면 결측 | 하락의 폭 |
| CORR12 | `corr12(ind12, t)` — 12 산업 63일 일별 단순 수익 상관행렬 비대각 평균(결측·분산 0 열이 있으면 결측) | 시스템 위험(흡수 비율, Kritzman 외 2011) |
| VOLRATIO | `volratio(logret(L), t)` — √mean(r²) 21일 / 252일 | 사건형(빠른 충격·변동성 급등) 대 경기형 약세장(Goldman 유형) |

결측 특징은 표준화 뒤 0(평균 대치). 표준화는 예측마다 그 학습 집합으로.

## 방법

4.8 절 공용 절차 그대로(연구 3 과 같은 규칙, 특징만 다름):
1. 사건 i(D = 발생일): 분류기 학습 집합 C(i) = {미국 사건 j : t0_j < D, lb_label(j, D) 있음}(라벨 1 = 252거래일 안 회복 못 함), `fit_ridge_logit(λ = 4)`.
   'fit 가능'(n ≥ 6, 두 갈래 각 1개 이상, 수렴)이 아니면 미적합 → 두 판정 모두에서 빠짐(n_unfit).
2. 모델 1·2(INTERNAL): T1 = m1_pool(us, D)·m2_pool(us, D) 의 라벨·특징으로 p_center → 두 갈래 가중치 → 재가중 분위수·베란 KM. p_center 가 None 이면 미적합.
3. p_lb = 분류기 학습 집합 기준 p_center 의 p([0.05, 0.95], 기울기가 모두 0 이면 p = π → INTERNAL = BASE).
4. 쌍 차이 d1 = 핀볼(BASE) − 핀볼(INTERNAL)(깊이 확정), d2 = 브라이어(BASE) − 브라이어(INTERNAL)(자료 안 회복). BASE = v1 발생일 기준선.

## 판정

| 키 | 비교 | 점수 | 통과 라벨 |
|---|---|---|---|
| INT_M1 | INTERNAL vs BASE | 평균 핀볼 | BEATS_BASELINE |
| INT_M2 | INTERNAL vs BASE | 브라이어(1·2·3·5년) | BEATS_BASELINE |

`lab.judge_us`: A ≥ 4·B ≥ 5·C ≥ 4·합친 ≥ 15, 무효 가드, A·B·C 평균 모두 양수 + 합친 한쪽 부호 뒤집기 p < α = 0.05/15. 그 밖 FAIL(세 평균 양수면 FAIL_UNDERPOWERED),
표본 미달·무효 → NOT_EVALUABLE. 족 15개 공통 α.

## 검정력·사전 기대

예상 n: A 5·B 9·C 7 = 21(분류기 적합 조건은 연구 3 과 같아 1946 부터). 필요 효과 0.66 sd. INT_M1·INT_M2 통과 각 약 8%(문장 전체는 run.py EXPECTED).

## 편향 방지

v1 의 가격·업종 특징(SPEED·FINREL)이 실패한 것을 보았다 — 이것은 통과 쪽 편향을 만들지 않는다. 특징 3개는 v1 에 없던 정보이고, 커널·띠폭이 아니라 공용 두 갈래 모형으로 함께 쓰며,
문턱 격자가 없다.

## 지금 읽기 (설명용 — 추천 아님)

마지막 날 특징 값 + "만약 오늘이 발생일이라면"(dd0 = −15%, 라벨 있는 모든 사건으로 학습) p_lb·INTERNAL 예측. 진행 중 사건이면 그 사건 발생일의 특징·깊이(회복은 경과일 조건부).
READING_HEADER 문구, SPY 확인 한 줄.

## 보고만

- 특징 하나씩: INTERNAL_BREADTH·INTERNAL_CORR·INTERNAL_VOLRATIO(같은 절차, 특징 1개) — 평균 d·합친 p.
- 분류 실력(연구 3 과 같은 정의), 기울기 요약, A+B 만 p, 미국 겹침 군집 p, 특징 결측 수.
- 7개 사건 표: BREADTH·CORR12·VOLRATIO·p_lb·INTERNAL vs BASE·실제.
- predictions.csv(미국 랜드마크 0): BASE, INTERNAL(p_lb), INTERNAL_BREADTH·INTERNAL_CORR·INTERNAL_VOLRATIO(보고).

## 한계

49 산업 구성은 시대에 따라 다르다(늦게 생긴 산업). 상관은 63일 창 하나. 사건 20개 남짓에 특징 3개.

## 의도적으로 뺀 것

VIX(1990~ 만, 시대 A·B 가 빔), 흡수 비율의 주성분 계산(상관 평균으로 대신 — 모수 없음), 문턱·창 격자, 업종 고르기(막다른 길).
